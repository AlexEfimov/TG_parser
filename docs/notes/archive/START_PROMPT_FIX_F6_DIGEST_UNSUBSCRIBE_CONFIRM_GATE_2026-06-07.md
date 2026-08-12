# START PROMPT — Fix F6 `test_unsubscribe_digest_ownership_enforced` (confirm-gate drift)

**Дата:** 2026-06-07 · **Автор контекста:** read-only investigation сессия (без правок кода).
**Goal (одной строкой):** починить пред-существующий FAIL F6-теста `tests/test_f6_scheduled_digests.py::TestBotDigestTools::test_unsubscribe_digest_ownership_enforced` — тест ждёт legacy-контракт `deleted: True`, а `_exec_unsubscribe_digest` теперь (BUG-046/G1) возвращает confirm-preview gate; примирить тест с двухфазным preview/confirm-контрактом (или, по решению сессии, восстановить direct-delete для этой формы вызова).

> Рабочий режим: коммит — только по явному запросу пользователя (AGENTS.md). Не трогать unrelated-код. **Поведение F11 watchlist оставить без изменений** — оно уже примирено со своим тестом.

---

## 1. Контекст

**F6 (Scheduled Digests)** — фича плановых дайджестов: подписки `DigestSubscription`, cron-расписание через `BackgroundScheduler`, доставка ботом, и bot/MCP-инструменты (`subscribe_digest` / `list_digests` / `unsubscribe_digest`). Bot-исполнители живут в `tg_parser/bot/tools.py` (`_exec_*`), MCP-обёртки — в `tg_parser/mcp_server.py`.

**Bot confirm-gate (BUG-031 → BUG-046/G1).** Весь write-surface бота переведён на детерминированный **двухфазный preview/confirm** контракт:
- На первом вызове (без `confirm=True`) исполнитель возвращает `{"preview": True, "user_facing_message": True, "message": "… Подтвердите [да/нет]."}` и **ничего не меняет**.
- Реальный side-effect (delete / persist) происходит только когда фреймворк (`handlers._handle_confirmation_response` через FSM `ConfirmFlow`) **повторяет** вызов с `confirm=True`.

BUG-046 (G1) добавил в этот контракт именно `unsubscribe_digest` / `unsubscribe_watchlist` — раньше они удаляли немедленно и были вне контракта, из-за чего следующее «да» уходило в opaque-fallback «Я не совсем понимаю ваш ответ». См. `tg_parser/bot/tools.py::_WRITE_TOOLS_REQUIRING_CONFIRM` (строки ~102–131, комментарии BUG-031/BUG-046).

**Это пред-существующий FAIL, изолированный от F11 watchlist-работы.** Подтверждено: воспроизводится на чистом дереве (после `git stash` несвязанных watchlist-правок). Тест-класс помечен `@pg_only`, поэтому без `TEST_POSTGRES=1` он скипается — вероятно поэтому дрейф долго оставался незамеченным (CI обычно не гоняет PG-gated тесты).

---

## 2. Падающий тест и симптом (verbatim)

**Test id:**
```
tests/test_f6_scheduled_digests.py::TestBotDigestTools::test_unsubscribe_digest_ownership_enforced
```

Тест (см. `tests/test_f6_scheduled_digests.py`, ~строки 1064–1089): создаёт подписку owner=alice; bob (не владелец) → ждёт `error` (✅ проходит, permission-denied срабатывает до preview-gate); затем alice (владелец) вызывает delete и ждёт:
```python
ok = await _exec_unsubscribe_digest(
    {"subscription_id": sub.id},
    current_user=alice_user,
)
assert ok.get("deleted") is True   # ← ПАДАЕТ
```

**Симптом (детерминированный, воспроизводимый):** вместо `deleted: True` возвращается confirm-preview dict:
```
{'message': 'Подписка «morning brief» (ID: <uuid>) будет удалена. Подтвердите [да/нет].',
 'name': 'morning brief',
 'preview': True,
 'subscription_id': '<uuid>',
 'tool': 'unsubscribe_digest',
 'user_facing_message': True}
```
`ok.get("deleted")` → `None` (preview-turn ничего не удаляет), assertion рушится.

---

## 3. Воспроизведение

**Окружение:**
- Python **3.12** обязателен (`pyproject.toml` → `requires-python >=3.12`); `python3.12` доступен на машине. Рабочий venv: `/tmp/tgvenv` (Python 3.12).
- Тесты класса `TestBotDigestTools` — **PG-gated**: нужен Postgres. Локально поднят pgvector-контейнер `tg_parser_postgres` на `127.0.0.1:5432`, выделенная БД `tg_parser_test`. Запуск под `TEST_POSTGRES=1`.

