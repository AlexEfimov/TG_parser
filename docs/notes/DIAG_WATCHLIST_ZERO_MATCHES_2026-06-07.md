# DIAG — диагностика нулевых матчей watchlists (F11), 2026-06-07

> **Назначение.** Воспроизводимый READ-ONLY промпт/ранбук для диагностики, почему
> все активные watchlists (F11 «topic watchlist» / «interest») дают **ноль матчей**.
> Все плейсхолдеры/неверные значения исходного черновика заменены на **проверенные**
> параметры и **реальные** имена таблиц/колонок/функций из кода.

---

## 0. Жёсткие ограничения (CRITICAL — соблюдать дословно)

- **READ-ONLY везде.** Никаких изменений в репозитории (кроме этого файла) и на VPS.
- На проде: **только `SELECT`** (никаких `INSERT/UPDATE/DELETE/DDL`). Не перезапускать и не
  пересоздавать сервисы. Не менять пороги/конфиг/watchlists.
- Читать код, БД (`SELECT`), логи, `docker-compose.yml`, **имена** env (без значений) — разрешено.
- **Никогда не печатать значения секретов.** Для env — только факт наличия (`<set>` / отсутствует).

---

## 1. Контекст и проверенные параметры (VERIFIED)

Проект `tg-parser` — пайплайн парсинга и топикизации Telegram-каналов. Подсистема **F11**:
после каждого инкрементального тика планировщика новые `ProcessedDocument` отслеживаемых
каналов скорятся против активных интересов гибридным методом (keyword + semantic), и
совпадения с `combined_score >= threshold` пишутся в таблицу матчей и пушатся в Telegram.

### Доступ (VERIFIED — исходный черновик содержал НЕВЕРНЫЙ хост `redboxtgbot`)
- SSH: `ssh -p 2296 user@212.72.189.15` (алиасы `prod` / `tg-parser-prod` в `~/.ssh/config`).
- Канонический деплой-каталог на VPS: `~/TG_parser` (`/home/user/TG_parser`).
- Контейнеры: `tg_parser_postgres` (pgvector pg17), `tg_parser` (**API + планировщик —
  здесь физически крутится пайплайн и матчер watchlists**), `tg_parser_mcp`, `tg_parser_bot`.
- БД: `tg_parser`, пользователь `tg_parser_user`. Паттерн psql:
  ```bash
  ssh -p 2296 user@212.72.189.15 "docker exec tg_parser_postgres psql -U tg_parser_user -d tg_parser -c \"<SQL>\""
  ```

### Эмбеддер (VERIFIED — исходный черновик ошибочно предполагал multilingual-e5 / BGE-M3)
- `EMBEDDING_PROVIDER=openai`, `EMBEDDING_MODEL=text-embedding-3-small`, **1536-dim**
  (defaults в `Settings`; в `docker-compose.yml` явно прописаны у сервисов `mcp`/`tg_bot`,
  у `tg_parser` берутся из defaults + bind-mount `./.env`).
- `OPENAI_API_KEY` обязателен; без него `make_watchlist_service` тихо падает в keyword-only
  режим (`embedding_client=None`).

---

## 2. Реальная архитектура матчера (из кода — подставлять в запросы ЭТИ имена)

**Скоринг:** `tg_parser/services/watchlist_service.py`
- `compute_watch_score(interest, doc, doc_embedding) -> WatchScore`.
- Формула (веса: keyword **0.4**, semantic **0.6**, сумма = 1.0, диапазон `[0,1]`):
  - `keyword = |interest_kw_tokens ∩ doc_tokens| / |interest_kw_tokens|`
    (recall-like; токенайзер `[a-zA-Zа-яА-ЯёЁ0-9]{2,}`, lower-case; многословные keywords
    бьются на токены — каждый увеличивает знаменатель; doc-токены = `topics ∪ summary ∪ text_clean`).
  - `semantic = clip(cosine(interest.embedding, doc_embedding), 0, 1)`; `semantic_available`
    требует **оба** эмбеддинга. Если нет — `combined = keyword` (semantic выпадает).
  - `excluded` (любой `exclude_keywords`-токен в doc) → `combined = 0.0`.
  - Иначе `combined = 0.4*keyword + 0.6*semantic`.
