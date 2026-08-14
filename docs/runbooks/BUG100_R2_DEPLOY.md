# Runbook — BUG-100 / BUG-101 (R2): чужой id на read-инструменте больше не отдаёт контент

**Создан:** 2026-08-14 (сессия R2). **Статус: ВЫПОЛНЕНО 2026-08-14** по GO владельца — merge `#422` → `ca737fc`, smoke §3 в ту же минуту. Явный чужой `channel_id` на `list_topics` даёт пустую страницу на bot, HTTP и MCP; админ по-прежнему видит темы. Одноразовый `user`-токен отозван.

**Что деплоим:** RBAC-паритет read-инструментов ([BUG-100](../notes/BUG_LOG.md), [BUG-101](../notes/BUG_LOG.md)). `list_topics` с явным чужим `channel_id` — пустая страница на bot и HTTP (MCP уже так делал). Экспорт сверяет `job.client == user.name`. Topic-хит без карточки отбрасывается. Класс ловит [`tests/test_bug100_bug101_explicit_id_matrix.py`](../../tests/test_bug100_bug101_explicit_id_matrix.py).

**Не docs-only.** Меняются `bot/tools.py`, `api/routes/topics.py`, `api/routes/export.py`, `mcp_server.py`, `retrieval_service.py`. **Миграции нет.** Пересоздаются **все три** сервиса: `tg_parser` (HTTP + retrieval), `mcp` (`get_export_status`), `tg_bot` (`_exec_list_topics`). Recreate `tg_parser` сдвигает фазу hourly incremental-pipeline (урок R10) — следующий тик ≈ старт + 3600 с, не следующий час по часам.

---

## 0. Перед деплоем

| Проверка | Команда / ожидание | Факт 2026-08-14 |
|---|---|---|
| Прод и `origin/main` сходятся после мержа | `ssh prod 'cd /home/user/TG_parser && git rev-parse --short HEAD'` | ✅ после `git pull --ff-only`: прод `963b16e` → **`ca737fc`** |
| Точки отката **трёх** образов | тег на крутящемся образе каждого сервиса, не общий `latest` | ✅ `tg_parser:pre-r2-parser-2026-08-14` → **`bdb3292dd7e9`** (R11); `tg_parser:pre-r2-mcp-2026-08-14` → **`5f6939dc9a5c`** (R1); `tg_parser:pre-r2-bot-2026-08-14` → **`94b713377d91`** |
| Backup | `pg_dump` до recreate | ✅ `data/backups/postgres_pre_r2_20260814_132551.sql.gz`, **368M** |
| Эскалировать некого | 5 строк `user` без `user_auth_mappings`; живой credential только у admin | ✅ до smoke так и было; после — плюс retired-строка без mapping |
| `.env` | не трогаем | ✅ не меняли |

---

## 1. Деплой

Процедура — [`PRODUCTION_DEPLOYMENT.md`](../../PRODUCTION_DEPLOYMENT.md) § Updating. Пересоздавать контейнер, **не** `restart` (BUG-078); `up -d` без изменения rendered spec не пересоздаёт, поэтому `--force-recreate` обязателен (BUG-090). Миграции нет — `db upgrade` не вызываем. Bot живёт под профилем `bot`.

```bash
ssh prod 'cd /home/user/TG_parser && git pull --ff-only origin main'
ssh prod 'cd /home/user/TG_parser && docker compose build tg_parser'
ssh prod 'cd /home/user/TG_parser && docker compose up -d --no-deps --force-recreate tg_parser'
ssh prod 'cd /home/user/TG_parser && docker compose up -d --no-deps --force-recreate mcp'
ssh prod 'cd /home/user/TG_parser && docker compose --profile bot up -d --no-deps --force-recreate tg_bot'
```

Фактически: прод HEAD `963b16e` → **`ca737fc`**, новый образ **`63de8a1123c5`** на всех трёх. `tg_parser` пересоздан **13:29:24 UTC**, `mcp` **13:29:32**, `tg_bot` **13:29:35**. Все `healthy` к **13:30:11 UTC**. `GET /health` → 200 `status=ok`. Scheduler started **13:29:44 UTC** — следующий incremental-тик ≈ **14:29:44 UTC**, не 14:00.

