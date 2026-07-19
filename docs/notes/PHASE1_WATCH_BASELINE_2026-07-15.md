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

# Re-snapshot t2 (2026-07-19)

**Тип:** read-only re-snapshot трёх Phase-1 окон против t0-baseline и t1. Единственный записанный артефакт — эта секция. Ни один сервис не запускался/останавливался.
**Запросы:** идентичны t0/t1 (Prometheus HTTP API `/api/v1/query` + `/api/v1/rules` через `tg_parser_prometheus`, `docker compose logs`), для сопоставимости.
**Назначение:** это целевой **48–72h billing-clean read** для W2/S3 (первый long-window read полностью в чистых billing-условиях). W1/W3 — подтверждающий (elapsed далеко за их целевыми окнами).

## t2. Контекст снятия

```text
T2_UTC:                     2026-07-19T13:01:05Z
ELAPSED since t0:           ≈ 96h39m00s  (t0 = 2026-07-15T12:22:05Z; ≈4d 0h 39m — за пределами всех целевых окон)
ELAPSED since t1:           ≈ 74h08m29s  (t1 = 2026-07-16T10:52:36Z)
PROD HEAD:                  1fbc9b5  (drift от t0 `186b60e` — см. Gap #5 ниже)
CONTAINERS:                 tg_parser / tg_parser_bot / tg_parser_mcp — Up 2 days (healthy);
                            tg_parser_prometheus Up 3 days; tg_parser_postgres / grafana Up.
SCHEDULER:                  24× "Incremental pipeline completed" за 24h (часовой тик работает);
                            последний тик 2026-07-19T12:40:23Z (succeeded=6, failed=7, degraded=7, duration=64.58s).
```

> ⚠️ **Gap #5 — HEAD drift (t0 `186b60e` → t2 `1fbc9b5`).** С t0 в `main` влились PR #317/#318/#319/#320/#321/#323 + cloud-bootstrap-коммиты (`dd85ed4`, `1fbc9b5`). Проверено `git diff 186b60e..HEAD`: изменения по watched-метрикам **аддитивные и не затрагивают W1/W2/W3**. `docker/prometheus/alerts.yml` — только +1 новый алерт `PromptInjectionSuspectSustained` (F9 Phase 2, severity=info, `tg_parser_prompt_injection_suspect_total`); `tg_parser/api/metrics.py` — только +новый counter `PROMPT_INJECTION_SUSPECT_TOTAL`. Метрики embedding/dedup/topicization/coverage и их алерты **идентичны** t0. Поэтому число alerting-правил выросло 26 → **27** (все inactive), baseline для трёх watch остаётся валиден. Единственное изменение кода в watched-путях — `prompts/topicization.yaml` (не метрика). Baseline валиден.

---

## t2.1 Watch — BUG-084 embedding quota / alert soak → **PASS (final / confirmatory)**

| Query | t0 | t1 | t2 |
|---|---|---|---|
| `sum by (outcome,stage) (tg_embedding_requests_total)` (raw) | `ok/rag_query = 2` | `ok/rag_query = 2` | **нет серии** (stale — нет rag_query за ≥24h, см. ниже) |
| `sum by (outcome) (increase(tg_embedding_requests_total[24h]))` | `ok ≈ 1.005` | `ok ≈ 1.0002` | **нет серии (0)** — no accrual в 24h |
| `sum by (outcome) (increase(tg_embedding_requests_total[7d]))` | `ok ≈ 1.005` | `ok ≈ 1.0002` | **`ok ≈ 2.0003`** (только `ok`) |
| `sum(increase(tg_embedding_requests_total{outcome="rate_limited"}[24h]))` | нет серии | нет серии (0) | **нет серии (0)** |
| `sum(increase(tg_embedding_requests_total{outcome="quota_exhausted"}[24h]))` | нет серии | нет серии (0) | **нет серии (0)** |

**Алерты (`/api/v1/rules`, t2):** `EmbeddingQuotaExhausted` — **inactive/ok** (active=0), `EmbeddingRateLimitedSustained` — **inactive/ok** (active=0). Всего alerting-правил: **27** (26 + новый F9-алерт); firing: **0**, pending: **0**.

> ℹ️ **Нюанс — raw-серия ушла в stale.** На t2 `tg_embedding_requests_total` не возвращает raw-серию, но `increase(...[7d])` = `ok≈2.0`. Причина: module-level `Counter` регистрирует серию только после первого `.inc()`; с последнего рестарта API (Up ~2 дня) не было ни одного `rag_query`-embedding-вызова → серия отсутствует в свежих scrape'ах, а 7d-окно ещё захватывает до-рестартовые сэмплы. Это **не деградация**: важен факт **нулевого accrual failure-outcome** (rate_limited/quota_exhausted серий нет ни в одном окне) и inactive-алерты.

