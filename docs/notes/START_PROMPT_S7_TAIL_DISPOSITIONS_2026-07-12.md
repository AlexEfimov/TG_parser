# START PROMPT — S7 **implementation**: O-9b + диспозиция Low-находок (хвост ревью)

**Дата:** 2026-07-12 · **Для:** implementation-сессии (отдельное окно).
**Planning:** **не требуется** — O-9b узкий (lifecycle клиента), диспозиции — документарные решения + микро-фиксы. Сразу код + unit-тесты (PLAN §S7, WORKFLOW §3/§5).

---

## Prerequisites

| Предпосылка | Статус |
|---|---|
| **S1–S4 deployed** | S1 #299 `6a07652`; S2 #300 `39fddff`; S3 #301; S4 #304 `b1e4c7b` (prod 2026-07-11, threshold 0.32) |
| **S5 merged** | PR #305 → `main` `dffd767`; sim [`S5_TOPK_ASSIGN_SIMULATION_2026-07-11.md`](S5_TOPK_ASSIGN_SIMULATION_2026-07-11.md); дефолт `topk_denom` |
| **S6 merged** | PR #306 → `main` `1c00ee1`; pure post-processing, no sim gate |
| **S0 baseline** | [`S0_BASELINE_PROCESSING_METRICS_2026-07-07.md`](S0_BASELINE_PROCESSING_METRICS_2026-07-07.md) |

**Нормативные документы (при расхождении — они первичны):**
- План: [`PLAN_REMEDIATION_SESSIONS_PROCESSING_ALGORITHMS_2026-07-07.md`](PLAN_REMEDIATION_SESSIONS_PROCESSING_ALGORITHMS_2026-07-07.md) §S7, §2 (S7 последним — ничего не блокирует).
- Отчёт: [`CODE_REVIEW_PROCESSING_ALGORITHMS_FABLE5_2026-07-07.md`](CODE_REVIEW_PROCESSING_ALGORITHMS_FABLE5_2026-07-07.md) — F-11/O-9b (§O-9, §297), остаточные Low-находки F-14–F-18 + Medium-остаток F-06 (accept) (§203–215), замечание A7 (§28/§98).
- Процесс: [`WORKFLOW_REMEDIATION_SESSIONS_AGREEMENTS_2026-07-07.md`](WORKFLOW_REMEDIATION_SESSIONS_AGREEMENTS_2026-07-07.md) §3 (отдельный PR), §5 (цикл), §7 (без контрактов/миграций).
- Проект: [`AGENTS.md`](../../AGENTS.md).

---

<role>
Ты — senior-инженер tg_parser. Закрываешь **хвост** code-review 2026-07-07: **O-9b** (переиспользуемый embedding-клиент в RAG-пути) как единственный код-деливерабл + **диспозицию всего хвоста находок** (остаточные Low F-14–F-18 + Medium-остаток F-06 + замечание A7) — фикс, если тривиально; иначе — осознанная запись в `BUG_LOG.md` / `FUTURE_FEATURES.md`.

**После S7 каждая из 18 находок ревью либо исправлена (S1–S6), либо имеет зафиксированную диспозицию.** Это последняя сессия серии.

**Минимализм:** O-9b трогает только lifecycle клиента в retrieval-пути. Не расширять на batch/ingestion пути без нужды. Контракты, миграции, промпты — не трогаем.
</role>

<context>
## O-9b (остаток F-11) — новый embedding-клиент на каждый RAG-запрос

`retrieval_service.search()` создаёт и закрывает свежий httpx-обёрнутый embedding-клиент на **каждый** семантический/hybrid запрос:

```117:124:tg_parser/services/retrieval_service.py
    query_vec: list[float] | None = None
    if effective_mode in ("semantic", "hybrid"):
        client = create_embedding_client()
        try:
            query_embeddings = await client.embed([query])
            query_vec = query_embeddings[0]
        finally:
            await client.close()
```

`create_embedding_client()` → `OpenAIEmbeddingClient` (`embedding_service.py:28–70`), который лениво поднимает `httpx.AsyncClient` в `_get_client()` и закрывает его в `close()`. Для чат-бота с потоком вопросов это **лишний TLS-handshake + сокеты на запрос** (отчёт §129, F-11: «десятки мс на запрос»).

**O-9a (per-topic LLM-клиент в resummarize) уже закрыт в S1** — S7 покрывает только retrieval-embedding-клиент.

**Size / risk (PLAN §S7 / отчёт §297):** M, средний риск — важен аккуратный lifecycle (закрытие на shutdown, отсутствие утечки клиента, совместимость с тестовым DI).

### Что не меняем
- Batch/ingestion embedding-пути (`embedding_service.py:111, 211, 286`) — там клиент амортизируется по батчу; вне scope (не поток одиночных запросов).
- Резолюция provider/model эмбеддингов, размер вектора, схема `EmbeddingRepo`.
- RRF-слияние, keyword-ветка, контекст-лимиты RAG.

