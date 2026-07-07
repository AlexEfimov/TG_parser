# S0 — Baseline метрик обработки (до remediation-сессий S1–S7)

**Тип документа:** baseline snapshot (read-only сессия S0 по [`WORKFLOW_REMEDIATION_SESSIONS_AGREEMENTS_2026-07-07.md`](WORKFLOW_REMEDIATION_SESSIONS_AGREEMENTS_2026-07-07.md) §4).
**Дата снятия:** 2026-07-07, live-снапшот 11:55:00Z–11:59:59Z (UTC).
**Основание:** [`PLAN_REMEDIATION_SESSIONS_PROCESSING_ALGORITHMS_2026-07-07.md`](PLAN_REMEDIATION_SESSIONS_PROCESSING_ALGORITHMS_2026-07-07.md), [`CODE_REVIEW_PROCESSING_ALGORITHMS_FABLE5_2026-07-07.md`](CODE_REVIEW_PROCESSING_ALGORITHMS_FABLE5_2026-07-07.md).

---

## 1. Назначение и режим сессии

Точка отсчёта («before») для доказательства эффектов сессий S1 (resummarize-токены/качество), S2 (длительность тика), S3 (pre-LLM дедуп, processing-вызовы), S4/S5 (топикизация, discover-вызовы), S7 (RAG latency) и для отлова регрессов.

**Сессия строго read-only:** ни один сервис не запускался и не останавливался, ни одна команда не меняла состояние; выполнены только чтение кода, `docker ps`, `curl` к уже работающим `/metrics` и `docker logs`/PromQL-запросы к уже работающему Prometheus. Единственный записанный файл — этот документ.

**Где снято.** Локальный стек tg_parser НЕ запущен (локально работает только `tg_parser_postgres`; API/Prometheus локально не подняты). Живой стек найден на **prod** (ssh-хост `prod`, `/home/user/TG_parser`): `tg_parser` (API+scheduler, up с 2026-07-06T21:50:07Z), `tg_parser_mcp` (up с 2026-07-02), `tg_parser_prometheus` (up с 2026-07-02, retention 30d), `tg_parser_bot`, `tg_parser_grafana`, `tg_parser_postgres`. Все live-значения ниже сняты с prod.

**Два окна значений** (важно для сравнения «после»):

- **since-restart** — сырые значения счётчиков с `/metrics` контейнера `tg_parser`; окно ≈ 14 часов (рестарт API 2026-07-06T21:50Z). Счётчики Prometheus обнуляются при рестарте контейнера — сравнивать «до/после» по сырым значениям можно только внутри одного uptime.
- **7d-increase** — `increase(...[7d])` через Prometheus API (переживает рестарты, но экстраполирует; значения дробные). Это основное сравнительное окно для S1/S3/S5.

**Конфигурация стадий LLM на prod в момент снятия** (из `.env`, без секретов): `PROCESSING_LLM_MODEL=claude-haiku-4-5-20251001`, `TOPICIZATION_LLM_MODEL=claude-sonnet-4-6`, `LLM_MODEL=claude-sonnet-4-6` (global default → RAG и resummarize), `RAG_LLM_*` не переопределён, `RESUMMARIZE_MAX_AGE_DAYS=14`. Это даёт рабочее правило разнесения токенов по стадиям: **haiku ≈ processing**, **sonnet ≈ topicization/discover/merge + resummarize + RAG**; resummarize дополнительно выделен собственным счётчиком.

---

## 2. Каталог метрик и снятые значения

### Область 1 — LLM-токены по стадиям (input/output)

| Метрика | Где определена | Labels | Текущее значение | Как снимать |
|---|---|---|---|---|
| `tg_parser_llm_tokens_total` | `tg_parser/api/metrics.py:96` | `provider, model, token_type∈{prompt,completion}` | **since-restart (14h):** haiku prompt=1 428 306, completion=1 139 891; sonnet prompt=7 487 640, completion=132 162. **7d-increase:** haiku prompt≈6 605 627, completion≈5 356 289; sonnet prompt≈29 050 032, completion≈5 558 529 | `curl http://127.0.0.1:8000/metrics` на prod; PromQL: `sum by (model, token_type) (increase(tg_parser_llm_tokens_total[7d]))` |
| `tg_resummarize_tokens_total` | `tg_parser/api/metrics.py:364` | `channel_id, provider, model, token_type` | **since-restart:** mediamedics prompt=136 726 / completion=45 441; Docma_ru prompt=115 925 / completion=26 439; Lab4health prompt=1 286 / completion=274 (все sonnet) | там же; PromQL: `sum by (channel_id, token_type) (increase(tg_resummarize_tokens_total[7d]))` — **ключевая метрика S1** (ожидаем рост prompt ~+1.5K/вызов) |
| `tg_parser_topicization_full_run_tokens_total` | `tg_parser/api/metrics.py:206` | `channel_id` | нет сэмплов since-restart (full-run не шёл в этом uptime) | PromQL: `increase(tg_parser_topicization_full_run_tokens_total[7d])` |

