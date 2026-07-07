# START PROMPT — S3: Пре-LLM дедуп и батчевые проверки в pipeline (F-01 High + F-09 Medium; O-2/O-8)

**Дата создания:** 2026-07-07 · **Для:** implementation-сессии в отдельном окне (агент ПРАВИТ код).
**Серия:** remediation-сессии по итогам code-review алгоритмов обработки, сессия **S3** (главная утечка токенов в processing — точный дедуп до LLM-вызова, + батчевые проверки в дедуп-пути).
**Нормативные документы (при расхождении — они первичны):**
- План сессии: [`PLAN_REMEDIATION_SESSIONS_PROCESSING_ALGORITHMS_2026-07-07.md`](PLAN_REMEDIATION_SESSIONS_PROCESSING_ALGORITHMS_2026-07-07.md) §1 «S3», §2 (граф зависимостей), §3 (обоснование порядка).
- Отчёт ревью: [`CODE_REVIEW_PROCESSING_ALGORITHMS_FABLE5_2026-07-07.md`](CODE_REVIEW_PROCESSING_ALGORITHMS_FABLE5_2026-07-07.md) — F-01 (§2 п.2, §3, §4 таблица, A2), F-09 (§4 таблица, §3), O-2/O-8 (§5), §6.4 (дешёвая модель — вне scope).
- Процесс: [`WORKFLOW_REMEDIATION_SESSIONS_AGREEMENTS_2026-07-07.md`](WORKFLOW_REMEDIATION_SESSIONS_AGREEMENTS_2026-07-07.md) **§7 (ключевое: S3 — без изменения контрактов и миграций; content-hash считаем на лету; персистентное raw-hash поле — отдельным согласованным решением, НЕ внутри сессии)**, §2 (git), §3 (деплой — S1–S3 одним блоком), §5 (цикл).
- Baseline: [`S0_BASELINE_PROCESSING_METRICS_2026-07-07.md`](S0_BASELINE_PROCESSING_METRICS_2026-07-07.md) §2 (токены по стадиям — ключ для S3; счётчики дедупа / processing-вызовов).

---

<role>
Ты — senior-инженер проекта tg_parser. Ты закрываешь **главную утечку LLM-бюджета** processing-стадии: сейчас точный дедуп срабатывает **после** оплаченного LLM-вызова, потому что хэш считается по `text_clean` (результат LLM). Каждый точный репост/форвард внутри канала оплачивается полным processing-вызовом (~2–4K токенов), после чего документ выбрасывается. Ты добавляешь **пре-LLM проверку по хэшу сырого текста** (O-2, закрывает F-01), сохраняя существующий post-LLM дедуп (ловит вариации форматирования), и заодно **батчируешь проверки в дедуп-пути** (O-8, закрывает F-09) — один subsystem (дедуп-путь `pipeline.py`), одна сессия. **Без изменения схемы БД, миграций и контрактов.** Провенанс дублей сохраняется. Никакой перекалибровки, никакого попутного рефакторинга соседнего кода.
</role>

<context>
**F-01 (High, стоимость) — дедуп после LLM.** Хэш присваивается по `text_clean` **после** LLM-вызова (`pipeline.py:767–772`, в `_process_single_message`). Проверки `find_by_content_hash` (в пределах канала) стоят в `process_message` (`:473–492`, single-message путь) и в `_filter_duplicates` (`:1051–1100`, батчевый путь) — обе **post-LLM**. Значит точный репост сначала проходит полный платный LLM-вызов и лишь потом распознаётся как дубль и выбрасывается. Для моно-тематического кластера каналов (ADR-0016 зафиксировал 916 cross-channel keyword-overlap на 10 каналов) это регулярно сжигаемый бюджет. **Дедуп per-channel** (все запросы скоупятся `channel_id`) — cross-channel репосты не в scope этой находки.

**F-09 (Medium, скорость) — избыточный `exists()`-цикл.** В `_process_batch_parallel` Phase 1 (`pipeline.py:1201–1204`) на КАЖДОЕ сообщение делается отдельный `await processed_doc_repo.exists(msg.source_ref)`. Но выборка сообщений для тика уже фильтрует `NOT EXISTS (processed_documents)` на уровне SQL (`raw_message_repo.py:292–295`), т.е. в tick-пути этот цикл дублирует уже применённый фильтр — до 300 лишних round-trip'ов БД на тик на канал. Плюс `_filter_duplicates` делает `find_by_content_hash` по одному документу (N запросов на чанк из ~20) — тривиально батчится.

