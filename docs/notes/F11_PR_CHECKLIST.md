# F11 — PR checklist (с пометками karpathy-like)

**Назначение:** вставить в описание Pull Request для F11 (Topic Watchlist). Набор критериев **совпадает по смыслу** с разделом «PR checklist» в [`START_PROMPT_SPRINT_F11.md`](START_PROMPT_SPRINT_F11.md) (тот же текст буллетов, плюс пометки **karpathy-like**). **Порядок строк здесь другой:** сгруппирован по рекомендованным **коммитам 1/2 и 2/2**; компактный список в **исходном** порядке остаётся в спринт-промпте.

**Имя файла миграции** в буллете — пример из спринт-промпта; фактическое имя ревизии берётся из `ls migrations/versions/ingestion/` и следующего свободного слота (см. Шаг 2 спринт-промпта).

**Порядок коммитов** соответствует рекомендации из того же промпта: **1/2** — persistence + scoring + тесты ядра; **2/2** — scheduler + MCP/Bot/CLI + оставшиеся тесты + документация. Пункты, которые физически живут в одном модуле (например `WatchlistService`), отнесены к коммиту, где они **впервые мерджатся**, даже если позже дополняются.

**Согласованность с продуктовым § F11:** в [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) в примере схемы встречается `threshold: 0.7`; **MVP default по спринт-промпту — 0.6** (обоснование — gotcha #9 в `START_PROMPT_SPRINT_F11.md`). В реализации и доках явно указать дефолт **0.6** и возможность тюнинга.

---

## Коммит 1/2 — schema + service + repos + тесты ядра

- [ ] Миграция `migrations/versions/ingestion/20260419_add_watchlist.py` создана; `tg-parser db check --db ingestion` → `No new upgrade operations detected.`; `Table()` декларации в `_metadata.py`. **(karpathy-like: персистентный user-defined query object + evidence-таблица как слой provenance для новых фактов из канала.)**
- [ ] `pgvector` extension включён в ingestion БД (idempotent `CREATE EXTENSION IF NOT EXISTS`). **(karpathy-like: семантический якорь интереса в том же векторном пространстве, что и документы KB.)**
- [ ] `WatchInterest` + `WatchMatch` доменные модели в `domain/models.py`. **(karpathy-like: явные типы «страница интереса» / «цитата с оценкой уверенности», без размытых dict в сервисе.)**
- [ ] `WatchInterestRepo` + `WatchMatchRepo` ports + SQLAlchemy реализации, `upsert_many` идемпотентен. **(karpathy-like: идемпотентные обновления журнала наблюдений — повторный tick не плодит дубликаты доказательств.)**
- [ ] `WatchlistService` с `compute_watch_score` (negative filter работает; threshold ровно на границе включает; пустой keywords-set → keyword_score = 0; пустой interest.embedding → semantic_score = 0). **(karpathy-like: гибрид keyword + cosine как дешёвый mini-RAG на потоке новизны, без LLM на каждый документ.)**
- [ ] Embedding fallback: при пустом description embed `f"{title}. {' '.join(keywords)}"`. **(karpathy-like: канонический embedding-текст для страницы интереса.)**
- [ ] Notification: group by `interest_id`, одно сообщение на группу, HTML-formatting, `match_repo.mark_notified` после send. **(karpathy-like: один digest-style wiki update на тему вместо спама по каждому source_ref.)**
- [ ] `MAX_DOCS_PER_TICK = 100` защита от flood при backfill. **(karpathy-like: controlled assimilation при всплеске новых «страниц» в канале.)**
- [ ] Часть набора «~30 тестов»: repo + service + integration (PG-gated) для слоя 1/2 — по плану промпта: `test_watchlist_service`, `test_watch_interest_repo`, `test_watch_match_repo`, `test_f11_watchlist_integration`. **(karpathy-like: регрессии качества scoring + сохранение provenance scores в БД.)**

---

## Коммит 2/2 — MCP/Bot/CLI + scheduler + оставшиеся тесты + docs

- [ ] Scheduler hook в `run_incremental_for_all_sources` — после `run_incremental_topicization`, fail-soft через `try/except + logger.exception`. **(karpathy-like: watchlist как хвост living-KB loop; сбой алертов не ломает ingestion/topicization.)**
- [ ] MCP tools (4): `subscribe_watchlist`, `list_watchlists`, `unsubscribe_watchlist`, `get_watchlist_matches`. Ownership через `assert_channel_access` для каналов + admin/owner для interest. **(karpathy-like: программируемые персональные темы и ACL на уровне каналов/пользователя.)**
- [ ] Bot tools (4): декларации + executors + `subscribe_watchlist` ∈ `_TOOLS_NEEDING_BOT_CONTEXT`. **(karpathy-like: тот же контракт для пользователя в боте; chat_id как канал доставки wiki updates.)**
- [ ] CLI: `tg-parser watchlist {add,list,remove,matches}`. **(karpathy-like: полный CRUD + чтение evidence log для power users и автоматизации.)**
- [ ] Оставшиеся тесты из плана ~30: MCP + bot + scheduler hook. **(karpathy-like: доверие к E2E wiring интерес → матч → уведомление и границам ownership.)**
- [ ] `docs/USER_GUIDE.md` — новый раздел F11 с примерами. **(karpathy-like: как формулировать интересы и читать матчи как citations.)**
- [ ] `docs/MCP_AGENT_GUIDE.md` — описания 4 новых tools. **(karpathy-like: контракт для агента: подписка, список, история матчей.)**
- [ ] `docs/notes/FUTURE_FEATURES.md` § F11 — `✅ MVP DONE`, scope явно прописан, Phase 2 в backlog. **(karpathy-like: Phase 2 batch/silent/LLM-matching отдельно, не размывая живую модель.)**
- [ ] `docs/notes/ROADMAP_V3_PRODUCTION_FIRST.md` — строка F11 → ✅, следующая F5-C явно помечена. **(karpathy-like: следующий шаг — эволюция страниц темы, а не раздувание watchlist.)**

---

## После обоих коммитов (PR целиком)

- [ ] Tests: ~30 новых, repo + service + integration (PG-gated) + MCP + bot + scheduler hook. **(karpathy-like: полное покрытие цепочки данные → скоринг → доставка.)**
- [ ] `pytest --tb=short -q` зелёный, baseline + ~30 passed. **(karpathy-like: не регрессируем RAG/topicization при добавлении личного слоя.)**
- [ ] `ruff format` + `ruff check .` чистые. **(karpathy-like: единый стиль с остальным KB-кодом.)**
- [ ] CI: 5/5 jobs зелёные. **(karpathy-like: миграции и Table() не расходятся с Alembic.)**
- [ ] Commit messages содержат: `feat(F11)`, breaking changes (нет), verification numbers, ссылку на дизайн-док FUTURE_FEATURES. **(karpathy-like: история коммитов читается как foundation → surfaces.)**

---

## Опционально (раздел Risks исходного промпта; не в минимальном PR checklist спринт-промпта)

- [ ] Метрика `tg_watchlist_matches_total` с лейблом `score_bucket` (например `0.6-0.7`, `0.7-0.8`, `0.8+`). **(karpathy-like: замкнутый цикл наблюдаемости для калибровки threshold без blind LLM-tuning.)**
- [ ] Ошибки доставки `Bot.send_message` (в т.ч. «Chat not found»): в `notify` не валить pipeline; при невозможности доставить — **soft-disable** интереса (`is_active = false`) + лог (см. таблицу Risks в спринт-промпте). **(karpathy-like: деградация канала доставки не ломает living-KB loop для остальных.)**
- [ ] В описании tool `subscribe_watchlist` (MCP/bot) кратко предупредить о возможной **серии уведомлений** при первом подключении канала / backfill (как в Risks спринт-промпта). **(karpathy-like: честный контракт с пользователем при controlled assimilation.)**

---

## Связанные документы

- Roadmap karpathy-like / Living KB (волны, принципы, что вне ближайших PR): [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md).
- Полный план шагов, риски, rollback: [`START_PROMPT_SPRINT_F11.md`](START_PROMPT_SPRINT_F11.md).
- Старт **следующей** сессии (дожим PR, karpathy-like контекст, хвост после F11): [`START_PROMPT_NEXT_SESSION_F11.md`](START_PROMPT_NEXT_SESSION_F11.md).