**Verdict: PASS (final).** С t0 нет накопления `rate_limited`/`quota_exhausted` (серии по-прежнему отсутствуют во всех окнах), `outcome=ok` — единственная серия, оба алерта остаются `inactive`. Критерий §1.3 выполнен. Elapsed ≈96.6h — далеко за целевым окном 24–48h → soak-watch **завершён, closeable**.

## t2.2 Watch — S3 pre-LLM dedup forward-watch → **FINAL: PASS (no-regress) / S3 effect = PARTIAL (dormant)**

| Метрика / query | t0 (07-15) | t1 (07-16) | t2 (07-19) | Δ / комментарий |
|---|---|---|---|---|
| `sum(tg_dedup_pre_llm_hits_total)` (raw) | нет сэмплов (0) | нет сэмплов (0) | **нет сэмплов (0)** | без изменений |
| `sum(increase(tg_dedup_pre_llm_hits_total[24h]))` | нет сэмплов (0) | нет сэмплов (0) | **нет сэмплов (0)** | 0 |
| `sum(increase(tg_dedup_pre_llm_hits_total[48h]))` | нет сэмплов (0) | нет сэмплов (0) | **нет сэмплов (0)** | 0 — в billing-clean 48h окне |
| `sum(increase(tg_dedup_pre_llm_hits_total[7d]))` | 0 | 0 | **нет серии (0)** | по-прежнему 0 |
| `sum(increase(tg_dedup_duplicates_detected_total[24h]))` (post-LLM) | ≈12.0 | ≈932.1 | **≈600.1** | post-LLM дедуп активен |
| `sum(increase(tg_dedup_duplicates_detected_total[7d]))` | ≈5258 | ≈5411 | **≈3753.1** | 7d-окно сдвинулось (t0-эпизод вышел) |
| `sum by (model,status) (increase(tg_parser_llm_requests_total[24h]))` | haiku ok≈23/err≈680; sonnet ok≈5/err≈11 | haiku ok≈977/err≈1; sonnet ok≈20/err0 | **haiku ok≈608 / err нет серии; sonnet ok≈27 / err нет серии** | 24h полностью чист (0 error-серий) |
| `sum by (model,status) (increase(tg_parser_llm_requests_total[48h]))` | — | — | **haiku ok≈1242 / err нет серии; sonnet ok≈39 / err нет серии** | **48h billing-clean** (0 error-серий) |
| `sum by (model,status) (increase(tg_parser_llm_requests_total[7d]))` | haiku ok≈5398/err≈1160 | haiku ok≈5572/err≈996 | **haiku ok≈3911/err≈1021; sonnet ok≈67/err≈11** | 7d-error — исторический эпизод, вне 48h |
| `sum by (model,status) (increase(tg_parser_llm_requests_total[1h]))` | haiku ok≈74/err0 | haiku ok≈41/err0 | **haiku ok≈25/err0** | чисто |
| `sum(increase(tg_parser_anthropic_billing_block_total[24h]))` | ≈796 | 0 | **нет серии (0)** | billing-clean |
| `sum(increase(tg_parser_anthropic_billing_block_total[48h]))` | — | — | **нет серии (0)** | **48h billing-clean** |
| `sum(increase(tg_parser_anthropic_billing_block_total[7d]))` | ≈1355 | ≈1168 | **≈1201** | исторический эпизод в trailing-7d |
| `sum(increase(tg_parser_anthropic_billing_block_total[1h]))` | 0 | 0 | **нет серии (0)** | чисто |

**Billing-clean статус (trailing-окна на t2):** окна **[24h] И [48h]** на t2 **полностью billing-clean** — `anthropic_billing_block[24h]=0`, `[48h]=0`, `[1h]=0`; `tg_parser_llm_requests_total` за 24h и 48h содержит **только `status=success`** (haiku + sonnet), error-серий нет вовсе. Логи за 48h: `malformed_merge`/`failed merge chunk` = **0**; grep `insufficient_quota|billing_block|overloaded_error` = 186 строк — **все 186** benign `parallel_batch_complete` (billing-статус поле события), 0 network_error, 0 `overloaded_error`, 0 реального billing-pause. `SessionCryptoError` за 72h = **0**. `AnthropicBillingStillBlocked` alert — **inactive/ok**. Все тики за 24h — `succeeded=6` (0 outage-тиков `succeeded=0`).

