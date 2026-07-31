# START PROMPT — Session: bot — заменить prose-детектор BUG-086 детерминированным affirmative-token триггером ([#359](https://github.com/AlexEfimov/TG_parser/issues/359))

> ## ✅ LANDED (2026-07-31) — план исполнен целиком; смержено и задеплоено на прод
>
> Все 10 шагов §1 выполнены; слои (c) и (d) удалены, prose-детектор в дереве отсутствует. Регистр итогов:
>
> - **Механизм:** `AgentResult.write_intent_pending` → `pending_write_intent` (snapshot, args санитизированы в момент записи) → pop в начале `handle_text` → `_handle_write_intent_router` (tier-1 only) → настоящий preview → `ConfirmFlow`. `PendingWriteIntentData` в [`states.py`](../../tg_parser/bot/states.py).
> - **Удалено:** `_recover_llm_authored_confirm`, `_looks_like_llm_authored_confirm`, `_looks_like_read_only_request`, пять регулярок, весь shadow-слой (d) с тремя `llm_authored_confirm_*` и `read_only_intent`.
> - **Observability:** `write_intent_set` / `_router_resume` / `_router_failed` / `_router_execute_failed` / `_declined` / `_dropped` (+ `reason`), плюс `fsm_confirm_declined` (закрывает отдельный GAP §3).
> - **Prompt:** [`bot.yaml`](../../prompts/bot.yaml) 1.9.3 → **1.9.4** (L2 / L8 / L9 / L32).
> - **Тесты:** новый файл [`test_bot_write_intent_trigger_359.py`](../../tests/test_bot_write_intent_trigger_359.py) (58 тестов), переписаны `TestPreviewLessWriteCallIsSnapshotted` (F5-C) и `TestWriteIntentResumeIsToolAgnostic` ([`test_bot_confirm_flow.py`](../../tests/test_bot_confirm_flow.py)).
> - **Ops-gate (PR standard, Postgres up):** **4098 passed / 22 skipped / 2 deselected**, ruff check + format чистые. Baseline `19e312a` был 4052 passed — дельта **+46** (оценка §3.9 «−17 / +12-15» относилась к числу тест-функций, не к собранным кейсам: новые классы параметризованы корпусом прозы).
> - **Mutation-верификация: 17/17 мутаций убиты** — 12 строк §3.9 плюс пять, добавленных за три раунда ревью (см. находки 1, 4, 6, 7, 8 ниже). Harness сохранён — [`scripts/mutation_verify_359.py`](../../scripts/mutation_verify_359.py) (blast radius = 42 модуля, импортирующих bot-адаптер). Три строки роняют больше заявленного, каждая законно — расшифровка в `BUG_LOG.md` § BUG-086, строка «Architectural replacement».
>
> **Self-review (2026-07-31, после исполнения плана) — три находки, все исправлены:**
> 1. **Дыра в adjacency: pop стоял НИЖЕ guard'а на пустой текст.** `@router.message(F.text)` пропускает сообщение из одних пробелов; `handle_text` выходил на `not user_text.strip()`, не дойдя ни до одного роутера, и snapshot **переживал** это сообщение — ровно тот «FP, перенесённый во время», против которого написан §10 R2-B1. Pop перенесён **выше** guard'а; пин — `TestWriteIntentSurvivesNoTurn::test_whitespace_only_message_drops_it`, mutation-верифицирован (обратный порядок роняет ровно его).
> 2. **Мёртвый код: `_clear_write_intent`** — создан по шагу 4, но шаг 6 сделал clear-сайты ненужными, вызовов не было ни одного. Удалён (прецедент рядом — тоже неиспользуемый `_clear_delete_intent`; повторять его не стал).
> 3. **Docs расходились с кодом по `reason`:** runbook и BUG_LOG писали `stale`, код пишет `ttl` (канон — §3.6). Исправлены docs, не код.
>
> **Bugbot-ревью (2026-07-31) — три находки; одна исправлена, две отклонены с обоснованием:**
> 4. **✅ Исправлено — resume вооружал `ConfirmFlow`, не сбрасывая `subscribe_intent`.** Штатные arm-сайты (`L829` agent-preview, `L849` clarify) сбрасывают его по BUG-050, наш роутер — нет. Дефект достижим: один turn может выставить **оба** детектора (set-site это допускает намеренно), а confirm-execute на `L1029-1030` **явно восстанавливает** `subscribe_intent` для любого не-subscribe tool'а ⇒ просроченный intent переживал весь двойной confirm и уводил последующее голое имя канала в неожиданный subscribe. Добавлен `_clear_subscribe_intent` перед армингом + пин `test_resume_clears_a_coexisting_subscribe_intent`, mutation-верифицирован.
> 5. **⚠️ Отклонено частично — «снапшот хранит сырой `identifier` для `add_user_auth` в FSM».** Обоснование Bugbot содержит ошибку: старый recovery возвращал `preview_pending`, который обработчик писал в `pending_action` (`L831-834`), т.е. сырой секрет попадал в FSM и до слайса — и попадает на **любом** штатном preview-turn'е `add_user_auth`. Хранилище при этом внутрипроцессное (`MemoryStorage`, `bot/main.py:244`), TTL 5 мин ⇒ это RAM, не диск. Свойство confirm-протокола, не регрессия. Верна узкая часть: снапшот **расширяет** множество turn'ов, на которых args персистятся (теперь каждый preview-less write-вызов). Убрать args нельзя — они нужны для переиздания. Кандидат на отдельный slice: шифровать/не хранить значения секретных ключей в FSM для всего confirm-протокола сразу. **Разбор этой находки вскрыл существенно бо́льшую и более старую экспозицию, которую ревью не заметило:** `agent_tool_call` (`agent.py`) логирует `args` любого вызова целиком на уровне INFO, без какой-либо редакции — единственные два редактора в кодовой базе (`_redacted_key_prefix`, `_mask_password`) живут в API и storage и на этот путь не приходят. То есть сырой credential пишется в лог-пайплайн при каждом `add_user_auth` — уже диск, а не RAM. Слайса не касается (предшествует ему), заведено отдельно как **BUG-087**.
> 6. **✅ Исправлено (round-3) — «выход по исчерпанию итераций не заполняет `write_intent_pending`»** (`agent.py` L551). Изначально отклонено как паритет — старый guard тоже жил только в text-only ветке, так что регрессии не было. При повторном разборе паритет оказался недостаточным основанием: тот же самый `return` **прокидывает `preview_pending`**, то есть fallback уже допускает вооружение confirm'а после «не удалось получить окончательный ответ», и два выхода одной функции просто расходились. Пользователь после preview-less write-вызова получал «переформулируйте» — ровно тот dead-end, ради которого слайс и делался. Оба выхода теперь идут через общий хелпер `_write_intent_or_none`, так что разойтись снова не могут; пин `test_turn_limit_exhaustion_still_hands_over_the_snapshot`, mutation-верифицирован. Достижимость низкая (нужны все 5 витков с tool-call'ами), риск нулевой — preview ничего не мутирует и требует второго «да».
>
> **Второй проход self-review (2026-07-31) — одна находка, исправлена:**
> 7. **✅ Исправлено — resume не вёл `last_subscription` для `unsubscribe_*`.** Тот же класс, что находка 4, вскрыт построчной сверкой моего arm-сайта с каноническим (`L826-844`): из пяти его действий у меня не хватало ровно одного — `_last_subscription_from_preview` (BUG-047 B-2). Достижимо через BUG-009-rejection `unsubscribe_digest(confirm=true)`: resume вооружал preview по id, но цель не запоминалась, поэтому позднейшая анафора «удали эту подписку» (например, после отказа на этом же confirm'е) не резолвилась. Добавлено + пин `test_resume_of_an_unsubscribe_records_last_subscription`, mutation-верифицирован. **Теперь arm-сайты эквивалентны по всем пяти действиям.**
> 8. **✅ Исправлено (Bugbot, второй прогон) — пунктуированный голый токен отбрасывался.** «да.» / «нет!» не совпадали с whitelist'ом целиком ⇒ `write_intent_dropped(reason=unrelated)` и падение к агенту, хотя на ConfirmFlow-turn'е тот же ответ принимается. Это ровно тот dead-end, который слайс закрывает, — и обоснование §3.2 против tier-2 сюда **не относится**: опасен в компаунде текст ПОСЛЕ разделителя, а у «да.» его нет. Снимается только **хвостовая** пунктуация (`,.;:!?`); ни один токен обоих словарей пунктуации не содержит, компаунды по-прежнему `unknown`. Пин `test_trailing_punctuation_does_not_make_a_token_unrelated`, mutation-верифицирован. Формулировка ADR-0020 §2 («точное совпадение целиком») была после этого **неточна** — уточнена там же.
> 9. **Уточнена точность privacy-пина:** тест использовал выдуманное имя аргумента `credential`, тогда как реальный секрет `add_user_auth` лежит в `identifier` (именно он идёт в `hash_credential`). Переписан на настоящие имена. Отдельно проверено и оказалось чисто: ни один executor не подставляет секрет в `error`, который роутер пишет в `write_intent_router_failed`.
>
> **Остаточное ограничение, зафиксировано честно (не исправлялось — выходит за рамки slice'а).** Формулировка «snapshot не может пережить сообщение **любым** путём» верна только для сообщений, попадающих в `handle_text`. Мимо него идут `/start` и `/help` (отдельные хендлеры выше по регистрации) и любое НЕтекстовое сообщение (стикер / фото — под `F.text` не подпадают, ни один хендлер их не берёт). На этих путях adjacency держится только TTL (5 мин). Худший исход не меняется — один непрошеный **preview**, 0 токенов и 0 записей, который всё равно требует явного второго «да» (§7 ADR-0020). Полное закрытие потребовало бы pop'а в middleware; если это нужно как гарантия, стоит либо добавить middleware, либо ослабить формулировку в ADR-0020 §3 до «любым путём `handle_text`».
>
> **Расхождения с планом (2, оба зафиксированы честно):**
> 1. **§3.8 `TestWriteIntentRouterPrecedenceMatrix`, кейс «delete_intent + snapshot ⇒ resume»** — реальный T1-turn для него недостижим: BUG-048-роутер стоит **выше** нашего и для любого текста, проходящего его четыре гейта (`classify_confirmation_token` = unknown, `_looks_like_new_intent` = False, нет delete-verb, нет channel-hint), резолвит имя против БД и отвечает сам — т.е. съедает **сам T1**, и восстанавливать становится нечего. Проверено: для «пере-суммаризируй тему <uuid>» все четыре гейта пропускают. Тест сохранён, но snapshot засевается напрямую — он пинит **наш** контракт, а не чужую резолюцию. Само взаимодействие — предсуществующее поведение BUG-048 (`_looks_like_new_intent` не знает про re-summarize), **вне scope** этого slice'а.
> 2. **Дельта тестов положительная (+46)**, а не «−17 / +12-15» — см. выше.
>
> **~~Не сделано намеренно:~~ ВСЁ ИСЧЕРПАНО** (относилось к моменту завершения имплементационной сессии): ~~ADR-0020 остаётся `Proposed`~~, ~~`git commit` не выполнялся~~, ~~issue #359 не редактировался~~ — issue закрыт автоматически по `Closes #359` в момент мержа (`2026-07-31T17:09:36Z`, reason `COMPLETED`). Детали — строка ниже.
>
> **✅ MERGED + DEPLOYED (2026-07-31)** — строка выше про `Proposed` / отсутствие коммита этим исчерпана. [PR #360](https://github.com/AlexEfimov/TG_parser/pull/360) (коммиты `48aeee7` + `5752bdb`) смержен как `102bb4c`, сверху status-flip `25654fa`: [ADR-0020](../adr/0020-deterministic-confirmation-triggers.md) теперь **Accepted**. CI зелёный, смерженная ветка удалена. Прод обновлён в окне **18:18–18:30 UTC** (20:18–20:30 CEST, ручной VPS-деплой): `9aadf5e → 25654fa` чистым fast-forward'ом (14 файлов, без merge-коммита), **без миграции и без backup'а**, `tg_parser:latest` = `b769dee25f54` (было `5b82aadbf88f`), `tg_parser_bot` пересоздан (BUG-078, НЕ `restart`) и `healthy`; `tg_parser` / `tg_parser_mcp` не тронуты. In-container smoke **на живом коде**: `bot.yaml` `1.9.4`, все пять удалённых символов отсутствуют (атрибуты модуля + recursive grep по `/app/tg_parser/`), новые символы на месте, классификатор даёт ожидаемые вердикты (включая пунктуированные «да.» / «нет!» из находки 8), `len(TOOL_DECLARATIONS)` = 35; 11 мин логов — 0 error/warn/traceback. Событий `write_intent_*` / `fsm_confirm_*` в окне деплоя ноль — трафика ещё не было. **Ручной e2e выполнен** тем же вечером, окно логов **19:28:13 → 19:35:43 UTC** (клиент owner'а показывает UTC+3; таймстемпы лога авторитетны): деградированный двойной confirm прошёл целиком (`write_intent_set` → голое «да» → `write_intent_router_resume` + `fsm_confirm_armed`, обслужено **детерминированно**, без `agent_tool_call` → второе «да» → `fsm_confirm_execute` → «✅ … ok.»), пунктуированное «да.» из находки 8 сработало на живом коде, «нет» дало новое `fsm_confirm_declined` + «❌ Отменено.», постороннее «привет» — `write_intent_dropped` `reason=unrelated` **до** того, как turn дошёл до агента. БД: ровно **+1** версия на цели (`topic:tg:mediamedics:post:1239` v3 → v4, новая md5, 3 history-строки), контроль `topic:tg:AgeManagment:post:977` **бит-в-бит** тот же; `write_intent_router_failed` ×0, `fsm_confirm_execute` ×1. `arg_keys=["topic_id"]` на всех записях — только ключи, значения не логируются. **Второй прогон e2e** (окно **20:00:22 → 20:03:17 UTC**, поднят задним числом через `docker logs --since 2026-07-31T19:58:00Z`, ничего не срезано) закрыл **оба** остававшихся инварианта. Компаунд «да, покажи темы канала Docma_ru» против **живого** снапшота: вооружён `20:00:36.061501Z`, снят `20:01:19.710247Z` — 43.6 с при `PENDING_TTL_SECONDS = 300`, `write_intent_dropped` `reason="unrelated"` за **80 µs** до `user_message`, единственный tool-вызов turn'а — `list_topics`; доказательность даёт именно `reason` — он пишется на одном сайте, стоящем ПОСЛЕ early-exit'а «снапшота нет», который не логирует ничего, поэтому «живой снапшот отвергнут» положительно отличимо от «снапшота не было» (экран Telegram этого не различает — потому первый прогон и был inconclusive). `write_intent_declined` — `20:03:16.773154Z`, ровно один, **без** `user_message` / `agent_tool_call` на turn'е (LLM не привлекался) и **без** арминга ConfirmFlow. Мутация была структурно недостижима: все три арминга шли на несуществующий `topic:tg:mediamedics:post:999999999` (0 строк в `topic_cards` / `topic_card_versions`), а самая свежая строка **во всей** `topic_card_versions` — `2026-07-31 19:30:39.299796+00`, за ~30 мин до открытия окна. ⚠️ Прогон 2 не отправлял голого affirmative ⇒ `write_intent_router_resume` / `fsm_confirm_armed` / `fsm_confirm_execute` — пути прогона 1: **покрытие полное только у двух прогонов вместе**. ⚠️ **И даже вместе они покрывают не «каждый инвариант ADR-0020»** — после них оставалось два прод-нуля, из которых один закрыт. ✅ **Прогон 3** (окно **21:20:36 → 21:31:06 UTC**, поднят через `docker logs --since 2026-07-31T21:18:00Z`) закрыл **fail-closed TTL** (§3, `handlers.py:2051–2058`): снапшот вооружён `21:21:09.591416Z` (`arg_keys=["topic_id"]`, арминг снова на несуществующий `topic:tg:mediamedics:post:999999999`), голое «да» ~10 мин спустя дало ровно одну запись `write_intent_dropped` `reason="ttl"` в `21:31:06.345948Z` — **596.754532 с** при `PENDING_TTL_SECONDS = 300`, на **141 µs** раньше `user_message` того же turn'а, при нулях `write_intent_router_resume` / `fsm_confirm_armed` / `write_intent_router_failed`, и «да» корректно упало к агенту. Форма записи (`tool` / `reason` / `chat_id`, **без** `arg_keys`) отличает сайт `_take_write_intent` от сайта `unrelated`; экран Telegram этого не различает — «Я не совсем понимаю ваш ответ» одинаков и при корректно истёкшем снапшоте, и при не созданном вовсе. Остаётся один ноль: `reason="fsm_armed"` (`handlers.py:688–694`, наблюдаемая форма «взаимное исключение доказуемо») **последовательным** путём недостижим — set-сайт снапшота стоит `elif`-ом ниже всех трёх arm-ветвей, а снапшот поп'ается в начале следующего turn'а, так что вооружить FSM и оставить снапшот в одном turn'е нельзя ⇒ ветка остаётся fail-safe'ом на CI/дизайн-аргументе, а не ожидающим прод-трейсом. **Открыто:** **24h watch** до **2026-08-01 18:18 UTC**; из сигнатур незакрытой остаётся одна — `reason="fsm_armed"`, и она обоснована как fail-safe, а не как ожидающий прогон. Полная запись — [`F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md) § Deploy record — #359 / ADR-0020.

> **📋 PLAN (2026-07-31, initial draft + adversarial self-review §9 + независимое ревью round 2 §10 — два изменения дизайна, см. R2-B1 / R2-B2).** Архитектурная замена **несущего** слоя (c) фикса BUG-086: `_recover_llm_authored_confirm` перестаёт **предсказывать просьбу по прозе LLM** и начинает **реагировать на детерминированный ответ пользователя**. Turn, вызвавший confirm-gated write-tool без preview, сохраняет маленький snapshot; на **следующем** сообщении, если оно классифицируется как affirmative token, framework переиздаёт тот же tool в preview-форме и вооружает `ConfirmFlow` тогда. Триггером становится **закрытый словарь**, который кодовая база уже классифицирует надёжно (`classify_confirmation_token`), вместо безграничной прозы. Три регулярки, все пять precision-проходов и весь shadow-слой (d) **удаляются**.
>
> **Тип slice'а:** bot-adapter only (ADR-0004 / ADR-0006 § «bot изолирован как адаптер»). Нет schema-change, нет миграций, нет новых deps, backend не тронут. Deploy = re-create `tg_bot` (BUG-078).

**Дата:** 2026-07-31 · **Тип:** implementation-plan (замена механизма внутри bot-adapter: `agent.py` + `handlers.py` + `states.py` + `prompts/bot.yaml` + tests + docs) · **Ветка (предложение):** `fix/bot-affirmative-confirm-trigger` (от `main` @ `19e312a`).

**Goal (одной строкой):** убрать из bot-фреймворка предсказание «просьбы подтвердить» по тексту LLM и заменить его детерминированным двухшаговым протоколом «preview-less write-вызов → snapshot → affirmative token пользователя → настоящий preview → ConfirmFlow», сохранив все инварианты BUG-009 / BUG-046 / BUG-032 / BUG-047-D1 и class-wide покрытие всех **16** tool'ов `_WRITE_TOOLS_REQUIRING_CONFIRM`.

---

> ## ⚠️ Governing constraint (2026-07-31) — решение принимается **на design-основаниях**, не по прод-данным
>
> Owner проинспектировал прод 2026-07-31. За пять суток после деплоя `9aadf5e` **conversational-трафика в боте не было вообще**: все 5 записей `agent_tool_call` и все 8 `request_completed` относятся к owner-e2e 26 июля 07:50–07:56 UTC, после этого — ничего. Суточный объём логов — исключительно scheduler (digest-cron'ы, watchlist flush). Контейнер не менялся (`StartedAt 2026-07-26T07:04:53Z`, 0 restarts, healthy).
>
> ⇒ Shadow-окно `read_only_intent` не может дать данные **по двум независимым причинам**: (1) структурная, уже зафиксированная — вердикт вычисляется **после** detector-гейта ([`agent.py`](../../tg_parser/bot/agent.py) L734 early-return vs L745 вычисление), т.е. пишется только когда guard сработал; (2) прозаическая — инструментировать **нечего**, трафика нет. Секция issue #359 «Prioritise with data, not intuition» предполагала измеримый трафик; на single-user-деплое его нет.
>
> **Нормативно для этого документа:** ни один пункт плана **не отложен** до «подождём прод-данные». Обоснование каждого решения — design-аргумент (структурная недостижимость FP-векторов регуляркой, асимметрия цены ошибки, наличие локального прецедента), а не измеренная частота. Формулировка issue «⚠️ Check the denominator first» считается **исполненной и закрытой**: знаменатель равен нулю и это **потолок**, а не warm-up.

---

**Prerequisite SoT (перечитать перед кодом — всё verified 2026-07-31 @ `19e312a`):**
- Issue [#359](https://github.com/AlexEfimov/TG_parser/issues/359) — body (мотивация, два оставшихся FP-вектора) + комментарий 2026-07-26 (прод-findings, observability GAP, cancel-path).
- [`BUG_LOG.md`](BUG_LOG.md) § **BUG-086** — полная история дефекта: root cause, слои (a)/(b)/(c)/(c′)/(d), **все пять** precision-проходов, «Guard / tests added», «Production e2e verification», «Shadow-mode observability GAP», «Follow-up (deferred…)». Лучший единственный источник о том, что детектор реально был обязан обрабатывать.
- Стиль-эталон этого документа: [`START_PROMPT_SESSION_F5C_BOT_FORCE_RESUMMARIZE_2026-07-25.md`](START_PROMPT_SESSION_F5C_BOT_FORCE_RESUMMARIZE_2026-07-25.md) (в частности § 11 post-deploy addendum — там же зафиксирован урок «терминальная preview-less ветка = конфигурация BUG-046»).
- **Прецедент формы (СМ. §9 B1 — атрибуция в issue неверна):** `_handle_delete_intent_router` ([`handlers.py`](../../tg_parser/bot/handlers.py) L2357, **BUG-048 Part A**) и `_handle_subscribe_intent_router` (L2418, **BUG-050**) — persisted intent-snapshot + детерминированное возобновление на следующем сообщении.
- Классификатор токенов: `classify_confirmation_token` (L453), `AFFIRMATIVE_TOKENS` (L393), `NEGATIVE_TOKENS` (L416), `_looks_like_new_intent` (L496).
- [`tests/README.md`](../../tests/README.md) — режимы pytest; [`docs/quality/AGENT_PLAYBOOK.md`](../quality/AGENT_PLAYBOOK.md) — quality-lifecycle (INBOX / incident / TRIAGED; **не** источник red→green-процедуры — см. §9 m3).
- ADR: [0004](../adr/0004-hexagonal-architecture-and-module-boundaries.md) (bot = адаптер), [0006](../adr/0006-karpathy-like-living-kb-principles.md) (§ «bot изолирован как адаптер»), [0017](../adr/0017-dependency-management-policy.md) (новых deps нет). **Ни один accepted ADR не описывает bot-FSM / confirm-протокол** ⇒ формально не ограничивает; см. §8 (рекомендация завести ADR-0020).
- `docs/contracts/*.schema.json` — **не затронуты**: ни одна схема не описывает bot-FSM (`rg -l confirm docs/contracts/` → пусто).

---

## 0. TL;DR

| Step | Действие | Тип |
|---|---|---|
| 1 | **AgentResult-хинт.** Добавить поле `write_intent_pending: dict \| None` в `AgentResult` ([`agent.py`](../../tg_parser/bot/agent.py) L276). Заполняется **ровно в том же состоянии**, что сегодня открывает guard: `preview_pending is None and unpreviewed_write_calls` (L495). Значение — `{"tool_name": …, "args": <sanitized>}`, где `args` уже **без** `confirm` и без `_PREVIEW_SUPPRESSING_ARGS` (санитизация переезжает из guard'а L738-742 в момент создания snapshot'а). Прозу turn'а **не читаем**. | code |
| 2 | **Удалить guard целиком.** `_recover_llm_authored_confirm` (L704-791), `_LLM_AUTHORED_CONFIRM_PATTERN` (L136), `_CONFIRMATION_DISCLAIMED_PATTERN` (L151), `_ARG_LITERAL_PATTERN` (L164), `_looks_like_llm_authored_confirm` (L167) и вызов L495-505. `_PREVIEW_SUPPRESSING_ARGS` (L268) **ОСТАЁТСЯ** (санитизация нужна по-прежнему). | code |
| 3 | **Удалить shadow-слой (d).** `_READ_ONLY_REQUEST_PATTERN` (L205), `_MUTATION_IMPERATIVE_PATTERN` (L243), `_looks_like_read_only_request` (L249), поле `read_only_intent=` в обеих log-записях. Аргументация — §3.4. **Не реализовывать** «compute the verdict before the gate» из комментария issue (§9 m5). | code |
| 4 | **FSM-snapshot.** Новый `PendingWriteIntentData` TypedDict в [`states.py`](../../tg_parser/bot/states.py) (сосед `SubscribeIntentData` L152) + `_set_write_intent` / `_take_write_intent` / `_clear_write_intent` в `handlers.py` (по образцу L1849-1892). **TTL = `PENDING_TTL_SECONDS` (5 мин, как ConfirmFlow), НЕ 15 мин**, вычисляется через **`_is_stale(created_at, PENDING_TTL_SECONDS)`** (L1643, fail-safe), **не** через `_is_pending_expired` (L1630 — fail-**open** на битом `created_at`, §10 R2-M2). Плюс **строгая adjacency** — snapshot живёт ровно до следующего сообщения (§3.1, §9 B2, §10 R2-B1). | code |
| 4b | **Set-site.** Заполнение snapshot'а в `handle_text` — отдельная ветка в цепочке arm-сайтов L761-826, срабатывает **только когда этим turn'ом не вооружён ни один FSM** (§3.1, §10 R2-M1). В брифе и в первой редакции плана этого шага не было вовсе. | code |
| 5 | **Trigger-router.** `_handle_write_intent_router(message, state, snapshot, current_user) -> bool` — по образцу `_handle_subscribe_intent_router` (L2418). Snapshot **снимается (pop) в начале `handle_text`** сразу после L633 и передаётся роутеру как локальное значение — это делает adjacency **структурной**, а порядок относительно delete/subscribe-роутеров — действительно нейтральным (§3.2, §10 R2-B1). Триггер — **только tier-1** (полная нормализованная форма ∈ `AFFIRMATIVE_TOKENS` / `NEGATIVE_TOKENS`), компаунды («да, покажи темы X») считаются `unrelated` (§3.2, §10 R2-B2). affirmative → переиздать tool в preview-форме → вооружить `ConfirmFlow`; negative → «❌ Отменено.»; **всё остальное → fall-through** (snapshot уже снят). | code |
| 6 | **Mutual exclusion.** Обеспечивается **pop-at-top** (шаг 5) структурно, а не перечнем clear-сайтов: snapshot физически не может пережить сообщение, каким бы путём turn ни был обработан. Отдельные `_clear_write_intent` на arm-сайтах **не нужны** — и это к лучшему: их список в первой редакции был неполон (не хватало **восьми** `set_state`-сайтов: L1202, L1222, L1248, L1354, L2114, L2129, L2504, L2521 — §10 R2-B1). | code |
| 7 | **Observability.** Новые события: `write_intent_set`, `write_intent_router_resume`, `write_intent_router_failed`, `write_intent_declined`, `write_intent_dropped(reason=…)`. Плюс **закрыть пробел cancel-path** (issue § 3): `fsm_confirm_declined` в negative-ветке `_handle_confirmation_response` (L935-961 — сегодня там **нет ни одной** log-записи). Приватность: **только ключи** args, никогда значения и никогда текст сообщения. | code |
| 8 | **Prompt.** [`prompts/bot.yaml`](../../prompts/bot.yaml) L65 (hard rule v1.9.3) содержит утверждение, которое становится **ложным** («…the user's «да» then has nothing to confirm»). Переписать + bump `1.9.3 → 1.9.4` в **трёх** местах (**L2**, **L8**, **L32** — не L31, §9 M4) **плюс новая ведущая клауза `v1.9.4 …` в `metadata.description` (L9)** — по конвенции файла (§10 R2-m3). Переписанная строка обязана **сохранить** подстроки `dry_run=true` / `confirm=false` / «Подтвердите» / `BUG-009` — их пинит `TestPromptHardRule::test_hard_rule_separates_the_two_call_shapes` (F5-C L1174-1182, §10 R2-M3). Version-пины `startswith("1.9")` держатся **в двух** местах: `test_f9_phase2_prompt_defense.py` L194 **и** F5-C L1163-1167 (там же `>= (1,9,3)`). | code+docs |
| 9 | **Tests.** Удалить / переписать / сохранить — точный реестр в **§3.8**. Новый инвариант-класс `TestFinalTextNeverArmsConfirmFlow` (корпус из пяти precision-проходов переиспользуется как **доказательство независимости от прозы**). Mutation-верификация по каждому новому пину (**§3.9**). | test |
| 10 | **Docs.** [`BUG_LOG.md`](BUG_LOG.md) § BUG-086 — новая строка «Architectural replacement (2026-07-31)»; [`F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md) § 327-349 — watch-секция shadow-режима **удаляется** (наблюдать больше нечего) и заменяется новыми событиями; этот START_PROMPT → «landed» pointer. Issue #359 **не редактировать**. | docs |
| 11 | **ADR.** Черновик ADR-0020 (§8) — **outline, не филим** без решения owner'а. | docs |

**Recommended order:** 1 → 4 → 4b → 5 (red→green ядра) → 6 → 7 → 2 → 3 (удаления только после зелёного ядра) → 8 → 9 → 10. Удаления **после** — иначе на середине сессии дерево остаётся без обоих механизмов.

**Hard OUT:** §4.

---

## 1. Контекст

Слой (c) фикса BUG-086 — несущий: он ремонтирует ситуацию «confirm-gated write-tool вызван, preview не получен, LLM сам сочинил «Подтвердите … [да/нет]»», переиздавая tool в preview-форме. Механизм рабочий и в CI покрыт, но **способ обнаружения** ситуации — regex по итоговому тексту turn'а — оказался структурно порочным: **шесть FP-векторов за четыре раунда ревью, три из четырёх исправленных — морфологические** (лицо «подтверждаю», финитность «подтверждая», наклонение «подтвердить»). Два оставшихся регуляркой недостижимы:

- **(a) Свободный порядок слов.** `_CONFIRMATION_DISCLAIMED_PATTERN` порядок-зависим, русский — нет: «подтверждение не требуется» вето срабатывает, «Ничего подтверждать не нужно …» / «Подтверждать этот отчёт не требуется …» / «Подтверждения от вас не требуется …» — нет. Каждый пробел возвращает FP на маркере `[да/нет]` — а именно вето позволяет этот (самый сильный и единственный прод-наблюдаемый) маркер сохранить.
- **(b) Чужой текст.** Детектор читает итоговый текст turn'а, куда LLM может процитировать контент базы знаний. Turn, который одновременно делает preview-less write-вызов и цитирует пост/заголовок темы с «Подтвердите … [да/нет]», вооружает preview по тексту, **который никто не писал как просьбу**.

**Что меняется по сути.** Сегодня framework отвечает на вопрос «просил ли LLM подтверждение?» — вопрос про **прозу**, открытый класс. Новый дизайн отвечает на вопрос «сказал ли **пользователь** «да»?» — вопрос про **закрытый словарь**, который handlers уже классифицирует детерминированно с BUG-032 (18 affirmative + 14 negative токенов, `casefold`, схлопывание пробелов, first-token-правило).

**Асимметрия цены ошибки меняется в нашу пользу — это главный design-аргумент.** Сегодня FP детектора вооружает `ConfirmFlow` **молча**: пользователь просил отчёт, получил мутационный preview, и случайное «да» **коммитит** мутацию (сжигает токены). В новом дизайне ложный триггер невозможен без того, чтобы пользователь сам напечатал affirmative token, и его результат — **preview** (0 токенов, 0 записей), после которого мутация требует **ещё одного** явного «да» поверх явно показанного мутационного текста. То есть мутация становится структурно недостижимой без того, что пользователь дважды видел и дважды подтвердил.

**Прецедент формы — локальный, не изобретаемый.** `delete_intent` (BUG-048 Part A) и `subscribe_intent` (BUG-050) уже делают ровно это: сохраняют snapshot интента и детерминированно возобновляют его на следующем сообщении, минуя LLM. Отличие одно и оно принципиально (§3.1): у них триггер **специфичный** (bare name), поэтому snapshot живёт 15 минут и переживает промежуточные turn'ы; у нас триггер **общий** («да»), поэтому snapshot обязан быть **строго смежным**.

---

## 2. Anchors (перечитать перед правкой — verified 2026-07-31 @ `19e312a`)

| Якорь | Файл | Строка | Роль |
|---|---|---|---|
| `AgentResult` (**добавить** `write_intent_pending`) | [`agent.py`](../../tg_parser/bot/agent.py) | **L276**; `clarify_pending` как образец-хинт **L326** | новый FSM-хинт для handler'а |
| `unpreviewed_write_calls` — инициализация / наполнение | [`agent.py`](../../tg_parser/bot/agent.py) | **L413** / **L602-606** | населяется, когда `tool ∈ _WRITE_TOOLS_REQUIRING_CONFIRM` и `result["preview"] is not True` |
| Guard-вызов (**удалить**) | [`agent.py`](../../tg_parser/bot/agent.py) | **L495-505** | здесь вместо recovery ставится snapshot |
| `_recover_llm_authored_confirm` (**удалить**) | [`agent.py`](../../tg_parser/bot/agent.py) | **L704-791**; гейт L734; санитизация **L738-742**; log L750 / L782 | санитизация переезжает в step 1 |
| Три регулярки + хелпер (**удалить**) | [`agent.py`](../../tg_parser/bot/agent.py) | **L136**, **L151**, **L164**, **L167** | + ~58 строк комментариев пяти проходов (L78-135) |
| Shadow-слой (d) (**удалить**) | [`agent.py`](../../tg_parser/bot/agent.py) | **L181-261** (паттерны L205 / L243, хелпер L249) | §3.4 |
| `_PREVIEW_SUPPRESSING_ARGS` (**ОСТАЁТСЯ**) | [`agent.py`](../../tg_parser/bot/agent.py) | **L268** | санитизация snapshot'а; tripwire в §9-тестах живёт |
| Ранние return'ы без snapshot'а (edge, §3.1) | [`agent.py`](../../tg_parser/bot/agent.py) | clarify **L683-688**, MAX_AGENT_TURNS **L692-702** | clarify — осознанный пробел (mutual exclusion); MAX_AGENT_TURNS — **исправлен на round-3**, см. §3.1 |
| `handle_text` — вход + FSM-state-гейты | [`handlers.py`](../../tg_parser/bot/handlers.py) | `current_state = …` **L633**; Confirm **L637**, Clarify **L646**, Pagination **L652** | **pop snapshot'а — сразу после L633**, до всех гейтов (§3.2, §10 R2-B1); router вызывается позже |
| Три существующих pre-router'а | [`handlers.py`](../../tg_parser/bot/handlers.py) | **L663** (`_handle_delete_prerouter`), **L671**, **L679** | порядок нейтрален **только при pop-at-top + tier-1-триггере** (§3.2, §10 R2-B2) |
| `_handle_delete_prerouter` — гейты | [`handlers.py`](../../tg_parser/bot/handlers.py) | **L2246**; `DELETE_VERB_PATTERN.match` **L2270**, `ANAPHORA_PATTERN.search` **L2271** | у него, в отличие от L2393/L2461, **нет** гейта `classify_confirmation_token` — контрпример к «нейтральности» на компаундах (§10 R2-B2) |
| Arm-сайты (**set-site + справочно**) | [`handlers.py`](../../tg_parser/bot/handlers.py) | preview **L761-779**, clarify **L780-795**, pagination **L796-811**, subscribe-intent **L812-826** | set-site нового snapshot'а — ветка этой же цепочки (§3.1, §10 R2-M1) |
| Остальные `set_state`-сайты (**не** в цепочке `handle_text`) | [`handlers.py`](../../tg_parser/bot/handlers.py) | **L1202**, **L1222**, **L1248**, **L1354**, **L2114**, **L2129**, **L2504**, **L2521** | пропущены в первой редакции step 6; при pop-at-top clear на них не нужен (§10 R2-B1) |
| `_handle_confirmation_response` | [`handlers.py`](../../tg_parser/bot/handlers.py) | **L829**; new-intent escape **L861**; affirmative **L867**; negative **L935-961** (**нет log'а** — issue § 3); unknown **L969** | образец для router'а + cancel-observability |
| `classify_confirmation_token` / токены | [`handlers.py`](../../tg_parser/bot/handlers.py) | **L453**; tier-1 (полная форма) **L484-487**, tier-2 (первый токен) **L488-492** / `AFFIRMATIVE_TOKENS` **L393** (18 шт.), `NEGATIVE_TOKENS` **L416** (14 шт.) | единственный триггер нового дизайна; берём **только tier-1** (§3.2, §10 R2-B2) |
| `_looks_like_new_intent` | [`handlers.py`](../../tg_parser/bot/handlers.py) | **L496** | классифицированный токен **никогда** не new-intent (L510) |
| TTL-хелперы | [`handlers.py`](../../tg_parser/bot/handlers.py) | `PENDING_TTL_SECONDS` **L78** (300), `READ_CONTEXT_TTL_SECONDS` **L84** (900), `_is_pending_expired` **L1630** (fail-**open**: `not created_at_iso → False`, L1632-1633), `_is_stale` **L1643** (fail-safe: `→ True`, L1650-1651) | берём 300 (§9 B2) **через `_is_stale`** (§10 R2-M2) |
| **Прецедент-эталон** `_set/_for_router/_clear_subscribe_intent` | [`handlers.py`](../../tg_parser/bot/handlers.py) | **L1849 / L1873 / L1890** | 1:1 форма для write-intent (у нас `_for_router` заменён на `_take_…` — pop) |
| **Прецедент-эталон** `_handle_subscribe_intent_router` | [`handlers.py`](../../tg_parser/bot/handlers.py) | **L2418-2544** (гейты L2447-2471, re-run L2487, arm L2516-2532, degraded L2537) | 1:1 форма router'а |
| `_handle_delete_intent_router` (BUG-048, **не** BUG-047) | [`handlers.py`](../../tg_parser/bot/handlers.py) | `def` **L2357**, docstring-ссылка §9 B1 — **L2362**; «стray «да» инертно» контракт **L2378-2380 / L2393** | BUG-047-D1 пин, который нельзя сломать |
| Double-confirm прецедент (UX-эталон) | [`handlers.py`](../../tg_parser/bot/handlers.py) | `_handle_delete_suggest_selection` **L2167** (affirmative → `_arm_delete_preview` **L2198**, «actual delete still needs a SECOND «да»» L2179-2181) | та же трёх-turn'овая форма |
| `SubscribeIntentData` (образец TypedDict) | [`states.py`](../../tg_parser/bot/states.py) | **L152-191**; `ConfirmFlow` **L33** | новый `PendingWriteIntentData` |
| `_WRITE_TOOLS_REQUIRING_CONFIRM` (16 tool'ов) | [`tools.py`](../../tg_parser/bot/tools.py) | **L110-163** | blast radius: **все 16**, не только `force_resummarize` (пересчитано — §10) |
| `dry_run`-ветка + `next_step` (комментарий ссылается на удаляемый символ) | [`tools.py`](../../tg_parser/bot/tools.py) | ветка A **L3192-3239**; комментарий про `agent._LLM_AUTHORED_CONFIRM_PATTERN` **L3221-3224**; `dry_run`+`confirm` reject **L3181** | правка комментария обязательна (§9 M4) |
| **Авторизация переиздания** | [`tools.py`](../../tg_parser/bot/tools.py) | `assert_admin(user)` **L3171**; **фолбэк `user = current_user or await get_default_admin()` L3168** | authz перепроверяется на resume; гейт `current_user is None` в роутере **несущий** (§3.2, §10 R2-M4) |
| BUG-009-гейт executor'а | [`tools.py`](../../tg_parser/bot/tools.py) | **L1353**; `_check_confirm_flow_match` **L1257** (точное равенство args, L1271-1273) | переиздание идёт **без** `confirm` и **без** `confirm_flow_state` ⇒ гейт не задет; на confirm-turn'е args совпадают бит-в-бит |
| `ChatSerializationMiddleware` (per-chat lock) | [`middleware.py`](../../tg_parser/bot/middleware.py) | **L140**, lock **L179-181**; `LoggingMiddleware` / `request_completed` **L184 / L210** | snapshot read-modify-write гонок не имеет |
| MemoryStorage (single-replica) + FSM-скоупинг | [`main.py`](../../tg_parser/bot/main.py) | **L244**; middleware-регистрация L247-253 | snapshot умирает с контейнером — как `pending_action`. **Verified:** `fsm_strategy` не передан ⇒ aiogram 3.29 default `FSMStrategy.USER_IN_CHAT` ⇒ ключ = (bot, chat, user) — snapshot скоупится per-user **и** per-chat (§10) |
| § 9 промоушен-тесты | [`tests/test_bot_confirm_flow.py`](../../tests/test_bot_confirm_flow.py) | **L1291** (§ 9), `…IsToolAgnostic` **L1312** (тесты L1340 / L1372), `…RegistryIsComplete` **L1399** (тесты L1410 / L1424) | один переписывается, второй — **unchanged** (§3.8) |
| BUG-086-блок F5-C-тестов | [`tests/test_f5c_bot_force_resummarize.py`](../../tests/test_f5c_bot_force_resummarize.py) | docstring про `read_only_intent` **L33**, импорты **L50-55**, `_PROD_SELF_AUTHORED_CONFIRM` **L486**, `_GUARD_LOG_EVENTS` **L495**, общий хелпер `_prod_trace_turn` **L823-847**, классы **L499 / L559 / L904 / L980 / L1153** | реестр §3.8 |
| **Prompt-пины (пропущены в первой редакции)** | [`tests/test_f5c_bot_force_resummarize.py`](../../tests/test_f5c_bot_force_resummarize.py) | `TestPromptHardRule` **L1153**: version **L1163-1167**, L8↔L32 consistency **L1169-1172**, **содержание hard rule L1174-1182** | ограничивает переписывание `bot.yaml` L65 (§3.7, §10 R2-M3) |
| bot-prompt | [`prompts/bot.yaml`](../../prompts/bot.yaml) | version **L2 / L8 / L32**; write-ops L42; § «Confirmation semantics» **L54**; BUG-086 hard rule **L65**; список токенов **L66**; BUG-007 «да X» read-flow **L69** | §3.6 |

---

## 3. Scope — детально

### 3.1 Где живёт snapshot и что в нём (code)

**Storage.** FSM-data-поле `pending_write_intent` (не state) — сосед `read_context` / `last_subscription` / `delete_intent` / `subscribe_intent`. Скоупинг per-chat/per-user наследуется от `FSMContext` бит-в-бит как у `pending_action` — отдельного механизма не нужно. **Verified (§10):** `Dispatcher(storage=MemoryStorage())` ([`main.py`](../../tg_parser/bot/main.py) L244) не передаёт `fsm_strategy`, а default aiogram 3.29 — `FSMStrategy.USER_IN_CHAT`, т.е. ключ = (bot_id, chat_id, user_id). В групповом чате чужой пользователь **не может** консумировать snapshot соседа; `ChatSerializationMiddleware` (per-(bot, chat) lock) при этом сериализует и групповой случай.

**Set-site (шаг 4b — в первой редакции отсутствовал, §10 R2-M1).** Snapshot ставится в `handle_text` в той же цепочке, что и остальные arm-сайты (L761-826), и **только когда этим turn'ом не вооружён ни один FSM**:

```python
elif result.pagination_pending:
    ...
else:
    if result.write_intent_pending:
        await _set_write_intent(state, **result.write_intent_pending)
        logger.info("write_intent_set", ...)
    if tool := _detect_subscribe_tool(user_text):   # BUG-050 — сохраняется
        ...
```

Почему **не** отдельный верхнеуровневый `if`: гейт агента (L495) исключает только `preview_pending`, но **не** `pagination_pending` — turn может одновременно вернуть `pagination_pending` и preview-less write-вызов, и независимый `if` вооружил бы `PaginationFlow` **и** поставил snapshot. `subscribe_intent` (L812) при этом сосуществовать со snapshot'ом **может и должен**: триггеры непересекающиеся (токен vs bare channel name), а BUG-050-резюме иначе бы регрессировало.

```python
class PendingWriteIntentData(TypedDict, total=False):
    created_at: str      # ISO UTC — TTL-анкер
    tool_name: str       # что переиздать
    args: dict           # УЖЕ санитизированные (см. ниже)
```

**Что идентифицирует вызов.** `tool_name` + `args` последнего элемента `unpreviewed_write_calls` (`[-1]` — та же политика, что у сегодняшнего guard'а L737). Санитизация — **в момент создания snapshot'а**, а не при переиздании:

- `confirm` вырезается **безусловно** (BUG-009: `confirm=True` ставит только FSM-confirm-turn — инвариант не меняется);
- любой ключ из `_PREVIEW_SUPPRESSING_ARGS` (сейчас `{"dry_run"}`) вырезается — иначе переиздание вернёт тот же report-only payload и preview не получится.

Verified: сегодняшний guard делает ровно это (L738-742) — предпосылка брифа подтверждена. Санитизация **до** записи в FSM даёт бонус: в storage никогда не лежит `confirm`/`dry_run`, поэтому мутационную форму нельзя восстановить из snapshot'а даже случайно.

**Приватность.** `args` кладутся в FSM целиком — это **уже существующий** класс экспозиции: `pending_action` (L766) хранит args ровно так же, а `add_user_auth` несёт сырой credential в значении. Нового риска нет, но **логировать по-прежнему только ключи** (`sorted(args)`), никогда значения — норма из BUG-086 layer (d) сохраняется, хотя сам layer удаляется.

**TTL и adjacency — два разных механизма, оба обязательны.**

| Механизм | Значение | Зачем |
|---|---|---|
| TTL | `PENDING_TTL_SECONDS` = **300 с** (как ConfirmFlow), **не** 900 с; проверка — **`_is_stale(created_at, PENDING_TTL_SECONDS)`** (L1643) | snapshot — это *pre*-confirmation, его срок жизни должен совпадать с confirmation, а не с read-context. `_is_pending_expired` (L1630) **не годится**: на отсутствующем/битом `created_at` он возвращает `False` (= «не истёк») — fail-open на пути, который вооружает мутационный preview (§10 R2-M2) |
| Adjacency | snapshot **снимается из FSM в начале `handle_text`** (сразу после L633) и дальше живёт только как локальная переменная этого turn'а | триггер общий («да»), поэтому «переживание» промежуточных turn'ов недопустимо — и это должно обеспечиваться **структурой**, а не перечнем clear-сайтов (§10 R2-B1) |

Это **сознательное отличие от прецедента**: `delete_intent` / `subscribe_intent` намеренно переживают промежуточный junk-reply и `state.clear()` (их триггер — конкретное имя, ложное срабатывание маловероятно). Здесь наоборот: без adjacency «да», сказанное через три turn'а совсем по другому поводу, вооружило бы мутационный preview — это ровно тот FP-класс, от которого мы уходим, только перенесённый во время. См. §9 B2.

**Почему именно pop-at-top, а не «дропать в роутере» (изменение дизайна, §10 R2-B1).** Роутер стоит после гейтов L637/L646/L652 и после трёх pre-router'ов L663/L671/L679. Любой из этих путей **возвращается раньше** роутера — и тогда snapshot не дропается вовсе. Конкретный достижимый случай: turn вернул `pagination_pending` **и** preview-less write-вызов (гейт агента L495 проверяет только `preview_pending`) ⇒ вооружён `PaginationFlow` + стоит snapshot; следующее сообщение «ещё» обрабатывается `_handle_pagination_response` и уходит на L1354 (или на подсказку L1382-1385) **без** `state.clear()` ⇒ snapshot жив; ещё через сообщение «да» вооружает мутационный preview из turn'а двухдавностной свежести. Pop-at-top закрывает весь класс одной строкой и делает шаг 6 (перечень clear-сайтов) излишним — что удобно, потому что тот перечень был неполон: `set_state` вызывается ещё в **восьми** местах (L1202, L1222, L1248, L1354, L2114, L2129, L2504, L2521).

**Что происходит, если следующее сообщение — не токен.** Snapshot уже снят при входе; логируется `write_intent_dropped(reason="unrelated")`, turn идёт обычным путём. Никаких сообщений пользователю — drop невидим.

**Осознанные пробелы (задокументировать в коде, не «чинить»):**
- turn, который вернулся через clarify-early-return (L683-688), snapshot **не** ставит. Это не пробел, а требование mutual exclusion: clarify вооружает свой FSM, и два механизма не должны конкурировать.
- ~~turn, исчерпавший `MAX_AGENT_TURNS` (L692-702), snapshot не ставит — сегодняшний guard в этой ветке тоже не работает; поведение сохраняется бит-в-бит.~~ **Пересмотрено на round-3 ревью и ИСПРАВЛЕНО** (см. находку 6 в landed-указателе): паритет со старым guard'ом не оправдывает пробел, потому что тот же `return` прокидывает `preview_pending`. Оба выхода теперь идут через `_write_intent_or_none`.

### 3.2 Trigger-path (code)

`_handle_write_intent_router(message, state, snapshot, current_user) -> bool` — форма 1:1 с `_handle_subscribe_intent_router` (L2418), но snapshot приходит **параметром**: он снят из FSM в начале `handle_text` (pop-at-top, §3.1). `state` по-прежнему нужен — чтобы вооружить `ConfirmFlow` на успешном resume.

**Гейты (в порядке проверки):**
1. пустой текст / `current_user is None` → `False`. Гейт на `current_user` — **несущий, а не косметический**: executor'ы делают фолбэк `user = current_user or await get_default_admin()` ([`tools.py`](../../tg_parser/bot/tools.py) L3168), поэтому переиздание с `current_user=None` выполнилось бы **от имени дефолтного админа** (§10 R2-M4). Пинится тестом;
2. `snapshot is None` (не было snapshot'а или `_is_stale(created_at, PENDING_TTL_SECONDS)`) → `False`;
3. **tier-1 классификация** — `" ".join(text.split()).casefold()` целиком ∈ `AFFIRMATIVE_TOKENS` / `NEGATIVE_TOKENS` ([`handlers.py`](../../tg_parser/bot/handlers.py) L484-487):
   - affirmative → **resume** (ниже);
   - negative → `write_intent_declined`, ответ «❌ Отменено.» → `True`;
   - иначе (в т.ч. любой компаунд) → `write_intent_dropped(reason="unrelated")`, → `False` (fall-through).

**Почему tier-1, а не весь `classify_confirmation_token` (изменение дизайна, §10 R2-B2 — отменяет §9 m2).** Tier-2 (L488-492) классифицирует по **первому** токену, поэтому affirmative — это не 18 строк, а весь класс «сообщение, начинающееся с одного из 18 токенов». В `ConfirmFlow` это безопасно: пользователь только что увидел framework'ов «Подтвердите [да/нет]», поэтому «да, давай» однозначно относится к нему. Здесь контекста нет по построению: T1 мог быть **честным** dry-run-отчётом, framework подсказку не добавляет (§9 п.12), и тогда:

- «да, покажи темы канала X» → router перехватывает turn, показывает **мутационный** preview и **теряет** собственный запрос пользователя;
- «нет, покажи другое» → «❌ Отменено.» и запрос так же теряется.

Это ровно read-only-intent-FP, ради измерения которого существовал слой (d), — то есть §3.4 (4) при tier-2 **неверно**. Асимметрия та же, что и во всех пяти precision-проходах: пропуск «да, давай» стоит одной переформулировки, ложное срабатывание — потерянного запроса плюс мутационного preview. ⇒ берём tier-1 и **пиним** это как осознанное расхождение с `_handle_confirmation_response` (не как «зеркалирование»).

**Resume:** `execute_tool(tool_name, dict(args), current_user=…, bot=…, chat_id=…)` (без `confirm` — args уже санитизированы; snapshot уже снят pop'ом, отдельный `_clear_write_intent` не нужен) →
- `result["preview"] is True` → `state.set_state(ConfirmFlow.awaiting_confirmation)`, `update_data(pending_action={"tool_name":…, "args": args}, created_at=_utcnow_iso())`, отрисовать `result["message"]` **verbatim** через `_send_html_response`, если `user_facing_message is True`, иначе `_format_tool_result` (лineage BUG-042; ровно как L2516-2532);
- иначе → `write_intent_router_failed`, детерминированное сообщение пользователю (§3.5, **обязательно** — см. §9 M2);
- исключение → `logger.exception`, `format_error(...)`, `True`.

**Авторизация на resume перепроверяется — verified, не предполагается (§10 R2-M4).** `execute_tool` не кеширует права: `current_user` приходит из `UserResolutionMiddleware` **на текущем** сообщении, а каждый executor сам проверяет доступ (`force_resummarize` → `assert_admin(user)`, [`tools.py`](../../tg_parser/bot/tools.py) L3171). Snapshot, созданный админом и переизданный после `update_user`-демоушена, вернёт `PermissionDenied`-payload ⇒ ветка `write_intent_router_failed`, мутации нет. Snapshot **не** несёт ни `current_user`, ни роли — только `tool_name` + санитизированные args, поэтому «доверие снимку» физически невозможно. Обязательные пины — §3.8.

**Args в snapshot'е не расширяют поверхность атаки.** Это те же args, которые LLM уже передал в `execute_tool` **в T1** (agent.py L556-563) — переиздание не добавляет ни одного ключа, а два вырезает. Дополнительно: BUG-009-гейт (`tools.py` L1353) на пути переиздания не задет (нет `confirm`), а на следующем, настоящем confirm-turn'е `_check_confirm_flow_match` (L1257) требует **точного равенства** `args` снимку `pending_action` (L1271-1273) — то есть LLM-issued `confirm=true` по-прежнему отбивается, а подмена args между preview и confirm по-прежнему невозможна.

**Почему нельзя вооружить два механизма одновременно (структурно, а не по договорённости):**

| Инвариант | Как обеспечивается |
|---|---|
| snapshot не ставится, когда `ConfirmFlow` уже вооружён | `handle_text` возвращается на L637 **до** агента, поэтому turn с armed ConfirmFlow не может создать snapshot |
| snapshot не переживает ни одного сообщения, каким бы путём turn ни был обработан | **pop-at-top** сразу после L633 (§3.1) — структурно, а не перечнем clear-сайтов |
| snapshot не ставится тем же turn'ом, что вооружил **любой** FSM | set-site — ветка цепочки L761-826 (§3.1), т.е. взаимоисключение с `preview` / `clarify` / `pagination` синтаксическое; плюс условие `preview_pending is None` (L495) в агенте |
| affirmative token при armed ConfirmFlow идёт в ConfirmFlow, не в router | приоритет L637 > router (snapshot при этом снят pop'ом и дропнут) |

**Порядок относительно delete/subscribe-роутеров нейтрален — при tier-1-триггере и pop-at-top; без них нет** (исправлено, §10 R2-B2; §9 m4 в этой части устарел). Проверка:

- ни одна из 18+14 **полных** форм не матчится `DELETE_VERB_PATTERN` (L112), `ANAPHORA_PATTERN` (L121), `COMMAND_VERB_PATTERN` (L164) — это в §9 m4 проверено верно;
- но `classify_confirmation_token` при tier-2 принимает и **компаунды**, а `ANAPHORA_PATTERN` ищется **где угодно в строке** (не якорем): «да, удали эту подписку» / «да, последнюю» — одновременно `affirmative` и валидный триггер `_handle_delete_prerouter` (L2270-2271), у которого, в отличие от L2393 / L2461, **нет** гейта `classify_confirmation_token`. То есть при tier-2 порядок решает исход, а при постановке роутера после L663 — ещё и оставляет snapshot непотреблённым (pre-router вернул `True`);
- при **tier-1** пересечение пусто (ни один из 32 токенов не матчит ни один из трёх паттернов), а pop-at-top снимает вопрос «кто съел snapshot» полностью.

Рекомендация не меняется: ставить **после** трёх существующих роутеров (перед `sanitize_user_input` L684) — читается как «последний детерминированный шанс перед агентом»; порядок пинится тестом, а не комментарием.

**BUG-047-D1 не ломается.** Контракт «стray «да» инертно для delete-флоу» сохраняется: при активном `delete_intent` и **отсутствии** snapshot'а «да» по-прежнему проваливается к агенту. Меняется только состояние «есть pending write snapshot», которого раньше не существовало. Обязательный пин — матрица в §3.8.

**Компаунды («да, давай», «да genotek», «да, покажи темы X») — ИЗМЕНЕНО в round 2 (§10 R2-B2).** Первая редакция решала «зеркалить `_handle_confirmation_response` дословно» (§9 m2). Отменено: в `ConfirmFlow` компаунд безопасен, потому что пользователь уже видел framework'ов «Подтвердите [да/нет]», а здесь T1 мог быть честным отчётом — и компаунд стоил бы пользователю потерянного запроса плюс мутационного preview. Роутер берёт **только tier-1**; компаунд ⇒ `unrelated` ⇒ snapshot дропнут, turn идёт к агенту как обычно. Побочный выигрыш: сохраняется prompt-правило BUG-007 «да X» (bot.yaml L69) — «да X» больше не перехватывается роутером.

### 3.3 Что удаляется (code) — verified против дерева

| Символ / блок | Строки | Судьба | Проверка |
|---|---|---|---|
| `_LLM_AUTHORED_CONFIRM_PATTERN` | agent.py L78-144 (с комментариями пяти проходов) | **удалить** | внешних потребителей нет |
| `_CONFIRMATION_DISCLAIMED_PATTERN` | L146-158 | **удалить** | — |
| `_ARG_LITERAL_PATTERN` | L160-164 | **удалить** | — |
| `_looks_like_llm_authored_confirm` | L167-178 | **удалить** | импортируется только тестом F5-C (L53) |
| `_READ_ONLY_REQUEST_PATTERN` / `_MUTATION_IMPERATIVE_PATTERN` / `_looks_like_read_only_request` | L181-261 | **удалить** | импортируется только тестом F5-C (L54) |
| `_recover_llm_authored_confirm` + вызов | L495-505, L704-791 | **удалить** | — |
| `read_only_intent` — вычисление **L745** + поля в log-записях **L755** / **L789** | L745, L755, L789 | **удалить** | L745 — это присваивание, а не log-запись (уточнено, §10 R2-m2); сами записи — L750-756 и L782-790. Watch-секция runbook'а тоже (§3.7) |
| `_PREVIEW_SUPPRESSING_ARGS` | L268 | **СОХРАНИТЬ** | нужен для санитизации; tripwire живёт |
| Комментарий в `tools.py`, ссылающийся на `agent._LLM_AUTHORED_CONFIRM_PATTERN` | tools.py L3221-3224 | **переписать** | иначе комментарий указывает на несуществующий символ |

**Итого:** ≈ **280** строк кода+комментариев в `agent.py` уходят (пересчитано, §10 R2-m1: L78-178 ≈ 97 + L181-261 = 81 + гейт-вызов L493-505 = 13 + метод L704-791 = 88; «~185» первой редакции — недооценка почти вдвое); остаётся ~35 строк snapshot-логики в `agent.py` + ~90 в `handlers.py`/`states.py`. Все пять precision-проходов (`\bconfirm\b` → структура; лицо; герундий; инфинитив; границы клауз) исчезают вместе с классом проблемы, а не с симптомами.

### 3.4 Shadow-слой (d) — удаляется, а не переносится (argued explicitly)

**Задача layer (d) была:** ответить на вопрос «а не просил ли пользователь read-only отчёт?» — потому что триггер (проза LLM) **не содержал никакого сигнала от пользователя**, и его приходилось добывать вторым угадывающим классификатором по тексту пользователя.

**В новом дизайне вопрос отвечен by construction:**
1. Триггер **и есть** сигнал пользователя. Пользователь, попросивший отчёт и получивший отчёт, просто не печатает «да» — и никакого arming не происходит. Не нужно угадывать интент: его сообщил сам пользователь.
2. Если он всё-таки печатает «да» после dry-run-отчёта — это **не** FP, а осмысленный запрос «давай, запускай». Правильная реакция — показать мутационный preview, что дизайн и делает.
3. Худший исход ложного триггера смещён: preview (0 токенов, 0 записей) + обязательное второе подтверждение поверх явного мутационного текста — вместо armed мутации в одном «да» от коммита.
4. Измерять больше нечего: FP-класс, ради измерения которого layer (d) существовал, в новом дизайне **не имеет представителей** — arming без **явного, одиночного** «да» невозможен. ⚠️ **Уточнено в round 2 (§10 R2-B2):** это утверждение верно **только** при tier-1-триггере. При tier-2 (как было в первой редакции) представитель есть и он очевиден: «да, покажи темы канала X» после честного dry-run-отчёта — router вооружает мутационный preview и **теряет** запрос пользователя, т.е. ровно тот read-only-intent-FP, ради которого слой (d) и строился. Пункт 4 держится ровно постольку, поскольку держится tier-1.

**Контраргумент, зафиксированный честно:** удаляется построенный и отревьюенный код, вместе с четырьмя тестами и watch-разделом runbook'а. Если замену когда-нибудь откатят, layer (d) придётся восстанавливать. Ответ: git-история; носить в дереве мёртвый классификатор ради гипотетического откатa дороже (он будет цитироваться и «поддерживаться»).

⇒ **Рекомендация: удалить целиком.** И **не** реализовывать промежуточный фикс «compute the verdict before the detector gate» из комментария issue — он существует ради измерения, которое новый дизайн отменяет (§9 m5).

### 3.5 Двойное подтверждение — точный UX и последовательность turn'ов (code)

**Degraded path (LLM выбрал не ту форму вызова) — три turn'а:**

| # | Кто | Что |
|---|---|---|
| T1 | user | «пере-суммаризируй тему `topic:tg:c1:post:1`» |
| T1 | bot | текст LLM **как есть** (например, dry-run-отчёт + собственное «Подтвердите …»). Framework: `preview_pending is None` ⇒ **snapshot** `{force_resummarize, {"topic_id": …}}`, `write_intent_set`. ConfirmFlow **не** вооружён. Дополнительной подсказки framework **не** добавляет (§9 m-design) |
| T2 | user | «да» |
| T2 | bot | переизданный **настоящий** preview tool'а, verbatim: «Тема «…» (текущая версия 8, новых элементов 0) будет немедленно пересуммаризирована — вызов LLM (расход токенов), будет записана новая версия сводки. **Подтвердите [да/нет].**» + `ConfirmFlow` armed (`write_intent_router_resume`, `fsm_confirm_armed`) |
| T3 | user | «да» |
| T3 | bot | `fsm_confirm_execute` → «✅ force_resummarize: `topic:tg:c1:post:1` — ok.» |

**Ветки T2:**

| Ответ | Поведение | Текст |
|---|---|---|
| negative **bare** («нет», «отмена», …) | `write_intent_declined` | «❌ Отменено.» (дословно как ConfirmFlow L960 — одна фраза на весь бот) |
| компаунд («да, покажи X» / «нет, покажи другое») или любой не-токен | snapshot дропнут (`reason="unrelated"`), turn идёт как обычно **к агенту** | — (запрос пользователя не теряется — §10 R2-B2) |
| affirmative, но preview недостижим (permission denied / not-found / любая ошибка executor'а) | `write_intent_router_failed` | «Не удалось подготовить подтверждение: <причина из `result["error"]`>. Повторите запрос.» — **обязательно** (§9 M2). Сюда же попадает **демоушен пользователя между T1 и T2**: `assert_admin` (tools.py L3171) вернёт `PermissionDenied`-payload, мутации нет (§10 R2-M4) |
| TTL истёк | snapshot отсутствует ⇒ router не срабатывает, «да» падает к агенту | сегодняшнее поведение (не регресс) |
| бот перезапустился между T1 и T2 | `MemoryStorage` ⇒ snapshot исчез вместе с контейнером; «да» падает к агенту | сегодняшнее поведение (тот же класс, что `pending_action`); «полу-состояний» не бывает |

**Про `status='locked'`.** Advisory-lock у `force_resummarize` живёт на **мутационном** пути; переиздание идёт с `confirm=false` (ветка B — чтение живой карточки, [`tools.py`](../../tg_parser/bot/tools.py) L3241+), поэтому `locked` на T2 недостижим. Если бы был — это обычная «preview недостижим»-ветка выше, состояние не выдумывается.

**Happy path не меняется:** правильный `confirm=false` → настоящий preview → ConfirmFlow → одно «да». Ровно как в прод-трейсе 26 июля (07:51:32 → 07:51:33 → 07:51:44).

**Сравнение с BUG-047 `delete_suggest` (уже отгруженная форма).** Там: T1 «удали подписку Genotk» → «Не найдено. Ближайшее совпадение: «Genotek»…»; T2 «да» → **принятие предложения** + arming unsubscribe-preview («… будет удалена. Подтвердите [да/нет]») — код прямо документирует «the actual delete still needs a SECOND «да» — BUG-009 / BUG-046 contract preserved; nothing is deleted on the acceptance turn» (L2179-2181); T3 «да» → удаление. Наш T2 занимает ровно позицию «acceptance turn»: первый «да» **ничего не мутирует**, он только достаёт настоящий preview. Форма не новая для пользователя и не новая для кодовой базы.

### 3.6 Observability (code)

| Событие | Уровень | Поля | Когда |
|---|---|---|---|
| `write_intent_set` | INFO | `tool`, `arg_keys` (sorted), `chat_id` | snapshot создан (T1) |
| `write_intent_router_resume` | INFO | `tool`, `arg_keys`, `rendered_verbatim`, `chat_id` | affirmative → preview получен, ConfirmFlow вооружён |
| `write_intent_router_failed` | WARNING | `tool`, `error`, `chat_id` | affirmative → preview недостижим |
| `write_intent_declined` | INFO | `tool`, `chat_id` | negative token на pending snapshot |
| `write_intent_dropped` | INFO | `tool`, `reason ∈ {unrelated, fsm_armed, ttl}`, `chat_id` | snapshot снят без использования |
| **`fsm_confirm_declined`** | INFO | `tool`, `chat_id` | **negative-ветка `_handle_confirmation_response`** — закрывает пробел issue § 3 |

**Пробел cancel-path — почему он именно здесь.** Verified: negative-ветка (L935-961) не пишет **ничего**; affirmative пишет `fsm_confirm_execute` (L878), unknown — `fsm_confirm_unknown_token` (L969). Отказ виден только как «голый» `request_completed` из `LoggingMiddleware` (L210), т.е. «пользователь отказался» и «флоу сломался» из логов неразличимы. В новом дизайне affirmative/negative токен становится **несущим триггером**, поэтому оба исхода обязаны быть наблюдаемы — иначе диагностика нового механизма невозможна ровно там, где он работает.

**Приватность (норма BUG-086, сохраняется дословно):** только ключи args, никогда значения; текст сообщения пользователя не логируется даже усечённым. `arg_keys` вместо `args` — потому что `add_user_auth` несёт credential в значении. ⚠️ Норма распространяется **только на новые записи**: соседние `agent_tool_call` (agent.py L549-554) и `fsm_confirm_execute` (handlers.py L878-883) логируют `args` целиком — это существующий, не создаваемый этим слайсом класс экспозиции, и трогать его здесь не в скоупе (§4).

**Метрик (Prometheus) слайс не добавляет** — сознательно: при нулевом трафике счётчик не даст ничего, чего не даст structlog, а прецедент рядом (`record_bot_gemini_empty_parts`) заведён под другую задачу. Если трафик появится — отдельный слайс (§10 R2-m6).

### 3.7 Prompt + docs-правки (code+docs)

- **`prompts/bot.yaml`:** hard rule v1.9.3 (**L65**) содержит фразу «…a hand-written confirmation question following a `dry_run` report is exactly the BUG-086 dead-end (the user's «да» then has nothing to confirm)» — после замены это **ложно**: «да» будет что подтверждать. Переписать так, чтобы правило осталось запретом (не сочинять своё «Подтвердите» — framework владеет подтверждением), но без ложного обоснования. **Ограничение на переписывание (§10 R2-M3):** `TestPromptHardRule::test_hard_rule_separates_the_two_call_shapes` (F5-C **L1174-1182**) берёт **первую** строку промпта, содержащую «BUG-086», и требует в ней `dry_run=true`, `confirm=false`, «Подтвердите» и `BUG-009` — все четыре подстроки обязаны выжить в новой редакции строки.
- **Version-bump `1.9.3 → 1.9.4`:** **L2** (YAML-комментарий, тестом не пинится), **L8** (`metadata.version`), **L32** (`- Version:` внутри промпта) — плюс **L9**: `metadata.description` по конвенции файла получает новую **ведущую** клаузу `v1.9.4 …` перед существующей `v1.9.3 …` (§10 R2-m3). Пины (verified): `test_f9_phase2_prompt_defense.py` **L194** `startswith("1.9")` — держится; F5-C **L1163-1167** — второй такой же пин **плюс** `>= (1,9,3)` — держится; F5-C **L1169-1172** (`f"- Version: {version}" in prompt`) — это и есть механизм, который заставляет L8 и L32 совпадать; `test_bot_read_context.py` **L643** `>= (1,8,0)` — держится. Tool-count-guard'ов сейчас **четыре** (`test_bot_tools_v11.py` L99, `test_bot_tools_v12.py` L151, `test_f5c_bot_force_resummarize.py` L182, `test_f5c_bot_topic_history.py` L158, все `== 35`) — verified, этот slice их не трогает (tool'ов не добавляем).
- **`tools.py` L3221-3224** — комментарий про `agent._LLM_AUTHORED_CONFIRM_PATTERN` переписать (сам `next_step`-текст можно оставить: он безвреден и полезен LLM).
- **`docs/runbooks/F5C_DEPLOY_AND_WATCH.md`** — § «BUG-086 — bot confirm-recovery guard» (**L327-349**, verified: заголовок L327, следующий заголовок L351; после исполнения плана на её месте — § «#359 / ADR-0020 — deterministic confirm trigger»): watch-поле `read_only_intent` **и вся таблица трёх `llm_authored_confirm_*` событий** удаляются (событий больше не существует), вместо них — новые события §3.6. Историческую § «Deploy record — BUG-086» (L17-57) **не трогать** — это запись о состоявшемся деплое.
- **`BUG_LOG.md` § BUG-086** — новая строка «Architectural replacement (2026-07-31)» + пометка в строке «Follow-up (deferred…)» что #359 закрыт этим slice'ом.

### 3.8 Тесты: что удаляется, что переписывается, что обязано выжить дословно

**Обязано выжить БЕЗ ИЗМЕНЕНИЙ (behaviour pins):**

| Тест / класс | Файл | Почему |
|---|---|---|
| `TestPreviewSuppressingArgRegistryIsComplete` (2 теста) | `test_bot_confirm_flow.py` **L1399** | **Ключевой вывод:** переиздание по-прежнему обязано вырезать report-only-флаги ⇒ `_PREVIEW_SUPPRESSING_ARGS` остаётся живым реестром, а tripwire — единственным способом поймать будущий tool, который молча переоткроет класс. Не трогать |
| `TestDryRunIsTerminal` (3 теста: L502 / L523 / L550) | `test_f5c_bot_force_resummarize.py` **L499** | dry-run по-прежнему не `preview: True`, `dry_run+confirm` по-прежнему `InvalidArguments`. Зависит от decision 7 (§7) |
| §§ 1-8 `test_bot_confirm_flow.py` (BUG-032 токены, BUG-009 gate, TTL, unknown-token) | `test_bot_confirm_flow.py` | классификатор становится **более** нагруженным ⇒ его пины ценнее, чем раньше |
| `TestWriteToolsContract` — `test_guard_set_matches_known_baseline` (L336) / `…forward…` (L317) / `…reverse…` (L327) | `test_bot_execute_tool_guard.py` **L302** | набор tool'ов не меняется (16), count-guard'ы (35) не трогаются |
| `TestPromptHardRule::test_version_bumped_within_the_1_9_pin` (L1163) и `…::test_version_consistent_in_system_prompt` (L1169) | `test_f5c_bot_force_resummarize.py` **L1153** | **пропущены в первой редакции (§10 R2-M3).** Оба зелёные на `1.9.4`; второй — единственное, что заставляет L8 и L32 совпасть |

**Переписывается (subject сохраняется, триггер меняется):**

| Тест | Было | Станет |
|---|---|---|
| `TestLlmAuthoredConfirmRecoveryIsToolAgnostic::test_recovery_arms_confirm_flow_for_a_non_dry_run_write_tool` (`test_bot_confirm_flow.py` L1340) | проза «Подтвердите …» после BUG-009-rejection ⇒ arming в том же turn'е | тот же `remove_channel`-сценарий, но arming на **втором сообщении** «да»; инвариант «recovery никогда не возвращает `confirm`» сохраняется дословно. **Класс не удалять** — class-wide generality по 16 tool'ам и есть несущий контракт |
| `…::test_recovery_does_not_fire_when_a_real_preview_armed` (L1372) | ровно один round-trip | + «snapshot не создан, когда настоящий preview вооружён» |
| `TestLlmAuthoredConfirmRecovery::test_prod_trace_…` (F5-C L567) | one-turn recovery | двухсообщенческий прод-трейс: T1 → snapshot, T2 «да» → armed |
| `…::test_confirm_true_rejection_also_recovers` (L606) | то же | двухсообщенческая форма |
| `…::test_dry_run_without_confirm_ask_stays_terminal` (L633) | «нет ask ⇒ terminal» | «turn ничего не вооружает» (остаётся верным) **+** snapshot присутствует — семантика turn'а изменилась, тест обязан это зафиксировать явно |
| `…::test_recovery_gives_up_when_no_preview_obtainable` (L661) | молчаливый `None` | детерминированное сообщение пользователю + `write_intent_router_failed` (§9 M2) |
| `…::test_read_only_turn_never_triggers_the_guard` (L769) | guard не сработал | turn ничего не вооружает; snapshot есть, но без «да» безвреден |
| `…::test_real_preview_turn_is_untouched` (L790) | — | + snapshot не создан |
| `…::test_shadow_verdict_is_logged_and_the_message_text_is_not` (L872) | shadow-вердикт + приватность | **приватностную половину сохранить**, переписав на новые записи: `arg_keys` присутствуют, значения args и текст сообщения — нет |
| `TestPromptHardRule::test_hard_rule_separates_the_two_call_shapes` (L1174) | assert'ы по строке L65 | **пропущен в первой редакции (§10 R2-M3).** Переписывается **вместе** с bot.yaml L65: четыре подстроки (`dry_run=true`, `confirm=false`, «Подтвердите», `BUG-009`) сохраняются, ложное обоснование из assert'ов не пинилось и не появляется |

**Удаляется:**

| Тест / класс | Файл | Кол-во |
|---|---|---|
| `TestLlmAuthoredConfirmDetector` — всё, **кроме** `test_dry_run_is_registered_as_preview_suppressing` | F5-C L980 | **10** |
| `TestReadOnlyIntentClassifier` | F5-C L904 | **4** |
| `TestLlmAuthoredConfirmRecovery::test_read_only_user_message_still_recovers_shadow_mode` | F5-C L849 | **1** |
| `test_dry_run_paraphrasing_the_next_step_hint_stays_terminal` / `…_confirm_infinitive_stays_terminal` | F5-C L686 / L727 | **2** → корпус переезжает в новый инвариант-класс (ниже) |
| импорты `_looks_like_llm_authored_confirm` / `_looks_like_read_only_request` | F5-C L53-54 | — |
| `_GUARD_LOG_EVENTS` | F5-C L495 | — |
| упоминание `read_only_intent=` в **docstring модуля** F5-C | F5-C L33 | — (пропущено в первой редакции, §10 R2-m4) |

`test_dry_run_is_registered_as_preview_suppressing` (L1148) **переезжает** в живой класс (реестр остаётся нормативным). Общий хелпер `_prod_trace_turn` (F5-C **L823-847**) используется и удаляемым L849, и переписываемым L872 — **сохранить**, адаптировав под двухсообщенческую форму. `_PROD_SELF_AUTHORED_CONFIRM` (L486) тоже **сохраняется** — он переезжает в корпус `TestFinalTextNeverArmsConfirmFlow`.

**Сирот после удаления слоя (d) нет — verified:** `rg` по дереву даёт ровно два потребителя удаляемых символов вне `agent.py` — `tests/test_f5c_bot_force_resummarize.py` (строки 33, 53-54, 494-495, 860, 894-896, 907, 916, 985) и комментарий `tools.py` L3224. Все перечислены в реестре выше.

**Новое:**

| Класс / тест | Что пинит |
|---|---|
| `TestFinalTextNeverArmsConfirmFlow` | **Главный новый инвариант и достойный наследник пяти precision-проходов.** Параметризован объединённым корпусом: `_PROD_SELF_AUTHORED_CONFIRM`, шесть «ask»-форм четвёртого прохода, семь `next_step`-пересказов, шесть клаузных вариантов пятого прохода, плюс «чужой текст» — процитированный пост с «Подтвердите … [да/нет]» (**вектор (b) из issue, ранее непокрываемый**). Утверждение для **каждого**: turn вооружает `ConfirmFlow` ровно тогда, когда пользователь напечатал affirmative token, и **никогда** — из-за текста turn'а. Один тест доказывает то, чего пять проходов добивались приближением |
| `TestWriteIntentSnapshotLifecycle` | создание (T1); TTL-истечение; drop на unrelated (adjacency); drop на arming любого FSM; negative → «❌ Отменено.» + событие; args в snapshot'е без `confirm`/`dry_run` |
| `TestWriteIntentAndConfirmFlowAreMutuallyExclusive` | четыре инварианта таблицы §3.2; в частности: при armed ConfirmFlow «да» идёт в ConfirmFlow, а не в router |
| `TestWriteIntentSurvivesNoTurn` (**новый, §10 R2-B1**) | pop-at-top: snapshot не переживает **ни один** путь `handle_text` — armed `PaginationFlow` + «ещё» (L1354), подсказка L1382, ConfirmFlow-гейт L637, Clarify-гейт L646, `True` от любого из трёх pre-router'ов L663/L671/L679. После каждого — snapshot'а в FSM нет |
| `TestWriteIntentRouterPrecedenceMatrix` | **BUG-047-D1 пин:** активный `delete_intent` + **нет** snapshot'а ⇒ «да» инертно (сегодняшнее поведение); + snapshot ⇒ resume. Плюс нейтральность порядка: ни один из 18+14 токенов не матчит `DELETE_VERB_PATTERN` / `ANAPHORA_PATTERN` / `COMMAND_VERB_PATTERN`; **отдельный кейс «да, последнюю» + non-stale `last_subscription`** — уходит в delete-pre-router, а не в наш (§10 R2-B2) |
| `TestCompoundAffirmativeIsNotATrigger` (**переименован и инвертирован, §10 R2-B2**) | «да, давай» / «да genotek» / «да, покажи темы X» / «нет, покажи другое» ⇒ `unrelated`: snapshot дропнут, `ConfirmFlow` **не** вооружён, turn ушёл к агенту (запрос пользователя не потерян). Осознанное **расхождение** с `_handle_confirmation_response`, а не зеркалирование |
| `TestWriteIntentResumeRechecksAuthorization` (**новый, §10 R2-M4**) | snapshot создан админом → `current_user` понижен до `user` → «да» ⇒ `PermissionDenied`-текст + `write_intent_router_failed`, `ConfirmFlow` не вооружён, мутации нет. Плюс: `current_user is None` ⇒ router возвращает `False` и **не** переиздаёт (иначе фолбэк `get_default_admin()`, tools.py L3168) |
| `TestCancelPathIsObservable` | `fsm_confirm_declined` присутствует с `tool`; отказ отличим от поломки |
| `TestWriteIntentLogPrivacy` | `arg_keys` есть, значения args нет, текст сообщения нет (наследник удаляемого shadow-теста) |

### 3.9 Red→green + mutation-верификация (норма проекта)

**Режимы прогона ([`tests/README.md`](../../tests/README.md)):** трогаем bot-код ⇒ **PR standard обязателен**: `TEST_POSTGRES=1 .venv/bin/python -m pytest -q`. Базовая линия на `19e312a` по § 11 F5-C-документа — **4052 passed / 22 skipped / 2 deselected**; итоговое число пересчитать фактическим прогоном (не выдумывать: удаляется ~17 тестов, добавляется ~12-15 — точная арифметика выводится из §3.8 в момент реализации).

**Порядок red→green:**
1. **RED** — новый двухсообщенческий тест (T1 snapshot → T2 «да» → armed ConfirmFlow) против текущего дерева: падает (`AgentResult` не имеет поля, «да» проваливается к агенту).
2. **GREEN A** — `AgentResult.write_intent_pending` + заполнение в `agent.py`. Handler-часть теста ещё красная.
3. **GREEN B** — `PendingWriteIntentData` + `_set/_for_router/_clear` + `_handle_write_intent_router` + вызов в `handle_text`. Тест зелёный.
4. **RED→GREEN** по каждой ветке отдельно: negative, unrelated-drop, TTL, failure-path, mutual exclusion, precedence-matrix, privacy, cancel-observability.
5. Только теперь — удаления §3.3 + §3.8 и новый `TestFinalTextNeverArmsConfirmFlow`.
6. Prompt-bump + docs.

**Mutation-верификация (обязательна по норме BUG-086 «Mutation-verified: …» — показать, что откат правки роняет *ровно* задуманные тесты):**

| Мутация | Обязано упасть |
|---|---|
| убрать вызов `_handle_write_intent_router` из `handle_text` | только resume-тесты, с точным прод-симптомом (`current_state is None`, «да» → stateless-агент) |
| перенести pop snapshot'а из начала `handle_text` внутрь роутера | только `TestWriteIntentSurvivesNoTurn` (§10 R2-B1) |
| поставить set-site отдельным `if` вместо ветки цепочки L761-826 | только pagination+snapshot кейс в `…SurvivesNoTurn` (§10 R2-M1) |
| заменить tier-1-гейт на `classify_confirmation_token` целиком | только `TestCompoundAffirmativeIsNotATrigger` (§10 R2-B2) |
| заменить `_is_stale(…, PENDING_TTL_SECONDS)` на `_is_pending_expired` | только TTL-тест с отсутствующим/битым `created_at` (§10 R2-M2) |
| не передавать `current_user` в `execute_tool` при resume | только `TestWriteIntentResumeRechecksAuthorization` (§10 R2-M4) |
| убрать adjacency-drop (оставить только TTL) | только «unrelated → потом «да»» тест |
| вернуть `confirm` в переизданные args | только BUG-009-инвариант в `…IsToolAgnostic` |
| перестать вырезать `dry_run` | только dry-run-resume-тест (executor вернёт report ⇒ `write_intent_router_failed`) |
| логировать `args` целиком или текст сообщения | только `TestWriteIntentLogPrivacy` |
| убрать `fsm_confirm_declined` | только `TestCancelPathIsObservable` |
| **вернуть детектор рядом с router'ом** (оба механизма) | `TestFinalTextNeverArmsConfirmFlow` — это защита от «фазового» внедрения (§9 m5) |

**Ops-gate:** `uv run ruff check .` + `uv run ruff format --check .` + `TEST_POSTGRES=1 uv run pytest -q`. Deploy — no-migration: `docker compose build tg_parser` → `docker compose up -d --no-deps tg_bot` (**re-create, не restart** — BUG-078). Smoke: happy path (`confirm=false` → preview → «да») **и** degraded path (dry-run-форма → «да» → preview → «да»).

---

## 4. Out of scope (жёстко)

- **Любой backend** (`ResummarizationService`, репозитории, `assert_admin`) — не трогать; slice живёт в bot-adapter (ADR-0004 / ADR-0006).
- **MCP / CLI surface** — не трогать. Решение по `dry_run` (§7 D7) касается **только** bot-декларации; CLI `--dry-run` и MCP-паритет не затрагиваются ни в одном варианте.
- **Состав `_WRITE_TOOLS_REQUIRING_CONFIRM`**, tool-count guard'ы (35), `test_bot_execute_tool_guard.py` baseline — не меняются.
- **Промежуточный фикс layer (d)** («compute the verdict before the gate») — **не делать** (§3.4, §9 m5).
- **Фазовое внедрение** «детектор + router одновременно» — запрещено (§9 m5): два механизма смогут вооружить один и тот же preview.
- **Расширение словаря токенов** (`AFFIRMATIVE_TOKENS`) — отдельное решение, не в этом slice'е.
- **RedisStorage / multi-replica** — MemoryStorage остаётся; snapshot умирает с контейнером, как `pending_action`.
- `docs/methodology/**`, `pyproject.toml`, `requirements.txt`, редактирование issue #359, `git commit` без явного запроса.

---

## 5. Acceptance criteria

- [ ] `AgentResult.write_intent_pending` заполняется **ровно** в состоянии «confirm-gated write-вызов без preview И ничего не вооружено»; args санитизированы (`confirm` + `_PREVIEW_SUPPRESSING_ARGS` вырезаны); проза turn'а не читается нигде.
- [ ] Прод-трейс BUG-086 (dry-run-форма на mutation-запрос) проходит за три turn'а: T1 отчёт+snapshot → T2 «да» → **настоящий** preview + `fsm_confirm_armed` → T3 «да» → `fsm_confirm_execute`.
- [ ] Happy path (`confirm=false`) — **одно** подтверждение, ровно один round-trip executor'а; snapshot не создаётся.
- [ ] Class-wide: контракт проверен на tool'е **без** `dry_run` (`remove_channel`, preview-less вызов через BUG-009-rejection).
- [ ] `confirm=True` ставит **только** FSM-confirm-turn (BUG-009 бит-в-бит); переизданные args никогда не содержат `confirm`.
- [ ] Два механизма подтверждения не могут быть вооружены одновременно (четыре инварианта §3.2, каждый — тест).
- [ ] Adjacency **структурна**: snapshot снимается из FSM в начале `handle_text` и не переживает ни один путь обработки turn'а (включая ранние return'ы L637/L646/L652 и `True` от pre-router'ов L663/L671/L679) — §10 R2-B1.
- [ ] Триггер — **только tier-1** (полная нормализованная форма ∈ токен-сетам); любой компаунд ⇒ snapshot дропнут и turn ушёл к агенту, запрос пользователя не потерян — §10 R2-B2.
- [ ] TTL считается через `_is_stale(created_at, PENDING_TTL_SECONDS)`; snapshot с отсутствующим/битым `created_at` считается протухшим (fail-safe) — §10 R2-M2.
- [ ] Авторизация перепроверяется на T2: демоушен между T1 и T2 ⇒ `write_intent_router_failed`, мутации нет; `current_user is None` ⇒ router не переиздаёт (фолбэк `get_default_admin()` недостижим) — §10 R2-M4.
- [ ] Snapshot не содержит ни `current_user`, ни роли — только `tool_name` + санитизированные args; TTL 5 мин; unrelated-сообщение снимает snapshot молча.
- [ ] Affirmative при недостижимом preview → детерминированное сообщение + `write_intent_router_failed` (никогда не молчание).
- [ ] Negative → «❌ Отменено.» + `write_intent_declined`; ConfirmFlow-отказ → `fsm_confirm_declined` (пробел issue § 3 закрыт).
- [ ] Три регулярки, `_recover_llm_authored_confirm` и весь shadow-слой (d) удалены; `_PREVIEW_SUPPRESSING_ARGS` и его tripwire живы и не вакуумны.
- [ ] `TestFinalTextNeverArmsConfirmFlow` покрывает объединённый корпус пяти проходов **плюс** вектор (b) (чужой процитированный текст).
- [ ] Логи: только `arg_keys`; значения args и текст сообщения отсутствуют во всех новых записях.
- [ ] `bot.yaml` = `1.9.4` синхронно L2/L8/L32 + новая клауза в `description` (L9); hard rule не содержит ложного обоснования, но сохраняет `dry_run=true` / `confirm=false` / «Подтвердите» / `BUG-009`; **оба** `startswith("1.9")`-пина (`test_f9_phase2_prompt_defense.py` L194 и F5-C L1163) и tuple-floor'ы зелёные.
- [ ] Mutation-верификация выполнена по таблице §3.9 — каждая мутация роняет **ровно** заявленные тесты.
- [ ] `ruff check` + `ruff format --check` + `TEST_POSTGRES=1 pytest -q` — green; изменение числа тестов объяснено реестром §3.8.
- [ ] Нет schema/contract/deps/migration изменений; backend и MCP/CLI не тронуты.
- [ ] Commit / PR — только по явному запросу owner'а.

---

## 6. Quality / ops gate commands

```bash
# repo quality (всегда)
uv run ruff check .
uv run ruff format --check .

# PR standard — обязателен (трогаем bot)
TEST_POSTGRES=1 uv run pytest -q

# точечно
uv run pytest -q tests/test_bot_confirm_flow.py \
  tests/test_f5c_bot_force_resummarize.py \
  tests/test_bot_execute_tool_guard.py \
  tests/test_bot_tools_v11.py tests/test_bot_tools_v12.py \
  tests/test_f9_phase2_prompt_defense.py tests/test_bot_read_context.py

# Runner note: tests/README.md предпочитает `.venv/bin/python -m pytest`; `uv run pytest` — принятый эквивалент.

# Deploy (NO-migration, bot-adapter only)
docker compose build tg_parser
docker compose up -d --no-deps tg_bot     # RE-CREATE, НЕ restart (BUG-078)
# smoke 1 (happy): «пере-суммаризируй тему X» → preview → «да» → ok
# smoke 2 (degraded): вынудить dry-run-форму → «да» → preview → «да» → ok
# smoke 3 (cancel): preview → «нет» → «❌ Отменено.» + fsm_confirm_declined в логе
```

---

## 7. Decisions

**Baked (обоснованы дизайном, не данными — см. governing constraint):**

1. **D1 — заменяем, а не тюним.** Шестого regex-прохода не будет: два оставшихся FP-вектора регуляркой недостижимы (свободный порядок слов; чужой текст в итоговом тексте turn'а).
2. **D2 — триггер = закрытый словарь пользователя.** `classify_confirmation_token` (18 affirmative / 14 negative), без нового классификатора и без расширения словаря.
3. **D3 — форма по локальному прецеденту.** Snapshot + детерминированное возобновление, как `delete_intent` (BUG-048) / `subscribe_intent` (BUG-050); никакого нового паттерна.
4. **D4 — adjacency + 5-минутный TTL**, а не 15-минутное «переживание» промежуточных turn'ов. Сознательное отличие от прецедента, обоснование §3.1 / §9 B2.
5. **D5 — layer (d) удаляется целиком** (§3.4), промежуточный observability-фикс не делается.
6. **D6 — замена атомарна.** Детектор и router не сосуществуют ни в одном коммите, попадающем в прод.
7. **D8 — `_PREVIEW_SUPPRESSING_ARGS` остаётся нормативным реестром** вместе с tripwire-тестом: это единственный механизм, которым будущий tool с report-only флагом не сможет молча сломать переиздание.

**Решено owner'ом:**

- **D7 (было открыто в issue #359) — ✅ `dry_run` ОСТАЁТСЯ в BOT-декларации `force_resummarize` (решение owner'а 2026-07-31).** CLI/MCP-паритет не затрагивается ни в одном варианте. Таблица ниже — обоснование, оставлено для трассируемости.

| | Оставить (**рекомендация**) | Убрать из bot-декларации |
|---|---|---|
| UX | сохраняется «покажи, что будет без запуска» — форма, которую прод **реально** использовал корректно (26.07 07:50:55) | пропадает из бота; остаётся в CLI/MCP |
| Источник неоднозначности | сохраняется: LLM по-прежнему выбирает между двумя формами (вероятностно, `mode=AUTO`) | устраняется **в источнике** |
| Нужен ли snapshot-механизм | да | **да, всё равно** — preview-less turn остаётся достижимым через BUG-009-rejection и через ошибки executor'а. Удаление `dry_run` **не** позволяет удалить механизм |
| `_PREVIEW_SUPPRESSING_ARGS` | остаётся живым реестром; tripwire защищает будущие tool'ы | реестр становится **пустым/вакуумным** ⇒ `test_registry_is_not_vacuous` падает, а class-wide tripwire теряет смысл — потеря защиты для tool'ов, которых ещё нет |
| Цена | ~2 строки санитизации, которые дизайн делает всё равно (`confirm` вырезается безусловно) | правка декларации + `bot.yaml` + `TestDryRunIsTerminal::test_declaration_dry_run_description_states_the_contract` + регресс задокументированного owner-решения о CLI-паритете |

**Рекомендация: ОСТАВИТЬ.** Ключевой аргумент — новый дизайн убирает именно то, что делало `dry_run` опасным: FP-класс существовал потому, что framework **интерпретировал прозу отчёта**; когда триггером становится ответ пользователя, второй call-shape перестаёт быть источником ложных arming'ов. А удаление `dry_run` не даёт главного выигрыша (механизм всё равно нужен) и при этом обнуляет живой tripwire. **✅ Owner согласился 2026-07-31 — `dry_run` остаётся; D7 закрыт, реализация идёт по левой колонке.** Следствия для slice'а: `TestDryRunIsTerminal` сохраняется (**§3.8**), декларация и `_PREVIEW_SUPPRESSING_ARGS` не меняются, отдельной правки `bot.yaml` под удаление флага не требуется.

> **Round-2 замечание к строке «Источник неоднозначности» (§10 R2-B2):** «сохраняется» здесь стоит читать буквально. Пока `dry_run` в декларации, честный read-only turn остаётся достижимым, а значит **snapshot ставится и на нём тоже** — и вся защита от «пользователь просил отчёт, а получил мутационный preview» держится на tier-1-триггере. Это не аргумент против D7, но это цена, которую D7 оплачивает именно tier-1-правилом, а не «дизайн убрал класс целиком».

---

## 8. Нужен ли новый ADR? — **ДА. ✅ ЗАВЕДЁН 2026-07-31: [ADR-0020](../adr/0020-deterministic-confirmation-triggers.md), статус `Proposed`**

> **Решение owner'а 2026-07-31.** ADR заведён по outline ниже; в него внесены обе поправки round-2 (§10): tier-1-only триггер (§2 ADR) и pop снапшота в начале `handle_text` + fail-closed TTL (§3 ADR). Перевод в `Accepted` — после мержа slice'а. Outline сохранён ниже для трассируемости.

Формально не обязателен: ни один accepted ADR не описывает bot-FSM / confirm-протокол, схемы `docs/contracts/` не затронуты, deps не меняются — по прецеденту F5-C-слайса («surface-only ⇒ ADR не нужен») можно обойтись. **Но** этот slice впервые формулирует принцип, который будет цитироваться каждым будущим write-tool'ом и без которого следующий автор с высокой вероятностью снова напишет prose-детектор. Именно такие долгоживущие ограничения ADR и фиксирует.

**Черновик — ADR-0020 «Deterministic confirmation triggers: closed user vocabulary over LLM-prose inference»:**

- **Context.** Framework вооружает `ConfirmFlow` только из `{"preview": True}` (BUG-002/-009/-046). Report-only форма внутри confirm-gated write-tool'а создаёт preview-less turn (BUG-086), и первая попытка ремонта предсказывала «просьбу подтвердить» по прозе LLM: шесть FP-векторов за четыре раунда, три из них морфологические, два структурно недостижимы регуляркой.
- **Decision.** (1) Framework **никогда** не выводит control flow из прозы, сгенерированной LLM. (2) Детерминированные триггеры берутся из **закрытого словаря, который печатает пользователь** — и там, где пользователю **не** был показан явный вопрос подтверждения, триггером считается **только точное совпадение** с токеном, а не первый токен компаунда (§10 R2-B2). (3) Восстановление после preview-less write-вызова делается через persisted snapshot + строго смежное подтверждение, причём смежность обеспечивается **снятием snapshot'а на входе в обработчик**, а не дисциплиной clear-сайтов (§10 R2-B1). (4) Report-only флаг на confirm-gated write-tool'е обязан быть в `_PREVIEW_SUPPRESSING_ARGS` (tripwire в CI). (5) Persisted intent **никогда** не несёт identity/роль — авторизация перепроверяется на исполнении (§10 R2-M4).
- **Consequences.** Деградированный путь стоит пользователю двух подтверждений (форма уже отгружена в BUG-047 `delete_suggest`). Ложный триггер невозможен без явного действия пользователя, а его худший исход — preview (0 токенов / 0 записей). Морфологический класс дефектов исчезает вместе с подходом. Affirmative token получает третье значение на уровне handler'а ⇒ обязательна проверяемая mutual exclusion.
- **Alternatives rejected.** Шестой regex-проход (не достаёт до (a)/(b)); enforcing layer (d) (второй угадывающий классификатор, чей FP-rate структурно неизмерим); удаление `dry_run` как единственная мера (не убирает необходимость механизма).
- **Status.** ✅ Заведён 2026-07-31 как [`docs/adr/0020-deterministic-confirmation-triggers.md`](../adr/0020-deterministic-confirmation-triggers.md) в статусе `Proposed`. D7 закрыт (`dry_run` остаётся); перевод в `Accepted` — после мержа slice'а.

---

## 9. Self-review — adversarial pass над **собственным** initial-планом

Метод: пофайловое перечитывание каждого якоря на `19e312a`; проверка каждого утверждения брифа и issue **против кода**, а не против BUG_LOG; отдельная проверка «выживет ли шаг при контакте с деревом». Найдено **2 BLOCKER + 4 MAJOR + 5 MINOR**; **два решения дизайна изменены**, оба отмечены явно.

1. **(BLOCKER B1) Атрибуция прецедента в issue #359 и в брифе — неверная.** Issue пишет «`_handle_delete_intent_router` and `_handle_subscribe_intent_router` … (BUG-047 / BUG-031)». Код говорит другое: persisted `delete_intent` + его router — **BUG-048 Part A** ([`states.py`](../../tg_parser/bot/states.py) L120-149, [`handlers.py`](../../tg_parser/bot/handlers.py) L2362), а `subscribe_intent` — **BUG-050** (`states.py` L152, `handlers.py` L2423). BUG-047 — это delete **pre-router**/анафора (немедленное разрешение, без persisted snapshot'а), BUG-031 — двухфазный subscribe-гейт. Мой первый черновик скопировал атрибуцию из issue ⇒ реализатор пошёл бы читать не тот прецедент (BUG-047 разрешает цель **в том же turn'е**, что как раз **не** нужная нам форма). Исправлено в SoT / §1 / §2.
2. **(BLOCKER B2) Семантика TTL у прецедента ПРОТИВОПОЛОЖНА нужной — это изменило решение дизайна.** `delete_intent` / `subscribe_intent` намеренно живут 15 минут и **переживают** промежуточные turn'ы и `state.clear()` (`handlers.py` L1811, L1862; snapshot-and-restore L908-931). Первый черновик «зеркалил прецедент» и брал ту же семантику. Это дефект: их триггер — конкретное имя, наш — «да». Snapshot, переживший три посторонних turn'а, превратил бы любое позднее «да» в мутационный preview — тот же FP-класс, от которого мы уходим, лишь перенесённый во время. **Решение изменено:** TTL = `PENDING_TTL_SECONDS` (300 с, как ConfirmFlow) **плюс строгая adjacency** (snapshot живёт ровно до следующего сообщения). §3.1, D4.
3. **(MAJOR M1) Snapshot физически не виден handler'у — брифом это не покрыто.** `unpreviewed_write_calls` — локальная переменная `process_message` (`agent.py` L413), а `AgentResult` (L276-326) не имеет подходящего поля. Без нового хинта router нечего читать. Добавлен step 1. Попутно найдены **два return'а агента, которые snapshot не поставят**: clarify-early-return (L683-688) и исчерпание `MAX_AGENT_TURNS` (L692-702). Первый — не пробел, а требование mutual exclusion (clarify вооружает свой FSM); второй сохраняет сегодняшнее поведение. Оба задокументированы как осознанные (§3.1), а не «забыты».
4. **(MAJOR M2) Failure-path меняет смысл, и молчание становится новым дефектом.** Сегодня `_recover_llm_authored_confirm` при недостижимом preview возвращает `None` — корректно: текст LLM уже отправлен, пользователь ничего не ждёт. В новом дизайне пользователь **напечатал «да»** и ждёт ответа: тот же `None` даёт молчание, т.е. dead-end собственного производства — ровно класс BUG-032/-046, который весь этот код и закрывает. Добавлены обязательный детерминированный текст + `write_intent_router_failed` (§3.5), и переписан соответствующий тест.
5. **(MAJOR M3) Реестр тестов был разложен неправильно в двух местах.** (a) `TestPreviewSuppressingArgRegistryIsComplete` (`test_bot_confirm_flow.py` L1399) в черновике попал в «удалить вместе с детектором» — **ошибка**: переиздание по-прежнему вырезает `dry_run`, значит `_PREVIEW_SUPPRESSING_ARGS` живёт и tripwire обязан остаться **без изменений**. (b) `TestLlmAuthoredConfirmRecoveryIsToolAgnostic` (L1312) — наоборот, стоял в «удалить»: его subject (class-wide покрытие всех 16 tool'ов, а не только `force_resummarize`) и есть несущий контракт; меняется только триггер ⇒ **переписать, не удалять**. Это прямой ответ на вопрос задачи про § 9.
6. **(MAJOR M4) Prompt-правка пропущена и в issue, и в брифе.** `prompts/bot.yaml` L65 (hard rule v1.9.3) утверждает «…the user's «да» then has nothing to confirm» — после замены это **ложно**; system prompt начал бы лгать LLM о механике framework'а. ⇒ правка + bump `1.9.3 → 1.9.4` в трёх местах. Заодно проверено расположение: in-prompt `- Version:` теперь **L32**, а не L31, как указано в sibling-плане (сдвинулось из-за capability #15), а tuple-floor в `test_bot_read_context.py` — **L643**, а не L642 — ещё один урок «пины сдвигаются, проверяй фактом, а не предыдущим планом». Плюс `tools.py` L3221-3224 ссылается в комментарии на удаляемый `agent._LLM_AUTHORED_CONFIRM_PATTERN`.
7. **(MINOR m1) «about a dozen tokens» — заниженная оценка.** Фактически `AFFIRMATIVE_TOKENS` = **18**, `NEGATIVE_TOKENS` = **14** (32 всего). Дизайн не меняется (словарь всё равно закрытый), но в плане приведены реальные числа: словарь, который придётся держать в голове при ревью, крупнее, чем звучит в issue.
8. **(MINOR m2) tier-2 классификатора расширяет триггер сильнее, чем «bare token».** `classify_confirmation_token` (L488) берёт первый токен со снятой пунктуацией, поэтому «да, давай» **и** «да genotek» / «да, удали канал X» классифицируются как affirmative. Первый черновик молча предполагал строгий bare-token. Проверено: `_handle_confirmation_response` ведёт себя **точно так же уже сегодня** (new-intent-escape L861 не срабатывает на классифицированном токене, L510) ⇒ решение: зеркалить существующий handler дословно и **запинить** это как осознанное следствие, а не вводить второе, расходящееся правило классификации.
9. **(MINOR m3) Бриф ссылается на `AGENT_PLAYBOOK.md` как на источник red→green/mutation-процедуры — там этого нет.** Playbook (перечитан целиком) описывает lifecycle `docs/quality/` (INBOX → incident → TRIAGED → sprint) и явно запрещает автокоммит; ни красно-зелёного цикла, ни mutation-верификации в нём нет. Эта норма живёт в практике BUG_LOG (§ BUG-086, «Mutation-verified: …» в каждой строке о precision-проходах) и в `tests/README.md` (режимы). План ссылается на **правильный источник для каждого** пункта и не приписывает playbook'у того, чего в нём нет.
10. **(MINOR m4) «Порядок роутеров нейтрален» — было утверждением, стало проверкой.** Проверил каждый из 18+14 токенов против `DELETE_VERB_PATTERN` (L112), `ANAPHORA_PATTERN` (L121), `COMMAND_VERB_PATTERN` (L164): совпадений нет; плюс оба существующих роутера сами возвращают `False` на любом классифицированном токене (L2393, L2461). ⇒ порядок — вопрос читаемости, и он **пинится тестом** (`TestWriteIntentRouterPrecedenceMatrix`), а не комментарием. Там же выяснилось, что нужен отдельный пин **BUG-047-D1**: контракт «стray «да» инертно» продолжает действовать в состоянии «есть `delete_intent`, нет snapshot'а», и новый механизм не должен его размывать.
11. **(MINOR m5) Соблазн фазового внедрения — вредный; и промежуточный фикс из комментария issue делать не нужно.** Комментарий #359 предлагает «ahead of the replacement» считать `read_only_intent` до гейта. Это (а) работа ради измерения, которое замена отменяет, и (б) при трафике = 0 всё равно ничего не измерит. Опаснее другое: если оставить детектор рядом с router'ом «на время наблюдения», **два** механизма смогут вооружить один и тот же preview — детектор в T1 и router в T2, — и появится новый гибридный класс дефектов. ⇒ D6 «замена атомарна» + mutation-пин, который ловит одновременное существование обоих.
12. **(изменение дизайна по итогам self-review) Отказ от «подсказки» в T1.** Первый черновик добавлял в T1 детерминированный суффикс «Чтобы запустить — ответьте «да»». Отброшено: суффикс печатался бы и на **честном** dry-run-turn'е, т.е. подталкивал бы к мутации пользователя, который попросил отчёт — это возвращает read-only-intent-проблему, только из входного канала в выходной. T1 остаётся неизменным: framework перестаёт **читать** просьбу LLM, но не мешает ей стоять как обычному тексту — а если LLM ничего не спросил, спонтанное «да» пользователя всё равно работает.

**Подтверждено пофайловым чтением (утверждения брифа/issue, оказавшиеся точными):**
13. Санитизация в guard'е действительно вырезает `confirm` **и** `_PREVIEW_SUPPRESSING_ARGS` (L738-742) — предпосылка брифа верна.
14. Observability GAP описан точно: гейт `return None` на L734 стоит **выше** вычисления `read_only_intent` на L745.
15. Cancel-path действительно без событий: negative-ветка L935-961 не содержит ни одного `logger.*`, тогда как affirmative пишет `fsm_confirm_execute` (L878), а unknown — `fsm_confirm_unknown_token` (L969). Единственный след — `request_completed` из `LoggingMiddleware` (L210).
16. Три регулярки и все пять проходов действительно не имеют потребителей вне `agent.py` и одного тест-файла (`rg` по дереву) — удаление не тянет за собой скрытых зависимостей.
17. `ChatSerializationMiddleware` (L140, lock L179-181) сериализует обработку per-(bot, chat) ⇒ read-modify-write snapshot'а гоночно безопасен; отдельной блокировки не нужно.
18. Blast radius — **16** tool'ов `_WRITE_TOOLS_REQUIRING_CONFIRM` (L110-163), не один `force_resummarize`; §11 исходит из этого. *(Ссылка перенумерована в round 2 — секция рисков стала §11; текст саморевью не менялся.)*

---

## 10. Independent review (round 2, 2026-07-31)

Метод: независимый adversarial-проход **вторым** агентом, без доступа к рассуждениям автора §9. Проверено пофайлово на `19e312a`: **каждая** L-ссылка, каждое имя теста, каждый счёт (16 tool'ов, 4 tool-count-гварда, 18/14 токенов, три version-сайта), плюс отдельные проходы по (a) авторизации на resume, (b) полноте mutual exclusion, (c) реальной семантике `classify_confirmation_token`, (d) сиротам после удаления слоя (d). Найдено **2 BLOCKER + 5 MAJOR + 6 MINOR**; **два решения дизайна изменены** (оба отмечены явно и оба отменяют пункты §9). §9 сохранён дословно — там, где round 2 расходится с round 1, расхождение зафиксировано здесь, а не правкой саморевью.

**Что проверено и оказалось верным** (чтобы не смешивать «не проверено» с «проверено и в порядке»): все L-ссылки §2 и §12 на `agent.py` / `handlers.py` / `states.py` / `tools.py` / `middleware.py` / `main.py` — **точны**; `_WRITE_TOOLS_REQUIRING_CONFIRM` = **ровно 16** (L110-163); `AFFIRMATIVE_TOKENS` = **18**, `NEGATIVE_TOKENS` = **14**; tool-count-гвардов **ровно четыре** и все `== 35`; `startswith("1.9")` и `>= (1,8,0)` — на местах; version-сайты **L2 / L8 / L32** (L31 действительно устарел); все имена тестов F5-C и `test_bot_confirm_flow.py` § 9 с их L-номерами — **совпадают**, включая арифметику «удалить 10 из 11 в `TestLlmAuthoredConfirmDetector`»; baseline **4052 passed / 22 skipped / 2 deselected** — есть в sibling-документе (L377); runbook-секция действительно **L327-349**; сирот после удаления слоя (d) нет; `ChatSerializationMiddleware` действительно снимает гонки. Плотность верных ссылок высокая — ошибки ниже касаются **дизайна и полноты**, а не аккуратности.

### BLOCKER

**R2-B1 — adjacency объявлена, но не обеспечена: snapshot переживает turn'ы.** §3.1 первой редакции обещала «snapshot консумируется или дропается на первом же следующем сообщении», а механизмом назначила роутер (step 5) плюс перечень clear-сайтов (step 6). Роутер стоит **после** гейтов [`handlers.py`](../../tg_parser/bot/handlers.py) L637 / L646 / L652 и после трёх pre-router'ов L663 / L671 / L679 — каждый из них возвращается раньше, и тогда snapshot не трогается вовсе. Достижимый путь: гейт агента ([`agent.py`](../../tg_parser/bot/agent.py) L495) проверяет только `preview_pending`, поэтому turn может вернуть **и** `pagination_pending`, **и** preview-less write-вызов ⇒ `PaginationFlow` armed + snapshot; следующее «ещё» уходит в `_handle_pagination_response` и завершается на L1354 (или на подсказке L1382-1385) **без** `state.clear()`; ещё через сообщение «да» вооружает мутационный preview из позапрошлого turn'а — ровно тот «FP, перенесённый во время», от которого §9 B2 уходила. Перечень clear-сайтов при этом был **неполон**: `set_state` вызывается ещё в восьми местах (L1202, L1222, L1248, L1354, L2114, L2129, L2504, L2521). **Изменение дизайна:** snapshot **снимается (pop) в начале `handle_text`** сразу после L633 и передаётся роутеру параметром. Adjacency становится структурной, step 6 — ненужным, а «полнота перечня» перестаёт быть требованием, которое нужно поддерживать вручную. §3.1, §3.2, TL;DR 5-6, новый тест `TestWriteIntentSurvivesNoTurn`, новая mutation-строка.

**R2-B2 — триггер шире, чем плану кажется: компаунды теряют запрос пользователя и ломают «нейтральность порядка».** §3.2 первой редакции решала «зеркалить `_handle_confirmation_response` дословно» (§9 m2), т.е. использовать `classify_confirmation_token` целиком. Но tier-2 (L488-492) классифицирует по **первому** токену, поэтому триггер — не 18 строк, а «любое сообщение, начинающееся с одного из них». В `ConfirmFlow` это безопасно (пользователь только что видел framework'ов «Подтвердите [да/нет]»), здесь — нет: T1 мог быть **честным** dry-run-отчётом, framework подсказку не добавляет (§9 п.12), и «да, покажи темы канала X» ⇒ мутационный preview **плюс потерянный запрос**, «нет, покажи другое» ⇒ «❌ Отменено.» **плюс потерянный запрос**. Это делает §3.4 (4) («FP-класс не имеет представителей») **ложным**. Он же ломает доказательство §9 m4: `ANAPHORA_PATTERN` (L121) ищется **не якорем**, а `_handle_delete_prerouter` (L2246, гейты L2270-2271), в отличие от L2393 / L2461, **не** имеет гейта `classify_confirmation_token` — значит «да, последнюю» при non-stale `last_subscription` одновременно валидна для обоих роутеров, и порядок решает исход. **Изменение дизайна:** триггер — **только tier-1** (полная нормализованная форма ∈ токен-сетам, L484-487); компаунд ⇒ `unrelated` ⇒ snapshot дропнут, turn уходит к агенту. Асимметрия та же, что во всех пяти precision-проходах: пропуск «да, давай» стоит одной переформулировки, ложное срабатывание — потерянного запроса. Побочно чинится и коллизия с prompt-правилом BUG-007 «да X» (bot.yaml L69). §3.2, §3.4, §3.5, §7-примечание, тест переименован в `TestCompoundAffirmativeIsNotATrigger`, новая mutation-строка.

### MAJOR

**R2-M1 — set-site не описан вообще.** Шаги 1 / 4 / 5 доводят дизайн до поля `AgentResult`, хелперов и роутера, но **нигде** не сказано, где именно `handle_text` пишет snapshot. Место не свободное: цепочка L761-826 — `if preview / elif clarify / elif pagination / elif _detect_subscribe_tool`, и независимый `if` дал бы «pagination armed + snapshot» (см. R2-B1). Добавлен шаг **4b** и код-скетч в §3.1: ветка той же цепочки, с явным решением, что `subscribe_intent` (L812) сосуществовать со snapshot'ом **может** (триггеры непересекающиеся — токен vs bare channel name), иначе регрессирует BUG-050.

**R2-M2 — выбран fail-open TTL-хелпер.** §3.1 писала «TTL = `PENDING_TTL_SECONDS`», §2 перечисляла оба хелпера, не указывая, какой брать. `_is_pending_expired` (L1630) на отсутствующем / непарсящемся `created_at` возвращает **`False`** (= «не истёк», L1632-1633) — fail-**open** на пути, вооружающем мутационный preview; `_is_stale` (L1643) в том же случае возвращает `True` (L1650-1651), и именно его используют оба прецедентных роутера. Зафиксировано: `_is_stale(created_at, PENDING_TTL_SECONDS)`. §3.1, §2, §5, mutation-таблица.

**R2-M3 — три prompt-пина не учтены, один из них ограничивает переписывание L65.** Реестр §3.8 не содержит класса `TestPromptHardRule` ([`tests/test_f5c_bot_force_resummarize.py`](../../tests/test_f5c_bot_force_resummarize.py) **L1153**). В нём: (a) `test_hard_rule_separates_the_two_call_shapes` (**L1174-1182**) берёт **первую** строку промпта с «BUG-086» и требует в ней `dry_run=true`, `confirm=false`, «Подтвердите», `BUG-009` — то есть напрямую ограничивает step 8, а план об этом молчал; (b) `test_version_bumped_within_the_1_9_pin` (**L1163-1167**) — **второй** `startswith("1.9")`-пин (план знал только про `test_f9_phase2_prompt_defense.py` L194) плюс `>= (1,9,3)`; (c) `test_version_consistent_in_system_prompt` (**L1169-1172**) — единственное, что механически связывает L8 и L32 (L2 — YAML-комментарий, тестом не пинится вовсе). Всё внесено в §3.7 / §3.8 / §5 / §2.

**R2-M4 — авторизация на resume: верно по факту, но нигде не заявлена, и один гейт оказался несущим по неочевидной причине.** Проверено: snapshot не несёт ни `current_user`, ни роли; `execute_tool` получает `current_user` от `UserResolutionMiddleware` **текущего** сообщения; `force_resummarize` проверяет права сам ([`tools.py`](../../tg_parser/bot/tools.py) L3171) ⇒ демоушен между T1 и T2 корректно приводит к `PermissionDenied` и ветке `write_intent_router_failed`. Но: тот же executor делает фолбэк `user = current_user or await get_default_admin()` (**L3168**), поэтому гейт «`current_user is None` → `False`» — это защита от **исполнения от имени дефолтного админа**, а не косметика; в плане он стоял без обоснования и без пина. Добавлены абзац в §3.2, ветка в §3.5, критерий в §5, тест `TestWriteIntentResumeRechecksAuthorization`, mutation-строка. Заодно проверено, что BUG-009-гейт (L1353) новым путём не обходится: переиздание идёт без `confirm` и без `confirm_flow_state`, а на настоящем confirm-turn'е `_check_confirm_flow_match` (L1257) требует точного равенства args (L1271-1273).

**R2-M5 — сломанные внутренние ссылки на разделы (5 мест).** Реестр тестов — это **§3.8**, mutation-верификация — **§3.9**, но TL;DR шаг 9 указывал «§3.7» и «§3.8», две строки §2 — «§3.7», следствие D7 в §7 — «§3.7». Для документа, который читается как инструкция, это отправляет реализатора в раздел про prompt вместо раздела про тесты. Исправлено везде.

### MINOR

**R2-m1 — объём удаления занижен вдвое.** §3.3 писала «~185 строк»; фактически ≈ **280**: `agent.py` L78-178 ≈ 97 + L181-261 = 81 + гейт-вызов L493-505 = 13 + метод L704-791 = 88. Цифра исправлена (влияет только на ожидание от диффа, но именно такие «мелочи» подрывают доверие к остальным числам).

**R2-m2 — L745 назван log-записью.** В §3.3 строка «`read_only_intent=` в log-записях | L745, L755, L789»: L745 — это **вычисление** (`read_only_intent = _looks_like_read_only_request(...)`), сами записи — L750-756 и L782-790. В §9 п.14 то же место описано корректно, так что это расхождение внутри документа. Уточнено.

**R2-m3 — четвёртый version-сайт в `bot.yaml`.** `metadata.description` (**L9**) начинается с «… — v1.9.3 BUG-086 …» и по конвенции файла получает новую **ведущую** клаузу на каждом бампе (в строке видно всю историю до v1.6.0). Тестом не пинится, поэтому и не всплыло бы в CI — и именно поэтому пропуск устойчив. Добавлено в step 8 / §3.7 / §5.

**R2-m4 — две сироты в тест-файле.** (a) Docstring модуля F5-C (**L33**) описывает `read_only_intent=` и переживёт удаление слоя (d) как ложная документация. (b) Хелпер `_prod_trace_turn` (**L823-847**) используется и удаляемым L849, и переписываемым L872 — реестр не отмечал, что он **должен выжить**. Оба внесены в §3.8. Также явно зафиксировано, что `_PROD_SELF_AUTHORED_CONFIRM` (L486) сохраняется — он переезжает в корпус `TestFinalTextNeverArmsConfirmFlow`.

**R2-m5 — расхождение L-ссылок между §2 и §9 B1.** §2 указывает `def`-строки (L2357 / L2418), §9 B1 — docstring-строки (L2362 / L2423). Обе «правильные», но читатель видит противоречие. §2 дополнен обеими координатами; §9 не тронут.

**R2-m6 — что осталось за рамками и это нормально.** (a) Метрик Prometheus слайс не заводит — при нулевом трафике счётчик не даст ничего сверх structlog; зафиксировано явно в §3.6, чтобы не выглядело как забытое. (b) Приватностная норма «только `arg_keys`» относится **только к новым записям**: соседние `agent_tool_call` (agent.py L549-554) и `fsm_confirm_execute` (handlers.py L878-883) логируют `args` целиком — существующий класс экспозиции, вне скоупа (§4), но теперь названный. (c) Перезапуск бота между T1 и T2: `MemoryStorage` ⇒ snapshot исчезает, «да» падает к агенту — добавлено строкой в таблицу §3.5, чтобы поведение было описано, а не выведено.

### Что round 2 **не** смог закрыть

- **Прод-верификация по-прежнему невозможна** — governing constraint не оспаривается: трафика нет, знаменатель ноль. Оба изменения дизайна (R2-B1 / R2-B2) обоснованы структурно и покрыты тестами, но их выигрыш в проде не измерим, как и выигрыш самой замены.
- **Точная итоговая цифра pytest** не проверялась прогоном (round 2 — read-only ревью, тесты не запускались). Оценка «−17 / +12-15» в §3.9 согласуется с реестром, но её всё равно надо подтвердить фактическим прогоном, а не арифметикой.
- **Полнота корпуса `TestFinalTextNeverArmsConfirmFlow`** проверена только по составу (пять проходов + вектор (b)); действительно ли он ловит «фазовое внедрение» — можно утверждать лишь после mutation-прогона по строке «вернуть детектор рядом с router'ом».

### Вердикт round 2

План **пригоден к реализации после внесённых правок** и остаётся архитектурно правильным: замена прозаического детектора детерминированным пользовательским триггером обоснована, прецедент выбран верно (BUG-048 / BUG-050, а не BUG-047 / BUG-031), удаление слоя (d) аргументировано, D7 закрыт. Два BLOCKER'а — не про идею, а про то, что **центральный инвариант (adjacency) не был обеспечен механизмом**, а **триггер был шире, чем описан**; оба чинятся малыми, локальными изменениями (pop-at-top + tier-1), и после них утверждения §3.2 / §3.4, которые раньше были оптимистичными, становятся верными.

---

## 11. Risks & rollback

| Риск | Оценка | Митигация |
|---|---|---|
| **Изменение затрагивает confirm-путь ВСЕХ 16 confirm-gated write-tool'ов**, включая деструктивные (`remove_channel`, `unsubscribe_*`, `remove_user_auth`) | главный риск slice'а | class-wide тест на tool'е без `dry_run` (переписанный `…IsToolAgnostic`); инвариант «первое «да» никогда не мутирует» пинится отдельно; BUG-009-гейт executor'а (`tools.py` L1353) остаётся последней линией: LLM-issued `confirm=true` по-прежнему отбивается |
| Affirmative token получает **третье** значение на уровне handler'а (ConfirmFlow / clarify / write-intent) | средний | четыре инварианта mutual exclusion (§3.2), каждый — тест; matrix-тест приоритетов; **pop-at-top** делает окно ровно одним сообщением структурно (§10 R2-B1); **tier-1** не даёт роутеру съесть компаунд с настоящим запросом (§10 R2-B2) |
| Snapshot ставится и на **честном** dry-run-turn'е (следствие D7) | средний | tier-1-триггер: без одиночного «да» arming невозможен; компаунд уходит к агенту (§3.2, §10 R2-B2) |
| Snapshot переиздаётся после смены прав пользователя | низкий | authz перепроверяется executor'ом на T2 (`assert_admin`, tools.py L3171); snapshot не несёт роли; гейт `current_user is None` закрывает фолбэк `get_default_admin()` (§10 R2-M4) |
| Snapshot от **упавшего** write-вызова (permission denied / not found) переиздаётся на «да» и выдаёт ошибку | низкий | детерминированный текст + `write_intent_router_failed`; мутации нет по построению |
| Регресс BUG-047-D1 («стray «да» инертно») | средний | явный пин в `TestWriteIntentRouterPrecedenceMatrix` |
| Регресс BUG-032 (opaque «Я не совсем понимаю ваш ответ») | низкий | §§ 1-8 `test_bot_confirm_flow.py` не трогаются; unknown-token-путь не меняется |
| args в FSM-storage содержат credential (`add_user_auth`) | не новый | тот же класс, что `pending_action`; логи — только `arg_keys` (пин `TestWriteIntentLogPrivacy`) |
| Прод-верификация невозможна (трафика нет) | принято | governing constraint; smoke-план §6 включает **оба** пути (happy + degraded), degraded воспроизводится вручную |
| Потеря построенного layer (d) | принято | git-история; §3.4 фиксирует аргумент |

**Rollback.** Один `git revert` слайса. Миграций нет, схем нет, персистентного состояния нет: MemoryStorage ⇒ живой snapshot умирает вместе с re-create контейнера, «полу-состояний» между версиями не бывает. `bot.yaml` откатывается тем же revert'ом (или `reload_prompts` после откатa файла). **Что делать нельзя:** оставлять детектор и router одновременно как «страховку» (D6 / §9 m5) — при откате возвращается прежний, полностью протестированный механизм, и это дешевле гибрида.

---

## 12. Ссылки

- Issue [#359](https://github.com/AlexEfimov/TG_parser/issues/359) (body + комментарий 2026-07-26); [#356](https://github.com/AlexEfimov/TG_parser/issues/356) item A; [PR #358](https://github.com/AlexEfimov/TG_parser/pull/358) (`9aadf5e` — слой, который заменяем), [PR #357](https://github.com/AlexEfimov/TG_parser/pull/357) (`b6c21ef` — slice, породивший `dry_run`)
- [`BUG_LOG.md`](BUG_LOG.md) § **BUG-086** (все строки, особенно «Guard / tests added», «Shadow-mode observability GAP», «Follow-up (deferred…)»); связанные **BUG-046** / **BUG-032** / **BUG-009** / **BUG-047** / **BUG-048** / **BUG-050** / **BUG-078**
- Код: [`agent.py`](../../tg_parser/bot/agent.py) L136/L151/L164/L167/L181-261/L268/L276/L413/L495/L602/L704; [`handlers.py`](../../tg_parser/bot/handlers.py) L78/L393/L453/L484-492/L496/L633/L637/L663-679/L761-826/L829-978/L1202/L1222/L1248/L1354/L1630/L1643/L1849-1892/L1973/L2114/L2129/L2167/L2246/L2319/L2357/L2418/L2504/L2521; [`states.py`](../../tg_parser/bot/states.py) L33/L120/L152; [`tools.py`](../../tg_parser/bot/tools.py) L110/L1257/L1353/L3168/L3171/L3181-3239; [`middleware.py`](../../tg_parser/bot/middleware.py) L140/L184; [`main.py`](../../tg_parser/bot/main.py) L244
- Тесты: [`test_bot_confirm_flow.py`](../../tests/test_bot_confirm_flow.py) § 9 (L1291-1430); [`test_f5c_bot_force_resummarize.py`](../../tests/test_f5c_bot_force_resummarize.py) L461-1182 (вкл. `TestPromptHardRule` L1153-1182); [`test_bot_execute_tool_guard.py`](../../tests/test_bot_execute_tool_guard.py) L302-345; [`tests/README.md`](../../tests/README.md)
- Prompt: [`prompts/bot.yaml`](../../prompts/bot.yaml) L2/L8/L32 (version) + L9 (`metadata.description`, история версий), L42 (write-ops), L54 (§ Confirmation semantics), L55 (LLM обязан просить подтверждение на preview-turn'е), L65 (BUG-086 hard rule), L66 (токены), L69 (BUG-007 «да X» read-flow)
- Runbook: [`F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md) § Deploy record — BUG-086 + § «BUG-086 — bot confirm-recovery guard» (L327-349; заменена на § «#359 / ADR-0020 — deterministic confirm trigger»)
- Стиль-эталон: [`START_PROMPT_SESSION_F5C_BOT_FORCE_RESUMMARIZE_2026-07-25.md`](START_PROMPT_SESSION_F5C_BOT_FORCE_RESUMMARIZE_2026-07-25.md) (§ 11 addendum)
- Процесс: [`AGENTS.md`](../../AGENTS.md), [`docs/quality/AGENT_PLAYBOOK.md`](../quality/AGENT_PLAYBOOK.md), [`agents-roles.md`](agents-roles.md)
- ADR: [0004](../adr/0004-hexagonal-architecture-and-module-boundaries.md), [0006](../adr/0006-karpathy-like-living-kb-principles.md), [0017](../adr/0017-dependency-management-policy.md) + черновик ADR-0020 (§8)
