# START PROMPT — Session: F5-C #15 item #5 — Bot tools для topic-history (`get_topic_versions` + `get_topic_history_diff` в `@Tgingest_bot`)

> **✅ LANDED + DEPLOYED (2026-07-24).** Surface-only реализовано: 2 declarations + executors (`_exec_get_topic_versions` / `_exec_get_topic_history_diff`, `bot/tools.py`) + dispatch-map + `bot.yaml` bump `1.9.0 → 1.9.1` (capability #14, L2/L8/L30) + tool-count guards `32 → 34` (`test_bot_tools_v11.py` / `test_bot_tools_v12.py`) + new tests [`tests/test_f5c_bot_topic_history.py`](../../tests/test_f5c_bot_topic_history.py). Backend не тронут; classifier-множества не тронуты. Quality gate: `ruff check/format` clean, `TEST_POSTGRES=1 pytest` = 4003 passed. **Prod (VPS `212.72.189.15`):** PR #355 (`fce2770 → b18c46e`), `docker compose build tg_parser` + re-create `tg_bot` (BUG-078, НЕ restart) → `healthy`, `len(TOOL_DECLARATIONS)==34`; owner-verified manual smoke PASS на темах с историей (`topic:tg:mediamedics:post:13525` и др.). Deploy record: [`F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md).

**Дата:** 2026-07-24 · **Тип:** implementation (surface-only: 2 read-only bot-tool'а поверх уже отгруженных read-path'ов + `bot.yaml` bump + guard update + tests + docs) · **Ветка:** feature-ветка от актуального `main` (напр. `feature/f5c-bot-topic-history`)

**Goal (одной строкой):** дать пользователю смотреть эволюцию темы **прямо из Telegram-бота** — два новых read-only bot-tool'а `get_topic_versions` (аудит-трейл прошлых сводок) и `get_topic_history_diff` (дельта между версиями, по умолчанию genesis → current), зеркалящих уже существующие MCP-инструменты; **backend-логика переиспользуется as-is** (нового кода в сервисах/репозиториях нет).

> **✅ UX-сигнал дан owner'ом (2026-07-24).** F5-C bot-tools изначально гейтились «только при запросе из бота» ([`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) L800). Сигнал получен. **ВАЖНО — это NO-migration, surface-only деплой:** фича лишь **добавляет 2 tool-декларации + executors** в боте поверх уже отгруженных `get_topic_versions`/`get_topic_history_diff` (MCP) и shared-хелперов. **Нет** schema-change, **нет** новых зависимостей, **ADR НЕ нужен** (контраст с topic-digest #3, который добавлял колонки). Deploy = обычный re-create образа (`up -d --no-deps tg_bot`, BUG-078), без `db upgrade`.

> **Рабочий режим (нормативно, [`AGENTS.md`](../../AGENTS.md)):** `git commit` / PR — **только** по явному запросу пользователя (PR = merge-commit + `--delete-branch`). Никаких правок `docs/methodology/**`. `pyproject.toml` / `requirements.txt` — **не трогать** (ADR-0017; новых deps нет). Уважать `docs/adr/` (accepted binding) и `docs/contracts/` (JSON Schema нерушимы). **Не трогать backend read-path** (`TopicCardVersionRepo`, `diff_topic_summaries`, `assert_topic_access`) — только вызывать. **Не трогать MCP/CLI diff-surface** — это лишь bot-паритет.

**Prerequisite SoT (перечитать перед кодом):**
- MCP-эталоны (зеркалить 1:1 по логике): `get_topic_versions` ([`mcp_server.py`](../../tg_parser/mcp_server.py) L2608) + `get_topic_history_diff` ([`mcp_server.py`](../../tg_parser/mcp_server.py) L2674).
- Bot-tool паттерн (declaration + executor + dispatch + visibility): `_exec_get_topic_details` ([`bot/tools.py`](../../tg_parser/bot/tools.py) L2052) + декларация L346.
- Diff-API (#2, building block): [`domain/topic_history_diff.py`](../../tg_parser/domain/topic_history_diff.py) L114 (`diff_topic_summaries`), L56 (`snapshot_from_version`), L74 (`snapshot_from_card`).
- ADR: [ADR-0006](../adr/0006-karpathy-like-living-kb-principles.md) (#1/#5 living-KB), [ADR-0017](../adr/0017-dependency-management-policy.md) (no new deps), [ADR-0018](../adr/0018-topic-card-versions-retention.md) §4 (genesis v1 + last-N present ⇒ TTL-gap = typed not-found, не 500).
- Topic-digest (#3, только что отгружен — сосед по #15): [`START_PROMPT_SESSION_F5C_TOPIC_DIGEST_2026-07-24.md`](START_PROMPT_SESSION_F5C_TOPIC_DIGEST_2026-07-24.md) (стиль-эталон этого документа).

---

## 0. TL;DR

| Step | Действие | Тип |
|---|---|---|
| 1 | **Declarations.** Добавить 2 записи в `TOOL_DECLARATIONS` ([`bot/tools.py`](../../tg_parser/bot/tools.py) L265, форма — как `get_topic_details` L346): `get_topic_versions` (params `topic_id` required, `limit` optional int 1..200 default 10) + `get_topic_history_diff` (params `topic_id` required, `version_a`/`version_b` optional int, default genesis v1 → current). Описания в стиле «Use after get_topic_details…». | code |
| 2 | **Executors.** `_exec_get_topic_versions` + `_exec_get_topic_history_diff` (зеркало `_exec_get_topic_details` L2052): открыть `resummarization_repos()` (даёт `version_repo`), `card = card_repo.get_by_id`; not-found → `{"error": ...}`; **visibility** (intersect `card.sources` с `user.allowed_channel_ids`, как L2070-2072); затем те же вызовы, что в MCP-эталонах (`version_repo.list_by_topic(topic_id, limit)` / `get_two_versions` + `diff_topic_summaries(snapshot_from_version, snapshot_from_card)`). Вернуть тот же dict-shape, что MCP. | code+test |
| 3 | **Dispatch-map.** Зарегистрировать оба executor'а в маппинге name→executor ([`bot/tools.py`](../../tg_parser/bot/tools.py) ~L4590, где `"get_topic_details": _exec_get_topic_details`). | code |
| 4 | **Классификация read-tools (⚠️ НИ В ОДНО из трёх множеств не добавлять — verified review-pass).** Оба tool'а topic_id-based и MCP-shape ⇒ **НЕ** в `_READ_TOOLS_TRACKED_FOR_CONTEXT` (L161 — только channel_id-carrying reads; `get_topic_details` там **отсутствует** намеренно, комментарий L158; D-2 contract [`test_bot_read_context.py`](../../tests/test_bot_read_context.py) L154 требует `channel_id`-свойство у каждого члена). `get_topic_versions` **НЕ** в `_PAGINATED_READ_TOOLS` (L180 — только list-shaped `pagination_pending`; contract-тесты [`test_pagination_contract_tdd.py`](../../tests/test_pagination_contract_tdd.py) L289 / [`test_mcp_pagination_contract.py`](../../tests/test_mcp_pagination_contract.py) L194 требуют fixture + `_paginate_read_result`-shape → сломается MCP-parity). Оба read-only ⇒ **НЕ** в `_WRITE_TOOLS_REQUIRING_CONFIRM` (L110). | code |
| 5 | **`prompts/bot.yaml` + guards.** Добавить capability-строку **#14** в нумерованный список (L15-28: «View how a topic's evolving summary changed / diff versions») — per-tool инвентаря в prompt нет. **Version bump `1.9.0 → 1.9.1` в ТРЁХ синхронных местах** (L2 `# Version:`, L8 `metadata.version`, L30 in-prompt `- Version:`) — **patch, НЕ `1.10.0`:** [`test_f9_phase2_prompt_defense.py`](../../tests/test_f9_phase2_prompt_defense.py) L194 пинит `startswith("1.9")`; tuple-floor [`test_bot_read_context.py`](../../tests/test_bot_read_context.py) L642 (`>= (1,8,0)`) — `1.9.1` зелёный для обоих без правки security-теста. ⚠️ **tool-count guards — ДВА:** `== 32 → == 34` в [`tests/test_bot_tools_v11.py`](../../tests/test_bot_tools_v11.py) **L99** И [`tests/test_bot_tools_v12.py`](../../tests/test_bot_tools_v12.py) **L151** (оба иначе CI красный). | code+docs |
| 6 | **Tests.** Declaration-presence + tool-count guard (34); executor happy-path (versions list / diff genesis→current); not-found → `{"error"}`; **no-access** (visibility, топик вне `allowed_channel_ids`); diff default (genesis→current); TTL-gap missing version → typed not-found (не 500/exception); опц. рендер результата. Зеркало [`test_bot_tools_v12.py`](../../tests/test_bot_tools_v12.py) / [`test_bot_read_context.py`](../../tests/test_bot_read_context.py). | test |
| 7 | **Quality gate.** `ruff check/format` + `TEST_POSTGRES=1 uv run pytest -q` (трогаем bot + repo read-paths). | gate |
| 8 | **Docs.** [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) L800 «Bot tools для F5-C» → DONE; короткая заметка + этот START_PROMPT → «landed» pointer. | docs |
| 9 | **Deploy (NO-migration).** `git pull` → `docker compose build tg_parser` → `docker compose up -d --no-deps tg_bot` (re-create, **НЕ** restart — BUG-078). Smoke: `@Tgingest_bot` отвечает на «покажи историю темы X» / «что менялось в теме X». **Нет** `db upgrade`, **нет** backup-обязательства (schema не тронута). | ops |

**Recommended order:** 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8. Декларации+executors+dispatch вместе (атомарный tool), guard/bot.yaml сразу за ними (иначе тесты красные), docs+deploy — по запросу.

**Hard OUT:** см. §4.

---

## 1. Контекст

F5-C сделал темы живыми: каждый успешный re-summarize пишет snapshot предыдущего состояния в `topic_card_versions`, а живой current (`summary_version=N`) лежит на `topic_cards`. На этом уже построены **два MCP-инструмента** (#15 item #2, отгружены 2026-07-23):
- `get_topic_versions(topic_id, limit)` ([`mcp_server.py`](../../tg_parser/mcp_server.py) L2608) — аудит-трейл: `card_repo.get_by_id` → `assert_topic_access` → `version_repo.list_by_topic(topic_id, limit)`; возвращает `{topic_id, current_version, last_summarized_at, new_items_since_last_summary, versions[]}`.
- `get_topic_history_diff(topic_id, version_a?, version_b?)` ([`mcp_server.py`](../../tg_parser/mcp_server.py) L2674) — дельта: `get_two_versions` (archival) + живая карточка (`snapshot_from_card`), `diff_topic_summaries` (text-diff `summary` + set-diff `scope_in`/`scope_out`); default genesis (v1) → current; robust к TTL-gaps (typed not-found «reclaimed by retention policy», не 500).

CLI-паритет тоже есть (`tg-parser topic versions` / `topic diff`). **Отсутствует только bot-surface** — сейчас `@Tgingest_bot` (Gemini-агент) умеет `get_topic_details` (текущее состояние темы), но не историю/дельту.

**Разница одной строкой:** бот сегодня показывает *снимок* темы (`get_topic_details`); эта сессия добавляет *эволюцию* — «как менялась» (`get_topic_versions`) и «что именно изменилось между версиями» (`get_topic_history_diff`), тем же in-process путём, что и остальные read-tools бота.

**Почему тривиально:** бот работает in-process с полным доступом к БД (см. `_exec_get_topic_details` L2052 использует `processing_repos()`); executor'ы новых tool'ов просто вызывают те же shared-функции, что и MCP-эталоны. Ноль нового backend-кода, миграций, deps, ADR.

---

## 2. Anchors (перечитать перед правкой — verified 2026-07-24)

| Якорь | Файл | Строка | Роль |
|---|---|---|---|
| MCP `get_topic_versions` (логика-эталон) | [`mcp_server.py`](../../tg_parser/mcp_server.py) | **L2608** | зеркалить: repos + visibility + `list_by_topic` + result-shape |
| MCP `get_topic_history_diff` (логика-эталон) | [`mcp_server.py`](../../tg_parser/mcp_server.py) | **L2674** | зеркалить: `get_two_versions` + `diff_topic_summaries` + default genesis→current + TTL-gap typed not-found |
| `TOOL_DECLARATIONS` (добавить 2) | [`bot/tools.py`](../../tg_parser/bot/tools.py) | **L265** | Gemini function declarations |
| `get_topic_details` declaration (форма) | [`bot/tools.py`](../../tg_parser/bot/tools.py) | **L346** | шаблон декларации (topic_id-based) |
| `_exec_get_topic_details` (executor-эталон) | [`bot/tools.py`](../../tg_parser/bot/tools.py) | **L2052** | шаблон executor'а: repos + visibility (`allowed_channel_ids` intersect `card.sources` L2070-2072) + dict-return |
| Dispatch-map `_TOOL_EXECUTORS` (name→executor) | [`bot/tools.py`](../../tg_parser/bot/tools.py) | **~L4586** (entry `"get_topic_details": _exec_get_topic_details` L4590) | зарегистрировать оба |
| `_WRITE_TOOLS_REQUIRING_CONFIRM` (НЕ трогать — read-only) | [`bot/tools.py`](../../tg_parser/bot/tools.py) | **L110** | подтверждение НЕ нужно |
| `_READ_TOOLS_TRACKED_FOR_CONTEXT` (⚠️ **НЕ добавлять**) | [`bot/tools.py`](../../tg_parser/bot/tools.py) | **L161** (comment L158 исключает `get_topic_details`) | **только channel_id-carrying reads**; topic-tool'ы вне (D-2 contract [`test_bot_read_context.py`](../../tests/test_bot_read_context.py) L154) |
| `_PAGINATED_READ_TOOLS` (⚠️ **НЕ добавлять**) | [`bot/tools.py`](../../tg_parser/bot/tools.py) | **L180** | **только list-shaped `pagination_pending`**; contract [`test_pagination_contract_tdd.py`](../../tests/test_pagination_contract_tdd.py) L289 / [`test_mcp_pagination_contract.py`](../../tests/test_mcp_pagination_contract.py) L194 |
| `execute_tool` (dispatch entry) | [`bot/tools.py`](../../tg_parser/bot/tools.py) | **L1204** | путь исполнения (read → без confirm-ветки) |
| Versions read-path | [`storage/sqlalchemy/topic_card_version_repo.py`](../../tg_parser/storage/sqlalchemy/topic_card_version_repo.py) | **`list_by_topic` L72**, **`get_two_versions` L102** | listing + archival pair |
| diff helper | [`domain/topic_history_diff.py`](../../tg_parser/domain/topic_history_diff.py) | **L114** (`diff_topic_summaries`), **L56** (`snapshot_from_version`), **L74** (`snapshot_from_card`) | reuse as-is |
| Access enforcement | [`auth/ownership.py`](../../tg_parser/auth/ownership.py) | **`assert_topic_access` L50** | доступ если виден ≥1 из `card.sources` |
| repos ctx (даёт version_repo) | [`services/db_context.py`](../../tg_parser/services/db_context.py) | `resummarization_repos` (yields `card_repo, bundle_repo, version_repo, proc_repo, db`) | executor'ам нужен `version_repo` (не `processing_repos`) |
| Bot prompt version (**3 места** синхронно) | [`prompts/bot.yaml`](../../prompts/bot.yaml) | **L2** `# Version:`, **L8** `metadata.version`, **L30** in-prompt `- Version:` (все `1.9.0`) | bump → **`1.9.1`** (patch, не 1.10.0) |
| Bot capabilities list (добавить #14) | [`prompts/bot.yaml`](../../prompts/bot.yaml) | **L15-28** (нумерованный 1-13; per-tool инвентаря нет) | +«14. topic history / diff» |
| **Tool-count guards (ДВА — оба обновить!)** | [`tests/test_bot_tools_v11.py`](../../tests/test_bot_tools_v11.py) **L99** + [`tests/test_bot_tools_v12.py`](../../tests/test_bot_tools_v12.py) **L151** | `assert len(TOOL_DECLARATIONS) == 32` | → `== 34` (оба) |
| Version-pin guard (НЕ ронять) | [`tests/test_f9_phase2_prompt_defense.py`](../../tests/test_f9_phase2_prompt_defense.py) | **L194** `startswith("1.9")` | 1.9.1 проходит; 1.10.0 — нет |
| Version tuple-floor (safe) | [`tests/test_bot_read_context.py`](../../tests/test_bot_read_context.py) | **L642** `>= (1,8,0)` | 1.9.1 зелёный |
| Read-context / pagination contract-эталон | [`tests/test_bot_read_context.py`](../../tests/test_bot_read_context.py) L154, [`tests/test_pagination_contract_tdd.py`](../../tests/test_pagination_contract_tdd.py) L289 | — | почему topic-tool'ы вне classifier-множеств |

---

## 3. Scope — детально

### 3.1 Declarations (code)
- Две записи в `TOOL_DECLARATIONS` ([`bot/tools.py`](../../tg_parser/bot/tools.py) L265), форма `get_topic_details` (L346):
  - `get_topic_versions`: `properties = {topic_id: STRING (required), limit: INTEGER (optional, 1..200, default 10)}`. Описание: «Show how a topic's evolving summary changed over time (audit trail of past summary versions). Use after get_topic_details when the user asks how a topic evolved / what versions exist.»
  - `get_topic_history_diff`: `properties = {topic_id: STRING (required), version_a: INTEGER (optional), version_b: INTEGER (optional)}`. Описание: «Show what changed in a topic's summary between two versions (text + scope diff). Default compares the first version (genesis) to the current live summary. Use when the user asks what changed / what's new in a topic.»

### 3.2 Executors (code+test)
- `_exec_get_topic_versions(args, current_user)` и `_exec_get_topic_history_diff(args, current_user)` — зеркало `_exec_get_topic_details` (L2052):
  - `user = current_user or await get_default_admin()`.
  - `async with resummarization_repos() as (card_repo, _bundle, version_repo, _proc, _db):` (нужен `version_repo`).
  - `card = await card_repo.get_by_id(topic_id)`; `None` → `{"error": f"Topic not found: {topic_id}"}`.
  - **Visibility** (как L2070-2072): если `user.allowed_channel_ids is not None` и `not any(s in user.allowed_channel_ids for s in card.sources)` → `{"error": f"No access to topic: {topic_id}"}`. (Эквивалент `assert_topic_access` в MCP; для бота используем существующую `allowed_channel_ids`-идиому для консистентности с `_exec_get_topic_details`.)
  - **versions:** `versions = await version_repo.list_by_topic(topic_id, limit)` → вернуть `{topic_id, current_version: card.summary_version, last_summarized_at, new_items_since_last_summary, versions: [v.model_dump(mode="json")…]}` (shape MCP L2661-2669).
  - **diff:** повторить ветвление MCP L2757-2781: `version_a` default = 1 (genesis), `version_b` default = current (живая карточка). `right_is_current` → `get_two_versions(topic_id, version_a, version_a)` + `snapshot_from_card(card)`; both-archival → `get_two_versions(topic_id, version_a, version_b)`. Отсутствующая версия → typed `{"error": …, "topic_id": …}` (не exception). Вернуть `{topic_id, **diff_topic_summaries(left, right)}`.
- **limit-валидация** (как MCP L2638): `1..200`, иначе `{"error": "limit must be between 1 and 200", …}`.
- Unit-тесты: happy (versions/diff); not-found; no-access (visibility); diff default genesis→current; diff both-archival; missing version → typed not-found; limit out-of-range.

### 3.3 Dispatch + классификация (code)
- Добавить в маппинг `_TOOL_EXECUTORS` (~L4586, entry-эталон L4590): `"get_topic_versions": _exec_get_topic_versions`, `"get_topic_history_diff": _exec_get_topic_history_diff`.
- **Classifier-множества — НИЧЕГО не добавлять** (verified review-pass 2026-07-24; иначе CI red):
  - **`_READ_TOOLS_TRACKED_FOR_CONTEXT` (L161)** — только **channel_id-carrying** reads (комментарий L158 явно исключает `get_topic_details` и `get_related_topics` как topic_id-based). D-2 contract [`test_bot_read_context.py`](../../tests/test_bot_read_context.py) L154 требует, чтобы у КАЖДОГО члена в декларации было свойство `channel_id`; у topic-tool'ов его нет ⇒ добавление = красный тест. **Не добавлять.**
  - **`_PAGINATED_READ_TOOLS` (L180)** — только **list-shaped** инструменты, эмитящие `pagination_pending` через `_paginate_read_result`. Contract-тесты [`test_pagination_contract_tdd.py`](../../tests/test_pagination_contract_tdd.py) L289 + [`test_mcp_pagination_contract.py`](../../tests/test_mcp_pagination_contract.py) L194 (`set(_TOOL_FIXTURES) == set(_PAGINATED_READ_TOOLS)`) требуют fixture + paginated-shape `{total,offset,limit,has_more,items}`. `get_topic_versions` отдаёт MCP-shape (полный список ≤`limit` одним ответом, как MCP-эталон) ⇒ добавление сломает и contract, и MCP-parity. MCP-side `_PAGINATED_READ_TOOLS` тоже НЕ содержит `get_topic_versions`. **Не добавлять.**
  - **`_WRITE_TOOLS_REQUIRING_CONFIRM` (L110)** — read-only ⇒ **не добавлять**.
  - **Итог:** оба tool'а — plain read-tools, вне всех трёх множеств.

### 3.4 Prompt + guards (code+docs)
- [`prompts/bot.yaml`](../../prompts/bot.yaml): per-tool инвентаря нет (grep `get_topic_details` в prompt пуст) — добавить **capability-строку #14** в нумерованный список (L15-28), напр. «14. View how a topic's evolving summary changed over time and diff two versions (read-only)». (Опц.) короткое tool-usage правило, если нужно направить агента.
- **Version bump `1.9.0 → 1.9.1`** в **ТРЁХ** синхронных местах: L2 (`# Version:`), L8 (`metadata.version`), L30 (in-prompt `- Version:`). **Patch, НЕ `1.10.0`:** [`test_f9_phase2_prompt_defense.py`](../../tests/test_f9_phase2_prompt_defense.py) L194 пинит `data["metadata"]["version"].startswith("1.9")` (1.10.0 его роняет), tuple-floor [`test_bot_read_context.py`](../../tests/test_bot_read_context.py) L642 (`>= (1,8,0)`) — оба зелёные на 1.9.1; security-defense-тест не трогаем.
- **Tool-count guards — ДВА (оба обновить, иначе CI red):** `assert len(TOOL_DECLARATIONS) == 32 → == 34` в [`tests/test_bot_tools_v11.py`](../../tests/test_bot_tools_v11.py) **L99** И [`tests/test_bot_tools_v12.py`](../../tests/test_bot_tools_v12.py) **L151**.
- **Presence-проверка:** presence-set в `test_bot_tools_v12.py` L141-147 — v12-специфичный subset (add_channel/remove_channel/llm-config); НЕ пихать топик-tool'ы туда. Добавить отдельную presence-ассерцию в **новом** тест-файле (`{"get_topic_versions","get_topic_history_diff"} ⊆ {d["name"] for d in TOOL_DECLARATIONS}`).

### 3.5 Docs (docs)
- [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) L800 «Bot tools для F5-C … только при UX-сигнале» → **DONE** (bot `get_topic_versions` + `get_topic_history_diff`, паритет с MCP/CLI). Этот START_PROMPT → «landed» pointer.

---

## 4. Out of scope (жёстко)

- **Новые backend-методы** — `list_by_topic`/`get_two_versions`/`diff_topic_summaries`/`assert_topic_access` reuse as-is; ничего не добавлять/менять.
- **MCP/CLI diff-surface** — не трогать (уже отгружено #2); это только bot-паритет.
- **force_resummarize / write-tools в боте** — OUT (это admin/write операции; если понадобятся — отдельный slice с confirm-gating).
- **Topic-digest подписки из бота** (`subscribe_digest mode=topic` через bot-tool) — отдельная UX-фича, не в этом slice (сейчас через MCP/CLI).
- **Rich-рендер diff в отдельный формат сообщения** — агент сам пересказывает dict; максимум мелкий case в детерминированном рендерере, без нового формата доставки.
- **Schema / migration / new deps / ADR** — фича surface-only, ничего из этого не требуется.
- **`docs/methodology/**`, `pyproject.toml`, `requirements.txt`.**

---

## 5. Acceptance criteria

- [ ] **Два новых read-tool'а** `get_topic_versions` + `get_topic_history_diff` объявлены в `TOOL_DECLARATIONS`, зарегистрированы в dispatch-map, доступны Gemini-агенту бота.
- [ ] **Логика-паритет с MCP:** result-shape и семантика (default genesis→current, TTL-gap typed not-found, limit 1..200) совпадают с MCP-эталонами L2608/L2674; backend не тронут.
- [ ] **Visibility:** топик вне `user.allowed_channel_ids` → `{"error": "No access to topic: …"}` (не утечка); not-found → `{"error": "Topic not found: …"}`; отсутствующая версия → typed not-found, **не** exception / не 500.
- [ ] **Read-only, вне classifier-множеств:** ни один tool не в `_WRITE_TOOLS_REQUIRING_CONFIRM`, `_READ_TOOLS_TRACKED_FOR_CONTEXT` (channel_id-only, D-2 contract), `_PAGINATED_READ_TOOLS` (list-shaped only) — оба plain read-tools с MCP-shape ответом.
- [ ] **Guards обновлены:** `len(TOOL_DECLARATIONS) == 34` в **обоих** `test_bot_tools_v11.py:99` + `test_bot_tools_v12.py:151`; `bot.yaml` version `1.9.1` синхронно в L2/L8/L30; `test_f9_phase2_prompt_defense.py:194` (`startswith("1.9")`) и tuple-floor `test_bot_read_context.py:642` — зелёные; новый тест ассертит присутствие обоих имён.
- [ ] **Нет новых deps** (ADR-0017; `pyproject`/`requirements` не тронуты); **нет** schema-change / migration / ADR.
- [ ] `uv run ruff check .` + `uv run ruff format --check .` + `TEST_POSTGRES=1 uv run pytest -q` — green.
- [ ] [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) L800 → DONE; START_PROMPT «landed» pointer.
- [ ] **Deploy (no-migration):** re-create `tg_bot` (`up -d --no-deps`, НЕ restart); smoke — бот отвечает на «история темы X» / «что менялось в теме X». `db upgrade` / backup **не** требуются.
- [ ] Commit/PR только по явному запросу пользователя.

---

## 6. Quality / ops gate commands

```bash
# repo quality (local, всегда)
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
# PR-standard (трогаем bot + repo read-paths → нужен Postgres):
TEST_POSTGRES=1 uv run pytest -q
# Runner note: tests/README.md L76 предпочитает `.venv/bin/python -m pytest`;
# `uv run pytest` — принятый эквивалент.

# reload prompts без рестарта (если только bot.yaml менялся, для быстрой проверки):
#   MCP/bot tool `reload_prompts`

# Deploy (NO-migration, surface-only):
git checkout main && git pull --ff-only origin main
docker compose build tg_parser                 # образ tg_parser:latest шарится всеми сервисами
docker compose up -d --no-deps tg_bot          # RE-CREATE (НЕ restart — BUG-078)
# smoke: в @Tgingest_bot спросить «покажи историю темы <topic_id>» и «что менялось в теме <topic_id>»
```

_**NO-migration deploy (в отличие от topic-digest #3):** фича surface-only — новых колонок нет ⇒ `db upgrade`/backup не требуются. Достаточно re-create образа `tg_bot`._

---

## 7. Decisions (baked)

1. **Паритет, не редизайн** — bot-tools 1:1 зеркалят MCP `get_topic_versions`/`get_topic_history_diff` (result-shape, defaults, error-shapes); никакой новой семантики.
2. **Reuse backend as-is** — `list_by_topic` / `get_two_versions` / `diff_topic_summaries` / snapshot-хелперы; ноль нового repo/service-кода.
3. **Read-only, вне classifier-множеств** — без confirm-gating; visibility через `allowed_channel_ids`-intersect (идиома `_exec_get_topic_details`), эквивалент `assert_topic_access`. Topic-tool'ы НЕ входят в `_READ_TOOLS_TRACKED_FOR_CONTEXT` (channel_id-only) и `_PAGINATED_READ_TOOLS` (list-shaped) — их contract-тесты это запрещают.
4. **NO-migration / NO-ADR** — surface-only; schema/contracts/deps не тронуты. Deploy = re-create `tg_bot` (BUG-078).
5. **Guard-hygiene (verified review-pass)** — в ТОМ ЖЕ PR: **ДВА** tool-count baseline'а (`v11:99` + `v12:151`) → `== 34`; `bot.yaml` version → **`1.9.1`** (patch, синхронно L2/L8/L30) чтобы не ронять security-guard `test_f9:194` (`startswith("1.9")`); classifier-множества НЕ трогать.

---

## 8. Нужен ли новый ADR? — **НЕТ**

Фича **не** меняет ни один контракт: не добавляет колонок, не меняет data-model, не вводит новых deps, не меняет delivery-семантику. Это чистое **surface-parity** расширение поверх уже отгруженных read-path'ов (#2 diff-API) и существующего bot-tool фреймворка. ADR не требуется (контраст: topic-digest #3 добавлял `mode`/`topic_ids` ⇒ ADR-0019 был обязателен; здесь — нет). Достаточно `bot.yaml` version bump + FUTURE_FEATURES отметки.

---

## 9. Self-review fixes applied (START_PROMPT)

Критический pass (anchor-correctness пофайлово / паритет с MCP / testable acceptance / explicit OUT / guard-hygiene / no-migration consequence):

1. **Anchors verified 2026-07-24 пофайловым чтением** — MCP `get_topic_versions` L2608 (repos+visibility+`list_by_topic`+result-shape L2661-2669), `get_topic_history_diff` L2674 (`get_two_versions`+`diff_topic_summaries`, ветвление L2757-2781); bot `TOOL_DECLARATIONS` L265, `get_topic_details` decl L346, `_exec_get_topic_details` L2052 (visibility L2070-2072), dispatch ~L4590, `_WRITE_TOOLS_REQUIRING_CONFIRM` L110, `_READ_TOOLS_TRACKED_FOR_CONTEXT` L161, `_PAGINATED_READ_TOOLS` L180, `execute_tool` L1204; `topic_card_version_repo` `list_by_topic` L72 / `get_two_versions` L102; `diff_topic_summaries` L114 / `snapshot_from_version` L56 / `snapshot_from_card` L74; `assert_topic_access` L50; `bot.yaml` version L8 (`1.9.0`); guard `test_bot_tools_v12.py` L151 (`== 32`). Ни одного invented symbol.
2. **Repos-context уточнён** — executor'ам нужен `version_repo` ⇒ `resummarization_repos()` (не `processing_repos()`, которым пользуется `_exec_get_topic_details`); явно в §2/§3.2.
3. **Guard-hygiene зафиксирован как обязательный шаг** — **ДВА** tool-count guard'а (`test_bot_tools_v11.py:99` + `test_bot_tools_v12.py:151`) `32 → 34` + `bot.yaml` `1.9.0 → 1.9.1` (patch, синхронно L2/L8/L30) в том же PR. §0 step5 / §3.4 / §5.
4. **Паритет-контракт testable** — acceptance привязан к MCP result-shape / defaults / error-shapes; visibility на not-found/no-access/missing-version.
5. **NO-migration / NO-ADR consequence** явно противопоставлено topic-digest #3 (§header banner, §6 deploy note, §8).
6. **Explicit OUT §4** — новые backend-методы, MCP/CLI изменения, write/force_resummarize в боте, subscribe из бота, rich-diff формат, schema/migration/deps/ADR, methodology/pyproject.
7. **Governance block** — commit/PR только по запросу; no methodology/pyproject/requirements edits; ADR/contracts respected (header).
8. **Adversarial review-pass applied (2026-07-24, отдельный воркер).** Пофайловая верификация поймала 2 BLOCKER + 2 MAJOR, все внесены: **(B1)** topic-tool'ы НЕ добавлять в `_READ_TOOLS_TRACKED_FOR_CONTEXT` — множество только channel_id-carrying (comment L158 исключает `get_topic_details`; D-2 contract `test_bot_read_context.py:154` требует `channel_id`-property). **(B2)** `get_topic_versions` НЕ добавлять в `_PAGINATED_READ_TOOLS` — только list-shaped `pagination_pending` (contract `test_pagination_contract_tdd.py:289` / `test_mcp_pagination_contract.py:194`); MCP-shape сохраняется. **(M1)** version → `1.9.1` (не `1.10.0`): `test_f9_phase2_prompt_defense.py:194` пинит `startswith("1.9")`. **(M2)** ДВА tool-count guard'а, не один (`v11:99` добавлен к `v12:151`). Плюс: bot.yaml version в 3 местах (L2/L8/L30); capability #14 в нумерованный список (per-tool инвентаря нет); dispatch-map = `_TOOL_EXECUTORS` ~L4586. CLI-parity (`topic versions`/`topic diff`) подтверждён существующим (`cli/topic_cmd.py`).

---

## 10. Ссылки

- MCP-эталоны: [`mcp_server.py`](../../tg_parser/mcp_server.py) `get_topic_versions` L2608 / `get_topic_history_diff` L2674
- Bot framework: [`bot/tools.py`](../../tg_parser/bot/tools.py) `TOOL_DECLARATIONS` L265, `get_topic_details` decl L346 / `_exec_get_topic_details` L2052, dispatch ~L4590, `execute_tool` L1204; classifier sets L110/L161/L180
- Diff-API (#2): [`domain/topic_history_diff.py`](../../tg_parser/domain/topic_history_diff.py) L114/L56/L74; versions repo [`topic_card_version_repo.py`](../../tg_parser/storage/sqlalchemy/topic_card_version_repo.py) L72/L102
- Access: [`auth/ownership.py`](../../tg_parser/auth/ownership.py) `assert_topic_access` L50
- Prompt + guards: [`prompts/bot.yaml`](../../prompts/bot.yaml) version L2/L8/L30 + capabilities L15-28; tool-count [`tests/test_bot_tools_v11.py`](../../tests/test_bot_tools_v11.py) L99 + [`tests/test_bot_tools_v12.py`](../../tests/test_bot_tools_v12.py) L151; version-pin [`tests/test_f9_phase2_prompt_defense.py`](../../tests/test_f9_phase2_prompt_defense.py) L194 + floor [`tests/test_bot_read_context.py`](../../tests/test_bot_read_context.py) L642; contract [`tests/test_pagination_contract_tdd.py`](../../tests/test_pagination_contract_tdd.py) L289
- Roadmap: Issue [#15](https://github.com/AlexEfimov/TG_parser/issues/15) item #5 (Bot tools); [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) L800
- Сосед по #15 (стиль-эталон): [`START_PROMPT_SESSION_F5C_TOPIC_DIGEST_2026-07-24.md`](START_PROMPT_SESSION_F5C_TOPIC_DIGEST_2026-07-24.md)
- ADR [0006](../adr/0006-karpathy-like-living-kb-principles.md), [0017](../adr/0017-dependency-management-policy.md), [0018](../adr/0018-topic-card-versions-retention.md)
