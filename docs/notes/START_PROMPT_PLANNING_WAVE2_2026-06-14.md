# START PROMPT — Wave 2 planning (audience-driven scope selection)

**Дата создания:** 2026-06-14 · **Для:** новой (свежей) сессии — **планирование Wave 2** (design-first, не sprint).
**Goal (одной строкой):** провести **чистую planning-сессию** Wave 2 (**НОЛЬ реализации, ноль кода**) и произвести её ГЛАВНЫЙ артефакт — **детальный implementation START PROMPT** для отдельной реализационной сессии (в своём окне): выбрать scope через audience-driven линзу, **для каждой выбранной задачи обсудить и утвердить наиболее эффективный метод решения**, и зашить эти утверждённые методы в implementation-промпт (+ supporting `PLAN_WAVE2_*.md` / decision-log / ADR-stubs, которые его питают). **Эта сессия не пишет ни строчки feature-кода.**

> **Рабочий режим (нормативно, [`AGENTS.md`](../../AGENTS.md)):** branch `main` (HEAD ~`c0e51e2`); `git commit` и деплой — **только по явному запросу пользователя** (этот START_PROMPT и produced PLAN-доки конвенционально остаются untracked/uncommitted, пока пользователь не попросит); `docs/methodology/**` — вне этого workspace (не трогать, не создавать); `pyproject.toml`/`requirements.txt`, код и тесты — **не трогать**. Принцип: **сначала собираем входы → фиксируем стратегические развилки → выбираем метод под каждую задачу → производим план-доки + детальный implementation-промпт**. **Это ПЛАНИРОВАНИЕ, не реализация:** ноль feature-кода, ноль scaffolding, ноль тестов, ноль миграций в этой сессии. Единственный «выход» — документы (design + decision-log + детальный implementation-промпт). Сама реализация — **отдельная сессия в отдельном окне**.

---

## 1. Контекст — где мы сейчас

**Wave 1 закрыт полностью.** Две дорожки закрытия пройдены:

- **Product/ops Wave 1** (audience-driven steps 1–4 + Step 5 ops) — закрыт 2026-06-06, tag `v4.4.0`; aggregate authority [`REVIEW_2026-06-03_WAVE1_DONE.md`](REVIEW_2026-06-03_WAVE1_DONE.md). Дорожка closure описана в [`START_PROMPT_WAVE1_CLOSURE_2026-06-06.md`](START_PROMPT_WAVE1_CLOSURE_2026-06-06.md) (§13 явно называет Wave 2 planning следующим intentional-треком).
- **Tech-debt Wave A–C** — закрыт 2026-06-13/14 по дорожке [`START_PROMPT_WAVE1_TECH_DEBT_CLOSURE_2026-06-12.md`](START_PROMPT_WAVE1_TECH_DEBT_CLOSURE_2026-06-12.md); инвентарь [`WAVE1_TECH_DEBT.md`](WAVE1_TECH_DEBT.md) § A полностью resolved. Verified **zero actionable debt**, кроме **BUG-008** (MCP transport hang — mitigation shipped, root-cause open, явно deferred → Wave 2).

Всё на `main` @ ~`c0e51e2` (последний коммит: MCP read-tool timeout guard BUG-008 mitigation + watchlist delivery alert BUG-060 + Wave 1 doc finalization).

**Почему сейчас Wave 2 planning.** Долг закрыт, продукт стабилен, дорожки Wave 1 явно указывают на planning как следующий шаг. Цель не «начать строить», а **осознанно выбрать, что строить** — на собранных сигналах, а не на интуиции.

