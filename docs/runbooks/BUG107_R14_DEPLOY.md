# Runbook — BUG-107: удалённый канал невидим везде + чистка `murashko_med` (R14)

**Создан:** 2026-09-25 (сессия R14). **Статус: ВЫПОЛНЕНО 2026-09-25** по GO владельца — merge `f84b398` ([PR #451](https://github.com/AlexEfimov/TG_parser/pull/451)), контейнеры пересозданы 20:01:37Z, чистка `murashko_med` закоммичена 20:12:47Z. Факты — в колонках «Факт». Отложенная проверка расхода Phase 2 (§2 п. 6) — при первом вызове discover.

**Что деплоим:**

- scope пользователя — всегда явный список **живых** каналов, у admin тоже: `allowed_channel_ids = None` («все каналы») остался только у синтетического admin dev-режима. Отсюда поиск и RAG (все три режима), навигация, аналитика и все проверки доступа по `channel_id` (экспорт, пайплайн, статистика, подписки) перестают видеть удалённый канал;
- `get_owned_channel_ids` без удалённых — `whoami` / `list_users` / лимит (DF-5);
- каталог Phase 2, обе линковки, аналитика и `list_topics` без scope — через `list_all_except_deleted`; дайджест (канальный и тематический), backfill и калибровка watchlist, кандидаты re-summarize — без удалённых каналов;
- восстановление (повторный `add_channel`) считается созданием для лимита `max_channels`; повторный `remove_channel` удалённого канала — «not found»; кэш scope сбрасывается в процессе при добавлении, восстановлении и удалении.

Единое определение «удалённого канала» — [`channel_liveness.py`](../../tg_parser/storage/sqlalchemy/channel_liveness.py). Подробности и решения — [BUG-107](../notes/BUG_LOG.md).

**Не docs-only:** меняется код всех трёх процессов (`tg_parser`, `mcp`, `tg_bot`). Миграции **нет**, `.env` **не меняется**, compose не меняется. Чистка данных — отдельный шаг §3, код от неё не зависит.

---

## 0. Перед деплоем

Снимок 2026-09-25 ~14:30Z (read-only, сессия R14):

| Проверка | Команда / ожидание | Факт 2026-09-25 |
|---|---|---|
| Прод и `main` | `ssh prod 'cd /home/user/TG_parser && git log --oneline -1'` | прод `54350bc`, `main` `912904e` (впереди только docs) |
| Образы | `docker ps --format '{{.Names}} {{.Image}}'`, `docker images tg_parser:latest` | `tg_parser`, `tg_parser_mcp`, `tg_parser_bot` — `tg_parser:latest` = **`a6977308e61d`** |
| Фаза тика | `docker logs --since 3h tg_parser 2>&1 \| grep 'Running job' \| grep incremental_pipeline \| tail -1` | **`:31:47`** UTC |
| Soft-deleted строки `sources` | `SELECT channel_id, deleted_at FROM sources WHERE deleted_at IS NOT NULL` | 7 — те же, что 2026-09-23; живых **18** (было 17) |
| `topic_links` без FK | `\d topic_links` | подтверждено: только PK и индексы, внешних ключей на `topic_cards` нет |
| Счётчики владения | `users` ⋈ `sources` | `admin` 19 всего / **14** живых; `Ye_Ale` 4 / **2**; `Alamogordo777` 2 / 2 |
| Утечка в поиске | `search_knowledge_base(query="murashko_med", mode=keyword, limit=5)` от admin | 19:22Z: **все пять** результатов — посты `murashko_med` (`tg:murashko_med:post:12807`, `16450`, `17615`, `14432`, `18046`) |
| `whoami` оператора | MCP `whoami` | 19 owned, в списке `murashko_med` и шесть фантомов |
| Орфанные данные | документы / эмбеддинги / карточки с `channel_id` без строки `sources` | **0** во всех таблицах — admin-scope «живые каналы» не скрывает живых данных |

**Точка отката:**

```bash
ssh prod 'docker tag tg_parser:latest tg_parser:pre-r14-2026-09-25 && docker images tg_parser:pre-r14-2026-09-25 --format "{{.ID}}"'
# ожидается a6977308e61d — один тег на три сервиса (урок R13)
```

Факт 2026-09-25 19:23Z: ✅ `tg_parser:pre-r14-2026-09-25` → **`a6977308e61d`**.

## 1. Деплой (по GO)

Процедура — [`PRODUCTION_DEPLOYMENT.md`](../../PRODUCTION_DEPLOYMENT.md): пересоздание, не `restart` (BUG-078); `--force-recreate` (BUG-090); бот — под `--profile bot`; `--no-deps`, Postgres не трогать. Пересоздание стирает логи контейнеров и сдвигает фазу тика на «старт плюс интервал» (урок R10) — дождаться конца текущего тика.

```bash
ssh prod 'cd /home/user/TG_parser && git pull --ff-only'
ssh prod 'cd /home/user/TG_parser && docker compose build tg_parser'
ssh prod 'cd /home/user/TG_parser && docker compose --profile bot up -d --no-deps --force-recreate tg_parser mcp tg_bot'
```

Если R15 (DF-4) готова — едет этим же образом.

| Шаг | Факт |
|---|---|
| `git pull` | прод `54350bc` → **`f84b398`**, рабочая копия чистая |
| Образ `tg_parser:latest` | **`0f7efaeeb46b`**, сборка 19:23–19:24Z, ~60 с. R15 в образ не вошла — не готова |
| Пересоздание, время | тик 19:31 дождались: `succeeded=18, failed=0`, 93 с, конец 19:33:20Z. Пересоздание **20:01:37Z** — ожидание конца тика заняло лишние полчаса: `grep` по `Job "incremental_pipeline…executed` не совпадал, в JSON-логе кавычки экранированы (`\"`). Искать `grep -F 'incremental_pipeline'` + `executed successfully` |
| `Background scheduler started` — новая фаза | **20:02:13Z** — фаза тика `:02`, первый тик ~21:02Z |

## 2. Проверка кода

| # | Что | Ожидание | Факт |
|---|---|---|---|
| 1 | Все три healthy | `docker ps` | ✅ `tg_parser`, `tg_parser_mcp`, `tg_parser_bot` — `0f7efaeeb46b`, `healthy` через минуту |
| 2 | Поиск admin | тот же `search_knowledge_base(mode=keyword)`, что в §0, **не** возвращает `murashko_med` | ✅ 20:03Z (до чистки): четыре результата, все `mediamedics` (посты, где упомянут `@murashko_med`), ни одного документа или темы `murashko_med` |
| 3 | `whoami` оператора | 14 живых каналов, без `murashko_med` и фантомов | ✅ `owned_channels_count: 14` |
| 4 | `list_users` | `Ye_Ale` — 2, `admin` — 14 | ⚠️ через MCP не снят — вызов отклонён автопроверкой агента как лишний доступ к данным. Счётчик строится тем же `get_owned_channel_ids`, что и `whoami` (п. 3); на уровне SQL в §0 — `Ye_Ale` 2 живых |
| 5 | Первый тик | `incremental_pipeline … executed successfully`, `failed=0` | ✅ 21:02→21:03:30Z: `succeeded=18, failed=0, degraded=0`, 76 с — уже после чистки. Вызова Phase 2 в тике не было |
| 6 | Phase 2 после деплоя (отложенно) | `cross_channel_topics` в строке `Phase 2 discover call:` меньше базовой линии на ~850; `prompt_chars` на ~25 % меньше 757 515; прирост `stage="topicization_discover"` меньше 290 961. Сверка — как в [runbook R13](BUG108A_R13_DEPLOY.md) §3 | |

Эффект §2 п. 6 появляется **сразу после деплоя кода**, до чистки: каталог уже фильтруется. Чистка §3 убирает данные, а не влияние.

## 3. Чистка `murashko_med` (отдельный GO)

Объём — **полное удаление** (решение владельца 2026-09-25). Строка `sources` остаётся: на ней держится путь восстановления.

**Таблицы.** Перечислены через `information_schema.columns` по колонкам `channel_id` / `source_id` / `source_ref` / `sources_json` / `channel_ids` / `channels_json` / `topic_id*` (2026-09-25):

| Таблица | Строк `murashko_med` | Решение |
|---|---:|---|
| `topic_cards` | 850 (все — единственный источник; карточек с несколькими источниками в базе **0**) | удалить |
| `topic_card_versions` | 0 | каскад по FK `ON DELETE CASCADE` |
| `topic_links` | **909** (было 904 на 2026-09-23 — инкрементальная линковка до R14 продолжала связывать с удалённым каналом); ни одной связи «обе стороны — `murashko_med`» | удалить явно по id карточек — **FK нет** |
| `topic_bundles` | 850 (по `topic_id`; `channels_json` у всех — только этот канал) | удалить |
| `document_embeddings` | 17 630 (все с единственным `channel_ids`, все `source_ref` — `tg:murashko_med:`; тематических эмбеддингов у карточек канала нет) | удалить |
| `processed_documents` | 18 056 | удалить |
| `raw_messages` | 33 248 | удалить |
| `processing_failures` | **15 069** | удалить: ссылаются на удаляемые raw-сообщения, повтор без них невозможен |
| `processing_dedup_drops`, `raw_conflicts`, `comment_cursors`, `task_history`, `api_jobs` | 0 | не касается |
| `digest_subscriptions`, `watch_interests`, `watch_matches`, `workspace_sources` | 0 | не касается |
| `source_attempts` | 174 | **оставить** — история попыток |
| `audit_log` | 0 по `resource_id` | оставить |
| `sources` | 1 (`deleted_at` = 2026-07-06) | **оставить** — путь восстановления |

⚠️ **После чистки восстановление не вернёт историю.** Строка `sources` хранит курсор (`last_post_id`, `backfill_completed_at`), поэтому повторный `add_channel` продолжит сбор с курсора, а удалённые сообщения заново не соберёт.

**Бэкап — вне рабочей копии.** Штатный скрипт ночного дампа, отдельный каталог на `/mnt/data` (там ~9 ГБ свободно, ночной дамп — ~400 МБ). Retention `3650` — чтобы ротация скрипта не удалила этот дамп вместе с ночными:

```bash
ssh prod 'install -d -m 700 /mnt/data/backups/tg_parser/pre-r14 \
  && /home/user/TG_parser/docker/backup.sh /mnt/data/backups/tg_parser/pre-r14 3650 \
  && ls -la /mnt/data/backups/tg_parser/pre-r14'
```

**Процедура.** `psql` на хосте, в интерактивной сессии, между тиками. Предохранители и контроль исполняемые: при провале блок сам делает `ROLLBACK` и выходит из `psql` (`\gset` + `\if`), напечатанные числа не надо сверять глазами, чтобы не закоммитить лишнее. Сам блок **не** коммитит: `COMMIT` набирается руками после строки `control ok`.

```bash
ssh -t prod 'docker exec -it tg_parser_postgres psql -U tg_parser_user -d tg_parser'
```

```sql
\set ON_ERROR_STOP on
\set ch 'murashko_med'
BEGIN;

-- Предохранители: канал удалён, живой строки с тем же channel_id нет, и нет
-- карточек, где канал — один из нескольких источников (их не удаляем).
SELECT (SELECT count(*) FROM sources WHERE channel_id = :'ch' AND deleted_at IS NOT NULL) = 1
   AND (SELECT count(*) FROM sources WHERE channel_id = :'ch' AND deleted_at IS NULL) = 0
   AND (SELECT count(*) FROM topic_cards
         WHERE sources_json::jsonb ? :'ch' AND jsonb_array_length(sources_json::jsonb) > 1) = 0
   AS guards_ok \gset
\if :guards_ok
  \echo 'guards ok'
\else
  \echo 'ABORT: guards failed, nothing deleted'
  ROLLBACK;
  \q
\endif

-- Точное условие вместо LIKE: sources_json — TEXT, '_' в LIKE — подстановочный знак.
CREATE TEMP TABLE purge_cards ON COMMIT DROP AS
  SELECT id FROM topic_cards WHERE sources_json::jsonb = jsonb_build_array(:'ch'::text);

-- Пробный подсчёт (сверить с таблицей выше).
SELECT 'cards' t, count(*) FROM purge_cards
UNION ALL SELECT 'links', count(*) FROM topic_links
  WHERE topic_id_a IN (SELECT id FROM purge_cards) OR topic_id_b IN (SELECT id FROM purge_cards)
UNION ALL SELECT 'bundles', count(*) FROM topic_bundles WHERE topic_id IN (SELECT id FROM purge_cards)
UNION ALL SELECT 'versions', count(*) FROM topic_card_versions WHERE topic_id IN (SELECT id FROM purge_cards)
UNION ALL SELECT 'embeddings', count(*) FROM document_embeddings
  WHERE channel_ids = ARRAY[:'ch']::text[] OR topic_id IN (SELECT id FROM purge_cards)
UNION ALL SELECT 'processed', count(*) FROM processed_documents WHERE channel_id = :'ch'
UNION ALL SELECT 'raw', count(*) FROM raw_messages WHERE channel_id = :'ch'
UNION ALL SELECT 'failures', count(*) FROM processing_failures WHERE channel_id = :'ch';

DELETE FROM topic_links
 WHERE topic_id_a IN (SELECT id FROM purge_cards) OR topic_id_b IN (SELECT id FROM purge_cards);
DELETE FROM topic_bundles WHERE topic_id IN (SELECT id FROM purge_cards);
DELETE FROM document_embeddings
 WHERE channel_ids = ARRAY[:'ch']::text[] OR topic_id IN (SELECT id FROM purge_cards);
DELETE FROM topic_cards WHERE id IN (SELECT id FROM purge_cards);   -- versions: каскад
DELETE FROM processed_documents WHERE channel_id = :'ch';
DELETE FROM processing_failures WHERE channel_id = :'ch';
DELETE FROM raw_messages WHERE channel_id = :'ch';

-- Контроль: всё 0, висячих связей нет, строка sources на месте.
SELECT 'cards_left' t, count(*) FROM topic_cards WHERE sources_json::jsonb ? :'ch'
UNION ALL SELECT 'dangling_links', count(*) FROM topic_links l
  WHERE NOT EXISTS (SELECT 1 FROM topic_cards c WHERE c.id = l.topic_id_a)
     OR NOT EXISTS (SELECT 1 FROM topic_cards c WHERE c.id = l.topic_id_b)
UNION ALL SELECT 'embeddings_left', count(*) FROM document_embeddings WHERE :'ch' = ANY(channel_ids)
UNION ALL SELECT 'processed_left', count(*) FROM processed_documents WHERE channel_id = :'ch'
UNION ALL SELECT 'raw_left', count(*) FROM raw_messages WHERE channel_id = :'ch'
UNION ALL SELECT 'failures_left', count(*) FROM processing_failures WHERE channel_id = :'ch'
UNION ALL SELECT 'sources_row_kept', count(*) FROM sources WHERE channel_id = :'ch';

SELECT NOT EXISTS (SELECT 1 FROM topic_cards WHERE sources_json::jsonb ? :'ch')
   AND NOT EXISTS (SELECT 1 FROM topic_links l
        WHERE NOT EXISTS (SELECT 1 FROM topic_cards c WHERE c.id = l.topic_id_a)
           OR NOT EXISTS (SELECT 1 FROM topic_cards c WHERE c.id = l.topic_id_b))
   AND NOT EXISTS (SELECT 1 FROM document_embeddings WHERE :'ch' = ANY(channel_ids))
   AND NOT EXISTS (SELECT 1 FROM processed_documents WHERE channel_id = :'ch')
   AND NOT EXISTS (SELECT 1 FROM raw_messages WHERE channel_id = :'ch')
   AND NOT EXISTS (SELECT 1 FROM processing_failures WHERE channel_id = :'ch')
   AND (SELECT count(*) FROM sources WHERE channel_id = :'ch') = 1
   AS control_ok \gset
\if :control_ok
  \echo 'control ok: type COMMIT; to commit, ROLLBACK; to discard'
\else
  \echo 'ABORT: control failed, rolled back'
  ROLLBACK;
  \q
\endif
```

После `COMMIT` — вне транзакции:

```sql
VACUUM (ANALYZE) topic_links, topic_bundles, topic_cards, document_embeddings,
                 processed_documents, processing_failures, raw_messages;
```

Агент не может набрать `COMMIT` в интерактивной сессии, поэтому блок выполнен дважды через stdin, извлечённый из этого файла дословно: сначала с дописанным `ROLLBACK;` (пробный), затем с `COMMIT;`. Предохранители и контроль внутри блока выходят из `psql` до `COMMIT`, если что-то не сошлось.

| Шаг | Факт |
|---|---|
| Дамп: файл, размер | ✅ `/mnt/data/backups/tg_parser/pre-r14/postgres_20260925_220327.sql.gz` (каталог `700`), **382 МБ**, 20:03:27–20:05:10Z; `gzip -t` OK, 30 таблиц (`COPY public.`). На `/mnt/data` осталось 9.0 ГБ |
| Пробный подсчёт (с `ROLLBACK`) | `guards ok`; cards **850**, links **909**, bundles **850**, versions 0, embeddings **17 630**, processed **18 056**, raw **33 248**, failures **15 069** — ровно таблица выше; `control ok`, откат |
| Контроль после `DELETE` | те же числа удалений; все `*_left` = 0, `dangling_links` = 0, `sources_row_kept` = 1, `control ok` |
| `COMMIT`, время | ✅ **20:12:47Z**, затем `VACUUM (ANALYZE)` по семи таблицам |
| Повторный подсчёт | связей с темами `murashko_med` **0**, висячих связей 0; карточек / эмбеддингов / документов / raw канала 0; `source_attempts` 174 и строка `sources` на месте; `topic_cards` всего **1 452** |
| `topic_links` всего после | **4 695** (было 5 584 на 14:30Z; ожидали 4 675 = 5 584 − 909 — тик 19:31 добавил ~20 связей между живыми каналами до пересоздания) |

**Проверка процедуры (2026-09-25, локально):** блок SQL выше, извлечённый из этого файла дословно, прогнан с `COMMIT` на `tg_parser_test`. Засев: удалённый `murashko_med`, живой `live_ch`, живой `murashko_medX` — имя с тем же префиксом, — по карточке, бандлу, эмбеддингу, документу, raw и failure на каждый; связи `live ↔ murashko_med`, `murashko_med ↔ murashko_medX`, `live ↔ murashko_medX`. Итог: удалены ровно строки `murashko_med` и обе его связи, связь `live ↔ murashko_medX` и все строки двух живых каналов на месте, строка `sources` удалённого канала сохранена, `dangling_links = 0`, напечатано `guards ok` и `control ok`. Второй прогон с `\set ch 'live_ch'` (живой канал) — `ABORT: guards failed, nothing deleted`, все счётчики до и после совпали.

## 4. Откат

Код: только образ, данных он не меняет.

```bash
ssh prod 'docker tag tg_parser:pre-r14-2026-09-25 tg_parser:latest \
  && cd /home/user/TG_parser \
  && docker compose --profile bot up -d --no-deps --force-recreate tg_parser mcp tg_bot'
```

Чистка: до `COMMIT` — `ROLLBACK`. После — восстановление строк из дампа §3 (`gunzip -c … | psql` в отдельную базу и перенос нужных строк), либо полный `pg_dump`-restore, если откатывать приходится всё.

## 5. Известное и осознанно не закрытое

- **Кэш scope — per-process, 60 с.** Добавление / восстановление / удаление сбрасывает кэш только в своём процессе. В другом процессе (бот ↔ API) удалённый канал живёт в scope до 60 с. MCP scope не кэширует.
- **Dev-режим без аутентификации** (`MCP_AUTH_ENABLED=false` / `API_KEY_REQUIRED=false` / пустой `BOT_ALLOWED_USERS`) по-прежнему даёт синтетического admin с `None`. На проде все три включены; легаси-статические MCP-токены и API-ключи без привязки к пользователю получают список живых каналов.
- **Подписки хранят `channel_ids` как заданы.** `list_digests` / `list_watchlists` показывают в настройках подписки id удалённого канала; контент из него не попадает ни в тело дайджеста, ни в матчи, ни в историю матчей. Вычищать id из настроек значило бы молча менять подписку пользователя — решение владельца, на проде таких подписок 0.
- **CLI `topic versions` / `diff` / `resummarize`** читают тему по явному id и удалённость не проверяют — операторский инструмент на хосте, действует только на названную тему. CLI `search` / `ask` scope получают (без `--user` — все живые каналы). Через MCP и бота `force_resummarize` удалённой темы отказывает и admin.
- **Тик, шедший в момент удаления.** Матч, найденный в тике, который собрал канал до удаления, отправляется в том же тике напрямую, минуя отфильтрованную выборку pending. Окно — один тик, контент собран, пока канал был живым; та же гонка, что у ingestion ниже.
- **Карточки с несколькими источниками** остаются видимыми, пока жив хотя бы один источник, и детали темы показывают `sources` / anchors / items целиком, включая удалённый источник. Пайплайн таких карточек не создаёт (единственное место создания — `topicization.py`, `sources=[channel_id]`), на проде их 0; если появятся — детали нужно будет прореживать.
- **`upsert_source` в ingestion** сбрасывает `deleted_at` в NULL. Гонка «тик собирает канал в момент удаления» реанимирует его — было и до R14 (BUG-002 M3), не менялось.

## 6. Ссылки

- [BUG-107](../notes/BUG_LOG.md); DF-5 — [`FUTURE_FEATURES.md`](../notes/FUTURE_FEATURES.md).
- [`START_PROMPT_R14_SOFT_DELETE_INVISIBLE_2026-09-25.md`](../notes/archive/START_PROMPT_R14_SOFT_DELETE_INVISIBLE_2026-09-25.md) — scope сессии.
- [`PLAN_POST_FORCED_DP_2026-09-23.md`](../notes/PLAN_POST_FORCED_DP_2026-09-23.md) §1, §3 — замер и решение о семантике.
- [`BUG108A_R13_DEPLOY.md`](BUG108A_R13_DEPLOY.md) §3 — сверка расхода Phase 2.
