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

# Re-snapshot t2 (2026-07-17)

**Тип:** read-only re-snapshot трёх Phase-1 окон против t0-baseline и t1 (выше). Единственный записанный артефакт — эта секция. Ни один сервис не запускался/останавливался/менялся.
**Запросы:** идентичны t0/t1 (Prometheus HTTP API `/api/v1/query` + `/api/v1/rules` через `tg_parser_prometheus`), для сопоставимости.

## t2. Контекст снятия

```text
T2_UTC:                     2026-07-17T12:25Z   (запросы выполнены 12:21–12:25Z)
ELAPSED since t0:           ≈ 48h03m  (t0 = 2026-07-15T12:22:05Z)
PROD HEAD:                  3b59ce9  (Merge PR #313→#323; факт HEAD = «Merge PR #323 feat/f9-phase3-full-hardening»)
CONTAINERS:                 tg_parser / tg_parser_bot / tg_parser_mcp — Up 17h (healthy), рестарт 2026-07-16T18:51:59Z;
                            tg_parser_prometheus Up 23h (13:21:02Z); tg_parser_postgres / grafana Up 2 недели.
SCHEDULER:                  часовой тик работает, НО с 2026-07-16T19:52Z каждый тик = succeeded=0, failed=13
                            (все 13 каналов падают на ingestion — см. Аномалию A1 ниже). Последний тик 11:52:17Z.
```

> ⚠️ **Gap #6 — HEAD drift (крупный, функциональный).** На t0/t1 prod HEAD = `186b60e`. На t2 prod HEAD = **`3b59ce9`** («Merge PR #323 `feat/f9-phase3-full-hardening`»). В отличие от docs-only дрейфа на t0 (Gap #1), это **функциональный деплой** (F9 phase-3 hardening, включая шифрование Telethon-сессии). Рестарт контейнеров 2026-07-16T18:51:59Z = момент выката. Alerting-правил стало **27** (было 26 на t0/t1) — одно новое правило из блока #323.
>
> ⚠️ **Gap #7 — per-worker флаппинг gauge/counter (расширение Gap #2).** На t2 instant-запросы `tg_channel_processed_coverage_ratio`, `tg_embedding_requests_total` (raw) и др. периодически возвращают `NO_SERIES` — попадание скрейпа на воркер без серии. Значения восстановлены через `last_over_time(...[24h/48h])` (Prometheus = источник истины). Свежесть подтверждена: последний coverage-сэмпл 2026-07-17T12:24:36Z (≈ now).

---

## 🔴 Аномалия A1 (доминирующая) — ingestion полностью упал после деплоя #323

**С 2026-07-16T19:52:18Z** (первый тик после рестарта 18:51:59Z) **каждый** часовой тик = `succeeded=0, failed=13, duration≈1s`. Все 13 каналов падают на стадии `[1/4] Ingestion`:

```text
SessionCryptoError: Encrypted Telethon session found at /app/sessions/tg_parser_session.session.enc
but TELEGRAM_SESSION_KEY is not set. Set the Fernet key to unseal, or restore a plaintext .session
for break-glass recovery.
```

