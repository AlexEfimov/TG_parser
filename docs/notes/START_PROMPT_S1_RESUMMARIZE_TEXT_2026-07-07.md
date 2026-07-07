# START PROMPT — S1: Ре-суммаризация получает текст документов (F-02 Critical + O-9a)

**Дата создания:** 2026-07-07 · **Для:** implementation-сессии в отдельном окне (агент ПРАВИТ код).
**Серия:** remediation-сессии по итогам code-review алгоритмов обработки, сессия **S1** (первая, Critical).
**Нормативные документы (при расхождении — они первичны):**
- План сессии: [`PLAN_REMEDIATION_SESSIONS_PROCESSING_ALGORITHMS_2026-07-07.md`](PLAN_REMEDIATION_SESSIONS_PROCESSING_ALGORITHMS_2026-07-07.md) §1 «S1».
- Отчёт ревью: [`CODE_REVIEW_PROCESSING_ALGORITHMS_FABLE5_2026-07-07.md`](CODE_REVIEW_PROCESSING_ALGORITHMS_FABLE5_2026-07-07.md) — F-02 (§4, A12), O-1 (§5), F-11/O-9a.
- Процесс: [`WORKFLOW_REMEDIATION_SESSIONS_AGREEMENTS_2026-07-07.md`](WORKFLOW_REMEDIATION_SESSIONS_AGREEMENTS_2026-07-07.md) §2 (git), §3 (деплой), §5 (цикл), §7 (scope-ограничения).
- Baseline: [`S0_BASELINE_PROCESSING_METRICS_2026-07-07.md`](S0_BASELINE_PROCESSING_METRICS_2026-07-07.md) §2 обл.5 — **≈1388 prompt-токенов/вызов resummarize** («before» для критерия приёмки).

---

<role>
Ты — senior-инженер проекта tg_parser. Ты чинишь единственный **Critical**-дефект code-review: фича F5-C (evolving topic summaries) вызывает LLM, **не передавая ему текст документов**, — сводки не могут обогащаться новым содержанием, а токены при этом сжигаются каждый тик. Твоя работа — сделать так, чтобы ре-суммаризация реально видела материал, и попутно убрать пересоздание LLM-клиента на каждую тему.
</role>

<context>
**Дефект (F-02).** В `tg_parser/services/resummarization_service.py`, метод `resummarize_topic`, строки **277–285** (рабочая копия 2026-07-07): `items_payload` содержит только `source_ref` / `role` / `score` / `justification` элементов бандла. Ни `summary`, ни `text_clean` документов в LLM не уходят. Промпт `prompts/resummarize.yaml` при этом требует «DO NOT invent claims that are not supported by the items» — на входе, где утверждений нет. На практике модель либо перефразирует старую сводку (вызов впустую), либо галлюцинирует из keyword-строк justification. До 10 вызовов × 4096 max_tokens на тик на канал.

**Сопутствующее (F-11, часть O-9a).** Там же: `resolve_llm_config("resummarize")` + `create_llm_client(...)` вызываются **внутри `resummarize_topic`** (строки 322–323), т.е. новый httpx-клиент и rate-limiter-обвязка создаются на каждую тему; клиент закрывается в `finally` того же метода (353–359). При 10 темах/тик это 10 лишних handshake'ов.

**Бюджеты (baseline S0):** сегодня ≈**1388 prompt-токенов/вызов** (метрика `tg_resummarize_tokens_total`, 253 937 prompt / 183 вызова since-restart). Ожидаемый рост от O-1 — умеренный: ~10 элементов окна × ~150 токенов ≈ **+1.5K/вызов**, заведомо в пределах существующего бюджета **50K токенов/тик** (`resummarize_max_tokens_per_tick`).
</context>

<verified_anchors>
Факты проверены по рабочей копии 2026-07-07 — опирайся на них, а не на память:

