# Dev Resurrection — План

**Дата составления:** 19 апреля 2026
**Версия проекта:** v4.8.0+ (`main` = `410452a`)
**Тип задачи:** infra hygiene (отдельная инженерная задача, не довесок к фиче)
**Статус:** план; реализация — в отдельной исполнительной сессии после approve.
**Источники:** `docs/prompts/DEV_RESURRECTION_PROMPT.md`; read-only диагностика локального Postgres от 19 апреля 2026.

---

## TL;DR

1. **Стратегия — full rebuild** в обоих окружениях (локально и на VPS). Аргументы за in-place перевешиваются риском Frankenstein-схемы и стоимостью ручных DDL/stamp-операций.
2. **Порядок — последовательный.** Сначала локальный rebuild → затем заморозка runbook → затем VPS rebuild.
3. **Backfill — 1 канал** (`labdiagnostica_logical`, нужен для отложенного smoke F6). Остальные 4 (`AgeManagment`, `Lab4health`, `LongevityClub`, `genotek`) доподключаются после успешной верификации.
4. **CI guardrail** добавляется в этом же плане (раздел 7) — небольшой инкремент к `.github/workflows/ci.yml`, тесно связанный с задачей.
5. **После resurrection** — отложенный smoke F6 по плану из transcript предыдущей сессии (не дублируется здесь).

---

## 1. Decision matrix: in-place vs full rebuild

### 1.1. Контекст (подтверждено диагностикой локального Postgres, 19 апреля 2026)

| Факт | Значение |
|------|----------|
| Запущен | `tg_parser_postgres` (pgvector/pgvector:pg17), uptime 36+ ч |
| Volume | `tg_parser_pgvector17_data` (external) |
| Таблиц в `public` | 16 |
| Таблиц `alembic_version*` | **0** |
| `processed_documents.processed_at` тип | `character varying` (значения вида `2026-04-01T15:13:20Z`) |
| `sources` строк | 5 |
| `processed_documents` строк | 5411 |
| Latest `processed_at` | 2026-04-01 (~18 дней назад) |
| Отсутствуют (vs. main) | `users`, `user_auth_mappings`, `digest_subscriptions`, колонка `sources.owner_id` |
| Присутствуют | `document_embeddings`, `topic_links`, `topic_bundles` (это уже **post-initial** таблицы) |

Ключевое наблюдение: **схема — Frankenstein**. Не «pre-F4» в чистом виде (тогда бы не было `document_embeddings`), а «pre-F4 + частично post-initial, созданное через `Base.metadata.create_all()`». Не соответствует никакой существующей alembic revision.

### 1.2. Опция A — In-place patch

| Шаг | Что нужно сделать вручную | Риск |
|-----|----------------------------|------|
| 1 | Решить, какой revision соответствует текущей схеме (она не равна ни одной существующей) | Высокий — субъективно, легко ошибиться |
| 2 | `alembic stamp` для всех трёх БД (ingestion / raw / processing) под выбранный псевдо-baseline | Средний |
| 3 | Ручной DDL: `ALTER TABLE processed_documents ALTER COLUMN processed_at TYPE TIMESTAMPTZ USING processed_at::timestamptz` (×3 таблицы с такими же `*_at VARCHAR`) | Средний-высокий — могут оказаться NULL/невалидные значения, бесшумная порча данных |
| 4 | `alembic upgrade head` | После шагов 1–3 должно пройти, но может всплыть очередная неожиданность типа отсутствующего индекса/constraint |
| 5 | `migrate-users` для проставления `sources.owner_id` | Низкий, идемпотентно |
| 6 | Smoke F6 на этих данных | Бесполезно: `last_digest_cursor` будет либо NULL, либо из старого VARCHAR — backfill cursor-логика всё равно упрётся в edge case |

**Сильные стороны:** сохраняет 5411 строк ingested data → можно «не ждать backfill».
**Слабые стороны:** требует трёх ручных стадий с высокой ценой ошибки; данные на стыке VARCHAR→TIMESTAMP могут потеряться без сигнала; «псевдо-baseline» в `alembic_version*` означает, что любая будущая миграция будет считать, что что-то уже накатано, хотя это неправда; smoke F6 на этих данных не валиден (cursor mechanism спроектирован под TIMESTAMPTZ-кратность, не под legacy ISO-строки).

### 1.3. Опция B — Full rebuild

| Шаг | Что | Риск |
|-----|-----|------|
| 1 | `docker compose down` (остановить tg_parser/mcp/bot, оставить postgres) | Низкий |
| 2 | `docker volume rm tg_parser_pgvector17_data` (после `docker compose down postgres`) | Низкий — данные намеренно удаляются (пользователь подтвердил, что ничего ценного нет) |
| 3 | `docker compose up -d postgres` → автоинициализация чистой БД через `docker/init-db.sh` | Низкий |
| 4 | `tg-parser db upgrade` (×3: ingestion/raw/processing) → создаёт `alembic_version_*` + всю схему линейно от initial до head | Низкий, штатный путь |
| 5 | `tg-parser migrate-users` → создаёт admin'а из `OPENAI/ANTHROPIC/GEMINI` ключей и `BOT_ALLOWED_USERS=5303033376,5445781511`, проставляет `sources.owner_id` (sources пока пустой → no-op для owner_id) | Низкий, идемпотентно |
| 6 | `tg-parser add-channel @labdiagnostica_logical` (1 канал для smoke) | Низкий |
| 7 | `tg-parser pipeline run` (или дождаться scheduler tick) → backfill истории | Средний по времени (десятки минут — час), низкий по риску |