**Связь с Wave 1.5 gate.** [`PLAN_WAVE1_5_DOGFOODING_2026-06-06.md`](PLAN_WAVE1_5_DOGFOODING_2026-06-06.md) — это **параллельная живая привычка** сбора сигналов (daily personal use / 2–3 external validators / light market research), которая **гейтит** commit к scope Wave 2 через Decision Point matrix (§5 того дока, mirror [`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 5.3](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md)). Перед фиксацией направления Wave 2 эта сессия **обязана** свериться с актуальным состоянием Wave 1.5 signal-counter'ов (§5/§11 review log dogfooding-дока): сколько distinct-сигналов набрано по 2A / 2B / 2C, сработал ли какой-то threshold, или мы всё ещё в «owner активно использует, никто не растёт» режиме.

---

## 2. Что уже решено vs что должна решить эта сессия

Эта секция заменяет «зафиксированный scope» из sprint-промптов: у planning-сессии scope *открыт by design*. Напоминание: всё ниже решается **на бумаге** — сессия ничего не реализует, она только выбирает и фиксирует.

### Уже решено (не пере-решать)

- **Wave 1 закрыт** (product+ops + tech-debt) — с пруфами/коммитами выше. Не возвращаться к Wave 1 item-ам.
- **Метод выбора scope = audience-driven линза.** Scope Wave 2 выбирается через «какой сегмент A1–A8 это активирует» ([`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md`](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md)), а не feature-driven «что прикольно». Conditional branches уже намечены: **2A** (A4 AI integrators), **2B** (A5/A6 Web consumer), **2C** (A3 team sharing).
- **Karpathy-like инварианты обязательны.** Любой кандидат проходит 7-checklist [ADR-0006](../adr/0006-karpathy-like-living-kb-principles.md) перед попаданием в план.
- **Wave 1.5 — gate, не часть Wave 2.** Сбор сигналов продолжается параллельно; не сворачивать его внутрь этой сессии.
- **Деферы из стратегии остаются deferred по умолчанию** (F7 Billing, F8 Redis/scalability, Web-как-первая-инвестиция, OSS-vs-commercial, A7 compliance) — пока нет triggered-сигнала. См. [`PRODUCT_STRATEGY` § 6 anti-patterns](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md).

### Должна решить эта сессия

- **Audience driver** — под какой сегмент Wave 2 целится в первую очередь (2A / 2B / 2C / «continue dogfooding»), на основании Wave 1.5 signal-state.
- **Тема и scope Wave 2** — какой набор workstream'ов входит в контракт; глубина (одна большая фича vs несколько средних).
- **Какие кандидаты из меню (§3) проходят отбор** и в каком порядке; что остаётся в parking-lot.
- **Судьба отложенных tech-item'ов** — складывать ли gated-score alert / F11 HTTP CRUD / webhook target 2A / BUG-008 root-cause в Wave 2 или держать deferred.
- **Наиболее эффективный метод решения под каждую выбранную задачу** (см. §5) — обсудить альтернативные подходы, выбрать оптимальный, записать обоснование. **Это — ключевая ценность сессии:** именно утверждённые методы переходят в implementation-промпт.

---

## 3. Меню кандидатов (prioritization backlog)

Полный набор workstream'ов на стол приоритезации. Source + GH issue (где есть) + одна строка value/cost. **Это меню, не план** — отбор делает эта сессия через линзу §2 + развилки §4.

| Кандидат | Источник | Issue / ADR | Value / Cost (одной строкой) |
|---|---|---|---|
| **F5-B — near-duplicate dedup** (embedding-similarity поверх F5-A exact-hash) | [`PLANNING_NEXT_CONTRACT_PREP.md` §2](PLANNING_NEXT_CONTRACT_PREP.md) (Кандидат 2); [`ROADMAP` Волна D](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) | — | Меньше мусорных дублей/ложных алертов; ~1.5–2 сессии, ~300–500 LOC. **Signal частичный** — нужен observation-only counter сначала (мини-PR). |
| **Wave E — graph-assisted retrieval** (`TopicLink.relation_type` + graph-augmented `ask_question`) | [`PLANNING_NEXT_CONTRACT_PREP.md` §2](PLANNING_NEXT_CONTRACT_PREP.md) (Кандидат 3); [`ROADMAP` Волна E](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) | — | Лучшее качество Q&A на multi-channel; minimal MVP ~1.5–2 сессии, full 3–5. **Signal слабый**, самый research-y/высокорисковый. |
| **F5-C P2 — evolving topic-summary phase 2** | [`WAVE1_TECH_DEBT.md` §C](WAVE1_TECH_DEBT.md) | [#15](https://github.com/AlexEfimov/TG_parser/issues/15) | Дозревание living-topics; forward-roadmap, scope из issue. |
| **F11 HTTP CRUD** — watchlist CRUD по HTTP API surface | [`WAVE1_TECH_DEBT.md` §C](WAVE1_TECH_DEBT.md) | — | Закрывает parity-gap для A4 (MCP/bot/CLI есть, HTTP нет); вписывается в 2A. |
| **Webhook subscription target** (ADR-0008 polymorphic `target_kind='webhook'` + HMAC + retry) | [`WAVE1_TECH_DEBT.md` §C](WAVE1_TECH_DEBT.md); [`PRODUCT_STRATEGY` §5.4 2A](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md) | [ADR-0008](../adr/0008-subscription-target-model.md) → Wave **2A** | Push-доставка F6/F11 в внешние системы (A4); additive non-breaking enum-extension. |
| **S4 — multilang tokenizer** (multi-language keyword tokenization) | [`WAVE1_TECH_DEBT.md` §C](WAVE1_TECH_DEBT.md) | — | Качество keyword-matching на не-английских каналах; изолированный. |
| **F1 Full** — DB-backed prompts / versioning / A-B testing | [`WAVE1_TECH_DEBT.md` §C](WAVE1_TECH_DEBT.md); [`PLANNING_NEXT_CONTRACT_PREP.md` §3](PLANNING_NEXT_CONTRACT_PREP.md) | — | Prerequisite если выбран кандидат с большим prompt-redesign'ом (напр. graph-augmented prompts). |
| **Gated watchlist score alert** (`semantic_available` label на `WATCHLIST_SCORE` → gated Prometheus rule) | [`WAVE1_TECH_DEBT.md` §C + §A.4 BUG-060](WAVE1_TECH_DEBT.md) | follow-up BUG-060 | Ловит silent degradation semantic-scoring (embedding provider down). Cost: metric/scoring-path change + tests. Explicitly deferred из Wave 1 → Wave 2. |
| **BUG-008 root-cause** — MCP transport hang (mitigation shipped, true client-side timeout fix вне репо) | [`BUG_LOG.md` BUG-008](BUG_LOG.md) | — | Reopen-to-resolve только после reproduced occurrence через новые lifecycle-логи; иначе держать `open`/monitoring. |
| **TD-D-01 — renderer unification** (page 1 LLM-render vs page 2+ deterministic; visual jump) | [`BUG_LOG.md` § TD from Session D](BUG_LOG.md) | [#39](https://github.com/AlexEfimov/TG_parser/issues/39) `tech-debt`+`p1` | Bot UX polish; promote `_format_paginated_list` на page 1 или strengthen prompt contract. |
| **TD-D-02 — pagination_pending coverage** (только в `_exec_list_topics`; др. list-tools не подведены) | [`BUG_LOG.md` § TD from Session D](BUG_LOG.md) | [#40](https://github.com/AlexEfimov/TG_parser/issues/40) `tech-debt`+`p1` | Латентный re-entry BUG-004 на др. surface'ах; применить контракт ко всем paginated read-tools. |
| **TD-D-03 — `_format_tool_result` fallback** (слабый `"✅ Готово"`; новый write-tool без `message` silently degrades) | [`BUG_LOG.md` § TD from Session D](BUG_LOG.md) | [#41](https://github.com/AlexEfimov/TG_parser/issues/41) `tech-debt`+`p1` | Synthesize fallback + contract-test что все write-tools возвращают non-empty `message`. |
| **Conditional-branch фичи (по audience signal)** — 2A: OAuth/rate-limit/schema-versioning/SDK/marketplace; 2B: P6c Web Catalog + P6d Web Chat + public API; 2C: F4-B Sharing (`workspace_members` M2M + roles + audit log + Q6 privacy) | [`PRODUCT_STRATEGY` §5.4](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md) | ADR-0008 (2A webhook) | 2A ~3–5 сессий; 2B ~6–10; 2C ~2.5–3.5 поверх F4-B Core. Выбор гейтится Decision Point matrix. |
| **Альтернативы** (F9 phase 2/3 security, F10 multimodal, F12 onboarding) | [`PLANNING_NEXT_CONTRACT_PREP.md` §3](PLANNING_NEXT_CONTRACT_PREP.md); [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) | — | Только по external/product signal'у (не дискреционно); могут попасть в combo. |

> **NB:** F11 Phase 2 (`notify_mode=batch/silent` + threshold calibration) — **уже DONE** через ADR-0010–0014 (Wave B tech-debt). Не вносить как кандидата; перечислено только чтобы не пере-завести.

---

## 4. Открытые стратегические развилки (resolve в начале сессии)

Это форки, которые planning-сессия **обязана** разрешить и записать в decision-log.

1. **Audience driver.** Какой сегмент ведёт Wave 2 — **2A** (A4 integrators), **2B** (A5/A6 web consumer), **2C** (A3 team), или «continue dogfooding / no new wave»? Решение опирается на **актуальный Wave 1.5 signal-state** (§5/§11 [`PLAN_WAVE1_5_DOGFOODING`](PLAN_WAVE1_5_DOGFOODING_2026-06-06.md)) + Decision Point thresholds (1 = anecdote, 3 = pattern; для 2C — 1 strong ask). Если ни один threshold не достигнут — это *само по себе решение* (continue dogfooding, зафиксировать).
2. **Глубина / форма контракта.** Одна большая фича (напр. полноценный Wave E или 2B Web) vs несколько средних (combo F5-B + dedup-counter + Bot UX TD-D), по аналогии с тем, как Living-KB-контракт паковал волны A+B+C. Risk scope-creep против value «закрыть сегмент целиком».
3. **F5-B dedup vs Wave E graph — что первым** (если выбираем quality/retrieval-трек). F5-B ближе к натуральному продолжению Wave D, дешевле, но signal частичный (нужен counter-мини-PR сначала). Wave E амбициознее и research-y, signal слабый. Какой даёт лучший cost/value при текущем bus-factor?
4. **Складывать ли отложенные tech-item'ы в Wave 2.** Gated-score alert (BUG-060 follow-up), F11 HTTP CRUD, webhook target (2A), BUG-008 root-cause, TD-D-01/02/03 — включить как параллельный hardening-трек в Wave 2 или держать deferred до отдельного сигнала? (Прецедент: Wave 1 шёл product-трек + параллельный tech-debt-трек.)
5. **Как Wave 1.5 сигналы взвешивают решение.** Если owner активно использует, но внешнего роста нет — это толкает к internal-quality треку (F5-B / Wave E / TD-D bot polish), не к публичным 2A/2B. Зафиксировать explicit правило взвешивания: data-readiness signal vs product-friction signal vs karpathy-like coherence vs cost/risk (см. [`PLANNING_NEXT_CONTRACT_PREP.md` §4 Q1](PLANNING_NEXT_CONTRACT_PREP.md)).
6. **Combo vs single-candidate** + **триггер старта реализации** (что считаем «готово начинать спринт»: closed planning-doc? набранный signal-threshold? временная отметка?). См. [`PLANNING_NEXT_CONTRACT_PREP.md` §4 Q2/Q4](PLANNING_NEXT_CONTRACT_PREP.md).

---

## 5. Ядро сессии — выбор наиболее эффективного метода под каждую задачу

**Главная активность planning-сессии — не «что делаем», а «КАК делаем наилучшим образом».** Для **каждой** отобранной Wave 2 задачи (из §3, прошедшей через линзу §2 и развилки §4) сессия обязана:

1. **Выложить альтернативные подходы решения** (минимум 2 варианта метода, где это осмысленно). Примеры реальных развилок метода: F5-B — pre-pipeline filter vs post-processing consolidation; ANN-index (pgvector `<=>`) vs sliding-window-of-last-N; Wave E — append-only links vs UPSERT по `(topic_a, topic_b, relation_type)`, hook после topicization vs после F5-C re-summarize; webhook target — sync push vs queued-retry, где живёт HMAC/retry policy. Опираться на open design questions из prep-доков ([`PLANNING_NEXT_CONTRACT_PREP.md` §4](PLANNING_NEXT_CONTRACT_PREP.md), [`PRODUCT_STRATEGY` §8](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md)).
2. **Выбрать наиболее эффективный** через двойной фильтр: **audience-driven линза** (какой сегмент и насколько это активирует) + **karpathy-like 7-checklist [ADR-0006](../adr/0006-karpathy-like-living-kb-principles.md)** (persistent entities / provenance / cheap retrieval / идемпотентность / living loop / observability / graceful degradation). Cost/risk и текущий bus-factor — tie-breaker.
3. **Записать обоснование** (decision-log): почему этот метод, почему отвергнуты альтернативы, какие контракты/ADR он обязан соблюдать, какие риски и как митигируются.

**Это и есть ценность planning-сессии.** Утверждённые методы — не «идея на потом», а **нормативный вход** для implementation-промпта (§6): реализационная сессия **НЕ переоткрывает** выбор метода, она исполняет утверждённый подход. Поэтому implementation START PROMPT обязан **дословно отражать** approved-методы (chosen approach per task + rationale-ссылка на decision-log) — иначе planning-работа теряется.

> **Прецедент глубины метода:** в [`START_PROMPT_TD_BOT_CONFIRM_COVERAGE_2026-06-13.md`](START_PROMPT_TD_BOT_CONFIRM_COVERAGE_2026-06-13.md) §2 метод зафиксирован ДО кода («полный admin-квартет + три согласованных части: `confirm`-param в декларации + членство в frozenset + executor preview/confirm-паттерн»). Wave 2 implementation-промпт должен давать такую же конкретику метода по **каждой** задаче.

---

## 6. Definition of Done для planning-сессии

Это **planning** DoD — артефакты, не код. **Ноль реализации:** никакого feature-кода, scaffolding, миграций, тестов, изменений `tg_parser/**` / `tests/**`. Любой code-touch → STOP, это не planning. Commit/deploy — только по явному go-ahead пользователя.

### ГЛАВНЫЙ артефакт (обязательный, центральный выход сессии)

- [ ] **Детальный implementation START PROMPT** — `START_PROMPT_SPRINT_WAVE2_<тема>_2026-06-XX.md` — заготовленный для **отдельной реализационной сессии в своём окне**. Это **НЕ skeleton/outline**, а полноценный промпт глубины [`START_PROMPT_TD_BOT_CONFIRM_COVERAGE_2026-06-13.md`](START_PROMPT_TD_BOT_CONFIRM_COVERAGE_2026-06-13.md) / [`START_PROMPT_SPRINT_F11.md`](START_PROMPT_SPRINT_F11.md). По **каждой** выбранной задаче обязан содержать:
  - **Конкретный scope** — что входит / что явно вне scope.
  - **Утверждённый метод/подход** (из §5) — выбранное решение + одна строка «почему» (rationale-ссылка на decision-log). Реализационная сессия НЕ переоткрывает выбор метода.
  - **Якоря в коде / затрагиваемые модули** — конкретные файлы/функции с line-anchors (по образцу §3 confirm-coverage промпта: `tg_parser/...:L...`).
  - **Контракты / ADR к соблюдению** — какие JSON-schema ([`docs/contracts/`](../contracts/)) и ADR (existing + новые stubs) нельзя нарушать.
  - **Test strategy** — что покрыть (happy / edge / negative), прецедент по объёму, baseline-прогон `TEST_POSTGRES=1 .venv/bin/python -m pytest -q` вне sandbox.
  - **DoD реализационной сессии** — self-review тестов, ruff чисто, prompt-version bump если задеты bot/MCP write-surface, закрывающие строки в BUG_LOG.
  - **Стартовая реплика для implementation-сессии** (copy-paste) — отдельная от §8 этого дока.

### Supporting артефакты (питают главный промпт)

- [ ] **`PLAN_WAVE2_<тема>_2026-06-XX.md`** в `docs/notes/` — выбранный audience driver, scope (что входит / что parking-lot), sequencing, karpathy-like 7-checklist по выбранным кандидатам, cost estimate.
- [ ] **Decision-log** — для каждой развилки §4 **и для каждого выбора метода §5**: выбор + обоснование + отвергнутые альтернативы + явная ссылка на Wave 1.5 signal-state. В `PLAN_WAVE2_*` или отдельном `REVIEW_*`/`DECISION_POINT_*` доке.
- [ ] **ADR-stub(s)** где Wave 2 вводит новое архитектурное решение (webhook target → дозреть [ADR-0008](../adr/0008-subscription-target-model.md); новый ADR под graph-retrieval / dedup-схему). Stub = Context + Decision-draft + Status `Proposed`, не полный ADR.
- [ ] **ROADMAP cross-link** — наметить (не обязательно применять) обновление [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) § «Next contract — TBD» → конкретный заголовок Wave 2.

---

## 7. Артефакты для контекста (прочитать в начале)

**Стратегия / метод:**
- [`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md`](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md) — §3 сегменты A1–A8, §5.3 Decision Point matrix, §5.4 conditional branches 2A/2B/2C, §6 anti-patterns.
- [`PLAN_WAVE1_5_DOGFOODING_2026-06-06.md`](PLAN_WAVE1_5_DOGFOODING_2026-06-06.md) — §5 Decision Point matrix + §7 exit criteria + §11 review log (signal-state gate).
- [`docs/adr/0006-karpathy-like-living-kb-principles.md`](../adr/0006-karpathy-like-living-kb-principles.md) — 7-checklist для кандидатов.

**Меню кандидатов:**
- [`PLANNING_NEXT_CONTRACT_PREP.md`](PLANNING_NEXT_CONTRACT_PREP.md) — §2 (F5-B / Wave E + F11 P2 done), §3 альтернативы, §4 open design questions, §5 reading list.
- [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) — Волна D (F5-B), Волна E (graph retrieval), «Next contract — TBD».
- [`WAVE1_TECH_DEBT.md`](WAVE1_TECH_DEBT.md) — §C forward-roadmap (F5-C P2 #15, F11 HTTP CRUD, S4 multilang, F1 Full, webhook 2A ADR-0008, gated-score alert), §B accepted-by-design (НЕ пере-заводить).
- [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) — полный backlog (F9/F10/F12 альтернативы).

**Backlog of record / долг:**
- [`BUG_LOG.md`](BUG_LOG.md) — BUG-008 (deferred, mitigation shipped 2026-06-14, root-cause open); § «TD from Session D» TD-D-01/02/03 ([#39](https://github.com/AlexEfimov/TG_parser/issues/39) / [#40](https://github.com/AlexEfimov/TG_parser/issues/40) / [#41](https://github.com/AlexEfimov/TG_parser/issues/41)).

**Закрытие Wave 1 (доказательная база «почему сейчас»):**
- [`REVIEW_2026-06-03_WAVE1_DONE.md`](REVIEW_2026-06-03_WAVE1_DONE.md) — aggregate authority (§13 «после закрытия»).
- [`START_PROMPT_WAVE1_CLOSURE_2026-06-06.md`](START_PROMPT_WAVE1_CLOSURE_2026-06-06.md) + [`START_PROMPT_WAVE1_TECH_DEBT_CLOSURE_2026-06-12.md`](START_PROMPT_WAVE1_TECH_DEBT_CLOSURE_2026-06-12.md) — дорожки closure.

**Format-precedents для produced артефактов:**
- **Главный артефакт (детальный implementation-промпт) — эталон глубины:** [`START_PROMPT_TD_BOT_CONFIRM_COVERAGE_2026-06-13.md`](START_PROMPT_TD_BOT_CONFIRM_COVERAGE_2026-06-13.md) (зафиксированный метод §2 + якоря в коде §3 + развилки §4 + DoD §5 + стартовая реплика §7) и [`START_PROMPT_SPRINT_F11.md`](START_PROMPT_SPRINT_F11.md) (~700 строк: gotchas / risks / PR-checklist).
- **Пара (planning prep → sprint prompt):** [`START_PROMPT_SPRINT_F5C.md`](START_PROMPT_SPRINT_F5C.md) + [`START_PROMPT_PLANNING_F5C.md`](START_PROMPT_PLANNING_F5C.md).

**Рабочий режим:** [`AGENTS.md`](../../AGENTS.md); quality lifecycle — [`docs/quality/AGENT_PLAYBOOK.md`](../quality/AGENT_PLAYBOOK.md).

---

## 8. Стартовая реплика для новой сессии (можно скопировать)

> Начинаем **планирование Wave 2** — это **чистая planning-сессия: ноль кода, ноль реализации**. Её ГЛАВНЫЙ результат — **детальный implementation START PROMPT** для отдельной реализационной сессии (в своём окне), в который зашиты утверждённые здесь методы решения. Прочитай [`docs/notes/START_PROMPT_PLANNING_WAVE2_2026-06-14.md`](docs/notes/START_PROMPT_PLANNING_WAVE2_2026-06-14.md), затем стратегию ([`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md`](docs/notes/PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md) §5.3/§5.4), gate ([`PLAN_WAVE1_5_DOGFOODING_2026-06-06.md`](docs/notes/PLAN_WAVE1_5_DOGFOODING_2026-06-06.md) §5/§11) и меню кандидатов (§3: F5-B, Wave E graph, F5-C P2 #15, F11 HTTP CRUD, webhook 2A ADR-0008, S4, F1 Full, gated-score alert, BUG-008 root-cause, TD-D-01/02/03 #39–41, conditional branches 2A/2B/2C). Wave 1 закрыт полностью (product+ops `v4.4.0` + tech-debt Wave A–C, zero debt кроме deferred BUG-008), всё на `main` @ ~`c0e51e2`. Порядок: (1) сверимся с актуальным Wave 1.5 signal-state; (2) разрешим стратегические развилки §4 (audience driver; глубина контракта; F5-B vs Wave E первым; складывать ли отложенные tech-item'ы; как сигналы взвешивают решение); (3) для **каждой** отобранной задачи **обсудим альтернативные подходы и утвердим наиболее эффективный метод** через audience-driven линзу + karpathy-like 7-checklist (ADR-0006), с записью в decision-log; (4) соберём из утверждённых методов **детальный implementation START PROMPT** (по каждой задаче: scope + утверждённый метод + якоря в коде + контракты/ADR + test strategy + DoD + своя стартовая реплика), глубины [`START_PROMPT_TD_BOT_CONFIRM_COVERAGE_2026-06-13.md`](docs/notes/START_PROMPT_TD_BOT_CONFIRM_COVERAGE_2026-06-13.md). DoD сессии: детальный implementation-промпт (главный артефакт) + supporting `PLAN_WAVE2_*.md` + decision-log + ADR-stub(s) — **без единой строки feature-кода**. Режим: коммит/деплой — только по моему явному запросу; `docs/methodology/**`, `pyproject.toml`/`requirements.txt`, код и тесты не трогать.
