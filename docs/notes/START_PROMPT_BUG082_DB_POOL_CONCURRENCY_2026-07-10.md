# START PROMPT — BUG-082: DB connection-pool exhaustion + concurrency-budget + DB-error outcome classification

**Дата создания:** 2026-07-10 · **Для:** implementation-сессии в отдельном окне (агент ПРАВИТ код).
**Тип:** bug-fix сессия (инфраструктура/надёжность+observability). **Вне серии S1–S7** — это pre-existing infra-находка, обнаруженная во время post-deploy watch блока S1–S3. Процессуально следует тем же соглашениям (ветка → PR → bugbot → merge), но НЕ является сессией remediation-плана.
**Нормативные документы (при расхождении — они первичны):**
- Журнал: [`BUG_LOG.md`](BUG_LOG.md) — **запись BUG-082** (полное описание, симптомы, root-cause, proposed fix #1–#4), плюс её `Update 2026-07-09` (коррекция от BUG-083: устойчивый `llm_error` на labdiagnostica оказался refusal, а НЕ DB-pool; genuine DB-pool mislabel остаётся валидным для реальной starvation) и запись **BUG-083** (для контекста «что уже разделено»).
- Процесс: [`WORKFLOW_REMEDIATION_SESSIONS_AGREEMENTS_2026-07-07.md`](WORKFLOW_REMEDIATION_SESSIONS_AGREEMENTS_2026-07-07.md) §2 (git), §5 (цикл), §6 (независимые ревью + bugbot), §7 (ограничения scope: контракты/миграции). Для этой сессии §7 применяется как «без миграций Alembic и без изменения `docs/contracts/**`».
- Проект: [`AGENTS.md`](../../AGENTS.md) (forbidden: `git commit` без явного цикла — здесь цикл согласован; прямые правки `pyproject.toml`/`requirements.txt` без явного запроса — не требуются).
- Инфра: [`../SERVER_ARCHITECTURE.md`](../SERVER_ARCHITECTURE.md) (prod: docker-compose, `postgres` = `pgvector/pgvector:pg17`; путь `/home/user/TG_parser`), деплой-паттерн [`../runbooks/S1_S3_DEPLOY_AND_WATCH.md`](../runbooks/S1_S3_DEPLOY_AND_WATCH.md).

---

<role>
Ты — senior-инженер проекта tg_parser. Ты закрываешь **BUG-082** — периодическое исчерпание пула соединений PostgreSQL (`sqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 10 reached, connection timed out, timeout 30.00`), при котором один всплеск потребления соединений в тике каскадно роняет несколько источников в `degraded`, а на resummarize-пути DB-ошибка **маскируется под `outcome="llm_error"`**, искажая LLM-health сигналы.

Находка **многосоставная** и часть уже смягчена в проде вручную (`DB_POOL_SIZE=5→10` в prod-`.env`, держит 24h+ без `QueuePool`-ошибок), но **эта митигация не durable** — она живёт только в untracked prod-`.env`; при пересборке из репо-дефолтов (`db_pool_size=5`) регрессирует. Твоя задача — сделать митигацию durable в коде, устранить observability-дефект (классификация DB-ошибок), и структурно снизить вероятность starvation — **без миграций и без live-нагрузочного теста** (его нет). Никакого попутного рефакторинга.
</role>

<context>
**Симптом (один тик, `2026-07-07T23:16:40–41Z`):** 10 событий `QueuePool limit of size 5 overflow 10 reached … timeout 30.00`, разлетевшихся по подсистемам одного тика: `kdl_ru` processing упал на `channel_advisory_lock` (`engine.connect()`); `Lab4health` incremental topicization — на `get_by_source_ref`; `AgeManagment` — `bug077_resume_checkpoint_read_error`; topic auto-embedding упал; `failure_cooldown_load_failed`. Затронутые источники → `outcome=degraded`. Resummarize age-путь посчитал свою pool-ошибку как `llm_error`. В том же окне независимо был OpenAI `429` на `/v1/embeddings` (**отдельная** проблема embedding-rate-limit, НЕ pool — см. `<out_of_scope>` #4).

**Root-cause (гипотеза из BUG_LOG).** Пиковая concurrency тика транзиентно требует **> 15** соединений из **processing**-пула: в одном тике параллельно работают processing-стадия, per-source incremental topicization (`get_by_source_ref`), topic auto-embedding, resummarize-candidate выборка, и **advisory-lock берёт ОТДЕЛЬНОЕ `engine.connect()`** из того же пула и держит его на весь guarded-run. При `pool_size=5 + max_overflow=10` (=15 max) и 30s checkout-timeout всплеск исчерпывает пул, и каждый поздний checkout поднимает `TimeoutError`. Это **недоразмер пула относительно параллельной per-source нагрузки**, не логическая ошибка.

**Транзиентность / no data loss.** Затронутые источники ретраятся на следующем тике (пайплайн идемпотентен); post-deploy coverage вырос. Проблема — надёжность + два observability-дефекта: (a) DB-ошибки resummarize считаются `llm_error` (искажает F5-C LLM-health tripwire); (b) pool-спайк выглядит как несколько несвязанных `degraded`-источников, пряча общую причину.

**Что уже разделено (BUG-083).** Живой probe доказал, что устойчивый `labdiagnostica_logical llm_error/age` — это Anthropic `stop_reason='refusal'`, а не DB-pool; BUG-083 уже задеплоен (`refusal`/`refusal_cooldown` outcomes). Поэтому в текущем проде `QueuePool`-ошибок ≈0. Это значит: **DB-error классификация (#3) — defensive** (сработает при следующей реальной starvation), а не для устранения текущего шумного счётчика. Не путай эти два: refusal уже вынесен, ты чинишь DB-путь.
</context>

<verified_anchors>
Факты проверены по рабочей копии 2026-07-10 — опирайся на них, при смещении строк ориентируйся на имена символов.

| Что | Где (файл:строки) | Факт |
|---|---|---|
| Pool-настройки | `config/settings.py:117` (`db_pool_size` default **5**, `ge=1 le=50`), `:123` (`db_max_overflow` default **10**), `:129` (`db_pool_timeout` **30.0**), `:135` (`db_pool_recycle` 3600), `db_pool_pre_ping` рядом | **репо-дефолт `db_pool_size=5`** ≠ prod-`.env` `DB_POOL_SIZE=10`. Митигация BUG-082 живёт ТОЛЬКО в prod-`.env` (untracked) → не durable |
| ⚠ Тест ассертит ДЕФОЛТ пула | `tests/test_postgres_integration.py:237–241` (`test_postgres_settings_defaults`) — `assert settings.db_pool_size == 5`, `:238` `== 10` (overflow), `:239` `== 30.0`, `:240` `== 3600` (после `delenv` всех env) | **этот тест СЛОМАЕТСЯ при подъёме дефолта 5→10** — это НЕ «explicit-override» тест, а defaults-тест. Обязательный red→green анкор для #1: обновить ожидания вместе со сменой дефолта. (`:243 test_pool_size_validation` — `le=50` границы, отдельно) |
| Advisory xact-lock внутри resummarize | `resummarization_service.py:289–292` (`topic_card_repo.session.execute(pg_try_advisory_xact_lock)`) | ⚠ ещё один DB-execute ВНУТРИ `resummarize_topic` ДО LLM-вызова — DB-ошибка здесь тоже пропагирует в `run_for_channel:235` (breakdown), это доп. DB call-site для классификации #3 |
| Engine-фабрика | `storage/engine_factory.py:66` (`create_postgres_engine_config`), `:97` (`create_engine_from_config`), `:140` (`create_engine_from_settings(settings, db_name)`) | все три engine берут ОДНИ И ТЕ ЖЕ `settings.db_pool_size/db_max_overflow/...`; менять дефолт = менять сразу все три пула |
| **Три отдельных engine/пула** | `storage/sqlalchemy/database.py:43–45` (`ingestion_state_engine`, `raw_storage_engine`, `processing_storage_engine`), инициализация `:94–98`, dispose `:126–131`, маппинг `:164–166` | **три независимых пула**, каждый `pool_size + max_overflow`. Контендится **processing**-пул (processing-данные + advisory-lock + topicization + resummarize-candidates + auto-embedding). ⚠ Суммарный потолок соединений = 3 × (`pool_size`+`max_overflow`) — при подъёме дефолта проверь `max_connections` Postgres |
| Advisory-lock берёт ОТДЕЛЬНОЕ соединение | `services/advisory_lock.py:82` (`conn = await engine.connect()`), engine из `engine_attr` (напр. `"processing_storage_engine"`), держится весь guarded-run, `conn.close()` в `finally` `:105`; degrade-to-True при `engine is None` `:78–80` | session-scoped lock на ВЫДЕЛЕННОМ соединении из processing-пула — ключевой structural-потребитель (#2). Комментарий файла: «dedicated connection NEVER returned to pool while lock held» |
| Resummarize: breakdown-мислейбл | `services/resummarization_service.py:235–242` (`run_for_channel`: `except Exception … skipped["llm_error"] += 1`) | **ЛЮБОЕ** исключение из `resummarize_topic` (включая DB `TimeoutError`, поднятый на `get_by_topic_id`/`get_by_source_refs`/`get_by_id`) → breakdown-ключ `llm_error`. AnthropicBillingError re-raise на `:229` (не трогать) |
| Resummarize: Prometheus llm_error-сайты | `resummarization_service.py:378–384` (template_missing), `:422–436` (`except Exception:` вокруг LLM-вызова → `status="llm_error"`, re-raise), `:486–494` (empty response), `:505–519` (parse_error) | Prometheus `record_resummarize_outcome(status="llm_error")`. ⚠ DB-вызовы (`get_by_id` `:297`, `get_by_topic_id` bundle `:329`, `get_by_source_refs` `:345`) стоят ВНЕ этих try — DB-ошибка там пропагирует и ловится в `run_for_channel:235` (breakdown), НЕ в Prometheus. `:422` `except Exception:` оборачивает ТОЛЬКО LLM-вызов (DB там не зовётся) |
| Метрика resummarize — outcome free-form | `api/metrics.py:347` (`RESUMMARIZE_TOTAL` Counter, labels `channel_id/outcome/trigger`), `record_resummarize_outcome` | label `outcome` — **свободная строка** (Counter): добавление `db_error` схему метрики НЕ меняет (как `refusal`/`refusal_cooldown` в BUG-083). Комментарий `:355` перечисляет известные outcome — обнови |
| Scheduler: stage_errors / degraded | `services/scheduler_service.py:212` (`stage_errors`), `:356` (`except TimeoutError → ("pipeline_timeout", exc)`), `:366` (`("pipeline", exc)`), `:410–413` (`fail_ratio ≥ degraded_ratio → degraded_reason`), `:439–441` (AnthropicBillingError promote) | pool-`TimeoutError` в processing-стадии → `stage_errors` → источник `degraded`. ⚠ `asyncio.TimeoutError`/`builtins.TimeoutError` (watchdog) ≠ `sqlalchemy.exc.TimeoutError` (pool) — они РАЗНЫЕ, не перепутай при классификации |
| Concurrency-настройки | `config/settings.py:783` (`scheduler_max_concurrent_sources` default **2**, `ge=1 le=10`), `:797` (`scheduler_max_instances` 2), `:813` (`scheduler_source_timeout_s` 1800) | per-source параллелизм в тике = 2 (prod может override в `.env` — **проверь фактическое prod-значение**). Комментарий предупреждает: Anthropic rate-limiter общий на ключ, потому держат 2 |
| Health показывает pool-конфиг | `api/health_checks.py:40–41` (`pool_size`/`max_overflow` из settings) | `/health` уже отдаёт pool-конфиг — удобно для smoke-проверки durable-дефолта после деплоя |
| Prod-факт | prod-`.env`: `DB_POOL_SIZE=10` (BUG-082 mitigation, `bak_bug082_poolsize_20260708`) | подтверждено на проде 2026-07-10; после durable-фикса prod-override можно оставить (совпадёт) или убрать |
</verified_anchors>

<design_decision>
Находка состоит из 4 частей с очень разной ценой/риском. **Реши и зафиксируй в PR, какие части входят в эту сессию; рекомендуемый scope ниже.** Ключевая развилка — часть #2 (structural).

**#1 — Durable pool budget (ОБЯЗАТЕЛЬНО, низкий риск).**
Сделать prod-митигацию durable в репо. Подними дефолт `db_pool_size` **5→10** в `config/settings.py` (по желанию пересмотри `db_max_overflow`). ⚠ **Обязательная проверка потолка:** дефолт применяется ко ВСЕМ ТРЁМ пулам (ingestion/raw/processing), суммарный max = 3 × (`pool_size` + `max_overflow`). При 10+10 это 3×20 = **60** соединений; сверь с Postgres `max_connections` (у `pgvector/pgvector:pg17` дефолт 100, но проверь prod-`postgresql.conf`/compose — зафиксируй запас в PR). Если запаса нет — поднимай точечно (только processing-пул) через отдельную настройку, а не общий дефолт. Обнови `.env.example`/compose-комментарий, если там документирован pool. **Prod-`.env` override после этого станет избыточным (совпадёт) — отметь в runbook, не удаляй вслепую.**

**#3 — DB-error outcome classification (ОБЯЗАТЕЛЬНО, низкий риск, observability core).**
На resummarize-пути отделить DB/pool-ошибки от `llm_error`. Введи distinct outcome **`db_error`** (свободный label — схему метрики не меняет).
- Классифицируй по типам SQLAlchemy: `sqlalchemy.exc.TimeoutError` (pool checkout), `OperationalError`, `DBAPIError`, `InterfaceError` (или базовый `sqlalchemy.exc.SQLAlchemyError` — **выбери минимально-широкий набор и обоснуй**, чтобы не проглотить логические ошибки).
- Два места (см. anchors):
  1. `run_for_channel:235–242` — в `except` различать DB-исключение → breakdown-ключ `db_error` (+ по возможности `record_resummarize_outcome(status="db_error", …)`, т.к. сейчас на этом пути Prometheus-outcome вообще не пишется — зафиксируй решение), иначе `llm_error`. **AnthropicBillingError re-raise (`:229`) не трогать.**
  2. `resummarize_topic:422–436` — `except Exception:` вокруг LLM-вызова: если сюда прилетит DB-исключение (маловероятно, LLM-only, но defensive) — тоже `db_error`. НЕ переклассифицировать реальные LLM-ошибки (404 от снятой модели и т.п. остаются `llm_error`).
- Обнови комментарий `api/metrics.py:355` (список outcome) и docstring `resummarize_topic` (`:272–274`).
- **Инвариант:** `refusal`/`refusal_cooldown` (BUG-083) не трогать; `db_error` — ещё один distinct outcome рядом.

**#2 — Structural concurrency-budget (РЕКОМЕНДУЕТСЯ, средний риск — центр сессии; если упирается в ADR/инфру — эскалация).**
Снизить вероятность starvation processing-пула структурно, БЕЗ live-нагрузочного теста. Порядок предпочтений:
1. **Выделенный маленький engine/пул под advisory-lock (основной путь, если ложится чисто).** Advisory-lock (`advisory_lock.py`) держит ОТДЕЛЬНОЕ соединение весь guarded-run из processing-пула — под нагрузкой acquisition сам себя же голодит. Дать advisory-lock крошечный отдельный пул (напр. новый `lock_engine` с `pool_size=scheduler_max_concurrent_sources+запас`, `max_overflow` малый), чтобы захват lock не конкурировал с data-запросами. ⚠ **Перед правкой перечисли всех вызывающих `channel_advisory_lock`** (grep по `channel_advisory_lock` / `engine_attr=` — processing-стадия, incremental topicization, и др.) и по каким `engine_attr` они ходят, чтобы новый lock-engine покрыл все и не разъехался с namespace'ами. Учти жизненный цикл (создание/`dispose` в `Database:94–98/126–131`), degrade-to-True путь (`:78–80`), и что суммарный потолок соединений вырастет — пересчитай под `max_connections`.
2. **Явный concurrency-budget: доказать `pool_size ≥ worst-case параллельных потребителей`.** Посчитать пиковых потребителей processing-пула на тик = `scheduler_max_concurrent_sources` × (advisory-lock + processing-data + topicization + auto-embedding + resummarize-candidate). Убедиться, что `db_pool_size (+ overflow)` покрывает пик; при необходимости привязать/ограничить `scheduler_max_concurrent_sources` к бюджету пула (документированная формула, а не магическое число). Дешевле кода, но лечит симптом sizing'ом.
3. **Эскалация.** Если корректный structural-фикс требует ADR (напр. смена модели пулинга, per-stage semaphore поверх пула) или инфра-изменения сверх настроек — **останови и вынеси owner'у** отдельным согласованным решением; не тащи ADR-уровневую переделку внутрь bug-fix сессии.

**Если сессия раздувается:** сделать #1 + #3 как самодостаточный durable+observability PR, а #2 вынести в под-задачу BUG-082b (structural) с этим же START_PROMPT как основой. Зафиксируй выбор в PR и BUG_LOG.
</design_decision>

<scope>
**Файлы (ожидаемые; не расширять без нужды):**
- `config/settings.py` — #1 (дефолт пула; опц. новая настройка lock-пула для #2).
- `tg_parser/services/resummarization_service.py` — #3 (классификация DB-ошибок в `run_for_channel` и defensive в `resummarize_topic`).
- `tg_parser/api/metrics.py` — #3 (комментарий outcome-списка; кода метрики менять не нужно — label free-form).
- `tg_parser/services/advisory_lock.py` + `storage/sqlalchemy/database.py` + `storage/engine_factory.py` — только если выбран #2 путь 1 (выделенный lock-engine).
- Тесты (см. `<test_strategy>`), `docs/notes/BUG_LOG.md`, при необходимости `.env.example`/compose-комментарий и runbook-заметка.

**Работы:**
1. #1 durable pool default + проверка `max_connections`-запаса (задокументировать расчёт в PR).
2. #3 distinct `db_error` outcome на обоих resummarize-путях; узкий набор DB-типов исключений; сохранить `llm_error` для настоящих LLM-ошибок, `refusal*` (BUG-083) и `AnthropicBillingError` (re-raise) не трогать.
3. #2 (если в scope) — по выбранному пути `<design_decision>`; пересчёт потолка соединений; жизненный цикл нового engine (init/dispose) и degrade-путь.
4. BUG_LOG: BUG-082 → отметить, какие части addressed этой сессией, зафиксировать выбор #2-пути и запаса `max_connections`; #4 явно вынести отдельным item.
</scope>

<out_of_scope>
- **Миграции Alembic и `docs/contracts/**` (JSON Schema)** — не трогать (workflow §7). Находка чисто инфра/сервис-уровня, схема БД не меняется.
- **#4 — OpenAI embeddings `429`** (co-occurring rate-limit на `/v1/embeddings`) — **отдельная проблема, НЕ pool**. В этой сессии только **завести отдельный item** в BUG_LOG/FUTURE (найти место embedding-клиента, backoff/раздельный трекинг — своя сессия). Не чинить здесь.
- **BUG-083 refusal-логика** — уже задеплоена; `refusal`/`refusal_cooldown` не трогать (только добавить `db_error` рядом).
- **Watchdog `asyncio.TimeoutError`** (`scheduler_source_timeout_s`, `:356 pipeline_timeout`) — это НЕ pool-ошибка; классификацию degraded для watchdog не менять.
- **Прод-деплой митигации `.env`** — уже применён вручную; в этой сессии не переустанавливать (только сделать durable в коде + отметить в runbook).
- Любой попутный рефакторинг engine/session-слоя сверх выбранного #2-пути; смена модели пулинга без ADR (эскалация).
</out_of_scope>

<acceptance_criteria>
Принято, когда доказано тестами/замерами:
1. **Durable pool (#1):** репо-дефолт `db_pool_size` = 10 (или обоснованное значение); в PR — расчёт `3 × (pool_size+max_overflow)` vs prod Postgres `max_connections` с явным запасом. **Обязательно обновить `tests/test_postgres_integration.py:237–241` (`test_postgres_settings_defaults`)** — он ассертит `db_pool_size == 5` (defaults-тест, СЛОМАЕТСЯ; red→green анкор для #1). Тесты, задающие `db_pool_size` **явно** (`tests/conftest.py:95`, `test_e2e_pipeline.py:121`, `test_phase3d_advanced.py` pool_size=1/overflow=0, и т.п.), остаются зелёными без правок — не путать их с defaults-тестом.
2. **DB-error classification (#3):** unit-тест — DB-исключение (`sqlalchemy.exc.TimeoutError`/`OperationalError`), поднятое репо внутри `resummarize_topic` (напр. `get_by_topic_id`/`get_by_source_refs` замокан на raise), классифицируется в `run_for_channel` как `db_error` (breakdown и/или Prometheus), **НЕ `llm_error`**. Отдельный тест — настоящая LLM-ошибка (404/пустой ответ) по-прежнему `llm_error`; `AnthropicBillingError` по-прежнему пропагирует (не `db_error`, не `llm_error`).
3. **`db_error` — distinct outcome:** `record_resummarize_outcome(status="db_error")` пишет `tg_resummarize_total{outcome="db_error"}`, метрика-схема не менялась (label free-form); `refusal`/`refusal_cooldown`/`llm_error`/`ok` не задеты.
4. **(если #2 в scope) Structural:** тест на выбранный путь — напр. advisory-lock использует выделенный engine (не processing-пул), либо тест/ассерт формулы concurrency-budget; degrade-to-True путь advisory-lock сохранён; новый engine корректно `dispose`-ится.
5. **Без миграций/контрактов:** нет новых Alembic-ревизий; `docs/contracts/**` не изменён.
6. **#4 зафиксирован отдельно:** в BUG_LOG есть отдельный item на embeddings-429 (не закрыт этой сессией).
7. Все существующие тесты зелёные в обоих режимах (`<test_strategy>`).
</acceptance_criteria>

<test_strategy>
Workflow §5.4: для бага — сначала **падающий тест (red → green)**.
1. **Новые:**
   - #3: `resummarize_topic`-репо (`get_by_topic_id`/`get_by_source_refs`/`get_by_id`, или xact-lock `session.execute` `:289`) замокан на `sqlalchemy.exc.TimeoutError` → `run_for_channel` даёт `db_error`, не `llm_error` (red перед фиксом). Негативные кейсы (обязательно): (a) реальная LLM-ошибка → `llm_error`; (b) **произвольное не-DB исключение** из `resummarize_topic` → по-прежнему `llm_error` (не проглотить логические ошибки в `db_error`); (c) `AnthropicBillingError` → пропагирует (не `db_error`/`llm_error`).
   - #1: обновить `tests/test_postgres_integration.py:237–241` (defaults 5→10); `Settings()` без env → `db_pool_size == 10`; (опц.) health-эндпоинт отдаёт новый pool_size.
   - #2 (если в scope): advisory-lock берёт соединение из выделенного engine (spy на engine_attr) / формула budget; degrade-путь при `engine is None`.
2. **Существующие — прогнать все, не сломать:**
   - `tests/test_f5c_resummarization_service.py` (**канонический resummarize outcome — включая BUG-083 `TestRefusalPoisonPillGuard`**), `tests/test_resummarize_metrics.py`, `tests/test_f5c_scheduler_hook.py`.
   - `tests/test_scheduler_service.py` (degraded/stage_errors классификация).
   - Тесты с явным `db_pool_size`: `tests/conftest.py`, `tests/test_e2e_pipeline.py`, `tests/test_embedding.py`, `tests/test_phase3d_advanced.py` (pool_size=1/overflow=0 — граничный), и др. из grep `db_pool_size`.
   - Advisory-lock / database-lifecycle тесты (если трогаешь #2): найди по `channel_advisory_lock` / `processing_storage_engine`.
3. **Режимы (`tests/README.md`):** *default* (`pytest -q`) обязателен. *PR standard* (`TEST_POSTGRES=1`) — при затрагивании реального engine/pool-поведения (#2, pool-конфиг на живой БД). *max local* — не требуется (нет E2E-нового пути), если #2 не вводит интеграционный путь.
4. **Ручное/метрики:** после деплоя — `/health` показывает новый pool_size; в Prometheus следить за `tg_resummarize_total{outcome="db_error"}` (должен появляться ТОЛЬКО при реальной starvation; в норме 0) и отсутствием `QueuePool limit` в логах. Зафиксировать команды в PR/runbook. **Живой нагрузочный тест не проводить** (нет инструмента; риск для прода).
</test_strategy>

<workflow>
Нормативно — workflow §2/§5/§6:
1. Ветка **`fix/bug082-db-pool-concurrency`** от `main`.
2. Red-тесты (#3 классификация; #1 дефолт) → реализация по `<design_decision>` (минимум #1+#3; #2 по решению) → зелёные тесты в нужных режимах.
3. Обновить [`BUG_LOG.md`](BUG_LOG.md): BUG-082 → `resolved`/`partially-resolved` (в зависимости от того, вошёл ли #2); зафиксировать выбранный #2-путь, расчёт `max_connections`-запаса, и отдельный item на #4 (embeddings-429). Обновить runbook-заметку про избыточность prod-`.env` override.
4. Self-review тестов и кода — **отдельными агентами со свежим контекстом**; **bugbot по изменениям ветки — обязательный гейт** (workflow §6). Security-review желателен (трогается пул/engine).
5. Зелёные тесты + зелёный bugbot → commit + push → **PR** → merge в `main`.
6. **Деплой (соло, по паттерну S1–S3 runbook):** `git pull --ff-only` на prod → пересборка (`docker compose --profile bot up -d --build --no-deps tg_parser mcp tg_bot`, tg_parser собирается из исходников) → smoke: `/health` pool_size, отсутствие `QueuePool` в логах, resummarize outcomes без `llm_error`-регресса. Rollback = `git checkout <pre> && rebuild`. **Миграций нет.** ⚠ После durable-фикса prod-`.env` `DB_POOL_SIZE=10` совпадёт с дефолтом — не удалять вслепую, отметить в runbook.
7. **Эскалация:** если #2 требует ADR/инфра-переделки (смена модели пулинга, per-stage semaphore) — остановиться, вынести owner'у; #1+#3 при этом можно завершить отдельным PR.
8. `git commit` — только в рамках этого цикла, не раньше зелёного статуса (AGENTS.md; здесь цикл согласован).
</workflow>

<recap>
| Часть | Что делаем | Приёмка |
|---|---|---|
| #1 durable pool | Репо-дефолт `db_pool_size` 5→10 (+ проверка `max_connections`-запаса на 3 пула) — prod-митигация становится durable | `Settings()` дефолт=10; расчёт запаса в PR; pool-тесты зелёные |
| #3 DB-error outcome | Distinct `db_error` вместо `llm_error` на resummarize-пути (узкий набор SQLAlchemy-исключений); `llm_error`/`refusal*`/billing не задеты | DB-ошибка → `db_error` (red→green); LLM-ошибка остаётся `llm_error`; billing пропагирует |
| #2 structural (реком.) | Выделенный lock-engine ИЛИ явный concurrency-budget vs pool; при ADR-уровне — эскалация | тест на выбранный путь; degrade-путь advisory-lock сохранён; engine dispose корректен |
| Инвариант | Без миграций/`docs/contracts/**`; #4 embeddings-429 — отдельный item; watchdog-TimeoutError не переклассифицировать | нет Alembic-ревизий; #4 заведён отдельно; existing tests зелёные |
</recap>

---

*Строки кода — по рабочей копии 2026-07-10. При смещении нумерации ориентируйся на имена символов: `db_pool_size`/`db_max_overflow`/`scheduler_max_concurrent_sources` (settings), `create_engine_from_settings` (engine_factory), `processing_storage_engine`/`ingestion_state_engine`/`raw_storage_engine` (database), `channel_advisory_lock` (advisory_lock), `run_for_channel`/`resummarize_topic` (resummarization_service), `record_resummarize_outcome`/`RESUMMARIZE_TOTAL` (metrics), `stage_errors`/`degraded_reason` (scheduler_service).*
