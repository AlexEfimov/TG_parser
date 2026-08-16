# Runbook — BUG-098 (b): покрытие `list_channels` снова считается (R12)

**Создан:** 2026-08-16 (сессия R12). **Статус: ВЫПОЛНЕНО 2026-08-16** по GO владельца — merge `#432` → `a6066f6`, recreate `tg_parser` + `mcp` + `tg_bot`. MCP `list_channels` → `degraded=false`, у всех 14 каналов числовое `coverage_percent`. `foodf4thought` 81.63 совпал с `GET /api/v1/channels/foodf4thought/stats`.

**Что деплоим:** перепись `coverage_counts_by_channel` ([BUG-098](../notes/BUG_LOG.md) половина b / BUG-066 item 2). Correlated `EXISTS` по развёрнутому CTE сменился на materialized distinct-пары и hash-join. Маркер деградации R3 не трогали.

**Не docs-only.** Меняется SQL в [`processed_document_repo.py`](../../tg_parser/storage/sqlalchemy/processed_document_repo.py). **Миграции нет.** Пересоздаются **все три** сервиса (общий образ). Recreate `tg_parser` сдвигает фазу hourly incremental-pipeline (урок R10) — следующий тик ≈ старт + 3600 с.

---

## 0. Перед деплоем

| Проверка | Факт 2026-08-16 |
|---|---|
| Прод до pull | `4010ea7` (R3); один образ на трёх сервисах `74a1fd2b016f…`, все `healthy` |
| Тик | последний `incremental_pipeline` завершился **08:13:26Z**; следующий был **09:12:21Z**. Recreate в окне, тик не резали |
| Откат | `tg_parser:pre-r12-2026-08-16` → `74a1fd2b016f…` |
| Backup | `data/backups/postgres_pre_r12_20260816.sql.gz`, **368M** |
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

Фактически: прод HEAD `4010ea7` → **`a6066f6`**, новый образ **`5e182dd6503f…`** на всех трёх. `tg_parser` пересоздан **08:50:16 UTC**, `mcp` **08:50:22**, `tg_bot` **08:50:37**. Parser и MCP `healthy` сразу; bot — к концу минуты. `GET /health` → 200 `status=ok`. Scheduler started **08:50:31 UTC** — следующий incremental-тик ≈ **09:50:31 UTC**, не 09:12.

---

## 2. Настройки — ничего

Новых ключей `.env` нет. Миграции нет.

---

## 3. Smoke (сразу, не тиком)

Поверхность: прод-MCP `user-tg-parser`. Оракул — HTTP `GET /api/v1/channels/{id}/stats` того же канала, не `get_cross_channel_stats` и не `GET /channels`.

| Проверка | Ожидание | Факт 2026-08-16 08:51 UTC |
|---|---|---|
| MCP `list_channels` | `degraded=false`, `coverage_percent` число на каждом канале | ✅ 14 каналов, `degraded=false` |
| `foodf4thought` | совпадает с HTTP stats | ✅ list 81.63; HTTP `processed=343` `covered=280` `coverage_percent=81.63` |
| Код в образе | `AS MATERIALIZED` в `coverage_counts_by_channel` | ✅ |
| `QueryCanceledError` на этом запросе | нет в свежих логах mcp | ✅ |

Workaround «число брать из `get_cross_channel_stats`» снят.

---

## 4. Что этот деплой НЕ закрывает

- **R5 / BUG-103** — `#430`, независим.
- **R6 / BUG-104** — стоп-лист, без симуляции не включать.
- **Bot-арм BUG-099** — `get_default_admin()` в исполнителях. Не трогали.
- Маркер R3 остаётся на будущий настоящий таймаут.

---

## 5. Откат

Тег на образе **до** R12. Откатывать сразу recreate, иначе `latest` перезапишется.

```bash
ssh prod 'docker tag tg_parser:pre-r12-2026-08-16 tg_parser:latest \
  && cd /home/user/TG_parser && docker compose up -d --no-deps --force-recreate tg_parser \
  && docker compose up -d --no-deps --force-recreate mcp \
  && docker compose --profile bot up -d --no-deps --force-recreate tg_bot'
```
