# START PROMPT — Tech-debt "B": ingestion-outage observability (B1) + compose env-parity guard (B2)

**Дата:** 2026-07-19 · **Тип:** implementation (code + alert rule + regression test) · **Ветка:** `main`

**Goal (одной строкой):** после ~18h тихого ingestion-outage закрыть ДВА follow-up tech-debt items из того инцидента — **B1** (сделать per-source-outcome тика первоклассной Prometheus-метрикой + alert, чтобы «все источники падают, а тик всё равно `status="success"`» больше не был невидим) и **B2** (regression-guard, чтобы scheduler-critical настройка снова не выпала из `tg_parser` compose `environment:` блока).

> Рабочий режим (нормативно, [`AGENTS.md`](../../AGENTS.md)): `git commit` / PR — **только** по явному запросу пользователя. Никаких правок `docs/methodology/**` из этого workspace. Правки `pyproject.toml` / `requirements.txt` — только с явного запроса (для этой задачи **не требуются**). Scope — **только** observability (metric + alert) и compose-parity test; поведение pipeline не меняем.

---

## 1. Контекст / мотивация (реальный инцидент этой сессии)

F9 Phase-3 добавила Telethon session-at-rest encryption, читающую `TELEGRAM_SESSION_KEY` (Fernet). Ключ был добавлен в prod `.env`, **но** сервис `tg_parser` в `docker-compose.yml` перечисляет env-переменные ЯВНЫМ allow-list-блоком (в отличие от `mcp` / `tg_bot`, которые используют `env_file: .env`), и `TELEGRAM_SESSION_KEY` туда **не попал**. Scheduler-синглтон читает OS-env на старте (документированный BUG-078 gotcha: pydantic-settings даёт приоритет OS-env над bind-mounted `/app/.env`), поэтому воркер увидел `TELEGRAM_SESSION_KEY=None` → `unseal_session_for_use` → `SessionCryptoError` на **каждом** инкрементальном тике.

**Итог:** ingestion-outage ~18h (**2026-07-16T19:52Z → 2026-07-17T13:41Z**), где каждый тик логировал `Incremental pipeline completed: succeeded=0, failed=13, degraded=0` и завершался БЕЗ исключения. Исправлено коммитом **`1fbc9b5`** — в `environment:` блок `tg_parser` добавлена строка `TELEGRAM_SESSION_KEY=${TELEGRAM_SESSION_KEY:-}` (см. `docker-compose.yml:116-122`, комментарий про BUG-078 gotcha уже на месте).

**Почему это осталось невидимым (B1, ПОДТВЕРЖДЕНО этой сессией):** единственная относящаяся к делу экспонированная метрика — `tg_parser_scheduler_tasks_total{status="success",task_name="incremental_pipeline"}` (`SCHEDULER_TASKS_TOTAL`, `tg_parser/api/metrics.py:314`). Она инкрементится обёрткой `BackgroundScheduler.add_task` (`tg_parser/services/background_scheduler.py:~89-98/~154-163`) по принципу «job-функция вернулась без raise → `status="success"`». `incremental_pipeline_task` (`scheduler_service.py:1417`) намеренно НЕ вызывает `record_scheduler_task` (комментарий `:1422-1423`), а `run_incremental_for_all_sources` ловит per-source ошибки и возвращает aggregate-dict нормально. Значит во время outage тик «успешен» → alert невозможен. **Per-source outcome (`succeeded`/`failed`/`degraded`) НЕ экспонирован как метрика** — эти числа живут только в лог-строке `Incremental pipeline completed: ...` (`scheduler_service.py:940-948`). ⇒ B1 = **instrumentation + alert**, а не «просто правило».

**Важно (`degraded` — доброкачественный):** `degraded` — это per-post `MsgIdInvalidError` при сборе комментариев / временный billing-block; это НЕ outage. Alert **не должен** тригериться на `degraded`. Целевое условие — `succeeded==0` при наличии hard-failures, устойчиво в течение N тиков.

---

## 2. Code anchors (VERIFIED 2026-07-19 — перечитать и подтвердить перед правкой)

