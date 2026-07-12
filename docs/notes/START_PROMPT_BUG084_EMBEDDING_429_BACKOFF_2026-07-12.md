# START PROMPT — BUG-084 **fix-session**: embedding `429` classify-by-`error.code` (transient backoff vs terminal quota) + RAG keyword-fallback + distinct metric

**Дата:** 2026-07-12 · **Для:** implementation-сессии (отдельное окно).
**Planning:** **лёгкий** — root cause подтверждён (см. Prerequisites + BUG_LOG §BUG-084 «Update 2026-07-12»); change set известен. Открытые вопросы по scope (retry-бюджет, degraded-UX, concurrency-knob, settings, follow-up) собраны в §OPEN QUESTIONS и **должны быть подтверждены пользователем до кодирования**.

---

## Prerequisites

| Предпосылка | Статус |
|---|---|
| **BUG-082 resolved** | `fix/bug082-db-pool-concurrency` (2026-07-10); embedding-`429` (#4) явно вынесен в **BUG-084** |
| **S7 merged** | PR #307 → `main` (`208db74`) — O-9b: per-loop reusable embedding-клиент в `retrieval_service.search()` (`embedding_service.get_embedding_client` / `close_embedding_client`). Этот fix НЕ трогает retry/ошибки — только lifecycle сокета |
| **Root cause подтверждён (prod diag 2026-07-12)** | Live `429` = **`insufficient_quota`** (terminal), НЕ transient rate-limit. Evidence: `x-request-id=req_7b8dc2fc9ac046159e1157fe4b6cd0dd`, **нет** `x-ratelimit-*` / `retry-after` заголовков, состояние держалось ~2ч (14:25–16:59 UTC). См. BUG_LOG §BUG-084 «Update 2026-07-12» |
| **FUTURE item** | [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) → «Configurable Embedding Provider» — долгосрочное снятие зависимости от единственного провайдера эмбеддингов |

**Нормативные документы (при расхождении — они первичны):**
- Баг: [`BUG_LOG.md`](BUG_LOG.md) §BUG-084 (+ «Update 2026-07-12 — root-cause diagnostic»).
- Проект: [`AGENTS.md`](../../AGENTS.md) — без контрактов/миграций/промптов; правки `settings.py` разрешены (эта сессия — код; данный документ — только план).
- Референс retry-паттерна: `tg_parser/processing/llm/openai_client.py::_request_with_retry` (`_RETRYABLE_STATUS_CODES={429,500,502,503,529}`, `_parse_retry_after`, jittered exp backoff).
- Референс метрики-outcome: BUG-082 fix #3 (`record_resummarize_outcome` с distinct `outcome="db_error"`).

---

<role>
Ты — senior-инженер tg_parser. Устраняешь BUG-084: `OpenAIEmbeddingClient.embed()` (`tg_parser/services/embedding_service.py:56–65`) не имеет retry/backoff — `raise_for_status()` пробрасывает `429` сырым, поэтому **и** фоновый topic/incremental embedding-этап (`background_scheduler.py`), **и** живой semantic/hybrid RAG-путь (`retrieval_service.search()` `~:120–129`, эмбеддинг запроса) жёстко падают на `429`. Отдельной embedding-метрики нет — `429` смешивается с DB-pool / LLM-ошибками.

**Ключевой урок диагностики 2026-07-12:** `429` бывает ДВУХ материально разных классов, и слепой retry на всех `429` вреден (жжёт latency/попытки на терминальном состоянии):
- **transient `rate_limit_exceeded`** (RPM/TPM/RPD) → backoff помогает;
- **terminal `insufficient_quota`** (исчерпан кредит / месячный usage-cap) → retry **бесполезен**, нужно billing/tier-действие.

**Минимализм:** трогаем embedding-клиент (retry+классификация), метрику, RAG-fallback, `settings.py`. Контракты, миграции, промпты — **не трогаем**.
</role>

<context>
## Root cause (подтверждён)

```56:65:tg_parser/services/embedding_service.py
    async def embed(self, texts: list[str]) -> list[list[float]]:
        client = await self._get_client()
        response = await client.post(
            "/embeddings",
            json={"input": texts, "model": self.model},
        )
        response.raise_for_status()
        data = response.json()
        sorted_data = sorted(data["data"], key=lambda x: x["index"])
        return [item["embedding"] for item in sorted_data]
```

Нет retry/backoff, нет классификации `429`. `raise_for_status()` → сырой `httpx.HTTPStatusError`.

**Два потребителя падают на одном и том же `429`:**
1. Фоновый embedding (topic auto-embedding + incremental) — `services/background_scheduler.py`.
2. Живой RAG (эмбеддинг запроса) — `retrieval_service.search()`:

```120:129:tg_parser/services/retrieval_service.py
    query_vec: list[float] | None = None
    if effective_mode in ("semantic", "hybrid"):
        # O-9b (F-11): reuse one embedding client per event loop instead of a
        # per-request create/close. ...
        client = get_embedding_client(factory=create_embedding_client)
        query_embeddings = await client.embed([query])
        query_vec = query_embeddings[0]
```

## Два класса `429` (OpenAI docs research, 2026)

| Класс | `error.code` / `error.type` | Заголовки | Retry? | Действие |
|---|---|---|---|---|
| **Transient rate-limit** | `rate_limit_exceeded` | `x-ratelimit-limit/remaining/reset-{requests,tokens}`; `Retry-After` **не гарантирован** на каждом `429` | **Да** — honor `Retry-After` → `x-ratelimit-reset-*` → jittered backoff | само рассосётся; опц. concurrency-cap |
| **Terminal quota** | `insufficient_quota` | **нет** `x-ratelimit-*` / `retry-after` | **Нет** — retry бесполезен, жжёт latency/попытки | **billing/tier-действие** (кредиты / способ оплаты / поднять tier) |

Embeddings (`text-embedding-3-small/large`) регулируются RPM+TPM (+ RPD на Free-tier). Перегрузка провайдера — это `503`, не `429`. Лимиты/tier: `platform.openai.com/settings/organization/limits`; usage: `/usage`; billing: `/settings/organization/billing`.

**Prod 2026-07-12:** живой `429` = `insufficient_quota` (terminal), без `x-ratelimit-*`/`retry-after`, держался ~2ч → это **не throttling**, а billing-состояние. Значит retry на нём futile; единственный код-митигатор, сохраняющий работоспособность RAG, — **semantic/hybrid → keyword fallback**.
</context>

---

## Target behavior

| Аспект | Current | Target |
|---|---|---|
| `embed()` на transient `rate_limit_exceeded` (+ 5xx/overload `{500,502,503,529}`) | сырой raise | backoff/retry: honor `Retry-After` → `x-ratelimit-reset-*` → jittered exp backoff; на исчерпании попыток → **типизированное** `EmbeddingRateLimitError` (transient) |
| `embed()` на terminal `insufficient_quota` | сырой raise (и был бы «зациклен» retry) | **немедленный** `EmbeddingQuotaError` (terminal) — **без retry** (не жечь попытки/latency) |
| RAG `search()` при любом embedding-fail (terminal **или** transient-exhausted) | весь запрос падает | **semantic/hybrid → keyword fallback**: выставить `effective_mode="keyword"` **до** решения `run_hybrid_parallel`; tenant-scoping уже mode-independent |
| Метрика | нет embedding-метрики; `429` смешан с DB/LLM | новый `tg_embedding_requests_total{outcome, stage}`, `outcome ∈ {ok, rate_limited, quota_exhausted, error}`; классификация в `background_scheduler` + `retrieval_service` |
| Concurrency (опц., knob-gated, default off) | нет | `asyncio.Semaphore(embedding_max_concurrency)`; `0 = off` |

**Типы исключений (рекомендация):** две типизированные ошибки — `EmbeddingRateLimitError` (transient, попытки исчерпаны) vs `EmbeddingQuotaError` (terminal) — **или** одно исключение с флагом `terminal: bool`, чтобы RAG-fallback и метрики их различали.

---

## Files to change

| File | Change |
|---|---|
| `tg_parser/services/embedding_service.py` (`OpenAIEmbeddingClient.embed`, `:56–65`) | (a) **CORE** backoff/retry на transient `rate_limit_exceeded` + `{500,502,503,529}`; классификация по `error.code`; terminal `insufficient_quota` → немедленный `EmbeddingQuotaError` без retry; на исчерпании transient → `EmbeddingRateLimitError`. Новые типизированные исключения объявить здесь (или в соседнем модуле). Ориентир — `openai_client._request_with_retry` / `_parse_retry_after` |
| `tg_parser/api/metrics.py` | (c) **CORE** новый `tg_embedding_requests_total{outcome, stage}` (`outcome ∈ {ok, rate_limited, quota_exhausted, error}`) + `record_embedding_outcome(...)` (зеркалит BUG-082 `db_error` паттерн) |
| `tg_parser/services/background_scheduler.py` | (c) классифицировать embedding-исход (ok / rate_limited / quota_exhausted / error) при вызове фонового embedding — не путать с DB-pool/LLM |
| `tg_parser/services/retrieval_service.py` (`search`, `~:120–129` + решение `run_hybrid_parallel` `~:143`) | (d) **CORE** semantic/hybrid → keyword fallback на `EmbeddingQuotaError` **и** `EmbeddingRateLimitError`: `effective_mode="keyword"` **до** `run_hybrid_parallel`; записать embedding-outcome |
| `tg_parser/config/settings.py` | новые: `embedding_max_retries` (~5), `embedding_retry_max_wait_s`, `embedding_max_concurrency` (`0=off`). **(см. OPEN QUESTIONS #4 — подтвердить перед добавлением)** |
| `tests/test_bug084_embedding_backoff.py` (новый) | RED→GREEN, см. §Test anchors |

**Optional (knob-gated, default off):** (b) `asyncio.Semaphore` concurrency-cap в embedding-путях — **только** если OPEN QUESTIONS #3 = «add now».

**Не трогаем:** контракты (`docs/contracts/**`), миграции, `prompts/**`, размер вектора, схему `EmbeddingRepo`, RRF-слияние.

---

## Test anchors

### Existing (regression — must stay green)
| File | Why |
|---|---|
| `tests/test_embedding.py` | клиент/`embed`-контракт не сломан |
| `tests/test_o9b_retrieval_embedding_client.py` | S7 per-loop client lifecycle не задет |
| `tests/test_retrieval_hybrid_session.py` | semantic/hybrid `search()` |
| `tests/test_rag_routes.py` | сквозной RAG (`ask_question`/`search_knowledge_base`) |
| `tests/test_f5a_hybrid_search.py`, `tests/test_f5a_topic_rag.py` | hybrid/topic-weighted RAG-ветки |

### New — `tests/test_bug084_embedding_backoff.py` (red → green)
| Case | Assert |
|---|---|
| retry-succeeds | transient `rate_limit_exceeded` затем `200` → `embed()` возвращает вектор; retry отработал (honor `Retry-After`) |
| retry-exhausted → typed + classified | серия transient `429` → `EmbeddingRateLimitError`; метрика `outcome="rate_limited"` |
| terminal quota — NO retry | `insufficient_quota` → немедленный `EmbeddingQuotaError`, **ровно 1** HTTP-вызов (нет retry); метрика `outcome="quota_exhausted"` |
| RAG fallback (semantic) | `search(mode="semantic")` при embedding-fail → `effective_mode="keyword"`, ответ отдаётся (не падает) |
| RAG fallback (hybrid) | `search(mode="hybrid")` при embedding-fail → keyword-ветка; fallback выставлен **до** `run_hybrid_parallel` |
| no-regression S7 per-loop client | client reuse per-loop не сломан (нет per-request close/leak) |
| batch paths | batch/ingestion embedding-пути всё ещё работают (классификация не ломает батч) |

**Modes:** *default* (`pytest -q`) + *PR standard* (`TEST_POSTGRES=1`). RED **до** правки production-кода (WORKFLOW цикл).

---

## Acceptance criteria

- [ ] red→green на новых кейсах **до** правки production-кода
- [ ] `embed()` ретраит **только** transient `rate_limit_exceeded` (+ `{500,502,503,529}`), honor `Retry-After` → `x-ratelimit-reset-*` → jittered backoff
- [ ] `insufficient_quota` → **немедленный** terminal `EmbeddingQuotaError`, **без** retry (проверено счётчиком HTTP-вызовов)
- [ ] transient-exhausted → `EmbeddingRateLimitError`
- [ ] RAG `search()` semantic **и** hybrid делают keyword-fallback на **обоих** классах ошибок; fallback выставлен до `run_hybrid_parallel`; tenant-scoping не нарушен
- [ ] `tg_embedding_requests_total{outcome, stage}` различает `ok / rate_limited / quota_exhausted / error`; классификация в `background_scheduler` + `retrieval_service`
- [ ] batch/ingestion embedding-пути не изменены по поведению
- [ ] concurrency-cap (если добавлен) default **off** (`embedding_max_concurrency=0`)
- [ ] PR standard green; bugbot clean

---

## Deploy

- Branch: **`fix/bug084-embedding-429-backoff`**
- retry+fallback — **on by default**; concurrency-cap — **off by default** (`embedding_max_concurrency=0`)
- Rollback: revert PR (нет схемы/миграции)
- **Operational prerequisite (см. Post-deploy):** terminal `insufficient_quota` кодом НЕ лечится

---

## Post-deploy validation

- [ ] **Billing/tier-действие сначала (оператор):** terminal `insufficient_quota` требует пополнения кредитов / способа оплаты / поднятия usage-tier на дашборде OpenAI (`/settings/organization/billing`, `/settings/organization/limits`). **Код не восстановит эмбеддинги без этого.**
- [ ] **Confirm a real embedding 200 after billing restored** — живой embedding-запрос возвращает `200` (не `429`), метрика `tg_embedding_requests_total{outcome="ok"}` растёт
- [ ] при активном `insufficient_quota` RAG остаётся рабочим через keyword-fallback (semantic/hybrid деградируют, не падают); метрика `outcome="quota_exhausted"` наблюдаема/алертится
- [ ] transient throttling (если возникнет) виден как `outcome="rate_limited"`, отделён от quota
- [ ] нет утечки/регресса per-loop client (S7)

---

## OPEN QUESTIONS (pending user decision)

1. **Retry-бюджет** — меньший на user-facing RAG query path (1–2 попытки, чтобы не тормозить чат) vs полный (5) на фоновых батчах? (Разные значения для двух путей?)
2. **Fallback UX** — отдавать `degraded: true` индикатор в RAG-ответе vs тихая keyword-деградация?
3. **`embedding_max_concurrency` knob** — добавить сейчас (default off) или отложить?
4. **Settings** — OK добавить `embedding_max_retries`, `embedding_retry_max_wait_s`, `embedding_max_concurrency` в `settings.py`? (AGENTS.md: правки `settings.py` разрешены, но подтвердить состав)
5. **Follow-up** — заводить ли OpenAI tier/billing review отдельным трекнутым follow-up (связать с FUTURE «Configurable Embedding Provider»)?

---

## Out of scope

- Контракты (`docs/contracts/**`), DB-миграции, `prompts/**`
- Смена провайдера эмбеддингов / мульти-провайдер (это FUTURE «Configurable Embedding Provider» — долгосрочное снятие single-provider зависимости)
- Размер вектора, схема `EmbeddingRepo`, RRF-слияние, keyword-ветка (кроме использования как fallback)
- Batch/ingestion lifecycle клиента (амортизирован по батчу — покрыт S7)

---

## One-liner for agent window

> BUG-084: в `OpenAIEmbeddingClient.embed()` (`embedding_service.py:56–65`) добавить retry/backoff **с классификацией по `error.code`** — ретраить только transient `rate_limit_exceeded` (+5xx/overload), а terminal `insufficient_quota` → немедленный `EmbeddingQuotaError` без retry. Сделать semantic/hybrid→keyword fallback в `retrieval_service.search()` (core, единственный митигатор при quota) + distinct метрику `tg_embedding_requests_total{outcome∈ok/rate_limited/quota_exhausted/error, stage}`. `settings.py` кнобы. Branch `fix/bug084-embedding-429-backoff`, отдельный PR. NB: terminal quota лечится billing-действием, не кодом (см. Post-deploy + OPEN QUESTIONS).