**Сильные стороны:** канонический путь, который мы хотим документировать в runbook'е (т.е. сама работа = валидация runbook'а); схема гарантированно совпадает с моделями; `alembic_version*` = single head per db, дальше любая новая миграция накатывается стандартно.
**Слабые стороны:** теряем 5411 строк (приемлемо — пользователь подтвердил, что ничего ценного нет); ждём backfill (приемлемо — параллельно работаем над другими задачами).

### 1.4. Решение и обоснование

**Выбор: Опция B (full rebuild).** Причины:

1. **Frankenstein-схема превращает in-place в auditing-задачу, а не в миграцию.** Стоимость определения «к какой revision это ближе всего» уже сопоставима с временем backfill'а одного канала.
2. **`processed_at VARCHAR → TIMESTAMPTZ` не покрыта ни одной существующей миграцией.** Любая ручная конверсия — это работа, которая не воспроизводима для следующего разработчика и не покрыта тестами.
3. **Stamp под несуществующий baseline = бомба замедленного действия.** Следующая фича добавит миграцию, и она запустится поверх stamp'а, который не отражает реального состояния.
4. **Пользователь подтвердил, что ничего ценного в данных нет** (B5–B7). 5411 docs — это публичный telegram-контент, который ingestion-pipeline восстановит за ~час.
5. **Rebuild — это и есть runbook**, который мы хотим зафиксировать. Делая его, мы проверяем `tg-parser db upgrade`/`migrate-users`/`add-channel`/`pipeline` end-to-end на свежей БД — то, чего сейчас нет ни в одном CI-job.

---

## 2. Audit existing data

### 2.1. Локальный dev

| Объект | Содержит | Решение |
|--------|----------|---------|
| `sources` (5 строк) | 5 каналов | Список зафиксирован в этом плане; пере-добавим через `add-channel`; **бэкап не нужен** |
| `processed_documents` (5411) | LLM-обработанные посты с устаревшим VARCHAR `processed_at` | Удаляются с volume; ingestion перекатает |
| `document_embeddings` | Векторные представления тех же 5411 docs | Удаляются; embedding pipeline перекатает |
| `topic_cards`, `topic_bundles`, `topic_links` | Темы, кластеризация | Удаляются; topicization перекатает |
| `agent_states`, `agent_stats`, `task_history`, `handoff_history` | Operational metrics старых runs | Удаляются; не имеют долгосрочной ценности |
| `raw_messages`, `raw_conflicts` | Сырые Telegram payload'ы | Удаляются; ingestion перекатает |
| `api_jobs` | История фоновых job'ов API | Удаляются |

**Бэкап `pg_dump`?** Не нужен. Пользователь подтвердил отсутствие ценности (B5–B7); схема не совпадает ни с какой revision, поэтому даже сам dump было бы некуда восстанавливать без in-place патчей.

