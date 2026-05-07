# Documentation Hygiene Sprint — между Session K и F4-B Core planning (2026-05-XX)

---

## 0. Когда стартовать

**После:**
- Merge Session K PR (`docs/session-k-wave1-step1-done-2026-05-08`).
- Merge runbook nomenclature hotfix PR [#63](https://github.com/AlexEfimov/TG_parser/pull/63) (`docs/hotfix-runbook-nomenclature-2026-05-08`, `Closes #62`), если он шёл отдельно.

**До:**
- F4-B Core planning sub-session в fresh chat (см. Session K § 5.3).

**Размер:** ~0.5–1 сессии. Single PR, 4 atomic commits, docs-only, no deploy.

**Зачем именно сейчас:** F4-B planning — это первая сессия после Wave 1 step 1 closure. Агент будет читать README / USER_GUIDE / architecture / SERVER_ARCHITECTURE / mcp-management-tools-spec для контекста. Если там tools counts, версии, MVP-формулировки расходятся с реальностью — F4-B planning получит ложный baseline. Hygiene sprint фиксирует это **до** F4-B, чтобы dependent сессии работали с чистым contextом.

---

## Что фиксим (по аудит-отчёту 2026-05-07)

| Audit ID | Что | Severity | Файлы |
|---|---|---|---|
| **M-1** | Tools count drift (24/17 → 35 MCP / 32 bot) | MAJOR | README.md, USER_GUIDE.md, SERVER_ARCHITECTURE.md, mcp-management-tools-spec.md, chatgpt-mcp-compatibility.md, mcp-clients-compatibility.md |
| **M-2** | Версионная асинхрония (4.3 / 4.2.0 / 1.27.0) | MAJOR | README.md, mcp-clients-compatibility.md, chatgpt-mcp-compatibility.md |
| **M-3** | ADR 0001/0003/0004 без implementation-status sections | MAJOR | docs/adr/0001, 0003, 0004 |
| **M-7** | architecture.md (MVP+SQLite) vs SERVER_ARCHITECTURE (production+PostgreSQL) | MAJOR | docs/architecture.md |
| **M-8** | business-requirements / product-overview MVP «без HTTP API» | MAJOR | docs/business-requirements.md, docs/product-overview.md |
| **M-15** | chatgpt-mcp-compatibility внутренние противоречия + честность по CORS | MAJOR | docs/chatgpt-mcp-compatibility.md |
| **M-16** | mcp-management-tools-spec неполная | MAJOR | docs/mcp-management-tools-spec.md |
| **C-3** | Двойное определение «Wave 1» (Living-KB vs Audience) | CRITICAL (опц.) | docs/notes/ROADMAP_V3_PRODUCTION_FIRST.md |
| **M-14** | BUG_LOG resolved в § Active секции | MAJOR (housekeeping) | docs/notes/BUG_LOG.md |
| **+** | testing-strategy.md устаревший (SQLite-ориентирован) | MAJOR | docs/testing-strategy.md |

**НЕ в scope этого sprint'а:**
- M-6 (contract hardening — content_hash + missing validators) — отдельный sprint.
- M-11/M-12/M-17 (code mini-fixes) — opportunistic в любой bot-touch sprint.
- Runbook nomenclature (C-1/C-2) — закрыто в hotfix PR [#63](https://github.com/AlexEfimov/TG_parser/pull/63) (`Closes #62`).
- ADR 0005 annotation — уже в Session K extended scope.
- Superseded markers FUTURE_FEATURES / SESSION48 / Session29 — уже в Session K extended scope.

---

## Opener (вставить в новый чат)

> Стартую documentation hygiene sprint (post-Session-K, pre-F4B-planning).
> Прочитай `docs/notes/START_PROMPT_DOC_HYGIENE_2026-05-XX.md` целиком +
> `pyproject.toml` (version) + `tg_parser/mcp_server.py` (grep `@mcp.tool()` count) +
> `tg_parser/bot/tools.py` (TOOL_DECLARATIONS count).
> Затем исполни 4 atomic commits в порядке C1 → C4 (см. § 4 этого промпта).
> Branch: `docs/hygiene-2026-05-XX`.
> **НЕ** трогать код / migrations / runbooks / docker-compose.
> **НЕ** редактировать `pyproject.toml` (ADR 0001 — без явного запроса);
> только читать оттуда `version` для sync README.
> Anti-scope (см. § 6) исполнять буквально.

---

## 1. Pre-flight (минимальный)

```bash
# 1. На main, чистый worktree
git checkout main && git pull --ff-only origin main && git status

# 2. Source of truth — собрать factual numbers ОДИН РАЗ перед началом правок
# (используются во всех 4 commits — не пересчитывать снова per file)

echo "=== pyproject version ==="
grep '^version' pyproject.toml

echo "=== MCP tools count ==="
grep -c '^@mcp.tool()' tg_parser/mcp_server.py

echo "=== Bot tools count (TOOL_DECLARATIONS) ==="
python3 -c "from tg_parser.bot.tools import TOOL_DECLARATIONS; print(len(TOOL_DECLARATIONS))"

echo "=== Full MCP tools list ==="
grep -A1 '^@mcp.tool()' tg_parser/mcp_server.py | grep '^async def\|^def' | awk '{print $2}' | sed 's/(.*//' | sort
```

Записать значения для использования в правках:
- `PYPROJECT_VERSION` = (например `4.2.0`)
- `MCP_TOOLS_COUNT` = (например `35`)
- `BOT_TOOLS_COUNT` = (например `32`)
- `MCP_TOOLS_LIST` = sorted list (для mcp-management-tools-spec validation)

---

## 2. Branch + GH issue

```bash
git checkout -b docs/hygiene-2026-05-XX

# (опционально) GH issue для traceability
gh issue create \
  --title "docs(hygiene): sync tools counts + versions + ADR implementation status + MVP banners" \
  --label "documentation,priority/p1" \
  --body "Self-review актуальной документации проекта 2026-05-07 нашёл ~10 расхождений между docs и реальностью кода. Этот sprint фиксит M-1, M-2, M-3, M-7, M-8, M-15, M-16, M-14, C-3, testing-strategy. См. \`docs/notes/START_PROMPT_DOC_HYGIENE_2026-05-XX.md\`."
```

---

## 3. Контекст — почему 4 commits, не один

Hygiene sprint трогает **много файлов**, но они группируются по **типу правки**, не по файлу. Атомарные коммиты по типу = чистая git history + независимый rollback per scope:

```
C1 (fact-sync):       README + USER_GUIDE + SERVER_ARCHITECTURE — реальные tools counts + версия
C2 (mcp-spec):        mcp-management-tools-spec + chatgpt-mcp-compatibility + mcp-clients-compatibility
C3 (adr-status):      ADR 0001 + 0003 + 0004 implementation-status blocks
C4 (mvp-banners):     architecture.md + business-requirements.md + product-overview.md + testing-strategy.md + ROADMAP_V3 disambiguation + BUG_LOG resolved cleanup
```

Если PR-review требует mini-PR'ы per commit — раздать на 4 отдельных PR. По умолчанию **single PR с 4 atomic commits**.

---

## 4. Commits

### Commit 1 (C1) — Fact sync: tools counts + version

#### 4.1 README.md

Найти все упоминания «24 инструмента» / «24 tools» (примерно L19-20 + по файлу).

Заменить на actual `MCP_TOOLS_COUNT` (например 35) и `BOT_TOOLS_COUNT` (например 32):

```markdown
- **MCP Server** — 35 инструментов для search/Q&A/management
  ([полный список](docs/mcp-management-tools-spec.md)).
- **Telegram Bot** — 32 tools (subset из MCP — без admin-only F5-C / export).
```

> Если число tools отличается на момент старта sprint'а от 35/32 — использовать **factual** значение из § 1.

Найти `Версия проекта: 4.3` (или эквивалент в шапке). Заменить на `Версия: <PYPROJECT_VERSION>` (например `4.2.0`).

Если в README есть архитектурное дерево, и оно не отражает `bot/` + `mcp_server.py` — добавить строки соответствующие реальному `tg_parser/` layout. Минимально:

```
tg_parser/
├── api/         # FastAPI HTTP endpoints
├── bot/         # Telegram bot (aiogram + Gemini agent)
├── cli/         # CLI entrypoints
├── mcp_server.py # MCP server (35 tools)
├── ingestion/   # Telethon MTProto ingestion
├── processing/  # LLM-based knowledge extraction
├── services/    # Domain services (RAG, watchlist, resummarize, ...)
├── storage/     # SQLAlchemy + PostgreSQL repos
├── domain/      # Domain models (Pydantic) + contracts
└── auth/        # F4-A multi-tenancy
```

#### 4.2 USER_GUIDE.md

Заменить `24 инструмента` → актуальное значение. Также **добавить cross-link на `docs/runbooks/BOT_LLM_FALLBACK.md`** (per audit H — runbook не упомянут в USER_GUIDE).

Минимальная вставка в подходящую секцию (например, «Operational procedures» или «Troubleshooting»):

```markdown
### Telegram Bot — Gemini outage handling

При недоступности Google Gemini API оператору доступен manual fallback per
[`docs/runbooks/BOT_LLM_FALLBACK.md`](runbooks/BOT_LLM_FALLBACK.md). Bot scope
LLM config поддерживает runtime model switching (ADR 0005 D-3) без рестарта.
```

#### 4.3 SERVER_ARCHITECTURE.md

В MCP-секции найти «**Tools (17)**» (или другое число) и заменить на актуальное `MCP_TOOLS_COUNT`. Если есть короткий список — пометить «полный список см. mcp-management-tools-spec.md».

> Если в Session K extended scope (commit C3) уже была обновлена scrape-targets таблица в SERVER_ARCHITECTURE — **не дублировать** правку. Если merge Session K ещё не произошёл — добавить scrape-targets edit в этот же commit (с флагом «possibly redundant; verify after Session K merge»).

#### 4.4 Commit message

```
docs: sync tools counts (35 MCP / 32 bot) + version (pyproject SoT) — fact-sync

README + USER_GUIDE + SERVER_ARCHITECTURE содержали устаревшие tools counts
(«24 / 17») и версию (4.3 в README vs pyproject 4.2.0). Single source of
truth — pyproject.toml для version, mcp_server.py @mcp.tool() для MCP count,
bot/tools.py TOOL_DECLARATIONS для bot count.

- README.md: tools count 24 → <MCP_TOOLS_COUNT>/<BOT_TOOLS_COUNT>; версия 4.3 → <PYPROJECT_VERSION>; архитектурное дерево включает bot/ + mcp_server.py.
- USER_GUIDE.md: tools count sync; cross-link на docs/runbooks/BOT_LLM_FALLBACK.md.
- SERVER_ARCHITECTURE.md: MCP tools count 17 → <MCP_TOOLS_COUNT>.

Refs: self-review актуальной документации 2026-05-07 (M-1, M-2, USER_GUIDE H gap).
```

---

### Commit 2 (C2) — MCP specs sync

#### 4.5 docs/mcp-management-tools-spec.md

В заголовке заменить «24 инструмента» → `MCP_TOOLS_COUNT` (если число совпало).

Сравнить full tools list из § 1 (`MCP_TOOLS_LIST`) с тем что в spec. Найти missing. Per audit M-16 типичные missing: `get_topic_versions`, `force_resummarize`, `subscribe_digest`, `list_digests`, `unsubscribe_digest`, `subscribe_watchlist`, `list_watchlists`, `unsubscribe_watchlist`, `get_watchlist_matches`, `export_channel`, `get_export_status`, `reload_prompts`.

**Decision Q-1:** либо (A) обновить spec под все 35 tools (~150-300 lines work), либо (B) ограничить scope spec'а оригинальным набором + явный «See `tg_parser/mcp_server.py` for full list (35 tools)» banner. **Recommendation: B** в этом sprint'е (быстрее, опускает risk drift'а). Полная spec для 35 tools = отдельный sprint.

Banner option (B):

```markdown
> **Scope (updated 2026-05-XX).** Этот документ описывает **первоначальный набор**
> management tools (управление каналами + pipeline). Полный набор реализованных
> MCP tools — **<MCP_TOOLS_COUNT>** (включая F5-C, F6 digests, F11 watchlist,
> export, prompts reload). Source of truth: `tg_parser/mcp_server.py`
> (`@mcp.tool()` декораторы) + USER_GUIDE.md.
>
> Полная spec для всех <MCP_TOOLS_COUNT> tools — backlog item, не блокирует MVP.
```

Также удалить устаревшие фразы вида «remove_channel не входит в этап» / «MCP локально stdio» (per audit § 10 historical contradictions).

#### 4.6 docs/chatgpt-mcp-compatibility.md

Per audit M-15:
- Внутреннее противоречие 24 vs 14 tools — sync на actual `MCP_TOOLS_COUNT`.
- ChatGPT помечен «✅ Работает», но `tg_parser/mcp_server.py` **не имеет** CORSMiddleware. Поменять на честный verdict:

```markdown
| ChatGPT Connectors | ⚠️ Partial | Browser-side path requires CORS middleware (not implemented as of <PYPROJECT_VERSION>); native path via mcp-remote works. |
```

Также sync version `v1.27.0` → `v<PYPROJECT_VERSION>`.

#### 4.7 docs/mcp-clients-compatibility.md

Sync version + tools count + (если упоминается ChatGPT с «✅ Работает») — same honesty fix как выше.

#### 4.8 Commit message

```
docs(mcp-spec,compat): sync tools count + scope-narrow + honest CORS verdict

mcp-management-tools-spec заявлял 24 tools и не покрывал F5-C / F6 / F11 /
export / prompts. Compatibility docs противоречили друг другу (24 vs 14)
и помечали ChatGPT как «✅ Работает» при отсутствии CORS middleware.

- mcp-management-tools-spec.md: scope-narrow banner + tools count sync; убраны
  устаревшие «не входит в этап» формулировки. Полная spec для 35 tools — backlog.
- chatgpt-mcp-compatibility.md: tools count sync (24/14 → <MCP_TOOLS_COUNT>);
  ChatGPT verdict «⚠️ Partial» с честной отметкой про CORS gap; версия sync.
- mcp-clients-compatibility.md: версия + tools count sync.

Refs: self-review 2026-05-07 (M-15, M-16).
```

---

### Commit 3 (C3) — ADR implementation status annotations

**Принцип:** не менять accepted decisions, **добавить блок «Implementation status (current)»** после § Контекст в каждом ADR. Даты + cross-links на code.

#### 4.9 docs/adr/0001-overall-architecture.md

После § Контекст добавить:

```markdown
> **Implementation status (2026-05-07).**
>
> **Access layer evolved:** ADR описывает MVP с CLI как primary entry point. Текущая реальность — **4 entry points**:
> - `tg_parser/cli/` (CLI)
> - `tg_parser/api/main.py` (FastAPI HTTP)
> - `tg_parser/mcp_server.py` (MCP server, <MCP_TOOLS_COUNT> tools)
> - `tg_parser/bot/main.py` (Telegram bot, <BOT_TOOLS_COUNT> tools)
>
> Разделение ingestion / processing / storage / export сохранено per ADR.
> Multi-entry-point эволюция следует из audience-driven roadmap (см.
> `docs/notes/PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md`).
> Decision **не отменён**, расширен.
```

#### 4.10 docs/adr/0003-storage-and-indexing.md

После § Контекст добавить:

```markdown
> **Implementation status (2026-05-07).**
>
> **MVP SQLite → production PostgreSQL.** ADR описывает MVP на трёх SQLite файлах
> (`ingestion_state.sqlite`, `raw_storage.sqlite`, `processing_storage.sqlite`).
> Текущая реальность — **PostgreSQL-only**:
> - `tg_parser/storage/engine_factory.py` — комментарий «PostgreSQL only»
> - `tg_parser/config/settings.py` — поля `db_*` (PostgreSQL connection params)
> - `migrations/env.py` — комментарий «PostgreSQL-only (SQLite support removed)»
>
> Логическое разделение на 3 области (ingestion / raw / processing) сохранено —
> теперь это **3 ветки Alembic** + 3 engine в `tg_parser/storage/sqlalchemy/database.py`.
> Indexing — гибридный поиск через **FTS** (миграции 20260417_add_fts_*) +
> **pgvector** (20260415_add_entry_type_to_embeddings).
>
> Decision **расширен** под production scale; SQLite removal — отдельная архитектурная
> эволюция (не покрыта новым ADR — opportunistic candidate для future ADR 0007).
```

#### 4.11 docs/adr/0004-hexagonal-architecture-and-module-boundaries.md

После § Контекст добавить:

```markdown
> **Implementation status (2026-05-07).**
>
> **CLI-only entry point расширен до 4 entry points** — см. ADR 0001 implementation
> status. Hexagonal core сохранён:
> - `tg_parser/domain/` — без `sqlalchemy` / `telethon` / `httpx` импортов (verified).
> - Порты репозиториев в `tg_parser/storage/ports.py`, реализации в `tg_parser/storage/sqlalchemy/*`.
> - Ingestion через порты + Telethon-адаптер.
>
> **Известные deviations** (cross-cutting concerns / pragmatic shortcuts):
> - `services/scheduler_service.py`, `resummarization_service.py`, `watchlist_service.py`,
>   `background_scheduler.py` импортируют `tg_parser.api.metrics` и/или
>   `tg_parser.bot.runtime` — service↔api/bot coupling для observability и
>   delivery (Telegram bot push). Это compromise vs strict hexagonal — фиксируется
>   как known TD, не блокирует MVP.
> - Bot agent (`tg_parser/bot/agent.py`) — без `LLMClient` порта (см. ADR 0005
>   явное исключение); тесная связь с Gemini API by design.
>
> Decision **сохранён в ядре**, deviations задокументированы.
```

#### 4.12 Commit message

```
docs(adr): annotate 0001 / 0003 / 0004 implementation status — post-MVP transition

Три accepted ADR описывают MVP-формулировки (CLI-only, SQLite, single entry
point), которые не отражают текущую production-реальность (FastAPI + MCP +
Bot + PostgreSQL + scheduler↔bot coupling). Без implementation-status секций
читатель не различает «исторический контекст» от «текущая реализация».

Не меняем accepted decisions — добавляем блок «Implementation status
(2026-05-07)» после § Контекст в каждом ADR с cross-links на код:

- ADR 0001: 4 entry points (CLI + API + MCP + Bot); ingestion/processing/storage/export разделение сохранено.
- ADR 0003: PostgreSQL-only + FTS + pgvector; SQLite removed; logical 3-area split = 3 Alembic branches.
- ADR 0004: hexagonal core preserved (`domain/` clean); known deviations — service↔api/bot coupling for observability + bot push delivery.

Refs: self-review 2026-05-07 (M-3).
```

---

### Commit 4 (C4) — MVP banners + roadmap disambiguation + BUG_LOG housekeeping

#### 4.13 docs/architecture.md

В самом верху файла (после `# `):

```markdown
> **⚠️ Historical / MVP (2025-12-XX).** Этот документ описывает **MVP-архитектуру**
> с тремя SQLite файлами и CLI-only access. Текущая production-архитектура —
> [`docs/SERVER_ARCHITECTURE.md`](SERVER_ARCHITECTURE.md) (PostgreSQL 17 +
> pgvector + Docker stack + 4 entry points). Сохраняется для исторического
> контекста и обоснования decisions; не использовать как production reference.
>
> Эволюция MVP → production задокументирована в ADR 0001 / 0003 / 0004
> Implementation status секциях (см. `docs/adr/`).
```

#### 4.14 docs/business-requirements.md

Аналогичный banner:

```markdown
> **⚠️ Historical / MVP requirements (2025-12-XX).** Этот документ фиксирует
> бизнес-требования на стадии MVP («без HTTP API» — всё через CLI). Текущая
> реальность — FastAPI + MCP + Telegram bot. Актуальный продуктовый план —
> [`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md`](notes/PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md).
```

#### 4.15 docs/product-overview.md

Аналогичный banner — то же самое содержание что в 4.14.

#### 4.16 docs/testing-strategy.md

Banner:

```markdown
> **⚠️ Outdated (2025-12-XX) — SQLite-oriented.** Тестовая стратегия описана
> для MVP с SQLite. Текущая реальность — PostgreSQL integration tests
> (`tests/test_postgres_integration.py`, `tests/test_migrations_*.py`,
> F4/F5/F11 MCP tests, etc. в `tests/`). Pyramid-структура (unit / integration /
> e2e) сохранена концептуально, конкретика хранилища устарела.
>
> Refresh — backlog item; не блокирует test execution (`pytest tests/` работает
> в актуальной БД через `migrations/`).
```

#### 4.17 docs/notes/ROADMAP_V3_PRODUCTION_FIRST.md — Wave 1 disambiguation

В самом верху файла (после `# ` заголовка) добавить banner:

```markdown
> **⚠️ Wave 1 = Living-KB contract phase (completed 2026-04-26).** Этот roadmap
> определяет **infrastructure-driven** «Wave 1» как D.1 + F11 + F5-C contract
> (закрыт). **Audience-driven Wave 1** (Bot UX → F4-B → Surface Parity →
> Shareable Digest) — отдельная плоскость, описана в
> [`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md`](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md) § 5.1.
>
> Если у тебя возник вопрос «какой следующий шаг» — приоритет **audience-driven**
> (PRODUCT_STRATEGY § 5.1). Этот документ — operational backbone (что построено,
> что в backlog инфраструктурно), не главный календарь.
```

#### 4.18 docs/notes/BUG_LOG.md — переместить resolved bugs

BUG-010 / BUG-011 / BUG-012 живут в `## Active bugs` со `Status: resolved`. Перенести их в `## Resolved bugs` секцию (per workflow в L1-15). **Записи целиком** (не сокращать), плюс перенумеровать sequence если требуется.

> **Внимание:** сохранить полное содержание записей (severity, root cause, resolution с date / commit / PR). Это living history, не cleanup ради cleanup'а.

#### 4.19 Commit message

```
docs(architecture,product,roadmap,bug-log): MVP banners + Wave 1 disambig + BUG_LOG cleanup

Несколько докуметов нацелены на MVP-формулировки (architecture / business-
requirements / product-overview / testing-strategy) — без banner'а читатель
получает MVP-контекст вместо production reality. ROADMAP_V3 содержит
коллизию термина «Wave 1» с PRODUCT_STRATEGY (Living-KB Wave 1 vs Audience
Wave 1). BUG_LOG имеет resolved bugs в § Active секции (workflow violation).

- docs/architecture.md: historical MVP banner + cross-link на SERVER_ARCHITECTURE.
- docs/business-requirements.md: MVP banner + cross-link на PRODUCT_STRATEGY.
- docs/product-overview.md: MVP banner + cross-link на PRODUCT_STRATEGY.
- docs/testing-strategy.md: outdated banner + указание на актуальный pytest path.
- docs/notes/ROADMAP_V3_PRODUCTION_FIRST.md: Wave 1 disambiguation banner —
  Living-KB Wave 1 (completed) vs Audience Wave 1 (active per PRODUCT_STRATEGY § 5.1).
- docs/notes/BUG_LOG.md: BUG-010/011/012 перенесены в § Resolved (полное содержание).

Refs: self-review 2026-05-07 (M-7, M-8, C-3, M-14, testing-strategy refresh).
```

---

## 5. Verification gates

### 5.1 Per-commit self-review

```
C1 (fact-sync):
[ ] grep -n "24 инструмент\|24 tools\|24 MCP\|17 tools" README.md USER_GUIDE.md SERVER_ARCHITECTURE.md → 0 matches
[ ] grep -n "v4.3\|version: 4.3\|Версия проекта: 4.3" README.md → 0 matches
[ ] README.md tools count соответствует MCP_TOOLS_COUNT / BOT_TOOLS_COUNT из § 1 pre-flight
[ ] USER_GUIDE.md содержит cross-link на docs/runbooks/BOT_LLM_FALLBACK.md

C2 (mcp-spec):
[ ] mcp-management-tools-spec.md scope banner добавлен (или полный refresh)
[ ] grep -n "remove_channel не входит\|MCP локально stdio" mcp-management-tools-spec.md → 0 matches
[ ] chatgpt-mcp-compatibility.md: ChatGPT verdict — «⚠️ Partial» (не «✅ Работает»)
[ ] grep -n "v1.27.0\|v4.3" chatgpt-mcp-compatibility.md mcp-clients-compatibility.md → 0 matches

C3 (adr-status):
[ ] docs/adr/0001-overall-architecture.md имеет «Implementation status» блок
[ ] docs/adr/0003-storage-and-indexing.md имеет «Implementation status» блок
[ ] docs/adr/0004-hexagonal-architecture-and-module-boundaries.md имеет «Implementation status» блок
[ ] Accepted decisions блоки в этих ADR не изменены (verify diff)

C4 (banners + housekeeping):
[ ] architecture.md / business-requirements.md / product-overview.md / testing-strategy.md имеют warning banner в начале
[ ] ROADMAP_V3 имеет Wave 1 disambiguation banner
[ ] BUG-010/011/012 в BUG_LOG.md под § Resolved bugs (не § Active)
```

### 5.2 No-code change verification

```bash
git diff --stat origin/main..HEAD

# Expected: changes ONLY в docs/, никаких:
# tg_parser/, tests/, docker-compose.yml, prompts/, migrations/, scripts/
```

### 5.3 CI

5/5 checks GREEN. Lint Documentation должен пройти; Test Python 3.12 = no-op.

### 5.4 Cross-document check (post-merge sanity)

После merge — проверить что числа везде согласованы:

```bash
echo "=== Tools count refs in all docs ==="
grep -rn "MCP.*tools\|MCP.*инструмент" docs/ README.md | grep -E "[0-9]+ "

echo "=== Version refs ==="
grep -rn "v[0-9]\+\.[0-9]\+\|версия [0-9]" docs/ README.md
```

Ожидание: все упоминания tools count = `MCP_TOOLS_COUNT` (или helpfully указывают на mcp_server.py); все версии = `PYPROJECT_VERSION`.

---

## 6. Anti-scope (явно)

- **НЕ редактировать** `pyproject.toml`, `requirements.txt` (per workspace AGENTS.md).
- **НЕ создавать** `scripts/count_mcp_tools.py` или CI gate для tools count drift —
  это code change (отдельный sprint, opportunistic).
- **НЕ полностью переписывать** `mcp-management-tools-spec.md` под все 35 tools —
  scope-narrow banner достаточно для MVP. Полная spec — backlog.
- **НЕ обновлять `pyproject.toml` version** — это release decision, не doc fix.
- **НЕ начинать F4-B Core planning** — это следующая сессия в **fresh chat** после
  hygiene merge.
- **НЕ трогать** `docs/runbooks/*` (закрыто PR [#63](https://github.com/AlexEfimov/TG_parser/pull/63)),
  `docs/adr/0005-*` (Session K), `docs/notes/REVIEW_2026-05-08_*` (Session K),
  `docs/notes/FUTURE_FEATURES.md L96` (Session K),
  `docs/notes/SESSION48*` / `Session29*` (Session K).
- **НЕ закрывать** GH issues (Session K делает это через PR keyword).

---

## 7. Risks

**R-1 — Конфликт с Session K если merge не до старта hygiene.** Mitigation: stage Session K первым (более urgent — closure milestone). Если hygiene стартует **до** merge Session K — повторная правка `SERVER_ARCHITECTURE.md` scrape targets безопасна (idempotent), но conflict при rebase возможен.

**R-2 — Tools count может измениться между pre-flight и commit.** Например если кто-то параллельно мерджит F4-B Core (новые workspace tools). Mitigation: commit pre-flight numbers инлайн в commit message; перепроверить factual numbers непосредственно перед `git commit` каждого commit'а.

**R-3 — CHANGELOG entry для hygiene sprint.** Single Unreleased entry с описанием 4 commits — добавить в начале PR (между Session K entry и Session J entry):

```markdown
### Documentation Hygiene — counts/versions/ADR-status/MVP-banners (2026-05-XX)

**Контекст.** Self-review актуальной документации проекта 2026-05-07 нашёл
~10 расхождений между документами и реальностью кода. Этот sprint фиксит
M-1, M-2, M-3, M-7, M-8, M-15, M-16, M-14, C-3 и testing-strategy refresh
docs-only, no code changes.

- Tools count + версия sync (README, USER_GUIDE, SERVER_ARCHITECTURE).
- MCP specs — scope-narrow + честная CORS отметка для ChatGPT.
- ADR 0001/0003/0004 — implementation status sections (без изменения decisions).
- MVP-banners (architecture, business-requirements, product-overview, testing-strategy).
- ROADMAP_V3 Wave 1 disambiguation.
- BUG_LOG resolved bugs перенесены в § Resolved.

Tracker: PR #XX. Refs: self-review actual documentation 2026-05-07.
```

CHANGELOG entry — часть commit C1 (или separate housekeeping commit C5 если вы предпочитаете).

---

## 8. PR / commit plan

**Branch:** `docs/hygiene-2026-05-XX`

**Single PR, 4 atomic commits:**
- C1 — `docs: sync tools counts (35 MCP / 32 bot) + version (pyproject SoT) — fact-sync`
- C2 — `docs(mcp-spec,compat): sync tools count + scope-narrow + honest CORS verdict`
- C3 — `docs(adr): annotate 0001 / 0003 / 0004 implementation status — post-MVP transition`
- C4 — `docs(architecture,product,roadmap,bug-log): MVP banners + Wave 1 disambig + BUG_LOG cleanup`

**PR title:** `docs(hygiene): tools counts + versions + ADR status + MVP banners (post-Session-K, pre-F4B)`

**PR body template:**

```markdown
## Summary

Documentation hygiene sprint между Session K (Wave 1 step 1 closure) и F4-B Core
planning. Resolves audit findings M-1, M-2, M-3, M-7, M-8, M-15, M-16, M-14, C-3,
plus testing-strategy refresh.

4 atomic commits, single PR, docs-only, no deploy.

## Refs

- Self-review актуальной документации проекта 2026-05-07 (general report).
- Companion: Session K PR (#XX, merged), runbook nomenclature hotfix PR (#YY, merged).
- Next: F4-B Core planning sub-session in fresh chat.

## Test plan

- [ ] All 4 self-review checklists в § 5.1 промпта — все GREEN.
- [ ] `git diff --stat origin/main..HEAD` — только docs.
- [ ] CI 5/5 GREEN.
- [ ] Cross-document check § 5.4: tools count + версии везде согласованы.
```

---

## 9. После hygiene sprint — handover к F4-B Core planning

Сразу после merge — стартовать **F4-B Core planning sub-session** в **fresh chat** per Session K § 5. Никаких блокеров от этого sprint'а к F4-B planning нет (hygiene не меняет Q1–Q8 decisions, не трогает PLANNING_F4B_WORKSPACES_PREP).

---

## Appendix — Key references

| Документ | Зачем |
|---|---|
| Self-review report (chat 2026-05-07) | Источник всех 10 audit findings |
| `docs/notes/START_PROMPT_SESSION_K_WAVE1_STEP1_DONE_2026-05-08.md` | Что уже зафиксено в Session K (не дублировать) |
| `docs/notes/START_PROMPT_HOTFIX_RUNBOOK_NOMENCLATURE_2026-05-08.md` | Что зафиксено в runbook hotfix — PR [#63](https://github.com/AlexEfimov/TG_parser/pull/63) (`Closes #62`) |
| `pyproject.toml` | Source of truth для version |
| `tg_parser/mcp_server.py` (`@mcp.tool()`) | Source of truth для MCP tools count |
| `tg_parser/bot/tools.py` (`TOOL_DECLARATIONS`) | Source of truth для bot tools count |
| `docker-compose.yml` | Source of truth для runtime topology (если потребуется в banners) |

---

## Appendix B — История правок

| Дата | Изменение |
|---|---|
| 2026-05-07 ~23:50 UTC+4 | Первая версия. Создан после self-review актуальной документации проекта 2026-05-07 как **отдельный sprint между Session K и F4-B Core planning**. Покрывает audit findings M-1, M-2, M-3, M-7, M-8, M-15, M-16, M-14, C-3 + testing-strategy refresh (всего ~10 issues). 4 atomic commits, docs-only. Дата старта (`2026-05-XX`) определится после merge Session K. |
