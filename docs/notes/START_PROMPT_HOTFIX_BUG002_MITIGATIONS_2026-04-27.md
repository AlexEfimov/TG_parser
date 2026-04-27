# Hot-fix Sprint — BUG-002 Mitigations (Session B+, 2026-04-27)

**Назначение:** короткая hot-fix-сессия, **снижающая blast radius BUG-002**
до того, как proper FSM-фикс (Session D) будет готов. Берёт **3 cheap
mitigation-задачи**, идентифицированные в `BUG_LOG.md` § BUG-002:

1. **M1** — убрать `test_channel` как default из production code path.
2. **M2** — pre-flight reject известных placeholder-имён в `add_channel`.
3. **M3** — soft-delete вместо hard-delete в `remove_channel`.

После landing'а этих трёх mitigation'ов severity BUG-002 **снижается с
Critical до High** даже до полного FSM-фикса. Полный фикс statelessness
по-прежнему делает Session D.

**Тип сессии:** writing — code, tests, PR. Сессия выполняется в **отдельном
окне** от Phase 2 и от Session D; это именно hot-fix-track.

**Дата подготовки промпта:** 2026-04-27 (сразу после первой обзорной волны
багов BUG-001..BUG-007).

**Когда использовать:** **только** после того как:

1. Phase 1 sprint и Phase 2 sprint завершены (post-watch report committed);
2. `BUG_LOG.md` § Session planning подтверждён — D1, D2 defaults в силе;
3. Пользователь явно подтвердил «можно делать hot-fix перед Session C/D»
   (поскольку D2 — это default, а не финальное blessing).

---

## 1. Pre-flight

### 1.1 Required reads (в этом порядке)

1. `docs/notes/BUG_LOG.md` § BUG-002 — целиком, **особенно**:
   - § «Update from set_llm_config trace (23:56) — scope escalation»
     (объясняет почему Critical и почему mitigation важен).
   - § «Update from MCP DB-check (2026-04-26 23:59) — `test_channel` отсутствует»
     (текущая БД безопасна, но это случайный state).
   - § «Mitigation backlog (помимо фикса самого BUG-002)» — три задачи M1/M2/M3.
2. `docs/notes/BUG_LOG.md` § Session planning — context, dependencies graph.
3. `tg_parser/processing/mock_llm.py` целиком (≈200 строк) —
   локализовать все упоминания `test_channel` как default.
4. `scripts/add_test_messages.py` целиком — обнаружить все fixture-uses
   `test_channel`.
5. `tg_parser/bot/tools.py` — `_exec_add_channel` (≈ L300-460), `_exec_remove_channel`
   (≈ L1495-1545); понять текущий контракт preview/confirm и как добавить
   placeholder-reject.
6. `tg_parser/storage/sqlalchemy/channel_repo.py` — текущий `delete()`-метод
   (если есть soft-delete уже частично — переиспользовать; если нет —
   добавить колонку `deleted_at`).
7. `tg_parser/mcp_server.py` — `remove_channel` MCP-обёртка (для согласованного
   контракта).

### 1.2 Sanity checks (must pass before edits)

```bash
# 1. На main, working tree чист
git checkout main
git pull --ff-only origin main
git status --short

# 2. Phase 1 + Phase 2 уже landed (по landing log из MERGED_PLAN § 9)
rg "Phase 2 landing log" docs/notes/REVIEW_2026-04-26_MERGED_PLAN.md

# 3. Baseline pytest зелёный
.venv/bin/pytest -q 2>&1 | tail -20

# 4. Проверить что в production-БД нет канала test_channel
#    (через MCP — gating-check, не блокирует, но влияет на rollout-план M3).
#    Если есть — отдельный rollback-план для M3 (см. § 4.3).

# 5. Branch
git checkout -b hotfix/bug-002-mitigations-2026-04-27
```

### 1.3 Gating decisions (must answer before code-changes)

| ID | Вопрос | Default per BUG_LOG § Session planning |
|---|---|---|
| HM-1 | Список placeholder-имён для M2 reject-list? | `["test_channel", "example_channel", "my_channel", "default", "channel_a", "channel_b", "test", "example"]` (8 имён, расширяемый список через env-var `BLOCKED_CHANNEL_IDS`) |
| HM-2 | Soft-delete для всех каналов или только future-deletes? | **Future-deletes only** — backfill миграция не нужна; channels удалённые в прошлом остаются hard-deleted. Это упрощает миграцию до single-column ADD. |
| HM-3 | Reanimate-tool в этом hot-fix или потом? | **Не в этом hot-fix** — soft-delete без reanimation tool достаточно для blast-radius reduction. Reanimate-tool как отдельный TD-NN на следующий backlog-cycle. |