- Порог сравнивается как `score.combined >= interest.threshold`.

**Хук планировщика:** `tg_parser/services/scheduler_service.py`
- `_process_source(...)`: `docs_before = list_by_channel(channel_id)` → `run_full_pipeline(... skip_topicize=True)`
  → `docs_after = list_by_channel(channel_id)` → `new_doc_refs = docs_after \ docs_before`.
- `run_watchlist_check_for_channel(channel_id, new_doc_refs)` → `WatchlistService.check_interests`.
- **Матчер скорит ТОЛЬКО `new_doc_refs`** — документы, ставшие НОВЫМИ `processed_documents`
  в рамках ЭТОГО тика. Бэкфилл/исторические доки (созданные до интереса или вне тика)
  **ретроактивно не скорятся**.

**`last_checked_at` относительно скоринга (КЛЮЧЕВО для гипотезы A):** в `check_interests`
`touch_checked()` вызывается:
1. на «тихом» тике (`new_doc_refs` пуст) — для всех активных интересов, затем `return` (ENH-001);
2. когда `docs_by_ref` пуст — аналогично;
3. в основном пути — **ПОСЛЕ** цикла скоринга и `match_repo.upsert_many(...)`.
→ Свежий `last_checked_at` НЕ доказывает, что скоринг шёл по реальным докам: он почти всегда
обновляется «тихими» тиками. Это делает liveness-метку **обманчивой** (но это не падение).

**Персистентность:** матчер пишет в `watch_matches` **только** кандидатов с
`combined >= threshold` (`upsert_many`, `ON CONFLICT (interest_id, source_ref) DO NOTHING`).
Под-пороговые скоры в БД **не сохраняются** — только в Prometheus
(`record_watchlist_match{result=filtered_threshold|filtered_keywords|delivered}` +
гистограмма `tg_watchlist_score`). → Потолок скоров измерять **прямым pgvector-замером**,
а не по `watch_matches`.

### Реальные таблицы/колонки (VERIFIED по repo/коду — НЕ как в черновике)
| Сущность | Таблица | Ключевые колонки |
|---|---|---|
| Интересы | `watch_interests` | `id, user_id, title, keywords text[], exclude_keywords text[], channel_ids text[], threshold, is_active, embedding vector(1536), last_checked_at, last_match_at, created_at` |
| Матчи | `watch_matches` | `id, interest_id, source_ref, channel_id, keyword_score, semantic_score, combined_score, notified, created_at` (UNIQUE `(interest_id, source_ref)`) |
| Processed docs | `processed_documents` | `source_ref, id, channel_id, **processed_at** (НЕ `created_at`!), text_clean, summary, topics_json` |
| Эмбеддинги | `document_embeddings` | `source_ref, embedding vector(1536), model, **created_at (TEXT!)**, entry_type ('message'/'topic'), topic_id, channel_ids text[]` |
| Raw | `raw_messages` | `source_ref, channel_id, **date (TEXT)**, text, inserted_at` |

> ⚠️ Исходный черновик использовал `processed_documents.created_at` и `interests`/`watch_matches`
> с угаданными полями. **Правильно:** `processed_documents.processed_at`; таблица интересов —
> `watch_interests`; эмбеддинги доков — `document_embeddings` (entry_type='message'),
> эмбеддинг интереса — инлайн в `watch_interests.embedding`.

---

## 3. Гипотезы (по убыванию вероятности, уточнены под код)

- **A. Матчер не доходит до скоринга, но `last_checked_at` отмечается.** Проверка: есть ли в
  логах `watchlist.check_interests` с `docs>0`? Если есть `docs>0, candidates=0` — скоринг
  ИДЁТ → A опровергнута. Свежесть `last_checked_at` сама по себе ничего не доказывает (тихие тики).
- **B. Новые доки не доходят до матчера / скорятся не те.** Два под-варианта:
  - B1 (обрыв пайплайна): нет свежих `processed_documents`/эмбеддингов после дат создания интересов.
  - B2 (**ретроактивный пробел**, архитектурный): релевантный корпус залит **бэкфиллом до
    создания интереса** → матчер его никогда не скорил (скорит только `new_doc_refs` пост-фактум).