> ⚠️ **Gap #6 — окно НЕ было непрерывно чистым «с t0»; отсчёт чистого live-окна ведётся от recovery.** Между t0 и t2 период был прерван: (1) **исторический Anthropic-billing-эпизод ~07-16** (виден как `billing_block[7d]≈1201` и `haiku error[7d]≈1021`, но **вне** trailing-[48h]) и (2) **ingestion-outage 2026-07-16T19:52Z → 2026-07-17T13:41Z** (не передавался `TELEGRAM_SESSION_KEY` → session-crypto ошибки, тики `succeeded=0`), устранённый рестартом контейнера **2026-07-17T12:39:08Z** (подтверждено `docker inspect StartedAt`; первый здоровый тик ≈07-17T13:41Z — по документированному инциденту прошлого прогона; сырые логи до 07-18T11:16Z ротировались). Поэтому чистое **healthy + billing-clean live-traffic окно отсчитывается от recovery ≈07-17T13:41Z** → на t2 это **≈47h20m** (≈48h22m от рестарта). Это **на нижней границе** целевого 48–72h. trailing-метрика `[48h]` при этом полностью чистая и покрывает практически весь post-recovery период.

**Verdict: FINAL — PASS (no-regression) / S3 effect = PARTIAL (dormant).**
Финализация обоснована совокупно (не только по одному счётчику окна):
- **Elapsed since t0 ≈96.6h** — далеко за верхней границей 72h.
- **Получен полный ~48h healthy + billing-clean live-traffic window** (от recovery 07-17T13:41Z; trailing-`[48h]` метрика verifiably чистая: `billing_block[48h]=0`, 0 LLM-error-серий, 0 `SessionCryptoError`, все тики `succeeded=6`). Окно на нижней границе 48–72h (Gap #6), но покрывает практически весь post-recovery живой трафик.
- **Регресс-стоп T1 PASSED:** coverage по **всем 11 overlap-каналам ≥ baseline** (§t2.3, три ↑) → дедуп ничего лишнего не режет.
- **Механизм-maturity (§2.3 PASS `pre-LLM hits>0`) НЕ достигнут:** `tg_dedup_pre_llm_hits_total` = **0** во всех окнах (24h/48h/7d) даже в чистом long-window. Подтверждает ранее зафиксированный **`S3 effect: PARTIAL`** — pre-LLM raw-hash-путь остаётся dormant (живой трафик не даёт точных raw-hash-мирроров в объёме; экзакт-дубликаты ловятся post-LLM `duplicates_detected`). Это **NEUTRAL по §2.3, не FAIL**.
**Заключение:** механизм структурно dormant на протяжении полного чистого 48h live-window **и** всех 7d — ожидание до 72h верхней границы не изменит structurally-dormant счётчик. Watch достиг терминального состояния (long-window billing-clean read получен, регресса нет) → **закрывается FINAL**.

## t2.3 Watch — S5/S6 post-deploy metric-watch → **PASS (final / confirmatory)**

**S6 — malformed_merge / failed batches (t2):**

| Метрика / query | t0 | t1 | t2 |
|---|---|---|---|
| `tg_parser_topicization_full_run_chunk_failed_total` (raw, все reasons) | нет серий | нет серий | **нет серий** |
| `...{reason="malformed_merge"}` (raw) | 0 sample | 0 sample | **нет серии (0)** |
| `sum(increase(...{reason="malformed_merge"}[7d]))` | нет сэмплов | нет сэмплов | **нет сэмплов** |
| `tg_parser_topicization_failed_batches_total` (raw) | нет серий (0) | нет серий (0) | **нет серий (0)** |
| логи `malformed_merge` / `failed merge chunk` (48h) | — | 0 строк (24h) | **0 строк** |
| `TopicizationFullRunChunkFailedSustained` alert | inactive | inactive/ok | **inactive/ok** |

**S5 — discover / assign / coverage (t2):**

| Метрика / query | t0 | t1 | t2 |
|---|---|---|---|
| `sum(increase(tg_parser_topicization_reconcile_discover_docs_total[7d]))` | 0 | нет сэмплов (0) | **нет сэмплов (0)** (proxy не «залипает») |
| `sum by (channel_id) (increase(tg_parser_topics_created_total[7d]))` | genotek 0, medportal_rfed 0 | medportal_rfed 0 | **нет серий (0)** |
| `TopicizationReconcileDiscoverSustained` alert | (inactive) | inactive/ok | **inactive/ok** |

**S5 coverage `tg_channel_processed_coverage_ratio` (регресс-стоп T1) — t0 → t2 по overlap-каналам:**

| channel_id | coverage t0 | coverage t2 | Δ vs baseline |
|---|---|---|---|
| BiocodebySechenov | 1.0 | 1.0 | = ✓ |
| kdl_ru | 1.0 | 1.0 | = ✓ |
| LongevityClub | 1.0 | 1.0 | = ✓ |
| medportal_rfed | 1.0 | 1.0 | = ✓ |
| mind_rise | 1.0 | 1.0 | = ✓ |
| profendocrinologist | 1.0 | 1.0 | = ✓ |
| genotek | 0.99828 | 0.99828 | = ✓ |
| Lab4health | 0.99791 | 0.99843 | +≈0.0005 ✓ |
| labdiagnostica_logical | 0.99754 | 0.99755 | +≈0 ✓ |
| foodf4thought | 0.99706 | 0.99706 | = ✓ |
| AgeManagment | 0.99655 | 0.99658 | +≈0 ✓ |

> ⚠️ **Gap #4-c — roster = 13 каналов.** На t2 присутствуют оба «плавающих» канала: `mediamedics` (0.99982) и `Docma_ru` (0.99691). Оба ≥ 0.99, регресс-стопа не образуют; в overlap-сравнение t0→t2 (11 каналов) не входят (нет t0-значения).

**Verdict: PASS (final).** `malformed_merge` = 0 (raw + логи 48h + алерт inactive); coverage по **всем 11 overlap-каналам ≥ baseline** (ни один не ниже §3.2, три канала ↑); reconcile-discover proxy = 0 (не sustained), `TopicizationReconcileDiscoverSustained` inactive. Критерии S5+S6 §3.3 выполнены. Elapsed ≈96.6h — далеко за 24–48h → watch **завершён, closeable**.

---

## t2. Сводка (one-look) + рекомендуемое действие

| Watch | t0 → t1 → t2 (ключевое) | Elapsed | Target | Verdict |
|---|---|---|---|---|
| BUG-084 embedding | 0 rate_limited/quota_exhausted во всех окнах; raw-серия stale (нет rag_query, no accrual); оба алерта inactive; firing=0 | ≈96.6h | 24–48h | **PASS (final)** |
| S3 pre-LLM dedup | pre-LLM hits по-прежнему **0** в чистом 48h long-window; post-LLM активен; **[24h]+[48h] billing-clean** (0 error-серий, blocks=0, 0 SessionCryptoError); чистое live-окно ≈47-48h от recovery (Gap #6); coverage не просел | ≈96.6h (≈48h от recovery) | 48–72h (billing-clean) | **FINAL — PASS (no-regress) / S3 effect PARTIAL (dormant)** |
| S5/S6 post-deploy | malformed_merge=0; coverage все 11 overlap ≥ baseline (3 ↑); discover proxy=0; алерты inactive | ≈96.6h | 24–48h | **PASS (final)** |

**Аномалии:** ни одной активной/материальной на t2. Новых `rate_limited`/`quota_exhausted` нет; ни один алерт не firing/pending (27 правил, все inactive); coverage-регресса нет; `malformed_merge`=0; `SessionCryptoError` за 72h = 0 (ingestion-outage полностью резолвнут, Gap #6). Историческое (вне trailing-[48h]): billing-эпизод ~07-16 (`billing_block[7d]≈1201`) и session-outage 07-16→07-17 — оба уже resolved. HEAD-drift `186b60e→1fbc9b5` аддитивен и не затрагивает watched-пути (Gap #5). Roster = 13 каналов (Gap #4-c). Метрических gap'ов при чтении нет.

**Рекомендуемое действие:**
- **W2 (S3) достиг FINAL:** elapsed ≈96.6h (за 72h), получен полный ~48h healthy + billing-clean live-traffic window от recovery (07-17T13:41Z; trailing-[24h]+[48h] verifiably чистые), coverage не просел, механизм стабильно dormant (`S3 effect: PARTIAL` подтверждён на 48h+7d). Окно на нижней границе 48–72h (Gap #6), но structurally-dormant счётчик не изменится к 72h. **Цель этой automation выполнена → automation можно ОТКЛЮЧИТЬ (DISABLE).**
- **W1 / W3** также закрыты как **PASS (final)** — elapsed далеко за их окнами, дальнейшие read'ы сигнала не добавят.
- Постоянный мониторинг регрессий обеспечивают Prometheus-алерты (`EmbeddingQuotaExhausted`, `EmbeddingRateLimitedSustained`, `AnthropicBillingStillBlocked`, `TopicizationFullRunChunkFailedSustained`, `TopicizationReconcileDiscoverSustained`) — отдельная ежедневная re-snapshot automation больше не нужна.

*Снято read-only с prod (`1fbc9b5`) 2026-07-19T13:01Z: Prometheus HTTP API `tg_parser_prometheus` (`/api/v1/query`, `/api/v1/rules`), `docker compose logs`. Значения не сфабрикованы — каждая ячейка либо live-значение с указанным окном, либо явное «нет сэмплов».*
