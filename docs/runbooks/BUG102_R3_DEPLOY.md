# Runbook — BUG-102 / BUG-098a (R3): форма ответов read-поверхности

**Создан:** 2026-08-15 (сессия R3). **Статус: ВЫПОЛНЕНО 2026-08-15** по GO владельца — merge `#428` → `4010ea7`, recreate `tg_parser` + `mcp` + `tg_bot`. Живой MCP-smoke: topic-хит читаем, `list_channels` честно помечает деградацию, страница дайджестов и watchlist — только под `items`.

**Что деплоим:** форма ответов read-инструментов ([BUG-102](../notes/BUG_LOG.md), половина (a) [BUG-098](../notes/BUG_LOG.md)). Topic-хит проецируется из `topic_card` (`entry_type` / `title` / `summary` / `channel_id`). `list_digests` / `list_watchlists` больше не дублируют страницу под `subscriptions` / `interests`. `list_channels` возвращает `ChannelListResult { items, degraded, … }`; при timeout агрегата `coverage_percent=null` и `degraded=true`. Класс ловят [`tests/test_bug102_search_topic_projection.py`](../../tests/test_bug102_search_topic_projection.py) и [`tests/test_bug098a_channel_list_degraded.py`](../../tests/test_bug098a_channel_list_degraded.py).

**Не docs-only.** Меняются `services/search_result_projection.py`, `mcp_server.py`, `api/routes/rag.py`, `bot/tools.py`, `channel_service.py`. **Миграции нет.** Пересоздаются **все три** сервиса. Recreate `tg_parser` сдвигает фазу hourly incremental-pipeline (урок R10) — следующий тик ≈ старт + 3600 с, не :00 часа.

---

## 0. Перед деплоем

| Проверка | Факт 2026-08-15 |
|---|---|
| Прод до pull | `75c8c07` (R4); образ `2984f88f4198` на `tg_parser` / `tg_parser_mcp` / `tg_parser_bot`, все healthy. Scheduler started **10:01:22Z** |
| Тик | последний `incremental_pipeline` завершился **19:01:22Z → 19:02:25Z**. Следующий был бы **20:01:22Z**. Recreate начат после 19:02:25, тик не резали |
| Откат | `tg_parser:pre-r3-parser-2026-08-15` / `pre-r3-mcp-2026-08-15` / `pre-r3-bot-2026-08-15` → **`2984f88f4198`** |
| Backup | `data/backups/postgres_20260815_205910.sql.gz`, **368M** (закончился 19:01:03 CEST / ~19:01Z) |
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

Фактически: прод HEAD `75c8c07` → **`4010ea7`**, новый образ **`74a1fd2b016f`** на всех трёх. `tg_parser` пересоздан **19:12:07 UTC**, `mcp` **19:12:10**, `tg_bot` **19:12:13**. Parser и MCP `healthy` сразу; bot — в ту же минуту. `GET /health` → 200 `status=ok` (19:12:30Z). Scheduler started **19:12:21 UTC** — следующий incremental-тик ≈ **20:12:21 UTC**, не 20:00.

---

## 2. Настройки — ничего

Новых ключей `.env` нет. Миграции нет.

---

## 3. Smoke (сразу, не тиком)

Поверхность: прод-MCP `user-tg-parser`, `whoami` → `role=admin` `c59d42b4`, 19 каналов.

| Проверка | Ожидание | Факт 2026-08-15 19:13–19:15 UTC |
|---|---|---|
| `search_knowledge_base` hybrid, topic-хит | `entry_type="topic"`, непустые `title` / `summary` / `channel_id` | ✅ запрос «Искусственный интеллект в медицине…» на `medportal_rfed`: `source_ref=topic:tg:medportal_rfed:post:4`, `entry_type=topic`, `title` совпал с карточкой, `summary` — полный текст темы, `channel_id=medportal_rfed`. Соседние хиты — `entry_type=message`, `title=null` |
| `list_channels` | конверт `items` + `degraded=true`, `coverage_percent is None`; raw/processed/topics живые | ✅ `total=14`, `degraded=true`, `limit=null`; у всех 14 `coverage_percent=null`; `mediamedics` 11300 / 11298 / 259. В логе MCP — тот же `QueryCanceledError` на `coverage_counts_by_channel` (R12) |
| `list_digests` | страница только под `items`, нет `subscriptions` | ✅ `count=4`, ключ `subscriptions` отсутствует |
| `list_watchlists` | страница только под `items`, нет `interests` | ✅ `total=24`, `limit=5`, `has_more=true`; ключ `interests` отсутствует; `pagination_pending.args` несёт `is_active=null` |

Первый hybrid без фильтра канала вернул пустую ошибку клиента — в ту же секунду `list_channels` держал coverage-запрос до timeout. Повтор на одном канале прошёл. Это не регресс формы.

Workaround «читать `items`; topic-хит добирать через `get_topic_details`; `coverage_percent=0.0` считать отсутствующим» снят для формы. Само число покрытия по-прежнему брать из `get_cross_channel_stats` — до R12.

---

## 4. Что этот деплой НЕ закрывает

- **BUG-098 (b) / R12** — `coverage_counts_by_channel` по-прежнему падает по statement timeout на каждом вызове. Честность ответа есть; измеренного процента в `list_channels` нет.
- **Bot-арм BUG-099** — `get_default_admin()` в остальных исполнителях. Не трогали.
- **R5 / BUG-103** — четыре мелочи. Следующая в очереди.
- **HTTP `GET /channels` / `GET /channels/{id}/stats`** — вне scope R3.

---

## 5. Откат

Три тега на образах **до** R3. Откатывать каждый своим тегом, сразу recreate, иначе `latest` перезапишется.

```bash
ssh prod 'docker tag tg_parser:pre-r3-parser-2026-08-15 tg_parser:latest \
  && cd /home/user/TG_parser && docker compose up -d --no-deps --force-recreate tg_parser'
ssh prod 'docker tag tg_parser:pre-r3-mcp-2026-08-15 tg_parser:latest \
  && cd /home/user/TG_parser && docker compose up -d --no-deps --force-recreate mcp'
ssh prod 'docker tag tg_parser:pre-r3-bot-2026-08-15 tg_parser:latest \
  && cd /home/user/TG_parser && docker compose --profile bot up -d --no-deps --force-recreate tg_bot'
```

Цена отката — topic-хиты снова строка из `null`, страница дайджестов/watchlist снова под двумя ключами, `list_channels` снова голый список с немым `coverage_percent=0.0`. Миграции откатывать нечего. Полное восстановление БД — из backup §0 (на этом деплое схема не менялась).

---

## 6. Ссылки

- План: [`PLAN_REMEDIATION_BOT_MCP_2026-08-12.md`](../notes/PLAN_REMEDIATION_BOT_MCP_2026-08-12.md) §R3
- Код: merge `#428` → `4010ea7`, фича `c0fd5ff`
- Соседний протокол: [`BUG096_R4_DEPLOY.md`](BUG096_R4_DEPLOY.md)