**Команда (точечно по падающему тесту):**
```bash
TEST_POSTGRES=1 /tmp/tgvenv/bin/python -m pytest \
  "tests/test_f6_scheduled_digests.py::TestBotDigestTools::test_unsubscribe_digest_ownership_enforced" -q
```

---

## 4. Investigation checklist (конкретные указатели)

- [ ] **`tg_parser/bot/tools.py::_exec_unsubscribe_digest`** (def на ~3481). Сигнатура: `(args: dict, current_user: CurrentUser | None = None)` — **нет** `bot`/`chat_id`. Порядок проверок:
  1. id|name эксклюзивность, owner-scoped name→id резолв (BUG-047, ~3508–3552);
  2. `existing = repo.get(sub_id)`; not-found → error (~3555–3557);
  3. **permission check** `if not user.is_admin and existing.owner_id != user.id: return {"error": "permission denied", ...}` (~3558–3559) — выполняется **до** preview-gate (поэтому bob-ветка теста зелёная);
  4. **preview gate** `if not confirm: return {"preview": True, … "Подтвердите [да/нет]."}` (~3564–3581) — **вот где** alice-вызов без `confirm` перестаёт удалять;
  5. `repo.delete` + `unregister_digest_subscription` + `{"deleted": True, ...}` только при `confirm=True` (~3583–3603).
- [ ] **`tg_parser/bot/tools.py::_WRITE_TOOLS_REQUIRING_CONFIRM`** (~102–131): `unsubscribe_digest` и `unsubscribe_watchlist` в наборе (BUG-046). Декларация инструмента несёт `confirm: BOOLEAN` (~830, 959).
- [ ] **`tg_parser/bot/tools.py::execute_tool`** confirm-guard (~1097): LLM-issued `confirm=True` структурно отвергается без совпадающего FSM-snapshot; `confirm=True` ставит только фреймворк на confirm-turn.
- [ ] **`tg_parser/bot/handlers.py::_handle_confirmation_response`** — FSM-turn, который реплеит previewed-вызов с `confirm=True`. **`tg_parser/bot/states.py`** — `ConfirmFlow` (FSM-группа подтверждения).
- [ ] **Прецедент примирения (КЛЮЧЕВОЙ для решения):**
  - `tests/test_bot_unsubscribe_confirm_gate_g1.py` — канонический G1-suite: `test_preview_call_does_not_delete` (confirm опущен → `preview: True`, ничего не удалено) **и** `test_confirm_true_deletes` (`{"subscription_id": …, "confirm": True}` → `deleted: True`). Оба уже зелёные для digest **и** watchlist.
  - `tests/test_f11_bot_tools.py` — watchlist-сиблинг: `test_owner_preview_does_not_delete` (~257) разбит на preview-assert + delete с `confirm: True` (~288–296). Это **тот самый паттерн**, под который НЕ был обновлён F6-тест.
- [ ] **`tests/test_f6_scheduled_digests.py::TestBotDigestTools`** — соседние тесты: `test_subscribe_digest_persists_and_registers` (~936) уже передаёт `"confirm": True` с явным комментарием «confirm=True required to reach the persistence branch» (~957–961). То есть subscribe-сиблинг в **этом же** файле уже обновлён под контракт, а unsubscribe-тест — нет (рассинхрон внутри одного файла).
- [ ] **`docs/notes/BUG_LOG.md`**, `docs/notes/START_PROMPT_BUG047_D1_D2_DELETE_ROUTING_2026-06-01.md` — история BUG-046/047 confirm-gate.

---

## 5. Корень и ДВА варианта фикса

**Корень.** BUG-046/G1 завёл `_exec_unsubscribe_digest` в двухфазный preview/confirm-контракт (`confirm=True` обязателен для реального delete). Сиблинг-тесты были обновлены под новый контракт (`test_f11_bot_tools.py`, G1-suite, и даже subscribe-тест в самом F6-файле передаёт `confirm: True`), а конкретно `test_unsubscribe_digest_ownership_enforced` **остался на legacy direct-delete контракте** — вызывает без `confirm` и ждёт `deleted: True`. Классический drift «фича обновила контракт → один старый тест не догнали».

