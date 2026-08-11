# Runbook — F5-C Deploy + 24h Watch

**Last reviewed:** 2026-05-08 (hotfix — container/service nomenclature corrected; unified deploy path with SERVER_ARCHITECTURE.md).

**Назначение:** безопасно задеплоить F5-C MVP (Evolving Topic Summaries) на VPS и в первые 24 часа отследить, что фича работает в проде так, как задумано.

**Когда применять:**
- При первом деплое F5-C MVP (тег `f5c-mvp-2026-04-26`, merge commit `29679e0`).
- При hot-fix на `topic_card_versions` / `ResummarizationService` / scheduler hook.

**Время:** ~15 минут активной работы на деплой + пассивный мониторинг 24 ч (полезно дёрнуться через 1 ч / 4 ч / 12 ч / 24 ч).

**Связанные runbook'и:** [SAFE_MIGRATION_ON_DEV.md](SAFE_MIGRATION_ON_DEV.md), [ANTHROPIC_BILLING_RECOVERY.md](ANTHROPIC_BILLING_RECOVERY.md). Tracking issue для Phase 2 — **#15**.

---

## Deploy record — #359 / ADR-0020: детерминированный affirmative-token триггер вместо prose-детектора BUG-086 (bot-only / NO-migration)

> ✅ **ВЫПОЛНЕНО 2026-07-31** (18:18–18:30 UTC / 20:18–20:30 CEST, ручной VPS-деплой).
> **bot-adapter only / NO-migration** архитектурная замена несущего слоя (c) фикса BUG-086:
> framework больше не читает прозу turn'а вообще. Preview-less confirm-gated write-вызов
> оставляет **snapshot**, триггером служит **следующее сообщение пользователя**, если оно —
> ровно один affirmative-токен. Прозаический детектор и весь shadow-слой (d) удалены.
> Что смотреть в watch — § «#359 / ADR-0020 — deterministic confirm trigger» ниже.
>
> - **Релиз:** [PR #360](https://github.com/AlexEfimov/TG_parser/pull/360) (`fix/bot-affirmative-confirm-trigger`, коммиты `48aeee7` + `5752bdb`), merge-commit `102bb4c`; сверху status-flip `25654fa` — [ADR-0020](../adr/0020-deterministic-confirmation-triggers.md) теперь **Accepted**. CI зелёный (Test Python 3.12, Lint Documentation, Alembic Guardrails, Alembic Runtime Upgrade Smoke, Docker Build, Dependency Lock Guard, pip-audit; Compose Integration — skipped). Смерженная ветка удалена, на репозитории в этой же сессии включён `delete_branch_on_merge`.
> - **Git:** prod `9aadf5e → 25654fa` — чистый fast-forward (`git pull --ff-only` → `Updating 9aadf5e..25654fa` / `Fast-forward`, 14 файлов, **без** merge-коммита). Ancestry проверена заранее: `git merge-base --is-ancestor HEAD origin/main`.
> - **Миграция:** **НЕТ.** Схема не тронута, новых зависимостей нет (ADR-0017).
> - **Backup:** не требовался (нет schema-change).
> - **Build:** `docker compose build tg_parser` ~3.5 мин → `tg_parser:latest` = `b769dee25f54` (было `5b82aadbf88f`). **`reload_prompts` было бы недостаточно:** правки в `agent.py` / `handlers.py` / `states.py` вшиты в образ, bind-mount покрывает только `prompts/bot.yaml` (`1.9.3 → 1.9.4`).
> - **Re-create (BUG-078, НЕ `restart`):** `docker compose --profile bot up -d --no-deps tg_bot` → `tg_parser_bot` пересоздан, `healthy` через ~45 с, `StartedAt 2026-07-31T18:18:43.120880542Z`. `tg_parser` и `tg_parser_mcp` **доказуемо** не тронуты: `StartedAt` совпадает бит-в-бит до и после (`2026-07-24T16:14:04.256920618Z` и `2026-07-24T16:14:04.285026556Z`), оба остались на прежнем образе `5b82aadbf88f`. Независимая перепроверка ~12 мин позже: bot `Up (healthy)` на `tg_parser:latest`, другие два `Up 7 days` на `5b82aadbf88f`.
> - **Smoke (in-container, живой код запущенного контейнера):** `prompts/bot.yaml` = `1.9.4` (перепроверено независимо из живого контейнера). Все пять удалённых символов отсутствуют — `_recover_llm_authored_confirm`, `_LLM_AUTHORED_CONFIRM_PATTERN`, `_CONFIRMATION_DISCLAIMED_PATTERN`, `_looks_like_read_only_request`, `_MUTATION_IMPERATIVE_PATTERN` — проверено **двумя** способами: атрибуты модуля И рекурсивный grep по `/app/tg_parser/` внутри контейнера, вернувший exit 1 (⇒ их нет во всём образе, а не только в namespace модуля). Новые символы на месте: `handlers._classify_bare_confirmation_token`, `handlers._handle_write_intent_router`, `agent._write_intent_or_none`, `AgentResult.write_intent_pending`. **Классификатор проверен на живом коде:** `'да'` → affirmative, `'да.'` → affirmative, `'нет!'` → negative, `'да, покажи темы канала X'` → unknown, `'.'` → unknown. Пунктуированные кейсы — фикс, добавленный ревью (пин (4) в `BUG_LOG.md` § BUG-086, строка «Architectural replacement»), поэтому именно их прохождение **на живом коде** и есть суть проверки. `len(TOOL_DECLARATIONS)` = **35**, без изменений — #359 не удалял инструментов.
> - **Логи:** `docker logs --timestamps tg_parser_bot`, окно 18:18:43 → 18:29:53 UTC (11 мин) — 37 строк, **0** совпадений с `error|warn|traceback|exception|critical`. Старт чистый: загружен `/app/prompts/bot.yaml`, `bot_starting` на `gemini-2.5-flash` с 2 allowed users, health-сервер на 8081, background scheduler поднят, digest scheduler с 4 активными подписками, `watchlist_batch_flush_registered`.
> - **Функциональный e2e (manual, в `@Tgingest_bot`, owner):** ✅ **PASS, полный — в ДВА прогона.** Прогон 1, `19:28:13 → 19:35:43 UTC`: сценарии 1 / 2 / 4 зелёные (в т.ч. ровно тот трейс, который раньше упирался в «Я не совсем понимаю ваш ответ»), сценарий 3 (компаунд «да, …») не отработан. Прогон 2, `20:00:22 → 20:03:17 UTC`: закрыты **оба** оставшихся инварианта — компаунд против **живого** снапшота и `write_intent_declined`. Подтверждено прод-логами `tg_parser_bot` (§ «Прод-лог e2e» и § «Прод-лог e2e — прогон 2» ниже) и сверкой БД в обоих окнах. ⚠️ **Покрытие полное только на двух прогонах вместе:** прогон 2 не отправлял голого affirmative, т.е. не трогал `write_intent_router_resume` / `fsm_confirm_armed` / `fsm_confirm_execute` — это пути прогона 1. Ни один прогон по отдельности протокол не покрывает.
>
> **Событий `write_intent_*` / `fsm_confirm_*` в окне деплоя — ноль** — так и ожидалось: новый протокол пишет только на реальном пользовательском трафике, поэтому watch-поля ADR-0020 начинают набираться с owner-e2e и далее (ср. § «Governing constraint» в [START_PROMPT](../notes/START_PROMPT_SESSION_BOT_AFFIRMATIVE_CONFIRM_TRIGGER_2026-07-31.md): за пять суток до этого деплоя conversational-трафика в боте не было вовсе). Первые события появились через ~1 ч, на owner-e2e — тэлли за его окно ниже.
>
> **Housekeeping (зафиксировано как есть):** в прод-рабочем дереве лежат **11 untracked** артефактов прошлых сессий (`.env.backup-*`, `.env.bak*`, `docker-compose.yml.bak-bug028-*`). Tracked-модификаций **ноль**, поэтому `git pull --ff-only` прошёл без помех и это ничего не блокировало — но дерево не чистое, стоит прибрать.
>
> **Что проверялось вручную — 4 сценария прогона 1: 3 PASS сразу, сценарий 3 закрыт прогоном 2** (темы `topic:tg:mediamedics:post:1239` — цель, и `topic:tg:AgeManagment:post:977` — контроль):
> 1. **Деградированный путь — главный сценарий, PASS. Единственная мутация всего прогона.** Мутационный запрос ушёл в dry-run-форме (`force_resummarize`, отчёт «текущая версия 3, новых элементов 0, элементов в бандле 9») — **без** просьбы подтвердить, ConfirmFlow не вооружён, снят `write_intent_set`. Голое «да» → `write_intent_router_resume` + `fsm_confirm_armed`, пользователь увидел **verbatim-preview самого framework'а** («… будет немедленно пересуммаризирована — вызов LLM (расход токенов) … Подтвердите [да/нет].»); ничего не мутировало. Второе «да» → `fsm_confirm_execute` → «✅ force_resummarize: `topic:tg:mediamedics:post:1239` — ok.». **Это ровно тот трейс, который раньше упирался в «Я не совсем понимаю ваш ответ»** (класс BUG-086 / BUG-046). Turn с первым «да» обслужен **детерминированно**: у него нет ни `user_message`, ни `agent_tool_call` — LLM не привлекался вовсе.
> 2. **Пунктуированный голый токен + новое cancel-событие, PASS.** Тот же деградированный вход на `topic:tg:AgeManagment:post:977` (отчёт «версия 3, новых 0, бандл 14») + `write_intent_set`. Ответ «**да.**» — с точкой — дал `write_intent_router_resume` + `fsm_confirm_armed`: это пин **(4)** round-3-ревью, проверенный **на живом прод-коде**, до него пунктуированный токен отбрасывался как `unrelated` и падал к агенту. Ответ «нет» на preview → **`fsm_confirm_declined`** + «❌ Отменено.», `fsm_confirm_execute` не было. Событие в этом слайсе **новое**: до #359 cancel-ветка не писала ничего и «пользователь отказался» было неотличимо от «флоу сломался».
> 3. **Компаунд «да, …» — в этом окне INCONCLUSIVE, ✅ закрыт прогоном 2 (`20:01:19.710247Z`).** В прогоне 1 компаунд был отправлен, но pending-снапшота к этому моменту уже не было: он был снят resume'ом сценария 2, а ConfirmFlow там же отклонён. Поэтому `write_intent_dropped` не сработал, а сообщение обслужилось как обычное чтение (`list_topics`), и инвариант — **компаунд не должен резюмить ЖИВОЙ snapshot** — через Telegram остался непроверенным. Прогон 2 вооружил снапшот заново и отправил тот же компаунд **против живого** снапшота: `write_intent_dropped` `reason="unrelated"` через **43.6 с** после арминга, глубоко внутри `PENDING_TTL_SECONDS = 300` ([`handlers.py:79`](../../tg_parser/bot/handlers.py)), единственный tool-вызов turn'а — `list_topics` `channel_id="Docma_ru"`. Разбор и доказательство «живости» — § «Прод-лог e2e — прогон 2» ниже. CI (`TestCompoundAffirmativeIsNotATrigger`) и проверка на живом коде контейнера (`'да, покажи темы канала Docma_ru'` → `bare=unknown`, при этом `classify_confirmation_token` → `affirmative`) остаются вторым контуром.
> 4. **Adjacency, PASS — две независимые половины.** (а) Dry-run на `topic:tg:mediamedics:post:1239` показал **версию 4** — независимое подтверждение с read-пути, что мутация сценария 1 легла, — и снял очередной `write_intent_set`; постороннее «привет» сразу после дало **`write_intent_dropped` `reason="unrelated"`**, причём событие пришло **раньше** `user_message`: snapshot снимается и уничтожается ДО того, как turn доходит до агента. (б) Отдельно: голое «да» **без** pending-снапшота упало к агенту и дало «Я не совсем понимаю ваш ответ» — это **корректный** исход: когда ничего не вооружено и ничего не отложено, affirmative-токен не создаёт состояния.
>
> **Прод-лог e2e (2026-07-31, окно 19:28:13 → 19:35:43 UTC, `docker logs --timestamps tg_parser_bot`; таймстемпы лога авторитетны — клиент owner'а показывает UTC+3, т.е. 22:28–22:35 по местному):**
> - Сценарий 1: `19:28:13` `user_message` → `19:28:14.731` `agent_tool_call` `force_resummarize` (dry-run-форма) → `19:28:15.902` `write_intent_set` `arg_keys=["topic_id"]`, **без** `fsm_confirm_armed`.
> - Сценарий 1, первое «да»: `19:29:53.138` `write_intent_router_resume` `arg_keys=["topic_id"]` **и** `fsm_confirm_armed` в одном миллисекундном бакете — **без** `user_message` и **без** `agent_tool_call` на этом turn'е (детерминированное обслуживание, LLM не спрашивали).
> - Сценарий 1, второе «да»: `19:30:39.297` `fsm_confirm_execute` → «✅ force_resummarize: `topic:tg:mediamedics:post:1239` — ok.»; `last_summarized_at` лёг в `19:30:50.453171+00`, т.е. ~11 с реальной работы LLM.
> - Сценарий 2: `19:31:52` `user_message` → `19:31:53.361` `agent_tool_call` → `19:31:54.621` `write_intent_set` на `topic:tg:AgeManagment:post:977`; «да.» → `19:32:11.578` `write_intent_router_resume` + `fsm_confirm_armed`; «нет» → `19:32:31.421` **`fsm_confirm_declined`** + «❌ Отменено.», `fsm_confirm_execute` отсутствует.
> - Сценарий 3: компаунд в `19:32:57` — снапшота уже нет (снят в `19:32:11`, ConfirmFlow отклонён в `19:32:31`), поэтому `write_intent_dropped` **не** сработал, а `19:32:58.812` `agent_tool_call` `list_topics` — обычное чтение.
> - Голое «да» без снапшота: `19:34:38` — падение к агенту и «Я не совсем понимаю ваш ответ», состояние не создано.
> - Сценарий 4: `19:35:35` `user_message` → `19:35:36.102` `agent_tool_call` (dry-run, теперь **версия 4**) → `19:35:37.044` `write_intent_set`; «привет» → `19:35:43.327` **`write_intent_dropped` `reason="unrelated"`**, сразу следом `user_message`.
>
> **Тэлли событий за окно:** `write_intent_set` ×3, `write_intent_router_resume` ×2, `fsm_confirm_armed` ×2, `fsm_confirm_execute` ×**1** (единственная мутация), `fsm_confirm_declined` ×1, `write_intent_dropped` `reason=unrelated` ×1, `write_intent_router_failed` ×**0**, `write_intent_declined` ×0. Последний путь — голый негатив, съедающий snapshot **не вооружая** ConfirmFlow, — в этом окне не отработан; ✅ закрыт прогоном 2 (`20:03:16.773154Z`, ровно один `write_intent_declined`), см. § «Прод-лог e2e — прогон 2» ниже.
>
> **Сверка БД (до / после).** Цель `topic:tg:mediamedics:post:1239`: было v3, md5 `5e1339a11132c86b92f2462c2e920887`, `last_summarized_at 2026-07-21 19:37:23.211154+00`, 2 history-строки → стало **v4**, md5 `e16e595276b0f4fc51eb2142934679aa`, `2026-07-31 19:30:50.453171+00`, **3** history-строки. Контроль `topic:tg:AgeManagment:post:977`: было v3, md5 `7a3ab3d2ff399f9d73c5f8b7301b843b`, `2026-07-22 14:37:34.29482+00`, 2 строки → **бит-в-бит то же самое** (v3, тот же md5, тот же timestamp, 2 строки). Ровно **+1** версия на цели, контроль не тронут, застрявшего FSM-состояния не осталось.
>
> **Privacy / санитизация — подтверждено в проде:** каждый `write_intent_set` и каждый `write_intent_router_resume` записали `arg_keys=["topic_id"]` — только **ключи** аргументов, никогда значения; `dry_run` / `confirm` срезаны в момент создания снапшота, поэтому мутационной формы в FSM-хранилище нет вовсе. Это норма `TestWriteIntentLogPrivacy`, удержавшаяся на живом трафике.
>
> ⚠️ **Ловушка для следующего читателя: dry-run-ответы пришли слово-в-слово как `message` инструмента — но это НЕ framework-verbatim.** `user_facing_message` потребляется **только** внутри ветки `preview is True` ([`agent.py:462`](../../tg_parser/bot/agent.py)) и в write-intent-роутере; dry-run-payload флаг ставит, но preview'ом не является, поэтому идёт путём `response_text` (LLM-перефраз) — что лог и подтверждает: у этих turn'ов есть и `user_message`, и `agent_tool_call`. Точное совпадение — это LLM, добросовестно воспроизведший готовую русскую user-facing фразу, и **run-to-run оно не гарантировано**. Verbatim-рендер гарантирован только на preview-turn'ах и на собственных детерминированных строках хендлера («❌ Отменено.», «✅ force_resummarize: … — ok.»).
>
> **Прод-лог e2e — прогон 2 (2026-07-31, окно `20:00:22 → 20:03:17 UTC`, добор двух оставшихся инвариантов).** Tail на стороне Telegram не запускался — команда утонула в SSH-баннере, — поэтому окно поднято **задним числом**: `docker logs --since 2026-07-31T19:58:00Z tg_parser_bot`. Retention ничего не срезал, ничего не потеряно. Таймстемпы лога авторитетны. ⚠️ **Клиент owner'а шёл с постоянным сдвигом ≈ +11.6 с** относительно прод-лога (все шесть межсообщенческих дельт совпадают с точностью до полусекунды), поэтому арифметика по локальным часам смещает turn'ы на ~12 с — реальная ловушка для того, кто позже будет сверять транскрипт с логом.
>
> **Дизайн прогона: мутация была структурно недостижима.** Все три арминг-turn'а шли на несуществующую тему `topic:tg:mediamedics:post:999999999`; пост-фактум подтверждено SQL — **0** строк в `topic_cards` и **0** в `topic_card_versions` по этому id. `args` всех трёх записей `agent_tool_call` несут `{"topic_id":"topic:tg:mediamedics:post:999999999","dry_run":true}`, т.е. LLM **не** подменил id на реальную тему втихую.
> - Арминг 1: `20:00:22.799606` `user_message` → `20:00:29.417460` `agent_tool_call` `force_resummarize` (dry-run-форма) → `20:00:30.243341` `write_intent_set` `arg_keys=["topic_id"]`.
> - **Дубль сообщения — учтён явно.** Не имея лог-обратной связи, owner переслал то же арминг-сообщение через 12 с. Пересылка сняла первый снапшот (`20:00:34.182563` `write_intent_dropped` `reason="unrelated"`) и вооружила свежий: `20:00:35.241170` `agent_tool_call` → `20:00:36.061501` `write_intent_set`. В Gap A вошёл ровно **один** живой снапшот; накопление невозможно by design — `_take_write_intent` поп'ает безусловно в самом верху `handle_text` ([`handlers.py:681`](../../tg_parser/bot/handlers.py)), до любого state-гейта.
> - **Gap A — компаунд «да, покажи темы канала Docma_ru» против ЖИВОГО снапшота, PASS по всем пяти условиям.** `20:01:19.710247` `write_intent_dropped` `reason="unrelated"` → `20:01:19.710327` `user_message` (на **80 µs** позже; порядок гарантирован и по построению: pop `681`, вызов роутера `749`, `user_message` `760`) → `20:01:20.388970` `agent_tool_call` `list_topics` `channel_id="Docma_ru"` — **единственный** tool-вызов turn'а, `force_resummarize` не переиздавался. Снапшот жил `20:00:36.061501 → 20:01:19.710247` = **43.6 с** при `PENDING_TTL_SECONDS = 300` ([`handlers.py:79`](../../tg_parser/bot/handlers.py)) ⇒ демонстративно **живой**. В слайсе `write_intent_router_resume` ×**0** и `fsm_confirm_armed` ×**0**.
> - `/start` между двумя gap'ами дал **ноль** событий в отфильтрованном наборе: это Command-хендлер, и живого снапшота в тот момент не было.
> - **Gap B — `write_intent_declined`, PASS по всем четырём условиям.** `20:02:37.784093` `user_message` → `20:02:44.937218` `agent_tool_call` (третий арминг) → `20:02:47.429117` `write_intent_set` → `20:03:16.773154` **`write_intent_declined`** `tool=force_resummarize`, пользователь увидел «❌ Отменено.». Ровно одна такая запись. **Ни `user_message`, ни `agent_tool_call` на этом turn'е** — последние в окне (`20:02:37.784093` и `20:02:44.937218`) принадлежат предыдущему: LLM не привлекался вовсе, роутер вернул на [`handlers.py:2773`](../../tg_parser/bot/handlers.py). Тот же класс доказательства, что аргумент детерминированности сценария 1 в прогоне 1. `write_intent_router_resume` ×**0** и `fsm_confirm_armed` ×**0** ⇒ snapshot съеден **без** арминга ConfirmFlow, в чём и весь смысл этого пути. `fsm_confirm_declined` ×**0** в слайсе, так что две cancel-ветки теперь различены с обеих сторон: прогон 1 отработал `fsm_confirm_declined`, прогон 2 — `write_intent_declined`.
>
> 🔑 **Почему прогон 2 доказателен, а сценарий 3 прогона 1 не был — вся сила в `reason`.** `reason="unrelated"` пишется ровно на **одном** сайте — [`handlers.py:2763`](../../tg_parser/bot/handlers.py) — и этот сайт стоит **ПОСЛЕ** early-exit'а `if not snapshot: return False` (`2753–2754`), который не логирует **вообще ничего**. Два других drop-сайта пишут другие reason'ы: `reason="ttl"` (`2055`, внутри `_take_write_intent`) и `reason="fsm_armed"` (`691`). Следовательно `unrelated` **положительно различает** «живой снапшот сознательно отвергнут» от «снапшота не было». Экран Telegram эту разницу сделать не может — ровно поэтому первый прогон остался inconclusive, а этот нет.
>
> ⚠️ **У строки «❌ Отменено.» ТРИ возможных источника, и только два наблюдаемы.** Байт-идентичная строка живёт в трёх местах `handlers.py`: `write_intent_declined` логируется на **2771**, ответ — на **2772**; `fsm_confirm_declined` логируется на **1069–1073**, ответ — на **1074**; третий, на **1174**, — негативная ветка clarify-флоу, и она **не логирует ничего**. В этом прогоне третий недостижим (clarify не вооружался), но норма общая: **лог — единственный дискриминатор**, а один из трёх эмиттеров молчит ⇒ разбирать cancel по скриншоту нельзя.
>
> **Сверка БД — не тронута.** Контроль `topic:tg:AgeManagment:post:977`: `summary_version=3`, md5 `7a3ab3d2ff399f9d73c5f8b7301b843b`, `last_summarized_at 2026-07-22 14:37:34.29482+00`, 2 строки в `topic_card_versions` — совпадает с baseline по всем четырём полям. `topic:tg:mediamedics:post:1239` по-прежнему `summary_version=4`, md5 `e16e595276b0f4fc51eb2142934679aa`, 3 history-строки, т.е. единственная мутация прогона 1 и ничего сверх неё. **Сильнее per-topic-проверки:** самая свежая строка **во всей** таблице `topic_card_versions` — `2026-07-31 19:30:39.299796+00`, за ~30 мин **до** открытия этого окна ⇒ за прогон в таблицу не записалось ничего нигде.
>
> **Тэлли watch'а на момент замера** (контейнер `StartedAt 2026-07-31T18:18:43.120880542Z`; лог-стрим начинается с этого re-create, поэтому окно ~**2 ч**, а не 24): `write_intent_set` 6 (3 прогон 1 + 3 прогон 2), `write_intent_dropped` 3 (1 + 2), `write_intent_router_resume` 2 (2 + 0), `write_intent_declined` 1 (0 + 1), `write_intent_router_failed` **0**, `write_intent_router_execute_failed` **0**, `fsm_confirm_armed` 2 (2 + 0), `fsm_confirm_execute` 1 (1 + 0), `fsm_confirm_declined` 1 (1 + 0). **Знаменатель: 11 `user_message` / 8 `agent_tool_call`** — оба ненулевые, поэтому эти нули — настоящие нули, а не observability-потолок (озабоченность из прецедента BUG-086 здесь **не** применима). Ошибок **0** по `grep -Eic 'error|warn|traceback|exception|critical'` на всех 118 строках лога.
>
> **Честное ограничение прогона 2.** Голого affirmative он не отправлял, поэтому не отработал ни `write_intent_router_resume`, ни `fsm_confirm_armed`, ни `fsm_confirm_execute` — это уже пройденные пути прогона 1 (2 / 2 / 1 в тэлли). **Покрытие полное только у двух прогонов вместе**, ни один по отдельности протокол не покрывает. Отдельно: `write_intent_router_failed` остался чистым **0** без owner-артефакта, который пришлось бы дисконтировать — несуществующий topic id его не породил, потому что execute-ветка роутера (`2775–2806`) требует affirmative, а его в этом прогоне не было.
>
> **Прод-лог e2e — прогон 3 (2026-07-31, окно `21:20:36 → 21:31:06 UTC`, добор fail-closed TTL).** Окно поднято задним числом: `docker logs --since 2026-07-31T21:18:00Z tg_parser_bot`. Таймстемпы лога авторитетны. ⚠️ Сдвиг клиента owner'а **не постоянен**: на обоих содержательных сообщениях он ≈ **+11.5 с** (арминг `00:20:56` local → `21:21:07.802248Z`; «да» `00:30:55` local → `21:31:06.346089Z`), а на `/start` — лишь ≈ **+3.2 с**. Переносить «+11.6 с» прогона 2 как константу нельзя, сверять только по логу.
> - `/start` (сознательный сброс состояния): `21:20:36.173121` `user_message` (`text_length=6`, `request_id=ab76b4c5`), **ноль** событий `write_intent_*` / `fsm_confirm_*` — живого снапшота в тот момент не было.
> - Арминг: `21:21:07.802248` `user_message` → `21:21:08.749826` `agent_tool_call` `force_resummarize` `args={"dry_run":true,"topic_id":"topic:tg:mediamedics:post:999999999"}` → `21:21:09.591416` `write_intent_set` `arg_keys=["topic_id"]` (`request_id=9998f284`).
> - **Fail-closed TTL — PASS по всем шести условиям.** Голое «да» ~10 мин спустя: `21:31:06.345948` **`write_intent_dropped` `reason="ttl"`** → `21:31:06.346089` `user_message` (на **141 µs** позже, `request_id=d8aff3e8`; порядок гарантирован и по построению: pop `681`, `user_message` `760`). Снапшот жил `21:21:09.591416 → 21:31:06.345948` = **596.754532 с** при `PENDING_TTL_SECONDS = 300` ⇒ перебор TTL на **296.754532 с**. Ровно **одна** такая запись. В слайсе `write_intent_router_resume` ×**0**, `fsm_confirm_armed` ×**0** и — отдельно важно — `write_intent_router_failed` ×**0**: его появление означало бы, что снапшот был ещё жив и «да» ушло в execute-ветку роутера. `agent_tool_call` на этом turn'е нет вовсе.
> - **Форма записи положительно отличает `ttl` от `unrelated`.** Дроп несёт `tool` / `reason` / `chat_id` и **не** несёт `arg_keys` — ровно то, что пишет `_take_write_intent` ([`handlers.py:2051–2058`](../../tg_parser/bot/handlers.py)), в отличие от сайта `unrelated` (`2763`). Экран Telegram здесь бесполезен: «Я не совсем понимаю ваш ответ» — обычный fallback агента на голое «да», и он **одинаков** и когда снапшот был корректно снят по TTL, и когда снапшот не создавался вовсе (LLM не вызвал инструмент). Различает только лог — та же логика, что сделала доказательным прогон 2.
> - **Мутация была структурно недостижима:** арминг снова шёл на несуществующий `topic:tg:mediamedics:post:999999999` (подтверждено ранее — 0 строк в `topic_cards` и 0 в `topic_card_versions`). ⚠️ Побочное наблюдение: `dry_run=true` в вызове **не** мешает снятию снапшота — арминг привязан к имени confirm-gated инструмента и к отсутствию preview, а не к форме аргументов (комментарий на месте: [`agent.py:473–481`](../../tg_parser/bot/agent.py)); в сам снапшот при этом легли только `arg_keys=["topic_id"]`, т.е. `dry_run` срезан, как и в прогонах 1–2.
>
> **Тэлли watch'а после прогона 3** (то же окно от `StartedAt 2026-07-31T18:18:43.120880542Z`, ~3 ч): `write_intent_set` 7, `write_intent_dropped` 4 (`unrelated` 3 + **`ttl` 1**), `write_intent_router_resume` 2, `write_intent_declined` 1, `write_intent_router_failed` **0**, `write_intent_router_execute_failed` **0**, `fsm_confirm_armed` 2, `fsm_confirm_execute` 1, `fsm_confirm_declined` 1, `fsm_confirm_unknown_token` **0**. **Знаменатель: 14 `user_message` / 9 `agent_tool_call`** — оба ненулевые, поэтому оставшийся ноль (`reason="fsm_armed"`) — настоящий ноль, а не observability-потолок. Ошибок **0** по `grep -Eic 'error|warn|traceback|exception|critical'` на всех 132 строках лога; контейнер `healthy`.
>
> **Финальный 24h watch (закрыт 2026-08-01) — PASS.** `tg_parser_bot` остался `running` / `healthy` в том же контейнере `31b5d5984d98`, `StartedAt 2026-07-31T18:18:43.120880542Z`. Финальный замер — `2026-08-01T18:20:06Z`, после дедлайна `18:18:00Z`: непрерывное окно **24.0 ч**, 190 строк лога, из них 168 structlog JSON. Итоговый тэлли: `write_intent_set` 7, `write_intent_dropped` 4, `write_intent_router_resume` 2, `write_intent_declined` 1, `fsm_confirm_armed` 2, `fsm_confirm_declined` 1, `fsm_confirm_execute` 1 — всего **18** событий #359. `write_intent_router_failed` **0** и `write_intent_router_execute_failed` **0** при ненулевом знаменателе: 18 `user_message` + 13 `agent_tool_call` = **31**, поэтому нули настоящие. Единственный `fsm_confirm_execute` (`2026-07-31T19:30:39.297664Z`, `force_resummarize`, `chat_id=5445781511`) — заранее задокументированная и одобренная оператором мутация сценария 1 прогона 1.
>
> Контроль `topic:tg:AgeManagment:post:977` остался **бит-в-бит** на baseline: `summary_version=3`, md5 `7a3ab3d2ff399f9d73c5f8b7301b843b`, `last_summarized_at=2026-07-22 14:37:34.29482+00`, 2 строки `topic_card_versions`.
>
> ⚠️ Скрипт вернул `exit 1 / ATTENTION` только из-за **одной** error-level строки: `2026-08-01T15:20:14.207152Z`, `Channel coverage aggregation failed; degrading coverage_percent only`, `request_id=67818204`. Это обычный завершившийся `list_channels`-запрос (`user_message` `15:19:41.571742Z` → `agent_tool_call list_channels` `15:19:42.394733Z` → fallback → `request_completed` `15:20:16.730319Z`), а не чистое zero-error окно. [`channel_service.py:154–161`](../../tg_parser/services/channel_service.py) реализует намеренный fallback **BUG-066**: `SQLAlchemyError` / `RuntimeError` дорогого `coverage_counts_by_channel` деградирует только `coverage_percent` до `0.0`; `raw` / `processed` / `topics` сохраняют реальные значения. Событие не связано с confirmation state, routing, mutation или execution #359 и adjudicated как существующая неродственная деградация.
>
> **Финальный вердикт:** **PASS — 24h watch passed for #359 with one adjudicated unrelated BUG-066 degradation; watch closed.** Функциональный e2e закрыт по всем путям, которые три прогона реально прогнали (вместе: arming, resume, мутация, оба cancel'а, отвержение живого снапшота, fail-closed TTL). Формулировка «каждый инвариант ADR-0020 отработан в проде» по-прежнему была бы overclaim'ом: `reason="fsm_armed"` остался production zero, но это последовательным путём недостижимый fail-safe, закрытый design- и CI-аргументом, а не ожидающий operational run.
> 1. ✅ **Fail-closed TTL — ЗАКРЫТ прогоном 3** (§3 ADR: «TTL — `PENDING_TTL_SECONDS`, направление отказа **fail-closed**»), реализован в [`handlers.py:2051–2058`](../../tg_parser/bot/handlers.py), наблюдаем как `write_intent_dropped` `reason="ttl"`. Все **три** drop-записи прогонов 1–2 были `reason="unrelated"`; прогон 3 (`21:31:06.345948Z`) дал ровно **одну** запись `reason="ttl"` — через **596.754532 с** после арминга при `PENDING_TTL_SECONDS = 300`, на **141 µs** раньше `user_message` того же turn'а, при нулевых `write_intent_router_resume` / `fsm_confirm_armed` / `write_intent_router_failed`, и голое «да» действительно упало к агенту. Подробности — § «Прод-лог e2e — прогон 3» выше.
> 2. **Требование доказуемого взаимного исключения** (§ Последствия ADR: «Взаимное исключение обязано быть **доказуемым**, а не подразумеваемым»), наблюдаемое как `reason="fsm_armed"` в [`handlers.py:688–694`](../../tg_parser/bot/handlers.py). Это **не** «нужен ещё один прогон»: **последовательного** пути к этой ветке нет. Set-сайт снапшота — `elif` **ниже** всех трёх arm-ветвей (`831` preview → `850` clarify → `866` pagination → `882` write-intent), поэтому один turn не может одновременно вооружить FSM и оставить снапшот; снапшот поп'ается в самом верху следующего текстового turn'а (`681`); `callback_query`-хендлеров в боте нет вовсе; а все тринадцать `set_state`-сайтов достижимы только изнутри `handle_text`, т.е. уже **после** поп'а — значит turn, вооружающий состояние, снапшот уже съел. Похоже, ветку достаёт только конкурентная обработка апдейтов ⇒ это **fail-safe, обоснованный CI и самой `elif`-структурой**, а не непройденный прод-путь, за которым нужно гоняться.
>
> Остальным двум правилам ADR прод-трейс не нужен по построению: §4 (tripwire реестра `_PREVIEW_SUPPRESSING_ARGS`) — CI-тест, §1 («никогда не читать прозу turn'а») доказан удалением символов плюс рекурсивным grep'ом внутри контейнера.
>
> **Rollback (НЕ выполнялся; код-only, миграции нет):** `cd ~/TG_parser && git checkout 9aadf5e && docker compose build tg_parser && docker compose --profile bot up -d --no-deps tg_bot`. ⚠️ Откат на `9aadf5e` возвращает prose-детектор BUG-086 — то есть рабочее-но-дефектное состояние, а не сломанное, — и заново открывает shadow-mode blind spot, из-за которого и делался #359.

---

## Deploy record — BUG-086 fix: framework repairs LLM-authored confirmations (surface-only / NO-migration)

> ✅ **ВЫПОЛНЕНО 2026-07-26** (~09:15–09:25 CEST / 07:15–07:25 UTC, ручной VPS-деплой).
> **surface-only / NO-migration** hotfix severe bot-дефекта, найденного ручным прод-smoke'ом
> сразу после деплоя `force_resummarize` (`88d4c94` / PR #357): мутационный запрос получал
> терминальный dry-run отчёт и самосочинённое «Подтвердите … [да/нет]», а «да» упиралось в
> «Я не совсем понимаю ваш ответ» — фича была недоступна из Telegram. Несущая часть фикса —
> framework-guard в agent-loop, закрывающий **весь класс BUG-046**, а не только этот инструмент.
>
> - **Релиз:** [PR #358](https://github.com/AlexEfimov/TG_parser/pull/358) (`fix/bot-force-resummarize-confirm-flow`, коммиты `11c71c7` + `8a7cf79`), prod `main` `b6c21ef → 9aadf5e` (merge-commit). CI зелёный (Test 3.12, Docker Build, Alembic Guardrails/Runtime Smoke, Lint Docs, Dependency Lock Guard, pip-audit; Compose Integration — skipped).
> - **Миграция:** **НЕТ.** Схема не тронута, новых зависимостей нет (ADR-0017). ADR не требовался.
> - **Backup:** не требовался (нет schema-change).
> - **Build:** `docker compose build tg_parser` → `tg_parser:latest` пересобран. **`reload_prompts` было бы недостаточно:** правки в `agent.py` / `tools.py` вшиты в образ, bind-mount покрывает только `prompts/bot.yaml` (`1.9.2 → 1.9.3`).
> - **Re-create (BUG-078, НЕ `restart`):** `docker compose --profile bot up -d --no-deps tg_bot` → `tg_parser_bot` пересоздан, `healthy`. `tg_parser` / `mcp` не трогались (bot-surface-only).
> - **Smoke (in-container):** `len(TOOL_DECLARATIONS) == 35`, `force_resummarize` в `_WRITE_TOOLS_REQUIRING_CONFIRM`; `bot.yaml` = `1.9.3` с BUG-086 hard rule; **детектор проверен на живом коде** — прод-фраза «Подтвердите … [да/нет]» → `True`, перефразировка-отчёт «нужно будет подтвердить запуск отдельно» → `False`, пересказ подсказки «с confirm=false и без dry_run» → `False`; shadow-классификатор — «покажи, что будет, если …» → `True`, «пере-суммаризируй X и покажи …» → `False`. Логи за 25 мин: **0** error/traceback.
> - **Функциональный e2e (manual, в `@Tgingest_bot`, owner):** ✅ **PASS 2026-07-26 07:50–07:56 UTC** — тот же трейс, что вскрыл дефект, плюс негативный контроль. Все 5 шагов зелёные, подтверждено прод-логами `tg_parser_bot` (см. § «Прод-лог e2e» ниже).
>
> **Что проверялось вручную — 5 шагов, все PASS** (темы `topic:tg:Docma_ru:post:252` и `topic:tg:mediamedics:post:2954`):
> 1. **Dry-run терминален.** «покажи, что будет, если пере-суммаризировать тему `Docma_ru:post:252`» → отчёт «текущая версия 8, новых элементов 0, элементов в бандле 197. LLM не вызывался, версия не записывалась.» — **без** просьбы подтвердить, ConfirmFlow не вооружён.
> 2. **Мутационный запрос даёт framework-preview.** «пере-суммаризируй тему `Docma_ru:post:252`» → «…будет немедленно пересуммаризирована — вызов LLM (расход токенов), будет записана новая версия сводки. Подтвердите [да/нет].» — это **preview от framework'а** (ветка B executor'а), не самосочинённый текст LLM.
> 3. **«да» реально коммитит.** → «✅ force_resummarize: `topic:tg:Docma_ru:post:252` — ok.»
> 4. **Версия выросла.** «покажи историю темы `Docma_ru:post:252`» → **9 версий**, last summarized 2026-07-26 07:51:57 UTC. Переход **8 → 9**, как и ожидалось.
> 5. **Негативный контроль чист.** «пере-суммаризируй тему `mediamedics:post:2954`» → preview («текущая версия 9, новых элементов 3») → «нет» → «❌ Отменено.» → «покажи историю темы `mediamedics:post:2954`» → по-прежнему **9 версий**, last update 2026-07-21 09:37:18 UTC. Baseline, снятый ДО теста (`current_version=9`, `last_summarized_at=2026-07-21T09:37:18Z`), совпал **бит-в-бит** — мутации не было, застрявшего FSM-состояния не осталось.
>
> **Прод-лог e2e (2026-07-26, окно 07:46–08:00 UTC, `docker logs --timestamps tg_parser_bot` — 38 строк; таймстемпы лога авторитетны, они на ~12 с позже клиентских):**
> - `07:50:55.232` `agent_tool_call` `force_resummarize` `args={"dry_run": true, "topic_id": "topic:tg:Docma_ru:post:252"}` → **нет** `fsm_confirm_armed` (шаг 1 корректен).
> - `07:51:32.847` `agent_tool_call` `force_resummarize` `args={"topic_id": "topic:tg:Docma_ru:post:252", "confirm": false}` → `07:51:33.732` **`fsm_confirm_armed`**. **Слой (a) — prompt-hardening — сработал сам:** LLM выбрал правильную форму вызова, preview пришёл штатным путём.
> - `07:51:44.179` `fsm_confirm_execute` `args={…, "confirm": true}` → `resummarize.yaml` загружен → Anthropic `claude-sonnet-4-6` (4778 in / 571 out) `07:51:57.411` → `topic_embedding_complete` `Docma_ru` `07:51:59.277`; turn 15158 ms.
> - `07:56:09.887` `force_resummarize` `{"topic_id": "topic:tg:mediamedics:post:2954", "confirm": false}` → `07:56:10.718` `fsm_confirm_armed`; `07:56:15.177` turn «нет» завершён за **46 ms** — без LLM-вызова, без `fsm_confirm_execute` (cancel-путь `❌ Отменено.` собственного структурного события не пишет — см. заметку об observability ниже).
> - **Ошибок / warning'ов / traceback'ов в окне 07:40–08:05 UTC — 0** в `tg_parser_bot`, `tg_parser` и `tg_parser_mcp`.
>
> **🔑 Structural guard НЕ срабатывал.** За всё время жизни контейнера (`StartedAt 2026-07-26T07:04:53Z`) в логе **ноль** записей `llm_authored_confirm_detected` / `llm_authored_confirm_recovered` / `_recovery_failed`. Правильный `confirm=false` дал prompt-слой (a); слой (c) остаётся **непроверенным в проде** belt-and-braces (в CI покрыт, в т.ч. tool-agnostic-кейсом). Это **хорошая** новость по BUG-086 и одновременно сигнал по [#359](https://github.com/AlexEfimov/TG_parser/issues/359) (см. следующий абзац).
>
> **Наблюдение (shadow mode):** новое лог-поле `read_only_intent` на записях `llm_authored_confirm_detected` / `llm_authored_confirm_recovered`. Признак ложного срабатывания guard'а — `llm_authored_confirm_recovered` с `read_only_intent=True`. ⚠️ Сначала проверять **знаменатель**: prompt-hardening из этого же релиза может дать ноль срабатываний вообще, и тогда пустая выборка означает «нет данных», а не «нет ложных срабатываний».
>
> ⚠️ **Знаменатель за первое окно = 0 (проверено 2026-07-26).** `read_only_intent` в логах **отсутствует полностью** — поле вычисляется внутри `_recover_llm_authored_confirm` **после** прохождения `_looks_like_llm_authored_confirm`, поэтому оно пишется **только когда guard сработал**. E2E-прогон дал ровно те два turn'а, для которых классификатор и строился (genuine read-only «покажи, что будет, если …» и genuine mutation «пере-суммаризируй …»), и **ни для одного из них вердикт не залогирован**. ⇒ shadow mode **структурно не может** измерить свой false-positive rate: на happy path (guard молчит — а это, судя по слою (a), подавляющее большинство turn'ов) выборка пуста **by construction**, а не потому, что FP нет. Продление окна наблюдения эту дыру не закроет. Кандидат в issue [#359](https://github.com/AlexEfimov/TG_parser/issues/359) — вынести вычисление вердикта **до** detector-гейта (по-прежнему только булево, privacy-норма сохраняется), иначе прод-данных для решения «включать ли вето» не появится никогда.
>
> **Rollback (код-only, миграции нет):** `cd ~/TG_parser && git checkout b6c21ef && docker compose build tg_parser && docker compose --profile bot up -d --no-deps tg_bot`. ⚠️ Откат возвращает исходный dead-end — фича снова станет недоступной из Telegram.

---

## Deploy record — F5-C bot topic-history tools (#15 item #5, surface-only / NO-migration)

> ✅ **ВЫПОЛНЕНО 2026-07-24** (~21:12–21:19 CEST / 19:12–19:19 UTC, ручной VPS-деплой).
> **surface-only / NO-migration** деплой двух read-only bot-tool'ов в `@Tgingest_bot`,
> зеркалящих уже отгруженные MCP/CLI: `get_topic_versions` (audit-trail прошлых сводок)
> + `get_topic_history_diff` (дельта версий, default genesis→current). Backend
> переиспользован as-is (`TopicCardVersionRepo.list_by_topic`/`get_two_versions`,
> `diff_topic_summaries`); ADR не требовался (контраст с #3, который добавлял колонки).
>
> - **Релиз:** PR #355 (`docs/f5c-bot-tools-start-prompt`), prod `main` `fce2770 → b18c46e` (fast-forward, merge-commit). CI зелёный (Test 3.12, Alembic Guardrails/Runtime Smoke, Docker Build, Lint Docs, Dependency Lock Guard, pip-audit; Compose Integration — skipped).
> - **Миграция:** **НЕТ.** Схема не тронута (`db upgrade` не запускался, `db check` не требовался). Новых зависимостей нет (ADR-0017).
> - **Backup:** не требовался (нет schema-change — нечего откатывать на уровне БД).
> - **Build:** образ `tg_parser:latest` = `59f06c54f755` (`docker compose build tg_parser`; `prompts/bot.yaml` bind-mounted → `1.9.1` подхватился без отдельного шага).
> - **Re-create (BUG-078, НЕ `restart`):** `docker compose --profile bot up -d --no-deps tg_bot` → контейнер `tg_parser_bot` пересоздан, `healthy`. `tg_parser` / `mcp` остались на прежнем образе (bot-surface-only change → их поведение не затронуто).
> - **Smoke (in-container):** `len(TOOL_DECLARATIONS) == 34`, оба имени (`get_topic_versions` / `get_topic_history_diff`) присутствуют; scheduler + digest-scheduler стартовали (4 активные подписки), логи без error/traceback.
> - **Функциональный e2e (manual, в `@Tgingest_bot`, owner-verified):** «покажи историю темы X» → `get_topic_versions`; «что менялось в теме X» → `get_topic_history_diff` (genesis→current). Проверено на реальных темах с историей: `topic:tg:mediamedics:post:13525` (14 версий), `topic:tg:mediamedics:post:10644` (13), `topic:tg:Docma_ru:post:196` (10), `topic:tg:mediamedics:post:2954` (8), `topic:tg:Docma_ru:post:252` (7). **PASS.**
>
> **Rollback (код-only, миграции нет):** `cd ~/TG_parser && git checkout fce2770 && docker compose --profile bot up -d --no-deps tg_bot` (re-create на прежнем образе; при необходимости `docker compose build tg_parser` на `fce2770`).

---

## Deploy record — F6 topic-digest subscription addendum (#15 item #3, ADR-0019)

> ✅ **ВЫПОЛНЕНО 2026-07-24** (~17:54–18:21 CEST / 15:54–16:21 UTC, ручной VPS-деплой).
> **with-migration** деплой топик-скоуп дайджеста («что нового / что изменилось по теме X» —
> content = `diff_topic_summaries` дельта эволюционирующих сводок тем поверх существующего
> F6 subscription/scheduler/bot-push пути). ADR-0019.
>
> - **Релиз:** PR #353 (`feature/f5c-topic-digest`), prod `main` `e608b04 → fce2770` (fast-forward, 8 коммитов).
> - **Миграция (ingestion-ветка):** `c0d1e2f3a4b5 → d1e2f3a4b5c6` — аддитивно 2 колонки на `digest_subscriptions`:
>   `mode VARCHAR NOT NULL DEFAULT 'channel'` + `topic_ids TEXT[]` (nullable). `db check` после — «No new upgrade operations detected».
> - **Backward-compat (bit-for-bit):** все legacy-подписки backfill'ятся в `mode='channel'` (raw-document F6 digest без изменений), `topic_ids=NULL`. Топик-режим включается только явным `mode='topic'`. Regression нет.
> - **Pre-deploy backup:** `data/backups/postgres_20260724_175440.sql.gz` (357M) — rollback point.
> - **Build:** образ `tg_parser:latest` = `5b82aadbf88f` (код+миграция вшиты; `prompts/` bind-mounted → `prompts/topic_digest.yaml` подхватился без rebuild).
> - **Миграция катилась НОВЫМ образом** one-off контейнером: `docker compose run --rm --no-deps tg_parser db upgrade --db ingestion` (running-контейнер держит старый код до re-create).
> - **Re-create (BUG-078, НЕ `restart`):** `docker compose --profile bot up -d --no-deps tg_parser mcp tg_bot` → все три `healthy`.
> - **Smoke:** `GET /health` → `status: ok, database: ok`; `information_schema` подтвердил `mode`/`topic_ids`; CLI `digest add --help` показывает `--mode`/`--topics`; scheduler стартовал (`Background scheduler started … every 3600s`), логи без error/traceback.
> - **Функциональный e2e (read-only, `generate()` без доставки/записи БД):** 3 сценария **PASS** —
>   (A) explicit `topic_ids` на `topic:tg:profendocrinologist:post:3663` (3 версии) → non-empty дайджест, реальная diff-сводка, prompt из `/app/prompts/topic_digest.yaml`;
>   (B) channel-scoped (`topic_ids=None`, канал `profendocrinologist`) → 54 темы, ~3.8k символов;
>   (C) M4 visibility (канал вне scope) → `skipped=True`, LLM не вызван, без 500.
> - **Не выполнено (by design):** реальная топик-подписка в prod не создавалась — доставка в Telegram и продвижение cursor'а происходят на штатном F6 cron-тике по мере того, как пользователи создают `mode='topic'` подписки через MCP `subscribe_digest` / CLI `digest add --mode topic`.
>
> **Rollback:** код — `git checkout e608b04 && docker compose --profile bot up -d --no-deps tg_parser mcp tg_bot`;
> схема (аддитивная, обычно не нужна) — `docker compose run --rm --no-deps tg_parser db downgrade --db ingestion --revisions 1 --yes` (дропнет `mode`/`topic_ids`);
> полное восстановление — из backup `postgres_20260724_175440.sql.gz`.

---

## Pre-deploy checklist

Перед началом — убедись, что выполнены **все** пункты:

| # | Что | Как проверить |
|---|---|---|
| 1 | F5-C смерджен в `main` | `git log --oneline -1 --first-parent main` → `29679e0 Merge pull request #14: feat(F5C) — Evolving Topic Summaries MVP` |
| 2 | Тег создан и запушен | `git tag -l 'f5c-mvp-*'` → `f5c-mvp-2026-04-26` |
| 3 | CI на merge-коммите зелёный | `gh pr checks 14` или Actions UI на `5038eda` |
| 4 | Alembic head на VPS соответствует `c9d8e7f6a5b4` (pre-F5C) | `ssh -p 2296 user@212.72.189.15 'cd ~/TG_parser && docker compose exec tg_parser tg-parser db current --db processing'` → должно быть `c9d8e7f6a5b4 (head)` **до** наката |
| 5 | Anthropic / OpenAI лимиты в порядке | `ANTHROPIC_BILLING_RECOVERY.md` § «health check»; иначе после деплоя F5-C начнёт ловить billing-ошибки и пометит source as paused |
| 6 | Backup processing-БД свежий | `docker compose exec postgres /docker/backup.sh` (compose service = `postgres`, container = `tg_parser_postgres`) или ваш регулярный backup-job; rollback требует восстановления из dump'a при downgrade миграции. Если `/docker/backup.sh` отсутствует — `pg_dump` напрямую (см. `SERVER_ARCHITECTURE.md`) |

> ⚠️ **F5-C не катится** без п.5 — `RESUMMARIZE_LLM_PROVIDER` по умолчанию наследует от `LLM_PROVIDER`; если на проде `anthropic` / `openai` упёрлись в лимит — F5-C сам пометит source as paused через `_pause_source_for_billing`. Это by design (Decision #13), но лучше деплоить когда LLM-провайдеры здоровы.

---

## Deploy

### 1. Pull кода на VPS

```bash
ssh -p 2296 user@212.72.189.15
cd ~/TG_parser  # canonical deploy path (см. SERVER_ARCHITECTURE.md)
git fetch --tags origin
git checkout main
git pull origin main

# Sanity check
git log --oneline -1 --first-parent  # должно показать 29679e0 Merge pull request #14
git describe --tags --exact-match     # должно показать f5c-mvp-2026-04-26
```

### 2. Накатить миграцию (без рестарта сервисов)

F5-C добавляет одну миграцию `a4b5c6d7e8f9` в processing-ветку: 3 колонки в `topic_cards` + partial index + новая таблица `topic_card_versions`.

```bash
# Pre-flight: убедимся, что нет drift'a
tg-parser db check --db processing  # → "No new upgrade operations detected." на старой схеме

# Накат
tg-parser db upgrade --db processing  # → applies a4b5c6d7e8f9

# Post-check: head обновился
tg-parser db current --db processing  # → "a4b5c6d7e8f9 (head)"
tg-parser db check --db processing    # → "No new upgrade operations detected."
```

> 📊 На большой БД bootstrap-step может занять секунды-минуты: ставит `last_summarized_at = updated_at::timestamptz` для всех существующих `topic_cards`. Партициализация: миграция содержит fallback на `NOW()` если `updated_at` не парсится как ISO-8601 (см. gotcha #11). Локов на READ нет — миграция использует `ALTER TABLE ... ADD COLUMN` с дефолтом, а не table rewrite (Postgres 11+).

### 3. Перезапустить сервисы (rolling — если возможно)

```bash
docker compose pull
# Compose services: tg_parser (API + scheduler), mcp, tg_bot (profile=bot).
# Container_name'ы: tg_parser, tg_parser_mcp, tg_parser_bot.
docker compose --profile bot up -d --no-deps tg_parser mcp tg_bot
docker compose ps  # все сервисы Up (healthy)
```

> 📦 Если стек single-node — будет ~5-секундный downtime между остановкой старого контейнера и запуском нового. Telegram bot переподключится автоматически (long-polling). Webhook'и (если есть) пропустят 1-2 update'a.

### 4. Smoke tests (через 30 секунд после рестарта)

```bash
# (a) API живой и метрики экспортируются
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/metrics | grep -c '^tg_resummarize_'  # → 0 пока не было ни одного re-summarize, это норма

# (b) Новые F5-C MCP-инструменты доступны
docker compose exec tg_parser tg-parser mcp list-tools | grep -E "get_topic_versions|force_resummarize"
# → должно вывести две строки

# (c) Новый CLI sub-app зарегистрирован
docker compose exec tg_parser tg-parser topic --help
# → должно показать команды `versions` и `resummarize`

# (d) Probe: попробовать прочитать audit-trail для существующей темы (ожидаем пустой,
# потому что F5-C ещё не пробежал ни разу)
docker compose exec tg_parser tg-parser topic versions <известный topic_id>
# → "history rows: 0 (limit=10)" + current_version: 1 + last_summarized_at: <updated_at>

# (e) Pipeline-tick test (best effort): дождаться следующего scheduler-tick'a
# и проверить, что в логах появился f5c_resummarize lines
docker compose logs -f tg_parser | grep -i "f5c_resummarize"
# → "f5c_resummarize source=... candidates=N resummarized=M skipped=K tokens=T"
# Ctrl-C через 1-2 минуты после первого попадания
```

Если **(a)–(e) все зелёные** — деплой считается успешным, переходим к watch.

---

## 24h Watch

После деплоя — **минимум 24 часа** мониторим следующие сигналы. Все метрики уже инструментированы в `tg_parser/api/metrics.py` и попадают в Prometheus через `/metrics` endpoint.

### Чек-поинты

| Время после деплоя | Что смотрим | Acceptance criteria |
|---|---|---|
| **+1 ч** | Просто запустился ли F5-C хотя бы раз | `sum(tg_resummarize_total) > 0` (если в каналах был incremental ingest, должны быть кандидаты) |
| **+4 ч** | Распределение outcome'ов | `outcome=ok` доминирует (>80% от total). `llm_error` / `version_raced` редкие (<5%) |
| **+12 ч** | Cost monitoring | Сумма `tg_resummarize_tokens_total` в день / канал не выходит за бюджет (см. ниже) |
| **+24 ч** | Stability | Ни одного source с `_pause_source_for_billing` (если был — открываем `ANTHROPIC_BILLING_RECOVERY.md`); размер `topic_card_versions` растёт линейно, не экспоненциально |

### PromQL queries

#### Health: rate of successful re-summaries

```promql
rate(tg_resummarize_total{outcome="ok"}[5m])
```
**Ожидание:** >0 на каналах с incremental трафиком; в idle-каналах может быть 0 (нет новых items → нет триггера).

#### Outcome distribution

```promql
sum by(outcome) (rate(tg_resummarize_total[15m]))
```
**Ожидание:** `ok` доминирует. Допустимая аномалия `locked` — две force-resummarize одной темы подряд (advisory-lock). `no_card` / `no_bundle` — чаще всего race c удалением канала. `empty_scope` — LLM вернул пустой scope, fallback на старый отработал.

#### Tripwire: error rates

```promql
# Tripwire #1 — LLM-ошибки выше 10%
sum(rate(tg_resummarize_total{outcome="llm_error"}[15m]))
  / sum(rate(tg_resummarize_total[15m])) > 0.1

# Tripwire #2 — version_raced > 5% (значит advisory-lock не спасает)
sum(rate(tg_resummarize_total{outcome="version_raced"}[15m]))
  / sum(rate(tg_resummarize_total[15m])) > 0.05

# Tripwire #3 — duration p95 близок к таймауту
histogram_quantile(0.95, rate(tg_resummarize_duration_seconds_bucket[15m])) > 30
```

Любой из этих 3 — **сигнал тревоги**, см. § Tripwire response ниже.

#### Cost (LLM tokens) per provider+model

```promql
# Tokens / hour
rate(tg_resummarize_tokens_total[1h]) * 3600

# Estimated cost / day (для openai/gpt-4o-mini = $0.15/1M input, $0.60/1M output)
sum by (model) (
  rate(tg_resummarize_tokens_total{model="gpt-4o-mini", token_type="prompt"}[1d]) * 86400 * 0.15 / 1e6
  + rate(tg_resummarize_tokens_total{model="gpt-4o-mini", token_type="completion"}[1d]) * 86400 * 0.60 / 1e6
)
```
**Ожидание (per Roadmap):** TCO upper bound ~1.2M tokens/day/channel в худшем случае (cap = `RESUMMARIZE_MAX_TOKENS_PER_TICK=50000` × 24 tick/day). На практике — десятки центов / месяц / канал. Если уехало в доллары/день — провёрнуть `RESUMMARIZE_TRIGGER_N` повыше или `RESUMMARIZE_INPUT_WINDOW_N` пониже.

#### Размер audit-trail таблицы

```sql
-- Запускать на processing-БД через ssh / docker exec, не Prometheus.
SELECT
  COUNT(*)                     AS rows,
  pg_size_pretty(pg_total_relation_size('topic_card_versions')) AS size,
  COUNT(DISTINCT topic_id)     AS topics_with_history,
  MAX(version_no)              AS max_version,
  AVG(version_no)::numeric(10,2) AS avg_version
FROM topic_card_versions;
```
**Ожидание (24 ч):** rows ≈ суммарное `tg_resummarize_total{outcome="ok"}` за сутки. Размер должен быть в МБ, не ГБ. Если рост слишком быстрый — это сигнал к Phase 2 пункту #1 (TTL/retention).

### F11 watchlist health (TD-02 — добавлено в post-Living-KB Phase 1)

F11 watchlist делит scheduler tick с F5-C; следующие PromQL-снипеты позволяют убедиться что F11 живой и помогают калибровать threshold перед F11 P2.

**Match-flow по 1 часу:**
```promql
rate(tg_watchlist_matches_total{result="delivered"}[1h])
rate(tg_watchlist_matches_total{result="filtered_threshold"}[1h])
rate(tg_watchlist_matches_total{result="filtered_keywords"}[1h])
```
Если `delivered = 0` и `filtered_threshold > 0` — порог слишком высок (либо реально нет совпадений). Если `filtered_keywords` высокий — exclude-keywords агрессивно режут.

**Distribution of combined scores (calibration для F11 P2):**
```promql
histogram_quantile(0.5, sum by (le) (rate(tg_watchlist_score_bucket[1h])))
histogram_quantile(0.9, sum by (le) (rate(tg_watchlist_score_bucket[1h])))
```
Использовать после ≥ 24 ч продакшн-сигнала чтобы выбрать sane default threshold (текущий 0.6 — placeholder).

> ⚠️ **BUG-060 — keyword-only rows skew `tg_watchlist_score` (preventive).** Гистограмма `tg_watchlist_score` смешивает keyword-only и hybrid строки. Когда `semantic_available=False` (нет эмбеддингов / семантический бэкенд недоступен), строка **by design** имеет `combined=keyword` и `semantic=0.0` (ADR-0010/0011; см. [`WAVE1_TECH_DEBT.md` § B](../notes/WAVE1_TECH_DEBT.md)). Сейчас НЕ существует provisioned alert на `tg_watchlist_score`, поэтому ложных срабатываний нет. Но **любое будущее alert-выражение, которое предполагает blended-формулу `kw_weight·keyword + sem_weight·semantic` (defaults 0.4/0.6), ОБЯЗАНО гейтить на `semantic_available`** (или явно исключать keyword-only строки), иначе keyword-only строки с `semantic=0.0` дадут ложные positives. Это сознательно отложенный preventive-долг (BUG-060): добавлять реальное правило здесь нельзя без этого гейта.

**Delivery success rate:**
```promql
rate(tg_watchlist_delivery_total{outcome="sent"}[1h])
rate(tg_watchlist_delivery_total{outcome="blocked"}[1h])
rate(tg_watchlist_delivery_total{outcome="error"}[1h])
```
`blocked` > 0 значит юзер заблокировал бота — interest soft-deleted автоматически. `error` > 0 — Telegram rate-limit / транзиентные ошибки; систематически > 5% → проверять bot токен / network.

**Active interests:**
```promql
tg_watchlist_active_interests
```
Gauge. Падение к нулю при non-empty `subscribe_watchlist` calls — индикатор массового soft-delete (например после длительного `blocked` storm).

**Tripwire (для F11):** `rate(tg_watchlist_delivery_total{outcome="error"}[5m]) > 0.1` — открыть hot-fix issue.

**Score-ceiling из логов (2026-06-07).** На no-match тике scheduler теперь пишет структурную строку `watchlist.score_ceiling` (per-interest max combined/keyword/semantic против threshold) — диагностика persistent zero-matches без захода в `tg_watchlist_score` гистограмму:
```bash
docker logs tg_parser 2>&1 | jq -Rc 'fromjson? | select(.event == "watchlist.score_ceiling")'
```
Если потолок стабильно ниже threshold → понизить порог интереса **или** ребалансить веса через `WATCHLIST_KEYWORD_WEIGHT` / `WATCHLIST_SEMANTIC_WEIGHT` (combined = `kw_weight·keyword + sem_weight·semantic`, defaults 0.4/0.6). `WATCHLIST_DEFAULT_THRESHOLD` (default 0.6) — порог для новых интересов без явного threshold. См. [`docs/notes/DIAG_WATCHLIST_ZERO_MATCHES_2026-06-07.md`](../notes/DIAG_WATCHLIST_ZERO_MATCHES_2026-06-07.md).

**Retroactive backfill (DIAG B2).** Scheduler скорит только per-tick новые документы, поэтому корпус, заингещенный до создания интереса, не матчится. Проверить/закрыть разрыв (dry-run по умолчанию):
```bash
tg-parser watchlist backfill <interest_id>            # preview: would_match / max_combined
tg-parser watchlist backfill <interest_id> --apply --notify
```
То же через MCP — `backfill_watchlist(interest_id, dry_run=True)`. Идемпотентно.

> ⚠️ **Гайдрейл: ручной / ретроактивный backfill запускай БЕЗ `limit` (uncapped).** `limit` — это newest-first кап на число скоримых документов; для multi-channel интересов он **молча undercount'ит** исторические матчи, потому что реально релевантный контент часто старый и выпадает за пределы newest-N окна. ADR-0011 default — uncapped (весь matched corpus); `limit` оставлен только как newest-first preview-кап. Замер 2026-06-15: Микробиота с `limit=450` → `would_match=0` (`max_combined=0.331`); без `limit` (весь корпус, 8004 docs) → `would_match=33` (`max_combined=0.789`). Прошлая сессия с `limit=450` записала ~8 матчей суммарно по 5 интересам — uncapped-перепрогон дал 342. Для preview используй `dry_run=true` БЕЗ `limit`; откатывайся на `limit` только если uncapped-прогон реально упал в таймаут (на практике uncapped-прогоны до `scored_docs=8536` проходили без таймаута — `limit` изначально добавляли «против таймаута», которого не случилось).

### #359 / ADR-0020 — deterministic confirm trigger (после деплоя bot-слайса)

Заменил BUG-086-guard (`_recover_llm_authored_confirm`), который выводил «LLM сочинил подтверждение» из **прозы** turn'а. Теперь framework не читает прозу вообще: preview-less confirm-gated write-вызов оставляет **snapshot**, а триггером служит **своё** следующее сообщение пользователя, если оно — ровно один affirmative-токен. Метрик нет, только структурные логи бота:

```bash
# Разовый скан всего лога контейнера
docker logs tg_parser_bot 2>&1 | jq -Rc 'fromjson? | select(.event | test("^write_intent_|^fsm_confirm_"))'

# То же вживую, на время watch'а
docker logs -f --since 1m tg_parser_bot 2>&1 | jq -Rc --unbuffered 'fromjson? | select(.event | test("^write_intent_|^fsm_confirm_"))'
```

> ⚠️ `-R` + `fromjson?` здесь не украшение: голый `jq` **падает на первой же не-JSON строке** (стартовый шум и вывод сторонних библиотек), то есть умирает раньше первого структурного события — а выглядит это как «событий нет», что для watch-процедуры хуже, чем ошибка. `2>&1` заводит в тот же пайп stderr контейнера: собственные structlog-строки идут в stdout (`logging.StreamHandler(sys.stdout)`, `tg_parser/config/logging.py`), но сторонние библиотеки пишут в stderr, и без `2>&1` их вывод сыпался бы мимо фильтра прямо в терминал. `--unbuffered` нужен только в `-f`-режиме.

> 🚀 **Одной командой — [`docker/watch_359.sh`](../../docker/watch_359.sh):** скрипт сам открывает SSH на прод и печатает за один заход всё, что нужно чек-поинту — provenance-заголовок (host / container id / `StartedAt` / покрытое окно), тэлли тех же событий, **знаменатель** `user_message` / `agent_tool_call`, error-count, отдельные call-out'ы по `write_intent_router_*failed` и по каждому `fsm_confirm_execute`, сверку контрольной темы с baseline (PASS / CHANGED) и verdict-блок. Ручные команды выше остаются fallback'ом.
>
> ```bash
> ./docker/watch_359.sh              # запускать с рабочей станции, НЕ с VPS
> ./docker/watch_359.sh --since 30m  # ad-hoc окно
> ```
>
> Exit codes: `0` — критерии закрытия выполнены, `1` — что-то не сошлось либо знаменатель `0` (INCONCLUSIVE, не clean), `2` — watch **void** (нет SSH, нет контейнера, лог не парсится, контрольной темы нет). Ради `2` всё и затевалось: те же команды, вставленные в **локальный** терминал, дают правдоподобный ноль вместо ошибки.

| Событие | Что значит | Ожидание за 24 ч |
|---|---|---|
| `write_intent_set` | write-вызов не дал preview ⇒ снят snapshot (`arg_keys` — только ключи) | единицы. ⚠️ **Скачок ≠ регрессия prompt-слоя (a).** Snapshot снимается на **любой** не-preview результат confirm-gated write-tool'а — см. комментарий на месте ([`agent.py:473–481`](../../tg_parser/bot/agent.py)): «a `dry_run` report, a BUG-009 rejection, an **error**». Корректный `confirm=false`-вызов по удалённой теме или у разжалованного админа даёт `write_intent_set` **без всякого** сбоя prompt-слоя: три записи прогона 2 легли ровно так — на error-результат «Topic not found» ([`tools.py:3203`](../../tg_parser/bot/tools.py)) по несуществующему `topic_id`. Поэтому при скачке сначала смотреть `agent_tool_call` того же `request_id`: `dry_run=true` ⇒ да, это (a); `confirm=false` ⇒ инструмент отбил вызов, искать причину отказа, а не промпт |
| `write_intent_router_resume` | пользователь ответил bare «да» ⇒ получен **настоящий** preview, ConfirmFlow вооружён | ≤ числу `write_intent_set` (в **дефолтном** окне: `MemoryStorage` умирает вместе с контейнером — [`bot/main.py:244`](../../tg_parser/bot/main.py) — поэтому ни один snapshot не старше `StartedAt`; в ad-hoc окне вида `--since 30m` resume законно может оказаться без своего `set`, если тот выпал за границу) |
| `write_intent_router_failed` | `warning`: инструмент отработал, но preview не вернул (тема удалена / демоушен прав) — пользователь получает «Не удалось подготовить подтверждение: `<error>`. Повторите запрос.», состояние не выдумывается | 0; иначе смотреть `error` |
| `write_intent_router_execute_failed` | `error` + traceback: тот же re-issue **упал исключением** (в отличие от `write_intent_router_failed`, где вызов вернулся штатно) — пользователь получает «⚠️ Внутренняя ошибка при подготовке подтверждения.», ConfirmFlow не вооружается, snapshot уже сгорел. В отличие от соседних событий `chat_id` тут не пишется — коррелировать по `request_id` / `telegram_user_id` из contextvars | 0; любое появление — баг, разбирать по traceback'у в этой же записи |
| `write_intent_declined` | ответ был bare-негативом ⇒ «❌ Отменено.», snapshot сгорел | сколько угодно, это норма |
| `write_intent_dropped` | snapshot сгорел не будучи использованным; `reason` = `fsm_armed` / `unrelated` / `ttl` | норма; `ttl` часто ⇒ TTL 5 мин маловат |
| `fsm_confirm_armed` | ConfirmFlow вооружён: preview показан, следующий affirmative-токен исполнит действие. Старше #359 (пять сайтов: обычный preview-turn, clarify-rerun, delete-flow, subscribe-rerun и write-intent-router), в фильтр попадает целиком по `^fsm_confirm_` — без него трейс не читается. Поля: `tool`, `chat_id` | ≥ числу `write_intent_router_resume` (router логирует его сразу после resume); сверх того — обычный confirm-трафик, не относящийся к #359 |
| `fsm_confirm_execute` | **единственный маркер мутации на confirm-gated поверхности**: подтверждение принято, инструмент вызывается с `confirm=True`. ⚠️ Обратное **не** верно: `fsm_confirm_execute` = 0 **не** значит «бот ничего не мутировал». `reload_prompts` и `export_channel` — write-tool'ы, сознательно оставленные **вне** `_WRITE_TOOLS_REQUIRING_CONFIRM` ([`tools.py:106–109`](../../tg_parser/bot/tools.py)), поэтому мутация через любой из них проходит вообще без confirm-протокола и следа здесь не оставляет; записи scheduler'а (ingestion, digest, watchlist, F5-C resummarize) тем более — они не идут через бот-FSM. Для «мутировал ли бот» смотреть `agent_tool_call` по имени инструмента, а не этот счётчик. Поля: `tool`, `chat_id`, `args` — secret-bearing keys **маскируются** (BUG-087: `add_user_auth.identifier` → prefix/length token; ключ остаётся); non-secret values по-прежнему полные ради forensics BUG-002/004. Соседнее `fsm_confirm_unknown_token` тоже закрыто (BUG-088, 2026-08-04): сырого текста ответа там больше нет, вместо него `verdict` + shape-факты — см. строку этого события ниже. **На проде оба фикса живут только после re-create контейнера бота** (`restart` оставляет старый код — BUG-078) — **re-create выполнен 2026-08-04 14:35 UTC**, оба фикса на проде живые | сколько угодно, но **каждый** обязан объясняться намеренным действием; необъяснённый — инцидент, разбирать по `chat_id` / `request_id` |
| `fsm_confirm_execute_failed` | `error` + traceback: подтверждённый вызов упал исключением, FSM очищен, пользователь получает «⚠️ Внутренняя ошибка при выполнении действия.». Мутация могла частично пройти — в отличие от `write_intent_router_execute_failed`, который падает ДО подтверждения. Поле только `tool`, коррелировать по `request_id` / `telegram_user_id` из contextvars | 0; любое появление — баг, разбирать по traceback'у в этой же записи |
| `fsm_confirm_declined` | пользователь отказался на ConfirmFlow-preview | норма; закрывает старый GAP «отказ и поломка неразличимы» |
| `fsm_confirm_unknown_token` | ответ на **вооружённый** ConfirmFlow не распознан ни как affirmative, ни как негатив и не похож на новую команду (иначе turn перерутился бы без события); FSM **остаётся вооружённым**, пользователь получает список принимаемых токенов и длину окна подтверждения (`PENDING_TTL_SECONDS`, 5 мин — константа, не остаток). Поля (после **BUG-088**, 2026-08-04, [`confirm_unknown_log.py`](../../tg_parser/bot/confirm_unknown_log.py)): `chat_id`, `tool` — какое именно pending-действие осталось без ответа (раньше этого поля не было вовсе), `verdict` и shape-факты `length` / `token_count` / `is_single_token` / `has_digits` / `has_punct`. **Сырого текста ответа в записи больше нет.** До 2026-08-04 здесь лежало поле `normalized` = **ВЕСЬ** ответ пользователя целиком, из-за чего строку нельзя было копировать никуда за пределы контейнера; **эта оговорка снята** — но **только на контейнере, пересозданном на образе с этим фиксом** (`restart` оставляет старый код — BUG-078). Пока prod-бот не re-created, записи по-прежнему несут `normalized` целиком и старая оговорка на них действует в полном объёме — **условие выполнено: `tg_parser_bot` пересоздан на проде 2026-08-04 14:35 UTC** (см. [`BUG_LOG.md`](../notes/BUG_LOG.md) § BUG-088 § Status), поэтому на текущем контейнере оговорка снята. На пересозданном контейнере записи события безопасно тащить в заметки и issue дословно. `verdict` — закрытый словарь из пяти значений: `near_miss_affirmative` / `near_miss_negative` — опечатка или украшение вокруг токена из whitelist («дя», «(да)»), т.е. прямой кандидат на расширение списка. **Оговорка: любой одиночный алфавитно-цифровой символ (`x`, `5`) даёт `near_miss_affirmative`** — в whitelist есть односимвольные `y` / `n`, до которых расстояние 1 достигается тривиально. Смотреть `length` прежде, чем читать вердикт как опечатку. `single_token_unlisted` — одно слово мимо обоих списков, а при большом `length` + `has_digits=true` это форма **вставки** (paste) и самый интересный случай для разбора; `multi_token_free_text` — свободный текст из двух и более токенов; `non_text` — пусто / только emoji / только пунктуация. Чего по логу больше **не** узнать — КАКОЙ именно синоним написал пользователь: осознанная цена shape (d)+(a), см. [`BUG_LOG.md`](../notes/BUG_LOG.md) § BUG-088. Фильтр `^fsm_confirm_` эти записи по-прежнему захватывает целиком — теперь это безвредно. | **ожидаемый шум**, не красный флаг; гоняться не за чем — сигнал только если пользователь так и не смог выйти из флоу. Отдельно смотреть на всплеск `verdict=single_token_unlisted` с `has_digits=true`: это форма «кто-то вставляет ключ в confirm-turn» — сам ключ в лог не попадает, но повод спросить у пользователя, что он делает |

**Почему shadow-поле `read_only_intent` исчезло, а не переехало.** Оно измеряло false-positive rate прозаического детектора — у нового механизма этого класса дефектов нет по построению: триггер исходит от пользователя, а не от догадки о тексте модели. Мерить больше нечего. Предыдущее окно наблюдения (закрыто 2026-07-26, знаменатель **0** — потолок, а не «мало данных»: вердикт считался **после** detector-гейта и на happy path молчал по построению) и было аргументом заменить механизм, а не донастраивать. История — § Deploy record BUG-086 выше и `BUG_LOG.md` § BUG-086.

**Ключевая инварианта при разборе инцидента:** `write_intent_router_resume` **никогда** не означает мутацию. Он вооружает preview; сама мутация требует ВТОРОГО «да» уже на framework'овый preview и видна как `fsm_confirm_execute` (BUG-009 / BUG-046 гейт сохранён). Прод-трейс деградированной формы — три turn'а: отчёт+`write_intent_set` → «да»+`write_intent_router_resume`+`fsm_confirm_armed` → «да»+`fsm_confirm_execute`.

> ⚠️ **`write_intent_dropped` с `reason=fsm_armed` — не баг, а fail-safe, и в проде он пока не срабатывал ни разу.** Смысл ветки ([`handlers.py:688–694`](../../tg_parser/bot/handlers.py)): если на входе в turn вооружён FSM **и** жив snapshot, побеждает FSM — два механизма подтверждения не могут быть вооружены одновременно. Но **последовательным** путём такое состояние недостижимо: set-сайт снапшота — `elif` **ниже** всех трёх arm-ветвей (`831` preview → `850` clarify → `866` pagination → `882` write-intent), т.е. один turn не может одновременно вооружить `PaginationFlow` и оставить snapshot — ровно эту несущую роль `elif`-цепочки фиксирует комментарий на месте («an independent `if` would arm `PaginationFlow` AND leave a snapshot behind»); а снапшот поп'ается в самом верху следующего текстового turn'а (`681`), до любого state-гейта. Похоже, ветку достаёт только конкурентная обработка апдейтов. Поэтому: увидели `reason=fsm_armed` — не «нормальный трафик», а повод проверить, откуда взялась одновременность.

### Где смотреть в Grafana

Если Grafana уже настроена (см. `docker/grafana/provisioning/`) — можно собрать панель ad-hoc прямо в UI:

1. **Panel 1: F5-C Outcomes (stacked area)** — `sum by(outcome) (rate(tg_resummarize_total[5m]))`.
2. **Panel 2: F5-C Token cost per hour** — `sum by(model, token_type) (rate(tg_resummarize_tokens_total[5m]) * 3600)`.
3. **Panel 3: F5-C Duration p50 / p95 / p99** — `histogram_quantile(0.5/0.95/0.99, ...)`.
4. **Panel 4: topic_card_versions row count** — Prometheus не покрывает; либо PostgreSQL exporter (если есть), либо ручной SQL.

> 💡 После 1-2 недель прода — эти панели можно зашить в provisioning JSON для постоянного дашборда (отдельная задача в Phase 2 issue).

---

## Tripwire response

### Tripwire #1 — `llm_error` > 10%

**Что значит:** LLM возвращает невалидный JSON / падает при парсинге / hits rate-limit.

**Действия:**
1. Проверить логи: `docker compose logs tg_parser | grep -E 'f5c_resummarize_failed|InvalidJSON|RateLimit'`.
2. Если rate-limit — снизить `RESUMMARIZE_MAX_PER_TICK` (например, с 10 до 3) через env-var и `docker compose up -d tg_parser` (RE-CREATE, **не** `restart` — иначе baked OS-env сохранится, изменение молча no-op; BUG-078-класс). Изменение не требует миграции / рестарта DB.
3. Если систематический InvalidJSON на конкретной модели — переключить scope на другую модель runtime через MCP: `set_llm_config(scope="resummarize", provider="openai", model="gpt-4o-mini")`. Изменение применяется к новым LLM-вызовам без рестарта.
4. Если #2 / #3 не помогают — kill-switch: `RESUMMARIZE_ENABLED=false` в `.env` + `docker compose up -d tg_parser` (RE-CREATE, **не** `restart` — `RESUMMARIZE_ENABLED` scheduler-critical, иначе baked OS-env сохранится и kill-switch молча no-op; BUG-078-класс). F5-C выключится, counter `new_items_since_last_summary` продолжит инкрементироваться (eventual consistency сохранится — после re-enable F5-C подхватит накопившихся кандидатов).

### Tripwire #2 — `version_raced` > 5%

**Что значит:** advisory-lock + UNIQUE constraint срабатывают чаще, чем ожидалось — две одинаковые темы пытаются re-summarize одновременно. Это не data corruption, но потеря работы (LLM-токены потрачены, summary не сохранён).

**Действия:**
1. Проверить, не запущены ли два worker'а параллельно: `docker compose ps | grep -E 'tg_parser'` (scheduler работает внутри `tg_parser` контейнера, отдельного compose-сервиса нет). Должна быть только одна реплика.
2. Если scheduler один — проверить, не дёргает ли кто-то `force_resummarize` через MCP / CLI на тех же темах одновременно с автоматическим тиком. Сообщить admin'ам.
3. Если ни #1, ни #2 — это **бага**, открыть GH issue с logs + PromQL screenshot. Decision #2 / #5 / #4d должны были это исключить — нужен post-mortem.

### Tripwire #3 — `duration p95 > 30 s`

**Что значит:** одна re-summarize заняла >30 с (почти таймаут scheduler tick'a).

**Действия:**
1. Проверить per-model breakdown: `histogram_quantile(0.95, rate(tg_resummarize_duration_seconds_bucket{model="gpt-4o-mini"}[15m]))`. Если только один model — переключиться через `set_llm_config`.
2. Снизить `RESUMMARIZE_INPUT_WINDOW_N` (например, с 10 до 5) — меньше items в prompt → быстрее LLM.
3. Если LLM здоров, но duration высокий — проверить network latency между API и LLM-провайдером (могут быть IPv6 / DNS проблемы на VPS).

### Tripwire #4 — source paused via `_pause_source_for_billing`

**Что значит:** `AnthropicBillingError` всплыл *внутри текущего интервала между cron-тиками*, scheduler пометил source как paused — F5-C сделал свою работу (Decision #13).

**Семантика alarm-а (после TD-NEW-B, 2026-04-27):**
- Alarm срабатывает на **delta** `tg_parser_anthropic_billing_block_total` между двумя последовательными запусками `f5c_watch.sh`, не на абсолютное значение counter-а.
- State хранится в `${F5C_WATCH_STATE_DIR:-~/.f5c-watch}/billing_block_state` (single-line ASCII number).
- **Первый запуск после деплоя**: no baseline → alarm подавлен (warm-up), state записывается для следующего тика. Ожидается одна `first run, no baseline` строка в `cron.log`.
- **Container restart** (counter reset, prev > current): delta clamped to 0, alarm подавлен. Любые *новые* billing events после рестарта tripp-нут на следующем тике.
- **Cumulative counter ≠ 0 but delta = 0**: означает, что billing-инцидент уже случился, но в текущем окне новых не было — это GREEN. До TD-NEW-B такая ситуация показывала false-positive TRIPWIRE до перезапуска API.

**Действия при настоящем delta > 0:** см. [`ANTHROPIC_BILLING_RECOVERY.md`](ANTHROPIC_BILLING_RECOVERY.md). После восстановления баланса — снять pause через MCP / CLI, F5-C автоматически возобновится на следующем тике (счётчик не потерял значение, но и delta вернётся к 0 как только новые pause-ы перестанут происходить).

---

## Rollback

Если деплой пошёл совсем плохо — F5-C спроектирован под backward-compatible откат:

```bash
# 1. Остановить F5-C через kill-switch (мгновенно, без миграции)
echo "RESUMMARIZE_ENABLED=false" >> ~/TG_parser/.env
docker compose up -d tg_parser   # RE-CREATE (НЕ restart — RESUMMARIZE_ENABLED scheduler-critical, иначе baked OS-env сохранится, kill-switch молча no-op; BUG-078-класс)

# 2. Если нужен hard rollback (вернуть код):
cd ~/TG_parser
git checkout <commit-before-f5c>  # например, e1b7ba1 (последний pre-F5C)
docker compose pull && docker compose --profile bot up -d --no-deps tg_parser mcp tg_bot

# 3. Откат миграции (опасно — теряются audit-trail rows; обычно НЕ нужен,
# потому что F11/F6 изолированы от F5-C):
tg-parser db downgrade --db processing --revisions 1 --yes
# → drops topic_card_versions + 3 columns from topic_cards
# → IMPORTANT: исторические версии тем теряются навсегда; для MVP допустимо.
```

Backward-compat проверена: F11 watchlist + F6 digest продолжают работать без F5-C-колонок (см. Sprint F5-C planning § «Migration / Backward»).

---

## T7 — Включение `RESUMMARIZE_MAX_AGE_DAYS` (freshness; prod LIVE `=21` с 2026-07-22, изначальный консервативный default `14`)

> ✅ **LIVE в проде `RESUMMARIZE_MAX_AGE_DAYS=21` с 2026-07-22 19:49Z** (bump `14 → 21` по owner GO; re-create `docker compose up -d tg_parser`, StartedAt `2026-07-22T19:49:08Z`, health `healthy`; backup `.env.bak.delta-t7-20260722T194808Z`). **История:** knob был LIVE `=14` c 2026-07-19 20:36Z; +48h watch **PASSED** (~2026-07-21 23:36 EEST); re-snapshot 2026-07-22T14:56Z дал `ratio14d≈0.989`, alert `ResummarizeAgeTriggerGateF5CPhase2` **firing** (`severity=info`), age-dominated (`labdiagnostica_logical`≈24, `mediamedics`≈11 / 24h) → **δ watch CLOSED, verdict bump `14 → 21`** (keep-14 rejected). Rollback: `=14` или `=0` + `up -d` (NOT `restart`, BUG-078). Verdict: [`DELTA_T7_VERDICT_2026-07-22.md`](../notes/DELTA_T7_VERDICT_2026-07-22.md). Prior: [`C2_T7_LIVE_SNAPSHOT_2026-07-20.md`](../notes/C2_T7_LIVE_SNAPSHOT_2026-07-20.md).
>
> ✅ **Re-watch checkpoint CLOSED 2026-08-05 — keep `=21`.** Trailing-14d окно полностью post-bump; raw `ratio14d≈0.989` / alert всё ещё `firing`, но **не** как провал cutoff: ≈330/365 age-событий за 14d — `refusal_cooldown` на poison-pill `labdiagnostica_logical` (BUG-083, `comment:8992`), zero-cost skips ~1/tick. Продуктивный mix без cooldown: age `ok`≈35 / counter `ok`≈4. Bump `→30` **rejected**; gate = info noise. **Событие B deferred.** Полная запись: [`DELTA_T7_VERDICT_2026-07-22.md`](../notes/DELTA_T7_VERDICT_2026-07-22.md) § «Re-watch checkpoint CLOSED».

### Что делает knob

`RESUMMARIZE_MAX_AGE_DAYS` (env, `settings.resummarize_max_age_days`, `tg_parser/config/settings.py:1134`) — **time-based** триггер re-summarize, который **дополняет, а не заменяет** counter-триггер `RESUMMARIZE_TRIGGER_N`. При `> 0` тема дополнительно становится кандидатом, если её последнее summary старше N дней **И** у неё есть хотя бы один новый item (`new_items_since_last_summary > 0`) — даже если counter ещё не дошёл до `RESUMMARIZE_TRIGGER_N`. Это ловит low-volume темы, которые морально устаревают, ни разу не набрав порог счётчика.

- Предикат `new_items > 0` сохранён умышленно → candidate-query остаётся под partial-index `idx_topic_cards_resummarize_candidates` (без full-scan).
- Отбор кандидатов — чистый SQL OR-предикат в `TopicCardRepo.list_resummarize_candidates` (`run_for_channel` передаёт `max_age_days=settings.resummarize_max_age_days`, `tg_parser/services/resummarization_service.py:208`); LLM на этапе отбора не вызывается.
- Почему именно при отборе селектится «age»: см. `_classify_trigger` (`tg_parser/services/resummarization_service.py:112`) — `counter` (counter ≥ N) / `age` (только time-based ветка) / `-` (force или путь без card).
- Хук тот же, что у MVP: `run_resummarize_for_channel`. Начиная с decoupling-правки он вызывается **в каждом** scheduler-тике (включая «тихие» тики без новых документов) — он вынесен ИЗ блока `if new_doc_refs:` (зеркало ENH-001 для F11 watchlist), чтобы age-ветка могла сработать на low-volume каналах, которые никогда не добирают counter-порог. Порядок сохранён: хук по-прежнему идёт ПЕРЕД F11 watchlist, поэтому при наличии новых документов matcher всё так же скорит по самому свежему summary (`tg_parser/services/scheduler_service.py`, вызов `rs_summary = await run_resummarize_for_channel(...)`). Нового surface нет.

### Рекомендованный консервативный prod-default ≈ 14 дней (rationale)

- Согласован со stale-detector из tracking-issue #15 («> 14 days»): тема, не обновлявшаяся 2 недели, при появлении новых items считается «морально устаревшей».
- Достаточно длинный, чтобы НЕ ре-суммаризировать активные темы повторно (их и так гоняет counter-триггер) — age-ветка добивает только хвост low-volume тем.
- KB вырос ~2× (≈745 топиков) → доля low-volume тем, стареющих без counter-триггера, реально значима; 14д — это «добивающий», а не «основной» триггер.
- Граница оценки агрессивности зашита в gate (см. ниже): если age-ветка начинает давать **большинство** re-summarize, default 14д надо удлинять.

### Как включить (когда будет go) — безопасно, поэтапно

1. **Pre-flight cost baseline.** Снять текущий per-channel re-summarize cost (24ч) ДО включения — будет с чем сравнивать:
   ```promql
   sum(increase(tg_resummarize_total[24h])) by (channel_id, trigger)
   sum(increase(tg_resummarize_tokens_total[24h])) by (channel_id, token_type)
   ```
   Ожидание до включения: `trigger="age"` ≈ 0 (knob disabled). Прикинуть размер хвоста stale-тем:
   ```sql
   -- processing-БД; сколько тем разом станут age-кандидатами на первом тике
   SELECT COUNT(*) FROM topic_cards
   WHERE new_items_since_last_summary > 0
     AND new_items_since_last_summary < 5            -- < RESUMMARIZE_TRIGGER_N
     AND last_summarized_at < NOW() - INTERVAL '14 days';
   ```
2. **Включить env (один knob, без миграции, без рестарта DB):**
   > 📌 **Historical.** Значение ниже — первоначальный консервативный default на момент включения (2026-07-19). Live-значение с 2026-07-22 — **`21`** (см. баннер вверху раздела); при повторном включении ставить актуальное, а не `14`.
   ```bash
   # ~/TG_parser/.env  — поставить значение явно (НЕ оставлять 0)
   RESUMMARIZE_MAX_AGE_DAYS=14
   docker compose up -d tg_parser   # RE-CREATE контейнера → перечитывает compose-интерполяцию
   # docker compose up -d --force-recreate tg_parser   # жёсткая гарантия
   ```
   > ⚠️ **НЕ `docker compose restart` (BUG-078-класс).** `restart` не пересоздаёт контейнер → старый baked OS-env (`RESUMMARIZE_MAX_AGE_DAYS=0`) сохраняется, а pydantic по BUG-078 отдаёт приоритет OS-env над bind-mounted `/app/.env` → значение `14` молча игнорируется, фича остаётся DORMANT. Интерполяция `${RESUMMARIZE_MAX_AGE_DAYS:-0}` перечитывается только при RE-CREATE (`up -d`).
   Триггер и каппинг тюнятся тем же стеком env, что у MVP — менять DB / схему не нужно.
3. **Наблюдать первые 24–48 ч** по разделу § Мониторинг ниже (особенно первый тик после re-create — там вскрывается накопленный хвост stale-тем).

> ⚠️ **Главный риск — cost-spike на ПЕРВОМ включении.** Весь хвост stale-тем фитит age-предикат одновременно → всплеск кандидатов на первых тиках. Митигируется существующим triple-cap (`RESUMMARIZE_MAX_PER_TICK=10` / `RESUMMARIZE_MAX_DURATION_S=60` / `RESUMMARIZE_MAX_TOKENS_PER_TICK=50000` per channel per tick) + fair-scheduling (`ORDER BY new_items DESC, updated_at DESC`): backlog растягивается на несколько тиков, абсолютный per-tick потолок cost **не меняется** от включения knob. Можно дополнительно занизить `RESUMMARIZE_MAX_PER_TICK` на время «переваривания» хвоста, затем вернуть.

### Cost implications (LLM-вызовы за тик)

- Каждый re-summarize = **1 LLM-вызов** (scope `resummarize`, провайдер/модель — через `RESUMMARIZE_LLM_PROVIDER`/`RESUMMARIZE_LLM_MODEL`, иначе наследуется глобальный `LLM_PROVIDER`/`LLM_MODEL`).
  > ⚠️ Репозиторный default (`gpt-4o-mini`, `tg_parser/processing/llm/factory.py`) **не равен** проду. Живой резолв стейджа на 2026-08-05: **`anthropic` / `claude-sonnet-4-6`** (per-stage переменных для `resummarize` в prod `.env` нет ⇒ наследуется глобальный). Cost-оценки ниже считались по прайсу `gpt-4o-mini` — при пересчёте брать фактическую модель. Снимать живьём: `get_llm_config` (MCP) или `resolve_llm_config("resummarize")` в контейнере.
- Включение age-триггера **повышает объём** re-summarize (добавляет хвост low-volume тем), но **не повышает per-tick потолок**: triple-cap бьёт по числу тем / wall-time / токенам на тик per channel независимо от того, какой предикат отобрал тему.
- Абсолютный TCO upper bound тот же, что у MVP: `RESUMMARIZE_MAX_TOKENS_PER_TICK=50000` × 24 тика/день ≈ ~1.2M tokens/day/channel в худшем случае; на практике — десятки центов / месяц / канал (см. § Cost выше).
- Тюнинг при перерасходе: поднять `RESUMMARIZE_MAX_AGE_DAYS` (реже триггерит хвост), либо понизить `RESUMMARIZE_INPUT_WINDOW_N` (дешевле prompt), либо поднять `RESUMMARIZE_TRIGGER_N`.

### Мониторинг (per-channel cost + freshness gate)

Метрики уже инструментированы (Wave 2 #10 — реальный `channel_id` в зарезервированном label):

```promql
# Доля «age»-триггера в общем re-summarize-миксе (cost от включения knob)
sum(rate(tg_resummarize_total{trigger="age"}[1h]))
  / sum(rate(tg_resummarize_total{trigger=~"counter|age"}[1h]))

# Per-channel re-summarize rate (какой канал гонит spend)
sum(rate(tg_resummarize_total[1h])) by (channel_id, trigger)

# Per-channel token-cost (channel_id="-" = card неизвестен)
sum(rate(tg_resummarize_tokens_total[1h])) by (channel_id, token_type)
```

Готовые панели и алерты **уже provisioned** (этот раздел их только описывает, дублировать JSON не нужно):

- **Grafana:** dashboard `docker/grafana/dashboards/wave2_observation.json`, row **«T7 F5-C P2 — Re-summarize freshness»** — панели: re-summarize rate by channel & outcome, outcomes 24h, **tokens by channel (rate + cumulative)**, duration p50/p95, **trigger split counter-vs-age** (rate + 24h), и **age-trigger 14d share** (stat + timeseries, observation-only).
- **Prometheus:** `docker/prometheus/alerts.yml` —
  - recording rule `tg:resummarize_age_trigger:ratio14d` = `age / (counter + age)` за trailing 14д. Исключены **и** bucket `-`, **и** `outcome="refusal_cooldown"` (обе части дроби) — zero-cost скипы карантинных тем больше не считаются селекцией кандидата (BUG-083, правка 2026-08-05);
  - **T7 GATE `ResummarizeAgeTriggerGateF5CPhase2` — СНЯТ 2026-08-06.** Решение, ради которого он существовал, закрыто (keep `=21`, bump `→30` rejected). Даже без `refusal_cooldown` честная доля **0.88** (замер 2026-08-06): на тихих каналах age-ветка легитимно даёт большинство **продуктивных** re-summarize (≈28 против 4 counter / 14д) при ~2 успешных age в день на всю систему ⇒ алерт был бы вечно-красным. `ratio14d` остался как observation-сигнал на панелях;
  - **`ResummarizeRefusalCooldownPoisonPill`** (info, `for: 6h`) поверх recording rule `tg:resummarize_refusal_cooldown:count24h` = `sum(increase(tg_resummarize_total{outcome="refusal_cooldown"}[24h])) by (channel_id)`: фитит при `>= 12` за 24ч на канал;
  - `ResummarizeLLMErrorRate` (info, `for: 30m`): `outcome="llm_error"` доля > 20% за 30м — health LLM-провайдера re-summarize. **Denominator excludes `refusal_cooldown`** (zero-cost BUG-083 skips; 2026-08-11) so free poison-pill ticks do not dilute the tripwire; poison-pill visibility = `ResummarizeRefusalCooldownPoisonPill`.

> ⚠️ **Деплой правил Prometheus (BUG-090).** Канонический источник — [`PRODUCTION_DEPLOYMENT.md`](../../PRODUCTION_DEPLOYMENT.md) § deploy step 4b; здесь только выжимка, при расхождении верить ему.
> ```bash
> ssh prod 'cd ~/TG_parser && git pull --ff-only'
> ssh prod 'docker exec tg_parser_prometheus wget -q -O- --post-data="" http://localhost:9090/-/reload'
> # доказательство, что контент реально доехал:
> ssh prod 'docker exec tg_parser_prometheus grep -c <новый-символ> /etc/prometheus/conf/alerts.yml'
> ssh prod 'docker exec tg_parser_prometheus promtool check rules /etc/prometheus/conf/alerts.yml'   # число правил должно ИЗМЕНИТЬСЯ
> ```
> **Почему нужны именно эти проверки.** До 2026-08-06 каждый файл монтировался по отдельности, а bind-mount файла привязан к его **inode**; `git pull` не правит файл на месте, а делает `rename()` ⇒ контейнер вечно держал старый файл. При этом `promtool check` **внутри** контейнера печатал SUCCESS, проверяя ровно тот устаревший файл, а `docker compose up -d` отвечал `Running` и не пересоздавал. С 2026-08-06 смонтирована **директория** `docker/prometheus`, и подмена файла видна сразу — но проверять контент всё равно обязательно: «SUCCESS» сам по себе не доказывает, что доехала новая версия.
>
> `--force-recreate` нужен только если менялся сам маунт или `command` сервиса. Данные Prometheus в named volume ⇒ re-create историю не теряет.

**Что делать, если `refusal_cooldown` растёт (алерт `ResummarizeRefusalCooldownPoisonPill`).** Это **не** spend-инцидент: гард стоит до фетча бандла и до LLM, скип стоит 0 токенов. Это **staleness**-инцидент: у темы заморожено summary, и сама она не восстановится — refusal не коммитит новое summary ⇒ `last_summarized_at` не двигается ⇒ age-предикат отбирает её каждый тик вечно.

1. Найти тему: `docker exec tg_parser_postgres psql -U tg_parser_user -d tg_parser -c "SELECT id, metadata_json::jsonb ->> 'resummarize_refusal_until' AS until, metadata_json::jsonb ->> 'resummarize_refusal_count' AS cnt FROM topic_cards WHERE metadata_json::jsonb ? 'resummarize_refusal_until';"`
2. Понять, отказ ли это провайдера: лог `f5c_resummarize_refusal` в `docker logs tg_parser` + `metadata.resummarize_refusal_llm` (какой провайдер отказал).
3. Попытка вылечить — сменой провайдера на **одну** попытку. Механизм: `RESUMMARIZE_REFUSAL_FALLBACK_STAGE` (по умолчанию выключен; **не** включаем постоянно — это потребовало бы второго chat-LLM аккаунта). Разовый путь без записи в prod `.env` и без re-create (проверен 2026-08-05, вылечил `comment:8992`): снять маркеры `resummarize_refusal_until` / `_count` у одной темы, затем `docker exec -e RESUMMARIZE_REFUSAL_FALLBACK_STAGE=<stage> -e <STAGE>_LLM_PROVIDER=<other> -e <STAGE>_LLM_MODEL=<model> tg_parser tg-parser topic resummarize <topic_id>`. Fallback обязан резолвиться в **другого** провайдера — иначе он молча пропускается. Полная процедура: [`SESSION_F5C_MINIMAL_FALLBACK_2026-08-05.md`](../notes/SESSION_F5C_MINIMAL_FALLBACK_2026-08-05.md).
4. Если не вылечилось — cooldown встанет заново сам; тема остаётся с прежним summary, система в безопасном состоянии.

Acceptance после включения: per-channel token-cost в пределах baseline + ожидаемого хвоста; `refusal_cooldown` не растёт устойчиво. **Доля age больше не является критерием** — gate снят, ре-оценка `RESUMMARIZE_MAX_AGE_DAYS` теперь ручной cadence: смотреть `ratio14d` и абсолютный объём `trigger="age",outcome="ok"` при заметном росте KB или счёта за LLM, а не по алерту.

### Rollback (мгновенный, без миграции)

```bash
# Вернуть knob в disabled — age-триггер выключается на следующем тике,
# counter-триггер MVP продолжает работать как раньше (bit-for-bit).
# ~/TG_parser/.env
RESUMMARIZE_MAX_AGE_DAYS=0
docker compose up -d tg_parser   # RE-CREATE (НЕ restart — иначе baked OS-env=14 сохранится, откат молча no-op; тот же BUG-078-класс)
```

Откат миграции/кода НЕ требуется — это чистый env-knob поверх уже задеплоенной P2-инфраструктуры. Полный kill-switch фичи (если нужно) — `RESUMMARIZE_ENABLED=false` (см. § Rollback выше). `topic_card_versions` и накопленный counter не трогаются — после повторного включения age-триггер просто перестаёт/начинает добивать хвост.

---

## Helper-скрипт `docker/f5c_watch.sh`

В каждом чек-поинте можно дёрнуть единый скрипт вместо ручного PromQL/SQL — он печатает то же, что таблица выше, и возвращает структурированный exit-code:

```bash
ssh -p 2296 user@212.72.189.15 'cd ~/TG_parser && ./docker/f5c_watch.sh'           # человеко-читаемый отчёт
ssh -p 2296 user@212.72.189.15 'cd ~/TG_parser && ./docker/f5c_watch.sh --quiet'   # одна строка-вердикт для лога
```

Exit codes: `0` — все четыре tripwire'а молчат, `1` — сработал ≥1 tripwire (см. § Tripwire response), `2` — инфраструктурная проблема (API/MCP/DB недоступны). Параметры через ENV: `F5C_API_URL`, `F5C_API_KEY`, `F5C_LLM_ERR_THRESHOLD`, `F5C_VERSION_RACED_THRESHOLD`, `F5C_DURATION_P95_THRESHOLD_S`, `F5C_DB_NAME_PROCESSING` (см. шапку скрипта).

Для multi-day pilot можно повесить на cron:

```cron
0 */4 * * * /home/user/TG_parser/docker/f5c_watch.sh --quiet >> /var/log/f5c_watch.log 2>&1
```

> Use the absolute path of the deploy user's home (`~/TG_parser` expands to
> `/home/user/TG_parser` for the canonical deploy user) — cron does not expand `~`
> reliably across shell wrappers.

> Скрипт делает coarse-grained проверку (cumulative ratios + bucket-приближение для p95). Для точного rate-based анализа за окно — Grafana / PromQL из § PromQL queries выше.

---

## Post-watch report (через 24 ч)

После 24 ч успешного watch'a — закрыть пилот:

1. Снять метрики:
   ```promql
   sum by(outcome) (increase(tg_resummarize_total[24h]))
   sum by(model) (increase(tg_resummarize_tokens_total[24h]))
   histogram_quantile(0.5, rate(tg_resummarize_duration_seconds_bucket[24h]))
   histogram_quantile(0.95, rate(tg_resummarize_duration_seconds_bucket[24h]))
   ```
2. Снять SQL-снапшот размера `topic_card_versions` (rows + size MB).
3. Пост в Phase 2 issue **#15**: цифры за 24 ч + рекомендации по приоритизации Phase 2 (например, «после 24 ч 100k rows и 50 MB — пункт #1 TTL приоритет 1»).
4. Если всё OK — F5-C MVP считается **производственно стабильным**, можно стартовать любой пункт Phase 2 по сигналу.

### Post-watch report — шаблон комментария для issue #15

Скопировать в комментарий к [F5-C Phase 2 tracking issue](https://github.com/AlexEfimov/TG_parser/issues/15), подставить значения вместо `<...>`. Вердикт по каждому пункту — один из `green` / `yellow` / `red` (объяснить если не green).

```markdown
## F5-C MVP — 24h post-watch report

**Период:** `<deploy-time>` … `<deploy-time + 24h>` (UTC)
**Релиз:** tag `f5c-mvp-2026-04-26` / merge commit `29679e0`
**Скрипт:** `docker/f5c_watch.sh` (последний run: `<timestamp> exit=<code>`)

### 1. Outcome distribution (PromQL `sum by(outcome) (increase(tg_resummarize_total[24h]))`)

| outcome          | count | %     | comment |
|------------------|-------|-------|---------|
| ok               | <N>   | <pct> |         |
| locked           | <N>   | <pct> |         |
| llm_error        | <N>   | <pct> |         |
| version_raced    | <N>   | <pct> |         |
| empty_scope      | <N>   | <pct> |         |
| no_card          | <N>   | <pct> |         |
| no_bundle        | <N>   | <pct> |         |
| unknown          | <N>   | <pct> |         |
| **TOTAL**        | <N>   | 100%  |         |

**Acceptance:** `ok` ≥ 80% от total → **<green/yellow/red>**.

### 2. Cost (PromQL `sum by(model) (increase(tg_resummarize_tokens_total[24h]))`)

| model           | prompt tokens | completion tokens | est. USD |
|-----------------|---------------|-------------------|----------|
| gpt-4o-mini     | <N>           | <N>               | $<N>     |
| <other>         | <N>           | <N>               | $<N>     |

**Расчёт:** gpt-4o-mini = `$0.15/1M prompt + $0.60/1M completion`.
**Acceptance:** ниже планируемого upper bound (1.2M tokens/day/channel) → **<green/yellow/red>**.

### 3. Duration

- p50: `<N>s` (PromQL `histogram_quantile(0.5, rate(tg_resummarize_duration_seconds_bucket[24h]))`)
- p95: `<N>s` (тот же query, `0.95`)
- p99: `<N>s`

**Acceptance:** p95 < 30s → **<green/yellow/red>**.

### 4. SQL snapshot — `topic_card_versions`

```sql
SELECT COUNT(*), pg_size_pretty(pg_total_relation_size('topic_card_versions')),
       COUNT(DISTINCT topic_id), MAX(version_no), AVG(version_no)::numeric(10,2)
FROM topic_card_versions;
```

| rows | size | topics_with_history | max_version | avg_version |
|------|------|---------------------|-------------|-------------|
| <N>  | <X>  | <N>                 | <N>         | <N>         |

**Acceptance:** rows ≈ counter(`outcome=ok`); size в МБ, не ГБ → **<green/yellow/red>**.

### 5. Tripwires fired

- [ ] `#1 llm_error > 10%` — **<no/yes (детали)>**
- [ ] `#2 version_raced > 5%` — **<no/yes>**
- [ ] `#3 duration p95 > 30s` — **<no/yes>**
- [ ] `#4 anthropic billing pause` — **<no/yes>**

### 6. Производственный сигнал → приоритет Phase 2

| Пункт #15 | Сигнал из 24h | Приоритет |
|-----------|---------------|-----------|
| #1 TTL для `topic_card_versions` | rows growth `<rows/day>`, projected `<GB/year>` | <P0/P1/P2/-> |
| #4 Time-based триггер | темы с `last_summarized_at < deploy_time AND new_items > 0` | <P0/P1/P2/-> |
| #5 Bot tools | UX-запрос: <none/<details>> | <P0/P1/P2/-> |
| #10 Per-channel метрика | если виден skew по каналам | <P0/P1/P2/-> |
| иные пункты | — | -- |

### 7. Финальный вердикт

- [ ] **GREEN** — F5-C MVP **производственно стабилен**, watch закрыт; новый спринт можно стартовать.
- [ ] **YELLOW** — есть warnings, но не блокеры; watch продлить ещё на 24 ч.
- [ ] **RED** — сработал tripwire, требуется hot-fix или rollback.

### 8. Артефакты

- Snapshot всех графиков Grafana (`.png` в комментарии).
- Если что-то меняли в env-tunable конфиге — указать новые значения в `<...>`.
```

---

## Retention / purge для `topic_card_versions` (#15 item #1, ADR-0018)

> **Что это.** Конфиг-driven TTL для append-only истории `topic_card_versions`.
> Daily cron `topic_card_versions_purge` (03:30 UTC) hard-DELETEs строки, которые
> провалили **все три** защиты: (a) вне новейших `KEEP_LAST_N` версий темы **AND**
> (b) старше `RETENTION_DAYS` дней **AND** (c) `version_no > 1` (genesis-snapshot
> `version_no=1` **никогда** не удаляется). Двойной floor = recent (keep-last-N) +
> origin (genesis-pin). Полное обоснование: [ADR-0018](../adr/0018-topic-card-versions-retention.md).

**Default = no-op.** Code-default `RESUMMARIZE_VERSION_RETENTION_DAYS=0` ⇒ деплой
кода **ничего не удаляет** (kill-switch, bit-for-bit MVP «храним всё»). Purge
включается только явной установкой prod-value.

**Prod-числа (owner-chosen):** `RETENTION_DAYS=180`, `KEEP_LAST_N=50`. Sanity floor
`RETENTION_DAYS ≥ 2 × RESUMMARIZE_MAX_AGE_DAYS` (LIVE=21 ⇒ 2×21=42 ≤ 180 ✓; при
нарушении scheduler логирует `topic_card_versions_purge_retention_below_floor`,
purge продолжается).

> **Два раздельных события (нормативно, не смешивать):**
> **Событие A** = выкатить код (default-off, no-op для прода) — можно на любом
> штатном деплой-окне. **Событие B** = флип `RETENTION_DAYS=180` (destructive-capable)
> — отдельный in-session owner GO (T7 re-watch 2026-08-05 закрыт; B на нём
> deferred — см. [`DELTA_T7_VERDICT_2026-07-22.md`](../notes/DELTA_T7_VERDICT_2026-07-22.md)).
> Событие A **не** запускает purge; Событие B требует Событие A уже задеплоенным.

---

### Событие A — деплой кода (default-off, no-op) — deploy-checklist

> Выкатывает retention-механизм в **выключенном** состоянии. Prod-поведение
> **не меняется** bit-for-bit: cron `topic_card_versions_purge` регистрируется и
> каждый тик `self-skip`'ается (`RESUMMARIZE_VERSION_RETENTION_DAYS=0` — code-default,
> в prod `.env` knob **не** ставим на этом шаге). Безопасно на обычном окне.

> ✅ **ВЫПОЛНЕНО 2026-07-24** (~06:40–06:49 UTC / 08:40–08:49 CEST, ручной VPS-деплой).
> Событие A задеплоено в **default-off (no-op)** состоянии — retention **НЕ** включён.
>
> - **Commit range:** `4b499e4 → e608b04` (fast-forward, **0 Alembic-миграций**). Батч из 32 коммитов; помимо TTL-кода (#346) также выкатил diff-API (#350 — #15 item #2), scheduler-fix (#336) и docs.
> - **Pre-deploy backup:** `data/backups/postgres_20260724_084029.sql.gz` (357M) — rollback point.
> - **Build:** образ `tg_parser:latest`, `tg-parser==4.3.0`.
> - **Re-create (BUG-078, НЕ `restart`):** `docker compose up -d --no-deps tg_parser mcp`.
> - **Health:** `tg_parser` + `tg_parser_mcp` оба `healthy`; `GET /health` → `status: ok, database: ok`.
> - **MCP:** FastMCP registry = **47 tools**, вкл. `get_topic_history_diff` и `get_topic_versions`.
> - **CLI:** `tg-parser topic diff` зарегистрирован («Diff two versions of a topic's evolving summary (F5-C #15 item #2)»).
> - **TTL default-off подтверждён:** `settings.resummarize_version_retention_days = 0`, `resummarize_version_keep_last_n = 50` → purge **DISABLED**. Daily cron `30 3 * * *` зарегистрирован, но self-skip'ается (kill-switch).
> - **E2E diff smoke** на `topic:tg:mediamedics:post:13525` (14 версий): default `v1 → current` ✅ (читает живую карточку), archival pair `v1 → v14` ✅, missing-версия `v99999` → typed not-found, clean `exit=1`, без traceback/500 ✅.
> - **Событие B НЕ выполнено:** `RESUMMARIZE_VERSION_RETENTION_DAYS=180` в prod **не** ставился. На re-watch 2026-08-05 снова **deferred** (would_purge ещё ~0); отдельный owner GO когда появятся кандидаты.
> - **Ещё не подтверждено (future/вне окна):** лог `topic_card_versions_purge_skipped` при первом ночном тике 03:30 UTC (следующий — 2026-07-25); проверки `/metrics`, baseline-rows и `tg-parser topic purge-versions --dry-run` в этом окне не выполнялись (оставлены неотмеченными ниже).

**Pre-deploy:**
- [x] PR смержен в `main`, CI зелёный (в т.ч. `TEST_POSTGRES=1` матрица).
- [x] Подтвердить, что prod `.env` **НЕ** содержит `RESUMMARIZE_VERSION_RETENTION_DAYS`
      (или он `=0`) — иначе это уже Событие B, а не A. `grep RESUMMARIZE_VERSION .env` → пусто/0.

**Deploy:**
- [x] Pre-deploy backup: `./docker/backup.sh` → `data/backups/postgres_20260724_084029.sql.gz` (357M).
- [x] `git checkout main && git pull --ff-only origin main` → `4b499e4 → e608b04` (fast-forward).
- [x] `docker compose build tg_parser` → `tg_parser:latest`, `tg-parser==4.3.0`.
- [x] Миграции (если есть): **не было** — деплой fast-forward с **0 Alembic-миграций** (шаг N/A на этом окне).
- [x] **Re-create, НЕ `restart`** (BUG-078): `docker compose up -d tg_parser` (фактически `up -d --no-deps tg_parser mcp`).

**Post-deploy verify (всё должно подтверждать «выключено»):**
- [x] `docker exec tg_parser env | grep RESUMMARIZE_VERSION` → `RETENTION_DAYS` отсутствует/`0`, `KEEP_LAST_N=50` (code-default).
- [ ] В логах при первом ночном тике (03:30 UTC) — `topic_card_versions_purge_skipped {reason=retention_disabled}` (НЕ `topic_card_versions_purge`).
- [ ] Метрики экспонируются: `curl -s localhost:.../metrics | grep tg_topic_card_versions` → gauge/counter присутствуют (gauge не обновляется на skip-path — это ожидаемо).
- [ ] `topic_card_versions` не изменился (rows как в baseline).
- [ ] CLI доступен: `tg-parser topic purge-versions --dry-run` (даже при `=0` он напечатает «Retention disabled … DB untouched»).

**Rollback Событие A:** обычный откат образа + `up -d` (re-create). Ничего в БД не изменено → откат чистый.

> ✅ После Событие A механизм «взведён»: включение (Событие B) — это один
> `.env`-edit + `up -d`, **без** нового кода/CI/ревью.

---

### Growth baseline (перед включением — Событие B)

```sql
-- ssh prod / docker exec tg_parser_postgres psql (processing-БД)
SELECT COUNT(*) AS rows,
       pg_size_pretty(pg_total_relation_size('topic_card_versions')) AS size,
       COUNT(DISTINCT topic_id) AS topics_with_history,
       MAX(version_no) AS max_version,
       AVG(version_no)::numeric(10,2) AS avg_version
FROM topic_card_versions;
```
```bash
# rows/day proxy (successful re-summarize за 24h) → проекция GB/year
ssh prod "docker exec tg_parser_prometheus promtool query instant http://localhost:9090 'sum(increase(tg_resummarize_total{outcome=\"ok\"}[24h]))'"
```

### Dry-run (всегда перед первым destructive run)

```bash
tg-parser topic purge-versions --dry-run
# печатает: mode=DRY-RUN, keep_last_n, retention_days+cutoff, predicate,
#           rows total + WOULD purge (тот же предикат вкл. version_no > 1)
```

### Событие B — включить retention в prod (owner GO; T7 re-watch больше не gate)

> **Триггер:** отдельный in-session owner GO. Re-watch δ/T7 ≈ 2026-08-05
> **закрыт** (`=21` OK) — на том checkpoint Событие B **сознательно deferred**
> (would_purge ещё ~0 до ~октября 2026; safety bound без срочности).
> Prerequisite: Событие A уже задеплоено. Hard-DELETE **необратим** → обязателен
> backup + dry-run. Решение зафиксировано в [`DELTA_T7_VERDICT_2026-07-22.md`](../notes/DELTA_T7_VERDICT_2026-07-22.md)
> § «Re-watch checkpoint CLOSED».

**Checklist (Событие B):**
- [ ] **owner GO** получен в текущей сессии.
- [ ] Событие A подтверждено задеплоенным (`grep RESUMMARIZE_VERSION` → код есть, cron self-skip'ается).
- [ ] Свежий **baseline snapshot** снят (см. выше) — evidence по M/N.
- [ ] **Dry-run** на живых данных → зафиксировать `WOULD purge` (ожидаемо всё ещё ~0, пока нет строк >180d):

```bash
# 1. Backup таблицы (hard-DELETE необратим!):
ssh prod "docker exec tg_parser_postgres pg_dump -U tg_parser_user -d tg_parser -t topic_card_versions" \
  > topic_card_versions.bak.$(date -u +%Y%m%dT%H%M%SZ).sql
# 2. Dry-run sanity count (см. § Dry-run выше) — зафиксировать число.
# 3. Backup .env + выставить knobs в prod .env:
#    RESUMMARIZE_VERSION_RETENTION_DAYS=180
#    RESUMMARIZE_VERSION_KEEP_LAST_N=50
cp .env .env.bak.ttl-$(date -u +%Y%m%dT%H%M%SZ)
# 4. Re-create (НЕ restart — BUG-078):
docker compose up -d tg_parser
docker exec tg_parser env | grep RESUMMARIZE_VERSION   # ждём RETENTION_DAYS=180 / KEEP_LAST_N=50
```

- [ ] **Verify первый on-path тик** (следующий 03:30 UTC): лог `topic_card_versions_purge {deleted, table_size, ...}` (НЕ `_skipped`); gauge `tg_topic_card_versions_rows` обновился; counter `tg_topic_card_versions_purged_total` ≥ 0.
- [ ] Зафиксировать факт включения + первый `deleted` в этой же note / BUG_LOG.

**Rollback Событие B:** `RESUMMARIZE_VERSION_RETENTION_DAYS=0` в `.env` → `docker compose up -d tg_parser` (re-create). Останавливает **будущие** purge; уже удалённые строки восстановимы **только** из backup (шаг 1).

### Observability

- Gauge `tg_topic_card_versions_rows` — row count после каждого purge-тика.
- Counter `tg_topic_card_versions_purged_total` — cumulative удалённых строк.
- Log `topic_card_versions_purge {deleted, table_size, keep_last_n, retention_days, cutoff, duration_s}`
  (или `topic_card_versions_purge_skipped` при `retention_days=0`).
- **Grafana Panel 4** (`topic_card_versions row count`) — раньше только ручной SQL;
  теперь можно завести на gauge `tg_topic_card_versions_rows`.

> Rollback покрыт per-event выше: **Событие A** — откат образа + `up -d`;
> **Событие B** — `RETENTION_DAYS=0` + `up -d` (останавливает будущие purge;
> удалённое восстановимо только из backup).

> ℹ️ `get_topic_versions` / `tg-parser topic versions` возвращают оставшиеся
> версии; gaps в `version_no` = retention policy (не потеря данных багом), genesis
> `version_no=1` всегда присутствует ⇒ read-path не 500-ит на gaps.

---

## FAQ

### Q: F5-C ничего не делает после деплоя — `tg_resummarize_total = 0`. Сломан?

**A:** Скорее всего — нет. После decoupling-правки сам хук `run_resummarize_for_channel` вызывается в **каждом** тике (даже без новых документов), поэтому «не было ingestion в этом тике» больше НЕ объясняет нулевой `tg_resummarize_total` — реальный гейт это наличие кандидатов. Проверь:
1. Идут ли вообще scheduler-тики? `tg-parser pipeline status` или `docker compose logs tg_parser | grep _process_source` — должны быть регулярные тики (если их нет — проблема в scheduler, а не в F5-C).
2. Есть ли темы-кандидаты? Counter-ветка: `SELECT COUNT(*) FROM topic_cards WHERE new_items_since_last_summary >= 5;`. Age-ветка (только если `RESUMMARIZE_MAX_AGE_DAYS > 0`): темы старше N дней с `new_items_since_last_summary > 0`.
3. Если #2 = 0 — F5-C bypass'ится **legitимно**: нет кандидатов, нет работы. Дождись накопления новых items в темах (а при включённой age-ветке — устаревания low-volume тем).
4. Если #2 > 0, но `tg_resummarize_total` всё ещё 0 — проверь `RESUMMARIZE_ENABLED` в env (`grep RESUMMARIZE_ENABLED .env`). Если установлен в `false` — это и есть причина.

### Q: Force-resummarize через CLI работает, а scheduler tick — нет.

**A:** Force-resummarize обходит порог (Decision #1) и kill-switch (`RESUMMARIZE_ENABLED=false` его НЕ блокирует — это admin-tool). Если force работает, а tick — нет, значит проблема в scheduler (не в F5-C самом). Проверь `docker compose logs tg_parser | grep _process_source` — должны быть регулярные тики.

### Q: Хочу включить F5-C только для одного канала на пилоте.

**A:** Не поддерживается в MVP. F5-C — global on/off через `RESUMMARIZE_ENABLED`. Если нужен per-channel pilot — это пункт-кандидат для Phase 2 (можно добавить в issue #15 как item #11).
