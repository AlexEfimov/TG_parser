# START PROMPT — Session: F5-C #15 item #5 — Bot **write**-tool `force_resummarize` (в `@Tgingest_bot`)

> **📋 PLAN (2026-07-25, обновлён после ревью owner'а — 2 решения baked, см. §9-addendum).** Это план для оставшейся **write**-части #15 item #5 ([#356](https://github.com/AlexEfimov/TG_parser/issues/356) item A). Surface-only: **1** declaration + executor (`_exec_force_resummarize`, `bot/tools.py`) + dispatch-map + **регистрация в `_WRITE_TOOLS_REQUIRING_CONFIRM`** (admin + two-phase confirm) + `bot.yaml` bump `1.9.1 → 1.9.2` (capability #15, L2/L8/L31 + write-ops строка L41) + tool-count guards `34 → 35` (`test_bot_tools_v11.py` / `test_bot_tools_v12.py`) + **baseline-frozenset guard** (`test_bot_execute_tool_guard.py:360`) + new tests. Backend не тронут (переиспользуется отгруженный `ResummarizationService`).
>
> **Решения owner'а (baked):** (1) **RICH preview** — на `confirm=false` executor делает дешёвый `card_repo.get_by_id` и возвращает `current_version` / `new_items_since_last_summary` / `sources` + ранний typed «Topic not found». (2) **`dry_run` IN** — параметр `dry_run` для полного паритета с CLI `topic resummarize --dry-run` (report-only, 0 LLM, 0 mutation, **терминальный** — confirm не нужен). Различие preview vs dry_run см. §7 decision 5.

**Дата:** 2026-07-25 · **Тип:** implementation-plan (surface-only: 1 **admin/write** bot-tool с confirm-gating поверх уже отгруженного MCP `force_resummarize` + CLI `topic resummarize`; `bot.yaml` bump + guard update + tests + docs) · **Ветка:** `feature/f5c-bot-force-resummarize` (от актуального `main` @ `be90058`).

**Goal (одной строкой):** дать админу запускать F5-C re-summarize темы **прямо из Telegram-бота** — один новый **write**-tool `force_resummarize(topic_id, confirm)`, admin-only и confirm-gated (two-phase preview/confirm, BUG-009), зеркалящий уже существующий MCP-инструмент `force_resummarize`; **backend-логика переиспользуется as-is** (нового кода в сервисах/репозиториях нет).

> **Контекст парности.** Read-часть #15 item #5 (`get_topic_versions` / `get_topic_history_diff`) отгружена и задеплоена 2026-07-24 (PR #355, [`START_PROMPT_SESSION_F5C_BOT_TOOLS_2026-07-24.md`](START_PROMPT_SESSION_F5C_BOT_TOOLS_2026-07-24.md) — стиль-эталон этого документа). Тот slice **явно** вынес write/force_resummarize за скобки (его §4: «force_resummarize / write-tools в боте — OUT … если понадобятся — отдельный slice с confirm-gating»). Это — тот самый отдельный slice.

> **ВАЖНО — это NO-migration, surface-only деплой:** фича лишь **добавляет 1 tool-декларацию + executor** в боте поверх уже отгруженного `force_resummarize` (MCP) и `ResummarizationService`. **Нет** schema-change, **нет** новых зависимостей, **ADR НЕ нужен** (surface-parity над отгруженным backend'ом). Deploy = обычный re-create образа `tg_bot` (`up -d --no-deps tg_bot`, BUG-078), без `db upgrade`.

> **Рабочий режим (нормативно, [`AGENTS.md`](../../AGENTS.md)):** `git commit` / PR — **только** по явному запросу пользователя (PR = merge-commit + `--delete-branch`). Никаких правок `docs/methodology/**`. `pyproject.toml` / `requirements.txt` — **не трогать** (ADR-0017; новых deps нет). Уважать `docs/adr/` (accepted binding) и `docs/contracts/` (JSON Schema нерушимы). **Не трогать backend** (`ResummarizationService`, `resummarization_repos`, `assert_admin`) — только вызывать. **Не трогать MCP/CLI force_resummarize-surface** — это лишь bot-паритет.

**Prerequisite SoT (перечитать перед кодом):**
- MCP-эталон (зеркалить 1:1 по логике): `force_resummarize` ([`mcp_server.py`](../../tg_parser/mcp_server.py) L2784) — `assert_admin` → `resummarization_repos()` → `ResummarizationService(...).resummarize_topic(topic_id)` в `try/finally: aclose()` → `return {"topic_id": topic_id, **outcome}`.
- MCP-контракт (зеркалить в тестах): [`tests/test_f5c_mcp_tools.py`](../../tests/test_f5c_mcp_tools.py) `TestForceResummarize` L462 — admin-invokes+aclose (L463), `status='locked'` passthrough (L503), **billing-error propagates** (L531), non-admin denied без создания сервиса (L564), aclose-on-raise (L589).
- CLI-эталон (семантика `--dry-run`): [`cli/topic_cmd.py`](../../tg_parser/cli/topic_cmd.py) `resummarize` L340 (dry-run печатает контекст без LLM; `status` ok/locked/… обрабатывается L437-457).
- Bot write-tool паттерн (admin + confirm + preview): `_exec_register_user` ([`bot/tools.py`](../../tg_parser/bot/tools.py) L3069) — **ближайший шаблон** (admin-gate до preview, `{"preview": True, ...}` при `confirm=false`, мутация под `confirm=True`); вторично `_exec_trigger_pipeline` L2375 (enriched preview) и `_exec_update_user` L3158.
- BUG-009 guard (confirm=True — framework-owned): `_check_confirm_flow_match` ([`bot/tools.py`](../../tg_parser/bot/tools.py) L1195) + `execute_tool` L1256 (guard L1291-1299, typed-catch BUG-005-B L1306-1350).
- ADR: [ADR-0006](../adr/0006-karpathy-like-living-kb-principles.md) (living-KB), [ADR-0017](../adr/0017-dependency-management-policy.md) (no new deps), [ADR-0018](../adr/0018-topic-card-versions-retention.md) (versions retention — фон F5-C).
- Сосед (read-часть, стиль-эталон): [`START_PROMPT_SESSION_F5C_BOT_TOOLS_2026-07-24.md`](START_PROMPT_SESSION_F5C_BOT_TOOLS_2026-07-24.md).

---

## 0. TL;DR

| Step | Действие | Тип |
|---|---|---|
| 1 | **Declaration.** Добавить 1 запись в `TOOL_DECLARATIONS` ([`bot/tools.py`](../../tg_parser/bot/tools.py) ~L265, форма — как `register_user` L729 с `confirm`-параметром L744): `force_resummarize` (params `topic_id` STRING **required**; `dry_run` BOOLEAN **optional** (CLI-parity report-only no-op); `confirm` BOOLEAN — **framework-owned**, дословно скопировать confirm-описание из `register_user`/`update_user` с BUG-009 hard-rule). Описание в стиле «Force an immediate F5-C re-summarize of one topic (admin only). Costs LLM tokens and writes a new topic-card version. Set dry_run=true for a no-op report (no tokens, no write).». | code |
| 2 | **Executor (3 ветки).** `_exec_force_resummarize(args, current_user)` — зеркало `_exec_register_user` (L3069) + MCP `force_resummarize` (L2784): `user = current_user or await get_default_admin()`; **`assert_admin(user)` ПЕРВЫМ** (до любой ветки) → `PermissionDenied` → `{"error": e.message, "topic_id": topic_id}`. Затем: **(A) `dry_run=true`** → CLI-parity report: `resummarization_repos()` → `card_repo.get_by_id`; None → `{"error": "Topic not found: …"}`; иначе `bundle_repo.get_by_topic_id` → `{"dry_run": True, topic_id, title, current_version, new_items_since_last_summary, bundle_items_count, sources, ...}` (0 LLM, 0 mutation; **терминально**). **(B) `not confirm`** → RICH preview: `card_repo.get_by_id`; None → typed «Topic not found»; иначе `{"preview": True, current_version, new_items_since_last_summary, sources, user_facing_message: True, message: "…расход токенов…Подтвердите [да/нет]"}`. **(C) `confirm=true`** → мутация: `resummarization_repos()` → `ResummarizationService(...)` → `try: outcome = await service.resummarize_topic(topic_id) finally: await service.aclose()` → `return {"topic_id": topic_id, **outcome}`. Billing/exc **пробрасывается** (aclose в finally). | code+test |
| 3 | **Dispatch-map.** Зарегистрировать `"force_resummarize": _exec_force_resummarize` в `_TOOL_EXECUTORS` ([`bot/tools.py`](../../tg_parser/bot/tools.py) L4743). | code |
| 4 | **Confirm-gate registration.** Добавить `"force_resummarize"` в `_WRITE_TOOLS_REQUIRING_CONFIRM` frozenset (L110). **НЕ** добавлять в `_READ_TOOLS_TRACKED_FOR_CONTEXT` (L161), `_PAGINATED_READ_TOOLS` (L180), `_TOOLS_NEEDING_BOT_CONTEXT` (L86 — DB-only, bot/chat_id не нужны). | code |
| 5 | **`prompts/bot.yaml` + guards.** Capability-строка **#15** («Force an immediate re-summarize of a topic — admin only, after confirmation»); добавить `force_resummarize` в write-ops инструкцию (L41). **Version bump `1.9.1 → 1.9.2`** в ТРЁХ местах (L2 `# Version:`, L8 `metadata.version`, L31 in-prompt `- Version:`) — **patch** (floor-тесты требуют `1.9.x`). **Tool-count guards — ДВА:** `== 34 → == 35` в [`test_bot_tools_v11.py`](../../tests/test_bot_tools_v11.py) **L99** И [`test_bot_tools_v12.py`](../../tests/test_bot_tools_v12.py) **L151**. **Baseline-frozenset guard:** добавить `"force_resummarize"` в pinned set в [`test_bot_execute_tool_guard.py`](../../tests/test_bot_execute_tool_guard.py) **L360** (иначе `test_guard_set_matches_known_baseline` red). | code+docs |
| 6 | **Tests.** Новый файл `tests/test_f5c_bot_force_resummarize.py`: declaration-presence + confirm-param есть; **admin preview** (`confirm=false` → `{"preview": True}`, сервис НЕ создан); **admin commit** (`confirm=true` → `{"topic_id", **outcome}`, `aclose` вызван); **`status='locked'` passthrough** (success-ish, не error); **non-admin denied** (`{"error"}`, сервис НЕ создан); **billing propagates** (executor не глотает `AnthropicBillingError` → `execute_tool` typed-catch → `error_class="AnthropicBillingError"`); BUG-009 (LLM-issued `confirm=true` без FSM-state → `ConfirmFlowMismatch`, из `test_bot_execute_tool_guard` контракта). Зеркало [`test_f5c_mcp_tools.py`](../../tests/test_f5c_mcp_tools.py) `TestForceResummarize`. | test |
| 7 | **Quality gate.** `ruff check/format` + `TEST_POSTGRES=1 uv run pytest -q` (трогаем bot + guard-тесты). | gate |
| 8 | **Docs.** [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) / #356 item A → DONE; этот START_PROMPT → «landed» pointer (по завершении). | docs |
| 9 | **Deploy (NO-migration).** `docker compose build tg_parser` → `docker compose up -d --no-deps tg_bot` (re-create, **НЕ** restart — BUG-078). Smoke: админ в `@Tgingest_bot` «пересуммаризируй тему X» → preview → «да» → outcome. **Нет** `db upgrade` / backup. | ops |

**Recommended order:** 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8. Declaration+executor+dispatch+confirm-set вместе (атомарный tool), guards/bot.yaml сразу за ними (иначе тесты красные), docs+deploy — по запросу.

**Hard OUT:** см. §4.

---

## 1. Контекст

F5-C сделал темы живыми: `ResummarizationService.resummarize_topic(topic_id)` немедленно пересобирает сводку темы (advisory-lock, snapshot предыдущей версии в `topic_card_versions`, UPDATE `topic_cards`), возвращая outcome-dict со `status ∈ {ok, locked, no_card, no_bundle, empty_scope, llm_error, version_raced}`. Поверх этого уже отгружены:
- **MCP** `force_resummarize(topic_id)` ([`mcp_server.py`](../../tg_parser/mcp_server.py) L2784) — admin-only ручной триггер (bypass N-threshold), passthrough outcome-dict; `status='locked'` — «уже пересуммаризируется» (не ошибка); billing-error (`AnthropicBillingError`) **пробрасывается** (не глотается — админ не должен палить кредиты повторами против paused-аккаунта).
- **CLI** `tg-parser topic resummarize <topic_id> [--dry-run]` ([`cli/topic_cmd.py`](../../tg_parser/cli/topic_cmd.py) L340) — тот же сервис; `--dry-run` печатает кандидат-контекст (summary_version / bundle items / sources) без вызова LLM.

**Отсутствует только bot-surface** — сейчас `@Tgingest_bot` умеет читать историю темы (`get_topic_versions` / `get_topic_history_diff`, PR #355), но не может **запустить** re-summarize. Это #356 item A / #15 item #5 (write-часть).

**Разница со sibling read-slice одной строкой:** тот slice добавлял **read-only** tool'ы (без confirm, visibility через `allowed_channel_ids`); этот — **admin write**-tool: (1) admin-only (`assert_admin`, не per-topic visibility — как MCP), (2) **confirm-gated** (two-phase preview/confirm, BUG-009), (3) дорогой/деструктивный side-effect (тратит токены, пишет версию).

**Почему тривиально:** бот работает in-process с полным доступом к БД; executor просто вызывает тот же `ResummarizationService`, что и MCP-эталон. Ноль нового backend-кода, миграций, deps, ADR.

---

## 2. Anchors (перечитать перед правкой — verified 2026-07-25 @ `be90058`)

| Якорь | Файл | Строка | Роль |
|---|---|---|---|
| **MCP `force_resummarize` (логика-эталон)** | [`mcp_server.py`](../../tg_parser/mcp_server.py) | **L2784** (`@mcp.tool`), def L2785; admin L2805-2813; repos+service L2815-2831; return L2833 | зеркалить: `assert_admin` → `resummarization_repos()` → `resummarize_topic` в `try/finally aclose` → `{"topic_id", **outcome}` |
| MCP-контракт (зеркалить в тестах) | [`tests/test_f5c_mcp_tools.py`](../../tests/test_f5c_mcp_tools.py) | **`TestForceResummarize` L462**; admin+aclose L463, locked L503, **billing L531**, non-admin L564, aclose-on-raise L589 | acceptance-паритет |
| **CLI-эталон `--dry-run` (зеркалить в ветке A)** | [`cli/topic_cmd.py`](../../tg_parser/cli/topic_cmd.py) | **L340** (`resummarize`), `dry_run`-opt L343, **`_dry()` L359-380** (`card_repo.get_by_id` → None=`{"error":"not_found"}`; `bundle_repo.get_by_topic_id`; `bundle_items_count = len(bundle.items) if bundle else 0`), печать L419-426 (title/current_version=`card.summary_version`/`new_items_since_last_summary`/bundle items/sources; **«LLM не вызывался, версия не записывалась»**), real `_run` L382-406, status-handling L437-457 | dry_run = report-only no-op (0 LLM, 0 write) |
| `TOOL_DECLARATIONS` (добавить 1) | [`bot/tools.py`](../../tg_parser/bot/tools.py) | **~L265** (список), пример write-декларации `register_user` **L729** + `confirm`-param **L744** | Gemini function declaration |
| `_exec_register_user` (executor-эталон: admin+confirm+preview) | [`bot/tools.py`](../../tg_parser/bot/tools.py) | **L3069** (admin L3090-3093, `confirm` L3095, preview-gate L3102-3123, мутация L3125+) | ближайший шаблон executor'а |
| `_exec_trigger_pipeline` (enriched preview, вторичный шаблон) | [`bot/tools.py`](../../tg_parser/bot/tools.py) | **L2375** (preview_base L2410, gate L2423-2427) | опц. обогащение preview контекстом темы |
| Dispatch-map `_TOOL_EXECUTORS` (name→executor) | [`bot/tools.py`](../../tg_parser/bot/tools.py) | **L4743** (последняя запись L4777) | зарегистрировать `force_resummarize` |
| `_WRITE_TOOLS_REQUIRING_CONFIRM` (**ДОБАВИТЬ**) | [`bot/tools.py`](../../tg_parser/bot/tools.py) | **L110** (текущие 15 tool'ов L112-150) | +`"force_resummarize"` |
| `_TOOLS_NEEDING_BOT_CONTEXT` (**НЕ добавлять** — DB-only) | [`bot/tools.py`](../../tg_parser/bot/tools.py) | **L86** (только export_channel/subscribe_*) | force_resummarize не нужен bot/chat_id |
| `_READ_TOOLS_TRACKED_FOR_CONTEXT` (**НЕ добавлять** — write) | [`bot/tools.py`](../../tg_parser/bot/tools.py) | **L161** | write-tool вне read-context |
| `_PAGINATED_READ_TOOLS` (**НЕ добавлять** — не list-shaped) | [`bot/tools.py`](../../tg_parser/bot/tools.py) | **L180** | outcome-dict, не paginated |
| BUG-009 guard | [`bot/tools.py`](../../tg_parser/bot/tools.py) | **`_check_confirm_flow_match` L1195**; `execute_tool` **L1256** (guard L1291-1299, typed-catch L1306-1350) | confirm=True — framework-owned; executor НЕ принимает LLM-issued confirm=True |
| Bot prompt version (**3 места** синхронно) | [`prompts/bot.yaml`](../../prompts/bot.yaml) | **L2** `# Version:`, **L8** `metadata.version`, **L31** in-prompt `- Version:` (все `1.9.1`) | bump → **`1.9.2`** (patch, не 1.10.0) |
| Bot capabilities list (добавить #15) | [`prompts/bot.yaml`](../../prompts/bot.yaml) | **L15-29** (нумерованный 1-14; #14 = topic history/diff L29) | +«15. force re-summarize (admin, confirm)» |
| Bot write-ops инструкция (добавить в список) | [`prompts/bot.yaml`](../../prompts/bot.yaml) | **L41** («For write operations (…): ALWAYS call with confirm=false first…») | +`force_resummarize` в перечень |
| **Tool-count guards (ДВА — оба!)** | [`tests/test_bot_tools_v11.py`](../../tests/test_bot_tools_v11.py) **L99** + [`tests/test_bot_tools_v12.py`](../../tests/test_bot_tools_v12.py) **L151** | `assert len(TOOL_DECLARATIONS) == 34` | → `== 35` (оба) |
| **Baseline-frozenset guard (⚠️ BLOCKER — обновить!)** | [`tests/test_bot_execute_tool_guard.py`](../../tests/test_bot_execute_tool_guard.py) | **L360** (`test_guard_set_matches_known_baseline`, pinned set L360-378) | добавить `"force_resummarize"` в pinned frozenset |
| Confirm-param контракт (авто-зелёный при declaration+set) | [`tests/test_bot_execute_tool_guard.py`](../../tests/test_bot_execute_tool_guard.py) | forward **L317** / reverse **L327** | требуют: confirm-param ⇔ членство в `_WRITE_TOOLS_REQUIRING_CONFIRM` |
| Version-pin guard (НЕ ронять) | [`tests/test_f9_phase2_prompt_defense.py`](../../tests/test_f9_phase2_prompt_defense.py) | **L194** `startswith("1.9")` | 1.9.2 проходит; 1.10.0 — нет |
| Version tuple-floor (safe) | [`tests/test_bot_read_context.py`](../../tests/test_bot_read_context.py) | **L642** `>= (1,8,0)` | 1.9.2 зелёный |
| Backend reuse (НЕ трогать) | [`services/resummarization_service.py`](../../tg_parser/services/resummarization_service.py) `ResummarizationService` **L139**, `resummarize_topic` **L307**, `aclose` **L853** | — | только вызывать |
| repos ctx | [`services/db_context.py`](../../tg_parser/services/db_context.py) `resummarization_repos` **L350** (yields `card_repo, bundle_repo, version_repo, proc_repo, db`) | — | reuse; ветки A/B используют `card_repo.get_by_id` + (A) `bundle_repo.get_by_topic_id`; ветка C — весь сервис |
| `TopicCard` поля (для preview/dry_run) | [`domain/models.py`](../../tg_parser/domain/models.py) `TopicCard` | `title`, `summary_version`, `new_items_since_last_summary`, `sources` | поля для report/preview (как CLI L421-425) |
| admin gate | [`auth/ownership.py`](../../tg_parser/auth/ownership.py) `assert_admin` **L97** (raises `PermissionDenied` L18, msg «Admin access required») | — | reuse |
| billing error | [`processing/llm/errors.py`](../../tg_parser/processing/llm/errors.py) `AnthropicBillingError` **L4** | — | должен пробрасываться |

---

## 3. Scope — детально

### 3.1 Declaration (code)
- Одна запись в `TOOL_DECLARATIONS` ([`bot/tools.py`](../../tg_parser/bot/tools.py) ~L265), форма `register_user` (L729):
  - `name`: `"force_resummarize"`.
  - `description`: «Force an immediate F5-C re-summarize of one topic (admin only). Bypasses the N-threshold counter, spends LLM tokens, and writes a new topic-card version. Set dry_run=true first for a no-op report (current version / pending items / sources — no tokens, no write). Use when an admin asks to refresh/rebuild a topic's summary now.»
  - `properties`:
    - `topic_id`: `{"type": "STRING", "description": "The topic ID to re-summarize"}` — **required**.
    - `dry_run`: `{"type": "BOOLEAN", "description": "If true, only report the candidate context (current version, pending items, sources) WITHOUT re-summarizing — no LLM tokens, no DB write. Terminal (no confirmation needed)."}` — optional.
    - `confirm`: `{"type": "BOOLEAN", "description": <дословно как register_user L744-754 — two-phase preview/confirm, NEVER pass confirm=true yourself, BUG-009 hard rule>}`.
  - `required`: `["topic_id"]`.

### 3.2 Executor (code+test) — 3 ветки
`_exec_force_resummarize(args, current_user=None)` — зеркало `_exec_register_user` (L3069) + логика MCP `force_resummarize` (L2784) + CLI `_dry` (L359):
```
from tg_parser.auth.ownership import PermissionDenied, assert_admin
from tg_parser.auth.resolvers import get_default_admin
from tg_parser.services.db_context import resummarization_repos
from tg_parser.services.resummarization_service import ResummarizationService

user = current_user or await get_default_admin()
topic_id = args["topic_id"]
try:
    assert_admin(user)                 # admin ПЕРВЫМ — non-admin отсекается во всех ветках
except PermissionDenied as e:
    return {"error": e.message, "topic_id": topic_id}

dry_run = bool(args.get("dry_run", False))
confirm = bool(args.get("confirm", False))

# --- ВЕТКА A: dry_run — CLI-parity report (0 LLM, 0 mutation, ТЕРМИНАЛЬНО) ---
if dry_run:
    async with resummarization_repos() as (card_repo, bundle_repo, _v, _p, _db):
        card = await card_repo.get_by_id(topic_id)
        if card is None:
            return {"error": f"Topic not found: {topic_id}", "topic_id": topic_id}
        bundle = await bundle_repo.get_by_topic_id(topic_id)
        bundle_items_count = len(bundle.items) if bundle else 0
    return {
        "dry_run": True,
        "topic_id": topic_id,
        "title": card.title,
        "current_version": card.summary_version,
        "new_items_since_last_summary": card.new_items_since_last_summary,
        "bundle_items_count": bundle_items_count,
        "sources": list(card.sources),
        "user_facing_message": True,
        "message": (
            f"🔍 Dry-run для «{html.escape(str(topic_id))}»: версия "
            f"{card.summary_version}, новых элементов "
            f"{card.new_items_since_last_summary}, элементов в бандле "
            f"{bundle_items_count}. LLM не вызывался, версия не записывалась."
        ),
    }

# --- ВЕТКА B: rich preview (confirm не выставлен) ---
if not confirm:
    async with resummarization_repos() as (card_repo, _b, _v, _p, _db):
        card = await card_repo.get_by_id(topic_id)
        if card is None:
            return {"error": f"Topic not found: {topic_id}", "topic_id": topic_id}
    return {
        "preview": True,
        "tool": "force_resummarize",
        "topic_id": topic_id,
        "current_version": card.summary_version,
        "new_items_since_last_summary": card.new_items_since_last_summary,
        "sources": list(card.sources),
        "user_facing_message": True,
        "message": (
            f"Тема «{html.escape(str(topic_id))}» (текущая версия "
            f"{card.summary_version}, новых элементов "
            f"{card.new_items_since_last_summary}) будет немедленно "
            f"пересуммаризирована — вызов LLM (расход токенов), будет "
            f"записана новая версия сводки. Подтвердите [да/нет]."
        ),
    }

# --- ВЕТКА C: реальный запуск (confirm=True — framework-owned) ---
async with resummarization_repos() as (card_repo, bundle_repo, version_repo, proc_repo, _db):
    service = ResummarizationService(
        topic_card_repo=card_repo,
        topic_bundle_repo=bundle_repo,
        topic_card_version_repo=version_repo,
        processed_document_repo=proc_repo,
    )
    try:
        outcome = await service.resummarize_topic(topic_id)
    finally:
        await service.aclose()

return {"topic_id": topic_id, **outcome}
```
- **Billing/exception (gotcha #16 паритет):** ветка C **НЕ** оборачивает `resummarize_topic` в catch-and-return — `AnthropicBillingError` (и любой другой сбой) пробрасывается из executor'а; `execute_tool` typed-catch (BUG-005-B, L1306-1350) конвертирует его в `{"error": …, "error_class": "AnthropicBillingError"}` (а не «внутренняя ошибка»). `aclose()` в `finally` гарантирован даже на исключении — как в MCP.
- **`status='locked'`** — success-ish: возвращается в outcome-dict как есть, `"error"` НЕ добавляется (retry-семантика). Passthrough, как MCP.
- **dry_run vs preview vs confirm (§7 decision 5):** dry_run — терминальный **явный** report-only no-op (паритет CLI `--dry-run`); preview — авто-turn перед мутацией (что произойдёт на реальном запуске). Оба не мутируют, но dry_run не ведёт к confirm-turn, а preview — ведёт (framework replay с `confirm=True`). Не избыточны: dry_run вызывается пользователем осознанно; preview — обязательная фаза write-контракта.

### 3.3 Dispatch + классификация (code)
- `_TOOL_EXECUTORS` (L4743): `"force_resummarize": _exec_force_resummarize`.
- `_WRITE_TOOLS_REQUIRING_CONFIRM` (L110): `+ "force_resummarize"` (иначе BUG-009 guard не сработает **и** forward-контракт `test_bot_execute_tool_guard.py:317` red — раз у declaration есть `confirm`-param).
- **НЕ добавлять** в `_TOOLS_NEEDING_BOT_CONTEXT` (L86 — DB-only, bot/chat_id не нужны), `_READ_TOOLS_TRACKED_FOR_CONTEXT` (L161 — write), `_PAGINATED_READ_TOOLS` (L180 — outcome-dict, не list).

### 3.4 Prompt + guards (code+docs)
- [`prompts/bot.yaml`](../../prompts/bot.yaml):
  - Capability **#15** в нумерованный список (после L29): «15. Force an immediate re-summarize of a topic (admin only, after user confirmation)».
  - **write-ops инструкция L41** — добавить `force_resummarize` в перечень write-tool'ов (перечисление сейчас: trigger_pipeline … add_user_auth, remove_user_auth).
  - **Version bump `1.9.1 → 1.9.2`** в ТРЁХ синхронных местах: **L2** (`# Version:`), **L8** (`metadata.version` + при желании короткий changelog-фрагмент в `description`), **L31** (in-prompt `- Version:`). **Patch, НЕ `1.10.0`:** [`test_f9_phase2_prompt_defense.py:194`](../../tests/test_f9_phase2_prompt_defense.py) пинит `startswith("1.9")`; tuple-floor [`test_bot_read_context.py:642`](../../tests/test_bot_read_context.py) (`>= (1,8,0)`) — оба зелёные на 1.9.2.
- **Tool-count guards — ТРИ (все обновить, иначе CI red):** `assert len(TOOL_DECLARATIONS) == 34 → == 35` в [`test_bot_tools_v11.py:99`](../../tests/test_bot_tools_v11.py), [`test_bot_tools_v12.py:151`](../../tests/test_bot_tools_v12.py) **И** [`test_f5c_bot_topic_history.py:158`](../../tests/test_f5c_bot_topic_history.py) (последний добавлен sibling read-slice'ом — обнаружен на full-suite прогоне, см. §9-addendum). Новый `test_f5c_bot_force_resummarize.py` тоже пинит `== 35`.
- **Baseline-frozenset guard (BLOCKER):** [`test_bot_execute_tool_guard.py:360`](../../tests/test_bot_execute_tool_guard.py) `test_guard_set_matches_known_baseline` пинит **точный** frozenset из 15 write-tool'ов → добавить `"force_resummarize"` (16-й). Без этого — red, даже если всё остальное корректно. (Forward/reverse контракты L317/L327 станут зелёными автоматически, раз declaration+`_WRITE_TOOLS_REQUIRING_CONFIRM` синхронны.)
- **Presence + confirm-param** проверить в новом тест-файле (не пихать в v12-specific presence-set L141-147).

### 3.5 Docs (docs)
- [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) / #356 item A / #15 item #5 (write-часть) → **DONE**. Этот START_PROMPT → «landed» pointer (по завершении сессии).

---

## 4. Out of scope (жёстко)

- **Новый backend-код** — `ResummarizationService` / `resummarize_topic` / `resummarization_repos` / `assert_admin` reuse as-is; ничего не добавлять/менять.
- **MCP/CLI force_resummarize-surface** — не трогать (уже отгружено); это только bot-паритет (в т.ч. bot `dry_run` зеркалит CLI `--dry-run`, но CLI-код не меняем).
- **Per-topic visibility** — force_resummarize admin-only (как MCP `assert_admin`); НЕ добавлять `allowed_channel_ids`-intersect из read-slice (это была read-семантика).
- **Batch / all-topics re-summarize, планировщик-хуки из бота, кастомные prompt-оверрайды** — OUT.
- **Schema / migration / new deps / ADR** — surface-only.
- **`docs/methodology/**`, `pyproject.toml`, `requirements.txt`.**

---

## 5. Acceptance criteria

- [ ] **Один новый write-tool** `force_resummarize` объявлен в `TOOL_DECLARATIONS` (params `topic_id` required + `dry_run` BOOLEAN optional + `confirm` BOOLEAN framework-owned), зарегистрирован в `_TOOL_EXECUTORS` и в `_WRITE_TOOLS_REQUIRING_CONFIRM`.
- [ ] **Admin-only:** non-admin caller → `{"error": "Admin access required", "topic_id": …}`, **сервис НЕ создаётся** (side-effect'а нет), во всех трёх ветках. Mirror MCP `assert_admin`.
- [ ] **`dry_run=true`:** возвращает `{"dry_run": True, current_version, new_items_since_last_summary, bundle_items_count, sources, …}`; **ResummarizationService НЕ создаётся** (0 LLM, 0 mutation); missing card → typed «Topic not found»; терминально (confirm не нужен). Паритет CLI `_dry` L359.
- [ ] **RICH preview:** `confirm=false` (и `dry_run` не выставлен) → `{"preview": True, current_version, new_items_since_last_summary, sources, …}` (дешёвый `card_repo.get_by_id`); missing card → ранний typed «Topic not found»; side-effect'а нет.
- [ ] **Confirm-gating:** side-effect только на `confirm=true`, который **framework-owned** (BUG-009: LLM-issued `confirm=true` без FSM-state → `ConfirmFlowMismatch`, executor не вызывается).
- [ ] **Outcome-паритет с MCP:** `confirm=true` → `{"topic_id", **outcome}` (status ok/locked/no_card/…); `status='locked'` — success-ish (без `"error"`); `aclose()` вызван в обоих путях (успех и исключение).
- [ ] **Billing propagates:** executor не глотает `AnthropicBillingError` → `execute_tool` возвращает `error_class="AnthropicBillingError"` (не generic); `aclose` при этом вызван.
- [ ] **Классификация:** в `_WRITE_TOOLS_REQUIRING_CONFIRM`; **НЕ** в `_TOOLS_NEEDING_BOT_CONTEXT` / `_READ_TOOLS_TRACKED_FOR_CONTEXT` / `_PAGINATED_READ_TOOLS`.
- [ ] **Guards обновлены:** `len(TOOL_DECLARATIONS) == 35` в обоих `test_bot_tools_v11.py:99` + `test_bot_tools_v12.py:151`; `test_bot_execute_tool_guard.py:360` baseline содержит `force_resummarize`; forward/reverse контракты (L317/L327) зелёные; `bot.yaml` version `1.9.2` синхронно L2/L8/L31; `test_f9_phase2_prompt_defense.py:194` + `test_bot_read_context.py:642` — зелёные.
- [ ] **Нет новых deps** (ADR-0017); **нет** schema-change / migration / ADR.
- [ ] `uv run ruff check .` + `uv run ruff format --check .` + `TEST_POSTGRES=1 uv run pytest -q` — green.
- [ ] **Deploy (no-migration):** re-create `tg_bot` (`up -d --no-deps`, НЕ restart); smoke — админ «пересуммаризируй тему X» → preview → «да» → outcome. `db upgrade` / backup **не** требуются.
- [ ] Commit/PR только по явному запросу пользователя.

---

## 6. Quality / ops gate commands

```bash
# repo quality (local, всегда)
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
# PR-standard (трогаем bot + guard-тесты → нужен Postgres для полного прогона):
TEST_POSTGRES=1 uv run pytest -q
# точечно:
uv run pytest -q tests/test_f5c_bot_force_resummarize.py \
  tests/test_bot_execute_tool_guard.py \
  tests/test_bot_tools_v11.py tests/test_bot_tools_v12.py \
  tests/test_f9_phase2_prompt_defense.py tests/test_bot_read_context.py
# Runner note: tests/README.md предпочитает `.venv/bin/python -m pytest`; `uv run pytest` — принятый эквивалент.

# reload prompts без рестарта (если только bot.yaml менялся, для быстрой проверки): MCP/bot tool `reload_prompts`

# Deploy (NO-migration, surface-only):
git checkout main && git pull --ff-only origin main
docker compose build tg_parser                 # образ tg_parser:latest шарится всеми сервисами
docker compose up -d --no-deps tg_bot          # RE-CREATE (НЕ restart — BUG-078)
# smoke: админ в @Tgingest_bot: «пересуммаризируй тему <topic_id>» → preview → «да» → status
```

_**NO-migration deploy:** фича surface-only — новых колонок нет ⇒ `db upgrade`/backup не требуются. Достаточно re-create образа `tg_bot`._

---

## 7. Decisions (baked)

1. **Паритет, не редизайн** — bot-tool 1:1 зеркалит MCP `force_resummarize` (outcome-shape, admin-gate, aclose-в-finally, billing-propagation); никакой новой семантики.
2. **Reuse backend as-is** — `ResummarizationService.resummarize_topic` / `resummarization_repos` / `assert_admin`; ноль нового service/repo-кода.
3. **Admin-only, НЕ per-topic visibility** — как MCP (`assert_admin`); read-slice'ов `allowed_channel_ids`-intersect здесь НЕ применяется (это была read-семантика). `assert_admin` выполняется **до** preview-gate — non-admin отсекается даже на preview-turn (mirror `_exec_register_user` L3090-3093).
4. **Confirm-gating (two-phase, BUG-009)** — `confirm=false` → `{"preview": True}`; `confirm=true` — только через FSM (framework-owned); executor читает `confirm`, но **никогда** не доверяет LLM-issued `confirm=true` (структурно защищено `execute_tool` guard L1291). Регистрация в `_WRITE_TOOLS_REQUIRING_CONFIRM` обязательна.
5. **`dry_run` IN + RICH preview (решения owner'а, 2026-07-25).** Обе фазы читают карточку, но роли разные и НЕ избыточны:
   - **`dry_run=true`** — **явный** report-only no-op (паритет CLI `topic resummarize --dry-run`, `_dry` L359): `card_repo.get_by_id` + `bundle_repo.get_by_topic_id`, возвращает current_version / new_items / bundle_items_count / sources, **0 LLM, 0 mutation, терминально** (confirm НЕ нужен — ничего не мутирует). Пользователь вызывает осознанно, чтобы «посмотреть, что есть».
   - **RICH preview** (`confirm=false`) — **обязательная** первая фаза write-контракта: дешёвый `card_repo.get_by_id` показывает current_version / new_items / sources + ранний typed «Topic not found», и всегда ведёт к confirm-turn (framework replay с `confirm=True` запускает реальный re-summarize). Тратит 0 токенов, но семантически это «подтверди мутацию», а не «report».
   - FSM-snapshot match (BUG-009) не ломается: dry_run терминален (никогда не порождает confirm-replay); preview-call args (`{topic_id}`) реплеятся как `{topic_id, confirm:True}` — dry_run в snapshot не участвует.
6. **`status='locked'` — success-ish** — passthrough в outcome без `"error"` (retry-семантика, mirror MCP `test_locked_status_passes_through` L503).
7. **Billing НЕ глотать** — executor не оборачивает вызов в catch-and-return; `execute_tool` typed-catch даёт `error_class="AnthropicBillingError"` (mirror MCP `test_billing_error_propagates` L531; gotcha #16).
8. **NO-migration / NO-ADR** — surface-only; schema/contracts/deps не тронуты. Deploy = re-create `tg_bot` (BUG-078).
9. **Guard-hygiene (verified review-pass)** — в ТОМ ЖЕ PR: **ДВА** tool-count baseline'а (`v11:99` + `v12:151`) `34 → 35`; **baseline-frozenset** `test_bot_execute_tool_guard.py:360` +`force_resummarize`; `bot.yaml` version → **`1.9.2`** (patch, синхронно L2/L8/L31).

---

## 8. Нужен ли новый ADR? — **НЕТ**

Фича **не** меняет ни один контракт: не добавляет колонок, не меняет data-model, не вводит новых deps, не меняет delivery-семантику. Это чистое **surface-parity** расширение поверх уже отгруженного MCP `force_resummarize` + `ResummarizationService` и существующего bot-tool + BUG-009 confirm-фреймворка. ADR не требуется. Достаточно `bot.yaml` version bump + guard-обновления + FUTURE_FEATURES отметки. (Confirm-gating и admin-gating — не новые инварианты, а переиспользование уже задокументированных: BUG-009 / ADR-контекст write-surface.)

---

## 9. Self-review fixes applied (START_PROMPT)

Adversarial pass — пофайловое перечитывание каждого якоря на актуальном дереве (`be90058`), проверка confirm/admin-claims против реального кода шаблонных executor'ов, проверка version/count-семантики против реальных пиннинг-тестов. Найдено **2 BLOCKER + 2 MAJOR**, все внесены в план:

1. **(BLOCKER B1) Забытый baseline-frozenset guard.** [`tests/test_bot_execute_tool_guard.py:360`](../../tests/test_bot_execute_tool_guard.py) `test_guard_set_matches_known_baseline` пинит **точный** набор из 15 write-tool'ов. Добавление `force_resummarize` в `_WRITE_TOOLS_REQUIRING_CONFIRM` **обязано** сопровождаться правкой этого baseline (→16 tool'ов), иначе CI red независимо от корректности остального. Task-бриф упоминал forward/reverse-контракты, но именно этот **третий** тест (жёсткий baseline) — реальный CI-blocker. Внесено: §0 step5, §2 anchor, §3.4, §5.
2. **(BLOCKER B2) Version уже `1.9.1`, а не `1.9.0`.** Sibling read-slice (PR #355) уже поднял `bot.yaml` до **1.9.1** (verified L2/L8/L31) и tool-count guards до **34** (не 32). Task-бриф говорил «1.9.1 → 1.9.2» — это верно; но исходная предпосылка «34→35» тоже нужно было подтвердить фактом (подтверждено: оба guard'а сейчас `== 34`). Рекомендация `1.9.1 → 1.9.2` (patch) удерживает floor `startswith("1.9")` (test_f9:194) и `>= (1,8,0)` (read_context:642). Внесено: §0, §2, §3.4, §7.9.
3. **(MAJOR M1) In-prompt `- Version:` сместился на L31 (не L30).** Из-за добавленной sibling'ом capability-строки #14 (L29) in-prompt version-строка теперь **L31**, а нумерованный список идёт **до #14** (L15-29). Новую capability добавляем как **#15**. Task-бриф ссылался на «~L40 write-ops / ~L15-28 list / #14» — уточнено фактическими номерами (write-ops = **L41**, список **L15-29**). Внесено: §2, §3.4.
4. **(MAJOR M2) Billing-propagation в боте работает иначе, чем в MCP — но результат-паритет сохраняется.** MCP просто **не ловит** `AnthropicBillingError` (пробрасывает наружу). В боте любой executor выполняется под `execute_tool` broad typed-catch (BUG-005-B, L1342-1350), который конвертирует исключение в `{"error", "error_class"}`. ⇒ Правильный контракт для bot-executor'а: **НЕ** оборачивать `resummarize_topic` в свой catch-and-return-ok (иначе billing-error замаскируется под успех/preview) — пробросить, и `execute_tool` вернёт `error_class="AnthropicBillingError"`. `aclose()` — в `finally`, вызывается и на исключении. Тест-паритет: unit `pytest.raises(AnthropicBillingError)` на самом executor'е + через `execute_tool` проверить `error_class`. Внесено: §3.2, §5, §7.7, §9.

Дополнительно подтверждено пофайловым чтением (no invented symbols):
5. **`_TOOLS_NEEDING_BOT_CONTEXT` (L86)** содержит только `export_channel`/`subscribe_digest`/`subscribe_watchlist` ⇒ `force_resummarize` DB-only, bot/chat_id не нужны — **не** добавлять. (Подтверждает предпосылку брифа.)
6. **Executor-шаблон = `_exec_register_user` (L3069)** — точный порядок: `assert_admin` **до** preview-gate (non-admin отсекается на preview-turn), `confirm = bool(args.get("confirm", False))`, `{"preview": True, "user_facing_message": True, "message": …}`, мутация под `confirm`. `PermissionDenied.message` («Admin access required») используется в возврате (как MCP L2813 и register_user L3093).
7. **`confirm`-param декларируется дословно** как в `register_user` (L744) / `update_user` (L777) — с BUG-009 hard-rule «NEVER pass confirm=true yourself». Это удовлетворяет forward-контракт `test_bot_execute_tool_guard.py:317` (declaration confirm-param ⇔ членство в guard-set).
8. **MCP-контракт-тесты** ([`test_f5c_mcp_tools.py`](../../tests/test_f5c_mcp_tools.py) `TestForceResummarize` L462-591) — прямой источник acceptance-паритета: admin+aclose (L463), locked passthrough (L503), billing propagates (L531), non-admin без создания сервиса (L564), aclose-on-raise (L589). Зеркалим все пять в bot-тестах.
9. **CLI `resummarize` (L340)** — фактически **не** вызывает `assert_admin` (локальный CLI-контекст; admin-гейт — свойство MCP/bot surface, не CLI). Так что «CLI admin-only» из брифа неточно для CLI-слоя; для bot-tool'а admin-гейт берём из **MCP**-эталона, не из CLI. Зафиксировано в §1/§7.3 без переноса CLI-поведения.

### 9-addendum. Owner-decisions baked (2026-07-25, ревью initial-plan)

Owner принял 2 решения по open questions §4 initial-плана; оба внесены в §0/§2/§3/§5/§7 и реализованы:

- **D1 — RICH preview (было: minimal).** На `confirm=false` executor делает дешёвый `card_repo.get_by_id(topic_id)` и возвращает `current_version` / `new_items_since_last_summary` / `sources` + **ранний** typed `{"error": "Topic not found: …"}` (вместо позднего `status='no_card'` на commit-turn). Bot-аналог видимости CLI `--dry-run`, но семантически это pre-confirm summary живой карточки. 0 токенов.
- **D2 — `dry_run` IN (было: OUT).** Добавлен параметр `dry_run` BOOLEAN для полного паритета с CLI `tg-parser topic resummarize --dry-run`. **Что делает CLI `--dry-run` (перечитан `_dry` L359-380 + печать L419-426):** открывает `resummarization_repos`, `card_repo.get_by_id` (None → not_found), `bundle_repo.get_by_topic_id`, `bundle_items_count = len(bundle.items) if bundle else 0`; печатает title / current_version=`card.summary_version` / `new_items_since_last_summary` / bundle items / sources; **НЕ** вызывает LLM и **НЕ** пишет версию. Bot-ветка A зеркалит это in-process и возвращает те же поля + `dry_run: True`; **терминальна** (confirm не нужен, ничего не мутирует).

**Новые/уточнённые anchors (D1/D2):**
- CLI `_dry` internals **L359-380** + печать **L419-426** (`cli/topic_cmd.py`) — источник семантики ветки A.
- `bundle_repo.get_by_topic_id` (yielded из `resummarization_repos` L350) — для `bundle_items_count`.
- `TopicCard` поля (`title` / `summary_version` / `new_items_since_last_summary` / `sources`) — `domain/models.py`.

**Проверка непротиворечивости (D1/D2 vs guards):** dry_run/ preview добавляют только read-ветки перед мутацией — count/confirm-контракты не меняются (tool всё ещё один, `confirm`-param присутствует ⇒ forward/reverse L317/L327 + baseline L360 зелёные с `force_resummarize`). `dry_run` **не** входит в FSM-snapshot preview-call (preview зовётся без dry_run), поэтому BUG-009 args-match не ломается. Ветка A терминальна ⇒ не конфликтует с confirm-gate.

**Реализация — фактические изменения (2026-07-25):** `tg_parser/bot/tools.py` (declaration + `_exec_force_resummarize` + `_TOOL_EXECUTORS` + `_WRITE_TOOLS_REQUIRING_CONFIRM`), `prompts/bot.yaml` (v1.9.2 ×3 + capability #15 + write-ops строка), `tests/test_bot_tools_v11.py` / `test_bot_tools_v12.py` (34→35), `tests/test_bot_execute_tool_guard.py` (baseline +`force_resummarize`), новый `tests/test_f5c_bot_force_resummarize.py`.

**Deviation (обнаружено на full-suite прогоне):** был **третий** tool-count guard — `tests/test_f5c_bot_topic_history.py:158` (`== 34`), добавленный sibling read-slice'ом и не замеченный при initial-план self-review (grep initial-плана нашёл только v11/v12). Обновлён до `== 35`. Урок: sibling-slice'ы могут ставить собственные count-пины в своих тест-файлах — при добавлении tool'а искать `len(TOOL_DECLARATIONS) ==` по **всему** `tests/`, а не только в v11/v12. §2/§3.4 обновлены (ТРИ guard'а).

---

## 11. Post-deploy addendum — BUG-086 (2026-07-25, manual prod smoke)

> **Слайс отгружен и задеплоен** (`88d4c94` → [PR #357](https://github.com/AlexEfimov/TG_parser/pull/357) → `main`=`b6c21ef`), после чего **ручной smoke в проде выявил severe bot-defect** — `docs/notes/BUG_LOG.md` § **BUG-086**. Фикс сделан на ветке `fix/bot-force-resummarize-confirm-flow` (commit/deploy — по явному запросу owner'а).

**Симптом.** «покажи, что будет, если пере-суммаризировать тему X» → корректный dry-run report. Затем «пере-суммаризируй тему X» (**реальный** mutation-запрос) → бот повторил **тот же dry-run report** и дописал собственное «Подтвердите, пожалуйста, пере-суммаризацию … [да/нет]». Ответ «да» → «Я не совсем понимаю ваш ответ» — dead-end, re-summarize так и не запускался.

**Root cause (подтверждён prod-логами).** Два сцепленных дефекта:
1. **Неверная форма вызова.** `agent_tool_call` на mutation-turn (`request_id=28b0d1c9`) — `args={"dry_run": true, "topic_id": …}`, `confirm` **отсутствует**, т.е. идентично read-only turn'у. Формулировка декларации «Set dry_run=true **first** for a no-op report» (§3.1 этого плана) читается как «шаг ПЕРЕД реальным запуском» — LLM использовал report-форму для обоих интентов (`mode=AUTO`, temp 0.2).
2. **Framework не мог вооружить ConfirmFlow.** Ветка A возвращает report **без** `preview: True`, а `agent.py` выставляет `preview_pending` **только** на `result.get("preview") is True` — единственный путь арминга ConfirmFlow. В логах того turn'а **нет `fsm_confirm_armed`**. ⇒ LLM сам сочинил confirm-фразу, «да» пришло при `current_state is None` → stateless LLM turn → opaque fallback. Это **дословно** механизм BUG-046, переоткрытый новым preview-less shape'ом внутри confirm-gated write-tool'а.
3. **Латентный третий дефект** (найден при фиксе): `dry_run` проверялся ДО `confirm`, поэтому `dry_run=true, confirm=true` молча возвращал report — **подтверждённая** мутация становилась no-op'ом.

**Где план оказался неточен (урок для будущих slice'ов).** §7 decision 5 и §9-addendum D2 объявили `dry_run` «терминальным ⇒ не конфликтует с confirm-gate» и признали непротиворечивость только по линии **BUG-009 args-match** (dry_run не попадает в FSM-snapshot — это верно). Не рассмотрен был **обратный** риск: терминальная ветка, не возвращающая `preview: True`, — это ровно та конфигурация, из которой родился BUG-046 (LLM сочиняет confirm, FSM не вооружён). Формулировка «Set dry_run=true **first**» усилила риск, подтолкнув LLM к report-форме на mutation-интенте. **Урок:** добавляя в confirm-gated write-tool любую вторую (report-only) форму, обязательно проверять её против BUG-046-класса, а не только против BUG-009 args-match, и покрывать **кросс-branch FSM-контракт** (а не только каждую ветку по отдельности).

**Фикс (3 слоя, слабый → сильный).**
- **(a) Prompt** — `prompts/bot.yaml` **1.9.2 → 1.9.3** (три места, внутри пина `startswith("1.9")`): HARD RULE, разделяющий две формы вызова (`dry_run=true` только на явный «что будет / покажи без запуска / dry-run»; реальный запрос — `confirm=false` **без** `dry_run`; никогда не сочинять своё «Подтвердите … [да/нет]»; никогда не ставить `confirm=true` — BUG-009). Переписаны и описания в самой декларации (убрано вводящее в заблуждение «first»).
- **(b) Executor guard** — `dry_run` + `confirm` вместе → `error_class="InvalidArguments"` **до** обеих ветвей (убивает silent no-op); dry-run payload несёт машиночитаемые `terminal: True` / `mutation_requires_confirm_preview_turn: True` / `next_step`.
- **(c) Структурный guard (несущий)** — `tg_parser/bot/agent.py` `_recover_llm_authored_confirm`: agent-loop запоминает confirm-gated write-вызовы **без** preview; если turn заканчивается текстом, попадающим под узкий `_LLM_AUTHORED_CONFIRM_PATTERN`, а FSM не вооружён — framework **детерминированно** переиздаёт тот же tool в preview-форме (`confirm` убран, `_PREVIEW_SUPPRESSING_ARGS`=`{"dry_run"}` вырезаны) и вооружает ConfirmFlow сам. Тот же паттерн, что `handlers._arm_delete_preview`. Семантика BUG-009 **не менялась**.

**Тесты.** `tests/test_f5c_bot_force_resummarize.py` дополнен блоком BUG-086: `TestDryRunIsTerminal`, `TestLlmAuthoredConfirmRecovery` (включая **точный prod-trace** на уровне `GeminiAgent.process_message`), `TestLlmAuthoredConfirmDetector`, `TestPromptHardRule`. Red→green проверен против pre-fix дерева (`b6c21ef`: `preview_pending=None`).

**Решение owner'а (2026-07-25, baked).** `dry_run` **остаётся** в bot-декларации — он структурно безопасен после слоя (c), а UX «покажи без запуска» в проде отработал корректно. Компромисс осознан и зафиксирован: `dry_run` — единственная report-only форма внутри confirm-gated write-tool'а, поэтому слой (c) обязателен, а реестр `_PREVIEW_SUPPRESSING_ARGS` становится нормативным (см. tripwire ниже). CLI `--dry-run` / MCP не затрагивались ни в одном варианте.

**Промоушен guard'а в общий suite (2026-07-25, решение owner'а).** Слой (c) живёт в agent-loop и защищает **весь** `_WRITE_TOOLS_REQUIRING_CONFIRM`, поэтому контракт поднят из F5-C-файла в общий ConfirmFlow-suite [`tests/test_bot_confirm_flow.py`](../../tests/test_bot_confirm_flow.py) § 9 — не копией, а **обобщением**:
- `TestLlmAuthoredConfirmRecoveryIsToolAgnostic` — guard вооружает ConfirmFlow для tool'а, у которого `dry_run` **нет вовсе** (`remove_channel`; preview-less первый вызов получен через BUG-009-rejection), плюс инварианты «recovery никогда не возвращает `confirm` в args» и «настоящий preview не переиздаётся дважды»;
- `TestPreviewSuppressingArgRegistryIsComplete` — tripwire, сканирующий декларации: любой report-only флаг (`dry_run` / `simulate` / `report_only` / …) на confirm-gated write-tool'е, не зарегистрированный в `agent._PREVIEW_SUPPRESSING_ARGS`, роняет CI. Это закрывает единственный способ будущего tool'а молча переоткрыть BUG-086 — ровно тот пробел, который в § «Why CI didn't catch» назван как «nothing generalised it».

Mutation-проверка: отключение вызова guard'а в `agent.py` роняет tool-agnostic-кейс с точным прод-симптомом (`preview_pending=None` + самосочинённый текст подтверждения).

**Дефект внутри самого фикса — слой (c′), найден Bugbot-ревью до коммита.** Первая версия `_LLM_AUTHORED_CONFIRM_PATTERN` принимала одиночное слово `confirm`, а `next_step` из слоя (b) буквально говорит LLM «call again with **confirm=false** … do NOT ask the user to **confirm** this report» — то есть подсказка, добавленная тем же фиксом, кормила детектор. Пересказ этой подсказки на **легитимном** read-only dry-run turn'е попадал под детектор ⇒ recovery подменял запрошенный отчёт мутационным preview и вооружал ConfirmFlow ⇒ случайное «да» сожгло бы LLM-токены на пере-суммаризацию, которую пользователь не просил. Это ровно тот сценарий, ради которого `dry_run` сознательно **не** возвращает `preview: True`. Исправлено четырьмя шагами: детектор опирается на **структуру просьбы** (`подтвердите` / `подтверждаете` / `[да/нет]` / `[yes/no]` / `please confirm` / `confirm?` / `do you confirm`), а не на упоминание слова; argument-литералы (`confirm=…`, `dry_run=…`) вычищаются `_ARG_LITERAL_PATTERN` до матчинга (плюмбинг, пересказанный пользователю, не является просьбой); `next_step` переформулирован без голого глагола (defense in depth); решение проведено через единственный продовый хелпер `_looks_like_llm_authored_confirm`, чтобы тест не мог продублировать scrub у себя и замаскировать регрессию — эта слабость обнаружилась именно на mutation-проверке. Регрессии: `test_dry_run_paraphrasing_the_next_step_hint_stays_terminal`, `test_argument_literals_are_not_a_confirmation_ask`, `test_detector_ignores_the_dry_run_payloads_own_next_step` (читает `next_step` из живого payload). Возврат bare-`confirm` роняет все три.

**Урок в копилку к §11.** Оба дефекта этой сессии — и исходный, и (c′) — родились из одного и того же: **машиночитаемая подсказка, адресованная LLM, попадает в пользовательский текст и меняет поведение framework'а**. Добавляя в payload поле, которое LLM будет пересказывать, надо проверять его против всех детекторов, которые читают итоговый текст turn'а.

Gate после промоушена и (c′): ruff clean, **4038 passed / 22 skipped**.

---

## 10. Ссылки

- MCP-эталон: [`mcp_server.py`](../../tg_parser/mcp_server.py) `force_resummarize` L2784; контракт [`tests/test_f5c_mcp_tools.py`](../../tests/test_f5c_mcp_tools.py) `TestForceResummarize` L462
- CLI-эталон: [`cli/topic_cmd.py`](../../tg_parser/cli/topic_cmd.py) `resummarize` L340
- Bot framework: [`bot/tools.py`](../../tg_parser/bot/tools.py) `TOOL_DECLARATIONS` L265, `register_user` decl L729 (`confirm` L744), `_exec_register_user` L3069, `_exec_trigger_pipeline` L2375, dispatch `_TOOL_EXECUTORS` L4743, `_WRITE_TOOLS_REQUIRING_CONFIRM` L110, `_TOOLS_NEEDING_BOT_CONTEXT` L86, `_check_confirm_flow_match` L1195, `execute_tool` L1256
- Backend (reuse): [`resummarization_service.py`](../../tg_parser/services/resummarization_service.py) L139/L307/L853; [`db_context.py`](../../tg_parser/services/db_context.py) `resummarization_repos` L350; [`ownership.py`](../../tg_parser/auth/ownership.py) `assert_admin` L97; [`errors.py`](../../tg_parser/processing/llm/errors.py) `AnthropicBillingError` L4
- Guards: tool-count [`test_bot_tools_v11.py`](../../tests/test_bot_tools_v11.py) L99 + [`test_bot_tools_v12.py`](../../tests/test_bot_tools_v12.py) L151; baseline [`test_bot_execute_tool_guard.py`](../../tests/test_bot_execute_tool_guard.py) L360 (+forward L317/reverse L327); version-pin [`test_f9_phase2_prompt_defense.py`](../../tests/test_f9_phase2_prompt_defense.py) L194 + floor [`test_bot_read_context.py`](../../tests/test_bot_read_context.py) L642
- Prompt: [`prompts/bot.yaml`](../../prompts/bot.yaml) version L2/L8/L31 + capabilities L15-29 + write-ops L41
- Roadmap: Issue [#356](https://github.com/AlexEfimov/TG_parser/issues/356) item A / [#15](https://github.com/AlexEfimov/TG_parser/issues/15) item #5 (write-часть)
- Сосед (read-часть, стиль-эталон): [`START_PROMPT_SESSION_F5C_BOT_TOOLS_2026-07-24.md`](START_PROMPT_SESSION_F5C_BOT_TOOLS_2026-07-24.md)
- ADR [0006](../adr/0006-karpathy-like-living-kb-principles.md), [0017](../adr/0017-dependency-management-policy.md), [0018](../adr/0018-topic-card-versions-retention.md)
