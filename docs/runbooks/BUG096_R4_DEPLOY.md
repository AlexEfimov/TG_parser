# Runbook — BUG-096 (R4): MCP `download_url` больше не 404

**Создан:** 2026-08-15 (сессия R4). **Статус: ВЫПОЛНЕНО 2026-08-15** по GO владельца — merge `#426` → `75c8c07`, recreate `tg_parser` + `mcp` + `tg_bot`. Живой MCP-`export_channel` → GET `download_url` → **200**.

**Что деплоим:** HTTP-dispatch экспорта ([BUG-096](../notes/BUG_LOG.md), вариант b, ADR-0007). MCP больше не пишет файл у себя: `export_channel` делает `POST /api/v1/export` с `X-API-Key`. Новые джобы кладут файл в `output/<job_id>/`. Bot остаётся синхронным, пишет в `output/<uuid4>/`. Класс ловят [`tests/test_bug096_export_job_path.py`](../../tests/test_bug096_export_job_path.py) и compose-плечо [`TestComposeMcpExportDownload`](../../tests/test_compose_pipeline_dispatch_integration.py).

**Не docs-only.** Меняются `mcp_server.py`, `api/routes/export.py`, `pipeline_dispatch_client.py`, `bot/tools.py`, плюс хелпер `services/export_job_access.py`. **Миграции нет.** Пересоздаются **все три** сервиса. Recreate `tg_parser` сдвигает фазу hourly incremental-pipeline (урок R10) — следующий тик ≈ старт + 3600 с.

---

## 0. Перед деплоем

| Проверка | Факт 2026-08-15 |
|---|---|
| Прод до pull | `0137b70` (docs); образы `mcp`/`tg_bot` R9 `2478721db563`, `tg_parser` R2 `63de8a1123c5` |
| Тик | последний `incremental_pipeline` завершился **09:30:57Z** (14/0/0, 73.64 с); следующий был **10:29:44Z**. Recreate начат в окне, тик не резали |
| Откат | `tg_parser:pre-r4-parser-2026-08-15` → `63de8a1123c5`; `pre-r4-mcp-2026-08-15` / `pre-r4-bot-2026-08-15` → `2478721db563` |
| Backup | `data/backups/postgres_pre_r4_20260815.sql.gz`, **368M** |
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

Фактически: прод HEAD `0137b70` → **`75c8c07`**, новый образ **`2984f88f4198`** на всех трёх. `tg_parser` пересоздан **10:01:11 UTC**, `mcp` **10:01:17**, `tg_bot` **10:01:37**. Parser и MCP `healthy` сразу; bot — к концу минуты. `GET /health` → 200 `status=ok`. Scheduler started **10:01:22 UTC** — следующий incremental-тик ≈ **11:01:22 UTC**, не 11:00.

---

## 2. Настройки — ничего

Новых ключей `.env` нет. Миграции нет. Общий том `output/` **не** добавляли (вариант a отклонён).

---

## 3. Smoke (сразу, не тиком)

Поверхность: прод-MCP `user-tg-parser`, `whoami` → `role=admin` `c59d42b4`. Канал `medportal_rfed`, `level=raw`, `format=json`. Тело файла в чат не выносилось — только метаданные и проверки на хосте.

| Проверка | Ожидание | Факт 2026-08-15 10:06 UTC |
|---|---|---|
| MCP `export_channel` | `status=pending`, непустой `job_id` | ✅ `8d53c1fa-9bd8-47f0-beee-c9bd217f00ad` |
| `get_export_status` | `completed` + `download_url` + `file_size` | ✅ URL `/api/v1/export/download/8d53c1fa-…`, **247870** байт |
| `api_jobs.file_path` | содержит `job_id` | ✅ `output/8d53c1fa-…/raw_messages.json`, `client=admin` |
| Файл на `tg_parser` | есть | ✅ `/app/output/8d53c1fa-…/raw_messages.json` 247870 |
| Файл на `tg_parser_mcp` | нет | ✅ каталога `/app/output` нет |
| `GET` `download_url` с `X-API-Key` | 200, непусто, без `raw_payload` | ✅ 200, 247870 байт, `raw_payload` отсутствует |
| Код в образах | MCP зовёт `post_export`; bot — `uuid4` | ✅ in-container inspect |

Workaround «экспорт для скачивания — через HTTP, не MCP» снят.

---

## 4. Что этот деплой НЕ закрывает

- **Bot-арм BUG-099** — `get_default_admin()` в остальных исполнителях. В `_exec_export_channel` его не трогали.
- **R3 / BUG-102 / BUG-098a** — форма ответов. Следующая в очереди.
- **Старые джобы** `1561b9da-…` и `9e3408af-…` с плоским `output/raw_messages.json` оставлены; download по-прежнему открывает `file_path` как есть.

---

## 5. Откат

Три тега на образах **до** R4. Откатывать каждый своим тегом, сразу recreate, иначе `latest` перезапишется.

```bash
ssh prod 'docker tag tg_parser:pre-r4-parser-2026-08-15 tg_parser:latest \
  && cd /home/user/TG_parser && docker compose up -d --no-deps --force-recreate tg_parser'
ssh prod 'docker tag tg_parser:pre-r4-mcp-2026-08-15 tg_parser:latest \
  && cd /home/user/TG_parser && docker compose up -d --no-deps --force-recreate mcp'
ssh prod 'docker tag tg_parser:pre-r4-bot-2026-08-15 tg_parser:latest \
  && cd /home/user/TG_parser && docker compose --profile bot up -d --no-deps --force-recreate tg_bot'
```