## Диспозиция Low-находок (PLAN §S7)

По каждому пункту — явное решение «тривиальный фикс → сделать | осознанно принять → зафиксировать»:

| Находка | Локация | Диспозиция (план) |
|---|---|---|
| **F-06** (Medium по отчёту, §203) — TTL-кэш только в `generate()`, пайплайн ходит мимо через `generate_with_usage()` | `processing/llm/instrumented.py:42–56 vs 66–96` | **Принять осознанно** — вердикт отчёта «расширение не делать»; зафиксировать в BUG_LOG |
| **F-14** — `text_clean` обрезается до 500 симв. перед эмбеддингом | `services/embedding_service.py:82–89` | **Правило по данным:** измерить долю документов с `len(text_clean) > 500`. Если доля **< 5 %** → **accept** + запись в BUG_LOG (эффект пренебрежимо мал, summary добирает контекст). Иначе → добавить `settings`-knob (default = текущие 500), поднимающий лимит входа эмбеддинга |
| **F-15** — O(topics×docs) в `_find_supporting_items_programmatic` | `processing/topicization.py:~1973–2026` | Фикс при следующем full-run окне; сейчас — зафиксировать (backlog/BUG_LOG) |
| **F-16** — N+1 в агентном пути (`orchestrator.send_to` в цикле) | `services/processing_service.py:659–664` | Путь экспериментальный → **backlog** (BUG_LOG/FUTURE_FEATURES) |
| **F-17** — truncation-сплит переотправляет обе половины батча | `processing/topicization.py:~1340–1391` | Смягчён ростом max_tokens → **принять**; зафиксировать |
| **F-18** — eviction кэша удаляет insertion-first, не старейшую/истёкшую | `processing/llm/response_cache.py:79–83` | Тривиальный фикс **или** принять как микронеоптимальность |
| **A7** — только промптовая защита от дублей в discover | `topicization.py` (`discover_new_topics`) | Кандидат в **FUTURE_FEATURES** (§6.5 эмбеддинг-assign — та же ось) |

**Строки указаны по состоянию отчёта 2026-07-07 — при реализации ориентироваться на имена функций** (после S3–S6 номера могли сдвинуться).
</context>

---

## Target behavior (O-9b)

| Аспект | Current | Target |
|---|---|---|
| Embedding-клиент в `search()` | новый `create_embedding_client()` + `close()` на каждый запрос | переиспользуемый клиент **на event loop** (loop-aware кэш **или** app-lifespan-managed); один `httpx.AsyncClient` на event loop, а не на процесс (клиент привязан к своему loop) |
| Закрытие клиента | per-request `finally: close()` | закрытие один раз на shutdown приложения (lifespan/atexit-хук), без утечки на каждый запрос |
| Тестовый путь (DI / mock) | без изменений | сохранить: тесты с инъекцией/моками и `reset` кэша между тестами не ломаются |
| Batch embedding пути | per-batch клиент | без изменений |

---

## Files to change

| File | Change |
|---|---|
| `tg_parser/services/retrieval_service.py` (`search`, `~117–124`) | использовать переиспользуемый embedding-клиент вместо per-request create/close |
| `tg_parser/services/embedding_service.py` | опциональный accessor/фабрика кэшированного клиента + идемпотентное закрытие (аккуратный lifecycle) |
| app shutdown seams | закрыть кэшированный клиент один раз на shutdown каждого долгоживущего loop: **FastAPI** — `lifespan` shutdown-блок (`api/main.py:~205`, после `yield`); **bot** (`bot/tools.py`) и **MCP** (`mcp_server.py`) — их долгоживущие shutdown-пути. **CLI** (`cli/app.py`) — one-shot `asyncio.run()` на команду: клиент закрывается сам на завершении loop (выгода переиспользования там нулевая, отдельный хук не нужен) |
| `tests/…` (новый `tests/test_o9b_retrieval_embedding_client.py` **или** дополнение к retrieval-тестам) | lifecycle: клиент переиспользуется между вызовами `search`; закрывается на shutdown; DI-путь не задет |
| `docs/notes/BUG_LOG.md` | F-11 → closed (O-9b); диспозиции F-06/F-14/F-15/F-16/F-17/F-18 |
| `docs/notes/FUTURE_FEATURES.md` | A7 (+ §6.5, если уместно) |
| `docs/notes/WORKFLOW_…AGREEMENTS…md` | S7 `pending → merged` после мержа |

**Не трогаем:** контракты (`docs/contracts/**`), миграции, `prompts/**`, settings без явной нужды (F-14 knob — только если решено «fix»).

---

## Test anchors

