# START PROMPT — TD-bot-confirm-coverage-completeness (admin write-tools confirm-gate)

> **Status: RESOLVED 2026-06-13 (commit `a35bcb4`)** — the work this prompt drove is closed on `main` (admin write-tool confirm gate; bot.yaml v1.7.8 → v1.7.9). Historical content below is preserved as the originating design brief.

**Дата создания:** 2026-06-13 (выделено из Wave C closure в отдельное окно по размеру) · **Для:** новой (свежей) сессии — единственный крупный (L) остаток Wave C.
**Goal (одной строкой):** довести покрытие confirm-gate бота до полноты — завести admin write-tools в `_WRITE_TOOLS_REQUIRING_CONFIRM` с полным confirm-flow паттерном (preview → confirm → execute), закрыв `TD-bot-confirm-coverage-completeness`.

> **Рабочий режим (нормативно, [`AGENTS.md`](../../AGENTS.md)):** branch `main`; `git commit` и деплой — **только по явному запросу пользователя**; `docs/methodology/**` — не трогать; `pyproject.toml`/`requirements.txt` — не трогать без явного запроса. Принцип: **сначала дизайн → фиксируем развилки → потом код**. Scope строго по этому item-у; unrelated-код не задевать.

---

## 1. Контекст — где мы сейчас

Дорожка закрытия Wave 1 tech-debt ([`START_PROMPT_WAVE1_TECH_DEBT_CLOSURE_2026-06-12.md`](START_PROMPT_WAVE1_TECH_DEBT_CLOSURE_2026-06-12.md)) пройдена по волнам:
- **Wave A** ✅ — BUG-019/020/021/055/056/057/059 + TD-confirm-flow-concurrency (commits `f254274`, `3f0c3fc`).
- **Wave B** ✅ — BUG-054 HYBRID-рекалибровка + ADR-0015 + миграция `threshold_source` + паритет MCP/bot/HTTP (commits `24352bf`, `c283eb4`, bot.yaml v1.7.7 → **v1.7.8**).
- **Wave C малые** ✅ — BUG-058 (`X-Trigger-Surface` header), BUG-060 (doc-only), DOC-001 + doc-drift.

**Этот item — последний крупный остаток Wave C.** Решение по scope **уже зафиксировано = полный admin-квартет** (см. §2). Дизайн confirm-flow известен (прецеденты BUG-009 / `subscribe_watchlist`); открытые развилки — только в деталях (см. §4).

Прочее в backlog (НЕ в этой сессии): `TD-test-isolation-execute-tool-leak` (Low, test-hygiene) — ✅ с тех пор resolved on `main` (commit `128e5db`).

---

## 2. Зафиксированное решение (scope)

Добавить в confirm-gate **полный admin-квартет** write-tools:
- `register_user`
- `update_user`
- `add_user_auth`
- `remove_user_auth`

(`reload_prompts` и `export_channel` — вне scope этой сессии: первый ops-sensitive с низким user-risk, второй имеет иную UX доставки файла; при желании — отдельный follow-up.)

**Полный фикс на каждый из 4 tools требует ТРЁХ согласованных частей** (иначе падает контракт-гард):
1. Параметр `confirm: BOOLEAN` в декларации tool-а (tool schema), иначе `TestWriteToolsContract.test_reverse_*` зафейлится.
2. Членство в frozenset `_WRITE_TOOLS_REQUIRING_CONFIRM`.
3. Executor по паттерну preview → confirm → execute (как `subscribe_watchlist`): без `confirm=True` возвращает preview, не мутирует; мутация только на детерминированном confirm-turn.

Плюс — обвязка в `handlers._handle_confirmation_response` (FSM ConfirmFlow), если для admin-tools нужен свой preview-текст.

---

## 3. Якоря в текущем коде (проверить — строки сдвигались в Wave A/B/C)

- **Frozenset + TD-комментарий:** [`tg_parser/bot/tools.py`] — комментарий-TD ~L91–103, `_WRITE_TOOLS_REQUIRING_CONFIRM` ~L104–133 (сейчас 11 tools: `add_channel`, `remove_channel`, `pause_channel`, `resume_channel`, `trigger_pipeline`, `set_llm_config`, `reset_llm_config`, `subscribe_digest`, `subscribe_watchlist`, `unsubscribe_digest`, `unsubscribe_watchlist`).
- **Декларации целевых tools (сейчас БЕЗ `confirm`):** `register_user` ~L589–606, `update_user` ~L609–627, `add_user_auth` ~L648–670, `remove_user_auth` ~L673–681.
- **Executors (выполняются немедленно, без preview):** напр. `_exec_register_user` ~L2717–2737.
- **BUG-009 server-side guard:** `_check_confirm_flow_match` ~L1007–1047; вызывается в `execute_tool` при `name in _WRITE_TOOLS_REQUIRING_CONFIRM and args.get("confirm") is True` ~L1103–1104.
- **FSM-хендлер:** `tg_parser/bot/handlers.py` `_handle_confirmation_response` (~L889) — на affirmative-пути вызывает `await state.clear()` ПОСЛЕ `execute_tool` (подтверждено в Wave A TD-confirm).
- **Pinned baseline frozenset:** `tests/test_bot_execute_tool_guard.py` `test_guard_set_matches_known_baseline` ~L336–367 — **обязательно обновить** при изменении состава.
- **Forward/reverse контракт:** `tests/test_bot_execute_tool_guard.py` `TestWriteToolsContract` (декларация ↔ frozenset, ~L327–334).
- **Version-floor гард:** `tests/test_bot_read_context.py` ~L626–640 — сейчас floor **≥ 1.7.8**, поднять под новую версию.

