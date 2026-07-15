# Runbook — OpenAI embedding quota / rate-limit: восстановление RAG

**Назначение:** оператор видит алерт `EmbeddingQuotaExhausted` (или `EmbeddingRateLimitedSustained`) — эмбеддинги OpenAI `/v1/embeddings` перестали проходить, семантический/гибридный RAG деградировал до keyword-only. Этот runbook — как подтвердить причину, различить terminal quota vs transient rate-limit, устранить и верифицировать восстановление.

**Когда применять:** BUG-084 ввёл классификацию `429` по `error.code` (см. `tg_parser/services/embedding_service.py::OpenAIEmbeddingClient.embed`): terminal `insufficient_quota` → немедленный `EmbeddingQuotaError` (без retry), transient `rate_limit_exceeded`/5xx → jittered backoff → `EmbeddingRateLimitError` при исчерпании бюджета. Оба исхода пишутся в метрику `tg_embedding_requests_total{outcome, stage}` (`tg_parser/api/metrics.py::record_embedding_outcome`), на которой построены алерты (`docker/prometheus/alerts.yml` группа `tg_parser_bug084_embedding_quota`).

> **Ключевое различие:** `quota_exhausted` кодом **не лечится** — нужно billing/tier-действие в OpenAI. `rate_limited` — транзиентный троттлинг, обычно самоустраняется; код уже деградирует RAG до keyword, чтобы запросы не падали.

**Время:** ~5–15 минут (основное — пополнение/повышение лимита в OpenAI и ожидание распространения квоты).

**Связанные:**
- Bug: `docs/notes/BUG_LOG.md` § BUG-084
- Fix-план + root-cause: `docs/notes/START_PROMPT_BUG084_EMBEDDING_429_BACKOFF_2026-07-12.md` (§ Post-deploy validation)
- Метрика: `tg_parser/api/metrics.py::EMBEDDING_REQUESTS_TOTAL` / `record_embedding_outcome`
- Call-sites: `tg_parser/services/background_scheduler.py`, `tg_parser/services/retrieval_service.py`
- Аналогичный provider-billing runbook: `docs/runbooks/ANTHROPIC_BILLING_RECOVERY.md`
- Алерты: `docker/prometheus/alerts.yml` (`EmbeddingQuotaExhausted`, `EmbeddingRateLimitedSustained`)

---

## Симптомы

Любой из этих сигналов:

1. **Алерт** `EmbeddingQuotaExhausted` (severity=warning) или `EmbeddingRateLimitedSustained` (severity=info) в Prometheus/Grafana.
2. **RAG-ответы деградировали** — HTTP `/search`, `/ask` и MCP `ask_question` возвращают `degraded=true`; результаты ранжируются keyword-only даже при `mode=semantic`/`hybrid`.
3. **В логах** есть `rag_embedding_quota_exhausted_fallback_keyword` или `rag_embedding_rate_limited_fallback_keyword` (retrieval), либо соответствующие строки на фоне (background_scheduler).

---

## Шаги

### 1. Подтвердить причину и различить quota vs rate-limit

Не устранять наугад — сначала посмотри, какой `outcome` растёт:

```bash
docker compose exec tg_parser curl -s http://localhost:8000/metrics | grep tg_embedding_requests_total
```

- Растёт `outcome="quota_exhausted"` → **terminal** `insufficient_quota` → шаг 2 (billing).
- Растёт только `outcome="rate_limited"` → **transient** троттлинг → шаг 3 (throughput/tier).
- `stage` (`background_message` / `background_topic` / `rag_query`) показывает, какие пути затронуты; quota, как правило, бьёт по всем сразу (account-global).

Живой probe (опционально) — один embedding-запрос: `429` с `error.code=insufficient_quota` и **без** `x-ratelimit-*`/`retry-after` = terminal quota; `429` с `x-ratelimit-reset-*`/`retry-after` = transient.

### 2. Terminal quota (`quota_exhausted`) — устранить в OpenAI

1. [OpenAI Billing](https://platform.openai.com/settings/organization/billing) → добавить кредиты / платёжный метод / включить auto-recharge.
2. [OpenAI Limits](https://platform.openai.com/settings/organization/limits) → при необходимости поднять usage-tier / месячный cap.
3. Проверить, что нет org-level suspension (баланс есть, но ключ/организация заблокированы).

> Код без этого шага RAG не восстановит — semantic embeddings недоступны, работает только keyword-fallback.

### 3. Transient rate-limit (`rate_limited`) — снизить нагрузку / поднять лимит

- Обычно самоустраняется, когда падает throughput; retry/backoff уже встроен (`embedding_max_retries`, `embedding_retry_max_wait_s`).
- Если хронически: рассмотреть повышение RPM/TPM-лимита (OpenAI Limits) или (deferred BUG-084 Q3/Q4) ограничение конкурентности эмбеддинг-вызовов.

### 4. Верификация

После billing/tier-действия дождись, пока квота распространится (обычно минуты), затем:

```bash
# Живой embedding проходит (200), метрика ok растёт, quota_exhausted СТОИТ на месте
docker compose exec tg_parser curl -s http://localhost:8000/metrics | grep 'tg_embedding_requests_total'
```

Ожидаемо: `outcome="ok"` инкрементится, `outcome="quota_exhausted"` (и `rate_limited`) **перестал** расти. Алерт `EmbeddingQuotaExhausted` разрешится сам, когда `increase(...[15m])` вернётся к 0 (в пределах окна + `for:`).

Проверить, что RAG больше не деградирует:

```bash
# degraded должен быть false для semantic/hybrid запроса
docker compose exec tg_parser curl -s "http://localhost:8000/api/v1/search?query=test&mode=semantic" | grep -o '"degraded":[a-z]*'
```

### 5. Зафиксировать инцидент

Если quota-exhaustion — следствие новой проблемы (изменение биллинга, скачок нагрузки, org suspension), завести запись в `docs/quality/INBOX.md` (см. `docs/quality/AGENT_PLAYBOOK.md`). Штатное исчерпание — достаточно операционного лога.

---

## Что НЕ делать

- ❌ **Не ретраить эмбеддинги руками при `quota_exhausted`** до billing-действия — клиент намеренно не ретраит `insufficient_quota` (retry бесполезен и только жжёт latency).
- ❌ **Не «чинить» RAG кодом при terminal quota** — keyword-fallback это уже штатная деградация; функционально RAG остаётся доступен, восстановление semantic — только через OpenAI billing.
- ❌ **Не путать с BUG-082** (DB connection-pool `QueuePool limit`) — тот сигнал независим (`tg_parser_db_connections_active`, `TimeoutError`), эмбеддинг-`429` к пулу отношения не имеет.