Если у юзера нет явного blessing'а по HM-1 — взять default и явно сообщить
ему в финальном summary.

### 1.4 Branch / PR strategy

**Один большой PR на все три mitigation'а.** M1 + M2 + M3 коротки сами по
себе (~30/40/80 строк), общий PR проще для review и rollback'а:

- Один branch: `hotfix/bug-002-mitigations-2026-04-27`.
- Один PR title: `hotfix(bug-002): pre-FSM mitigations — placeholder strip + reject + soft-delete`.
- Три коммита внутри PR'а: `M1: strip test_channel from prod code`, `M2: reject placeholder names`,
  `M3: soft-delete in remove_channel`.

PR labels: `bug-fix`, `hotfix`, `bug-002`, `pre-fsm-mitigation`.

---

## 2. Out of scope

| Категория | Куда отложить | Причина |
|---|---|---|
| **FSMContext / aiogram storage / state-machine для confirm-flow** | Session D | Это и есть proper фикс BUG-002, делается отдельно после mitigation'ов |
| **Pagination-state для list-tools (BUG-004)** | Session D | Зависит от FSM scaffolding'а |
| **Reanimate-tool для soft-deleted каналов** | отдельный TD после Session D | См. HM-3 default |
| **Backfill `deleted_at` для уже удалённых каналов** | wontfix или отдельный data-migration | См. HM-2 default |
| **Изменение MCP-обёртки `remove_channel` если она уже soft-delete-aware через storage** | minimal touch | Контракт сохраняется, изменение прозрачно для MCP-клиентов |
| **Reformatting / rename / mass-refactor mock_llm.py** | wontfix | Только удалить `test_channel` default; не трогать остальное |
| **Изменение `prompts/bot.yaml`** | Session D / F | Не нужно для mitigation'ов |
| **Расширение списка blocked names через config-fetch** | future TD | Hardcoded list + env-var override достаточен |

---

## 3. Sprint scope (Session B+)

### 3.1 M1 — strip `test_channel` defaults from production code path

**Files to touch:**

- `tg_parser/processing/mock_llm.py` — найти все литералы `"test_channel"`
  как default-аргумента или fixture-данных, заменить на:
  - либо `None` + assertion в начале функции (если функция тестируется с
    realistic-аргументами всегда),
  - либо `"_mock_channel_placeholder"` с явным комментарием
    `# Internal placeholder — never use as real channel_id; see BUG-002`.