| Якорь | Файл | Линия (2026-07-19) |
|---|---|---|
| `run_incremental_for_all_sources` (def) | [`tg_parser/services/scheduler_service.py`](../../tg_parser/services/scheduler_service.py) | 126 |
| `aggregate` dict init (ключи `sources_succeeded/failed/degraded/lock_contended/skipped/total`) | то же | 164-177 |
| Ранний выход при отсутствии активных источников (idle-тик, метрику НЕ эмитим) | то же | 195-197 |
| Per-source outcome resolution (⚠ `sources_failed` **включает** `degraded`, см. §3.1) | то же | 844-893 |
| **Completion log site** (`Incremental pipeline completed: succeeded=%d, failed=%d, degraded=%d, lock_contended=%d`) — **точка инструментации B1** | то же | 940-948 |
| `incremental_pipeline_task` (не вызывает `record_scheduler_task`) | то же | 1417-1433 |
| `SCHEDULER_TASKS_TOTAL` (`tg_parser_scheduler_tasks_total{task_name,status}`) | [`tg_parser/api/metrics.py`](../../tg_parser/api/metrics.py) | 314-318 |
| `record_scheduler_task` | то же | 894-906 |
| **`EMBEDDING_REQUESTS_TOTAL` (`tg_embedding_requests_total{outcome,stage}`) — ШАБЛОН для нового счётчика (BUG-084)** | то же | 114-132 |
| `record_embedding_outcome` (helper-шаблон) | то же | 846-860 |
| `CHANNEL_PROCESSED_COVERAGE_RATIO` (per-channel gauge; смежный, НЕ per-tick outcome) | то же | 1263-1273, `set_channel_coverage` 1303 |
| `record_scheduler_task` call-sites (обёртка add_task) | [`tg_parser/services/background_scheduler.py`](../../tg_parser/services/background_scheduler.py) | ~89-98, ~154-163 |
| Alerts file (group `tg_parser_alerts` + все прочие группы) | [`docker/prometheus/alerts.yml`](../../docker/prometheus/alerts.yml) | 1-650 |
| `EmbeddingQuotaExhausted` (`>0`/`[15m]`/`for:30m` window<for шаблон) + group `tg_parser_bug084_embedding_quota` | то же | group начинается ~589; сам alert ~609-611 (блок 589-635) |
| `NoMessagesProcessed` (смежный «idle» alert; НЕ покрывает all-fail случай) | то же | 78-88 |
| promtool unit tests (firing + negative кейсы) | [`docker/prometheus/alerts_test.yml`](../../docker/prometheus/alerts_test.yml) | 1-479 |
| **compose env-parity test (B2 живёт ЗДЕСЬ)** — `_service_env_keys` helper + DI-16 паттерн | [`tests/test_compose_env_propagation.py`](../../tests/test_compose_env_propagation.py) | 43-60, 68-85 |
| `tg_parser` compose `environment:` allow-list + `TELEGRAM_SESSION_KEY` (fix `1fbc9b5`) | [`docker-compose.yml`](../../docker-compose.yml) | 48-132 (ключ на 122) |
| `mcp` / `tg_bot` используют `env_file: .env` | то же | 165, 235 |
| `TELEGRAM_SESSION_KEY` (закомментирован) | [`.env.example`](../../.env.example) | 27 |
| `scheduler_default_interval` (default **3600s** = 1 тик/час) | [`tg_parser/config/settings.py`](../../tg_parser/config/settings.py) | 832-835 |
| scheduler-тесты (unit-тест B1 живёт ЗДЕСЬ) | [`tests/test_scheduler_service.py`](../../tests/test_scheduler_service.py) | 89-249 |

> ⚠️ Линии приблизительны для длинных файлов — **прочитать и подтвердить** перед записью в тесты/правки.

---

## 3. Scope — B1 (observability: metric + alert)

### 3.1 Новая метрика (первоклассная, mirror BUG-084 паттерна)

Объявить в [`tg_parser/api/metrics.py`](../../tg_parser/api/metrics.py) рядом с `SCHEDULER_TASKS_TOTAL` (≈314) или блоком BUG-084 (≈128), в стиле `EMBEDDING_REQUESTS_TOTAL`:

