# Runbook — BUG-103: четыре мелких дефекта поверхности bot/MCP (R5)

**Создан:** 2026-08-16 (сессия R5). **Статус: ВЫПОЛНЕНО 2026-08-16** по GO владельца — merge `#430` → `3b6072c`, recreate `tg_parser` + `mcp` + `tg_bot`. MCP `list_topics(limit=-5)` отдаёт одну строку и `pagination_pending` с `offset=1`; неизвестный `workspace_id` с отрицательными границами — пустая страница `offset=0` `limit=1`, не ошибка.

**Что деплоим:** батч F-06 / F-08 / F-09 / F-11 ([BUG-103](../notes/BUG_LOG.md)). Описание сервера совпадает с пустым / 404-like результатом; `resource_channel_topics` итерирует `topics.items`; `clamp_page_bounds` зажимает отрицательные `offset`/`limit` без верхнего потолка страницы; заголовок watchlist уходит через `html.escape`.

**Не docs-only.** Меняются [`mcp_server.py`](../../tg_parser/mcp_server.py), [`bot/tools.py`](../../tg_parser/bot/tools.py), [`utils/pagination.py`](../../tg_parser/utils/pagination.py). **Миграции нет.** Пересоздаются **все три** сервиса (общий образ). Recreate `tg_parser` сдвигает фазу hourly incremental-pipeline (урок R10) — следующий тик ≈ старт + 3600 с.

---

## 0. Перед деплоем

| Проверка | Факт 2026-08-16 |
|---|---|
| Прод до pull | `185e83a` (R12 docs); один образ на трёх сервисах `5e182dd6503f…`, все `healthy` |
| Тик | scheduler с R12 стартовал **08:50:31Z**; следующий incremental был **09:50:31Z**. Recreate в окне (`health_check` только), тик не резали |
| Откат | `tg_parser:pre-r5-2026-08-16` → `5e182dd6503f…` |
| Backup | `data/backups/postgres_pre_r5_20260816.sql.gz`, **368M** |
| `.env` / миграции | не трогали |

---

## 1. Деплой

Процедура — [`PRODUCTION_DEPLOYMENT.md`](../../PRODUCTION_DEPLOYMENT.md) § Updating. Пересоздавать контейнер, **не** `restart` (BUG-078); `--force-recreate` обязателен (BUG-090). Миграции нет — `db upgrade` не вызываем. Bot живёт под профилем `bot`.

```bash
ssh prod 'cd /home/user/TG_parser && git pull --ff-only origin main'
ssh prod 'cd /home/user/TG_parser && docker compose build tg_parser'
ssh prod 'cd /home/user/TG_parser && docker compose up -d --no-deps --force-recreate tg_parser'
ssh prod 'cd /home/user/TG_parser && docker compose up -d --no-deps --force-recreate mcp'
ssh prod 'cd /home/user/TG_parser && docker compose --profile bot up -d --no-deps --force-recreate tg_bot'
```

Фактически: прод HEAD `185e83a` → **`3b6072c`**, новый образ **`054fceef30c0…`** на всех трёх. `tg_parser` пересоздан **09:14:51 UTC**, `mcp` **09:14:53**, `tg_bot` **09:14:55**. Parser и MCP `healthy` сразу; bot — к концу минуты. `GET /health` → 200 `status=ok`. Scheduler started **09:15:09 UTC** — следующий incremental-тик ≈ **10:15:09 UTC**, не 09:50.

---

## 2. Настройки — ничего

Новых ключей `.env` нет. Миграции нет. Верхний потолок страницы в настройку не выносили (out of scope R5 / ловушка BUG-092).

---

## 3. Smoke (сразу, не тиком)

Поверхность: прод-MCP `user-tg-parser`. F-11 живым `subscribe_watchlist` не гоняли — не создавать интерес ради экранирования; путь проверен `html.escape(created_interest.title)` в образе и тестом `test_watchlist_confirmation_escapes_title_html`.

| Проверка | Ожидание | Факт 2026-08-16 09:15 UTC |
|---|---|---|
| MCP `list_channels` | R12 жив: `degraded=false`, числовое покрытие | ✅ 14 каналов, `foodf4thought` 81.63 |
| MCP `list_topics(foodf4thought, limit=3)` | страница из 3, `has_more=true` | ✅ `total=30` |
| MCP `list_topics(…, limit=-5)` (F-08) | одна строка, `limit=1`, `pagination_pending.offset=1` | ✅ не slice-from-end |
| MCP `list_channels` неизвестный workspace + `offset=-10` `limit=-5` (F-06+F-08) | пустая страница, `offset=0` `limit=1`, не ошибка | ✅ |
| Код в образе | `raises a 404-like error` нет; `topics.items`; `html.escape` | ✅ |
| `GET /health` | 200 `status=ok` | ✅ |

Живой `resource_channel_topics` из `docker exec` без MCP-контекста падает в `PermissionError` (R1 fail-closed) — это не регресс F-09. Ресурс итерирует `.items`; конверт `list_topics` на живом MCP отдаёт `items`.

---

## 4. Что этот деплой НЕ закрывает

- **R6 / BUG-104** — стоп-лист, без симуляции не включать.
- **Bot-арм BUG-099** — `get_default_admin()` в исполнителях. Не трогали.
- **BUG-008** — `open` by design.
- Верхний потолок страницы по-прежнему не настройка.

---

## 5. Откат

Тег на образе **до** R5. Откатывать сразу recreate, иначе `latest` перезапишется.

```bash
ssh prod 'docker tag tg_parser:pre-r5-2026-08-16 tg_parser:latest \
  && cd /home/user/TG_parser && docker compose up -d --no-deps --force-recreate tg_parser \
  && docker compose up -d --no-deps --force-recreate mcp \
  && docker compose --profile bot up -d --no-deps --force-recreate tg_bot'
```
