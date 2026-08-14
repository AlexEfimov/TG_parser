# Runbook — BUG-094 (R9): `add_channel` больше не затирает курсор ingestion

**Создан:** 2026-08-14 (сессия R9). **Статус: ВЫПОЛНЕНО 2026-08-14** по GO владельца — merge `#424` → `8d870e5`, recreate только `mcp` и `tg_bot`. `tg_parser` оставлен на образе R2, hourly incremental-pipeline не сдвигался.

**Что деплоим:** частичный update на `add_channel` ([BUG-094](../notes/BUG_LOG.md), вариант a). Повторный вызов overlay'ит только переданные поля; `last_post_id` переживает settings edit. Класс ловит [`tests/test_bug094_add_channel_preserves_cursor.py`](../../tests/test_bug094_add_channel_preserves_cursor.py).

**Не docs-only.** Меняются `mcp_server.py`, `bot/tools.py`, `cli/add_source_cmd.py`, плюс хелпер `storage/source_overlay.py`. HTTP `add_channel` нет — `tg_parser` не пересоздавали. **Миграции нет.**

---

## 0. Перед деплоем

| Проверка | Факт 2026-08-14 |
|---|---|
| Прод до pull | `96b01e2` (docs R2), код — образ R2 `63de8a1123c5` на всех трёх |
| Откат | `tg_parser:pre-r9-mcp-2026-08-14` / `pre-r9-bot-2026-08-14` / `pre-r9-parser-2026-08-14` → все `63de8a1123c5` |
| `.env` / миграции | не трогали |

---

## 1. Деплой

```bash
ssh prod 'cd /home/user/TG_parser && git pull --ff-only origin main'
ssh prod 'cd /home/user/TG_parser && docker compose build tg_parser'
ssh prod 'cd /home/user/TG_parser && docker compose up -d --no-deps --force-recreate mcp'
ssh prod 'cd /home/user/TG_parser && docker compose --profile bot up -d --no-deps --force-recreate tg_bot'
```

`tg_parser` **не** recreate (урок R10: сдвигает hourly incremental-pipeline).

Факт: прод HEAD `96b01e2` → **`8d870e5`**, новый образ **`2478721db563`** на `mcp` и `tg_bot`. `tg_parser` остался на **`63de8a1123c5`**, `StartedAt` не менялся (~8 часов uptime). Оба новых контейнера `healthy` в течение минуты.

---

## 2. Smoke (read-only)

Живой owner-`add_channel` **не вызывали** — без снимка до/после он как раз и есть этот баг.

| Проверка | Ожидание | Факт |
|---|---|---|
| Хелпер в установленном mcp/bot | `source_overlay.py` в site-packages | ✅ `/opt/venv/lib/python3.12/site-packages/tg_parser/storage/source_overlay.py` |
| Хелпер в `tg_parser` | отсутствует (старый образ) | ✅ `find_spec` → False |
| Сигнатура MCP `add_channel` | defaults `None` / `None` | ✅ |
| Курсоры живых каналов | не тронуты этим деплоем | ✅ `medportal_rfed.last_post_id=123`; `mediamedics.last_post_id=15396` |
| Health | mcp/bot/parser healthy | ✅ |

Owner-вызов `add_channel` без лишних полей со сверкой строки — отдельный GO, не этот деплой.

---

## 3. Что этот деплой НЕ закрывает

- **Bot-арм BUG-099** — `get_default_admin()` в остальных исполнителях.
- **R4 / BUG-096** — экспорт, следующая сессия.
- **CLI-флаги** — `include_comments` default False / `--batch-size` 100 по-прежнему утверждают значения, если флаги не переданы; курсор CLI уже сохраняет.

---

## 4. Откат

```bash
ssh prod 'docker tag tg_parser:pre-r9-mcp-2026-08-14 tg_parser:latest \
  && cd /home/user/TG_parser && docker compose up -d --no-deps --force-recreate mcp'
ssh prod 'docker tag tg_parser:pre-r9-bot-2026-08-14 tg_parser:latest \
  && cd /home/user/TG_parser && docker compose --profile bot up -d --no-deps --force-recreate tg_bot'
```

`tg_parser` откатывать не нужно: он и так на `pre-r9-parser`.
