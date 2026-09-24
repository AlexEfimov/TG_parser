# START PROMPT — R13: наблюдаемость LLM-расхода по стадиям + ротация логов (BUG-108 a)

**Дата:** 2026-09-23 · **Сессия:** R13 по [`PLAN_REMEDIATION_BOT_MCP_2026-08-12.md`](../PLAN_REMEDIATION_BOT_MCP_2026-08-12.md) §4a · **Баг:** [BUG-108](../BUG_LOG.md) (a); попутно ops-пункты этапа 4 из [`PLAN_POST_FORCED_DP_2026-09-23.md`](../PLAN_POST_FORCED_DP_2026-09-23.md)
**Ветка:** новая от `main`, например `cursor/fix-bug108a-llm-stage-observability`.

**Goal (одной строкой):** после деплоя по Prometheus видно, сколько токенов съела каждая стадия (прежде всего Phase 2 discover); каждый вызов Phase 2 оставляет в логе размер каталога и фактические токены; логи контейнеров приложения переживают хотя бы неделю.

> Это **измерение перед вмешательством**: R14 (чистка удалённых каналов) и R17 (потолок контекста Phase 2) выбирают и проверяют эффект по данным этой сессии. Поведение LLM-вызовов не меняется — ни промпты, ни модели, ни каталог Phase 2. Прод — `ssh prod` только с `required_permissions: ["all"]`; чтение до GO, деплой только по явному GO владельца. Коммит — по запросу владельца. R14…R18 здесь не начинать.

---

## 0. Opener (вставить в новый чат)

> Стартую R13 — наблюдаемость LLM-расхода по стадиям (BUG-108 a) и ротация логов контейнеров.
>
> Прочитай:
> 1. `docs/notes/START_PROMPT_R13_LLM_COST_OBSERVABILITY_2026-09-23.md` — **этот файл целиком**
> 2. `docs/notes/BUG_LOG.md` — записи **BUG-108** и **BUG-107**; блок «Known constraint (2026-08-04)» над партией BUG-099 (про то, что короткое хранение логов — часть обоснования severity BUG-087 / BUG-088)
> 3. `docs/notes/PLAN_POST_FORCED_DP_2026-09-23.md` §1 — замер 2026-09-23, из которого калибруется алерт
> 4. `docs/quality/incidents/2026-08-28_anthropic_spend_phase2_discover.md` — follow-up 2 (observability)
> 5. `docs/notes/AUDIT_TOPICIZATION_KEYWORD_NOISE_2026-08-31.md` §3 — лог-строка `[3/4]`
> 6. `tests/README.md` — режимы; обязательный для app-code — PR standard (`TEST_POSTGRES=1`)
>
> Начни с `bash scripts/dev_doctor.sh`, сверь `main` с продом, затем read-only снимок из §1. Если код уже не такой, как в таблице, — скажи вслух, не чини исчезнувшее.

---

## 1. Состояние на входе (сверить, а не поверить; снято 2026-09-23 с `main` = прод = `bd03d3e`)

