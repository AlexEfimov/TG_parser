# 24h Watch — Bot Actions (Manual, 2026-05-22)

**Назначение:** пополнить series `tg_pipeline_trigger_total{surface=bot}` и проверить
bot-side health (FSM, agent routing, confirmation flow) **ручным** вводом через
Telegram-бот. Этот файл — companion к [`WATCH_24H_ACTIVITY_PLAN_2026-05-22.md`](WATCH_24H_ACTIVITY_PLAN_2026-05-22.md);
MCP/HTTP действия там, бот — здесь.

**Time anchors:**
- T+0 = `2026-05-22T17:42:42Z` = `21:42 MSK 22-05` (`d143e5d`).
- Окно ручных bot-действий: **T+0 → T+15h** (~`12:42 MSK 23-05`).
- Closure-сессия запускается `~14:25 MSK 23-05` (T+16h43).

**Интерфейс бота:** свободный текст (Gemini-агент роутит в tools); единственные slash-команды — `/start`, `/help`. Любая bot-write операция требует подтверждения в чате (FSM `ConfirmFlow`). Команды ниже — **шаблоны на русском**; формулировки можно адаптировать (агент толерантен), главное — сохранить намерение и суффиксы.

---

## 1. Безопасность

- **Суффикс** всех создаваемых через бот артефактов — `_bot_watch_smoke` (отдельно от MCP/HTTP `_watch_smoke`), чтобы cleanup был детерминирован.
- **Не** запускайте `add_channel` / `remove_channel` / `pause_channel` / `resume_channel` через бот — ingestion baseline замёрз.
- **Не** дёргайте `set_llm_config` / `reset_llm_config` / `reload_prompts` — LLM прод замёрз.
- `trigger_pipeline` через бот — **только один раз** на `mind_rise` (хватит для series `surface=bot`).
- Если бот ответил подтверждением (preview) — отвечайте **«да»** или **«нет»** текстом, без слэша; не отправляйте новый запрос поверх preview (FSM сожрёт его).
- **Все артефакты удалить к T+14h30** (см. §3 Cleanup), чтобы успеть до T+15h45 hard cut-off из основного плана.

---

## 2. Расписание ручных bot-действий

> Время указано как ориентир — ±15 минут допустимо. Главное — попасть в окно T+0…T+14h30 и пройти всю последовательность.

| # | Время (MSK) | T+N | Команда / текст в чат | Ожидаемая реакция бота |
|---|---|---|---|---|
| 1 | 22:12 22-05 | T+0h30 | `/start` → затем «Кто я?» → затем «Покажи каналы» | greeting + role; `whoami` → роль/access; `list_channels` → список с `mind_rise`, `genotek`, `AgeManagment` |
| 2 | 01:42 23-05 | T+4h00 | «Запусти обработку канала `mind_rise`» → подтвердить **«да»** на preview | `trigger_pipeline` → 200 / job dispatched; **series `tg_pipeline_trigger_total{surface="bot"}` +1** |
| 3 | 06:42 23-05 | T+9h00 | «Подпишись на watchlist по каналам `mind_rise`, `genotek`, ключевые слова health, longevity, порог 0.6, название `wl_bot_watch_smoke`» → подтвердить **«да»** | `subscribe_watchlist` → 201; `tg_watchlist_subscribe_total{surface=bot}` +1 |
| 4 | 08:42 23-05 | T+11h00 | «Покажи мои watchlists» → затем «Статус пайплайна для `mind_rise`» | `list_watchlists` → виден `wl_bot_watch_smoke`; `get_pipeline_status` → job `done` (после T+4h trigger) |
| 5 | 12:12 23-05 | T+14h30 | «Отпишись от watchlist `wl_bot_watch_smoke`» → подтвердить **«да»** → затем «Статус» / «Покажи каналы» | `unsubscribe_watchlist` → 204; финальная проверка bot-side health |

**Итого:** 5 точек, покрывающих read (1, 4), write-with-confirm (2, 3, 5), bot health check.

---

## 3. Cleanup через бот (≤ T+14h30)

| # | Действие | Команда |
|---|---|---|
| 1 | Снять bot watchlist | «Отпишись от watchlist `wl_bot_watch_smoke`» → «да» |
| 2 | Проверить, что чисто | «Покажи мои watchlists» → не должно быть `_bot_watch_smoke` |
| 3 | Финальная sanity-проверка | «Статус» / `/start` (FSM clear) |

Если бот вернул ошибку при отписке — записать в `BUG_LOG.md` и в closure-сессии под Open Items; не блокировать closure.

---

## 4. Чек-лист (для отметки выполнено)

- [ ] T+0h30 — `/start` + whoami + list_channels (sanity baseline)
- [ ] T+4h00 — trigger_pipeline `mind_rise` через бот (подтверждено `да`) → **surface=bot series +1**
- [ ] T+9h00 — subscribe_watchlist `wl_bot_watch_smoke` (подтверждено `да`)
- [ ] T+11h00 — list_watchlists + get_pipeline_status (видим `wl_bot_watch_smoke` и `done` job)
- [ ] T+14h30 — unsubscribe `wl_bot_watch_smoke` (подтверждено `да`) → list_watchlists подтверждает чистоту
- [ ] Финальный `/start` — FSM сброшен, состояние чистое

---

## 5. Примечания

- Если бот не зарегистрировал вас — сначала просите админа `register_user` через MCP, иначе `/start` ответит «Вы не зарегистрированы».
- Если preview-confirmation истёк (TTL 5 минут) — повторите команду, бот пере-сгенерит preview.
- Если `trigger_pipeline` вернул 409 `JobAlreadyRunning` — нормально, series инкрементировался; идём дальше.
- Точные формулировки можно подстроить под реальную лексику бота — Gemini-агент толерантен к синонимам; **главное — намерение и суффикс** `_bot_watch_smoke`.
- Если вы используете только slash-команды (`/start`, `/help`) — этого **недостаточно** для bot-side series; нужен хотя бы один natural-language `trigger_pipeline` (точка #2).
