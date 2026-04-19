# Runbook — Dev Resurrection (поднять dev-стенд с нуля)

**Назначение:** воспроизвести full rebuild dev-окружения (локального или VPS) при desync схемы с `main`. Применять при любом из:

- `tg-parser db heads --db <X>` возвращает >1 строки или ошибку.
- В БД отсутствуют таблицы `alembic_version_*`.
- Схема не соответствует ни одной alembic revision (Frankenstein).
- Перед smoke-тестом новой фичи, требующей актуальной схемы.

**Время:** ~25–35 мин активной работы + 30–90 мин фонового backfill (на канал).

**Уровень разрушительности:** ⚠️ удаляет volume Postgres → теряются ВСЕ данные. Делать только когда подтверждено, что данные не нужны (или есть бэкап).

---

## Prerequisites

| Что | Минимум |
|-----|---------|
| Docker | 24+ (тестировано на 29.3.0) |
| Docker Compose plugin | v2 |
| Свободное место на диске | 2× размера текущего volume `tg_parser_pgvector17_data` |
| `.env` | существует, содержит `DB_*`, `TELEGRAM_API_ID/HASH/PHONE`, `OPENAI_API_KEY` (или `ANTHROPIC_API_KEY`/`GEMINI_API_KEY`), `BOT_ALLOWED_USERS` |
| `git` | working tree clean, на `main`, актуальный pull |

Если есть Telethon session (`data/sessions/tg_parser_session*`) — она ВНЕ Postgres-volume, переживёт rebuild. Если её нет — приготовиться к SMS-логину при первом ingest.

---

## Шаги

### 1. Проверка на `main`

```bash
git status          # working tree clean
git log --oneline -1 # должно совпадать с origin/main
```

### 2. Tear down

```bash
docker compose down                            # остановит tg_parser, mcp, bot
docker compose stop postgres                   # остановит postgres
docker compose rm -f postgres                  # удалит контейнер
docker volume rm tg_parser_pgvector17_data     # ⚠️ УДАЛЯЕТ ДАННЫЕ
```

**Критерий:** `docker volume ls | grep tg_parser_pgvector17_data` — пусто.

### 3. Fresh DB

```bash
docker volume create tg_parser_pgvector17_data # external volume — нужно создать вручную
docker compose up -d postgres                  # автоинит через docker/init-db.sh
docker exec tg_parser_postgres pg_isready -U tg_parser_user -d tg_parser
docker exec tg_parser_postgres psql -U tg_parser_user -d tg_parser -c "\dx" | grep vector
```

**Критерий:** healthcheck = healthy; в `\dx` присутствует extension `vector`.

### 4. Накатить миграции

```bash
docker compose build tg_parser                                            # если ещё не собран
docker compose run --rm tg_parser db upgrade --db ingestion
docker compose run --rm tg_parser db upgrade --db raw
docker compose run --rm tg_parser db upgrade --db processing

docker compose run --rm tg_parser db heads --db ingestion
docker compose run --rm tg_parser db heads --db raw
docker compose run --rm tg_parser db heads --db processing
```

**Критерий:** каждая команда `db heads` выводит ровно одну revision.

Структурная sanity:

```bash
docker exec tg_parser_postgres psql -U tg_parser_user -d tg_parser \
  -c "\dt" \
  -c "\d users" \
  -c "\d digest_subscriptions" \
  -c "\d processed_documents"
```

**Критерий:** присутствуют `users`, `user_auth_mappings`, `digest_subscriptions`, `sources` (с колонкой `owner_id UUID`); `processed_documents.processed_at` = `timestamp with time zone`.

### 5. Migrate-users

```bash
docker compose run --rm tg_parser migrate-users --dry-run   # посмотреть, что собирается сделать
docker compose run --rm tg_parser migrate-users             # реальный прогон
docker exec tg_parser_postgres psql -U tg_parser_user -d tg_parser \
  -c "SELECT id, name, role FROM users;" \
  -c "SELECT auth_type, COUNT(*) FROM user_auth_mappings GROUP BY 1;"
```