| Факт | Где |
|---|---|
| `tg_parser_llm_tokens_total` — лейблы `provider`, `model`, `token_type`; **стадии нет**. То же у `tg_parser_llm_requests_total` | `tg_parser/api/metrics.py` (`LLM_TOKENS_TOTAL`, `record_llm_request`) |
| Единственная точка записи — `InstrumentedLLMClient` (`generate` / `generate_with_usage`); создаётся в `create_llm_client(..., instrument=True)`; про стадию не знает | `tg_parser/processing/llm/instrumented.py`, `factory.py` |
| Вызовы `create_llm_client` — 9: `processing_service.py`, `processing/pipeline.py`, `retrieval_service.py` (RAG), `topicization_service.py` ×2 (полный прогон; Phase 2 discover — клиент создаётся только при `unassigned_refs`), `scheduler_service.py` (`_llm_factory` → `resolve_llm_config("digest")`), `resummarization_service.py` ×3 (включая cross-vendor fallback) | `rg -n 'create_llm_client\(' tg_parser` |
| Прецедент стадийного лейбла — `record_llm_truncation(provider, model, stage)` и `record_embedding_outcome(outcome, stage)` | `metrics.py` |
| Алерты на `tg_parser_llm_tokens_total` уже есть и **агрегируют через `sum(...)`** — лишний лейбл их не ломает. Комментарий в `alerts.yml` прямо говорит «NOT stage-scoped» — после сессии его нужно поправить | `docker/prometheus/alerts.yml` (`tg_parser_bug071_topicization`), тесты — `alerts_test.yml` |
| Логи Phase 2: `Loaded %d cross-channel topics as context …` (`_load_cross_channel_topics`), `incremental_llm_batch_start channel=… docs=…`, `Phase 2 batch: … (channel=…)` — **токенов нет ни в одной строке** | `topicization_service.py`, `processing/topicization.py` |
| `[3/4] Topicization skipped (scheduler does not auto-topicize by design; …)` — вводит в заблуждение: сразу после неё планировщик запускает `incremental_topicization` | `pipeline_service.py` (блок BUG-017) |
| В `docker-compose.yml` **нет ни одного** `logging:`; на проде логи `tg_parser` на 2026-09-23 держатся меньше суток (самая ранняя запись — 2026-09-22 08:32Z). Откуда лимит — daemon-дефолт или `/etc/docker/daemon.json` — **не проверено** (проверка из прошлой сессии упёрлась в auto-review; запросить одобрение) | `docker-compose.yml`; прод `docker inspect -f '{{.HostConfig.LogConfig}}'` |
| Маунт `./.env:/app/.env` уже снят (BUG-092 (c) исполнен) — не трогать и не возвращать | комментарий в `docker-compose.yml` |
| Базовая линия расхода (2026-09-02…22): Sonnet ~4.67M, Haiku ~0.72M; дни без Phase 2 — 7k–90k Sonnet, дни с одним вызовом — ~300k, двойной — ~590k; пик 2026-08-26 — ~1.09M | `PLAN_POST_FORCED_DP_2026-09-23.md` §1 |

---

## 2. Scope

**Входит:**

1. **Лейбл `stage`** на `tg_parser_llm_tokens_total` и `tg_parser_llm_requests_total` (гистограмму длительности не трогать — кардинальность × бакеты). Прокинуть через `create_llm_client(..., stage=…)` → `InstrumentedLLMClient` → `record_llm_request`. Словарь стадий — **закрытый**, согласованный со скоупами `set_llm_config` и стадиями `record_llm_truncation`; Phase 2 discover отличим от полного прогона (например `topicization_full` / `topicization_discover`). Значение по умолчанию — явное `unknown`, а не пропуск лейбла.
2. **Токены в логах Phase 2:** на старте батча — число карточек каталога и длина промпта в символах; на завершении — `input_tokens` / `output_tokens` из `LLMResponse`. Если Phase 2 вызывает `generate`, а не `generate_with_usage`, токенов в ответе нет — сказать вслух и решить, переводить ли вызов (это не меняет поведения модели, но меняет путь кэша ответов: `generate` кэширует, `generate_with_usage` — нет).
3. **Формулировка `[3/4]`** — по аудиту §3, например `[3/4] In-pipeline topicization skipped (handled by scheduler stage incremental_topicization)`. Комментарий BUG-017 над ней сохранить.
4. **Алерт на суточный расход** в `alerts.yml` + юнит-тест в `alerts_test.yml` (`promtool test rules`). Порог калибровать от базовой линии §1: не срабатывать на обычный день с одним-двумя вызовами Phase 2, срабатывать на порядок инцидента 2026-08-26 и выше. Перед этим выяснить, **куда реально доставляются алерты** (в compose нет Alertmanager; есть provisioning Grafana alerting) — если правило Prometheus никуда не доставляется, записать это и положить алерт туда, откуда он дойдёт до владельца. Оговорка в описании алерта: Prometheus видит только этот сервис, расход других программ на том же аккаунте Anthropic он не покажет.
5. **Ротация логов:** общий `x-logging` (json-file, `max-size` / `max-file`) для `tg_parser`, `tg_parser_bot`, `tg_parser_mcp` (и, по желанию, `prometheus` / `grafana`). **Не** для `postgres` — правка его спеки означает пересоздание контейнера БД. Размер посчитать от фактического суточного объёма логов, цель — 7–14 дней.