---

## 4. Открытые развилки для обсуждения (в начале сессии)

1. **Состав подтверждён = квартет** (register_user/update_user/add_user_auth/remove_user_auth). Подтвердить, не расширять на reload_prompts/export_channel в этой сессии.
2. **Preview-текст admin-tools:** единый шаблон vs per-tool формулировки (что показывать оператору перед confirm — какие именно поля/последствия).
3. **`prompts/bot.yaml` bump:** v1.7.8 → **v1.7.9** (+ admin-confirm HARD RULEs по образцу subscribe/unsubscribe). Сколько и какие HARD RULEs.
4. **Granularity тестов confirm-flow:** один параметризованный тест на 4 tools vs отдельные per-tool (preview → confirm → execute + BUG-009 mismatch-reject).
5. **Идемпотентность/edge:** поведение при повторном confirm (stale-second → `ConfirmFlowMismatch`, уже покрыто паттерном Wave A) — подтвердить, что admin-tools наследуют тот же guard.

---

## 5. Definition of Done (нормативно)

- [ ] Для каждого из 4 tools: `confirm`-param в декларации + членство в frozenset + executor preview/confirm-паттерн + FSM-обвязка.
- [ ] **Bump `prompts/bot.yaml`** v1.7.8 → v1.7.9 + admin-confirm HARD RULEs; обновить version-floor гард (`test_bot_read_context.py`) и `test_guard_set_matches_known_baseline`.
- [ ] **Self-review тестов** — preview не мутирует, confirm мутирует, mismatch-reject (BUG-009), reverse/forward контракт. Прецедент по объёму: ~400 LOC / ~25 тестов (Session G).
- [ ] **Полный прогон с БД вне sandbox:** `TEST_POSTGRES=1 .venv/bin/python -m pytest -q` (`required_permissions: all`). Baseline после Wave C малых ≈ **3245 passed / 20 skipped / 2 deselected**; suite вырастет — re-baseline, любой новый fail/skip — блокирующий.
- [ ] **ruff** чисто на изменённых файлах.
- [ ] **commit + deploy — только по явному go-ahead**; закрывающая строка `TD-bot-confirm-coverage-completeness` в [`BUG_LOG.md`](BUG_LOG.md) (BUG-028 convention) + обновить [`WAVE1_TECH_DEBT.md`](WAVE1_TECH_DEBT.md) § A.2.

---

## 6. Артефакты для контекста (прочитать в начале)

- **Инвентарь:** [`WAVE1_TECH_DEBT.md`](WAVE1_TECH_DEBT.md) § A.2 (TD-bot-confirm-coverage-completeness).
- **Backlog:** [`BUG_LOG.md`](BUG_LOG.md) — TD-bot-confirm-coverage-completeness + прецеденты BUG-009 / BUG-025 / BUG-046.
- **Дорожка:** [`START_PROMPT_WAVE1_TECH_DEBT_CLOSURE_2026-06-12.md`](START_PROMPT_WAVE1_TECH_DEBT_CLOSURE_2026-06-12.md) (Wave C, confirm-gate TD).
- **Confirm-flow прецедент:** `tests/test_bot_confirm_flow.py` (паттерн preview → confirm → execute + concurrency-гард из Wave A).
- **Рабочий режим:** [`AGENTS.md`](../../AGENTS.md); режимы pytest — [`tests/README.md`](../../tests/README.md).

---

## 7. Стартовая реплика для новой сессии (можно скопировать)

> Берёмся за `TD-bot-confirm-coverage-completeness` — последний крупный остаток Wave C. Прочитай [`docs/notes/START_PROMPT_TD_BOT_CONFIRM_COVERAGE_2026-06-13.md`](docs/notes/START_PROMPT_TD_BOT_CONFIRM_COVERAGE_2026-06-13.md) и записи TD в BUG_LOG. Решение по scope зафиксировано = admin-квартет (register_user/update_user/add_user_auth/remove_user_auth) с полным confirm-flow (декларация `confirm` + frozenset + executor preview/confirm + FSM-обвязка), bump `prompts/bot.yaml` → v1.7.9. Сначала обсудим развилки (§4), потом код. DoD: self-review тестов, полный прогон `TEST_POSTGRES=1 .venv/bin/python -m pytest -q` вне sandbox, ruff чисто, закрывающая строка в BUG_LOG. Режим: коммит/деплой — только по моему явному запросу.
