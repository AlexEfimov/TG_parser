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

Owner-вызов `add_channel` без лишних полей — §2.1.

---

## 2.1 Smoke (живой owner-`add_channel`, 2026-08-15)

Протокол: [`START_PROMPT_VERIFY_BUG094_OWNER_ADD_CHANNEL_SMOKE_2026-08-15.md`](../notes/START_PROMPT_VERIFY_BUG094_OWNER_ADD_CHANNEL_SMOKE_2026-08-15.md). GO владельца в той сессии. Поверхность: прод-MCP `user-tg-parser`. Аргумент только `channel_id="medportal_rfed"` — `include_comments` / `batch_size` / `channel_username` не передавались (клиент не подставил `false`/`100`).

| | Факт |
|---|---|
| SHA | local + прод `0137b70` |
| Образ | `mcp` / `tg_bot` `2478721db563`; `tg_parser` оставлен на R2 `63de8a1123c5` |
| `whoami` | `role=admin`, id `c59d42b4-8e05-42a7-be7e-50e9d1f4b951` = `owner_id` строки |
| Ответ | `created=false`, `Channel 'medportal_rfed' updated (status=active).` |
| До (08:36:45Z) | `last_post_id=123`, `rate_limit_until=2026-07-15T11:21:43Z`, `last_attempt_at=last_success_at=updated_at=2026-08-15T08:30:37Z`, `include_comments=f`, `batch_size=100`, `status=active`, `fail_count=0`, `backfill_completed_at` NULL |
| После (08:38:34Z) | байт-в-байт то же, кроме `updated_at=2026-08-15T08:38:29Z` |
| Откат | не понадобился |
| Тик | optional follow-up: следующий incremental 09:29:44 UTC; сверки строки достаточно |

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