**Ограничения (важно для интерпретации):**
- Токены **не разнесены по стадиям** первоклассным label'ом — только по `model`; разнесение через mapping стадий→модели (см. §1). Если сессии S1–S5 поменяют модель стадии — mapping пересобрать.
- **RAG-токены не учитываются вовсе:** RAG идёт через `generate()` (`tg_parser/processing/llm/instrumented.py:33–64`), где `record_llm_request` вызывается **без** `prompt_tokens/completion_tokens`; токены пишутся только на пути `generate_with_usage` (`instrumented.py:66–96`). В baseline sonnet-токены ≈ topicization+resummarize.
- Расчётный итог «topicization ≈ sonnet − resummarize» since-restart: prompt ≈ 7 487 640 − 253 937 ≈ 7 233 703; completion ≈ 132 162 − 72 154 ≈ 60 008.

### Область 2 — Длительность тика планировщика

| Метрика/поле | Где определена | Labels | Текущее значение | Как снимать |
|---|---|---|---|---|
| Лог `Incremental pipeline completed ... duration=X.XXs` | `tg_parser/services/scheduler_service.py:907–918` (aggregate), `:878` (per-source `duration_seconds` в `details` записи attempt) | — (structlog, logger `tg_parser.services.scheduler_service`) | **Последние 14 тиков (2026-07-06T23:00Z → 2026-07-07T11:53Z):** 596.62, 436.65, 356.24, 407.39, 412.53, 79.59, 42.67, 50.48, 46.01, 259.59, 214.86, 204.37, 142.43, 199.97 s. Медиана ≈ 207 s, min 42.67, max 596.62 | `docker logs tg_parser --since 48h \| grep "Incremental pipeline completed"` — **ключевая метрика S2** |
| `tg_parser_scheduler_tasks_total` | `tg_parser/api/metrics.py:285` | `task_name, status` | since-restart: `incremental_pipeline/success=14`, `incremental_embedding/success=14`, `health_check/success=168`, `idempotency_keys_cleanup/success=14` | `/metrics`; только счётчик запусков — **гистограммы длительности тика в Prometheus нет** (gap; S2 меряется по логам) |
| `tg_telethon_session_lock_wait_seconds` | `tg_parser/api/metrics.py:1213` | `outcome∈{acquired,contention}` | since-restart: acquired count=169, sum=189.76 s (avg ≈ 1.12 s); contention — нет сэмплов | `/metrics` (histogram) — компонент времени тика, не затрагиваемый S2 |

**Замечание к baseline S2:** в окне попали деградированные тики (billing-блоки, failed=6–8 из 13 источников) — 42–80 s это тики с малым объёмом работы. Честное сравнение «до/после» S2 — по тикам с сопоставимым `new_messages` (поле `details.new_messages` в attempt-записях, `scheduler_service.py:872–880`).

### Область 3 — Latency RAG-запроса

| Метрика | Где определена | Labels | Текущее значение | Как снимать |
|---|---|---|---|---|
| `tg_parser_http_http_request_duration_seconds` | инструментатор `create_instrumentator` в `tg_parser/api/metrics.py:597–661` (namespace `tg_parser`, subsystem `http`) | `handler` (пути: `/api/v1/ask`, `/api/v1/search` — роуты в `tg_parser/api/routes/rag.py:84,116`, prefix `:16`) | **Нет сэмплов** — с рестарта API не было ни одного HTTP RAG-запроса (`..._highr_seconds_count=0.0`); RAG-трафик идёт через MCP/бота | PromQL: `histogram_quantile(0.95, sum by (le) (rate(tg_parser_http_http_request_duration_seconds_bucket{handler="/api/v1/ask"}[1d])))` |
| `tg_parser_llm_request_duration_seconds` | `tg_parser/api/metrics.py:89` | `provider, model` | since-restart: haiku count=1296, sum=8801.04 s (avg 6.79 s); sonnet count=235, sum=2049.42 s (avg 8.72 s) | `/metrics` — LLM-компонента ответа RAG (не end-to-end) |