**⚠ Ключевая асимметрия хэшей (читать до написания кода).** Существующая колонка `content_hash` (`processed_documents`, CHAR(64), партиал-индекс `idx_pd_channel_content_hash (channel_id, content_hash) WHERE content_hash IS NOT NULL`) хранит хэш **`text_clean`** (post-LLM). Пре-LLM у тебя есть только `message.text` (сырой). `compute_content_hash(message.text)` даёт хэш в **другом пространстве**, чем сохранённый `content_hash` (кроме случая, когда `text_clean == raw`). Значит `find_by_content_hash(hash(message.text))` **НЕ совпадёт** с существующими документами. Поэтому cross-tick пре-LLM дедуп нельзя реализовать «в лоб» через существующую колонку/индекс — это и есть центральное проектное решение сессии (см. `<design_decision>`), которое **обязано уложиться без миграции** (workflow §7).

**Бюджет/baseline (S0).** Эффект S3 измеряется в токенах processing-стадии (S0 §2) и счётчике дедупа: ожидание — −1 полный processing-вызов на каждый точный дубль (единицы–десятки % processing-бюджета в пересекающемся кластере), −до 300 `exists()`-запросов/тик/канал, чанковый дедуп — 1 запрос вместо ~20. Новая метрика pre-LLM dedup hits — часть deliverable.
</context>

<verified_anchors>
Факты проверены по рабочей копии 2026-07-07 — опирайся на них, а не на план (в плане часть строк приблизительна; ниже — фактические):

| Что | Где (файл:строки) | Факт |
|---|---|---|
| Чистые хэш-функции | `domain/hashing.py:15` (`normalize_for_hash`), `:34` (`compute_content_hash`) | `compute_content_hash(text_clean, *, strip_url_query=True)` → SHA-256(64 hex) от нормализованного текста (параметр назван `text_clean`, но функция чистая — принимает любой текст, включая сырой `message.text`); zero-I/O, годна для пре-LLM пути «как есть» |
| Post-LLM присвоение хэша | `processing/pipeline.py:767–772` (в `_process_single_message`) | `processed.content_hash = compute_content_hash(processed.text_clean, strip_url_query=settings.dedup_strip_url_query)` — хэш по **text_clean**, не по сырому тексту |
| Post-LLM дедуп (single-msg) | `pipeline.py:473–492` (внутри `self._db_lock`), `exists()` на `:442` | `find_by_content_hash(channel_id, content_hash)`; при хите `!= source_ref` → **возврат существующего документа** (`return existing`), метрика `record_dedup_duplicate_detected` |
| Post-LLM дедуп (батч) | `pipeline.py:1051–1100` (`_filter_duplicates`), per-doc `find_by_content_hash` на `:1084`; вызывается из `_persist_chunk` `:1123` | внутрибатчевый (`seen` dict) + БД-дедуп с сохранением порядка; **цель O-8** — заменить per-doc вызов на батчевый |
| Избыточный per-message `exists()` (F-09) | `pipeline.py:1202` (вызов), цикл `:1201–1208` (Phase 1 в `_process_batch_parallel`) | `for msg in messages: if await processed_doc_repo.exists(msg.source_ref): ...` — N запросов; ⚠ тот же цикл считает `cooldown_skipped_refs` → удалять только `exists()`-вызов, не цикл; `_batch_attempted = len(to_process)` на `:1227` |
| Выборка уже фильтрует NOT EXISTS | `raw_message_repo.py:292–295` (tick-выборка `list_unprocessed*`), `:270` (cooldown NOT EXISTS) | `WHERE r.channel_id=… AND NOT EXISTS (SELECT 1 FROM processed_documents p WHERE p.source_ref=r.source_ref)` — в tick-пути сообщения уже без обработанных |
| `find_by_content_hash` (единичный) | порт `storage/ports.py:593`, impl `processed_document_repo.py:354–378` | `(channel_id, content_hash) -> ProcessedDocument | None`; использует партиал-индекс; **плюрального `find_by_content_hashes` НЕТ — новый метод** |
| Индекс/колонка | `storage/sqlalchemy/_metadata.py:571` (`content_hash CHAR(64)`), `:577–580` (`idx_pd_channel_content_hash … WHERE content_hash IS NOT NULL`), `:564` (`metadata_json Text()`) | индекс есть ТОЛЬКО по `content_hash` (=text_clean-хэш). ⚠ `metadata_json` — **TEXT-колонка с JSON-строкой** (пишется `stable_json_dumps`, читается `stable_json_loads` — `processed_document_repo.py:84,137,395`), **НЕ JSONB** и не индексирована → фильтр по ключу требует каста: `metadata_json::jsonb ->> 'raw_content_hash'` (PG) / `json_extract(metadata_json,'$.raw_content_hash')` (SQLite), и это **непроиндексированный full-scan по каналу** |
| Метрика дедупа | `api/metrics.py:54` (`DEDUP_DUPLICATES_DETECTED` Counter), `:712` (`record_dedup_duplicate_detected(*, channel_id)`) | существующий post-LLM счётчик; для pre-LLM — **отдельный** счётчик/метка, чтобы не смешивать |
| Флаги | `settings.dedup_enabled`, `settings.dedup_strip_url_query` | пре-LLM путь должен уважать `dedup_enabled` и `force` (при `force` дедуп пропускается — как в существующих путях) |
| `force`-обход | `pipeline.py:440` (`if not force:` exists-гейт), `:474` (`… and not force`), `:1122` (`… and not force`) | при `force=True` весь дедуп отключён — новый пре-LLM путь обязан вести себя так же |
</verified_anchors>

