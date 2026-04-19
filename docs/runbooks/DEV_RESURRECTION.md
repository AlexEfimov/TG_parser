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

**Критерий (что ожидается в идеале):** 1 admin user (DI-11 fix: миграция сидит admin'а, `migrate-users` его reuses); в `user_auth_mappings` есть строки `telegram` (по числу id в `BOT_ALLOWED_USERS`), `mcp_token` (по числу токенов в `MCP_AUTH_TOKENS`), и `api_key` (по числу ключей в `API_KEYS`).

После починки DI-11 / DI-12 (19 апреля 2026) больше не нужны workarounds. Если что-то всё-таки не так — диагностика:

1. **`api_keys_in_settings=0`, `mcp_tokens_in_settings=0` или `telegram_users_in_settings=0`** в выводе `migrate-users` (а ты ожидал >0): значит JSON в `.env` поломан. Должен быть WARN `json_dict_parse_failed` в логах контейнера — проверить, исправить `.env`, перезапустить.
2. **2 admin'а в `users`**: DI-11 fix откатили. `git log --oneline tg_parser/cli/migrate_users_cmd.py | head` должен содержать коммит про find_first_by_role.
3. **`mcp_tokens_in_settings=N`, но `mcp_tokens_mapped=0`**: реальный bug в repo (раньше DI-12 был ложно понят как такой). Запустить `pytest tests/test_migrate_users_cmd.py::TestMigrateUsersDI12 -v` — все 3 теста должны быть зелёные.

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
> После DI-13 fix (19 апреля 2026) `add-source` сам auto-resolve'ит owner к admin'у. Если админ не найден — команда падает с понятным сообщением и не создаёт orphan source. Можно явно указать владельца через `--owner-id <uuid>`. Re-run `migrate-users` после `add-source` больше **не нужен**.

**Критерий:** в `sources` появилась строка `status='active'`, `owner_id = admin.id` (выставлен прямо `add-source`).

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

**A:** Должно быть починено фиксом DI-12 (19 апреля 2026). Если повторяется:

1. Сравнить `api_keys_in_settings` / `mcp_tokens_in_settings` / `telegram_users_in_settings` в выводе `migrate-users` со значениями в `.env`. Если `*_in_settings=0`, JSON в `.env` некорректен — проверить логи на `json_dict_parse_failed` или `json_list_parse_failed` warning, исправить `.env`, перезапустить контейнер.
2. Если `*_in_settings=N`, но `*_mapped=0`, значит регрессия в repo. Прогнать `pytest tests/test_migrate_users_cmd.py::TestMigrateUsersDI12 -v` — все 3 теста должны быть зелёными.
3. Real root cause (для понимания): `parse_json_dict()` / `parse_json_list()` раньше silently возвращали `{}` / `["*"]` при `JSONDecodeError`. Теперь логируют WARNING + новые поля `*_in_settings` показывают 0 в выводе. Если было `MCP_AUTH_TOKENS=` без значения — pydantic ставит default `{}` без error (это OK).

### Q: На свежей VPS `migrate-users` показывает `mcp_tokens_mapped=0` и `telegram_users_mapped=0` БЕЗ warning'ов про `no_*_in_settings` (т.е. settings выглядят пустыми изнутри контейнера).

**A:** Это **DI-16** (compose env-leak — env-переменные не пробрасывались в `tg_parser` сервис). Должно быть починено фиксом DI-16 (19 апреля 2026). Если повторяется:

1. Внутри контейнера: `docker compose exec -T tg_parser env | grep -E '^(MCP_AUTH_TOKENS|BOT_ALLOWED_USERS)='` — должны быть **обе** строки. Если их нет — проверить `services.tg_parser.environment` в `docker-compose.yml`.
2. Pinning тест: `pytest tests/test_compose_env_propagation.py -v` — все 14 cases должны быть зелёными. Если красный case `test_tg_parser_service_exposes_auth_env[MCP_AUTH_TOKENS]` или аналогичный — кто-то откатил DI-16 fix.
3. После фикса compose recreate без image rebuild: `docker compose up -d tg_parser` — env-only изменение, ~6 сек.

### Q: MCP `tools/call ask_question` возвращает `Error executing tool ask_question: Anthropic API key required` (или `Gemini API key required`), хотя `.env` содержит соответствующий ключ и HTTP `/api/v1/ask` работает.

**A:** Это **DI-17** (sibling DI-16 для `mcp` сервиса). MCP-контейнер исторически имел только `OPENAI_API_KEY`. Должно быть починено фиксом DI-17 (19 апреля 2026). Если повторяется:

1. Внутри контейнера: `docker compose exec -T mcp env | grep -E '^(ANTHROPIC_API_KEY|GEMINI_API_KEY|RAG_LLM_PROVIDER|EMBEDDING_PROVIDER)='` — должны присутствовать ANTHROPIC_API_KEY и GEMINI_API_KEY.
2. Pinning тест: `pytest tests/test_compose_env_propagation.py::test_mcp_service_exposes_full_llm_surface -v` — все 7 параметризованных cases зелёные.
3. После фикса compose recreate: `docker compose up -d mcp` — env-only, ~6 сек.

### Q: Как почистить duplicate admin от pre-DI-11 deployment'а?

**A:** Если на VPS лежит deployment, сделанный **до** фикса DI-11 (19 апреля 2026), `users` может содержать 2 строки role='admin': старший (orphan от alembic-seed `b2c3d4e5f6a7`, без auth_mappings) и младший (созданный старым `migrate-users`, держит все mappings). Для cleanup'а:

1. **Бэкап** (обязательно): `docker exec tg_parser_postgres pg_dump -U tg_parser_user -d tg_parser | gzip > data/backups/pre_cleanup_$(date +%Y%m%d_%H%M%S).sql.gz`.
2. **Audit:** `psql ... -c "SELECT id, name, role, created_at FROM users ORDER BY created_at;"` — определить старшего/младшего по `created_at`.
3. **Проверить FK на старшего** (3 таблицы): `user_auth_mappings.user_id`, `sources.owner_id`, `digest_subscriptions.owner_id`. Все три COUNT'а должны быть 0 — иначе он не orphan, и нужен `UPDATE … SET user_id/owner_id = '<keep>'` ДО `DELETE`.
4. **Транзакция:**
   ```sql
   BEGIN;
   SELECT COUNT(*) FROM user_auth_mappings   WHERE user_id  = '<orphan_uuid>';  -- 0
   SELECT COUNT(*) FROM sources              WHERE owner_id = '<orphan_uuid>';  -- 0
   SELECT COUNT(*) FROM digest_subscriptions WHERE owner_id = '<orphan_uuid>';  -- 0
   DELETE FROM users WHERE id = '<orphan_uuid>';
   SELECT id, name, role, created_at FROM users;  -- ровно 1 row
   COMMIT;
   ```
5. **Verify:** `migrate-users --dry-run` после cleanup'а должен показывать `Skipped (already mapped): N` (N=кол-во auth_mappings) и `reusing_existing_admin_via_api_key`. На свежем deployment'е DI-11 не даст плодить дубликаты.

### Q: HTTP `/api/v1/search` или `/api/v1/ask` возвращает 500 Internal Server Error с `IllegalStateChangeError`.

**A:** Должно быть починено фиксом DI-15 (19 апреля 2026). Если падает снова:

1. Проверить, что в локальной checkout есть фикс: `git log --oneline tg_parser/services/retrieval_service.py | head -3` — должен быть коммит «fix(retrieval): DI-15 hybrid mode session safety» или похожий.
2. На VPS — после `git pull` обязателен `docker compose build tg_parser` (без rebuild старый image не содержит исправленной функции `search()`).
3. Запустить regression test: `pytest tests/test_retrieval_hybrid_session.py -v` — должны быть зелёные 5 cases. Если красный hybrid — значит фикс откатили или сломали.
4. Real root cause (для понимания): `asyncio.gather(sem_task, kw_task)` над **одной** AsyncSession — SQLAlchemy запрещает concurrent ops. Stack trace вёл к `session.close()` в `db_context.py` — это false alarm, реальный баг был в `retrieval_service.search()` hybrid path. См. **DI-15 FIXED** в FUTURE_FEATURES.md.

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