**Статус: to capture.** End-to-end RAG latency на живом трафике не измерена: HTTP-endpoint без трафика, а MCP-путь (`ask_question`) не отдаёт `tg_parser_llm_*`-серии на `:8080/metrics` (проверено — пусто). Для S7 («−десятки мс на запрос») baseline снять непосредственно перед S7: N=10–20 повторяемых запросов `POST /api/v1/ask` на prod/dev с секундомером curl (`time_total`), либо по логу `rag_ask` (`tg_parser/api/routes/rag.py:123`) + timestamp'ам. Шаблон — §4.

### Область 4 — Дедуп-счётчики и processing-вызовы

| Метрика | Где определена | Labels | Текущее значение | Как снимать |
|---|---|---|---|---|
| `tg_dedup_duplicates_detected_total` (exact, post-LLM) | `tg_parser/api/metrics.py:54`; инкременты `tg_parser/processing/pipeline.py:481–484, 1065–1089` | `channel_id` | **since-restart (сумма=745):** Docma_ru=442, labdiagnostica_logical=143, Lab4health=60, AgeManagment=40, mediamedics=30, genotek=20, foodf4thought=10. **7d-increase: ≈1559** | `/metrics`; PromQL: `sum(increase(tg_dedup_duplicates_detected_total[7d]))` — **ключевая метрика S3**: сейчас каждый из этих hit'ов = оплаченный LLM-вызов; после S3 они должны уйти в новый pre-LLM счётчик |
| `tg_dedup_near_duplicates_detected_total` | `tg_parser/api/metrics.py:68` | `channel_id, method, dimension∈{intra,cross}` | 7d: intra=2, cross=0 (max_over_time; since-restart сэмплов нет) | PromQL: `sum by (dimension) (max_over_time(tg_dedup_near_duplicates_detected_total[7d]))` |
| `tg_dedup_near_duplicate_similarity` | `tg_parser/api/metrics.py:75` | `dimension` (histogram) | практически пусто (2 наблюдения за 7d) | `/metrics` |
| `tg_parser_llm_requests_total` (processing-вызовы ≈ haiku) | `tg_parser/api/metrics.py:83` | `provider, model, status` | **since-restart:** haiku success=1151, error=145; sonnet success=228, error=7. **7d-increase:** haiku success≈5617, error≈14 968 (!); sonnet success≈1469, error≈1006 | PromQL: `sum by (model, status) (increase(tg_parser_llm_requests_total[7d]))` — haiku-success = прокси числа processing-вызовов для S3 |
| `tg_parser_messages_processed_total` | `tg_parser/api/metrics.py:41` | `channel_id, status` | нет сэмплов since-restart (в этом uptime не проходил учитываемый путь) | `/metrics`; PromQL `increase(...[7d])` |
| Pre-LLM dedup hits | — **не существует** | — | — | появится в S3 (deliverable «новая метрика pre-LLM dedup hits») — имя зафиксировать в S3 |

**Контекст для S3/S5:** высокий 7d error-rate haiku (≈15K error при ≈5.6K success) — это billing-блоки/ретраи периода 2026-07-06 (см. `tg_parser_anthropic_billing_block_total`); учитывать при сравнении «число вызовов до/после», сравнивать по `status="success"`.

### Область 5 — Прочие метрики, привязанные к deliverable'ам сессий