### Existing (regression — must stay green)
| File | Why |
|---|---|
| `tests/test_retrieval_hybrid_session.py` | путь `search()` semantic/hybrid (session-scoped) не сломан |
| `tests/test_retrieval_llm_refactor.py` | retrieval-рефактор / DI-инъекция не задеты |
| `tests/test_f5a_hybrid_search.py` | hybrid-ветка RAG (RRF-слияние) не сломана |
| `tests/test_f5a_topic_rag.py` | topic-weighted RAG-путь не сломан |
| `tests/test_embedding.py` | клиент/`embed`-контракт |
| `tests/test_rag_routes.py` | сквозной RAG (`ask_question`/`search_knowledge_base`) не задет |

### New (red → green для O-9b)
| Case | Assert |
|---|---|
| Client reuse (в пределах loop) | два последовательных `search(mode="semantic")` в одном loop → `create_embedding_client`/новый `httpx.AsyncClient` создаётся **один раз** |
| Cross-loop / per-loop safety | `search()` под двумя разными `asyncio.run(...)` loop'ами **не** бросает `RuntimeError: Event loop is closed`; в пределах одного loop клиент создаётся ровно один раз (loop-aware кэш). Runnable в *default* режиме: mock `embed` + mock repos, без Postgres |
| Shutdown close | shutdown-хук закрывает кэшированный клиент ровно один раз; повторный вызов идемпотентен |
| No per-request leak | нет `close()` на каждый запрос (клиент остаётся живым между запросами) |
| DI/mock unaffected | инъекция/mock и reset кэша между тестами работают (изоляция) |

**Modes:** *default* (`pytest -q`) + *PR standard* (`TEST_POSTGRES=1`); для O-9b — lifecycle-тест на отсутствие утечки клиентов.

---

## Acceptance criteria

- [ ] red→green на новых lifecycle-кейсах **до** правки production-lifecycle (WORKFLOW §5)
- [ ] `search()` переиспользует embedding-клиент между запросами **в пределах одного event loop** — один клиент на event loop (loop-aware кэш), переиспользуемый между вызовами `search()` в этом loop; **не** единый process-global клиент (`httpx.AsyncClient` привязан к loop, создавшему его → CLI/pytest поднимают много loop'ов, process-singleton даст `RuntimeError: Event loop is closed`)
- [ ] клиент закрывается ровно один раз на shutdown; нет per-request leak и нет double-close
- [ ] DI/mock retrieval-тесты и изоляция между тестами не сломаны
- [ ] batch/ingestion embedding-пути не изменены
- [ ] каждая остаточная находка хвоста — Low F-14–F-18 + Medium-остаток F-06 — имеет статус в BUG_LOG (fix **или** осознанный accept с обоснованием)
- [ ] A7 зафиксирован в FUTURE_FEATURES
- [ ] F-11 → closed (O-9b deliverable) в BUG_LOG
- [ ] PR standard green; bugbot clean
- [ ] **Ревью формально закрыто:** все 18 находок — fixed (S1–S6) или dispositioned (S7)

---

## Deploy

- Branch: **`fix/S7-tail-dispositions`**
- **Отдельный PR/деплой** (WORKFLOW §3); не батчить с S5/S6
- Rollback: revert PR (O-9b — lifecycle-изменение без env-knob; диспозиции — документарные)
- **No simulation gate**

---

## Post-deploy validation (PLAN §S7)

Lightweight — нет metric-watch band:
- [ ] RAG-запрос на dev/prod (`ask_question` / `search_knowledge_base`) отдаёт корректный ответ; latency не выше baseline (ожидается −десятки мс за счёт отсутствия handshake на запрос)
- [ ] нет ошибок закрытия клиента/утечки сокетов в логах после shutdown/restart
- [ ] `tg_channel_processed_coverage_ratio` — не ниже S0 §2 обл.5 (общий T1 регресс-стоп серии)

---

## Out of scope

- **§6.1** (эмбеддинг-кластеризация, XL), **§6.4** (дешёвая модель для коротких сообщений, M), **§6.5** (эмбеддинг-assign, L) — отдельные будущие контракты, gated
- Расширение TTL-кэша на `generate_with_usage` (вердикт отчёта — «не делать»)
- Любые contracts / DB migrations
- Batch/ingestion embedding client lifecycle (амортизирован по батчу)

---

## One-liner for agent window

> S7 (последняя): O-9b — переиспользуемый embedding-клиент в `retrieval_service.search()` (`:117–124`) вместо per-request create/close, аккуратный shutdown-lifecycle. + диспозиция хвоста F-14–F-18 (Low) + F-06 (Medium-остаток, accept) в BUG_LOG и A7 в FUTURE_FEATURES. Unit lifecycle-тесты. Branch `fix/S7-tail-dispositions`, отдельный PR. Закрывает ревью целиком.
