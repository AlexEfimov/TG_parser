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

**Критерий:** 1 admin user; в `user_auth_mappings` есть строки `telegram` (по числу id в `BOT_ALLOWED_USERS`); если в `.env` есть API/MCP keys — они тоже маппятся.

### 6. Поднять основной сервис и подключить канал(ы)

```bash
docker compose up -d tg_parser                              # API + scheduler
docker compose exec tg_parser tg-parser add-channel labdiagnostica_logical
```

> Замени `labdiagnostica_logical` на нужный канал. На фазе resurrection — только 1 канал для быстрой проверки; остальные доподключаются после.

**Критерий:** в `sources` появилась строка `status='active'`, `owner_id = admin.id`.

### 7. Запустить pipeline (или дождаться scheduler tick'а)

```bash
docker compose exec tg_parser tg-parser pipeline run --channel labdiagnostica_logical
```

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

### Q: На VPS чем отличается?

Главные отличия (см. также `docs/plans/DEV_RESURRECTION_PLAN.md` §4 + Appendix A):

1. **Селективный tear down.** На VPS живут соседние стеки (`flowise`, `n8n*`, `portainer`, `dozzle`) и собственная инфраструктура (`tg_parser_grafana`, `tg_parser_prometheus`, `tg_parser_caddy`). НЕ делать `docker compose down` без аргументов. Останавливать только `tg_parser`, `tg_parser_mcp`, `tg_bot`, `postgres`.
2. **Бот запущен через profile.** Restart обязательно с `COMPOSE_PROFILES=bot docker compose up -d tg_parser tg_parser_mcp tg_bot` (или `--profile bot`). Без profile бот не подхватится.
3. **Compose v5.1.0 stand-alone**, не upstream Compose v2 (бинарник по `/usr/libexec/docker/cli-plugins/docker-compose`). Парсит наш `docker-compose.yml` корректно, но если увидишь поведение, отличное от документации Compose v2 — проверь версию через `docker compose version --short`.
4. **Image rebuild обязателен после `git checkout main`.** На VPS `tg_parser:latest` собран на старой ветке — без `docker compose build tg_parser` после checkout будет диссонанс.
5. **F9 Phase 1 включён** (`API_KEY_REQUIRED=true`, `MCP_AUTH_ENABLED=true` в `.env`). Verification endpoints требуют:
   - API: заголовок `X-API-Key: <key из .env API_KEYS>` или `Authorization: Bearer <key>`.
   - MCP: `Authorization: Bearer <token из .env MCP_AUTH_TOKENS>`.
   - `/health`, `/metrics` — открыты, без auth.
6. **Telethon session — owner=root в bind-mount.** Это не баг, а нормальное поведение (контейнер запускается от root). Не пытаться «починить» через `chown`.
7. **Бэкап.** В `data/backups/` уже лежит `postgres_*.sql.gz` от 10 апреля. Этого достаточно как emergency rollback. Дополнительный фреш-dump опционален.
8. **Downtime окно.** Стек на VPS реально работает (бот отвечает на запросы). Зафиксировать start/end timestamp, чтобы выработать привычку для будущего production-deploy.

---

## Откат (если что-то пошло не так на ШАГЕ < 7)

```bash
docker compose down
docker volume rm tg_parser_pgvector17_data
# Вернуться к шагу 3
```

Так как мы намеренно не делали бэкап (full rebuild от и до), "откат" = "начать с шага 3".

Если волнуешься — перед шагом 2 можно сделать `pg_dump` (но обычно не нужно, см. план §2).