| Метрика | Где определена | Labels | Текущее значение | Сессия / как снимать |
|---|---|---|---|---|
| `tg_parser_topicization_reconcile_discover_docs_total` | `tg_parser/api/metrics.py:191` | `channel_id` | since-restart: mediamedics=736 | S5 (−10–30% discover): PromQL `sum(increase(...[7d]))` — прокси discover-объёма reconcile-пути |
| `tg_parser_topicization_failed_batches_total` | `tg_parser/api/metrics.py:144` | `stage, channel_id` | нет сэмплов since-restart | S6; `/metrics` |
| `tg_parser_llm_truncation_total` | `tg_parser/api/metrics.py:111` | `provider, model, stage` | нет сэмплов since-restart | S6; `/metrics` |
| `tg_parser_llm_json_parse_retry_total` | `tg_parser/api/metrics.py:300` | `stage` | нет сэмплов since-restart | S3/S6; `/metrics` |
| `tg_parser_topicization_full_run_*` (chunks/budget_halt/resume/chunk_failed/noprogress_skip) | `tg_parser/api/metrics.py:215,224,233,247,258` | `channel_id` (+`kind`/`reason`) | нет сэмплов since-restart | S4/S6; `/metrics` |
| `tg_parser_anthropic_billing_block_total` | `tg_parser/api/metrics.py:291` | `stage` | since-restart: processing=141, process_billing_blocked=13 | контекст для всех сессий; `/metrics` |
| `tg_watchlist_score` (histogram) | `tg_parser/api/metrics.py:396` | — | since-restart: count=17, sum=0.667 (все ≤0.5, кроме 2 в (0.3,0.5]) | S2/O-7 — скоры должны остаться байт-в-байт теми же; `/metrics` |
| `tg_watchlist_matches_total` | `tg_parser/api/metrics.py:382` | `result` | since-restart: filtered_threshold=17; delivered/filtered_keywords=0 | S2; `/metrics` |
| `tg_watchlist_active_interests` | `tg_parser/api/metrics.py:415` | — | 16 | S2 (масштаб I для O(I×D)) |
| `tg_watchlist_semantic_unavailable_total` | `tg_parser/api/metrics.py:434` | `reason` | since-restart: doc_no_embedding=17 | S2; `/metrics` |
| Watchlist scoring time | — **не существует** (есть только распределение скоров) | — | — | S2: эффект O-7 мерить по общей длительности тика (лог §2) — отдельной метрики CPU-времени скоринга нет |
| LLM response cache hit/miss | `tg_parser/processing/llm/response_cache.py:39–40, 96–110` (`stats()`: hits/misses/hit_rate/size) | — | **не экспортируется** ни в Prometheus, ни в API — только in-process dict | S2/O-6: тест-уровень; если нужен live-baseline — снимать нечем (осознанный gap) |
| LLM rate-limiter | `tg_parser/processing/llm/rate_limiter.py:108–116` (log-events `rate_limit_rpm_adjusted`/`itpm`/`otpm`), `:148` (debug acquire) | — (логи) | не снималось (debug-уровень) | S3: «снижение processing-вызовов в логах rate-limiter» — включить LOG_LEVEL=DEBUG точечно или опираться на `tg_parser_llm_requests_total` |
| `tg_channel_processed_coverage_ratio` | `tg_parser/api/metrics.py:1198` | `channel_id` | 13 каналов: 6×1.0; AgeManagment 0.9965, foodf4thought 0.9970, genotek 0.9983, mediamedics 0.9997, Lab4health 0.9968, labdiagnostica_logical 0.9893, Docma_ru 0.9867 | регресс-стоп для S3 (дедуп не должен уронить coverage) |
| `tg_resummarize_total` | `tg_parser/api/metrics.py:338` | `channel_id, outcome, trigger` | since-restart: mediamedics ok/counter=95, Docma_ru ok/counter=87, Lab4health ok/age=1, labdiagnostica_logical llm_error/age=11 | S1: доля outcome=ok и рост prompt-токенов/вызов |
| `tg_resummarize_duration_seconds` | `tg_parser/api/metrics.py:373` | `model` | since-restart: count=183, sum=1070.49 s (avg 5.85 s/вызов) | S1: avg prompt-токенов/вызов baseline = 253 937/183 ≈ **1388 prompt-tokens/вызов** (после S1 ожидаем ≈ +1.5K) |

**Итого каталогизировано: 24 метрики/источника** (обл.1: 3; обл.2: 3; обл.3: 2; обл.4: 6; обл.5: 10), из них 2 отсутствуют в кодовой базе (pre-LLM dedup hits — появится в S3; watchlist scoring time — нет и не планируется) и 2 не экспортируются наружу (cache stats, rate-limiter — только логи/in-process).

---

## 3. Что снято живьём vs отложено

**Снято живьём** (prod, 2026-07-07T11:55–12:00Z; источник: `/metrics` контейнера `tg_parser`, Prometheus HTTP API `tg_parser_prometheus`, `docker logs tg_parser`):
- все значения областей 1, 2, 4 и 5 из таблиц выше — и since-restart, и 7d-increase;
- конфигурация стадий LLM (mapping model→стадия);
- список работающих контейнеров + их uptime (окна счётчиков).

