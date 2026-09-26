# Runbook — DF-4: ссылки `t.me/…` сводятся к username + чистка фантомов `Ye_Ale` (R15)

**Создан:** 2026-09-26 (сессия R15). **Статус: ВЫПОЛНЕНО 2026-09-26** по GO владельца — merge `4b194e4` ([PR #454](https://github.com/AlexEfimov/TG_parser/pull/454)), контейнеры пересозданы 14:09Z, фантомы `Ye_Ale` удалены (вариант (a)) 16:03:03Z. Scope — [`START_PROMPT_R15_TME_URL_NORMALIZATION_2026-09-26.md`](../notes/archive/START_PROMPT_R15_TME_URL_NORMALIZATION_2026-09-26.md).

**Что деплоим:** закрытая грамматика ссылок в `normalize_channel_id` (`https://t.me/x`, `t.me/s/x/5` … → `x`; прочий link-like ввод → `InvalidChannelUsername`, никогда не «без фильтра»); нормализация source id до RBAC / lookup / idempotency / lock на всех внешних входах (бот, MCP, HTTP, CLI) и `validate_channel_username` на путях записи. Меняется код всех трёх процессов. Миграции нет, `.env` и compose не меняются.

## 0. Перед деплоем

Снимок 2026-09-26 14:04Z (read-only):

| Проверка | Факт |
|---|---|
| Прод и `main` | прод `f84b398`, рабочая копия чистая; `main` `4b194e4` |
| Образы | `tg_parser`, `tg_parser_mcp`, `tg_parser_bot` — все `0f7efaeeb46b` (`tg_parser:latest`), healthy |
| Фаза тика | `:02`; тик 14:02 закончился 14:03:20Z, `succeeded=18, failed=0` |
| Строки `sources` с `/` или `:` | ровно две: `https://t.me/physics_of_business` и `t.me/physics_of_business`; `source_id = channel_id`, владелец `0e4f4650-0e2b-4757-8396-2e7dd370bddc` (= `Ye_Ale` по `users`), созданы 2026-08-31 08:49:07–08Z, удалены 08:50:33Z, `last_post_id` пуст |
| Настоящий канал | `physics_of_business` — живая строка, владелец `Alamogordo777` |
| `sources` всего | 25, живых 18 |

**Точка отката:** `tg_parser:pre-r15-2026-09-26` → **`0f7efaeeb46b`** (один тег на три сервиса).

## 1. Деплой

```bash
ssh prod 'cd /home/user/TG_parser && git pull --ff-only'
ssh prod 'cd /home/user/TG_parser && docker compose build tg_parser'
ssh prod 'cd /home/user/TG_parser && docker compose --profile bot up -d --no-deps --force-recreate tg_parser mcp tg_bot'
```

| Шаг | Факт |
|---|---|
| `git pull` | прод `f84b398` → **`4b194e4`**, рабочая копия чистая |
| Образ `tg_parser:latest` | **`6d0461e9a379`**, сборка 14:07:45–14:08:36Z |
| Пересоздание | **14:08:45–14:09:04Z**, между тиками (тик 14:02 закончился 14:03:20Z) |
| `Background scheduler started` | **14:09:16Z** — новая фаза тика `:09`, первый тик ~15:09Z |

## 2. Проверка кода (только чтение)

| # | Что | Факт |
|---|---|---|
| 1 | Все три healthy, новый образ | ✅ `6d0461e9a379`, `healthy`, `RestartCount=0`; строк уровня error / critical в логах трёх процессов — 0 |
| 2 | Прод-MCP `list_topics` | ✅ `channel_id="https://t.me/kdl_ru"` = `"kdl_ru"`: `total=48`, те же id первой страницы (`limit=3`); `"https://t.me/+abc"` — отказ `«…» — не ссылка на публичный Telegram-канал`, не полный список |
| 3 | HTTP на хосте `GET /api/v1/topics` | ✅ ключ из настроек контейнера, не выводился: `kdl_ru` и `https://t.me/kdl_ru` — `200`, `total=48`; `https://t.me/+abc` — `422 InvalidChannelUsername` |
| 4 | Первый тик после деплоя | ✅ 15:09→15:10:30Z: `succeeded=18, failed=0, degraded=0`, 74 с; строк error / critical — 0 |

Пишущих вызовов на проде для проверки не делалось.

## 3. Чистка фантомов `Ye_Ale` (отдельный GO)

Объём — вариант (a): жёсткое удаление двух строк `sources`; `audit_log` не трогается. Данных под фантомами нет (§1 промпта).

**Зависимости** снимаются внутри транзакции из `information_schema.columns` живой схемы по колонкам `source_id`, `channel_id`, `source_ref`, `sources_json`, `channels_json`, `channel_ids` (на схеме head — 13 таблиц кроме `sources`, включая `workspace_sources` с FK `ON DELETE CASCADE`). Любая ссылка на фантом — `ABORT` без удаления.

**Бэкап** (до чистки):

```bash
ssh prod 'install -d -m 700 /mnt/data/backups/tg_parser/pre-r15 \
  && docker exec tg_parser_postgres pg_dump -U tg_parser_user -d tg_parser -Fc -t sources \
       > /mnt/data/backups/tg_parser/pre-r15/sources_20260926.dump \
  && test -s /mnt/data/backups/tg_parser/pre-r15/sources_20260926.dump \
  && docker exec -i tg_parser_postgres pg_restore --list < /mnt/data/backups/tg_parser/pre-r15/sources_20260926.dump | head \
  && sha256sum /mnt/data/backups/tg_parser/pre-r15/sources_20260926.dump'
```

**Блок SQL** — через stdin, дважды: с дописанным `ROLLBACK;` (пробный), затем с `COMMIT;`. Предохранители, проверка зависимостей и контроль сами делают `ROLLBACK` и выходят из `psql`.

```sql
\set ON_ERROR_STOP on
\set owner '0e4f4650-0e2b-4757-8396-2e7dd370bddc'
\set a 'https://t.me/physics_of_business'
\set b 't.me/physics_of_business'
BEGIN;

SELECT source_id FROM sources WHERE source_id IN (:'a', :'b') ORDER BY 1 FOR UPDATE;

SELECT (SELECT count(*) FROM sources WHERE source_id IN (:'a', :'b')) = 2
   AND (SELECT count(*) FROM sources
         WHERE source_id IN (:'a', :'b') AND source_id = channel_id
           AND owner_id::text = :'owner' AND deleted_at IS NOT NULL AND last_post_id IS NULL) = 2
   AND (SELECT name FROM users WHERE id::text = :'owner') = 'Ye_Ale'
   AND (SELECT count(*) FROM sources WHERE channel_id = 'physics_of_business' AND deleted_at IS NULL) = 1
   AS guards_ok \gset
\if :guards_ok
  \echo 'guards ok'
\else
  \echo 'ABORT: guards failed, nothing deleted'
  ROLLBACK;
  \q
\endif

CREATE TEMP TABLE phantom_refs (tbl text, col text, n bigint) ON COMMIT DROP;
DO $$
DECLARE
  ids text[] := ARRAY['https://t.me/physics_of_business', 't.me/physics_of_business'];
  r record;
  cond text;
  n bigint;
BEGIN
  FOR r IN
    SELECT table_name, column_name, data_type
      FROM information_schema.columns
     WHERE table_schema = 'public'
       AND column_name IN ('source_id', 'channel_id', 'source_ref', 'sources_json',
                           'channels_json', 'channel_ids')
       AND table_name <> 'sources'
     ORDER BY 1, 2
  LOOP
    IF r.data_type = 'ARRAY' THEN
      cond := format('%I && $1', r.column_name);
    ELSIF r.column_name IN ('sources_json', 'channels_json') THEN
      cond := format('%I::jsonb ?| $1', r.column_name);
    ELSIF r.column_name = 'source_ref' THEN
      cond := format('starts_with(%I, ''tg:'' || $1[1] || '':'') OR starts_with(%I, ''tg:'' || $1[2] || '':'')',
                     r.column_name, r.column_name);
    ELSE
      cond := format('%I = ANY($1)', r.column_name);
    END IF;
    EXECUTE format('SELECT count(*) FROM %I WHERE %s', r.table_name, cond) INTO n USING ids;
    INSERT INTO phantom_refs VALUES (r.table_name, r.column_name, n);
  END LOOP;
END $$;

SELECT tbl, col, n FROM phantom_refs ORDER BY tbl, col;
SELECT count(*) = 0 AS deps_ok FROM phantom_refs WHERE n > 0 \gset
\if :deps_ok
  \echo 'deps ok'
\else
  \echo 'ABORT: a phantom is referenced, nothing deleted'
  ROLLBACK;
  \q
\endif

SELECT count(*) AS audit_before FROM audit_log WHERE resource_id IN (:'a', :'b') \gset

DELETE FROM sources
 WHERE source_id IN (:'a', :'b') AND source_id = channel_id
   AND owner_id::text = :'owner' AND deleted_at IS NOT NULL AND last_post_id IS NULL;

SELECT (SELECT count(*) FROM sources WHERE source_id ~ '[/:]' OR channel_id ~ '[/:]') = 0
   AND (SELECT count(*) FROM sources WHERE channel_id = 'physics_of_business' AND deleted_at IS NULL) = 1
   AND (SELECT count(*) FROM audit_log WHERE resource_id IN (:'a', :'b')) = :audit_before
   AS control_ok \gset
\echo 'audit rows for the phantoms:' :audit_before
\if :control_ok
  \echo 'control ok'
\else
  \echo 'ABORT: control failed, rolled back'
  ROLLBACK;
  \q
\endif
```

Агент не набирает `COMMIT` в интерактивной сессии: блок выше подаётся в `psql` через stdin дословно, с дописанным `ROLLBACK;` или `COMMIT;`.

| Шаг | Факт |
|---|---|
| Прогон блока на `tg_parser_test` | ✅ засев: `Ye_Ale` с прод-UUID, живой `physics_of_business` другого владельца, живой `kdl_ru`, два фантома, 4 строки `audit_log`. С `ROLLBACK` — `guards ok`, `deps ok`, `control ok`, все строки на месте; с `COMMIT` — удалены ровно два фантома, живые строки и 4 строки аудита на месте; фантом в `workspace_sources` — `ABORT: a phantom is referenced, nothing deleted`; фантом без `deleted_at` — `ABORT: guards failed, nothing deleted` |
| Бэкап | ✅ 15:48:33Z, `/mnt/data/backups/tg_parser/pre-r15/sources_20260926.dump` (каталог `700`), 5 760 байт; `pg_restore --list` читается — `TABLE public sources` и `TABLE DATA public sources`; sha256 `560925e95ac3d68cc9ef3bd956080798799ebca8b71c83a523c7798723043d26` |
| Пробный прогон на проде (`ROLLBACK`) | ✅ 16:02:23Z: `guards ok`; 25 колонок в 13 таблицах — все `n = 0`; `deps ok`; строк аудита по фантомам 4; `control ok`, откат |
| `COMMIT`, время | ✅ **16:03:03Z** — `guards ok`, `deps ok`, `control ok` |
| Контроль после | строк `sources` с `/` или `:` — **0**; `sources` 23, живых 18 (было 25 / 18); `physics_of_business` — живая, владелец `Alamogordo777`; строк `audit_log` по фантомам — 4, не тронуты |
| Тик после чистки | ✅ 16:09→16:11:05Z: `succeeded=18, failed=0, degraded=0`, 109 с; строк error / critical — 0 |

## 4. Откат

Код — только образ, данных он не меняет:

```bash
ssh prod 'docker tag tg_parser:pre-r15-2026-09-26 tg_parser:latest \
  && cd /home/user/TG_parser \
  && docker compose --profile bot up -d --no-deps --force-recreate tg_parser mcp tg_bot'
```

Чистка: до `COMMIT` — `ROLLBACK`. После — ровно две строки из бэкапа §3. `pg_restore` прямо в рабочую `sources` вернул бы всю таблицу и упёрся бы в существующие первичные ключи, а восстановление во временную базу падает на внешнем ключе `owner_id → users` (таблицы `users` в дампе нет). Поэтому строки берутся из текстовых данных дампа и грузятся `\copy` со списком колонок из его заголовка — порядок колонок в рабочей таблице не важен. На хосте (`ssh prod`), в `bash`:

```bash
set -euo pipefail
umask 077
D=/mnt/data/backups/tg_parser/pre-r15/sources_20260926.dump
OUT=$(mktemp)
trap 'rm -f "$OUT" "$OUT.all"' EXIT
docker exec -i tg_parser_postgres pg_restore --data-only -t sources -f - < "$D" > "$OUT.all"
COLS=$(grep -m1 '^COPY public\.sources ' "$OUT.all" | sed -E 's/^COPY public\.sources (\(.*\)) FROM stdin;$/\1/')
awk -F'\t' '/^COPY public\.sources /{f=1; next} /^\\\.$/{f=0}
            f && ($1 == "https://t.me/physics_of_business" || $1 == "t.me/physics_of_business")' \
  "$OUT.all" > "$OUT"
test "$(wc -l < "$OUT")" -eq 2
docker exec -i tg_parser_postgres psql -U tg_parser_user -d tg_parser -X -q -1 -v ON_ERROR_STOP=1 \
  -c "\\copy sources $COLS FROM pstdin" \
  -c 'DO $$ BEGIN
        IF (SELECT count(*) FROM sources
             WHERE source_id IN ($q$https://t.me/physics_of_business$q$, $q$t.me/physics_of_business$q$)
               AND source_id = channel_id AND deleted_at IS NOT NULL AND last_post_id IS NULL
               AND owner_id = $q$0e4f4650-0e2b-4757-8396-2e7dd370bddc$q$) <> 2
        THEN RAISE EXCEPTION $q$restored rows do not match the phantoms, rolled back$q$;
        END IF;
      END $$' \
  < "$OUT"
test "$(docker exec tg_parser_postgres psql -U tg_parser_user -d tg_parser -X -At -c \
  "SELECT count(*) FROM sources WHERE source_id ~ '[/:]'")" -eq 2
echo 'restored 2 rows'
```

Загрузка и проверка — одна транзакция (`psql -1`): если строк не две или у них не совпадают `source_id = channel_id`, `deleted_at`, пустой курсор и владелец `Ye_Ale`, `DO`-блок бросает исключение и загрузка откатывается целиком. Любой сбой обрывает скрипт (`set -euo pipefail`, контроль — явный `test`); временные файлы — `600` и удаляются при любом выходе (`trap`). Повторный запуск упрётся в первичный ключ и ничего не изменит.

**Проверка процедуры (2026-09-26, локально, на проде не выполнялась):** блок выше, извлечённый из этого файла дословно (заменены только путь к дампу и имя базы), прогнан на `tg_parser_test` в трёх вариантах. (1) засев §3 → `pg_dump -Fc -t sources` → чистка блоком §3 с `COMMIT` → откат: `restored 2 rows`, обе строки с `deleted_at` и владельцем `Ye_Ale`, живые не тронуты. (2) Повторный запуск — выход 1 на `duplicate key`, строк столько же. (3) В дампе у фантома непустой `last_post_id` — выход 1, `restored rows do not match the phantoms, rolled back`, в таблице 0 восстановленных строк. `trap` проверен отдельно: файлы `600`, после падения по `set -e` удалены.