**Имя (DECIDED §7 #1):** `tg_parser_incremental_pipeline_sources_total`
**Labels:** `outcome` ∈ `{succeeded, failed, degraded, skipped, lock_contended}` — фиксированная низкая кардинальность (5). БЕЗ `channel_id`/`source_id` (aggregate-level; per-channel уже покрыт `CHANNEL_PROCESSED_COVERAGE_RATIO`). **DECIDED:** label `failed` = HARD failures only (`sources_failed - sources_degraded`); `degraded` — отдельный label; НЕ суммировать `failed`+`degraded` (degraded уже вычтен из failed — суммирование дало бы двойной учёт и ложный alert).

```python
INCREMENTAL_PIPELINE_SOURCES_TOTAL = Counter(
    "tg_parser_incremental_pipeline_sources_total",
    "Per-source outcomes of each completed incremental_pipeline tick (B1). "
    "outcome ∈ {succeeded, failed, degraded, lock_contended, skipped}. "
    "'failed' is HARD failures ONLY (excludes degraded); 'degraded' is benign "
    "(per-post MsgIdInvalidError / temporary billing block) and must NOT trip "
    "the all-sources-failing alert.",
    ["outcome"],
)
```

Helper (mirror `record_embedding_outcome`, `metrics.py:846`):

```python
def record_incremental_tick_outcomes(
    *, succeeded: int, failed: int, degraded: int, lock_contended: int, skipped: int = 0
) -> None:
    """Record ONE completed incremental_pipeline tick's aggregate per-source outcomes (B1).

    ``failed`` MUST be HARD failures only (already net of ``degraded``). Every
    outcome is emitted every tick (``.inc(0)`` when zero) so the series stays
    present and the alert's ``== 0`` term on the succeeded series is never an
    empty vector during an all-sources-failing outage.
    """
    INCREMENTAL_PIPELINE_SOURCES_TOTAL.labels(outcome="succeeded").inc(max(succeeded, 0))
    INCREMENTAL_PIPELINE_SOURCES_TOTAL.labels(outcome="failed").inc(max(failed, 0))
    INCREMENTAL_PIPELINE_SOURCES_TOTAL.labels(outcome="degraded").inc(max(degraded, 0))
    INCREMENTAL_PIPELINE_SOURCES_TOTAL.labels(outcome="lock_contended").inc(max(lock_contended, 0))
    INCREMENTAL_PIPELINE_SOURCES_TOTAL.labels(outcome="skipped").inc(max(skipped, 0))
```

> `prometheus_client` допускает `.inc(0)` — это no-op, но регистрирует серию. Эмитить ВСЕ пять outcome каждый тик обязательно (см. `== 0`-trap в §3.2).

> **Single-process registry:** репо использует дефолтный single-process `prometheus_client` registry (нет `PROMETHEUS_MULTIPROC_DIR` / `MultiProcessCollector`); scheduler-синглтон и `/metrics` живут в одном процессе, поэтому новый счётчик наследует то же рабочее поведение, что и `SCHEDULER_TASKS_TOTAL` — без per-worker split класса Gap-#2.

### 3.2 Точка инструментации (ТОЧНО)

Вызвать helper в `run_incremental_for_all_sources`, **прямо у completion-log site** (`scheduler_service.py:940-948`), после того как `aggregate` финализирован. **КРИТИЧЕСКИЙ nuance (verified 2026-07-19):** в текущем коде (`:884-893`) `aggregate["sources_failed"]` **ДВОЙНО учитывает** degraded — degraded/billing-тик делает И `sources_failed += 1`, И `sources_degraded += 1`. Поэтому «hard failures» = `aggregate["sources_failed"] - aggregate["sources_degraded"]`. Не эмитить `aggregate["sources_failed"]` как label `failed` напрямую — иначе degraded будет тригерить alert (ровно то, что запрещено).

```python
# сразу после logger.info("Incremental pipeline completed: ...") на :940-948
record_incremental_tick_outcomes(
    succeeded=aggregate["sources_succeeded"],
    failed=aggregate["sources_failed"] - aggregate["sources_degraded"],  # HARD failures only
    degraded=aggregate["sources_degraded"],
    lock_contended=aggregate["sources_lock_contended"],
    skipped=aggregate["sources_skipped"],
)
```

Idle-тик (нет активных источников) выходит раньше на `:195-197` и метрику НЕ эмитит — это **намеренно**: idle ≠ outage, и `failed` серия остаётся flat (alert не сработает). Оставить как есть.

Инкрементальный тик диспатчится обёрткой `BackgroundScheduler.add_task` (`background_scheduler.py`); `SCHEDULER_TASKS_TOTAL` не трогаем (оставляем как есть — новая метрика его дополняет, а не заменяет).

### 3.3 Alert rule

Добавить в [`docker/prometheus/alerts.yml`](../../docker/prometheus/alerts.yml) НОВУЮ группу (например `tg_parser_incremental_ingestion`) рядом с BUG-084 группой (≈589), по форме близко к `EmbeddingQuotaExhausted` — но устойчивость к одиночному блипу здесь даёт НЕ соотношение window/`for` (тут окно `[2h]` > `for:30m`, обратное BUG-084-шаблону `[15m]`<`for:30m`), а второй конъюнкт `increase(succeeded[2h])==0`. Тик = 1h (`scheduler_default_interval=3600`, `settings.py:832`), поэтому окно `[2h]` покрывает ≥2 тика.

> **Зависимость от B2 (DECIDED §7 #2):** окно `[2h]`/`for:30m` рассчитано на тик = 3600s. Сегодня `SCHEDULER_DEFAULT_INTERVAL` НЕ зеркалится в `tg_parser` compose-блок → воркер использует code-default 3600, а prod-`.env`-override интервала был бы тихо проигнорирован (latent BUG-078-класс), что подорвало бы саму окно-математику. Поэтому B2 добавляет `SCHEDULER_DEFAULT_INTERVAL` в `SCHEDULER_CRITICAL_ENV` **и** в compose (§4) — это часть данной задачи, а не отдельный follow-up.

**Спека (пороги DECIDED 2026-07-19, §7 #2 — `[2h]` + `for:30m` + `severity:critical`):**

```yaml
  - name: tg_parser_incremental_ingestion
    rules:
      # B1 — every active source failed HARD across ≥2 consecutive ticks while
      # NONE succeeded. This is the ~18h SessionCryptoError outage signature
      # (succeeded=0, failed=13). tg_parser_scheduler_tasks_total stays
      # status="success" through such an outage (the job returns without
      # raising), so THIS metric is the only signal. degraded is a SEPARATE
      # label and is intentionally NOT in the condition — a benign degraded
      # tick (per-post MsgIdInvalidError / temporary billing block) must NOT page.
      #
      # WHY the single-blip guard lives ENTIRELY in the SECOND conjunct — NOT in
      # a window<for relationship. Here window 2h > for 30m, the OPPOSITE of the
      # BUG-084 EmbeddingQuotaExhausted template ([15m] < for:30m), so the
      # for/window relationship does NOT provide benign-blip protection. That
      # protection comes solely from `increase(succeeded[2h]) == 0`: it requires
      # ZERO successful ticks in the trailing 2h, so under normal hourly
      # operation the alert can only BEGIN firing ~2h after the LAST success
      # (i.e. after ≥2 consecutive failed ticks with no success in between); the
      # for:30m then debounces on top of that (→ ~2–2.5h detection). The
      # succeeded `or vector(0)` guard keeps the `== 0` term from silently
      # disabling the alert when the succeeded series has no samples in the
      # window (analogous to TopicizationBurnNoProgress's `or vector(0)`).
      - alert: IncrementalIngestionAllSourcesFailing
        expr: >
          sum(increase(tg_parser_incremental_pipeline_sources_total{outcome="failed"}[2h])) > 0
          and
          (sum(increase(tg_parser_incremental_pipeline_sources_total{outcome="succeeded"}[2h])) or vector(0)) == 0
        for: 30m
        labels:
          severity: critical
        annotations:
          summary: "Incremental ingestion: every source failing, none succeeding"
          description: "All active sources failed HARD across the trailing 2h (≥2 ticks) with ZERO successes — an ingestion outage (e.g. the BUG-078-class TELEGRAM_SESSION_KEY / SessionCryptoError incident, prod 2026-07-16→17, fix 1fbc9b5). degraded ticks are excluded. Check tg_parser logs for 'Incremental pipeline completed: succeeded=0' + SessionCryptoError and the tg_parser compose env allow-list."
```

Детекция ~2–2.5h против фактических ~18h — на порядок лучше.

> **Cold-start / Prometheus-restart caveat:** сразу после свежего деплоя или force-recreate Prometheus (этот проект force-recreate'ит Prometheus на изменение rule-файла) ПРЕДЫДУЩЕГО `succeeded`-сэмпла нет, поэтому `increase(succeeded[2h])==0` тривиально истинно с нуля и ОДИН all-fail тик может зафайрить уже на ~30m. Это, возможно, желательно (все источники падают с самого старта — реальный outage), но оговаривает framing «≥2 тика / одиночный блип не файрит». Если нужна жёсткая гарантия ≥2 тиков — поднять `for:` чуть выше одного интервала тика (напр. `for: 1h5m` при 1h-тике).

### 3.4 promtool unit tests

Добавить кейсы в [`docker/prometheus/alerts_test.yml`](../../docker/prometheus/alerts_test.yml) (mirror структуры BUG-084-блока `:387-479`):
- **(a) FIRES:** `outcome="failed"` растёт линейно (≥1/tick), `outcome="succeeded"` flat (0) → alert firing после `for:`.
- **(b) SILENT (healthy):** и `failed`, и `succeeded` растут (или только `succeeded`) → not firing.
- **(c) SILENT (degraded-only):** растёт только `outcome="degraded"` (+ `succeeded` flat, `failed` flat) → **must NOT fire** (доказывает degraded-исключение).
- **(d) SILENT (single blip amid healthy ticks):** один плохой тик (`failed` +1), ОКРУЖЁННЫЙ здоровыми тиками — входная серия ДОЛЖНА содержать `succeeded`-инкремент В ПРЕДЕЛАХ trailing-`[2h]` окна (реалистичный benign-кейс: одна плохая итерация между нормальными). Тогда `increase(succeeded[2h])>0` ⇒ второй конъюнкт `==0` ложен → not firing. ⚠ NB: тишина здесь идёт от НЕнулевого `succeeded`-терма, а НЕ оттого, что `failed`-всплеск «стареет» из окна — при `[2h]` без `succeeded`-сэмпла `succeeded[2h]==0` осталось бы истинным и `failed[2h]>0` держался бы 2h ≫ `for:30m`, т.е. алерт ЗАФАЙРИЛ бы.

Проверка (локально; promtool не в CI/pytest — это **ручной gate**):
```bash
promtool check rules docker/prometheus/alerts.yml
promtool test rules docker/prometheus/alerts_test.yml
```
(prod Prometheus — `prom/prometheus:v2.53.0`; rule/test schema совместим с локальным promtool v3.x.)

### 3.5 Unit test инструментации (B1 python)

В [`tests/test_scheduler_service.py`](../../tests/test_scheduler_service.py) (там уже мокается `run_incremental_for_all_sources` с `AsyncMock` repos, asserts на `sources_succeeded/failed`, `:89-249`):
- тест: hard-failing source → `INCREMENTAL_PIPELINE_SOURCES_TOTAL{outcome="failed"}` вырос на 1, `degraded` НЕ вырос;
- тест: degraded/billing тик → `degraded` вырос, `failed` label НЕ вырос (доказывает вычитание `sources_failed - sources_degraded`);
- читать счётчик через `INCREMENTAL_PIPELINE_SOURCES_TOTAL.labels(outcome=...)._value.get()` или (предпочтительно) `prometheus_client` collect-снимок до/после.

---

## 4. Scope — B2 (compose env-parity regression guard)

**Проблема:** `tg_parser` перечисляет env явным allow-list (`docker-compose.yml:48-132`), тогда как `mcp`/`tg_bot` — `env_file: .env` (`:165`, `:235`). Scheduler-critical настройка (`TELEGRAM_SESSION_KEY`) тихо выпала из блока → OS-env-priority (BUG-078) → воркер прочитал default → 18h outage. Нужен guard, чтобы это **не могло** молча повториться.

**Место:** расширить [`tests/test_compose_env_propagation.py`](../../tests/test_compose_env_propagation.py) — там уже есть `_service_env_keys(compose_config, service)` helper (`:43-60`) и точный DI-16 паттерн (`:68-85`). Новый тест = минимальная дельта в том же стиле.

**Подход (MVP, DECIDED §7 #3):** явный canonical-set scheduler-critical переменных, которые ОБЯЗАНЫ присутствовать в `tg_parser` env-блоке. Единый источник истины — отложен до возможного будущего ADR. Параметризованный тест как DI-16:

> **⚠ ОБЯЗАТЕЛЬНАЯ ПРАВКА COMPOSE в рамках B2 (DECIDED §7 #2/#4):** все переменные ниже уже присутствуют в `docker-compose.yml:48-132` `tg_parser`-блоке (проверено 2026-07-19) **КРОМЕ `SCHEDULER_DEFAULT_INTERVAL`** — его сегодня там НЕТ (verified: grep находит его только в `settings.py`/`cli`/`api`/`services`, но НЕ в `docker-compose.yml`). Поэтому B2 = тест **И** добавление строки `- SCHEDULER_DEFAULT_INTERVAL=${SCHEDULER_DEFAULT_INTERVAL:-3600}` в `tg_parser` env-блок (иначе новый параметризованный тест упадёт на этом var сразу). Это одновременно закрывает latent BUG-078-класс: alert-окно `[2h]` (§3.3) предполагает тик=3600s, а без зеркалирования prod-`.env`-override интервала тихо игнорировался бы воркером.

```python
# Scheduler-critical settings the long-lived tg_parser worker reads from OS env
# at import (BUG-078: pydantic-settings prioritises OS env over bind-mounted
# /app/.env). Each MUST be mirrored into the tg_parser compose `environment:`
# allow-list or it silently falls back to the code default in the running
# scheduler singleton. Adding a new scheduler-critical knob? Add it to BOTH the
# compose block AND this set. (TELEGRAM_SESSION_KEY dropping out here caused the
# ~18h SessionCryptoError ingestion outage of 2026-07-16→17; fix 1fbc9b5; BUG-085.)
# DECIDED 2026-07-19 (§7 #4): this is the FINAL curated set. Do NOT expand to
# unrelated DB/LLM keys. All present in docker-compose.yml:48-132 EXCEPT
# SCHEDULER_DEFAULT_INTERVAL, which MUST be added to the compose block as part
# of B2 (see the ⚠ note above) or this test fails on it.
SCHEDULER_CRITICAL_ENV = {
    "TELEGRAM_SESSION_KEY",        # F9 Phase-3 session-at-rest key (the 1fbc9b5 fix; BUG-085)
    "TELEGRAM_SESSION_NAME",
    "TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_PHONE",
    "RESUMMARIZE_ENABLED", "RESUMMARIZE_TRIGGER_N",
    "TOPICIZATION_FULL_RESUME_ENABLED",   # BUG-078 original victim
    "ANTHROPIC_CALL_TIMEOUT_S", "ANTHROPIC_HTTP_TIMEOUT_S",  # BUG-079
    "ANTHROPIC_STREAMING_ENABLED",        # BUG-080
    "SCHEDULER_DEFAULT_INTERVAL",         # ⚠ NOT yet in compose — B2 must ADD it (see note above); protects the §3.3 [2h] window math
}

@pytest.mark.parametrize("var", sorted(SCHEDULER_CRITICAL_ENV))
def test_tg_parser_mirrors_scheduler_critical_env(compose_config, var):
    keys = _service_env_keys(compose_config, "tg_parser")
    assert var in keys, (
        f"{var!r} missing from tg_parser `environment:` allow-list in "
        "docker-compose.yml. The scheduler singleton reads OS env at startup "
        "(BUG-078); an unmirrored scheduler-critical setting silently falls back "
        "to its code default in the running worker — this caused the ~18h "
        "SessionCryptoError ingestion outage (fix 1fbc9b5; BUG-085). Mirror it as "
        f"`- {var}=${{{var}:-}}` in the tg_parser env block."
    )
```

**Опциональный сильный вариант (DECIDED §7 #3 — отклонён для MVP, отложен до возможного будущего ADR):** вместо ручного set — вывести invariant из единого источника (напр. сравнить с `.env.example` ключами, или с множеством `Settings` полей, которые читает scheduler-путь). Отклонено для MVP как brittle/слишком широкое (`.env.example` содержит и не-scheduler ключи; полный `Settings`-diff зашумлён). Явный curated set + комментарий «add to BOTH» — достаточный и house-style guard. Единый источник истины — предмет отдельного будущего ADR, НЕ этой задачи.

---

## 5. Acceptance criteria (Definition of Done)

**B1:**
- [ ] `INCREMENTAL_PIPELINE_SOURCES_TOTAL` (`tg_parser_incremental_pipeline_sources_total{outcome}`) объявлен в `metrics.py` + helper `record_incremental_tick_outcomes`.
- [ ] Helper вызывается у completion-log site (`scheduler_service.py:940-948`); label `failed` = `sources_failed - sources_degraded` (hard-only); все 5 outcome эмитятся каждый (не-idle) тик.
- [ ] Метрика видна на `/metrics` (серии зарегистрированы; значения могут быть 0).
- [ ] Alert `IncrementalIngestionAllSourcesFailing` в `alerts.yml`, gated на `succeeded==0 AND failed>0`, degraded исключён; single-blip guard даёт конъюнкт `increase(succeeded[2h])==0` (НЕ соотношение window/`for`).
- [ ] promtool: `check rules` OK + `test rules` SUCCESS (кейсы a–d, включая degraded-only silent).
- [ ] Unit-тест инструментации в `tests/test_scheduler_service.py` (hard-fail vs degraded) зелёный. **ОБЯЗАТЕЛЬНО** проверять через before/after delta-снимок счётчика (снять значение до вызова, вычесть после) — module-level global Counter аккумулируется через тесты в одной сессии, поэтому сырые `== 1` asserts были бы flaky.

**B2:**
- [ ] В `tg_parser` compose `environment:` добавлена строка `- SCHEDULER_DEFAULT_INTERVAL=${SCHEDULER_DEFAULT_INTERVAL:-3600}` (DECIDED §7 #2/#4 — сегодня var отсутствует; без этой правки новый тест падает).
- [ ] Новый параметризованный тест в `tests/test_compose_env_propagation.py` c финальным `SCHEDULER_CRITICAL_ENV` (§4, §7 #4); проходит на `docker-compose.yml` после правки выше (остальные vars уже в блоке — `TELEGRAM_SESSION_KEY` c `1fbc9b5`); падал бы, если убрать любую scheduler-critical переменную.
- [ ] Комментарий фиксирует BUG-078 gotcha + правило «add to BOTH compose block and this set» + ссылку на BUG-085.

**Общее:**
- [ ] Поведение pipeline байт-в-байт не изменено (только добавлена metric-эмиссия). `SCHEDULER_TASKS_TOTAL` не тронут.
- [ ] ЗК/quality gate (§6) зелёный.

---

## 6. ЗК / Quality gate (перед объявлением готовности)

```bash
# lint + format (нормативно)
uv run ruff check .
uv run ruff format --check .

# default suite (integration-фильтр; PG-тесты пропускаются)
uv run pytest -q

# PR standard — обязателен, т.к. трогаем app-code (scheduler) + compose/metrics
TEST_POSTGRES=1 uv run pytest -q
# ожидание ~3222 passed (tests/README.md); новые B1/B2 тесты добавляются к сумме

# alert rules (ручной gate — promtool НЕ в CI)
promtool check rules docker/prometheus/alerts.yml
promtool test rules docker/prometheus/alerts_test.yml
```

Плюс: self-review диффа + прогон **Bugbot** по локальным изменениям перед тем как просить пользователя о коммите.

---

## 7. Out of scope / decisions (DECIDED 2026-07-19)

**Out of scope:**
- Изменение поведения scheduler / retry / pause-логики; правка `SCHEDULER_TASKS_TOTAL`.
- Per-channel/per-source label на новой метрике (кардинальность; per-channel покрыт `CHANNEL_PROCESSED_COVERAGE_RATIO`).
- Grafana dashboard-панель (можно follow-up; alert самодостаточен).
- Деплой Prometheus на prod (force-recreate) — отдельный `PRODUCTION_DEPLOYMENT.md` шаг, не часть этой задачи.
- Правки `docs/methodology/**`, `pyproject.toml`, `requirements.txt`.
- Заведение BUG-записи для самого инцидента — **СДЕЛАНО**: инцидент залогирован как **BUG-085** (`resolved`, fix `1fbc9b5`) в [`BUG_LOG.md`](BUG_LOG.md). Запись явно указывает, что PREVENTION этой задачи (B1 alert + B2 guard) ещё НЕ реализована и ссылается на этот START_PROMPT.

**Decisions (DECIDED 2026-07-19, утверждено владельцем) — все зависимые секции приведены в соответствие (§3.1 metric, §3.3 alert, §4 B2 set/code):**
1. **Имя метрики / labels — DECIDED.** Counter `tg_parser_incremental_pipeline_sources_total{outcome}`, `outcome ∈ {succeeded, failed, degraded, skipped, lock_contended}`. Label `failed` = **HARD failures only** (`aggregate["sources_failed"] - aggregate["sources_degraded"]`); `degraded` — отдельный label. **Явно:** НЕ суммировать `failed`+`degraded` — degraded уже ВЫЧТЕН из failed, суммирование дало бы двойной учёт и ложный alert. См. §3.1 / §3.2.
2. **Alert window / for / severity — DECIDED.** Оставляем `[2h]` + `for:30m` + `severity:critical` (окно-математика предполагает тик = `scheduler_default_interval=3600s`, т.е. `[2h]` покрывает ≥2 тика). **ДОПОЛНИТЕЛЬНО:** `SCHEDULER_DEFAULT_INTERVAL` добавляется в B2-set `SCHEDULER_CRITICAL_ENV`, потому что сегодня этот var **НЕ зеркалится** в `tg_parser` compose-блок (latent BUG-078-класс: воркер берёт code-default 3600, и если prod-`.env` переопределит интервал, окно `[2h]` тихо перестанет покрывать ≥2 тика, подорвав саму alert-математику). Guard B2 это закрывает. Отражено в §3.3 (alert) и §4 (B2 set + обязательная правка compose).
3. **B2 подход — DECIDED.** Явный curated `SCHEDULER_CRITICAL_ENV` set (MVP). Вывод инварианта из единого источника истины — **отложен до возможного будущего ADR** (не в этой задаче). См. §4.
4. **Полный список `SCHEDULER_CRITICAL_ENV` — DECIDED (финальный).** Полное документированное семейство: `TELEGRAM_SESSION_KEY`, `TELEGRAM_SESSION_NAME`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_PHONE`, `RESUMMARIZE_ENABLED`, `RESUMMARIZE_TRIGGER_N`, `TOPICIZATION_FULL_RESUME_ENABLED`, `ANTHROPIC_CALL_TIMEOUT_S`, `ANTHROPIC_HTTP_TIMEOUT_S`, `ANTHROPIC_STREAMING_ENABLED` **PLUS** `SCHEDULER_DEFAULT_INTERVAL`. НЕ расширять на несвязанные DB/LLM-ключи. **Проверено 2026-07-19:** все перечисленные vars уже присутствуют в `docker-compose.yml:48-132` `tg_parser`-блоке **КРОМЕ** `SCHEDULER_DEFAULT_INTERVAL` → его надо ДОБАВИТЬ в compose как `- SCHEDULER_DEFAULT_INTERVAL=${SCHEDULER_DEFAULT_INTERVAL:-3600}` в рамках B2 (иначе новый guard-тест упадёт сразу). См. §4.

---

## 8. Ссылки

- **Инцидент / fix:** commit `1fbc9b5` (`TELEGRAM_SESSION_KEY=${TELEGRAM_SESSION_KEY:-}` в `tg_parser` env-блок); outage 2026-07-16T19:52Z→2026-07-17T13:41Z. Recovery/verification задокументирован в [`PHASE1_WATCH_BASELINE_2026-07-15.md`](PHASE1_WATCH_BASELINE_2026-07-15.md) **Gap #6** (t2 re-snapshot; merge `1a2a9aa`).
- **BUG_LOG** ([`docs/notes/BUG_LOG.md`](BUG_LOG.md)):
  - **BUG-085** — САМ инцидент этой задачи (F9 Phase-3 `TELEGRAM_SESSION_KEY` выпал из `tg_parser` compose-allow-list → `SessionCryptoError` каждый тик → ~18h silent outage; `resolved`, fix `1fbc9b5`). Запись явно указывает, что PREVENTION (B1 alert + B2 guard) — эта задача, ещё не реализована. **Заведён этой сессией** (2026-07-19; вставлен как верхняя запись § Active bugs).
  - **BUG-078** (`:313-333`) — OS-env-priority над bind-mounted `.env` для explicit-allow-list `tg_parser`; ровно тот класс, что уронил `TELEGRAM_SESSION_KEY` (fix того инцидента — `78c3b93` для `TOPICIZATION_FULL_*`). Тот же класс, что BUG-085.
  - **BUG-067** (`:556+`) — прецедент silent-outage: тик, обработавший 0/N доков, всё равно `outcome=success`, `fail_count=0` (та же «зелёный монитор при outage» патология; мотивирует per-outcome метрику).
  - **BUG-084** (`:141`, alerts `:589-635`, metric `metrics.py:128`) — **шаблон**: `tg_embedding_requests_total{outcome,stage}` + `record_embedding_outcome` + `>0`/`[15m]`/`for:30m` alert + promtool кейсы. Копировать паттерн.
  - **BUG-079 / BUG-080** — прочие члены env-mirror family (для B2-set).
- **ADR:** [`0006`](../adr/0006-karpathy-like-living-kb-principles.md) (#6 observability — «сделай отказ наблюдаемым»; #7 graceful — почему degraded ≠ failure).
- **Convention:** [`AGENTS.md`](../../AGENTS.md) (commit только по запросу; no methodology/pyproject/requirements), [`docs/quality/AGENT_PLAYBOOK.md`](../quality/AGENT_PLAYBOOK.md), [`tests/README.md`](../../tests/README.md) (режимы pytest).
- **Похожий по форме START_PROMPT** (metric+alert+promtool, ЗК): [`START_PROMPT_FIX_F11_SEMANTIC_AVAILABLE_GUARD_T6_2026-06-15.md`](START_PROMPT_FIX_F11_SEMANTIC_AVAILABLE_GUARD_T6_2026-06-15.md).
- **Runbook (session-key контекст):** [`docs/runbooks/CURSOR_CLOUD_PROD_SSH.md`](../runbooks/CURSOR_CLOUD_PROD_SSH.md); `tg_parser/ingestion/telegram/session_crypto.py` (источник `SessionCryptoError`).