- **C. Пороги выше реального потолка `combined`.** Замерить `combined = 0.4*kw + 0.6*sem` против
  `threshold`. Под-порог по всем скоренным докам → C.
- **D. Деградация env матчера** (нет `OPENAI_API_KEY`/`DB_*`/embedding-конфига у `tg_parser`) →
  semantic выпадает или матчер не работает.

---

## 4. План диагностики (READ-ONLY)

### Шаг 0. Связь
```bash
ssh -p 2296 user@212.72.189.15 'echo OK && docker ps --format "{{.Names}}\t{{.Status}}"'
```

### Шаг 1. Инвентаризация интересов (ядро)
```sql
SELECT id, title, threshold, is_active,
       array_length(keywords,1) AS n_kw, keywords,
       array_length(exclude_keywords,1) AS n_excl,
       channel_ids, (embedding IS NOT NULL) AS has_emb,
       last_checked_at, last_match_at, created_at
FROM watch_interests ORDER BY created_at;
```
Зафиксировать: активные интересы, их `channel_ids`, пороги, наличие keywords/эмбеддинга,
свежесть `last_checked_at`, `last_match_at`.

### Шаг 2. Свежие processed-доки по каналам интересов (разводит B1 от A/C)
```sql
SELECT channel_id, count(*) AS docs,
       count(*) FILTER (WHERE processed_at > '2026-05-14') AS after_create,
       min(processed_at) AS earliest, max(processed_at) AS latest
FROM processed_documents
WHERE channel_id IN ('profendocrinologist','LongevityClub','AgeManagment','Lab4health',
                     'kdl_ru','genotek','labdiagnostica_logical','mind_rise','foodf4thought')
GROUP BY channel_id ORDER BY latest DESC NULLS LAST;
```

### Шаг 2b. Бэкфилл vs пост-создание (проверка B2 — ретроактивный пробел)
```sql
SELECT channel_id,
       count(*) FILTER (WHERE processed_at < '2026-05-15 16:00:00+00') AS before_create,
       count(*) FILTER (WHERE processed_at >= '2026-05-15 16:00:00+00') AS after_create
FROM processed_documents
WHERE processed_at > '2026-05-14'
  AND channel_id IN ('profendocrinologist','LongevityClub','AgeManagment','Lab4health',
                     'kdl_ru','genotek','labdiagnostica_logical','mind_rise','foodf4thought')
GROUP BY channel_id ORDER BY before_create DESC;
```
> Если релевантный корпус почти весь `before_create` — он залит до интереса и **никогда не
> скорился** (B2). Это объясняет ноль матчей даже при высоком cosine.

### Шаг 3. Эмбеддинги доков (semantic-компонент)
```sql
SELECT entry_type, count(*) FROM document_embeddings GROUP BY entry_type;
SELECT count(*) AS docs, count(de.source_ref) AS with_emb
FROM processed_documents pd
LEFT JOIN document_embeddings de ON de.source_ref=pd.source_ref AND de.entry_type='message'
WHERE pd.processed_at > '2026-05-14'
  AND pd.channel_id IN ('AgeManagment','Lab4health','kdl_ru','genotek','mind_rise');
```

### Шаг 4. Таблица матчей (под-пороги НЕ сохраняются — ожидаемо пусто при C)
```sql
SELECT count(*) FROM watch_matches;
-- если есть строки: SELECT interest_id, count(*), min(combined_score), avg(combined_score), max(combined_score)
--                    FROM watch_matches GROUP BY interest_id;
```