**Не входит:** потолок контекста Phase 2 и любые изменения промптов / моделей / каталога (R17); фильтр удалённых каналов (R14); нормализация `t.me` (R15 — параллельная сессия); бот-процесс (Gemini-клиент бота живёт отдельно, в этот словарь не входит — записать как известную дыру, если так и есть).

---

## 3. Ловушки

- **Удлинение хранения логов — не нейтральная правка.** Блок «Known constraint (2026-08-04)» в `BUG_LOG` и § Severity у BUG-087 / BUG-088 называют короткое хранение смягчающим фактором. Перед деплоем: убедиться, что редакция credential'ов (фиксы BUG-087 / BUG-088) в образе, и дописать в оба места одну строку о новом сроке хранения. Иначе severity-обоснование молча станет неверным.
- **Пересоздание — это стирание логов** (тот же блок): все улики, нужные до деплоя, снимать до `up -d`.
- **Фаза тика сдвигается** при пересоздании `tg_parser`: `incremental_pipeline` — interval-задача (урок R10), первый тик — «старт плюс интервал».
- **Prometheus-конфиг — директорный маунт** (`./docker/prometheus`); правило подхватывается `/-/reload` или рестартом Prometheus. Не возвращать одиночный file-маунт (BUG-090).
- **Кэш ответов:** `generate` отдаёт кэшированный ответ без записи метрики — это правильно (токенов не потрачено), тест не должен ожидать инкремента на кэш-хите.
- **Два параллельных полных прогона** на одной локальной БД `tg_parser_test` конфликтуют (`DROP SCHEMA` при инициализации). Если параллельно идёт R15 — полный PR standard запускать по очереди.

---

## 4. Тесты (минимум)

- Параметризованный тест словаря стадий: каждый вызов `create_llm_client` в `tg_parser/` передаёт стадию из закрытого множества (AST- или grep-проверка по образцу существующих «класс важнее экземпляра») — чтобы следующий новый вызов не уехал в `unknown` молча.
- `record_llm_request` пишет `stage` в обе метрики; кэш-хит метрику не трогает.
- Phase 2: лог-строки содержат размер каталога и токены (caplog).
- `promtool test rules` для нового алерта: не срабатывает на профиль «обычный день», срабатывает на профиль 2026-08-26.
- Полный PR standard (`TEST_POSTGRES=1`) зелёный; ожидание — порядка 4.2k passed (сверить с `tests/README.md`).

---

## 5. Деплой и проверка (только по GO)

1. Снимок до: `docker inspect` LogConfig трёх контейнеров, образы, `next run` тика, текущие серии `tg_parser_llm_tokens_total`.
2. Точка отката — тег текущего образа `tg_parser` (по образцу `BUG097_R10_DEPLOY_AND_WATCH.md`).
3. Пересоздать `tg_parser`, `tg_parser_bot`, `tg_parser_mcp` (ротация требует пересоздания всех трёх; если R15 готова — едет этим же деплоем). Postgres не трогать. Prometheus — reload.
4. Проверка: у всех трёх новый LogConfig; серии `tg_parser_llm_tokens_total` получили `stage`; первый тик прошёл; алерт загружен и в `inactive`.
5. **Отложенная проверка** (не блокирует закрытие сессии): первый вызов Phase 2 после деплоя (раз в 1–2 дня) оставил в логе размер каталога и токены, а серия `stage="topicization_discover"` выросла на ту же величину. Это и есть базовая линия «до R14».
6. Протокол — `docs/runbooks/BUG108A_R13_DEPLOY.md`; BUG-108 остаётся `open` (закроется после R17), в блоке «Что открыто» — отметка «(a) задеплоена».

---

## 6. Definition of Done

- PR смержен, прод на новом образе, три контейнера с ротацией, алерт загружен и доставляется.
- По Prometheus можно ответить «сколько токенов за сутки съела Phase 2», не читая логи.
- Комментарий «NOT stage-scoped» в `alerts.yml` и severity-строки BUG-087 / BUG-088 обновлены.
- `PLAN_REMEDIATION` §4a: R13 отмечена; `PLAN_POST_FORCED_DP_2026-09-23.md` этап 4: ротация логов и алерт — выполнены.
- Этот промпт переезжает в `docs/notes/archive/` в PR, закрывающем сессию (правило аудита документации §4).
