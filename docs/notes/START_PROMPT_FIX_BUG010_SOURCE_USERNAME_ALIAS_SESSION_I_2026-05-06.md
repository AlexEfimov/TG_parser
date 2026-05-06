# Fix Sprint — Bot/MCP Source Username Alias Resolution (BUG-010) (Session I, 2026-05-06)

---

## Pre-flight status — READY

**Status:** READY. Pre-flight gate-1 verification (§ 0) **must run** at
session start, but all upstream prerequisites have landed (Session H
BUG-011 fix — PR #58, squash `993451d`, 2026-05-03; 24h watch period
already elapsed by 2026-05-06).

**Создан:** 2026-05-06 ~18:50 UTC+4 (текущая сессия планирования, Session I
pre-flight).

### Gate-1 verification (§ 0) — TO BE EXECUTED AT SESSION START

VPS HEAD должен быть на Session H post-deploy SHA (`993451d`).
Prometheus и bot должны быть здоровы.

```bash
ssh prod 'docker exec tg_parser_prometheus wget -qO- \
  "http://localhost:9090/api/v1/query?query=up{service=\"bot\"}" \
  | python3 -m json.tool'
# Expected: result vector live, value="1"

ssh prod 'docker logs --since 24h tg_parser_bot 2>&1 \
  | grep -cE "confirm_flow_mismatch"'
# Expected: 0 (Session G guard hold)

ssh prod 'docker logs --since 24h tg_parser_bot 2>&1 \
  | grep -cE "gemini_empty|gemini_no_candidates|gemini_blocked"'
# Expected: 0 (Session E hold)
```

| Check | Expected | Actual | Status |
|---|---|---|---|
| Prometheus `up{service="bot"}` | `value: "1"` | TBD | TBD |
| `confirm_flow_mismatch` grep 24h | `0` | TBD | TBD |
| `gemini_empty\|..._blocked` grep 24h | `0` | TBD | TBD |

Если любой check FAIL — остановить сессию, расследовать регрессию
до начала кода.

### Telegram smoke § 5.4 (BUG-011 closure proof — если ещё не выполнено)

Согласно handover Session H → I, пп. 1–4 должны быть выполнены до
Session I:

1. «темы канала AgeManagment» → бот возвращает ~75 тем AgeManagment
2. «покажи 5 главных тем» (без channel ref) → 5 тем AgeManagment + acknowledgement
3. «топ темы канала Lab4health» → переключается на Lab4health
4. «удали канал» (без channel ref, после п.1+2) → просит уточнить, НЕ использует implicit context

Если smoke ещё не проводился — выполнить сначала его. Только при GREEN → кодить BUG-010.

### Locked decisions (BUG-010 specific — зафиксированы в этом файле)

- **D-A (locked):** Fallback-lookup реализуется в двух слоях:
  (1) новый метод `get_source_by_username` в port + SA impl (pure repo
  concern); (2) shared helper `_resolve_source` в `bot/tools.py` (dry
  across 4 executors). В `mcp_server.py` аналогичный inline-паттерн
  (нет shared helper — MCP callers прямые, 5 функций).
