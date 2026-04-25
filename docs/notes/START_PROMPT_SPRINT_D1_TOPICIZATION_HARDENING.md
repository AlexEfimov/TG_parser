# Sprint D.1 — Topicization Hardening (post-`genotek` incident)

**Дата подготовки:** 20 апреля 2026 (по итогам инцидента `genotek` 2026-04-19/20 — см. [`docs/quality/incidents/2026-04-20_genotek_topicization_silent_failure.md`](../quality/incidents/2026-04-20_genotek_topicization_silent_failure.md)).
**Тип сессии:** Reliability + Observability hardening (~1.5–2 сессии).
**Статус:** **DONE (in-code)** — реализовано 25 апреля 2026, ожидает merge → main и деплой на VPS. См. секцию «Post-sprint» ниже.
**Связанные задачи:** `docs/quality/TRIAGED.md` § «2026-04-20 — genotek topicization silent failure», `docs/notes/FUTURE_FEATURES.md` § «Sprint D.1 — Topicization Hardening».
**Roadmap:** вставляется перед **F11** как production-блокер (silent failure в критическом стадии). После D.1 → F11 → F5-C.
**Прецеденты (читать перед стартом):** инцидент выше (timeline, stacktraces, точные line-numbers), `docs/notes/START_PROMPT_SPRINT_A7_DI19.md` (структура prompt'а, чеклисты, ruff/pytest reminders).

---

## Почему это отдельный sprint (а не часть F11)

F11 (Topic Watchlist) **опирается** на стабильную topicization — watchlist-матчинг читает `topic_cards` и их supporting items. Если каналы могут молча залипать с 0 topics, любой watchlist на них будет выдавать false-negative алерты («по теме X ничего не пришло») и это маскируется под «темы нет в канале», а не «topicization сломалась». Ship F11 поверх текущей fragile topicization = встроить в продукт багу-невидимку.

Поэтому порядок: **D.1 (hardening) → F11 (feature on top of hardened base)**.

---

## Цель сессии

Закрыть 4 high/medium латентных дефекта, всплывших в инциденте `genotek`. После этого пайплайн должен:

1. **Никогда не застревать на 0 topics молча** — если первый full-run прошёл с ошибкой, следующий scheduler-tick сам эскалирует incremental → full (§5.1 в RCA).
2. **Не терять прогресс при частичном сбое** — успешные batch'и 1..N-1 сохраняются до попытки batch'а N (§5.2).
3. **Дифференцировать типы ошибок Anthropic** — `invalid_request_error: credit balance` ≠ transient HTTP error; нет retry, есть метрика, одна ERROR-строка в логе на окно (§5.3).
4. **Не врать в `source_attempts.success`** — если любая стадия упала, `success=false` + `error_class` + `error_message` (§5.4).

Вне scope:
- MCP-инструмент `force_retopicize(...)` (§6 / §5 из RCA) — отдельный mini-sprint после D.1, если останется желание.
- Более общая reliability-работа (F8-B circuit breaker) — это дальнейший F-roadmap.
- Изменения в RAG / watchlist / prompt tuning.

---

## Pre-flight

```bash
cd /Users/alexanderefimov/TG_parser
git pull --ff-only origin main
gh run list --branch main --limit 3             # CI на main зелёный

docker compose ps                                # tg_parser_postgres healthy
docker version                                   # нужен для testcontainers

# Критичные файлы — открыть перед стартом, перечитать вдумчиво:
#   tg_parser/services/scheduler_service.py         (§5.1, §5.4)
#   tg_parser/services/topicization_service.py      (§5.1, §5.2 — caller)
#   tg_parser/processing/topicization.py            (§5.2 — batch loop)
#   tg_parser/processing/llm/anthropic_client.py    (§5.3 — where to raise)
#   tg_parser/processing/pipeline.py                (§5.3 — retry loop)

.venv/bin/pytest tests/ -q --tb=line             # baseline — должен быть зелёным до начала
```

**Critical reminder:** перед каждым `git commit` запускать `.venv/bin/ruff format <files>` и `.venv/bin/ruff check <files>` (sustained lesson из Sprints A → A.7).

---

## План (5 шагов, каждый коммитится отдельно)

### Шаг 1 — Observability-first: `source_attempts.success` перестаёт врать (§5.4)

**Почему сначала:** без этого последующие фиксы нельзя будет верифицировать на проде (у нас сейчас нет сигнала «incremental topicization failed»). Это и дешёвый шаг.

**Изменения:**
- `scheduler_service._process_source`: собрать `stage_errors: list[tuple[str, Exception]]` по мере выполнения; в финальном `record_source_attempt`:
  - `success = not stage_errors`
  - `error_class = stage_errors[0][1].__class__.__name__` если есть
  - `error_message = str(stage_errors[0][1])[:500]` (truncate — уже есть где-то в коде, проверь column width)
  - `failed_stage = stage_errors[0][0]` (новое поле? — см. существующий schema у `source_attempts`, если нет — добавить миграцией в этом же PR).
- Log: вместо несогласованных двух строк один итоговый `source=<id>: stages_ok=[...], stages_failed=[...], outcome=<success|failure>`.

**Тесты:**
- `tests/test_scheduler_service.py` (или создать): mock'нуть `run_incremental_topicization` чтобы кидала `HTTPStatusError`; assert `source_attempts.success == False`, `error_class == "HTTPStatusError"`, `error_message` не пустой.

**Миграция:** если добавляем `failed_stage`, то `alembic revision -m "di-XX_source_attempts_failed_stage" --autogenerate` (ingestion branch) + ручная проверка diff'а (см. runbook `docs/runbooks/SAFE_MIGRATION_ON_DEV.md`).

### Шаг 2 — `AnthropicBillingError` как отдельный тип (§5.3)

**Изменения:**
- `tg_parser/processing/llm/anthropic_client.py`: перед `response.raise_for_status()` (строка ~173) — если `response.status_code == 400`, попробовать `response.json()`; если `body.get("error", {}).get("type") == "invalid_request_error"` и `"credit balance"` в `body["error"]["message"].lower()` → raise `AnthropicBillingError(body["error"]["message"], request_id=response.headers.get("request-id"))`.
- Новый тип: `tg_parser/processing/llm/errors.py` (создать, если нет) с `AnthropicBillingError(Exception)`.
- `tg_parser/processing/pipeline.py` retry loop: ловить `AnthropicBillingError` отдельно — никаких retry, одна ERROR-строка, metric `tg_parser_anthropic_billing_block_total` инкремент, ре-raise (чтобы scheduler тоже увидел через §5.1).
- `scheduler_service._process_source`: если поймал `AnthropicBillingError` на любой стадии — pause source на `settings.billing_block_backoff_s` (дефолт 3600), чтобы следующий тик не молотил впустую. Поле `sources.rate_limit_until` уже есть (см. DI-9 / DI-10 контекст).

**Тесты:**
- `tests/test_anthropic_client_billing.py`: httpx_mock возвращает 400 с указанным body → assert `AnthropicBillingError` raised, не `HTTPStatusError`.
- Integration: mock Anthropic on batch 2 of 5 в `discover_new_topics` → assert 1 error log, 0 retries, metric `anthropic_billing_block_total == 1`.

### Шаг 3 — Per-batch checkpoint в `discover_new_topics` (§5.2)

**Самая сложная часть.** Выбор **А (savepoint)** из RCA §5.2.

**Изменения:**
- `tg_parser/processing/topicization.py::discover_new_topics`: вместо одного большого commit в конце — `async with session.begin_nested()` вокруг каждого batch'а. Внутри nested-транзакции insert `topic_cards` + их assignments. При успехе nested commit'ится (SAVEPOINT RELEASE), при failure — rollback только этого batch'а, ре-raise exception.
- Идемпотентность: `topic_cards` insert → `ON CONFLICT (id) DO NOTHING` (id генерируется deterministic'но из `topic_slug + channel_id` или uuid4? — проверить существующий код; если uuid4, нужно добавить deterministic id или unique constraint на `(channel_id, canonical_title)`).
- **Осторожно:** убедиться, что outer transaction (которая обрамляет `discover_new_topics`) всё ещё коммитится в конце или явно rollback'ится, чтобы SAVEPOINT'ы не висели в `prepared transactions`.

**Тесты:**
- `tests/test_topicization_batch_checkpoint.py`: 5-batch run, mock LLM так, чтобы batch 3 кинул `HTTPStatusError`. Assert:
  - `topic_cards` count == sum(topics from batches 1+2)
  - `processed_documents` без cascade-regression'а
  - Re-run (с тем же LLM mock'ом, но теперь batches 1+2 уже в БД) не дублирует topic_cards.

### Шаг 4 — Fall-through incremental → full если 0 prior cards (§5.1)

**Изменения:**
- `tg_parser/services/topicization_service.py::run_incremental_topicization`: если `existing_cards_count == 0` и `len(new_docs) > 0` → вместо `logger.warning("No topic cards...")` + return, вызвать `await self.run_full_topicization(channel_id)` и вернуть его результат. Log: INFO-строка `"channel=<id> has 0 topic cards but <N> new docs — escalating to full topicization"`.
- Альтернатива с `topicization_state` column в `sources` — **отложить** в отдельный PR (шире blast radius, требует миграции). В этом sprint'е достаточно поведенческого escalation.

**Тесты:**
- `tests/test_topicization_service.py`: scenario «источник с 100 docs, 0 topic_cards» → `run_incremental_topicization` вызывает `run_full_topicization` (через `mocker.spy` на метод) и возвращает его результат.
- Integration через scheduler (опционально): полный tick с таким источником заканчивается с `topic_cards > 0`.

### Шаг 5 — E2E regression-проверка на реплике инцидента

**Сценарий:**
1. Testcontainer PG + mock Anthropic (уже есть инфраструктура из A.6 для первого, нужно добавить pytest-httpx fixture для второго).
2. Добавить канал с 1000 processed_docs (fixture).
3. Первый scheduler tick: Anthropic mock возвращает 400 credit-balance на batch 3 из 10.
   - Ожидаем: `source_attempts.success = False`, `error_class = "AnthropicBillingError"`, `topic_cards` count == sum(batches 1+2) (> 0), metric `anthropic_billing_block_total == 1`.
4. Снять mock (Anthropic «получил кредит»).
5. Второй scheduler tick (следующий час): incremental видит `existing_cards_count > 0`, идёт incremental-путём и обрабатывает оставшиеся docs без начала с нуля. ИЛИ если batches 1+2 не коммитились — пошёл full.
   - Ожидаем: финальное `topic_cards > 0` для всех значимых тем, `source_attempts.success = True`.

Это тест — самый ценный deliverable sprint'а, он формализует «incident shall not recur».

---

## Acceptance (для code review и PR description)

Каждый пункт — boolean, галочка в PR description:

- [x] `source_attempts` содержит `failed_stage` / `error_class` / `error_message` после каждого сбоя; unit-test подтверждает (`tests/test_scheduler_service.py::test_failed_incremental_topicization_marks_attempt_failed`, миграция `20260425_add_source_attempts_failed_stage.py`)
- [x] `AnthropicBillingError` raises только на credit-balance 400; для остальных 400 поведение не меняется; unit-test на обе ветки (`tests/test_anthropic_client_billing.py`)
- [x] Metric `tg_parser_anthropic_billing_block_total` виден в `/metrics` (`tg_parser/api/metrics.py::ANTHROPIC_BILLING_BLOCK_TOTAL`, инкремент из `pipeline.py` и `scheduler_service.py`)
- [x] `rate_limit_until` устанавливается при `AnthropicBillingError`; scheduler пропускает source до его истечения (`tests/test_scheduler_service.py::test_billing_error_pauses_source_and_marks_failure`)
- [x] `discover_new_topics` сохраняет прогресс частичных batch'ов; integration-test с injected failure (`tests/test_incremental_topicization.py::test_incremental_llm_checkpoint_persists_previous_batches_on_failure`)
- [x] `run_incremental_topicization` эскалирует на full если `existing_cards == 0 and new_docs > 0`; unit-test (`tests/test_incremental_topicization.py::test_incremental_escalates_to_full_when_no_topic_cards`)
- [x] E2E-сценарий (Шаг 5) — покрыт композицией unit/integration-тестов: per-batch checkpoint persistence + scheduler billing-error path + incremental→full escalation. Полноценный testcontainer-mock-Anthropic E2E отложен на отдельный мини-PR (см. «Не сделано / следующие шаги» ниже).
- [x] `docs/quality/TRIAGED.md` — апдейт строки genotek (status → `fixed in code`, ожидает merge/deploy)
- [x] `docs/quality/incidents/2026-04-20_genotek_topicization_silent_failure.md` — `Status:` обновлён
- [x] `docs/notes/FUTURE_FEATURES.md` / `ROADMAP_V3_PRODUCTION_FIRST.md` — Sprint D.1 помечен ✅

---

## Что НЕ трогаем в этом sprint'е

- **MCP-инструмент `force_retopicize`** — отдельная сессия (мини-fea­ture, не hardening).
- **`topicization_state` column** в `sources` — требует миграцию и enum-дизайн; fall-through из §5.1 покрывает 90% случаев без него.
- **Структура `topic_cards`** — если при работе над §5.2 выяснится, что нет уникального ключа для `ON CONFLICT`, это мини-миграция в рамках Шага 3, но без ре-дизайна модели тем.
- **Prompt tuning** — никаких изменений в `prompts/topicization*.yaml`.
- **Rate-limiter refactor** — видели `rate_limit_otpm_adjusted from=200000 to=160000` как early-warning в timeline, но это работает корректно; не наш scope.

---

## Post-sprint

После мёрджа:

1. Deploy на VPS (`git pull && docker compose build && docker compose up -d`), удостовериться что metric `tg_parser_anthropic_billing_block_total` появился в Prometheus.
   - На проде один раз выполнить `alembic -c migrations/alembic_ingestion.ini upgrade head` (миграция `a1d1_topic_failed_stage` добавляет `source_attempts.failed_stage`).
2. Обновить:
   - `docs/quality/TRIAGED.md` — `status: fixed in code → fixed (commit <hash>)`
   - `docs/quality/incidents/2026-04-20_genotek_topicization_silent_failure.md` — `Status:` финальный (с commit-хешем)
   - `docs/notes/FUTURE_FEATURES.md` (Sprint D.1 — ✅, deployed)
   - `docs/notes/ROADMAP_V3_PRODUCTION_FIRST.md` (D.1 ✅ deployed, показать, что F11 снова в голове очереди)
3. Переход к **F11** (Topic Watchlist) по [`START_PROMPT_SPRINT_F11.md`](START_PROMPT_SPRINT_F11.md).

---

## Не сделано / следующие шаги (явный backlog после D.1)

- **Полноценный E2E-сценарий с testcontainer PG + mock Anthropic** (исходный Шаг 5 в первозданном виде): сейчас 1000-doc сценарий с двумя scheduler-tick'ами разложен на изолированные unit/integration тесты, которые верифицируют каждый узел контрактом. Имеет смысл добавить отдельный slow-test (`@pytest.mark.integration`) для регрессионного покрытия именно «инцидент не повторится» as-is. Разумный размер: 1 файл `tests/test_d1_genotek_regression_e2e.py`, 1 коммит.
- **MCP-инструмент `force_retopicize(channel_id)`** (явно вне scope D.1) — даст оператору ручной откат на full, когда мониторинг вылавливает «застрявший» источник раньше следующего auto-tick'а.
- **`topicization_state` column** в `sources` (`never_run | partial | healthy`) — более строгая модель состояния вместо неявного «`existing_cards_count == 0`». Потребует миграцию + дашборд-плитку. Brings discoverability, не критично, после F11.
- **Circuit breaker per source/per provider** (F8-B уровень) — обобщение `rate_limit_until`-логики.
