# START PROMPT — S2: Батч perf quick-wins (F-03 High + F-07/F-08 Medium; O-3/O-6/O-7)

**Дата создания:** 2026-07-07 · **Для:** implementation-сессии в отдельном окне (агент ПРАВИТ код).
**Серия:** remediation-сессии по итогам code-review алгоритмов обработки, сессия **S2** (второй заход — батч низкорисковых perf-фиксов, поведенческая эквивалентность).
**Нормативные документы (при расхождении — они первичны):**
- План сессии: [`PLAN_REMEDIATION_SESSIONS_PROCESSING_ALGORITHMS_2026-07-07.md`](PLAN_REMEDIATION_SESSIONS_PROCESSING_ALGORITHMS_2026-07-07.md) §1 «S2», §2 (граф зависимостей), §3 (обоснование порядка).
- Отчёт ревью: [`CODE_REVIEW_PROCESSING_ALGORITHMS_FABLE5_2026-07-07.md`](CODE_REVIEW_PROCESSING_ALGORITHMS_FABLE5_2026-07-07.md) — F-03 (§4, п.3), F-07/F-06 (§4, п.5 + §5.2), F-08 (§4), O-3/O-6/O-7 (§5), сводная приоритизация.
- Процесс: [`WORKFLOW_REMEDIATION_SESSIONS_AGREEMENTS_2026-07-07.md`](WORKFLOW_REMEDIATION_SESSIONS_AGREEMENTS_2026-07-07.md) §2 (git), §3 (деплой — S1–S3 одним блоком), §5 (цикл), §7 (scope-ограничения).
- Baseline: [`S0_BASELINE_PROCESSING_METRICS_2026-07-07.md`](S0_BASELINE_PROCESSING_METRICS_2026-07-07.md) §2 обл.2 (длительность тика — **ключевая метрика S2**) и обл.5 (watchlist-скоры, cache-gap).

---

<role>
Ты — senior-инженер проекта tg_parser. Ты закрываешь **три независимых perf-фикса** одним батчем: горячий путь тика планировщика (единственный **High** — F-03), CPU-стоимость watchlist-скоринга (F-08) и корректность ключа LLM-кэша после runtime-переключения модели (F-07, частично F-06). Все три — «делать сейчас» с **поведенческой эквивалентностью по результату**: тик считает те же `new_doc_refs`, watchlist выдаёт **байт-в-байт те же** скоры, кэш перестаёт отдавать ответы чужой модели. Никакой перекалибровки порогов, никаких изменений схемы/контрактов, никакого попутного рефакторинга.
</role>

<context>
**F-03 (High, скорость) — тик планировщика.** В `tg_parser/services/scheduler_service.py` per-source обработка тика дважды грузит **весь корпус канала целиком** (`list_by_channel` — SELECT со всеми полями, включая `text_clean`) в `docs_before` (строка **296**) и `docs_after` (строка **378**), хотя далее нужны только `source_ref`'ы. Вычисление `new_doc_refs` (строки **496–500**) пересобирает множество `{dd.source_ref for dd in docs_before}` **внутри list-comprehension на каждый элемент** `docs_after` — это O(N²) по числу документов канала. На канале 10K+ документов это доминирует время тика и гонит мегабайты трафика БД на каждый тик каждого канала.

**F-08 (Medium, скорость) — watchlist CPU.** В `tg_parser/services/watchlist_service.py` `compute_watch_score` (строка **528**) внутри себя вызывает `_build_doc_tokens(doc)` (строка **554**) — pymorphy3-лемматизация текста документа. В `check_interests` (строка **1142**) горячий цикл — **вложенный**: `for interest in active:` (внешний, строка 1228) × `for ref, doc in docs_by_ref.items():` (внутренний, строка 1236) → `compute_watch_score(...)` (строка **1238**). Значит один и тот же документ **токенизируется заново для каждого интереса** — O(I×D) лемматизаций вместо O(D). `lru_cache` на `normalize_token` смягчает повторные токены, но на длинных документах и десятках интересов это заметный CPU в тике. На prod активно **16 интересов** (S0 обл.5, `tg_watchlist_active_interests`).

