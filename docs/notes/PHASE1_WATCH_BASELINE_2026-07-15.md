# Phase-1 Watch — t0 baseline snapshot (2026-07-15)

**Тип документа:** read-only baseline snapshot (start of three Phase-1 observation windows).
**Режим:** строго read-only prod (Prometheus HTTP API `/api/v1/query` + `/api/v1/rules`, `curl` к `/metrics`, `docker compose logs`). Ни один сервис не запускался/останавливался; единственный записанный артефакт — этот документ.
**Шаблон снапшота:** [`S0_BASELINE_PROCESSING_METRICS_2026-07-07.md`](S0_BASELINE_PROCESSING_METRICS_2026-07-07.md) §4.
**Доступ/команды:** [`../runbooks/S1_S3_DEPLOY_AND_WATCH.md`](../runbooks/S1_S3_DEPLOY_AND_WATCH.md) (ssh-хост `prod`, `/home/user/TG_parser`).

---

## 0. Контекст снятия (t0)

```text
T0_UTC:                     2026-07-15T12:22:05Z
PROD HEAD:                  186b60e  (Merge PR #313 — feat/bug084-quota-exhausted-alert)
API_CONTAINER_STARTED_AT:   2026-07-15T11:21:10Z   (uptime ≈ 1h → since-restart окно ≈ 1h)
PROMETHEUS_STARTED_AT:      2026-07-15T11:27:56Z
CONTAINERS:                 tg_parser / tg_parser_bot / tg_parser_mcp — Up (healthy);
                            tg_parser_prometheus Up; tg_parser_postgres / grafana Up.
```

> ⚠️ **Gap #1 — HEAD drift.** Задача указывала prod HEAD `df820ce`, но фактический prod HEAD на момент снятия — **`186b60e`**. Дельта `186b60e..df820ce` — единственный коммит **PR #314 `docs(bug084): mark BUG-084 resolved after prod deploy`** (docs-only, `docs/notes/BUG_LOG.md`). Функциональной разницы для метрик/алертов нет: alert-rules (`docker/prometheus/alerts.yml`) и код метрик (`tg_parser/api/metrics.py`) идентичны на обоих коммитах. Baseline валиден.
>
> ⚠️ **Общая оговорка по окнам.** API-контейнер рестартнул ≈1ч назад (11:21Z). Сырые (since-restart) счётчики отражают ~1ч; `increase(...[24h/7d])` переживают рестарт (обрабатывают reset), но окна 24h/7d частично покрывают до-рестартовый период.

---

## 1. Watch — BUG-084 embedding quota / alert soak

**Цель watch:** подтвердить, что после восстановления квоты OpenAI нет накопления `rate_limited` / `quota_exhausted` и нет ложного срабатывания алертов.
**Окно re-check:** 24–48h.

### 1.1 `tg_embedding_requests_total{outcome, stage}` (t0)