**Отложено (to capture):**
- **End-to-end RAG latency (область 3)** — живого HTTP RAG-трафика нет, MCP-путь не инструментирован серия­ми `tg_parser_llm_*` на `:8080/metrics`. Снять перед S7 по шаблону §4.
- **RAG-токены** — не записываются вообще (путь `generate()` без usage); либо принять как gap, либо S7 добавит usage-учёт.
- **Cache hit/miss и rate-limiter counts** — не экспортируются; baseline по ним не существует (зафиксировано как осознанный gap, а не «нули»).
- `tg_parser_messages_processed_total`, near-dup similarity, truncation/json-retry/full-run-серии — сэмплов в текущем uptime нет; их «before» = 0 в окне сравнения, отдельного снятия не требуется.

Ничего в этом документе не сфабриковано: каждая ячейка — либо live-значение с указанным окном, либо явное «нет сэмплов» / «to capture» / «не существует».

---

## 4. Шаблон снапшота для последующего снятия (fill-in)

Снимать на prod (или dev-стеке) непосредственно перед и после каждой сессии. Команды read-only.

```text
SNAPSHOT_ID: (before-S1 | after-S1 | before-S3 | ... )
DATE_UTC: ____
API_CONTAINER_STARTED_AT: ____   # docker inspect -f '{{.State.StartedAt}}' tg_parser
WINDOW: (since-restart | 7d-increase | оба)
```

```bash
# 1. Токены по модели/типу (7d) — области 1
docker exec tg_parser_prometheus wget -qO- \
  'http://localhost:9090/api/v1/query?query=sum by (model,token_type) (increase(tg_parser_llm_tokens_total[7d]))'
# haiku prompt=____ completion=____ ; sonnet prompt=____ completion=____

# 1a. Resummarize-токены и вызовы (S1)
curl -s http://127.0.0.1:8000/metrics | grep -E '^tg_resummarize_(tokens_total|total|duration_seconds_(count|sum))'
# prompt_total=____ ; calls(ok)=____ ; avg prompt/call=____   (baseline: 1388)

# 2. Длительность тика (S2)
docker logs tg_parser --since 48h 2>&1 | grep 'Incremental pipeline completed'
# последние N тиков: ____  (baseline: медиана ≈207s на 13 источниках, min 42.67 max 596.62)

# 3. RAG latency (S7) — N=10 повторяемых вопросов
for i in $(seq 1 10); do curl -s -o /dev/null -w '%{time_total}\n' \
  -X POST http://127.0.0.1:8000/api/v1/ask -H 'Content-Type: application/json' \
  -d '{"question":"<фиксированный вопрос>","channel_id":"<канал>"}'; done
# p50=____ p95=____   (baseline: НЕ СНЯТ — нет трафика)

# 4. Дедуп и processing-вызовы (S3)
docker exec tg_parser_prometheus wget -qO- \
  'http://localhost:9090/api/v1/query?query=sum(increase(tg_dedup_duplicates_detected_total[7d]))'
# exact_dedup_7d=____   (baseline: ≈1559)
docker exec tg_parser_prometheus wget -qO- \
  'http://localhost:9090/api/v1/query?query=sum by (model,status) (increase(tg_parser_llm_requests_total[7d]))'
# processing(haiku) success=____ error=____   (baseline: ≈5617 / ≈14968)
# pre-LLM dedup hits (метрика появится в S3): ____

# 5. Discover-объём (S5) и watchlist (S2)
docker exec tg_parser_prometheus wget -qO- \
  'http://localhost:9090/api/v1/query?query=sum(increase(tg_parser_topicization_reconcile_discover_docs_total[7d]))'
# reconcile_discover_docs_7d=____   (baseline since-restart: 736)
curl -s http://127.0.0.1:8000/metrics | grep -E '^tg_watchlist_(score_(count|sum)|matches_total|active_interests)'
# score_count=____ score_sum=____ (скоры после O-7 должны совпасть байт-в-байт)

# 6. Регресс-стопы
curl -s http://127.0.0.1:8000/metrics | grep '^tg_channel_processed_coverage_ratio'
# coverage per channel: ____ (baseline: см. §2 обл.5; падение = регресс S3)
```

---

*Строки кода — по рабочей копии 2026-07-07 (совпадает с отчётом ревью). При смещении нумерации ориентироваться на имена метрик — они уникальны в `tg_parser/api/metrics.py`.*