### Вариант (a) — РЕКОМЕНДУЕМЫЙ: тест устарел → обновить под confirm-gate
Изменить alice-ветку (owner-delete) теста на двухфазный контракт, как у сиблингов:
```python
# preview-turn: confirm опущен → ничего не удалено
preview = await _exec_unsubscribe_digest(
    {"subscription_id": sub.id}, current_user=alice_user
)
assert preview.get("preview") is True
assert preview.get("deleted") is not True
# confirm-turn: фреймворк реплеит с confirm=True → реальный delete
ok = await _exec_unsubscribe_digest(
    {"subscription_id": sub.id, "confirm": True}, current_user=alice_user
)
assert ok.get("deleted") is True
```
**Доказательства в пользу (a) — сильные и сходящиеся:**
- `_WRITE_TOOLS_REQUIRING_CONFIRM` намеренно включает `unsubscribe_digest` (BUG-046, с развёрнутым обоснованием в комментарии).
- Watchlist-сиблинг `test_f11_bot_tools.py::test_owner_preview_does_not_delete` уже использует ровно этот двухшаговый паттерн.
- Канонический G1-suite (`test_bot_unsubscribe_confirm_gate_g1.py`) фиксирует preview→confirm как контракт для digest **и** watchlist.
- `subscribe`-тест в **том же** F6-файле уже передаёт `confirm: True`. Рассинхрон чисто на одном unsubscribe-тесте.

### Вариант (b) — менее вероятный: prod-код регрессировал / gate применён слишком широко
Гипотеза: для bot-tool вызова **этой формы** (прямой `_exec_*` с `subscription_id`, без FSM) надо сохранить direct-delete, т.е. confirm-gate навешен чрезмерно широко.
**Доказательства против (b):** двухфазность здесь — это и есть целевое поведение BUG-046 (иначе возвращается баг «да»-dead-end); guard в `execute_tool` намеренно запрещает LLM ставить `confirm=True`, делегируя это FSM. Менять prod ради одного старого теста сломало бы G1/F11-инварианты. Рассматривать (b) только если найдётся ADR/контракт (`docs/adr/`, `docs/contracts/`), фиксирующий direct-delete-контракт `unsubscribe_digest` как нормативный — на момент investigation такого не обнаружено.

**Рекомендация:** вариант **(a)**. Доказательная база (три независимых сиблинга + намеренный membership в confirm-set) однозначно указывает, что устарел именно тест, а не prod-код. Перед правкой быстро проверить `docs/adr/`/`docs/contracts/` на предмет нормативного direct-delete-контракта; при отсутствии — обновлять тест.

---

## 6. Acceptance criteria

1. Целевой тест зелёный:
   ```bash
   TEST_POSTGRES=1 /tmp/tgvenv/bin/python -m pytest \
     "tests/test_f6_scheduled_digests.py::TestBotDigestTools::test_unsubscribe_digest_ownership_enforced" -q
   ```
2. Весь F6-файл зелёный (PG-gated классы тоже):
   ```bash
   TEST_POSTGRES=1 /tmp/tgvenv/bin/python -m pytest tests/test_f6_scheduled_digests.py -q
   ```
3. Сиблинг confirm-gate / watchlist остаются зелёными (no-regress):
   ```bash
   TEST_POSTGRES=1 /tmp/tgvenv/bin/python -m pytest \
     tests/test_bot_unsubscribe_confirm_gate_g1.py \
     tests/test_f11_bot_tools.py \
     tests/test_bot_execute_tool_guard.py -q
   ```
4. Поведение F11 watchlist — **бит-в-бит без изменений**.

---

## 7. Constraints (нормативно, AGENTS.md)

- **`git commit` — только по явному запросу пользователя.** Не коммитить самостоятельно.
- Не менять unrelated-код; держать diff минимальным и сфокусированным на причине.
- **F11 watchlist поведение не трогать.**
- Не создавать `docs/methodology/**`; не править `pyproject.toml` / `requirements.txt` без явного запроса.
- ADR (`docs/adr/`) и контракты (`docs/contracts/`) нормативны — свериться перед выбором (a) vs (b).
- Ветка: `main`.

## 8. Первое действие в новом окне
Воспроизвести FAIL точечной командой из §3, открыть `tg_parser/bot/tools.py::_exec_unsubscribe_digest` (~3481) + `tests/test_f11_bot_tools.py::test_owner_preview_does_not_delete` (прецедент), быстро проверить `docs/adr/`/`docs/contracts/` на нормативный direct-delete-контракт, затем реализовать вариант (a) (failing-first → green) и прогнать acceptance-набор §6.