**Что НЕ удаляется:**
- `.env` — содержит API keys, MTProto creds, `BOT_ALLOWED_USERS`, smoke bot token. **Файл вне volume Postgres**, остаётся как есть.
- `data/sessions/` (Telethon session) — bind-mount, не на volume Postgres. Сохраняется → не нужно re-логиниться по SMS.
- `data/` остальные артефакты (export'ы, логи) — не критичны, но сохраняются попутно.

### 2.2. VPS dev

**Audit отложен до server pre-flight (раздел 4.1).** До тех пор не строим предположений.

---

## 3. Local execution plan

**Estimate сессии: 1.5–2.5 часа** (без учёта backfill, который идёт фоном).

### 3.1. Pre-flight (5 мин)

| # | Действие | Команда / файл | Критерий успеха |
|---|----------|---------------|-----------------|
| 3.1.1 | Подтвердить, что на `main` | `git status && git log --oneline -1` | HEAD = `410452a`, working tree clean (кроме `docs/`) |
| 3.1.2 | Зафиксировать список каналов | вручную в этом плане | 5 каналов: `AgeManagment`, `Lab4health`, `LongevityClub`, `genotek`, `labdiagnostica_logical` |
| 3.1.3 | Проверить `.env` — есть ли всё, что нужно для F6 | grep `BOT_ALLOWED_USERS`, `TELEGRAM_BOT_TOKEN`, `OPENAI_API_KEY`, `DB_*`, `TELEGRAM_API_*` | все ключи присутствуют |
| 3.1.4 | Решить про `DIGEST_SCHEDULER_ENABLED` | если нужен опциональный feature flag — выставить в `.env`; иначе пропустить | по дефолту F6 scheduler работает; флаг trip-wire для отключения, не для включения |

### 3.2. Tear down (5 мин)

| # | Действие | Команда | Критерий успеха |
|---|----------|---------|-----------------|
| 3.2.1 | Остановить app-контейнеры (tg_parser, mcp, bot если запущен) | `docker compose down` | `docker ps` не показывает `tg_parser*` (кроме postgres) |
| 3.2.2 | Остановить postgres | `docker compose stop postgres && docker compose rm -f postgres` | контейнер удалён |
| 3.2.3 | **Удалить volume** | `docker volume rm tg_parser_pgvector17_data` | команда вернула имя volume |

> Note: `tg_parser_pgvector17_data` декларирован как `external: true` в `docker-compose.yml` → нужно удалять явно.

### 3.3. Fresh DB (5 мин)

| # | Действие | Команда | Критерий успеха |
|---|----------|---------|-----------------|
| 3.3.1 | Создать external volume заново | `docker volume create tg_parser_pgvector17_data` | volume существует |
| 3.3.2 | Поднять postgres | `docker compose up -d postgres` | healthcheck = healthy в течение ~30 сек |
| 3.3.3 | Проверить, что `init-db.sh` отработал (extension vector) | `docker exec tg_parser_postgres psql -U tg_parser_user -d tg_parser -c "\dx"` | строка `vector` присутствует |

### 3.4. Apply migrations (10 мин)

| # | Действие | Команда | Критерий успеха |
|---|----------|---------|-----------------|
| 3.4.1 | Сборка образа (если ещё не собран на текущем main) | `docker compose build tg_parser` | image `tg_parser:latest` собран |
| 3.4.2 | Накатить миграции ingestion | `docker compose run --rm tg_parser db upgrade --db ingestion` | `alembic_version_ingestion.version_num = f6a1b2c3d4e5` |
| 3.4.3 | Накатить миграции raw | `docker compose run --rm tg_parser db upgrade --db raw` | `alembic_version_raw.version_num = 5c658f04eff0` |
| 3.4.4 | Накатить миграции processing | `docker compose run --rm tg_parser db upgrade --db processing` | один head для processing ветки (после F5-A Phase 3 + FTS) |
| 3.4.5 | Проверить single head per db | `docker compose run --rm tg_parser db heads --db ingestion` (×3) | по одной строке на каждую БД |
| 3.4.6 | Структурная проверка | `docker exec tg_parser_postgres psql -U tg_parser_user -d tg_parser -c "\dt"` | присутствуют `users`, `user_auth_mappings`, `digest_subscriptions`, `sources` (с колонкой `owner_id`) |

> Если шаг 3.4.2 упадёт — STOP и зафиксировать в «Известные блокеры», не двигаемся дальше.

### 3.5. Migrate-users (3 мин)

| # | Действие | Команда | Критерий успеха |
|---|----------|---------|-----------------|
| 3.5.1 | Dry-run | `docker compose run --rm tg_parser migrate-users --dry-run` | вывод: `admin_created=true`, `api_keys_mapped=N`, `telegram_users_mapped=2` (5303033376, 5445781511) |
| 3.5.2 | Реальный запуск | `docker compose run --rm tg_parser migrate-users` | те же цифры; `users` table = 1 admin row |
| 3.5.3 | Verify | `docker exec ... psql -c "SELECT id, name, role FROM users;"` | 1 admin |

> На этом этапе `sources` ещё пустой → `orphan_sources_assigned = 0`, это ожидаемо.

### 3.6. Add channel + backfill (5 мин setup, 30–90 мин backfill)

| # | Действие | Команда | Критерий успеха |
|---|----------|---------|-----------------|
| 3.6.1 | Поднять основной сервис + scheduler | `docker compose up -d tg_parser` | healthcheck OK |
| 3.6.2 | Добавить smoke-канал | `docker compose exec tg_parser tg-parser add-channel labdiagnostica_logical` | строка в `sources` (status=active, owner_id=admin.id) |
| 3.6.3 | Trigger pipeline вручную (или дождаться scheduler tick) | `docker compose exec tg_parser tg-parser pipeline run --channel labdiagnostica_logical` или MCP-tool `trigger_pipeline` | новые строки в `processed_documents` (с `processed_at` типа `timestamptz`) |
| 3.6.4 | Дождаться завершения backfill | `tg-parser db query` или `psql` чтобы посмотреть `MAX(processed_at)` | приближается к `now()` |

> **Параллельно** можно начинать раздел 5 (verification plan) на тех данных, что уже подъехали.

### 3.7. Финальная проверка (5 мин)

См. раздел 5. После прохождения — переход к VPS (раздел 4).

---

## 4. Server execution plan (VPS)

**VPS:** `redboxtgbot` (Ubuntu 24.04.4 LTS, kernel 6.8.0-101).
**Доступ:** `ssh -p 2296 user@212.72.189.15` (root login закрыт; `sudo` есть; user в группе `docker` ⇒ для docker-команд sudo не нужен).
**Путь проекта:** `/home/user/TG_parser`.
**Docker:** 29.3.0, Compose **v5.1.0 stand-alone** (плагин `/usr/libexec/docker/cli-plugins/docker-compose`).
**Estimate сессии: 1–1.5 часа** активной работы + 30–90 мин фонового backfill.

> **Server pre-flight уже выполнен 19 апреля 2026** (read-only). Полный снимок — Appendix A в конце документа. Здесь — только итоговые действия для исполнительной сессии. Перед стартом исполнения — короткий re-check (10 мин), что состояние не изменилось.

### 4.1. Pre-rebuild re-check (10 мин)

Выполнить уже зафиксированные команды из Appendix A повторно. Что должно совпасть:

| Параметр | Ожидаемое значение |
|----------|---------------------|
| HEAD, branch | `ffcad72` на `feature/phase3-tg-bot` (либо новее, если кто-то двигал) |
| Working tree | clean, no stash |
| Соседи (`flowise`, `n8n*`, `portainer`, `dozzle`) | Up |
| `tg_parser_postgres` | Up (healthy), volume `tg_parser_pgvector17_data` ≈ 200 MB ± |
| `data/sessions/tg_parser_session.session` | присутствует |
| Disk | свободно ≥ 5 GB |

Если что-то отличается (особенно — появился новый soседний контейнер с зависимостью на `tg_parser_postgres`) — STOP, обновить план.

### 4.2. Pre-rebuild backup (5 мин — опционально)

В `data/backups/` уже лежит `postgres_20260410_202414.sql.gz` (42 MB, от 10 апреля). Это ~9-дневный snapshot, и его достаточно как emergency rollback (мы всё равно делаем full rebuild, не in-place). Дополнительный фреш-dump — опционально:

```bash
docker exec tg_parser_postgres pg_dump -U tg_parser_user -d tg_parser \
  | gzip > /home/user/TG_parser/data/backups/pre_resurrection_$(date +%Y%m%d_%H%M%S).sql.gz
```

### 4.3. Tear down (5 мин)

**Окно downtime:** ~40–60 мин (rebuild + начало backfill). Других пользователей нет → формальное окно не требуется, но зафиксировать start/end timestamp в runbook для привычки.

```bash
cd /home/user/TG_parser

# Остановить ТОЛЬКО наши app-сервисы (НЕ трогаем prometheus/grafana/n8n/flowise/etc)
COMPOSE_PROFILES=bot docker compose stop tg_parser tg_parser_mcp tg_bot
COMPOSE_PROFILES=bot docker compose rm -f tg_parser tg_parser_mcp tg_bot

# Postgres отдельно
docker compose stop postgres
docker compose rm -f postgres

# Volume
docker volume rm tg_parser_pgvector17_data
```

**Критерий:** `docker volume ls | grep tg_parser_pgvector17_data` пусто; `docker ps` показывает только prometheus/grafana/caddy/n8n*/flowise/portainer/dozzle (но НЕ `tg_parser*` app-сервисы и НЕ `tg_parser_postgres`).

### 4.4. Git checkout main + image rebuild (10 мин)

```bash
cd /home/user/TG_parser
git fetch origin
git checkout main
git pull --ff-only origin main
git rev-parse HEAD                     # должен быть актуальный main (≥ 410452a)
git status                             # working tree clean

docker compose build tg_parser         # пересобрать образ под новый код
```

> `ffcad72` (текущий HEAD) подтверждённо находится в `origin/main`, поэтому checkout безопасен и ничего не теряет.

### 4.5. Fresh DB + migrations (10 мин)

```bash
docker volume create tg_parser_pgvector17_data
docker compose up -d postgres
# подождать healthy:
docker compose ps postgres

# проверить vector extension:
docker exec tg_parser_postgres psql -U tg_parser_user -d tg_parser -c "\dx" | grep vector

# миграции:
docker compose run --rm tg_parser db upgrade --db ingestion
docker compose run --rm tg_parser db upgrade --db raw
docker compose run --rm tg_parser db upgrade --db processing

# heads:
for db in ingestion raw processing; do
  docker compose run --rm tg_parser db heads --db "$db"
done

# структурная sanity:
docker exec tg_parser_postgres psql -U tg_parser_user -d tg_parser \
  -c "\dt" \
  -c "\d users" \
  -c "\d digest_subscriptions" \
  -c "SELECT data_type FROM information_schema.columns WHERE table_name='processed_documents' AND column_name='processed_at';"
```

**Критерий:** `processed_at` = `timestamp with time zone`; `users`/`user_auth_mappings`/`digest_subscriptions` присутствуют; `sources` имеет колонку `owner_id`.

### 4.6. Migrate-users (5 мин)

```bash
docker compose run --rm tg_parser migrate-users --dry-run
docker compose run --rm tg_parser migrate-users
docker exec tg_parser_postgres psql -U tg_parser_user -d tg_parser \
  -c "SELECT id, name, role FROM users;" \
  -c "SELECT auth_type, COUNT(*) FROM user_auth_mappings GROUP BY 1;"
```

**Ожидание:** 1 admin user; в `user_auth_mappings` минимум:
- 2 строки `telegram` (id из `BOT_ALLOWED_USERS`),
- N строк `api_key` (для `API_KEYS` — на VPS они есть),
- M строк `mcp_token` (для `MCP_AUTH_TOKENS` — на VPS они есть).

### 4.7. Поднять стек + add-channel + backfill (~10 мин setup, 30–90 мин backfill)

```bash
# Восстановить ровно тот же набор сервисов, что был запущен до tear down:
COMPOSE_PROFILES=bot docker compose up -d tg_parser tg_parser_mcp tg_bot

# Подождать healthy:
docker compose ps

# Добавить smoke-канал:
docker compose exec tg_parser tg-parser add-channel labdiagnostica_logical

# Trigger pipeline (или дождаться scheduler tick):
docker compose exec tg_parser tg-parser pipeline run --channel labdiagnostica_logical
```

> **Profile `production` (caddy)** на VPS сейчас Created, но не Up. Не поднимать в рамках этой задачи — TLS/reverse proxy относится к D-remaining track.

### 4.8. VPS-specific verification отличия

Дополнительно к разделу 5 — на VPS включены `API_KEY_REQUIRED` и `MCP_AUTH_ENABLED`, поэтому verification endpoints требуют auth:

| Endpoint / способ | Как авторизоваться |
|-------------------|---------------------|
| API `/api/v1/...` | заголовок `X-API-Key: <key из .env API_KEYS>` или `Authorization: Bearer <key>` |
| MCP `/mcp` | `Authorization: Bearer <token из .env MCP_AUTH_TOKENS>` |
| Bot tools | через сам Telegram chat (bot token из `.env`) |
| `/health`, `/metrics` | открыты, без auth |

### 4.9. Sequential gating

```
Local 3.1–3.7 → Local verification (раздел 5) PASSED
                ↓
        Update runbook with discovered gotchas (раздел 6)
                ↓
        Server 4.1 (pre-rebuild re-check)
                ↓
        Server 4.2 (optional fresh backup)
                ↓
        Server 4.3–4.7 (rebuild)
                ↓
        Server verification (раздел 5 + 4.8 auth notes)
                ↓
        STOP. Smoke F6 — отдельная сессия.
```

---

## 5. Verification plan (применим и для local, и для server)

**Estimate: 15–20 мин** (без учёта backfill ожидания).

### 5.1. Database health (2 мин)

| Что | Команда | Критерий |
|-----|---------|----------|
| Single head per db | `tg-parser db heads --db {ingestion,raw,processing}` (×3) | по одной строке |
| `alembic check` (нет drift'а models vs migrations) | `tg-parser db check` (или прямой `alembic -x db_name=ingestion check`) | exit 0 на каждой БД |
| Schema-level inspect | `psql ... -c "\d users" -c "\d digest_subscriptions" -c "\d processed_documents"` | `processed_at` = `timestamp with time zone`; `sources.owner_id` присутствует |

### 5.2. Ingest sanity (5 мин)

| Что | Как |
|-----|-----|
| Pipeline status | MCP `get_pipeline_status` (или `tg-parser pipeline status`) — нет ошибок |
| Ingest нового сообщения | Дождаться следующего polling-tick'а (по `Source.poll_interval_seconds`) или вручную `pipeline run` |
| Проверка | `SELECT MAX(processed_at) FROM processed_documents WHERE channel_id = '<labdiag_id>';` — растёт |

### 5.3. Topicization (3 мин)

| Что | Как |
|-----|-----|
| `topic_cards` создаются | `SELECT COUNT(*) FROM topic_cards;` > 0 после первого pipeline-run'а |
| Получить разбивку | MCP `list_topics` или `tg-parser topics list` |

### 5.4. Search (2 мин)

| Что | Как |
|-----|-----|
| Hybrid search | MCP `search_knowledge_base` с любым релевантным запросом по тематике канала | возвращает ненулевой результат с `score` > 0 |
| FTS живой | в результатах присутствует и keyword-, и semantic-driven выдача (mode=hybrid) |

### 5.5. Bot Q&A (3 мин)

| Что | Как |
|-----|-----|
| MCP `ask_question` | вопрос по тематике канала | возвращает ответ с цитатами (source_ref) |

### 5.6. F6 hand-off

После прохождения 5.1–5.5 — runbook готов; **smoke F6** проводится в отдельной сессии по плану из transcript предыдущей сессии (9 пунктов: happy path, empty tick, backlog cap, reconcile, stale-sub race, long digest, failure modes, ownership, cleanup).

---

## 6. Runbook

Создаётся файл `docs/runbooks/DEV_RESURRECTION.md` (см. отдельный артефакт). Назначение: воспроизвести этот процесс через 3 месяца без транскрипта. Структура:

- Prerequisites (Docker version, переменные `.env`)
- Tear down (с явным `docker volume rm`)
- Fresh DB (включая ручное `docker volume create` для external volume)
- Migrations (×3 БД)
- Migrate-users
- Add-channel + verification commands
- **Грабли и FAQ:**
  - `migrations/alembic.ini` всё ещё содержит SQLite-секции `[ingestion]/[raw]/[processing]` — это legacy, env.py их игнорирует, **не паниковать**.
  - `tg_parser_pgvector17_data` декларирован как `external: true` → docker compose down/up **сам не пересоздаст** volume; нужен ручной `docker volume create`.
  - Если `migrate-users` не находит api_keys в settings — это нормально, маппинг сделан только для `BOT_ALLOWED_USERS`; admin всё равно создаётся.
  - Backfill `labdiagnostica_logical` занимает ~30–90 мин (зависит от глубины истории и LLM throttling).

Runbook писать на русском (как существующие в репозитории), формат — пошаговая команда + критерий успеха в одну строку каждой. Без длинных параграфов.

---

## 7. CI guardrail

**Решение (D11):** включаем в этот же план как маленький инкремент. Изменения локализованы в `.github/workflows/ci.yml`, не требуют новых зависимостей.

### 7.1. Что добавляем

Новый job (или дополнительный step в существующем `test` job — выбор по предпочтению автора реализации):

```yaml
  alembic-guardrail:
    name: Alembic Guardrails
    runs-on: ubuntu-latest
    services:
      postgres:
        image: pgvector/pgvector:pg17
        env:
          POSTGRES_DB: tg_parser_alembic
          POSTGRES_USER: tg_parser_alembic
          POSTGRES_PASSWORD: alembic_password
        ports: ['5432:5432']
        options: >-
          --health-cmd pg_isready --health-interval 10s
          --health-timeout 5s --health-retries 5
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12', cache: 'pip' }
      - run: |
          pip install -r requirements.txt && pip install -e .
      - name: Enable pgvector
        run: PGPASSWORD=alembic_password psql -h localhost -U tg_parser_alembic -d tg_parser_alembic -c "CREATE EXTENSION IF NOT EXISTS vector;"
      - name: Single head per database
        env: { DB_HOST: localhost, DB_PORT: 5432, DB_NAME: tg_parser_alembic, DB_USER: tg_parser_alembic, DB_PASSWORD: alembic_password, OPENAI_API_KEY: sk-test, ANTHROPIC_API_KEY: sk-test, GEMINI_API_KEY: test }
        run: |
          for db in ingestion raw processing; do
            heads=$(tg-parser db heads --db "$db" | wc -l)
            if [ "$heads" -ne 1 ]; then
              echo "ERROR: db $db has $heads heads, expected 1"; exit 1
            fi
          done
      - name: Smoke upgrade head + downgrade base
        env: { ... тот же блок ... }
        run: |
          for db in ingestion raw processing; do
            tg-parser db upgrade --db "$db"
          done
          for db in ingestion raw processing; do
            tg-parser db downgrade --db "$db" --revision base
          done
          for db in ingestion raw processing; do
            tg-parser db upgrade --db "$db"
          done
      - name: Alembic check (model vs migration drift)
        env: { ... }
        run: |
          for db in ingestion raw processing; do
            tg-parser db check --db "$db" || true
          done
```

**Почему `|| true` на `db check`:** в текущей кодовой базе `target_metadata=None` в `migrations/env.py`, то есть `alembic check` структурно работать не будет до отдельного refactor'а (подключение моделей к metadata). Это записываем как follow-up — поднимать `|| true` до failing после того, как ручной refactor сделан.

### 7.2. Что эта guard'а ловит

| Класс ошибок | Поймает? |
|--------------|----------|
| Дубликат revision id (как PR #12) | Да — `db heads` вернёт >1 строки или `db upgrade` упадёт на multiple heads |
| Невалидная миграция (синтаксис/imports) | Да — `db upgrade` упадёт на import |
| Невалидный downgrade | Да — `db downgrade base` упадёт |
| Drift моделей vs миграций | Только после подключения `target_metadata` (follow-up) |
| Несоответствие данных схеме | Нет — это runtime, не migration-time |

### 7.3. Estimate реализации

15–25 мин: добавить job в `.github/workflows/ci.yml`, прогнать на feature branch, проверить, что ловит искусственно созданный duplicate revision.

---

## 8. Out-of-scope для этой работы

Записываем сюда, чтобы scope не разрастался во время исполнения:

| Что | Куда переносим |
|-----|----------------|
| Подключение `target_metadata` к `migrations/env.py` для рабочего `alembic check` | follow-up в `FUTURE_FEATURES.md` (см. ниже) |
| Чистка `migrations/alembic.ini` от legacy SQLite-секций | follow-up |
| Второй runbook «как безопасно накатить новую миграцию на dev» (D12) | follow-up |
| Production deployment trail (TLS, monitoring, alerting) | track D-remaining (вне этой задачи) |
| Backfill всех 5 каналов, не только `labdiagnostica_logical` | следующая обычная dev-сессия (после resurrection) |
| Smoke F6 (9 пунктов) | отдельная сессия после resurrection |
| Любые изменения схемы БД, не требуемые для приведения к head | следующие фичи |
| Refactor `Settings`/`.env`/`docker-compose.yml` | вне scope |
| Apgrade Python / pgvector / pg17 | вне scope |

---

## Известные блокеры (на момент составления плана)

Зафиксированы здесь, не пытаемся решать в рамках этой задачи:

1. **`migrations/alembic.ini` ссылается на SQLite-файлы** в секциях `[ingestion]/[raw]/[processing]`. Это legacy от Session 22; реально игнорируется `migrations/env.py` (URL собирается из `Settings`). Не блокирует resurrection, но запутывает новичка → вынесено в follow-up.
2. **`alembic check` неработоспособен** до подключения `target_metadata` в `env.py`. CI guardrail (раздел 7) включает шаг с `|| true`; полное включение — follow-up.
3. **`processed_at` исторический drift** (VARCHAR в текущей dev-БД vs TIMESTAMPTZ в моделях): нет существующей миграции для конверсии. Полностью обходится через full rebuild. Отсутствие такой миграции — само по себе НЕ блокер для main, потому что чистая БД через alembic создаст сразу TIMESTAMPTZ.

---

## Open questions (требуют решения перед стартом)

Все основные вопросы (A1–C10) закрыты ответами пользователя. Делегированные defaults:

- **D11** (CI guardrail в этот же план): принят default «да, включаем» — раздел 7.
- **D12** (второй runbook про безопасные миграции): принят default «не сейчас» — вынесено в follow-up.

Если на момент исполнительной сессии что-то изменилось — пересмотреть до старта раздела 3.

---

## Estimates (cumulative)

| Этап | Время | Комментарий |
|------|-------|-------------|
| 3.1 Local pre-flight | 5 мин | |
| 3.2 Local tear down | 5 мин | |
| 3.3 Local fresh DB | 5 мин | |
| 3.4 Local migrations | 10 мин | |
| 3.5 Migrate-users | 3 мин | |
| 3.6 Add channel + start backfill | 5 мин setup | backfill идёт фоном 30–90 мин |
| 5 Local verification | 15–20 мин | можно частично параллельно с backfill |
| Заморозка runbook | 10 мин | дописываем грабли, обнаруженные по факту |
| 4.1 VPS pre-rebuild re-check | 10 мин | по чек-листу из Appendix A |
| 4.2 VPS optional fresh backup | 5 мин | пропустить, если 9-дневный достаточен |
| 4.3 VPS tear down | 5 мин | селективно, не трогая n8n/flowise/grafana |
| 4.4 git checkout main + image rebuild | 10 мин | `ffcad72 ∈ origin/main` ⇒ безопасно |
| 4.5 VPS fresh DB + migrations | 10 мин | |
| 4.6 VPS migrate-users | 5 мин | на VPS дополнительно маппятся API_KEYS и MCP_AUTH_TOKENS |
| 4.7 VPS up + add-channel + start backfill | 10 мин setup | backfill фоном 30–90 мин |
| 5 VPS verification | 15–20 мин | |
| 7 CI guardrail | 15–25 мин | можно делать параллельно с server backfill |
| **Итого активной работы** | **~2.5–3.5 ч** | без учёта 30–90 мин backfill (×2 окружения) |

Для одной исполнительной сессии комфортно: 2–3 ч активной работы + параллельные backfill ожидания.

---

## Definition of Done (этой задачи)

- [ ] Локальный dev: `tg-parser db heads` — single head per db (×3); `users` / `digest_subscriptions` присутствуют; admin user создан; 1 канал ingest'ится; verification (раздел 5) проходит.
- [ ] VPS dev: то же самое.
- [ ] `docs/runbooks/DEV_RESURRECTION.md` обновлён с граблями, обнаруженными по ходу исполнения.
- [ ] CI guardrail добавлен в `.github/workflows/ci.yml`, прогнан на feature branch, ловит искусственный duplicate revision.
- [ ] Follow-up'ы записаны в `docs/notes/FUTURE_FEATURES.md`.
- [ ] План закоммичен (отдельным коммитом, не merge'ится в main).
- [ ] Smoke F6 — передан в следующую сессию (не делается в рамках этой задачи).

---

## Appendix A: Снимок состояния VPS (server pre-flight 19 апреля 2026)

Зафиксирован read-only диагностикой через SSH 19 апреля 2026. Источник правды на момент составления плана; перед исполнительной сессией — повторить (раздел 4.1).

### A.1. Окружение

| Параметр | Значение |
|----------|----------|
| Hostname | `redboxtgbot` |
| ОС | Ubuntu 24.04.4 LTS, kernel 6.8.0-101 x86_64 |
| Доступ | `ssh -p 2296 user@212.72.189.15`, root login закрыт, `sudo` есть |
| User membership | `user` ∈ `sudo, docker, lxd, ...` ⇒ docker без sudo |
| Docker | 29.3.0 |
| Compose | **v5.1.0 stand-alone** (плагин `/usr/libexec/docker/cli-plugins/docker-compose`, не upstream Compose v2) |
| Disk | `/dev/mapper/ubuntu--vg-ubuntu--lv` 19G total, 11G used, **7.4G free (59%)** |
| Путь проекта | `/home/user/TG_parser` |

### A.2. Git

| Параметр | Значение |
|----------|----------|
| Branch | `feature/phase3-tg-bot` |
| HEAD | `ffcad72caf982abd72a4d43e21753753b9ece821` («Fix bot healthcheck to use /proc/1/cmdline», 10 апреля 2026) |
| HEAD ∈ origin/main | **YES** (подтверждено локально через `git merge-base --is-ancestor`) |
| Working tree | clean |
| Stash | empty |
| Отставание от main | 10+ commits (отсутствуют все hotfix #12, F2, F5-A Phase 2/3, F6) |

### A.3. Контейнеры (13 штук)

**Наш стек (управляется этим планом):**

| Container | Image | Status | Notes |
|-----------|-------|--------|-------|
| `tg_parser` | `tg_parser:latest` | Up 8 days, healthy, `127.0.0.1:8000→8000` | образ собран на ffcad72, нужен rebuild после checkout main |
| `tg_parser_mcp` | `tg_parser:latest` | Up 8 days, healthy, `127.0.0.1:8080→8080` | то же |
| `tg_parser_bot` | `tg_parser:latest` | Up 8 days, healthy | запущен через `compose --profile bot` (label `com.docker.compose.service: tg_bot`) |
| `tg_parser_postgres` | `pgvector/pgvector:pg17` | Up 2 weeks, healthy, `127.0.0.1:5432→5432` | volume target tear-down |
| `tg_parser_grafana` | `grafana/grafana:11.1.0` | Up 2 weeks, `127.0.0.1:3001→3000` | НЕ трогаем |
| `tg_parser_prometheus` | `prom/prometheus:v2.53.0` | Up 2 weeks, `:9090` | НЕ трогаем |
| `tg_parser_caddy` | `caddy:2-alpine` | **Created** (не Up) | profile `production` не активирован, не трогаем |

**Соседи (НЕ трогаем):**

| Container | Image | Notes |
|-----------|-------|-------|
| `flowise` | `flowiseai/flowise:3.0.13` | Up 6w, `:3000` |
| `n8n-n8n-1` | `docker.n8n.io/n8nio/n8n:2.10.3` | Up 6w, `:5678` |
| `n8n-db-1` | `postgres:15-alpine` | Up 6w (healthy) — **свой Postgres**, не наш |
| `portainer` | `portainer/portainer-ce:latest` | Up 6w, `:9000/:9443` |
| `dozzle` | `amir20/dozzle:latest` | Up 6w, `:9999` |

⇒ **Подтверждение A3:** `tg_parser_postgres` обслуживает только наш стек.

### A.4. Volumes

| Volume | Размер | Действие |
|--------|--------|----------|
| `tg_parser_pgvector17_data` | **194 MB** (через `du -sh /var/lib/postgresql/data`) | drop + recreate |
| `tg_parser_caddy_data` / `_config` | — | не трогаем |
| `tg_parser_grafana_data` | — | не трогаем |
| `tg_parser_prometheus_data` | — | не трогаем |

### A.5. Postgres схема (Frankenstein, идентично локальному dev)

| Параметр | Значение |
|----------|----------|
| Tables в `public` | 16 (тот же набор, что локально) |
| `alembic_version*` | **0** |
| `users` / `user_auth_mappings` / `digest_subscriptions` | **отсутствуют** |
| `sources.owner_id` | **отсутствует** |
| `processed_documents.processed_at` тип | `character varying` |
| `sources` rows | 5 (`AgeManagment`, `Lab4health`, `LongevityClub`, `genotek`, `labdiagnostica_logical`) |
| `processed_documents` rows | **5474** (немного больше локального 5411) |
| Latest `processed_at` | **2026-04-18T20:33:42Z** (vs локально 2026-04-01) — VPS активно ingest'ил вчера |

### A.6. ENV (`.env` в корне проекта, presence только)

**SET:** `DB_NAME/USER/PASSWORD/HOST/PORT`, `TELEGRAM_API_ID/HASH/PHONE`, `TELEGRAM_BOT_TOKEN`, `BOT_ALLOWED_USERS`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, **`API_KEY_REQUIRED`**, **`API_KEYS`**, **`MCP_AUTH_ENABLED`**, **`MCP_AUTH_TOKENS`**, `DOMAIN_API`, `DOMAIN_MCP`, `LLM_PROVIDER`, `PROCESSING_LLM_PROVIDER`, `TOPICIZATION_LLM_PROVIDER`, `BOT_GEMINI_MODEL`.

**UNSET (используются default'ы):** `TELEGRAM_SESSION_NAME`, `DIGEST_SCHEDULER_ENABLED` (default = on), `RAG_LLM_PROVIDER`, `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`.

⇒ **F9 Phase 1 (security hardening) на VPS уже включён** — verification на VPS требует API key / MCP token из `.env` для protected endpoints.

### A.7. Прочее

| Параметр | Значение |
|----------|----------|
| Telethon session | `data/sessions/tg_parser_session.session`, 28 KB, mtime 2026-04-18, owner=`root` (через bind-mount); переживёт rebuild |
| Backup существующий | `data/backups/postgres_20260410_202414.sql.gz` (42 MB, 9 дней назад) |
| App logs | `/health` и `/metrics` отрабатывают штатно (Prometheus scrape каждые ~15 сек), ошибок не видно |

---

## Appendix B: Логи диагностики

Команды server pre-flight 19 апреля 2026 (для воспроизведения):

```bash
# Базовая инфо:
ssh -p 2296 user@212.72.189.15 'uname -a; whoami; id; pwd'
ssh -p 2296 user@212.72.189.15 'cd /home/user/TG_parser && git rev-parse HEAD && git rev-parse --abbrev-ref HEAD && git status --short'
ssh -p 2296 user@212.72.189.15 'docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"'
ssh -p 2296 user@212.72.189.15 'docker volume ls; df -h /'

# DB схема:
ssh -p 2296 user@212.72.189.15 'docker exec tg_parser_postgres psql -U tg_parser_user -d tg_parser -c "\dt"'
ssh -p 2296 user@212.72.189.15 "docker exec tg_parser_postgres psql -U tg_parser_user -d tg_parser -tAc \"SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'alembic%';\""

# Volume size:
ssh -p 2296 user@212.72.189.15 'docker exec tg_parser_postgres du -sh /var/lib/postgresql/data'

# Profile detection:
ssh -p 2296 user@212.72.189.15 'docker inspect tg_parser_bot --format "{{json .Config.Labels}}" | tr "," "\n" | grep compose.service'
```