| Что | Где (файл:строки) | Факт |
|---|---|---|
| `items_payload` | `tg_parser/services/resummarization_service.py:277–285` | dict из `source_ref`, `role`, `score`, `justification`; окно `bundle.items[:window_n]`, `window_n = settings.resummarize_input_window_n` (default 10) |
| Создание клиента | `resummarization_service.py:322–323` (внутри `resummarize_topic`) | `resolve_llm_config("resummarize")` → `create_llm_client(...)`; close в `finally` 353–359; `aclose()` (537–543) — no-op с docstring «clients are short-lived» — обнови при рефакторинге |
| Batch-fetch метод | `tg_parser/storage/sqlalchemy/processed_document_repo.py:163` + порт `tg_parser/storage/ports.py:534` | **`get_by_source_refs(source_refs: list[str]) -> dict[str, ProcessedDocument]`** — уже существует, SELECT включает `text_clean` и `summary`; новый repo-метод НЕ нужен |
| Поля документа | `tg_parser/domain/models.py:105+` (`ProcessedDocument`) | `text_clean: str` (обязательное), `summary: str \| None` |
| Wiring репозиториев | `tg_parser/services/db_context.py:337–358` (`resummarization_repos`) | Сейчас yield'ит только (TopicCardRepo, TopicBundleRepo, TopicCardVersionRepo, Database) — **ProcessedDocumentRepo туда нужно добавить** (на той же processing-сессии) и прокинуть в `ResummarizationService.__init__` |
| Распаковка `resummarization_repos()` | конструктор сервиса: `scheduler_service.py:1158–1168`, `mcp_server.py:2540–2550` (force_resummarize), `cli/topic_cmd.py:143–153`; только распаковка кортежа (сервис НЕ конструируется): `mcp_server.py:2481` (get_topic_versions), `cli/topic_cmd.py:41` (versions), `cli/topic_cmd.py:120` (resummarize --dry-run) | Кортеж распаковывается позиционно в **6 местах** — при расширении кортежа обнови ВСЕ шесть; сервис конструируется только в первых трёх |
| Прямые вызовы `resummarize_topic` | `mcp_server.py:2552` (force_resummarize), `cli/topic_cmd.py:155` | Метод вызывается и МИМО `run_for_channel` — hoist клиента не должен ломать standalone-путь (опциональный параметр client с fallback-созданием — приемлемое решение) |
| Промпт | `prompts/resummarize.yaml` | `user.template` подставляет `{items_json}`; шапка-комментарий и system-описание входа говорят только про refs/scores — скорректируй под новый состав items |
</verified_anchors>

<scope>
**O-1 (закрывает F-02, Critical):**
1. В `resummarize_topic` перед сборкой `items_payload` батчево получить документы окна: `processed_doc_repo.get_by_source_refs([it.source_ref for it in input_items])` — один запрос, не N+1.
2. В каждый элемент `items_payload` добавить содержание: `summary` документа и/или усечённый `text_clean` (~**400–600 символов** per item; порог — константа или настройка, на твоё усмотрение, но усечение обязано покрываться тестом). Документ может отсутствовать в БД (ref без записи) — элемент остаётся с пустым содержанием, не падаем.
3. Прокинуть `ProcessedDocumentRepo` в сервис: расширить `resummarization_repos()` в `db_context.py` (та же processing-сессия) и конструктор `ResummarizationService`; обновить **все 6 мест распаковки кортежа** (3 конструируют сервис — scheduler hook, MCP force_resummarize, CLI resummarize; 3 только распаковывают — MCP get_topic_versions, CLI versions, CLI dry-run; точные file:line в `<verified_anchors>`).
4. Обновить `prompts/resummarize.yaml`: описание входа (комментарий-шапка + system.prompt) должно соответствовать новому составу items — теперь инструкция «DO NOT invent claims not supported by the items» выполнима. Версию промпта поднять (metadata.version).