Источник истины — Prometheus (см. gap #2 про `/metrics`).

| Query | Результат (t0) |
|---|---|
| `sum by (outcome,stage) (tg_embedding_requests_total)` | `{outcome="ok", stage="rag_query"} = 2` — **единственная серия** |
| `sum by (outcome) (increase(tg_embedding_requests_total[24h]))` | `ok ≈ 1.005` |
| `sum by (outcome) (increase(tg_embedding_requests_total[7d]))` | `ok ≈ 1.005` |

**Отсутствуют полностью** (не «ноль», а нет серии): `outcome ∈ {rate_limited, quota_exhausted, error}` во всех окнах; `stage ∈ {background_message, background_topic}` — нет сэмплов в этом uptime (фоновый embedding-путь ещё не инкрементировал классифицированный счётчик с рестарта).

> ⚠️ **Gap #2 — `/metrics` vs Prometheus.** `curl :8000/metrics | grep '^tg_embedding_requests_total'` вернул пусто, при этом Prometheus-scrape видит `ok/rag_query=2`. Счётчик `EMBEDDING_REQUESTS_TOTAL` — module-level `prometheus_client.Counter`, инкремент прошёл на одном воркере/инстансе; выбранный `curl`-скрейпом воркер серию не отдал. Для этого watch **Prometheus — источник истины** (алерты считаются именно по нему). `tg_channel_processed_coverage_ratio` (Gauge, §3) в том же `/metrics` присутствует — расхождение только по этому counter'у.

### 1.2 Состояния алертов (`/api/v1/rules`, t0)

| Alert | state | health | active | for | expr |
|---|---|---|---|---|---|
| `EmbeddingQuotaExhausted` | **inactive** | ok | 0 | 1800s | `sum(increase(tg_embedding_requests_total{outcome="quota_exhausted"}[15m])) > 0` |
| `EmbeddingRateLimitedSustained` | **inactive** | ok | 0 | 1800s | `sum(increase(tg_embedding_requests_total{outcome="rate_limited"}[15m])) > 0` |

Всего alerting-правил загружено: **26**; firing: **0**.

### 1.3 Re-snapshot и критерии

- **Re-snapshot:** 2026-07-16T12:22Z (24h) → 2026-07-17T12:22Z (48h).
- **PASS:** `increase(tg_embedding_requests_total{outcome="rate_limited"}[24h]) == 0` **и** `{outcome="quota_exhausted"}[24h] == 0`; оба алерта остаются `inactive`; `outcome=ok` — единственная серия по outcome.
- **FAIL:** любое накопление `rate_limited`/`quota_exhausted`; либо любой из двух алертов перешёл в `pending`/`firing`. Действие при FAIL — [`../runbooks/OPENAI_EMBEDDING_QUOTA_RECOVERY.md`](../runbooks/OPENAI_EMBEDDING_QUOTA_RECOVERY.md).

---

## 2. Watch — S3 pre-LLM dedup forward-watch

**Цель watch:** накопить pre-LLM hit-rate на живом трафике (рекомендация [`S3_DELTA_WATCH_2026-07-11.md`](S3_DELTA_WATCH_2026-07-11.md) §Рекомендации) и подтвердить отсутствие регресса coverage (T1).
**Окно re-check:** 48–72h. Метрики/запросы — те же, что в S3 delta watch и [`S0_BASELINE_PROCESSING_METRICS_2026-07-07.md`](S0_BASELINE_PROCESSING_METRICS_2026-07-07.md) §5 (для сопоставимости).

### 2.1 Значения (t0)

| Метрика / query | t0 (2026-07-15) | Референс 2026-07-11 (S3 delta) |
|---|---|---|
| `sum(tg_dedup_pre_llm_hits_total)` (raw) | **нет сэмплов** (0 since-restart) | — |
| `sum(increase(tg_dedup_pre_llm_hits_total[24h]))` | нет сэмплов (0) | 0 (billing-clean 24h) |
| `sum(increase(tg_dedup_pre_llm_hits_total[48h]))` | нет сэмплов (0) | — |
| `sum(increase(tg_dedup_pre_llm_hits_total[7d]))` | **0** (по каналам Docma_ru / Lab4health / labdiagnostica_logical — все 0) | ≈6 (7d) |
| `sum(increase(tg_dedup_duplicates_detected_total[24h]))` (post-LLM) | **≈12.0** | ≈1014 |
| `sum(increase(tg_dedup_duplicates_detected_total[7d]))` | **≈5258** | ≈5191 |
| `sum by (model,status) (increase(tg_parser_llm_requests_total[24h]))` | haiku success **≈23**, error **≈680**; sonnet success ≈5, error ≈11 | haiku success ≈1037, error 0 |
| `sum by (model,status) (increase(tg_parser_llm_requests_total[7d]))` | haiku success **≈5398**, error **≈1160**; sonnet success ≈92, error ≈15 | haiku success ≈8806, error ≈8142 |
| `sum(increase(tg_parser_anthropic_billing_block_total[24h]))` (confounder) | **≈796** | ≈0 (billing-clean) |
| `sum(increase(tg_parser_anthropic_billing_block_total[7d]))` | **≈1355** | ≈8196 |

### 2.2 Текущее состояние (последний 1h, since-restart — чистое)

Elevated 24h/7d haiku-error + billing-block выше — это **исторический billing-эпизод** РАНЬШЕ в trailing-окне, уже снятый:

| Проверка (последний 1h) | Значение |
|---|---|
| `sum by (model,status) (increase(tg_parser_llm_requests_total[1h]))` | haiku success **≈74**, **error отсутствует**; sonnet success ≈9 |
| `sum(increase(tg_parser_anthropic_billing_block_total[1h]))` | **нет сэмплов (0)** |
| `sum(rate(tg_parser_anthropic_billing_block_total[10m]))` | нет сэмплов (0) |
| `AnthropicBillingStillBlocked` alert | **inactive / ok** |
| billing/insufficient_quota/overloaded в логах за 70m | **0 строк** |

> ⚠️ **Gap #3 — S3-окно confounded.** 24h/48h/7d сравнение pre-LLM vs post-LLM dedup confounded недавним Anthropic-billing-эпизодом (≈796 blocks / ≈680 haiku errors за 24h), совпадающим с BUG-082/BUG-084-паттерном прошлых watch'ей. С ~11:21Z (рестарт) окно чистое. Для вердикта на re-snapshot использовать **billing-clean окно** (как в S3 delta watch): выбрать интервал с `increase(anthropic_billing_block_total[window])≈0` и haiku error≈0.

### 2.3 Re-snapshot и критерии

- **Re-snapshot:** 2026-07-17T12:22Z (48h) → 2026-07-18T12:22Z (72h), в billing-clean окне.
- **PASS (механизм созревает):** `sum(increase(tg_dedup_pre_llm_hits_total[48h])) > 0` в billing-clean окне, **и** coverage (§3) по каждому каналу ≥ baseline (нет T1-регресса).
- **NEUTRAL / PARTIAL:** pre-LLM hits всё ещё 0 при созревающем `raw_content_hash`-корпусе — не провал (это уже зафиксированный `S3 effect: PARTIAL`), продолжить watch.
- **FAIL (регресс-стоп T1):** любой канал `tg_channel_processed_coverage_ratio` < baseline (§3) → дедуп режет лишнее → откат S3 (`DEDUP_ENABLED=false` + restart, runbook §Rollback).

---

## 3. Watch — S5/S6 post-deploy metric-watch

**Цель watch:** подтвердить чистоту S6 (malformed-merge) и стабильность S5 (assign/coverage/discover) под живой нагрузкой — [`WORKFLOW_REMEDIATION_SESSIONS_AGREEMENTS_2026-07-07.md`](WORKFLOW_REMEDIATION_SESSIONS_AGREEMENTS_2026-07-07.md) §8 S5/S6 блок.

### 3.1 S6 — malformed_merge / failed batches (t0)

| Метрика / query | t0 |
|---|---|
| `tg_parser_topicization_full_run_chunk_failed_total` (raw, все reasons) | **нет серий** (resumable full-path ships dark — flat/absent by design) |
| `tg_parser_topicization_full_run_chunk_failed_total{reason="malformed_merge"}` (raw) | **0 sample** |
| `sum(increase(...{reason="malformed_merge"}[7d]))` | нет сэмплов |
| `tg_parser_topicization_failed_batches_total` (raw) | **нет серий (0)** |
| `sum by (stage) (increase(tg_parser_topicization_failed_batches_total[7d]))` | нет сэмплов |

### 3.2 S5 — discover / assign / coverage (t0)

| Метрика / query | t0 |
|---|---|
| `sum(increase(tg_parser_topicization_reconcile_discover_docs_total[7d]))` (discover proxy) | **0** |
| `sum by (channel_id) (increase(tg_parser_topics_created_total[7d]))` | genotek 0, medportal_rfed 0 |

**S5 coverage baseline — `tg_channel_processed_coverage_ratio` (регресс-стоп T1, 11 каналов):**

| channel_id | coverage (t0) |
|---|---|
| BiocodebySechenov | 1.0 |
| kdl_ru | 1.0 |
| LongevityClub | 1.0 |
| medportal_rfed | 1.0 |
| mind_rise | 1.0 |
| profendocrinologist | 1.0 |
| genotek | 0.99828 |
| Lab4health | 0.99791 |
| labdiagnostica_logical | 0.99754 |
| foodf4thought | 0.99706 |
| AgeManagment | 0.99655 |

> ⚠️ **Gap #4 — сменился channel roster.** Текущий набор (11 каналов) отличается от S0/S5-baseline (`Docma_ru`, `mediamedics` и др., 13 каналов). Прямое per-channel сравнение с S0 §2 обл.5 и §7 возможно только по пересечению: `foodf4thought`, `AgeManagment`, `genotek`, `Lab4health`, `labdiagnostica_logical`. Для них t0-coverage ≥ соответствующих S0-значений (напр. labdiagnostica 0.99754 ≥ S0 0.9893). `Docma_ru`/`mediamedics` в текущем `/metrics` отсутствуют.

### 3.3 Re-snapshot и критерии

- **Re-snapshot:** ближайшие часовые тики + формально 24–48h (2026-07-16 → 2026-07-17).
- **S6 PASS:** `tg_parser_topicization_full_run_chunk_failed_total{reason="malformed_merge"}` остаётся 0 sample; нет `failed merge chunk` в логах; `TopicizationFullRunChunkFailedSustained` inactive.
- **S5 PASS:** coverage по каждому пересекающемуся каналу ≥ baseline (§3.2); `TopicizationReconcileDiscoverSustained` inactive (discover proxy не «залипает» non-zero на 2h).
- **FAIL:** `malformed_merge > 0`; либо падение coverage ниже baseline; либо reconcile-discover sustained non-zero >2h (non-convergence).

---

## 4. Сводка t0 (one-look)

| Watch | Ключевой t0 | Re-snapshot | PASS-критерий (кратко) |
|---|---|---|---|
| BUG-084 embedding | `ok/rag_query=2`; 0 failure-outcomes; оба алерта inactive | 24–48h | 0 rate_limited/quota_exhausted; алерты inactive |
| S3 pre-LLM dedup | pre-LLM hits 7d=0; post-LLM 7d≈5258; haiku(1h)=74 ok/0 err | 48–72h (billing-clean) | pre-LLM hits>0 **и** coverage ≥ baseline |
| S5/S6 post-deploy | malformed_merge=0 sample; coverage ≥0.9965; discover 7d=0 | часовые тики + 24–48h | malformed_merge=0 **и** coverage ≥ baseline |

**Gaps зафиксированы:** #1 HEAD drift (docs-only `186b60e` vs `df820ce`), #2 `/metrics` per-worker counter (Prometheus = источник истины), #3 S3-окно confounded историческим billing-эпизодом (текущий 1h чист), #4 сменился channel roster vs S0/S5. Ни одно значение не сфабриковано — каждая ячейка либо live-значение с указанным окном, либо явное «нет сэмплов».

*Снято read-only с prod (`186b60e`) 2026-07-15T12:22Z: Prometheus HTTP API `tg_parser_prometheus`, `/metrics` контейнера `tg_parser`, `docker compose logs`.*

---

# Re-snapshot t1 (2026-07-16)

**Тип:** read-only re-snapshot трёх Phase-1 окон против t0-baseline (выше). Единственный записанный артефакт — эта секция. Ни один сервис не запускался/останавливался.
**Запросы:** идентичны t0 (Prometheus HTTP API `/api/v1/query` + `/api/v1/rules` через `tg_parser_prometheus`), для сопоставимости.

## t1. Контекст снятия

```text
T1_UTC:                     2026-07-16T10:52:36Z
ELAPSED since t0:           ≈ 22h30m31s  (t0 = 2026-07-15T12:22:05Z)
PROD HEAD:                  186b60e  (тот же, что t0 — HEAD drift нет)
CONTAINERS:                 tg_parser / tg_parser_bot / tg_parser_mcp — Up 24h (healthy);
                            tg_parser_prometheus Up 23h; tg_parser_postgres / grafana Up.
SCHEDULER:                  23× "Incremental pipeline completed" за 24h (часовой тик работает);
                            последний тик 2026-07-16T10:22:48Z (succeeded=6, failed=7, degraded=7, duration=82s).
```

> ⚠️ **Общая оговорка по elapsed.** С t0 прошло **≈22.5h** — это НИЖЕ формальных целевых окон всех трёх watch (W1 24–48h, W2 48–72h, W3 24–48h). Часовой since-restart больше не действует (контейнеры Up 24h), поэтому `increase(...[24h])` теперь полностью покрывает пост-t0-период. W2 явно помечен **INTERIM** (см. ниже).

---

## t1.1 Watch — BUG-084 embedding quota / alert soak → **PASS**

| Query | t0 | t1 | Δ |
|---|---|---|---|
| `sum by (outcome,stage) (tg_embedding_requests_total)` | `ok/rag_query = 2` (единственная серия) | `ok/rag_query = 2` (единственная серия) | без изменений; новых outcome-серий нет |
| `sum by (outcome) (increase(tg_embedding_requests_total[24h]))` | `ok ≈ 1.005` | `ok ≈ 1.0002` | только `ok`; no-op рост |
| `sum by (outcome) (increase(tg_embedding_requests_total[7d]))` | `ok ≈ 1.005` | `ok ≈ 1.0002` | только `ok` |
| `sum(increase(tg_embedding_requests_total{outcome="rate_limited"}[24h]))` | нет серии | **нет серии (0)** | 0 accrual |
| `sum(increase(tg_embedding_requests_total{outcome="quota_exhausted"}[24h]))` | нет серии | **нет серии (0)** | 0 accrual |

**Алерты (`/api/v1/rules`, t1):** `EmbeddingQuotaExhausted` — **inactive/ok** (active=0), `EmbeddingRateLimitedSustained` — **inactive/ok** (active=0). Всего alerting-правил: **26**; firing: **0** (как t0).

**Verdict: PASS.** С t0 нет накопления `rate_limited`/`quota_exhausted` (серии по-прежнему отсутствуют), `outcome=ok` — единственная серия, оба алерта остаются `inactive`. Критерий §1.3 выполнен. Elapsed ≈22.5h (чуть ниже 24h-точки, но soak чист) — рекомендуется подтверждающий read на 48h.

## t1.2 Watch — S3 pre-LLM dedup forward-watch → **INTERIM (too-early)**

| Метрика / query | t0 (2026-07-15) | t1 (2026-07-16) | Δ / комментарий |
|---|---|---|---|
| `sum(tg_dedup_pre_llm_hits_total)` (raw) | нет сэмплов (0) | **нет сэмплов (0)** | без изменений |
| `sum(increase(tg_dedup_pre_llm_hits_total[24h]))` | нет сэмплов (0) | **нет сэмплов (0)** | 0 |
| `sum(increase(tg_dedup_pre_llm_hits_total[48h]))` | нет сэмплов (0) | **нет сэмплов (0)** | 0 |
| `sum(increase(tg_dedup_pre_llm_hits_total[7d]))` | 0 | **0 (нет серии)** | по-прежнему 0 |
| `sum(increase(tg_dedup_duplicates_detected_total[24h]))` (post-LLM) | ≈12.0 | **≈932.1** | ↑ (живой трафик, пост-LLM дедуп активен) |
| `sum(increase(tg_dedup_duplicates_detected_total[7d]))` | ≈5258 | **≈5411** | +≈153 |
| `sum by (model,status) (increase(tg_parser_llm_requests_total[24h]))` | haiku ok ≈23 / err ≈680; sonnet ok ≈5 / err ≈11 | **haiku ok ≈977 / err ≈1; sonnet ok ≈20 / err 0** | haiku error ↓≈680→1 (billing-эпизод вышел из окна) |
| `sum by (model,status) (increase(tg_parser_llm_requests_total[7d]))` | haiku ok ≈5398 / err ≈1160; sonnet ok ≈92 / err ≈15 | **haiku ok ≈5572 / err ≈996; sonnet ok ≈84 / err ≈11** | haiku 7d-err ↓ |
| `sum by (model,status) (increase(tg_parser_llm_requests_total[1h]))` | haiku ok ≈74 / err 0 | **haiku ok ≈41 / err 0** | чисто |
| `sum(increase(tg_parser_anthropic_billing_block_total[24h]))` (confounder) | ≈796 | **0** | 24h-окно теперь billing-clean |
| `sum(increase(tg_parser_anthropic_billing_block_total[7d]))` | ≈1355 | **≈1168** | historical episode тает |
| `sum(increase(tg_parser_anthropic_billing_block_total[1h]))` | нет сэмплов (0) | **нет сэмплов (0)** | чисто |

**Billing-clean статус:** окно [24h] на t1 **billing-clean** — `anthropic_billing_block[24h]=0` и haiku `error[24h]≈1` (единичный transient `overloaded_error`, не billing-pause). Confounder из t0 (Gap #3, ≈796 blocks) вышел из trailing-окна. Логи за 24h: 0 `malformed`/`failed merge chunk`; grep по `billing|insufficient_quota|overloaded` = 190 строк, из них 167 — benign `parallel_batch_complete` (billing-статус поле), 21 — transient `anthropic_network_error`, 1 — `overloaded_error`, 1 — `processing_attempt_failed`. Реального billing-pause нет (метрика подтверждает).

**Verdict: INTERIM (too-early).** Прошло ≈22.5h из целевого окна **48–72h** — это не финальный PASS/FAIL. По существу: pre-LLM hits **всё ещё 0** (созревающий `raw_content_hash`-корпус) → это зафиксированный статус `S3 effect: PARTIAL` / NEUTRAL по §2.3, **не** провал. Coverage не просел (§t1.3) → нет T1-регресса. Важно: в отличие от t0, окно [24h] теперь **billing-clean**, так что следующий 48–72h read впервые пройдёт в чистых условиях. **Требуется поздний billing-clean read на 48–72h** (2026-07-17→18).

## t1.3 Watch — S5/S6 post-deploy metric-watch → **PASS**

**S6 — malformed_merge / failed batches (t1):**

| Метрика / query | t0 | t1 |
|---|---|---|
| `tg_parser_topicization_full_run_chunk_failed_total` (raw, все reasons) | нет серий | **нет серий** |
| `...{reason="malformed_merge"}` (raw) | 0 sample | **0 sample** |
| `sum(increase(...{reason="malformed_merge"}[7d]))` | нет сэмплов | **нет сэмплов** |
| `tg_parser_topicization_failed_batches_total` (raw) | нет серий (0) | **нет серий (0)** |
| логи `malformed_merge` / `failed merge chunk` (24h) | — | **0 строк** |
| `TopicizationFullRunChunkFailedSustained` alert | inactive | **inactive/ok** |

**S5 — discover / assign / coverage (t1):**

| Метрика / query | t0 | t1 |
|---|---|---|
| `sum(increase(tg_parser_topicization_reconcile_discover_docs_total[7d]))` | 0 | **нет сэмплов (0)** (proxy не «залипает») |
| `sum by (channel_id) (increase(tg_parser_topics_created_total[7d]))` | genotek 0, medportal_rfed 0 | **medportal_rfed 0** |
| `TopicizationReconcileDiscoverSustained` alert | (inactive) | **inactive/ok** |

**S5 coverage `tg_channel_processed_coverage_ratio` (регресс-стоп T1) — t0 → t1 по overlap-каналам:**

| channel_id | coverage t0 | coverage t1 | Δ |
|---|---|---|---|
| BiocodebySechenov | 1.0 | 1.0 | = |
| kdl_ru | 1.0 | 1.0 | = |
| LongevityClub | 1.0 | 1.0 | = |
| medportal_rfed | 1.0 | 1.0 | = |
| mind_rise | 1.0 | 1.0 | = |
| profendocrinologist | 1.0 | 1.0 | = |
| genotek | 0.99828 | 0.99828 | = |
| Lab4health | 0.99791 | 0.99791 | = |
| labdiagnostica_logical | 0.99754 | 0.99755 | +≈0 |
| foodf4thought | 0.99706 | 0.99706 | = |
| AgeManagment | 0.99655 | 0.99655 | = |

> ⚠️ **Gap #4-b — roster снова изменился.** На t1 вернулись 2 канала, отсутствовавшие на t0: `mediamedics` (coverage 0.99973) и `Docma_ru` (0.99290). Теперь roster = **13 каналов**. У них нет t0-значения для прямого сравнения (на t0 отсутствовали в `/metrics`); оба ≥ 0.99, регресс-стопа не образуют, но в overlap-сравнение t0→t1 не входят.

**Verdict: PASS.** `malformed_merge` = 0 sample (raw + логи + алерт inactive); coverage по **всем 11 overlap-каналам ≥ baseline** (равны с точностью округления, ни один не ниже §3.2); reconcile-discover proxy = 0 (не sustained non-zero), `TopicizationReconcileDiscoverSustained` inactive. Критерии S5+S6 §3.3 выполнены. Elapsed ≈22.5h (ниже 24–48h) — часовые тики подтверждают стабильность; рекомендуется подтверждающий read на 48h.

---

## t1. Сводка (one-look) + рекомендуемый следующий re-snapshot

| Watch | t0 → t1 (ключевое) | Elapsed | Target | Verdict |
|---|---|---|---|---|
| BUG-084 embedding | `ok/rag_query=2` без изменений; 0 rate_limited/quota_exhausted; оба алерта inactive; firing=0 | ≈22.5h | 24–48h | **PASS** |
| S3 pre-LLM dedup | pre-LLM hits по-прежнему 0; post-LLM 24h ≈12→≈932; 24h-окно теперь **billing-clean** (blocks 796→0); coverage не просел | ≈22.5h | 48–72h | **INTERIM (too-early)** |
| S5/S6 post-deploy | malformed_merge=0 sample; coverage все 11 overlap ≥ baseline; discover proxy=0; алерты inactive | ≈22.5h | 24–48h | **PASS** |

**Аномалии:** ни одной материальной. 1 transient `overloaded_error` + 21 `anthropic_network_error` за 24h (не billing-pause; `anthropic_billing_block[24h]=0`). Roster вырос до 13 каналов (Gap #4-b). Метрических gap'ов при чтении нет — все запросы вернулись; `tg_dedup_pre_llm_hits_total` по-прежнему без серии (как на t0, ожидаемо для незрелого корпуса).

**Рекомендуемый следующий re-snapshot:**
- **W2 (S3) — обязателен:** billing-clean read на **48–72h** (2026-07-17T12:22Z → 2026-07-18T12:22Z) для финального PASS/FAIL (первый чистый long-window).
- **W1 / W3 — подтверждающий:** совместный read на **48h** (2026-07-17T12:22Z); при отсутствии изменений оба закрываются как PASS.

*Снято read-only с prod (`186b60e`) 2026-07-16T10:52Z: Prometheus HTTP API `tg_parser_prometheus` (`/api/v1/query`, `/api/v1/rules`), `docker compose logs`. Значения не сфабрикованы — каждая ячейка либо live-значение с указанным окном, либо явное «нет сэмплов».*

---

# Re-snapshot t3 (2026-07-17, ~56h) — ingestion restored (Gap #6 fixed via `1fbc9b5`)

**Тип:** read-only re-snapshot трёх Phase-1 окон против t0-baseline. Единственный записанный артефакт — эта секция. Ни один сервис не запускался/останавливался; код/методология/contracts/migrations/prompts не трогались.
**Запросы:** идентичны t0/t1/t2 (Prometheus HTTP API `/api/v1/query` (+`/api/v1/query_range` для локализации billing-spike) + `/api/v1/rules` через `tg_parser_prometheus`), для сопоставимости.

> **Про t2.** Предыдущий ~48h re-snapshot (t2, 2026-07-17T~12:2XZ) зафиксирован в двух ещё **открытых** docs-PR — [#325](https://github.com/AlexEfimov/TG_parser/pull/325) и [#326](https://github.com/AlexEfimov/TG_parser/pull/326) — и в `main` (HEAD `1fbc9b5`) **не влит**, поэтому в этом файле секции t2 нет. Ключевое из t2: **W1 PASS, W3 no-regression (frozen), W2 INTERIM**, а доминирующая аномалия — **тотальный ingestion-outage** (`SessionCryptoError`: encrypted Telethon session present, но `TELEGRAM_SESSION_KEY` не задан) с 2026-07-16T19:52Z. Этот t3 читает уже **после фикса**.

## t3. Контекст снятия

```text
T3_UTC:                     2026-07-17T20:12:05Z
ELAPSED since t0:           ≈ 55h50m00s  (t0 = 2026-07-15T12:22:05Z)
PROD HEAD:                  1fbc9b5  (fix(compose): pass TELEGRAM_SESSION_KEY into tg_parser scheduler)
                            drift vs t0/t1 186b60e → t2 3b59ce9 → t3 1fbc9b5 (fix-deploy)
API_CONTAINER_STARTED_AT:   2026-07-17T12:39:08Z   (fix-deploy restart → since-restart окно ≈ 7.5h)
PROMETHEUS_STARTED_AT:      2026-07-16T13:21:03Z   (Up ≈31h)
CONTAINERS:                 tg_parser / tg_parser_bot / tg_parser_mcp — Up 8h (healthy);
                            tg_parser_prometheus Up 31h; tg_parser_postgres / grafana Up.
SCHEDULER:                  7 подряд часовых тиков после фикса (13:41Z…19:40Z), все succeeded>=6;
                            последний тик 2026-07-17T19:40:25Z (succeeded=6, degraded=7, failed=0-по-стадиям).
```

> ✅ **Gap #6 (ingestion outage) — RESOLVED via `1fbc9b5`.** `TELEGRAM_SESSION_KEY` теперь пробрасывается в контейнер `tg_parser`. За 8h после рестарта (12:39Z): **`SessionCryptoError` = 0 строк** (было 442/24h на t2). Первый восстановленный тик — 2026-07-17T13:41:29Z.
>
> ✅ **Gap #7 (coverage-gauge dark) — RESOLVED.** После фикса `tg_channel_processed_coverage_ratio` снова отдаёт live-сэмплы по всем 13 каналам (см. t3.3) — больше не «тёмный» пост-рестарта.
>
> ⚠️ **Про elapsed / post-fix accrual.** Формально прошло ≈55.8h (внутри W1 24–48h+, W2 48–72h, W3 24–48h). НО ingestion был мёртв ~18h (2026-07-16T19:52Z → 2026-07-17T~13:40Z), и «живого» пост-фикс трафика накоплено лишь **≈7.5h** (с 12:39Z). Это прямо влияет на финальность W2 (см. t3.2).

## t3.0 Ingestion health (закрытие Gap #6/#7)

Per-source outcomes последнего тика (2026-07-17T19:40Z), все 13 источников:

| Категория | Каналы | stages |
|---|---|---|
| `outcome=success` (6) | BiocodebySechenov, mind_rise, kdl_ru, profendocrinologist, medportal_rfed, LongevityClub | `ingest,process,export` OK |
| `outcome=degraded` (7) | foodf4thought, labdiagnostica_logical, genotek, mediamedics, Docma_ru, AgeManagment, Lab4health | `ingest,process,export` OK, `stages_failed=[]` |

- **`stages_failed=[]` у всех 13** — ни один источник не проваливает ingest/process/export.
- **`degraded` — benign:** per-post `MsgIdInvalidError` на сборе комментариев (`GetRepliesRequest` по несуществующим/приватным reply-тредам), 952 warning'а/8h, `event=error_collecting_comments`, level=`warning`. Это не failure канала (счётчик summary-строки `failed=7` = число degraded-источников, но по стадиям все три стадии OK).
- **0 `SessionCryptoError`** за 8h и 24h. **0 `FloodWaitError`/`ChannelPrivateError`**.
- 7 подряд часовых тиков после фикса, все succeeded>=6.

**⇒ Ingestion полностью восстановлен. Gap #6 и Gap #7 закрыты live-данными.**

## t3.1 Watch — BUG-084 embedding quota / alert soak → **PASS (можно закрывать)**

| Query | t0 | t1 | t2 (PR #325/#326) | t3 |
|---|---|---|---|---|
| `sum by (outcome,stage) (tg_embedding_requests_total)` (raw) | `ok/rag_query=2` | `ok/rag_query=2` | (per-worker) | **нет серии** (per-worker reset после 12:39Z; Gap #2) |
| `sum by (outcome) (increase(...[7d]))` | `ok≈1.005` | `ok≈1.0002` | `ok` | **`ok≈2.0003`** (единственная серия) |
| `sum by (outcome) (increase(...[24h]))` | `ok≈1.005` | `ok≈1.0002` | `ok` | **нет серии** (2 rag_query-эмбеддинга старше 24h) |
| `sum(increase(...{outcome="rate_limited"}[24h]))` | нет серии | нет серии (0) | 0 | **нет серии (0)** |
| `sum(increase(...{outcome="quota_exhausted"}[24h]))` | нет серии | нет серии (0) | 0 | **нет серии (0)** |
| `...{outcome="rate_limited"}[48h]` / `...{quota_exhausted}[48h]` | — | — | — | **нет серии (0) / нет серии (0)** |

**Алерты (`/api/v1/rules`, t3):** `EmbeddingQuotaExhausted` — **inactive/ok** (active=0), `EmbeddingRateLimitedSustained` — **inactive/ok** (active=0). Всего alerting-правил: **27** (было 26 на t0/t1 → +1 после деплоя #323; ни одно не firing/pending); **firing=0, pending=0**.

**Verdict: PASS.** За всё окно (24h/48h/7d) нет накопления `rate_limited`/`quota_exhausted` (серий нет), `outcome=ok` — единственная outcome-серия, оба алерта `inactive`. Watch не зависит от ingestion-outage. Критерий §1.3 выполнен на ≈56h → **можно закрывать**.

## t3.2 Watch — S3 pre-LLM dedup forward-watch → **INTERIM (не FINAL)**

| Метрика / query | t0 | t1 | t2 (PR) | t3 | комментарий |
|---|---|---|---|---|---|
| `sum(tg_dedup_pre_llm_hits_total)` (raw) | нет (0) | нет (0) | 0 | **нет сэмплов (0)** | нет серии |
| `sum(increase(tg_dedup_pre_llm_hits_total[8h]))` (post-fix живое окно) | — | — | — | **нет сэмплов (0)** | 7.5h живого трафика → 0 pre-LLM hits |
| `sum(increase(tg_dedup_pre_llm_hits_total[24h]))` | нет (0) | нет (0) | 0 | **нет сэмплов (0)** | 0 |
| `sum(increase(tg_dedup_pre_llm_hits_total[48h]))` | нет (0) | нет (0) | 0 | **нет сэмплов (0)** | 0 |
| `sum(increase(tg_dedup_pre_llm_hits_total[7d]))` | 0 | 0 | 0 | **нет сэмплов (0)** | по-прежнему 0 |
| `sum(increase(tg_dedup_duplicates_detected_total[24h]))` (post-LLM) | ≈12 | ≈932 | — | **≈156.1** | пост-LLM дедуп активен |
| `sum(increase(tg_dedup_duplicates_detected_total[7d]))` | ≈5258 | ≈5411 | — | **≈4288.1** | 7d-окно частично захватывает outage-период |
| `sum by (model,status) (increase(tg_parser_llm_requests_total[1h]))` | haiku ok≈74/err0 | haiku ok≈41/err0 | — | **haiku ok≈26.1 / err 0; sonnet ok 0** | чисто |
| `sum by (model,status) (increase(tg_parser_llm_requests_total[8h]))` | — | — | — | **haiku ok≈192.1 / err 0; sonnet ok≈8.0 / err 0** | пост-фикс окно чисто |
| `sum by (model,status) (increase(tg_parser_llm_requests_total[24h]))` | haiku ok≈23/err≈680 | haiku ok≈977/err≈1 | — | **haiku ok≈192.1 / err 0; sonnet ok≈8.0 / err 0** | **error=0** |
| `sum by (model,status) (increase(tg_parser_llm_requests_total[7d]))` | haiku ok≈5398/err≈1160 | haiku ok≈5572/err≈996 | — | **haiku ok≈4482 / err≈1021; sonnet ok≈51 / err≈11** | 7d-err — исторический |
| `sum(increase(tg_parser_anthropic_billing_block_total[1h]))` | нет (0) | нет (0) | — | **нет сэмплов (0)** | чисто |
| `sum(increase(tg_parser_anthropic_billing_block_total[8h]))` | — | — | — | **нет сэмплов (0)** | чисто |
| `sum(increase(tg_parser_anthropic_billing_block_total[24h]))` | ≈796 | 0 | — | **нет сэмплов (0)** | **24h billing-clean** |
| `sum(increase(tg_parser_anthropic_billing_block_total[48h]))` | — | — | ≈28.65 | **≈28.65** | локализован в час 2026-07-16T~19:00Z (query_range) — старый deploy-spike |
| `sum(increase(tg_parser_anthropic_billing_block_total[7d]))` | ≈1355 | ≈1168 | — | **≈1201.1** | исторический эпизод тает |

**Billing-clean статус:** trailing-окна **[1h]/[8h]/[24h] billing-clean** (`anthropic_billing_block=0` и haiku `error=0`). Но **[48h] НЕ billing-clean**: содержит один старый spike **≈28.65 blocks в час 2026-07-16T~19:00Z** (локализован через `query_range`, ~25h назад, совпадает с deploy-#323-часом). Полный 48h billing-clean trailing-read станет возможен только когда этот spike выйдет из окна (~2026-07-18T19:00Z+).

**Verdict: INTERIM (не FINAL).** Причины, почему W2 **нельзя** объявить FINAL из live-данных:
1. **pre-LLM hits всё ещё 0** во всех окнах, включая пост-фикс `[8h]`. Это зафиксированный статус `S3 effect: PARTIAL` / NEUTRAL по §2.3 — **не провал**, но и **не** выполнение PASS-критерия «`pre_llm_hits[48h] > 0`».
2. **Недостаточно пост-фикс accrual:** живого ingestion лишь ≈7.5h (фикс 12:39Z); корпус `raw_content_hash` после ~18h простоя ещё не «созрел», чтобы дать pre-LLM попадания.
3. **48h-окно ещё не billing-clean** (spike ≈28.65 из 2026-07-16T~19:00Z в trailing 48h) — PASS-критерий §2.3 задан именно на `[48h]` в billing-clean окне.

**Не FAIL:** coverage не просел (t3.3), регресс-стопа T1 нет; billing-clean на 24h. **Earliest valid W2 FINAL:** после того как ingestion отработает полный **48h billing-clean** интервал — не раньше ~**2026-07-18T19:00Z**, практически **2026-07-19** read.

## t3.3 Watch — S5/S6 post-deploy metric-watch → **PASS (no-regression), сигнал снова LIVE**

**S6 — malformed_merge / failed batches (t3):**

| Метрика / query | t0 | t1 | t3 |
|---|---|---|---|
| `tg_parser_topicization_full_run_chunk_failed_total` (raw) | нет серий | нет серий | **нет серий** |
| `...{reason="malformed_merge"}` (raw) | 0 sample | 0 sample | **0 sample** |
| `sum(increase(...{reason="malformed_merge"}[7d]))` | нет | нет | **нет сэмплов** |
| `tg_parser_topicization_failed_batches_total` (raw) | нет серий | нет серий | **нет серий** |
| `TopicizationFullRunChunkFailedSustained` | inactive | inactive | **inactive/ok** |

**S5 — discover / coverage (t3):**

| Метрика / query | t0 | t1 | t3 |
|---|---|---|---|
| `sum(increase(tg_parser_topicization_reconcile_discover_docs_total[7d]))` | 0 | 0 | **нет сэмплов (0)** |
| `...[2h]` (не «залипает») | — | — | **нет сэмплов (0)** |
| `sum by (channel_id) (increase(tg_parser_topics_created_total[7d]))` | genotek/medportal 0 | medportal 0 | **нет сэмплов (0)** |
| `TopicizationReconcileDiscoverSustained` | inactive | inactive/ok | **inactive/ok** |

**S5 coverage `tg_channel_processed_coverage_ratio` (регресс-стоп T1) — t0 → t3:**

| channel_id | coverage t0 | coverage t3 | Δ vs baseline |
|---|---|---|---|
| BiocodebySechenov | 1.0 | 1.0 | = |
| kdl_ru | 1.0 | 1.0 | = |
| LongevityClub | 1.0 | 1.0 | = |
| medportal_rfed | 1.0 | 1.0 | = |
| mind_rise | 1.0 | 1.0 | = |
| profendocrinologist | 1.0 | 1.0 | = |
| genotek | 0.99828 | 0.99828 | = |
| Lab4health | 0.99791 | **0.99843** | ↑ ≥ baseline |
| labdiagnostica_logical | 0.99754 | 0.99755 | +≈0 |
| foodf4thought | 0.99706 | 0.99706 | = |
| AgeManagment | 0.99655 | 0.99655 | = |
| mediamedics | (нет t0) 0.99973@t1 | **0.99982** | ↑ (roster-13) |
| Docma_ru | (нет t0) 0.99290@t1 | **0.99660** | ↑ (roster-13) |

**Verdict: PASS (no-regression).** `malformed_merge` = 0 sample (raw + алерт inactive); coverage по **всем 13 каналам ≥ baseline** (Lab4health и Docma_ru даже подросли); reconcile-discover proxy = 0 (не sustained), `TopicizationReconcileDiscoverSustained` inactive. Критерии §3.3 выполнены. В отличие от t2 (сигнал был *frozen* из-за outage), на t3 сигнал снова **LIVE** — coverage-gauge отдаёт свежие сэмплы (Gap #7 закрыт), тики идут.

---

## t3. Сводка (one-look)

| Watch | t2 → t3 (ключевое) | Elapsed | Target | Verdict |
|---|---|---|---|---|
| W1 BUG-084 embedding | 0 rate_limited/quota_exhausted (24h/48h/7d); оба алерта inactive; firing=0; `ok`-only | ≈55.8h | 24–48h+ | **PASS (закрывать)** |
| W2 S3 pre-LLM dedup | pre-LLM hits по-прежнему 0 (вкл. пост-фикс 8h); 24h billing-clean, но 48h ещё содержит старый spike ≈28.65; лишь ≈7.5h живого трафика | ≈55.8h (но ~7.5h живого) | 48–72h billing-clean | **INTERIM (не FINAL)** |
| W3 S5/S6 post-deploy | malformed_merge=0; coverage все 13 ≥ baseline (LIVE, не frozen); discover proxy=0; алерты inactive | ≈55.8h | 24–48h | **PASS (no-regression)** |

**Ingestion health:** ✅ восстановлен — 13/13 источников `ingest,process,export` OK, 0 `SessionCryptoError`, 7 подряд тиков succeeded>=6 (Gap #6 закрыт via `1fbc9b5`); coverage-gauge снова live (Gap #7 закрыт).

**Аномалии:** benign per-post `MsgIdInvalidError` на сборе комментариев (degraded, не failure). Старый billing-spike ≈28.65 в 2026-07-16T~19:00Z (deploy-#323-час) — уже вне 24h-окна, тает из 48h.

**Рекомендуемый следующий re-snapshot (W2 FINAL):** после полного **48h billing-clean** окна на восстановленном ingestion — не раньше ~**2026-07-18T19:00Z**, практически **2026-07-19**. W1/W3 можно закрывать как PASS. **Automation остаётся ENABLED** до FINAL-вердикта W2.

*Снято read-only с prod (`1fbc9b5`) 2026-07-17T20:12Z: Prometheus HTTP API `tg_parser_prometheus` (`/api/v1/query`, `/api/v1/query_range`, `/api/v1/rules`), `docker compose logs`. Значения не сфабрикованы — каждая ячейка либо live-значение с указанным окном, либо явное «нет сэмплов».*