**Критерий (что ожидается в идеале):** 1 admin user; в `user_auth_mappings` есть строки `telegram` (по числу id в `BOT_ALLOWED_USERS`), `mcp_token` (по числу токенов в `MCP_AUTH_TOKENS`), и `api_key` (по числу ключей в `API_KEYS`).

**⚠️ Грабли реальной VPS-сессии (зафиксированы в DI-11 и DI-12, FUTURE_FEATURES.md):**

1. **DI-11:** в `users` появится 2 admin'а (миграция `b2c3d4e5f6a7` сидит первого, `migrate-users` создаёт второго). Функционально не блокирует — оба валидны. Cleanup опционален.
2. **DI-12 (КРИТИЧНО):** `migrate-users` смапит ТОЛЬКО `api_keys`. `mcp_tokens_mapped=0` и `telegram_users_mapped=0` несмотря на корректные значения в `.env`. Без mcp_token Claude Desktop не может подключиться, без telegram_users бот не пускает пользователей.

**Workaround по DI-12** (запустить ВНУТРИ контейнера, читает `Settings`, прямой вызов repo):

```bash
docker compose exec tg_parser python -c "
import asyncio
from tg_parser.config import settings
from tg_parser.services.db_context import user_repo
from tg_parser.security import hash_secret

async def main():
    async with user_repo() as (repo, _db):
        admin = await repo.find_first_user_by_role('admin')  # см. DI-11: возьмёт первого
        if admin is None:
            raise RuntimeError('No admin user found — run db upgrade first')
        admin_id = admin.id

        for name, token in settings.mcp_auth_tokens.items():
            await repo.add_auth_mapping(admin_id, 'mcp_token', hash_secret(token), client_name=name)
            print(f'mapped mcp_token: {name}')

        for tg_id in settings.bot_allowed_user_ids:
            await repo.add_auth_mapping(admin_id, 'telegram', str(tg_id), client_name=None)
            print(f'mapped telegram: {tg_id}')

asyncio.run(main())
"
```

Если у тебя нет `find_first_user_by_role` — заменить на raw SQL `SELECT id FROM users WHERE role='admin' ORDER BY created_at LIMIT 1`. Verify результат тем же `SELECT auth_type, COUNT(*) FROM user_auth_mappings GROUP BY 1;`.

### 6. Поднять основной сервис и подключить канал(ы)

```bash
docker compose up -d tg_parser                              # API + scheduler

docker compose exec tg_parser tg-parser add-source \
    --source-id labdiagnostica_logical \
    --channel-id labdiagnostica_logical \
    --channel-username labdiagnostica_logical
```

