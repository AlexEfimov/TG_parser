# Планировочная prep — Next Karpathy-like contract (post Wave A/B/C)

**Назначение:** prep-документ для **будущей** планирующей сессии,
которая зафиксирует следующий Karpathy-like-контракт после закрытия
Living-KB (волны A/B/C, 2026-04-26). Этот файл — НЕ план, НЕ решение.
Он собирает контекст, кандидатов, открытые вопросы и criteria для
приоритезации, чтобы планирующая сессия начиналась не с пустого листа.

**Дата подготовки prep:** 2026-05-02 (после Session G closure, ADR 0005,
ADR 0006).

**Когда использовать:** в момент, когда команда (a) завершит Session H
(BUG-011 read-context-preservation) или эквивалентный текущий
bug-fix-цикл, (b) явно решит «возвращаемся к feature-roadmap'у».
До тех пор — этот документ остаётся справочным.

**Что должна произвести планирующая сессия:**

1. Зафиксированный приоритетный кандидат (или комбо) для следующего
   контракта.
2. Полный спринт-промпт по образцу [`START_PROMPT_SPRINT_F5C.md`](START_PROMPT_SPRINT_F5C.md)
   (pre-flight, шаги, gotchas, риски, PR-чеклист).
3. Обновление [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md)
   § «Next contract — TBD» → конкретный заголовок с ссылкой на новый
   спринт-промпт (формат повторяет § «2026-04-26 — Contract closed»).
4. Запись decision-log в `docs/notes/REVIEW_*` или эквивалентном
   артефакте о том, **почему** выбран этот кандидат, а не другие.

**Что планирующая сессия делать НЕ должна:**

- Реализовывать код (это делается отдельным спринтом).
- Изменять ADR 0006 (фиксирует инварианты, не roadmap).
- Принимать решения, нарушающие принципы ADR 0006 без явного флага
  «исключение, см. <reasoning>».

---

## 1. Контекст: где сидит «Next contract» в общей траектории

| Источник | Что говорит |
|----------|-------------|
| [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) § «2026-04-26 — Contract closed» | Living-KB-контракт (Waves A + B + C) закрыт коммитами `c1c9f35` (F11), `473f107`+`53f72ef` (F5-C), TD-01..TD-04 (Phase 1). 24h F5-C deploy-watch verdict GREEN ([`F5C_24h_post_watch.md`](../runbooks/post_watch_reports/2026-04-27_F5C_24h_post_watch.md)). |
| [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) § «Next contract — TBD» | Явный placeholder без содержания: «не выдумывать scope без планирующей сессии», «прийти с открытыми вопросами», список кандидатов для контекста. |
| [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) § «Волна D — Данные и шум» | F5-B (near-duplicate dedup) + F11 P2 (`notify_mode=batch/silent`) + threshold calibration — все три в Wave D, но без приоритезации. |
| [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) § «Волна E — Граф и retrieval+» | Graph-assisted retrieval — после F5-C stabilization, отдельным спринтом. Currently `TopicLink` stored, `get_related_topics` works. |
| [`docs/adr/0006-karpathy-like-living-kb-principles.md`](../adr/0006-karpathy-like-living-kb-principles.md) | Нормативные 7 принципов; новый контракт обязан проходить 7-checklist (см. § «Применение принципов к будущим фичам»). |
| [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) сводная таблица L14–28 | F1, F4-B, F7, F9 phase 2/3, F10, F12 — другие feature-кандидаты, **не** в Wave D/E, но потенциально могут быть выбраны как «параллельный трек». |
| [`REVIEW_2026-04-26_MERGED_PLAN.md`](REVIEW_2026-04-26_MERGED_PLAN.md) | Post-Living-KB audit; рекомендация — debt-fix sprint **before** new feature wave. Phase 1/2/3 debt-fix prompts уже landed. |
| [`docs/adr/0005-bot-llm-provider-flexibility.md`](../adr/0005-bot-llm-provider-flexibility.md) | Связанный artifact — runbook draft `docs/runbooks/BOT_LLM_FALLBACK.md` остаётся не созданным; может быть сложен в текущий цикл prep'ов. |

