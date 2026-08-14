# Runbook — BUG-097 (b): дубликат перестаёт оплачиваться каждым тиком (деплой + watch)

**Создан:** 2026-08-14 (сессия R11). **Статус: к исполнению** по GO владельца.

**Что деплоим:** запись факта post-LLM отбраковки ([BUG-097](../notes/BUG_LOG.md), половина **b**). Отброшенный дубликат раньше не сохранялся, `list_unprocessed_by_channel` снова его предлагал, и каждый тик платил за тот же summary бессрочно (≈99 % токенов стадии processing, 27 документов по кругу). Теперь отбраковка пишется в `processing_dedup_drops` и анти-джойнится в окне выборки. Форма — маркер, не строка-документ: иначе `new_doc_refs` утащил бы дубликат в топикизацию Phase 2 и во второй watchlist-алерт.

**Не docs-only.** Меняется processing-пайплайн и SQL выборки. **Есть миграция** (`e7f8a9b0c1d2` на ветке `processing`) — в отличие от R10. `.env` не тронут, новых ключей нет. `tg_parser_mcp` и `tg_bot` не пересоздаём: правка их не касается, а пересоздание MCP стёрло бы окно логов для R1 (BUG-099), как и в R10.

---

## 0. Перед деплоем

| Проверка | Команда / ожидание | Факт |
|---|---|---|
| Прод и `origin/main` сходятся после мержа | `ssh prod 'cd /home/user/TG_parser && git rev-parse --short HEAD'` — сверить с `git rev-parse --short origin/main` | |
| Processing head на проде = `a4b5c6d7e8f9` | `ssh prod 'cd /home/user/TG_parser && docker compose exec tg_parser tg-parser db current --db processing'` | |
| Точка отката образа | `ssh prod 'docker tag tg_parser:latest tg_parser:pre-r11-2026-08-14'` — записать id | |
| Backup | `ssh prod 'cd /home/user/TG_parser && docker compose exec postgres pg_dump -U tg_parser_user tg_parser \| gzip > data/backups/postgres_pre_r11_$(date -u +%Y%m%d_%H%M%S).sql.gz'` — записать путь и размер | |
| База `deduplicated_count` | запрос §4.2 **до** пересоздания: плато 27 на стабильных каналах | |
| База логов | `dedup_db_duplicate`: 27 уникальных, `once-only` = 0 | |

---

## 1. Деплой

Процедура — [`PRODUCTION_DEPLOYMENT.md`](../../PRODUCTION_DEPLOYMENT.md) § Updating. Пересоздавать контейнер, **не** `restart` (BUG-078); `up -d` без изменения rendered spec не пересоздаёт, поэтому `--force-recreate` обязателен (BUG-090). Миграция — **новым** образом через `compose run`, не `exec`: running-контейнер до re-create держит старый код без файла миграции (F5C).

Порядок обязателен: если сначала пересоздать, новый код начнёт анти-джойнить `processing_dedup_drops`, которой ещё нет, и тик упадёт.

```bash
ssh prod 'cd /home/user/TG_parser && git pull --ff-only'
ssh prod 'cd /home/user/TG_parser && docker compose build tg_parser'
ssh prod 'cd /home/user/TG_parser && docker compose run --rm --no-deps tg_parser db upgrade --db processing'
ssh prod 'cd /home/user/TG_parser && docker compose run --rm --no-deps tg_parser db current --db processing'
# ожидание: e7f8a9b0c1d2 (head)
ssh prod 'cd /home/user/TG_parser && docker compose up -d --no-deps --force-recreate tg_parser'
```

Пересоздаётся **ровно один** контейнер — `tg_parser`. Планировщик и processing-путь живут в нём. `tg_parser_mcp` не трогаем (окно логов для R1). `tg_bot` не трогаем.

---

## 2. Настройки — ничего; миграция — одна таблица

Новых ключей `.env` нет, allow-list `tg_parser` (BUG-092) не задет.

Миграция `e7f8a9b0c1d2` создаёт `processing_dedup_drops` (PK `source_ref`, индекс по `channel_id`, частичный индекс `(channel_id, raw_content_hash)`). Аддитивна: ни одну существующую таблицу не трогает. Backfill не делается — первые 27 маркеров пишет первый тик, и это же сигнал, что фикс работает.

Проверка схемы после наката:

```bash
ssh prod "cd /home/user/TG_parser && docker compose exec postgres psql -U tg_parser_user -d tg_parser -c \"
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'processing_dedup_drops'
ORDER BY ordinal_position;
\""
```

Ожидание: `source_ref`, `channel_id`, `canonical_source_ref`, `raw_content_hash`, `dropped_at`.

---

## 3. Когда ждать проверки

`incremental_pipeline` — **interval** 3600 с, не cron. Пересоздание сдвигает фазу: ждать **старт плюс интервал**, не следующего часа (дефект процедуры R10). Опорная точка — `Scheduler started` в логах.

```bash
ssh prod 'docker logs tg_parser 2>&1 | grep "Background scheduler started"'
ssh prod 'date -u -Iseconds'
```

До первого тика код уже на месте: миграция применена, анти-джойн в образе. Пустая таблица до тика — норма: маркеры появятся, когда пайплайн в первый (и последний) раз отбракует те же 27.

---

## 4. Проверка

Все проверки read-only. Ключ `deduplicated_count` у холостого тика **отсутствует** — читать через `coalesce` / `.get(..., 0)`.