- **D-B (locked):** Обновить ВСЕ write-tool call-sites в обеих
  поверхностях (bot и MCP). Не только `remove_channel` — все 4
  бот-экзекутора и 5 MCP-функций. `add_channel` dedup-check тоже
  обновить (чтобы `add_channel AgeManagment` не создавал дубль если
  канал уже есть под тем username'ом).
- **D-C (locked):** Порядок lookup: `get_source(normalized)` сначала
  (поддержка числовых `source_id` для backward compat + admin
  use-cases) → fallback `get_source_by_username(normalized)` если
  первый вернул `None`. Не менять интерфейс существующего `get_source`.

### Implementation session opener

Открыть новый чат и вставить:

> Стартую Session I — fix BUG-010 source username alias resolution.
> Gate-1 verification и Telegram smoke BUG-011 выполнены (GREEN).
> Прочитай `docs/notes/START_PROMPT_FIX_BUG010_SOURCE_USERNAME_ALIAS_SESSION_I_2026-05-06.md`
> целиком + `docs/notes/BUG_LOG.md` § BUG-010, затем исполни § 3
> (port interface → SA impl → shared helper → bot executors → MCP
> functions → tests → verify → PR → deploy → closure).
> Branch: `fix/bug-010-source-username-alias-2026-05-06`.
> Локированные решения: D-A (fallback в repo layer + shared helper),
> D-B (все write-tools в обеих поверхностях), D-C (PK first, username
> fallback).

---

## 0.5. Где Session I сидит в общем roadmap'е

Session I — **второй шаг Wave 1 step 1 (Bot UX hardening)** из
[`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 5.1](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md).

**Wave 1 step 1 sequence:**

1. ✅ **Session H** — BUG-011 read-context preservation (PR #58, `993451d`)
2. ← **Session I** **(← сейчас)** — BUG-010 username alias (~80 LOC + tests), single PR
3. 🔲 **Session J** — ADR 0005 mini-refactor `GeminiAgent.resolve("bot")` +
   `BOT_LLM_FALLBACK` runbook, single PR с 2 atomic commits
4. 🔲 **Wave 1 step 1 DONE marker** —
   `REVIEW_2026-05-XX_WAVE1_STEP1_DONE.md` по template из
   [`PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md` § 4](PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md)

**Operational packaging (decision A3):** Session I — single PR, single
squash-commit, отдельный deploy + 24h watch. НЕ комбинировать с
Session J.

**После Wave 1 step 1** — планирующая под-сессия F4-B Core (~0.3
сессии), sprint F4-B Core (~2.5 сессии), Surface Parity, Shareable
Digest. Детали в `PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md`.

**Наблюдения для parity tracker:** если в процессе работы над BUG-010
заметите gap (например, «в API-endpoint `remove_channel` также нет
username-lookup» — уже в scope D-B), но что-то выходящее за рамки —
записать в [`PARITY_DECISION_TRACKING.md`](PARITY_DECISION_TRACKING.md),
не делать сейчас.

---

**Назначение:** закрыть BUG-010 структурно — write-tools (remove/pause/
resume/trigger_pipeline) через bot и MCP принимают `channel_id=username`
от пользователя, но передают его в `get_source(source_id)` который
выполняет PK-lookup по числовому Telegram chat ID. Пользователь вводит
`AgeManagment`, бот возвращает «Channel not found» хотя канал виден в
`list_channels`. Добавить `get_source_by_username` в repo layer +
fallback-логику во всех write-tool call-sites.

**Источник:** [`BUG_LOG.md` § BUG-010](BUG_LOG.md), диагностика Session F
2026-04-30 (production smoke F-9).

**Tracker:** GH issue [#50](https://github.com/AlexEfimov/TG_parser/issues/50)
(TD-bot-source-username-alias, filed в Session F closure backlog).

**Тип сессии:** writing — repo layer (port + SA impl), bot executors,
MCP functions, tests (unit + integration/testcontainers), PR.
Архитектурно небольшая сессия (~80 LOC); основное время — тесты
(4 integration via testcontainers + unit suite).

**Дата подготовки промпта:** 2026-05-06 ~18:50 UTC+4.

---

## 0. Why this session is small-medium (vs Session H larger)

BUG-010 — repo-layer lookup fix с fan-out в 9 call-sites (4 бот-
экзекутора + 5 MCP функций). Принципиальная новая логика минимальна:
один новый SQL-запрос (`WHERE channel_username = :username`) + one-
liner fallback helper. Сложность — в тщательном обновлении всех
call-sites без пропуска + testcontainers integration tests (потому что
именно моки скрыли этот баг в CI — см. § 1.3 «Why CI didn't catch»).

Estimate: ~80 LOC production code + ~4 integration tests + ~6 unit tests
= ~10 тестов total. ~1.5–2.5 часа.

---

## 1. Pre-flight

### 1.1 Required reads (в этом порядке)

1. `docs/notes/BUG_LOG.md` § BUG-010 — **полностью** (Severity /
   Status / Component / Discovered / Symptoms / Root cause / Why CI
   didn't catch / Proposed fix / Linked / Planned fix).
2. `tg_parser/storage/ports.py` class `IngestionStateRepo` (~L238–320) —
   текущий port интерфейс. Убедиться в отсутствии существующего
   `get_source_by_username`.
3. `tg_parser/storage/sqlalchemy/ingestion_state_repo.py` L1–100 —
   `SAIngestionStateRepo.get_source` (L40–55) + `list_sources` (L57–82).
   `list_sources` возвращает `channel_username` — именно это поле
   нужно для reverse lookup.
4. `tg_parser/bot/tools.py` — четыре executor'а с `get_source` call-sites:
   - `_exec_pause_channel` (~L1534, call на L1553)
   - `_exec_resume_channel` (~L1610, call на L1629)
   - `_exec_remove_channel` (~L1808, call на L1828)
   - `_exec_trigger_pipeline` (~L1400, call на L1414)
   Прочитать каждый полностью (они короткие, ~40–60 строк каждый).
5. `tg_parser/mcp_server.py` — пять функций с `get_source` call-sites:
   - `add_channel` (~L1158, dedup check на ~L1200)
   - `pause_channel` (~L1241, call на L1264)
   - `resume_channel` (~L1297, call на L1321)
   - `remove_channel` (~L1358, call на ~L1426)
   - `trigger_pipeline` (~L1527)
   Re-grep перед стартом: `rg -n "get_source(" tg_parser/mcp_server.py`
   (line numbers могли сдвинуться с момента написания этого промпта).
6. `tg_parser/utils/channel_id.py` — `normalize_channel_id` (весь файл,
   ~63 строки). Важно: функция стрипает `@` и кавычки, возвращает
   bare username. `normalized` value в executors — это уже bare username
   без `@`, он же кандидат для `channel_username` lookup.
7. `tests/test_ingestion_state_repo_soft_delete.py` — существующий
   testcontainers integration test (паттерн для новых тестов). Особое
   внимание на `_seed_owner` helper + `ingestion_db_url` fixture +
   async test structure. Новые тесты BUG-010 должны следовать
   этому же паттерну.
8. `tests/_testcontainer_fixtures.py` L1–50 — `requires_testcontainers`
   декоратор + `pgvector_container` fixture semantics.

### 1.2 Required state

- Local repo на `origin/main` HEAD = `993451d` или выше (Session H
  squash). `git status` clean.
- VPS на Session H deploy SHA `993451d`. Gate-1 GREEN (см. § 0).
- Branch convention: `fix/bug-010-source-username-alias-2026-05-06`.
- pytest baseline: **2028 passed** (Session H baseline). После Session I
  ожидается ~2038–2042 (+10 новых, 0 рег рессий). Если pytest на
  старте показывает другое — зафиксировать в § 5.1.

### 1.3 Gating decisions (D-A, D-B, D-C locked — не обсуждать, исполнять)

Все три ключевых решения уже зафиксированы в этом документе (см.
«Locked decisions» в §0). Здесь — техническое уточнение для
реализации:

**D-A детализация:**

```python
# tg_parser/storage/ports.py — добавить абстрактный метод в IngestionStateRepo:
@abstractmethod
async def get_source_by_username(
    self, username: str, *, include_deleted: bool = False
) -> Source | None:
    """Получить источник по channel_username (BUG-010, Session I).

    Fallback-lookup когда пользователь передаёт username вместо
    числового source_id. Без нормализации — вызывающий должен
    передать уже normalize_channel_id()'d значение.
    """
    pass

# tg_parser/storage/sqlalchemy/ingestion_state_repo.py — реализация:
async def get_source_by_username(
    self, username: str, *, include_deleted: bool = False
) -> Source | None:
    """Получить источник по channel_username (BUG-010, Session I)."""
    deleted_clause = "" if include_deleted else " AND deleted_at IS NULL"
    query = text(
        f"SELECT {self._SOURCE_COLUMNS} "
        f"FROM sources "
        f"WHERE channel_username = :username{deleted_clause}"
    )
    result = await self.session.execute(query, {"username": username})
    row = result.fetchone()
    return self._row_to_source(row) if row else None
```

**D-A shared helper в `bot/tools.py`** — добавить после импортов,
перед первым executor'ом (или рядом с другими helpers):

```python
async def _resolve_source(
    normalized: str, state_repo
) -> "Source | None":
    """Resolve channel by PK first, then by username fallback (BUG-010, Session I).

    ``normalized`` must already be passed through ``normalize_channel_id``.
    Tries numeric ``source_id`` lookup first for backward compat (admin
    tooling that uses raw Telegram chat IDs), then falls back to
    ``channel_username`` for the common user-facing case.
    """
    source = await state_repo.get_source(normalized)
    if source is None:
        source = await state_repo.get_source_by_username(normalized)
    return source
```

Заменить `await state_repo.get_source(normalized)` → `await _resolve_source(normalized, state_repo)` во всех 4 bot-executor'ах.

**D-B MCP:** в `mcp_server.py` нет центрального helper'а (функции
прямые, не через executor map). Добавить аналогичную inline-логику
или module-level helper прямо в `mcp_server.py`:

```python
async def _resolve_source(normalized: str, state_repo) -> "Source | None":
    """BUG-010 (Session I): PK-first, username-fallback lookup."""
    source = await state_repo.get_source(normalized)
    if source is None:
        source = await state_repo.get_source_by_username(normalized)
    return source
```

Заменить все 5 `await state_repo.get_source(normalized)` call-sites
в MCP-функциях. Функция идентична бот-хелперу — если хочется DRY,
вынести в `tg_parser/services/source_resolver.py` (optional, в рамках
~80 LOC estimate это +10 LOC за dry-up).

---

## 2. Reproduction context

### 2.1 BUG-010 production observation (2026-04-30, Session F smoke F-9)

```
[bot] User: list_channels
[bot] Bot:  ... channel_id=-1002123123123, channel_username=test_channel, status=active ...
            (7 channels, including test_channel)

[bot] User: remove_channel test_channel
[bot] Bot:  _exec_remove_channel(channel_id="test_channel")
              → normalize_channel_id("test_channel") = "test_channel"
              → state_repo.get_source("test_channel")
              → SQL: WHERE source_id = 'test_channel'   ← BUG-010
              → None  (source_id is '-1002123123123', not 'test_channel')
[bot] Bot:  "Channel not found. Available channels: [AgeManagment, Lab4health, ...]"
            (suggestion list от BUG-007 correctly excludes test_channel — circular UX)

EXPECTED:
            → state_repo.get_source("test_channel") → None
            → state_repo.get_source_by_username("test_channel")
            → SQL: WHERE channel_username = 'test_channel'
            → Source(source_id='-1002123123123', channel_username='test_channel', ...)
[bot] Bot:  "Channel test_channel found. Confirm remove? ..."
```

### 2.2 Почему это не BUG-003 class

BUG-003 был про `@`-prefix asymmetry — поверхностная нормализация
(решена `normalize_channel_id`). BUG-010 глубже: `get_source` сам по
себе работает правильно — он ищет по `source_id` (PK). Проблема в
том что write-tools передают ему `channel_username` (то что видит
пользователь), а не числовой `source_id`. Два разных поля, два
разных кода пути.

### 2.3 Что Session I НЕ делает

- **Не меняет `get_source` интерфейс** — он остаётся PK-lookup.
  `get_source_by_username` — отдельный метод.
- **Не меняет `list_sources`** — он уже возвращает `channel_username`,
  это и есть источник данных для reverse lookup.
- **Не трогает read-tools** — `list_topics`, `ask_question` и др. уже
  работают через `LIKE '%"X"%'` на `topic_cards.sources_json`, не
  через `get_source`. Их проблема была BUG-003 (решена), не BUG-010.
- **Не вводит username-based routing для `get_source`** — нет желания
  усложнять существующий метод. Новый метод чище.
- **Не меняет `normalize_channel_id`** — он уже идемпотентен и
  стрипает `@`; `channel_username` в DB тоже без `@` (BUG-003 fix).
  Lookup по голому username'у корректен.

---

## 3. Implementation plan

### 3.1 Step 1 — Port interface (5 мин)

`tg_parser/storage/ports.py` — добавить абстрактный метод
`get_source_by_username` в `IngestionStateRepo` после `get_source`
(~L246), перед `list_sources`. Комментарий: `BUG-010, Session I`.

### 3.2 Step 2 — SA implementation (10 мин)

`tg_parser/storage/sqlalchemy/ingestion_state_repo.py` — добавить
`get_source_by_username` после `get_source` (~L55), перед
`list_sources` (~L57). SQL: `WHERE channel_username = :username`.
Аналогичный паттерн `deleted_clause` как в `get_source`.

### 3.3 Step 3 — Shared helper + bot executors (20 мин)

`tg_parser/bot/tools.py`:

1. Добавить `_resolve_source(normalized, state_repo)` async helper
   рядом с другими internal helpers (после frozenset-констант, перед
   первым `_exec_*`).
2. В каждом из 4 executor'ов заменить `await state_repo.get_source(normalized)` →
   `await _resolve_source(normalized, state_repo)`:
   - `_exec_pause_channel` (~L1553)
   - `_exec_resume_channel` (~L1629)
   - `_exec_remove_channel` (~L1828)
   - `_exec_trigger_pipeline` (~L1414)
   
   Re-grep сначала: `rg -n "get_source" tg_parser/bot/tools.py`

### 3.4 Step 4 — MCP functions (15 мин)

`tg_parser/mcp_server.py`:

1. Добавить module-level `_resolve_source` helper (идентичный боту).
2. Заменить все 5 call-sites:
   ```
   rg -n "get_source" tg_parser/mcp_server.py
   ```
   Ожидаемые строки: ~1200 (`add_channel`), ~1264 (`pause_channel`),
   ~1321 (`resume_channel`), ~1426 (`remove_channel`), ~1527
   (`trigger_pipeline`). Проверить каждую контекстуально — убедиться
   что замена корректна (не нарушает ветку `add_channel` dedup logic).

### 3.5 Step 5 — BUG_LOG + CHANGELOG (5 мин)

- `docs/notes/BUG_LOG.md` § BUG-010 — добавить update-строку
  «Update 2026-05-XX — Session I landed → BUG-010 RESOLVED» (mirror
  BUG-011 update format).
- `CHANGELOG.md` — `## [Unreleased]` → новая запись «Session I — BUG-010
  source username alias resolution».

---

## 4. Testing strategy

### 4.1 Integration tests — testcontainers (новый файл)

**Файл:** `tests/test_ingestion_state_repo_username_alias.py`

Паттерн: точная копия структуры `test_ingestion_state_repo_soft_delete.py` —
`pgvector_container` fixture, `_seed_owner` helper, `@requires_testcontainers`,
`@pytest.mark.asyncio`.

#### Тест I-1 — `test_get_source_by_username_resolves_existing`

```
seed: INSERT source (source_id='-1002111111', channel_username='AgeManagment', ...)
call: repo.get_source_by_username("AgeManagment")
assert: result is not None
assert: result.source_id == "-1002111111"
assert: result.channel_username == "AgeManagment"
```

Это **прямой regression test** на BUG-010 root cause. Если SQL
`WHERE channel_username = :username` написан неверно — упадёт здесь.

#### Тест I-2 — `test_get_source_returns_none_for_username_input`

```
seed: INSERT source (source_id='-1002111111', channel_username='AgeManagment', ...)
call: repo.get_source("AgeManagment")  ← старый метод, PK-lookup
assert: result is None  ← демонстрирует что без фикса get_source не находит
```

Контрастный тест — документирует старое поведение и гарантирует что
новый fix не ломает изоляцию PK-lookup.

#### Тест I-3 — `test_resolve_source_fallback_path`

```
seed: INSERT source (source_id='-1002111111', channel_username='AgeManagment', ...)
call: _resolve_source("AgeManagment", state_repo)
      # PK lookup: get_source("AgeManagment") → None (не числовой PK)
      # fallback:  get_source_by_username("AgeManagment") → Source(...)
assert: result is not None
assert: result.source_id == "-1002111111"
```

End-to-end regression BUG-010 production scenario через `_resolve_source`.
Нужно импортировать `_resolve_source` из `tg_parser.bot.tools`
(или из `tg_parser.mcp_server` — протестировать оба, или один).

#### Тест I-4 — `test_resolve_source_pk_path_preserved`

```
seed: INSERT source (source_id='-1002111111', channel_username='AgeManagment', ...)
call: _resolve_source("-1002111111", state_repo)
      # PK lookup: get_source("-1002111111") → Source(...)  (числовой PK)
      # fallback не вызывается
assert: result is not None
assert: result.source_id == "-1002111111"
```

Backward compat test — числовые IDs всё ещё работают. Убеждает что
добавление fallback не ломает admin use-case (direct PK access).

### 4.2 Unit tests — без testcontainers (extend `test_bot_tools_session_f.py` or new file)

**Файл:** новый `tests/test_bot_tools_bug010_username_alias.py` (чтобы
не засорять существующий `test_bot_tools_session_f.py`, который уже
обсуждается в контексте CI gaps).

#### Тест U-1 — `test_resolve_source_calls_username_fallback_on_none`

Mock `state_repo.get_source` → `None`, mock `get_source_by_username`
→ `Source(source_id='-1002', channel_username='ch')`.
Assert: `_resolve_source("ch", state_repo)` возвращает source,
`get_source_by_username` был вызван 1 раз с `"ch"`.

#### Тест U-2 — `test_resolve_source_no_fallback_when_pk_found`

Mock `state_repo.get_source` → `Source(...)` (нашли по PK).
Assert: `get_source_by_username` НЕ вызывался (fallback не нужен).

#### Тест U-3 — `test_exec_remove_channel_uses_username_resolution`

Mock `state_repo.get_source` → None, `get_source_by_username` →
`Source(source_id='-1002', channel_username='AgeManagment', status='active')`.
Call `_exec_remove_channel({"channel_id": "AgeManagment", "confirm": False})`.
Assert: ответ содержит preview (не `"error": "Channel not found"`).
Assert: `get_source_by_username` вызван с `"AgeManagment"`.

Это **прямой regression test на production symptom** BUG-010.

#### Тест U-4 — `test_exec_pause_channel_uses_username_resolution`

Аналогично U-3 для `_exec_pause_channel`. Проверить что pause тоже
ходит через `_resolve_source`.

#### Тест U-5 — `test_exec_resume_channel_uses_username_resolution`

Аналогично для `_exec_resume_channel`.

#### Тест U-6 — `test_exec_trigger_pipeline_uses_username_resolution`

Аналогично для `_exec_trigger_pipeline`.

### 4.3 Self-review checklist перед коммитом

Выполнить вручную перед `git add`:

```
[ ] rg "state_repo.get_source(" tg_parser/bot/tools.py
    → Expected: 0 matches (все заменены на _resolve_source)

[ ] rg "state_repo.get_source(" tg_parser/mcp_server.py
    → Expected: 0 matches (все заменены на _resolve_source)

[ ] rg "def get_source_by_username" tg_parser/storage/ports.py
    → Expected: 1 match (abstract method)

[ ] rg "def get_source_by_username" tg_parser/storage/sqlalchemy/ingestion_state_repo.py
    → Expected: 1 match (concrete implementation)

[ ] rg "def _resolve_source" tg_parser/bot/tools.py
    → Expected: 1 match

[ ] rg "def _resolve_source" tg_parser/mcp_server.py
    → Expected: 1 match

[ ] pytest tests/test_ingestion_state_repo_username_alias.py -v
    → 4 tests PASS (требует TEST_TESTCONTAINERS=1 + Docker)

[ ] pytest tests/test_bot_tools_bug010_username_alias.py -v
    → 6 tests PASS

[ ] pytest --tb=short -q (default mode, без testcontainers)
    → baseline 2028 + ~6 новых = ~2034, 0 regressions

[ ] ruff check . && ruff format --check .
    → 0 violations
```

### 4.4 Risk mitigations

- **R-1** — `channel_username` в DB может быть NULL для старых записей
  (каналы добавленные до соответствующей миграции). **Mitigation:**
  `get_source_by_username` с `WHERE channel_username = :username`
  работает корректно при NULL (NULL != 'AgeManagment', не вернёт
  ложный результат). Проверить схему Alembic что `channel_username`
  nullable — если yes, SQL корректен; если NOT NULL — тем проще.
  Тест I-1 покрывает happy-path; добавить I-5 (optional):
  `test_get_source_by_username_returns_none_for_null_username` если
  хотите explicit coverage.
- **R-2** — два канала с одинаковым `channel_username` (не должно быть
  по DB constraint, но стоит проверить). **Mitigation:** проверить
  схему — есть ли `UNIQUE` на `channel_username`. Если нет — SQL
  `fetchone()` вернёт первый; рассмотреть `LIMIT 1 ORDER BY created_at`.
  Если `UNIQUE` есть (вероятно) — всё ОК.
- **R-3** — `add_channel` dedup check: если `get_source` по PK не
  находит, но `get_source_by_username` находит — `add_channel`
  правильно вернёт «already exists» вместо создания дубля.
  **Mitigation:** тест U-3 проверяет `remove_channel`; аналогичный
  тест для `add_channel` — добавить опционально если estimate
  позволяет.
- **R-4** — `find_deleted_source` в `SAIngestionStateRepo` тоже PK-bound.
  Используется в BUG-002 reanimate path. Не трогать — `find_deleted_source`
  работает только через `add_channel` flow где пользователь передаёт
  `source_id`; username-based reanimate за scope.

---

## 5. Verification gates

### 5.1 Local (before commit)

- [ ] Self-review checklist § 4.3 всё GREEN.
- [ ] `pytest tests/test_ingestion_state_repo_username_alias.py \
      tests/test_bot_tools_bug010_username_alias.py -v` — все PASS.
- [ ] Full pytest (default mode) — baseline 2028 → expect ~2034, 0 regressions.
- [ ] Full pytest (with Postgres / testcontainers, `TEST_TESTCONTAINERS=1`) —
      ожидается ~2050+ включая интеграционные тесты.
- [ ] `ruff check .` clean. `ruff format --check .` clean.

### 5.2 CI (PR open)

- [ ] Все 5 CI checks GREEN (Test Python 3.12, Lint Documentation,
  Alembic Guardrails, Alembic Runtime Upgrade Smoke, Docker Build).
- [ ] PR description contains `Closes #50`.

### 5.3 Production deploy gate

```bash
ssh prod 'cd ~/TG_parser && git pull --ff-only origin main \
  && docker compose build tg_parser \
  && docker compose up -d --no-deps --force-recreate tg_bot tg_parser_api'
```

Примечание: `mcp_server.py` изменяется — нужен rebuild API container
тоже (`tg_parser_api`). Если MCP сервер живёт отдельно — включить его.

### 5.4 Smoke verification (post-deploy) — Telegram bot

**BUG-010 прямой regression** (реальный Telegram-бот):
1. `list_channels` → убедиться что каналы отображаются с username.
2. «удали канал AgeManagment» (или любой реальный канал по username) →
   бот ДОЛЖЕН показать preview (не «Channel not found»).
3. «пауза канала AgeManagment» → preview, затем «нет» → cancel.
4. «возобнови канал AgeManagment» (если был на паузе) → preview.

**Regression: BUG-011 read-context всё ещё работает** (не сломали):
5. «темы канала AgeManagment» → «5 главных тем» → channel-scoped ответ.

**Regression: BUG-009 guard всё ещё работает** (не сломали):
6. «запусти пайплайн» (без channel_id) → бот просит уточнить.

### 5.5 Smoke verification (post-deploy) — MCP

Через MCP client (Cursor или curl):

```
pause_channel("AgeManagment")
# Expected: preview или success (не "Channel not found")

resume_channel("AgeManagment")
# Expected: success или "already active"
```

---

## 6. PR / commit plan

Single PR (mirrors Session H — small and atomic):

**Branch:** `fix/bug-010-source-username-alias-2026-05-06`

**Squash commit message template:**
```
fix(bug-010): resolve channel by username alias in write-tools (Session I)

Add `get_source_by_username` to IngestionStateRepo port + SA impl;
add `_resolve_source` helper (PK-first, username-fallback) in bot/tools
and mcp_server; update all 9 write-tool call-sites. Closes #50.

Tests: 4 testcontainers integration + 6 unit, 0 regressions.
```

**PR title:** `fix(bug-010): resolve channel by username alias in write-tools (Session I)`

**PR body (через `/tmp/pr_body_bug010.md` — паттерн Session H/PR #58):**

```
## Summary
Closes #50 (BUG-010) — write-tools failed to find channels when user
provides username (e.g. "AgeManagment") instead of numeric source_id.

## Root cause
`IngestionStateRepo.get_source(source_id)` performs PK-lookup only.
Write-tool executors passed normalized username directly as source_id.
Users who see channel_username in `list_channels` could not use the
same name to remove/pause/resume.

## Architecture
- New `get_source_by_username(username)` method in IngestionStateRepo
  port + SAIngestionStateRepo impl (WHERE channel_username = :username).
- New `_resolve_source(normalized, state_repo)` helper in bot/tools and
  mcp_server: tries PK first (backward compat for numeric IDs), falls
  back to username lookup.
- 9 call-sites updated: 4 bot executors + 5 MCP functions.

## Test plan
- [x] I-1..I-4: testcontainers integration (get_source_by_username SQL,
      PK/username isolation, _resolve_source happy paths)
- [x] U-1..U-6: unit tests (mock-based, resolve_source + all 4 executors)
- [x] Self-review rg checklist: 0 raw get_source() calls in executors
- [x] Full pytest 0 regressions
- [x] ruff clean

## Smoke (post-deploy)
[copy from § 5.4 + 5.5]

## Out of scope
- BUG-011 read-context (Session H, already closed)
- ADR 0005 mini-refactor + BOT_LLM_FALLBACK runbook (Session J)
- find_deleted_source username-based lookup (out of scope)
```

---

## 7. Out of scope / TD carry-forward

Session I закрывает только BUG-010. НЕ касается:

- **BUG-011** read-context — ✅ закрыт Session H (PR #58, `993451d`).
- **ADR 0005 mini-refactor** + **BOT_LLM_FALLBACK runbook** — **Session J**
  (следующий шаг Wave 1 step 1). `GeminiAgent.resolve("bot")` +
  `reset_llm_config(scope='bot')` + runbook.
- **`find_deleted_source` username-based** — не нужен для BUG-010 fix;
  использовать только в admin/reanimate flow.
- **`add_channel` username-dedup расширенный тест** — R-3 в §4.4;
  за scope estimate, defer unless R-3 materialises.
- **TD-bot-confirm-coverage-completeness** (Session G TD) — ~400 LOC,
  defer.

---

## 8. Risks (R-1 .. R-4) — см. § 4.4

---

## 9. Appendix A — File line ranges quick reference

Re-grep на старте сессии (числа могут сдвинуться):

```bash
rg -n "get_source\b" tg_parser/bot/tools.py
rg -n "get_source\b" tg_parser/mcp_server.py
rg -n "def get_source|def list_sources|def get_source_by" tg_parser/storage/sqlalchemy/ingestion_state_repo.py
rg -n "class IngestionStateRepo|def get_source|def list_sources" tg_parser/storage/ports.py
```

| File | Section | Lines (approximate, Session H baseline) |
|---|---|---|
| `tg_parser/storage/ports.py` | `IngestionStateRepo.get_source` | ~246–254 |
| `tg_parser/storage/ports.py` | `IngestionStateRepo.list_sources` | ~256–269 |
| `tg_parser/storage/sqlalchemy/ingestion_state_repo.py` | `get_source` | 40–55 |
| `tg_parser/storage/sqlalchemy/ingestion_state_repo.py` | `list_sources` | 57–82 |
| `tg_parser/bot/tools.py` | `_exec_trigger_pipeline` | ~1390–1490 |
| `tg_parser/bot/tools.py` | `_exec_pause_channel` | ~1534–1610 |
| `tg_parser/bot/tools.py` | `_exec_resume_channel` | ~1610–1700 |
| `tg_parser/bot/tools.py` | `_exec_remove_channel` | ~1808–1900 |
| `tg_parser/mcp_server.py` | `add_channel` (dedup check) | ~1158, call ~1200 |
| `tg_parser/mcp_server.py` | `pause_channel` | ~1241, call ~1264 |
| `tg_parser/mcp_server.py` | `resume_channel` | ~1297, call ~1321 |
| `tg_parser/mcp_server.py` | `remove_channel` | ~1358, call ~1426 |
| `tg_parser/mcp_server.py` | `trigger_pipeline` | ~1527 |
| `tests/test_ingestion_state_repo_soft_delete.py` | паттерн для I-1..I-4 | 1–146 |
| `tests/_testcontainer_fixtures.py` | `requires_testcontainers` + fixture | 1–50 |

---

## Appendix B — История правок документа

| Дата | Изменение |
|------|-----------|
| 2026-05-06 ~18:50 UTC+4 | Первая версия. Создана в Session I pre-flight chat. Все решения D-A/D-B/D-C locked на основе BUG_LOG § BUG-010, handover Session H→I, и анализа кода (ports.py, ingestion_state_repo.py, bot/tools.py, mcp_server.py). Self-review тесты и testcontainers integration suite добавлены согласно запросу. |

---

**End of Session I pre-flight document.** Ready for execution after
gate-1 verification (§ 0) + Telegram smoke BUG-011 (§ 0) GREEN.