> **North star одной строкой:** Living-KB-контракт закрыт; следующая
> волна должна **либо** добивать noise/quality (Wave D) **либо** строить
> next-level retrieval поверх стабилизированной базы (Wave E). Выбор
> определяется тем, что именно мешает product-experience сейчас (это и
> есть главный open question).

---

## 2. Три первичных кандидата (по roadmap)

### Кандидат 1 — F11 Phase 2: `notify_mode=batch/silent` + threshold calibration

**Что входит:**

- Расширение [`WatchInterest.notify_mode`](../../tg_parser/domain/models.py)
  с текущего default `instant` на `{instant, batch, silent}`. `batch`
  использует существующую digest-инфраструктуру (F6) — interest
  агрегируется в плановый дайджест вместо instant push. `silent` —
  пишет в `watch_matches`, но не push'ит, для post-hoc просмотра через
  MCP/Bot/CLI.
- Threshold calibration: использовать собранную production-data из
  `tg_watchlist_score` histogram (TD-02 metrics surface уже есть) для
  обоснования смены default 0.6 → реальное оптимальное значение.
- MCP/Bot/CLI surface: `subscribe_watchlist` принимает
  `notify_mode` parameter; `list_watchlists` возвращает его в payload.

**Зависимости (все DONE):**

- F11 MVP (commit `c1c9f35`).
- TD-02 metrics surface ([`tg_parser/api/metrics.py`](../../tg_parser/api/metrics.py) L161–198).
- F6 digest infrastructure (`subscribe_digest` / `list_digests` /
  `digest_scheduler`).

**Karpathy-like check (ADR 0006):**

| # | Принцип | Соответствие |
|---|---------|--------------|
| 1 | Persistent entities | `WatchInterest.notify_mode` — расширение enum, не новая сущность; small surface. |
| 2 | Provenance | Без изменений (matches уже хранят `source_ref`). |
| 3 | Cheap retrieval | Без изменений (hybrid scoring уже без LLM). |
| 4 | Идемпотентность | Дайджест-route reuse'ит F6 idempotency. |
| 5 | Living loop | Hook не меняется; меняется only delivery path. |
| 6 | Observability | `tg_watchlist_delivery_total{outcome}` — добавить outcome `batched` / `silent`. |
| 7 | Graceful degradation | `silent` mode — already graceful по definition. |

**Costs estimate (preliminary):** ~1–1.5 сессии, ~150–250 LOC, ~15–20
тестов (extending F11 surface).

**Concrete signal:** **есть** — production WATCHLIST_SCORE histogram
данные собраны с момента TD-02 deploy. Можно посмотреть реальное
распределение и обосновать смену threshold цифрами.

**Risks (preliminary):**

- F6 digest и F11 batch — два разных concept'а delivery; нужно решить
  shape (один digest на interest? на user? на канал?).
- `silent` без UI для просмотра matches — может быть бесполезен;
  требуется новый MCP/Bot tool `list_watch_matches(interest_id)`.

### Кандидат 2 — F5-B: Near-duplicate content dedup

**Что входит:**

- Дополнение к F5-A Phase 3 (exact-hash dedup): использовать embedding
  similarity для near-duplicate detection. Например, два re-post'а с
  минимальной разницей в тексте — sha-256 hash разный, но embedding
  cosine similarity > 0.95.
- Pre-pipeline filter (между ingestion и processing) ИЛИ post-processing
  consolidation — это open question (см. § 4 Open design questions).
- Метрика `tg_dedup_near_duplicates_detected_total{channel_id, method}`
  по аналогии с существующим `tg_dedup_duplicates_detected_total`
  (exact-hash).
- Decision: какой именно threshold (0.95? 0.92? 0.98?) и какая
  similarity-метрика (cosine? L2 normalized?).

**Зависимости (все DONE):**

- F5-A Phase 3 (`content_hash` field в `ProcessedDocument`,
  `tg_dedup_duplicates_detected_total` counter).