| # | Что | Как | Ожидание |
|---|---|---|---|
| 1 | Первый тик ещё платит, и это сигнал | `source_attempts.details_json.pipeline_stats` после первого тика нового контейнера | `deduplicated_count` = 27 в сумме по каналам (последний раз), `failed_count` = 0 |
| 2 | Маркеры записаны | `SELECT count(*) FROM processing_dedup_drops;` | 27 (или столько, сколько было в тике) |
| 3 | Второй тик — ноль | тот же запрос §4.1 на **следующем** тике | `coalesce(deduplicated_count, 0)` = 0 на стабильном канале; `processed` 0–3 как раньше |
| 4 | Логи: цикл закрыт | `docker logs tg_parser 2>&1 \| grep dedup_db_duplicate` за окно **двух** тиков | unique = 27, `once-only` = 27 (каждый документ ровно один раз). Событие `dedup_drop_recorded` — по одному на ref |
| 5 | Расход упал | токены в `source_attempts` на втором тике | на ≈35 800 меньше, чем плато до фикса |
| 6 | Здоровый путь не задет | канал без дубликатов в том же тике | `processed_count` > 0 если было что обрабатывать; иначе короткий idle-stats |
| 7 | `fail_count` остаётся нулевым | `SELECT channel_id, fail_count, last_error FROM sources WHERE deleted_at IS NULL` | все 0 / NULL — это дало R10, R11 не должен вернуть ложный `degraded` |
| 8 | Нет перекоррекции | `grep -E "processing_failed\|persist_"` | настоящая ошибка не проглатывается; если в окне 0 вхождений — как в R10, закрыто тестом, не продом |

Запросы (обязательно `coalesce`):

```sql
SELECT
  date_trunc('hour', attempt_at) AS hour,
  coalesce(sum((details_json::jsonb #>> '{pipeline_stats,process,deduplicated_count}')::int), 0) AS dedup,
  coalesce(sum((details_json::jsonb #>> '{pipeline_stats,process,processed_count}')::int), 0) AS processed,
  coalesce(sum((details_json::jsonb #>> '{pipeline_stats,process,failed_count}')::int), 0) AS failed,
  coalesce(sum((details_json::jsonb #>> '{pipeline_stats,process,tokens_total}')::int), 0) AS tokens
FROM source_attempts
WHERE attempt_at >= now() - interval '6 hours'
GROUP BY 1
ORDER BY 1;
```

Повторность в логах:

```bash
ssh prod "docker logs tg_parser 2>&1 | grep dedup_db_duplicate > /tmp/dd.jsonl; python3 -c \"
import json,collections
refs=collections.Counter(); ts=[]
for l in open('/tmp/dd.jsonl'):
    d=json.loads(l); refs[d['source_ref']]+=1; ts.append(d.get('timestamp',''))
print('window', min(ts) if ts else None, '->', max(ts) if ts else None)
print('unique', len(refs), 'events', sum(refs.values()))
print('once-only', sum(1 for v in refs.values() if v==1))
\""
```

⚠️ Метрика `tg_dedup_duplicates_detected_total` обнуляется при пересоздании; мгновенный запрос сразу после старта — пустой вектор. Сравнивать `increase()` внутри одного времени жизни процесса.

---

## 5. Что этот деплой НЕ закрывает

Перенос pre-LLM проверки и бэкфилл `raw_content_hash` на 44 тысячах legacy-строк — вердикт R11 «не делаем»: приток новых дубликатов нулевой, экономия была бы один вызов на документ. Триггер пересмотра: `deduplicated_count` устойчиво > 0 на стабильном канале **после** того, как плато 27 ушло. Качество выдачи поиска по существующим зеркалам — отдельный вопрос с июля, маркеры в поиск не попадают.

---

## 6. Откат

Код откатывается образом, схема — отдельно и только если нужна. Порядок: сначала старый образ (новый код без таблицы упадёт на анти-джойне), потом опционально downgrade.

```bash
ssh prod 'docker tag tg_parser:pre-r11-2026-08-14 tg_parser:latest \
  && cd /home/user/TG_parser && docker compose up -d --no-deps --force-recreate tg_parser'
# только если таблицу тоже надо убрать:
ssh prod 'cd /home/user/TG_parser && docker compose run --rm --no-deps tg_parser db downgrade --db processing --revisions 1 --yes'
```

Оставить таблицу при откате кода безопасно: старый код её не читает. Цена отката кода — возврат бессрочного расхода (те же 27, ≈35 800 токенов/тик). Маркеры, уже записанные, после повторного наката продолжат исключать свои refs (`ON CONFLICT` идемпотентен).

Полное восстановление БД — из backup §0.

---

## 7. Ссылки

- [BUG-097](../notes/BUG_LOG.md) — половины (a)/(b), раскладка 27, форма (C), база для проверки.
- [`START_PROMPT_FIX_BUG097_DEDUP_REBURN_R11_2026-08-13.md`](../notes/START_PROMPT_FIX_BUG097_DEDUP_REBURN_R11_2026-08-13.md)
- [`BUG097_R10_DEPLOY_AND_WATCH.md`](BUG097_R10_DEPLOY_AND_WATCH.md) — предыдущий деплой; оттуда взяты `--force-recreate`, фаза interval-тика и ловушка пустой метрики.
- [`PRODUCTION_DEPLOYMENT.md`](../../PRODUCTION_DEPLOYMENT.md) § Updating — `compose run` для миграции, не `exec`.