**F-07 (Medium, качество; частично F-06) — ключ кэша.** В `tg_parser/processing/llm/response_cache.py` `_make_key` (строки **42–50**) собирает ключ из `system_prompt|prompt|temperature|max_tokens` — **без provider/model**. Кэш — глобальный синглтон (`get_llm_cache`, `instrumented.py:28`), разделяемый всеми клиентами. После runtime-переключения модели (`set_llm_config`) один и тот же промпт в течение TTL (5 минут) вернёт ответ **прежней** модели. `provider`/`model` доступны в `InstrumentedLLMClient` (`instrumented.py:24–27`), где кэш и используется — только в `generate()` (get на строке 42, put на строке 56).

**Бюджеты/baseline (S0).** Длительность тика: последние 14 тиков **медиана ≈207 s** (min 42.67, max 596.62; лог `Incremental pipeline completed ... duration=X.XXs`, `scheduler_service.py:907–918`). Отдельной Prometheus-гистограммы длительности тика **нет** — меряем по логам. Отдельной метрики CPU-времени watchlist-скоринга **нет и не планируется** — эффект O-7 виден только в общей длительности тика. Cache hit/miss **не экспортируется** наружу (только in-process dict) — live-baseline по кэшу не существует (осознанный gap), O-6 верифицируется на тест-уровне.
</context>

<verified_anchors>
Факты проверены по рабочей копии 2026-07-07 — опирайся на них, а не на план (в плане часть строк указана приблизительно; ниже — фактические):