- pgvector index на `embeddings` table (используется для search).
- Embedding pipeline стабилен.

**Karpathy-like check (ADR 0006):**

| # | Принцип | Соответствие |
|---|---------|--------------|
| 1 | Persistent entities | Новая таблица `near_duplicate_links(source_ref_a, source_ref_b, similarity, detected_at)` ИЛИ flag в существующих? — open question. |
| 2 | Provenance | Both source_ref's сохраняются; trace «почему этот документ скрыт» возможен. |
| 3 | Cheap retrieval | Embedding similarity — это keyword-cheap (на уровне dot product), не LLM. ✓ |
| 4 | Идемпотентность | Re-run pipeline не должен пересчитывать all-vs-all; нужен incremental matching против last-N документов канала. |
| 5 | Living loop | Hook между ingestion и processing ИЛИ post-processing — open question. |
| 6 | Observability | Counter + histogram similarity-distribution для калибровки threshold. |
| 7 | Graceful degradation | Если embedding service down — fallback на exact-hash only (что уже работает). ✓ |

**Costs estimate (preliminary):** ~1.5–2 сессии (per FUTURE_FEATURES F5-B
estimate), ~300–500 LOC, ~25–35 тестов.

**Concrete signal:** **частичный** — `tg_dedup_duplicates_detected_total`
показывает exact-dedup rate, но **near-duplicate rate неизвестен**
(нет метрики). Будет полезно сначала добавить **observation-only**
counter (без блокировки), чтобы оценить scale, перед тем как строить
full implementation. Это сама по себе под-задача (~1–2 часа).

**Risks (preliminary):**

- O(N²) similarity comparison наивно — нужен ANN index (pgvector
  `<=>` operator) или sliding-window-of-last-N approach.
- False positives: «похожие новости от двух каналов» vs «один и тот
  же re-post» — где граница? Cross-channel dedup vs intra-channel —
  разные UX.
- Cascade на F11 watchlist: если document A near-duplicate document B,
  и A уже matched watchlist — что делать с B? Skip? Match как новый
  evidence?

### Кандидат 3 — Wave E: Graph-assisted retrieval

**Что входит:**

- Расширение типов `TopicLink.relation_type` (currently — see
  [`tg_parser/domain/models.py`](../../tg_parser/domain/models.py)
  TopicLink class L444). Добавление явных типизированных связей:
  `topic-doc` (тема упоминает документ), `topic-topic` (родственные
  темы), `cross-channel` (одна тема в нескольких каналах).
- Graph traversal в retrieval: `ask_question` или `search_knowledge_base`
  использует topic graph для расширения query (например: пользователь
  спросил про X → найти topic X → расширить до related_topics →
  включить их evidence в RAG context).
- MCP-tool `get_topic_graph(topic_id, depth)` — вернуть subgraph для
  визуализации / навигации.

**Зависимости (все DONE):**

- F5-C TopicCard stable (re-summarization не валит structure).
- TopicLink уже хранится; `get_related_topics` MCP-tool работает.
- F11 watchlist использует `TopicCard` без graph — никаких regressions
  от добавления graph-traversal.

**Karpathy-like check (ADR 0006):**

| # | Принцип | Соответствие |
|---|---------|--------------|
| 1 | Persistent entities | `TopicLink` уже есть; новые `relation_type` enum values — small extension. |
| 2 | Provenance | Каждое link имеет evidence (anchor messages, score). ✓ |
| 3 | Cheap retrieval | Graph traversal — pure SQL/python, без LLM. ✓ |
| 4 | Идемпотентность | Links — append-only ИЛИ UPSERT по `(topic_a, topic_b, relation_type)`? Open question. |
| 5 | Living loop | Hook генерации links — после topicization-tick? После F5-C re-summarize? Open question. |
| 6 | Observability | Метрика graph-density, link-creation rate, retrieval-augmentation outcomes. |
| 7 | Graceful degradation | Fallback на non-graph retrieval, если traversal fails. ✓ |