**O-9a (часть F-11):**
5. Поднять `resolve_llm_config` + `create_llm_client` из `resummarize_topic` в `run_for_channel` — **один клиент на тик**, закрытие один раз в конце тика (`try/finally`). Standalone-вызовы `resummarize_topic` (force_resummarize из MCP, CLI) должны продолжать работать — например, через опциональный параметр клиента с созданием по месту, если не передан. Учти: `provider`/`model` используются внутри `resummarize_topic` и после создания клиента (метрики `record_resummarize_outcome(model=f"{provider}/{model}")` на строках ~350/~377/~523, поля `provider`/`model` в outcome-dict на ~533–534) — при hoist'е передавай их вместе с клиентом (напр. кортеж `(client, provider, model)`), а не только клиент; клиент создавай ПОСЛЕ проверки кандидатов (ранние return'ы `run_for_channel` — disabled / нет кандидатов — не должны стоить лишнего handshake'а). Docstring `aclose()` привести в соответствие.
</scope>

<out_of_scope>
- **O-9b** — retrieval/embedding-клиент (`retrieval_service.py`) — это S7. Не трогать.
- **Триггеры и лимиты ре-суммаризации** — `resummarize_trigger_n` (N=5), `resummarize_max_per_tick` (10 тем/тик), `resummarize_max_tokens_per_tick` (50K/тик), `resummarize_input_window_n`, advisory-lock, версионирование, optimistic locking — поведение не менять.
- **Контракты и миграции** — `docs/contracts/**` (JSON Schema) и Alembic не трогать вообще (workflow §7). Схема БД не меняется — `get_by_source_refs` уже существует.
- Любые файлы за пределами: `resummarization_service.py`, `prompts/resummarize.yaml`, `db_context.py` (только расширение `resummarization_repos`), все 6 мест распаковки `resummarization_repos()` (см. `<verified_anchors>`), тесты. Никакого попутного рефакторинга соседнего кода.
</out_of_scope>