### Шаг 5. Прямой замер потолка `combined` (ключ для C)
**Только cosine-потолок (быстро):**
```sql
SELECT wi.title, wi.threshold, count(de.*) AS docs_scored,
       round(max(1 - (de.embedding <=> wi.embedding))::numeric,4) AS max_cos,
       round(avg(1 - (de.embedding <=> wi.embedding))::numeric,4) AS avg_cos
FROM watch_interests wi
JOIN processed_documents pd ON pd.channel_id = ANY(wi.channel_ids) AND pd.processed_at > '2026-05-14'
JOIN document_embeddings de ON de.source_ref = pd.source_ref AND de.entry_type='message'
WHERE wi.is_active
GROUP BY wi.id, wi.title, wi.threshold ORDER BY max_cos DESC;
```
**Полный `combined` (kw воспроизводится через regexp-токенайзер; substring-оценка kw —
ВЕРХНЯЯ граница, реальный токен-set строже):**
```sql
WITH toks AS (
  SELECT wi.id, lower(t) AS tok FROM watch_interests wi
  CROSS JOIN LATERAL unnest(wi.keywords) k
  CROSS JOIN LATERAL regexp_matches(lower(k),'[a-zа-яё0-9]{2,}','g') m
  CROSS JOIN LATERAL unnest(m) t WHERE wi.is_active
),
nt AS (SELECT id, count(DISTINCT tok) n FROM toks GROUP BY id),
cand AS (
  SELECT wi.id iid, wi.title, wi.threshold,
         (1-(de.embedding <=> wi.embedding))::numeric sem,
         lower(coalesce(pd.text_clean,'')||' '||coalesce(pd.summary,'')) dtext
  FROM watch_interests wi
  JOIN processed_documents pd ON pd.channel_id=ANY(wi.channel_ids) AND pd.processed_at>'2026-05-14'
  JOIN document_embeddings de ON de.source_ref=pd.source_ref AND de.entry_type='message'
  WHERE wi.is_active
),
scored AS (
  SELECT c.iid,c.title,c.threshold,c.sem,
         (SELECT count(DISTINCT t.tok) FROM toks t WHERE t.id=c.iid AND position(t.tok in c.dtext)>0)::numeric/nt.n AS kw
  FROM cand c JOIN nt ON nt.id=c.iid
)
SELECT title, threshold, round(max(0.4*kw+0.6*sem),4) max_combined,
       round(max(kw),3) max_kw, round(max(sem),4) max_sem,
       count(*) FILTER (WHERE 0.4*kw+0.6*sem >= threshold) AS would_match
FROM scored GROUP BY title, threshold ORDER BY max_combined DESC;
```

### Шаг 6. Логи матчера (A vs C; ищем `docs`/`candidates`/`inserted`)
```bash
ssh -p 2296 user@212.72.189.15 "docker logs tg_parser --since 72h 2>&1 | grep -iE 'watchlist|check_interests' | tail -80"
```
- `docs>0, candidates=0` → скоринг идёт, порог не берётся (**C**).
- всегда `docs:0 / skipped=no_new_docs` → матчер не получает новых доков (**B**).
- traceback/`embedding_failed`/`notify_failed` → A/D.

### Шаг 7. Env матчера (гипотеза D; только имена, маскировать)
```bash
ssh -p 2296 user@212.72.189.15 "docker exec tg_parser printenv | grep -iE 'OPENAI_API_KEY|EMBEDDING_PROVIDER|EMBEDDING_MODEL|DB_HOST|DB_NAME|DB_USER|ANTHROPIC_API_KEY' | sed -E 's/=.*/=<set>/' | sort"
```
> `EMBEDDING_PROVIDER/MODEL` могут отсутствовать в `printenv` у `tg_parser` (в отличие от
> `mcp`/`tg_bot`) — это НЕ дефект: код берёт defaults (`openai` / `text-embedding-3-small`).
> Критичен `OPENAI_API_KEY`.

---

## 5. Формат итогового отчёта
1. **Вердикт** — какая гипотеза/комбо (A/B/C/D), один абзац, с конкретными числами.
2. **Доказательная таблица** — гипотеза → проверка → результат → подтверждена/опровергнута.
3. **Ключевые метрики** — processed-доки после дат создания по каналам; доля с эмбеддингом;
   `before_create` vs `after_create`; потолок `max_cos` / `max_combined` vs пороги; число строк
   `watch_matches`; дословные строки логов; где в коде ставится `last_checked_at` относительно скоринга.
4. **Рекомендация** (НЕ применять — только предложить): при C — целевые пороги по замеренному
   потолку; при B2 — механизм ретроактивного скоринга бэкфилла; при A/B1 — точное место в коде;
   при D — недостающая env + сервис.
5. **Открытые вопросы / что не удалось проверить.**

> Любые изменения порогов/конфига — только после явного согласования с пользователем.