| Признак | t2 |
|---|---|
| Первый упавший тик | 2026-07-16T19:52:18Z (совпадает с деплоем #323) |
| Часовые тики после | все `succeeded=0 / failed=13` (17 тиков подряд, 19:52→11:52Z) |
| `SessionCryptoError` в логах за 24h | **442** |
| `TELEGRAM_SESSION_KEY` в env контейнера `tg_parser` | **NOT_SET** |
| Файл сессии | `/app/sessions/tg_parser_session.session.enc` присутствует (создан 2026-07-16 19:18), но нет Fernet-ключа для распечатывания |
| Алерты firing | **0** — тотальный ingestion-outage **не алертится** (observability-gap) |

**Root cause (гипотеза, read-only):** блок F9 phase-3 (#323) включил шифрование Telethon-сессии; при выкате была создана `.session.enc`, но переменная `TELEGRAM_SESSION_KEY` (Fernet) на prod **не выставлена** → сессию нельзя распечатать → ingestion не подключается к Telegram. Новые сообщения не поступают ни по одному каналу с ~19:52Z 2026-07-16 (**≈16.5h простоя на момент t2**).

> Это **вне scope данного read-only снапшота** (правка только этого документа), НО материально влияет на интерпретацию W2/W3: forward-watch'и не могут накапливать живой трафик, пока ingestion лежит. Вынесено как приоритетное next-action (см. §t2.4).

---

## t2.1 Watch — BUG-084 embedding quota / alert soak → **PASS**

| Query | t0 | t1 | t2 |
|---|---|---|---|
| `sum by (outcome,stage) (tg_embedding_requests_total)` (raw) | `ok/rag_query=2` | `ok/rag_query=2` | **NO_SERIES** (per-worker флаппинг, Gap #7; increase ниже подтверждает только `ok`) |
| `sum by (outcome) (increase(tg_embedding_requests_total[24h]))` | `ok≈1.005` | `ok≈1.0002` | **`ok=0`** (no-op, только `ok`) |
| `sum by (outcome) (increase(tg_embedding_requests_total[7d]))` | `ok≈1.005` | `ok≈1.0002` | **`ok≈2.0003`** (только `ok`) |
| `sum(increase(tg_embedding_requests_total{outcome="rate_limited"}[24h]))` | нет серии | нет серии (0) | **нет серии (0)** |
| `sum(increase(tg_embedding_requests_total{outcome="quota_exhausted"}[24h]))` | нет серии | нет серии (0) | **нет серии (0)** |
| то же `[48h]` (rate_limited / quota_exhausted) | — | — | **нет серии (0) / нет серии (0)** |

**Алерты (`/api/v1/rules`, t2):** `EmbeddingQuotaExhausted` — **inactive/ok** (active=0), `EmbeddingRateLimitedSustained` — **inactive/ok** (active=0). Всего alerting-правил: **27**; firing: **0**.

**Verdict: PASS.** За окно [24h] и [48h] нет накопления `rate_limited`/`quota_exhausted` (серии отсутствуют), `outcome=ok` — единственный outcome, оба алерта `inactive`. Критерий §1.3 выполнен на elapsed ≈48h (в пределах/за целевым 24–48h). Embedding-путь (`rag_query`) **не зависит** от ingestion-аномалии A1, поэтому вердикт устойчив. **W1 можно закрывать.**

## t2.2 Watch — S3 pre-LLM dedup forward-watch → **INTERIM (не финал: billing-confounded + ingestion down)**

| Метрика / query | t0 | t1 | t2 | Δ / комментарий |
|---|---|---|---|---|
| `sum(tg_dedup_pre_llm_hits_total)` (raw) | нет сэмплов (0) | нет сэмплов (0) | **NO_SERIES** | серии нет и в `last_over_time[7d]` |
| `sum(increase(tg_dedup_pre_llm_hits_total[24h]))` | 0 | 0 | **NO_SERIES (0)** | 0 |
| `sum(increase(tg_dedup_pre_llm_hits_total[48h]))` | 0 | 0 | **NO_SERIES (0)** | 0 |
| `sum(increase(tg_dedup_pre_llm_hits_total[7d]))` | 0 | 0 | **NO_SERIES (0)** | по-прежнему 0 |
| `sum(increase(tg_dedup_duplicates_detected_total[24h]))` (post-LLM) | ≈12.0 | ≈932.1 | **≈147.15** | ↓ vs t1 (24h-окно теперь на 2/3 покрывает post-outage простой) |
| `sum(increase(tg_dedup_duplicates_detected_total[48h]))` | — | — | **≈1082.18** | — |
| `sum(increase(tg_dedup_duplicates_detected_total[7d]))` | ≈5258 | ≈5411 | **≈4457.15** | 7d-окно «съедает» ранние высокие сутки |
| `sum by (model,status) (increase(tg_parser_llm_requests_total[1h]))` | haiku ok≈74/err0 | haiku ok≈41/err0 | **только sonnet ok=0; haiku отсутствует** | LLM-трафика в последний 1h нет (ingestion down) |
| `sum by (model,status) (increase(tg_parser_llm_requests_total[24h]))` | haiku ok≈23/err≈680 | haiku ok≈977/err≈1 | **haiku ok≈165 / err≈23.5; sonnet ok≈1.0** | почти весь трафик — из pre-outage хвоста |
| `sum by (model,status) (increase(tg_parser_llm_requests_total[48h]))` | — | — | **haiku ok≈1163 / err≈25.0; sonnet ok≈17.0** | — |
| `sum by (model,status) (increase(tg_parser_llm_requests_total[7d]))` | haiku ok≈5398/err≈1160 | haiku ok≈5572/err≈996 | **haiku ok≈4615 / err≈1021; sonnet ok≈46 / err≈11** | — |
| `sum(increase(tg_parser_anthropic_billing_block_total[1h]))` | 0 | 0 | **NO_SERIES (0)** | чисто сейчас |
| `sum(increase(tg_parser_anthropic_billing_block_total[24h]))` | ≈796 | **0** | **≈28.65** | ⚠️ снова НЕ ноль |
| `sum(increase(tg_parser_anthropic_billing_block_total[48h]))` | — | — | **≈28.65** | = 24h → эпизод целиком в последних 24h |
| `sum(increase(tg_parser_anthropic_billing_block_total[12h] / [17h]))` | — | — | **0 / 0** | эпизод локализован в 17–24h назад |
| `sum(increase(tg_parser_anthropic_billing_block_total[7d]))` | ≈1355 | ≈1168 | **≈1201.14** | — |
| `sum(rate(tg_parser_anthropic_billing_block_total[10m]))` | 0 | 0 | **0** | сейчас блокировок нет |

**Billing-статус:** окно [24h/48h] на t2 **НЕ billing-clean** — свежий эпизод ≈**28.65** blocks + haiku `error≈23.5` за 24h. Локализация: `[12h]=0`, `[17h]=0`, `[24h]≈28.65` → эпизод произошёл **17–24h назад** (≈2026-07-16 12:24–19:24Z), т.е. **до** рестарта 18:51Z. Последние ≈17h (since-restart) — по метрике чисты (`[1h]=0`, `rate[10m]=0`, `AnthropicBillingStillBlocked` inactive), но это <48h и совпадает с ingestion-outage (трафика почти нет). В логах за 24h: 0 строк `malformed`/`failed merge chunk`; 0 строк по grep `billing|insufficient_quota|overloaded|rate_limit` (эпизод либо на краю 24h-буфера, либо ротация json-логов — метрика фиксирует ≈28.65, лог-строки не сохранились; текущее состояние чисто).

**Verdict: INTERIM (не финал).** Хотя elapsed ≈48h формально попадает в окно 48–72h, **ни одно** из условий финального PASS не выполнимо на этом чтении:
1. **Окно НЕ billing-clean** (свежий эпизод ≈28.65 blocks / haiku err≈23.5 в trailing-24h) → сравнение confounded, как и на t0 (Gap #3). Условие «billing-clean since t0» из задачи **не выполнено** (были эпизоды и на t0 ≈796, и свежий).
2. **Ingestion лежит с ≈19:52Z 07-16** (Аномалия A1) → forward-watch физически **не может** накапливать pre-LLM hits: новых сообщений нет, `raw_content_hash`-корпус не растёт живым трафиком. `pre-LLM hits=0` теперь объясняется не только незрелостью корпуса, но и отсутствием ввода.
3. Coverage не просел (см. §t2.3) → нет T1-регресса, S3 не режет лишнее → **не FAIL**.

Итого: по-прежнему зафиксированный `S3 effect: PARTIAL`/NEUTRAL (§2.3), но **финальный billing-clean 48–72h read невозможен, пока ingestion не восстановлен**. **Требуется: (1) починить ingestion (A1), (2) дать живому трафику накопиться в billing-clean окне, (3) повторить W2-read на 48–72h.**

## t2.3 Watch — S5/S6 post-deploy metric-watch → **PASS (no-regression) — но заморожен ingestion-outage'ом**

**S6 — malformed_merge / failed batches (t2):**

| Метрика / query | t0 | t1 | t2 |
|---|---|---|---|
| `tg_parser_topicization_full_run_chunk_failed_total` (raw, все reasons) | нет серий | нет серий | **нет серий** (ships dark, by design) |
| `...{reason="malformed_merge"}` (raw + `last_over_time[7d]`) | 0 sample | 0 sample | **NO_SERIES (0)** |
| `sum(increase(...{reason="malformed_merge"}[7d]))` | нет сэмплов | нет сэмплов | **нет сэмплов** |
| `tg_parser_topicization_failed_batches_total` (raw + `last_over_time[7d]`) | нет серий (0) | нет серий (0) | **NO_SERIES (0)** |
| логи `malformed_merge` / `failed merge chunk` (24h) | — | 0 строк | **0 строк** |
| `TopicizationFullRunChunkFailedSustained` alert | inactive | inactive/ok | **inactive/ok** |

**S5 — discover / assign / coverage (t2):**

| Метрика / query | t0 | t1 | t2 |
|---|---|---|---|
| `sum(increase(tg_parser_topicization_reconcile_discover_docs_total[7d]))` | 0 | нет сэмплов (0) | **NO_SERIES (0)** (proxy не «залипает») |
| `sum by (channel_id) (increase(tg_parser_topics_created_total[7d]))` | genotek 0, medportal_rfed 0 | medportal_rfed 0 | **NO_SERIES** (нет прироста — ingestion down) |
| `TopicizationReconcileDiscoverSustained` alert | (inactive) | inactive/ok | **inactive/ok** |

**S5 coverage `tg_channel_processed_coverage_ratio` (регресс-стоп T1) — через `last_over_time[24h]`, последний сэмпл 12:24:36Z:**

| channel_id | coverage t0 | coverage t1 | coverage t2 | vs baseline |
|---|---|---|---|---|
| BiocodebySechenov | 1.0 | 1.0 | **1.0** | = |
| kdl_ru | 1.0 | 1.0 | **1.0** | = |
| LongevityClub | 1.0 | 1.0 | **1.0** | = |
| medportal_rfed | 1.0 | 1.0 | **1.0** | = |
| mind_rise | 1.0 | 1.0 | **1.0** | = |
| profendocrinologist | 1.0 | 1.0 | **1.0** | = |
| genotek | 0.99828 | 0.99828 | **0.99828** | = |
| Lab4health | 0.99791 | 0.99791 | **0.99843** | ↑ ≥ baseline |
| labdiagnostica_logical | 0.99754 | 0.99755 | **0.99755** | ≥ baseline |
| foodf4thought | 0.99706 | 0.99706 | **0.99706** | = |
| AgeManagment | 0.99655 | 0.99655 | **0.99655** | = |
| mediamedics (t1+) | — | 0.99973 | **0.99982** | ↑ (≥ 0.99) |
| Docma_ru (t1+) | — | 0.99290 | **0.99660** | ↑ |

**Verdict: PASS (по критериям §3.3), с оговоркой.** `malformed_merge`=0 sample (raw + логи + алерт inactive); coverage по **всем 13 каналам ≥ baseline** (ни один не ниже §3.2, несколько выросли); reconcile-discover proxy=0, оба алерта inactive. Формальные регресс-стопы (malformed>0, падение coverage, sustained discover) **не сработали** → S5/S6 деплой #323 регрессов не внёс. **Оговорка:** сигнал **заморожен** — с ≈19:52Z 07-16 нет нового ingestion/topicization (A1), поэтому это подтверждение «нет регресса на удержанных значениях», а не «нет регресса под живой нагрузкой». Полноценное живое подтверждение S5/S6 требует восстановления ingestion.

---

## t2. Сводка (one-look)

| Watch | t0 → t1 → t2 (ключевое) | Elapsed | Target | Verdict |
|---|---|---|---|---|
| BUG-084 embedding (W1) | 0 rate_limited/quota_exhausted [24h/48h]; оба алерта inactive; firing=0; только `ok` | ≈48h | 24–48h | **PASS** (закрывать) |
| S3 pre-LLM dedup (W2) | pre-LLM hits по-прежнему 0; окно НЕ billing-clean (свежий эпизод ≈28.65 blocks 24h); ingestion down → forward-watch не копит | ≈48h | 48–72h (billing-clean) | **INTERIM** (не финал) |
| S5/S6 post-deploy (W3) | malformed_merge=0; coverage все 13 ≥ baseline; алерты inactive — но заморожено (нет нового ingestion) | ≈48h | 24–48h | **PASS (no-regression), заморожен** |

**Аномалии:** **A1 (доминирующая) — тотальный ingestion-outage с 2026-07-16T19:52Z из-за отсутствия `TELEGRAM_SESSION_KEY` после деплоя #323** (442 `SessionCryptoError`/24h, все 13 каналов, не алертится). A2 — свежий Anthropic-billing-эпизод ≈28.65 blocks + haiku err≈23.5 в 17–24h назад (до рестарта; сейчас чисто). A3 (observability-gap) — 17h ingestion-простоя прошли **без единого firing-алерта**. Coverage-регресса нет; malformed_merge=0.

## t2.4 Рекомендуемое next-action

1. **🔴 Приоритет 0 (вне scope этого docs-снапшота, но критично):** восстановить ingestion — выставить `TELEGRAM_SESSION_KEY` (Fernet) на prod и рестартнуть `tg_parser`, ЛИБО break-glass: восстановить plaintext `.session`. Проверить, что тик снова `succeeded>0`. Разобрать деплой #323: F9-hardening требует секрет, которого нет в prod-env. Рассмотреть алерт на `succeeded=0` подряд (A3).
2. **W1 (BUG-084):** закрыть как **PASS** (soak чист на 48h, не зависит от A1).
3. **W2 (S3):** держать открытым. Финальный billing-clean 48–72h read невозможен, пока ingestion лежит и пока trailing-окно не станет billing-clean. После починки A1 — дать живому трафику накопиться, затем повторить.
4. **W3 (S5/S6):** no-regression подтверждён на удержанных значениях; после починки A1 — один живой read для подтверждения под нагрузкой.

## t2.5 Статус автоматизации (task step 6)

**W2/S3 НЕ достиг финального вердикта** (INTERIM: окно не billing-clean + ingestion-outage блокирует forward-accrual). Условие отключения — финальный PASS/FAIL W2 в billing-clean 48–72h окне — **не выполнено**. ⇒ **Эту автоматизацию отключать НЕЛЬЗЯ, оставить ENABLED.** Ближайший валидный W2-финал возможен только после (а) восстановления ingestion (A1) и (б) накопления живого трафика в billing-clean 48–72h окне.

*Снято read-only с prod (`3b59ce9`) 2026-07-17T12:25Z: Prometheus HTTP API `tg_parser_prometheus` (`/api/v1/query`, `/api/v1/rules`), `/metrics` контейнера `tg_parser`, `docker compose logs`. Значения не сфабрикованы — каждая ячейка либо live-значение с указанным окном (при per-worker флаппинге — через `last_over_time`), либо явное «нет сэмплов»/`NO_SERIES`. Prod не менялся: ни один сервис не запускался/останавливался.*