<design_decision>
**Единственное открытое решение сессии — как сделать cross-tick пре-LLM дедуп БЕЗ миграции** (workflow §7: «content-hash считаем на лету; персистентное raw-hash поле — отдельным согласованным решением, не внутри сессии»).

**⚠ Провенанс — точная формулировка (в плане неточность, не копируй её дословно).** План §S3 предписывает «копировать поля существующего документа с новым `source_ref` (как post-LLM ветка `pipeline.py:479+`)», НО фактически post-LLM ветка (`pipeline.py:479–492`) делает `return existing` и **новую строку НЕ пишет** (repost остаётся без своей `processed_documents`-строки). Это два РАЗНЫХ поведения. Решение S3 (следуя намерению плана — чтобы repost был прослеживаем и попадал в `new_doc_refs`/топикизацию): **создать НОВУЮ persisted-строку**, зеркалящую оригинал, но со своим `source_ref`. Поля на уровне записи:
- **новые (для repost'а):** `source_ref = message.source_ref`; `id = make_processed_document_id(message.source_ref)` (контракт `id = "doc:"+source_ref` — НЕ копировать `id` оригинала, иначе дубль PK); `source_message_id = message.id`; `processed_at = now`; `metadata["raw_content_hash"]` — по выбранному пути;
- **копируемые из оригинала:** `text_clean`, `summary`, `topics`, `entities`, `language`, `content_hash` (=text_clean-хэш оригинала), прочий `metadata` (+ провенанс-ссылка на оригинал, напр. `metadata["dedup_of"] = existing.source_ref`).

Выбери один путь дедупа и зафиксируй обоснование в PR. Порядок предпочтений:

1. **Cross-tick raw-hash в существующей `metadata_json` (без миграции) — основной путь, если укладывается.** При создании документа класть `metadata["raw_content_hash"] = compute_content_hash(message.text, strip_url_query=settings.dedup_strip_url_query)`; добавить батчевый репо-метод (напр. `find_by_raw_content_hashes(channel_id, raw_hashes) -> dict[str, ProcessedDocument]`). ⚠ `metadata_json` — **TEXT-колонка с JSON-строкой, не JSONB**, поэтому фильтр обязан кастовать: **PG** `WHERE channel_id=… AND metadata_json::jsonb ->> 'raw_content_hash' = ANY(:hashes)`, **SQLite** `json_extract(metadata_json,'$.raw_content_hash')`. Пре-LLM: посчитать raw-хэши батча кандидатов, одним запросом найти хиты, для хитов — создать новую строку по провенанс-спеке выше (LLM-вызов пропускается), инкремент новой метрики. **Уважать `dedup_enabled`/`force`.**
   - ⚠ Лукап **не индексирован** — per-channel full-scan по TEXT с рантайм-кастом в jsonb. Если на реальных объёмах производительность неприемлема и нужен **индекс** (= миграция) — **СТОП и эскалация** (out of scope, workflow §7); НЕ добавлять индекс/колонку внутри S3. Оцени стоимость до выбора этого пути.
   - Контракт-проверка выполнена: `docs/contracts/processed_document.schema.json` — `metadata` = `type:object, additionalProperties:true` (+ top-level `additionalProperties:true`), так что добавление `raw_content_hash`/`dedup_of` **контракт не нарушает** (миграции всё равно нет). Перепроверь, если правишь другой contract-файл.

2. **Within-tick пре-LLM дедуп (чистый on-the-fly, нулевая персистентность) — безопасный baseline.** Дедуплицировать кандидатов батча по raw-хэшу ДО LLM: первое вхождение идёт в LLM, остальные — новая строка по провенанс-спеке (копия первого). Cross-tick репосты по-прежнему ловятся post-LLM (без изменений). Ловит меньше (только внутри тика), зато нулевой риск по схеме/производительности **и работает в default-режиме (SQLite)**. Бери как минимум это; путь 1 — расширение сверху, если непроиндексированный скан приемлем.

3. **Эскалация — персистентная индексированная raw-hash колонка.** Только как отдельное согласованное решение с миграцией — **вне S3**. Если без неё цель не достигается, останови сессию и вынеси решение owner'у.

**Общее для всех путей:** существующий post-LLM дедуп по `text_clean` (`:473–492`, `_filter_duplicates`) остаётся — он ловит вариации форматирования, которые raw-hash пропускает.
</design_decision>

<scope>
**O-2 (закрывает F-01, High) — `processing/pipeline.py` (+ репо по выбранному пути):**
1. Пре-LLM дедуп по хэшу **сырого** текста (`compute_content_hash(message.text)`), реализация по `<design_decision>`. Оба пути обработки: `process_message` (single) и `_process_batch_parallel` (батч, Phase 1 — до параллельных LLM-вызовов).
2. При хите — **создать новую persisted-строку по провенанс-спеке `<design_decision>`** (свой `source_ref`/`id`/`processed_at`, скопированные `text_clean`/`summary`/`topics`/`entities`/`language`/`content_hash`, провенанс-ссылка), LLM-вызов не выполнять; инкремент **новой** pre-LLM dedup метрики (отдельной от post-LLM `record_dedup_duplicate_detected`).
3. Post-LLM дедуп сохранить без изменений (он остаётся `return existing`, без записи новой строки — не путать с провенансом пре-LLM пути).
4. Уважать `settings.dedup_enabled` и `force` (при `force` — пропуск дедупа, как в существующих путях).
5. **`_batch_attempted`-учёт (`pipeline.py:1227`, `= len(to_process)`) кормит B1-degraded в scheduler.** Пре-LLM хиты не идут в LLM — определи и зафиксируй в PR, считаются ли они `skipped` (рекомендуется — как уже-обработанные) и **исключаются из `to_process`/`_batch_attempted`**, чтобы degraded-ratio не поехал (fail_ratio считается по реально попробованным). Не менять смысл `attempted` = «отправлено в LLM».

**O-8 (закрывает F-09 + батчинг) — `processing/pipeline.py` + `processed_document_repo.py`:**
6. `_filter_duplicates` (`:1051–1100`): заменить per-doc `find_by_content_hash` на один батчевый `find_by_content_hashes(channel_id, [hashes]) -> dict[str, ProcessedDocument]` (новый репо-метод; порт + impl). Метод — обычное равенство по индексированной `content_hash` (`IN`/`= ANY`), **портируется на SQLite** (не PG-only). Сохранить порядок и семантику (within-batch `seen` + БД-дедуп).
7. Избыточный per-message `exists()` (`pipeline.py:1202`): **заменить именно вызов `exists()`** для **tick-пути** (выборка уже фильтрует `NOT EXISTS`, `raw_message_repo.py:292–295`), **сам цикл `for msg in messages` (`:1201–1208`) сохранить** — он же вычисляет `cooldown_skipped_refs`. Для не-tick вызовов `_process_batch_parallel` (сообщения не пред-фильтрованы) корректность сохранить — напр. один батчевый `get_by_source_refs` вместо N единичных `exists()`, или условный скип при гарантированном пред-фильтре. НЕ ломать `skipped`/`existing_refs`-учёт.
</scope>

<out_of_scope>
- **Миграции Alembic и изменения `docs/contracts/**` (JSON Schema)** — запрещены (workflow §7). Схему БД не трогаем; персистентная индексированная raw-hash колонка — отдельное согласованное решение вне S3 (эскалация, см. `<design_decision>` п.3).
- **Дешёвая модель для коротких сообщений (§6.4)** — «делать позже», отдельным треком после S3 по данным метрики дедупа. Не трогать.
- **Near-dup / «почти-дубли» (ADR-0016, Phase 1)** — свой gate; near-dup hook (`test_near_duplicate_observe.py`) не задевать.
- **Cross-channel дедуп** — вне F-01 (дедуп остаётся per-channel; не расширять скоуп `channel_id`).
- **Перекалибровка нормализации хэша** (`normalize_for_hash`) — использовать «как есть».
- Любые файлы за пределами: `processing/pipeline.py`, `storage/sqlalchemy/processed_document_repo.py`, `storage/ports.py`, `api/metrics.py` (только новая метрика), тесты (+ репо по выбранному пути). Никакого попутного рефакторинга.
</out_of_scope>

<acceptance_criteria>
Сессия принята, когда ВСЁ нижеследующее доказано тестами/замерами:
1. **Точный репост не доходит до LLM:** на mock-LLM клиенте точный репост (тот же канал, идентичный сырой текст ранее обработанного документа) обрабатывается **без нового LLM-вызова** (assert на call-count LLM-клиента). Документ-дубль **прослеживаем**: **новая persisted-строка** со своим `source_ref`/`id`, скопированными полями оригинала и провенанс-ссылкой (`<design_decision>` спека) — не `return existing` и не молчаливый скип. ⚠ Если выбран путь 1 (cross-tick через `metadata_json`), этот cross-tick кейс проверяется **только под `TEST_POSTGRES=1`** (JSON-каст PG-специфичен); в default-режиме доказывается within-tick кейс (путь 2).
2. **Пре-LLM метрика:** новый счётчик pre-LLM dedup hits инкрементируется на хит и **не смешан** с post-LLM `DEDUP_DUPLICATES_DETECTED`.
3. **Post-LLM дедуп не сломан:** документ с идентичным `text_clean`, но разным сырым текстом (вариация форматирования) по-прежнему ловится post-LLM (характеризационный тест: raw различается → пре-LLM miss → LLM отрабатывает → post-LLM hit).
4. **Идемпотентность:** повторный прогон того же тика не порождает ни нового LLM-вызова, ни дубль-строк.
5. **O-8 батчинг:** `_filter_duplicates` делает **один** батчевый `find_by_content_hashes` на чанк (assert на число вызовов/запросов, не N); избыточный per-message `exists()` в tick-пути устранён (assert, что `exists` не зовётся N раз в tick-пути), при этом не-tick путь остаётся корректным и `_batch_attempted`/degraded-учёт не изменился.
6. **`dedup_enabled=false` / `force=True`:** пре-LLM путь полностью пропускается (поведение как до S3).
7. **Без миграций/контрактов:** нет новых Alembic-ревизий, `docs/contracts/**` не изменён; если решение потребовало индекс/колонку — сессия остановлена и эскалирована (не закрыта силой).
8. Все существующие тесты зелёные в обоих режимах (см. `<test_strategy>`).
</acceptance_criteria>

<test_strategy>
Workflow §5.4: для находки-бага — сначала **падающий тест (red → green)**; для дедуп-эквивалентности — характеризационные тесты идентичности до/после там, где поведение не должно меняться (post-LLM путь).

1. **Новые тесты:**
   - **O-2 пре-LLM:** точный репост → mock-LLM `generate` НЕ вызван (call-count == 0 для дубля, == 1 для оригинала); дубль-документ прослеживаем (новый `source_ref`, скопированные поля, провенанс к оригиналу); пре-LLM метрика инкрементнулась.
   - **Разграничение raw vs clean:** сырой текст различается, `text_clean` совпадает → пре-LLM miss + post-LLM hit (доказывает, что оба слоя работают и не конфликтуют).
   - **Идемпотентность:** второй тик по тем же сообщениям — 0 новых LLM-вызовов, 0 новых строк.
   - **`dedup_enabled=false` и `force=True`:** пре-LLM путь не активен.
   - **O-8 батч `find_by_content_hashes`:** пустой список, частичные совпадения, cross-chunk дубль (ловится через уже персистированный ранний чанк); assert на батчевость (1 вызов вместо N).
   - **F-09:** в tick-пути `exists()` не зовётся per-message (spy/patch), поведение фильтрации сохранено.
2. **Существующие (план §S3) — прогнать все, дополнить fakes при изменении арности репо:**
   - `tests/test_processing_pipeline.py` (основной дедуп/pipeline), `tests/test_f5a_phase3_dedup.py` (**канонический post-LLM content-hash дедуп — не сломать**), `tests/test_e2e_pipeline.py`, `tests/test_storage_integration.py` (репо-методы), `tests/test_near_duplicate_observe.py` (near-dup hook НЕ задет), `tests/test_metrics_instrumentation.py` (метрики).
3. **Режимы (`tests/README.md`):** *default* (`pytest -q`) обязателен — покрывает O-8 `find_by_content_hashes` (обычное равенство по `content_hash`, портируется на SQLite) и within-tick O-2 (путь 2). ***PR standard* (`TEST_POSTGRES=1`) обязателен** — **только** `find_by_raw_content_hashes` (путь 1, JSON-каст `metadata_json::jsonb->>`) и cross-tick O-2 (AC#1) PG-специфичны. Перед merge — ***max local*** (`TEST_POSTGRES=1 TEST_TESTCONTAINERS=1`) для E2E-пути.
4. **Метрики/ручное:**
   - Счётчик pre-LLM dedup hits в Prometheus (или assert на in-process метрику, если live-стек недоступен — зафиксировать команду/ожидание в PR).
   - На dev-прогоне канала с известными форвардами/репостами — снижение processing-вызовов в логах rate-limiter'а и/или падение input-токенов processing-стадии (S0 §2 baseline) до/после; зафиксировать в PR.
</test_strategy>

<workflow>
Нормативно — workflow §2/§3/§5:
1. Ветка **`fix/S3-pre-llm-dedup`** от `main`.
2. Red-тесты (пре-LLM дедуп, F-09) → реализация по выбранному пути `<design_decision>` → характеризационные тесты post-LLM (эквивалентность) → оба режима тестов зелёные, E2E max-local перед merge.
3. Обновить [`BUG_LOG.md`](BUG_LOG.md): F-01 (High), F-09 (Medium) — addressed этой сессией (ссылка на отчёт ревью); зафиксировать выбранный путь дедупа и решение по провенансу; отметить, что §6.4 (дешёвая модель) остаётся отдельным треком.
4. Self-review тестов и кода — отдельными агентами со свежим контекстом; **bugbot по изменениям ветки — обязательный гейт**.
5. Зелёные тесты + зелёный bugbot → commit + push → **PR** → merge в `main`.
6. **Деплой — НЕ соло:** S3 выкатывается в составе безопасного блока **S1–S3** (workflow §3). В этой сессии деплой не выполняется.
7. **Зависимости (план §2):** S1/S2/S3 взаимно независимы (разные файлы) — порядок свободный; S3 не блокирует и не блокируется S1/S2.
8. **Эскалация:** если реализация упирается в необходимость миграции/контракта (индексированный raw-hash) — **остановиться и вынести решение owner'у**, не добавлять миграцию внутри S3 (workflow §7).
9. `git commit` — только в рамках этого цикла, не раньше зелёного статуса (AGENTS.md: без явного цикла коммиты запрещены; здесь цикл согласован workflow-документом).
</workflow>

<recap>
| Находка | Что делаем | Приёмка |
|---|---|---|
| F-01 (High) / O-2 | Пре-LLM дедуп по хэшу **сырого** текста (путь по `<design_decision>`, без миграции); при хите — **новая persisted-строка** со своим `source_ref`/`id` + скопированные поля оригинала + провенанс-ссылка (не `return existing`), LLM не звать; отдельная pre-LLM метрика; post-LLM дедуп сохранён | точный репост → 0 LLM-вызовов (тест на call-count); дубль прослеживаем (новая строка); пре-LLM метрика растёт; падение processing-токенов/вызовов на dev-прогоне |
| F-09 (Medium) / O-8 | `_filter_duplicates` → один батчевый `find_by_content_hashes` (новый репо-метод); избыточный per-message `exists()` в tick-пути устранён (выборка уже NOT EXISTS-фильтрует), не-tick путь корректен | 1 запрос вместо N (тест на батчевость); `exists()` не зовётся per-message в tick-пути; degraded/attempted-учёт не изменился |
| Инвариант | Без миграций и `docs/contracts/**`; `dedup_enabled`/`force` уважаются; near-dup/cross-channel/§6.4 не задеты | нет новых Alembic-ревизий; при необходимости схемы — эскалация, не силовое закрытие |
</recap>

---

*Строки кода — по рабочей копии 2026-07-07. При смещении нумерации ориентируйся на имена символов: `compute_content_hash` / `normalize_for_hash` (hashing), `_process_single_message` / `process_message` / `_process_batch_parallel` / `_filter_duplicates` / `_persist_chunk` (pipeline), `find_by_content_hash` / `find_by_content_hashes` / `exists` (repo), `record_dedup_duplicate_detected` (metrics).*
