# BUG_LOG — журнал обнаруженных багов

**Назначение:** живой реестр багов, обнаруженных в процессе работы над проектом
(в проде, в dev-окружении, на ревью, в чатах с агентами). Каждая запись — это
готовый input для будущей fix-сессии: симптомы, проверенная гипотеза причины,
предлагаемое решение, известный workaround.

**Workflow:**

1. При обнаружении бага — добавить запись в § «Active bugs», статус `open`.
2. При начале fix-сессии — статус `in-progress`, сослаться на стартовый промпт
   (`docs/notes/START_PROMPT_SPRINT_*.md`) или PR.
3. После merge'а fix'а — статус `resolved`, перенести запись в § «Resolved
   bugs» с указанием commit'а / PR'а.
4. Если баг переоткрыт — вернуть в `Active`, добавить новую дату и контекст.

**Поля записи (обязательные):**

- `ID` — `BUG-NNN`, монотонно растёт.
- `Severity` — `Critical | High | Medium | Low`.
- `Status` — `open | in-progress | resolved | wontfix`.
- `Component` — какая подсистема (`mcp_server`, `bot`, `pipeline`, `api`, ...).
- `Discovered` — ISO-дата + кто/как обнаружил.
- `Symptoms` — что именно наблюдается у пользователя / в логах.
- `Root cause` — проверенная (не предполагаемая) причина с ссылками на код.
- `Why CI didn't catch` — где blind-spot в тестах (важно для fix-плана).
- `Proposed fix` — минимальный фикс + hardening, разделённые.
- `Workaround` — что делать прямо сейчас, пока баг не закрыт.
- `Artifacts` — токены, UUID, конфиги, логи, ссылки на чаты-репорты.
- `Linked` — ID связанных багов / TD / DI / PR.

**Severity definitions:**

- **Critical** — блокирует core-функционал в проде (auth, ingestion, RAG) или
  представляет security-issue. Чинится первым приоритетом.
- **High** — ломает важный feature, есть workaround, не утечка данных.
- **Medium** — ухудшает UX или затрудняет работу, но не блокирует.
- **Low** — косметика, edge case, низкочастотный сценарий.

---

## Active bugs

> **Housekeeping note (2026-05-14, docs hygiene sprint M-14).** Записи
> BUG-010 / BUG-011 / BUG-012 — структурно `resolved` (Session I / H /
> v1.5.0 prompt fix соответственно) — перенесены в § «Resolved bugs» ниже
> за нарушение workflow (resolved-в-Active). Их полное содержание
> (severity, root cause, resolution с date / commit / PR) сохранено как
> living history без сокращений. См. § Resolved bugs § BUG-010 / BUG-011 /
> BUG-012.
>
> **Housekeeping note (2026-05-15, MCP testing derived-actions batch).**
> BUG-009 — структурно `resolved` (Session G 2026-05-02 — `execute_tool`
> server-side guard с typed `error_class="ConfirmFlowMismatch"`; см. row
> `Update 2026-05-02 — Session G landed → BUG-009 RESOLVED` в перенесённой
> записи) — перенесён в § «Resolved bugs» ниже совместно с filing
> BUG-015..024 из 2026-05-15 Claude MCP testing session. Anti-scope
> упоминание из PR #69 (M-14 hygiene sprint, «also resolved Session G
> 2026-05-02 но outside explicit M-14 scope») finalized here per
> [`HANDOFF_POST_WAVE1_STEP2_2026-05-15.md`](HANDOFF_POST_WAVE1_STEP2_2026-05-15.md)
> § 6 #4 cleanup. Полное содержание сохранено без сокращений. См.
> § Resolved bugs § BUG-009.
>
> **Housekeeping note (2026-05-20, M-15 docs hygiene sprint).**
> BUG-013 / BUG-014 / BUG-024 / BUG-014B — структурно `resolved` (joint
> fix-sprint PR [#79](https://github.com/AlexEfimov/TG_parser/pull/79) SHA `5465918` +
> BUG-014B PR [#84](https://github.com/AlexEfimov/TG_parser/pull/84) SHA `39da8cc`;
> 24h production watches GREEN per
> [`REVIEW_2026-05-16_BUG013_14_24_DONE.md`](REVIEW_2026-05-16_BUG013_14_24_DONE.md) and
> [`REVIEW_2026-05-20_BUG014B_DONE.md`](REVIEW_2026-05-20_BUG014B_DONE.md)) —
> перенесены в § «Resolved bugs» ниже. Полное содержание сохранено без
> сокращений. См. § Resolved bugs § BUG-013 / BUG-014 / BUG-024 / BUG-014B.
>
> **Housekeeping note (2026-05-21, S1 doc-drift cleanup post-Wave-1-step-2
> hygiene tail).** BUG-016 — структурно `resolved` (PR [#81](https://github.com/AlexEfimov/TG_parser/pull/81)
> SHA `5907179`, deployed 2026-05-15T21:55Z, auto-closed issue #80; status
> flip captured in [`REVIEW_2026-05-16_BUG013_14_24_DONE.md` § 4.2](REVIEW_2026-05-16_BUG013_14_24_DONE.md))
> — статус `open` → `resolved`, добавлена «Update 2026-05-15» closure row.
> BUG-015 / BUG-017..BUG-023 остаются `open` намеренно (BUG-015 gated на
> ADR 0007 dispatch contract; BUG-017/018/023 — quick-wins batch не в
> этом spring'е; BUG-019/020 — backlog; BUG-021 — bundle с ENH-4;
> BUG-022 — closed в Wave 1 step 3 sprint per ADR 0009). См. § Resolved
> bugs § BUG-016.
>
> **Housekeeping note (2026-05-21, S2 quick-wins post-merge / S3 pre-flight).**
> BUG-017 / BUG-018 / BUG-023 — структурно `resolved` (PR
> [#87](https://github.com/AlexEfimov/TG_parser/pull/87) SHA `2e9213c`,
> merged 2026-05-21; per-bug «Update 2026-05-21 — S2 quick-wins fix»
> closure rows ниже + docs backfill commit `4d567ce`). Эти три бага
> ранее (предыдущий 2026-05-21 housekeeping note) были помечены как
> «остаются open намеренно — quick-wins batch не в этом sprint'е»; S2
> quick-wins slot landed их в одном PR с 31 новым тестом. **Open after
> S2:** BUG-015 (gated на ADR 0007 — step 3.1); BUG-019 / BUG-020
> (backlog); BUG-021 (bundle с ENH-4); BUG-022 (closed в Wave 1 step 3
> execution — S3). См. § BUG-017 / § BUG-018 / § BUG-023 closure rows
> ниже.

---

## Documentation cleanup TODOs

* **DOC-001 (Low, 2026-05-24)** — Stale bot username in [`docs/prompts/DEV_RESURRECTION_PROMPT.md:26`](../prompts/DEV_RESURRECTION_PROMPT.md): file references `@smoke_tgparser_bot`, but the actual production bot is `@Tgingest_bot` (id `8657845219`, verified during Wave 1 Step 4 VPS watch OP-2 / OP-3 interactive tests session on `2026-05-24T21:35Z`). Replace string in a separate cleanup commit. Cross-ref: [`WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md` § T+10h45m OP-2 / OP-3 interactive tests results](WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md).

---

### BUG-002 — Бот теряет контекст между сообщениями: «да» на preview уводит LLM в hallucination (`channel_id="test_channel"`)

| Поле | Значение |
|---|---|
| **Severity** | **High** (понижено с Critical → High 2026-04-27 после Session B+ mitigations — см. Update 2026-04-27: M1+M2+M3 закрывают **data-loss vector**: hard-delete устранён (M3 soft-delete), `test_channel` как `add_channel`-аргумент отвергается preflight'ом (M2), placeholder убран из production code path (M1). Root cause (нет conversation memory) **не закрыт** — destructive hallucination всё ещё возможна на чужих каналах, поэтому Critical не уходит ниже High до фикса в Session D (FSM). |
| **Status** | ✅ **`resolved`** (Session D landed 2026-04-28 — root cause закрыт architecturally: FSM-handler выполняет confirm детерминированно, LLM не зовётся на «да»; M1+M2+M3 mitigations остаются для defense-in-depth) |
| **Component** | `tg_parser/bot/agent.py`, `tg_parser/bot/handlers.py`, `tg_parser/bot/main.py` (Dispatcher без storage), tool prompts |
| **Discovered** | 2026-04-26, Alexander, Telegram-бот в проде |
| **Linked** | `prompts/bot.yaml` (preview/confirm-контракт держится только LLM-дисциплиной); косвенно — M3 в `docs/notes/FUTURE_FEATURES.md` (tool args на INFO) |
| **Planned fix** | **Session B+** (mitigations, **landed 2026-04-27**) → `docs/notes/START_PROMPT_HOTFIX_BUG002_MITIGATIONS_2026-04-27.md`; **Session D** (full FSM, 2026-04-28) → `docs/notes/START_PROMPT_FIX_BUG002_BUG004_BOT_FSM_2026-04-28.md` |
| **Update 2026-04-26 23:52** | Контрольная B2-проверка после пополнения Anthropic billing — **BUG-002 воспроизводится с тем же placeholder'ом `test_channel`** (3.5 часа спустя после первого инцидента 19:40, **тот же канал `@mind_rise`**, **то же поведение** turn 1 ok / turn 2 hallucination). Это подтверждает: (a) BUG-002 не зависит от Anthropic billing (как и предсказывалось — bot-Gemini ≠ RAG-LLM); (b) `test_channel` устойчиво генерируется как **hallucinated placeholder из training-data** Gemini (типичный example в open-source Telegram-tutorial'ах), а **не** утечка из `mock_llm.py:180` или fixture'ов в репозитории — `test_channel` отсутствует в `prompts/bot.yaml` и в tool descriptions, и LLM не имеет доступа к коду. См. § «Update from billing-top-up control test (23:52)». |
| **Update 2026-04-26 23:56** | 🚨 **CRITICAL ESCALATION.** На запросе `Переключи LLM на openai` → preview корректный (`set_llm_config(scope='global', provider='openai')`); user «да» → bot **hallucinates другой tool**: `remove_channel(channel_id="test_channel", confirm=True)`. Подтверждено по explicit-тексту ошибки «Я не смог найти канал 'test_channel' **для удаления**». Это значит: scope hallucination'а **шире чем просто `channel_id`** — Gemini теряет **полный** контекст (tool, args, scope) на голом «да» и **систематически предпочитает destructive ops** (`remove_channel`). Severity повышена с High до **Critical** (data-loss potential для канала `test_channel` если он существует в БД). См. § «Update from set_llm_config trace (23:56) — scope escalation». |
| **Update 2026-04-27 — Session B+ landed** | ✅ **Mitigations M1, M2, M3 в проде** (см. § «Mitigation backlog» — все три пункта закрыты). Status переведён в `mitigated`, Severity понижена Critical → High (data-loss vector закрыт, но root-cause контекст-loss остаётся). Что именно сделано: **M1** — `tg_parser/processing/mock_llm.py` больше не имеет default'а `channel_id="test_channel"` (TopicizationMockLLM теперь требует явный аргумент); `scripts/add_test_messages.py` принимает `--channel-id` обязательно и блокирует placeholder-имена; документация (README, USER_GUIDE, scripts/README) переведена на `my_dev_channel`. **M2** — bot и MCP `add_channel` теперь pre-flight отвергают `test_channel`/`example_channel`/`my_channel`/`default`/`channel_a`/`channel_b`/`test`/`example` (плюс runtime-расширение через `BLOCKED_CHANNEL_IDS` env). Реализовано в новом модуле `tg_parser/services/channel_placeholders.py`. **M3** — `remove_channel` (и в боте, и в MCP) больше **не делает cascade hard-delete**; единственный side-effect — soft UPDATE `sources.deleted_at = now()`. Дополнительная Alembic-миграция `d7e8f9a0b1c4` добавляет колонку и partial-index `idx_sources_active`. `IngestionStateRepo` получил `find_deleted_source` и `include_deleted=` kwarg на read-методах; `upsert_source` теперь сбрасывает `deleted_at` на conflict (transparent reanimate-via-add_channel). **Verification**: full pytest 1781 passed (was 1765 baseline; +16 от новых тестов M1/M2/M3); `alembic heads` показывает `d7e8f9a0b1c4` как новую ingestion-голову. **Remaining risk**: контекст-loss всё ещё может породить «пользователь говорит «да» → бот удаляет реальный канал (а не `test_channel`)» — данные после M3 не пропадут, но канал будет временно скрыт от ingestion. Полный фикс — Session D (FSM). |
| **Update 2026-04-27 — post-merge SQL fix (PR #36)** | 🐛➡️✅ **Critical SQL-bug в M3 пойман локальным smoke'ом, исправлен hot-fix follow-up'ом.** При первом ручном `remove_channel` на свежем Docker-стеке после merge'а PR #35 — `asyncpg.exceptions.AmbiguousParameterError: inconsistent types deduced for parameter $1` (UPDATE упал, soft-delete не выполнялся). Корень: `delete_source` использовал один и тот же named-параметр `:now` для двух колонок (`deleted_at`, `updated_at`) — asyncpg не смог вывести consistent type ($1 deduced один раз для двух разных контекстов). Юнит-тесты M3 в PR #35 не ловили — `state_repo.delete_source` был полностью замокан, реальная сериализация asyncpg никогда не запускалась (CI gap). **Fix** ([commit `cf978b1`](https://github.com/AlexEfimov/TG_parser/commit/cf978b1)): SQL переписан на `SET deleted_at = NOW(), updated_at = NOW()` (server-side timestamp; идентичная семантика, без named-params). **Coverage**: новый testcontainers integration test `tests/test_ingestion_state_repo_soft_delete.py` гоняет full M3 lifecycle (upsert → soft-delete → filter → find_deleted → resurrect) на real Postgres + alembic@head; добавлен в CI job `Alembic Runtime Upgrade Smoke (testcontainers)` ([commit `cc4f2b8`](https://github.com/AlexEfimov/TG_parser/commit/cc4f2b8)). **Compose hardening** ([commit `e9ff001`](https://github.com/AlexEfimov/TG_parser/commit/e9ff001)): `tg_parser`/`mcp`/`tg_bot` services получили hardcoded `DB_HOST=postgres`/`DB_PORT=5432` — host-side `.env DB_HOST=localhost` (для CLI runs против published 127.0.0.1:5432) больше не оверайдит compose-default и не вызывает `ConnectionRefusedError` внутри контейнеров. **Verification**: full pytest passes; integration test ~30 сек на свежем стеке; VPS smoke (`docker exec tg_parser_mcp python -c …`) подтвердил полный lifecycle на проде. **Lesson learned**: «If your unit-test mock'ает repo-метод, который содержит non-trivial SQL (named-params, ON CONFLICT, partial-index), запиши companion integration-test через testcontainers — CI должна гонять real DB-driver хотя бы по hot-path'у». |
| **Update 2026-04-28 (15:50) — Session D landed → BUG-002 RESOLVED** | ✅ **Root cause закрыт architecturally.** PR с 6 atomic commits (`a3e3f6c`, `a71a4da`, `8d35eef`, `2357756`, `88773dc`, `a42994d`) на ветке `fix/bug-002-bug-004-bot-fsm-2026-04-28`: aiogram FSMContext + MemoryStorage в Dispatcher, два StatesGroup (`ConfirmFlow.awaiting_confirmation` / `PaginationFlow.has_active_list`), детерминированный `_handle_confirmation_response` (на confirm-turn LLM **не зовётся**, handler берёт original args из state и вызывает `execute_tool(name, {**args, "confirm": True})`). На non-yes/no — D-4 default (clear state + re-route в agent). TTL 5 минут (D-3). `prompts/bot.yaml` v1.1.0 — секции «Confirmation semantics» (LLM объяснено, что повторно не вызывает confirm=true) и «Soft-delete semantics» (M3 wording'и). Tests: `tests/test_bot_fsm.py` 67 тестов в 9 классах, **`test_yes_after_remove_preview_does_not_call_add_channel`** — direct regression на 28.04 00:04 трейс. Production cleanup: `test_channel_123` soft-deleted через прямой SQL `UPDATE sources SET deleted_at=NOW()` 28.04 11:29 UTC+4 (M3 reversible). Полный pytest: 1863 passed, 0 регрессий (baseline 1796 + 67 новых). M2 reject-list оставлен **как есть** (decision per runbook — Session D FSM фикс закрывает hallucination class целиком, в т.ч. через suffixed placeholders, regex-расширение M2 не требуется). M1, M2, M3 остаются для defense-in-depth. |
| **Update 2026-04-28 (00:04) — constructive-op hallucination + M2 bypass via suffixed placeholder** | 🚨 **Новый под-сценарий BUG-002, evidence-trace из проды.** На write-flow `remove_channel(channel_id="-1002120019100")` после корректного preview (с упоминанием M3 soft-delete семантики) и ответа «да» — bot отвечает «Канал 'test_channel_123' успешно добавлен и активирован.». Три новых findings: (1) **constructive-op hallucination** — ранее все traces показывали destructive (`remove_channel`); это первый зафиксированный turn-2-hallucination в **`add_channel`** (новый scope-loss под-вариант, расширяет 23:56 update); (2) **M2 reject-list имеет дыру по exact-match** — `tg_parser/services/channel_placeholders.py:61–63` использует `channel_id in get_blocked_placeholder_names()`, suffix `_123` (или любой другой) проскакивает; placeholder `test_channel_123` ≠ `test_channel`. Это live evidence для гипотетического риска из § Other-placeholder риск (строка 489–494); (3) **Production-БД получила «грязный» канал** — response «успешно добавлен и активирован» подразумевает что `_exec_add_channel` дошёл до telethon-validate'ации и upsert'а в `sources`. Это превращает гипотетический «Future-add риск» из update 23:59 (строка 483) в реальную мину для будущих destructive hallucinations на `test_channel*` префикс. **Severity остаётся High (mitigated)** (data-loss vector закрыт M3, но новая failure-mode задокументирована); **Status остаётся `mitigated`** — M2 оставляем ✅ landed но с явным gap-disclosure (см. § Mitigation backlog). **Implications для Session D**: out-of-scope decision «Test_channel hallucination через другой placeholder = wontfix, closed by M2» **опровергнут evidence'ом** — но архитектурный фикс Session D (FSM-handler выполняет confirm детерминированно, LLM не зовётся на «да») закроет hallucination-class **целиком**, независимо от полноты M2 reject-list. **Follow-up TD**: после landing'а Session D — провести cleanup placeholder-каналов в production-БД (через MCP `list_channels` + regex-фильтр + `remove_channel`); не блокирующий task. См. § «Update 2026-04-28 (00:04) — constructive-op hallucination + M2 bypass» ниже. |

#### Symptoms

Воспроизводимый сценарий из чата:

```
User:  дробавь канал @mind_rise
Bot:   Я собираюсь добавить канал @mind_rise в систему.
       … Действие: Создать новый канал. … Лимит каналов: 5 из 20.
       Вы уверены, что хотите добавить этот канал? Ответьте "да" или "нет".
User:  да
Bot:   Канал 'test_channel' не найден. Возможно, он уже был удален
       или указано неверное имя.
```

То есть preview корректный (`mind_rise`), но финальное «execute»-действие
выполняется над **другим, придуманным** каналом (`test_channel`).

#### Root cause (проверенный)

**У бота нет conversation memory между сообщениями.**

1. `tg_parser/bot/handlers.py:144–149` — каждое текстовое сообщение
   обрабатывается через `agent.process_message(user_text, …)`. Никакого
   per-chat буфера, истории или FSM в handler'е нет.

2. `tg_parser/bot/agent.py:70–72` — `process_message` пересоздаёт `contents`
   с нуля на каждом вызове:

   ```python
   contents: list[dict[str, Any]] = [
       {"role": "user", "parts": [{"text": user_message}]},
   ]
   ```

   Это локальная переменная функции, она мусор-собирается сразу после
   `return`. История turn'ов одного chat'а в Gemini API не передаётся.

3. `tg_parser/bot/main.py:161` — `Dispatcher()` создаётся без `storage=…`,
   FSMContext не используется ни в одном handler'е (поиск `FSMContext`,
   `state.set/get`, `chat_history`, `conversation`, `memory` в
   `tg_parser/bot/` ничего не возвращает кроме `task_history` про каналы).

Реконструкция:

- **Turn 1** («дробавь канал @mind_rise»): Gemini вызывает
  `add_channel(channel_id="mind_rise", confirm=false)`, получает preview,
  формулирует русский текст для пользователя. `contents` обнуляется.
- **Turn 2** («да»): Gemini получает только `[{"role":"user","parts":[{"text":"да"}]}]`
  + system-prompt. Понятия не имеет, что подтверждается. System-prompt
  (`prompts/bot.yaml:31–32`) при этом обязывает использовать tool'ы для
  любого действия. LLM вынуждена что-то вызвать на чистом контексте.

Почему именно `test_channel`: в репозитории это имя встречается **50+ раз**
(`tests/`, `scripts/add_test_messages.py`, `docs/notes/`, `docs/USER_GUIDE.md`)
плюс зашит как default в `tg_parser/processing/mock_llm.py:180`. Это сильный
attractor в обучающих данных Gemini для сценария «подставь какой-нибудь
channel_id». Формулировка ответа («Возможно, он уже был удален или указано
неверное имя») — приукрашенный перевод одного из tool-response'ов
`"Channel 'test_channel' not found."` (см. `tg_parser/bot/tools.py:1262, 1336,
1505` — pause/resume/remove). Самой строки про «возможно, удален» в коде нет —
её добавил Gemini от себя.

##### Почему гипотезы-альтернативы отметены

| H | Описание | Вердикт |
|---|---|---|
| H2 | System prompt мутит модель упоминанием `test_channel` | `prompts/bot.yaml` целиком прочитан, `test_channel` отсутствует. |
| H3 | Tool description содержит default-значение `test_channel` | Декларации (`tg_parser/bot/tools.py:280–346`) дают defaults `false`/`100`, никаких string-defaults для channel_id. |
| H4 | Слишком высокая `temperature=0.2` | Не root cause. На пустом контексте даже `0.0` не помог бы — модели приходится что-то отвечать. |
| H5 | Aiogram middleware режет текст | `handle_text` тривиален, `user_text` идёт в агент as-is. |

#### Why CI didn't catch

- Единственные тесты `GeminiAgent` (`tests/test_rag_prompt_config.py:947–977`)
  проверяют только загрузку system-prompt'а из YAML.
- Нет ни одного теста, прокатывающего **two-turn confirm-flow** через
  `agent.process_message` (turn 1: preview tool call → turn 2: «да» →
  ожидание execute-tool-call с теми же args + `confirm=true`).
- `tests/test_mcp_management.py` тестирует MCP-tool'ы напрямую с готовым
  `confirm=true` — это другая поверхность (MCP, не bot agent loop).
- Весь preview/confirm-контракт держится исключительно на LLM-дисциплине
  внутри **одного** turn'а. Архитектурный gap фиксируется первым же
  межсообщенческим сценарием, как только пользователь подтверждает в
  отдельном reply.

#### Proposed fix

Три варианта по нарастающей правильности; рекомендация — B + Hardening.

**Вариант A — минимум (in-memory conversation buffer).**
Завести `dict[chat_id, list[Turn]]` внутри `GeminiAgent` (или DI-инжекцией
поверх dispatcher'а), TTL ≈ 10 минут, MAX_TURNS ≈ 6. На каждом
`process_message`: подгрузить историю → передать в `contents` перед
текущим сообщением → после ответа записать turn(s) обратно. ≈50 строк.
**Минусы:** не переживает рестарт пода, не multi-replica safe, без backpressure.

**Вариант B — правильный (FSMContext + storage).**
Aiogram уже даёт `FSMContext`/`StateGroup`. Завести state
`ConfirmFlow.awaiting_confirmation`. Когда LLM в turn 1 возвращает
tool-result с `"preview": True`, handler сохраняет в FSM
`pending_action = {tool_name, args}` и переводит chat в
`awaiting_confirmation`. На следующем сообщении в этом state'е:
- «да/yes/подтверждаю/ok» → handler сам зовёт `_exec_<tool>` с
  тем же `args` + `confirm=True`, чистит state. **Не дёргаем LLM
  для подтверждения вообще** — детерминированно.
- «нет/cancel/отмена» → state очищается, ответ «Отменено».
- иначе → state очищается, сообщение идёт через агента как новый
  запрос (юзер передумал).
Storage: Redis в проде (multi-replica safe), `MemoryStorage` в dev.
Нативно для aiogram. ≈200 строк + миграция Dispatcher'а на storage.
**Минусы:** меняет контракт между `agent.py` и `handlers.py` — handler
должен знать tool-семантику preview'а, а не делегировать всё LLM.

**Вариант C — гибрид (buffer + явный «да/нет»-detector).**
Per-chat buffer (как в A) + лёгкий guard в handler'е: если в последнем
tool-response был `"preview": True`, запомнить `pending_tool` (in-memory
или FSM); на следующем сообщении при матче regex'а «да/нет» — handler
вызывает `_exec_*` напрямую без обращения к Gemini, иначе — обычный путь
через агента с conversation history.
**Минусы:** parsing «да/нет» в свободной форме не идеален (false positive
на «да это вообще не про канал»); по сути B, реализованный без FSM.

**Hardening (для всех вариантов):**

1. **Логировать tool args на INFO** (сейчас `agent.py:115` — `DEBUG`).
   В первой же сессии было бы видно `tool=remove_channel
   args={"channel_id":"test_channel","confirm":true}`. С учётом, что бот
   за `BOT_ALLOWED_USERS`, security-impact приемлем (M3 из
   `FUTURE_FEATURES.md` относится к публичному API).
2. **Tool-side sanity check** для read-after-write tool'ов
   (`_exec_remove_channel/pause/resume/trigger_pipeline`): если
   `channel_id` не найден в БД, возвращать ошибку **со списком доступных
   user'у каналов**. LLM получает список — не может «угадать», и при
   `confirm=True` без canonical match отказ происходит детерминированно.
   Не root-cause-fix, но второй слой защиты от любых будущих hallucinations.
3. **Two-turn integration test** для bot agent. Mock Gemini: turn 1 →
   `add_channel(channel_id="X", confirm=false)`, turn 2 (после "да" от
   юзера) → должен зайти `add_channel(channel_id="X", confirm=true)` с
   **тем же** `channel_id`. Без этого теста любой будущий рефактор
   сломает контракт молча.
4. **Убрать `test_channel` как production-default.**
   `tg_parser/processing/mock_llm.py:180` — формально mock-класс, но если
   его дефолт когда-либо просочится в prompt context'ы или embeddings
   через утечку из тестов, он усиливает attractor для LLM. Минимум —
   переименовать в `__placeholder__` или сделать обязательным аргументом
   без default'а. (Low-priority cosmetic.)

**Рекомендация:** **B + Hardening 1, 2, 3.** Если нужен экстренный
костыль до полной FSM-миграции — выкатить A на 1 коммит, накрыть
hardening 1+3, и дальше эволюционировать в B без переписывания
контракта (per-chat buffer ↔ FSM-state — взаимно совместимы).

#### Workaround (на время до фикса)

Юзеру: подтверждать действие **в одном сообщении вместе с командой**:

> «Добавь канал @mind_rise, подтверждаю»
> «Удали канал old_one, я уверен, confirm=true»

В этом случае Gemini увидит и команду, и подтверждение в рамках одного
turn'а — `contents` не успеет обнулиться. Это работает, потому что
система-промпт явно описывает preview/confirm-протокол как «вызови
tool с confirm=false → спроси юзера → вызови с confirm=true», но при
явном подтверждении в первом же сообщении Gemini обычно делает оба
вызова в одном turn-loop'е.

Альтернатива (только для admin) — через MCP / SQL workaround из BUG-001
(пока он не закрыт, сам add_channel через MCP всё равно даёт FK
violation; SQL-вставка работает).

#### Artifacts

- Конкретные строки источника текста ошибки:
  `tg_parser/bot/tools.py:1262` (pause), `:1336` (resume), `:1505` (remove)
  — все возвращают `f"Channel '{normalized}' not found."`.
- Default `test_channel` в `tg_parser/processing/mock_llm.py:180`.
- Системный промпт: `prompts/bot.yaml:30–43` (раздел Instructions).
- Точка отсутствия истории: `tg_parser/bot/agent.py:70–72`,
  `tg_parser/bot/handlers.py:144–149`, `tg_parser/bot/main.py:161`.
- Тестовый gap: `tests/test_rag_prompt_config.py:947–977` — единственное
  покрытие `GeminiAgent`, без multi-turn.

#### Update from billing-top-up control test (2026-04-26 23:52)

Контрольная B2-проверка через 3.5 часа после первого инцидента
19:40:54. Тот же канал, тот же placeholder, та же ошибка:

```
Alex: добавь канал @mind_rise              [23:52:20]
Bot:  Я собираюсь добавить канал @mind_rise в систему.
      Предварительный просмотр:
      * Действие: Создать
      * ID канала: mind_rise
      * Текущий статус: Нет (будет добавлен как новый)
      * Активных источников после добавления: 5 из 20
      Вы уверены, что хотите добавить этот канал? (да/нет)
                                              [23:52:22]
Alex: да                                      [23:52:30]
Bot:  Произошла ошибка: канал 'test_channel' не найден.
      Возможно, он уже был удален или указано неверное имя.
                                              [23:52:35]
```

###### Что подтверждает контрольный трасс

1. **Turn 1 идеально работает**: bot вызвал `_exec_add_channel(channel_id="mind_rise", confirm=False)` корректно (preview показывает правильный ID), отрисовал preview за 2 секунды. То есть проблема **не** в parsing'е первого сообщения и **не** в `_exec_add_channel` сам по себе — проблема **строго в потере контекста** между turn 1 и turn 2.

2. **Turn 2 видит только «да»**: Gemini-агент без conversation memory вынужденно угадывает аргументы для второго вызова. **Реально вызвал `_exec_add_channel(channel_id="test_channel", confirm=True)`** — об этом говорит маршрут текста ошибки. `Channel '{normalized}' not found` приходит из telethon `get_entity("test_channel")` → Telegram-API ответил «not found» (такого канала действительно нет в Telegram).

3. **Placeholder `test_channel` стабилен через сессии**: и трасс 19:40, и трасс 23:52 (через 3.5 часа, после рестарта Telegram, после неизвестного количества интерфейс-событий) выдают **тот же** `test_channel`. Это не stochastic hallucination, а **strong-prior placeholder** в LLM training data.

###### Почему именно `test_channel` (уточнение к прежнему анализу)

Прежний анализ зафиксировал, что `test_channel` встречается в репозитории 50+ раз (`tg_parser/processing/mock_llm.py:180`, тесты, docs, scripts) и предположил роль H3 (tool description containing default). Свежий grep подтверждает прежнюю диагностику:

| Источник | Виден ли LLM? |
|---|---|
| `tg_parser/processing/mock_llm.py:180` (`channel_id: str = "test_channel"`) | ❌ Нет — это server-side default, не передаётся в LLM context. |
| `tests/test_*.py` (12+ упоминаний) | ❌ Нет — тесты в LLM context не попадают. |
| `docs/notes/*.md`, `QUICK_START.md` | ❌ Нет — docs в LLM context не попадают. |
| `scripts/add_test_messages.py` | ❌ Нет. |
| `prompts/bot.yaml` (system prompt) | ❌ Нет — `test_channel` отсутствует (повторно проверено). |
| Tool declarations в `tg_parser/bot/tools.py:43+` (видны LLM) | ❌ Нет — string-defaults для `channel_id` отсутствуют (повторно проверено). |
| **Training data самой Gemini-2.5-flash** | ✅ Да |

Вывод: `test_channel` — **classical archetypical placeholder** из публичных Telegram-tutorial'ов (огромное количество туториалов вида «Setting up a Telegram bot» используют `test_channel` как пример). Gemini training data содержит много таких текстов. Когда модель ищет канал-плейсхолдер в условиях нехватки контекста, она статистически попадает в `test_channel` как наиболее вероятную форму.

**Это означает:**
- Удалить `test_channel` из `mock_llm.py` — не поможет (LLM его не видит).
- Поменять fixture-имена в тестах — не поможет.
- Реальный фикс — **убрать саму возможность угадывания** через FSM-storage (см. § Predicted fix BUG-002).

###### Severity подтверждена

Bot **физически блокирует** любой add_channel-flow для пользователя, не знающего workaround'а. Если пользователь напишет «да» (как и 95% людей в подобной диалоговой ситуации), bot пытается добавить `test_channel`, который не существует, и flow завершается ошибкой. **Невозможно добавить ни один реальный канал стандартным способом**. Severity High остаётся.

###### Workaround (для пользователя до фикса)

Все write-flow'ы выполнять **в одном сообщении** с явной формулировкой намерения:

```
✗ Не работает:
   Alex: добавь канал @mind_rise
   Bot:  preview…
   Alex: да                          ← turn 2 теряет контекст

✓ Работает:
   Alex: добавь канал @mind_rise с подтверждением      ← один turn
         (тогда LLM видит и канал, и confirm в одном сообщении и
          сразу делает add_channel(channel_id="mind_rise", confirm=True))
```

Этот workaround **обходит preview-step**, что нарушает safety-контракт
(BUG-002 root cause описывает почему). Это **не настоящий фикс**, но
позволяет продолжать пользоваться ботом до фикса BUG-002.

#### Update from set_llm_config trace (2026-04-26 23:56) — scope escalation

Третий контрольный трасс (после 19:40 и 23:52) даёт **новое и очень
тревожное наблюдение**. На write-flow для `set_llm_config` (а не
`add_channel`):

```
Alex: Переключи LLM на openai                           [23:56:08]
Bot:  Я собираюсь изменить глобальный провайдер LLM на "openai".
      Текущая конфигурация:
        * Глобальный провайдер: anthropic
          (модель: claude-sonnet-4-20250514)
      После подтверждения:
        * Глобальный провайдер: openai
          (модель: по умолчанию для openai)
      Вы уверены, что хотите применить это изменение?
      (да/нет)                                          [23:56:10]
Alex: да                                                [23:56:20]
Bot:  Я не смог найти канал 'test_channel' для удаления.
      Возможно, он уже был удален или указано неверное имя.
                                                        [23:56:22]
```

###### Что нового по сравнению с прежними трассами

| Аспект | 19:40 / 23:52 (add_channel) | 23:56 (set_llm_config) |
|---|---|---|
| Tool в turn 1 | `add_channel` | `set_llm_config` |
| Tool в turn 2 | `remove_channel` (presumed) или `add_channel` | **`remove_channel` (однозначно)** |
| Hallucinated args | `channel_id="test_channel"` | `channel_id="test_channel"` |
| Текст ошибки | «Канал 'test_channel' не найден…» (general) | «Я не смог найти канал 'test_channel' **для удаления**…» (explicit `remove_channel`) |
| Confirmation идентификации tool'а | Ambiguous | **Однозначная** (фраза «для удаления») |

###### Ключевое наблюдение: scope hallucination'а **шире**, чем считали

Прежний анализ BUG-002 говорил: «turn 2 теряет `channel_id` и
hallucinates `test_channel`». Реальность хуже:

> **На голом «да» в turn 2 Gemini теряет ВСЁ:**
> - Tool, который собирался выполняться в turn 1.
> - Args этого tool'а.
> - Scope действия.
>
> И вынуждена угадать **новую** tool-call'у с нуля, имея только
> `[{"role":"user","parts":[{"text":"да"}]}]` + system-prompt.

В трассе 23:56 первоначальная операция была **`set_llm_config`**, а
hallucinated в turn 2 операция — **`remove_channel`**. Это разные
tool'ы с разной семантикой и разными args — статистически Gemini
**выбирает** `remove_channel` в условиях нехватки контекста для
подтверждения, потому что в training-data confirmation-pattern «да»
чаще ассоциируется с destructive op'ами (delete, remove, terminate),
чем с конструктивными (add, create, set).

###### Data-loss risk

Если в БД **существует** канал с `channel_id == "test_channel"` (а это
**реальный риск**: `tg_parser/processing/mock_llm.py:180` имеет
`channel_id: str = "test_channel"` как default; `scripts/add_test_messages.py:24`
использует `"test_channel"` для fixture'ов; в репозитории это имя
встречается 50+ раз — кто-то мог добавить его через CLI/scripts), то:

```
remove_channel(channel_id="test_channel", confirm=True)
  → tg_parser/bot/tools.py:1505 _exec_remove_channel
  → ChannelRepo.delete(channel_id="test_channel")
  → CASCADE DELETE all RawMessage / ProcessedDocument /
                     TopicCard / TopicBundle для test_channel
```

**Это IRREVERSIBLE data deletion**, выполняемое **silently** для
пользователя, который думал что подтверждает совершенно другое
действие (`set_llm_config` или `add_channel`). Bot не показал на
preview-step что собирается удалять канал — потому что в turn 1
preview был корректным для **другого** действия.

**Это data-loss scenario с silent execution.** Severity bump → Critical.

###### Обновлённый workaround

Прежний workaround «всё в одном сообщении с явным `с подтверждением`»
работает для `add_channel`, но **критически важно применять его
к ВСЕМ write-flow'ам** (`add/remove/pause/resume_channel`,
`set/reset_llm_config`, `trigger_pipeline`):

```
✓ Безопасно (один turn):
   Alex: Переключи LLM на openai с подтверждением
   Bot:  set_llm_config(scope='global', provider='openai', confirm=True)
         (одна tool-call'а, нет turn 2 → нет hallucination)

✗ Опасно (два turn'а):
   Alex: Переключи LLM на openai
   Bot:  preview…
   Alex: да
   Bot:  remove_channel(test_channel, confirm=True)  ← может удалить данные
```

###### Дополнительный mitigation на стороне репозитория (немедленный)

Поскольку фикс BUG-002 нетривиален (требует FSM-storage + integration
test), **разумно немедленно проверить и подчистить БД** на наличие
канала `test_channel`:

```sql
SELECT * FROM channels WHERE channel_id = 'test_channel';
SELECT COUNT(*) FROM raw_messages WHERE channel_id = 'test_channel';
SELECT COUNT(*) FROM processed_documents WHERE channel_id = 'test_channel';
```

Если канал существует — он либо нужный (тогда переименовать в
`test_channel_safe` или подобное), либо тестовый артефакт (тогда
вручную удалить через `remove_channel`-tool в контролируемой ситуации,
не через bot-flow). После этого `remove_channel(test_channel, True)`
hallucination станет no-op'ом — каналу нечего удалять, безопасно.

Это **не фикс BUG-002**, это **mitigation для data-loss риска** на
время до фикса.

###### Updated linked

Поскольку scope hallucination shires than just `channel_id`, BUG-002
теперь **косвенно связан** со всеми write-tool'ами, не только
`add_channel`-flow:

- `_exec_remove_channel` — главный риск (destructive, IRREVERSIBLE).
- `_exec_pause_channel`, `_exec_resume_channel` — non-destructive, но
  меняют состояние не того канала.
- `_exec_set_llm_config`, `_exec_reset_llm_config` — меняют LLM-конфиг
  не той scope'ы.
- `_exec_trigger_pipeline` — может стартовать pipeline для не того
  канала.

###### Severity rationale (final)

- **High** до 23:56 — broken UX for write-flows, no data corruption.
- **Critical** после 23:56 — data-loss potential без preview, scope
  shifted from "wrong target" to "wrong operation entirely on
  destructive tool".

Это меняет приоритет в backlog'е: BUG-002 теперь **должен быть
закрыт раньше BUG-006**, потому что блокирует data-safety, а не
просто UX.

###### Update from MCP DB-check (2026-04-26 23:59) — `test_channel` отсутствует

После идентификации Critical-риска проведена немедленная проверка
production-БД через MCP-tool'ы:

| Проверка | Что смотрит | Результат |
|---|---|---|
| `list_topics(channel_id="test_channel")` | `topic_cards.sources` JSONB | `total: 0` |
| `search_knowledge_base(query="test", channel_id="test_channel")` | `processed_documents` + topic-search | empty |
| `get_pipeline_status()` | `sources` table (Channel records) | 5 каналов, **`test_channel` отсутствует** |

5 реально подключённых каналов: `AgeManagment`, `Lab4health`,
`LongevityClub`, `genotek`, `labdiagnostica_logical`.

**Вывод**: production-БД **временно безопасна** от конкретного
`test_channel`-data-loss-сценария. Hallucinated `remove_channel(test_channel)`
гарантированно вернёт `Channel 'test_channel' not found` без cascade-delete
(`_exec_remove_channel` ищет Channel record первым и failuet'ит до
любого `delete()`).

###### Что Critical-rating сохраняет даже при безопасной БД

Severity Critical **не понижается**, потому что:

1. **Future-add риск.** Любой будущий канал с именем `test_channel`
   (через CLI, scripts, тестирование на production-окружении, или сам
   bot если в нём появится новый flow) попадёт под удар немедленно.
   `mock_llm.py:180` и `scripts/add_test_messages.py:24` создают
   нетривиальную вероятность что кто-то это сделает.

2. **Other-placeholder риск.** В этой сессии трасс 23:56 однозначно
   показал hallucination в **`remove_channel`**. Но Gemini может с
   разной вероятностью генерить **другие** placeholder'ы:
   `example_channel`, `my_channel`, `default`, `channel_a`, etc. Для
   проверки безопасности нужно prove **отсутствие** ВСЕХ
   placeholder'ов, что невозможно exhaustively.

3. **Model-drift риск.** Если для лечения BUG-006 будет принято решение
   сменить `BOT_GEMINI_MODEL` на gpt-4o / claude-haiku-4-5 / другой
   провайдер, у новой модели training-data prior может оказаться
   другим placeholder'ом. Тогда BUG-002 может вне предупреждения
   реализоваться на новом имени канала, которое *уже существует* в БД.

4. **Any destructive write-tool в turn 2.** Не только remove_channel:
   `set_llm_config` мог бы установить provider в неправильный scope,
   `trigger_pipeline` стартовать pipeline для не того канала,
   `reset_llm_config` сбросить настройки которые пользователь только
   что выставил. Все эти write-flow'ы под угрозой.

###### Update 2026-04-28 (00:04) — constructive-op hallucination + M2 bypass

Четвёртый контрольный трасс (после 19:40, 23:52, 23:56) — **первое
зафиксированное hallucination на constructive op'е**, плюс live
evidence для гипотетического "Other-placeholder риск" (предыдущий
пункт 2). Это не Critical-escalation — M3 soft-delete уже в проде
и data-loss vector закрыт — но качественно новая под-форма scope-loss'а,
которую нужно зафиксировать **до старта Session D**.

```
[28 апр. 2026 г., 00:03:51]
Bot:  This looks like a Telegram channel ID. What would you like to
      do with it? I can:
      - Answer questions about its content
      - Search for information within it
      - List its topics
      - Show its overview and statistics
      - Start the processing pipeline
      - Pause or resume it
      - Add or remove it
      - Export its content
                                              [пользователь до этого
                                               отправил сам channel_id]
[00:04:09]
Alex: удали его
[00:04:11]
Bot:  Пожалуйста, уточните, что именно вы хотите удалить. Я могу удалить:
      * Канал
      * Подписку на дайджест
      * Отслеживаемый список (watchlist)
      Укажите ID или название того, что нужно удалить.
[00:04:19]
Alex: канал '-1002120019100'
[00:04:21]
Bot:  Что вы хотите сделать с каналом '-1002120019100'? Вы хотите получить
      информацию о нем, запустить обработку, или что-то еще?
[00:04:27]
Alex: удалить
[00:04:30]
Bot:  Что именно вы хотите удалить? У меня есть функция для удаления
      канала, но это необратимое действие, которое приведет к удалению
      всех данных канала.
[00:04:41]
Alex: Удали канал '-1002120019100'
[00:04:43]
Bot:  Вы собираетесь удалить канал с ID -1002120019100.
      Текущий статус: active
      Количество обработанных документов: 0
      Количество сырых сообщений: 0
      Количество тем: 0
      Внимание: Это будет мягкое удаление. Строка источника будет
      помечена как deleted_at=now(), и прием данных будет остановлен.
      Существующие необработанные сообщения, обработанные документы,
      темы и встраивания будут сохранены и могут быть восстановлены
      администратором.
      Вы уверены, что хотите продолжить? (да/нет)
[00:04:52]
Alex: да
[00:04:54]
Bot:  Канал 'test_channel_123' успешно добавлен и активирован.
      Планировщик начнет обработку в следующем цикле. Вы можете
      использовать команду trigger_pipeline, чтобы запустить
      обработку немедленно.
```

**Что нового по сравнению с 19:40 / 23:52 / 23:56:**

| Аспект | 19:40 / 23:52 (add_channel) | 23:56 (set_llm_config) | **00:04 (remove_channel)** |
|---|---|---|---|
| Tool в turn 1 | `add_channel` | `set_llm_config` | `remove_channel` |
| Tool в turn 2 после "да" | `add_channel(test_channel)` | `remove_channel(test_channel)` | **`add_channel(test_channel_123)`** ⬅️ новое |
| Семантика turn 2 op'а | constructive | destructive | **constructive** ⬅️ новое |
| Hallucinated placeholder | `test_channel` (точный M2-hit) | `test_channel` (точный M2-hit) | **`test_channel_123`** ⬅️ M2 miss |
| Op-direction match с turn 1 | partial | mismatch | mismatch (delete→add) |
| Side-effect в БД | reject (telethon: not found) | reject (telethon: not found) | **возможно success** (имя validates как Telegram username) |
| M2 защита сработала | ✅ да (для имени) | ✅ да (для имени) | ❌ **нет** (suffix bypass) |

**Finding 1 — constructive-op hallucination (новая под-форма).**

Update 23:56 утверждал: «Gemini систематически предпочитает destructive
ops в условиях scope loss». Этот трасс — контр-evidence: в 00:04
исходный intent был **destructive** (`remove_channel`), а
hallucinated turn 2 — **constructive** (`add_channel`). Прежнее
утверждение нужно ослабить: Gemini выбирает **первый popped tool из
training-data prior'а для confirmation-pattern** независимо от
направления исходной op'ы. Иногда destructive (как в 23:56), иногда
constructive (как в 00:04). Это **расширяет** scope-loss-class,
а не противоречит ему.

**Finding 2 — M2 reject-list имеет дыру по exact-match.**

Реализация в `tg_parser/services/channel_placeholders.py:61–63`:

```python
def is_blocked_placeholder(channel_id: str) -> bool:
    """True iff `channel_id` (already normalised, no leading `@`) is reserved."""
    return channel_id in get_blocked_placeholder_names()
```

`get_blocked_placeholder_names()` возвращает frozenset с 8
hardcoded именами (`test_channel`, `example_channel`, `my_channel`,
`default`, `channel_a`, `channel_b`, `test`, `example`) плюс
runtime-расширение из `BLOCKED_CHANNEL_IDS` env. Это **точное**
string-сравнение. `test_channel_123` ≠ `test_channel` →
проскакивает. Это **live confirmation** § Other-placeholder риск
из update 23:59 (пункт 2) — гипотетический риск получил production
trace.

**Finding 3 — production-БД, по всей видимости, получила «грязный» канал.**

Response «Канал 'test_channel_123' успешно добавлен и активирован.
Планировщик начнет обработку в следующем цикле.» — характерный
success-payload для `_exec_add_channel`, который генерируется только
**после** успешного `IngestionStateRepo.upsert_source(...)`. То есть
Gemini-сторона не выдумала текст: tool реально вернул success, и
строка `sources(channel_id='test_channel_123', deleted_at=NULL,
status='active')` предположительно есть в production-БД.

Это превращает гипотетический «Future-add риск» из update 23:59
(пункт 1, строка 483) — «любой будущий канал с placeholder-именем
попадёт под удар немедленно» — в реальную мину **прямо сейчас**:

- Любая будущая destructive hallucination на `test_channel*`-prefix
  имеет реальный target.
- M3 soft-delete минимизирует blast radius, но `test_channel_123`
  всё ещё может стать noise'ом в `list_channels` UI и в digest/watchlist
  scoping'е (если case передавался без validation).
- Cleanup нужно сделать в течение 1-2 дней — лучше до Session D, чтобы
  regression-тесты не конфликтовали с реальной row'ой.

Конкретный SQL для проверки и cleanup:

```sql
SELECT channel_id, status, created_at, deleted_at
FROM sources
WHERE channel_id ~ '^(test|example|my|default)[_-]?channel.*'
   OR channel_id ~ '^channel_[a-z]$'
   OR channel_id IN ('test', 'example');
```

Через MCP — `list_channels()` + visual scan на placeholder-pattern'ы.
Soft-delete через `remove_channel(channel_id, confirm=True)` —
безопасно, M3 reversible через `add_channel`.

###### Severity-rationale (после 00:04)

Severity **остаётся High (mitigated)**, не повышается обратно до
Critical:

- **Data-loss vector закрыт M3** — даже если в turn 2 произошёл
  destructive hallucination на реальный канал, он soft-delete'ится
  и обратимо восстанавливается через add_channel.
- **Constructive hallucination (00:04 trace) НЕ data-loss** — добавляет
  лишний row в `sources`, не теряет существующие данные. UX-mess,
  не safety-critical.
- **M2 bypass — это severity-neutral observation**: M2 закрывает
  только blast radius на placeholder-имена; реальный root cause
  (statelessness) и так требует Session D.

Если бы 00:04 trace показал destructive hallucination на existing
real channel — severity бы повысилась до Critical (но и тогда M3
бы спас данные). Текущий trace — **новый failure mode**, но не
escalation severity.

###### Implications для Session D scope (читать перед стартом)

Out-of-scope decision в `START_PROMPT_FIX_BUG002_BUG004_BOT_FSM_2026-04-28.md`
§ 2 — «Test_channel hallucination через другой placeholder = wontfix,
closed by Session B+ M2 reject-list» — **опровергнут evidence'ом**.
Однако правильное действие — **НЕ** расширять M2 до regex-pattern
(это не нужно), а зафиксировать что архитектурный фикс Session D
(FSM-handler детерминированно зовёт `_exec_<tool>` с originally-previewed
args + `confirm=True`, **не дёргая LLM**) закроет hallucination-class
**целиком**, независимо от полноты M2 reject-list. Out-of-scope
строку нужно переписать с «wontfix» на «covered architecturally by
Session D» — это уже сделано в обновлённом runbook'е.

###### Follow-up TD (post-Session-D cleanup)

**TD-bug-002-postmortem-cleanup**: после landing'а Session D —
выполнить cleanup placeholder-каналов в production-БД через
MCP-flow:

1. `list_channels()` → отфильтровать по regex-pattern из SQL выше.
2. Для каждого matching канала: `remove_channel(channel_id,
   confirm=True)` — soft-delete безопасно, reversible.
3. Verify `find_deleted_source(channel_id)` возвращает row с
   `deleted_at != NULL`.

Не блокирующий task; лучше сделать в первые 1-2 дня после Session D,
пока контекст свежий. Если Session D откладывается — этот cleanup
имеет смысл сделать до неё, чтобы integration-tests не конфликтовали
с production row'ой `test_channel_123`.

###### Mitigation backlog (помимо фикса самого BUG-002)

1. ✅ **[LANDED 2026-04-27, M1, commit `e927f53`]** **Defensive naming
   в коде** — `test_channel` больше не default ни в одном production
   code path. `tg_parser/processing/mock_llm.py:TopicizationMockLLM.__init__`
   требует `channel_id` без default'а; `scripts/add_test_messages.py`
   получил argparse-обёртку с обязательным `--channel-id` и блокирует
   placeholder-имена. Документация переведена на `my_dev_channel`.
   Регрессионный тест: `tests/test_mock_llm.py`.

2. ✅ **[LANDED 2026-04-27, M2, commit `295d6e9`]** **Pre-flight check
   на каналы с подозрительными именами** — bot и MCP `add_channel`
   отвергают входные `channel_id` ∈ {`test_channel`, `example_channel`,
   `my_channel`, `default`, `channel_a`, `channel_b`, `test`,
   `example`}. Список расширяется через `BLOCKED_CHANNEL_IDS` env
   (CSV). Реализация: `tg_parser/services/channel_placeholders.py`.
   Регрессионные тесты: новые классы `TestExecAddChannelBlockedPlaceholder`
   (бот) и `TestAddChannelBlockedPlaceholder` (MCP).
   - ⚠️ **M2 gap discovered 2026-04-28 (00:04)**: exact-string match
     не покрывает variants с суффиксами (`test_channel_123` slipped
     through, см. § «Update 2026-04-28 (00:04)»). M2 **не**
     пере-открывается как `open` — gap закрывается архитектурно в
     Session D (FSM-handler не зовёт LLM на «да», hallucination-class
     закрывается целиком). При откладывании Session D >7 дней —
     рассмотреть расширение `channel_placeholders.py` до regex-pattern
     как hot-fix follow-up (`^test[_-]?channel`, `^example[_-]?channel`,
     etc); до тех пор — env-override через `BLOCKED_CHANNEL_IDS=test_channel_123,...`
     для известных in-prod placeholder'ов.

3. ✅ **[LANDED 2026-04-27, M3, commit `eac05b6`]** **Soft-delete вместо
   hard-delete для `remove_channel`** — `remove_channel` (и MCP, и бот)
   больше не делает cascade-DELETE. Соответствующая `sources` строка
   получает `deleted_at = now()`, остальные таблицы не трогаются.
   Дополнено Alembic-миграцией `d7e8f9a0b1c4` (колонка + partial
   `idx_sources_active WHERE deleted_at IS NULL`). `IngestionStateRepo`
   фильтрует soft-deleted по умолчанию; `upsert_source` сбрасывает
   `deleted_at` на conflict — re-`add_channel` прозрачно реанимирует
   канал. Тесты: `test_remove_success_soft_delete` (MCP),
   `test_confirm_soft_delete_only` (бот) — оба явно проверяют, что
   `delete_by_channel` ни разу не вызван.

Эти три mitigation-задачи **сделаны раньше** основного фикса BUG-002
(FSM-storage в Session D). Они не закрывают баг (контекст-loss всё
ещё возможен), но **радикально снижают blast radius**: data-loss
сценарий устранён, hallucination на placeholder-имени отвергается
preflight'ом.

---

### BUG-003 — Read-tool'ы бота не нормализуют `@` в `channel_id` → пустой ответ на «темы канала @AgeManagement»

| Поле | Значение |
|---|---|
| **Severity** | **Low для bot-канала, Medium для MCP-канала** (через Telegram-бот Gemini-агент сам стрипает `@`, баг невидим; через прямой MCP-клиент без LLM — баг воспроизводится детерминированно. Хрупко к смене модели бота.) |
| **Status** | `resolved (Session F, 2026-04-29; deployed 2026-04-30 15:12 UTC, squash SHA 88e4337)` — shared `tg_parser.utils.channel_id.normalize_channel_id` helper landed; все 25+ existing `lstrip("@")` call-sites consolidated; 8 read-tool executors в `bot/tools.py` + 4 MCP read-tool'а в `mcp_server.py` нормализуют `channel_id` (плюс quote-strip и whitespace-strip для F-8). Acceptance grep `rg "lstrip..@.." tg_parser/ scripts/` возвращает только helper body. **Production smoke 2026-04-30**: `темы канала @AgeManagment` (с @-prefix) → 75 тем (BUG-003 production trigger confirmed closed). См. § Updates → Session F (2026-04-30) deployed. |
| **Component** | `tg_parser/bot/tools.py` (read-tool executors), `tg_parser/mcp_server.py` (latent — та же дыра, прячется за дисциплиной клиента) |
| **Discovered** | 2026-04-26, Alexander, Telegram-бот в проде |
| **Linked** | Структурно — дубль логики `lstrip("@")` по всем write-tool'ам `tg_parser/bot/tools.py`; косвенно — `LIKE '%"X"%'`-паттерн в `topic_card_repo` / `topic_bundle_repo` (отдельный технический долг, не root cause); **BUG-007-кандидат** (typo / fuzzy matching по `channel_id` без suggestion'ов) — отдельный UX-баг, маскировал BUG-003 в исходном трассе. |
| **Planned fix** | ✅ landed in **Session F** (read-hardening батч, 2026-04-29) → `docs/notes/START_PROMPT_FIX_READ_HARDENING_BUG003_005B_007_2026-04-29.md` (только tool+prompt; storage-side `LIKE → JSONB ?` deferred per D-5 в TD-storage-jsonb-channel-id) |

#### Symptoms

```
Alex:           Каковы основные темы канала @AgeManagement?
Tg_parser_Bot:  К сожалению, я не нашел никаких тем для канала @AgeManagement.
                Возможно, канал еще не был обработан или в нем нет
                достаточно контента для извлечения тем.
```

При этом тот же самый канал `AgeManagement` через MCP (`list_topics`,
`get_topic_details`) **возвращает темы корректно**. В БД канал процессирован,
`topic_cards` / `topic_bundles` присутствуют — данные на месте.

#### Root cause (проверенный)

**Асимметрия нормализации `channel_id` между write- и read-tool'ами бота.**

1. `add_channel` всегда сохраняет канал в каноническую форму **без `@`**:

   ```1409:tg_parser/bot/tools.py
   normalized = str(args["channel_id"]).lstrip("@")
   ```

   Аналогично write-tool'ы `_exec_pause_channel:1246`, `_exec_resume_channel:1320`,
   `_exec_remove_channel:1491`, `_exec_trigger_pipeline:1111` и subscribe-tool'ы
   (`_exec_subscribe_digest:2064`, `_exec_subscribe_watchlist:2311`). В БД,
   соответственно, `sources_json` для topic-card'а содержит `"AgeManagement"`,
   а не `"@AgeManagement"`.

2. **Read-tool'ы передают `channel_id` в репозиторий «как есть»**, без нормализации:

   ```854:876:tg_parser/bot/tools.py
   async def _exec_list_topics(
       args: dict[str, Any],
       current_user: CurrentUser | None = None,
   ) -> dict[str, Any]:
       from tg_parser.auth.resolvers import get_default_admin
       from tg_parser.services.db_context import processing_repos

       user = current_user or await get_default_admin()
       channel_id = args.get("channel_id")
       …
       async with processing_repos() as (proc_repo, topic_card_repo, topic_bundle_repo, _db):
           if channel_id:
               cards = await topic_card_repo.list_by_channel(channel_id)
               bundles = await topic_bundle_repo.list_by_channel(channel_id)
   ```

   Та же картина — без `lstrip("@")` — в `_exec_ask_question:802`,
   `_exec_search:827`, `_exec_get_cross_channel_stats:1038`.

3. Storage-слой строит SQL-pattern буквально по полученной строке:

   ```130:143:tg_parser/storage/sqlalchemy/topic_card_repo.py
       async def list_by_channel(self, channel_id: str) -> list[TopicCard]:
           """Получить все topic cards канала."""
           query = text(
               f"SELECT {_TC_SELECT_COLUMNS} FROM topic_cards "
               "WHERE sources_json LIKE :channel_pattern "
               "ORDER BY updated_at DESC"
           )

           channel_pattern = f'%"{channel_id}"%'
   ```

   То же `LIKE '%"{channel_id}"%'` в `topic_bundle_repo.list_by_channel:148–166`.
   Если `channel_id == "@AgeManagement"`, паттерн становится
   `%"@AgeManagement"%` и **никогда не матчится** с `"AgeManagement"` в JSON.
   Результат — `[]`, и бот честно сообщает «тем не нашёл».

4. Системный промпт (`prompts/bot.yaml`) **ничего не говорит** про нормализацию
   `channel_id`. Gemini-2.5-flash при запросе «темы канала @AgeManagement»
   буквально проксирует пользовательский ввод в tool-call:
   `list_topics(channel_id="@AgeManagement")`.

##### Почему через MCP это работает

В `tg_parser/mcp_server.py:752–786` лежит **тот же самый код** без
`lstrip("@")`:

```775:780:tg_parser/mcp_server.py
    user = await resolve_mcp_user(ctx.client_id if ctx else None)

    async with processing_repos() as (proc_repo, topic_card_repo, topic_bundle_repo, _db):
        if channel_id:
            cards = await topic_card_repo.list_by_channel(channel_id)
            bundles = await topic_bundle_repo.list_by_channel(channel_id)
```

Баг **есть и тут — латентно**. Не срабатывает только потому, что Claude как
MCP-клиент дисциплинированно отправляет канонический `channel_id="AgeManagement"`
без `@`. Любой клиент / любой LLM, который проксирует пользовательский ввод
буквально (как Gemini-2.5-flash в боте), наступит на эту мину и в MCP.

##### Где ещё латентно та же проблема

Read-tool'ы, не делающие `lstrip("@")`:

| Tool | Bot (`tg_parser/bot/tools.py`) | MCP (`tg_parser/mcp_server.py`) |
|---|---|---|
| `list_topics` | `_exec_list_topics:854` ❌ | `list_topics:752` ❌ |
| `ask_question` | `_exec_ask_question:802` ❌ | `ask_question` ❌ |
| `search_knowledge_base` / `search` | `_exec_search:827` ❌ | `search_knowledge_base` ❌ |
| `get_cross_channel_stats` | `_exec_get_cross_channel_stats:1038` ❌ | `get_cross_channel_stats` ❌ |

Write-tool'ы и subscribe-tool'ы (`add_channel`, `pause_channel`, `resume_channel`,
`remove_channel`, `trigger_pipeline`, `subscribe_digest`, `subscribe_watchlist`) —
все делают `lstrip("@")` (см. строки 1057, 1111, 1246, 1320, 1409, 1491, 1884,
2064, 2311 в `tg_parser/bot/tools.py`). В этом и видна асимметрия: один и тот же
контракт реализован в одних tool'ах и пропущен в других.

##### Почему гипотезы-альтернативы отметены

| H | Описание | Вердикт |
|---|---|---|
| H1 | Канал `AgeManagement` не процессирован / ingestion broken | Через MCP `list_topics(channel_id="AgeManagement")` темы возвращаются — данные в БД консистентны. |
| H2 | RBAC: у пользователя нет доступа к каналу | `list_topics` для admin'а с `allowed_channel_ids=None` отдал бы все карточки канала; кроме того, ошибка была бы другой — `error: "No access"`, а не пустой `items=[]`. |
| H3 | Capitalization mismatch (`agemanagement` vs `AgeManagement`) | Через MCP именно `AgeManagement` (CamelCase) работает, и Gemini-бот в Symptoms тоже передал `@AgeManagement`. Регистр одинаковый, проблема — префикс `@`. |
| H4 | LIKE-pattern глючит (например, на каналах вида «ai») | Это отдельный технический долг (см. ниже), но не root cause: при правильной форме `channel_id="AgeManagement"` тот же `LIKE` отрабатывает. |
| H5 | Bot-side кэш topic'ов | Кэша topic'ов на стороне бота нет; `_exec_list_topics` каждый раз идёт в `processing_repos()`. |

#### Why CI didn't catch

- Тесты, дёргающие `_exec_list_topics` / MCP `list_topics`, всегда передают
  каноническую форму (`channel_id="test_channel"`, `"channel_a"` и т.п.).
  Сценария «пользователь / LLM передаёт `@X`» в тестах нет.
- Нет conformance / property-теста, который бы прогонял **все** tool'ы,
  принимающие `channel_id`, через одинаковый набор форм (`"X"`, `"@X"`,
  с пробелами, разный регистр) и проверял эквивалентность результата.
- Нет end-to-end теста бота с реальным форматом пользовательских сообщений
  («@AgeManagement» в естественном русскоязычном вопросе) и mock-Gemini,
  буквально проксирующим аргументы. Без такого теста асимметрия write/read
  легко проходит ревью.

#### Proposed fix

**Минимум (фикс блокера, ≤30 строк):**

1. Добавить `lstrip("@")` в read-tool'ы `tg_parser/bot/tools.py`:
   `_exec_ask_question`, `_exec_search`, `_exec_list_topics`,
   `_exec_get_cross_channel_stats` (и при последующем аудите — везде, где
   на вход приходит `channel_id`). Шаблон тот же, что уже используется в
   write-tool'ах:

   ```python
   raw_channel_id = args.get("channel_id")
   channel_id = str(raw_channel_id).lstrip("@") if raw_channel_id else None
   ```

2. Симметрично — в `tg_parser/mcp_server.py` (`list_topics`,
   `search_knowledge_base`, `ask_question`, `get_cross_channel_stats`).
   Latent-баг закрывается тем же изменением.

**Hardening (один или два дополнительных коммита):**

3. **Вынести нормализацию в helper и использовать его везде** — единый
   источник истины. Например, в `tg_parser/services/channel_service.py`
   (или `tg_parser/auth/ownership.py`):

   ```python
   def canonical_channel_id(value: str | None) -> str | None:
       """Canonical form of channel_id used as DB key.
       Strips '@' and surrounding whitespace; keeps case as-is."""
       if value is None:
           return None
       return str(value).strip().lstrip("@") or None
   ```

   Заменить все `str(args["channel_id"]).lstrip("@")` (≈10 мест в bot/tools.py
   + ≈столько же в mcp_server.py) на `canonical_channel_id(...)`. Это убирает
   риск пропустить очередной tool при будущем добавлении.

4. **Tool decl JSON-schema description** для `channel_id`-параметров: уточнить
   ожидаемый формат в `prompts/bot.yaml` или прямо в tool descriptions
   (`tg_parser/bot/tools.py:78–139`). Например: «Pass without leading `@`
   (e.g. `AgeManagement`, not `@AgeManagement`). The tool also accepts the
   prefixed form for convenience.» — комбинация явного контракта в схеме
   + нормализации даёт defense-in-depth.

5. **Conformance-тест** — pytest-параметризация по всем tool'ам, принимающим
   `channel_id`: для одного и того же канала проверить, что `"X"`, `"@X"`,
   `" @X "` дают идентичный результат. Один тест ловит весь класс багов.

6. **Структурный долг** (Low-priority, отдельный bug, не часть этого фикса):
   `LIKE '%"{channel_id}"%'` в `topic_card_repo.list_by_channel:130` /
   `topic_bundle_repo.list_by_channel:148` — фрагильный матч. Канал `"ai"`
   подматчит карточки `"openai"`, `"kaiclub"` и т.п. через JSON-substring.
   Долгосрочно — заменить на `jsonb_path_exists` / `?` оператор или хранить
   `sources` как нормализованную таблицу. Не root cause BUG-003, но в одной
   зоне ответственности.

#### Workaround (на время до фикса)

Спрашивать без `@`:

> Каковы основные темы канала AgeManagement?
> Найди в канале AgeManagement посты про ...
> Что говорят в AgeManagement про ...

Тогда Gemini передаст в `list_topics` каноническую форму и SQL-pattern совпадёт.
Также можно дёрнуть тот же канал через MCP-клиент (Claude / curl) — там запрос
работает за счёт дисциплины клиента.

#### Artifacts

- Read-tool'ы без нормализации:
  `tg_parser/bot/tools.py:802` (ask_question), `:827` (search),
  `:854` (list_topics), `:1038` (get_cross_channel_stats).
- Write-tool'ы с нормализацией (для контраста):
  `tg_parser/bot/tools.py:1111, 1246, 1320, 1409, 1491` + helper'ы `:1057, 2064, 2311`.
- Storage-слой (LIKE-pattern):
  `tg_parser/storage/sqlalchemy/topic_card_repo.py:130–143`,
  `tg_parser/storage/sqlalchemy/topic_bundle_repo.py:148–166`.
- Latent-копия в MCP: `tg_parser/mcp_server.py:752–786`.
- Системный промпт без указаний по нормализации: `prompts/bot.yaml:30–43`.
- Триггер-канал: `AgeManagement` (через MCP темы видны, через бота — нет).

#### Update 2026-04-26 23:28 — кажущееся подтверждение асимметрии `@` (позже опровергнуто)

В контрольном трассе (BUG-004 reproduction после пополнения Anthropic
billing) пользователь спросил про темы канала `Lab4health` **без `@`**:

```
Alex: <запрос на список тем канала Lab4health>
Bot:  *   Воспалительные процессы… (54 документа)
      *   Интерактивные опросы… (11 документов)
      …
      Всего найдено 165 тем. Показаны первые 20.
```

На тот момент сравнивалось с трассом 21:39:07 c `@AgeManagement`,
который вернул 0 тем. Я тогда заключил, что это «финальное
подтверждение» `@`-асимметрии. **Это заключение оказалось преждевременным
— см. следующий update.**

#### Update 2026-04-26 23:35 — контр-открытие: BUG-003 НЕ подтверждён в проде (typo-confound)

Пользователь прогнал чистую дисамбигуацию:

```
Alex: перечисли основные темы канала AgeManagement     [23:35:06]
Bot:  Я не нашел никаких тем для канала "AgeManagement"… [23:35:08]

Alex: перечисли основные темы канала @AgeManagement    [23:35:19]
Bot:  Я не нашел никаких тем для канала @AgeManagement…[23:35:21]
```

**Оба варианта вернули 0 тем.** Это означает: дискриминатор симптома —
**не `@`-prefix**, а что-то другое.

Verifying через MCP:

```
list_channels() → "channel_id": "AgeManagment", "topics_count": 75
list_topics(channel_id="AgeManagement")  → total: 0
list_topics(channel_id="@AgeManagement") → total: 0
```

**Канал в БД называется `AgeManagment`** (без буквы `e` между `Manag`
и `ment`), а пользователь во всех трассах набирал `AgeManagement`
(грамматически правильное английское). LIKE-pattern не матчит две
разные строки → корректные 0 тем для несуществующего ID. **MCP
поведение идентично боту** — никакой асимметрии нет.

###### Что это означает для BUG-003

| Утверждение | Статус |
|---|---|
| Read-tool'ы (`_exec_list_topics`, `_exec_search`, `_exec_ask_question`, `_exec_get_cross_channel_stats`) **в коде не делают** `lstrip('@')` | ✅ Сохраняется как латентный код-баг (см. § Root cause) |
| `LIKE '%"@X"%'` не матчит запись `["X"]` в БД | ✅ Сохраняется как теоретически корректный механизм |
| Симптом 21:39:07 (`@AgeManagement` → 0 тем) **подтверждает** этот баг в проде | ❌ **Опровергнуто.** Симптом был продуктом **typo в имени канала**, а не `@`-prefix'а. Один лишь typo (`AgeManagement` ≠ `AgeManagment`) даёт 0 тем независимо от наличия `@`. |
| Workaround «спрашивать без `@`» доказанно работает в проде | ⚠️ Не подтверждён: оба корректных трасса (Lab4health-без-@ и LongevityClub-без-@ через ask_question) использовали корректное имя канала, поэтому работа без `@` объясняется и `@`-теорией, и просто корректным именем. |

###### Что нужно для чистого подтверждения / опровержения BUG-003

Прогон в боте на **заведомо корректном** имени канала:

```
1. перечисли темы канала Lab4health    (без @, ожидание: 20 тем)
2. перечисли темы канала @Lab4health   (с @,  ожидание: ?)
```

Если (1) → 20, а (2) → 0 — BUG-003 в проде подтверждён в чистой форме.
Если оба → 20 — BUG-003 либо отсутствует в проде, либо где-то по
дороге между Gemini и DB всё же есть `@`-стрип, который я не нашёл при
code-walk'е. **До этого прогона BUG-003 фактически не подтверждён.**

###### Status update

- **BUG-003 как латентный код-баг**: `open` (теоретически возможен,
  read-tools без `lstrip('@')` — факт).
- **BUG-003 как воспроизводимый pro-симптом**: **`unconfirmed`** до
  чистого прогона.
- **BUG-003 severity**: следует **понизить с Medium на Low** до тех пор,
  пока не получено воспроизводимое доказательство.
- **Триггер-канал «AgeManagement»**: больше не валидный триггер для
  BUG-003 — он триггерит **другой** баг (typo / fuzzy matching).

###### Кросс-баг наблюдение → кандидат BUG-007

В БД хранится канал `AgeManagment` (вероятно typo при добавлении или
реальное имя канала в Telegram с typo). Пользователь набирает
`AgeManagement` (грамматически правильно) — tool молча отдаёт 0 без
подсказки «вы имели в виду `AgeManagment`?». Это **отдельный UX-баг**:
read-tool'ы не делают fuzzy matching по `channel_id` и не отдают
suggestion'ы при `total: 0`. Кандидат-фикс для BUG-007 (см. отдельную
секцию ниже, если будет).

#### Update 2026-04-26 23:39 — детерминированное подтверждение через MCP + LLM-маскировка в боте

Контр-открытие 23:35 заставило перепроверить всё с чистого листа.
Проведены два решающих теста:

###### Тест 1 — bot на корректном имени канала с/без `@`

```
Alex: перечисли темы канала Lab4health     → Bot: 20 тем
Alex: перечисли темы канала @Lab4health    → Bot: 20 тем
```

В боте **обе формы** работают одинаково. Это **отрицает** BUG-003 на
бот-уровне.

###### Тест 2 — прямой MCP-вызов с `@` и без

```
list_topics(channel_id="Lab4health")   → total: 165 ✓
list_topics(channel_id="@Lab4health")  → total: 0   ✗
```

В прямом MCP-вызове **`@`-форма стабильно ломается**. Это **подтверждает**
BUG-003 на storage/tool-уровне детерминированно.

###### Что это означает (3-layer reality)

| Слой | Поведение | Источник доказательства |
|---|---|---|
| **Storage (`topic_card_repo.list_by_channel`)** | `LIKE '%"@X"%'` не матчит `["X"]` в JSONB. Detерминированный fail. | `tg_parser/storage/sqlalchemy/topic_card_repo.py:130–143` + Тест 2. |
| **Tool executor (`_exec_list_topics` и др.)** | **Не делает** `lstrip('@')`. Передаёт `channel_id` as-is в storage. | `tg_parser/bot/tools.py:854–906` (нет `.lstrip('@')` ни в одном из read-`_exec_*`). |
| **LLM-агент (Gemini в боте)** | Стрипает `@` сам перед формированием tool-call'а. Implicit-знание Telegram-конвенции. | Тест 1 (bot работает в обоих формах) + `prompts/bot.yaml` (нет explicit-инструкции). |

**Финальная диагностическая картина:**
- Код-баг в коде **есть** (storage + tool executor).
- В **MCP-канале** (curl, автоматизация, тесты, не-Gemini-клиенты) баг
  воспроизводится **детерминированно**.
- В **Telegram-боте** баг **маскируется** Gemini-агентом, который имеет
  тренировочное знание про Telegram-handle-конвенцию и стрипает `@` сам.

###### Хрупкость LLM-маскировки

Это не «settled state», а уязвимая защита, которая может откатиться
при следующих изменениях:

1. **Смена модели бота** через `BOT_GEMINI_MODEL` (например, на
   `gemini-1.5-pro`, `gemini-2.5-pro` или, если мы добавим, на не-Gemini).
   Другая модель может не нормализовать `@` так же надёжно. **Это
   реальный риск** — мы уже обсуждали смену модели для лечения BUG-006.
2. **Изменение tool-deklaraций (`tg_parser/bot/tools.py:43+`)**, которые
   могут изменить LLM-понимание `channel_id`-параметра.
3. **Изменения в `prompts/bot.yaml`**, которые «учат» LLM передавать
   значения as-is.
4. **Future LLM-провайдеры** для бота (если когда-нибудь захотим
   abstract over OpenAI / Anthropic / etc. для бота, не только для RAG)
   — каждый из них имеет своё implicit-поведение для `@`-prefix.

Любое из этих изменений может **внезапно** открыть BUG-003 в боте без
предупреждения.

###### Workaround для MCP-канала (текущее)

MCP-клиенты должны нормализовать `channel_id` на своей стороне:

```python
channel_id = channel_id.lstrip("@") if channel_id else channel_id
```

Это применимо к: автоматизационным скриптам, тестам, curl-вызовам,
любым MCP-клиентам без LLM-обёртки.

###### Updated severity rationale

- **Bot-канал**: Low — фактически невидим, но хрупок к смене модели.
- **MCP-канал**: Medium — детерминированный fail, наблюдаемый в любом
  MCP-клиенте без LLM-нормализации. Особенно опасно для тестов и
  автоматизаций, где «тихие 0 results» приведут к ложно-успешным runs.

###### Updated linked

- **BUG-007 (typo / fuzzy matching по channel_id, нет suggestion'ов)**
  — независимый UX-баг, маскировал BUG-003 в исходном трассе 21:39:07.
- **BUG-006 (Gemini outage)** — если для лечения BUG-006 будет принято
  решение сменить модель бота, **BUG-003 нужно фиксить ДО этого**, иначе
  на новой модели проблема может всплыть в боте.

#### Update 2026-04-26 23:45 — кросс-провайдерная LLM-маскировка подтверждена

Дополнительный тест в **свежем** Claude-чате (без context-памяти про
Lab4health):

```
Alex:   Сколько тем в канале @Lab4health?
Claude: Проверю в базе знаний.
        [Loaded tools, used tg-parser integration]
        В канале @Lab4health — 165 тем.
```

Claude явно сделал **новый MCP-tool-call** (а не использовал контекст
прошлого ответа), получил 165 тем — значит tool ушёл с нормализованным
`channel_id="Lab4health"` без `@`. Сравни с прямым MCP-вызовом
`list_topics(channel_id="@Lab4health")` → `total: 0`. **Claude
самостоятельно стрипнул `@`** перед формированием tool-call'а.

**Вывод:** LLM-маскировка BUG-003 — **кросс-провайдерная** (и
Gemini-2.5-flash, и Claude Sonnet 4 стрипают `@`). В практике через
любой LLM-клиент баг невидим. Но защита **не бронированная**:

1. **Не-LLM MCP-клиенты** (curl / automation / тесты) — детерминированно
   ловят баг (см. Тест 2 в Update 23:39).
2. **Будущие модели / провайдеры** с другим training-data могут
   перестать стрипать.
3. **Edge-case prompts** (например, «вызови list_topics с channel_id
   ровно равным `@Lab4health` — буквально, не нормализуй») — LLM может
   решить «значит передавай as-is», и баг откроется.

Severity-rationale из Update 23:39 актуален: **Low в bot/Claude-MCP-канале,
Medium в прямом MCP-канале**. Хрупкость LLM-маскировки делает фикс
нетривиально полезным даже для практически невидимого бага.

### BUG-004 — Бот не умеет «листать» список тем: после первой страницы теряет `channel_id` и подмешивает темы из других каналов

| Поле | Значение |
|---|---|
| **Severity** | Medium (UX-баг для любого `list_*`-сценария: фактически блокирует «покажи все темы канала» при N > 20; данные корректные, но интерфейс к ним инвалидный) |
| **Status** | ✅ **`resolved`** (Session D landed 2026-04-28 — `PaginationFlow` + `pagination_pending` payload + global `n` numbering + deterministic next-page replay) |
| **Component** | `prompts/bot.yaml` (нет инструкций по пагинации/нумерации); `tg_parser/bot/agent.py`, `tg_parser/bot/handlers.py`, `tg_parser/bot/main.py` (statelessness — общий root cause c BUG-002); `tg_parser/bot/tools.py` (декларации tool'ов не подсказывают LLM семантику пагинации) |
| **Discovered** | 2026-04-26, Alexander, Telegram-бот в проде |
| **Linked** | **BUG-002** (общая первопричина — отсутствие conversation memory). Канал-фильтр для `list_topics` дополнительно ломает BUG-003 (`@`-нормализация); если фикс BUG-003 опередит, он же чистит первый turn здесь. |
| **Planned fix** | **Session D** (вместе с BUG-002 full FSM, 2026-04-28) → `docs/notes/START_PROMPT_FIX_BUG002_BUG004_BOT_FSM_2026-04-28.md` (paginates piggybacks на FSM scaffolding) |
| **Update 2026-04-28 (15:50) — Session D landed → BUG-004 RESOLVED** | ✅ **Root cause закрыт architecturally.** Вместе с BUG-002 в одном PR. `tg_parser/bot/tools.py:_exec_list_topics` штампует каждый item глобальным 1-based `n` (`offset + idx + 1`) и при `has_more=True` возвращает `pagination_pending = {tool_name, args, total, offset, limit}` где `args` сохраняет channel/topic_type фильтр **без изменений** и advanced offset. `tg_parser/bot/handlers.py:_handle_pagination_response` детерминированно replay'ит stashed query на `NEXT_PAGE_PATTERN` («ещё/далее/next/more/продолжай» — anchored regex) — channel context structurally сохраняется. На «стоп» — clear, на non-match — D-4 default, на terminal page — clear, soft-cap warning после 10 cumulative items (D-6, state preserved). `prompts/bot.yaml` v1.1.0 секция «Pagination and numbering» инструктирует LLM использовать `n` (никогда не restart at 1) и не делать самостоятельный list_topics на следующем turn'е. Tests: 29 pagination-тестов в `tests/test_bot_fsm.py` (Test*PaginationPattern, *ListTopicsPagination, *FormatPaginatedList, *PaginationFlowHandler, *HandleTextSetsPaginationFlow), включая регрессию global numbering n=11..20 на page 2 и channel_id intact across pages. Полный pytest: 1863 passed. |

#### Symptoms

```
Alex: перечисли все темы канала @AgeManagement
Bot:  • <тема 1>
      • <тема 2>
      …
      • <тема 20>
Alex: остальные?
Bot:  • <тема из канала X>
      • <тема из канала Y>
      …  (20 случайных «свежих» тем по всем каналам пользователя)
```

То есть:
1. Первая страница частично корректная (если канал передан без `@`).
2. Пользователю не сообщается, что есть `total`, что показано `1–20 из N`,
   и что для продолжения нужно явно спросить.
3. Список без нумерации — ссылаться «дай мне детали по 7-й» неудобно.
4. На «остальные / ещё / следующие» бот теряет контекст канала и
   возвращает «20 свежих тем по всему KB» — формально это валидный
   результат `list_topics()` без фильтра, но пользователь ждёт совсем
   другого.

#### Root cause (проверенный)

Композитная проблема. Три независимых слоя, все вкладываются в
наблюдаемый симптом, и фиксить нужно как минимум два из трёх.

##### 1. Statelessness между turn'ами (наследуется от BUG-002)

`tg_parser/bot/agent.py:70–72` пересоздаёт `contents` с нуля на каждом
вызове `process_message`, FSM в `Dispatcher()` не подключён
(`tg_parser/bot/main.py:161`). Когда в Turn 2 пользователь пишет
«остальные», Gemini получает только `[{"role":"user","parts":[{"text":"остальные"}]}]`
+ system-prompt. Канал-фильтр и `offset` из Turn 1 потеряны.

System-prompt (`prompts/bot.yaml:31`) обязывает использовать tool'ы для
любого ответа. Модель вынужденно вызывает что-то релевантное на голом
контексте — обычно `list_topics()` без аргументов. Tool возвращает первые
20 строк из `topic_card_repo.list_all()` (или `list_by_channels(allowed_channel_ids)`
для не-admin'а) — отсортированные по `updated_at DESC`. С точки зрения
`list_topics` это легитимный ответ, но это «свежие темы по всему KB», а
не продолжение списка `AgeManagement`.

##### 2. Tool возвращает достаточно данных для пагинации, но prompt не учит ими пользоваться

`_exec_list_topics` уже возвращает всё нужное:

```900:906:tg_parser/bot/tools.py
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < total,
        "items": items,
    }
```

И декларация tool'а описывает `offset` / `limit` (`tg_parser/bot/tools.py:111–119`):

```111:119:tg_parser/bot/tools.py
                "offset": {
                    "type": "INTEGER",
                    "description": "Number of topics to skip (for pagination, default 0)",
                },
                "limit": {
                    "type": "INTEGER",
                    "description": "Maximum topics to return (default 20)",
                },
```

Но в `prompts/bot.yaml` (System prompt) отсутствуют:

- инструкция «при `has_more=true` сообщи пользователю `Показано N–M из TOTAL` и
  предложи продолжить»;
- инструкция «при следующем запросе на продолжение вызывай **тот же** tool с
  `offset += limit` и сохрани все остальные args (особенно `channel_id`)»;
- инструкция «нумеруй элементы списков с `1.`, чтобы пользователь мог
  ссылаться по номеру».

Раздел Instructions (`prompts/bot.yaml:30–43`) ничего про пагинацию не
говорит — есть только общее «Structure your responses clearly… use bullet
points». Поэтому Gemini-2.5-flash:

- агрегирует только `items`, выкидывает `total/has_more/offset/limit`;
- использует bullet'ы (`•`), а не нумерованный список;
- не предлагает пользователю command continuation.

##### 3. Tool decl без cross-call payload (косметический усилитель)

Декларация `list_topics` не намекает модели, что `channel_id` нужно
сохранять между вызовами. Описание `channel_id` (`tg_parser/bot/tools.py:103–106`)
тоже минимальное:

```103:106:tg_parser/bot/tools.py
                "channel_id": {
                    "type": "STRING",
                    "description": "Optional channel filter",
                },
```

Без явного hint'а вроде «If a previous call filtered by `channel_id`,
the same value MUST be reused for follow-up pagination calls» Gemini
не понимает, что следующая страница — это тот же запрос. Сам по себе
этот пробел не root cause (его починил бы system-prompt), но
дублирующая подсказка в schema — defense-in-depth для других tool'ов
с пагинацией (`list_channels`, `list_topics`, `search`, future).

##### Вклад каждой причины (перекрытие)

| Слой | Влияет на Turn 1 | Влияет на Turn 2 | Без него баг был бы… |
|---|---|---|---|
| Statelessness (BUG-002) | нет | да | …без подмены channel_id, но без «следующих 20» вообще |
| System prompt (нет инструкций пагинации) | да | да | …просто без нумерации и без хедера «1–20 из N» |
| Tool decl (нет hint'а cross-call) | косвенно | косвенно | …устранён, если system prompt полный |

##### Telegram-инфраструктура работает корректно (не root cause)

`tg_parser/bot/handlers.py:166–177` уже разбивает длинные ответы через
`split_message` (`tg_parser/bot/formatter.py:21`, лимит 4096). То есть
многосообщенческая выдача *в рамках одного turn'а* поддержана без
изменений в коде — достаточно, чтобы LLM сформировала длинный ответ
с нумерацией, и `split_message` сама раскидает его на 2–3 message'а.
Эту часть фиксить не нужно.

##### Почему гипотезы-альтернативы отметены

| H | Описание | Вердикт |
|---|---|---|
| H1 | `list_topics` физически отдаёт только 20 — остальные «потеряны» | Нет: `total` и `has_more` корректные, `offset` параметризован. |
| H2 | RBAC режет результаты | Для admin'а `allowed_channel_ids=None`, `list_all()` возвращает все темы; страдает только сортировка/фильтр. |
| H3 | Telegram режет сообщение | `split_message` уже есть, бот шлёт несколько chunks подряд. |
| H4 | Gemini-2.5-flash не умеет в `offset` физически | Умеет, если попросить промптом. Текущее поведение — отсутствие hint'а, а не модели. |
| H5 | LLM игнорирует `has_more` потому что не видит | Видит — поле в JSON-результате tool'а. Не использует, потому что system prompt не говорит «использовать». |

#### Why CI didn't catch

- Нет ни одного теста, прокатывающего «list-then-paginate» сценарий через
  `agent.process_message`: turn 1 → `list_topics(channel_id="X")` с
  `total>limit`; turn 2 «ещё» → ожидание `list_topics(channel_id="X",
  offset=limit)` с **тем же** `channel_id`. Архитектурный gap — same as
  BUG-002.
- Тесты `_exec_list_topics` (если они есть) не проверяют наличие
  `total/has_more/offset/limit` в ответе — только `items`.
- Нет prompt-конформанс-теста, который скармливает синтетический
  `list_topics`-result с `has_more=true` mocked-Gemini и проверяет,
  что в финальном тексте есть слова про `total` / `показано` /
  «попросите ещё». Без такого теста любая регрессия в `prompts/bot.yaml`
  ломает UX молча.

#### Proposed fix

Три варианта по нарастающей правильности; рекомендация — **B + A** (фактически
обе ветки в одном PR; они дополняют друг друга, а не конкурируют).

**Вариант A — «промпт + tool decl» (минимум, чисто LLM-discipline).**

1. Дополнить `prompts/bot.yaml` (раздел Instructions) тремя пунктами:
   - «When a tool returns `total`, `has_more`, `offset`, `limit` — open the
     reply with `Показано <offset+1>–<offset+len(items)> из <total>:` and
     **always number list items** (`1.`, `2.`, …, continuing across pages).»
   - «When `has_more` is true — end the reply with «Чтобы увидеть следующие
     <limit> — попросите «ещё» / «next».»
   - «If the user asks for «ещё / next / следующие / больше», reuse the
     **exact same tool args** from the previous call (especially
     `channel_id`, `topic_type`, `query`), bumping `offset` by `limit`.
     Never call `list_*` without a filter just because the user said
     «остальные».»

2. Усилить декларации tool'ов с пагинацией (`list_topics`, `list_channels`,
   `search_knowledge_base`, в будущем `list_users`/`list_digests`):
   - `channel_id.description`: «Channel filter. **MUST be preserved
     unchanged in follow-up pagination calls.**»
   - `offset.description`: «Skip first N items. For follow-up pages: pass
     `previous_offset + previous_limit`.»

   ≈30 строк, эффект мгновенный.
   **Минусы:** держится только на дисциплине Gemini. Без conversation
   memory модель в Turn 2 всё равно не знает, что было `previous_offset` и
   `channel_id`. То есть A в одиночку чинит **первый** turn (правильное
   оформление, нумерация, hint про «ещё»), но **не** второй.

**Вариант B — «FSM pagination state» (правильно, синхронно с фиксом BUG-002).**

Использовать тот же FSM-механизм, что предложен для BUG-002 (вариант B).
Завести state `Pagination.in_progress` и контекст `last_listing = {tool,
args, offset, limit, total, returned_count, channel_id}`. После каждого
read-tool'а с `has_more=true` handler сохраняет это в FSM. На следующем
сообщении в этом state'е:

- **regex-match «ещё / next / следующие / more / далее / +N»** → handler
  **сам** зовёт тот же `_exec_<tool>` с `offset += limit`, не дёргая
  Gemini для аргументов. Gemini остаётся только для финального
  text-форматирования (или вообще можно построить ответ детерминированно
  через шаблон — быстрее и без рисков hallucination).
- **regex-match «отмена / стоп / новый запрос» или просто новый смысловой
  вопрос** → state чистится, сообщение идёт через агента как обычно.
- **«дай детали по 7-й»** → handler знает `last_listing.items[6].id`,
  зовёт `get_topic_details` детерминированно. Это бонус нумерации,
  стоит добавить в этот же fix.

≈150 строк, требует тех же изменений в `Dispatcher` (storage), что
для BUG-002. **Минус:** лишний слой между LLM и tool'ом — нужно
аккуратно пробросить `bot`/`chat_id` для tool'ов с side-effects.

**Вариант C — гибрид (in-memory cache).**

Per-chat dict `last_listing` в памяти процесса (как Вариант A в BUG-002),
TTL 10 минут. Без FSM/Redis. Дёшево, но не переживает рестарт пода и не
multi-replica safe. Подходит как промежуточный шаг.

**Hardening (для всех вариантов):**

1. **Tool result schema audit**. Все `list_*`-tool'ы (bot+MCP) должны
   единообразно возвращать `{total, offset, limit, has_more, items}`.
   Сейчас:
   - `_exec_list_topics` (`tg_parser/bot/tools.py:900–906`) — ✅ есть.
   - `_exec_search` (`tg_parser/bot/tools.py:841–851`) — ❌ возвращает
     только `{results, count}`. Без `total/has_more` LLM физически не
     может предложить пагинацию.
   - `_exec_list_channels` (`tg_parser/bot/tools.py:960–982`) — нужно
     проверить отдельно, в этом баге не был root cause.
   - `_exec_list_users`, `_exec_list_digests`, `_exec_list_watchlists` —
     аналогично.
2. **Prompt-conformance test.** Скармливать mock'у Gemini синтетический
   `list_topics` result с `total=42, has_more=True, items=[...]` и
   проверять, что в финальном пользовательском тексте присутствуют:
   нумерация (`1.` … `20.`), header `Показано 1–20 из 42`, hint про
   «попросите ещё». Регресс ловится мгновенно.
3. **Two-turn pagination integration test** (после фикса B). Mock Gemini:
   turn 1 «темы канала X» → `list_topics(channel_id="X", offset=0)`,
   turn 2 «ещё» → handler вызывает `list_topics(channel_id="X",
   offset=20)` без обращения к LLM (или, для варианта A, проверяет, что
   LLM сама сформировала такой call). Покрытие — общее с тестом BUG-002.
4. **Логирование `list-tool` args на INFO** (опять-таки общее с BUG-002).
   Без этого диагностика «почему вторая страница содержит мусор» опирается
   только на user-facing-текст.

**Рекомендация:** **B + A в одном PR**, в той же fix-сессии, что закрывает
BUG-002 (общий FSM-storage, общий integration-test setup). Hardening 1
делать сразу — это отдельный коммит на 30 строк, который мгновенно
улучшает любой `list_*`-tool без дополнительных изменений в LLM-логике.

#### Workaround (на время до фикса)

1. Спрашивать с явным указанием диапазона и канала:
   > «покажи темы канала AgeManagement с 21-й по 40-ю»
   > «list_topics channel_id=AgeManagement offset=20 limit=20»

   Gemini обычно корректно мапит это на `list_topics(channel_id="AgeManagement",
   offset=20, limit=20)` в одном turn'е.

2. Запрашивать с большим лимитом сразу:
   > «покажи 50 тем канала AgeManagement»

   Tool отдаёт `limit=50` items, `split_message` раскидает по нескольким
   сообщениям автоматически.

3. Альтернатива через MCP (Claude / curl) — там пагинация работает за
   счёт дисциплины клиента и истории переписки на стороне клиента.

#### Artifacts

- Tool result со всеми нужными полями: `tg_parser/bot/tools.py:854–906`
  (read-side в `mcp_server.py:752–852` — симметрично).
- Tool decl без hint'ов про пагинацию: `tg_parser/bot/tools.py:94–122`
  (raw schema), `tg_parser/bot/tools.py:103–119` (`channel_id` / `offset`
  descriptions).
- Statelessness root cause: `tg_parser/bot/agent.py:70–72`,
  `tg_parser/bot/handlers.py:144–149`, `tg_parser/bot/main.py:161`.
- System prompt без правил пагинации/нумерации: `prompts/bot.yaml:30–43`
  (раздел Instructions).
- Telegram-доставка длинных ответов уже работает:
  `tg_parser/bot/handlers.py:166–177` + `tg_parser/bot/formatter.py:21–64`.
- Конкретный канал-триггер: `AgeManagement`, `total > 20`.

#### Update 2026-04-26 23:28 — clean reproduction после пополнения Anthropic billing

Чистое воспроизведение, контрольная проверка после фикса BUG-005-A через
пополнение billing (Anthropic):

```
Alex: <запрос на список тем канала Lab4health>
Bot:  *   Воспалительные процессы… (54 документа)
      *   Интерактивные опросы… (11 документов)
      …
      *   Опросы и интерактивное взаимодействие… (103 документа)

      Всего найдено 165 тем. Показаны первые 20.

Alex: ещё
Bot:  Пожалуйста, уточните, что именно вас интересует. Я могу:
      *   Отвечать на вопросы по содержимому каналов.
      *   Искать информацию в каналах.
      *   Показывать список тем из каналов.
      *   Предоставлять статистику по каналам.
      …
      Что бы вы хотели сделать?
```

Несколько важных подтверждений:

1. **`list_topics(channel_id='Lab4health')` корректно отдаёт пагинационные
   метаданные** (`165 / 20 / first 20`) — bot их **показывает** в footer'е.
   Значит композитный root cause (1) **statelessness** + (2) **prompt без
   pagination-инструкций** воспроизводится точно.
2. На `ещё` Gemini не видит контекста предыдущего turn'а (statelessness,
   BUG-002), но и **не делает** `list_topics(...)` без аргументов
   (предыдущая описанная вариация). На этот раз Gemini уехала в
   **discovery-fallback** — выдала пользователю общее меню возможностей
   («Пожалуйста, уточните…»). Это **новая вариация поведения**: на голом
   `«ещё»` LLM может либо галлюцинировать tool-call, либо отказаться
   выбирать tool и показать meta-help. Какой именно путь — стохастика.
3. **BUG-003 побочное наблюдение, асимметрия `@`-prefix (позже опровергнуто):**
   - Канал `Lab4health` (без `@`) → `list_topics` отдал 20 тем ✓.
   - Канал `@AgeManagement` (с `@`) — трасс 21:39:07 — отдал 0 тем ✗.

   На тот момент это казалось чистым подтверждением BUG-003. **Update
   23:35 показал: канал в БД хранится как `AgeManagment` (с typo, без `e`
   между Manag и ment), а пользователь набирал `AgeManagement`** — итого
   симптом был продуктом несовпадения имени, а не `@`-prefix'а. И с `@`,
   и без `@` для написания `AgeManagement` MCP/bot отдают 0 тем. См.
   развёрнутый разбор в **BUG-003 § Update 2026-04-26 23:35**.

Вывод по этому трассу: **billing-фикс BUG-005-A никак не повлиял на
BUG-004** (что и предсказывалось, так как pagination-цепочка не вызывает
LLM-провайдера за пределами bot-Gemini). Это контрольное свидетельство,
что мы не закрыли BUG-004 случайно вместе с BUG-005.

### BUG-005 — `ask_question` падает с generic «internal error», Gemini парафразит мягкий текст без диагностики

| Поле | Значение |
|---|---|
| **Severity** | High (блокирует ключевую RAG Q&A-фичу для конкретного запроса; админ может откатиться на MCP/Claude или `search`-tool, обычный пользователь — нет; root cause без логов не локализуется) |
| **Status** | **BUG-005-A: `resolved` через workaround (Anthropic billing top-up, 2026-04-26 23:32)**; **BUG-005-B: `resolved (Session F, 2026-04-29; deployed 2026-04-30 15:12 UTC, squash SHA 88e4337)`** — `execute_tool` теперь различает `TimeoutError` / `PermissionError` / `ValueError` / `KeyError` / generic `Exception` и preserves `error_class` + truncated `error` message (cap 500 chars) в payload; bot-агент видит специфичный класс и формулирует осмысленный ответ вместо «внутренней ошибки». **Production smoke 2026-04-30**: in-container synthesizing test (`docker exec tg_parser_bot python3 -c '...'`) confirmed `KeyError`/`TimeoutError` payload shape с `error_class` + truncated `error` message. См. § Updates → Session F (2026-04-30) deployed. |
| **Component** | `tg_parser/bot/tools.py` (`_exec_ask_question`, `_call_tool_safe` — generic-catch без таксономии); `tg_parser/services/retrieval_service.py` (`answer`, `search`, `_call_llm`, `_load_rag_config`); `tg_parser/services/embedding_service.py`; конфиг RAG-LLM (`RAG_LLM_PROVIDER` / `RAG_LLM_MODEL` + соответствующие API-ключи); `prompts/rag.yaml` |
| **Discovered** | 2026-04-26, Alexander, Telegram-бот в проде |
| **Linked** | Косвенно: BUG-003 (`@`-нормализация + non-admin → `PermissionDenied` мог стать одним из триггеров для не-admin пользователя); BUG-002 (общая прочность tool-loop'а); общий ad-hoc-uplift у всех `_exec_*`-tool'ов (нет единой error-таксономии) |
| **Planned fix** | **BUG-005-A** (Anthropic credit balance) — resolved 2026-04-26 через billing top-up; ops follow-up — quota-monitoring alarm (out-of-band ops track, no separate prompt). **BUG-005-B** (generic catch в `_call_tool_safe`) — ✅ landed in **Session F** (2026-04-29) → `docs/notes/START_PROMPT_FIX_READ_HARDENING_BUG003_005B_007_2026-04-29.md` |
| **Update 2026-04-26 22:53** | Дополнительный observability-факт от пользователя: **тот же запрос через MCP отрабатывает корректно**. Это сужает hypothesis space — см. ниже § «Update from MCP-cross-check». |
| **Update 2026-04-26 23:00** | MCP `get_llm_config` отдал полный конфиг: **anthropic / claude-sonnet-4-20250514 на всех 4 стадиях, runtime-оверрайдов нет**. Bot-сторону Шага 0-bis **выполнить не удалось** — бот сейчас вообще не отвечает на free-form-запросы (см. **BUG-006**, Gemini agent loop). Это блокирует прямую сверку bot↔MCP, но косвенно ослабляет H1b и усиливает H1 — см. § «Update from get_llm_config + bot Gemini outage». |
| **Update 2026-04-26 23:09** | **Решающий observability-факт: `search` работает, `ask_question` стабильно падает с интервалом ≤4 сек.** Bot Gemini agent loop ожил (BUG-006 транзиентен). Цепочка отметает H8/H1c/H2/H3/H4/H5/H6/H10. Локализация — `_call_llm` (Anthropic SDK call). См. § «Update from search-vs-ask_question split». |
| **Update 2026-04-26 23:13** | Третий неудачный трасс на тему «Фитофотодерматит». **Время отказа стабильно 3–4 сек** на всех попытках. На Anthropic-вызов после декомпозиции остаётся <1 сек — это **gateway-level rejection** (401/402/403/429), а не transient overload (5xx обычно >5 сек). Это смещает root cause: **H1'-семейство (auth / credits / rate-limit)** теперь главный кандидат, обычная H1 (transient 5xx) понижена. См. § «Update from sub-second Anthropic fail-time». |
| **Update 2026-04-26 23:17** | ✅ **ROOT CAUSE FOUND.** Шаг B (MCP `ask_question` тем же запросом) дал детерминированный результат: `Error executing tool ask_question: Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits.` Это **HTTP-402 от Anthropic gateway** — подтверждён **H7c (Anthropic account credits depleted)**. И bot, и MCP падают одинаково потому что упираются в один и тот же billing-аккаунт. Бонус: MCP-сторона корректно пробросила точный текст ошибки, а bot-сторона потеряла в generic catch — значит **BUG-005-B (generic catch) специфичен для bot-`_call_tool_safe`**, а не общая проблема. См. § «Final root cause: H7c confirmed». |
| **Update 2026-04-26 23:20** | После пополнения Anthropic billing **MCP-сторона восстановлена**: A1–A4 (фитофотодерматит / LongevityClub / пролактин-2) дали полноценные RAG-ответы, model `claude-haiku-4-5-20251001`. Любопытная деталь: model в ответе — haiku, а не sonnet, что отличается от 23:00-снимка `get_llm_config` — возможный сброс runtime-override либо рестарт MCP-процесса с другим `.env`-снапшотом. Не критично для unblock'а. |
| **Update 2026-04-26 23:32** | ✅ **BUG-005-A RESOLVED.** A1 (тот же запрос про фитофотодерматит) через **Telegram-бот** прошёл за 19 секунд, выдал содержательный RAG-ответ с тем же source `tg:Lab4health:post:2853`, что и MCP-эталон. Время-bisection (3–4 сек fail vs 19 сек success) подтверждает: упирались именно в gateway-level reject, не в timeout/embedding/DB. Bot-процесс читает **тот же** Anthropic-аккаунт что и MCP-процесс, никакого drift'а — H7b отметается окончательно. См. § «BUG-005-A resolved via billing top-up». |

#### Symptoms

```
Alex:           что в канале LongevityClub говорится о международных
                критериях и классификации возрастных патологий?
Tg_parser_Bot:  Извините, произошла внутренняя ошибка при попытке ответить
                на ваш вопрос с использованием RAG. Пожалуйста, попробуйте
                перефразировать вопрос или воспользуйтесь поиском
                по ключевым словам.
```

Особенности симптома, важные для диагностики:

- Этой строки **нет в коде** — её нет в `tg_parser/`, нет в `prompts/*.yaml`,
  нет в `_FORMATTER` бота. Это сочинение Gemini-2.5-flash поверх tool-result'а.
- Это **не** «не нашлось документов» — для пустого результата `answer()`
  возвращает другую формулировку из `prompts/rag.yaml` (см. ниже Root cause).
- Похожий запрос через MCP/Claude к тому же KB обычно возвращает либо
  полноценный ответ, либо сырой traceback в client-side-output (что и
  делает MCP полезной диагностикой).

#### Root cause (структурный — A + B)

##### A. Технический инцидент (uncertain до получения logs)

`_exec_ask_question` сам ничего не ловит:

```802:824:tg_parser/bot/tools.py
async def _exec_ask_question(
    args: dict[str, Any],
    current_user: CurrentUser | None = None,
) -> dict[str, Any]:
    from tg_parser.auth.resolvers import get_default_admin
    from tg_parser.services.retrieval_service import answer

    user = current_user or await get_default_admin()
    result = await answer(
        question=args["question"],
        channel_id=args.get("channel_id"),
        allowed_channel_ids=user.allowed_channel_ids,
    )
    sources = [
        {
            "source_ref": s.source_ref,
            "score": round(s.score, 4),
            "summary": s.document.summary if s.document else None,
            "channel_id": s.document.channel_id if s.document else None,
        }
        for s in result.sources
    ]
    return {"answer": result.answer, "sources": sources, "model": result.model}
```

Любое исключение из `retrieval_service.answer()` улетает наверх и
ловится generic-обёрткой `_call_tool_safe`:

```792:794:tg_parser/bot/tools.py
    except Exception:
        logger.exception("tool_execution_error", tool=name)
        return {"error": f"Tool '{name}' failed with an internal error"}
```

В лог уходит **полный traceback** (`logger.exception` пишет `exc_info`),
а в LLM приходит безликая строка — ровно из неё Gemini сочинила фразу
про «внутренняя ошибка при попытке ответить на ваш вопрос с использованием
RAG / попробуйте перефразировать / воспользуйтесь поиском по ключевым
словам».

Hypothesis space (упорядочен по эмпирической частотности; финальный
выбор — после чтения `tool_execution_error` event'а):

| H | Слой | Конкретный код | Признак в логе |
|---|---|---|---|
| H1 | RAG-stage LLM (rate-limit / 401 / 5xx / timeout / API-ключ) | `tg_parser/services/retrieval_service.py:439–474` (`_call_llm`) → `llm_client.generate(...)` | `anthropic.RateLimitError` / `openai.APIError` / `httpx.ReadTimeout` / `google.api_core.exceptions.*` в traceback |
| H2 | Embedding-сервис (или его API-ключ) | `tg_parser/services/retrieval_service.py:117–124` (`client.embed([query])`) | `EmbeddingError` / `openai.APIError` / `httpx.ConnectError` |
| H3 | DB / pgvector — connection timeout, race в `asyncio.gather` | `tg_parser/services/retrieval_service.py:126–188`; см. комментарий DI-15 (стр. 127–138) | `IllegalStateChangeError` / `asyncpg.PostgresError` / `sqlalchemy.exc.*` |
| H4 | `PermissionDenied` для non-admin user'а + `channel_id="@LongevityClub"` | `tg_parser/services/retrieval_service.py:96–98` | `tg_parser.auth.ownership.PermissionDenied: No access to channel @LongevityClub` (cross-effect c **BUG-003**) |
| H5 | Сломанный/отсутствующий `prompts/rag.yaml` | `tg_parser/services/retrieval_service.py:237–241` (`_load_rag_config`) | `FileNotFoundError` / `yaml.YAMLError` |
| H6 | Pydantic-валидация при гидрации corrupted topic_card / processed_document | `_build_context` (стр. 280–349), `proc_repo.get_by_source_refs`, `topic_card_repo.get_by_id` | `pydantic.ValidationError` |
| H7 | Misconfigured `RAG_LLM_PROVIDER` / unsupported model alias | `tg_parser/processing/llm/factory.create_llm_client` (`retrieval_service.py:453–460`) | `ValueError: unknown provider` / `KeyError: model` |

Без `exc_info` фиксируем как **uncertain root cause; required next step
— вытащить traceback из лога**. Это явная зависимость BUG-005 → triage,
а не BUG-005 → fix.

##### Update from MCP-cross-check (2026-04-26 22:53)

Пользователь подтвердил: **тот же запрос (тот же канал `LongevityClub`,
тот же текст про международные критерии классификации возрастных
патологий) через MCP-клиент возвращает полноценный RAG-ответ**. MCP-tool
`ask_question` (`tg_parser/mcp_server.py:698–744`) и bot-executor
`_exec_ask_question` (`tg_parser/bot/tools.py:802–824`) — **разные
обёртки над одной и той же функцией `retrieval_service.answer()`**. Это
исключает все слои, общие для bot+MCP, и оставляет ровно те, что
отличаются между процессами или вызывающими сторонами.

Hypothesis space после этого факта:

| H | Статус | Аргумент |
|---|---|---|
| H2 (embedding-service) | ❌ Отметается | `_embedding_client.embed()` отрабатывает на стороне MCP-процесса — тот же сервис. |
| H3 (DB / pgvector) | ❌ Отметается | `embedding_repos()` / `topic_embedding_repos()` те же самые. |
| H5 (битый `prompts/rag.yaml`) | ❌ Отметается | YAML парсится для MCP, значит файл валиден. |
| H6 (Pydantic-валидация) | ❌ Отметается | Те же ProcessedDocument / TopicCard гидратируются успешно. |
| H4 (`PermissionDenied`) | ❌ Отметается | Bot-юзер — admin (тот же пользователь в обоих сценариях). |
| H1 (RAG-LLM-провайдер сам по себе) | ⚠️ Частично возможно | Если провайдер отвечает с прерывистым 5xx/429, MCP мог попасть в «удачный» вызов, бот — в «неудачный». Не объясняет повторяемость. |
| **H1b — Drift `LLMConfigManager` между процессами** | 🔥 Главный кандидат | Runtime-override `set_llm_config(scope='rag', ...)` хранится **в памяти процесса**. Если override был сделан через MCP-tool — он применился только к MCP-процессу. Бот всё ещё резолвит RAG-провайдера через `.env` (или старый runtime override). Если в `.env` — нерабочая комбинация (просрочённый ключ / удалённая модель / неактивный провайдер), бот падает, MCP отвечает. Это **per-process state**, не inter-process. |
| **H7b — Stale env / API-key в bot-процессе** | 🔥 Сильный кандидат | Бот не был перезапущен после ротации API-ключа (или после правки `.env`). MCP-процесс рестартился позже / запустился со свежим `.env`. Те же `RAG_LLM_PROVIDER`/`RAG_LLM_MODEL`, но разные effective ключи. |
| H8 (60s timeout в боте) | ⚠️ Менее вероятно для **этого** симптома | `GeminiAgent.__init__` (`tg_parser/bot/agent.py:44–48`) дефолтит `timeout=60.0`, который пробрасывается в `asyncio.wait_for(executor, timeout=...)` в `_call_tool_safe` (`tg_parser/bot/tools.py:784–787`). MCP такого budget'а не накладывает. Но `TimeoutError` ушёл бы по отдельной ветке `except TimeoutError` (стр. 789–791) с текстом `"timed out after 60.0s"` → Gemini сформулировала бы про «слишком долго», не «внутреннюю ошибку». Поэтому H8 объясняет смежный класс инцидентов, но не точно этот. Держим как сопутствующий риск. |
| H9 (concurrency между `_keep_typing` и RAG в bot loop) | ⚠️ Низкая | aiogram-typing-task шлёт `chat_action` и засыпает; общих ресурсов с RAG-pipeline'ом нет. Маловероятно. Закрывается тем же fix'ом из Шага 1 (структурный observability). |
| H10 (разная семантика args от Gemini vs Claude) | ❌ Не root cause | Даже если Gemini послал `channel_id="@LongevityClub"` (см. **BUG-003**), это даёт **пустой** результат, а не exception. Текст был бы про «не нашёл документов», не «внутренняя ошибка». |

После этого факта **новый рекомендованный triage-flow** (≈2 минуты):

1. В Telegram-боте: спросить «выведи текущий llm config» — бот вызовет
   `_exec_get_llm_config` (`tg_parser/bot/tools.py:1573`) и распечатает
   эффективный provider/model для каждого scope'а в **bot-процессе**.
2. В MCP/Claude: вызвать `get_llm_config` — печатает то же для
   **MCP-процесса**.
3. Сравнить `rag.provider` / `rag.model` / `rag.api_key_present` (и
   косвенно `rag.source`: `runtime_override` vs `.env_default`).

   - **Если значения отличаются** → подтверждается **H1b**. Действие:
     либо синхронизировать через `set_llm_config(scope='rag', ...)` в
     **бот-процессе** через MCP-tool, либо вынести RAG-provider в
     общий source-of-truth (DB / Redis), что становится частью fix'а
     этого бага.
   - **Если значения одинаковые** → подтверждается **H7b** (или H1):
     stale ключ в env-варе, бот не перезапущен. Действие: рестарт
     bot-сервиса; затем повторить запрос; если повторно падает — снять
     traceback и идти дальше по H1.

Этот triage-flow выполняется без доступа к серверным логам — пользователь
сам видит конфиг через бота и MCP. Если он показывает разный конфиг —
root cause локализован за один шаг.

##### Update from get_llm_config + bot Gemini outage (2026-04-26 23:00)

MCP-сторона Шага 0-bis выполнена. `get_llm_config` (MCP-процесс) вернул:

- Глобально: **anthropic / claude-sonnet-4-20250514**.
- По стадиям (processing / topicization / rag / digest): **anthropic / claude-sonnet-4-20250514**, без runtime-оверрайдов.
- Доступные провайдеры: openai / anthropic / gemini / ollama (ключи прописаны для всех четырёх).
- Источник: `.env`-defaults.

Bot-сторона Шага 0-bis **не выполнена** — бот на тривиальный запрос
«выведи текущий llm config» возвращает хардкод-фолбэк
«Не удалось получить ответ от LLM.» из `tg_parser/bot/agent.py:87, 98`.
Это уже **BUG-006** (см. ниже): Gemini-agent-loop возвращает
`candidates=[]` или `parts=[]` без диагностических полей. **BUG-006
блокирует cross-check** для BUG-005 и одновременно делает бот
непригодным для любых free-form запросов.

Уточнённый hypothesis space для BUG-005 при условии «бот и MCP читают
один и тот же `.env`»:

| H | Статус | Аргумент |
|---|---|---|
| H1b (LLMConfigManager-drift bot ↔ MCP) | ⬇️ Сильно ослаблена | Если оба процесса на одном хосте с одним `.env` — `_load_llm_config()` даст идентичный результат. Не исключена полностью только в сценарии «разные хосты / разные `.env`». |
| H7b (stale env, бот не перезапущен) | ⬇️ Ослаблена | Возможна только если ключ Anthropic был ротирован после старта бота. На текущих данных без подтверждения. |
| **H1 (Anthropic Sonnet 4 transient — 5xx / overloaded / rate-limit)** | 🔥 Главный кандидат | На выходных у Anthropic сейчас часто observable-instability на Sonnet 4. Отказ оборачивается `anthropic.APIStatusError` или `httpx.HTTPStatusError` → exception → generic catch в `_call_tool_safe`. Что MCP «успел» в окно стабильности — нормально для transient'ов. |
| **H8 (60s timeout для медленного Sonnet 4 ответа)** | ⚠️ Возможно, но текст не точно соответствует | Sonnet 4 на сложном медицинско-классификационном RAG-запросе с контекстом ~7500 chars + thinking может отдавать ответ >60s. Но `TimeoutError` в `_call_tool_safe` идёт по отдельной ветке (`tg_parser/bot/tools.py:789–791`) с текстом `"timed out after 60.0s"` → Gemini сформулировала бы про «слишком долго», не «внутреннюю ошибку». Поэтому H8 объясняет смежный класс инцидентов, но **этот конкретный** симптом — менее вероятно. |
| **H1c (Anthropic exception в `_call_llm` цепляется за cancellation race из H8)** | ⚠️ Узкий, но возможный | Если 60s `wait_for` отменяет таску внутри `anthropic.AsyncAnthropic.messages.create(...)`, SDK может выкинуть **не** `CancelledError`, а внутренний `APIStatusError` или `RuntimeError` (наблюдалось на v0.x релизах). Этот путь даст `Exception` ветку, не `TimeoutError`. Без traceback'а — гипотеза, но именно она объяснила бы, почему мы видим **«внутреннюю ошибку»**, а не «timed out». |
| H10 (BUG-003 cross-effect) | ❌ Не root cause | Нерелевантно: с `@LongevityClub` `effective_channel_ids=["@LongevityClub"]` → пустой результат → `no_results_msg`, не exception. |

Рекомендованный обновлённый порядок диагностики:

1. **Дождаться разблокировки бота** (см. BUG-006: либо рестарт + ожидание сброса Gemini-quota, либо смена бот-агентной модели на `gemini-1.5-pro`/`gemini-2.5-pro`).
2. После разблокировки — повторить «выведи текущий llm config» в боте, сравнить с MCP. Финализировать H1b/H7b.
3. Если конфиги совпали и бот всё ещё падает на `ask_question` — ловить **traceback** из `tool_execution_error tool=ask_question` (Шаг 0). Анализ traceback однозначно скажет: H1 vs H1c vs H8.
4. Если до разблокировки бота нужно срочно — диагностировать на стороне MCP-логов (там стек тоже виден). Это требует доступа к bash на сервере, что пользователь сейчас просил не делать.

##### Update from search-vs-ask_question split (2026-04-26 23:09)

Получен **третий и решающий observability-факт**, фиксирую трасс целиком:

```
23:07:59  Alex: Что говорится в каналах о подготовке к анализу крови
                на пролактин?
23:08:03  Bot:  Извините, произошла внутренняя ошибка при попытке
                ответить на ваш вопрос. Пожалуйста, попробуйте
                перефразировать вопрос или воспользуйтесь поиском
                по ключевым словам.

23:08:21  Alex: поищи информацию о пролактине
23:08:26  Bot:  Я нашел следующую информацию о пролактине:
                * Функции и выработка: Пролактин — гормон…
                  (tg:Lab4health:post:1518, tg:Lab4health:post:1219)
                * Подготовка к анализу: Для получения достоверных
                  результатов анализа на пролактин необходима строгая
                  подготовка… (tg:labdiagnostica_logical:post:188,
                  tg:labdiagnostica_logical:post:190)
                …

23:08:54  Alex: Как правильно подготовиться к сдаче анализа на
                проллактин?
23:08:57  Bot:  Извините, произошла внутренняя ошибка при попытке
                ответить на ваш вопрос. Пожалуйста, попробуйте
                перефразировать вопрос или я могу попробовать найти
                документы, связанные с подготовкой к анализу на
                пролактин, если вы хотите.
```

##### Что наблюдение исключает (окончательно)

| H | Статус | Обоснование |
|---|---|---|
| H2 (embedding-сервис) | ❌ | `search`-tool отработал — embedding/pgvector живы. |
| H3 (DB / pgvector) | ❌ | Та же причина. |
| H4 (`PermissionDenied`) | ❌ | `search` принимает `allowed_channel_ids` так же, как `ask_question` — упало бы там же. |
| H5 (битый `prompts/rag.yaml`) | ❌ | YAML-файл доказанно валиден через MCP-стороннее использование (22:45). |
| H6 (Pydantic-гидрация) | ❌ | `search` отдаёт `summary` / `text_preview` из тех же `ProcessedDocument`'ов — они гидрируются. |
| H10 (BUG-003 `@`-cross-effect) | ❌ | В обоих неудачных запросах **нет `channel_id`** вообще — нечего «не нормализовать». |
| **H8 (60s timeout)** | ❌ **Окончательно** | Время от запроса до error-фразы — **3–4 секунды** (23:07:59 → 23:08:03 = 4 сек; 23:08:54 → 23:08:57 = 3 сек). `asyncio.wait_for(timeout=60.0)` не успевает сработать. Exception приходит **до** 60s. |
| **H1c (cancellation race)** | ❌ | Зависит от срабатывания timeout — а его нет. |
| **HG-2 (thinking-budget Gemini agent loop)** | ❌ для этого инцидента | Bot-агент успешно произвёл tool-call — генерируется русский parafrasis tool-error'а с осмысленным контекстом. Gemini жива. |

##### Что остаётся (final shortlist)

| H | Статус | Аргумент |
|---|---|---|
| **H1 — Anthropic Sonnet 4 transient/persistent issue (5xx / overloaded / 429)** | 🔥 **Главный кандидат** | (a) `ask_question` падает быстро (≤4 сек) — это HTTP-exception от Anthropic SDK, а не таймаут. (b) `search` живёт, потому что не зовёт RAG-LLM (`tg_parser/services/retrieval_service.py:51–234` против `:439–474`). (c) Повторяемость с разными формулировками за минутный интервал — это persistent issue провайдера или нашей конфигурации, не флакушесть. |
| **H7b — stale/невалидный Anthropic key в bot-процессе** | ⚠️ Условно возможен | Если ключ был ротирован после старта бота, bot всегда получает 401/403 на любом `ask_question`. **Но**: MCP-процесс в 22:45 успешно ответил через Anthropic Sonnet 4 на «LongevityClub». Если оба процесса читают один `.env` — H7b отпадает. Если из разных `.env` (разные хосты / разные deployments) — возможен. |

##### Локализация в коде

`_exec_ask_question` (`tg_parser/bot/tools.py:802–824`) делает три вещи:

1. `result = await answer(...)` (`tg_parser/services/retrieval_service.py:352–436`):
   - `search()` — **доказанно жив** (`tg_parser/bot/tools.py:827–851` зовёт ту же функцию).
   - `_load_rag_config()` — **доказанно жив** (MCP сегодня уже отвечал).
   - `_call_llm()` — **единственное место, где локализуется ошибка**.
2. Преобразование sources в dict — pure-функция, не падает.
3. Возврат dict.

`_call_llm` (`tg_parser/services/retrieval_service.py:439–474`) сводится к
`anthropic.AsyncAnthropic.messages.create(...)` через
`tg_parser/processing/llm/factory.create_llm_client(provider="anthropic", ...)`.
Любой `anthropic.APIStatusError` / `anthropic.APIConnectionError` /
`httpx.HTTPStatusError` пролетает наверх → `_exec_ask_question` (без
`try/except`) → `_call_tool_safe` (стр. 792–794) → generic
`{"error": "Tool 'ask_question' failed with an internal error"}` →
Gemini-парафраз.

##### Финальный диагноз для BUG-005 на текущих данных

С вероятностью **≈85%** root cause — **H1 (Anthropic transient or
persistent issue with Sonnet 4 right now)**. Оставшиеся ≈15% делятся
между H7b (stale key в bot-процессе при разных `.env` для bot и MCP) и
менее вероятными edge-case'ами. Без traceback'а полностью верифицировать
H1 vs H7b нельзя, но **есть детерминированный bisection-test за 30 секунд
без правки кода**:

##### Triage-step для финальной верификации (≤30 сек, без правки кода)

Через **MCP** выполнить:

1. `set_llm_config(scope='rag', provider='gemini', model='gemini-2.5-flash')`
   — переключить RAG-LLM на Gemini в обоих процессах? **Нет, только в
   MCP-процессе** (см. **H1b** — runtime overrides per-process). Поэтому
   делаем через **бот**:
   - В Telegram: «переключи RAG-LLM на gemini-2.5-flash» — бот сделает
     `_exec_set_llm_config(scope='rag', provider='gemini', model='gemini-2.5-flash')`.
2. Повторить тот же запрос боту: «Как правильно подготовиться к сдаче
   анализа на пролактин?»

Распознавание:
- **Если бот корректно ответит** → подтверждается **H1** (Anthropic
  Sonnet 4 был источником проблемы). Можно держать Gemini как RAG, либо
  вернуться на Anthropic позже, либо разнести RAG на разные провайдеры.
- **Если бот падает с тем же error'ом** → проблема **не** в Anthropic
  (или не **только** в Anthropic). Идём за traceback'ом из лога — это
  уже H7b или новый кандидат.

Этот шаг **не требует доступа к серверу/логам**, делается из чата за 30
секунд и однозначно бисектирует hypothesis space.

##### Update from sub-second Anthropic fail-time (2026-04-26 23:13)

Получен **четвёртый трасс**, фиксирую целиком:

```
23:12:56  Alex: Что говорится по теме Фитофотодерматит и
                фототоксические реакции кожи?
23:13:00  Bot:  Извините, произошла внутренняя ошибка при попытке
                ответить на ваш вопрос. Я могу попробовать найти
                информацию по теме … с помощью поиска по ключевым
                словам или вывести список тем …

23:13:13  Alex: найди по ключевым словам
23:13:14  Bot:  Пожалуйста, уточните, какие ключевые слова вы хотите
                использовать для поиска.

23:13:27  Alex: Фитофотодерматит и фототоксические реакции кожи
23:13:30  Bot:  Извините, произошла внутренняя ошибка при попытке
                ответить на ваш вопрос. Пожалуйста, попробуйте
                перефразировать запрос или я могу выполнить поиск
                по ключевым словам "Фитофотодерматит" и
                "фототоксические реакции кожи" в базе знаний.
```

###### Декомпозиция времени отказа

Время от запроса до error-фразы: **3–4 секунды на каждой попытке** (3 раза подряд: 4с / 1с / 3с — для tool-call'ов, без учёта turn'а с уточнением). Это даёт жёсткий budget на Anthropic-вызов:

| Стадия | Оценка | Комментарий |
|---|---|---|
| Telegram → handler → Dispatcher | ~100 мс | aiogram + middleware |
| Gemini agent loop turn 1 (decide tool) | 500 мс – 1.5 с | gemini-2.5-flash, ~30 tool-deklaraций |
| `_exec_ask_question` → `search()` | 1 – 2 с | embedding + pgvector + FTS (известно по успешным «пролактин»-вызовам) |
| **`_call_llm` → Anthropic** | **<1 с** | то, что осталось |
| Gemini agent loop turn 2 (paraphrase error) | 500 мс – 1 с | rendering русского apology |
| **Σ** | **3–4 с** | ✓ согласовано с трассом |

**На Anthropic-вызов остаётся <1 секунды.** Это критическая численная улика.

###### Сигнатура HTTP-ответа

Anthropic API timing-сигнатуры по типу ошибки:

| HTTP Code | Тип | Типичный fail-time |
|---|---|---|
| 5xx (overloaded / `overloaded_error`) | transient overload | 5–30 секунд (queue + retry внутри SDK) |
| 401 / 403 (auth — invalid/revoked key) | gateway-level reject | <500 мс (мгновенный 4xx на edge) |
| 429 (rate-limit / quota) | gateway-level reject | <500 мс |
| 402 / 400 (insufficient credits / billing) | gateway-level reject | <500 мс |
| 404 (model deprecated / no access) | gateway-level reject | <500 мс |
| Network connect-error (`APIConnectionError`) | DNS / TLS fail | 1–3 с (с DNS retry внутри SDK) |

**<1 секунды — это сигнатура gateway-level rejection (4xx), не overloaded (5xx).**

###### Уточнённый hypothesis shortlist

| H | Статус | Аргумент |
|---|---|---|
| **H1' — Anthropic gateway-level rejection (4xx)** | 🔥 **Главный кандидат** | <1 с на Anthropic-side fail-time. Семейство объединяет: H1'a (auth/key), H1'b (credits/billing), H1'c (rate-limit org-tier), H1'd (model access removed). |
| **H7b — stale/revoked ключ только в bot-процессе** | 🔥 Sub-case H1'a | Bot-процесс стартовал с ключом, который потом был ротирован/отозван; MCP-процесс рестартовал со свежим ключом → MCP отвечает (22:45), bot падает (23:13). |
| **H7c — account credits depleted (NEW)** | 🔥 Sub-case H1'b | За ~30 минут активного MCP-тестирования (включая `force_resummarize` / topic-init / processing) Anthropic-credits/billing-cap могли быть пробиты после 22:45. Тогда **и MCP, и bot падают одинаково сейчас**. Простой проверочный шаг — Шаг B ниже. |
| **H7d — org-level rate-limit hit (NEW)** | ⚠️ Возможно | Anthropic считает RPM/RPD per-org. Если org-level лимит выбит, оба процесса падают. Симптомы такие же, как у H7c. |
| H1 (Anthropic transient 5xx / overloaded_error) | ⬇️ **Понижен** | Не объясняет 3–4 с total time. Sonnet 4 5xx обычно прилетает после 5+ секунд (queue+retry). Не отметается полностью (могут быть быстрые 5xx без retry в нашем SDK-конфиге), но менее вероятен. |
| HG-2 (Gemini thinking-budget) | ❌ для этого инцидента | Turn'ы 1 и 2 (paraphrase apology) отработали быстро и осмысленно; Gemini agent loop жив. |

###### Двухшаговый детерминированный triage (≤5 минут, без правки кода)

Прошлый Шаг A (бисекция через смену провайдера) **остаётся релевантным**, но добавляется **Шаг B** для разделения H7b vs H7c/H7d:

**Шаг A — bisection через смену RAG-провайдера на стороне бота.**

В Telegram: «переключи RAG-LLM на gemini-2.5-flash». Затем повторить любой неудачный вопрос.
- ✅ Ответил → подтверждается **H1'-семейство** (Anthropic-side issue, любой sub-case). Дальше — Шаг B чтобы выяснить точный sub-case (полезно для outage-постмортема, но не критично для unblock'а).
- ❌ Не ответил → проблема не в Anthropic-провайдере. Идти за traceback'ом (потребует доступа к серверу/логам).

**Шаг B — повторить тот же вопрос через MCP-`ask_question`.**

В Claude вызвать MCP-tool:
```
ask_question(question="Что говорится по теме Фитофотодерматит и
                       фототоксические реакции кожи?")
```

- ✅ MCP **работает** → подтверждается **H7b** (drift между bot-процессом и MCP-процессом — разные effective Anthropic-keys или разные `.env`/deployments). **Фикс**: рестарт bot-сервиса (если ключ был обновлён в `.env`, но bot-процесс ещё с прошлым), либо постоянное переключение RAG на другого провайдера через Шаг A.
- ❌ MCP **тоже падает** (быстро, как и bot) → подтверждается **H7c или H7d** (account-level Anthropic issue: credits / rate-limit / billing). **Фикс**: пополнить billing на dashboard Anthropic, либо сменить ключ на ключ другой организации, либо переключить все RAG-стадии на другого провайдера через Шаг A.

Шаг A + Шаг B вместе **за ≤5 минут** определяют точный sub-case. Шаг 0 (traceback из лога) на этом фоне — уже verification, а не диагностика для триажа.

###### Сравнение с предыдущим состоянием анализа

Прошлая итерация фиксировала: «локализовали в `_call_llm` (Anthropic SDK call), вероятная причина — H1 (Anthropic transient/persistent issue), 85% уверенности». Текущий update **уточняет**: проблема всё ещё в `_call_llm` / Anthropic-call, но **не transient overload**, а **gateway-level rejection (4xx)**, что радикально меняет сценарий фикса:

| Раньше предполагали | Сейчас более вероятно | Разница в фиксе |
|---|---|---|
| Sonnet 4 «лежит» (5xx) — нужно подождать или сменить модель временно | Ключ/credits/quota issue — нужно проверить billing dashboard и/или ротацию ключа | Принципиально разные действия. Подождать не поможет, если credits depleted. |

###### Что происходит с третьим turn'ом трасса (UX-наблюдение)

Третий turn (23:13:27 — 23:13:30) интересен сам по себе: пользователь написал «Фитофотодерматит и фототоксические реакции кожи» как продолжение предыдущей реплики «найди по ключевым словам». Из-за **statelessness (BUG-002)** Gemini не знает, что это «keywords для search», и видит просто declarative-style фразу. По system-prompt'у это `ask_question` (а не `search`). **Поэтому третий turn — это снова `ask_question`, не `search`**, и снова падает по той же причине. То есть мы не имеем данных о работоспособности `search` в этой серии (он не был вызван).

Это пересекается с BUG-002 (statelessness) и снова показывает, насколько отсутствие memory ломает многошаговые сценарии.

##### Final root cause: H7c confirmed (2026-04-26 23:17)

Выполнил **Шаг B** — вызов MCP `ask_question` с тем же запросом про фитофотодерматит. Результат **детерминированный**:

```
Error executing tool ask_question: Your credit balance is too low to
access the Anthropic API. Please go to Plans & Billing to upgrade
or purchase credits.
```

Это **HTTP-402 (Insufficient Credits)** от Anthropic API gateway. На стороне SDK летит `anthropic.BadRequestError` или `anthropic.PermissionDeniedError` (зависит от версии SDK) с сообщением `{"type":"error","error":{"type":"invalid_request_error","message":"Your credit balance is too low..."}}`.

###### Что это исключает / подтверждает

| H | Финальный статус | Обоснование |
|---|---|---|
| **H7c — Anthropic credits depleted** | ✅ **CONFIRMED** | Буквальный текст ошибки от Anthropic API. |
| H1 (transient 5xx / overloaded) | ❌ Final no | Это 4xx, не 5xx. Время <1 сек на gateway-level reject. |
| H7b (stale key drift bot↔MCP) | ❌ Final no | Оба процесса падают **одинаково** — значит это account-level, не per-process key. |
| H7d (org-tier rate-limit / RPM) | ❌ Final no | Явный credit-balance error, не quota-error message. |
| H1'a / H1'd (key revoked / model deprecated) | ❌ Final no | Отметены тем же сообщением. |

###### Все ранее наблюдавшиеся факты согласованы

- ✅ 3–4 сек total fail-time → <1 сек на Anthropic = HTTP-402 gateway reject (мгновенный 4xx на edge).
- ✅ MCP в 22:45 ответил на «LongevityClub» через Sonnet 4 → в тот момент credits ещё были.
- ✅ За ~30 минут активного MCP-тестирования (вкл. force_resummarize / topic-init / processing / RAG) credits исчерпались.
- ✅ В 23:13 и bot, и MCP падают одинаково → account-level (один billing-account).
- ✅ `search`-запросы про «пролактин» в 23:08 работали → `search` не зовёт RAG-LLM (`tg_parser/services/retrieval_service.py:51–234` против `:439–474`).

###### Бонус-находка: BUG-005-B асимметричен

**MCP-сторона корректно пробросила точный текст ошибки** («Your credit balance is too low…») — significant. Это означает:

- **MCP-tool НЕ ловит exception в generic catch** — он пропускает наверх настоящий `error.message` из Anthropic SDK.
- **Bot-tool ловит** в `_call_tool_safe` (`tg_parser/bot/tools.py:792–794`) и заменяет на `{"error": "Tool 'ask_question' failed with an internal error"}`.

Значит структурный observability-баг (BUG-005-B, generic catch) — **специфика именно bot-`_call_tool_safe`**, а не общая проблема всего MCP-стека. Фикс точечный: пробросить `e.__class__.__name__` + `str(e)` (с redaction) до уровня tool-result, чтобы Gemini могла сформулировать осмысленный ответ типа «у Anthropic кончились credits — переключите RAG на gemini командой `…`» вместо абстрактного «внутренняя ошибка».

###### Действия для немедленной разблокировки

**Вариант 1 — пополнить Anthropic billing.** [console.anthropic.com → Plans & Billing](https://console.anthropic.com/settings/billing). Не требует никаких рестартов: тот же API-key, просто появятся credits.

**Вариант 2 — переключить RAG на другого провайдера** через `set_llm_config`:

- В **MCP-процессе**: вызвать `set_llm_config(scope='global', provider='gemini', model='gemini-2.5-flash')` (или `openai`/`ollama`). Это даёт runtime override **per-process** (см. **H1b** в основном анализе) — действует только в MCP.
- В **bot-процессе**: то же самое, но команду нужно отдать **из Telegram-бота**, чтобы override применился к bot-процессу. Например: «переключи все LLM-стадии на gemini-2.5-flash».
- Оба override не персистируются через рестарт; в `.env` остаётся Anthropic.

Этот Вариант 2 не требует доступа к billing-account и работает за 30 секунд.

###### Long-term recommendations (для backlog'а)

1. **Cost-protection alerts**: настроить billing-alerts на Anthropic dashboard на пороге, скажем, 25% / 50% / 80% от месячного бюджета.
2. **Автопереключение RAG при credit-exhaustion**: можно ловить `anthropic.BadRequestError` с `error.type=='invalid_request_error'` и `'credit balance'` в message — и автоматически фоллбэк на secondary-provider (как H1b-aware fallback в `_call_llm`). Тогда bot не «упадёт» в момент исчерпания credits, а тихо переключится.
3. **BUG-005-B фикс**: passthrough `error_class` + `error_message` в `_call_tool_safe` (с PII-redaction если нужно) — bot будет показывать «у RAG кончились credits» вместо «внутренняя ошибка».

##### BUG-005-A resolved via billing top-up (2026-04-26 23:32)

После пополнения Anthropic billing проведена контрольная проверка из
Telegram-бота с тем же запросом, что упал последним:

```
Alex: Что говорится по теме Фитофотодерматит и фототоксические
      реакции кожи?  [23:32:01]
Bot:  По теме фитофотодерматита и фототоксических реакций кожи
      представлена подробная информация:
      Определение и механизм
      Фитофотодерматит — это воспалительная реакция кожи…
      [tg:Lab4health:post:2853]
      …
      [tg:Lab4health:post:2853]    [23:32:20]
```

###### Замеры и подтверждения

| Метрика | До (23:13) | После (23:32) | Интерпретация |
|---|---|---|---|
| Время до ответа | **3–4 сек** (gateway reject) | **19 сек** (полноценный RAG-генерационный latency) | Anthropic-вызов теперь живёт ~12–14 сек, что нормально для содержательного ответа. |
| Источник в response | (нет — error) | `tg:Lab4health:post:2853` | Тот же source, что у MCP-эталона. RAG-pipeline корректно находит документ. |
| Структура ответа | (нет) | определение → симптомы → причины → группы риска → лечение/профилактика | Содержание совпадает с MCP-эталоном. Минорные расхождения структуры (5 секций vs 7 у MCP) — нормальная вариация Gemini turn-2 paraphrase'а. |

###### Окончательный hypothesis status для BUG-005-A

| H | Финальный статус |
|---|---|
| **H7c — Anthropic account credits depleted** | ✅ **CONFIRMED + FIXED** через пополнение billing |
| H7b (stale key drift bot↔MCP) | ❌ Окончательно отметён: bot-процесс читает **тот же** аккаунт, иначе пополнение не помогло бы. |
| H7d (org-tier rate-limit) | ❌ Окончательно отметён по тексту ошибки. |
| H1 / H1c / H8 / H2 / H3 / H4 / H5 / H6 / H10 | ❌ Все окончательно отметены ранее. |

###### Что осталось открытым (BUG-005-B)

Структурный observability-баг **не починен** пополнением billing — это
бы и не могло. Bot-`_call_tool_safe` (`tg_parser/bot/tools.py:792–794`)
по-прежнему стирает реальный `error_message` от Anthropic SDK и заменяет
на `{"error": "Tool 'ask_question' failed with an internal error"}`.
Это означает: **при следующем H7c-инциденте** (например, очередное
исчерпание credits через месяц) пользователь снова будет видеть
бессодержательную «внутреннюю ошибку», и снова потребуется ручная
бисекция bot ↔ MCP, чтобы выяснить причину. Точечный фикс — описан в
§ B (структурный) и в Long-term recommendations.

**BUG-005-A → status: `resolved` (workaround = billing top-up).**
**BUG-005-B → status: `open`** (требует точечной правки в
`tg_parser/bot/tools.py:792–794`).

##### B. Структурный UX/observability-баг (root cause независимо от A)

Даже если завтра упадёт совершенно по другой причине, пользователь
увидит то же самое.

1. **Generic catch без таксономии.** `_call_tool_safe` (`tg_parser/bot/tools.py:792–794`)
   уравнивает все исключения в одну строку. Tool-исполнитель не имеет
   возможности сообщить LLM, **что именно** не сработало.

2. **Tool decl `ask_question` (`tg_parser/bot/tools.py:43–66`)** не описывает
   возможные `error_code`'ы → у LLM нет инструкции «пробросить технический
   намёк юзеру». Gemini дисциплинированно «облагораживает» error-строку.

3. **Нет correlation-id**, который связал бы видимое сообщение с
   соответствующей строкой в логе. Оператор не может сказать «покажи лог
   за такой-то id» — приходится ловить по timestamp'у, что хрупко при
   высоком трафике.

4. **Нет user-actionable hint'ов** даже для известных классов сбоев:
   - RAG-LLM-down → нужно «попробуйте через минуту» / «админ — проверь
     `RAG_LLM_PROVIDER`».
   - PermissionDenied → нужно «у вас нет доступа к каналу X; ваши
     каналы: …».
   - Empty-results-vs-error → разные UX, сейчас слитное «попробуйте
     перефразировать».

5. **Нет fallback-стратегии.** Когда RAG-LLM падает, можно было бы
   автоматически degrade'нуться на чистый `search` (без LLM-генерации,
   но со списком найденных документов) — пользователь хотя бы получит
   первичные источники. Сейчас «всё или ничего».

6. **Нет retry на transient ошибки.** LLM-провайдер с 429/503 — это
   нормальный transient, но `_call_llm` не делает ни одного retry.

##### Почему именно такой текст у Gemini (а не сырой error)

System-prompt (`prompts/bot.yaml:31, 39`):
> «If the search returns no results, say so honestly.»
> «ALWAYS use tools to retrieve information before answering.»

Внутренние heuristics модели + `temperature=0.2` (`tg_parser/bot/agent.py`)
дают характерную «бережную» формулировку для tool-error'а: извинение +
причину «обобщить» + предложение workaround'а (`перефразируйте /
воспользуйтесь поиском`). Слово «RAG» Gemini берёт из tool description
(`Uses RAG: retrieves relevant documents and generates an answer with
an LLM`, `tg_parser/bot/tools.py:48`). Это объясняет узнаваемый шаблон
сообщения, но не помогает в диагностике — текст один и тот же на любую
из H1–H7.

##### Почему гипотезы-альтернативы (что Gemini «сама придумала») отметены

| H | Описание | Вердикт |
|---|---|---|
| HG1 | Gemini сама решила «не отвечать» по контентным соображениям | На вопросе про «международные критерии возрастных патологий» нет триггеров safety-фильтров. Кроме того, `_call_tool_safe` явно вызывался — иначе формулировка была бы другая (без слова «попробуйте перефразировать»). |
| HG2 | `answer()` вернула пустой результат и Gemini сочинила извинение | Нет: при пустом результате `answer()` возвращает строку из `rag_config.no_results.message` («Не найдено релевантных документов…», `retrieval_service.py:402–407`) — это **успешный** tool-result, и Gemini в таком случае стандартно говорит «по этому вопросу в KB нет данных». |
| HG3 | Сетевая ошибка между ботом и Gemini | Если бы Gemini не ответила — бот вернул бы `format_timeout()` или `format_error("Внутренняя ошибка. Попробуйте позже.")` из `tg_parser/bot/handlers.py:150–158`. Но текст пришёл от Gemini полным, значит первый round-trip отработал; упало внутри tool-call'а. |

#### Why CI didn't catch

- Тесты `_exec_ask_question` (если есть) мокают `retrieval_service.answer`
  на success/empty results. **Failure-mode тестов нет**: нет ни одного
  кейса, где `answer()` raises (rate-limit / API-down / DB-down /
  PermissionDenied / corrupted prompt YAML). Поведение `_call_tool_safe`
  для exception-path не проверяется на пользовательский UX.
- `tests/test_rag_prompt_config.py` проверяет только загрузку YAML.
  Сценария «YAML битый → как реагирует tool» нет.
- Нет integration-теста с реальным LLM-провайдером (даже на staging),
  который ловил бы регрессии конфигурации `RAG_LLM_PROVIDER`.
- Нет prompt-conformance-теста: когда tool вернул `{error_code,
  error, hint}`, проверять, что Gemini донесла `hint` до пользователя,
  а не «зализала» его.

#### Proposed fix

Делится на **обязательный triage-step** (он же помогает закрыть инцидент)
и **структурный fix** (который делается в любом случае).

**Шаг 0 — Triage (≈5 минут, требует доступ к логам бота).**

Найти в логах event `tool_execution_error tool=ask_question` за
2026-04-26 ≈22:45 (timestamp пользователя), извлечь traceback. Это
вернёт точную H1…H7 и сильно сужает Шаг 1 (минимум, минимум-таксономии
для конкретно ask_question). Если логи ротированы — воспроизвести запрос
с `LOG_LEVEL=DEBUG` (или хотя бы INFO + structured-log).

**Шаг 0-bis — Быстрая cross-process сверка LLM-конфига (≈2 минуты, без доступа к логам).**

Применимо после факта «MCP отвечает на тот же вопрос». Сверить, что
bot-процесс и MCP-процесс читают одинаковый эффективный RAG-провайдер:

1. В Telegram-боте: «выведи текущий llm config» → `_exec_get_llm_config`
   (`tg_parser/bot/tools.py:1573`).
2. В Claude/MCP: вызвать MCP-tool `get_llm_config`.
3. Сравнить `rag.provider`, `rag.model`, наличие соответствующего
   `*_API_KEY` (по-возможности — индикатор `runtime_override` vs
   `env_default`).

Если конфиги расходятся — root cause локализован как **H1b
(LLMConfigManager-drift)**. Если совпадают и оба стейлы — это
**H7b (stale env, бот не перезапущен)**, действие: рестарт бот-сервиса
и повтор запроса. Если совпадают и MCP-процесс работает — переходить к
Шагу 0 (логи) для разделения H1 vs H8.

**Шаг 1 — Минимум: таксономия ошибок в `_exec_ask_question` (≈40 строк).**

В `tg_parser/bot/tools.py::_exec_ask_question` обернуть вызов `answer()`
явным `try/except`:

```python
from tg_parser.auth.ownership import PermissionDenied
# (плюс импорты конкретных провайдер-исключений по мере необходимости)
try:
    result = await answer(...)
except PermissionDenied as e:
    return {"error": str(e), "error_code": "permission_denied",
            "hint": "Запрашиваемый канал недоступен в вашем профиле."}
except (TimeoutError, asyncio.TimeoutError):
    return {"error": "RAG pipeline timed out", "error_code": "timeout",
            "hint": "Попробуйте через минуту или сузьте запрос."}
except FileNotFoundError as e:
    return {"error": f"RAG prompt config missing: {e}",
            "error_code": "prompt_config_missing",
            "hint": "Админ: проверьте prompts/rag.yaml и BOT_PROMPTS_DIR."}
except Exception as e:
    cid = uuid.uuid4().hex[:8]
    logger.exception("ask_question_failed", correlation_id=cid)
    return {"error": "Internal RAG error", "error_code": "internal",
            "correlation_id": cid,
            "hint": f"Сообщите администратору код инцидента: {cid}."}
```

И в `prompts/bot.yaml` добавить инструкцию: **если в tool-result есть
`error_code` и/или `hint` — донести `hint` до пользователя дословно
(плюс `correlation_id` если он есть)**, не перепридумывая текст.

**Шаг 2 — Hardening (один или два дополнительных коммита, ≈150 строк).**

1. **Поднять таксономию на уровень всех `_exec_*`-tool'ов через decorator:**

   ```python
   def with_error_taxonomy(*known_excs):
       def deco(fn):
           @functools.wraps(fn)
           async def wrapper(*a, **kw):
               try:
                   return await fn(*a, **kw)
               except known_excs as e:
                   ...
               except Exception:
                   ...
           return wrapper
       return deco
   ```

   Заменить generic catch в `_call_tool_safe` на «catch ровно
   `BaseException` + log + propagate как `error_code=internal`».
   Tool-side ловит конкретные классы и возвращает `error_code`. Закрывает
   класс будущих BUG-XYZ от любого tool'а сразу.

2. **`correlation_id` в каждом сообщении бота при error-path** —
   `tg_parser/bot/handlers.py` или прямо в `_call_tool_safe`. Оператор
   получает grepable ключ; пользователь — что приложить к bug-репорту.

3. **Retry transient-ошибок RAG-LLM**. В `retrieval_service._call_llm`
   обернуть `llm_client.generate` в `tenacity.retry` с
   `retry_if_exception_type` для 429/5xx + max-attempts=2,
   exponential backoff 1s/2s. Это нивелирует H1 как «временный»
   инцидент.

4. **Graceful degradation при падении LLM:** если `_call_llm` упал
   и в `search()` уже есть результаты — вернуть `AnswerResult(
   answer="LLM временно недоступна, вот источники по запросу:",
   sources=results, model=None)`. Пользователь получает первичные
   ссылки вместо извинений.

5. **Health-tool** для админа: `/healthz_rag` (или
   `_exec_check_rag_health`) — пингует embedding API, RAG-LLM API,
   pgvector. Возвращает таблицу «компонент / статус / latency».
   Делает Шаг 0 одной командой в чате.

6. **Tool decl расширение:** в `ask_question` (и аналогично в
   `search`, `list_topics`, …) описать в `description` структуру
   error-result'а: «On failure, returns `{error, error_code, hint?,
   correlation_id?}`. Forward `hint` to the user verbatim.»

7. **Cross-process consistency `LLMConfigManager`** (мотивирован
   H1b из § «Update from MCP-cross-check»). Сейчас runtime override
   через `set_llm_config(scope=..., provider=..., model=...)` хранится
   в памяти процесса (`tg_parser/config/llm_config.py`) и **не
   синхронизируется** между bot-процессом и MCP-процессом. Это
   архитектурный gap, провоцирующий «MCP работает, бот падает» (и
   наоборот) **без видимой причины** — администратор видит «один и тот
   же» config, не подозревая о per-process state. Варианты фикса:
   - **Минимум:** в выводе `get_llm_config` явно отмечать процесс
     («bot pid=… runtime_override=… env_default=…»), плюс предупреждение
     в docstring tool'а «runtime overrides do not propagate across
     processes — restart all processes after `.env` changes, or use
     `set_llm_config` separately in each.»
   - **Правильно:** хранить runtime overrides в DB (`llm_overrides`
     таблица) либо в Redis с TTL, и подгружать на каждый
     `resolve_full(scope)`. Это превращает per-process override в
     cluster-wide. Согласуется с архитектурой fix BUG-002 (FSM-storage
     уже потребует Redis в multi-replica) — можно объединить в одну
     fix-сессию.
   - Альтернатива на «выходные»: pub/sub-канал, на котором bot и MCP
     слушают `set_llm_config`-events. Дешевле, но требует наличия
     broker'а (Redis), что снова возвращает к предыдущему пункту.

**Тесты (обязательны для каждого варианта).**

- `_exec_ask_question` failure-mode-suite: моки `answer()` бросают
  каждое из H1–H7 → tool возвращает соответствующий `error_code`.
- Prompt-conformance: mock-Gemini получает `{error: ..., hint: ...,
  correlation_id: ...}` → сгенерированный пользовательский текст
  содержит `hint` дословно и `correlation_id`.
- Smoke-integration с `prompts/rag.yaml`: парсится без ошибок (catches
  H5 при ребейзе).
- Retry-test: mock LLM-провайдер бросает 429 N раз, на N+1 успех →
  `_call_llm` отдаёт ответ.

**Рекомендация:** Шаг 0 + Шаг 1 в одной fix-сессии (это всё ещё ≤1 час
работы и сразу убирает observable bug у пользователя). Шаг 2 — в
параллельную сессию по rolling-improvement бот-инфры. Шаг 2.4
(graceful degradation) особенно ценен в комбинации с Шагом 1, поскольку
покрывает самый частый сценарий — кратковременный RAG-LLM outage.

#### Workaround (на время до фикса)

1. **Получить технический root cause** — открыть лог бота, найти
   `tool_execution_error tool=ask_question` рядом с timestamp'ом
   («22:45:25 +04:00»), прочитать traceback. Это сразу даёт ответ
   на «починить → перезапустить / прокинуть API-ключ / откатить
   модель / etc.».

2. **Fallback на `search` (keyword-режим)** — у бота он есть отдельной
   tool'ой и не зависит от RAG-LLM:

   > «Найди в LongevityClub упоминания международных критериев
   > классификации возрастных патологий»

   Tool вернёт ранжированные документы, без сгенерированного ответа,
   но с источниками — этого обычно достаточно, чтобы понять, есть ли
   ответ в KB.

3. **Через MCP/Claude** — там сырой error пробрасывается клиенту;
   увидите конкретный exception без «зализывания».

4. **Сменить RAG-провайдера временно** через MCP-tool `set_llm_config`
   (scope='rag'), если H1 (LLM-down) подтверждается. Например, переключить
   с проблемного на тот, что точно работает в текущем env.

5. **Если confirmed H1b (drift между bot и MCP)** — выполнить
   `set_llm_config(scope='rag', provider=..., model=...)` **из самого
   бота** (бот тоже умеет — `_exec_set_llm_config` в `tg_parser/bot/tools.py:1582`),
   чтобы override применился в bot-процессе. Это не починит
   архитектурный gap (override всё ещё per-process и сбросится при
   рестарте), но мгновенно разблокирует пользователя.

6. **Если confirmed H7b (stale env)** — рестартить bot-сервис
   (`systemctl restart tg_parser_bot` / `docker restart …`) после
   обновления `.env`. После рестарта повторить запрос; если падает
   снова — идти за traceback'ом.

#### Artifacts

- Generic-catch без таксономии: `tg_parser/bot/tools.py:792–794`.
- Executor без локального `try/except`: `tg_parser/bot/tools.py:802–824`.
- RAG entry point: `tg_parser/services/retrieval_service.py:352–436`
  (`answer`), `:51–234` (`search`), `:439–474` (`_call_llm`),
  `:237–241` (`_load_rag_config`), `:402–407` (no-results branch).
- Embedding entry point: `tg_parser/services/retrieval_service.py:117–124`,
  `tg_parser/services/embedding_service.create_embedding_client`.
- RAG prompt config: `prompts/rag.yaml`.
- Tool decl, который Gemini читает (откуда слово «RAG»):
  `tg_parser/bot/tools.py:43–66`.
- System prompt бота (источник «бережной» формулировки):
  `prompts/bot.yaml:30–43`.
- MCP-симметричный handler (без BUG-005-обёртки, но с теми же
  failure-modes — потенциальная цель того же fix'а):
  `tg_parser/mcp_server.py:698–744`.
- Канал-триггер: `LongevityClub`, запрос про международные критерии
  классификации возрастных патологий.
- **Cross-check observability (2026-04-26 22:53):** идентичный запрос
  через MCP-клиент возвращает корректный RAG-ответ. Это исключает
  H2/H3/H4/H5/H6 и переводит главными подозреваемыми H1b
  (LLMConfigManager per-process drift) и H7b (stale env / API-key в
  bot-процессе).
- **Нужно от пользователя/оператора:** (a) сверить
  `_exec_get_llm_config` (бот) и `get_llm_config` (MCP) — Шаг 0-bis;
  (b) `tool_execution_error tool=ask_question` + traceback из лога бота
  (Шаг 0).
- Per-process state в `LLMConfigManager`: `tg_parser/config/llm_config.py`
  (runtime overrides не пересекают process boundary).
- 60-секундный budget tool-loop'а: `tg_parser/bot/agent.py:44–48`
  (`__init__ timeout=60.0`) → `tg_parser/bot/tools.py:784–787`
  (`asyncio.wait_for(executor, timeout=...)`).

---

### BUG-007 — Read-tool'ы тихо отдают `total: 0` при невалидном/опечатанном `channel_id`, без suggestion'ов и fuzzy-match: пользователь не может отличить «канал отсутствует» от «опечатка в имени»

| Поле | Значение |
|---|---|
| **Severity** | Medium (UX-ловушка, маскирует другие баги — например, в исходном трассе BUG-003 21:39:07 typo в имени `AgeManagement` vs `AgeManagment` создавал иллюзию сломанной `@`-нормализации; данные не повреждаются, но диагностика чужих багов становится сильно дороже из-за этого confound'а) |
| **Status** | `resolved (Session F, 2026-04-29; deployed 2026-04-30 15:12 UTC, squash SHA 88e4337)` — `_build_no_results_suggestion` (bot) + `_build_no_results_suggestion_mcp` (MCP) добавляют `available_channel_ids` (top-10 RBAC-filtered) + optional `suggestion` (difflib `get_close_matches` cutoff=0.7) в payload read-tool'ов на `total=0`. `prompts/bot.yaml` v1.2.0 учит LLM использовать эти поля для fallback'а вместо generic «не нашёл». **Production smoke 2026-04-30**: `темы канала AgeManagement` (typo, реальный канал `AgeManagment`) → suggestion «Возможно, имелся в виду 'AgeManagment'?» + 6 channels listed (BUG-007 production trigger confirmed closed). Side-effect: surfaced **BUG-009** (LLM hallucinates `add_channel(confirm=true)` on suggestion-confirmation reply) — distinct bug, mitigated via prompt v1.3.0 hotfix on VPS. См. § Updates → Session F (2026-04-30) deployed. |
| **Component** | `tg_parser/bot/tools.py` (read-tool executors: `_exec_list_topics`, `_exec_search`, `_exec_ask_question`, `_exec_get_cross_channel_stats`, `_exec_get_topic_details`); `tg_parser/mcp_server.py` (та же дыра — наследуется); `prompts/bot.yaml` (нет инструкции «при `total=0` сделай fallback-lookup доступных каналов») |
| **Discovered** | 2026-04-26, в ходе диагностики BUG-003 — пользователь набрал `AgeManagement`, в БД хранится `AgeManagment` (без `e` между `Manag` и `ment`). Bot и MCP оба молча отдали 0 тем без подсказки про typo. |
| **Linked** | **BUG-003** (этот баг маскировал BUG-003 на симптом-уровне, см. BUG-003 § Update 23:35 / 23:39); BUG-002 (statelessness усугубляет — пользователь не может сказать «возьми канал из своего предыдущего ответа»); БД-инвариант — допустимо ли в `add_channel` сохранять опечатанный `username` (отдельный data-quality вопрос). |
| **Planned fix** | ✅ landed in **Session F** (read-hardening батч, 2026-04-29) → `docs/notes/START_PROMPT_FIX_READ_HARDENING_BUG003_005B_007_2026-04-29.md` (suggestion-emit + system-prompt teach; storage-side fuzzy-match deferred per D-5 в TD-storage-jsonb-channel-id) |

#### Symptoms

```
Alex: перечисли основные темы канала AgeManagement     [23:35:06]
Bot:  Я не нашел никаких тем для канала "AgeManagement". Возможно,
      канал еще не был обработан или не содержит достаточно контента
      для извлечения тем.                              [23:35:08]

Alex: перечисли основные темы канала @AgeManagement    [23:35:19]
Bot:  Я не нашел никаких тем для канала @AgeManagement. Возможно,
      канал еще не был обработан или в нем нет извлеченных тем.
                                                       [23:35:21]
```

При этом в БД:

```
list_channels() → "channel_id": "AgeManagment", "topics_count": 75
list_topics(channel_id="AgeManagment") → 75 тем (рабочая запись)
```

То есть данные на месте, но пользователь видит «канал не обработан» и
на этом застревает: нет fuzzy match, нет suggestion'а, нет фоллбэка
на `list_channels()`.

#### Root cause

Композитный, три слоя:

##### 1. Storage: exact-match LIKE без fuzzy

`topic_card_repo.list_by_channel` (`tg_parser/storage/sqlalchemy/topic_card_repo.py:130–143`)
делает `WHERE sources::text LIKE '%"{channel_id}"%'`. Это exact-match
с граничными кавычками — никакой толерантности к опечаткам.

##### 2. Tool executor: возвращает голый `{total: 0, items: []}`

`_exec_list_topics` (`tg_parser/bot/tools.py:854–906`) при `total=0` не
прикладывает к result'у:
- `available_channel_ids` (список реально подключённых каналов),
- `did_you_mean` (Levenshtein-кандидаты ≤ 2 по имени),
- никакого hint'а вообще.

То же для `_exec_search`, `_exec_ask_question`, `_exec_get_cross_channel_stats`,
`_exec_get_topic_details`.

##### 3. System prompt: не учит делать fallback-lookup

`prompts/bot.yaml:30–43` не содержит инструкции вида:

> Если read-tool вернул `total: 0` для конкретного `channel_id`,
> вызови `list_channels()` и сравни написание; если есть похожий канал,
> предложи его пользователю как «возможно, вы имели в виду …».

Без этой инструкции LLM просто транслирует «0 тем» как пользователю-факт,
не пытаясь докрутить.

#### Why CI not caught

- Нет integration-теста, который покрывал бы «typo-сценарий» —
  обращение к каналу, отличающемуся на 1–2 буквы от реально подключённого.
- Юнит-тесты `_exec_list_topics` (если они есть) проверяют happy-path
  с заведомо корректным `channel_id`.
- Любой LLM-клиент тоже эту проблему не ловит автоматически: Gemini /
  Claude ни в коем случае не угадывают canonical-форму при опечатках —
  они стрипают `@`, но не делают spell-check.

#### Predicted fix

##### A. Минимальный (одна правка в `_exec_list_topics`, сразу применима ко всем read-tool'ам через общий helper)

При `total == 0` (или `len(items) == 0`):

```python
if total == 0 and channel_id:
    available = await proc_repo.list_active_channel_ids()
    closest = _fuzzy_closest(channel_id, available, max_distance=2)
    return {
        "total": 0,
        "offset": offset,
        "limit": limit,
        "has_more": False,
        "items": [],
        "available_channel_ids": available,
        "did_you_mean": closest,  # list[str], отсортирован по близости
    }
```

`_fuzzy_closest` — простой Levenshtein через стандартную либу (например,
`rapidfuzz` — уже потенциально в deps; иначе `difflib.get_close_matches`
из stdlib без новых зависимостей).

##### B. Дополнить `prompts/bot.yaml` инструкцией

```
- Если read-tool возвращает total=0 для конкретного channel_id и
  поле did_you_mean не пустое, обязательно покажи пользователю:
  «Канал X не найден. Возможно, вы имели в виду: <did_you_mean>?»
- Если did_you_mean пуст, но available_channel_ids не пуст,
  покажи: «Канал X не подключён. Доступные каналы: <available_channel_ids>».
```

##### C. Симметрично в `mcp_server.py`

Те же поля `available_channel_ids` / `did_you_mean` в JSON-ответе MCP-tool'а.
Не-LLM-клиенты (curl / автоматизации) тогда сами решают, как с этим
работать.

#### Tests to add

1. **Unit:** `_exec_list_topics(channel_id="AgeManagement")` (где в БД
   только `AgeManagment`) → `did_you_mean == ["AgeManagment"]`.
2. **Unit:** `_exec_list_topics(channel_id="totally_unknown_channel")` →
   `did_you_mean == []`, `available_channel_ids == [<все подключённые>]`.
3. **Unit:** для `_exec_search`, `_exec_ask_question`,
   `_exec_get_cross_channel_stats`, `_exec_get_topic_details` — те же
   три проверки.
4. **Integration:** отправить боту «темы канала AgeManagement» — bot
   должен показать «Возможно, вы имели в виду AgeManagment».

#### Workaround (текущий)

Пользователь спрашивает «список каналов»:

```
Alex: какие каналы доступны?
Bot:  Доступны каналы: AgeManagment, Lab4health, LongevityClub,
      genotek, labdiagnostica_logical.
Alex: перечисли темы канала AgeManagment    (без typo)
Bot:  <75 тем>
```

Помогает, но требует от пользователя помнить, что при «странном пустом
ответе» нужно сначала запросить список каналов.

#### Notes / status updates

- Severity Medium даже при low data-impact: основной вред — это
  **диагностический confound**. В нашей сегодняшней сессии исходный
  трасс BUG-003 (21:39:07) **дважды** перекластеризовывался: сначала
  в Update 23:28 как «подтверждение `@`-asymmetry», потом в Update
  23:35 как опровержение, потом в Update 23:39 как реальный `@`-bug
  через прямой MCP. Если бы этого confound'а не было, диагностика
  BUG-003 заняла бы 3 минуты вместо 90.
- Data-quality замечание: канал в БД хранится как `AgeManagment`. Это
  либо реальное имя в Telegram (некоторые публичные каналы действительно
  имеют typo в username — это допустимо), либо опечатка при `add_channel`.
  Перепроверить на этапе фикса BUG-007: если опечатка — потребуется
  дополнительный фикс data-quality (`pause_channel` старый, `add_channel`
  правильный, `remove_channel` старый).

#### Artifacts

- Read-tool executors без fuzzy-fallback'а:
  `tg_parser/bot/tools.py:802` (ask_question), `:827` (search),
  `:854` (list_topics), `:909` (get_topic_details), `:1038`
  (get_cross_channel_stats).
- Симметричные MCP-обёртки: `tg_parser/mcp_server.py:752–852`
  (read-tool'ы).
- Storage без fuzzy: `tg_parser/storage/sqlalchemy/topic_card_repo.py:130–143`.
- System prompt без fallback-инструкции: `prompts/bot.yaml:30–43`.
- Триггер-канал: `AgeManagment` (в БД) vs `AgeManagement` (грамматически
  правильное английское) — расстояние Левенштейна = 1 (вставка одной 'e').

---

### BUG-008 — MCP remote endpoint hang: `list_channels` через `CallMcpTool` не вернул response за ~3.5 ч

| Поле | Значение |
|---|---|
| **Severity** | **pending** — нужен root-cause spike. Потенциально Medium-High если повторится: hang в production blocks любой client-flow ходящий через MCP read-tool'ы (Cursor/Claude/etc.). На момент фиксации воспроизведён один раз, root cause неизвестен. |
| **Status** | `open` (root cause unknown, repro flaky) |
| **Component** | MCP remote endpoint `https://mcp.tgp.efimov.mobi/mcp` (или MCP client transport / shim) — точный слой не локализован. Кандидаты: `tg_parser/mcp_server.py` runtime, MCP SDK transport (SSE / stdio), Cursor MCP client cache, OAuth token refresh. |
| **Discovered** | 2026-04-28 ~11:18 UTC+4, в ходе Session D sanity-step 4 (cleanup orphan placeholder channels). `CallMcpTool` для `list_channels` повис без response. Tool-call сидел в pending state ~3.5 ч до ручного interrupt. |
| **Linked** | BUG-001 (Session C — недавний deploy `mcp.tgp.efimov.mobi` 2026-04-27 19:00 UTC; новые auth code-paths могли создать lock); прецедент частичных проблем — BUG-005-A (генерик `internal error` без диагностики) показал, что MCP-shim слабо логирует error states. |
| **Planned fix** | **Diagnostic spike** в отдельном таске (~1 ч): (1) попытаться воспроизвести (10× consecutive `list_channels` calls); (2) собрать `docker logs tg_parser_mcp` за окно incident'а 11:18-14:50 UTC+4; (3) проверить metrics: outbound DB-connection pool, in-flight requests, OAuth refresh activity; (4) проверить Cursor-side MCP cache. Если воспроизводится — bump severity, открыть detailed runbook. Если flaky — оставить open с findings + monitoring hook. |

#### Symptoms

В Session D окне (Cursor IDE) tool call:

```
CallMcpTool(server="project-0-TG_parser-tg-parser", toolName="list_channels", arguments={})
→ pending → pending → ... → pending [~3.5 hours] → manual interrupt
```

Параллельно direct SQL через SSH (`docker exec tg_parser_postgres psql ...`) отработал за < 1 с и вернул корректный список каналов вкл. `test_channel_123`. Cleanup был выполнен напрямую через SQL UPDATE без обращения к MCP.

#### Reproduction (flaky)

Не воспроизводится стабильно. Single occurrence в Session D на временно́м окне 11:18-14:50 UTC+4. Direct curl против `https://mcp.tgp.efimov.mobi/mcp` (smoke из Session C, 19:00 UTC) — отрабатывал за секунды.

#### Hypotheses (для diagnostic spike)

| ID | Hypothesis | Где смотреть |
|---|---|---|
| **HG-1** | Lock в MCP server runtime (`mcp_server.py`) — long-running query держит advisory lock или DB connection pool drained. | `docker logs tg_parser_mcp`, `pg_stat_activity` на VPS. |
| **HG-2** | Cursor-side MCP client cache stale (после Session C re-deploy). Client держит open SSE-stream который сервер уже закрыл, но не перподключается. | Cursor MCP cache reset; перезапуск Cursor; `tcpdump` на VPS edge. |
| **HG-3** | OAuth token refresh deadlock — Cursor получил expired bearer, попытался refresh, server держит token-validation lock. | MCP server auth middleware logs; OAuth refresh trace. |
| **HG-4** | Network blip между Cursor host и VPS (DNS, edge proxy). MCP transport не имеет explicit timeout → ждёт бесконечно. | `traceroute`, `mtr` от Cursor host к VPS; nginx/edge logs. |
| **HG-5** | Race в новых code path Session C (`_extract_authenticated_user_id` → `auth_context_var`). Если contextvar не propagated в async-task → infinite await. | `grep auth_context_var` в Session C diff; добавить `asyncio.wait_for` timeout. |

#### Mitigation (in-place)

- Direct SQL fallback через `docker exec tg_parser_postgres psql` отработал за секунды. Добавить в operator runbook'и: «Если MCP завис на read-tool — direct SQL (read-only) допустим как админ-fallback».
- В Session D код-changes на MCP не трогали (только bot side), значит regression от Session D исключён. Hang структурно existed до Session D.

#### Notes

- На момент Session D landing'а (28.04 13:00) — это **TD-mcp-hang**, не bug. После пользовательского ревью переклассифицирован в **BUG-008** (severity pending) для visibility и планирования diagnostic spike'а отдельным таском вместо втискивания в Session F (которая про tool-executor + prompt, не runtime).

---

### BUG-025 — Bot `unsubscribe_watchlist` does not pre-validate UUID format; LLM passing watchlist name as `interest_id` leaks raw asyncpg traceback

| Поле | Значение |
|---|---|
| **Severity** | **Medium** (UX: user sees raw asyncpg parser error `invalid input for query argument $1: '<name>' (invalid UUID '<name>': badly formed hexadecimal UUID string)` instead of a clean «interest_id must be a UUID, use list_watchlists to find the ID»; LLM-driven retries thrash the same error 3-4 times per session as observed in 2026-05-22 watch dialog (3 occurrences in 25-minute window: `_smoke_post91_…` 19:57:53Z, `S3 smoke` 19:59:15Z, `wl_bot_watch_smoke` 20:07:41Z); structural cause (LLM unconditioned to resolve name→UUID, executor unconditioned to reject non-UUID) compounds — every confused user re-triggers the same trace; no data correctness impact) |
| **Status** | `open` (filed 2026-05-23 during Wave 1 step 3 24h watch closure analysis — see [`WATCH_24H_BOT_ACTIONS_2026-05-22.md` § 6 Observations](WATCH_24H_BOT_ACTIONS_2026-05-22.md)) |
| **Component** | `tg_parser/bot/tools.py` `_exec_unsubscribe_watchlist` (~ line 2834-2877) — accepts any string as `interest_id` and forwards directly to `service.delete_interest_for_user` → `self.interest_repo.get(interest_id)` → asyncpg SQL with `interest_id::uuid` param; no `uuid.UUID(interest_id)` pre-validation; **same gap likely in** `_exec_unsubscribe_digest`, `_exec_get_watchlist_matches`, and MCP-side `unsubscribe_watchlist` / `unsubscribe_digest` / `get_watchlist_matches` handlers (audit needed); secondary contributor: `prompts/bot.yaml` does not include a HARD RULE «to delete a watchlist by name, always call `list_watchlists` first and use the returned UUID» — LLM (Gemini) happily passes the name as `interest_id` directly |
| **Discovered** | 2026-05-22T19:57:53Z (23:57 MSK 22-05), Alexander, Telegram-бот в проде; reproduced 3× consecutively within a 25-min window in the same dialog (different names — `_smoke_post91_20260522T174541Z`, `S3 smoke`, `wl_bot_watch_smoke` — same root cause); analysed during 2026-05-23 closure of WATCH_24H bot action journal |
| **Linked** | BUG-009 / TD-bot-confirm-coverage-completeness (write-tool confirm coverage decision matrix — `unsubscribe_watchlist` is currently NOT in `_WRITE_TOOLS_REQUIRING_CONFIRM` set per `tg_parser/bot/tools.py:48-58`; adding it would gate destructive operations behind a preview that could surface «target candidates» before the SQL hit, mitigating this bug indirectly); BUG-022 (subscribe-tool idempotency — adjacent service-surface issue); F11 `delete_interest_for_user` contract in [`watchlist_service.py:676-698`](../../tg_parser/services/watchlist_service.py); F11 watch-interest model in `user-tg-parser` MCP server description |
| **Symptoms (production trace, 2026-05-22 23:57 MSK / 19:57:53Z)** | User: «Удали watchlist _smoke_post91_20260522T174541Z» → bot `agent_tool_call`: `{"tool": "unsubscribe_watchlist", "args": {"interest_id": "_smoke_post91_20260522T174541Z"}}` → 27 ms later `tool_execution_error` event with `exc_info=true` (asyncpg `InvalidTextRepresentationError`: `invalid input for query argument $1: '_smoke_post91_20260522T174541Z' (invalid UUID …)`) → Gemini paraphrased error back to user including the raw asyncpg message. Same trace repeats at 19:59:15Z with `interest_id="S3 smoke"` (Gemini paraphrased as «ID должен быть в формате UUID») and at 20:07:41Z with `interest_id="wl_bot_watch_smoke"`. |
| **Root cause (HIGH confidence — code path traced end-to-end)** | (1) `_exec_unsubscribe_watchlist` in `tg_parser/bot/tools.py` does `interest_id = (args.get("interest_id") or "").strip()`; only check is `if not interest_id: return {"error": "interest_id is required"}` — no UUID format validation. (2) `WatchlistService.delete_interest_for_user` (`watchlist_service.py:690`) calls `await self.interest_repo.get(interest_id)` — SQLAlchemy / asyncpg eagerly parses the bind parameter as `UUID` type before query execution; the parse fails before any row is fetched, raising `InvalidTextRepresentationError`. (3) `_exec_unsubscribe_watchlist` does not catch this exception class explicitly — falls through to the generic `execute_tool` typed-catch (added in Session F per BUG-005-B) which produces `error_class` payload — but the LLM still sees the raw asyncpg message. (4) The Gemini LLM has no system-prompt instruction to resolve name → UUID via `list_watchlists` before calling `unsubscribe_watchlist` (verified: `prompts/bot.yaml` last touched v1.4.0 Session G — no `unsubscribe_*` semantics section). |
| **F4-B Core relationship** | **NOT a F4-B regression.** F4-B Core landed workspace scoping for read tools; `unsubscribe_watchlist` executor surface unchanged since F11 landing. Pre-existing structural gap surfaced by 2026-05-22 watch session (bot-side execution journal in `WATCH_24H_BOT_ACTIONS_2026-05-22.md`). |
| **Why CI didn't catch** | (a) `_exec_unsubscribe_watchlist` unit tests cover happy path (valid UUID, owner match) and permission-denied path; no test covers «invalid UUID format input» → assert `error_class="InvalidUUID"` and no asyncpg traceback. (b) `tests/test_bot_tools_*` mock the underlying repo / service layer, so the SQL parse error never fires in CI even on bad input. **Closure plan**: parametrized test `_exec_unsubscribe_watchlist({"interest_id": <not-a-UUID>})` for ≥ 5 invalid forms (name, partial UUID, empty-after-strip whitespace, integer-as-string, name with leading underscore) → assert `error_class="InvalidUUID"`, `error` matches `re.compile(r"interest_id must be a valid UUID")`, **no traceback emitted**. Symmetric tests for `_exec_unsubscribe_digest`, `_exec_get_watchlist_matches`, and MCP-side equivalents. |
| **Proposed fix** | **Layer A (executor pre-validation, ~5 LOC per call-site × 6 = 30 LOC + 5-10 tests):** add `try: uuid.UUID(interest_id) except ValueError: return {"error_class": "InvalidUUID", "error": "interest_id must be a valid UUID (e.g. 604632d4-23e9-4e50-a992-80aeefb9cf74). Use list_watchlists to find the ID by name."}` at the top of `_exec_unsubscribe_watchlist` and 5 sibling executors. **Layer B (prompt v1.5.0, ~5-line section):** add HARD RULE in `prompts/bot.yaml` under «UUID-typed arguments»: «To delete / inspect a watchlist or digest by name, ALWAYS call `list_watchlists` / `list_digests` first and use the returned `id` (UUID) — NEVER pass the name as `interest_id` / `subscription_id`». **Layer C (defense-in-depth, optional ~10 LOC):** wrap `service.delete_interest_for_user` to catch `InvalidTextRepresentationError` and translate to typed error. Recommended scope: A + B in single PR; C deferred unless Layer A misses an executor. Bundle naturally with TD-bot-confirm-coverage-completeness if that batch lands first (adding `unsubscribe_*` to `_WRITE_TOOLS_REQUIRING_CONFIRM` would surface a preview before the executor fires, giving the LLM another chance to resolve the name). |
| **Workaround (current, in-place)** | (1) User must explicitly pass the UUID — quoted («Удали watchlist "604632d4-…"») or unquoted; the bot accepts both. (2) If user types a name, the LLM sometimes auto-recovers by calling `list_watchlists` first (observed at 20:00:45Z for «Idem» → bot suggested UUID candidate, see also BUG-026 for the continuation failure mode that follows). (3) Operator fallback: use MCP `unsubscribe_watchlist` from Cursor with a UUID copied from `list_watchlists`. |
| **Evidence** | Bot log (`tg_parser_bot` container, 2026-05-22T19:57:53Z): `{"tool": "unsubscribe_watchlist", "turn": 0, "args": {"interest_id": "_smoke_post91_20260522T174541Z"}, "event": "agent_tool_call", "request_id": "46b330c8", ...}` → 27 ms later: `{"tool": "unsubscribe_watchlist", "exc_info": true, "event": "tool_execution_error", "request_id": "46b330c8", "level": "error", ...}`. Two additional traces at 19:59:15Z (`"S3 smoke"`) and 20:07:41Z (`"wl_bot_watch_smoke"`). DB cross-check confirms the watchlists exist with the corresponding UUIDs in `watch_interests` table (no orphan / corruption — purely an input-validation issue at the bot/executor boundary). |
| **Planned fix** | TD-bot-uuid-validation-write-tools; bundle with next bot-side touch (or pair with TD-bot-confirm-coverage-completeness if that lands first). |

---

### BUG-026 — Bot context loss on standalone UUID continuation after «did you mean X?» bot prompt (write-tool target IDs analogue of BUG-011)

| Поле | Значение |
|---|---|
| **Severity** | **Low** (UX: user pastes just the UUID after the bot proposed it as a candidate in the preceding turn; bot responds «Я не понимаю, что означает …»; user must re-type the full command «Удали watchlist "<UUID>"» — one extra turn per intent; observed once in 2026-05-22 watch dialog; not a data-loss concern; structural analogue to read-side BUG-011 which was closed in Session H — same root-cause class (write-tool target IDs lack FSM-tracked continuation context), different surface) |
| **Status** | `open` (filed 2026-05-23 during Wave 1 step 3 24h watch closure analysis — see [`WATCH_24H_BOT_ACTIONS_2026-05-22.md` § 6 Observations](WATCH_24H_BOT_ACTIONS_2026-05-22.md)) |
| **Component** | `tg_parser/bot/tools.py` (`_READ_TOOLS_TRACKED_FOR_CONTEXT` frozenset at lines 67-77 covers read-tool `channel_id` continuation per BUG-011 Session H — no symmetric mechanism for write-tool target IDs like `interest_id` / `subscription_id` / `workspace_id`); `tg_parser/bot/handlers.py` (agent_loop dispatch — does not detect «bot just emitted a candidate-UUID suggestion + user replied with just that UUID» → no FSM state arming); `prompts/bot.yaml` (no explicit instruction to LLM about handling standalone-UUID continuation messages) |
| **Discovered** | 2026-05-23T00:01:05Z (00:01 MSK 23-05), Alexander, Telegram-бот в проде; reproduced once during 2026-05-22 watch dialog (turn sequence at 20:00:49Z → 20:01:05Z → 20:01:32Z documented in detail below) |
| **Linked** | BUG-011 (read-context analogue — `channel_id` continuation; closed in Session H per `_READ_TOOLS_TRACKED_FOR_CONTEXT`); BUG-025 (delete-by-name UUID validation — adjacent UX class on the same dialog turn surface); BUG-004 (paginated-list continuation — closed Session D via `PaginationFlow` FSM state); TD-bot-confirm-coverage-completeness (BUG-009 Session G — `unsubscribe_*` not in confirm set; if added, the «preview shows candidate, user confirms» flow would naturally handle this case via FSM `ConfirmFlow`) |
| **Symptoms (production trace, 2026-05-23 00:00-00:02 MSK / 20:00-20:02Z)** | (1) 20:00:44Z user: «удали watchlist Idem» → 20:00:45Z bot `agent_tool_call(list_watchlists)` → bot response listed candidates including `abfbfbf9-8068-480f-8732-55976aa59d76` (Idem 1779449293) and asked user to confirm by ID. (2) 20:01:05Z user: paste of just `abfbfbf9-8068-480f-8732-55976aa59d76` (text_length=36 — UUID only, no verb) → bot log shows `gemini_response` with 47 output tokens, **NO `agent_tool_call` event** → bot responded «Я не понимаю, что означает '<UUID>'» (user-reported wording). (3) 20:01:32Z user re-typed «Удали watchlist "abfbfbf9-…"» (text_length=54 — explicit verb + quoted UUID) → bot `agent_tool_call(unsubscribe_watchlist, interest_id="abfbfbf9-…")` → SUCCESS (DB `updated_at=20:01:34.111604+00`). |
| **Root cause (HIGH confidence — agent loop + prompt walk)** | (1) Bot's agent loop (`tg_parser/bot/agent.py`) reconstructs `contents` per-turn from `[{role:user, parts:[{text:<user_message>}]}]` — no conversation history is propagated between turns (per the original BUG-002 root cause; closed structurally via FSM for confirm flow but NOT for arbitrary continuation). (2) Standalone UUID has no syntactic anchor that maps to a tool — Gemini without context can't infer «this is a continuation of the unsubscribe_watchlist intent from the previous bot suggestion». (3) `prompts/bot.yaml` lacks a HARD RULE «if user replies with just a UUID after you proposed a candidate, treat it as confirmation of the previous suggested action». (4) `_READ_TOOLS_TRACKED_FOR_CONTEXT` covers `ask_question`/`search_knowledge_base`/`list_topics`/`get_cross_channel_stats` (channel_id-bearing read tools) but the mechanism is read-tool-specific — it tracks the most-recent successful `channel_id` arg, not «I just emitted a candidate to the user for X-write-tool». (5) `_TOOLS_NEEDING_BOT_CONTEXT` (lines 29-33) tracks which tools need the bot instance for upload — orthogonal mechanism. |
| **F4-B Core relationship** | **NOT a F4-B regression.** Read-side context (BUG-011) was closed in Session H; write-side target-ID context was out of scope for that session (BUG-011 § Symptoms scoped to channel-context preservation for `list_topics` / `ask_question`). Pre-existing structural gap surfaced for the first time by 2026-05-22 watch dialog interactive cleanup sequence. |
| **Why CI didn't catch** | (a) No `tests/test_bot_fsm.py` or `test_bot_agent.py` case covers the «turn N bot emits candidate UUID via list_watchlists; turn N+1 user sends just the UUID; turn N+1 should resume previous intent» contract. (b) Pre-existing tests for Session H read-context cover `channel_id` continuation only. **Closure plan**: integration test `test_bug026_standalone_uuid_after_suggestion_resumes_intent` — simulate turn 1 «удали watchlist Foo» → mock `list_watchlists` returns candidates → bot response contains UUID; simulate turn 2 just the UUID text → assert `agent_tool_call` for `unsubscribe_watchlist(interest_id=<that UUID>)` (NOT «Я не понимаю» fall-through). Symmetric tests for `unsubscribe_digest`, `delete_workspace`, `remove_workspace_source`. |
| **Proposed fix** | **Option A (smallest, prompt-only ~10 LOC `prompts/bot.yaml` v1.5.0):** add HARD RULE: «If your previous turn emitted a UUID candidate and the next user message is just that UUID (with optional surrounding whitespace), treat it as confirmation of the previously-suggested action — call the previously-suggested write-tool with that UUID as the appropriate argument (`interest_id` / `subscription_id` / `workspace_id` per context).» Cheap + risk-bounded; relies on LLM discipline (similar to original BUG-002 v1.1.0 confirmation-semantics section). **Option B (structural, ~50 LOC + 3-5 tests):** extend FSM with `SuggestionFlow` StatesGroup tracking `{tool_name, target_id_field, candidate_id}` armed when bot's previous turn emitted a list_* result for a write-tool ambiguity; on next-turn standalone-UUID input, fire `_exec_<tool_name>(<target_id_field>=<candidate_id>)` deterministically without LLM (mirrors Session D `_handle_confirmation_response` pattern). **Recommended:** Option A initially (low risk, surfaces if LLM-discipline is sufficient); Option B if A fails to close per 2026-05-29 follow-up smoke. |
| **Workaround (current, in-place)** | User must include an explicit verb («Удали watchlist "<UUID>"», «отпиши от <UUID>») in the continuation turn — surfaces in the bot log as `text_length ≥ 50` and reliably triggers `unsubscribe_watchlist(interest_id=<UUID>)`. Documented in `WATCH_24H_BOT_ACTIONS_2026-05-22.md` § 6.1 as observed expected-success path. |
| **Evidence** | Bot log (`tg_parser_bot` container) turn sequence at 20:00:45Z → 20:01:05Z → 20:01:32Z; turn 2 (20:01:05Z `user_message text_length=36` + `gemini_response output_tokens=47`) shows zero `agent_tool_call` events for this `request_id` (`6d6eb687`) — definitive proof that LLM did not resume intent. Turn 3 (20:01:32Z `user_message text_length=54` + `agent_tool_call(unsubscribe_watchlist, interest_id="abfbfbf9-…")`, request_id `6a41132c`) shows the workaround working. |
| **Planned fix** | TD-bot-suggestion-continuation-context; prompt-only Option A bundle with next `prompts/bot.yaml` touch; consider structural Option B in next bot-FSM sprint if Option A insufficient. |

---

### BUG-027 — Bot soft-delete returns ambiguous «Возможно, он уже неактивен» message conflating «not found» and «already inactive» service returns

| Поле | Значение |
|---|---|
| **Severity** | **Low** (UX clarity: when `unsubscribe_watchlist` is called on a watchlist that exists in DB but is already `is_active=false` (previously soft-deleted), service returns `(deleted=False, error="delete failed (already inactive?)")` per `watchlist_service.py:697`; bot paraphrases as «Не удалось удалить … Возможно, он уже неактивен» — parenthesised question wording is ambiguous: a user reading it doesn't know whether (a) the watchlist doesn't exist at all, (b) exists but is already inactive (the actual case in 2026-05-22 trace), or (c) some other failure; no data correctness impact, no retry storm, but operator UX is muddy when triaging cleanup loops; correlates with BUG-022 idempotency class — DELETE on already-deleted should be 204 No Content semantics, not «failed») |
| **Status** | `open` (filed 2026-05-23 during Wave 1 step 3 24h watch closure analysis — see [`WATCH_24H_BOT_ACTIONS_2026-05-22.md` § 6 Observations](WATCH_24H_BOT_ACTIONS_2026-05-22.md)) |
| **Component** | `tg_parser/services/watchlist_service.py` line 695-697 (`delete_interest_for_user` — `if not deleted: return False, "delete failed (already inactive?)"` — parenthesised question is the smoking gun); `tg_parser/storage/sqlalchemy/interest_repo.py` (the underlying `soft_delete` method that returns `False` when WHERE filter doesn't match — likely `WHERE id = … AND is_active = TRUE` so already-inactive rows return 0 rowcount → `soft_delete` returns False); `tg_parser/bot/tools.py` `_exec_unsubscribe_watchlist` (returns `{"error": "delete failed (already inactive?)"}` to LLM); `prompts/bot.yaml` (LLM paraphrases the error text to user) |
| **Discovered** | 2026-05-22T19:58:32Z (23:58 MSK 22-05), Alexander, Telegram-бот в проде; reproduced once during 2026-05-22 watch dialog; analysed 2026-05-23 during closure |
| **Linked** | BUG-022 (subscribe-tool idempotency — adjacent: idempotency semantics for both subscribe and unsubscribe should be unified per ADR 0009); F11 watchlist soft-delete contract in `delete_interest_for_user` (`watchlist_service.py:676-698`); F6 digest equivalent (`digest_service.py` `delete_subscription_for_user` likely has identical pattern — audit needed); HTTP API `/api/v1/watchlists/<id> DELETE` semantics (REST convention: 204 on second delete is idempotent-correct; current backend likely returns 404/422 to match service-layer behavior — verify) |
| **Symptoms (production trace, 2026-05-22 23:58 MSK / 19:58:32Z)** | User: «удали watchlist 1eac40cd-…» → bot `agent_tool_call: {"tool": "unsubscribe_watchlist", "args": {"interest_id": "1eac40cd-0f30-4c8e-8f88-9cdbe6b19035"}}` → bot paraphrased response: «Не удалось удалить watchlist '1eac40cd-…'. Возможно, он уже неактивен». DB cross-check at 2026-05-23 12:50Z: row exists with `id=1eac40cd-…`, `title=_smoke_post91_20260522T174541Z`, `is_active=f`, `created_at=2026-05-22 17:45:41.701033+00`, `updated_at=2026-05-22 17:45:43.658683+00` (≈ 6 hours before the user's 19:58 unsubscribe attempt — was soft-deleted by a prior smoke run). The user's confused user-flow («it might be inactive? but I'm asking you to inactivate it») demonstrates the ambiguity. |
| **Root cause (HIGH confidence — code path traced end-to-end)** | (1) `delete_interest_for_user` (`watchlist_service.py:690`) first calls `existing = await self.interest_repo.get(interest_id)` — for already-inactive rows this returns the row (no `is_active` filter in get_by_pk lookup), so `existing is None` branch is NOT taken. (2) Permission check passes (admin). (3) `deleted = await self.interest_repo.soft_delete(interest_id)` is called — implementation likely has `WHERE id = … AND is_active = TRUE` clause, so already-inactive rows match 0 rows → `deleted=False`. (4) Service returns `(False, "delete failed (already inactive?)")` — the parenthesised question expresses uncertainty even at the service layer. (5) Bot executor `_exec_unsubscribe_watchlist` returns `{"interest_id": …, "deleted": False, "error": "delete failed (already inactive?)"}` to LLM. (6) Gemini paraphrases as «Возможно, он уже неактивен» — propagating the uncertainty to the user. **Better contract:** distinguish three states at service layer — `(deleted=True, error=None)` (real soft-delete happened), `(deleted=False, error="not_found")` (row absent from DB), `(deleted=False, error="already_inactive")` (row present but inactive — idempotent NO-OP, treat as success in idempotent flows). |
| **F4-B Core relationship** | **NOT a F4-B regression.** F11 service-layer wording predates F4-B Core by several months; F4-B Core touched workspace scoping but not watchlist delete semantics. Pre-existing UX gap surfaced by 2026-05-22 watch session (cleanup of orphaned smoke watchlists with mixed active/inactive state). |
| **Why CI didn't catch** | (a) `tests/test_watchlist_service.py` (if extant) covers happy-path delete (`is_active=True` row → `(True, None)`) and not-found delete (`existing is None` → `(False, "interest not found")`), but no test covers the «exists but already inactive» branch returning `(False, "delete failed (already inactive?)")` — the wording itself was never asserted. (b) Bot-layer tests use mocked service returning either deleted/not-found tuples — no third state. **Closure plan**: parametrized test `test_delete_interest_for_user_already_inactive_returns_typed_error` — fixture inserts an already-inactive row → assert service returns `(False, "already_inactive")` (NOT `"delete failed (already inactive?)"`). Companion bot-layer test asserting executor maps service `error="already_inactive"` to user-facing «Watchlist ID '<UUID>' is already inactive (soft-deleted previously); no action needed.». |
| **Proposed fix** | **Layer A (service-layer typed return, ~20 LOC):** add pre-check `if not existing.is_active: return False, "already_inactive"` in `delete_interest_for_user` between the permission check and the `soft_delete` call. Switch sentinel string from `"delete failed (already inactive?)"` to `"already_inactive"` for the structurally-impossible-to-reach branch (defense-in-depth). Symmetric change in `digest_service.delete_subscription_for_user`. **Layer B (bot executor mapping, ~5 LOC):** in `_exec_unsubscribe_watchlist`, when `error == "already_inactive"` return `{"interest_id": …, "deleted": False, "already_inactive": True, "message": "Watchlist is already inactive (soft-deleted previously); no action needed."}` — explicit positive shape rather than `error` field. **Layer C (prompt v1.5.0 ~3 lines):** update `prompts/bot.yaml` soft-delete semantics section: «If unsubscribe returns `already_inactive=True`, tell the user the watchlist was already removed and confirm no action was needed — DO NOT use uncertain wording like «possibly inactive».» **Recommended scope**: A + B + C in single PR (~30 LOC + 3 tests). Bundle with BUG-022 idempotency policy when ADR 0009 lands (per HANDOFF_POST_WAVE1_STEP2 sequencing — both are idempotency-class). |
| **Workaround (current, in-place)** | Operator should treat the «Возможно, он уже неактивен» message as confirmation that the watchlist is structurally absent from the active set — equivalent to delete-success for cleanup purposes. Cross-check with `list_watchlists` after the attempt — if the target UUID is not in the active list (or is in the inactive list with `is_active=false`), the cleanup goal is achieved despite the bot's uncertain wording. |
| **Evidence** | Bot log (`tg_parser_bot` container, 2026-05-22T19:58:32Z): `{"tool": "unsubscribe_watchlist", "turn": 0, "args": {"interest_id": "1eac40cd-0f30-4c8e-8f88-9cdbe6b19035"}, "event": "agent_tool_call", "request_id": "cfb1f1a5", ...}` — no `tool_execution_error` event (service returned cleanly, not an exception). DB cross-check (`SELECT id, title, is_active, updated_at FROM watch_interests WHERE id='1eac40cd-…'`): row exists, `is_active=f`, `updated_at=2026-05-22 17:45:43.658683+00` (≈ 6h before user's unsubscribe attempt — confirms «already inactive» case, not «not found»). |
| **Planned fix** | TD-watchlist-already-inactive-typed-error; bundle with BUG-022 idempotency-policy fix (ADR 0009). |

---

### BUG-028 — Digest cron task: `PromptLoader(prompts_dir=str(settings.prompts_dir))` resolves to literal path `None/digest.yaml` when `settings.prompts_dir is None` → daily digest delivery aborts with `PromptLoaderError`

| Поле | Значение |
|---|---|
| **Severity** | **High** (operational: every scheduled digest run fails — 100% delivery failure rate for any active `digest_subscriptions` row while `PROMPTS_DIR` env var is unset; surfaced once-per-cron-period until fixed; **no user notification of the failure** — error is logged at scheduler level only, end-user just sees no digest arrive; structural cause exists in prod since F6 landing 2026-04-19 but only fires on days with at least one active subscription whose cron tick lands while we observe; production daily digest `digest_94483db9` (prod endocrinology) failed at `2026-05-23T06:00:00Z` = `09:00 MSK` during Wave 1 step 3 24h watch — see [`WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md` § Verdict — Open items](WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md)) |
| **Status** | ✅ **`resolved`** (hotfix PR [#92](https://github.com/AlexEfimov/TG_parser/pull/92) merged 2026-05-23T16:57:45Z squash [`26d03a5`](https://github.com/AlexEfimov/TG_parser/commit/26d03a5b9e40b64fa7f75f3a3de5576c67fca8ef); deployed to prod VPS `mcp.tgp.efimov.mobi` 2026-05-23 ≈19:23 UTC; see «Update 2026-05-23 — PR #92 landed → BUG-028 RESOLVED» closure row below). Filed 2026-05-23 during Wave 1 step 3 24h watch closure analysis — see [`WATCH_24H_BOT_ACTIONS_2026-05-22.md` § 6](WATCH_24H_BOT_ACTIONS_2026-05-22.md) — log-scan tally of `tg_parser_bot` over watch window surfaced this as the single non-BUG-025 error event. |
| **Component** | `tg_parser/services/scheduler_service.py:560` (`prompt_loader = PromptLoader(prompts_dir=str(settings.prompts_dir))` — `str(None) == "None"` Python literal); `tg_parser/processing/prompt_loader.py:73-87` (`PromptLoader.__init__` does `Path(prompts_dir)` without `None`-check when `prompts_dir is not None` argument is provided — `"None"` string is treated as a literal directory name and `Path("None")` evaluates to a non-existent relative path); `tg_parser/config/settings.py:287` (`prompts_dir: Path \| None = None` — default is `None`, not `Path("prompts")`); deployed VPS env has no `PROMPTS_DIR` override (verified via `docker exec tg_parser_bot printenv \| grep -i prompt` → empty); `digest.yaml` exists in `/app/prompts/digest.yaml` (2656 bytes, last touched 2026-04-19) but is never reached due to the wrong path |
| **Discovered** | 2026-05-23T06:00:00.123603Z (09:00 MSK) — daily digest cron tick on prod for subscription `digest:94483db9-9351-4f99-9aec-46949d9ddd09` (prod endocrinology); fired once during 2026-05-22 → 2026-05-23 watch window; surfaced via `docker logs tg_parser_bot \| grep error` in closure-session log scan (4 total error events over 22h: 3× BUG-025 + 1× this BUG-028) |
| **Linked** | F6 scheduled-digest contract (`docs/plans/F6_SCHEDULED_DIGESTS_PLAN.md`, `docs/prompts/F6_SCHEDULED_DIGESTS_PROMPT.md`); `PromptLoader` REQUIRED_PROMPT_STAGES post-TD-03c fail-loud contract (`prompt_loader.py:129-134` — correct behavior: refuses to silently fall back to empty defaults for required stages); ADR 0007 (MCP dispatch — adjacent: scheduler_service.py is the same module that runs dispatched pipelines, but this bug is independent of dispatch path); BUG-022 (subscribe idempotency — adjacent: also touches digest_service surface but at create-time, not run-time) |
| **Symptoms (production trace, 2026-05-23 09:00 MSK / 06:00:00.123603Z)** | Scheduler-emitted error: `{"task_id": "digest:94483db9-9351-4f99-9aec-46949d9ddd09", "error": "missing prompt for required stage='digest': YAML at None/digest.yaml did not provide a non-empty system.prompt and the built-in default is empty", "exc_info": true, "event": "cron_task_failed", "level": "error", "timestamp": "2026-05-23T06:00:00.123603Z"}`. End user (subscriber) receives **no digest message** for the day; **no error notification** in their Telegram chat. Bot stays up, other tools work; next cron tick (next morning) will repeat the failure deterministically. Cross-check: `docker exec tg_parser_bot ls -la /app/prompts/digest.yaml` confirms file exists and is readable; `printenv \| grep -i prompt` confirms no `PROMPTS_DIR` env override on prod. |
| **Root cause (HIGH confidence — code path traced + verified on prod)** | (1) `tg_parser/config/settings.py:287` declares `prompts_dir: Path \| None = None` with default `None`. (2) Prod VPS does NOT set `PROMPTS_DIR` env var (confirmed via `printenv` on `tg_parser_bot` container) — so `settings.prompts_dir is None` at runtime. (3) `scheduler_service.py:560` does `PromptLoader(prompts_dir=str(settings.prompts_dir))` — `str(None)` evaluates to the literal Python string `"None"`. (4) `PromptLoader.__init__` lines 79-83: `if prompts_dir is not None: self.prompts_dir = Path(prompts_dir)` — `"None"` is not `None`, so the if-branch fires and `self.prompts_dir = Path("None")` (a non-existent relative path). (5) `.load("digest")` resolves `path = Path("None") / "digest.yaml" == Path("None/digest.yaml")` — `.exists()` returns False; falls through to `_get_default("digest")` which returns `{}` (no built-in default for `digest` stage); `"digest" in REQUIRED_PROMPT_STAGES` is True (post-TD-03c contract); fail-loud raises `PromptLoaderError`. (6) `scheduler_service.digest_task` does not catch `PromptLoaderError` — bubbles up to scheduler wrapper which logs `cron_task_failed` and continues. **NB:** the same buggy line `PromptLoader(prompts_dir=str(settings.prompts_dir))` was authored 2026-04-19 (`410452a6`, F6 sprint, well before Wave 1 step 3); other call sites (`prompt_loader.py:464` `_default_loader = PromptLoader(prompts_dir=_settings.prompts_dir)` — passes `None` correctly without `str()` wrap; processing pipeline uses this default loader and works fine — that's why `processing.yaml` / `topicization.yaml` continued to load through `tg_parser` container). |
| **Wave 1 step 3 relationship (git diff adjudication)** | **NOT a step 3 regression** — verified via `git blame -L 555,565 tg_parser/services/scheduler_service.py` → buggy `str(settings.prompts_dir)` line authored `410452a6` (2026-04-19, F6 scheduled-digest sprint). Pre-existing latent bug in service-layer dispatch code, surfaced for the first time by 24h watch because (a) prod endocrinology digest subscription was the only active one when watch started, (b) its daily 09:00 MSK cron tick fell inside the watch window. `git show 5b828cf --stat -- tg_parser/services/scheduler_service.py` confirms step 3 commit 4/4 only added the idempotency-cleanup cron task (34 insertions, 0 modifications to existing digest_task code path). Adjudicated «new bug surfaced by watch» per Wave 1 step 2 precedent (`REVIEW_2026-05-14_WAVE1_STEP2_DONE.md` § 6 pattern), NOT «regression introduced by sprint». |
| **Why CI didn't catch** | (a) `tests/test_f6_scheduled_digests.py` likely injects a `PromptLoader` instance with a pytest tmp_path (test-isolation pattern) — the production `PromptLoader(prompts_dir=str(None))` call site is not exercised by unit tests because `digest_task` is bypassed in favor of `DigestService` direct construction with mock dependencies. (b) No integration test exercises the full scheduler dispatch path (`scheduler_service.digest_task → PromptLoader → load digest`) with `settings.prompts_dir=None`. (c) F6 sprint's PR review likely did not lint the `str(settings.prompts_dir)` defensive cast for `None`-handling (Python's `str(None) == "None"` is a well-known footgun, but the call site was reviewed in isolation without considering env-default state). **Closure plan**: (1) `test_digest_task_with_default_settings_loads_yaml_prompt` — fixture sets `settings.prompts_dir = None` explicitly, ensures `digest.yaml` exists at `Path("prompts/digest.yaml")` (CWD-relative default), asserts `digest_task` runs without raising and returns `{"status": "delivered" \| ...}`; (2) `test_prompt_loader_rejects_literal_None_string` — `PromptLoader(prompts_dir="None").load("processing")` should raise (or gracefully fall back), NEVER silently misroute to a `None/processing.yaml` path. |
| **Proposed fix** | **Layer A (minimal, scheduler_service.py:560, ~2 LOC):** change to `prompt_loader = PromptLoader(prompts_dir=str(settings.prompts_dir) if settings.prompts_dir is not None else None)`. Idiomatic guard. Mirror `_default_loader` pattern from `prompt_loader.py:464` (which passes the raw `Path \| None` correctly). **Layer B (PromptLoader hardening, ~3 LOC):** in `PromptLoader.__init__`, after `if prompts_dir is not None: self.prompts_dir = Path(prompts_dir)`, add: `if str(self.prompts_dir) == "None": logger.warning("PromptLoader: prompts_dir resolved to literal 'None' — falling back to default"); self.prompts_dir = Path("prompts")`. Defense-in-depth against future call-site mistakes. **Layer C (settings.py audit, ~5 LOC):** review whether `prompts_dir` default should change from `None` to `Path("prompts")` to remove the ambiguity entirely (would also remove the need for Layer A guard everywhere). **Layer D (operational, ~1 LOC docker-compose env):** add `PROMPTS_DIR=/app/prompts` to `docker-compose.yml` for `tg_parser_bot` (and `tg_parser`, `tg_parser_mcp` for consistency) — eliminates the unset-env latent bug class entirely. **Recommended scope**: Layer A + Layer D in single hotfix PR (small + immediate prod relief), Layer B + Layer C in follow-up housekeeping PR. **NB**: until fix lands, every daily 09:00 MSK cron tick for `digest_94483db9` will continue to fail silently — operator should set `PROMPTS_DIR=/app/prompts` env on prod containers as immediate workaround before next 09:00 MSK tick. |
| **Workaround (immediate, prod)** | Add `PROMPTS_DIR=/app/prompts` to `tg_parser_bot` service env in `docker-compose.yml` and `docker compose up -d tg_parser_bot` (no rebuild needed — env-only change, restart suffices). Restart timing: ideally before next 09:00 MSK cron tick (i.e. before `2026-05-24T06:00:00Z`). Alternatively (if Layer A hotfix lands first): redeploy `tg_parser_bot` with patched scheduler_service.py — also no rebuild needed if pulled. |
| **Evidence** | (1) Production log: `{"task_id": "digest:94483db9-9351-4f99-9aec-46949d9ddd09", "error": "missing prompt for required stage='digest': YAML at None/digest.yaml did not provide a non-empty system.prompt and the built-in default is empty", "exc_info": true, "event": "cron_task_failed", "level": "error", "timestamp": "2026-05-23T06:00:00.123603Z"}` — captured via `docker logs --since 2026-05-22T11:25:47Z tg_parser_bot 2>&1 \| grep error`. (2) Prod env check: `docker exec tg_parser_bot printenv \| grep -iE "prompt\|digest"` → empty (no `PROMPTS_DIR` set). (3) Prod fs check: `docker exec tg_parser_bot ls -la /app/prompts/digest.yaml` → file exists, 2656 bytes, readable. (4) Git blame: `git blame -L 555,565 tg_parser/services/scheduler_service.py` → buggy line authored `410452a6` (2026-04-19), pre-dates step 3 sprint by ~5 weeks. (5) Source confirmation: `git show 5b828cf --stat -- tg_parser/services/scheduler_service.py` → step 3 commit 4/4 added 34 lines, 0 deletions; did not modify `digest_task` code path. |
| **Planned fix** | TD-digest-cron-prompt-loader-path; hotfix PR (Layer A + Layer D) before next 09:00 MSK cron tick. |
| **Workaround applied (prod)** | `2026-05-23T09:49:15Z` — `PROMPTS_DIR=/app/prompts` env set on `tg_parser_bot` (Layer D, method A: added `- PROMPTS_DIR=${PROMPTS_DIR:-/app/prompts}` to `docker-compose.yml` `tg_bot.environment` block, recreated container via `docker compose --profile bot up -d --no-deps tg_bot`; backup at `docker-compose.yml.bak-bug028-20260523-114830`). Post-restart verification: `env \| grep PROMPTS_DIR` → `PROMPTS_DIR=/app/prompts`; `docker inspect ... .State.Health.Status` → `healthy`, `RestartCount=0`; boot log shows `PromptLoader initialized with prompts_dir=PosixPath('/app/prompts')` and `Loaded prompt 'bot' from PosixPath('/app/prompts/bot.yaml')` (no `None/...` path leakage); digest scheduler re-loaded subscription `digest:94483db9-9351-4f99-9aec-46949d9ddd09` (cron `0 9 * * *` `Europe/Nicosia` ≡ `09:00 MSK`). Next cron tick: `2026-05-24T06:00:00Z` (≈ 20h11m post-workaround); high confidence the tick will succeed because the exact `PromptLoader` call path that scheduler_service uses is now seeded with a real existing directory. Hotfix PR (Layer A + Layer C) still to land — `str(settings.prompts_dir)` footgun stays in code, this workaround only masks symptom via env-default. |
| **Update 2026-05-23 — PR [#92](https://github.com/AlexEfimov/TG_parser/pull/92) (squash [`26d03a5`](https://github.com/AlexEfimov/TG_parser/commit/26d03a5b9e40b64fa7f75f3a3de5576c67fca8ef)) landed → BUG-028 RESOLVED** | ✅ **Resolved.** Hotfix PR #92 «fix(bug-028): digest cron PromptLoader None-string regression (hotfix)» merged 2026-05-23T16:57:45Z by AlexEfimov; deployed to prod VPS `mcp.tgp.efimov.mobi` the same day at ≈19:23 UTC (≈22:23 local Europe/Nicosia / 23:23 UTC+4 per deploy report). **All four layers from Proposed fix delivered (full defense-in-depth)**: **Layer A** — call-site guard in `tg_parser/services/scheduler_service.py:560` (`PromptLoader(prompts_dir=str(settings.prompts_dir) if settings.prompts_dir is not None else None)`), idiomatic `None`-aware cast mirroring the `_default_loader` pattern from `prompt_loader.py:464`; **Layer B** — literal-`"None"` string fallback in `tg_parser/processing/prompt_loader.py` `__init__` (warn-then-fallback to `Path("prompts")` if `str(self.prompts_dir) == "None"`), defense-in-depth against any future call-site `str(None)` mistake; **Layer C** — default `Path("prompts")` in `tg_parser/config/settings.py` (`prompts_dir: Path = Field(default=Path("prompts"))`), removes the ambiguity at the source so other call sites stop needing the Layer A guard; **Layer D** — `- PROMPTS_DIR=${PROMPTS_DIR:-/app/prompts}` propagated to all three services (`tg_parser`, `tg_parser_mcp`, `tg_bot`) in `docker-compose.yml`, eliminates the unset-env latent bug class entirely. **Prod state**: all three containers (`tg_parser`, `tg_parser_mcp`, `tg_parser_bot`) restarted and `healthy`; scheduler reloaded with the digest cron job (`0 9 * * *` `Europe/Nicosia`); zero `PromptLoaderError` lines in post-restart logs. **Workaround status**: manual VPS edit from 2026-05-23T09:49:15Z (the `PROMPTS_DIR=/app/prompts` env override on `tg_bot` only) was **discarded** during deploy because Layer D in the merged `docker-compose.yml` is a strict superset (same env wired on all three services via the `${PROMPTS_DIR:-/app/prompts}` parameter expansion). The on-VPS backup file `~/TG_parser/docker-compose.yml.bak-bug028-20260523-114830` is **preserved** for audit / emergency rollback; explicit cleanup deferred until after the 24h watch window. **Pending follow-ups**: (1) 24h watch window — next digest cron tick fires `2026-05-24T06:00:00Z` (09:00 MSK), to be observed in a separate session; (2) optional cleanup of the VPS backup file after watch is GREEN. |

---

### BUG-029 (Medium — backend correctness) — `digest_service.subscribe_digest` race-retry branch missing `await session.rollback()` before retry → cascading session-state errors on concurrent `IntegrityError`

| Поле | Значение |
|---|---|
| **Severity** | **Medium** (backend correctness: on a concurrent `subscribe_digest` race the `_subscription_repo.create()` call raises `IntegrityError` and the except branch immediately re-queries via `find_by_owner_and_name(...)` + `_apply_digest_upsert(...)` WITHOUT first issuing `await session.rollback()` — the session is left in a failed-transaction state, so any subsequent ORM operation in the same `AsyncSession` raises `sqlalchemy.exc.PendingRollbackError` / `IllegalStateChangeError` and the entire request fails with a 500 instead of the intended idempotent upsert. Symptom path: two `subscribe_digest` calls with the same `(owner_id, name)` racing → first commits the row, second gets `IntegrityError`, the retry then sees a dirty session and bubbles a non-retryable error to the API/MCP caller. Operational impact: rare but deterministic when it does happen; corrupts the subscribe-tool idempotency invariant introduced by BUG-022; closely matches the BUG-013 family of «one `AsyncSession` shared across concurrent flows» bugs but at a different surface (in-request retry instead of `asyncio.gather` fanout). No data loss per se — the first row IS committed — but the second caller receives a misleading 500 and may retry-storm.) |
| **Status** | `resolved` (merged 2026-05-29 via [PR #139](https://github.com/AlexEfimov/TG_parser/pull/139) — `fix(digest): rollback aborted session before subscribe race-retry (BUG-029)`; landed on `main` as part of HEAD `656f23c`. Filed retroactively 2026-05-25T06:22Z as part of Wave 1 Step 4 VPS watch closure pre-flight — referenced earlier from [`WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md` § Targets for closure session OA-7](WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md) and cross-linked from BUG-035 «Related» row) |
| **Component** | `tg_parser/services/digest_service.py:263-284` — the `try: created = await self._subscription_repo.create(draft) / except IntegrityError: ... find_by_owner_and_name(...) / _apply_digest_upsert(...)` block at the end of `subscribe_digest()`. Symmetric pattern likely exists in `tg_parser/services/watchlist_service.py` `subscribe_watchlist` (audit needed — verify whether `IntegrityError` recovery there also skips `session.rollback()`). `AsyncSession` lifecycle is owned by the repo context manager (`tg_parser/services/db_context.py` `digest_subscription_repo`) — the rollback would need to be issued against `self._subscription_repo._session` (or threaded through a `repo.rollback()` helper). |
| **Discovered** | Referenced in [`WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md`](WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md) OA-7 (local watch note OA-4 prior). Filed retroactively as part of Wave 1 Step 4 closure pre-flight `2026-05-25T06:22Z`. Originally surfaced via code-review of the step-4 `subscribe_digest` upsert path during local watch analysis. NOT observed in production trace during the VPS watch window (race window is narrow — needs two near-simultaneous subscribe calls), but the structural gap is deterministic. |
| **Linked** | **BUG-013** (closed 2026-04-27 — scheduler shared `AsyncSession` + `asyncio.gather` → `IllegalStateChangeError`; same family of `AsyncSession`-lifecycle bugs at a different surface — that fix moved each `asyncio.gather` task to its own session; this bug needs a similar but smaller fix: rollback-before-retry within a single session); **BUG-022** (subscribe-tool idempotency contract — this bug breaks that contract under race conditions); **BUG-030** (companion — scheduler initial-load fragile to Postgres startup race; both bugs are scheduler-DB lifecycle gaps); ADR 0008 polymorphic subscription target (the `_apply_digest_upsert` retry path is the new step-4 surface — this bug exists pre-step-4 but is more reachable now that more code paths touch the upsert helper). |
| **Symptoms (synthesized — no prod trace yet)** | Two concurrent `subscribe_digest(owner_id=X, name="Y", ...)` calls (e.g. user clicks «Subscribe» button twice or MCP retries on transient network error): (1) First call commits row `R1` successfully. (2) Second call's `INSERT` hits the `UNIQUE(owner_id, name)` constraint → `asyncpg` raises `UniqueViolationError` → SQLAlchemy wraps it as `IntegrityError`. (3) Except branch at line 265 fires WITHOUT `await session.rollback()`. (4) `find_by_owner_and_name(...)` at line 271 executes a `SELECT` against the same session → SQLAlchemy raises `PendingRollbackError: This Session's transaction has been rolled back due to a previous exception during flush. To begin a new transaction with this Session, first issue Session.rollback()` (verbatim — well-documented SQLAlchemy guard). (5) Error bubbles up unhandled → API/MCP caller receives 500. **Cross-check**: in CPython + SQLAlchemy 2.x async, the `IntegrityError` raised from `_subscription_repo.create()` automatically marks the session as «invalidated for commit, requires rollback» — any subsequent `.execute()` on the same session raises `PendingRollbackError` deterministically. |
| **Root cause (HIGH confidence — code-traced)** | Lines 263-284 of `digest_service.py`: `try: created = await self._subscription_repo.create(draft) except IntegrityError: logger.info("digest.subscribe_race_retry_update", ...); existing = await self._subscription_repo.find_by_owner_and_name(owner_id, name); if existing is None: raise; return await self._apply_digest_upsert(...)`. The except branch does NOT issue `await self._subscription_repo._session.rollback()` (or equivalent helper) before the subsequent `find_by_owner_and_name` / `_apply_digest_upsert` calls. Author intent was clearly «if the row already exists, fall through to upsert» (a reasonable idempotency design), but the implementation forgot that `IntegrityError` leaves the SQLAlchemy session in a failed-transaction state that MUST be rolled back before any further ORM call. **NB**: `_apply_digest_upsert` itself may attempt `await self._subscription_repo.update(...)` which ALSO requires a clean session — so even if `find_by_owner_and_name` (a `SELECT`) somehow succeeded against a failed session, the upsert `UPDATE` would still hit `PendingRollbackError`. |
| **Why CI didn't catch** | (a) `tests/test_digest_service.py` and `tests/test_subscribe_legacy_chat_id.py` likely cover the happy path + the upsert-path-when-row-already-exists path INDEPENDENTLY, not the actual race (first-call-races-second-call within one session lifecycle); (b) the race window is hard to reproduce without a deterministic two-task `asyncio.gather` test that pins ordering; (c) BUG-022 idempotency tests verify the public contract («second subscribe returns same row») but with sequential ordering, not concurrent. **Closure plan**: integration test `test_subscribe_digest_race_retry_rolls_back_before_upsert` — use `asyncio.gather` with two concurrent `subscribe_digest` calls on the same `(owner_id, name)`, assert that BOTH calls return a `SubscribeResult` (one with `created=True`, one with `created=False` + correct `changed_fields=[]`), no `PendingRollbackError` raised. Symmetric test for `subscribe_watchlist` if the same pattern exists there. |
| **Proposed fix** | **Layer A (minimal, ~3 LOC):** in `tg_parser/services/digest_service.py` line 265 except branch, add `await self._subscription_repo.session.rollback()` (or expose a `rollback()` method on the repo) as the FIRST statement inside the `except IntegrityError:` block, before the `logger.info(...)` call. **Layer B (audit, ~5 LOC):** `grep -rn "except IntegrityError" tg_parser/services/` and verify each occurrence either issues a rollback or runs against a session that will be discarded immediately. Symmetric fix in `subscribe_watchlist` if needed. **Layer C (test, ~30 LOC):** `tests/test_digest_service_race_retry.py` parametrized on `(target_kind=chat, target_kind=channel)` × `(legacy chat_id, new target)` to ensure rollback-before-retry holds across all subscribe shapes introduced by ADR 0008. **Recommended scope**: A + C in single PR (defensive but small); B as a follow-up housekeeping task. |
| **Workaround (current, in-place)** | None robust — operator must avoid issuing concurrent `subscribe_digest` calls for the same `(owner_id, name)` (rare in practice; would require race within sub-second window). On observed `PendingRollbackError` 500 response: simply retry the subscribe call — the second attempt runs against a fresh session and hits the «row already exists → upsert path» which IS exercised by tests and works. |
| **Evidence** | (1) Source: `tg_parser/services/digest_service.py:263-284` — `try/except IntegrityError` block with no `session.rollback()` between `except` and `find_by_owner_and_name`. (2) SQLAlchemy 2.x async docs «Pending rollback» guard semantics. (3) Cross-reference: BUG-013 closure PR introduced per-task session ownership for `asyncio.gather` to side-step the same family of issues, but this in-request retry path predates that fix and was not audited. **No production trace** — race window is narrow; bug surfaced during step-4 code review, not from a live incident. |
| **Planned fix** | TD-digest-subscribe-race-retry-rollback; defer to Step 5 quality work (no production impact yet; structural gap with deterministic synthesis but rare to hit in practice). |
| **Watch-window note** | Filed as stub during Wave 1 Step 4 VPS watch closure pre-flight 2026-05-25T06:22Z to honor the OA-7 «MANDATORY before step-5 starts» commitment from `WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md`. Stub captures structural diagnosis + recommended fix path; production trace, exact line-range re-verify, and CI test plan to be elaborated when this bug is actually scheduled into a step-5 fix sprint. **2026-05-25T14:36Z update (Phase 1 fill-in)**: re-verified line numbers `263-284` against `main@209637f` snapshot — exact match, no drift; added verbatim code excerpt below; refined "Proposed fix" to specify the exact insertion point for `await session.rollback()` and the regression-test shape (`asyncio.gather` two-call race). |

#### Exact code excerpt (re-verified 2026-05-25T14:36Z — lines unchanged at 263-284)

Source: [`tg_parser/services/digest_service.py:263-284`](../../tg_parser/services/digest_service.py) — tail of `subscribe_digest()` (insertion-row block):

```python
        try:
            created = await self._subscription_repo.create(draft)
        except IntegrityError:
            logger.info(
                "digest.subscribe_race_retry_update",
                owner_id=owner_id,
                name=name,
            )
            existing = await self._subscription_repo.find_by_owner_and_name(owner_id, name)
            if existing is None:
                raise
            return await self._apply_digest_upsert(
                existing=existing,
                target_storage=target_storage,
                channel_ids=channel_ids,
                cron_expression=cron_expression,
                timezone=timezone,
                format=format,
                language=language,
                workspace_id=workspace_id,
            )
        return SubscribeResult(subscription=created, created=True, changed_fields=[])
```

The smoking gun is the **absence** of an `await self._subscription_repo.session.rollback()` (or equivalent helper) between the `logger.info("digest.subscribe_race_retry_update", ...)` call (lines 266-270) and the subsequent `find_by_owner_and_name(...)` call (line 271). SQLAlchemy 2.x async leaves the `AsyncSession` in an "aborted transaction" state after `IntegrityError`; any subsequent `.execute()` on the same session raises `sqlalchemy.exc.PendingRollbackError: This Session's transaction has been rolled back due to a previous exception during flush. To begin a new transaction with this Session, first issue Session.rollback()`. The `find_by_owner_and_name` `SELECT` and the `_apply_digest_upsert` `UPDATE` both share the same session via the `digest_subscription_repo()` context manager (see [`tg_parser/services/db_context.py`](../../tg_parser/services/db_context.py)).

#### Why CI didn't catch (verified — Phase 1 update)

- **No concurrent-update test for `subscribe_digest`**: existing tests in `tests/test_digest_service.py` and `tests/test_subscribe_legacy_chat_id.py` exercise the happy path + the upsert-when-row-already-exists path *independently and sequentially* — they never fire two `subscribe_digest` calls concurrently against the same `(owner_id, name)` within one event loop, so the `IntegrityError`-retry branch is never entered by a real race.
- **BUG-022 idempotency tests verify the public contract serially** ("second subscribe returns the same row") but with deliberate ordering, so the dirty-session retry path is bypassed.
- **No fault-injection on the `_subscription_repo.create()` path**: there is no test that simulates `IntegrityError` to assert that the very next `session.execute(...)` does NOT raise `PendingRollbackError`.

#### Proposed fix (verified — Phase 1 update)

1. **Insert `await self._subscription_repo.session.rollback()`** (or expose a thin `await self._subscription_repo.rollback()` helper if `.session` is not part of the public repo surface) as the **first** statement inside the `except IntegrityError:` block — i.e. **immediately after** the `logger.info("digest.subscribe_race_retry_update", ...)` log call (lines 266-270) and **before** the `find_by_owner_and_name(...)` call (line 271). This single `await` resets the session to a clean state so the subsequent `SELECT` and `UPDATE` proceed normally.
2. **Add regression unit-test** `tests/test_digest_service_race_retry.py::test_subscribe_digest_race_retry_rolls_back_before_upsert`:
   - Fire two concurrent `subscribe_digest(owner_id=X, name="Y", ...)` calls via `asyncio.gather` on the same `(owner_id, name)` tuple.
   - Assert that **both** calls return a `SubscribeResult` — one with `created=True`, one with `created=False` (idempotent upsert path) — OR that **at most one** raises a *typed* error (`PendingRollbackError` MUST NOT leak; an explicit `RaceRetryExhausted` or similar typed error is acceptable).
   - Parametrize across `(target_kind=chat, target_kind=channel)` × `(legacy chat_id, new ADR-0008 target)` shapes so the rollback fix holds for every subscribe surface introduced by ADR 0008.
3. **Symmetric audit** of `subscribe_watchlist` in [`tg_parser/services/watchlist_service.py`](../../tg_parser/services/watchlist_service.py) — `grep -rn "except IntegrityError" tg_parser/services/` and verify each occurrence either issues a rollback or runs against a session that will be discarded immediately. Apply the same fix + test pattern if missing.

**Recommended PR scope**: items 1 + 2 in a single small PR (≈3 LOC fix + ≈30 LOC test); item 3 as a follow-up housekeeping task. No `requirements.txt` change needed.

---

### BUG-030 (Medium — backend startup) — Bot `_start_digest_scheduler` initial-load (`tg_parser/bot/main.py:285-340`) silently degrades to `active_subscriptions=0` on Postgres startup race; recovery only via 60s reconcile-loop, no retry-with-backoff on first read

| Поле | Значение |
|---|---|
| **Severity** | **Medium** (backend startup: at bot container boot, `_start_digest_scheduler` in `tg_parser/bot/main.py:285-340` performs a single un-retried DB read (`async with digest_subscription_repo() as (repo, _db): active = await repo.list_active()`) inside a bare `try / except Exception:` block. If Postgres is still warming up — typical when `docker compose up -d` brings up containers in parallel and the bot's connection pool initializes before Postgres is ready to accept connections, OR when an alembic migration is mid-flight at the moment the bot reads schema — the read raises (`OperationalError`, `InterfaceError`, or schema-mismatch from reflection), the except clamps `active = []`, the scheduler starts with ZERO subscriptions, and the system enters a degraded state where NO digests will be delivered until the `_reconcile_loop` ticks (default `digest_refresh_interval=60s`) and re-loads from DB. Recovery IS self-healing within ≤60s in the observed VPS deploy 2026-05-24T10:46:40Z → 10:47:40Z (1 missed scheduler tick window), but: (a) any subscription whose cron tick falls in the 60s degraded window is silently skipped; (b) `structlog`'s `exc_info=true` is logged but no traceback is rendered (current VPS log config), so the root cause of any individual failure is opaque; (c) if the reconcile loop is ALSO degraded — e.g. by the same Postgres-startup race or by a separate transient — the system can stay in `active_subscriptions=0` indefinitely until full restart.) |
| **Status** | `resolved` (merged 2026-05-29 via [PR #138](https://github.com/AlexEfimov/TG_parser/pull/138) — `fix(bot): hand-rolled retry for digest scheduler initial-load DB race (BUG-030)`; landed on `main` as part of HEAD `656f23c`. Filed retroactively 2026-05-25T06:22Z as part of Wave 1 Step 4 VPS watch closure pre-flight — referenced from [`WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md` § Targets for closure session OA-8](WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md) and cross-linked from BUG-035 «Related» row) |
| **Component** | `tg_parser/bot/main.py:285-340` — `_start_digest_scheduler` async function; specifically the initial-load `try / except Exception:` block at lines 306-311 (no retry, no backoff, no CRITICAL escalation) and the reconcile loop at lines 329-339 (which catches its own exceptions but offers no retry budget for the initial-load case it never sees). `tg_parser/services/db_context.py` `digest_subscription_repo` async-context-manager (the surface where the connection pool is first exercised — verify whether it eagerly opens a connection on `__aenter__` or lazily on the first `.execute()`). `tg_parser/services/background_scheduler.py` `register_digest_subscription` / `get_scheduler` (downstream — receives the `active=[]` empty list silently). `tg_parser/services/scheduler_service.py` `reconcile_digest_subscriptions` (the self-healing path that DOES recover within ≤60s in observed VPS case). |
| **Discovered** | Observed empirically `2026-05-24T10:46:40.131309Z` (T+12s post-restart) during Wave 1 Step 4 VPS deploy — see [`WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md` § Anomaly observed during deploy](WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md) (`digest_scheduler_initial_load_failed` event with `exc_info=true`; self-healed at `10:47:40.164Z` via reconcile loop). Filed as a separate stub per OA-8 commitment 2026-05-25T06:22Z. |
| **Linked** | **BUG-029** (companion stub — `digest_service` race-retry rollback gap; both bugs touch scheduler ↔ DB session-lifecycle invariants); **BUG-035** (orphan-delivery race on `unsubscribe_digest` — closely related but distinct: BUG-030 is startup-time race, BUG-035 is mid-flight delete race; both are scheduler ↔ DB consistency gaps and could share a single «scheduler-hardening» PR per BUG-035 closure plan); BUG-013 (closed 2026-04-27 — shared `AsyncSession` + `asyncio.gather`; same family of session-lifecycle bugs at a different surface); ADR 0008 polymorphic subscription target migration (the alembic `f1a2b3c4d5e6 → a8b7c6d5e4f3` upgrade is one specific trigger of the Postgres-startup race because it ran POST `docker compose up -d` per the step-4 runbook — the bot started reading the schema before the migration committed). |
| **Symptoms (production trace, 2026-05-24T10:46:40.131309Z, VPS post-step-4-deploy)** | Bot started `10:46:39.872Z`; alembic migration `f1a2b3c4d5e6 → a8b7c6d5e4f3` completed `10:47:19Z`. At `10:46:40.131309Z` (`bot start +259ms`, well before migration commit), `_start_digest_scheduler` logged structlog event `{"event": "digest_scheduler_initial_load_failed", "level": "error", "exc_info": true}` and proceeded with `active=[]`. Scheduler started, logged `{"event": "digest_scheduler_started", "active_subscriptions": 0, "refresh_interval": 60}`. At `10:47:40.164Z` (T+60s), reconcile loop ticked: `{"task_id":"digest:94483db9-9351-4f99-9aec-46949d9ddd09","cron_expression":"0 9 * * *","timezone":"Europe/Nicosia","event":"added_cron_task"}` followed by `{"added":1,"removed":0,"failed":0,"event":"digest_reconcile"}`. System self-healed within 60s; the next prod tick `2026-05-25T06:00:05Z` fired successfully (verified via MCP `list_digests` post-watch: `last_sent_at=2026-05-25T06:00:05.145122+00:00`). No structural traceback visible in logs because `structlog` `exc_info=true` is a marker only — traceback rendering not configured on this deploy. |
| **Root cause (MEDIUM-HIGH confidence — empirical + code-traced)** | **Hypothesis A (most likely):** Connection-pool warmup race — `_start_digest_scheduler` runs as one of the first async tasks at bot boot; `digest_subscription_repo()` async context manager either eagerly opens a connection on `__aenter__` or lazily on `repo.list_active()`'s underlying `.execute()`, and at T+259ms post-boot Postgres either is not yet accepting connections (typical when `docker compose up -d` brings up all containers in parallel and the bot's `wait-for-it`-style guard is absent or insufficient), or accepts the connection but the SQLAlchemy reflection sees the pre-migration schema (no `target_kind` column) while the bot's ORM models expect the post-migration shape → `DatabaseError` / `InvalidRequestError`. **Hypothesis B:** Alembic-migration race — bot reads `digest_subscriptions` BETWEEN the time alembic locks the table for ALTER TABLE and the time it commits — SQLAlchemy reflection or query sees an inconsistent schema (e.g. `target_kind` column present but `chat_id` not yet nullable per ADR 0008 migration) → `IntegrityError` on `SELECT` due to model-vs-table shape drift. **Hypothesis C:** FK/PK race — `users` or `digest_subscriptions` table not yet visible to the bot's SQLAlchemy reflection cache when `list_active()` runs its JOIN. Regardless of root cause: the `except Exception:` catch is too coarse, the retry budget is zero, the CRITICAL-escalation log is absent, and the only self-healing is the 60s reconcile loop — which itself is not retry-protected for its FIRST tick. |
| **Why CI didn't catch** | (a) Unit tests for `_start_digest_scheduler` likely mock the `digest_subscription_repo` async-context-manager with a deterministic-success fixture — they verify the happy path (`active=[sub1, sub2]` → `register_digest_subscription` called for each) but NOT the cold-start race (Postgres not yet ready); (b) Integration tests bring up the test database BEFORE the test suite imports the bot, so the race window doesn't exist in tests; (c) No deploy-time smoke test asserts `len(scheduler.get_jobs()) >= len(active_subscriptions)` within 60s of container start as an explicit health-gate. **Closure plan**: startup smoke test `test_start_digest_scheduler_retries_initial_load_on_db_not_ready` — patch `digest_subscription_repo` to raise `OperationalError` for first 2 calls then succeed, assert the function retries with backoff and ends with `active=[...]` non-empty; integration smoke `test_bot_startup_reconcile_loop_succeeds_within_60s_after_postgres_ready` — bring up Postgres T+30s AFTER bot, assert `digest_scheduler_started` eventually shows `active_subscriptions > 0` within 90s (60s reconcile + 30s grace). |
| **Proposed fix** | **Layer A (bounded retry-with-backoff, ~15 LOC):** wrap the initial-load DB read in `tg_parser/bot/main.py:306-311` with a retry helper — e.g. `tenacity.AsyncRetrying(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=2, min=2, max=15), retry=retry_if_exception_type((OperationalError, InterfaceError)))` — surfacing a CRITICAL log on final failure (`logger.critical("digest_scheduler_initial_load_exhausted_retries", ...)`). Final-failure path STILL falls through to `active=[]` (preserves self-healing-via-reconcile), but at CRITICAL level instead of silently. **Layer B (typed exception narrowing, ~5 LOC):** replace bare `except Exception:` with `except (OperationalError, InterfaceError, DatabaseError):` — schema-shape errors (`IntegrityError` on `SELECT` from a half-migrated table) should NOT be retried (won't self-heal); they should fail loud and crash the bot to force operator attention + container restart. **Layer C (traceback rendering, ~3 LOC docker config):** wire `structlog.processors.format_exc_info` into the bot's `structlog` chain on the VPS deploy so that `exc_info=true` actually renders the traceback into the structured log — currently the marker is logged but the traceback is opaque, hampering all future debugging of this bug class. **Layer D (startup smoke test, ~30 LOC):** add CI integration test per «Why CI didn't catch» closure-plan above. **Layer E (deploy-time guard, ~5 LOC docker-compose):** add an explicit `depends_on: postgres: condition: service_healthy` on the `tg_parser_bot` service in `docker-compose.yml` (the postgres container already has a HEALTHCHECK per the Wave 1 step 2 sprint — verify) to eliminate the connection-pool race at the orchestrator level. **Recommended scope**: A + B + E in a single PR (treat as a Medium step-5 quality task — no production impact in steady-state thanks to self-healing-via-reconcile, but the silent-degradation window is a latent invariant violation that becomes a bigger risk if `digest_refresh_interval` is ever raised OR if a future bug breaks the reconcile loop itself). C + D as a follow-up housekeeping task. **NB**: coordinate scope with BUG-035 (orphan-tick race) per BUG-035 closure plan — a single «scheduler-hardening» PR could close BUG-030 + BUG-035 + BUG-029 in one go. |
| **Workaround (current, in-place)** | **NONE NEEDED in steady-state** — the 60s reconcile loop self-heals all observed cases of this bug. **For deploy-time concern**: operator should manually verify `docker logs --since <start-time> tg_parser_bot | grep -E "digest_scheduler_(started\|initial_load_failed\|reconcile)"` within T+90s of every recreate/redeploy and confirm the `added_cron_task` event fires for all expected subscriptions. If it does NOT fire within 90s, restart `tg_parser_bot` container manually (`docker compose --profile bot restart tg_bot`) — second start almost always succeeds because Postgres is fully warm by then. **For mass-deploy concern**: operator should ALWAYS run `alembic upgrade` BEFORE `docker compose up -d` for the bot (i.e. reverse the step-4 deploy order) to eliminate the alembic-race subset of root causes — this is a per-deploy operational discipline, not a code fix. |
| **Evidence** | (1) `WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md § Anomaly observed during deploy` documents the empirical 2026-05-24T10:46:40Z event with `digest_scheduler_initial_load_failed → digest_scheduler_started active_subscriptions=0 → 60s later digest_reconcile added=1 added_cron_task digest:94483db9-…`. (2) Source: `tg_parser/bot/main.py:285-340` — single un-retried `try/except Exception:` at lines 306-311. (3) Post-watch verification via MCP `list_digests` 2026-05-25T06:22Z confirms `last_sent_at=2026-05-25T06:00:05.145122+00:00` — i.e. the next-day prod cron tick fired successfully, confirming self-healing held end-to-end across the 24h window. (4) Cross-reference: same family as BUG-013 (closed) and BUG-035 (resolved — PR #112) — scheduler ↔ DB lifecycle invariant gaps. |
| **Planned fix** | TD-bot-digest-scheduler-initial-load-retry; defer to Step 5 quality work; coordinate with BUG-029 + BUG-035 in a single scheduler-hardening PR per BUG-035 closure plan. |
| **Watch-window note** | Filed as stub during Wave 1 Step 4 VPS watch closure pre-flight 2026-05-25T06:22Z to honor the OA-8 «RECOMMEND перед step 5» commitment from `WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md`. Stub captures empirical observation + structural diagnosis + recommended fix path; final line-range re-verification and CI test design to be elaborated when this bug is actually scheduled into a step-5 fix sprint. Severity adjudicated «Medium» (originally «Low» per OA-8 wording — recovery self-healing within 60s) — escalated to Medium because the 60s `active_subscriptions=0` window represents a silent invariant violation that would mask additional bugs in any future scheduler regression. **2026-05-25T14:36Z update (Phase 1 fill-in)**: re-verified line numbers — function `_start_digest_scheduler` at lines `285-340`, bare `try / except Exception:` at lines `306-311` — exact match against `main@209637f` snapshot, no drift; added verbatim code excerpt below; refined "Proposed fix" to specify the exact `tenacity.AsyncRetrying` parameters (backoff cadence 2-3-5-10-15s) and the typed-exception-narrowing scope. **Caveat flagged**: the proposed fix introduces a new runtime dependency on `tenacity` (`tenacity.AsyncRetrying`, `stop_after_attempt`, `wait_exponential`, `retry_if_exception_type`); per workspace `AGENTS.md` forbidden-action list, any `requirements.txt` change requires explicit operator approval at fix-PR time — do NOT add the dependency unilaterally during fix work. |

#### Exact code excerpt (re-verified 2026-05-25T14:36Z — function at 285-340, bare-`except Exception:` at 306-311)

Source: [`tg_parser/bot/main.py:285-340`](../../tg_parser/bot/main.py) — `_start_digest_scheduler` function, with the smoking-gun `try / except Exception:` block highlighted at lines 306-311:

```python
async def _start_digest_scheduler() -> tuple[Any, asyncio.Task[None] | None]:
    """Initialize the F6 digest scheduler inside the bot process.

    Returns ``(scheduler, reconciliation_task)``. Scheduler is started and the
    initial set of active subscriptions registered before the polling loop
    begins. The reconciliation task wakes up every
    ``digest_refresh_interval`` seconds and diffs DB ↔ scheduler so MCP-side
    create/delete (or another bot replica) propagate without a restart.
    """
    from tg_parser.config import settings
    from tg_parser.services.background_scheduler import (
        get_scheduler,
        register_digest_subscription,
    )
    from tg_parser.services.db_context import digest_subscription_repo
    from tg_parser.services.scheduler_service import reconcile_digest_subscriptions

    scheduler = get_scheduler()
    if not scheduler.is_running:
        scheduler.start()

    try:
        async with digest_subscription_repo() as (repo, _db):
            active = await repo.list_active()
    except Exception:
        logger.exception("digest_scheduler_initial_load_failed")
        active = []

    for sub in active:
        try:
            register_digest_subscription(sub, scheduler)
        except ValueError as exc:
            logger.warning(
                "digest_subscription_invalid_skip",
                subscription_id=sub.id,
                error=str(exc),
            )

    logger.info(
        "digest_scheduler_started",
        active_subscriptions=len(active),
        refresh_interval=settings.digest_refresh_interval,
    )

    async def _reconcile_loop() -> None:
        while True:
            try:
                await asyncio.sleep(settings.digest_refresh_interval)
                await reconcile_digest_subscriptions()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("digest_reconcile_tick_failed")

    task = asyncio.create_task(_reconcile_loop(), name="digest-reconcile-loop")
    return scheduler, task
```

The smoking gun is the **bare `except Exception:` at line 309** combined with the **zero-retry, zero-backoff** behavior of the read at lines 307-308. On any DB-level transient (Postgres still warming up, alembic mid-migration, connection-pool reset), the read raises, the except clamps `active = []`, and `logger.info("digest_scheduler_started", active_subscriptions=0, ...)` deceptively reports a clean start. Self-healing only kicks in when `_reconcile_loop()` fires its first tick after `settings.digest_refresh_interval` seconds (default 60s) — empirically observed `2026-05-24T10:46:40.131Z → 10:47:40.164Z` window during the Wave 1 Step 4 VPS deploy (see `WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md § Anomaly observed during deploy`).

#### Why CI didn't catch (verified — Phase 1 update)

- **No compose-startup-ordering test exercising `bot` boot against a still-migrating `postgres` container**: CI runs `alembic upgrade head` *synchronously* before bot startup, so the race window (bot reading schema before migration commits, or before Postgres accepts connections) simply does not exist in the CI environment. Production `docker compose up -d` brings up all containers in parallel.
- **Unit tests for `_start_digest_scheduler` mock the `digest_subscription_repo()` async-context-manager** with a deterministic-success fixture — they verify the happy path (`active=[sub1, sub2]` → `register_digest_subscription` called for each) but never inject `OperationalError` / `InterfaceError` to exercise the `except Exception:` branch.
- **No deploy-time smoke gate** asserts `len(scheduler.get_jobs()) >= len(active_subscriptions)` within T+90s of container start.
- **`structlog`'s `exc_info=true` is logged but no traceback is rendered** on the VPS deploy (current logging config), so even when the bug fires in production the root cause is opaque.

#### Proposed fix (verified — Phase 1 update)

1. **Layer A — bounded retry-with-backoff (≈15 LOC)**: wrap the initial-load DB read at lines 306-311 with a `tenacity.AsyncRetrying` helper:

    ```python
    from tenacity import (
        AsyncRetrying,
        retry_if_exception_type,
        stop_after_attempt,
        wait_exponential,
    )
    from sqlalchemy.exc import DatabaseError, InterfaceError, OperationalError

    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(5),
            wait=wait_exponential(multiplier=2, min=2, max=15),
            retry=retry_if_exception_type((OperationalError, InterfaceError)),
            reraise=True,
        ):
            with attempt:
                async with digest_subscription_repo() as (repo, _db):
                    active = await repo.list_active()
    except (OperationalError, InterfaceError, DatabaseError):
        logger.critical(
            "digest_scheduler_initial_load_exhausted_retries",
            exc_info=True,
        )
        active = []
    ```

    The 5-attempt schedule with `multiplier=2, min=2, max=15` produces the backoff cadence **2-3-5-10-15s** (≈35s total worst case — fits comfortably inside the existing 60s `digest_refresh_interval` self-healing window so behavior degrades gracefully). On final failure the helper logs at **CRITICAL** (instead of the current silent `active = []` after a single `logger.exception`) and falls through to `active = []` to preserve the existing self-healing-via-reconcile-loop behavior.

2. **Layer B — typed exception narrowing (≈5 LOC)**: change the outer `except Exception:` to `except (OperationalError, InterfaceError, DatabaseError):` so that schema-shape errors (e.g. `IntegrityError` on a `SELECT` from a half-migrated table — Hypothesis B in root cause) fail loud and crash the bot process. Operator container-restart on a hard crash is preferable to a silent steady-state degraded scheduler.

3. **Layer C — structlog traceback rendering (≈3 LOC, deploy config)**: wire `structlog.processors.format_exc_info` into the bot's `structlog` chain so `exc_info=True` actually renders the traceback into the structured log — currently the marker is logged but the traceback is opaque, hampering all future debugging of this bug class.

4. **Layer D — startup smoke test (≈30 LOC)**: `tests/test_start_digest_scheduler_retries_initial_load_on_db_not_ready.py` — patch `digest_subscription_repo` to raise `OperationalError` for the first 2 calls then succeed, assert the function retries with backoff and ends with `active=[...]` non-empty; integration smoke `test_bot_startup_reconcile_loop_succeeds_within_60s_after_postgres_ready` — bring up Postgres T+30s **after** bot, assert `digest_scheduler_started` eventually shows `active_subscriptions > 0` within 90s (60s reconcile + 30s grace).

5. **Layer E — compose-level guard (≈5 LOC `docker-compose.yml`)**: add an explicit `depends_on: postgres: condition: service_healthy` on the `tg_parser_bot` service to eliminate the connection-pool race at the orchestrator level (verify the postgres container already has a `HEALTHCHECK` per Wave 1 step 2).

**Recommended PR scope**: A + B + E in a single PR. **⚠️ Dependency caveat**: Layer A's `tenacity` import is the only potential `requirements.txt` change in this fix; per workspace `AGENTS.md` forbidden-action list, `requirements.txt` modifications require **explicit operator approval at fix-PR time** — flag the dependency add in the PR description and wait for sign-off before merging. If operator declines, fall back to a hand-rolled `for attempt in range(5)` loop with manual `asyncio.sleep(backoff)` (≈25 LOC, no new dependency). C + D as a follow-up housekeeping task. Coordinate scope with BUG-035 and BUG-029 per the BUG-035 closure plan — a single "scheduler-hardening" PR could close BUG-030 + BUG-035 + BUG-029 in one go.

---

### BUG-031 — Bot creates digest subscription in DB BEFORE user confirms (preview-then-confirm contract inverted)

| Поле | Значение |
|---|---|
| **Severity** | **Severe** (UX / correctness: violates documented invariant from `/help` — «Операции записи выполняются только после вашего явного подтверждения в чате»; user receives «📰 Подписка создана» message **before** the «Подтвердите, пожалуйста, … [да/нет]» prompt; if the user then says «нет», the row is already in DB; no data corruption per se (the row can be cleanly unsubscribed) but trust-in-bot regression — destructive create-then-rollback semantics rather than the contracted gate-on-confirm pattern; observed twice consecutively in P1-1 + P1-2 NL tests → high reproducibility) |
| **Status** | `resolved` (merged 2026-05-25 via [PR #111](https://github.com/AlexEfimov/TG_parser/pull/111) — `fix(bot): require explicit affirmative confirmation before subscribe side-effects (BUG-031, BUG-032)`; landed on `main` as commit `66e8297`. Code verified 2026-05-30: `_exec_subscribe_digest` now returns `{"preview": True, ...}` after all validation but BEFORE any DB write/scheduler register when `confirm` is not truthy (`tg_parser/bot/tools.py:2620`); `subscribe_digest`/`subscribe_watchlist` added to `_WRITE_TOOLS_REQUIRING_CONFIRM` (`:51`); server-side `execute_tool` guard `_check_confirm_flow_match` rejects any LLM-issued `confirm=True` lacking a matching FSM snapshot with `error_class="ConfirmFlowMismatch"` (`:991`) — only `handlers._handle_confirmation_response` supplies the snapshot (`tg_parser/bot/handlers.py:464-475`). Regression suite `tests/test_bot_confirm_flow.py` green. Filed 2026-05-24 during Wave 1 Step 4 VPS watch OP-2 / OP-3 interactive tests session — see [`WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md` § T+10h45m OP-2 / OP-3 interactive tests results](WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md). **Prod real-fire smoke verified 2026-05-31** on prod SHA `39b6ba2` (which contains `66e8297`) — see real-fire closure note below.) |
| **Component** | `tg_parser/bot/handlers.py` + `tg_parser/bot/agent.py` + `tg_parser/bot/tools.py` `_exec_subscribe_digest` + `tg_parser/bot/main.py` (FSM `ConfirmFlow` dispatch); `_WRITE_TOOLS_REQUIRING_CONFIRM` set in `tg_parser/bot/tools.py:48-58` — verify that `subscribe_digest` is actually in this set AND that the FSM `ConfirmFlow` state is armed BEFORE the executor fires (suspected race: LLM is calling the executor directly without first emitting the preview-and-arm-FSM step); `prompts/bot.yaml` v1.7.0 preview-and-confirm contract section (BUG-002 closure) |
| **Discovered** | 2026-05-24T~20:55Z (Test C, P1-1 NL channel) and reproduced ~21:10Z (Test D, P1-2 NL chat) by Alexander during Wave 1 Step 4 VPS watch session; Telegram bot `@Tgingest_bot` (id `8657845219`) |
| **Linked** | BUG-002 (preview-confirm contract closure via FSM in Session D — this bug appears to be a regression OR a different code path that bypasses the FSM guard); BUG-009 (server-side `confirm=True` guard rejecting unmatched FSM snapshots in MCP `execute_tool` — symmetric pattern needed in bot executor); BUG-032 (companion bug — confirmation parser broken for «да»/«подтверждаю», compounds this bug's severity because even after-the-fact rollback is hard) |
| **Symptoms (production trace, 2026-05-24 ~20:55Z, Test C)** | User said «Подпиши меня на ежечасный дайджест канала @vps_watch_test_r1_Alex» (P1-1 NL) → bot did NOT emit a preview step; instead immediately responded «📰 Подписка создана» followed by subscription metadata (id `5d8b83ad-…`, cron `0 * * * *` `Europe/Moscow`, target `@vps_watch_test_r1_Alex`); only AFTER the create-confirmation message did the bot ask «Подтвердите, пожалуйста, создание подписки [да/нет]». DB row was already inserted in `digest_subscriptions` at this point (verified via MCP `list_digests` cross-check). Same trace pattern at ~21:10Z (Test D, sub `0a00768d-…`). |
| **Root cause (HIGH confidence on symptom; MEDIUM on code path until traced)** | **Hypothesis A (most likely):** LLM (Gemini) is generating both the «📰 Подписка создана» tool-result-paraphrase AND the «Подтвердите [да/нет]» preview-prompt in the same turn after the executor has already fired — i.e. the agent-loop did NOT route `subscribe_digest` through the FSM preview gate at all, and the LLM is post-hoc fabricating a «confirm» message that has no FSM state behind it. **Hypothesis B:** `subscribe_digest` is missing from `_WRITE_TOOLS_REQUIRING_CONFIRM` set in `tg_parser/bot/tools.py:48-58` (regression from Session D scope — only `add_channel` / write-tools active at Session D landing were added). **Hypothesis C:** Session D FSM `ConfirmFlow` requires explicit preview-emission by the LLM (Hard rule in `prompts/bot.yaml`), and the v1.7.0 prompt change for `target_kind_semantics` accidentally weakened that rule for `subscribe_digest` write-tool path. **Verification needed**: (1) `grep _WRITE_TOOLS_REQUIRING_CONFIRM tg_parser/bot/tools.py` to see current membership; (2) re-read `prompts/bot.yaml` v1.7.0 to verify the «preview-before-write» hard rule for write-tools is still present and unambiguous; (3) trace bot logs for the C+D test sessions for `agent_tool_call` / `FSMConfirm` / `ConfirmFlow` events to determine whether the FSM was ever armed for these subscriptions. |
| **Why CI didn't catch** | (a) Session D FSM tests likely focus on `add_channel` happy path (the original BUG-002 target) and do not exercise `subscribe_digest` confirm-flow end-to-end. (b) Bot prompt v1.7.0 was validated for `target_kind` disambiguation (the C / D test goals) but NOT for the preview-then-confirm ordering invariant — there is no e2e bot test that asserts «preview message MUST precede DB insert event for write-tools». **Closure plan**: integration test `test_subscribe_digest_emits_preview_before_db_insert` (mock Telegram + DB + LLM) → assert ordering of events: (1) preview message → (2) user «да» → (3) FSM dispatch → (4) DB insert → (5) create-confirmation message. Symmetric for `subscribe_watchlist`, `add_channel`, `register_user`, all write-tools in `_WRITE_TOOLS_REQUIRING_CONFIRM` set. |
| **Proposed fix** | **Layer A (audit + restore membership, ~5 LOC):** verify `subscribe_digest` and `subscribe_watchlist` are in `_WRITE_TOOLS_REQUIRING_CONFIRM`; add if missing. **Layer B (FSM hard-gate, ~20 LOC):** in `tg_parser/bot/agent.py` agent-loop, BEFORE invoking any executor in `_WRITE_TOOLS_REQUIRING_CONFIRM` set, REQUIRE that FSM state is `ConfirmFlow.awaiting_confirmation` with matching snapshot — if not, REJECT the executor invocation with typed error `error_class="MissingConfirmation"` and emit a deterministic preview message instead (server-side guard, NOT LLM-dependent — mirrors BUG-009 Session G MCP `execute_tool` pattern). **Layer C (prompt v1.7.x ~10 LOC):** strengthen hard rule in `prompts/bot.yaml`: «For write-tools (`subscribe_*`, `add_channel`, `register_user`, …), you MUST emit a preview message and wait for user confirmation BEFORE calling the tool. NEVER call the tool first and ask for confirmation after.» **Recommended scope**: A + B + C in single PR (Layer B is the architectural fix mirroring BUG-009 — make the bot defensible against LLM contract violations, not reliant on LLM discipline). |
| **Workaround (current, in-place)** | None robust — operator must visually inspect message ordering and call `unsubscribe_digest` if they did not actually intend the subscription. Confirmation flow breakage compounded by BUG-032 («да» / «подтверждаю» not recognized) makes after-the-fact recovery non-trivial; operator must use MCP `unsubscribe_digest` from Cursor with subscription UUID copied from the bot's create-confirmation message. |
| **Evidence** | Two consecutive Test C + Test D bot transcripts on 2026-05-24 ~20:55Z and ~21:10Z showing message ordering: «📰 Подписка создана» followed by «Подтвердите [да/нет]». DB cross-check via `list_digests` confirms both subscriptions (`5d8b83ad-…`, `0a00768d-…`) materialized in `digest_subscriptions` BEFORE the confirmation prompt was issued. Subscriptions later hard-deleted via `unsubscribe_digest` during test cleanup. |
| **Planned fix** | TD-bot-preview-confirm-hardgate; bundle with BUG-032 (companion confirmation parser) and BUG-009 pattern audit (server-side guard for write-tools, mirroring MCP `execute_tool`). |

**Real-fire verified 2026-05-31** in group `vps-watch-test-grp` (chat_id `-5279672667`) against prod SHA `39b6ba2` — original Test C/D trace observed closed: every subscribe attempt showed the `Preview … Подтвердите [да/нет]` prompt FIRST; «📰 Подписка создана» only ever appeared AFTER an affirmative (verified ~5×). Mirrors the BUG-037 real-fire closure precedent ([`HANDOFF_BUG037_2026-05-30.md`](HANDOFF_BUG037_2026-05-30.md)). Status unchanged (`resolved`). See [`SMOKE_TEST_BUG031_034_2026-05-30.md` § Results 2026-05-31](SMOKE_TEST_BUG031_034_2026-05-30.md).

---

### BUG-032 — Bot does not parse «да» / «подтверждаю» as valid confirmation tokens

| Поле | Значение |
|---|---|
| **Severity** | **Medium** (UX: confirmation handler parser repeatedly responds «Я не совсем понимаю ваш ответ» to plain affirmative responses like «да» / «подтверждаю» / «yes» / «ok»; user can't progress the FSM `ConfirmFlow` past the preview step using natural Russian/English affirmative tokens; observed in both Test C and Test D sessions; compounds BUG-031 by making after-the-fact rollback or alternative recovery flows brittle; no data correctness impact in isolation, but blocks normal user flow) |
| **Status** | `resolved` (merged 2026-05-25 via [PR #111](https://github.com/AlexEfimov/TG_parser/pull/111) — `fix(bot): require explicit affirmative confirmation before subscribe side-effects (BUG-031, BUG-032)`; landed on `main` as commit `66e8297` (bundled with BUG-031). Code verified 2026-05-30: canonical `classify_confirmation_token` (`tg_parser/bot/handlers.py:164-204`) backed by `AFFIRMATIVE_TOKENS`/`NEGATIVE_TOKENS` frozensets — «да»/«yes»/«y»/«ok»/«ок»/«подтверждаю»/«согласен»/«хорошо»/«+»/«👍» all classify `affirmative` (casefold + inner-whitespace collapse + first-token fallback for «да, давай»); on an unknown token the FSM stays armed and surfaces a structured «accepted tokens» prompt instead of the opaque «Я не совсем понимаю ваш ответ» (`:502-517`). Regression suite `tests/test_bot_confirm_flow.py` green. Filed 2026-05-24 during Wave 1 Step 4 VPS watch OP-2 / OP-3 interactive tests session — see [`WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md` § T+10h45m OP-2 / OP-3 interactive tests results](WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md). **Prod real-fire smoke verified 2026-05-31** on prod SHA `39b6ba2` (which contains `66e8297`) — see real-fire closure note below.) |
| **Component** | `tg_parser/bot/handlers.py` `_handle_confirmation_response` (or equivalent FSM dispatch for `ConfirmFlow.awaiting_confirmation` state — Session D scope); confirmation token whitelist (likely a hardcoded set like `{"да", "yes"}` or a regex pattern); `prompts/bot.yaml` confirmation-semantics section if confirmation routing is LLM-mediated rather than FSM-deterministic |
| **Discovered** | 2026-05-24T~20:56Z (Test C) and ~21:11Z (Test D), Alexander, Telegram bot `@Tgingest_bot`; reproduced twice within a 25-minute window across two different write-tool intents |
| **Linked** | BUG-031 (companion — preview-confirm ordering inverted; this bug compounds its severity by making confirmation impossible to recover); BUG-002 (Session D FSM `ConfirmFlow` landing — that fix introduced the FSM scaffolding; this bug suggests the token-parsing surface inside the FSM dispatch is incomplete); BUG-009 (Session G `execute_tool` server-side guard — symmetric MCP-side mechanism for confirm-flow, may have a less brittle token parser worth porting); BUG-026 (standalone-UUID continuation context — adjacent FSM continuation surface) |
| **Symptoms (production trace, 2026-05-24 ~20:56Z, Test C)** | After bot emitted «Подтвердите, пожалуйста, создание подписки [да/нет]» (BUG-031 ordering issue notwithstanding), user replied «да» → bot responded «Я не совсем понимаю ваш ответ». User retried with «подтверждаю» → same response. User retried with «yes» / «ok» → same. Test D at ~21:11Z reproduced the identical pattern. No `agent_tool_call` event for confirm-dispatch in either case — the response is generated deterministically (handler-side) without LLM involvement. |
| **Root cause (MEDIUM confidence — needs code trace)** | **Hypothesis A (most likely):** FSM `ConfirmFlow.awaiting_confirmation` dispatch in `_handle_confirmation_response` has a narrow whitelist (e.g. `{"да", "yes"}` lowercase-stripped) that does NOT include common variants like «подтверждаю», «подтверждаю!», «да-да», «ок», etc.; non-match falls through to the «Я не совсем понимаю ваш ответ» catch-all. **Hypothesis B:** the whitelist IS broad enough but the user's input is being routed to LLM-agent loop (because FSM state was never armed per BUG-031), and the LLM does not have prompt instructions to recognize standalone «да» as confirmation of a previously-issued preview. **Hypothesis C:** unicode normalization issue — user typed «да» with a different unicode codepoint variant (e.g. combining grave accent) that fails strict equality match. **Verification needed**: (1) `grep -n "не совсем понимаю" tg_parser/bot/` to find the catch-all handler; (2) trace bot logs for the C / D test sessions to determine whether the message was dispatched via FSM or via LLM agent-loop. |
| **Why CI didn't catch** | (a) Session D FSM tests likely use a single canonical token («да») in their fixtures and do not parameterize for variants. (b) No CI matrix test for confirmation token parsing: «да» / «yes» / «подтверждаю» / «ok» / «согласен» / «нет» / «no» / «cancel» / «отмена». **Closure plan**: parametrized test `test_confirmation_handler_accepts_variants` covering ≥ 8 affirmative + ≥ 4 negative tokens with whitespace / case / punctuation variants; assert FSM transitions to `ConfirmFlow.confirmed` (affirmative) or `ConfirmFlow.cancelled` (negative). |
| **Proposed fix** | **Layer A (whitelist expansion, ~10 LOC):** expand affirmative whitelist to `{"да", "yes", "y", "подтверждаю", "ok", "ок", "согласен", "согласна", "хорошо", "+", "👍"}` (case-insensitive, whitespace-stripped, punctuation-tolerant); negative whitelist to `{"нет", "no", "n", "отмена", "cancel", "отказ", "не подтверждаю", "стоп", "-", "👎"}`. **Layer B (typed return, ~5 LOC):** when neither whitelist matches, return typed `error_class="UnknownConfirmationToken"` with a helpful message listing accepted tokens, instead of the opaque «Я не совсем понимаю ваш ответ». **Layer C (prompt v1.7.x ~3 lines):** add user-facing hint in the preview message itself: «Ответьте «да», «подтверждаю» или «нет» / «отмена»». **Recommended scope**: A + B + C in single PR; bundle with BUG-031 since both are FSM `ConfirmFlow` surface. |
| **Workaround (current, in-place)** | None — user is blocked at the confirmation step. Operator-side recovery: directly use MCP `unsubscribe_digest` to remove the BUG-031-induced premature row, then re-issue the intent via different bot phrasing (or accept the FSM stall and clean up out-of-band). |
| **Evidence** | Two consecutive Test C + Test D bot transcripts on 2026-05-24 showing identical pattern: user «да» → bot «Я не совсем понимаю ваш ответ»; user «подтверждаю» → same; user «yes» / «ok» → same. No `agent_tool_call` event for these turns in bot log (deterministic handler-side dispatch, not LLM). |
| **Planned fix** | TD-bot-confirm-token-parser; bundle with BUG-031 (preview-confirm hardgate) and BUG-009 pattern (server-side guard parity). |

**Real-fire verified 2026-05-31** in group `vps-watch-test-grp` (chat_id `-5279672667`) against prod SHA `39b6ba2` — original Test C/D trace observed closed: at the subscribe-confirm gate «да» / «yes» / «подтверждаю» / «ок» were all accepted as affirmative, and «нет» / «no» correctly cancelled. Mirrors the BUG-037 real-fire closure precedent ([`HANDOFF_BUG037_2026-05-30.md`](HANDOFF_BUG037_2026-05-30.md)). Status unchanged (`resolved`). **NB — scope caveat:** this affirmative-token acceptance is scoped to the `ConfirmFlow.awaiting_confirmation` gate only; the same «да» is NOT actionable on the channel-name clarification surface (no FSM armed there) — tracked as the NEW residual **BUG-039**. See [`SMOKE_TEST_BUG031_034_2026-05-30.md` § Results 2026-05-31](SMOKE_TEST_BUG031_034_2026-05-30.md).

---

### BUG-033 — Bot inserts `chat_id=123` placeholder for «в этот чат» NL intent in group context (real group chat_id leak)

| Поле | Значение |
|---|---|
| **Severity** | **Critical** (correctness: bot stores `chat_id=123` (a hardcoded placeholder / seed value) when user issues NL intent «в этот чат» from within a Telegram group; the resulting subscription has an undeliverable `chat_id` — Telegram chat `123` is not the actual group; on next scheduled cron tick the bot will attempt `sendMessage(chat_id=123)` and increment a `delivery_failed` counter, orphaning the digest; **NB**: real group chat_id for the test was `-5279672667`; the placeholder `123` is structurally the same value that appears in `tests/conftest.py` / fixture seeds — indicating a test-fixture leak into production code path; observed once in Test D, but the deterministic shape suggests 100% reproducibility for any «в этот чат» NL intent from group context) |
| **Status** | `resolved` (merged 2026-05-25 via [PR #108](https://github.com/AlexEfimov/TG_parser/pull/108) — `fix(bot): resolve chat_id from update for group subscribe_digest (BUG-033)`; landed on `main` as commit `e50449b`. Code verified 2026-05-30: `_resolve_target_for_bot_subscribe` (`tg_parser/bot/tools.py:2391`) treats the bot-context `Message.chat.id` as authoritative for `kind=chat` — whenever `bot_context_chat_id is not None` it returns `TargetChat(chat_id=bot_context_chat_id)`, overriding any LLM-supplied value and logging `subscribe_target_chat_id_overridden` on divergence (`:2459-2470`); so the hallucinated `chat_id=123` from group `-5279672667` can no longer reach the DB. Applied symmetrically to `_exec_subscribe_digest` (`:2536`) and `_exec_subscribe_watchlist` (`:2920`). Root-cause refinement: there is **no** `chat_id=123` literal anywhere in the codebase — the original "test-fixture leak" hypothesis was wrong; the LLM hallucinated `123` because it has no factual access to `Message.chat.id`. Regression suite `tests/test_bot_chat_target_resolution.py` green. Filed 2026-05-24 during Wave 1 Step 4 VPS watch OP-2 / OP-3 interactive tests session — see [`WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md` § T+10h45m OP-2 / OP-3 interactive tests results](WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md). **Prod real-fire smoke verified 2026-05-31** on prod SHA `39b6ba2` (which contains `e50449b`) — subscription bound to real group chat_id `-5279672667`, no `123`; see real-fire closure note below.) |
| **Component** | `tg_parser/bot/tools.py` `_exec_subscribe_digest` (target resolution for `target_kind=chat` when user phrasing is «в этот чат» — must consume `update.message.chat.id` from aiogram Message context, NOT a literal placeholder); `tg_parser/bot/agent.py` (agent-loop tool-args resolution — possibly the seed of the `123` value is in argument-defaulting logic); `tg_parser/bot/handlers.py` (entry point for group-message handling — must propagate `chat_id` from `Message.chat.id` into agent context); `prompts/bot.yaml` v1.7.0 `target_kind_semantics` section (which presumably teaches the LLM to emit `target.kind=chat, chat_id=<context>` — but the «context» injection mechanism appears broken or uninitialized in group context, defaulting to hardcoded `123`) |
| **Discovered** | 2026-05-24T~21:10Z (Test D, P1-2 NL chat), Alexander, Telegram bot `@Tgingest_bot` in basic group `vps-watch-test-grp` (chat_id `-5279672667`, bot promoted to admin to bypass privacy mode); single occurrence, but deterministic shape |
| **Linked** | BUG-002 (Session D FSM scaffolding — chat_id propagation through FSM context may be the missing piece); BUG-011 (Session H read-context `channel_id` continuation — symmetric mechanism for `chat_id` from group `Message.chat.id` may be missing); BUG-034 (companion bug — channel-name parser typo handling, also surfaced in Test D); ADR 0008 polymorphic subscription target (the `target.kind=chat` path is the new step-4 surface — this bug is a step-4 correctness regression at the NL → API layer); chat fixture `123` typical seed in `tests/conftest.py` (verify exact origin via `grep -rn "123" tg_parser/bot/ tests/` for chat_id-typed bindings) |
| **Symptoms (production trace, 2026-05-24 ~21:10Z, Test D)** | User in group `vps-watch-test-grp` (chat_id `-5279672667`) said «Подпиши этот чат на ежечасный дайджест канала profendocrinologist» (P1-2 NL) → bot agent_tool_call: `{"tool": "subscribe_digest", "args": {"name": "...", "target": {"kind": "chat", "chat_id": 123}, "channel_ids": ["pro_fendocrinologist"], "cron_expression": "0 * * * *"}}` (the `chat_id=123` value is the smoking gun — clearly NOT the actual group chat_id `-5279672667`; `channel_ids="pro_fendocrinologist"` is companion BUG-034 typo issue). Subscription was created (id `0a00768d-…`); on next scheduled cron tick (would-be 22:00 UTC) the dispatch would target `chat_id=123` (an invalid Telegram chat) and fail. |
| **Root cause (MEDIUM-HIGH confidence — needs code trace)** | **Hypothesis A (most likely):** `tg_parser/bot/agent.py` agent-loop has a default value or fixture-seed for `chat_id` in the agent-args context (likely from test scaffolding) that survived into production code path — when the LLM emits `target.kind=chat` without an explicit `chat_id` value (relying on context to fill it), the agent-loop substitutes a hardcoded `123` instead of `update.message.chat.id`. **Hypothesis B:** the `target_kind_semantics` section in `prompts/bot.yaml` v1.7.0 instructs the LLM to emit `chat_id=<context>` literal, and the LLM hallucinated `123` as a plausible placeholder; the agent-loop did NOT validate or substitute it. **Hypothesis C:** ADR 0008 polymorphic target schema in MCP `subscribe_digest` accepts `chat_id=123` (any positive integer is technically valid Telegram chat_id syntax) without checking that the chat exists or that the bot has access — server-side validation gap. **Verification needed**: (1) `grep -rn "chat_id.*=.*123\|chat_id: 123\|chat_id=123" tg_parser/ tests/` to locate the `123` literal origin; (2) trace the agent-loop tool-args resolution for `subscribe_digest` from `Message` → `agent_args` → `_exec_subscribe_digest` → MCP request; (3) re-read `prompts/bot.yaml` v1.7.0 `target_kind_semantics` for explicit «use chat from current update» instruction. |
| **Why CI didn't catch** | (a) Session D + step-4 tests for `subscribe_digest` likely use a fixture `chat_id=123` and assert exact echo — i.e. tests pass because they expect the same value that the bug emits. (b) No e2e test exercises «bot in actual Telegram group, user says «в этот чат», assert resulting `chat_id` equals `Message.chat.id`». (c) ADR 0008 contract tests verify schema shape but not semantic chat_id validity. **Closure plan**: integration test `test_subscribe_digest_in_group_resolves_chat_id_from_message` — mock aiogram `Message(chat=Chat(id=-1001234))`, simulate user NL «в этот чат подпиши на канал …», assert `_exec_subscribe_digest` receives `target.chat_id=-1001234` (NOT `123`). Server-side validation test: `subscribe_digest(target={kind:chat, chat_id:123})` → either reject as «chat_id not accessible by bot» or accept and emit a warning metric. |
| **Proposed fix** | **Layer A (agent-args context injection, ~15 LOC):** in `tg_parser/bot/agent.py`, when building the agent invocation context for a group-message intent, propagate `update.message.chat.id` into a reserved context field `_current_chat_id` and require executors that need a chat_id from context to consume it. Reject any executor invocation where `target.kind=chat` AND `target.chat_id` was sourced from a fixture-default rather than context. **Layer B (executor validation, ~10 LOC):** in `_exec_subscribe_digest`, when `target.kind=chat`, validate `target.chat_id == _current_chat_id` (if user said «в этот чат») OR validate that the bot has membership in `target.chat_id` (Telegram `getChat` API call). Reject otherwise with typed error. **Layer C (fixture-leak audit, ~20 LOC):** grep for all `123` literals in `tg_parser/bot/` and adjacent test scaffolding; eliminate any production code path that has `123` as a default value; mark all test-only seeds with a `_TEST_ONLY_` prefix. **Recommended scope**: A + B + C in single PR; treat as a Critical step-4 hotfix because Test D demonstrates this would produce orphan digests at every scheduled tick for any production user issuing «в этот чат» from a group. |
| **Workaround (current, in-place)** | Operator: do NOT use «в этот чат» phrasing from groups until fix lands; instead explicitly state the chat_id («подпиши чат `-5279672667` на дайджест …») OR subscribe via DM (where `Message.chat.id` equals user_id and the LLM might correctly populate it). Test D row was hard-deleted via `unsubscribe_digest` during cleanup. |
| **Evidence** | Single Test D bot transcript on 2026-05-24 ~21:10Z showing `subscribe_digest` tool args `{"target": {"kind": "chat", "chat_id": 123}, ...}` issued from a group whose actual chat_id is `-5279672667`. Subscription `0a00768d-…` created and immediately hard-deleted during test cleanup. |
| **Planned fix** | TD-bot-chat-context-propagation; treat as Critical step-4 hotfix candidate; coordinate with BUG-034 (NL parser typo handling) since both surfaced in Test D and both touch `subscribe_digest` arg resolution. |

**Real-fire verified 2026-05-31** in group `vps-watch-test-grp` (chat_id `-5279672667`) against prod SHA `39b6ba2` — original Test D trace observed closed: «Подпиши этот чат на ежечасный дайджест канала profendocrinologist» issued from the group created a subscription bound to the **real group chat_id `-5279672667`**, NOT the hallucinated placeholder `123`. Confirmed authoritatively via `list_digests` (MCP): subscription `6ed3785c-d73f-4042-a4ba-76aa78388d82` → `chat_id: -5279672667`, `target_kind: chat` (for contrast, the pre-existing DM-scoped daily subscription shows a positive `chat_id: 5445781511`, proving «этот чат» correctly resolved the negative group id from `Message.chat.id`). Mirrors the BUG-037 real-fire closure precedent ([`HANDOFF_BUG037_2026-05-30.md`](HANDOFF_BUG037_2026-05-30.md)). Status unchanged (`resolved`). See [`SMOKE_TEST_BUG031_034_2026-05-30.md` § Results 2026-05-31](SMOKE_TEST_BUG031_034_2026-05-30.md).

---

### BUG-034 — Source channel name parser fails on user typo with embedded whitespace («pro fendocrinologist» → underscored `pro_fendocrinologist` mismatch)

| Поле | Значение |
|---|---|
| **Severity** | **Medium** (UX / correctness: bot stores `channel_ids=["pro_fendocrinologist"]` (with underscore) when user typed «pro fendocrinologist» (with space — typo for `profendocrinologist`); the underscored variant is NOT a valid Telegram username pattern that matches the real source `profendocrinologist`; resulting subscription is structurally undeliverable because it references a non-existent channel; no data corruption (the row exists but is inert at digest-time) but silent semantic failure — user thinks they subscribed to endocrinology channel but no digest will ever materialize; observed once in Test D but high-likelihood reproducible for any user typo with embedded whitespace) |
| **Status** | `resolved` (merged 2026-05-25 via [PR #109](https://github.com/AlexEfimov/TG_parser/pull/109) — `fix(bot): reject space-as-underscore in channel name parser (BUG-034)`; landed on `main` as commit `6ebad33`. Code verified 2026-05-30: `_exec_subscribe_digest` now runs each `channel_id` through `validate_channel_username` BEFORE persisting (`tg_parser/bot/tools.py:2554-2560`); the helper (`tg_parser/utils/channel_id.py:123`) rejects embedded whitespace BEFORE normalization (`:181-195`), so «pro fendocrinologist» returns `error_class="InvalidChannelUsername"` with suggestion «profendocrinologist» instead of silently underscoring to `pro_fendocrinologist`; also enforces the Telegram username regex `^[a-zA-Z][a-zA-Z0-9_]{4,31}$` with a numeric-chat-id fast path. Regression suite `tests/test_bot_channel_name_parser.py` green. Filed 2026-05-24 during Wave 1 Step 4 VPS watch OP-2 / OP-3 interactive tests session — see [`WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md` § T+10h45m OP-2 / OP-3 interactive tests results](WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md). **Prod real-fire smoke verified 2026-05-31 (core)** on prod SHA `39b6ba2` (which contains `6ebad33`) — «pro fendocrinologist» rejected, not underscored; see real-fire closure note below.) |
| **Component** | `tg_parser/bot/agent.py` (agent-loop channel-name resolution from NL) OR `prompts/bot.yaml` (LLM instructions for normalizing channel usernames from NL); `tg_parser/bot/tools.py` `_exec_subscribe_digest` (`channel_ids` arg validation — does NOT pre-validate that each entry matches `^[a-zA-Z][a-zA-Z0-9_]*$` Telegram username regex AND does NOT verify channel existence via `get_source_by_username`); MCP `subscribe_digest` server-side handler (also missing username validation / existence check) |
| **Discovered** | 2026-05-24T~21:11Z (Test D, P1-2 NL chat), Alexander, Telegram bot `@Tgingest_bot`; user typed «Подпиши этот чат на ежечасный дайджест канала pro fendocrinologist» (с пробелом — typo для `profendocrinologist`) |
| **Linked** | BUG-010 (`get_source_by_username` resolution path — Session I fix; should be reused as a pre-validation step in `_exec_subscribe_digest` to verify channel existence); BUG-033 (companion — both surfaced in Test D `subscribe_digest`); BUG-025 (UUID-validation analogue — symmetric «validate args before SQL» class of bugs); ADR 0008 polymorphic target (the `channel_ids` arg is part of step-4 channel-target surface — this bug is a step-4 UX regression) |
| **Symptoms (production trace, 2026-05-24 ~21:11Z, Test D)** | User: «Подпиши этот чат на ежечасный дайджест канала **pro fendocrinologist**» (с пробелом). Bot `agent_tool_call`: `{"tool": "subscribe_digest", "args": {..., "channel_ids": ["pro_fendocrinologist"], ...}}` — the LLM (or the bot's arg-normalization layer) replaced the space with an underscore, producing a non-existent username. Subscription `0a00768d-…` was created with this wrong channel_id. No `WatchInterestInfo`-style validation error fired because `subscribe_digest` does not pre-validate channel existence. |
| **Root cause (MEDIUM confidence — needs trace to determine whether normalization is LLM-side or code-side)** | **Hypothesis A (most likely):** Gemini LLM (or `prompts/bot.yaml` v1.7.0 channel-resolution section) instructs the model to normalize whitespace by replacing spaces with underscores — this is a reasonable heuristic for some username styles but produces invalid Telegram usernames for typos. **Hypothesis B:** there is a Python-side string-normalization helper in `tg_parser/bot/tools.py` or `tg_parser/bot/agent.py` (e.g. `channel_id = channel_id.strip().replace(" ", "_")`) — find via `grep -rn "replace.*\" \".*\"_\"\\|replace(' ', '_')" tg_parser/bot/`. **Hypothesis C:** neither — the LLM heard a space-separated phonetic spelling and emitted the underscored form as a guess without normalization rule. Regardless of root cause, the executor accepts the value without validating against `get_source_by_username` — that gap is the structural fix surface. **Verification needed**: (1) bot log for Test D `agent_tool_call` for `subscribe_digest` should show the raw LLM-emitted args; (2) grep for `.replace(" ", "_")` in `tg_parser/bot/`; (3) re-read `prompts/bot.yaml` v1.7.0 channel-name section. |
| **Why CI didn't catch** | (a) Step-4 `subscribe_digest` tests use canonical channel names («@test_channel», «profendocrinologist») without whitespace typos. (b) No fuzz-style test for «common user typos in channel names» (whitespace, hyphens, mixed case, leading `@` vs none). (c) Server-side `subscribe_digest` MCP handler does NOT call `get_source_by_username` to verify channel existence — Layer 8 source resolution introduced in Session I (BUG-010) is read-side only; write-side surfaces should also pre-validate. **Closure plan**: parametrized test `test_subscribe_digest_validates_channel_existence` for ≥ 6 typo variants («pro fendocrinologist», «@profendocrinologist», «Profendocrinologist», «profendocrinologist », «https://t.me/profendocrinologist», «pro-fendocrinologist») → assert either (a) normalization to canonical form `profendocrinologist` (if a clear rule applies) OR (b) reject with `error_class="UnknownChannel"` and a helpful list of nearby channels (via fuzzy search). |
| **Proposed fix** | **Layer A (executor pre-validation, ~15 LOC):** in `_exec_subscribe_digest`, for each entry in `channel_ids`: (1) strip leading `@` if present; (2) validate against regex `^[a-zA-Z][a-zA-Z0-9_]{4,31}$` (Telegram username constraints); (3) call `get_source_by_username` to verify existence; (4) reject the whole subscribe with `error_class="UnknownChannel"` if any entry fails. **Layer B (prompt v1.7.x ~5 lines):** add hard rule in `prompts/bot.yaml` channel-resolution section: «If a channel name has embedded whitespace or hyphens, ask the user to clarify rather than guessing a normalized form. NEVER replace spaces with underscores.» **Layer C (MCP server-side, ~15 LOC):** mirror Layer A in MCP `subscribe_digest` handler — defense-in-depth + apply uniformly to API surface too. **Recommended scope**: A + B + C in single PR; bundle with BUG-033 (companion Test D fix). |
| **Workaround (current, in-place)** | Operator: type channel names carefully without whitespace; verify subscription resolved to the intended channel via `list_digests` immediately after creation. Test D row was hard-deleted during cleanup. |
| **Evidence** | Test D bot transcript on 2026-05-24 ~21:11Z showing `subscribe_digest` `channel_ids=["pro_fendocrinologist"]` for user input «pro fendocrinologist» (с пробелом); the real source `profendocrinologist` (no underscore, no space) was the user's intent per separate cross-check via `list_channels`. Subscription `0a00768d-…` was created with the wrong channel id and hard-deleted during cleanup. |
| **Planned fix** | TD-subscribe-digest-channel-validation; bundle with BUG-033 (Test D `subscribe_digest` correctness batch); coordinate with BUG-010 pattern (Session I source resolution — reuse `get_source_by_username` as pre-validation step on write surfaces). |

**Real-fire verified 2026-05-31 (core)** in group `vps-watch-test-grp` (chat_id `-5279672667`) against prod SHA `39b6ba2` — original Test D trace observed closed: «pro fendocrinologist» (with a space) produced the explicit rejection «Канал «pro fendocrinologist» содержит пробелы — Telegram usernames не могут содержать пробелы. Возможно, вы имели в виду «profendocrinologist»?», never silently underscored to `pro_fendocrinologist`. Mirrors the BUG-037 real-fire closure precedent ([`HANDOFF_BUG037_2026-05-30.md`](HANDOFF_BUG037_2026-05-30.md)). Status unchanged (`resolved`). **NB — two NEW residual gaps surfaced on adjacent surfaces:** (a) the clarification suggestion is a dead-end — the follow-up «да» is not actionable (no FSM armed for the clarification) → **BUG-039**; (b) the deterministic guard is bypassable — Gemini sometimes strips the space upstream so the validator never sees it and a `profendocrinologist` preview is produced directly → **BUG-041**. See [`SMOKE_TEST_BUG031_034_2026-05-30.md` § Results 2026-05-31](SMOKE_TEST_BUG031_034_2026-05-30.md).

---

### BUG-035 — `unsubscribe_digest` does not invalidate pre-loaded APScheduler job (orphan-tick after mid-flight unsubscribe)

| Поле | Значение |
|---|---|
| **Severity** | **Critical** (correctness: after `unsubscribe_digest` hard-deletes a subscription row from `digest_subscriptions`, the corresponding APScheduler in-memory job continues running and fires at its next scheduled tick anyway — delivering an orphan digest to the target channel/chat using stale subscription data; observed once in Test C cleanup, but deterministic shape suggests 100% reproducibility for any mid-flight unsubscribe of a subscription whose APScheduler job has already been loaded into memory; **closely related to but distinct from pre-existing BUG-030** (`digest_scheduler_initial_load` startup race surfaced during 2026-05-24 step-4 deploy — BUG-030 is a startup-time race where scheduler initial-load fails; BUG-035 is a mid-flight unsubscribe → orphan-job race where the in-memory job continues executing after the DB row is deleted); operational impact: orphan deliveries to channels/chats that the user explicitly unsubscribed from, potentially confusing real subscribers + breaking trust in the unsubscribe contract) |
| **Status** | `resolved` (merged 2026-05-25 via [PR #112](https://github.com/AlexEfimov/TG_parser/pull/112) — `fix(scheduler): synchronously remove APScheduler job on unsubscribe (BUG-035)`; landed on `main` as part of HEAD `656f23c`. Filed 2026-05-24 during Wave 1 Step 4 VPS watch OP-2 / OP-3 interactive tests session — see [`WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md` § T+10h45m OP-2 / OP-3 interactive tests results](WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md)) |
| **Component** | `tg_parser/services/scheduler_service.py` (APScheduler job-lifecycle hooks — `add_cron_task` / `remove_cron_task`); `tg_parser/services/digest_service.py` `delete_subscription_for_user` (must call scheduler hook to remove the APScheduler job after the DB delete); `tg_parser/bot/main.py` reconcile-loop `_reconcile_subscriptions` (refresh_interval default 60s — does NOT remove orphan in-memory jobs that no longer have a DB row, OR does so but with a 60s lag that misses ticks falling in the gap window); APScheduler `BackgroundScheduler.remove_job` semantics (verify whether removal is atomic with in-flight ticks) |
| **Discovered** | 2026-05-24T~21:00Z (Test C cleanup), Alexander, prod VPS bot `@Tgingest_bot`; Test C subscription `5d8b83ad-…` (cron `0 * * * *` `Europe/Moscow`) was hard-deleted via `unsubscribe_digest` at ~20:58Z; the 21:00 UTC tick fired anyway and delivered «Ежечасный дайджест profendocrinologist» digest to R-1 channel (`@vps_watch_test_r1_Alex`) using stale subscription metadata — same prod content as Test A's earlier successful delivery |
| **Linked** | **BUG-030** (companion — `digest_scheduler_initial_load` startup race surfaced during 2026-05-24 step-4 deploy; both bugs touch scheduler-DB consistency, but at different lifecycle phases — BUG-030 is startup, BUG-035 is mid-flight delete); BUG-031 / BUG-032 (Test C / D upstream bugs that produced the subscription which then needed unsubscribe — the test sequence that surfaced BUG-035); BUG-022 (subscribe-tool idempotency — adjacent contract surface, suggests broader scheduler-hook audit needed); ADR 0008 polymorphic target (the `target.kind=channel` cron-tick path was the one that fired the orphan delivery — new step-4 surface) |
| **Symptoms (production trace, 2026-05-24 ~20:58Z → ~21:00Z, Test C cleanup)** | (1) ~20:58Z: operator called `unsubscribe_digest(5d8b83ad-…)` → MCP returned `{"deleted": true}`; DB row was hard-deleted (verified via `list_digests` cross-check post-unsubscribe — row absent). (2) ~21:00Z: bot delivered «Ежечасный дайджест profendocrinologist» digest message to `@vps_watch_test_r1_Alex` (R-1 channel) — the cron tick fired despite the DB row no longer existing; the delivered content was the same `profendocrinologist` digest as Test A's earlier successful delivery, suggesting the scheduler job had already cached the subscription metadata in memory. (3) Next would-be tick at 22:00 UTC — should NOT fire (the in-memory job should age out of cache OR the next reconcile-loop tick should have cleaned it up by then) but this was not directly verified in the watch window. |
| **Root cause (MEDIUM-HIGH confidence on symptom; needs code trace for exact lifecycle gap)** | **Hypothesis A (most likely):** `digest_service.delete_subscription_for_user` does NOT call `scheduler.remove_job(f"digest:{sub.id}")` after the DB hard-delete — the APScheduler job remains armed in memory and fires at its next cron tick; the reconcile-loop in `tg_parser/bot/main.py` (refresh_interval=60s) eventually detects the orphan and removes it, but only on the NEXT reconcile cycle, leaving a window where 1+ ticks can fire. **Hypothesis B:** the scheduler-remove call exists but is racing with the in-flight cron tick — APScheduler's `BackgroundScheduler.remove_job` may not interrupt a job that is already in the misfire-grace window or has been picked up by an executor thread. **Hypothesis C:** the scheduler-remove call is only triggered via the reconcile-loop, not synchronously from the unsubscribe path — i.e. the design relies on eventual consistency via reconcile rather than immediate consistency via direct scheduler API call. Regardless of root cause, the structural fix is to call `scheduler.remove_job` SYNCHRONOUSLY from `delete_subscription_for_user` BEFORE returning success to the user, and to use `remove_job` semantics that wait for any in-flight tick of that job to complete (or use APScheduler's `pause_job` followed by `remove_job` pattern). **Verification needed**: (1) `grep -n "remove_job\|remove_cron_task" tg_parser/services/digest_service.py tg_parser/services/scheduler_service.py tg_parser/bot/main.py` to locate current scheduler-hook coverage; (2) trace bot log at ~20:58Z → ~21:00Z for `removed_cron_task` event for `digest:5d8b83ad-…`; (3) review APScheduler docs for `remove_job` atomicity guarantees. |
| **Why CI didn't catch** | (a) Step-4 `unsubscribe_digest` tests likely use a mocked scheduler (in-memory or asyncio TaskGroup) — they verify DB delete and assert `deleted=True` but do NOT exercise the real APScheduler job-lifecycle. (b) No e2e test for «create subscription with cron tick in N seconds, unsubscribe within N seconds, assert no orphan tick fires». (c) Reconcile-loop tests likely focus on add-orphan (subscription created externally) detection, not delete-orphan (subscription deleted but job still alive). **Closure plan**: integration test `test_unsubscribe_digest_removes_apscheduler_job_atomically` — use real APScheduler `BackgroundScheduler` with a `*/30 * * * * *` cron (every 30s), create subscription, sleep 5s, unsubscribe, sleep 35s, assert no `digest_tick_fired` event in that window. Also: `test_reconcile_loop_removes_orphan_jobs` — simulate manual DB delete bypassing the service layer, assert reconcile-loop removes the orphan within `refresh_interval`. |
| **Proposed fix** | **Layer A (synchronous scheduler hook, ~10 LOC):** in `tg_parser/services/digest_service.py` `delete_subscription_for_user`, after the DB hard-delete commits successfully, call `await self.scheduler_service.remove_cron_task(f"digest:{sub.id}")` BEFORE returning `(True, None)`. Symmetric change in `watchlist_service.delete_interest_for_user` if watchlist matching has its own scheduler jobs (audit needed). **Layer B (atomicity guarantee, ~5 LOC):** in `scheduler_service.remove_cron_task`, wrap `scheduler.remove_job(task_id)` in a try/except for `JobLookupError` (idempotent — already removed by reconcile-loop is OK) and emit a `removed_cron_task` structlog event with `task_id`, `reason="user_unsubscribe"`. **Layer C (reconcile-loop tightening, ~10 LOC):** reduce `refresh_interval` from 60s to 15s OR add an explicit refresh trigger from the unsubscribe path (so reconcile fires immediately, providing belt-and-suspenders against Layer A failures). **Recommended scope**: A + B in single PR (treat as Critical step-4 hotfix because the orphan-tick contract violation could deliver real digests to real users who unsubscribed); Layer C deferred to follow-up. **NB**: coordinate with BUG-030 (`digest_scheduler_initial_load` startup race) since both bugs touch scheduler-DB consistency; consider a single scheduler-hardening PR covering both. |
| **Workaround (current, in-place)** | Operator: after `unsubscribe_digest`, wait at least one `refresh_interval` (60s) before assuming the orphan-tick risk window has closed; OR manually call `scheduler.remove_job(f"digest:{sub_id}")` from a debug shell. Better: do NOT unsubscribe within `cron_expression` interval of a scheduled tick — wait for a quiescent window. |
| **Evidence** | Test C cleanup sequence on 2026-05-24 ~20:58Z (unsubscribe) → ~21:00 UTC (orphan-tick delivery to R-1). The orphan digest message in `@vps_watch_test_r1_Alex` was observed by operator; subscription DB row was confirmed absent via `list_digests` at the same time. The orphan delivery content («Ежечасный дайджест profendocrinologist») matches what Test A's earlier successful delivery contained, confirming the scheduler used stale subscription metadata from in-memory job state rather than re-reading from DB. |
| **Planned fix** | TD-scheduler-unsubscribe-atomicity; treat as Critical step-4 hotfix candidate; coordinate with BUG-030 in single scheduler-hardening PR. |

---

### OBS-001 — Watchlist matcher does not update `last_checked_at` even after successful manual `trigger_pipeline` run (observation, not yet a bug)

| Поле | Значение |
|---|---|
| **Severity** | **Observation** (not yet adjudicated as bug; potential UX / operational issue for watchlist freshness telemetry; no data loss; needs investigation outside the watch window) |
| **Status** | **`CLOSED / expected-behaviour`** (resolved 2026-05-29 via read-only investigation spike — see closure block below + [`OBS_001_INVESTIGATION_2026-05-29.md`](OBS_001_INVESTIGATION_2026-05-29.md)). Filed 2026-05-24 during Wave 1 Step 4 VPS watch OP-2 / OP-3 interactive tests session — see [`WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md` § T+10h45m OP-2 / OP-3 interactive tests results](WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md). NOT promoted to a structural BUG; one Low-severity telemetry follow-up filed as **ENH-001** (below). |
| **Component** | `tg_parser/services/watchlist_service.py` (watchlist matcher hook — invocation point in scheduler / pipeline); `tg_parser/services/pipeline_service.py` (full-pipeline orchestration — verify whether watchlist matcher is called from `trigger_pipeline` path or only from a separate scheduled hook); `tg_parser/storage/sqlalchemy/interest_repo.py` (`last_checked_at` update semantics — does the matcher update it always, or only when a match is found?); `tg_parser/services/scheduler_service.py` (separate scheduled matcher hook — verify cron expression and active state) |
| **Discovered** | 2026-05-24T~21:13Z (Test E follow-up), Alexander, prod VPS via MCP `trigger_pipeline` + `get_watchlist_matches` + DB cross-check |
| **Linked** | F11 watchlist matcher contract; ADR 0008 polymorphic target (new step-4 watchlist `target.kind=channel` surface — Test E exercised this); BUG-022 (subscribe-tool idempotency — adjacent contract surface); previous WATCH notes for context on pre-existing 5 active watchlists in prod DB |
| **Symptoms (observation, 2026-05-24 ~21:13Z, Test E follow-up)** | (1) Created new watchlist `2184bced-…` via `subscribe_watchlist(target.kind=channel, channel_ids=["profendocrinologist"])` at ~21:08Z. (2) Called `trigger_pipeline(channel_id=profendocrinologist)` at ~21:11Z → returned `{"status": "completed", "last_success_at": "2026-05-24T21:13:18Z", "fail_count": 0}` (pipeline executed cleanly). (3) Called `get_watchlist_matches(2184bced-…)` at ~21:15Z → returned **0 matches**. (4) DB cross-check at ~21:16Z: our new interest has `last_checked_at = null` (never updated even though the pipeline ran); ALL 5 pre-existing active `watch_interests` have `last_checked_at = 2026-05-24T11:48:25Z` (~10h before the watch session — i.e. stuck since before deploy). Suggests watchlist matcher is either (a) not running on `trigger_pipeline` (only on separate scheduled hook), (b) running but not updating `last_checked_at` unless a match is found, or (c) running but the scheduled matcher hook is silently failing. |
| **Root cause hypotheses (LOW confidence — needs investigation)** | **Hypothesis A:** Watchlist matcher is invoked only from a separate scheduled cron hook (e.g. every 10 min), NOT from the `trigger_pipeline` path — that hook may be silently failing OR not configured at all on this VPS deploy. Verify via `grep -rn "watchlist_matcher\|match_interests\|run_matcher" tg_parser/services/ tg_parser/bot/main.py`. **Hypothesis B:** Matcher runs but only updates `last_checked_at` when a match is found (i.e. `last_checked_at` was misnamed — it's actually `last_matched_at`); the 5 pre-existing interests last had matches at `2026-05-24T11:48:25Z` and have had none since. Verify by inserting a watchlist with broad keywords (e.g. «новость», «вакансия») and re-running `trigger_pipeline`, then checking whether `last_checked_at` advances. **Hypothesis C:** Step-4 ADR 0008 polymorphic target schema migration broke the matcher's query for `target.kind=channel` watchlists — the migration added `target_kind` / `channel_id` columns but the matcher's WHERE clause may still filter on the pre-step-4 shape, silently skipping all `target.kind=channel` rows. Verify by checking matcher SQL for `target_kind` filter. **Hypothesis D:** Matcher runs but is gated on `last_checked_at IS NULL OR last_checked_at < NOW() - threshold` — and the threshold is too long (e.g. 24h) so newly-created watchlists with `last_checked_at=null` get matched but pre-existing ones that already have a stale `last_checked_at` from 10h ago aren't yet eligible. Verify by reading the matcher SQL gate. |
| **Investigation steps (recommended)** | (1) `grep -rn "watchlist_matcher\|run_matcher\|match_interests\|last_checked_at" tg_parser/` to locate the matcher entrypoint and its update semantics; (2) check `docker logs --since 2026-05-24T21:00Z tg_parser` for any `matcher_run` / `match_evaluated` events around the test window; (3) inspect APScheduler job list (`scheduler.get_jobs()`) for any matcher-related cron jobs and their last/next run times; (4) re-run Test E with broader keywords (e.g. add the test channel `profendocrinologist` source content to the corpus and create an interest with keyword «эндокринология») and observe whether matches materialize. |
| **Impact (current best estimate)** | **Low operational impact** if Hypothesis B holds (matcher runs but `last_checked_at` is mis-named); **HIGH operational impact** if Hypothesis A or C holds (matcher silently not running on any subset of watchlists — would mean F11 contract violated for all `target.kind=channel` users since step-4 deploy, potentially missing alerts on tracked topics). Distinguishing requires the investigation steps above. |
| **Not yet adjudicated as bug because** | (a) Only observed once with a single watchlist that may have legitimately had no keyword matches in the recent pipeline window; (b) `last_checked_at` semantics may be «last match found» rather than «last evaluated» (Hypothesis B) — would make the observation expected behavior; (c) full investigation needed to distinguish the four hypotheses before filing as a structural bug. **Promote to BUG-NNN** if Hypotheses A or C are confirmed (matcher silently not running for `target.kind=channel` watchlists is a step-4 regression). |
| **Evidence** | Test E sequence on 2026-05-24: `subscribe_watchlist(channel_ids=["profendocrinologist"])` → `interest_id=2184bced-5f99-4705-83ce-df96bc89636c`; `trigger_pipeline(channel_id=profendocrinologist)` → `last_success_at=2026-05-24T21:13:18Z, fail_count=0`; `get_watchlist_matches(2184bced-…)` → 0 matches; DB cross-check `SELECT id, title, last_checked_at FROM watch_interests WHERE id='2184bced-…'` → `last_checked_at=null`. Comparison: `SELECT id, title, last_checked_at FROM watch_interests WHERE is_active=true` → 5 active rows ALL with `last_checked_at=2026-05-24T11:48:25Z`, suggesting universal stagnation since before watch session. |
| **Planned next step** | ~~TD-watchlist-matcher-investigation~~ — **DONE 2026-05-29.** See closure block. |

**Closure 2026-05-29 (read-only investigation spike — full report: [`OBS_001_INVESTIGATION_2026-05-29.md`](OBS_001_INVESTIGATION_2026-05-29.md)):**

Verdict per hypothesis: **A — SPLIT** (CONFIRMED matcher is wired ONLY into the hourly scheduler tick `_process_source`, gated on `new_doc_refs`, and `trigger_pipeline` never invokes the matcher; but REJECTED "failing/unconfigured" — live log `watchlist.check_interests` @2026-05-29T17:04:43Z, all 5 active interests' `last_checked_at` advanced to 2026-05-29). **B — REJECTED** (`touch_checked` is called unconditionally per active interest each tick, `watchlist_service.py:820-824`, independent of `touch_match`; `watch_matches` empty + `last_match_at` null for all, yet `last_checked_at` advanced on a `candidates=0` tick). **C — REJECTED** (matcher selects on the F11 `channel_ids[]` source array `watch_interest_repo.py:213-222`, orthogonal to ADR-0008 `target_kind`/`channel_id` delivery columns; migration could not have broken selection). **D — REJECTED** (no `last_checked_at` time-gate exists; only gate is `new_doc_refs` non-empty).

**Root cause:** `last_checked_at` = "timestamp of the last hourly tick that found NEW docs for a watched channel" — NOT "last evaluated." Two benign facts produce the symptom: (1) matcher bound to hourly tick + gated on new docs; (2) `trigger_pipeline` runs `run_full_pipeline` + `run_embedding` only, never the matcher. The OBS-001 test row `2184bced` was soft-deleted ~16 min after creation (before any new-doc tick covered it) → `last_checked_at` stays null forever (inactive rows excluded). The "5 stuck @11:48Z" rows were simply between new-doc ticks; all advanced today. **No functional defect — F11 contract intact.**

---

### ENH-001 (Low — observability) — `last_checked_at` is a misleading watchlist-freshness signal

**Filed:** 2026-05-29, spun out of OBS-001 closure (the only real residual issue — operator-facing telemetry, not a functional defect).

**Symptom:** `last_checked_at` reads as "last time this interest was evaluated" but actually means "last hourly tick that found NEW docs for a watched channel." It stays `null`/stale for newly-created interests and for quiet channels even though the matcher is healthy, and `trigger_pipeline` deceptively never advances it. This conditions operators to misread a healthy matcher as stuck (exactly what triggered OBS-001).

**Component:** `tg_parser/services/watchlist_service.py:820-824` (`touch_checked` invocation, gated upstream on `new_doc_refs` at `:747`); `tg_parser/services/scheduler_service.py:297-301` (matcher wiring); MCP projection of `last_checked_at` in watchlist read tools.

**Proposed fix (pick one):**
* **(a)** Add a true matcher-liveness gauge (e.g. Prometheus `tg_watchlist_last_tick_at` / per-channel `last_evaluated_at`) and re-document/rename the existing field as "last tick with new docs" so the semantics are explicit; OR
* **(b)** Call `touch_checked` for ALL active interests on EVERY tick (including the empty-`new_doc_refs` branch) so the field reflects evaluation cadence rather than new-doc cadence.

**Regression-test shape:** scheduler-tick test asserting `touch_checked` is invoked for active interests when `candidates=0` (empty `new_doc_refs`); plus a test pinning whether the `trigger_pipeline` path does/does-not advance the field per the chosen semantics.

**Severity rationale:** Low — no data loss, no missed alerts, matcher fully functional; purely an operator-confusion / observability-clarity issue.

**Defer to:** Step 5 quality work (alongside BUG-036/037 observability cluster) or housekeeping sprint.

**Resolution 2026-05-29 (branch `fix/enh-001-watchlist-last-checked-telemetry`, merged 2026-05-29 via [PR #141](https://github.com/AlexEfimov/TG_parser/pull/141) — `fix(watchlist): advance last_checked_at every tick for honest matcher telemetry (ENH-001)`; landed on `main` as part of HEAD `656f23c`):** Implemented **option (b)**. `WatchlistService.check_interests` now stamps `last_checked_at` on every active interest on EVERY tick — including quiet ticks with empty `new_doc_refs` (the early `if not new_doc_refs: return []` is gone; a dedicated empty-tick branch touches all active interests and returns). The scheduler hook `run_watchlist_check_for_channel` lost its `no_new_docs` fast-path, and `_process_source` now calls the watchlist check OUTSIDE the `if new_doc_refs:` block so quiet ticks still reach the matcher (matching/scoring stays gated on new docs — behaviour unchanged). Field semantics re-documented in `domain/models.py` (`WatchInterest.last_checked_at`), `mcp_server.py` (`WatchInterestInfo` + `list_watchlists` docstring). **`trigger_pipeline` deliberately still does NOT advance `last_checked_at`** (the matcher is wired only into the hourly scheduler tick, not `run_full_pipeline`); pinned by `tests/test_enh001_last_checked_telemetry.py::test_trigger_pipeline_path_does_not_wire_matcher`. Regression proof: `tests/test_enh001_last_checked_telemetry.py` (PG-gated) + updated `tests/test_f11_scheduler_hook.py` / `tests/test_watchlist_service.py`; fail-before-fix verified by stashing the source change. Ran `TEST_POSTGRES=1 pytest` over the watchlist+scheduler subset → 162 passed. **Tradeoff accepted:** quiet ticks now open a watchlist-repos session + build the service even with no new docs (was previously fast-pathed); cost is bounded (hourly cadence, one UPDATE per active interest, embedding client constructed lazily and unused) and judged acceptable vs. the telemetry win.

---

### BUG-036 (Medium — ops/observability) — Grafana alert-rule UI-state drift; noData semantics not provisioned-as-code

**Severity history:** Originally filed Low 2026-05-25T06:11Z. **Bumped Low → Medium at closure-session 2026-05-25T11:15Z** — see § *Closure-session 2026-05-25T11:15Z update* below.

**Discovered:** Wave 1 step 4 VPS watch finalization, 2026-05-25T06:11Z.

**Symptom:** Operator/agent attempted at 2026-05-24T18:30Z to set `noDataState: OK` for Grafana alert rule `tg_api_5xx_spike` (folder `wave1-step4-watch`) via Grafana UI in order to suppress webhook-issue noise from DatasourceNoData transitions. Patch claim recorded in `docs/notes/HANDOFF_NEW_CHAT_WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md:42`. However, at 22:11Z (#100) and 02:16Z next day (#101) the same alert rule re-emitted `alertname=DatasourceNoData` with `status="firing"` and identical fingerprint `47991b0914dd7148` — proving the noData state remained `Alerting/NoData`, not `OK`. Either the UI edit was not saved, or Grafana state drifted back (e.g., container restart resetting non-provisioned rule state).

**Impact:** Operator workflow gets spurious GitHub issues every `repeat_interval` (default 4h) for `tg_api_5xx_spike` during any data-feed gap on the Prometheus 5xx metric. No production user impact, but it pollutes the watch-window incident channel and conditions operators to ignore real RED alerts.

**Recommended fix:**
1. Provision all 3 Grafana alert rules (`tg_parser_bot_down`, `tg_parser_api_down`, `tg_api_5xx_spike`) via file-based provisioning at `docker/grafana/provisioning/alerting/wave1_step4.yaml` with definitive `noDataState: OK` and proper `for: 5m` config.
2. Bind the contact-point `cursor-watch-webhook` config to the same provisioning file so it survives Grafana restarts.
3. Add an idempotency test that confirms a Grafana restart preserves `noDataState=OK` for these rules.

**Workaround until fixed:** During watch windows, operator manually re-applies UI edit and silences the contact point if noise becomes disruptive.

**Defer to:** Step 5 quality work.

**Related issues:** #100, #101 (both closed with deferral comment), #96, #98 (earlier instances of same root cause, closed). #102 (06:20Z race-acceptable, ~1 min before operator's second UI patch at 06:21Z), #103 (10:25Z), #104 (10:31Z) — all three closed at closure-session 2026-05-25T11:15Z, see § *Closure-session 2026-05-25T11:15Z update* below.

**Closure-session 2026-05-25T11:15Z update:**

Despite the operator's second `noDataState=Normal` UI patch applied at ~2026-05-25T06:21Z, **three additional GitHub issues fired** during the remainder of the watch window with the same fingerprint `47991b0914dd7148` / rule `tg_api_5xx_spike`:

- **#102** at 2026-05-25T06:20:25Z — fired ~1 min *before* the 06:21Z UI patch was applied; treated as race-acceptable.
- **#103** at 2026-05-25T10:25Z — fired **4h+ after** the 06:21Z UI patch; identical fingerprint to #100/#101.
- **#104** at 2026-05-25T10:31Z — same fingerprint as #103, re-firing inside Grafana's `repeat_interval` (4h default) window.

This confirms the UI-state patch did **not persist** across Grafana's evaluation cycle. Either the UI save silently failed, or Grafana drifted back to `Alerting/NoData` after some internal state-recompute. **Severity bumped Low → Medium** based on observed ops impact (3 spurious post-patch issues during a single 24h watch window, requiring closure-session cleanup labour).

**Recommendation unchanged:** provision all three Wave 1 step 4 alert rules as code in step 5 at `docker/grafana/provisioning/alerting/wave1_step4.yaml` with explicit `noDataState: OK`, `for: 5m`, and contact-point binding so they survive container restarts and Grafana state-recomputes.

---

### BUG-037 (Low — ops/automation) — Cursor webhook automation classifier instability — identical Grafana payload routed to different issue title prefixes

**Discovered:** Wave 1 step 4 VPS watch finalization, 2026-05-25T06:11Z.

**Symptom:** Cursor automation `7b35ca01-a7d1-4c3a-bb8b-940918e506d6` (webhook ingress for Grafana alerts) opens GitHub issues with auto-generated title prefixes. Investigation of #100 vs #101 showed that the same underlying Grafana payload — identical fingerprint `47991b0914dd7148`, identical alert rule `tg_api_5xx_spike`, identical `startsAt` — got routed to two different title prefixes at different times: `[5xx]` for #100 (22:11Z) but `[alert]` for #101 (02:16Z next day, 4h later).

**Impact:** Inconsistent issue titles break dashboards, search, and triage rules that filter by prefix. Easy to overlook a repeat-fire incident as a new alert if the prefix changes. Low severity because issue body is intact and rule name is grep-able.

**Recommended fix:** Inspect the automation's payload-classifier logic at `7b35ca01…` workflow definition. Likely cause: the classifier branches on a field that's sometimes empty (`labels.alertname` vs `labels.rulename` vs `commonLabels.severity`) and falls back to a generic prefix. Make the branch deterministic — prefer `labels.rulename` first, then `labels.alertname`, then generic `[alert]` only if both are absent.

**Workaround until fixed:** Triage by alert-rule fingerprint or rule name in body, not by title prefix.

**Defer to:** Step 5 quality work, or earlier if `7b35ca01` automation logic is easily readable from Cursor UI.

**Related:** investigation report 2026-05-25T06:11Z (foreground), this watch session's batched FIN section.

**Resolved: 2026-05-30 — deterministic STEP 2 classifier (applied & verified by real-fire; see Verification below).**

**Root cause (confirmed this session):** the automation's STEP 2 classifier defined its title-prefix buckets by PromQL/metric expressions, time windows, and rates (e.g. `tg_api_requests_total{status=~"5.."}` spike, `up{job=...}==0 for >5m`), but a single Grafana webhook payload carries none of those — only `alerts[].labels.alertname` etc. — so the agent had to *infer* the `alertname=tg_api_5xx_spike` → 5xx mapping via LLM judgment, which is non-deterministic and produced the `[5xx]`↔`[alert]` flip.

**Fix (point-wise — STEP 1, STEP 3, RULES unchanged):** STEP 2 was replaced with a deterministic resolution keyed only on the alert-name string (never on PromQL/metric expressions, windows, or rates). Applied STEP 2 text:

```text
2. Determine the title prefix DETERMINISTICALLY from the alert-name string only —
   never from PromQL/metric expressions, time windows, or rates.
   Resolve `name` = first non-empty of:
       alerts[0].labels.rulename
       alerts[0].labels.alertname
       alertname            (manual curl, top-level)
       commonLabels.alertname
       event.title          (Sentry)
     else ""
   Lowercase `name`; match in THIS fixed order, first hit wins:
     name == "tg_api_5xx_spike"      OR contains "5xx"                       -> [5xx]
     name == "tg_parser_bot_down"    OR (contains "bot" and "down")          -> [bot down]
     name == "tg_parser_api_down"    OR (contains "api" and "down")          -> [api down]
     contains "digest_scheduler_initial_load_failed"                          -> [BUG-030 elevation]
     contains "permission_denied" OR "soft_deactivation" OR "soft-deactivation" -> [soft-deactivation]
     contains "channel_publish_failed" OR (contains "publish" and "fail")     -> [channel-publish-fail]
     name is non-empty                                                        -> "[" + name + "]"
     name is empty                                                            -> [alert]
```

**How it was applied (workaround — important):** the `cursor-backend-control` MCP server (Cursor Automations `get_automation` / `update_automation`) was **unavailable** this session — calls returned `MCP server does not exist: cursor-backend-control` and its descriptor folder had no tools registered (runtime-registration defect, see [`cursor-automations-app-control-workaround.md`](cursor-automations-app-control-workaround.md)). So instead of `update_automation`, we used the `cursor-app-control` `open_automation({automationId, view:"edit"})` tool to open the automation in the operator's authenticated Glass editor; the operator pasted the new STEP 2 and clicked **Save** manually (human-in-the-loop). The automation remains **enabled**. Closed issues #100/#101/#103/#104 were not touched.

**Provisioning note (3 of 6 buckets are real):** only 3 of the 6 buckets correspond to alert rules that actually exist as code (BUG-036 / PR #140) in `docker/grafana/provisioning/alerting/wave1_step4.yaml` — `tg_parser_bot_down`, `tg_parser_api_down`, `tg_api_5xx_spike`. The other 3 (BUG-030 elevation, channel-publish-fail, soft-deactivation) exist only as runbook guidance with naming drift, so the fix uses exact-match for the 3 real ones and defensive OR-matching covering both documented name variants for the other 3.

**Status:** resolved & verified 2026-05-30 — fix applied AND confirmed by real-fire verification (see Verification below). See handoff [`HANDOFF_BUG037_2026-05-30.md`](HANDOFF_BUG037_2026-05-30.md).

**Verification (real-fire, PASSED 2026-05-30):** after the deterministic STEP 2 was saved, the same noData alert fired organically twice on its normal ~4h repeat cadence and both opened issues resolved to `[5xx]` — no `[alert]` flip:
- #146 (2026-05-30T13:00:39Z) — `[5xx] DatasourceNoData — rule tg_api_5xx_spike (Wave 1 step 4 VPS watch)`
- #148 (2026-05-30T17:06:57Z) — `[5xx] tg_api_5xx_spike — NoData state (Wave 1 step 4 VPS watch)`

Both issues carry the exact bug fingerprint `47991b0914dd7148` with `alertname=DatasourceNoData` and `rulename=tg_api_5xx_spike` — the identical payload that previously flipped between `[5xx]` (#100) and `[alert]` (#101/#124). Root-cause refinement worth noting: the real payloads are Grafana `DatasourceNoData` meta-alerts where `labels.alertname="DatasourceNoData"` but `labels.rulename="tg_api_5xx_spike"`; the old classifier sometimes keyed on `alertname` (→ `[alert]`) and sometimes on `rulename` (→ `[5xx]`), and the fix's `rulename`-first resolution makes it deterministic.

---

### BUG-038 (Low/Medium — ops/observability) — Live Grafana `tg_api_5xx_spike` rule uses stale metric name → only emits `DatasourceNoData`, blind to real 5xx

**Discovered:** 2026-05-30, while reconciling the live VPS Grafana rule against the provisioned-as-code rule landed in BUG-036 / PR #140. Previously untracked except as a comment in [`docker/grafana/provisioning/alerting/wave1_step4.yaml`](../../docker/grafana/provisioning/alerting/wave1_step4.yaml).

**Symptom:** The live Grafana rule `tg_api_5xx_spike` on the VPS only ever fires `alertname=DatasourceNoData` (fingerprint `47991b0914dd7148`, the same noise tracked in BUG-036 / BUG-037) and never fires on an actual 5xx burst, even when real 5xx responses are present in Prometheus.

**Root cause:** The LIVE rule queries a metric name that does not exist — `tg_parser_http_http_requests_total{...,status="5xx"}` — with a doubled `http_http` prefix and the literal label `status="5xx"`. The provisioned-as-code rule (BUG-036 / PR #140) in `docker/grafana/provisioning/alerting/wave1_step4.yaml` carries the CORRECTED query `tg_parser_http_requests_total{...,status=~"5.."}`. The live VPS rule still runs the stale pre-correction query because `656f23c` (which carries the corrected provisioned rule) has not yet been deployed to the VPS.

**Impact:** Until `656f23c` is deployed, the live rule can never match real data, so it only ever emits `DatasourceNoData` — i.e. the 5xx alert is effectively blind to real 5xx bursts (it would miss a genuine 5xx incident) while simultaneously generating the `DatasourceNoData` noise tracked in BUG-036. No production user impact, but the alert provides false coverage assurance.

**Resolution:** Deploy `656f23c` to the VPS (the provisioned rule in `docker/grafana/provisioning/alerting/wave1_step4.yaml` is already corrected). Post-deploy, verify the live `tg_api_5xx_spike` rule query matches the provisioned `tg_parser_http_requests_total{...,status=~"5.."}` (not the stale `tg_parser_http_http_requests_total` / `status="5xx"`).

**Status:** open / resolved-pending-deploy — code fix already merged into `main` (BUG-036 / PR #140, on HEAD `656f23c`); resolves on the VPS the moment `656f23c` is deployed and the live rule reloads from provisioning.

**Defer to:** next VPS deploy of `656f23c`. Verification item added to [`docs/runbooks/WAVE1_STEP4_VPS_POST_CLOSURE_CLEANUP.md`](../runbooks/WAVE1_STEP4_VPS_POST_CLOSURE_CLEANUP.md).

**Related:** BUG-036 (same rule's noData UI-state drift / provisioning-as-code), BUG-037 (`DatasourceNoData` webhook title-prefix routing for the same fingerprint).

---

### BUG-039 (Severe — bot UX / correctness) — Channel-name clarification suggestion is a dead-end; the opaque «не совсем понимаю» catch-all (BUG-032's target) resurfaces on the clarification surface

**Discovered:** 2026-05-31 production real-fire smoke (`SMOKE_TEST_BUG031_034_2026-05-30.md`), human operator in group `vps-watch-test-grp` (chat_id `-5279672667`), bot `@Tgingest_bot`, prod SHA `39b6ba2`.

**Symptom:** When the BUG-034 guard rejects a space-containing channel name and suggests a correction, the user's affirmative reply to that suggestion is not actionable and instead drops to the generic NLU fallback:
- 23:49:52 bot: «Канал «pro fendocrinologist» содержит пробелы … Возможно, вы имели в виду «profendocrinologist»?»
- 23:50:03 user: «да»
- 23:50:04 bot: «Я не совсем понимаю ваш ответ. Пожалуйста, переформулируйте ваш запрос…»
The same opaque «Я не совсем понимаю ваш ответ» reappeared at 23:52:11 and 23:52:23. So BUG-032's whole point (kill the opaque catch-all, accept «да») holds at the subscribe-confirm gate but is defeated on this clarification surface.

**Root cause (HIGH confidence — code-traced):** The clarification message is a **tool error**, not a preview. `validate_channel_username` returns the «содержит пробелы … Возможно, вы имели в виду X?» dict with `error_class="InvalidChannelUsername"` and a `suggestion` (`tg_parser/utils/channel_id.py:181-195`); `_exec_subscribe_digest` returns that error dict verbatim (`tg_parser/bot/tools.py:2556-2558`). Because the result is an `error` and NOT `{"preview": True}`, the agent loop never sets `preview_pending` (`tg_parser/bot/agent.py:306-319`), so the handler never arms `ConfirmFlow.awaiting_confirmation` (`tg_parser/bot/handlers.py:391-392`). The clarification text the user sees is LLM-paraphrased and carries no FSM state behind it. The user's «да» therefore arrives in `handle_text` with `current_state is None` (`tg_parser/bot/handlers.py:325-331`), so it is NOT routed to the deterministic `_handle_confirmation_response` / `classify_confirmation_token` path (which is scoped strictly to `ConfirmFlow.awaiting_confirmation` — `tg_parser/bot/handlers.py:329, 445`). Instead the bare «да» is sent to `agent.process_message` as a brand-new, **stateless** turn — `contents` is re-initialised to just `[{"role": "user", "parts": [{"text": user_message}]}]` with no conversation history (`tg_parser/bot/agent.py:181-183`). With only the system prompt and a context-free «да», Gemini produces the generic «Я не совсем понимаю ваш ответ» fallback (the phrase now originates LLM-side; the code path that used to emit it was removed by BUG-032 — see `prompts/bot.yaml:48` and the comment at `tg_parser/bot/handlers.py:502-517`). Net: the suggestion is a dead-end because nothing makes accepting it actionable — no FSM is armed, no `suggestion` field is consumed, and there is no conversational memory to anchor «да».

**Impact:** User cannot recover from a single channel-name typo within the flow; they hit a loop of opaque «не совсем понимаю». This is the exact UX failure BUG-032 was filed to eliminate, re-exposed on the clarification surface — hence Severe (blocks the corrective path the BUG-034 fix advertises).

**Suggested fix (future task — NOT in scope here):** Make the clarification a first-class confirm/clarify FSM surface rather than a bare tool error. Options: (a) when `validate_channel_username` returns a `suggestion`, arm a lightweight `ClarifyFlow`/`ConfirmFlow` that stashes the corrected channel id and re-runs the previewed `subscribe_digest` with the suggestion on an affirmative; (b) at minimum, carry a `suggestion`-bearing pending action so the deterministic `classify_confirmation_token` handler fires on «да». Mirror the BUG-002/BUG-031 FSM-arming pattern; keep it server-side (do not rely on LLM discipline).

**Status:** resolved. **Filed:** 2026-05-31. **Resolved:** 2026-05-31 (branch `fix/bug039-042-conversation-layer`, baseline `6ae610f`; PR #TBD — final merge SHA to be recorded on merge).

**Resolution:** Made the channel-name clarification a first-class FSM surface instead of a dead-end tool error. `validate_channel_username` rejections in `_exec_subscribe_digest`/`_exec_subscribe_watchlist` are now decorated with a `clarify_pending` action (`_decorate_clarify_error`, `tg_parser/bot/tools.py`) carrying the tool name, original args, channel index, and the `suggestion`. The agent loop captures `clarify_pending` into `AgentResult` and **short-circuits** with the deterministic clarification text (no second LLM re-author turn) (`tg_parser/bot/agent.py`). `handle_text` arms the new `ClarifyFlow.awaiting_channel_clarification` state (`tg_parser/bot/states.py`); a follow-up «да» is handled deterministically by `_handle_clarification_response` (`tg_parser/bot/handlers.py`), which re-runs the previewed `subscribe_*` with the suggested channel id and transitions to `ConfirmFlow` — the opaque «не совсем понимаю» catch-all no longer reachable on this surface. **Regression tests:** `tests/test_bot_conversation_layer_bug039_042.py::TestBug039ClarificationIsActionable` (5 tests; confirmed FAIL on pre-fix `6ae610f`, PASS post-fix).

**Residual (2026-05-31, real-fire of this fix @ `c0ff6d3`):** the SAME dead-end was found on a DIFFERENT clarification surface — the channel-not-found fuzzy suggestion emitted by `_build_no_results_suggestion` for the read intents (`list_topics`/`search`/`get_cross_channel_stats`), which this fix did not cover. Tracked and closed as **BUG-043** by EXTENDING the same `ClarifyFlow` mechanism to that surface (`clarify_pending` of `kind="read"`). This entry's subscribe-surface fix remains correct/verified — BUG-039 stays `resolved`; see BUG-043.

**Related:** BUG-032 (affirmative-token acceptance scoped only to the subscribe-confirm gate, not the clarification surface), BUG-034 (the clarification message this gap follows on from), BUG-040 (shared systemic root cause — `process_message` is stateless across messages), BUG-002 (FSM `ConfirmFlow` arming pattern to mirror).

**Evidence:** Real-fire transcript 2026-05-31 (group `vps-watch-test-grp`): 23:49:52 clarification → 23:50:03 «да» → 23:50:04 «Я не совсем понимаю ваш ответ. Пожалуйста, переформулируйте ваш запрос…»; repeated 23:52:11 / 23:52:23.

---

### BUG-040 (Severe — bot correctness / context retention) — Bare channel-name reply mid-subscribe-flow routed to the WRONG intent, non-deterministically (no conversational memory)

**Discovered:** 2026-05-31 production real-fire smoke, human operator in group `vps-watch-test-grp` (chat_id `-5279672667`), bot `@Tgingest_bot`, prod SHA `39b6ba2`.

**Symptom:** While the user is trying to subscribe to a digest, a bare channel-name reply is mapped to two different unrelated intents on different turns:
- 23:50:31 user: «profendocrinologist» → 23:50:32 bot: «Подтвердите, пожалуйста, обновление канала profendocrinologist. Текущий статус: active…» (interpreted as a **channel-UPDATE** intent)
- 23:53:05 user: «profendocrinologist» → 23:53:13 bot: «Показываю топ-20 тем канала profendocrinologist…» (interpreted as a **SHOW-TOPICS / `list_topics`** intent)
The subscribe-flow context is lost; the identical bare input resolves to two distinct intents on different turns.

**Root cause (HIGH confidence — code-traced):** `GeminiAgent.process_message` is **stateless across messages** — every invocation rebuilds `contents` from scratch as `[{"role": "user", "parts": [{"text": user_message}]}]` (`tg_parser/bot/agent.py:181-183`); there is no append of prior user/model turns. The only cross-turn memory mechanisms are (1) the FSM `ConfirmFlow`/`PaginationFlow` states (`tg_parser/bot/handlers.py:327-337`) and (2) the read-side `read_context` last-`channel_id` hint injected into the system prompt (`tg_parser/bot/agent.py:377-392`). None of these covers a mid-subscribe clarification (see BUG-039 — no FSM armed), so a bare «profendocrinologist» reaches the LLM with no anchoring context. Gemini then guesses an intent under `functionCallingConfig.mode="AUTO"` (`tg_parser/bot/agent.py:398-400`); with a context-free single token and `temperature=0.2` sampling, the guess is non-deterministic — once `update_channel`/pause-resume-style preview, once `list_topics`. The read_context hint can even actively bias toward the wrong tool: it tells the LLM to reuse the last-read channel id for ambiguous read requests, nudging the bare token toward `list_topics`. The "user is mid-subscribe" intent is retained nowhere, so there is nothing to route on.

**Impact:** Mid-flow replies are silently misclassified, including into a **write-intent preview** (`update_channel`), confusing the user and risking an unintended (though still confirm-gated) action. The behaviour is non-deterministic, so it is hard to reproduce/triage. Severity raised to **Severe** because root-cause is a **systemic** absence of conversational context (confirmed in code), shared with BUG-039, not a one-off mis-route. (No unconfirmed side effect occurred — the misrouted `update_channel` path is still preview/confirm-gated; impact is correctness-of-intent + UX, not data loss.)

**Suggested fix (future task — NOT in scope here):** Introduce bounded conversational memory for the agent loop (carry the last N user/model turns into `contents`, or a structured "active intent" hint), and/or arm an explicit clarify/subscribe FSM so bare replies are interpreted within the in-flight flow rather than re-classified from zero. Coordinate with BUG-039 (same root) so a single FSM/context mechanism closes both. Keep write-intent routing defensible server-side.

**Status:** resolved. **Filed:** 2026-05-31. **Resolved:** 2026-05-31 (branch `fix/bug039-042-conversation-layer`, baseline `6ae610f`; PR #TBD — final merge SHA to be recorded on merge).

**Resolution:** Closed together with BUG-039 via the shared `ClarifyFlow` FSM rather than relying on stateless LLM re-classification. Once a clarification is armed, a bare channel-name reply mid-flow (e.g. «profendocrinologist») is routed deterministically through `_handle_clarification_response` to re-run the in-flight `subscribe_*` — it is NEVER handed back to `agent.process_message`, so it can no longer be non-deterministically misrouted to `update_channel`/`list_topics`. Write-intent routing stays server-side (the FSM, not LLM discipline). **Regression tests:** `tests/test_bot_conversation_layer_bug039_042.py::TestBug040BareTokenStaysInFlow` (4 tests incl. bare-token-stays-in-flow, no-LLM-consultation, negative-cancels, TTL-expiry; confirmed FAIL on pre-fix `6ae610f`, PASS post-fix).

**Related:** BUG-039 (shared systemic root: no conversational memory + no FSM on the clarification surface), BUG-011 (existing read-side `read_context` continuation mechanism — the only cross-turn memory today, and a candidate to generalise), BUG-002 (FSM-arming precedent), BUG-026 (standalone-continuation context-loss analogue).

**Evidence:** Real-fire transcript 2026-05-31 (group `vps-watch-test-grp`): 23:50:31 «profendocrinologist» → 23:50:32 «Подтвердите, пожалуйста, обновление канала profendocrinologist…»; 23:53:05 «profendocrinologist» → 23:53:13 «Показываю топ-20 тем канала profendocrinologist…».

---

### BUG-041 (Medium — bot correctness) — Deterministic BUG-034 space-guard is bypassable: Gemini sometimes auto-corrects «pro fendocrinologist» upstream of the validator

**Discovered:** 2026-05-31 production real-fire smoke, human operator in group `vps-watch-test-grp` (chat_id `-5279672667`), bot `@Tgingest_bot`, prod SHA `39b6ba2`.

**Symptom:** The same «pro fendocrinologist» input (space typo) is handled inconsistently:
- **Rejected** for the embedded space (correct BUG-034 guard) at 23:49:52, 23:51:54, 23:52:39.
- **Silently auto-corrected** at 23:53:37 and 23:54:09 — the same input produced «Preview: создать подписку «Ежечасный дайджест profendocrinologist» …» directly, with no clarification.

**Root cause (HIGH confidence — code-traced; LLM-side, not code-side):** The deterministic BUG-034 guard `validate_channel_username` only fires on what actually reaches it — and `channel_ids` is populated by Gemini's `functionCall.args`, not by the raw user text. In the agent loop the tool args come straight from the model (`tg_parser/bot/agent.py:283, 296-303`) and are handed to `_exec_subscribe_digest`, which validates each entry only at `tools.py:2554-2560`. When Gemini passes the literal `["pro fendocrinologist"]`, the validator sees the space and rejects (`tg_parser/utils/channel_id.py:181-195`) — the guard works. But Gemini frequently **normalises the channel name itself** (drops the space → `["profendocrinologist"]`) before emitting the tool call, in which case the validator never sees a space, accepts the value, and the preview is shown directly. Because LLM extraction is sampled (`temperature=0.2`, stateless per BUG-040), whether the space survives to the validator is non-deterministic turn-to-turn. So the space→correction happens **LLM-side, upstream of the code-side validator**, and the deterministic guarantee BUG-034 was meant to provide is in fact probabilistic. (The auto-corrected outcome happens to pick the right channel, so it is partially benign — but it defeats the explicit "ask to clarify, never guess" contract and makes the guard's coverage unverifiable.)

**Impact:** Medium. The guard cannot be relied on as deterministic; a different typo that the LLM "corrects" to the *wrong* valid-looking username would silently bypass the guard and create an undeliverable subscription with no clarification. No incorrect persistence was observed in this smoke (the LLM's correction matched the intended channel).

**Suggested fix (future task — NOT in scope here):** Add a hard rule in `prompts/bot.yaml` channel-resolution section forbidding the LLM from normalising/guessing channel names (pass the user's token verbatim; never strip embedded whitespace) so the deterministic validator always adjudicates. Defence-in-depth: have the executor additionally verify channel existence via `get_source_by_username` (BUG-010 pattern) so an LLM-"corrected" but non-existent channel is still rejected. The code-side validator is correct; the gap is that it can be short-circuited upstream.

**Status:** resolved. **Filed:** 2026-05-31. **Resolved:** 2026-05-31 (branch `fix/bug039-042-conversation-layer`, baseline `6ae610f`; PR #TBD — final merge SHA to be recorded on merge).

**Resolution:** Two layers. (1) Prompt hardening — `prompts/bot.yaml` (v1.7.3) adds a HARD RULE forbidding the LLM from stripping/collapsing internal whitespace or guessing a canonical username; the model must pass the token VERBATIM so the deterministic `validate_channel_username` guard always adjudicates. (2) Defence-in-depth — `verify_channel_exists` (`tg_parser/bot/tools.py`, BUG-010 `get_source_by_username` pattern, fail-open `None` on numeric ids / DB-unreachable) is consulted on **both** the LLM-direct primary path AND the clarify re-run path. On the **primary path** (the path the original trace actually hits: the LLM emits a wrong-but-valid username DIRECTLY, with no embedded space, so the clarify FSM never arms) `_exec_subscribe_digest` / `_exec_subscribe_watchlist` call `verify_channel_exists` after format validation and before returning a preview (`_reject_nonexistent_channel`) — a definitively non-existent channel is rejected with «не найден» (`error_class="ChannelNotFound"`) instead of producing a bogus preview; existence-unknown / unreachable-DB fail-opens so a not-yet-ingested channel or an absent test DB never wedges the flow. On the **clarify re-run path** the same helper rejects an LLM-/user-"corrected" non-existent channel while keeping the clarify FSM armed for a retry. The code-side `validate_channel_username` guard was already correct; these close the upstream LLM bypass. **Note:** the executor-level primary-path check was added in the review-driven hardening (item B2) — the initial fix only consulted `verify_channel_exists` on the clarify re-run, which left the primary (no-space, wrong-username) trace uncovered. **Regression tests:** `tests/test_bot_conversation_layer_bug039_042.py::TestBug041GuardHardening` (4 tests) + `TestB2ExecutorExistenceCheckPrimaryPath` (3 tests: direct-non-existent rejected in digest + watchlist executors, fail-open allows preview when existence unknown; confirmed FAIL on the pre-B2 iteration, PASS post-fix).

**Related:** BUG-034 (the deterministic guard this gap bypasses), BUG-040 (statelessness/sampling that drives the non-determinism), BUG-010 (`get_source_by_username` existence-check pattern for defence-in-depth).

**Evidence:** Real-fire transcript 2026-05-31 (group `vps-watch-test-grp`): «pro fendocrinologist» rejected at 23:49:52 / 23:51:54 / 23:52:39, but the identical input produced a direct `profendocrinologist` preview at 23:53:37 and 23:54:09.

---

### BUG-042 (Minor — bot UX / cosmetic) — Subscribe preview cron rendering truncated to «0» (LLM-paraphrased preview), while the creation confirmation shows the full «0 * * * *»

**Discovered:** 2026-05-31 production real-fire smoke, human operator in group `vps-watch-test-grp` (chat_id `-5279672667`), bot `@Tgingest_bot`, prod SHA `39b6ba2`.

**Symptom:** The preview text rendered «по расписанию `0     (Europe/Moscow)`» (just "0" + whitespace) whereas the post-confirmation message correctly showed «0 * * * *».

**Root cause (HIGH confidence — code-traced):** The two messages are produced by two different mechanisms:
- The **preview** turn (`confirm` falsy) returns a structured result whose `message` field contains the correct full string `f"… по расписанию {cron_expression} ({timezone}), формат … Подтвердите [да/нет]."` (`tg_parser/bot/tools.py:2635-2639`). But that `message` is NOT sent verbatim — it is returned to the agent loop as a `functionResponse` (`tg_parser/bot/agent.py:330-337`), and the user-facing preview text is then **re-authored by Gemini** (`tg_parser/bot/agent.py:267-275`) and sent as `result.response_text` (`tg_parser/bot/handlers.py:376-381`). The transcript's markdown code-span around `` `0     ` `` is not present in the tool template, confirming the LLM re-rendered it — and in doing so it truncated the 5-field cron «0 * * * *» to «0» (dropping the `* * * *`). (That `cron_expression` was a valid 5-field spec is guaranteed: the preview is only returned after `CronTrigger.from_crontab(cron_expression …)` passes at `tools.py:2599-2607`, else an error — not a preview — is returned.)
- The **creation confirmation** is emitted **deterministically by code** — `f"… Расписание: <code>{created_sub.cron_expression}</code> …"` via `bot.send_message` (`tg_parser/bot/tools.py:2704-2713`), bypassing the LLM — so it always shows the full stored cron.

So the truncation is LLM-side rendering of the preview, not a data defect; the stored/created cron is correct.

**Impact:** Minor / cosmetic. The previewed schedule is misleading (looks like an invalid/partial cron) but the actually-created subscription uses the correct expression. No correctness impact on the stored row or delivery cadence.

**Suggested fix (future task — NOT in scope here):** Send the preview deterministically the same way the creation confirmation is sent (use the tool's own `message` field verbatim rather than letting the LLM paraphrase), or render the cron inside `<code>…</code>` / pre-format it to a human label so the LLM can't drop fields. Aligns the preview surface with the already-deterministic post-confirm message.

**Status:** resolved. **Filed:** 2026-05-31. **Resolved:** 2026-05-31 (branch `fix/bug039-042-conversation-layer`, baseline `6ae610f`; PR #TBD — final merge SHA to be recorded on merge).

**Resolution:** The subscribe preview is now sent deterministically instead of being LLM-paraphrased. The tool `message` renders the cron inside `<code>…</code>` (`_exec_subscribe_digest`/`_exec_subscribe_watchlist`, `tg_parser/bot/tools.py`); the agent surfaces that verbatim string as `AgentResult.preview_message` (`tg_parser/bot/agent.py`); and `handle_text` sends it via `_send_html_response` (`parse_mode="HTML"`, bypassing the markdown re-render) whenever a `preview_message` accompanies a `preview_pending` (`tg_parser/bot/handlers.py`). The full 5-field cron «0 * * * *» can no longer be truncated to «0». Mirrors the already-deterministic post-confirmation creation message. **Review-driven hardening (B1):** the verbatim path is scoped to the subscribe executors ONLY — they tag their preview with `user_facing_message: True`, and the agent populates `preview_message` only when that flag is present. Every OTHER preview tool (`pause_channel`, `remove_channel`, `set_llm_config`, …) carries LLM-directed scaffolding in its `message` («Preview only. Ask the user to confirm…») and stays on the LLM-paraphrase (`response_text`) path, so the deterministic render never leaks raw English scaffolding to the user. **(N1):** the user-controlled `name`/`timezone` (digest) and `title` (watchlist) are `html.escape()`-d before interpolation so a value containing `&`/`<`/`>` can't break the `parse_mode="HTML"` render (the literal `<code>…</code>` cron wrapper is preserved). **Regression tests:** `tests/test_bot_conversation_layer_bug039_042.py::TestBug042DeterministicPreviewCron` (3 tests: tool message carries full cron in `<code>`, agent captures preview_message verbatim, handle_text sends full cron not the truncated paraphrase) + `TestB1VerbatimPreviewScopedToSubscribe` (3 tests: non-subscribe preview NOT captured verbatim, subscribe preview IS, handler renders the LLM paraphrase for non-subscribe previews; confirmed FAIL on the pre-B1 iteration, PASS post-fix).

**Related:** BUG-031 (preview-before-write contract — the preview surface this renders), BUG-039/BUG-040 (other gaps rooted in LLM-paraphrased / LLM-routed surfaces vs deterministic code paths).

**Evidence:** Real-fire transcript 2026-05-31 (group `vps-watch-test-grp`): preview «по расписанию `0     (Europe/Moscow)`» vs creation confirmation «Расписание: 0 * * * *».

---

### BUG-043 (Severe — bot UX / correctness) — BUG-039/040 residual: the channel-not-found suggestion is a dead-end on the READ surface too (`list_topics`/`search`/`get_cross_channel_stats`)

**Discovered:** 2026-05-31 production real-fire smoke of the BUG-039..042 fix, against the fix branch HEAD `c0ff6d3` (NOT the original `39b6ba2` baseline). Same operator surface as BUG-039/040.

**Decision (filing):** filed as a NEW entry (monotonic-ID convention) rather than reopening BUG-039/040. The ORIGINAL surface those covered — the subscribe space-typo clarification (`validate_channel_username` → `_decorate_clarify_error` in `_exec_subscribe_*`) — remains correctly fixed and real-fire-verified; this is a DISTINCT clarification surface (a different resolver) that exhibits the SAME class of dead-end. BUG-039/040 stay `resolved`; this entry tracks the residual on the read surface (see the residual note appended to BUG-039's resolution). The fix EXTENDS (reuses) the `ClarifyFlow` mechanism rather than duplicating it.

**Symptom (real-fire transcript, 2026-05-31 12:41, prod @ `c0ff6d3`):**
- 12:41:22 user: «pro fendocrinologist» (a bare channel name, OUTSIDE any subscribe flow)
- 12:41:24 bot: «Канал pro fendocrinologist не найден. Возможно, вы имели в виду profendocrinologist? Доступные каналы: AgeManagment, BiocodebySechenov, … profendocrinologist.»
- 12:41:43 user: «да»
- 12:41:43 bot: «Я не совсем понимаю ваш ответ. Пожалуйста, уточните, что вы имели в виду.» ← BUG-039 opaque fallback RESURFACES on this surface
- 12:42:14 user: «я имел в виду profendocrinologist» → 12:42:22 bot: «Показываю топ-20 тем канала profendocrinologist: …» (only an explicit re-phrasing recovered)

**Root cause (HIGH confidence — code-traced):** The «Канал X не найден. Возможно, вы имели в виду Y? Доступные каналы: …» message is emitted by a DIFFERENT code path than the subscribe space-guard. The read executors `_exec_list_topics` / `_exec_search` / `_exec_get_cross_channel_stats` enrich a `total=0` / not-found result with the fuzzy-suggestion payload from `_build_no_results_suggestion` (`tg_parser/bot/tools.py`), which attached `available_channel_ids` + a `suggestion` SENTENCE but — pre-fix — NO `clarify_pending` action. The agent loop only captures a clarify hint when the tool result carries `clarify_pending` (`tg_parser/bot/agent.py`), so this surface never armed `ClarifyFlow`; the not-found+suggestion text was LLM-paraphrased and carried no FSM state. The user's follow-up «да» therefore reached `handle_text` with `current_state is None`, bypassed `classify_confirmation_token` (scoped to `ConfirmFlow`/`ClarifyFlow`), fell through to the stateless Gemini turn, and produced the opaque «Я не совсем понимаю ваш ответ» (`prompts/bot.yaml` closure / the LLM-side fallback). I.e. BUG-039/040's fix scope was incomplete: it covered the subscribe space-typo suggestion but not the channel-not-found suggestion surface shared by the read intents.

**Affected intents (every emitter of the not-found+suggestion message):** `list_topics`, `search`, `get_cross_channel_stats` — the three callers of `_build_no_results_suggestion`. `get_topic_details` / `get_document` operate on `topic_id` / `source_ref` (not `channel_id`) and return a bare `{"error": "… not found"}` with no fuzzy suggestion, so they do not produce this surface.

**Impact:** Severe — the exact UX failure BUG-039 was filed to eliminate, re-exposed on the most common (read) surface; a user who mistypes a channel name and accepts the bot's own suggestion with «да» dead-ends on the opaque catch-all and must re-phrase explicitly to recover.

**Status:** resolved. **Filed:** 2026-05-31. **Resolved:** 2026-05-31 (branch `fix/bug039-042-conversation-layer`, baseline `c0ff6d3`; commit recorded below).

**Resolution:** Made the channel-not-found suggestion ACTIONABLE by reusing — not duplicating — the existing `ClarifyFlow` mechanism. `_build_no_results_suggestion` now accepts the calling `tool_name` + `args` and, when `difflib` finds a close match, attaches a `clarify_pending` action (`_build_read_clarify_pending`, `tg_parser/bot/tools.py`) of `kind="read"` carrying the original tool, the original args, the singular `channel_arg` (`"channel_id"`), the BARE suggested channel id, and a deterministic Russian not-found+suggestion `message`. The agent loop already captures any `clarify_pending` and short-circuits; it now surfaces the hint's own `message` verbatim when the result has no `error` field (`tg_parser/bot/agent.py`). `handle_text`'s existing arming path stores the read `clarify_action`, and `_handle_clarification_response` (`tg_parser/bot/handlers.py`) branches on `kind`: for `kind="read"` an affirmative «да» (or a bare suggested token) deterministically RE-RUNS the original read intent with the corrected `channel_id` and renders the result server-side via `_format_read_result` (reusing `_format_paginated_list` for `list_topics`, arming `PaginationFlow` when more pages remain) — the LLM is never consulted, so a bare reply cannot be misrouted (BUG-040 class) and the opaque «не совсем понимаю» can no longer resurface on this surface. **Edge cases:** «нет»/cancel clears state; a bare suggested token re-runs the intent; a re-typed `pro fendocrinologist` (still not found) keeps the clarify FSM armed (`verify_channel_exists` fail-open False → re-clarify, no dead-end / no preview); TTL expiry clears state. All existing behavior preserved — the subscribe surface (`kind` absent → the `channel_ids`/`channel_index` branch), `ConfirmFlow`, and pagination are untouched; `_build_no_results_suggestion` without a `tool_name` keeps its legacy shape (back-compat test). Honors the BUG-041 fail-open existence semantics. **Rendering fidelity note:** `get_cross_channel_stats` re-runs deterministically but its analytics result falls back to a compact render (no bespoke analytics formatter); the correctness guarantee (re-run with the suggested channel, no opaque fallback) holds regardless. **Regression tests:** `tests/test_bot_conversation_layer_bug039_042.py::TestBug043ReadSuggestionIsActionable` (10 tests; the 5 core-defect tests — resolver attaches read clarify, agent short-circuits with the read message, affirmative re-runs the read intent, bare-token re-runs, pagination armed — confirmed FAIL on pre-fix `c0ff6d3`, PASS post-fix; the other 5 are edge/back-compat guards that already pass on the generic plumbing).

**Related:** BUG-039 (same dead-end class on the subscribe space-typo surface; this is the read-surface residual), BUG-040 (shared statelessness root; the `kind="read"` branch keeps a bare reply in-flow), BUG-041 (`verify_channel_exists` fail-open existence semantics reused), BUG-007 (the `_build_no_results_suggestion` fuzzy-suggestion helper this extends), BUG-004 (`PaginationFlow` armed on the re-run list).

**Evidence:** Real-fire transcript 2026-05-31 12:41 (prod @ `c0ff6d3`), reproduced verbatim in the test docstring above.

---

### BUG-044 (Minor — bot UX / cosmetic) — Auto-derived subscription name keeps the pre-correction channel token after a clarify re-run

**Discovered:** 2026-05-31 real-fire smoke of the BUG-039..042 fix, same surface as BUG-043. Operator-flagged.

**Decision (filing):** filed as a small NEW entry (monotonic-ID) rather than folded into BUG-043 — BUG-043 is the dead-end/actionability fix on the read surface; this is a distinct, cosmetic naming-consistency gap on the SUBSCRIBE clarify re-run. Closely linked, separately traceable.

**Symptom:** A subscribe created via the clarify→confirm flow (user typed «pro fendocrinologist», bot suggested «profendocrinologist», user said «да») bound the channel correctly to `profendocrinologist` but the created subscription's display NAME still embedded the typo: «📰 Подписка «Ежечасный дайджест pro fendocrinologist» создана.»

**Root cause (code-traced):** On the subscribe clarify re-run (`_handle_clarification_response`, subscribe `kind`, `tg_parser/bot/handlers.py`) only `channel_ids[channel_index]` was substituted with the suggestion; the digest `name` / watchlist `title` — which the LLM had AUTO-derived from the user's original (typo'd) text — was carried through unchanged. So the channel binding was corrected but the auto-derived display name kept the wrong token.

**Impact:** Minor / cosmetic. The subscription is functionally correct (right channel, right schedule); only the human-readable name is misleading.

**Status:** resolved. **Filed:** 2026-05-31. **Resolved:** 2026-05-31 (branch `fix/bug039-042-conversation-layer`, baseline `657c5e7`; commit recorded below).

**Resolution:** On the subscribe clarify re-run the handler now captures the ORIGINAL channel token at the corrected index (before substitution) and, when the `name` (digest) / `title` (watchlist) literally CONTAINS that exact token, deterministically replaces that specific substring with the corrected channel id (`tg_parser/bot/handlers.py`). **Detection rule for "auto-derived vs explicit":** the rewrite fires ONLY when the original channel token is a substring of the name — that is the signature of an LLM-auto-derived name; an explicit user-chosen name that doesn't embed the token is left UNTOUCHED (no guessing, no clobber). The substitution is scoped to the precise original token at the corrected index (`str.replace(original_token, chosen)`), so a blind global rewrite can't corrupt unrelated text and, with multiple channels, only the corrected channel's token in the name is rewritten (an unrelated `durov` token is preserved). Server-side and deterministic (the LLM is never asked to re-author). **Regression tests:** `tests/test_bot_conversation_layer_bug039_042.py::TestBug044AutoDerivedNameConsistency` (4 tests: digest name corrected, watchlist title corrected, explicit user name preserved, multi-channel corrects only the target token; the 3 correction tests confirmed FAIL on pre-fix `657c5e7`, PASS post-fix; the explicit-name guard passes both pre- and post-fix by construction).

**Related:** BUG-043 / BUG-039 / BUG-040 (the `ClarifyFlow` re-run mechanism this refines), BUG-034 (the original space-typo this naming gap follows on from).

**Evidence:** Real-fire 2026-05-31: «📰 Подписка «Ежечасный дайджест pro fendocrinologist» создана.» with the channel correctly bound to `profendocrinologist`.

---

### ENH-002 (Low — bot UX / i18n) — Human-readable schedule label alongside the verbatim cron in digest preview/creation

**Discovered / requested:** 2026-05-31, operator UX follow-up to BUG-042 (the digest preview/creation messages previously showed only the bare cron «`0 9 * * *`», which is opaque to non-technical users).

**Type:** ENHANCEMENT, not a defect. Filed as `ENH-002` mirroring the `ENH-001` non-defect convention in this file.

**Decision (bounded vs free-form):** investigated and confirmed the `cron_expression` input is **FREE-FORM** — a plain `STRING` schema arg with no `enum`/allowlist (`tg_parser/bot/tools.py` `subscribe_digest` declaration), validated only by APScheduler's full `CronTrigger.from_crontab` (`tg_parser/bot/tools.py:2794`, `tg_parser/services/background_scheduler.py:131`); no presets in `prompts/bot.yaml` or `docs/contracts/`. So a general cron describer would need a dependency (`cron-descriptor`) — declined (no-dependency constraint). Instead implemented a **STRICT** no-dependency mapper that describes only common digest patterns and returns `None` for everything else (caller then shows the raw cron — free-form-safe).

**Resolution:** Added `tg_parser/utils/cron_humanize.py::cron_to_human(cron_expression, timezone, lang="ru") -> str | None` — a pure, dependency-free, i18n strict mapper. Supported patterns (5-field `m h dom mon dow`, `dom`/`mon` must be `*`): hourly `M * * * *` → «ежечасно в :MM» / "hourly at :MM"; daily `M H * * *` → «ежедневно в HH:MM» / "daily at HH:MM"; weekly `M H * * D` (single dow 0–7, 0/7 = Sunday) → «еженедельно по понедельникам …» / "weekly on Mondays …". Anything with steps/ranges/lists/non-wildcard dom·mon/out-of-range/unrecognized shape → `None`. Locales live in a per-language `_LOCALES` table (templates + weekday names) so a 3rd language is one entry; unknown/`None` `lang` falls back to `ru` (case-insensitive). The verbatim cron is ALWAYS preserved (BUG-042 fidelity): `tg_parser/bot/tools.py::_format_schedule_phrase` renders «<label> (tz) — `<code>cron</code>`» when recognized, else the legacy «`<code>cron</code>` (tz)» verbatim-only form. Wired into BOTH deterministic digest message paths — the preview `message` and the deterministic creation-confirmation `bot.send_message` (`tg_parser/bot/tools.py`). **Language source:** the digest's OWN `language` arg/field (`subscribe_digest` already accepts `language`, default `ru`, persisted on the subscription — `tools.py:2789` preview / `created_sub.language` creation); chosen because the label language should match the digest's output language. No per-user/per-chat locale exists in the bot today; `en` is fully reachable via the `language` arg and unit-tested. `subscribe_watchlist` has no cron schedule (keyword-matched per tick) — out of scope. **Tests:** `tests/test_cron_humanize.py` (63 tests: ru + en exact strings for every supported pattern, unsupported→`None` for both langs, unknown/None/empty/cased `lang` fallback, default-lang, no-tz, non-string; `_format_schedule_phrase` ru/en/unsupported; message-level preview ru + en label-and-verbatim-cron + unsupported-raw-only). The message-level / `_format_schedule_phrase` tests fail on pre-fix `10f0d9d` (symbols `cron_to_human` / `_format_schedule_phrase` did not exist and the preview rendered raw cron only) and pass post-fix.

**Related:** BUG-042 (the verbatim-cron fidelity guarantee this builds on — preview is rendered deterministically, never LLM-paraphrased), BUG-031 (the preview/confirm contract surface), ENH-001 (non-defect entry convention).

**Evidence:** Operator request 2026-05-31; the preview/creation now reads e.g. «Расписание: ежедневно в 09:00 (Europe/Moscow) — `0 9 * * *`» (ru) / "daily at 09:00 (Europe/Moscow) — `0 9 * * *`" (en).

**UX-polish refinement 2026-05-31 (items 1+2 — friendly label is now the SOLE human-facing schedule):** Operator feedback during final-smoke: the «label — `<code>cron</code>`» combo is noisy. Reframed `_format_schedule_phrase` (`tg_parser/bot/tools.py`): a RECOGNIZED cron now renders the friendly label ONLY (e.g. «ежечасно в :00 (Europe/Moscow)» — the raw cron is dropped from user-facing text); an UNRECOGNIZED cron still renders the verbatim `<code>{cron}</code> (tz)`. **The BUG-042 guarantee is PRESERVED in reframed form, not weakened:** the schedule is always shown correctly and deterministically — as a friendly label when we can name it, otherwise as the verbatim cron (the only faithful representation for an exotic cron) — and is never silently dropped or LLM-mangled. The «label — cron» combo no longer appears anywhere in user-facing text. The `cron_to_human` helper itself is unchanged (unit tests untouched); only the wrapper + message-level tests were reframed (`tests/test_cron_humanize.py`, `tests/test_bot_confirm_flow.py`, `tests/test_bot_conversation_layer_bug039_042.py::TestBug042…`).

**UX-polish refinement 2026-05-31 (item 3 — name the target channel(s)):** The preview and creation-confirmation messages now NAME the resolved channel(s) instead of only counting them — «… на канал profendocrinologist …» / «Каналы: profendocrinologist.» rather than the opaque «1 канал(ов)» / «Каналов: 1». Added `_format_channel_names` (HTML-escaped, comma-joined) + a trivial `_channel_word_ru` singular/plural helper (no full Russian plural rules). Uses the RESOLVED `channel_ids` / `created_sub.channel_ids`. `created_sub.name` is now HTML-escaped in the creation message too (N1 parity).

---

### BUG-043 residual (final-smoke 2026-05-31) — read re-run rendering fidelity

**Discovered:** 2026-05-31 operator final-smoke of the BUG-039..044 + ENH-002 branch (`195589b`). All target traces PASSED; two rendering-fidelity gaps remained on the BUG-043 read re-run surface (`_handle_clarification_response` `kind="read"` → `_format_read_result`, and `_build_no_results_suggestion` / `_build_read_clarify_pending`).

**Defect-1 (FIX) — missing per-intent header on the deterministic read re-run.** After a channel-not-found clarification answered «да» / bare token, the deterministic re-run jumped straight into the topics list with NO preamble, whereas the normal `list_topics` path shows «Показываю топ-N тем канала {channel}:» first. That header is the user's confirmation of WHICH channel was finally resolved after an AMBIGUOUS clarification — its absence is a fidelity gap, not mere cosmetics. The normal header is composed by the LLM (canonical wording documented in `prompts/bot.yaml` § implicit-context, line 73), so there is no shared Python string to import; we mirror the documented format deterministically. **Fix:** added `_read_intent_header(tool_name, channel, result)` (`tg_parser/bot/handlers.py`) and threaded the resolved `chosen` channel into `_format_read_result(tool_name, result, channel=chosen)`. Per-intent headers: `list_topics` → «Показываю топ-N тем канала {channel}:» (N = items shown on the page, mirroring «топ-20 … Показано 1–20 из 178»); `search` → «Результаты поиска в канале «{channel}»:»; `get_cross_channel_stats` → «Статистика по каналу «{channel}»:». Pagination (PaginationFlow arming, «Показано … «ещё»/«стоп») is unchanged — the header is prepended to the existing `_format_paginated_list` body, not a divergent re-implementation.

**Defect-2 (INVESTIGATE → FIX) — «Доступные каналы» shrank from ~10 to 5 and dropped the suggested channel. VERDICT: partial regression (count) + intentional (exclusion).** Root cause (`tg_parser/bot/tools.py::_build_read_clarify_pending`): the BUG-043 deterministic clarify `message` hard-coded `avail = [a for a in available if a != suggested][:5]`. The pre-BUG-043 baseline rendered `available_channel_ids` (capped at `_NO_RESULTS_AVAILABLE_CAP = 10`, INCLUDING the suggested) via the LLM. So BUG-043 introduced (a) an unintended `5` cap — a genuine regression vs the established `10` constant — and (b) exclusion of the suggested channel. **Decision:** (a) is a regression → replaced the magic `5` with `_NO_RESULTS_AVAILABLE_CAP` (restores ~10 parity; since `available_channel_ids` is itself pre-capped at 10 incl. the suggested, the net list lands at 9 after exclusion). (b) the exclusion is KEPT deliberately — the suggested channel is already named verbatim in the «Возможно, вы имели в виду «X»?» line directly above, so repeating it in «Доступные каналы» is pure redundancy; stated and intentional, now via a named constant rather than a magic number.

**Item-4 (UX) — «Доступные каналы» rendered vertically.** Operator request folded into the same fix: the available-channels list is now rendered one «• {channel}» per line under the «Доступные каналы:» label (was a comma-joined inline string), for readability. Channel ids are plain usernames (no HTML metacharacters) and «• » survives the markdown→HTML render unchanged.

**Tests:** `tests/test_bot_conversation_layer_bug039_042.py::TestBug043FinalSmokeFidelity` (read re-run header present + names resolved channel + «топ-N» = page size + pagination intact; «Доступные каналы» cap = `_NO_RESULTS_AVAILABLE_CAP - 1` (9, not 5) + vertical «• » format + suggested excluded but named once). All fail on pre-fix `195589b` (no header; list = 5; inline) and pass post-fix.

---

### BUG-045 (G2 / Severe — bot correctness) — subscribe channel-not-found dropped the intent; read clarify hijacked «да»

**Discovered:** 2026-05-31, G2 real-fire smoke of the BUG-039..044 + ENH-002 branch (`fix/bug039-042-conversation-layer`), same operator surface as BUG-043/044.

**Symptom:** On the subscribe preview path, a not-found channel with a fuzzy match returned a plain `ChannelNotFound` error with no `clarify_pending`, so the subscribe intent was dropped; the LLM then misrouted the user's «да» to `list_topics`, and BUG-043's new `kind="read"` clarify deterministically bound «да» to re-run `list_topics` (a second channel «genotek» was also dropped). Symptom-regression from BUG-043 layered on pre-existing LLM misrouting.

**Root cause (HIGH confidence — code-traced):** `_reject_nonexistent_channel` (`tg_parser/bot/tools.py`) returned a bare `ChannelNotFound` error without arming any clarify FSM, so the subscribe intent had no state to recover from. The agent loop (`tg_parser/bot/agent.py`) would then arm a `kind="read"` clarify from a later read tool call even when the same turn had already routed a write tool, letting the read clarify capture the affirmative «да» that belonged to the (dropped) subscribe intent.

**Impact:** Severe — a typo'd channel on the subscribe surface silently lost the user's intent, and a follow-up «да» was hijacked into re-running an unrelated read intent; additional channels in a multi-channel subscribe were dropped entirely.

**Status:** resolved. **Filed:** 2026-05-31. **Resolved:** 2026-05-31 (branch `fix/bug039-042-conversation-layer`, PR #158; commit recorded below).

**Resolution:** (1) `_reject_nonexistent_channel` now arms a `kind="subscribe"` clarify (sharing the same fuzzy matcher / not-found copy) carrying the FULL channel list, so «да» re-runs `subscribe_*` → `ConfirmFlow` keeping ALL channels (additional channels like «genotek» survive); (2) the agent loop refuses to arm a `kind="read"` clarify on a turn that also routed a write tool, so a bare affirmative can no longer be hijacked away from the pending subscribe intent. Genuine read-not-found clarify (BUG-043) is unchanged. **Regression tests:** `tests/test_bot_conversation_layer_bug039_042.py` (G2 section), verified red→green.

**Related:** BUG-043 (the `kind="read"` clarify whose interaction with the dropped subscribe intent is constrained here), BUG-039/BUG-040 (the dropped-intent / LLM-misrouting class this closes on the subscribe-not-found surface), BUG-044 (sibling refinement on the subscribe clarify re-run).

**Evidence:** G2 real-fire transcript 2026-05-31, reproduced in the `tests/test_bot_conversation_layer_bug039_042.py` G2 regression section.

---

## TD from Session D — code observations after PR #38

**Назначение секции:** post-landing observations из self-review PR #38 (Session D, BUG-002 + BUG-004 closure). Не блокеры — но подходящие кандидаты для Session F или последующего housekeeping-sprint'а. Каждый item открыт как отдельный GH issue с label `tech-debt` + `priority/p1` per Phase 1/2 convention.

| TD | Issue | Suggested timing | Summary |
|---|---|---|---|
| **TD-D-01** | [#39](https://github.com/AlexEfimov/TG_parser/issues/39) | Session F или после | UX asymmetry: page 1 paginated list рендерится через LLM (free-form markdown), page 2+ — детерминистом (`<b>n.</b> title — summary[:120]`). Visual jump между pages, numbering на page 1 может рестартовать с 1 несмотря на `n` field. Suggested: promote `_format_paginated_list` на page 1 too (или strengthen prompt contract). |
| **TD-D-02** | [#40](https://github.com/AlexEfimov/TG_parser/issues/40) | Session F | `pagination_pending` payload реализован только в `_exec_list_topics` (D-2 default per Session D runbook). Остальные list-tool'ы (`list_channels`, `list_users`, `list_digests`, `list_watchlists`, paginated `get_cross_channel_stats`) не подведены — латентный re-entry BUG-004 на других surface'ах. Suggested: applied тот же контракт ко всем paginated read-tool'ам, симметрично в `mcp_server.py`. |
| **TD-D-03** | [#41](https://github.com/AlexEfimov/TG_parser/issues/41) | Session F или housekeeping | `_format_tool_result` fallback `"✅ Готово: {tool_name}."` слабо информативен — currently unreachable (все write-tool'ы возвращают `message`), но любой новый write-tool без явного `message` field silently degrades. Suggested: synthesize fallback из `channel_id`/`id`/`status` + contract-test что все write-tool'ы возвращают non-empty `message`. |

---

## Session planning (2026-04-27)

**Назначение секции:** карта upcoming fix-сессий, привязка к существующим
sprint'ам (Phase 1 / Phase 2), порядок и зависимости. Обновляется при
изменении приоритетов и после landing'а каждой сессии.

**Anchor:** 2026-04-27, сразу после первой обзорной волны багов
BUG-001..BUG-007 и параллельно с активным 24h F5-C watch (deploy
`2026-04-26T11:07:13Z`, окно закрывается `2026-04-27T11:07Z` ≈ 15:07 UTC+4).

### Контекст

- **Phase 1 sprint** (`START_PROMPT_SPRINT_POST_LIVING_KB_DEBT_FIX_PHASE1.md`)
  — готов, может стартовать немедленно (parallel to watch).
- **Phase 2 sprint** (`START_PROMPT_SPRINT_POST_LIVING_KB_DEBT_FIX_PHASE2.md`)
  — готов, стартует после закрытия watch'а + sanity-buffer.
- **7 багов** в этом журнале, 3 Critical (BUG-001, BUG-002, BUG-006), ни один
  пока не имеет fix-сессии.

### Timeline

```text
NOW (Apr 27 00:11 UTC+4)
│
├─ [перерыв пользователя]
│
Apr 27 morning        ── Session A — Phase 1 sprint
                          (parallel to watch, watch-aware cadence)
│
Apr 27 ~15:07 UTC+4   ── 24h watch closes; sanity-check (~30 min)
│
Apr 27 afternoon      ── Session B — Phase 2 sprint
                          (TD-03c + post-watch report)
│
Apr 27 evening / Apr 28 morning
                      ── Session B+ — BUG-002 mitigations HOT-FIX
                          (3 mitigations, reduce blast radius)
│
Apr 28                ── Session C — BUG-001 fix (MCP auth Critical)
                          [independent of bot track]
│
Apr 28                ── Session D — bot FSM (BUG-002 full + BUG-004)
                          [shared FSM scaffolding]
│
Apr 29                ── Session E — BUG-006 (bot Gemini-flash)
                          [needs research-spike + Session D stable]
│
Apr 29                ── Session F — read-tool hardening
                          (BUG-003 + BUG-005-B + BUG-007)
│
Out-of-band ops track ── BUG-005-A monitoring (Anthropic quota alarm)
```

### Decisions (D1–D5, defaults taken)

| ID | Вопрос | Принятое решение |
|---|---|---|
| **D1** | Phase 2 scope: minimum-viable или full P1 stretch? | **minimum-viable** — TD-03c + post-watch report only; **TD-05..08 deferred** до отдельного housekeeping-sprint'а после BUG-fix-волны (приоритет Critical-багов выше, чем P1 stretch refactor'а). |
| **D2** | BUG-002 mitigations — отдельный hot-fix или в Session D? | **отдельный hot-fix** (Session B+) сразу после Phase 2; снижает blast radius _до_ proper FSM-фикса в Session D, защищает прод раньше. |
| **D3** | BUG-006 model decision (bump tokens / split tools / switch model)? | **research-spike в начале Session E** (~30 мин); три опции тестируются, выбор фиксируется в session-prompt'е до старта code-changes. |
| **D4** | BUG-002 storage backend для FSMContext? | **MemoryStorage** (aiogram default) — bot работает в одной реплике; Redis отложен до scale-out (отдельный TD). |
| **D5** | BUG-007 storage-side LIKE→JSONB или только tool+prompt? | **только tool+prompt в Session F**; storage-side `LIKE → JSONB ?` вынесен в отдельный TD (затрагивает миграции, требует отдельного review). |

Все defaults пересматриваются до старта соответствующей сессии — обновить
эту таблицу + соответствующий start-prompt.

### Sessions roster

| Session | Дата (UTC+4) | Scope | Start prompt | Эстимат |
|---|---|---|---|---|
| **A** | Apr 27 morning | TD-04, TD-02, TD-01, TD-03a, TD-03b | `START_PROMPT_SPRINT_POST_LIVING_KB_DEBT_FIX_PHASE1.md` | 4-5 ч |
| _(watch closes)_ | Apr 27 ~15:07 | sanity-check | _none_ | 30 мин |
| **B** | Apr 27 afternoon | TD-03c, post-watch report | `START_PROMPT_SPRINT_POST_LIVING_KB_DEBT_FIX_PHASE2.md` | 2-3 ч |
| **B+** | Apr 27 evening or Apr 28 morning | BUG-002 mitigations (M1+M2+M3) | `START_PROMPT_HOTFIX_BUG002_MITIGATIONS_2026-04-27.md` | 1-1.5 ч |
| **C** | Apr 28 | BUG-001 (MCP auth Critical) | `START_PROMPT_FIX_BUG001_MCP_AUTH_2026-04-28.md` | 1.5-2 ч |
| **D** | Apr 28 | BUG-002 full FSM + BUG-004 pagination | `START_PROMPT_FIX_BUG002_BUG004_BOT_FSM_2026-04-28.md` | 4-5 ч |
| **E** | Apr 29 | BUG-006 (Gemini-flash empty parts) | `START_PROMPT_FIX_BUG006_BOT_GEMINI_2026-04-29.md` | 2-4 ч |
| **F** | Apr 29 | BUG-003 + BUG-005-B + BUG-007 | `START_PROMPT_FIX_READ_HARDENING_BUG003_005B_007_2026-04-29.md` | 2.5 ч |
| **Ops track** | any time after Session B | BUG-005-A monitoring (Anthropic quota alarm) | _no separate prompt — ops-task in F5C runbook_ | 1 ч |

### Bug → session mapping

| Bug | Severity | Status | Session | Why |
|---|---|---|---|---|
| BUG-001 | Critical | `resolved (Session C, 2026-04-27)` | C | self-contained MCP-auth fix; isolated track |
| BUG-002 (mitigations) | Critical | `mitigated (Session B+, 2026-04-27)` | **B+** | reduces blast radius PRE-FSM-fix |
| BUG-002 (full FSM) | Critical | `resolved (Session D, 2026-04-28)` | D | shares scaffolding с BUG-004 |
| BUG-003 | Low (bot) / Medium (MCP) | `resolved (Session F, 2026-04-29; deployed 2026-04-30)` | F | mass read-tool hardening батч |
| BUG-004 | Medium | `resolved (Session D, 2026-04-28)` | D | паразитирует на BUG-002 FSM scaffolding |
| BUG-005-A | High | `resolved` (Anthropic top-up) | Ops track | monitoring only, без code-fix |
| BUG-005-B | Medium | `resolved (Session F, 2026-04-29; deployed 2026-04-30)` | F | `_call_tool_safe` typed catch — мелкий read-side fix |
| BUG-006 | Critical | `resolved (Session E, 2026-04-29)` | E | thinkingBudget=0 + maxOutputTokens=8192 + classification + Prometheus metric; см. § Resolved bugs |
| BUG-007 | Medium | `resolved (Session F, 2026-04-29; deployed 2026-04-30)` | F | suggestion-emit + prompt-teach |
| BUG-009 | High | `resolved (Session G, 2026-05-02)` | G | server-side guard в `execute_tool` rejects LLM-issued `confirm=True` без matching FSM snapshot; см. § Resolved bugs |
| BUG-010 | Medium | `resolved (Session I, 2026-05-06)` | I | `get_source_by_username` + `_resolve_source` PK-first/username-fallback; см. § Resolved bugs |
| BUG-011 | Medium | `resolved (Session H, 2026-05-03)` | H | `ReadContextData` + programmatic injection в Gemini systemInstruction; см. § Resolved bugs |
| BUG-012 | Low | `resolved (prompt v1.5.0, 2026-05-02)` | H | BUG-012 format directive в `prompts/bot.yaml`; см. § Resolved bugs |

### Dependencies graph

```text
Phase 1 (Session A) ──┐
                      │
                      ▼
                Phase 2 (Session B) ──────┐
                                          │
                                          ▼
                              Session B+ (mitigations) ──┬─→ Session C (BUG-001) [independent]
                                                          │
                                                          └─→ Session D (FSM scaffolding)
                                                              │
                                                              ├─→ BUG-002 full
                                                              └─→ BUG-004 (built on top)
                                                              │
                                                              ▼
                                                         Session E (BUG-006)
                                                         [needs scaffolding stable]
                                                              │
                                                              ▼
                                                         Session F (read hardening)
                                                         [final batch, мелкие фиксы]
```

Жёсткие dependencies (нельзя нарушать):

- **Phase 1 → Phase 2** (по дизайну debt-fix sprint'а).
- **Phase 2 → Session B+** (mitigations должны идти после post-watch report, чтобы не путать
  TRIPWIRE-correlation если что-то задрожит).
- **Session B+ → Session D** (если M3 — soft-delete — landed, FSM-фикс
  D становится менее срочным; meaning, mitigations критично пройти ДО D).
- **Session D → Session E** (bot-loop refactor в D трогает `agent.process_message`,
  а Session E чинит `_call_gemini` — лучше после D, иначе rebase-pain).

Soft dependencies (можно нарушать с осторожностью):

- **Session C ⊥ Session D**: разные track'и (MCP vs bot); можно делать параллельно
  в разных worktree'ях, если нет single-developer constraint'а.
- **Session F ⊥ всё кроме D**: read-tool hardening не зависит от FSM, но
  лучше после D, чтобы touch'ить `prompts/bot.yaml` один раз согласованно.

### Critical rules during BUG-fix-волна

1. **Не модифицировать F5-C internals** ни в одной BUG-fix-сессии без
   отдельного решения — F5-C уже стабилизирован двумя sprint'ами и watch'ем.
2. **Каждая BUG-fix-сессия завершается** переносом соответствующего bug-entry
   в § «Resolved bugs» с PR/commit-указанием (см. § Mapping в fix-сессии).
3. **Если в ходе fix-сессии обнаружится новый bug** — сразу заводить
   новый BUG-NNN entry в § Active bugs, не маскировать в текущем PR'е.
4. **Severity escalation discipline**: если critical-bug раскрывается как
   шире чем ожидалось — обновить severity, пересмотреть session-mapping,
   и проинформировать пользователя ДО старта соответствующей сессии.
5. **Test count baseline** (anchor): на момент старта BUG-fix-волны должен
   быть ≥ 1881 + N от Phase 1 + N от Phase 2. Каждая BUG-fix-сессия добавляет
   regression-тесты — не уменьшать count.

### Updates

_(формат: `Session X (date) — landed: <PR-#, commit-SHA, +N tests>; bugs moved to Resolved: BUG-NNN`)_

- **Session B+ (2026-04-27) — landed:** PR #35 ([`b5f7121`](https://github.com/AlexEfimov/TG_parser/commit/b5f7121); M1 `e927f53` + M2 `295d6e9` + M3 `eac05b6` + docs `223b370` + lint `5d87e5d`) + PR #36 ([`c29f4c1`](https://github.com/AlexEfimov/TG_parser/commit/c29f4c1); SQL fix `cf978b1` + compose `e9ff001` + CI hook `cc4f2b8`); +17 tests (16 от M1+M2+M3 unit-coverage; +1 testcontainers integration regression `tests/test_ingestion_state_repo_soft_delete.py`). **Bugs mitigated** (не resolved — root cause закроется в Session D): BUG-002 (Severity Critical → High, Status `open` → `mitigated`). Deployed both locally (Docker compose) и на VPS (`mcp.tgp.efimov.mobi`); VPS post-deploy smoke подтвердил M2-rejection и M3-soft-delete cycle. Side-find в ходе VPS smoke: BUG-001 воспроизведён вживую (anonymous `owner_id = 00000000-…` от Cursor Bearer-token'а ловит FK-violation на `add_channel` — мотивация для Session C ровно из этого observation).
- **Session C (2026-04-27) — landed:** PR #37 ([`59ec116`](https://github.com/AlexEfimov/TG_parser/commit/59ec116)); +15 tests (5 в `TestExtractAuthenticatedUserId`, 3 в `TestMcpAuthCabinetry`, 1 split в `TestResolveMcpUser` для production-mode fail-loud, 6 в новом `tests/test_mcp_auth_integration.py` E2E через httpx + ASGITransport). **Bugs resolved (moved to § Resolved bugs)**: BUG-001 (Critical) + BUG-001b cabinetry. Полный pytest 1796 passed (was 1781 baseline; +15). Mass-edit: 35 call-site'ов `resolve_mcp_user(ctx.client_id if ctx else None)` → `resolve_mcp_user(_extract_authenticated_user_id(ctx))`. Factory cabinetry: `auth_enabled && tokens={}` теперь fail-loud `RuntimeError` (was: silent skip → admin-bypass). **Production deploy** на VPS `mcp.tgp.efimov.mobi` выполнен 2026-04-27 19:00 UTC (`git pull` + `docker compose build tg_parser` + `docker compose up -d --no-deps tg_parser mcp tg_bot`); все три контейнера (`tg_parser` API / `tg_parser_mcp` / `tg_parser_bot`) healthy, cabinetry RuntimeError не triggered (tokens на VPS — JSON-объект 65 chars, не пустой). **Post-deploy smoke** (curl direct против `https://mcp.tgp.efimov.mobi/mcp`) PASSED on 5/5 cases: (1) no-bearer → 401 `invalid_token`; (2) invalid-bearer → 401 `invalid_token`; (3) valid-bearer + `tools/list` → 200 OK; (4) valid-bearer + `whoami` → real UUID `c59d42b4-8e05-42a7-be7e-50e9d1f4b951` с 5 owned channels (`AgeManagment, Lab4health, LongevityClub, genotek, labdiagnostica_logical`), вместо synthetic admin `00000000-…` pre-fix; (5) valid-bearer + attacker `_meta.client_id="deadbeef-0000-4000-8000-000000000000"` → тот же real UUID `c59d42b4-…` (helper полностью игнорирует attacker-controlled `_meta.client_id` — критическая регрессия закрыта end-to-end). BUG-001 → BUG-001b закрыты **полностью** код + production.
- **Session D (2026-04-28) — landed:** [PR #38](https://github.com/AlexEfimov/TG_parser/pull/38) (squash [`8332aa3`](https://github.com/AlexEfimov/TG_parser/commit/8332aa3); 6 atomic commits + docs + lint follow-up); +67 tests в `tests/test_bot_fsm.py` (включая `test_yes_after_remove_preview_does_not_call_add_channel` — direct regression на 2026-04-28 00:04 production trace). **Bugs resolved (moved to § Resolved bugs)**: BUG-002 (High) + BUG-004 (Medium). Полный pytest 1863 passed; 0 regressions. Architecture: aiogram `FSMContext` + `MemoryStorage` + 2 state groups (`ConfirmFlow`, `PaginationFlow`) → confirmation handler выполняет previewed tool детерминированно (`execute_tool(name, {**args, "confirm": True})`) **без LLM**, pagination handler replays `{tool_name, args, offset, limit}` из FSM state. `AgentResult` dataclass заменил bare-string return из `process_message`, переносит `preview_pending` / `pagination_pending` hints. `prompts/bot.yaml` v1.1.0 (confirmation semantics + pagination numbering + soft-delete M3). TTL 5 мин, soft-cap 10 items. **Production cleanup**: orphan `test_channel_123` (placeholder из 28.04 00:04 hallucination trace) soft-deleted напрямую через SQL `UPDATE sources SET deleted_at = NOW(), updated_at = NOW() WHERE channel_id = 'test_channel_123'` (MCP remote endpoint висел ~3.5ч — задокументирован как **BUG-008** для diagnostic spike'а). **Post-landing TD**: 3 GH issues открыты с label `tech-debt`+`priority/p1` ([#39](https://github.com/AlexEfimov/TG_parser/issues/39) renderer unification, [#40](https://github.com/AlexEfimov/TG_parser/issues/40) pagination_pending coverage, [#41](https://github.com/AlexEfimov/TG_parser/issues/41) `_format_tool_result` fallback) + cross-ref-table в § «TD from Session D». **Не resolved**: M1+M2+M3 mitigations (Session B+ → PR #35) остаются для defense-in-depth, FSM закрывает root cause. **Production deploy 2026-04-29 11:49 UTC** (через Session E bundle — единый image rebuild на VPS `mcp.tgp.efimov.mobi`): F1 BUG-002 confirm-flow verified end-to-end (`Удали канал '-1002120019100'` → preview → «да» → реальный `Channel marked as deleted (soft-delete)`) — direct regression trace из 28.04 00:04 закрыт на проде; F2 reserved-name guard (M2 mitigation) — `test_channel` placeholder rejected.
- **Session E (2026-04-29) — landed:** [PR #42](https://github.com/AlexEfimov/TG_parser/pull/42) ([`d055a52`](https://github.com/AlexEfimov/TG_parser/commit/d055a52); branch `fix/bug-006-bot-gemini-2026-04-29`); +14 tests в `tests/test_bot_agent.py` (5 классов: `TestGenerationConfigWiring`, `TestEmptyPartsClassification`, `TestNoCandidatesBranches`, `TestHappyPathUnchanged`, `TestBug006Regression`). Полный pytest 1877 passed (was 1863 baseline; +14). **Bugs resolved (moved to § Resolved bugs)**: BUG-006 (Critical) — Option A + thinkingBudget=0. **Spike-blocker**: live `tools/spike_bug_006.py` в текущей dev-среде упирается в Gemini API геополитику (`HTTP 400 "User location is not supported"`); script сохранён как production-ready, запуск отложен до VPS-side execution. Решение об опции принято на детерминированной HG-2 диагностике из BUG_LOG (2026-04-26 23:51 trace). **Architecture**: `bot_gemini_max_output_tokens=8192` + `bot_gemini_thinking_budget=0` (configurable Settings) → `_call_gemini` шаблонит `generationConfig.thinkingConfig.thinkingBudget` ровно когда поле не None (sentinel-конвенция для не-2.5 моделей); empty-parts/no-candidates/blocked ветки classify по `finishReason` и эмитят specific user-facing message + Prometheus counter `tg_bot_gemini_empty_parts_total{model, finish_reason}` (label set bounded). **Acceptance criteria deferred** (post-merge): live smoke Q1-Q5 на dev-bot + 24h watch на metric (≤1% от total bot-Gemini calls). **Carried over**: TD Option B (split TOOL_DECLARATIONS) — реализация отложена до post-deploy метрических данных; TD nightly health-check job. Pre-merge sanity: `git log main` показал Session D landed (`8332aa3`), working tree clean, baseline pytest зелёный. **Merge SHA**: [`b92a6f5`](https://github.com/AlexEfimov/TG_parser/commit/b92a6f5) (squash on main 2026-04-29). **Production deploy 2026-04-29 11:49 UTC**: VPS `mcp.tgp.efimov.mobi` `git pull --ff-only origin main` (b92a6f5) + `docker compose build tg_parser` (image `fa36d5fb...`) + `up -d --no-deps --force-recreate tg_parser mcp tg_bot` — все 3 контейнера healthy. **Live smoke** (Q1-Q5 + Session D F1+F2) — все 5 deterministic-trigger queries из BUG_LOG за 30 минут produced tool calls, **0 generic «Не удалось получить ответ от LLM»** в transcript бот↔пользователь, counter `tg_bot_gemini_empty_parts_total` = 0 events. Bundle deploy также закрыл production deploy для Session D FSM scaffolding.
- **Session F (2026-04-29) — landed:** branch `fix/read-hardening-bug-003-005b-007-2026-04-29`; +98 tests (33 в новом `tests/test_utils_channel_id.py` для shared helper; 47 в новом `tests/test_bot_tools_session_f.py` — 4 класса: `TestBug003ReadToolNormalization`, `TestF9ProductionScenarios`, `TestBug007SuggestionPayload`, `TestBug005BTypedCatch`, плюс happy-path shape; 18 в `tests/test_mcp_server.py::TestSessionFMcpReadHardening`). Полный pytest **1975 passed** (default mode; was 1877 baseline; +98). Self-review extended coverage post-implementation: добавил BUG-003 ask_question симптом-тест (был пропущен — оригинальный production trigger), advisory-path swallowing contract (suggestion helper при DB error не маскирует основной answer), happy-path no-injection (execute_tool успешный path не получает error_class), F-9 расширен на pause_channel + add_channel preview, MCP get_cross_channel_stats normalize. **Self-review нашёл 1 production bug:** `normalize_channel_id` не идемпотентен на `' @ch '` (peel-quote → lstrip(@) видел leading space, не @, и оставлял префикс) — direct re-introduction BUG-003 в quoted-disguise варианте; зафиксен трёхстрочной перестановкой `.strip()` после quote-peel + dedicated regression test. **Полный sweep с PostgreSQL + testcontainers + integration gates**: 2138 passed (TEST_POSTGRES=1 TEST_TESTCONTAINERS=1, OPENAI_API_KEY, `-m ""`) — 0 skipped, 0 deselected, 0 regression. **Bugs resolved (moved to § Resolved bugs)**: BUG-003 (Low/Medium), BUG-005-B (Medium), BUG-007 (Medium) — три read-side bug'а закрыты одним батчем. **Architecture**: shared `tg_parser.utils.channel_id.normalize_channel_id` helper (strips `@` prefix, surrounding `'`/`"` quotes, whitespace incl. tab/newline; idempotent — order: outer-strip → quote-peel → inner-strip → lstrip(@) → strip) — single source of truth, 25+ existing `lstrip("@")` call-sites consolidated в bot/tools.py, mcp_server.py, services/, cli/, ingestion/, scripts/. `rg "lstrip..@.." tg_parser/ scripts/` возвращает только helper body. `_build_no_results_suggestion` (bot) + `_build_no_results_suggestion_mcp` (MCP) добавляют `available_channel_ids` (top-10 RBAC-filtered) + optional `suggestion` (difflib `get_close_matches` cutoff=0.7) на `total=0`. `execute_tool` теперь различает `TimeoutError`, `PermissionError`, `ValueError`/`KeyError`, и generic `Exception` — каждая ветка preserves `error_class` + truncated `error` message (cap 500 chars). `prompts/bot.yaml` v1.2.0 (channel-normalization + fallback + error-classification sections; bump 1.1.0 → 1.2.0). `TopicListResult` (MCP) расширен optional полями `available_channel_ids` / `suggestion` (backward compat). **Pre-deploy gate**: 24h watch metric `tg_bot_gemini_empty_parts_total` (Session E) активен до **2026-04-30 11:49 UTC** — production deploy откладывается до closure для confound-free metric data.
- **Session G (2026-05-02) — landed:** branch `fix/bug-009-execute-tool-guard-2026-05-01`; +15 tests (13 в новом `tests/test_bot_execute_tool_guard.py` — 4 класса: `TestGuardRejectPaths` (5), `TestGuardPassPaths` (3), `TestGuardEdgeCases` (2), `TestWriteToolsContract` (3 — bidirectional contract per R-1 mitigation); 2 в `tests/test_bot_fsm.py` — wiring contract + integration regression `TestBug009SuggestionConfirmGuard.test_yes_after_suggestion_does_not_call_add_channel` на 2026-04-30 15:15:44 UTC trace). Полный pytest **1869 passed** (was 1854 baseline; +15; same 35 DB-related infra failures pre/post — pre-existing). 0 regressions. **Bug resolved**: BUG-009 (High) — server-side guard в `execute_tool` rejects LLM-issued `confirm=True` без matching FSM snapshot с typed `error_class="ConfirmFlowMismatch"`. **Architecture**: `_WRITE_TOOLS_REQUIRING_CONFIRM: frozenset[str]` (7 tools — все, чьи Gemini-declarations имеют `confirm: BOOLEAN`); `ConfirmFlowSnapshot` TypedDict; new optional kwarg `confirm_flow_state` на `execute_tool`; guard матч-контракт — exact `tool_name` + exact `args modulo confirm` (закрывает attack vector через injected extra args); diagnostic error message diffs `extra=`, `missing=`, `changed=` keys. `handlers._handle_confirmation_response` (единственный legitimate confirm=true call-site) теперь передаёт `confirm_flow_state={"tool_name": tool_name, "args": original_args}`; `agent.process_message` намеренно не передаёт state → любой LLM-issued `confirm=True` отвергается. **Prompt v1.4.0**: bumped 1.3.0 → 1.4.0; description обновлён («Session G structural guard active»); added recovery hint в Confirmation semantics для `error_class="ConfirmFlowMismatch"` graceful recovery. v1.3.0 hard rules сохранены (defense-in-depth — prompt-tuning + structural guard оба активны). **R-3 audit (test surface)**: 22 pre-existing tests в `test_bot_tools_v11.py` / `test_bot_tools_v12.py` / `test_rag_prompt_config.py` обновлены — добавлен `confirm_flow_state` kwarg matching args (тесты целились в executor behavior, не в guard). **Locked decisions** (per pre-flight 2026-05-02): A — trim `_WRITE_TOOLS_REQUIRING_CONFIRM` до 7 tools (vs B — extend confirm coverage to subscribe_*, register_*, *_user_auth — out of scope, tracked as TD-bot-confirm-coverage-completeness ~400+ LOC); X — prompt-fix landed как doc-only `4214d41` directly on main (mirrors `d322afc` precedent), implementation branch starts from corrected main. **Acceptance criteria deferred** (post-merge): production deploy + synthetic in-container smoke (`docker exec tg_parser_bot python3 -c "..."` returns `{"error_class": "ConfirmFlowMismatch", ...}`) + real Telegram bot smoke («да AgeManagment» after suggestion → `list_topics`, NOT `add_channel`).
- **Session F (2026-04-30) — deployed:** [PR #44](https://github.com/AlexEfimov/TG_parser/pull/44) merged via squash SHA [`88e4337`](https://github.com/AlexEfimov/TG_parser/commit/88e4337); production deploy на VPS `mcp.tgp.efimov.mobi` 15:07–15:12 UTC (5-минутное окно). **Phase 0 watch closure (BUG-006/Session E gate)**: 24h Prometheus watch на `tg_bot_gemini_empty_parts_total` reported 0 events для всех `finish_reason` cells — fix Session E полностью stable, Session F deploy unblocked. **Phase 0.4 finding** (newly discovered TD): `tg_bot` container не имеет exposed Prometheus port + нет соответствующего job в `prometheus.yml`; in-process registry-check + log-grep over 27h-window (`docker logs --since 27h tg_parser_bot | grep "gemini_empty\|gemini_no_candidates\|gemini_blocked"`) returned **0 events** — equivalent confidence через alternative observability path; filed as **TD-bot-prometheus-scrape**. **Phase 2 deploy** (15:07–15:12 UTC): `git pull --ff-only origin main` (88e4337), `docker compose build tg_parser` (cache-hit для unchanged layers + 5-6 sec for changed Python sources — only `prompts/bot.yaml`/`bot/tools.py`/`mcp_server.py`/`utils/channel_id.py` rebuilt since Session E baseline `b92a6f5`), `docker compose up -d --no-deps --force-recreate tg_parser mcp tg_bot` — все 3 контейнера healthy за ≤30 sec через docker health-checks. **Phase 3 smoke (PASS partial)**: F-1 (`темы канала @AgeManagment` с @-prefix) → 75 тем (BUG-003 production trigger closed); F-3 (`темы канала AgeManagement` typo) → suggestion + available_channel_ids (BUG-007 closed); F-2 (in-container synthetic typed-catch test через `docker exec tg_parser_bot python3 -c '...'`) → `KeyError`/`TimeoutError` payload shape с `error_class` + cap-500 truncated `error` (BUG-005-B closed); F-9 (`remove_channel test_channel`) deferred — see BUG-010. **Side-effects discovered & filed during Phase 3 smoke**: **BUG-009** (LLM hallucinates `add_channel(confirm=true)` on suggestion-confirmation reply, mitigated 2026-04-30 15:35–16:01 UTC via prompt v1.3.0 — see Phase B-(b) below); **BUG-010** (orphan placeholder `test_channel` from Session B+ M2 testing 2.5 days predates Session F — soft-deleted 2026-04-30 15:35 UTC via Phase B-(a) SQL hotfix); **BUG-011** (read-context loss multi-turn, deferred to Session H); **BUG-012** (cosmetic suggestion phrasing, P3). **Phase B-(a) hotfix (15:35 UTC, no rebuild)**: SQL `UPDATE sources SET deleted_at=NOW() WHERE source_id='-1002123123123'` inside `tg_parser_postgres`; pre/post `list_sources` confirms 6 active channels remain; reversible per Session B+ M3 contract. **Phase B-(b) hotfix (15:59:41 UTC, prompt-only — bind-mount, no rebuild)**: `prompts/bot.yaml` bumped 1.2.0 → 1.3.0 on VPS — added 2 HARD RULE bullets (one in `Instructions` strengthening «NEVER call confirm=true», one in `Confirmation semantics` as standalone HARD RULE with explicit BUG-009 reference) + 1 new bullet in `Confirmation semantics` covering Suggestion-confirmation flow (read-side context: «да X» after suggestion → re-run SAME read-tool с `channel_id=X`, NOT write-tool); backup at `prompts/bot.yaml.bak-bug009`; `docker compose restart tg_bot` reloaded prompt at 15:59:41 UTC, healthy by 12 sec. Sanity-check at 16:01 UTC: F-1 BUG-002 confirm-flow regression guard (`Удали канал mind_rise` → preview → «нет» → cancelled — Session D FSM intact) PASS; BUG-009 mitigation guard («да AgeManagment» after suggestion → `list_topics(AgeManagment)`, NOT `add_channel`) PASS. **Production state post-deploy**: 6 active channels, 3 containers healthy, prompt v1.3.0 live, BUG-003/005-B/007 closure proofs collected from real conversation traces. **Carried forward**: BUG-009 structural fix (TD-bot-execute-tool-confirm-guard, Session G), BUG-010 structural fix (TD-bot-source-username-alias), BUG-011 read-context FSM (TD-bot-read-context-preservation), BUG-012 prompt polish (TD-prompt-suggestion-format-clarity), TD-bot-prometheus-scrape, TD-storage-jsonb-channel-id (deferred since Session F gating decision D-5), TD-data-quality-AgeManagment (rename canonical?), TD-bot-intent-router (Option B Session E carry-forward), TD-bot-nightly-health-check, BUG-008 diagnostic spike.

---

## Resolved bugs

### BUG-001 — MCP tool handlers читают `ctx.client_id` вместо OAuth-контекста

| Поле | Значение |
|---|---|
| **Severity** | Critical (auth-bypass + блокирует все write-операции от имени реального user'а) |
| **Status** | `resolved (Session C, 2026-04-27, [PR #37](https://github.com/AlexEfimov/TG_parser/pull/37) → [`59ec116`](https://github.com/AlexEfimov/TG_parser/commit/59ec116))` — production deploy на VPS `mcp.tgp.efimov.mobi` выполнен 2026-04-27 19:00 UTC; post-deploy smoke (no-bearer→401, valid-bearer→real UUID `c59d42b4-…`, attacker `_meta.client_id`-attack ignored→тот же real UUID) PASSED. |
| **Component** | `tg_parser/mcp_server.py`, auth-резолверы |
| **Discovered** | 2026-04-26, Alexander через Claude (web) → remote MCP `https://mcp.tgp.efimov.mobi/mcp` |
| **Linked** | Phase 1 security audit C2 (см. `docs/notes/FUTURE_FEATURES.md:1408`); blind-spot в `tests/test_f4_auth_resolution.py` |
| **Planned fix** | **Session C** (2026-04-28 — landed early, 2026-04-27) → `docs/notes/START_PROMPT_FIX_BUG001_MCP_AUTH_2026-04-28.md` |
| **Resolution** | Helper `_extract_authenticated_user_id(ctx)` читает identity из `mcp.server.auth.middleware.auth_context.auth_context_var` (SDK contextvar, заполняемая `AuthContextMiddleware` из `scope["user"]: AuthenticatedUser`); 35 call-site'ов tool-handler'ов в `mcp_server.py` переписаны на `resolve_mcp_user(_extract_authenticated_user_id(ctx))`; `resolve_mcp_user` raises `PermissionError` в production-режиме (auth_enabled + None identity) вместо silent admin fallback'а; factory `create_mcp_server` raises `RuntimeError` при `auth_enabled && tokens={}` (BUG-001b cabinetry); E2E integration test `tests/test_mcp_auth_integration.py` (6 cases) закрывает CI blind-spot. Landed via [PR #37](https://github.com/AlexEfimov/TG_parser/pull/37) → [`59ec116`](https://github.com/AlexEfimov/TG_parser/commit/59ec116). Production deploy на VPS (`mcp.tgp.efimov.mobi`) выполнен 2026-04-27 19:00 UTC (`git pull` + `docker compose build` + `up -d --no-deps tg_parser mcp tg_bot`). Post-deploy smoke (curl direct против `https://mcp.tgp.efimov.mobi/mcp`) confirmed: (a) no-bearer / invalid-bearer → 401 `invalid_token`; (b) valid bearer → real UUID `c59d42b4-8e05-42a7-be7e-50e9d1f4b951` с 5 owned channels (вместо synthetic admin `00000000-…` pre-fix); (c) valid bearer + attacker-supplied `_meta.client_id="deadbeef-…"` → тот же real UUID `c59d42b4-…` (helper полностью игнорирует `_meta`, BUG-001 регрессия закрыта). |

#### Symptoms (исторически)

При вызове любого MCP-tool через remote endpoint с валидным Bearer-токеном:

1. `whoami` возвращает синтетического админа:

   ```json
   {"id": "00000000-0000-0000-0000-000000000000",
    "name": "admin", "role": "admin",
    "max_channels": 20, "owned_channels": [], "owned_channels_count": 0}
   ```

2. `add_channel` падает с `ForeignKeyViolationError` —
   `Key (owner_id)=(00000000-0000-0000-0000-000000000000) is not present in table "users"`.

3. `add_user_auth` (повторная попытка вручную «починить» mapping) падает
   с `UniqueViolationError` — mapping в БД **уже есть и корректен**.

4. `list_users` показывает реального admin (`c59d42b4-…`) с 5 owned channels —
   значит данные в БД консистентны.

#### Root cause (проверенный)

`BearerTokenVerifier` в `tg_parser/mcp_server.py:148–167` корректно резолвит
SHA-256-хэш токена через `resolve_user_by_auth("mcp_token", hashed)` и
возвращает `AccessToken(client_id=str(user.id), ...)`. SDK кладёт результат
в `scope["user"]: AuthenticatedUser` и в contextvar `auth_context_var`
(`mcp/server/auth/middleware/{bearer_auth.py,auth_context.py}`).

**Но** каждый tool-handler в `mcp_server.py` читает идентичность так:

```python
user = await resolve_mcp_user(ctx.client_id if ctx else None)
```

`Context.client_id` в FastMCP SDK (`mcp/server/fastmcp/server.py:1285–1290`)
определён как:

```python
@property
def client_id(self) -> str | None:
    return getattr(self.request_context.meta, "client_id", None) \
        if self.request_context.meta else None
```

`request_context.meta` — это JSON-RPC `params._meta` (`mcp/types.py:61–83`,
`RequestParams.Meta` с `extra="allow"`), то есть **client-supplied** request-
level метаданные. К Bearer-аутентификации это поле не имеет никакого отношения.
Claude / `mcp-remote` его не выставляет → `ctx.client_id` всегда `None` →
`resolve_mcp_user(None)` уходит в `get_default_admin()` →
`_DEFAULT_ADMIN_ID = "00000000-0000-0000-0000-000000000000"` с захардкоженной
ролью `admin` и именем `admin` (`tg_parser/auth/resolvers.py:65–73`).

Это **полностью** объясняет все 4 симптома без остаточных гипотез.

##### Почему гипотезы из исходного репорта мимо

| H | Вердикт | Почему |
|---|---|---|
| H1 (header не извлекается) | Близко, но мимо | Header SDK извлекает корректно; ломается downstream — наш handler читает не тот атрибут. |
| H2 (proxy режет header) | Маловероятно | `add_user_auth` (admin-only) дошёл до DB и упал на UNIQUE — значит auth-flow прошёл. |
| H3 (mcp-remote teardown) | Не подтверждается | `stateless_http=True` — каждый JSON-RPC проходит через тот же auth-backend, нет «handshake-only». |
| H4 (разный hash) | Отметаем | `hash_credential = sha256` идентичен в `add_user_auth` и `BearerTokenVerifier`; репорт сам подтверждает совпадение хэша. |
| H5 (silent fallback) | Реально, но amplifier | Без бага из root cause fallback бы не срабатывал. Чинится отдельно — это security-issue: любой неаутентифицированный → admin. |

##### Bonus-мина (вторая, ниже по severity) — BUG-001b cabinetry

В `create_mcp_server` (`tg_parser/mcp_server.py:189–194`, до фикса) auth-backend
подключался **только если оба** условия truthy:

```python
if settings.mcp_auth_enabled and settings.mcp_auth_tokens:
    kwargs["token_verifier"] = BearerTokenVerifier(settings.mcp_auth_tokens)
    kwargs["auth"] = AuthSettings(...)
```

Это нелогично — `MCP_AUTH_TOKENS` задумывался как статический *fallback*
поверх DB-резолва. С учётом DI-12 / DI-16 истории (`parse_json_dict` тихо
проглатывал `JSONDecodeError`) на проде возможно: `MCP_AUTH_ENABLED=true`
+ `MCP_AUTH_TOKENS=` пустой/битый → token_verifier не подключён → все запросы
падают в default admin даже до того, как `ctx.client_id`-баг успевает сработать.
**Resolved в Session C** (тот же PR #37): factory теперь raises `RuntimeError`
при `auth_enabled && tokens={}` — fail-loud at startup вместо silent skip.

#### Why CI didn't catch (исторически — закрыто в Session C)

`tests/test_f4_auth_resolution.py::TestBearerTokenVerifier` тестировал только
сам `verify_token` (он работал). Все остальные MCP-тесты
(`tests/test_f4_ownership.py`, `test_mcp_management.py`, `test_f5c_mcp_tools.py`,
`test_f2_parse_only_export.py`) **мокали** `resolve_mcp_user` напрямую через
`@patch("tg_parser.mcp_server.resolve_mcp_user")`. Это фиксировало контракт
«если резолвер вернул такого user'а, tool делает X», но никогда не проверяло
end-to-end путь `Bearer header → real user_id внутри tool`. Дырка была ровно
там, где сидел баг. **Закрыто в Session C** новым `tests/test_mcp_auth_integration.py`
(6 E2E-тестов через `httpx + ASGITransport`).

#### Artifacts

- Token (proverka): `qFj-BAH0umK7OxneCPxYLbKVqx9tBiC9pH0PgNVvQx0`
- SHA-256 в `user_auth_mappings`: `bfe99ca1a8646f715f48adfb491a5ebff3700d723bdb33c702d1418780068820`
- Real admin user_id: `c59d42b4-8e05-42a7-be7e-50e9d1f4b951`
- Anonymous fallback id (pre-fix): `00000000-0000-0000-0000-000000000000`
- Endpoint: `https://mcp.tgp.efimov.mobi/mcp`
- Транспорт: HTTP/SSE через `mcp-remote` (stdio bridge на стороне клиента)
- PR: [#37](https://github.com/AlexEfimov/TG_parser/pull/37) — merge SHA [`59ec116`](https://github.com/AlexEfimov/TG_parser/commit/59ec116)
- Production deploy SHA on VPS: `59ec116` (deployed 2026-04-27 19:00 UTC)

### BUG-006 — Бот возвращает «Не удалось получить ответ от LLM» на любой free-form запрос: Gemini-2.5-flash отдаёт пустой `parts=[]`, agent не различает причины

| Поле | Значение |
|---|---|
| **Severity** | Critical (бот **полностью** неработоспособен для любых текстовых запросов через `handle_text` → `agent.process_message`; команды-стейтлес `/start`, `/help` ещё работают, всё free-form — нет; блокирует cross-check для **BUG-005**) |
| **Status** | ✅ **`resolved`** (Session E landed 2026-04-29 via [PR #42](https://github.com/AlexEfimov/TG_parser/pull/42) → [`b92a6f5`](https://github.com/AlexEfimov/TG_parser/commit/b92a6f5); **production deploy на VPS** `mcp.tgp.efimov.mobi` выполнен 2026-04-29 11:49 UTC; live smoke Q1-Q5 + FSM F1 PASSED, counter `tg_bot_gemini_empty_parts_total` = 0 events за весь smoke run. Spike-blocker: live `tools/spike_bug_006.py` геоблокирован в dev-среде; на VPS прогон отложен до 24h watch closure.) |
| **Component** | `tg_parser/bot/agent.py` (`GeminiAgent.process_message`, `_call_gemini`); `tg_parser/bot/tools.py` (`TOOL_DECLARATIONS` объёмом 30+ tool'ов, ~10–15k input-токенов); косвенно — `prompts/bot.yaml` (system prompt) |
| **Discovered** | 2026-04-26, Alexander, Telegram-бот в проде |
| **Linked** | **BUG-005** (BUG-006 блокирует Шаг 0-bis из BUG-005 — невозможно сравнить `_exec_get_llm_config` бота и `get_llm_config` MCP); **BUG-002** (общий statelessness-каркас не влияет, но улучшение тестирования agent loop'а закрывает оба класса дефектов) |
| **Planned fix** | **Session E** (2026-04-29 — landed) → `docs/notes/START_PROMPT_FIX_BUG006_BOT_GEMINI_2026-04-29.md` (research-spike в начале для выбора между Option A / B / C per D-3 default; spike блокирован геополитикой Gemini API в dev-среде, выбор сделан на детерминированной HG-2 диагностике) |
| **Update 2026-04-29 11:49 UTC — Production deploy + live smoke PASSED** | ✅ Deployed на VPS `mcp.tgp.efimov.mobi` через bundle: `git pull --ff-only origin main → b92a6f5` + `docker compose build tg_parser` (image `tg_parser:latest@sha256:fa36d5fb1b1ede4f73ca8efbd60fefa5eb8a08f8f369be2240206dc38379a586`) + `docker compose up -d --no-deps --force-recreate tg_parser mcp tg_bot`. Все 3 контейнера (`c25d97179756 tg_parser`, `d349106659cb tg_parser_mcp`, `794815b50cdf tg_parser_bot`) healthy за <60 сек, новый код (`bot_gemini_max_output_tokens` / `bot_gemini_thinking_budget` / `BOT_GEMINI_EMPTY_PARTS_TOTAL`) подтверждён `docker exec`-grep в `/app/tg_parser/{config/settings.py,bot/agent.py,api/metrics.py}`. **Live smoke** (16:02-16:13 UTC+4 = 12:02-12:13 UTC) — все запросы dispatched tool calls, 0 generic «Не удалось получить ответ от LLM»: Q1 «Покажи LLM конфиг» → `get_llm_config` ✓ (точный pre-fix deterministic trigger из 2026-04-26 23:51 update); Q2 «выведи текущий llm config» → `get_llm_config` ✓; Q3 multi-channel `ask_question` Lab4health × LongevityClu(b) → 2 parallel `search_knowledge_base` ✓ (BUG-007 truncation `LongevityClu` отдельно — Session F); Q4 «перечисли темы канала Lab4health» → `list_topics` ✓; Q5 «покажи список каналов» → `list_channels` ✓; **FSM F1 BUG-002 confirm-flow** → `Удали канал '-1002120019100'` → preview → «да» → `Channel '-1002120019100' marked as deleted (soft-delete). Data preserved; ingestion stopped.` ✓ (Session D scaffolding verified end-to-end via этот же bundle deploy — direct regression на 28.04 00:04 production trace closed); F2 reserved-name guard `test_channel` → «зарезервированные названия каналов» ✓ (M2 mitigation из Session B+ verified). **Server-side metrics**: `tg_bot_gemini_empty_parts_total` = 0 events за весь smoke run; ни одного `gemini_empty_parts` / `gemini_no_candidates` / `gemini_blocked` / `parts_empty_no_candidates` / `parts_empty_with_finish_reason` log event за 30 минут проде-логов. **24h watch metric** стартовал — следить с 2026-04-29 11:49 UTC по 2026-04-30 11:49 UTC (target ≤1% empty_parts от total bot-Gemini calls; alert если spike >5%). **Carried forward**: optional `tools/spike_bug_006.py --option all --runs 2` запуск с VPS (геоблокировка обходится — прод-сервер в `RU` не блокируется Gemini API так, как dev-среда). |
| **Update 2026-04-29 — Session E landed → BUG-006 RESOLVED** | ✅ **Root cause закрыт.** Branch `fix/bug-006-bot-gemini-2026-04-29`. **Code changes**: `tg_parser/config/settings.py` — два новых конфигурируемых Settings (`bot_gemini_max_output_tokens` default 8192, `bot_gemini_thinking_budget` default 0; sentinel `None` омитит `thinkingConfig`). `tg_parser/bot/agent.py:GeminiAgent.__init__` принимает `max_output_tokens` + `thinking_budget`; `_call_gemini` шаблонит `generationConfig.thinkingConfig.thinkingBudget`. `tg_parser/bot/main.py` пробрасывает оба значения в factory-call. **Empty-parts classification** (§ Step 2 BUG_LOG): `parts=[]`/`candidates=[]`/`promptFeedback.blockReason` ветки в `process_message` теперь различают по `finishReason` и эмитят specific user-facing message (`MAX_TOKENS` → «исчерпал бюджет»; `RECITATION` → «recitation guard»; `MALFORMED_FUNCTION_CALL` → «некорректный вызов»; `SAFETY` → «безопасности»; default → generic «пустой ответ»; `candidates=[]` без block → «ни одного кандидата»). Все ветки логируют payload-dump truncated to 2048 chars + `finishReason` + `usageMetadata` + `model` + `tool_count`. **Telemetry**: `tg_parser/api/metrics.py` — новый Counter `tg_bot_gemini_empty_parts_total{model, finish_reason}` с label set bounded к {STOP, MAX_TOKENS, MALFORMED_FUNCTION_CALL, RECITATION, SAFETY, OTHER, none, no_candidates, blocked, FUTURE_*}. Helper `record_bot_gemini_empty_parts` инкрементируется из всех empty-paths. **Tests**: `tests/test_bot_agent.py` (новый файл, 14 тестов в 5 классах) — `TestGenerationConfigWiring` (defaults шлют `thinkingBudget=0`/`maxOutputTokens=8192`; `None` омитит `thinkingConfig`; custom propagated), `TestEmptyPartsClassification` (6 параметризаций по `finishReason` — каждая со специфичным message и metric incremented), `TestNoCandidatesBranches` (`blocked` vs `no_candidates`), `TestHappyPathUnchanged` (no false-positive metric increments), `TestBug006Regression` (direct «Покажи LLM конфиг» trace — message specific, не равно pre-fix string). Полный pytest 1877 passed (was 1863 baseline; +14). 0 регрессий. **Spike script**: `tools/spike_bug_006.py` сохранён как production-ready runner (Q1-Q5 × 7 опций — current/a/a-thinking-0/thinking-0/b/c-pro/c-flash-2-0); запуск отложен до VPS-side post-deploy verification из-за `HTTP 400 "User location is not supported"` в dev-среде. **Acceptance criteria deferred** (post-merge): live smoke Q1-Q5 на dev-bot, 24h watch на metric (target ≤1% от total bot-Gemini calls). **Carried over**: TD Option B (split TOOL_DECLARATIONS via intent classification) — отложено до post-deploy метрических данных; TD nightly health-check job (синтетический «Покажи LLM конфиг» каждый час + alert при empty-parts spike). |
| **Update 2026-04-26 23:09** | В новой серии запросов (23:07–23:09) bot Gemini agent loop **ожил** — корректно произвёл tool-call'ы для `ask_question` (упал в самом tool'е, см. BUG-005) и `search` (полностью успешно). Это значит BUG-006 **транзиентный для конкретного запроса**, но HG-2/HG-3 **не опровергнуты как класс**: «выведи текущий llm config» (23:00) проваливается чаще, чем «поищи информацию о пролактине» (23:08), потому что для первого нужно сравнить ~30 tool'ов с одинаковой релевантностью, а для второго — однозначный `search`. Проблема никуда не делась, просто не воспроизводится на каждом запросе. См. § «Update from search-vs-ask
| **Update 2026-04-26 23:13** | В трассе «Фитофотодерматит…» (23:12–23:13) Gemini agent loop **снова жив** на всех трёх turn'ах: turn 1 произвёл tool-call `ask_question` + render русского apology с осмысленным offer; turn 2 на «найди по ключевым словам» корректно потребовал уточнений (без tool-call'а — правильное поведение); turn 3 произвёл tool-call (вероятно опять `ask_question` из-за statelessness BUG-002, см. BUG-005 sub-секцию `sub-second Anthropic fail-time`) + apology с offer. **Никаких пустых parts/candidates за всю серию** — то есть HG-2 не воспроизводится для declarative-style запросов про контент канала, в полном соответствии с гипотезой о query-dependent thinking-budget exhaustion (трудные tool-disambiguation-запросы вроде `get_llm_config` чаще выбивают, простой content lookup — почти никогда). |
| **Update 2026-04-26 23:51** | **Контрольная B1-проверка после пополнения Anthropic billing — BUG-006 воспроизводится детерминированно** на запросе того же класса: `Покажи LLM конфиг` (вариант 23:00 «выведи текущий llm config») → `Не удалось получить ответ от LLM.` за **1 секунду**. Подтверждает: (a) BUG-006 **не зависит** от Anthropic billing (Anthropic — для RAG-LLM, не для bot-Gemini-агента); (b) HG-2 — **детерминированный паттерн** для класса запросов «покажи/выведи конфиг», а не stochastic шум; (c) 1-секундный fast-fail = типичная сигнатура `parts=[]` (Gemini API возвращает 200 OK с пустым content без тяжёлой работы). HG-2 окончательно становится главным кандидатом, HG-3 (`MALFORMED_FUNCTION_CALL`) — secondary. |_question split». |

#### Symptoms

```
Alex:           выведи текущий llm config
Tg_parser_Bot:  Не удалось получить ответ от LLM.
```

Дополнительно (важно для триажа): при том же канале и в тот же временной
окно через **MCP** аналогичный запрос (`get_llm_config`) **отрабатывает
корректно** — Anthropic Claude Sonnet 4 на стороне Claude Desktop
возвращает полную распечатку конфига. Это **не** проблема
`_exec_get_llm_config` или общей инфры; это проблема **bot's Gemini
agent loop**.

Контекст в этой же сессии: ~15 минут назад **тот же** бот успешно
отрабатывал tool-call'ы (BUG-002 — preview добавления канала, BUG-003 —
ответ «не нашёл тем»). Между 22:45 и 23:00 что-то в Gemini-стороне
изменилось.

Пользователь дополнительно подтвердил: **запросов было буквально
несколько** — отметает гипотезу выработки дневного лимита
(public free tier — 1500 RPD, paid tier — намного выше).

#### Root cause (структурный, конкретный H — uncertain без logs)

##### Что именно происходит на уровне кода

`tg_parser/bot/agent.py:160–164` шлёт HTTP POST в Gemini API. Ответ
**HTTP 200** (иначе сработала бы ветка `resp.status_code != 200` на
166–173 → текст «Gemini API returned %d…», который пользователь не
видел). Но в payload'е либо:

- `candidates=[]` без `promptFeedback.blockReason` → попадает в
  `agent.py:81–87`, возвращает «Не удалось получить ответ от LLM»;
- ИЛИ `candidates[0].content.parts=[]` без `finishReason="SAFETY"` →
  попадает в `agent.py:97–98`, возвращает то же самое сообщение.

Обе ветки **не логируют `finishReason`** (в DEBUG только
`promptTokenCount`/`candidatesTokenCount` на стр. 178–182). Это первый
структурный root cause — **нулевая диагностика для пустого ответа**.

##### Hypothesis space для пустого ответа Gemini-2.5-flash

| HG | Причина | Сигнал в `usageMetadata` / `finishReason` | Вероятность для текущего инцидента |
|---|---|---|---|
| **HG-2** | **Thinking-budget exhaustion под `maxOutputTokens=4096`** (`agent.py:153–156`). Gemini-2.5-flash включает thinking by default; thinking-токены **списываются из того же `maxOutputTokens`-budget'а** (документированная семантика, отличающаяся от 1.5-серии). С 30+ TOOL_DECLARATIONS и system prompt'ом модель тратит весь бюджет на «мысли о выборе tool'а» и возвращает `parts=[]`. | `finishReason="MAX_TOKENS"`; `usageMetadata.thoughtsTokenCount ≈ 4096`; `candidatesTokenCount = 0`. | 🔥 **Главный кандидат** (не зависит от числа запросов; объясняет нестабильность «то работает, то нет» — model-internal вариативность thinking'а). |
| **HG-3** | **`finishReason="MALFORMED_FUNCTION_CALL"`** — известная нестабильность 2.5-flash с function calling. Модель пытается вызвать tool, но валидатор Gemini side rejects → `parts=[]`. | `finishReason="MALFORMED_FUNCTION_CALL"`. | 🔥 **Сильный кандидат**, особенно при большом количестве tool'ов с похожими сигнатурами. |
| **HG-4** | **TOOL_DECLARATIONS overflow** — суммарно ~30 tool'ов с детальными descriptions (`tg_parser/bot/tools.py:43–760`), особенно крупные: `export_channel`, `subscribe_digest`, `subscribe_watchlist`, `set_llm_config`. Это ~10–15k input-токенов; technically ниже 1M context window, но **усиливает HG-2 и HG-3** под flash-моделью. | Не отдельный root cause; усилитель. | ⚠️ **Сопутствующий фактор** для HG-2/HG-3. |
| HG-5 | Региональная транзиентная деградация Gemini API (case-by-case). | Может быть `candidates=[]` без других сигналов. | ⚠️ Возможна, но не объясняет повторяемость на тривиальных запросах. |
| HG-6 | `finishReason="RECITATION"` (фильтр копирайта). | `finishReason="RECITATION"`. | ❌ Маловероятно для запроса «выведи текущий llm config». |
| HG-7 | Schema-validation rejection всего payload'а (битая JSON-Schema в одном из tool decl'ов после недавнего рефакторинга). | Отвалился бы **HTTP 400** (или внутренний 200 с пустым `candidates`). Логи покажут. | ⚠️ Стоит проверить `tg_parser/bot/tools.py:43–760` на свежие правки tool-deck. |
| HG-1 | **Quota / RPM-rate limit** | HTTP 429 (или 200 c пустыми candidates у некоторых эндпоинтов). | ❌ **Опровергнут пользователем** (несколько запросов за сессию — недостаточно для исчерпания дневного лимита free-tier 1500 RPD; на paid tier лимиты ещё выше). |

##### Почему HG-2 — главный кандидат прямо сейчас

1. **Не зависит от числа запросов** — срабатывает, как только сложность
   thinking'а превысит token-budget; «несколько запросов» сюда укладывается.
2. **Объясняет работающие случаи и неработающие в одной сессии** — для
   простых запросов («перечисли темы») модель быстро выбирает tool, для
   сложных («выведи текущий llm config» = 30+ tool'ов на сравнение) —
   тратит больше thinking'а.
3. **Объясняет несовпадение с BUG-005** — в BUG-005 Gemini успела
   произвести function call, в BUG-006 — даже не дошла до tool-call'а.
   Разный объём thinking'а — разный исход.
4. **Документировано в Gemini API release notes** (Gemini 2.5 series,
   thinking-default behavior).

##### Хронология подтверждает HG-2/HG-3 над HG-1

- 19:40 — preview добавления канала прошёл (BUG-002 trace)
- 21:39 — ответ «не нашёл тем для @AgeManagement» прошёл (BUG-003 trace)
- 22:45 — `ask_question(LongevityClub, ...)` вернул «внутренняя ошибка»
  (BUG-005 — но Gemini успешно произвела tool-call, упало в самом tool'е)
- 23:00 — `get_llm_config` → пустой ответ Gemini (BUG-006).

В каждом случае Gemini вынуждена выбрать из всего multi-tool'ного меню,
но количество thinking'а растёт нелинейно. К 23:00 thinking-budget'а
не хватает.

##### Почему гипотезы-альтернативы (что виноват backend бота, а не Gemini) отметены

| H | Описание | Вердикт |
|---|---|---|
| HB-1 | Бот упал / процесс мёртв | Нет: бот **отвечает** — просто хардкод-фолбэком из `agent.py:87/98`. Если бы процесс был мёртв, не было бы вообще никакого ответа. |
| HB-2 | `_call_gemini` ловит exception в `try/except Exception` | Нет: эта ветка отдаёт **другой** текст («Произошла ошибка при обращении к LLM. Попробуйте позже.» из `handlers.py:157` через `format_error`). Видимая фраза — другая. |
| HB-3 | Сетевая проблема между ботом и Gemini | Нет: HTTP-ошибка ушла бы по ветке `resp.status_code != 200` → текст «Gemini API returned …». |
| HB-4 | Битый system prompt после `reload_prompts` | Возможен, но проверяется быстро: попросить бота через MCP `reload_prompts` или рестартнуть. На текущих данных низкая вероятность, потому что `prompts/bot.yaml` валиден (он же используется ровно так же в работавшие до этого turn'ы). |

#### Why CI didn't catch

- **Тесты `_call_gemini` мокают валидный response** с `candidates[0].content.parts`. Не существует unit-теста на «что делает agent.py при `candidates=[]`», «при `parts=[]`», «при `finishReason="MAX_TOKENS"`», «при `finishReason="MALFORMED_FUNCTION_CALL"`».
- Нет integration-теста с реальным Gemini API даже на staging/CI (один смоук-тест с любой моделью 2.5 с включённым thinking уловил бы HG-2 на синтетическом большом tool deck'е).
- Нет nightly-задачи «ping all configured LLM providers, report degraded ones» — Gemini-2.5-flash с thinking-overflow-ом ничем не отличается от «мёртвого» провайдера на стороне юзера.
- Отсутствует prometheus/structured-metric для `gemini_response_finish_reason` distribution. Если бы был — на выборке за день видно было бы рост `MAX_TOKENS` / `MALFORMED_FUNCTION_CALL`.

#### Proposed fix

Делится на **немедленный мини-фикс** (≤30 строк, разблокирует пользователя
сразу) и **структурный fix** (исправляет class-of-bugs).

**Шаг 0 — Triage (≈3 минуты, без правки кода).**

Прочитать в логе бота HTTP body последнего ответа Gemini. У `_call_gemini`
сейчас есть `logger.debug("gemini_response", ...)` на 178–182, но он
печатает только token-counts. Нужно:

1. Поднять `LOG_LEVEL=DEBUG` для `tg_parser.bot.agent` (или временно
   добавить INFO-лог `data` целиком при `not parts`/`not candidates`).
2. Воспроизвести запрос «выведи текущий llm config» в боте.
3. Извлечь из лога `finishReason` и `usageMetadata.thoughtsTokenCount`.

Распознавание:
- `finishReason="MAX_TOKENS"` + `thoughtsTokenCount` высокий →
  **HG-2**. Шаг 1 ниже.
- `finishReason="MALFORMED_FUNCTION_CALL"` → **HG-3**. Шаг 1b ниже.
- `finishReason` пуст / `OTHER` → **HG-5/HG-7**, идти к Шагу 2.

**Шаг 1 — Минимум для HG-2 (≤10 строк, мгновенный анти-фикс).**

В `tg_parser/bot/agent.py:153–156` сделать одно из двух (любое из
вариантов разблокирует бота сейчас же):

```python
"generationConfig": {
    "temperature": 0.2,
    "maxOutputTokens": 8192,            # вариант A: удвоить budget
    "thinkingConfig": {                 # вариант B: отключить thinking
        "thinkingBudget": 0,
    },
},
```

- **Вариант A (поднять budget)** — самый безопасный; thinking остаётся,
  но ему дают где «дышать». Стоимость на запрос растёт линейно с
  thinking-токенами; в проде у нас ≤200 запросов/день — пренебрежимо.
- **Вариант B (отключить thinking)** — самый детерминированный.
  Function-calling с thinking=0 у 2.5-flash работает стабильнее по
  observability (предсказуемые latency, нет «слепых» пустых ответов).
  Стоимость падает.

Рекомендация: **Вариант A для прод-инцидента сейчас + Вариант B как
базовый settings во второй итерации** (можно вынести в
`tg_parser/config/settings.py` как `BOT_GEMINI_THINKING_BUDGET=0`).

**Шаг 1b — Минимум для HG-3 (≤20 строк).**

Добавить retry на `MALFORMED_FUNCTION_CALL` — известная transient-ошибка
2.5-flash:

```python
# в process_message, цикле for turn in range(MAX_AGENT_TURNS):
finish_reason = candidate.get("finishReason", "")
if finish_reason == "MALFORMED_FUNCTION_CALL":
    logger.warning("gemini_malformed_function_call", turn=turn)
    if turn < MAX_AGENT_TURNS - 1:
        continue  # retry — modal часто исправляется на втором проходе
    return "Не удалось разобрать вызов инструмента, попробуйте переформулировать."
```

**Шаг 2 — Структурный fix (отдельный коммит, ~80 строк).**

1. **Логирование `finishReason` для каждого ответа Gemini** (INFO-уровень
   при не-`STOP` finishReason, WARN при пустых parts). Plus
   `thoughtsTokenCount` если присутствует. Это закрывает observability-gap
   мгновенно.

2. **Расширить обработку всех `finishReason` в `agent.py:81–98`**:

   ```python
   FINISH_REASON_MESSAGES = {
       "MAX_TOKENS": "Запрос требует слишком много обдумывания. Уменьшите количество подзадач или попробуйте упростить вопрос.",
       "MALFORMED_FUNCTION_CALL": "Внутренняя ошибка вызова инструмента (повтор тоже не помог).",
       "RECITATION": "Ответ был отклонён фильтром копирайта.",
       "OTHER": "Неизвестная остановка генерации; обратитесь к администратору.",
       "SAFETY": "Ответ заблокирован фильтрами безопасности LLM.",
   }
   ```

   В каждом случае — log + structured user-message.

3. **Конфигурируемая модель и `thinkingBudget`** — добавить в
   `tg_parser/config/settings.py`:
   - `BOT_GEMINI_MODEL` (default `gemini-2.5-flash`)
   - `BOT_GEMINI_THINKING_BUDGET` (default `0` — отключаем thinking)
   - `BOT_GEMINI_MAX_OUTPUT_TOKENS` (default `8192`)

   Перенести из хардкода `agent.py:43, 154–155` в настройки. Это
   позволит легко переключиться на `gemini-2.5-pro` (стабильнее,
   дороже) или `gemini-2.0-flash` (без thinking) без правки кода.

4. **Health-check tool** — `_exec_check_bot_health` (или CLI-команда):
   делает один синтетический запрос к Gemini API с минимальным prompt'ом,
   проверяет получение валидного `candidates[0].content.parts`. Возвращает
   ok/fail + `finishReason` + latency. Делает Шаг 0 одной командой.

5. **Retry на пустой response** — обернуть `_call_gemini` в `tenacity.retry`
   для случаев `not candidates`/`not parts` без явного `blockReason`/
   `finishReason`. Max-attempts=2, delay 1s. Покрывает HG-3 и HG-5.

**Тесты (Шаг 3, обязательны).**

- Параметризация на каждый `finishReason` в `tests/test_bot_agent.py`:
  `STOP / SAFETY / MAX_TOKENS / MALFORMED_FUNCTION_CALL / RECITATION /
  OTHER / ""` — для каждого валидируется user-facing-сообщение.
- Тест на `candidates=[]` без `blockReason`.
- Тест на retry-логику для `MALFORMED_FUNCTION_CALL`.
- Smoke-test против реального Gemini API (можно условно включать через
  env-флаг, не пускать в обязательный CI, но запускать в nightly).

**Рекомендация:** Шаг 0 + Шаг 1 (вариант A: поднять `maxOutputTokens` до
8192) **сейчас как hotfix** (≈10 строк). Шаг 1b + Шаг 2 — отдельная
fix-сессия в течение дня. Шаг 3 — критично, без него регресс
гарантированно вернётся.

#### Workaround (на время до фикса)

1. **Использовать MCP/Claude вместо бота** — Claude как агентный клиент
   стабилен, у него thinking-budget не списывается из output-budget'а
   так же агрессивно. Все bot-tool'ы доступны и в MCP-форме.

2. **Перезапустить бот** — НЕ помогает (это не stale state, а
   model-side behavior), но иногда «прогревает» Gemini-провайдера на
   следующий запрос. Не надёжно.

3. **Сменить модель бот-агента вручную через env**: если есть доступ
   к `.env`, поменять `BOT_GEMINI_MODEL` (если такая переменная
   уже существует — иначе хардкод в `agent.py:43`) на
   `gemini-2.5-pro` (медленнее, дороже, стабильнее) или
   `gemini-2.0-flash` (быстрее, дешевле, без thinking). Перезапустить.

4. **Упростить запрос** — для разовой разблокировки попробовать
   обращения короткими формулировками без многозначных требований
   («покажи каналы», «дай темы канала X»). Иногда это выводит
   thinking-budget'а под порог.

#### Artifacts

- Заглушка возврата при пустом content: `tg_parser/bot/agent.py:81–87`
  (candidates=[]) и `tg_parser/bot/agent.py:97–98` (parts=[]).
- Хардкод модели и generation config: `tg_parser/bot/agent.py:43, 153–156`.
- Размер TOOL_DECLARATIONS (усилитель HG-2/HG-4):
  `tg_parser/bot/tools.py:43–760` (и продолжается до ~стр. 760
  для всех tool decl'ов; ~30 tool'ов).
- System prompt: `prompts/bot.yaml`.
- Точка отсутствия `finishReason`-логирования:
  `tg_parser/bot/agent.py:178–182`.
- **Что нужно от пользователя/оператора:** body последнего Gemini-ответа
  (либо включить DEBUG, либо добавить временный `logger.info("debug_gemini_full",
  data=data)`) — это сразу разделяет HG-2/HG-3/HG-5/HG-7.
- Cross-effect на BUG-005: пользователь не может выполнить Шаг 0-bis
  для BUG-005 (сравнить bot и MCP `get_llm_config`), пока BUG-006 не
  починен.
- **Update 2026-04-26 23:09 — пример НЕвоспроизводящегося случая
  (для понимания вариативности):** в серии 23:07–23:09 bot agent loop
  отработал и `ask_question`, и `search` — Gemini корректно делала
  tool-call'ы. Значит HG-2/HG-3 — **stochastic**, а не deterministic;
  они срабатывают на сложных decision'ах (большой tool-spread, как
  «выведи текущий llm config» — 30 tool'ов с близкой релевантностью)
  и не срабатывают на однозначных decision'ах («поищи / расскажи /
  что в канале X» — обычно один tool явно лидирует). Это согласуется
  с природой thinking-budget'а: больше внутренних альтернатив → больше
  thinking-токенов → шанс пробить `maxOutputTokens=4096`. Чисто
  cosmetic-фикс «упрости запрос» — не решение, а workaround.

---

### BUG-010 — `IngestionStateRepo.get_source` lookup-by-PK vs `list_sources` lookup-by-username UX mismatch surfaces orphan placeholder records as «not found»

> **Перенесена из § Active bugs 2026-05-14** (docs hygiene sprint M-14
> housekeeping; запись resolved Session I 2026-05-06).

| Поле | Значение |
|---|---|
| **Severity** | Medium (UX-ловушка для admin-tools и smoke-tests; data integrity intact — soft-deleted record correctly hidden from list, но `get_source` использует `source_id` (PK, e.g. `-1002123123123`), а users typing user-friendly `channel_username` (e.g. `test_channel`); расходится с `list_sources` поведением которое вернёт row by username via downstream join) |
| **Status** | ✅ **`resolved`** (2026-05-06 — Session I structural close; `get_source_by_username` repo layer + `_resolve_source` helper; GH issue [#50](https://github.com/AlexEfimov/TG_parser/issues/50)) |
| **Component** | `tg_parser/storage/sqlalchemy/ingestion_state_repo.py` (`get_source` at PK level, `list_sources` returns full row), implicit through `tg_parser/bot/tools.py` write-tool resolvers (`_exec_remove_channel/pause_channel/resume_channel` — use raw user input as `channel_id`, expect `get_source` to find it) |
| **Discovered** | 2026-04-30 (initially F-9 smoke failure for `remove_channel test_channel` — placeholder orphan from Session B+ M2 mitigation testing 2026-04-27 19:59 UTC predates Session F by 2.5 days; `list_channels` displayed it but `get_source` couldn't resolve `channel_username="test_channel"` since it queries by `source_id` (PK)) |
| **Symptoms** | (1) `list_channels` shows `test_channel`, total=6+1=7. (2) `remove_channel(channel_id="test_channel")` → "Channel not found" (Session F suggestion logic kicks in, returning `available_channel_ids` excluding test_channel since `get_source` couldn't find it — circular UX). (3) Pre-existing orphan record cannot be cleaned via bot/MCP UX without admin SQL access. |
| **Root cause (verified via Phase E SQL + repo code-read)** | (1) DB row state: `source_id='-1002123123123'`, `channel_username='test_channel'`, `status='active'`, `deleted_at=NULL`, `created_at='2026-04-27 19:59:34 UTC'` (Session B+ M2 mitigation testing artifact, predates Session F 2.5 days, NOT a Session F regression). (2) `IngestionStateRepo.get_source(self, source_id, *, include_deleted=False)` queries `SELECT * FROM sources WHERE source_id = :source_id AND deleted_at IS NULL` — PK lookup, не username lookup. (3) `IngestionStateRepo.list_sources(...)` returns full row including `channel_username` — user sees friendly name but cannot use it for downstream operations. (4) `_exec_remove_channel`-like tools accept user input as `channel_id` but pass to `get_source` directly — works only if user types numeric `source_id`, fails for `channel_username`. |
| **Why this isn't BUG-003-class** | BUG-003 was about `@`-prefix asymmetry between read- and write-tools — surface-level normalization. BUG-010 is deeper: read-tools (`list_topics`) work via `LIKE '%"X"%'` over `topic_cards.sources_json` (matches whatever's in sources JSON); write-tools resolve via `get_source(channel_id)` which is PK-bound. Different code path, different mismatch class. |
| **Why CI didn't catch** | F-9 production scenarios test (`tests/test_bot_tools_session_f.py:TestF9ProductionScenarios`) mocks `state_repo.get_source` to always return `Source(...)` regardless of input — this is the same CI gap pattern as Session B+ M3 SQL-bug (PR #36 cleanup): unit-test mocks bypass real repo dispatch logic. **Closure plan**: integration-test `test_username_alias_resolves_to_source_id` via testcontainers (Session B+ pattern). |
| **Workaround (Phase B-(a) applied 2026-04-30 15:35 UTC)** | One-shot SQL transaction inside `tg_parser_postgres`: `BEGIN; UPDATE sources SET deleted_at=NOW() WHERE source_id='-1002123123123'; COMMIT;` — soft-deleted (Session B+ M3 reversible). Pre/post `list_sources` confirms: 6 active channels remain, `test_channel` no longer in active list. F-9 re-smoke skipped per Phase E synthesis (normalization already verified at code level via Phase 2.6 + 3.3 in deploy log). |
| **Proposed fix (structural)** | Add `IngestionStateRepo.get_source_by_username(username, *, include_deleted=False)` method (queries `WHERE channel_username = :username`); update `_exec_remove_channel`/`_exec_pause_channel`/`_exec_resume_channel` to try numeric `source_id` first, fallback to `channel_username` lookup (or accept either). Companion integration-test via testcontainers. Estimate ~80 LOC + 4 tests. |
| **Linked** | Session B+ M2 (placeholder orphan-record cleanup track — original M2 reject-list landed Apr 27, the orphan was created during M2 acceptance testing; «cleanup of placeholder records in production-DB» listed as «non-blocking task» in BUG-002 § «Update 2026-04-28 (00:04)» — partially addressed by B-(a) for `test_channel`); BUG-007 (suggestion logic correctly excludes orphan from suggestions); BUG-009 (BUG-010 enables harder failure-mode if BUG-009 succeeds in adding new channels — orphan accumulation) |
| **Planned fix** | TD-bot-source-username-alias (file as GH issue in Session F closure backlog). |
| **Update 2026-05-06 — Session I landed → BUG-010 RESOLVED** | ✅ **Root cause closed structurally.** Branch `fix/bug-010-source-username-alias-2026-05-06`. GH issue [#50](https://github.com/AlexEfimov/TG_parser/issues/50). **Architecture**: new `get_source_by_username(username, *, include_deleted=False)` abstract method in `IngestionStateRepo` port + `SAIngestionStateRepo` impl (`WHERE channel_username = :username`); new `_resolve_source(normalized, state_repo)` async helper in `bot/tools.py` and `mcp_server.py` (PK-first, username-fallback per D-C); all 10 write-tool call-sites updated (5 bot executors: `trigger_pipeline`, `pause_channel`, `resume_channel`, `add_channel` dedup, `remove_channel`; 5 MCP functions: `add_channel`, `pause_channel`, `resume_channel`, `remove_channel`, `trigger_pipeline`). **Tests**: 4 testcontainers integration (I-1..I-4) + 6 unit (U-1..U-6). Full pytest 0 regressions. |

---

### BUG-011 — Bot loses subject channel context across turns: «покажи 5 главных тем» after `list_topics(AgeManagment)` returns global top-5 instead of channel-scoped

> **Перенесена из § Active bugs 2026-05-14** (docs hygiene sprint M-14
> housekeeping; запись resolved Session H 2026-05-03).

| Поле | Значение |
|---|---|
| **Severity** | Medium (UX, не data-loss; affects multi-turn conversational flows; intersects with BUG-002 root-cause-class — context-loss is structural, not specific) |
| **Status** | ✅ **`resolved`** (2026-05-03 — Session H structural close; `prompts/bot.yaml` v1.6.0 + FSMContext `read_context` shadow field + programmatic injection into Gemini `systemInstruction`; GH issue [#57](https://github.com/AlexEfimov/TG_parser/issues/57)) |
| **Component** | `tg_parser/bot/agent.py:GeminiAgent.process_message` (each call re-creates `contents=[{role:user, parts:[user_message]}]` from scratch — no per-chat conversation buffer, no FSMContext for read-context); `tg_parser/bot/handlers.py` (text handler delegates без read-context preservation); косвенно — `prompts/bot.yaml` (no instructions to «remember last channel_id from previous read-tool calls») |
| **Discovered** | 2026-04-30, Alexander, live Telegram-бот (after BUG-007 + BUG-003 closure validation) |
| **Symptoms** | User: «темы канала AgeManagment» → bot returns 75 topics for AgeManagment. User: «покажи 5 главных тем» (no explicit channel reference) → bot returns 5 topics from **all KB** (cross-channel global), not from AgeManagment. User has to repeat «5 главных тем канала AgeManagment» explicitly. |
| **Root cause** | Same root-cause-class as BUG-002 (statelessness), but for read-tools instead of write-tools. Session D FSM closes write-flow context (ConfirmFlow + PaginationFlow handles immediate next-turn), но не закрывает «implicit subject channel» across read-tool turns. Each `process_message` call sees only current user text, no «last channel mentioned» state. |
| **Why CI didn't catch** | No multi-turn read-context tests. `tests/test_bot_fsm.py` covers ConfirmFlow + PaginationFlow but не «read tool → ambiguous follow-up»-class. **Closure plan**: integration-test `test_implicit_channel_context_preserved_across_read_turns` (mock GeminiAgent: turn 1 → list_topics(AgeManagment), turn 2 «5 главных» → must call same tool with same channel_id). |
| **Proposed fix (Session H, larger refactor)** | Extend FSMContext с `read_context = {last_channel_id: str | None, last_tool: str | None}` field; update on every read-tool call; в `prompts/bot.yaml` add instruction «Если пользователь спрашивает о темах/документах без явного channel_id, и в state есть last_channel_id — use it». Estimate ~200 LOC + 12-15 tests. Это полу-FSM-, полу-prompt-fix; structural part необходим (LLM not reliable on prompt-discipline alone — see BUG-002 history). |
| **Workaround (current)** | User must explicitly include channel name in every read-tool query («5 главных тем канала AgeManagment»). |
| **Linked** | BUG-002 (parent context-loss class); BUG-009 (sibling LLM-context-loss failure-mode); косвенно — BUG-004 (was pagination-context-loss, resolved by Session D PaginationFlow — analogous solution pattern для read-context) |
| **Planned fix** | TD-bot-read-context-preservation (file as GH issue, lower priority than BUG-009). |
|| **Update 2026-05-03 — Session H landed → BUG-011 RESOLVED** | ✅ **Root cause closed structurally.** Branch `fix/bug-011-read-context-2026-05-03`. GH issue [#57](https://github.com/AlexEfimov/TG_parser/issues/57). **Architecture**: `ReadContextData` TypedDict in `bot/states.py` (data-only, D-1 — no new StatesGroup); `_READ_TOOLS_TRACKED_FOR_CONTEXT` frozenset in `bot/tools.py` (4 tools with `channel_id`: `ask_question`, `search_knowledge_base`, `list_topics`, `get_cross_channel_stats` — `get_related_topics` uses `topic_id`, correctly excluded per D-2 contract test); `_refresh_read_context` + `_read_context_for_agent` helpers in `bot/handlers.py`; TTL 15 min (D-5); `read_context` preserved across `state.clear()` in `_handle_confirmation_response` + `_handle_pagination_response` (snapshot + restore); D-7 reset on `/start`; programmatic injection into Gemini `systemInstruction` via `_call_gemini(read_context=...)` (D-4); `AgentResult.read_tools_called` carries (tool_name, args) back to handler for FSMContext update. **Prompt**: `prompts/bot.yaml` v1.5.0 → v1.6.0 — new section «Implicit channel context for read-tools» + D-6 write-tool immunity HARD RULE. **Tests**: new `tests/test_bot_read_context.py` — 29 tests across 6 classes (A: update-site guard, B: TTL resolution, C: agent injection, D: integration/BUG-011 regression, E: FSM-state interaction, F: prompt contracts). Full pytest: **2028 passed** (was 1999 baseline; +29 new, 0 regressions). ruff check + format clean. **D-2 correction vs pre-flight**: `get_related_topics` removed from frozenset (schema uses `topic_id` not `channel_id`; 4 tools instead of planned 5). **D-6 immunity**: enforced in both injection text (NEVER apply to write-tools) and R-1 contract test (forward check: every tracked tool has `channel_id` in TOOL_DECLARATIONS). |

---

### BUG-012 — Bot Gemini emits absurd self-suggestion text: «темы 1 из ['AgeManagment']» after empty-result for typo `AgeManagement`

> **Перенесена из § Active bugs 2026-05-14** (docs hygiene sprint M-14
> housekeeping; запись resolved 2026-05-02 prompt v1.5.0 fix).

| Поле | Значение |
|---|---|
| **Severity** | Low (cosmetic, surfaces only in BUG-007 suggestion-helper edge case; no data corruption; user can re-phrase) |
| **Status** | ✅ **`resolved`** (2026-05-02 — `prompts/bot.yaml` v1.4.0 → v1.5.0 prompt-only fix landed; HARD RULE против pagination phrasing на `suggestion`/`available_channel_ids` + 4 contract tests pinning the directive's wording — `tests/test_rag_prompt_config.py:TestBotPromptBug012FormatDirective`) |
| **Component** | `prompts/bot.yaml` (system prompt's «Fallback на пустом результате» section — instruction format may produce odd phrasings); косвенно — `tg_parser/bot/tools.py:_build_no_results_suggestion` payload format (LLM may misinterpret list-format) |
| **Discovered** | 2026-04-30, Alexander, live Telegram-бот (interaction directly после BUG-007 closure smoke) |
| **Symptoms** | User: «темы канала AgeManagement» → bot returns suggestion + available_channel_ids (correct BUG-007 behavior). Bot's user-facing response ends with surreal phrasing: «...темы 1 из ['AgeManagment']», suggesting LLM mis-rendered Python-list-as-string as «1 of [list]» pagination semantics. |
| **Root cause (hypothesis, unverified)** | LLM treats `available_channel_ids: ["AgeManagment", "Lab4health", ...]` as a paginated result and applies «total=N, items=...» pagination phrasing template, producing «1 из 10» style text. Format-bleed between pagination-helper output and suggestion-helper output. |
| **Workaround** | Ignore the trailing «1 из [...]» text — actual suggestion logic above is correct. |
| **Proposed fix** | Update `prompts/bot.yaml` § Fallback на пустом результате: explicit format directive «Format `available_channel_ids` as comma-separated names или bullet list, NEVER use «N из M» pagination phrasing for this field (it's not paginated)»; companion repro-test in `tests/test_rag_prompt_config.py` smoke loop (mock LLM with `available_channel_ids=[A,B,C]` → assert response не contains «из ['»). |
| **Linked** | BUG-007 (parent — this is a downstream cosmetic artifact of suggestion-emit); косвенно — BUG-004 pagination phrasing template (Session D) — possible cross-pollination in LLM's prompt understanding |
| **Planned fix** | TD-prompt-suggestion-format-clarity (file as GH issue, P3). |
| **Update 2026-05-02 — v1.5.0 prompt directive landed → BUG-012 RESOLVED** | ✅ **Format-bleed закрыт prompt-only.** Branch `fix/bug-012-prompt-format-2026-05-02`. **Code changes**: `prompts/bot.yaml` v1.4.0 → v1.5.0 — bumped version + description («v1.5.0 BUG-012 format directive against pagination phrasing on suggestion/available_channel_ids fields»); section heading «Fallback on empty results» updated to reference Session F + v1.5.0; appended a 5th HARD RULE bullet that (a) explicitly tags `suggestion` + `available_channel_ids` as HINT FIELDS (not paginated lists), (b) enumerates banned templates («N из M», «1 из 10», «показано N из M», «первая страница», «page 1 of …»), (c) prescribes format ("comma-separated list" / "short bullet list"), (d) explicitly scopes Pagination semantics ONLY to `items` field of `list_topics`/`list_channels`/`search_knowledge_base`, separating the two prompt-sections so format-bleed is structurally improbable. **Tests**: new class `TestBotPromptBug012FormatDirective` in `tests/test_rag_prompt_config.py` (4 contract tests — version pin ≥ 1.5.0, BUG-012 tag presence, anti-pattern phrasing presence (`N из M`/`1 из 10`), pagination-scope-separation contract (`items` mention + `advisory`/`hint` role marker)). All 4 PASS, ruff/format clean. Полный `pytest tests/test_rag_prompt_config.py tests/test_bot_fsm.py tests/test_bot_execute_tool_guard.py tests/test_bot_tools_session_f.py` — **219 passed**, 0 регрессий. **Why prompt-only is sufficient here**: BUG-012 is purely an LLM rendering-template selection error — there is no code-path where a Python-side guard could catch «LLM emitted '1 из 10' text» (the cosmetic phrasing is generated by the LLM AFTER all tool calls). Structural fix would require enforcing output format via Gemini structured-output mode, which is a much larger change for a Low-severity cosmetic bug. The 4 pinning tests prevent silent regression on future prompt sweeps. **Acceptance criteria deferred** (post-merge): production deploy + reload prompt + real Telegram bot smoke («темы канала AgeManagement» (typo) → assert response does NOT contain «1 из» or «из ['» before the suggestion). |

---

### BUG-009 — Bot Gemini hallucinates `add_channel(confirm=true)` on suggestion-confirmation reply (BUG-007 read-side context misclassified as write-flow confirm)

> **Перенесена из § Active bugs 2026-05-15** (MCP testing derived-actions
> batch — HANDOFF § 6 #4 cleanup; запись structurally resolved
> 2026-05-02 Session G server-side guard в `execute_tool` с typed
> `error_class="ConfirmFlowMismatch"`). Anti-scope упоминание из PR #69
> (M-14 hygiene sprint) finalized here.

| Поле | Значение |
|---|---|
| **Severity** | High (data-integrity risk: LLM unilaterally calls write-tool with `confirm=true` bypassing FSM scaffolding from Session D; can create orphan placeholder rows in `sources` если M2 reject-list не покрывает аргумент; Session B+ M3 soft-delete остаётся defensive net) |
| **Status** | ✅ **`resolved`** (Session G landed 2026-05-02 — server-side guard в `execute_tool` rejects LLM-issued `confirm=True` без matching FSM snapshot с typed `error_class="ConfirmFlowMismatch"`; prompt v1.3.0/v1.4.0 hard rules сохраняются как defense-in-depth) |
| **Component** | `prompts/bot.yaml` (LLM-дисциплина); structurally — `tg_parser/bot/tools.py:execute_tool` (нет guard'а на «`confirm=true` без matching `ConfirmFlow.awaiting_confirmation` FSM state»); `tg_parser/bot/handlers.py` (`_handle_confirmation_response` — handler знает FSM, но `execute_tool` доверяет любому LLM-call'у) |
| **Discovered** | 2026-04-30 15:15 UTC, Alexander, live smoke Session F deploy (Phase 3) — production trace через Telegram-бот |
| **Symptoms (live trace, 2026-04-30 15:15:44 UTC)** | User: «темы канала AgeManagement» → bot: «Возможно, имелся в виду 'AgeManagment'?» (BUG-007 suggestion working as designed) → user: «да AgeManagment» → bot: «Я собираюсь добавить канал \`AgeManagment\` в систему. ... Подтвердите, пожалуйста: \`да\`/\`нет\`» (FALSE POSITIVE — `add_channel(channel_id="AgeManagment", confirm=False)` instead of `list_topics(channel_id="AgeManagment")`). Continuation: user replied «нет» — bot correctly cancelled (FSM state-machine intercepted as expected) — НО initial mis-classification IS the bug. |
| **Root cause (verified)** | LLM context-loss across turns (BUG-002 root-cause-class structurally NOT closed by Session D — Session D only enforces deterministic `confirm=true` execution after preview, не предотвращает spurious `confirm=false` preview from LLM at all). On user's «да X» reply: agent loop receives bare `[{role:user, parts:[{text:"да AgeManagment"}]}]` + system-prompt + tool descriptions. Без conversation memory, LLM hallucinates «user wants me to add new channel `AgeManagment`» (training-data attractor: «да + channel-name» → `add_channel`). Pre-Session-F prompt only had warning «do NOT call again with confirm=true», nothing about «do NOT initiate a fresh write-flow on suggestion-context replies». |
| **Why CI didn't catch** | (1) Tests for `prompts/bot.yaml` v1.2.0 не покрывают cross-turn semantic (`tests/test_rag_prompt_config.py:947–977` тестирует только load). (2) `tests/test_bot_fsm.py` (Session D, 67 tests) covers deterministic `confirm=true` path AFTER preview, но не «LLM spuriously initiates write-preview from non-write user input» — это distinct class. (3) BUG-007 suggestion-emit tests (`tests/test_bot_tools_session_f.py:TestBug007SuggestionPayload`) verify payload shape но не agent-loop interpretation of payload + user reply. **Closure plan (executed Session G)**: integration-test `test_yes_after_suggestion_does_not_call_add_channel` (mock GeminiAgent: turn 1 → list_topics with suggestion, turn 2 «да X» → must produce list_topics, NOT add_channel) + 13 unit tests for the guard contract в `tests/test_bot_execute_tool_guard.py`. |
| **Proposed fix (structural — Session G TD)** | Server-side guard в `execute_tool`: если LLM зовёт write-tool с `confirm=True`, проверить `ConfirmFlow.awaiting_confirmation` FSM state (через handler context); если FSM state не указывает на этот tool с этими args — reject с typed error_class `"ConfirmFlowMismatch"`. Это закроет hallucination-class structurally (FSM-side authoritative), prompt-tuning остаётся defense-in-depth. Estimate ~150 LOC + 8-10 tests. |
| **Workaround (current)** | Live на VPS — prompt v1.3.0 mitigates через два HARD RULE bullets (verified 2026-04-30 16:01 UTC sanity check: «да AgeManagment» → `list_topics(AgeManagment)`, NOT `add_channel`). Если LLM всё-таки uno-prompts the rule (Gemini не deterministic) — пользователь говорит «нет» → FSM cancels → no DB harm. Logs scrape: `docker logs tg_parser_bot | grep "tool=add_channel"` для observability. |
| **Linked** | BUG-002 (родительский context-loss class — Session D закрыл deterministic-execute, оставил spurious-preview); BUG-007 (read-side suggestion emit — корректно работает как designed, baits LLM на trigger); косвенно — Session B+ M2 reject-list (не покрывает все channel-id, но `AgeManagment` legitimate channel — был бы accepted in `add_channel` create flow, единственное что спасло — user said «нет» на FSM preview) |
| **Planned fix** | Session G — `TD-bot-execute-tool-confirm-guard` ([GH issue #49](https://github.com/AlexEfimov/TG_parser/issues/49)); estimate 1.5–2 ч; включить companion test `test_yes_after_suggestion_does_not_call_add_channel`. |
| **Update 2026-05-02 — Session G landed → BUG-009 RESOLVED** | ✅ **Root cause закрыт structurally.** Branch `fix/bug-009-execute-tool-guard-2026-05-01`. **Code changes**: `tg_parser/bot/tools.py` — added `_WRITE_TOOLS_REQUIRING_CONFIRM: frozenset[str]` (7 tools — все, чьи Gemini-declarations имеют `confirm: BOOLEAN`: `add_channel`, `remove_channel`, `pause_channel`, `resume_channel`, `trigger_pipeline`, `set_llm_config`, `reset_llm_config`); new `ConfirmFlowSnapshot` TypedDict; new helper `_check_confirm_flow_match`; new optional kwarg `confirm_flow_state: ConfirmFlowSnapshot | None = None` на `execute_tool`. Guard runs ONLY на `name in _WRITE_TOOLS_REQUIRING_CONFIRM and args.get("confirm") is True` → возвращает `{"error": ..., "error_class": "ConfirmFlowMismatch"}` если (a) `confirm_flow_state is None`, (b) `tool_name` mismatch, или (c) `args` (modulo confirm) mismatch (extra/missing/changed keys diagnosed in error message). `tg_parser/bot/handlers.py:_handle_confirmation_response` — единственный legitimate confirm=true call-site, теперь передаёт `confirm_flow_state={"tool_name": tool_name, "args": original_args}`; agent loop (`agent.py:process_message`) намеренно НЕ передаёт state → любой LLM-issued `confirm=True` отвергается. **Prompt v1.4.0**: bumped 1.3.0 → 1.4.0; description обновлён («Session G structural guard active»); добавлен recovery hint в § Confirmation semantics — «if you ever receive `error_class="ConfirmFlowMismatch"`, recover by calling the same tool again with confirm=false». Все existing v1.3.0 hard rules сохранены (defense-in-depth). **Tests**: `tests/test_bot_execute_tool_guard.py` (новый, 13 тестов в 4 классах — `TestGuardRejectPaths` 5 тестов на reject paths, `TestGuardPassPaths` 3 теста на legitimate paths, `TestGuardEdgeCases` 2 теста, `TestWriteToolsContract` 3 теста — bidirectional contract `forall t: t has confirm BOOLEAN ⇔ t ∈ _WRITE_TOOLS_REQUIRING_CONFIRM`, R-1 mitigation per Session G runbook). `tests/test_bot_fsm.py` дополнен 2 тестами в `TestConfirmationResponseHandler` (`test_handler_passes_confirm_flow_state_matching_preview` — wiring contract) + 1 классом `TestBug009SuggestionConfirmGuard.test_yes_after_suggestion_does_not_call_add_channel` — direct integration regression на 2026-04-30 15:15:44 UTC trace (mock Gemini issues `add_channel(confirm=True)` через agent loop → guard rejects, executor sentinel never fires, `ConfirmFlowMismatch` payload reaches LLM via functionResponse). **R-3 audit**: 22 pre-existing tests в `test_bot_tools_v11.py` / `test_bot_tools_v12.py` / `test_rag_prompt_config.py` обновлены — добавлен `confirm_flow_state` kwarg matching args (тесты целились в executor behavior, не в guard). Полный pytest **+15 tests, 0 regressions**: 1869 passed (was 1854 baseline; same 35 DB-related failures pre/post — pre-existing infra). `ruff check` + `ruff format --check` clean repo-wide. **Acceptance criteria deferred** (post-merge): production deploy + synthetic in-container smoke (`docker exec tg_parser_bot python3 -c "..."` returns `{"error_class": "ConfirmFlowMismatch", ...}`) + real Telegram bot smoke («да AgeManagment» after suggestion → `list_topics`). |

#### Reproduction trace (production, 2026-04-30 15:15:44 UTC)

```
[15:15:34] User:  каковы основные темы канала AgeManagement ?
[15:15:38] Bot:   list_topics(channel_id="AgeManagement")
                  → total=0, available_channel_ids=[..., "AgeManagment", ...],
                    suggestion="Возможно, имелся в виду 'AgeManagment'?
                                (вы запросили 'AgeManagement')"
[15:15:38] Bot:   К сожалению, я не нашел тем для канала "AgeManagement".
                  Возможно, имелся в виду 'AgeManagment'? Также есть:
                  AgeManagment, Lab4health, LongevityClub, ...
[15:15:42] User:  да AgeManagment
[15:15:44] Bot:   Я собираюсь добавить канал "AgeManagment" в систему.
                  ❌ ❌ ❌  ← BUG-009 manifests here (add_channel preview emitted)
                  Действие: Создать новый канал.
                  Подтвердите, пожалуйста: "да" или "нет".
[15:15:50] User:  нет
[15:15:51] Bot:   Действие отменено.  ← FSM correctly cancelled
```

This is BUG-009-α: «da X»-after-suggestion confused with «da»-after-write-preview. Distinct from BUG-002 (resolved) — Session D ensures «да»-after-actual-write-preview is handled deterministically by FSM (no LLM call); BUG-009 is the inverse failure where LLM creates a write-preview from a non-write user input (read-context confirmation).

---

> **Перенесена из § Active bugs 2026-05-20** (M-15 docs hygiene sprint; joint fix-sprint PR #79 `5465918`, 24h watch GREEN per [`REVIEW_2026-05-16_BUG013_14_24_DONE.md`](REVIEW_2026-05-16_BUG013_14_24_DONE.md)).

### BUG-013 — Scheduler shares one `AsyncSession` pair across `asyncio.gather` tasks → `IllegalStateChangeError` + cascading `InterfaceError` on every `incremental_pipeline` tick

| Поле | Значение |
|---|---|
| **Severity** | Medium (observability: 0 user-visible data impact — inner pipeline sessions complete; scheduler-tick gets flagged `success=false` after data-work is already persisted; `tg_parser_scheduler_tasks_total{status="success",task_name="incremental_pipeline"}` is **absent** since deploy, every tick counted as `status="error"`, "completed" structured-log lines never emitted → metric & log signal degraded) |
| **Status** | ✅ **`resolved`** (Joint fix-sprint landed 2026-05-15 — see «Update 2026-05-15» closure row below) |
| **Component** | [`tg_parser/services/scheduler_service.py`](../../tg_parser/services/scheduler_service.py) (`run_incremental_for_all_sources` lines 61-65 — single `ingestion_and_processing_repos()` opened at line 63 and shared via `asyncio.gather` over per-source closures; `repo_lock = asyncio.Lock()` band-aid at line 81 only serializes `processed_repo.list_by_channel` reads on lines 102-103/134, **not** the `state_repo` writes inside per-task `finally` blocks); [`tg_parser/services/db_context.py`](../../tg_parser/services/db_context.py) line 192 (`await proc_session.close()` is where the exception surfaces during context-exit) |
| **Discovered** | 2026-05-14 — Wave 1 step 2 F4-B Core 24h post-deploy watch (deploy 2026-05-13T19:30:28Z; first tick to fail logged 2026-05-13T20:28:37Z — tick #1 post-F4B deploy reproduces immediately on fresh log buffer). Watch verdict GREEN otherwise — see [`REVIEW_2026-05-14_WAVE1_STEP2_DONE.md`](REVIEW_2026-05-14_WAVE1_STEP2_DONE.md) § 4 "Pre-existing bugs surfaced by watch window". |
| **Symptoms (production trace, watch window 2026-05-13T19:30:00Z → 2026-05-14T19:30:00Z)** | Prometheus: `increase(tg_parser_scheduler_tasks_total{task_name="incremental_pipeline"}[24h])` ≈ 24 ticks, 100% `status="error"`, **zero** `status="success"`. Container `tg_parser` (API + scheduler) logs over the same window: 18 `sqlalchemy.exc.IllegalStateChangeError` tracebacks at `db_context.py:192` + 3 cascading `sqlalchemy.exc.InterfaceError` (`<class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress`) during the rollback path that the failed close triggers. Data side: `incremental_embedding` task succeeds 39/39 over the same period, `processed_documents` rows advance — pipeline payload IS completing inside per-source `run_full_pipeline` (which opens its own internal sessions), only the wrapper close-time/rollback fails. |
| **Root cause (HIGH confidence — code-walk verified)** | SQLAlchemy 2.x `AsyncSession` is **not safe** to share across concurrent `asyncio` tasks regardless of user-space locking ([SQLAlchemy docs — concurrency caveats](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html#using-asyncio-scoped-session)). The scheduler entrypoint at [`scheduler_service.py:61-65`](../../tg_parser/services/scheduler_service.py) opens **one** `(state_repo, processed_repo, db)` triple via `ingestion_and_processing_repos()` and at line 306 fans out `await asyncio.gather(*[_process_source(s) for s in sources])` over all 12 active sources. Every `_process_source` closure shares the same `proc_session` / `state_session`. The `repo_lock` on line 81 serializes the two `processed_repo.list_by_channel` reads (lines 103, 134) but does **not** wrap (a) `state_repo` writes in the per-task `finally` blocks, (b) the per-task `run_full_pipeline` call which itself opens nested sessions — these can overlap arbitrarily. When the `AsyncExitStack` unwinds at line 61 and `db_context.py:192` calls `await proc_session.close()`, the session is mid-flight on another task's operation → `IllegalStateChangeError` on close; the asyncpg connection's autorollback then hits "another operation is in progress" → cascading `InterfaceError`. |
| **F4-B Core relationship** | **NOT a F4-B regression.** `git diff 7953302^ 7953302 -- tg_parser/services/scheduler_service.py tg_parser/services/db_context.py` shows **0 lines** changed in `scheduler_service.py` and a purely additive `+12` lines in `db_context.py` (new `workspace_repo()` context manager only — the `ingestion_and_processing_repos` block at lines 176-192 is untouched). Bug is structurally pre-existing; F4-B Core deploy gave it a fresh log buffer (containers restarted, counter from zero) which is what made it visible enough to file. Verified non-regression also via Prometheus: `tg_workspace_resolver_seconds` p99 over 24h = 4.96 ms (healthy) and 0 workspace-related errors across api/bot/mcp logs in the watch window. |
| **Why CI didn't catch** | Scheduler concurrency is hard to exercise in unit tests — current `test_scheduler_service.py` mocks `state_repo`/`processed_repo` and runs `_process_source` either sequentially or with a 1-source fixture; no test forces ≥ 2 concurrent sources against real SQLAlchemy `AsyncSession`. The sharing-violation is a runtime invariant of asyncpg/SQLAlchemy 2.x, not catchable by static checks. **Closure plan**: integration test via `pytest-asyncio` + testcontainers Postgres that runs `run_incremental_for_all_sources` with ≥ 2 fake-but-real sources (mock telethon ingest) and asserts no `IllegalStateChangeError` / `InterfaceError` in captured logs + `success` counter increments. |
| **Proposed fix (Session next per HANDOFF § 6 #2)** | Move `ingestion_and_processing_repos()` **inside** each `_process_source` task (per-task session pair); drop the `repo_lock` (no longer needed — each task has private sessions; the small contention on `aggregate` dict mutations can be replaced by per-task return values aggregated by the parent after `asyncio.gather`). Keep the outer `state_repo.list_sources(status="active")` read using a one-shot session opened before the gather. Estimated ~30 LOC delta in `scheduler_service.py` + 2 new integration tests (1 multi-source success path, 1 partial-failure isolation guarantee). Half-day effort. |
| **Workaround (current, in-place)** | None required for data correctness — pipeline payload completes per-source; only observability noise. **Operator note for runbooks**: do **NOT** trust `tg_parser_scheduler_tasks_total{task_name="incremental_pipeline",status="error"}` as a signal until BUG-013 closes — cross-check via `incremental_embedding{status="success"}` counter (which is single-threaded and works correctly) and `processed_documents` row count growth. |
| **Linked** | BUG-014 (sibling pre-existing scheduler bug, complementary failure-mode same tick); [`REVIEW_2026-05-14_WAVE1_STEP2_DONE.md`](REVIEW_2026-05-14_WAVE1_STEP2_DONE.md) § 4 (watch verdict that surfaced the bug); F4-B Core merge SHA [`7953302`](https://github.com/AlexEfimov/TG_parser/commit/7953302) (non-regression proof — zero `scheduler_service.py` changes). |
| **Planned fix** | TD-scheduler-per-task-sessions (filed as [#76](https://github.com/AlexEfimov/TG_parser/issues/76) at start of joint fix-sprint with BUG-014 [#77](https://github.com/AlexEfimov/TG_parser/issues/77) + BUG-024 [#78](https://github.com/AlexEfimov/TG_parser/issues/78)); fix-sprint planned per [`HANDOFF_POST_WAVE1_STEP2_2026-05-15.md`](HANDOFF_POST_WAVE1_STEP2_2026-05-15.md) § Pending #2 + planning artifact [`START_PROMPT_FIX_BUG013_SCHEDULER_SESSION_2026-05-15.md`](START_PROMPT_FIX_BUG013_SCHEDULER_SESSION_2026-05-15.md). |
| **Update 2026-05-15 — Joint fix-sprint landed via PR [#79](https://github.com/AlexEfimov/TG_parser/pull/79) (SHA `5465918`)** | ✅ **Root cause closed structurally.** `tg_parser/services/scheduler_service.py:run_incremental_for_all_sources` refactored so each `_process_source` task opens its OWN `ingestion_and_processing_repos()` session triple — no `AsyncSession` is shared across `asyncio.gather` tasks. Outer scope opens a short-lived `ingestion_state_repo()` purely for the initial `list_sources(status="active")` read and closes it before fanning out. `repo_lock` dropped (no longer needed once sessions are per-task; aggregate-dict mutations remain safe under asyncio cooperative scheduling — see inline contract comment in `_process_source`). `asyncio.gather` now uses `return_exceptions=True`; unhandled escapes surface via a `scheduler_unhandled_escape source_id=...` structured `logger.error` line. **Tests**: 6 new pure-mock unit tests in `tests/test_scheduler_service.py` (T-1 .. T-6) cover per-task session isolation across concurrent sources (queue-based fixture asserts distinct mock-triple per task) and `return_exceptions=True` isolation. All 19 pre-existing scheduler tests updated to also patch `ingestion_state_repo` (the new outer-read path). Full suite: 2095 passed, 0 regressions; `ruff format` + `ruff check` clean. **Closes [#76](https://github.com/AlexEfimov/TG_parser/issues/76)**; see joint commit message and PR body for the full deviation log + 24h post-merge watch checklist. |

#### Reproduction trace (production, 2026-05-14T09:28:37Z — one representative tick)

```
{"event": "Processing source labdiagnostica_logical (channel=labdiagnostica_logical)",
 "logger": "tg_parser.services.scheduler_service",
 "timestamp": "2026-05-14T09:28:37.608798Z"}
{"event": "Processing source mind_rise (channel=mind_rise)",
 "logger": "tg_parser.services.scheduler_service",
 "timestamp": "2026-05-14T09:28:37.608870Z"}
   ↑ ≈ 70 µs apart — two `asyncio.gather` tasks racing on the same `proc_session`

{"event": "Task incremental_pipeline failed: ...InterfaceError: cannot perform operation: another operation is in progress",
 "level": "error",
 "logger": "tg_parser.services.background_scheduler",
 "timestamp": "2026-05-14T09:28:37.610457Z",
 "exception": "Traceback ...
   File scheduler_service.py:306 in run_incremental_for_all_sources
     await asyncio.gather(*[_process_source(s) for s in sources])
   ...
   File db_context.py:192 in ingestion_and_processing_repos
     await proc_session.close()
   ...
   sqlalchemy.exc.IllegalStateChangeError  ← surfaces at close
   ...
   sqlalchemy.dialects.postgresql.asyncpg.AsyncAdapt_asyncpg_dbapi.InterfaceError:
     cannot perform operation: another operation is in progress  ← cascading rollback"}
```

(The same minute also produced a separate BUG-014 TypeError for a different source — see BUG-014 entry below. Both bugs co-fire on most ticks.)

---

> **Перенесена из § Active bugs 2026-05-20** (M-15 docs hygiene sprint; joint fix-sprint PR #79 `5465918`).

### BUG-014 — Scheduler `_process_source` compares offset-naive `source.rate_limit_until` against `datetime.now(UTC)` → `TypeError` aborts the tick before any pipeline work runs

| Поле | Значение |
|---|---|
| **Severity** | Medium (observability: 0 user-visible data impact — the affected source is **skipped** for that tick because the comparison fails before `run_full_pipeline` is called; pipeline retries on next hourly tick. Hot-path effect: for any source with a non-null `rate_limit_until`, every tick fails at line 89 → that source's data never advances until manual intervention or the rate-limit row is cleared. Cross-fires with BUG-013 in the same tracebacks — both visible per-tick.) |
| **Status** | ✅ **`resolved`** (Joint fix-sprint landed 2026-05-15 — see «Update 2026-05-15» closure row below) |
| **Component** | [`tg_parser/services/scheduler_service.py`](../../tg_parser/services/scheduler_service.py) line 89 — `rate_limited = source.rate_limit_until and source.rate_limit_until > datetime.now(UTC)`; left operand `source.rate_limit_until` is read from DB as `datetime` (tz-naive when the underlying SQLAlchemy column was declared without `timezone=True` or when the Postgres column is `TIMESTAMP WITHOUT TIME ZONE`), right operand is `datetime.now(UTC)` (tz-aware). |
| **Discovered** | 2026-05-14 — Wave 1 step 2 F4-B Core 24h post-deploy watch window. 6 tracebacks `TypeError: can't compare offset-naive and offset-aware datetimes` observed in `docker logs --since 2026-05-13T19:30:00Z --until 2026-05-14T19:30:00Z tg_parser` (~25% of the 24 ticks in the window). |
| **Symptoms (production trace, watch window 2026-05-13T19:30:00Z → 2026-05-14T19:30:00Z)** | Container `tg_parser` logs over 24h window: 6 occurrences of the `TypeError` stacktrace, originating exactly at `scheduler_service.py:89`. The TypeError bubbles up out of `_process_source` into the `asyncio.gather` at `scheduler_service.py:306`, then the surrounding `AsyncExitStack.__aexit__` on line 61 unwinds — which is also where BUG-013 surfaces (3 cascading `InterfaceError` rollbacks visible). Sources that triggered the TypeError were skipped for that tick; next-tick repeat unless `rate_limit_until` aged out. |
| **Root cause (likely — surface-level diagnosis)** | DB returns `source.rate_limit_until` as offset-naive `datetime` (likely because either (a) the SQLAlchemy column on the `sources` model uses `DateTime` not `DateTime(timezone=True)`, or (b) Postgres column type is `TIMESTAMP WITHOUT TIME ZONE` — needs source-of-truth read of the SA model + Alembic head to disambiguate before fix). Comparison with `datetime.now(UTC)` (tz-aware) raises `TypeError`. Same class of bug as the long-running "naive vs aware" footgun in Python `datetime`. **Verification deferred to fix-sprint** — recommend `await state_repo.list_sources(status="active")` followed by `print([type(s.rate_limit_until), s.rate_limit_until.tzinfo for s in sources if s.rate_limit_until is not None])` to confirm the naive/aware mix before changing the column or the comparison. |
| **F4-B Core relationship** | **NOT a F4-B regression.** Same proof as BUG-013: F4-B Core merge `7953302` made zero changes to `scheduler_service.py` and only additive changes to `db_context.py`. Line 89 (`source.rate_limit_until > datetime.now(UTC)`) is unchanged since well before F4-B Core. Bug surfaces during the 24h watch window because (a) one or more `sources.rate_limit_until` rows happen to be populated with naive timestamps from earlier ingestion attempts, and (b) the container restart on F4-B deploy reset the log buffer making the prior history of the same bug less visible. |
| **Why CI didn't catch** | Tests for `_process_source` mock `Source` rows with `rate_limit_until=None` (the happy path) or fully tz-aware values; no fixture exercises the naive-DB-read code path. There is no integration test that round-trips a `rate_limit_until` write → DB → read against testcontainers Postgres to verify the tzinfo invariant. **Closure plan**: pin the invariant by (a) declaring `DateTime(timezone=True)` on the ORM column if it isn't already, (b) Alembic migration to `TIMESTAMP WITH TIME ZONE` if Postgres column is naive, (c) unit test asserting `Source.rate_limit_until.tzinfo is not None` after read from testcontainers Postgres, (d) optional defensive `_to_aware(dt)` helper that coerces naive → UTC at the comparison site. |
| **Proposed fix (Session next per HANDOFF § 6 #2)** | Smallest correct fix: change the comparison to `rate_limited = source.rate_limit_until is not None and source.rate_limit_until.replace(tzinfo=source.rate_limit_until.tzinfo or UTC) > datetime.now(UTC)` (~3 LOC at the call site). Better long-term fix: enforce tz-aware at the ORM column boundary (Alembic + SQLAlchemy column type) so the entire codebase is naive-free downstream. ~5-10 LOC total + 1 testcontainers integration test. |
| **Workaround (current, in-place)** | None needed — affected sources retry on next hourly tick once `rate_limit_until` ages past `datetime.now(UTC)` (the comparison succeeds when the operand was set very recently with a known tz, and fails specifically for naive values). For operator-driven cleanup: `UPDATE sources SET rate_limit_until = NULL WHERE source_id = ...` (Session B+ M3 reversibility pattern). |
| **Linked** | BUG-013 (sibling pre-existing scheduler bug — co-fires in same ticks, identical F4-B non-regression proof, recommended to fix in the same sprint); [`REVIEW_2026-05-14_WAVE1_STEP2_DONE.md`](REVIEW_2026-05-14_WAVE1_STEP2_DONE.md) § 4 (watch verdict surfacing the bug); F4-B Core merge SHA [`7953302`](https://github.com/AlexEfimov/TG_parser/commit/7953302) (non-regression proof). |
| **Planned fix** | TD-scheduler-rate-limit-tz-aware (filed as [#77](https://github.com/AlexEfimov/TG_parser/issues/77) alongside BUG-013 [#76](https://github.com/AlexEfimov/TG_parser/issues/76) + BUG-024 [#78](https://github.com/AlexEfimov/TG_parser/issues/78) at start of joint fix-sprint); fix planned in same session as BUG-013 per [`HANDOFF_POST_WAVE1_STEP2_2026-05-15.md`](HANDOFF_POST_WAVE1_STEP2_2026-05-15.md) § Pending #2 + planning artifact [`START_PROMPT_FIX_BUG013_SCHEDULER_SESSION_2026-05-15.md`](START_PROMPT_FIX_BUG013_SCHEDULER_SESSION_2026-05-15.md). |
| **Update 2026-05-15 — Joint fix-sprint landed via PR [#79](https://github.com/AlexEfimov/TG_parser/pull/79) (SHA `5465918`)** | ✅ **Defensive coerce landed.** `tg_parser/services/scheduler_service.py` now defines a module-level `_coerce_aware_utc(dt)` helper that attaches `UTC` to tz-naive `datetime` inputs (identity on already-aware, `None` passes through). The helper is called at the `rate_limit_until` comparison site in `_process_source`, so the comparison is always aware-vs-aware. Parse-boundary structural fix in `tg_parser/domain/json_utils.parse_iso_datetime` is **deferred** (cross-cutting; would change tz-info shape for many downstream consumers — filed as a follow-up TD per planning artifact § 7). **Tests**: `tests/test_scheduler_service.py::test_bug014_naive_rate_limit_until_does_not_crash` (T-3) asserts that a `Source` with a tz-naive future `rate_limit_until` is cleanly skipped (no `TypeError`, `sources_skipped == 1`, `mark_attempt_started` NOT called). **Closes [#77](https://github.com/AlexEfimov/TG_parser/issues/77)**; see joint commit + PR body for context. |

#### Reproduction trace (production, 2026-05-14T09:28:37Z — same tick as BUG-013 example)

```
Traceback (most recent call last):
  File "/root/.local/lib/python3.12/site-packages/tg_parser/services/scheduler_service.py",
       line 89, in _process_source
    rate_limited = source.rate_limit_until and source.rate_limit_until > datetime.now(UTC)
                                               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
TypeError: can't compare offset-naive and offset-aware datetimes
```

(Followed immediately by the BUG-013 `InterfaceError` + `IllegalStateChangeError` cascade during `AsyncExitStack` unwind — the two bugs co-fire on most ticks.)

---

### BUG-015 — MCP `trigger_pipeline` silent no-op (architectural cross-container dispatch gap)

| Поле | Значение |
|---|---|
| **Severity** | High (silent failure mode for AI agents / automation scripts driving ingestion through MCP — `triggered: true` returned without any work performed; no observability path for the caller to detect; data correctness unaffected for scheduler-driven ticks, but MCP `trigger_pipeline` is the documented escape hatch for «start now» workflows and it is unconditionally broken) |
| **Status** | ✅ **`resolved`** (Wave 1 step 3.1 — branch `fix/wave1-step3-1-mcp-dispatch-2026-05-22`; ADR 0007 Option A+B: `POST /api/v1/pipeline/trigger` on `tg_parser`, MCP/Bot HTTP proxy, `trigger_topicization` / `trigger_link_topics` MCP tools; PR SHA pending user commit/push) |
| **Component** | `tg_parser/mcp/tools.py` (handler `trigger_pipeline` — returns `{triggered: true}` without dispatching to scheduler); `tg_parser/services/scheduler_service.py` (no entrypoint accepting external one-shot jobs); `docker-compose.yml` (MCP service `tg_parser_mcp` is in a separate container — no shared queue / IPC / network path to the `tg_parser` scheduler service) |
| **Discovered** | 2026-05-15 — Claude (Anthropic) MCP testing session; first reproduced 2026-05-14 ~05:43 UTC and ~06:00 UTC for channel `profendocrinologist`; investigation-log § Phase 3 documents the architectural root-cause walk |
| **Symptoms (session trace, 2026-05-14 ~05:43 + ~06:00 UTC)** | `trigger_pipeline(channel_id="profendocrinologist")` returns `{triggered: true}` (HTTP 200) at both call-times. Zero corresponding log lines in `tg_parser` container over the next 20+ minutes. Channel only processed at the scheduled `incremental_pipeline` tick at 06:28 UTC (i.e. the natural hourly cadence — `trigger_pipeline` had no causal effect). Reproduced twice in the same session. |
| **Root cause (HIGH confidence — architectural walk verified during session)** | MCP server lives in container `tg_parser_mcp`, scheduler + pipeline live in container `tg_parser`. There is no shared queue, no event bus, no HTTP-API hook on `tg_parser` for one-shot scheduler jobs, and the MCP container does **not** have a Telethon-client session for the user (auth lives in `tg_parser`). The handler likely fires `asyncio.create_task(...)` locally inside the MCP process; the task either (a) dies when the JSON-RPC response is sent and the request's event-loop scope closes, or (b) survives but cannot perform ingestion because there is no Telethon client in this container. Either way the call is a no-op from the user's perspective. |
| **F4-B Core relationship** | **NOT a F4-B regression.** Cross-container dispatch gap is pre-existing; `git log -- tg_parser/mcp/tools.py tg_parser/services/scheduler_service.py` shows no changes related to MCP→scheduler dispatch in the F4-B Core landing. F4-B Core did not touch the MCP container's network access to `tg_parser`. Surfaced by external testing session, not by F4-B's 24h watch. |
| **Why CI didn't catch** | MCP `trigger_pipeline` tests mock the scheduler (`test_mcp_management.py` patches the dispatch target); no test exercises the **cross-container** dispatch path against a real `tg_parser_mcp` container talking to a real `tg_parser` container. The architectural gap is invisible to single-process pytest. **Closure plan**: integration test via docker-compose harness that runs both containers and asserts `tg_parser.log` shows `Starting ingestion: source=<X>` within 60 s of a successful MCP `trigger_pipeline(X)` response. Test design depends on the dispatch-contract chosen in ADR 0007. |
| **Proposed fix** | Requires **ADR 0007** (MCP↔scheduler dispatch-contract decision: HTTP API endpoint on `tg_parser` (`POST /pipeline/trigger`) vs shared message queue (Redis / Postgres LISTEN-NOTIFY) vs event bus). ADR 0007 to be drafted in Wave 1 step 3 planning session (per parent decision Q4 of MCP-testing classification). Implementation deferred to Wave 1 step 3.1 sprint per parent decision Q7. The `{triggered: true}` lie should at minimum be replaced with `{triggered: false, error_class: "DispatchNotImplemented", ...}` as a pre-ADR safety patch — but is itself a behaviour change that the ADR should authorize. |
| **Workaround (pre-fix, historical)** | Operator dropped to SSH on VPS: `docker compose exec tg_parser tg-parser ingest --source <X>` (per [operational runbook § 1, § 5](mcp_testing/2026-05-15_claude_session/04-operational-runbook.md)), or waited ≤ 1 hour for the scheduler tick. **Post-fix (2026-05-22):** MCP/Bot `trigger_pipeline` queues work via `POST /api/v1/pipeline/trigger`; verify `triggered: true` and `job_id` in the response. |
| **Linked** | ENH-1 (`trigger_topicization` — same architectural concern, blocked by same ADR) and ENH-2 (`trigger_link_topics` — same) per [`mcp_testing/.../02-enhancements.md`](mcp_testing/2026-05-15_claude_session/02-enhancements.md); BUG-016 (env-drift on the same MCP container — compounds confusion when triaging this bug); parity tracker O-3 (MCP write-tool asymmetry — see [`PARITY_DECISION_TRACKING.md` § 3 O-3](PARITY_DECISION_TRACKING.md)) |
| **Planned fix** | ADR 0007 **Accepted** 2026-05-22 (Option A+B). Execution: [`START_PROMPT_SPRINT_WAVE1_STEP3_1_2026-05-22.md`](START_PROMPT_SPRINT_WAVE1_STEP3_1_2026-05-22.md). |

---

> **Перенесена из § Active bugs 2026-05-21** (S1 doc-drift cleanup). Status `open` → `resolved` per [`REVIEW_2026-05-16_BUG013_14_24_DONE.md` § 4.2](REVIEW_2026-05-16_BUG013_14_24_DONE.md) (closed by PR [#81](https://github.com/AlexEfimov/TG_parser/pull/81) SHA `5907179` on 2026-05-15T21:55Z, auto-closed issue #80). Полное содержание сохранено без сокращений.

### BUG-016 — `tg_parser_mcp` container env drift: `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` missing

| Поле | Значение |
|---|---|
| **Severity** | Medium (low direct user-visible impact — Telethon client is not used by most MCP code paths — but the startup log line `Missing TELEGRAM_API_ID/HASH` compounds confusion when triaging BUG-015 and similar cross-container issues; operators reasonably conclude that the MCP container cannot ingest, leading to wasted investigation cycles) |
| **Status** | ✅ **`resolved`** (PR [#81](https://github.com/AlexEfimov/TG_parser/pull/81) SHA `5907179` co-deployed with BUG-013/14/24 joint fix on 2026-05-15T21:55Z; auto-closed issue #80; verdict captured in [`REVIEW_2026-05-16_BUG013_14_24_DONE.md` § 4.2](REVIEW_2026-05-16_BUG013_14_24_DONE.md) as «CLOSED by PR #81»). Originally flagged 2026-05-14 in [`REVIEW_2026-05-14_WAVE1_STEP2_DONE.md` § 2.3](REVIEW_2026-05-14_WAVE1_STEP2_DONE.md), reinforced by [`mcp_testing/.../01-bug-report.md` § ISSUE-1 investigation log](mcp_testing/2026-05-15_claude_session/01-bug-report.md). |
| **Component** | `docker-compose.yml` — `tg_parser_mcp` service `env_file` or `environment` block (does not pull `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` from the shared `.env`); `tg_parser` service in the same compose file pulls them correctly — env-drift between the two services |
| **Discovered** | 2026-05-14 — Wave 1 step 2 F4-B Core watch window (REVIEW § 2.3 flagged future housekeeping); reinforced 2026-05-15 by the Claude MCP testing session ISSUE-1 walk |
| **Symptoms** | On `docker compose up tg_parser_mcp` (or container restart), startup logs emit `Missing TELEGRAM_API_ID/HASH` (or equivalent) at WARNING/ERROR level. The MCP server still starts and accepts JSON-RPC requests for read-tools, but any code path that would instantiate a Telethon client fails. `tg_parser` container in the same compose stack starts cleanly with the same env values resolved. |
| **Root cause (HIGH confidence — env-file drift)** | The `tg_parser_mcp` service block in `docker-compose.yml` either omits the env-file declaration entirely, or lists a subset of env vars that excludes `TELEGRAM_API_ID` / `TELEGRAM_API_HASH`. The `tg_parser` service block (which lists them) was updated at some point without the corresponding update to `tg_parser_mcp`. Pure config-drift, no code involved. |
| **F4-B Core relationship** | **NOT a F4-B regression.** Env-drift pattern is structurally pre-existing; F4-B Core did not modify `docker-compose.yml` service env declarations. F4-B Core 24h watch noticed the warning lines as part of the broader observability audit (REVIEW § 2.3). |
| **Why CI didn't catch** | No CI job exercises `docker compose up tg_parser_mcp` against a populated `.env` and grep's startup logs for missing-env warnings. CI `Docker Build` job builds the image but does not start it with the production env-file. **Closure plan**: extend `Alembic Runtime Upgrade Smoke (testcontainers)` (or add a sibling compose-smoke job) to bring up `tg_parser_mcp` and assert zero `Missing TELEGRAM_API_*` lines in stdout. |
| **Proposed fix** | Align `tg_parser_mcp` service block in `docker-compose.yml` with `tg_parser` service block's env handling — typically a single `env_file: .env` line (or equivalent `environment:` mapping). ~2 LOC. May bundle with BUG-015 architectural fix sprint OR land standalone earlier as a quick housekeeping commit. **Extended scope (2026-05-16, Path 1 decision per parent agent session):** also covers (a) the Telethon sessions volume mount `./data/sessions:/app/sessions` in the `mcp` service (originally not listed here because BUG-016 framed Telethon usage in MCP as minimal — that assumption was invalidated by the 2026-05-15T20:55Z AMBER probe of the joint BUG-013/014/024 fix, which surfaced that `tg_parser/mcp_server.py:1758-1792` `_run_pipeline_background` runs `run_full_pipeline` in-process and thus instantiates Telethon), and (b) mirror env_file + sessions volume to the `tg_bot` service (same defect — bot exposes `trigger_pipeline` as a bot tool at `tg_parser/bot/tools.py:54,266,2846` and runs the same `_run_pipeline_background` pattern at `tg_parser/bot/tools.py:1373` → `run_full_pipeline` → Telethon). BUG-015 (architectural silent-noop / cross-container dispatch pattern) intentionally NOT addressed here — remains ADR-0007-gated, separate sprint. Cross-refs: [`mcp_testing/2026-05-16_claude_session/tg_parser_pipeline_regression_report.md`](mcp_testing/2026-05-16_claude_session/tg_parser_pipeline_regression_report.md) (Claude's P0 deep-dive that re-surfaced and root-caused the env+volume gap), [`mcp_testing/2026-05-16_claude_session/analysis_and_options.md`](mcp_testing/2026-05-16_claude_session/analysis_and_options.md) (cross-check + 5-option matrix). |
| **Workaround (current, in-place)** | Ignore the warning lines on `tg_parser_mcp` startup — they do not block MCP read-tools. Operators triaging BUG-015 should be aware that this is a separate, lower-severity issue. |
| **Linked** | BUG-015 (architectural — symptoms of BUG-015 are often misread as «BUG-016 caused it»); [`REVIEW_2026-05-14_WAVE1_STEP2_DONE.md` § 2.3](REVIEW_2026-05-14_WAVE1_STEP2_DONE.md) (original flag) |
| **Planned fix** | TD-mcp-container-env-alignment (small standalone commit, or bundle with BUG-015 sprint). |
| **Update 2026-05-15 — PR [#81](https://github.com/AlexEfimov/TG_parser/pull/81) (SHA `5907179`) landed → BUG-016 RESOLVED** | ✅ Aligned `tg_parser_mcp` + `tg_bot` service blocks in `docker-compose.yml` with `tg_parser` env handling: added `env_file: .env` plus the Telethon sessions volume mount `./data/sessions:/app/sessions` to both services (mirrors the `tg_parser` service block). Path 1 decision per parent agent session 2026-05-16 — closes (a) env drift on `TELEGRAM_API_ID` / `TELEGRAM_API_HASH`, (b) sessions-volume gap surfaced by the 2026-05-15T20:55Z AMBER probe (`tg_parser/mcp_server.py:1758-1792` `_run_pipeline_background` runs `run_full_pipeline` in-process and thus instantiates Telethon), (c) symmetric defect in `tg_bot` (`tg_parser/bot/tools.py:54,266,2846` exposes `trigger_pipeline` and reaches `run_full_pipeline` via `_run_pipeline_background` at `tg_parser/bot/tools.py:1373`). Auto-closed [#80](https://github.com/AlexEfimov/TG_parser/issues/80). Verdict captured in [`REVIEW_2026-05-16_BUG013_14_24_DONE.md` § 4.2](REVIEW_2026-05-16_BUG013_14_24_DONE.md) as the bundled infra unblock for the joint scheduler watch window. BUG-015 (architectural cross-container dispatch / Telethon `code_callback` `EOFError`) remains **OPEN** as a side-effect discovery — newly reachable now that the env layer is fixed; ADR-0007-gated separate sprint queued for Wave 1 step 3.1. |

---

### BUG-017 — Misleading scheduler log "[3/4] Topicization skipped (--skip-topicize)"

| Поле | Значение |
|---|---|
| **Severity** | Low (no functional impact on data correctness — topicization is by-design separated from the hourly scheduler and runs via CLI `tg-parser topicize` manually; severity is UX / diagnostic clarity only); however testing-session evidence shows the message produced **~60 min of wasted investigation** in the Claude session before the architectural intent was understood — so cumulative cost across operators is high |
| **Status** | ✅ **`resolved`** (S2 quick-wins fix landed 2026-05-21 — see «Update 2026-05-21» closure row below) |
| **Component** | `tg_parser/services/pipeline_service.py:236` (or thereabouts — verify exact line at fix time; the literal string `Topicization skipped (--skip-topicize)` is the searchable anchor); CLI flag passing originates in `tg_parser/services/scheduler_service.py:112` (`skip_topicize=True` hardcode — by-design per ISSUE-3 retraction in session) |
| **Discovered** | 2026-05-15 — Claude (Anthropic) MCP testing session, surfaced during Phase 4 wrong-hypothesis investigation («forgot to remove `--skip-topicize` after billing-incident mitigation»); resolved via code-walk that found the hardcode in `scheduler_service.py:112` — by-design, not a runtime flag |
| **Symptoms** | Every hourly scheduler tick (~24 ticks/day) emits a log line of the form `[3/4] Topicization skipped (--skip-topicize)` for each active source. The `(--skip-topicize)` suffix reads as if a runtime CLI flag was passed and could be unset — but it cannot, the flag is hardcoded in `scheduler_service.py:112` as an architectural decision (topicization is expensive, scheduler ticks hourly, topicization is intentionally a separate manual workflow via `tg-parser topicize <channel>`). Operators reading the log line waste time looking for the (non-existent) place where the flag is set at runtime. |
| **Root cause (HIGH confidence — code-walk verified in session)** | The log message format string was lifted from an earlier version of the codebase when `--skip-topicize` was indeed a runtime flag; subsequent refactor moved it to a hardcode in `scheduler_service.py:112` but did **not** update the per-tick log line in `pipeline_service.py`. The message format outlived the runtime-configurability it described. |
| **F4-B Core relationship** | **NOT a F4-B regression.** Pre-existing log line, unchanged across F4-B Core landing (`pipeline_service.py:236` not touched). Surfaced 2026-05-15 because the testing session was the first deep dive into scheduler behaviour by an external operator. |
| **Why CI didn't catch** | Log-message wording is not subject to any CI check (and probably should not be; this is a UX-clarity bug, not a behavioural one). **Closure plan**: amend the log message to read `[3/4] Topicization step (run separately via 'tg-parser topicize' CLI — scheduler does not auto-topicize by design)` or similar; add a regression test in `tests/test_pipeline_service.py` pinning the literal string (so future refactors cannot silently regress the wording). |
| **Proposed fix** | Replace the literal `Topicization skipped (--skip-topicize)` with `Topicization skipped (scheduler does not auto-topicize by design; run 'tg-parser topicize <channel>' manually)` — or, more elegantly, promote `skip_topicize` to a real `SCHEDULER_AUTO_TOPICIZE` env-var with default `false`, then the log line `Topicization skipped (SCHEDULER_AUTO_TOPICIZE=false)` becomes natural. Either way ~1-2 LOC + 1 pinning test. **Quick win** — bundle with BUG-018 / BUG-023 in a small quick-wins PR per HANDOFF updated sequence step #3. |
| **Workaround (current, in-place)** | Operators reading logs should know that `--skip-topicize` is a hardcoded by-design behaviour (not a runtime flag); see [operational-runbook § 1 «What does NOT happen automatically»](mcp_testing/2026-05-15_claude_session/04-operational-runbook.md). |
| **Linked** | BUG-018 (CLI false-success — both surfaced in same Phase 4/5 investigation walk); BUG-023 (silent topic-quality rejection — both bundled as quick-win candidates); operational-runbook § 1 (workaround doc) |
| **Planned fix** | TD-pipeline-log-clarity-skip-topicize; quick-win batch (per parent decision Q6 «later session», not this task). |
| **Update 2026-05-21 — S2 quick-wins fix on branch `fix/quick-wins-018-017-023-2026-05-21` (local SHA `6b029ce` — PR #87 SHA `2e9213c`)** | ✅ **Resolved.** `tg_parser/services/pipeline_service.py` log line on the `skip_topicize=True` path replaced from the misleading `[3/4] Topicization skipped (--skip-topicize)` (which reads as a runtime CLI flag) to `[3/4] Topicization skipped (scheduler does not auto-topicize by design; run 'tg-parser topicize <channel>' manually)`. Zero runtime semantics change; ~1 LOC behaviour change (log wording only). **Tests**: `tests/test_bug017_topicization_skipped_log.py` — pinning test that asserts the new log line lacks the `--skip-topicize` literal AND mentions `by design` + `tg-parser topicize` so future refactors cannot silently regress the wording. |

---

### BUG-018 — CLI `tg-parser topicize` reports success when 100% of LLM batches fail

| Поле | Значение |
|---|---|
| **Severity** | High (automation safety: CLI prints `✅ Topicization завершён` and exits 0 even when every single LLM batch failed for systemic reasons — billing / auth / quota class errors; automation scripts wrapping the CLI exit code interpret this as success and proceed to dependent steps; false-success masks systemic outages — the highest-impact data-correctness bug surfaced by the testing session) |
| **Status** | ✅ **`resolved`** (S2 quick-wins fix landed 2026-05-21 — see «Update 2026-05-21» closure row below) |
| **Component** | `tg_parser/services/topicization_service.py` (returns `TopicizationResult(topic_cards=0, ...)` silently when all batches errored — no class-of-error tracking); `tg_parser/processing/topicization.py` (per-batch error swallowing); `tg_parser/cli/app.py` topicize handler (emits ✅ message based on no-exception return, not on batch-result aggregate) |
| **Discovered** | 2026-05-15 — Claude (Anthropic) MCP testing session, Phase 5 manual topicization 2026-05-14 ~07:33 UTC; first topicize run on `kdl_ru` failed all 17 batches with `Your credit balance is too low to access the Anthropic API`, CLI nonetheless printed `✅ Topicization завершён: • Создано тем: 0` and exited 0; second run after balance top-up succeeded normally — establishing that the false-success only manifests under systemic failure |
| **Symptoms (session trace, 2026-05-14 07:33 UTC)** | `docker compose exec tg_parser tg-parser topicize --channel kdl_ru` → all 17 batches log `Your credit balance is too low...` → CLI summary prints `✅ Topicization завершён: • Создано тем: 0 • Создано подборок: 0 • Coverage: 0.0% (0/841 documents) ⚠️ Темы не созданы (возможно, недостаточно данных)`. The «возможно недостаточно данных» message is doubly misleading: actual cause is API failure, not data shortage. Exit code 0 (confirmed by session operator). `total_tokens: 0` in the summary is the only hint of systemic fail, easy to miss. |
| **Root cause (HIGH confidence — code-walk hypothesis, requires fix-sprint confirmation)** | `run_batches(...)` returns aggregate counts of created topics / topic_cards; per-batch failures are caught and logged but **not** propagated to the caller as a class-of-error tag. The CLI handler interprets `topic_cards == 0` as «no data» rather than «all attempts failed». No distinction is drawn between (a) genuine 0-data-no-topics, (b) partial fail (e.g. 3/17 batches errored, 14 succeeded), (c) full systemic fail (17/17 batches errored with same class of error — billing / auth / quota). All three currently render the same ✅ + exit 0. |
| **F4-B Core relationship** | **NOT a F4-B regression.** Pre-existing topicization-service code path, unchanged across F4-B Core. F4-B Core 24h watch did not cover manual CLI topicize invocations. |
| **Why CI didn't catch** | Tests for `topicize` CLI mock the LLM client to return successful batch results or pre-canned failures; no test asserts CLI exit-code behaviour on the «all batches fail with same systemic error» scenario. **Closure plan**: unit test mocking `run_batches` to return aggregate `(0 topics, 17 errors, error_class="BillingError")` → assert CLI exits non-zero AND prints the first error message + the «N/M batches errored» count + a hint about API credentials. |
| **Proposed fix** | (1) Distinguish «0 topics produced» from «all N batches errored» by tracking `failed_batches / total_batches` ratio in `TopicizationResult`; (2) Non-zero exit code (exit 2) on systemic-fail class (e.g. `failed_batches / total_batches > 0.5`); partial fail (1-50 % errored) stays exit 0 with a warning summary; (3) Surface the first error category in the summary table (`Failed: 17/17 batches errored (BillingError: Your credit balance is too low...)`); (4) Drop the misleading «возможно недостаточно данных» line when batch failures dominate. ~30 LOC + 2-3 tests. **Quick win** — bundle with BUG-017 / BUG-023 in a small quick-wins PR per HANDOFF updated sequence step #3. |
| **Workaround (current, in-place)** | After CLI completes, operator runs `list_topics(channel_id="<channel>", limit=3)` via MCP — if `total == 0` AND the CLI log contains `Batch X/Y failed: ...` lines, treat as real fail despite the ✅. Documented as «⚠️ Verify success» pattern in [operational-runbook § 2](mcp_testing/2026-05-15_claude_session/04-operational-runbook.md). |
| **Linked** | BUG-017 (Phase 4-5 same investigation walk, both quick-win candidates); BUG-019 (LLM JSON-parse retry — adjacent reliability class); BUG-023 (silent topic-quality rejection — same observability class) |
| **Planned fix** | TD-topicize-cli-systemic-fail-exit-code; quick-win batch (per parent decision Q6). |
| **Update 2026-05-21 — S2 quick-wins fix on branch `fix/quick-wins-018-017-023-2026-05-21` (local SHA `875a5f6` — PR #87 SHA `2e9213c`)** | ✅ **Resolved.** Pipeline now tracks per-invocation `total_batches` / `failed_batches` / `last_batch_error` on `TopicizationPipelineImpl` (`tg_parser/processing/topicization.py:topicize_channel`); counters reset at the top of each call; multi-batch path increments `failed_batches` from the `asyncio.gather(return_exceptions=True)` aggregation site, single-batch path captures state before propagating the exception. `tg_parser/services/topicization_service.py:run_topicization` surfaces the trio in its returned stats dict. CLI `tg_parser/cli/app.py:_run_full_topicization` exits with code **2** when `failed_batches / total_batches > 0.5` (systemic-fail class), prints the first error class to stderr with a credentials / quota hint, and drops the misleading «возможно, недостаточно данных» line when batch failures dominate. Partial-fail (≤50 % errored) stays exit 0 with a warning summary. **Tests**: `tests/test_bug018_topicize_exit_code.py` — 6 cases (multi-batch all-fail counter, partial-fail counter, counter reset between runs, CLI exit 2 on systemic fail with «недостаточно данных» line suppressed, CLI exit 0 on partial fail with warning, CLI exit 0 with the legacy «недостаточно данных» hint on truly empty channel). |

---

### BUG-019 — LLM JSON-parse retry uses identical prompt → deterministic triple-fail on malformed-JSON path

| Поле | Значение |
|---|---|
| **Severity** | Medium (cost overrun + latency: when the LLM returns malformed JSON on a batch, the retry path resends the **identical** prompt — same input → same output → 3 consecutive guaranteed failures + ~18 seconds wasted per failure batch + 3× input-token billing for the same content; rare per session but compounds cost when triggered) |
| **Status** | `open` (pre-existing, surfaced 2026-05-15 by Claude MCP testing session — see [`mcp_testing/.../01-bug-report.md` § ISSUE-5](mcp_testing/2026-05-15_claude_session/01-bug-report.md)) |
| **Component** | `tg_parser/processing/pipeline.py` (LLM call + retry block — `max_attempts=3` config, retry without prompt mutation); inherited via `tg_parser/processing/topicization.py` for the topicize flow |
| **Discovered** | 2026-05-15 — Claude (Anthropic) MCP testing session, observed during `profendocrinologist` processing — log lines `post:1799 attempt 1 → "Invalid JSON response from LLM: Expecting ',' delimiter: line 2 column 435"` repeated 3× with identical error message |
| **Symptoms (session trace, profendocrinologist processing)** | `post:1799 attempt 1 → "Invalid JSON response from LLM: ..."` → `post:1799 attempt 2 → <same error>` → `post:1799 attempt 3 → <same error>` → `parallel_message_processing_failed`. The 3 retries do not mutate the prompt (no «previous response was malformed JSON» hint), do not change temperature, and do not switch to a different response format — so the LLM produces the same output and the parser rejects it again. |
| **Root cause (HIGH confidence — retry-block code path is straightforward)** | Retry loop in `pipeline.py` is unconditional re-issue of the original prompt with no mutation. Anthropic API is mostly deterministic for the same input + temperature, so this guarantees the same malformed-JSON output every time. The retry budget is wasted by construction. |
| **F4-B Core relationship** | **NOT a F4-B regression.** Pre-existing LLM-call wrapper, unchanged across F4-B Core. |
| **Why CI didn't catch** | LLM client tests mock either «always-success» or «always-fail» scenarios — no test exercises the «malformed JSON returned → retry → assert prompt mutated between attempts» contract. **Closure plan**: contract test asserting that on `JSONDecodeError` retry, the second-attempt prompt contains a hint string («your previous response was malformed JSON ...») OR uses structured-output mode (Anthropic tool-use). |
| **Proposed fix** | **Preferred**: switch to Anthropic structured-output / tool-use mode for the topicization JSON contract (schema-enforced server-side — eliminates the malformed-JSON class entirely). **Fallback**: on `JSONDecodeError` retry, append an explicit hint to the user message — «your previous response was malformed JSON (error: <truncated parse error>), please return strictly valid JSON». Moderate effort either way (~50-150 LOC depending on path). |
| **Workaround (current, in-place)** | None — failed batches are skipped and re-processed on the next incremental tick. Cost overrun is small per session (3× a few hundred tokens), but compounds across long-tail of session retries. |
| **Linked** | BUG-018 (topicize systemic-fail surface — adjacent reliability class); BUG-020 (no exp-backoff for 5xx — adjacent retry-strategy class) |
| **Planned fix** | TD-llm-structured-output-or-retry-hint; bundle with next processing-pipeline touch. |

---

### BUG-020 — No exponential backoff for Anthropic HTTP 5xx (520 / 529 / 503)

| Поле | Значение |
|---|---|
| **Severity** | Low (rare — provider-side transient hiccups; retries do eventually succeed; no data correctness impact; the bug is that immediate retries amplify transient errors rather than recover gracefully from them) |
| **Status** | `open` (pre-existing, surfaced 2026-05-15 by Claude MCP testing session — see [`mcp_testing/.../01-bug-report.md` § ISSUE-6](mcp_testing/2026-05-15_claude_session/01-bug-report.md); session logs 2026-05-14 07:01-07:02 UTC show `Server error '520 <none>' for url 'https://api.anthropic.com/v1/messages'` for several consecutive posts) |
| **Component** | `tg_parser/processing/pipeline.py` (or wherever the Anthropic client wrapper lives — the retry block around HTTP-status-code 5xx responses); shared with all Anthropic-using paths |
| **Discovered** | 2026-05-15 — Claude (Anthropic) MCP testing session, observed in logs around 2026-05-14 07:01-07:02 UTC — burst of Cloudflare 520 responses (Anthropic upstream hiccup) caused immediate retries without backoff |
| **Symptoms** | When Anthropic API returns `HTTP 520 <none>` (or `529 Overloaded` / `503 Service Unavailable`), the retry happens immediately without jitter or backoff. Multiple in-flight requests retrying simultaneously compound the transient overload condition. Eventually succeeds (Cloudflare 520 is transient), but with worse-than-necessary tail latency and a small risk of cascading rate-limit. |
| **Root cause (HIGH confidence — retry-block code path)** | Retry wrapper does not classify HTTP error class (5xx-transient vs 4xx-permanent); does not apply backoff sleep between attempts; does not jitter. Standard retry-omitted-backoff anti-pattern. |
| **F4-B Core relationship** | **NOT a F4-B regression.** Pre-existing HTTP client wrapper. |
| **Why CI didn't catch** | HTTP-error-class retry behaviour is not exercised in unit tests (the client is mocked). **Closure plan**: contract test asserting that on first 5xx response, second attempt is delayed by at least `MIN_BACKOFF_MS` (≥ 100 ms); jitter within `±25 %` of the nominal delay. |
| **Proposed fix** | Wrap the Anthropic HTTP client in a standard exp-backoff + jitter retry layer (`tenacity` already in deps, or hand-rolled — small enough to do inline); emit Prometheus gauge `anthropic_api_5xx_total{status}` per error class. Bundle with the next processing-pipeline touch. ~20-30 LOC. |
| **Workaround (current, in-place)** | None needed — failed batches are skipped and reprocessed on the next incremental tick; failure rate is low enough that this is not actively painful. |
| **Linked** | BUG-019 (adjacent retry-strategy class — both should be fixed together); ENH-5 / ENH-6 (cost-control — exp-backoff reduces wasted token spend during outages) |
| **Planned fix** | TD-anthropic-client-exp-backoff; bundle with next processing-pipeline touch. |

---

### BUG-021 — `get_cross_channel_stats` ignores `topic_links` table (returns keyword overlap only after link-topics run)

| Поле | Значение |
|---|---|
| **Severity** | Medium (analytics blindness: after running `link-topics` to populate the cross-channel semantic-link table, the MCP `get_cross_channel_stats` endpoint returns **identical JSON** to its pre-link-topics output — the analytics surface exposes only keyword overlaps, never semantic-link counts / averages; A1 (AI-curious learner) and A6 (Domain curator) audiences cannot perceive the value of the `link-topics` operation through the analytics tool) |
| **Status** | `open` (pre-existing, surfaced 2026-05-15 by Claude MCP testing session — see [`mcp_testing/.../01-bug-report.md` § ISSUE-8](mcp_testing/2026-05-15_claude_session/01-bug-report.md), [`03-investigation-log.md` § Phase 6](mcp_testing/2026-05-15_claude_session/03-investigation-log.md), [`05-data-quality-report.md` § 3 «Limitation»](mcp_testing/2026-05-15_claude_session/05-data-quality-report.md)) |
| **Component** | `tg_parser/services/analytics_service.py` (or equivalent — the implementation of `get_cross_channel_stats`); `tg_parser/mcp/tools.py` handler `get_cross_channel_stats` (the public-facing tool surface) |
| **Discovered** | 2026-05-15 — Claude (Anthropic) MCP testing session, Phase 6 cross-channel analysis 2026-05-14; reproduced by calling `get_cross_channel_stats` **before** and **after** `link-topics` (which created 746 links at threshold 0.3) — JSON output was byte-identical for the relevant sections, only keyword overlaps were reported (795 entries) |
| **Symptoms** | Pre-`link-topics`: `get_cross_channel_stats` returns `{keyword_overlaps: 718, ...}` (no `topic_link_stats` key). Post-`link-topics` with 746 new links: same response, byte-identical structure, no `topic_link_stats` key, no per-channel-pair semantic stats. Operator running `get_related_topics(<topic>)` separately **does** see the new links — so they exist in `topic_links` table, just not surfaced through the aggregate endpoint. |
| **Root cause (HIGH confidence — endpoint implementation hypothesis)** | The `get_cross_channel_stats` implementation queries only the `keyword_overlaps` table (or equivalent) and has no JOIN / aggregation over the `topic_links` table. Likely a feature-gap from when `topic_links` was added (probably after `get_cross_channel_stats` was already shipped) — the endpoint was never updated to expose the new analytic dimension. |
| **F4-B Core relationship** | **NOT a F4-B regression.** Pre-existing analytics endpoint, unchanged across F4-B Core (F4-B touched workspace scoping but not the topic-links surface). |
| **Why CI didn't catch** | Tests for `get_cross_channel_stats` use fixtures that do not populate the `topic_links` table — they cannot detect the «output is identical with or without topic_links populated» symptom. **Closure plan**: test with fixture that populates `topic_links` (e.g. 5-10 mock links between 3 channels) → assert response contains `topic_link_stats.total_links == 5` (or equivalent). |
| **Proposed fix** | Add `topic_link_stats` section to the response shape — `total_links`, `avg_similarity`, `links_by_channel_pair[]`, optionally `strongly_connected_components`. Schema sketched in [ISSUE-8 source](mcp_testing/2026-05-15_claude_session/01-bug-report.md). Bundle naturally with ENH-4 (workspace-overlap analytics) when that lands — same code surface, complementary use case. ~50-80 LOC + 1 fixture-rich test. |
| **Workaround (current, in-place)** | For semantic connectivity queries, use `get_related_topics(<topic_id>)` per-topic instead of the aggregate endpoint — it does read `topic_links` correctly. For aggregate analytics, no workaround — limitation is documented in [data-quality-report § 3 «⚠️ Limitation»](mcp_testing/2026-05-15_claude_session/05-data-quality-report.md). |
| **Linked** | ENH-4 (workspace-overlap analytics — same code surface, bundle for cohesion); operational-runbook § 4 «Verify» (mentions `get_related_topics` as workaround); [`PARITY_DECISION_TRACKING.md` O-3](PARITY_DECISION_TRACKING.md) (MCP write-tool asymmetry — adjacent but distinct: O-3 is about missing write tools, BUG-021 is about an existing read tool being incomplete) |
| **Planned fix** | TD-analytics-topic-link-stats; bundle with ENH-4 implementation. |

---

### BUG-022 — `subscribe_watchlist` / `subscribe_digest` not idempotent (re-running creates duplicate subscriptions → duplicate pushes)

| Поле | Значение |
|---|---|
| **Severity** | Medium (automation safety: re-running a subscription script with the same `(name, channel_ids, ...)` arguments creates a new subscription row each time — UUID changes, content identical; inconsistent with `add_workspace_source` which is correctly idempotent via UNIQUE constraint and returns `changed: false`; users running automation scripts with «safe re-run» semantics end up with N duplicates and N× push amplification on every watchlist match) |
| **Status** | `open` (pre-existing, surfaced 2026-05-15 by Claude MCP testing session — see [`mcp_testing/.../01-bug-report.md` § ISSUE-10](mcp_testing/2026-05-15_claude_session/01-bug-report.md), [`02-enhancements.md` § O-7](mcp_testing/2026-05-15_claude_session/02-enhancements.md); idempotency policy decision deferred to ADR 0009 in Wave 1 step 3 planning per parent decision Q4) |
| **Component** | `tg_parser/services/watchlist_service.py` (`subscribe_watchlist` — INSERT-only); `tg_parser/services/digest_service.py` (`subscribe_digest` — INSERT-only); `tg_parser/mcp/tools.py` handlers `subscribe_watchlist` / `subscribe_digest` (public surface) |
| **Discovered** | 2026-05-15 — Claude (Anthropic) MCP testing session, Phase 7 subscription setup 2026-05-14; reproduced directly — calling `subscribe_watchlist` with the same `(title, channel_ids, keywords, description)` twice produced two rows with different UUIDs |
| **Symptoms (session trace, Phase 7)** | After creating 4 watchlists via MCP, the session operator noted that re-running the same script would create 4 additional duplicates (total 8) — verified by calling each `subscribe_*` twice in sequence with identical args. `add_workspace_source` on the same session is correctly idempotent (returns `changed: false`) — establishing that the idempotency-pattern exists in the system but is not applied to subscribe-tools. |
| **Root cause (HIGH confidence — service code path)** | `watchlist_service.subscribe_watchlist` / `digest_service.subscribe_digest` perform a plain INSERT without ON CONFLICT semantics and without a pre-flight existence check by `(user_id, name)` or `(user_id, params-hash)`. The corresponding table schemas likely lack a UNIQUE constraint on the natural key. |
| **F4-B Core relationship** | **NOT a F4-B regression.** F4-B Core landed workspace scoping for read tools — did not touch subscribe-tools surface. Subscriptions remain channel-scoped (see [ENH-9 in 02-enhancements.md](mcp_testing/2026-05-15_claude_session/02-enhancements.md) — workspace-bound subscriptions are a Wave 1 step 3.1 enhancement, not a regression of F4-B). |
| **Why CI didn't catch** | Tests for `subscribe_*` cover single-call success paths and unsubscribe paths; no test asserts the re-run-with-same-args behaviour. **Closure plan**: contract test asserting that `subscribe_watchlist(args)` followed by `subscribe_watchlist(args)` (same args) returns the same UUID + `created: false` on the second call. |
| **Proposed fix** | Upsert-by-`(user_id, name)` semantics per **ADR 0009** (idempotency policy ADR — to be drafted in Wave 1 step 3 planning per parent decision Q4). Implementation: pre-flight `find_by_user_and_name` → if exists, update mutable fields (description / keywords / threshold) and return existing UUID with `created: false`; if not, INSERT. Optional Alembic migration for UNIQUE constraint as defense-in-depth. Land alongside P-1 / P-2 surface refactor in Wave 1 step 3. |
| **Workaround (current, in-place)** | Before re-running a subscription script, call `list_watchlists()` / `list_digests()` and `unsubscribe_*` on duplicates by UUID. Documented in [operational-runbook § 8 «⚠️ Подписки НЕ идемпотентны»](mcp_testing/2026-05-15_claude_session/04-operational-runbook.md). |
| **Linked** | ENH-9 (workspace-bound subscriptions — same service surface, natural to fix together in Wave 1 step 3.1); O-7 in `02-enhancements.md` (architectural observation — inconsistent idempotency between `add_workspace_source` and `subscribe_*`); P-1 / P-2 in [`PARITY_DECISION_TRACKING.md` § 1](PARITY_DECISION_TRACKING.md) (HTTP API parity for F11/F6 — should be implemented idempotent-by-default) |
| **Planned fix** | TD-subscribe-idempotency (per ADR 0009); fix planned for Wave 1 step 3 sprint alongside P-1 / P-2. |

---

### BUG-023 — Silent topic-quality rejection — no name / reason / aggregate count logged

| Поле | Значение |
|---|---|
| **Severity** | Low (observability: per-topic rejection event is logged as `Topic failed quality criteria, skipping` with no detail — no topic title, no specific criterion, no aggregate count at end of run; operators cannot understand why coverage is below expectation for a given channel, cannot calibrate quality threshold, cannot reproduce «lost» topic candidates from logs alone) |
| **Status** | ✅ **`resolved`** (S2 quick-wins fix landed 2026-05-21 — see «Update 2026-05-21» closure row below) |
| **Component** | `tg_parser/processing/topicization.py` (the quality-filter code path that emits the rejection log line — currently `logger.info("Topic failed quality criteria, skipping")` or equivalent with no structured fields); `tg_parser/services/topicization_service.py` (aggregate counter is absent); CLI `topicize` handler (end-of-run summary missing rejection breakdown) |
| **Discovered** | 2026-05-15 — Claude (Anthropic) MCP testing session, Phase 8 mass incremental topicization 2026-05-14; observed on `AgeManagment` (6 rejections per run), `labdiagnostica_logical` (1), `genotek` (1) — all without per-event context, no aggregate at end of run |
| **Symptoms** | During `tg-parser topicize --channel <X> --mode incremental` for several channels, log emits the literal string `{"event": "Topic failed quality criteria, skipping"}` — sometimes multiple times per run. The log line has zero context: no proposed topic title, no specific criterion that failed (`min_items_too_low`? `duplicate_title`? `toxicity_score`? unclear from logs), no raw LLM proposal that triggered the filter. End-of-run summary contains aggregates for `topics_created` and `documents_assigned` but no `topics_rejected` or breakdown by reason. |
| **Root cause (HIGH confidence — log-emit code path)** | The quality-filter block in `topicization.py` emits an unstructured log with no fields. Aggregate counts are not tracked in `TopicizationResult` (it currently exposes `topic_cards`, `coverage`, `tokens_in`, etc., but no `rejected_count` or `rejection_breakdown`). The data needed for both improvements is **available locally** in the filter block — it just isn't propagated outward. |
| **F4-B Core relationship** | **NOT a F4-B regression.** Pre-existing topicization-pipeline observability gap. |
| **Why CI didn't catch** | Topicization-pipeline tests use mock LLM responses that always pass the quality filter (or always fail in a deterministic way that doesn't exercise the per-criterion classification). **Closure plan**: unit test with mock LLM proposing a topic that fails `min_items` criterion → assert log line contains `reason=min_items_too_low`, `title=<proposed title>`, `items=<count>`. |
| **Proposed fix** | (1) Add structured fields to the per-event log: `{"event": "Topic failed quality criteria", "reason": "<criterion_name>", "title": "<proposed title>", "items": <int>}`; (2) Track aggregate counter in `TopicizationResult.rejection_breakdown: dict[str, int]`; (3) End-of-run summary line: `Quality filter rejected X topics: 4 by min_items, 2 by duplicate_title, 1 by toxicity` (or equivalent). ~30 LOC + 2-3 tests. **Quick win** — bundle with BUG-017 / BUG-018 in a small quick-wins PR per HANDOFF updated sequence step #3. |
| **Workaround (current, in-place)** | None — operators noting low coverage for a channel must run with manual debug logging enabled (no flag exists yet) or accept the opacity. |
| **Linked** | BUG-017 (Phase 4-5 observability class — bundle in same quick-wins PR); BUG-018 (topicize false-success — adjacent observability class); A4 anomaly in [`05-data-quality-report.md`](mcp_testing/2026-05-15_claude_session/05-data-quality-report.md) (data-quality observation that motivated this bug filing) |
| **Planned fix** | TD-topicize-quality-filter-observability; quick-win batch (per parent decision Q6). |
| **Update 2026-05-21 — S2 quick-wins fix on branch `fix/quick-wins-018-017-023-2026-05-21` (local SHA `8e69ed1` — PR #87 SHA `2e9213c`)** | ✅ **Resolved.** `tg_parser/processing/topicization.py` quality-filter refactored: `_validate_quality` now returns `(valid, reason)` tuple with six discrete reasons (`singleton_no_anchors` / `singleton_score_below_min` / `singleton_doc_not_found` / `singleton_text_too_short` / `cluster_too_few_anchors` / `cluster_anchor_score_below_min`); `_build_topic_card` calls new `_record_rejection` helper for every rejection path including early `no_raw_anchors` / `no_valid_anchors_after_parsing` — emits structured `topic_failed_quality_criteria` event with `reason` / `title` (truncated to 80 chars) / `items` fields, and increments `self.rejection_breakdown[reason]`. `__init__` initialises `rejection_breakdown: dict[str, int] = {}`; `topicize_channel` resets it per invocation. `run_topicization` surfaces `rejection_breakdown` in its stats dict (full path); new `IncrementalTopicizeResult.rejection_breakdown` field surfaces it on the incremental path (populated from the Phase 2 LLM-discover pipeline instance). CLI `_run_full_topicization` and `_print_incremental_stats` share a new `_print_rejection_breakdown` helper emitting «Quality filter rejected X topics: 4 by cluster_too_few_anchors, 2 by …» when non-empty. **Tests**: `tests/test_bug023_topic_rejection.py` — 11 cases (validate-quality returns the seven (valid, reason) tuples, `_record_rejection` increments aggregate, `_build_topic_card` emits structured event + legacy line gone, `no_raw_anchors` early-rejection counted, `rejection_breakdown` resets between `topicize_channel` runs). |

---

> **Перенесена из § Active bugs 2026-05-20** (M-15 docs hygiene sprint; joint fix-sprint PR #79 `5465918`).

### BUG-024 — Scheduler `last_attempt_at` invariant not enforced synchronously (close-time failure rolls back the write)

| Поле | Значение |
|---|---|
| **Severity** | Medium (low direct user-visible impact — affects observability, not data correctness — but HIGH indirect impact: `health_check` and stuck-source queries cannot distinguish «stuck active source» from «newly added active source not yet ticked» because both look like `last_attempt_at IS NULL`; correlates with BUG-013 close-time failure rate (~77 % of ticks in the watch window) — joint-fix candidate per parent decision Q1) |
| **Status** | ✅ **`resolved`** (Joint fix-sprint landed 2026-05-15 — see «Update 2026-05-15» closure row below) |
| **Component** | `tg_parser/services/scheduler_service.py` (`_process_source` — `state_repo.update_attempt_at` likely called inside the per-task `try/finally`); `tg_parser/services/pipeline_service.py` (downstream attempt-tracking writes); `tg_parser/persistence/sources.py` (the underlying `update_attempt_at` repo method, possibly missing synchronous-commit semantics) |
| **Discovered** | 2026-05-15 — Claude (Anthropic) MCP testing session, Phase 3 investigation 2026-05-14 06:28-06:30 UTC; reproduced via `get_pipeline_status(channel="profendocrinologist")` immediately after the channel was successfully processed by the scheduler tick → response showed `last_success_at: "2026-05-14T06:30:47"` (correct) BUT `last_attempt_at: null` (impossible — success implies attempt) |
| **Symptoms (session trace, 2026-05-14 06:30 UTC)** | `get_pipeline_status(channel_id="profendocrinologist")` returns `{"last_attempt_at": null, "last_success_at": "2026-05-14T06:30:47", "fail_count": 0, "last_error": null}`. The `last_success_at` value is correct (matches the visible scheduler-completion log line), but `last_attempt_at` should at minimum equal that value (or earlier) — being `null` indicates the attempt-tracking write was never committed. Cross-fires with BUG-013 in the same tick (BUG-013's `IllegalStateChangeError` on session close rolls back any pending per-task writes that were not yet committed). |
| **Root cause (HIGH confidence — code-walk hypothesis pending fix-sprint confirmation)** | The expected invariant is: «for any source the scheduler attempts to process, `last_attempt_at = now()` is committed BEFORE the first `await` of the actual processing». Current behaviour writes `last_attempt_at` in the per-task `finally` block, which can be (a) skipped if the task is cancelled, or (b) rolled back when the outer `AsyncSession` close fails (BUG-013 mechanism — same session-sharing concurrency issue). Either failure mode produces the observed `null` value. |
| **F4-B Core relationship** | **NOT a F4-B regression.** Same `scheduler_service.py:_process_source` code path as BUG-013 / BUG-014 — unchanged across F4-B Core landing. F4-B Core 24h watch surfaced BUG-013 / BUG-014 but not this third symptom (because `last_attempt_at: null` is silent unless an external observer queries `get_pipeline_status` and notices the impossibility — which the testing session did). |
| **Why CI didn't catch** | No integration test asserts the invariant «after `_process_source` runs to completion (success or failure), `last_attempt_at` is non-null and ≤ `last_success_at` (if success path)». Closure plan tracks alongside BUG-013 fix-sprint. **Closure plan**: integration test via `pytest-asyncio` + testcontainers Postgres running `run_incremental_for_all_sources` with ≥ 1 source → assert `last_attempt_at IS NOT NULL` after completion; companion negative test asserts `last_attempt_at IS NOT NULL` even on per-task simulated failure. |
| **Proposed fix** | Write `state_repo.update_attempt_at(source_id, now())` **synchronously and committed** before any pipeline `await` in `_process_source` (rather than in the per-task `finally`). Once BUG-013 is fixed (per-task sessions — see BUG-013 § Proposed fix), the synchronous write becomes naturally safe because each task owns its own session. Adds ~10 LOC + 1 invariant integration test. **Joint-fix with BUG-013 + BUG-014 in upcoming fix-sprint per parent decision Q1** — the three bugs share a single code surface and the fixes compose. |
| **Workaround (current, in-place)** | When triaging stuck sources, do **NOT** rely on `last_attempt_at IS NULL` as a «source never attempted» signal — cross-check with `last_success_at` (if non-null, the source was attempted successfully despite the null), and with `tg_parser_scheduler_tasks_total{task_name="incremental_pipeline"}` Prometheus counter. ENH-3 (health-check for stuck active sources, see [02-enhancements.md](mcp_testing/2026-05-15_claude_session/02-enhancements.md)) will close this UX gap. |
| **Linked** | BUG-013 (sibling pre-existing scheduler bug — co-fires in same ticks, joint-fix sprint per parent decision Q1); BUG-014 (sibling pre-existing scheduler bug — same joint-fix sprint); ENH-3 (downstream UX improvement for stuck-source detection — see [02-enhancements.md](mcp_testing/2026-05-15_claude_session/02-enhancements.md)); [`HANDOFF_POST_WAVE1_STEP2_2026-05-15.md`](HANDOFF_POST_WAVE1_STEP2_2026-05-15.md) § 6 #2 (scheduler fix-sprint sequence anchor) |
| **Planned fix** | TD-scheduler-attempt-at-synchronous-commit (filed as [#78](https://github.com/AlexEfimov/TG_parser/issues/78) alongside BUG-013 [#76](https://github.com/AlexEfimov/TG_parser/issues/76) + BUG-014 [#77](https://github.com/AlexEfimov/TG_parser/issues/77) at start of joint fix-sprint); fix planned for the same sprint as BUG-013 / BUG-014 per parent decision Q1 + [HANDOFF § Pending #2](HANDOFF_POST_WAVE1_STEP2_2026-05-15.md) + planning artifact [`START_PROMPT_FIX_BUG013_SCHEDULER_SESSION_2026-05-15.md`](START_PROMPT_FIX_BUG013_SCHEDULER_SESSION_2026-05-15.md). |
| **Update 2026-05-15 — Joint fix-sprint landed via PR [#79](https://github.com/AlexEfimov/TG_parser/pull/79) (SHA `5465918`)** | ✅ **Invariant restored via synchronous pre-await write.** New `IngestionStateRepo.mark_attempt_started(source_id)` abstract method (port: `tg_parser/storage/ports.py`; SQLAlchemy impl: `tg_parser/storage/sqlalchemy/ingestion_state_repo.py`) commits `UPDATE sources SET last_attempt_at = now(), updated_at = now()` with its own `await self.session.commit()` — idempotent / monotonically advancing. Scheduler `_process_source` now calls `await task_state_repo.mark_attempt_started(source_id)` immediately after the rate-limit early-return + "Processing source" log, **before** the first pipeline `await`. After the BUG-013 per-task session fix the commit cannot race siblings (each task owns its session). The redundant `record_attempt` write in `finally` continues to refresh the value (later timestamp; monotonic). **Tests**: `test_bug024_mark_attempt_started_called_before_pipeline_await` (T-4 — asserts `mark_attempt_started` is awaited BEFORE `run_ingestion` using ordered side-effects) and `test_bug024_mark_attempt_started_skipped_for_rate_limited_source` (T-5 — guards the early-return path: rate-limited sources MUST NOT get the attempt-at write). **Closes [#78](https://github.com/AlexEfimov/TG_parser/issues/78)**. |

---

> **Перенесена из § Active bugs 2026-05-20** (M-15 docs hygiene sprint; PR #84 `39da8cc`, 24h watch GREEN per [`REVIEW_2026-05-20_BUG014B_DONE.md`](REVIEW_2026-05-20_BUG014B_DONE.md)).

### BUG-014B — Orchestrator `ingest_source` compares offset-naive `source.rate_limit_until` against `datetime.now(UTC)` → `TypeError` at `orchestrator.py:110` (second site, missed by BUG-014 scheduler-side fix)

| Поле | Значение |
|---|---|
| **Severity** | **High** (data correctness: 2 active production sources — `kdl_ru`, `profendocrinologist` — are in a permanent fail-loop, accumulating `fail_count ≥ 29` over the 24h BUG-013/14/24 watch window with zero successful `last_success_at` since the rate-limit row was first persisted. ~56 `TypeError` log lines / day in `tg_parser` container. `last_attempt_at` does advance (BUG-024 fix works on the failure path), so the failure is observable, but the affected sources never re-ingest until manual operator intervention clears `sources.rate_limit_until` to NULL.) |
| **Status** | ✅ **`resolved`** (storage-boundary fix landed 2026-05-18 — see «Update 2026-05-18» closure row below) |
| **Component** | [`tg_parser/ingestion/orchestrator.py`](../../tg_parser/ingestion/orchestrator.py) line 110 — `if source.rate_limit_until and source.rate_limit_until > datetime.now(UTC):`; left operand `source.rate_limit_until` is read from DB as **offset-naive** `datetime` because [`tg_parser/storage/sqlalchemy/ingestion_state_repo.py`](../../tg_parser/storage/sqlalchemy/ingestion_state_repo.py) `_row_to_source` (line 412) parses it via `parse_iso_datetime` ([`tg_parser/domain/json_utils.py`](../../tg_parser/domain/json_utils.py) line 80) which **strips the `Z` suffix and returns naive datetime by design**. Right operand `datetime.now(UTC)` is tz-aware. Also fires at lines 111 (`source.rate_limit_until - datetime.now(UTC)`) and 115/120/493 (`isoformat()` on the naive value — these don't TypeError but propagate the naive value into log lines / RetryableError messages). |
| **Discovered** | 2026-05-15T20:55Z — AMBER MCP probe of joint BUG-013/14/24 fix (PR #79). Reconfirmed 2026-05-16T19:45Z closure probe and documented as the «known partial» of that sprint in [`REVIEW_2026-05-16_BUG013_14_24_DONE.md` § 4.2](REVIEW_2026-05-16_BUG013_14_24_DONE.md). Originally analysed in [`docs/notes/mcp_testing/2026-05-16_claude_session/analysis_and_options.md`](mcp_testing/2026-05-16_claude_session/analysis_and_options.md) (5-option fix matrix, Option B = storage-boundary coerce, recommended). |
| **Symptoms (production trace, watch window 2026-05-15T15:01:20Z → 2026-05-16T15:01:20Z + ~4.7h post-close)** | `kdl_ru` + `profendocrinologist`: `last_attempt_at` advances every tick (BUG-024 invariant holds), `last_success_at = null`, `fail_count = 29` per source after 28 ticks (one fail/source/tick — 28×2=56 tracebacks per `docker compose logs tg_parser --since 28h`), `last_error = "can't compare offset-naive and offset-aware datetimes"`. Traceback originates exclusively at `orchestrator.py:110` and bubbles up via `pipeline_service.py:115` → `ingestion_service.py:64` → caught by PR #79's per-task `try/except` in `scheduler_service.py:201` `_process_source`. The 7 healthy sources advance both `last_attempt_at` and `last_success_at` cleanly — failure is fully isolated. |
| **Root cause (HIGH confidence — code-walk verified)** | `_row_to_source._row_to_source(row)` parses every datetime column through `parse_iso_datetime` which is **documented to return naive UTC** (`tg_parser/domain/json_utils.py` line 80-94: `«datetime object (naive UTC)»`, `s.endswith("Z") → s = s[:-1]; return datetime.fromisoformat(s)`). Write-path roundtrip is symmetric and lossy: `_format_datetime` (line 455-459) does `dt.strftime("%Y-%m-%dT%H:%M:%SZ")` — strips tzinfo on write, restoring «Z» as a literal suffix. So a `Source` built from DB always has naive datetimes regardless of whether the original code constructed `rate_limit_until` as tz-aware (line 486: `datetime.now(UTC) + timedelta(...)` is aware on write → naive on read). BUG-014 scheduler-side fix added `_coerce_aware_utc` at `scheduler_service.py:142` which patches the naive value at one call-site only — orchestrator-side `orchestrator.py:110` was not audited as a separate consumer of `source.rate_limit_until` during the joint sprint (per [`START_PROMPT_FIX_BUG013_SCHEDULER_SESSION_2026-05-15.md` § 3.2 «scheduler is the only place...» — assumption proved incomplete by AMBER probe](START_PROMPT_FIX_BUG013_SCHEDULER_SESSION_2026-05-15.md)). |
| **F4-B Core relationship** | **NOT a F4-B regression.** Orchestrator-side bare comparison at `orchestrator.py:110` predates F4-B Core by several months (`git log -- tg_parser/ingestion/orchestrator.py` shows last touch unrelated to datetime handling). The bug was **structurally present but unreachable** before PR #79: pre-PR-#79, the scheduler-side BUG-014 TypeError at `scheduler_service.py:89` aborted the tick before any code could reach `orchestrator.ingest_source(...)`. After PR #79 closed scheduler-side BUG-014, the orchestrator-side site became newly reachable — surfaced by the post-deploy AMBER probe. Classic «fix one bug, expose its sibling» pattern (also: same dynamic landed BUG-015 visible after PR #81 closed BUG-016). |
| **Why CI didn't catch** | (a) No existing integration test runs `orchestrator.ingest_source(...)` against a `Source` with non-null naive `rate_limit_until` that's in the future. The 19 existing scheduler tests + 6 new tests added in PR #79 (`tests/test_scheduler_service.py`) all mock at the **scheduler layer** — `_process_source` is exercised but `orchestrator.ingest_source` is mocked away (`AsyncMock`). (b) No DB-roundtrip integration test for `_row_to_source.rate_limit_until.tzinfo` invariant — `tests/test_ingestion_state_repo.py` (if extant) covers persistence shape but not tzinfo. (c) BUG-014 closure test (`test_bug014_naive_rate_limit_until_does_not_crash`) only asserts scheduler behaviour on the naive-input → no traversal into orchestrator. **Closure plan**: unit test on `_row_to_source` asserting `Source.rate_limit_until.tzinfo is not None` for non-null naive DB values; orchestrator-layer regression test mirroring T-3 from PR #79 but for `orchestrator.ingest_source`. |
| **Proposed fix (Option B per analysis)** | **Storage-boundary coerce in `_row_to_source`**: wrap the existing `parse_iso_datetime(row.rate_limit_until)` call at line 445-447 with a tz-aware-UTC coerce. Recommended implementation: promote the existing `_coerce_aware_utc` helper from `scheduler_service.py:26` to `tg_parser/domain/json_utils.py` (colocated with `parse_iso_datetime` — symmetric naming pair), then import + apply at the `_row_to_source` line 445-447 site. Scheduler-side `_coerce_aware_utc` becomes a no-op identity but remains as belt-and-suspenders defense (documented comment + retain test). Optional broader scope: apply the coerce to **all** datetime fields in `_row_to_source` (`history_from`, `history_to`, `backfill_completed_at`, `last_attempt_at`, `last_success_at`, `created_at`, `updated_at`) to make `Source` an aware-datetime entity throughout the codebase — narrow rate_limit_until-only fix closes the specific bug; broader fix prevents future BUG-014C/D/E... at zero additional risk. **Decision pending § 8 user OK** in planning artifact. ~5-25 LOC depending on scope. Alternative options considered + rejected: A (mole-whack at `orchestrator.py:110`) — fails the open-ended «who else reads this naive value?» problem; C (parse-time fix in `parse_iso_datetime`) — large blast radius across the codebase; D (DB column → TIMESTAMPTZ migration) — ADR-grade decision; E (B + symmetric write-side fix in `_format_datetime`) — write-side already aware-tolerant, fix unnecessary. See [`analysis_and_options.md`](mcp_testing/2026-05-16_claude_session/analysis_and_options.md) § 5 for the full matrix. |
| **Workaround (current, in-place)** | Operator clears `sources.rate_limit_until` to `NULL` for affected sources: `UPDATE sources SET rate_limit_until = NULL, fail_count = 0, last_error = NULL WHERE source_id IN ('kdl_ru', 'profendocrinologist');` then containers/scheduler resume normal ingestion until either `_maybe_set_rate_limit` fires again (which puts the source back into the same fail-loop) or the fix lands. **Operator note**: do NOT clear `rate_limit_until` proactively if there's reason to believe the source genuinely has a Telegram FloodWait pending — but in the current state, the loop is **structural** (every tick) so the rate-limit signal is purely an artefact of one prior FloodWait that the scheduler can never re-attempt. |
| **Linked** | BUG-014 (✅ resolved — sibling scheduler-side fix; BUG-014B is the orchestrator-side mirror); BUG-013 / BUG-024 (✅ resolved — joint fix-sprint that surfaced this second site post-deploy); [`REVIEW_2026-05-16_BUG013_14_24_DONE.md` § 4.2](REVIEW_2026-05-16_BUG013_14_24_DONE.md) (known-partial classification); [`docs/notes/mcp_testing/2026-05-16_claude_session/analysis_and_options.md`](mcp_testing/2026-05-16_claude_session/analysis_and_options.md) (5-option matrix + Option B recommendation); AMBER MCP probe 2026-05-15T20:55Z + closure probe 2026-05-16T19:45Z (evidence). |
| **Planned fix** | TD-orchestrator-rate-limit-tz-aware (will be filed as GH issue at sprint kickoff — see § 8); fix planned per `docs/notes/START_PROMPT_FIX_BUG014B_STORAGE_BOUNDARY_2026-05-18.md` (Option B storage-boundary coerce, single-file scope `tg_parser/storage/sqlalchemy/ingestion_state_repo.py` + optional shared helper in `tg_parser/domain/json_utils.py`). |
| **Update 2026-05-18 — Storage-boundary fix landed (BUG-014B sprint)** | ✅ **Option B landed.** Promoted `coerce_aware_utc` to `tg_parser/domain/json_utils.py` (was `scheduler_service._coerce_aware_utc`). `SAIngestionStateRepo._row_to_source` wraps all 8 naive datetime fields (`history_from`, `history_to`, `backfill_completed_at`, `last_attempt_at`, `last_success_at`, `rate_limit_until`, `created_at`, `updated_at`) with `coerce_aware_utc(parse_iso_datetime(...))` so `Source` instances are tz-aware on read; orchestrator `ingest_source` comparison at line 110 succeeds without modification. Scheduler-side `coerce_aware_utc` retained as belt-and-suspenders (PR #79 T-3 unchanged). **Tests**: `tests/test_json_utils.py::TestCoerceAwareUtc` (T-0); `tests/test_ingestion_state_repo_datetime_coerce.py` (T-1 parametrised × 8, T-2 null guard); `tests/test_orchestrator_rate_limit.py` (T-3). **Closes [#83](https://github.com/AlexEfimov/TG_parser/issues/83)**; deploy `39da8cc` 2026-05-18T20:08:08Z. |
| **Update 2026-05-20 — 24h post-deploy watch GREEN (8/8)** | ✅ Production verdict per [`REVIEW_2026-05-20_BUG014B_DONE.md`](REVIEW_2026-05-20_BUG014B_DONE.md): `TypeError.*offset` **0** over 24h+; `kdl_ru` + `profendocrinologist` `last_success_at` non-null, `fail_count=0`; **38/38** ticks `succeeded=9, failed=0`. BUG-014B functionally closed. |

#### Reproduction trace (production, 2026-05-15T16:02:04.701906Z — first post-PR-#79 fire on `profendocrinologist`)

```
Traceback (most recent call last):
  File "/root/.local/lib/python3.12/site-packages/tg_parser/services/scheduler_service.py",
       line 201, in _process_source
    stats = await run_full_pipeline(
  File "/root/.local/lib/python3.12/site-packages/tg_parser/services/pipeline_service.py",
       line 115, in run_full_pipeline
    ingest_stats = await run_ingestion(
  File "/root/.local/lib/python3.12/site-packages/tg_parser/services/ingestion_service.py",
       line 64, in run_ingestion
    stats = await orchestrator.ingest_source(
  File "/root/.local/lib/python3.12/site-packages/tg_parser/ingestion/orchestrator.py",
       line 110, in ingest_source
    if source.rate_limit_until and source.rate_limit_until > datetime.now(UTC):
TypeError: can't compare offset-naive and offset-aware datetimes
```

(Identical trace fired 56 times across the 28h watch+scan span — 28 ticks × 2 affected sources; PR #79's per-task `try/except` correctly isolates the failure to the 2 sources without crashing the gather or sibling tasks.)

---

---

## Scheduler fix-sprint — resolved batch (M-15 hygiene 2026-05-20)

Перенос из § Active bugs после GREEN 24h post-deploy watches. См. [`REVIEW_2026-05-16_BUG013_14_24_DONE.md`](REVIEW_2026-05-16_BUG013_14_24_DONE.md) и [`REVIEW_2026-05-20_BUG014B_DONE.md`](REVIEW_2026-05-20_BUG014B_DONE.md).


## Mapping в fix-сессии

Когда планируется fix-сессия, в её start-prompt'е (`START_PROMPT_SPRINT_*.md`)
явно перечисляются ID багов из этого журнала, и после merge'а они переезжают
в § «Resolved bugs» с указанием PR/commit'а. Это даёт двустороннюю
прослеживаемость bug ↔ fix без необходимости поднимать issue tracker.
