# Parity Decision Tracking — observations log для Wave 1 step 3

**Назначение:** лёгкий журнал, в который складываются observations,
suspected priority candidates и signals по теме «MCP/API/CLI Surface
Parity» (Wave 1 step 3 audience-driven roadmap'а) **по мере прохождения
Wave 1 step 1 и step 2**. Журнал даёт планирующей сессии для step 3
готовый набор отметок вместо чтения 68K-prep'а с нуля.

**Дата создания:** 2026-05-03 (в окне ожидания Session H, по итогам
обсуждения двух развилок A vs B vs C для parity-package choice).

**Status (2026-05-22 post-S3):** **Wave 1 step 3 execution merged**
([PR #89](https://github.com/AlexEfimov/TG_parser/pull/89) `a30abd5`).
**P-1 / P-2 / ENH-9 / BUG-022 closed** in step 3 main sprint. **O-3 +
BUG-015 closed** in step 3.1 (branch `fix/wave1-step3-1-mcp-dispatch-2026-05-22`;
ADR 0007 **Accepted**,
[`START_PROMPT_SPRINT_WAVE1_STEP3_1_2026-05-22.md`](START_PROMPT_SPRINT_WAVE1_STEP3_1_2026-05-22.md).
Execution sub-session pending user review. Step 3 Phase C deploy +
24h watch: [`WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md`](WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md).

**Не sprint prompt**, **не decision-document** — observations only.

**Когда использовать:**

- При работе любого Wave 1 step 1 / step 2 sprint'а — если замечаете
  «бесит, что нет X через MCP/API/Bot/CLI», **запишите сюда**, не в
  голове.
- Перед планирующей сессией Wave 1 step 3 — пробежать журнал, выбрать
  пакет(ы), удалить устаревшие observations.
- При появлении внешнего user'а с «как мне сделать X через Y» — тоже
  сюда.

**Что НЕ делает:**

- НЕ замещает [`PLANNING_SURFACE_COVERAGE_PARITY_PREP_2026-05-02.md`](PLANNING_SURFACE_COVERAGE_PARITY_PREP_2026-05-02.md)
  (полная inventory + матрица — там).
- НЕ принимает решений о scope step 3 — это задача планирующей сессии.
- НЕ описывает технические детали реализации — это в sprint prompt'е,
  который будет произведён планирующей сессией.

---

## 1. Pre-references (initial guesses на 2026-05-03)

Эти **suspected priority candidates** зафиксированы до старта Wave 1
step 1, на основе уже известного аудита из
[`PLANNING_SURFACE_COVERAGE_PARITY_PREP_2026-05-02.md` § 4](PLANNING_SURFACE_COVERAGE_PARITY_PREP_2026-05-02.md)
и audience-driven фильтра из
[`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 5.1](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md).
Каждая запись — **гипотеза**, не commitment.

### P-1. Watchlist HTTP API parity (F11 → API)

- **Surface gap:** F11 (subscribe / list / unsubscribe / get-matches)
  доступен через MCP / Bot / CLI — но **НЕ через HTTP API**.
- **Audience driver:** A4 (AI Agent Builder) — внешний агент через
  плоский HTTP проще интегрирует, чем MCP-stdio для serverless / web.
- **Косвенная польза:** A5 (journalists) тоже выигрывают, если есть
  thin web-обёртка над watchlist (Stage 3 hosted scenario из
  monetization § 5.5).
- **Risk если выбрать:** F4-B Core может добавить `workspace_id` в
  watchlist subscription → API контракт придётся пересматривать.
  Mitigation — делать step 3 **после** step 2 (что и так в плане).
- **Confidence:** medium-high.

### P-2. Digest HTTP API parity (F6 → API)

- **Surface gap:** аналогично P-1 — F6 digest доступен MCP / Bot / CLI,
  не API.
- **Audience driver:** A4 (для programmatic подписки) + A6 (для curator
  workflow «опубликовать digest по schedule в свой канал» — Wave 1 step
  4 shareable-digest enabler).
- **Сцепка с step 4:** shareable digest (Wave 1 step 4) расширяет F6
  через `publish_to_channel=...` — если параллельно открывать API
  endpoint, лучше делать одной волной, чтобы API сразу включал new
  shape.
- **Risk если выбрать:** меньше, чем P-1 — digest сейчас полностью
  user-scoped, workspace integration отложена в Q8 (skip-in-MVP).
- **Confidence:** medium-high.

### P-3. Topics / Channels read API enrichment

- **Surface gap:** API не имеет endpoints для list_topics /
  get_topic_details / list_channels — есть только в MCP / CLI / Bot.
- **Audience driver:** A4 (если кто-то хочет построить web-каталог
  поверх API), A2 (Web consumer — но он в `defer` per § 4.2 strategy
  doc).
- **Risk если выбрать:** дублирует логику MCP, увеличивает поверхность
  без явного A4-driver'а (внешний агент через MCP уже это получает).
- **Confidence:** low-medium. **Снижен относительно** SESSION48 P6a
  оценки — audience-driven фильтр показывает, что A4 покрывается MCP,
  а A2 deferred. Если параллельно нет A4-customer, который явно просит
  REST — слабый кандидат.

### P-4. CLI / Bot parity для admin-tools

- **Surface gap:** некоторые admin-функции (например `link-topics`,
  `embed`, F5-C `get_topic_versions` / `force_resummarize`) есть в
  CLI / MCP, но не в Bot.
- **Audience driver:** **никакой** прямой — owner проекта всё это
  делает через CLI/MCP.
- **Confidence:** low. **Не приоритет** до сильного UX-сигнала «не
  хочу переключаться в терминал». Анти-паттерн: mass parity ради
  parity.

### P-5. `delete_user` отсутствует в MCP

- **Surface gap:** `delete_user` есть только в API.
- **Audience driver:** **никакой** немедленный — admin operation,
  rarely needed.
- **Confidence:** very low. Может попасть в любой mini-cleanup PR,
  не достоен sprint'а.

---

## 2. Шаблон для добавления observation

Каждая новая запись — отдельный H3-блок в § 3, по этому шаблону:

```markdown
### O-N. Краткое название observation

- **Дата:** YYYY-MM-DD
- **Контекст:** в каком sprint'е / при каком действии замечено
- **Surface gap:** конкретный gap (например «watchlist subscription
  не принимает workspace_id из MCP, хотя F4-B Core добавил workspace
  scoping в search/ask»)
- **Audience driver:** A1 / A4 / A5 / A6 / другое — кто и зачем хочет
- **Связь с pre-references:** уточняет / усиливает / противоречит P-N
- **Action для planning:** что предлагается обсудить
- **Confidence:** low / medium / high
```

Отдельный observation для **observations, противоречащих
pre-references** (например «P-1 не нужен, потому что внешний агент
работает только через MCP») — пишется тем же шаблоном с пометкой
`Status: contradicts P-N`.

---

## 3. Журнал observations

### O-1. Atomic `move_workspace_source` — defer до signal'а

- **Дата:** 2026-05-03
- **Контекст:** deep-dive Q4 для F4-B Core (см.
  [`PLANNING_F4B_WORKSPACES_PREP.md` § 4 Q4 «Refined decisions»](PLANNING_F4B_WORKSPACES_PREP.md)).
  В F4-B Core MVP перенос канала между workspaces одного user'а — это
  два non-atomic вызова: `remove_workspace_source(from_ws, ch)` +
  `add_workspace_source(to_ws, ch)`. Между ними канал может оказаться
  «вне» обоих workspaces при network/process crash.
- **Surface gap (potential):** atomic `move_workspace_source(channel_id,
  from_ws, to_ws)` — не существует ни в MCP, ни в API, ни в CLI, ни в
  Bot. По F4-B Core MVP — **сознательно не планируется** (см. Q4
  refined decision).
- **Audience driver:** A1 (owner) + A4 (AI agent builder) — если у user
  workflow часто включает «реорганизацию» каналов между темами (например
  при перепланировании структуры knowledge base).
- **Связь с pre-references:** дополняет pre-references — это **новый
  candidate P-6** (suspected, very low confidence сейчас). Не противоречит
  P-1..P-5.
- **Action для planning Wave 1 step 3:** проверить, накопились ли
  evidence «move случается часто в production». Если да — promote до
  P-6 active; если нет (по дефолту) — defer в Wave 2 / удалить из
  consideration.
- **Confidence:** very low (preemptive flag, не основан на реальном
  pain-driven evidence).

### O-2. BUG-007 fuzzy-suggestion не срабатывает на status-check path

- **Дата:** 2026-05-06
- **Контекст:** Session I post-deploy Telegram smoke § 5.4. Реальный
  диалог на проде:

  ```
  User: покажи статус AgeMenagment   ← typo: Mena vs Mana
  Bot:  Канал "AgeMenagment" не найден или ещё не обработан.
                              ↑ нет suggestion «возможно, имелся в виду 'AgeManagment'?»
  ```

  При этом BUG-007 closure (Session F, PR #44 / `88e4337`) добавил
  `_build_no_results_suggestion` в `tg_parser/bot/tools.py` через
  `difflib.get_close_matches` с cutoff. Для read-tool'ов
  (`list_topics`, `search`, `ask_question`) suggestion работает —
  убедились в Session I integration tests.
- **Surface gap (potential):** suggestion logic не охватывает
  status-check pathway. Возможные causes (требуют диагностики):
  - (a) `_exec_get_pipeline_status` или эквивалент status-tool не
    интегрирован с `_build_no_results_suggestion` / `available_channel_ids`
  - (b) Gemini agent для status-query формулирует ответ из tool result
    без attaching suggestion (LLM-formatting bypass)
  - (c) Cutoff threshold (`_NO_RESULTS_FUZZY_CUTOFF`) недостаточно
    мягкий для 1-letter typo — однако это маловероятно (typo на 1
    символ обычно проходит default cutoff 0.6+)
  - (d) Status-check идёт через read-tool который **не возвращает
    `available_channel_ids`** (это вернётся из BUG-007 audit)
- **Audience driver:** A1 (owner) и A6 (curator) — UX improvement;
  consistency между read-tools. Низкий driver, но **smoke-quality
  signal** что BUG-007 fix не покрыл весь scope.
- **Связь с pre-references:** не connected directly с P-1..P-6 (это
  не parity gap между surface'ами, а **internal consistency gap
  внутри bot read-tools**). **Может быть переклассифицирован** в
  обычный TD / BUG если симптом подтверждается, и **не относится к
  Wave 1 step 3 parity scope**.
- **Action для planning Wave 1 step 3:** **probably не для step 3**
  — это intra-surface consistency, не cross-surface parity. Скорее
  кандидат на:
  1. Filed as BUG-013 в `BUG_LOG.md` (если воспроизводится) — мелкая
     UX improvement в любой следующий bot-touch sprint
  2. Audit pass в Session J (~5 мин): `rg -n "не найден|not found"
     tg_parser/bot/tools.py | rg -v _build_no_results_suggestion` —
     найти все error pathways без suggestion attach. Если их 1–2 —
     opportunistic fix в Session J. Если 5+ — отдельный mini-sprint.
- **Confidence:** low (single observation; root cause not diagnosed).
  **Re-classification likely** при первом deeper look — переедет в
  BUG_LOG как simple TD candidate.

### O-3. MCP write-tool asymmetry (`trigger_topicization` / `trigger_link_topics` CLI-only)

- **Status (2026-05-22):** ✅ **Closed** in Wave 1 step 3.1 — MCP tools
  `trigger_topicization` and `trigger_link_topics` dispatch via
  `POST /api/v1/pipeline/trigger` (same contract as `trigger_pipeline`).
- **Дата:** 2026-05-15
- **Контекст:** 2026-05-15 Claude (Anthropic) MCP testing session
  (snapshot landed in PR #74 — see
  [`docs/notes/mcp_testing/2026-05-15_claude_session/02-enhancements.md`](mcp_testing/2026-05-15_claude_session/02-enhancements.md)
  § ENH-1, § ENH-2, § O-1 plus
  [`03-investigation-log.md` § Phase 5](mcp_testing/2026-05-15_claude_session/03-investigation-log.md)).
  External tester attempted the «add channel → topicize → link-topics»
  workflow end-to-end through MCP and found it aborts at stage 2:
  topicization и cross-channel linking доступны только через CLI
  внутри контейнера `tg_parser`, через MCP их вызвать невозможно.
- **Surface gap (potential):** MCP surface экспонирует ~30 read tools
  (`list_*`, `get_*`, `search_*`, `ask_question`, ...) и ~5 write
  tools (`add_channel`, `subscribe_*`, `create_workspace`,
  `trigger_pipeline`). Notable gaps: `trigger_topicization` и
  `trigger_link_topics` отсутствуют, несмотря на тривиальный
  conceptual mapping в существующие CLI subcommands `tg-parser
  topicize` / `tg-parser link-topics`. Same architectural concern как
  BUG-015 (cross-container dispatch from `tg_parser_mcp` container —
  see § Active bugs § BUG-015 в [`BUG_LOG.md`](BUG_LOG.md) for the
  full root-cause walk).
- **Audience driver:** A1 (owner) + A4 (AI agent builder) — оба
  завязаны на «всё через MCP» workflow promise; необходимость
  SSH-иться в контейнер для administrative operations breaks the
  unified-surface contract. **Pain evidence:** 1 testing session
  (Claude 2026-05-15) — operator had to drop to CLI / SSH for
  topicization workflows even when MCP was the documented entry point;
  see [operational-runbook § 2 + § 4](mcp_testing/2026-05-15_claude_session/04-operational-runbook.md).
- **Связь с pre-references:** усиливает P-1 / P-2 (HTTP API parity для
  F11 / F6) — обнаруживает что **MCP** surface тоже имеет parity gaps,
  не только HTTP API. Не противоречит P-3 / P-4 / P-5. **Promotion
  candidate:** может быть переведён в active candidate (предположительно
  P-7) если ADR 0007 подписан и BUG-015 fix-sprint scheduled.
- **Action для planning Wave 1 step 3:** **defer to Wave 1 step 3.1**
  (post step 3 main sprint) — bundle с BUG-015 / BUG-016 architectural
  fix per parent decision Q7. Promotion to active scope **conditional
  on ADR 0007** (MCP↔scheduler dispatch contract). Без ADR 0007 даже
  точечный фикс `trigger_topicization` структурно невозможен,
  поскольку упирается в ту же cross-container dispatch gap, что и
  BUG-015 — нет общего канала связи между `tg_parser_mcp` и
  `tg_parser` контейнерами для one-shot job dispatch.
- **Confidence:** medium (single testing session, но с conceptual
  walk-through + cross-evidence из investigation log § Phase 5 +
  § Phase 6).
- **Note on numbering:** не путать с `O-1` в исходном MCP-testing
  report ([`02-enhancements.md` § O-1](mcp_testing/2026-05-15_claude_session/02-enhancements.md))
  — тот документ повторно использовал label `O-1` для того же
  finding, но в каноничной нумерации `PARITY_DECISION_TRACKING.md`
  `O-1` — это **atomic `move_workspace_source` observation** (см. § 3
  O-1 выше). Эта запись — `O-3` в каноничной нумерации трекера.

---

## 4. Когда триггерить планирующую сессию для step 3

По audience-driven roadmap'у — **после Wave 1 step 2 (F4-B Core)
DONE**. До этого момента — только пополнение журнала.

Дополнительные триггеры для **раннего старта** step 3 (если случится):

- Внешний user явно просит конкретный gap из pre-references (P-1 / P-2
  / P-3 — высокий приоритет в этом порядке).
- Появление новой ADR-decision'и, которая ломает текущий surface
  contract (например, если ADR 0005 phase 2 приведёт к переписыванию
  MCP authentication path — parity-pass логичен в той же сессии).
- Регрессия parity surface'а (если случайно сломается какой-то
  существующий tool в одном из surface'ов — fix может расшириться
  до parity-pass).

Триггеры для **отсрочки** step 3 за пределы Wave 1:

- Если step 1 / step 2 затянутся больше плана (~2x от estimate) —
  переоценивать целесообразность step 3 vs ранний переход в Wave 1.5
  dogfooding для измерения, что реально болит.
- Если в журнале накопилось 0 observations за весь Wave 1 step 2 —
  сильный signal, что parity не критичен, можно отложить.

---

## 5. Удаление этого файла

Когда Wave 1 step 3 sprint завершён и parity-волна landed —
этот файл либо архивируется
(`PARITY_DECISION_TRACKING_<date>_archived.md` со ссылкой на sprint
prompt), либо удаляется. На усмотрение step 3 планирующей сессии.

Альтернатива: если step 3 отложен за пределы Wave 1 — файл остаётся
активным и продолжает пополняться. Re-purpose возможен под Wave 2A
(A4 AI integrators) parity scope.

---

## 6. Связанные документы

| Документ | Зачем |
|----------|-------|
| [`PLANNING_SURFACE_COVERAGE_PARITY_PREP_2026-05-02.md`](PLANNING_SURFACE_COVERAGE_PARITY_PREP_2026-05-02.md) | Полная inventory 49 функций × 4 surface, gap-матрица, 6 кандидатов parity-пакетов. **Основной reference**. |
| [`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 5.1](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md) | Wave 1 step 3 — место step 3 в общем sequence. Audience filter (A1, A4, A5, A6). |
| [`PLANNING_F4B_WORKSPACES_PREP.md` § 4](PLANNING_F4B_WORKSPACES_PREP.md) | Q1–Q8 для F4-B; Q2 (workspace identity) и Q7/Q8 (F11/F6 integration) определят shape parity-пакета. |
| [`docs/MCP_AGENT_GUIDE.md`](../MCP_AGENT_GUIDE.md) | Текущее positioning MCP-surface для AI integrators. |
| [`docs/architecture.md` § Phase 3C](../architecture.md) | Прецедент явного by-design asymmetry (agents observability — только CLI / API). |

---

## 7. История

| Дата | Изменение |
|------|-----------|
| 2026-05-03 | Первая версия. Создана в окне ожидания Session H по итогам обсуждения «как поступить с parity-package choice — A (defer) vs B (narrow now) vs C (lightweight tracking)». Выбран compromise C: pre-references P-1..P-5 на основе аудита 2026-05-02 + шаблон + пустой журнал, который будет пополняться по мере прохождения Wave 1 step 1 / step 2. |
| 2026-05-03 | § 3 Журнал — добавлен **O-1 atomic `move_workspace_source` defer до signal'а** как первая запись. Источник: deep-dive Q4 для F4-B Core, где зафиксировано что MVP не включает atomic move tool. Demonstrates intended use of journal как pre-emptive flag для будущих Wave 1 step 3 / Wave 2 considerations. |
| 2026-05-06 | § 3 Журнал — добавлен **O-2 BUG-007 fuzzy-suggestion gap на status-check pathway**. Источник: Session I post-deploy Telegram smoke (`покажи статус AgeMenagment` → «не найден» без suggestion). Likely re-classification как BUG-013 / TD после диагностики; не relevant для step 3 parity scope (intra-surface consistency, not cross-surface). |
| 2026-05-15 | § 3 Журнал — добавлен **O-3 MCP write-tool asymmetry (`trigger_topicization` / `trigger_link_topics` CLI-only)**. Источник: 2026-05-15 Claude (Anthropic) MCP testing session (snapshot landed in PR #74; derived actions in this PR). Pain evidence: external testing run had to drop to CLI / SSH for `topicize` и `link-topics` workflows despite using MCP as the entry point. Same architectural concern как BUG-015 (cross-container dispatch from `tg_parser_mcp`). Confidence: medium (single testing session). Promotion to active scope **conditional on ADR 0007** (MCP↔scheduler dispatch contract). Defer to **Wave 1 step 3.1** sprint per parent decision Q7 — bundle with BUG-015 / BUG-016 architectural fix. Note on numbering: `02-enhancements.md` re-used the `O-1` label for this same finding; в каноничной нумерации трекера это **O-3** (`O-1` зарезервирован за atomic `move_workspace_source`). |