---

## 2. Настройки — ничего

Новых ключей `.env` нет. Миграции нет.

---

## 3. Smoke (сразу, не тиком)

Контроль: admin `list_topics(channel_id=medportal_rfed)` → **total=17**.

| Проверка | Ожидание | Факт 2026-08-14 13:32–13:33 UTC |
|---|---|---|
| Рабочий admin-токен | `whoami` жив | ✅ `role=admin` `c59d42b4`, 19 каналов |
| Одноразовый `user`-токен, MCP `list_topics(medportal_rfed)` | пустая страница | ✅ `total=0`, `n_items=0`. Своя поверхность: `list_topics()` без фильтра → `total=0` |
| Bot in-process `_exec_list_topics` с `allowed=["no_such_channel"]` | пусто; admin — 17 | ✅ `user_total=0`; `admin_total=17` |
| HTTP in-process `GET /topics?channel_id=medportal_rfed` той же личностью | пусто; admin — 17 | ✅ `user_total=0`; `admin_total=17` |
| Отзыв | mapping снят, пользователь retired | ✅ `zz-retired-probe-bug100-20260814`, `max_channels=0`, `user_auth_mappings` пусто |

Живой HTTP с `X-API-Key` через `ssh python3 -c` не доехал из-за кавычек bash; ключ к тому моменту уже был выдан и отозван вместе с MCP-токеном. Дыру закрывает тот же код-путь, что in-process вызов `list_topics` на крутящемся `tg_parser`.

`/health` у MCP по-прежнему `{"status":"degraded","database":"not_initialized"}` при HTTP 200 — не регресс R2 (то же, что после R1).

---

## 4. Что этот деплой НЕ закрывает

- **Bot-арм BUG-099** — `current_user or await get_default_admin()` в 34 из 35 исполнителей. Hardening после R2, теперь очередь свободна.
- **Форма ответов (R3 / BUG-102)** — topic-hit projection, `entry_type`, `items`/`subscriptions`/`interests`.
- **High остаётся латентным** — на проде по-прежнему нет живого не-admin credential. Гейт «до выпуска первого такого токена» снят кодом, не наличием второго арендатора.
- **`process.py` PROCESSING-джобы** — вне scope F-10.

---

## 5. Откат

Три разных старых образа. Откатывать каждый своим тегом, сразу recreate, иначе `latest` перезапишется.

```bash
ssh prod 'docker tag tg_parser:pre-r2-parser-2026-08-14 tg_parser:latest \
  && cd /home/user/TG_parser && docker compose up -d --no-deps --force-recreate tg_parser'
ssh prod 'docker tag tg_parser:pre-r2-mcp-2026-08-14 tg_parser:latest \
  && cd /home/user/TG_parser && docker compose up -d --no-deps --force-recreate mcp'
ssh prod 'docker tag tg_parser:pre-r2-bot-2026-08-14 tg_parser:latest \
  && cd /home/user/TG_parser && docker compose --profile bot up -d --no-deps --force-recreate tg_bot'
```

Цена отката — явный чужой `channel_id` на bot/HTTP `list_topics` снова отдаёт темы; чужой `job_id` снова виден. Миграции откатывать нечего. Полное восстановление БД — из backup §0 (на этом деплое схема не менялась).

---

## 6. Ссылки

- [BUG-100](../notes/BUG_LOG.md) / [BUG-101](../notes/BUG_LOG.md) — механизм, диспозиция `Job.client`, smoke.
- [`START_PROMPT_FIX_BUG100_BUG101_RBAC_READ_PARITY_R2_2026-08-14.md`](../notes/START_PROMPT_FIX_BUG100_BUG101_RBAC_READ_PARITY_R2_2026-08-14.md)
- [`PRODUCTION_DEPLOYMENT.md`](../../PRODUCTION_DEPLOYMENT.md) § Updating — `--force-recreate`, не `restart`; bot под `--profile bot`.
- [`BUG099_R1_DEPLOY.md`](BUG099_R1_DEPLOY.md) — предыдущий деплой; оттуда «не recreate `tg_parser` без нужды». Здесь нужда была.