> Замени `labdiagnostica_logical` на нужный канал. На фазе resurrection — только 1 канал для быстрой проверки; остальные доподключаются после.
>
> **⚠️ Грабля (DI-13):** `add-source` НЕ принимает `--owner-id` → source создаётся с `owner_id=NULL`. После него нужно перезапустить `migrate-users` (он привяжет orphan source к admin'у):
>
> ```bash
> docker compose run --rm tg_parser migrate-users
> ```

**Критерий:** в `sources` появилась строка `status='active'`, `owner_id = admin.id` (после повторного `migrate-users`).

### 7. Запустить pipeline (или дождаться scheduler tick'а)

```bash
docker compose exec -d tg_parser bash -c \
    "tg-parser run --source labdiagnostica_logical --out /app/data/output > /tmp/run.log 2>&1"
```

> **⚠️ Грабля:** правильная команда — `tg-parser run --source <id>`, **не** `pipeline run --channel <id>`. Аргумент `--source` обязательный.

Или просто ждать — scheduler сам подцепит новый канал на следующем tick'е.

Мониторинг прогресса:

```bash
docker exec tg_parser_postgres psql -U tg_parser_user -d tg_parser \
  -c "SELECT channel_id, COUNT(*) AS docs, MAX(processed_at) AS latest FROM processed_documents GROUP BY 1;"
```

### 8. Verification

См. `docs/plans/DEV_RESURRECTION_PLAN.md` раздел 5 (database health → ingest → topicization → search → bot Q&A).

---

## Грабли (FAQ)

### Q: `docker compose down` не удалил volume `tg_parser_pgvector17_data`. Это нормально?

**A:** Да. Volume объявлен `external: true` в `docker-compose.yml`. Compose НЕ управляет его жизненным циклом. Удалять надо вручную через `docker volume rm`. Соответственно и пересоздавать вручную через `docker volume create` (см. шаг 3).

### Q: `migrations/alembic.ini` содержит секции `[ingestion]/[raw]/[processing]` со ссылками на `.sqlite` файлы. Это правильно?

**A:** Это legacy от Session 22 (когда ещё был SQLite). `migrations/env.py` эти URL **игнорирует** и собирает Postgres URL из `Settings`. Не паниковать, не "чинить", не трогать без отдельной задачи. См. follow-up в `docs/notes/FUTURE_FEATURES.md` § Dev Infra.

### Q: `tg-parser db upgrade` падает с «Multiple head revisions are present for given argument 'head'».

**A:** Должно было быть починено коммитом `7adc07c` (per-call temporary `alembic.ini` с `version_locations` отфильтрованным под одну БД). Если падает снова:
1. Проверить, что в локальной checkout есть коммит `7adc07c` (`git log --oneline | grep make-tg-parser-db-work`).
2. На VPS — убедиться, что после `git pull` сделан `docker compose build tg_parser` (без rebuild старый image не содержит исправленного CLI).
3. Если всё равно — `tg-parser db heads --db <X>` должен показать ровно 1 head на ветку. Если показывает 3 (`f6a1b2c3d4e5`, `5c658f04eff0`, `f5a3c0d7e8b9`) — значит не тот коммит. См. план Appendix C.1 #3 и DI-7 в FUTURE_FEATURES.md.

### Q: `tg-parser db upgrade --db processing` падает с `NoSuchTableError: document_embeddings`.

**A:** Должно быть починено коммитом `4b48214` (bootstrap `document_embeddings` + `pgvector` extension в миграции `a1b2c3d4e5f6`). Если падает снова — тот же чеклист, что и в предыдущем Q (нет коммита локально или image не пересобран). Как **временный** работ-аround можно вручную создать таблицу через `init_processing_storage_schema()` и сделать `tg-parser db stamp --db processing f40d85317f03`, но это возвращает Frankenstein и должно делаться только в emergency. См. DI-8 в FUTURE_FEATURES.md.

### Q: `tg-parser db upgrade` внутри `docker compose run --rm tg_parser` падает с `Connect call failed (127.0.0.1, 5432)`.

**A:** Локально `.env` обычно содержит `DB_HOST=localhost` (так нужно для запуска CLI с хоста через venv). Внутри docker-контейнера `localhost` = сам контейнер, не postgres. Решения:
- **Локально:** запускать миграции через venv (`source .venv/bin/activate && tg-parser db upgrade --db all`), не через `docker compose run`.
- **На VPS:** в production `.env` должно быть `DB_HOST=postgres` (имя docker-compose сервиса). Если стоит `localhost` — поправить.
- **Ad-hoc override:** `docker compose run --rm -e DB_HOST=postgres tg_parser db upgrade --db all`.

### Q: `pydantic-settings` падает на `JSONDecodeError` при старте контейнера, не дойдя даже до миграций.

**A:** Должно быть починено коммитом `80aebaf` (default `${API_KEYS:-{}}` / `${CORS_ORIGINS:-["*"]}` в compose). Если падает снова — проверить, что коммит присутствует и `docker compose config tg_parser | grep -E "API_KEYS|CORS_ORIGINS"` показывает валидный JSON. Корень причины: `pydantic-settings` парсит JSON-полях **до** того, как `BeforeValidator` может поймать пустую строку.

### Q: Почему `processed_documents.processed_at` имеет тип `character varying`, а не `TIMESTAMPTZ`?

**A:** Это **canonical state code base**, не drift. Ни одна alembic-миграция тип не меняет. План `DEV_RESURRECTION_PLAN.md` §3 ошибочно полагал TIMESTAMPTZ canonical (см. Appendix C.3). Решение «как с этим жить» — DI-10 в FUTURE_FEATURES.md (либо новая миграция convert, либо документировать как as-designed).

### Q: `migrate-users` пишет `api_keys_mapped=0`. Это сломалось?

**A:** Нет. Если в `.env` нет `API_KEYS=...` (или `MCP_AUTH_TOKENS`) — нечего маппить. Admin всё равно создаётся, telegram-ids из `BOT_ALLOWED_USERS` маппятся. Это нормально для dev'а, где API/MCP auth не используются.

### Q: Backfill `labdiagnostica_logical` идёт уже час, это ОК?

**A:** Да. Глубина истории канала + LLM throttling + embedding generation. Реалистичная оценка: 30–90 мин на 1 средний канал. Пока ждёшь — можно делать verification на тех документах, что уже подтянулись.

### Q: `db upgrade` упал на `relation "X" already exists`.

**A:** Значит volume не был очищен, и в БД остались таблицы старой схемы. Вернуться к шагу 2 и убедиться, что `docker volume rm` действительно отработал (не было ли вместо него `docker compose down -v`, который для `external: true` volume'а — no-op).

### Q: Telethon просит SMS-код при первом ingest.

**A:** Значит session-файл в `data/sessions/` отсутствует или невалиден. Ввести код один раз — он сохранится в session-файле, который binds-mount'ится в контейнер.

### Q: Можно ли НЕ удалять volume и сделать in-place upgrade?

**A:** Не рекомендуется без отдельного аудита. См. `docs/plans/DEV_RESURRECTION_PLAN.md` раздел 1 (decision matrix). Короткий ответ: текущие initial-миграции (`89f91e768b9b`, `f40d85317f03`) используют `op.create_table` без `IF NOT EXISTS` → упадут на любой непустой схеме без предварительного `alembic stamp`. А stamp под несуществующий baseline закладывает мину под все будущие миграции.

### Q: `migrate-users` показывает `mcp_tokens_mapped=0` и `telegram_users_mapped=0`, хотя в `.env` всё есть.

**A:** Это **DI-12** (см. FUTURE_FEATURES.md). Известный баг: CLI `migrate-users` silently не маппит mcp_token и telegram даже когда Settings правильно парсит значения. Workaround — async-скрипт с прямым `repo.add_auth_mapping(...)` (см. шаг 5 выше). До починки бага запускать workaround **обязательно** после каждого fresh resurrection, иначе F4 multi-tenancy не работает (Claude Desktop, telegram bot).

### Q: HTTP `/api/v1/search` или `/api/v1/ask` возвращает 500 Internal Server Error.

**A:** Это **DI-15** (см. FUTURE_FEATURES.md). В `tg_parser` логах будет:

```
sqlalchemy.exc.IllegalStateChangeError:
Method 'close()' can't be called here; method '_connection_for_bind()' is already in progress
```

Async session lifecycle bug в `tg_parser/services/db_context.py::embedding_repos`. Также блокирует MCP `ask_question` (тот же code path). **MCP `search_knowledge_base` НЕ затронут** — используй его для retrieval, пока DI-15 не починен.

### Q: CI job `alembic-guardrail` зависает на step `Smoke upgrade head -> downgrade base -> upgrade head`.

**A:** Это **DI-14** (см. FUTURE_FEATURES.md). `tg-parser db downgrade` использует `typer.confirm()` без bypass-флага → в non-tty контексте ждёт input бесконечно. Workaround в CI: `yes y | tg-parser db downgrade --db "$db" base` (уже стоит в `.github/workflows/ci.yml`). Если добавляешь новый CI step с downgrade — не забудь pipe.

### Q: Какая правильная команда добавить канал — `add-channel` или `add-source`?

**A:** **`add-source`**. Команды `add-channel` не существует. Минимальный набор аргументов — `--source-id`, `--channel-id`, `--channel-username` (часто все три = название канала, см. шаг 6). См. `tg-parser add-source --help` для полного списка.

### Q: Какая правильная команда запустить ingestion — `pipeline run --channel <X>` или `run --source <X>`?

**A:** **`tg-parser run --source <id>`**. `--source` — обязательный аргумент. Удобно запускать в фоне через `docker compose exec -d` с redirect в файл (см. шаг 7).

### Q: На VPS чем отличается?

Главные отличия (см. также `docs/plans/DEV_RESURRECTION_PLAN.md` §4 + Appendix A + Appendix C.5):

1. **Селективный tear down.** На VPS живут соседние стеки (`flowise`, `n8n*`, `portainer`, `dozzle`) и собственная инфраструктура (`tg_parser_grafana`, `tg_parser_prometheus`, `tg_parser_caddy`). НЕ делать `docker compose down` без аргументов. Останавливать только `tg_parser`, `mcp`, `tg_bot`, `postgres`.
   > **⚠️ Грабля:** в compose service называется `mcp`, не `tg_parser_mcp`. Команда `docker compose stop tg_parser tg_parser_mcp tg_bot` упадёт с `no such service: tg_parser_mcp`. Правильно: `COMPOSE_PROFILES=bot docker compose stop tg_parser mcp tg_bot`.
2. **Бот запущен через profile.** Restart обязательно с `COMPOSE_PROFILES=bot docker compose up -d tg_parser mcp tg_bot` (или `--profile bot`). Без profile бот не подхватится.
3. **Compose v5.1.0 stand-alone**, не upstream Compose v2 (бинарник по `/usr/libexec/docker/cli-plugins/docker-compose`). Парсит наш `docker-compose.yml` корректно, но если увидишь поведение, отличное от документации Compose v2 — проверь версию через `docker compose version --short`.
4. **Image rebuild обязателен после `git checkout main`.** На VPS `tg_parser:latest` собран на старой ветке — без `docker compose build tg_parser` после checkout будет диссонанс.
5. **F9 Phase 1 включён** (`API_KEY_REQUIRED=true`, `MCP_AUTH_ENABLED=true` в `.env`). Verification endpoints требуют:
   - API: заголовок `X-API-Key: <key из .env API_KEYS>` или `Authorization: Bearer <key>`.
   - MCP: `Authorization: Bearer <token из .env MCP_AUTH_TOKENS>`.
   - `/health`, `/metrics` — открыты, без auth.
6. **Telethon session — owner=root в bind-mount.** Это не баг, а нормальное поведение (контейнер запускается от root). Не пытаться «починить» через `chown`.
7. **Бэкап.** В `data/backups/` уже лежит `postgres_*.sql.gz` от 10 апреля. Этого достаточно как emergency rollback. Дополнительный фреш-dump опционален.
8. **Downtime окно.** Стек на VPS реально работает (бот отвечает на запросы). Зафиксировать start/end timestamp, чтобы выработать привычку для будущего production-deploy.
9. **Перед началом — push локальных коммитов.** Прежде чем подключаться к VPS, убедиться что `git log --oneline origin/main..HEAD` пусто (всё запушено). VPS сделает `git pull --ff-only` — без push'а изменений сервер так и останется на старом коде, и весь rebuild будет использовать устаревший `Settings`/CLI/migrations.

---

## Откат (если что-то пошло не так на ШАГЕ < 7)

```bash
docker compose down
docker volume rm tg_parser_pgvector17_data
# Вернуться к шагу 3
```

Так как мы намеренно не делали бэкап (full rebuild от и до), "откат" = "начать с шага 3".

Если волнуешься — перед шагом 2 можно сделать `pg_dump` (но обычно не нужно, см. план §2).
