# Runbook — BUG-104: стоп-лист keywords (R6)

**Создан:** 2026-08-16 (сессия R6). **Статус: КОД ЗАДЕПЛОЕН 2026-08-16** по GO владельца — merge `#436` → `261f178`, recreate `tg_parser` + `mcp` + `tg_bot`. **Relink не делали** — второй GO. BUG-104 остаётся `in-progress`, пока нет полного `link_topics` @ 0.32.

**Что деплоим:** константа `KEYWORD_STOPLIST` (24 слова сида) в [`_extract_keywords`](../../tg_parser/services/analytics_service.py). Решение A: стоп-лист как есть, порог **0.32**, df не включать. Симуляция — [`R6_STOPLIST_LINKING_SIMULATION_2026-08-16.md`](../notes/R6_STOPLIST_LINKING_SIMULATION_2026-08-16.md): прогноз relink **4970** links.

**Не docs-only.** Меняется экстрактор keywords. **Миграции нет.** Пересоздаются **все три** сервиса (общий образ). Recreate `tg_parser` сдвигает фазу hourly incremental-pipeline (урок R10) — следующий тик ≈ старт + 3600 с.

---

## 0. Перед деплоем

| Проверка | Факт 2026-08-16 |
|---|---|
| Прод до pull | `8e3b98f` (docs R6 start prompt); образ `054fceef30c0…` на трёх сервисах, все `healthy` |
| Тик | incremental завершился **10:16:27Z** (14/0, 78 с); следующий был **11:15:09Z**. Recreate в окне, тик не резали |
| Откат | `tg_parser:pre-r6-2026-08-16` → `054fceef30c0…` |
| Backup | `data/backups/postgres_pre_r6_20260816.sql.gz`, **368M** |
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

Фактически: прод HEAD `8e3b98f` → **`261f178`**, новый образ **`5924dcfc43c3…`** на всех трёх. `tg_parser` пересоздан **10:22:54 UTC**, `mcp` **10:23:01**, `tg_bot` **10:23:05**. Parser и MCP `healthy` сразу; bot — к концу минуты. `GET /health` → 200 `status=ok`. Scheduler started **10:23:07 UTC** — следующий incremental-тик ≈ **11:23:07 UTC**, не 11:15.

---

## 2. Настройки — ничего

Новых ключей `.env` нет. Миграции нет. Стоп-лист — константа, не env (ловушка BUG-092).

---

## 3. Smoke (сразу, не тиком)

Поверхность: прод-MCP `user-tg-parser` + `docker exec` live analytics.

| Проверка | Ожидание | Факт 2026-08-16 10:23 UTC |
|---|---|---|
| `KEYWORD_STOPLIST` в образе | 24 слова, есть «для» | ✅ 24 |
| MCP `get_cross_channel_stats` → `keyword_overlaps` | нет `для` / `при` / `как` / `его` (live из карточек) | ✅ `stoplist_hits []`, overlap_count 2737 |
| `GET /health` | 200 `status=ok` | ✅ |
| `topic_links` | таблица **не** пересчитана | ✅ 4422 @ 0.3523, `dla_alone` 27 (тик 10:15 дописал 11 vs 4411) |
| MCP `get_related_topics(foodf4thought:651)` | старые ярлыки, пока нет relink | ✅ «для»/«как»/«его» на месте; `mind_rise:550` = `["для"]` |

---

## 4. Что этот деплой НЕ закрывает

- **Полный relink** — второй GO. Без `delete_all` + `link_topics` @ 0.32 старые `shared_keywords` остаются. Не CLI `link-topics` без `--threshold 0.32`. Не во время `incremental_pipeline`.
- **BUG-104 `resolved`** — только после relink и замера §5 стартового промпта.
- **Bot-арм BUG-099** — `get_default_admin()`. Не трогали.
- **BUG-008** — `open` by design.

---

## 5. Откат

Тег на образе **до** R6. Откатывать сразу recreate, иначе `latest` перезапишется. Таблица `topic_links` этим деплоем не менялась — откат кода её не чинит и не портит.

```bash
ssh prod 'docker tag tg_parser:pre-r6-2026-08-16 tg_parser:latest \
  && cd /home/user/TG_parser && docker compose up -d --no-deps --force-recreate tg_parser \
  && docker compose up -d --no-deps --force-recreate mcp \
  && docker compose --profile bot up -d --no-deps --force-recreate tg_bot'
```