**Costs estimate (preliminary):** **большой разброс** — minimal MVP
(`relation_type` enum + одна graph-traversal в `ask_question`) ~1.5–2
сессии; full Wave E с graph-density-tuning, A/B-testing качества Q&A
на graph-augmented vs flat retrieval — 3–5 сессий.

**Concrete signal:** **слабый** — нет product-data, что текущий flat
retrieval недостаточен. Hypothetical benefit «лучшее качество Q&A на
сложных multi-channel queries» — не подтверждён measurement'ом.
Кандидат самый research-y и самый высокорисковый из трёх.

**Risks (preliminary):**

- Graph-density blow up: на 100 каналов и 50 тем на канал получаем
  5000 nodes; cross-channel links могут вырасти до 50k+ edges. SQL
  queries деградируют без правильных индексов.
- Auto-link generation требует threshold tuning (когда два topic'а
  достаточно похожи?) — это новый full тюнинг-цикл, аналогичный F11
  threshold.
- Без явного product-driver («пользователи жалуются на X») risk
  build-and-nobody-uses; гипотеза benefit'а не сама-эвидентна.

---

## 3. Альтернативные кандидаты (out of Wave D/E, но могут попасть в комбо)

| ID | Источник | Состояние | Когда уместно включать в next contract |
|----|----------|-----------|----------------------------------------|
| F1 | [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) F1 | Backlog (~2 сессии) | Если выбран кандидат с большим prompt-redesign'ом (например, Wave E с graph-augmented prompts) — F1 (configurable prompts) становится prerequisite. |
| F4-B | [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) F4-B + [`PLANNING_F4B_WORKSPACES_PREP.md`](PLANNING_F4B_WORKSPACES_PREP.md) | Backlog (~2.5–3.5 сессии — revised после F4-A landed) | Если product-driver — пользователь с >20 каналами в разных тематиках, multi-tenant compliance (упомянут в [`ADR 0005 § Re-evaluation triggers`](../adr/0005-bot-llm-provider-flexibility.md) #3), или эквивалентный signal. Prep-документ содержит revised cost estimate (vs original ~2 сессии до F4-A) и 8 open design questions. Только если есть конкретный клиент-сигнал. |
| F9 phase 2/3 | [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) F9 | Phase 1 done; Phase 2/3 backlog | Если security audit / penetration test выявил конкретные находки. **Не** дискреционно — driven by external signal. |
| F10 | [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) F10 | Backlog (1–4 сессии) | Если есть product-driver (мультимодальные каналы с медиа-контентом). Может trigger'ить ADR 0005 opportunistic C (см. ADR 0005 § Opportunistic C). |
| F12 | [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) F12 | Backlog (1–3 сессии) | Если onboarding-friction измеряемо высокий («пользователи не знают, какие каналы добавить»). Driven by user-research, не intuition. |
| TD-bot-confirm-coverage-completeness | Session G prompt § 1.3 G-4 | Backlog (~400 LOC, ~25 тестов) | Если расширяется bot UX до большего количества write-tools или если security-audit требует. Локальный техдолг, не Wave D/E. |
| BOT_LLM_FALLBACK runbook | ADR 0005 «Operational complement» | Запланирован, не создан | Может быть сложен в текущий prep-цикл как side-task (~1 страница, не блокер). |
| BUG-010 / -011 / -012 (open) | [`docs/notes/BUG_LOG.md`](BUG_LOG.md) | Active backlog | Bug-class, не feature; не должны попасть в next-contract scope, идут отдельными bug-fix sprint'ами. |

---

## 4. Open design questions для планирующей сессии

Эти вопросы НЕ имеют «правильного» ответа в текущих документах — их
надо явно обсудить и зафиксировать в результирующем спринт-промпте.

### Q1. Метакритерий приоритезации — что важнее?

Какой signal должен доминировать при выборе из F11 P2 vs F5-B vs Wave E?

- **Product-friction signal:** какая текущая UX-проблема больнее всего
  для существующих пользователей? (Чрезмерные notifications от F11 →
  F11 P2; тонны дубликатов в каналах → F5-B; плохие ответы на сложные
  вопросы → Wave E.)
- **Data-readiness signal:** где у нас уже есть метрики для обоснования
  scope? (F11 P2 — есть `tg_watchlist_score` histogram; F5-B —
  нет near-duplicate counter, нужно добавить отдельным мини-PR
  сначала; Wave E — нет данных вообще.)
- **Karpathy-like coherence:** какой кандидат ближе всего к натуральной
  продолженности Wave A/B/C? (F11 P2 наиболее близок — это direct
  extension Wave B; F5-B — продолжение Wave D; Wave E — переход в
  Wave E, что является «дальним хвостом» по roadmap'у.)
- **Cost / risk balance:** какой кандидат имеет наилучшее
  cost/value соотношение при текущем bus-factor проекта?

### Q2. Combo vs single-candidate?

Можно ли упаковать **два** кандидата в один контракт, по аналогии с
тем, как Living-KB-контракт включал волны A + B + C?

Кандидаты на combo:

- **F11 P2 + F5-B observation-only counter** — оба маленькие, оба
  feedback-driven, и каждый создаёт data-foundation для следующего
  цикла. Risk: scope-creep.
- **F11 P2 + threshold calibration as decision artifact** — почти
  один и тот же scope, но decision-artifact (записать «пересмотрели
  default 0.6 → X») сам по себе value.
- **Wave E minimal MVP + F5-B** — оба средне-сложные; combo может
  растянуть session до 3+ дней. Risk: high.

### Q3. Параллельный track — bug-fixes / тех-долг?

Текущий backlog имеет:

- BUG-010 (TD-bot-source-username-alias) — open issue #50.
- BUG-011 (TD-bot-read-context-preservation) — open Session H pre-flight.
- BUG-012 (cosmetic, mitigated в prompt v1.5.0).
- TD-bot-confirm-coverage-completeness — open backlog.
- ADR 0005 implementation (mini-refactor scope='bot') — pre-planned.

Должен ли next contract быть pure-feature (выбор 1 кандидата из § 2)
или composed-track (1 кандидат + параллельный bug-fix sweep)?

### Q4. Когда «next contract» начинается?

Триггер start'а:

- После Session H (BUG-011) closure?
- После ADR 0005 mini-refactor implementation?
- По временной отметке (например, через 2 недели независимо от bug-fix
  состояния)?
- По метрическому условию (например, `tg_bot_gemini_empty_parts_total` =
  0 за 7 дней подряд = «прод стабилен, можем строить»)?

### Q5. Updated cost estimates after data measurement

Все cost estimates в § 2 — preliminary. Перед фиксацией приоритета
планирующая сессия может потребовать **micro-spike** (~1 час) на
измерение конкретных метрик:

- F5-B: добавить observation-only counter near-duplicate detection,
  собрать 7 дней данных, посмотреть rate.
- F11 P2: запросить production WATCHLIST_SCORE histogram через
  Grafana, посмотреть actual distribution и обоснование смены
  threshold.
- Wave E: запросить (через MCP `ask_question`) test-suite сложных
  multi-channel вопросов; измерить failure rate flat retrieval'а.

---

## 5. Reading list для планирующей сессии

### Обязательные

| Файл | Зачем |
|------|-------|
| [`docs/adr/0006-karpathy-like-living-kb-principles.md`](../adr/0006-karpathy-like-living-kb-principles.md) | 7-checklist обязателен для нового кандидата. Без прохождения checklist'а — кандидат не должен попадать в roadmap. |
| [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) § «2026-04-26 — Contract closed» + § «Next contract — TBD» | История закрытия предыдущего контракта + placeholder для нового. |
| [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) | Альтернативные кандидаты (F1, F4-B, F9, F10, F12) — для combo-вопроса § 4 Q2. |
| Этот файл (PLANNING_NEXT_CONTRACT_PREP.md) | Сами кандидаты § 2 + open questions § 4. |

### Контекстные (по выбранному кандидату)

| Кандидат | Reading |
|----------|---------|
| F11 P2 | [`START_PROMPT_SPRINT_F11.md`](START_PROMPT_SPRINT_F11.md) (исходный F11 spec) + [`tg_parser/api/metrics.py`](../../tg_parser/api/metrics.py) L161–198 (current metrics) + [`tg_parser/services/watchlist_service.py`](../../tg_parser/services/watchlist_service.py) (current implementation) + Grafana dashboard для F11 (если существует) |
| F5-B | [`docs/plans/F5A_PHASE3_IMPLEMENTATION_PLAN.md`](../plans/F5A_PHASE3_IMPLEMENTATION_PLAN.md) (F5-A Phase 3 как foundation) + [`tg_parser/api/metrics.py`](../../tg_parser/api/metrics.py) `DEDUP_DUPLICATES_DETECTED` (L53–58) + [`docs/contracts/processed_document.schema.json`](../contracts/processed_document.schema.json) (`content_hash` field) |
| Wave E | [`tg_parser/storage/sqlalchemy/topic_link_repo.py`](../../tg_parser/storage/sqlalchemy/topic_link_repo.py) + [`tg_parser/domain/models.py`](../../tg_parser/domain/models.py) `TopicLink` class L444 + текущий `get_related_topics` MCP-tool implementation |

### Operational

| Файл | Зачем |
|------|-------|
| [`docs/notes/BUG_LOG.md`](BUG_LOG.md) | Active bugs — для § 4 Q3 (combo с bug-fixes?). |
| [`CHANGELOG.md`](../../CHANGELOG.md) [Unreleased] | Свежие изменения (Session G, Session F, prompt v1.5.0) — что есть в production state на момент планирующей сессии. |
| [`docs/runbooks/F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md) | Deploy-pattern для будущей реализации. |

---

## 6. Format-precedent для результирующего sprint-промпта

После того как планирующая сессия выберет кандидата, она производит
sprint-промпт по образцу:

- **F11 (Wave B):** [`START_PROMPT_SPRINT_F11.md`](START_PROMPT_SPRINT_F11.md)
  — наиболее полный, ~700 строк, с Hidden gotchas, Risks, PR checklist.
- **F5-C (Wave C):** [`START_PROMPT_SPRINT_F5C.md`](START_PROMPT_SPRINT_F5C.md)
  + предшествующий [`START_PROMPT_PLANNING_F5C.md`](START_PROMPT_PLANNING_F5C.md)
  — точный precedent для пары (planning prep → sprint promt).
- **Bug-fix template (для combo с bug-fix):** [`START_PROMPT_FIX_BUG009_EXECUTE_TOOL_GUARD_SESSION_G_2026-05-01.md`](START_PROMPT_FIX_BUG009_EXECUTE_TOOL_GUARD_SESSION_G_2026-05-01.md)
  — bug-fix-specific structure (Pre-flight, Reproduction context, Risks).

---

## 7. История prep-документа

| Дата | Изменение |
|------|-----------|
| 2026-05-02 | Первая версия. Создан после ADR 0006 (формализация karpathy-like) и ADR 0005 (bot LLM flexibility). Три кандидата § 2 + альтернативы § 3 + open questions § 4. Планирующая сессия — TBD по триггеру § 4 Q4. |
| 2026-05-02 | § 3 (альтернативные кандидаты): F4-B обновлён — добавлен cross-link на [`PLANNING_F4B_WORKSPACES_PREP.md`](PLANNING_F4B_WORKSPACES_PREP.md) (отдельный prep-документ для F4-B с revised cost estimate ~2.5–3.5 vs original ~2 сессии после landing F4-A, 8 open questions, 7-checklist). Pure cross-link, не меняет приоритеты § 2. |

---

## 8. Когда удалить этот файл

Когда планирующая сессия пройдёт и produced спринт-промпт landed —
этот prep-документ заменяется ссылкой из roadmap § «Next contract —
TBD» → `## 202X-XX-XX — Next contract: <title>` со ссылкой на
произведённый sprint-промпт. Этот файл может быть либо удалён, либо
переименован в `PLANNING_NEXT_CONTRACT_PREP_<date>_archived.md` для
истории — на усмотрение планирующей сессии.