| Что | Где (файл:строки) | Факт |
|---|---|---|
| Полная загрузка корпуса ×2 | `services/scheduler_service.py:296` (`docs_before`), `:378` (`docs_after`) | `await task_processed_repo.list_by_channel(channel_id)` — тянет ВСЕ поля, включая `text_clean`; `task_processed_repo: ProcessedDocumentRepo` (аннотация `:264`) |
| O(N²) `new_doc_refs` | `services/scheduler_service.py:496–500` | comprehension по `docs_after` с `{dd.source_ref for dd in docs_before}` **внутри** условия — set пересобирается на каждый элемент |
| coverage-знаменатель | `services/scheduler_service.py:467` | `processed_total = len(docs_after)` — единственное иное использование `docs_after`; `docs_before` используется ТОЛЬКО в `new_doc_refs` (496–500) |
| Репо-метод (refs) | порт `storage/ports.py:588` + impl `storage/sqlalchemy/processed_document_repo.py:275` | **`list_source_refs_by_channel(channel_id) -> list[str]`** — уже существует; SELECT `source_ref` без полного row |
| Репо-метод (count) | порт `storage/ports.py:583` + impl `processed_document_repo.py:268` | **`count_by_channel(channel_id) -> int`** — `SELECT COUNT(*)`, уже существует |
| **⚠ Расхождение ORDER BY** | `list_by_channel` (def `processed_document_repo.py:177`) — в его запросе **`ORDER BY source_ref ASC`** (клауза сортировки на строке **203**); `list_source_refs_by_channel` (`:275–280`) — **БЕЗ ORDER BY** | Прямая замена изменит порядок `new_doc_refs`. Чтобы сохранить байт-в-байт порядок — сортировать refs в сервисе (`sorted(...)`) либо считать разность через множество и сортировать; НЕ трогать сигнатуру/поведение репо ради этого без необходимости |
| `compute_watch_score` сигнатура | `services/watchlist_service.py:528–537` | `(interest, doc, doc_embedding, *, keyword_weight, semantic_weight, aggregation, topk)` — **precomputed-tokens параметра НЕТ**; `_build_doc_tokens(doc)` дёргается внутри (`:554`). Новый параметр добавляй **keyword-only** (после `*`) с fallback — тогда все текущие вызовы совместимы |
| `_build_doc_tokens` | `services/watchlist_service.py:419–431` | `set[str]`; объединяет `_tokenize` по `topics`, `summary`, `text_clean`. Чистая функция от `doc` — безопасно кэшировать по `source_ref` |
| Горячий вложенный цикл | `services/watchlist_service.py:1228` (`for interest in active`) × `:1236` (`for ref, doc in docs_by_ref.items()`) → `:1238` `compute_watch_score(...)` | `docs_by_ref` уже собран одним `get_by_source_refs` (`:1198`) — идеальная точка построить `doc_tokens_by_ref` ОДИН раз до внешнего цикла |
| Прочие вызовы `compute_watch_score` | `watchlist_service.py:1452` (`backfill_interest`), `:1849` (`_collect_corpus_combined_scores`) | Оба — **single-interest** циклы (I=1), там токенизация уже O(D); обновлять не обязательно (fallback покрывает). Обновить для консистентности — по желанию, но НЕ обязательно |
| `_make_key` кэша | `processing/llm/response_cache.py:42–50` | `raw = f"{system_prompt or ''}|{prompt}|{temperature}|{max_tokens}"` → sha256; **provider/model отсутствуют** |
| get/put кэша | `response_cache.py:52–69` (`get`), `:71–89` (`put`) | оба зовут `_make_key`; при добавлении provider/model в ключ — прокинуть через обе сигнатуры |
| Provider/model доступны | `processing/llm/instrumented.py:24–27` (`__init__`), вызовы кэша: `:42` (`get`), `:56` (`put`) | `self._provider`, `self._model` — здесь и только здесь кэш читается/пишется в проде; `generate_with_usage` (`:66–96`) кэш НЕ использует — не трогать |
| Единственный prod-потребитель кэша | `instrumented.py` | `get_llm_cache` в проде используется только тут; в `api/routes/llm_config.py` `.clear()`/`@router.put` — это НЕ response-cache (ложное совпадение), не трогать |
</verified_anchors>