<acceptance_criteria>
Сессия принята, когда ВСЁ нижеследующее доказано тестами/замерами:
1. **Payload содержит материал:** для темы с документами в БД каждый элемент `items_payload` несёт `summary` и/или усечённый `text_clean`; усечение до ~400–600 символов работает (длинный документ не уходит целиком). Assert на реальный текст промпта (существующий паттерн — `_CapturingClient` в `tests/test_f5c_resummarization_service.py:844+`).
2. **Батч, не N+1:** документы окна получены одним вызовом `get_by_source_refs`.
3. **Рост токенов ограничен (верхняя граница):** per-item усечение (~400–600 символов) покрыто тестом — это механическая гарантия верхней границы (оценочно +1.5–3.5K/вызов к baseline ≈1388 в зависимости от того, кладём ли и `summary`, и `text_clean`; заведомо в пределах 50K/тик); cap-логика `run_for_channel` не изменена. Live-сравнение по метрике `tg_resummarize_tokens_total` (шаблон снапшота — S0 §4, блок 1a) — если стек недоступен из сессии, зафиксируй в PR команду снятия и ожидаемый диапазон.
4. **Один клиент на тик:** в `run_for_channel` `create_llm_client` вызывается ровно один раз независимо от числа кандидатов (тест с mock'ом на `tg_parser.services.resummarization_service.create_llm_client` — patch-target уже используется в тестах, см. `_patch_llm`); клиент корректно закрывается; standalone `resummarize_topic` работает без внешнего клиента.
5. **Сводки отражают новый материал:** в тесте факт из `summary`/`text_clean` документа доходит до user-prompt LLM (композиционная проверка; содержательную проверку на dev-канале фиксируем в PR как ручной шаг).
6. Все существующие тесты зелёные в обоих режимах (см. test_strategy), `prompts/resummarize.yaml` валиден для `PromptLoader`.
</acceptance_criteria>

<test_strategy>
Workflow §5.4: для баг-находки — сначала **падающий тест (RED), потом фикс (GREEN)**.

1. **RED:** новый тест «payload ре-суммаризации содержит текст/summary документов окна» — на текущем коде падает (payload содержит только refs/scores). Зафиксируй падение, потом реализуй O-1. Для RED понадобится посеять `processed_documents` (через `SAProcessedDocumentRepo.upsert*`) под `source_ref`'ы бандла — существующий `_seed` в `test_f5c_resummarization_service.py` сеет только карточки/бандлы, документов там нет.
2. **GREEN + новые тесты:**
   - состав payload: `summary`/`text_clean` присутствуют; усечение длинного `text_clean`; отсутствующий в БД документ не роняет вызов;
   - «клиент создаётся один раз на `run_for_channel`» (несколько кандидатов → один `create_llm_client`);
   - standalone `resummarize_topic` (путь force_resummarize) работает после hoist'а;
   - `resummarize.yaml` остаётся валидным — прогнать/при необходимости дополнить `tests/test_prompt_loader.py`.
3. **Существующие тесты (из плана S1) — прогнать все:** `tests/test_f5c_resummarization_service.py` (21 тестов; фикстуры `test_db`, `_FakeLLMClient`, `_patch_llm`/`_patch_resolve`/`_patch_embed` — переиспользуй их), `tests/test_resummarize_metrics.py`, `tests/test_f5c_scheduler_hook.py`, `tests/test_f5c_counter_increment.py`, `tests/test_f5c_topic_card_repo.py`, `tests/test_prompt_loader.py`.
   **Дополнительно — ломаются расширением кортежа `resummarization_repos()` (обнови fakes):** `tests/test_f5c_mcp_tools.py` (`_fake_resummarization_repos` на строке ~122 yield'ит **4-кортеж** `(card_repo, "_bundle_repo", version_repo, "_db")` — патчится в ~10 тестах) и `tests/test_f5c_cli.py` (тот же паттерн, ~11 патч-сайтов). Также в `tests/test_f5c_scheduler_hook.py` `_ReposCtx.__aenter__` (строка ~67) возвращает жёстко зашитый 4-кортеж — тоже обнови под новый состав.
4. **Режимы (tests/README.md):** *default* (`pytest -q`) обязателен; *PR standard* (`TEST_POSTGRES=1`) обязателен — затронут repo-фетч и wiring сессий.
5. **Метрика:** сравнение resummarize input_tokens before/after против baseline ≈1388/вызов — по шаблону S0 §4 (блок 1a); если live-стек недоступен из сессии — зафиксируй в PR готовую команду снятия и ожидание (~2.9K/вызов).
</test_strategy>

<workflow>
Нормативно — workflow §2/§3/§5:
1. Ветка **`fix/S1-resummarize-text`** от `main`.
2. Реализация → RED→GREEN → оба режима тестов зелёные.
3. Обновить [`BUG_LOG.md`](BUG_LOG.md): F-02 (со ссылкой на отчёт ревью) — addressed этой сессией; упомянуть O-9a.
4. Self-review тестов и кода — отдельными агентами со свежим контекстом; **bugbot по изменениям ветки — обязательный гейт**.
5. Зелёные тесты + зелёный bugbot → commit + push → **PR** → merge в `main`.
6. **Деплой — НЕ соло:** S1 выкатывается в составе безопасного блока S1–S3 (workflow §3). В этой сессии деплой не выполняется.
7. `git commit` — только в рамках этого цикла, не раньше зелёного статуса (AGENTS.md: без явного цикла коммиты запрещены; здесь цикл согласован workflow-документом).
</workflow>

<recap>
| Находка | Что делаем | Приёмка |
|---|---|---|
| F-02 (Critical) / O-1 | `summary` + усечённый `text_clean` в `items_payload`; батч через существующий `get_by_source_refs`; wiring repo через `resummarization_repos`; обновлённый `resummarize.yaml` | payload содержит материал; усечение покрыто тестом; рост ~+1.5K/вызов к baseline 1388; 50K/тик не нарушен |
| F-11 (часть) / O-9a | Клиент LLM создаётся в `run_for_channel`, один на тик | `create_llm_client` ровно 1 раз на тик (тест); standalone-путь жив |
</recap>

---

*Строки кода — по рабочей копии 2026-07-07. При смещении нумерации ориентируйся на имена символов: `items_payload`, `resummarize_topic`, `run_for_channel`, `get_by_source_refs`, `resummarization_repos`.*