- `scripts/add_test_messages.py` — заменить hardcoded `"test_channel"`
  на argparse-флаг `--channel-id` с **обязательным** прохождением
  (без default'а). Если cli-юзеры зависели от старого default'а — добавить
  CHANGELOG-warning.

**Где НЕ трогать:**

- `tests/` — там `test_channel` legitimate fixture name, оставить.
- `docs/` — где `test_channel` упомянут как пример в гайдах,
  желательно заменить на `your_channel_id` или `example_channel_username`,
  но это can-be-done-later, не блокирующее для mitigation.

**Verification:**

```bash
# Все non-test, non-docs упоминания test_channel должны исчезнуть
rg --type-not test "test_channel" tg_parser/ scripts/ -l
# Ожидаемо: пусто или только в комментариях с явным reference на BUG-002.
```

**Tests:**

- Один regression-тест: `tests/test_mock_llm.py` (новый или дополнить
  существующий) — assertion что `mock_llm` без явного `channel_id`-аргумента
  падает с `ValueError("channel_id required")` (если выбрана option-A) или
  возвращает placeholder (option-B). Конкретная форма зависит от choice
  при scoping'е M1.

### 3.2 M2 — pre-flight reject known-placeholder names в `add_channel`

**Files to touch:**

- `tg_parser/bot/tools.py::_exec_add_channel` (≈ L300-460):
  - В начале функции, **до** preview-логики, добавить:
    ```python
    BLOCKED_PLACEHOLDER_NAMES = frozenset({
        "test_channel", "example_channel", "my_channel", "default",
        "channel_a", "channel_b", "test", "example",
    })
    BLOCKED_FROM_ENV = frozenset(
        s.strip() for s in os.getenv("BLOCKED_CHANNEL_IDS", "").split(",") if s.strip()
    )
    if normalized_id in (BLOCKED_PLACEHOLDER_NAMES | BLOCKED_FROM_ENV):
        return {
            "success": False,
            "error": "blocked_placeholder_name",
            "message": f"Channel ID '{channel_id}' is reserved as a placeholder "
                       "and cannot be added. Use a real Telegram channel username.",
            "blocked_list_size": len(BLOCKED_PLACEHOLDER_NAMES | BLOCKED_FROM_ENV),
        }
    ```
- `tg_parser/mcp_server.py::add_channel` — симметричная защита
  (если есть отдельный handler), **либо** просто доверить bot-tool layer'у
  если MCP-handler делегирует через тот же executor.

**Где НЕ трогать:**

- `_exec_pause_channel`, `_exec_resume_channel`, `_exec_remove_channel` —
  они работают на существующих каналах в БД; placeholder-reject там не
  имеет смысла (если placeholder в БД — это уже corruption, отдельный issue).

**Tests:**

- `tests/test_bot_tools.py` (новый или дополнить):
  - case 1: `_exec_add_channel(channel_id="test_channel")` returns
    `{"success": False, "error": "blocked_placeholder_name", ...}`.
  - case 2: `_exec_add_channel(channel_id="real_channel_xyz")` proceeds normally.
  - case 3: env-var override — `BLOCKED_CHANNEL_IDS=foo,bar`, then
    `_exec_add_channel(channel_id="foo")` returns blocked.

### 3.3 M3 — soft-delete в `remove_channel`

**Files to touch:**

- `tg_parser/storage/sqlalchemy/models.py` (или соответствующий ORM-файл)
  — добавить колонку `Channel.deleted_at: datetime | None = None`.
- **Migration**: новая alembic-миграция
  `alembic/versions/<timestamp>_soft_delete_channels.py`:
  - `ADD COLUMN deleted_at TIMESTAMP NULL`.
  - `CREATE INDEX idx_channels_deleted_at ON channels(deleted_at) WHERE deleted_at IS NULL;`
    (partial index для частого фильтра «только active»).
- `tg_parser/storage/sqlalchemy/channel_repo.py`:
  - `delete(channel_id)` → переименовать существующий метод в
    `_hard_delete()` (приватный), добавить новый `delete(channel_id)` который
    выставляет `deleted_at = utcnow()` и **не** удаляет связанные записи.
  - Все `list_*` / `get_*` методы должны фильтровать
    `WHERE deleted_at IS NULL` по умолчанию (option `include_deleted=False`).
  - Добавить метод `find_deleted(channel_id)` для будущего reanimate-tool.
- `tg_parser/bot/tools.py::_exec_remove_channel` — изменить response message
  с «удалён» на «помечен как удалённый, восстановление через admin-tool»;
  preview-секция — указать что это soft-delete.
- `tg_parser/mcp_server.py::remove_channel` — обновить docstring и
  return-payload analogously.

**Rollback план для M3:**

Если в production-БД есть канал `test_channel` (по результатам Sanity 1.2 §4):

1. **PRE-deploy**: вручную через MCP / SQL пометить его `deleted_at = utcnow()`.
2. **DEPLOY M3**: миграция и code-changes.
3. **POST-deploy verification**: канал не появляется в `list_channels()`,
   данные сохранены в `raw_messages`/`processed_documents`/`topic_cards`.

Если канала `test_channel` нет (текущее состояние per BUG_LOG § BUG-002 update 23:59):

1. **DEPLOY M3** напрямую — миграция-only ADD COLUMN, zero downtime.

**Tests:**

- `tests/test_channel_repo.py` (новый или дополнить):
  - case 1: `delete(channel_id)` → `find(channel_id)` returns None;
    `find_deleted(channel_id)` returns object with `deleted_at != None`.
  - case 2: `list_all()` исключает soft-deleted; `list_all(include_deleted=True)`
    включает.
  - case 3: связанные `raw_messages` / `processed_documents` остаются в БД.
- `tests/test_mcp_management.py` или `test_bot_tools.py`:
  - case 4: `_exec_remove_channel(channel_id, confirm=True)` после успеха —
    `_exec_list_channels()` не включает удалённый канал; данные сохранены.

---

## 4. Per-mitigation playbook

### 4.1 M1 playbook (strip placeholders)

```bash
# 1. Локализовать все упоминания
rg -n '"test_channel"' tg_parser/ scripts/ --type-not test

# 2. Для каждого hit'а — оценить: production code path vs fixture vs comment.
#    Если production: заменить (см. § 3.1).

# 3. Smoke test
.venv/bin/pytest tests/test_mock_llm.py -q
.venv/bin/pytest tests/test_processing*.py -q

# 4. Commit
git add tg_parser/ scripts/ tests/
git commit -m "M1(bug-002): strip test_channel default from production code path

Removes test_channel as a default-argument literal from mock_llm.py
and scripts/add_test_messages.py. test_channel survives as a legitimate
fixture name in tests/ and as a documentation example in docs/, but
no longer appears in code-paths that production-Gemini could
hallucinate from training-data prior.

Refs: BUG_LOG.md BUG-002 mitigation M1, Session B+."
```

### 4.2 M2 playbook (reject placeholder names)

```bash
# 1. Edit tg_parser/bot/tools.py::_exec_add_channel — добавить guard.
# 2. Edit tg_parser/mcp_server.py::add_channel — symmetrical guard
#    (если handler не делегирует через тот же executor).
# 3. Tests
.venv/bin/pytest tests/test_bot_tools.py -q
.venv/bin/pytest tests/test_mcp_management.py -q -k "add_channel"

# 4. Commit
git add tg_parser/ tests/
git commit -m "M2(bug-002): reject known placeholder channel names in add_channel

Prevents accidentally adding test_channel / example_channel / etc as real
channels through bot or MCP. Default blocked-list is hardcoded; supports
runtime extension via BLOCKED_CHANNEL_IDS env var.

Refs: BUG_LOG.md BUG-002 mitigation M2, Session B+."
```

### 4.3 M3 playbook (soft-delete)

```bash
# 1. ORM model + migration
alembic revision -m "soft_delete_channels"
# редактировать новый файл — ADD COLUMN deleted_at + partial index

# 2. Repo refactor
# редактировать tg_parser/storage/sqlalchemy/channel_repo.py

# 3. Tool layer
# редактировать tg_parser/bot/tools.py::_exec_remove_channel
# редактировать tg_parser/mcp_server.py::remove_channel

# 4. Tests
.venv/bin/pytest tests/test_channel_repo.py -q
.venv/bin/pytest tests/test_mcp_management.py -q -k "remove_channel"
.venv/bin/pytest tests/test_storage_integration.py -q

# 5. Migration smoke
alembic upgrade head  # на dev-БД
alembic downgrade -1
alembic upgrade head

# 6. Commit
git add alembic/ tg_parser/ tests/
git commit -m "M3(bug-002): soft-delete channels instead of hard-delete

Changes Channel.delete() to set deleted_at timestamp instead of
DELETE-cascading raw_messages/processed_documents/topic_cards. Reduces
blast radius for hallucinated remove_channel calls (see BUG-002):
data is recoverable via reanimate-tool (TBD, separate TD).

Schema change: ADD COLUMN channels.deleted_at TIMESTAMP NULL +
partial index on (deleted_at IS NULL) for active-only filter.

Refs: BUG_LOG.md BUG-002 mitigation M3, Session B+."
```

---

## 5. Testing & verification (full run)

```bash
# Full pytest suite после landing'а всех трёх mitigation'ов
.venv/bin/pytest -q 2>&1 | tail -20
# Ожидаемо: count ≥ baseline + 4-6 новых regression-тестов.

# Verify M1 — никаких prod-упоминаний test_channel
rg --type-not test "test_channel" tg_parser/ scripts/

# Verify M2 — reject path работает
.venv/bin/python -c "
import asyncio
from tg_parser.bot.tools import _exec_add_channel
result = asyncio.run(_exec_add_channel(channel_id='test_channel'))
assert result['success'] is False, result
assert result['error'] == 'blocked_placeholder_name', result
print('M2 verified')
"

# Verify M3 — soft-delete отдельный path
psql -d tg_parser_dev -c "\d channels" | grep deleted_at
# должно показать: deleted_at | timestamp without time zone
```

Manual smoke (опционально, на dev-окружении):

1. Через bot: `добавь канал test_channel` → ожидать reject от M2.
2. Через MCP: `add_channel(channel_id="test_channel")` → ожидать reject.
3. Через MCP: `add_channel(channel_id="example_real_xyz")` → preview.
4. Через MCP: `remove_channel(channel_id="some_existing", confirm=True)` →
   успех; затем `list_channels()` — нет; затем SQL
   `SELECT deleted_at FROM channels WHERE channel_id='some_existing'` — set.

---

## 6. PR / commit conventions

- **PR title**: `hotfix(bug-002): pre-FSM mitigations — M1+M2+M3`.
- **PR body** должен содержать:
  - Цель: blast radius reduction для BUG-002 до Session D.
  - Список mitigation'ов с reference на BUG_LOG sections.
  - Severity rationale: Critical → High после landing'а (зафиксировать в
    BUG-002 update после merge'а).
  - Schema change disclosure: M3 добавляет колонку + index;
    backward-compatible (NULL по умолчанию).
- **CHANGELOG entry**:
  ```markdown
  ## Hot-fix BUG-002 mitigations (2026-04-27)

  - M1: Stripped test_channel default from production code paths
        (mock_llm.py, scripts/add_test_messages.py).
  - M2: add_channel now rejects known placeholder names
        (test_channel, example_channel, etc); env-var override via
        BLOCKED_CHANNEL_IDS.
  - M3: remove_channel is now soft-delete (deleted_at timestamp);
        related raw_messages/processed_documents/topic_cards preserved
        for future reanimate.

  See docs/notes/BUG_LOG.md BUG-002 for context.
  ```
- **Commit-message Refs footer**: `Refs: BUG_LOG.md BUG-002, Session B+ hot-fix.`
- **PR labels**: `bug-fix`, `hotfix`, `bug-002`, `pre-fsm-mitigation`,
  per-area (`bot`, `mcp_server`, `storage`).

---

## 7. Acceptance criteria

Session B+ считается завершённой, если:

- [ ] § 1.2 sanity-checks прошли до старта работ
- [ ] § 1.3 gating decisions HM-1/HM-2/HM-3 закрыты (default или explicit blessing)
- [ ] **M1 landed** — `rg "test_channel" tg_parser/ scripts/ --type-not test`
      возвращает только комментарии или пусто
- [ ] **M2 landed** — pytest regression coverage для blocked-list +
      env-var override
- [ ] **M3 landed** — schema migration applied, pytest coverage для
      soft-delete + active-only filter
- [ ] full pytest suite зелёный (count ≥ baseline + 4-6)
- [ ] CHANGELOG обновлён hot-fix-секцией
- [ ] PR merged в main с зелёным CI
- [ ] **`BUG_LOG.md` BUG-002 обновлён**:
  - Severity понижена с Critical до High с явным rationale про landed
    mitigation'ы;
  - Status остаётся `open` (полный фикс — Session D);
  - В § Mitigation backlog добавлено `Status: M1+M2+M3 landed PR #N (date)`.
- [ ] **`BUG_LOG.md` § Session planning § Updates** содержит:
  ```
  Session B+ (2026-04-NN) — landed: PR #NN, commit <SHA>, +N tests;
  bugs partially mitigated: BUG-002 (M1+M2+M3, severity Critical→High).
  ```

---

## 8. Handoff

Перед закрытием Session B+:

1. **Проверить production-deploy готовность M3.**
   - Если в проде есть `test_channel` (через MCP-check) — ВРУЧНУЮ
     помечать его deleted_at до deploy'а (или отдельный admin-skript).
   - Если нет — миграция zero-touch.
2. **Уведомить пользователя** о готовности Session C (BUG-001 fix) и
   Session D (BUG-002 full FSM):
   - Session C можно стартовать параллельно — independent track.
   - Session D теперь менее срочен (severity High, не Critical), но
     по-прежнему open.
3. **НЕ редактировать Session C / D / E / F prompts** — они уже готовы,
   читают `BUG_LOG.md` § Updates и адаптируются.
4. **Финальное сообщение юзеру** должно содержать:
   - PR# и SHA mitigation-PR'а.
   - Severity-update BUG-002 (Critical → High).
   - Подтверждение что full FSM fix (Session D) теперь imeет более
     гибкий timing.
   - Если M3 потребовал ручного intervent'a в проде — отдельный block.

---

## 9. Citation back

- **Bug source:** `docs/notes/BUG_LOG.md` § BUG-002 § «Mitigation backlog».
- **Session planning:** `docs/notes/BUG_LOG.md` § Session planning (D2 default).
- **Successor session (full FSM fix):**
  `docs/notes/START_PROMPT_FIX_BUG002_BUG004_BOT_FSM_2026-04-28.md`.
- **Parallel session (independent track):**
  `docs/notes/START_PROMPT_FIX_BUG001_MCP_AUTH_2026-04-28.md`.

В commit-message'ах достаточно `Refs: BUG_LOG.md BUG-002, Session B+ hot-fix.`