<scope>
**O-3 (закрывает F-03, High) — `scheduler_service.py`:**
1. `docs_before`/`docs_after` (строки 296, 378): заменить `list_by_channel` на `list_source_refs_by_channel` — грузим только `source_ref`'ы, не полный корпус с текстами.
2. `new_doc_refs` (строки 496–500): множество `before_refs = set(refs_before)` построить **один раз** до вычисления разности (устранить O(N²)); разность — линейная. **Сохранить порядок** `new_doc_refs` байт-в-байт: `list_source_refs_by_channel` не имеет `ORDER BY` (в отличие от `list_by_channel` с `ORDER BY source_ref ASC`) — отсортируй refs так, чтобы результат совпал с прежним (проще всего — сортировка по `source_ref`; покрыть тестом).
3. coverage-знаменатель (строка 467): `processed_total` больше не может браться из `len(docs_after)` полных моделей — использовать `len(refs_after)` или `count_by_channel(channel_id)` (эквивалентно; выбор на твоё усмотрение, но без второго полного SELECT).
4. Вариант (в) из O-3 (возврат новых ref'ов прямо из результата пайплайна) — **вне scope** (см. `<out_of_scope>`).

**O-7 (закрывает F-08) — `watchlist_service.py`:**
5. `compute_watch_score` (528): добавить **keyword-only** параметр precomputed-токенов (напр. `doc_tokens: set[str] | None = None`) с fallback на `_build_doc_tokens(doc)`, если не передан — сигнатура остаётся совместимой со всеми текущими вызовами.
6. В `check_interests` (1142): построить `doc_tokens_by_ref = {ref: _build_doc_tokens(doc) for ref, doc in docs_by_ref.items()}` **один раз** до внешнего цикла по интересам (после `get_by_source_refs` на 1198) и передавать `doc_tokens_by_ref[ref]` в `compute_watch_score` на 1238 — O(I×D)→O(D) лемматизаций. Скоры обязаны остаться **байт-в-байт теми же**.

**O-6 (закрывает F-07, частично F-06) — `response_cache.py` + `instrumented.py`:**
7. Добавить `provider`/`model` в состав `_make_key` (и в сигнатуры `get`/`put`, прокинув из вызывающего кода). В `instrumented.py` передавать `self._provider`/`self._model` в get (42) и put (56). Порядок новых параметров выбирай так, чтобы **не сломать существующие позиционные вызовы** `cache.get(...)`/`cache.put(...)` в `tests/test_f8a_hardening.py` (см. `<test_strategy>`) — добавляй как trailing-optional или keyword-only.
</scope>

<out_of_scope>
- **Расширение кэша на `generate_with_usage`** — вердикт отчёта (O-6): **«Не делать»** (одинаковые промпты в пайплайне редки, скрытие usage-токенов исказит метрики и rate-limiter). `generate_with_usage` (`instrumented.py:66–96`) не трогать.
- **F-18** (eviction кэша удаляет insertion-first, а не старейшую/истёкшую — `response_cache.py:79–83`) — Low, диспозиция в **S7**. Не трогать.
- **Вариант (в) O-3** («возврат новых ref'ов прямо из результата пайплайна») — опционально по отчёту, только если ляжет тривиально; по умолчанию **вне этой сессии** (меняет контракт результата пайплайна — риск сверх quick-win).
- **Перекалибровка порогов / изменение метрики скоринга watchlist** (веса keyword/semantic, aggregation/topk, threshold) — поведение не менять; скоры остаются идентичными.
- **Порядок хуков в тике** (то, что меняет S4) — S2 чинит только горячий путь `list_by_channel`/`new_doc_refs`/coverage; последовательность вызовов хуков не трогать.
- **Контракты и миграции** — `docs/contracts/**` (JSON Schema) и Alembic не трогать (workflow §7). Схема БД не меняется — все нужные repo-методы уже существуют.
- Любые файлы за пределами: `scheduler_service.py`, `watchlist_service.py`, `response_cache.py`, `instrumented.py`, тесты. Никакого попутного рефакторинга соседнего кода.
</out_of_scope>

<acceptance_criteria>
Сессия принята, когда ВСЁ нижеследующее доказано тестами/замерами:
1. **Тик без полнокорпусных загрузок и без O(N²):** `docs_before`/`docs_after` больше не тянут полный корпус (`list_by_channel` в этом пути заменён на `list_source_refs_by_channel`); множество `before_refs` строится один раз; вычисление `new_doc_refs` — линейное. Coverage-знаменатель считается без второго полного SELECT.
2. **`new_doc_refs` — байт-в-байт та же последовательность:** характеризационный тест на репрезентативном фикстурном наборе (пересечение before/after, новые refs, дубли) доказывает, что состав И порядок `new_doc_refs` совпадают с прежним поведением (`ORDER BY source_ref` учтён). Это главный регресс-риск O-3.
3. **Watchlist: токенизация 1×/тик, скоры идентичны:** `_build_doc_tokens`/`compute_watch_score` вызывается так, что каждый документ токенизируется один раз на тик (assert на счётчик вызовов `_build_doc_tokens` через spy/patch: при I интересах × D документах — ровно D вызовов, а не I×D); результат `compute_watch_score` с precomputed-токенами **идентичен** результату с внутренним `_build_doc_tokens` (характеризационный тест эквивалентности на нескольких (interest, doc) парах, включая exclude-keywords и multi-word phrase).
4. **Ключ кэша различает provider/model:** одинаковый `prompt`/`system_prompt`/`temperature`/`max_tokens`, но разные `model` (и/или `provider`) → разные записи кэша (put модели A + get модели B на тех же промпт-параметрах = miss). Прежнее поведение для одной и той же модели сохранено (hit). Существующие позиционные вызовы в `tests/test_f8a_hardening.py` остаются валидны.
5. **Метрики/поведение (регресс-стопы):** `tg_watchlist_score` (histogram) и `tg_watchlist_matches_total` на фикстурном прогоне не меняются (скоры те же → те же match/filter-исходы); длительность тика (лог `Incremental pipeline completed`) — сравнение до/после на dev/prod по тикам с сопоставимым `details.new_messages` (S0 обл.2 caveat), ожидаемо ниже, но **обязательное условие — не выше**. Cache hit/miss наружу не экспортируется (осознанный gap) — live-baseline не требуется, критерий 4 доказывается тестом.
6. Все существующие тесты зелёные в обоих режимах (см. `<test_strategy>`).
</acceptance_criteria>

<test_strategy>
Workflow §5.4: для perf-эквивалентности — **характеризационные тесты, доказывающие идентичность вывода** (перед фиксом зафиксировать эталон, после — совпадение); для F-08/F-07, где меняется наблюдаемое поведение вызовов, — сперва тест, фиксирующий текущее/желаемое, затем фикс.

1. **Новые тесты:**
   - **O-3 `new_doc_refs`:** характеризационный тест на большом фикстурном наборе — состав И **порядок** разности before/after совпадают с эталоном (кейсы: пустой before, полное пересечение, частичное, дубликаты ref'ов); отдельный тест, что coverage-знаменатель корректен без полного SELECT.
   - **O-7 эквивалентность скоров:** `compute_watch_score(..., doc_tokens=precomputed)` ≡ `compute_watch_score(...)` (fallback) — идентичные `WatchScore` на наборе пар (в т.ч. exclude-keywords, multi-word phrase, keyword-only degrade); тест «токенизация один раз на тик» — spy/patch на `_build_doc_tokens`, assert call-count == D (не I×D) в `check_interests`.
   - **O-6 ключ кэша:** одинаковый промпт + разные model/provider → разные записи (miss); та же model → hit; проверить `get`/`put`/`_make_key` сигнатуры.
2. **Существующие (из плана §S2) — прогнать все, дополнить fakes/патчи при изменении арности:**
   - Планировщик/хуки (порядок хуков не сломан): `tests/test_scheduler_service.py`, `tests/test_f11_scheduler_hook.py`, `tests/test_f5c_scheduler_hook.py`.
   - Watchlist: `tests/test_watchlist_score.py` (прямые вызовы `compute_watch_score` — все с `doc_embedding=`/позиционным 3-м арг; keyword-only новый параметр их НЕ ломает), `tests/test_watchlist_service.py`, `tests/test_watchlist_batch.py`, `tests/test_watchlist_metrics.py` + точечный прогон watchlist из `tests/README.md`.
   - Кэш: `tests/test_f8a_hardening.py` — **⚠ содержит ~много позиционных вызовов `cache.put(prompt, system, temp, max_tokens, value)` и `cache.get(prompt, system, temp, max_tokens)`** (строки ~607–684 в `TestLLMResponseCache`, плюс дополнительные позиционные вызовы на строках **709**, **731**, **746** в `TestInstrumentedCacheIntegration`). Все эти call-sites (полный набор: ~607–684, 709, 731, 746) — те, где новые provider/model параметры в `get`/`put` **обязаны** быть добавлены так, чтобы вызовы остались валидны (trailing-optional с дефолтом или keyword-only) — иначе они массово упадут. Дополни файл кейсом «разные model → разные ключи».
3. **Режимы (`tests/README.md`):** *default* (`pytest -q`) обязателен; ***PR standard* (`TEST_POSTGRES=1`) обязателен** — repo-методы `list_source_refs_by_channel`/`count_by_channel` PG-gated, путь O-3 иначе не проверяется на реальном SQL.
4. **Метрики/ручное:**
   - Длительность тика: снять до/после по шаблону S0 §4 блок 2 (`docker logs tg_parser --since 48h | grep 'Incremental pipeline completed'`), сравнивать по тикам с сопоставимым `details.new_messages`; зафиксировать в PR (baseline: медиана ≈207 s).
   - Watchlist-скоры не изменились: S0 §4 блок 5 (`tg_watchlist_score_count`/`_sum`, `tg_watchlist_matches_total`) — до/после совпадают; если live-стек недоступен из сессии — зафиксировать команду и ожидание в PR.
   - Cache: live-baseline нечем снять (не экспортируется) — критерий 4 закрывается тестом, отметить gap в PR.
</test_strategy>

<workflow>
Нормативно — workflow §2/§3/§5:
1. Ветка **`fix/S2-perf-quickwins`** от `main`.
2. Реализация → характеризационные тесты (эквивалентность до/после) → новые тесты O-3/O-6/O-7 → оба режима тестов зелёные.
3. Обновить [`BUG_LOG.md`](BUG_LOG.md): F-03 (High), F-07, F-08 (со ссылкой на отчёт ревью) — addressed этой сессией; отметить, что F-06 закрыта частично (расширение кэша — «Не делать»), F-18 остаётся в S7.
4. Self-review тестов и кода — отдельными агентами со свежим контекстом; **bugbot по изменениям ветки — обязательный гейт**.
5. Зелёные тесты + зелёный bugbot → commit + push → **PR** → merge в `main`.
6. **Деплой — НЕ соло:** S2 выкатывается в составе безопасного блока **S1–S3** (workflow §3). В этой сессии деплой не выполняется.
7. **Зависимости (план §2):** S1/S2/S3 взаимно независимы (разные файлы) — порядок свободный. **S4 мягко зависит от S2** (S4 меняет порядок хуков в том же `scheduler_service.py`; отчёт предписывает O-4 «после O-1..O-3») — поэтому чиним горячий путь тика ДО S4, чтобы S4 лёг на чистую базу.
8. `git commit` — только в рамках этого цикла, не раньше зелёного статуса (AGENTS.md: без явного цикла коммиты запрещены; здесь цикл согласован workflow-документом).
</workflow>

<recap>
| Находка | Что делаем | Приёмка |
|---|---|---|
| F-03 (High) / O-3 | `list_source_refs_by_channel` вместо двух `list_by_channel`; `before_refs` set один раз (O(N²)→O(N)); coverage через `len(refs)`/`count_by_channel`; порядок `new_doc_refs` сохранён | тик без полнокорпусных SELECT'ов; `new_doc_refs` состав+порядок байт-в-байт (тест); длительность тика не выше baseline ≈207 s |
| F-08 (Medium) / O-7 | `doc_tokens_by_ref` один раз в `check_interests`; keyword-only precomputed-параметр `compute_watch_score` с fallback | `_build_doc_tokens` вызван D раз, не I×D (тест); скоры идентичны (характеризация); `tg_watchlist_score` не изменился |
| F-07 (Medium; часть F-06) / O-6 | `provider`/`model` в `_make_key`/`get`/`put`; прокинуть из `InstrumentedLLMClient` | разные model → разные ключи (тест); прежние позиционные вызовы в `test_f8a_hardening.py` не сломаны; `generate_with_usage` не трогается |
</recap>

---

*Строки кода — по рабочей копии 2026-07-07. При смещении нумерации ориентируйся на имена символов: `list_by_channel` / `list_source_refs_by_channel` / `count_by_channel` / `new_doc_refs` (scheduler), `compute_watch_score` / `_build_doc_tokens` / `check_interests` / `doc_tokens_by_ref` (watchlist), `_make_key` / `get_llm_cache` / `InstrumentedLLMClient` (кэш).*
