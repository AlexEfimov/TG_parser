# Changelog

All notable changes to TG_parser will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [3.0.0-alpha.3] - 2025-12-28

### Added

#### Agent Observability (Session 19 Phase 3C) ⭐
- **CLI группа `agents`**: новые команды для мониторинга агентов
  - `agents list` — список всех агентов с фильтрами (--type, --active)
  - `agents status <name>` — статистика агента (--days для периода)
  - `agents history <name>` — история задач (--limit, --errors)
  - `agents cleanup` — очистка истёкших записей (--dry-run, --archive)
  - `agents handoffs` — статистика handoff'ов (--stats, --agent)
  - `agents archives` — список архивных файлов
- **API Endpoints (Agent Observability)**:
  - `GET /api/v1/agents` — список агентов с метаданными
  - `GET /api/v1/agents/{name}` — информация об агенте
  - `GET /api/v1/agents/{name}/stats` — статистика агента за период
  - `GET /api/v1/agents/{name}/history` — история задач с пагинацией
  - `GET /api/v1/agents/stats/handoffs` — статистика handoff'ов
- **AgentHistoryArchiver**: архивация истёкших записей
  - Экспорт в NDJSON.gz формат
  - Поддержка task_history и handoff_history
  - Автоматическая очистка после архивации
  - Список архивов с метаданными
- **Pydantic Response Models**: типизированные ответы API
  - `AgentListResponse`, `AgentInfoResponse`
  - `AgentStatsResponse`, `TaskHistoryResponse`
  - `HandoffStatsResponse`

### Configuration
- `AGENT_ARCHIVE_ENABLED` — включить архивацию (default: false)
- `AGENT_ARCHIVE_PATH` — путь для архивов (default: ./data/archives)

### Tests
- **15 новых тестов** в `tests/test_agents_observability.py`
- Общее количество тестов: **340** (было 325)
- Все тесты проходят ✅

### Documentation
- Создан `docs/notes/SESSION19_PHASE3C_COMPLETE.md`
- Создан `docs/notes/START_PROMPT_SESSION20_PHASE3D.md`
- Обновлены: DEVELOPMENT_ROADMAP.md, DOCUMENTATION_INDEX.md, README.md, CHANGELOG.md
- Обновлены: tests/README.md, docs/notes/README.md

---

## [3.0.0-alpha.2] - 2025-12-28

### Added

#### Agent State Persistence (Session 18 Phase 3B) ⭐
- **AgentPersistence Layer**: unified интерфейс для работы с persistence
  - Сохранение состояния агентов при регистрации
  - Восстановление статистики при рестарте
  - Полное хранение input/output задач с TTL
  - Агрегированная статистика по дням
- **AgentStateRepo**: хранение метаданных и статистики агентов
  - Сохранение capabilities, model, provider
  - Накопление total_tasks, total_errors, avg_processing_time
  - Автообновление при выполнении задач
- **TaskHistoryRepo**: полная история задач
  - Хранение полного input_json/output_json
  - Настраиваемый TTL через `expires_at`
  - Фильтрация по агенту, каналу, датам
  - Метод `cleanup_expired()` для очистки
- **AgentStatsRepo**: агрегированная статистика по дням
  - Ежедневные агрегаты: total_tasks, successful, failed
  - min/max/avg processing time
  - Сохраняется даже после очистки task_history
- **HandoffHistoryRepo**: история handoffs между агентами
  - Tracking статусов: pending → accepted → completed
  - Время обработки и ошибки
  - Статистика по парам агентов
- **Registry интеграция**:
  - `register_with_persistence()` — регистрация + сохранение + восстановление
  - `unregister_with_persistence()` — отмена + пометка inactive
  - `record_task_completion_with_persistence()` — запись в history + stats

### Database
- **4 новые таблицы** в `processing_storage.sqlite`:
  - `agent_states` — состояние агентов с метаданными и статистикой
  - `task_history` — полная история задач с TTL
  - `agent_stats` — ежедневная агрегированная статистика
  - `handoff_history` — история handoffs между агентами

### Configuration
- `AGENT_RETENTION_DAYS` — TTL для task_history (default: 14)
- `AGENT_RETENTION_MODE` — delete | export (default: delete)
- `AGENT_ARCHIVE_PATH` — путь для архивации
- `AGENT_STATS_ENABLED` — включить агрегацию статистики
- `AGENT_PERSISTENCE_ENABLED` — включить persistence

### Tests
- **25 новых тестов** в `tests/test_agent_persistence.py`
- Общее количество тестов: **325** (было 300)
- Все тесты проходят ✅

### Documentation
- Создан `docs/notes/SESSION18_PHASE3B_COMPLETE.md`
- Создан `docs/notes/START_PROMPT_SESSION19_PHASE3C.md`
- Обновлены: DEVELOPMENT_ROADMAP.md, DOCUMENTATION_INDEX.md, architecture.md, README.md, CHANGELOG.md

---

## [3.0.0-alpha.1] - 2025-12-28

### Added

#### Multi-Agent Architecture (Session 17 Phase 3A) ⭐
- **Base Agent Protocol**: стандартизированный интерфейс для всех агентов
  - `BaseAgent` абстрактный класс с lifecycle методами
  - `AgentInput`/`AgentOutput` типизированные контракты
  - `AgentCapability`/`AgentType` enum'ы для классификации
- **Agent Registry**: централизованное управление агентами
  - Регистрация/отмена регистрации агентов
  - Поиск по типу и capabilities
  - Статистика выполнения задач
  - Health checks
- **Handoff Protocol**: обмен данными между агентами
  - `HandoffRequest`/`HandoffResponse` структуры
  - `HandoffStatus` для отслеживания состояния
  - Приоритеты и контекст передачи
- **OrchestratorAgent**: координация workflow
  - Управление workflow'ами
  - Маршрутизация задач к специализированным агентам
  - Lifecycle management для всех агентов
- **Specialized Agents**:
  - `ProcessingAgent` — очистка текста, извлечение тем/entities, routing (simple/deep)
  - `TopicizationAgent` — кластеризация документов по темам
  - `ExportAgent` — экспорт в NDJSON/JSON форматы
- **CLI флаг `--multi-agent`**: активация multi-agent режима
  - `tg-parser process --channel @lab --multi-agent`
  - `tg-parser process --channel @lab --multi-agent --provider anthropic`

### Architecture
- Hybrid подход: Specialized Agents (Variant A) + элементы Agentic Workflow (Variant C)
- Routing внутри ProcessingAgent для адаптивной обработки
- Расширяемая архитектура через Agent Registry

### Tests
- **42 новых теста** в `tests/test_multi_agent.py`
- Общее количество тестов: **300** (было 258)
- Все тесты проходят ✅

### Documentation
- Создан `docs/notes/SESSION17_PHASE3A_COMPLETE.md`
- Создан `docs/notes/START_PROMPT_SESSION18_PHASE3B.md`
- Обновлены: DEVELOPMENT_ROADMAP.md, DOCUMENTATION_INDEX.md, architecture.md, README.md
- Обновлена пользовательская документация: USER_GUIDE.md, pipeline.md, LLM_SETUP_GUIDE.md, QUICKSTART_v1.2.md

---

## [2.0.0-alpha.4] - 2025-12-28

### Added

#### API Production (Session 16 Phase 2F) ⭐
- **API Key Authentication**: защита endpoints через X-API-Key header
  - Конфигурируемые ключи через `API_KEYS` environment variable
  - Режим разработки (auth опционален) и production (auth обязателен)
- **Rate Limiting**: защита от перегрузки через slowapi
  - Настраиваемые лимиты для `/process`, `/export` endpoints
  - По умолчанию: 10/min для process, 20/min для export
- **Webhooks**: уведомления о завершении задач
  - HMAC-SHA256 подписи для верификации
  - Retry с экспоненциальным backoff
  - Стандартный payload для job completion/failure
- **Request Logging**: структурированное логирование с X-Request-ID
  - Автоматическая генерация UUID для каждого запроса
  - Сохранение пользовательского X-Request-ID
  - Duration tracking
- **Persistent Job Storage**: SQLite хранилище для job state
  - `Job` модель с полным lifecycle tracking
  - `JobRepo` интерфейс (порт) и SQLite реализация
  - `JobStore` singleton для API routes
  - Таблица `api_jobs` в processing_storage.sqlite
- **Configurable CORS**: CORS_ORIGINS через environment

### Tests
- **38 новых тестов** (22 в test_api_security.py, 16 в test_job_storage.py)
- Общее количество тестов: **258** (было 219)
- Исправлено зависание тестов из-за незакрытых SQLite соединений
- Все тесты проходят ✅

### Documentation
- Создан `docs/notes/SESSION16_PHASE2F_COMPLETE.md`
- Обновлены CHANGELOG.md, DEVELOPMENT_ROADMAP.md, DOCUMENTATION_INDEX.md, README.md

---

## [2.0.0-alpha.3] - 2025-12-28

### Added

#### Hybrid Agent Mode (Session 15 Phase 2E) ⭐
- **Pipeline Tool**: v1.2 pipeline как инструмент агента
  - `process_with_pipeline` — глубокая обработка через проверенный pipeline
  - `PipelineResult` — структурированный результат с metadata
  - Автоматический fallback на basic processing при недоступности pipeline
  - On-demand создание pipeline если не передан в контексте
- **AgentContext update**: добавлено поле `pipeline` для hybrid mode
- **TGProcessingAgent update**: 
  - Новый параметр `use_pipeline_tool` для включения pipeline tool
  - Новый параметр `pipeline` для передачи экземпляра pipeline
  - Динамическое формирование инструкций агента для hybrid mode
- **CLI флаг `--hybrid`**: включает v1.2 pipeline как tool агента
  - `tg-parser process --channel @lab --agent --hybrid` — basic + pipeline (4 tools)
  - `tg-parser process --channel @lab --agent --agent-llm --hybrid` — LLM + pipeline (2 tools)
- **InMemoryProcessedDocumentRepo**: in-memory репозиторий для on-demand pipeline

### Performance
- **Hybrid режим**: адаптивная обработка — простые сообщения через basic tools, сложные через pipeline
- Agent выбирает оптимальный инструмент в зависимости от сложности сообщения

### Tests
- **32 новых теста** в `tests/test_agents_phase2e.py`
- Общее количество тестов: **219** (было 187)
- Все тесты проходят ✅

### Documentation
- Создан `docs/notes/SESSION15_PHASE2E_COMPLETE.md`
- Обновлены CHANGELOG.md, DEVELOPMENT_ROADMAP.md, DOCUMENTATION_INDEX.md

---

## [2.0.0-alpha.2] - 2025-12-27

### Added

#### Agents Integration (Session 14 Phase 2C) ⭐
- **LLM-Enhanced Tools**: глубокий семантический анализ через LLM
  - `analyze_text_deep` — комплексный анализ с key_points и sentiment
  - `extract_topics_llm` — семантическое извлечение тем
  - `extract_entities_llm` — NER через LLM
- **AgentContext**: dataclass для передачи LLM client в tools
- **DeepAnalysisResult**: расширенная модель с key_points и sentiment
- **CLI флаги**:
  - `--agent` — использовать agent-based processing
  - `--agent-llm` — включить LLM-enhanced tools
- **Multi-provider support**: агент поддерживает OpenAI, Anthropic, Gemini, Ollama
- **Quality comparison script**: `scripts/compare_agents_pipeline.py`

### Performance
- **Agent Basic**: ~0.3ms/сообщение (1000x быстрее pipeline) без LLM вызовов
- Автоматический fallback к pattern matching при отсутствии LLM

### Tests
- **14 новых тестов** для Phase 2C
- Общее количество тестов: **187** (было 174)
- Все тесты проходят ✅

### Documentation
- Обновлён USER_GUIDE.md с секцией об Agent-based Processing
- Обновлён README.md с новыми CLI флагами
- Создан SESSION14_PHASE2C_COMPLETE.md

---

## [2.0.0-alpha.1] - 2025-12-27

### Added

#### HTTP API (Session 14 Phase 2A) ⭐
- **FastAPI HTTP API**: полноценный REST API для TG_parser
- **8 endpoints** в трёх группах:
  - `/health`, `/status` — health checks и статус системы
  - `/api/v1/process`, `/api/v1/status/{job_id}`, `/api/v1/jobs` — управление обработкой
  - `/api/v1/export`, `/api/v1/export/status/{job_id}`, `/api/v1/export/download/{job_id}` — экспорт
- **CLI команда `tg-parser api`**: запуск сервера с параметрами `--port`, `--host`, `--reload`
- **OpenAPI/Swagger**: автодокументация на `/docs` и `/redoc`
- **CORS middleware**: поддержка cross-origin запросов
- **Job-based processing**: асинхронная обработка с отслеживанием статуса

#### OpenAI Agents SDK PoC (Session 14 Phase 2B) ⭐
- **Новый модуль `tg_parser/agents/`**: интеграция с OpenAI Agents SDK
- **TGProcessingAgent**: агент для обработки сообщений с тремя tools:
  - `clean_text` — очистка и нормализация текста
  - `extract_topics` — извлечение тем и генерация summary
  - `extract_entities` — извлечение сущностей (email, URL, phone, hashtags, etc.)
- **Function tools**: используют `@function_tool` декоратор из agents SDK
- **Batch processing**: `process_batch_with_agent()` с настройкой concurrency

### Tests
- **24 теста для HTTP API** в `tests/test_api.py`
- **24 теста для Agents** в `tests/test_agents.py`  
- Общее количество тестов: 174 (было 126)
- Все тесты проходят ✅

### Dependencies
- `openai-agents>=0.6` — OpenAI Agents SDK
- `fastapi>=0.115`, `uvicorn>=0.32` — уже были для API

## [1.2.0] - 2025-12-27

### Added

#### Multi-LLM Support ⭐
- **AnthropicClient**: поддержка Claude models (claude-sonnet-4-20250514)
- **GeminiClient**: поддержка Google Gemini models (gemini-2.0-flash-exp, gemini-1.5-pro)
- **OllamaClient**: поддержка локальных LLM через Ollama (qwen3:8b, llama3.2, mistral, etc.)
- **Factory**: `create_llm_client()` для создания клиентов по провайдеру
- CLI флаги `--provider` и `--model` для выбора LLM
- Environment variables: `LLM_PROVIDER`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`

#### Performance
- **Parallel processing**: флаг `--concurrency` для параллельной обработки сообщений
- `ProcessingPipelineImpl._process_batch_parallel()` с `asyncio.Semaphore`
- Реальное ускорение: до 3x при `--concurrency 5` для облачных провайдеров

#### Docker & CI/CD
- **Dockerfile**: multi-stage build для production (370MB image)
- **docker-compose.yml**: compose файл с опциональным Ollama service
- **GitHub Actions CI**: автоматическое тестирование, линтинг, Docker build
- Markdown link checking в CI

#### PromptLoader Integration
- `ProcessingPipelineImpl` использует `PromptLoader` по умолчанию
- Model settings (temperature, max_tokens) загружаются из YAML
- Fallback на hardcoded промпты если YAML не найден

#### Documentation
- **TESTING_RESULTS_v1.2.md**: полный отчёт о тестировании
- **MIGRATION_GUIDE_v1.1_to_v1.2.md**: руководство по миграции
- Обновлённые README.md и USER_GUIDE.md с Multi-LLM примерами

### Fixed
- **Anthropic JSON parsing**: Claude иногда возвращает JSON в markdown блоках (`\`\`\`json`), добавлена функция `extract_json_from_response()` для корректного парсинга
- **Anthropic model name**: обновлено с устаревшего `claude-3-5-sonnet-20241022` на актуальное `claude-sonnet-4-20250514`
- **docker-compose.yml**: удалён устаревший атрибут `version`

### Changed
- `tg_parser/processing/pipeline.py`: обновлена `create_processing_pipeline()` для Multi-LLM
- `tg_parser/cli/process_cmd.py`: добавлены параметры `provider`, `model`, `concurrency`
- `tg_parser/cli/app.py`: обновлена команда `process` с новыми флагами
- `tg_parser/config/settings.py`: добавлен `gemini_api_key`

### Performance Benchmarks

| Provider | Model | Throughput | Quality |
|----------|-------|------------|---------|
| OpenAI | gpt-4o-mini | 0.120 msg/s | Good |
| Anthropic | claude-sonnet-4-20250514 | 0.121 msg/s | Best (90% entities) |
| Gemini | gemini-2.0-flash-exp | 0.342 msg/s | Great (fastest!) |
| Ollama | qwen3:8b | 0.024 msg/s | Good |

### Tests
- Добавлено 23 новых теста в `tests/test_llm_clients.py`
- Общее количество тестов: 126 (было 103)
- Все тесты проходят ✅
- Протестированы все 4 LLM провайдера на реальных данных

## [1.1.0] - 2025-12-26

### Added
- **Configurable Prompts (YAML)**: Prompts can now be customized via YAML files in `prompts/` directory
  - `prompts/processing.yaml` - Processing prompts
  - `prompts/topicization.yaml` - Topicization prompts
  - `prompts/supporting_items.yaml` - Supporting items prompts
  - `prompts/README.md` - Documentation for YAML format
- **PromptLoader class** (`tg_parser/processing/prompt_loader.py`): 
  - Loads prompts from YAML with fallback to defaults
  - Caching support
  - Helper methods: `get_system_prompt()`, `get_user_template()`, `get_model_settings()`
- **`--retry-failed` flag** for `process` command: Retry only failed messages
- **`list_all()` method** in ProcessedDocumentRepo: Export all channels without filter
- **`get_channel_usernames()` method** in IngestionStateRepo: Get channel username mappings
- **Improved LLM response validation**: 
  - Validates required fields
  - Fills defaults for optional fields
  - Normalizes entity confidence scores
- **18 new tests** for PromptLoader (total: 103 tests)

### Fixed
- Export command now works without `--channel` filter
- Telegram URLs now correctly include channel usernames when available

### Changed
- Dependencies: added `PyYAML>=6.0`

### Technical Debt Resolved
- Removed TODO at `export_cmd.py:82` (list_all implemented)
- Removed TODO at `export_cmd.py:99` (usernames implemented)

## [1.0.0] - 2025-12-25

### Added
- Initial production-ready release
- **Ingestion Pipeline**: Telethon-based Telegram message collection
  - Posts and comments support
  - Incremental and snapshot modes
  - Cursor-based pagination
- **Processing Pipeline**: LLM-based message processing
  - Text cleaning and normalization
  - Entity extraction
  - Topic detection
  - Language detection
- **Topicization Pipeline**: Message clustering into topics
  - Singleton and cluster topics
  - Anchor-based topic cards
  - Supporting items with relevance scores
- **Export System**:
  - `kb_entries.ndjson` - Knowledge base entries
  - `topics.json` - Topic catalog
  - `topic_<id>.json` - Detailed topic files
- **CLI Commands**:
  - `init` - Initialize databases
  - `add-source` - Add ingestion source
  - `ingest` - Run ingestion
  - `process` - Run processing
  - `topicize` - Run topicization
  - `export` - Export artifacts
  - `run` - One-shot full pipeline
- **Storage**:
  - SQLite-based storage (3 databases)
  - Idempotent operations
  - Cursor management

### Technical
- 85 tests passing
- 99.76% success rate on 846 real messages
- Pydantic v2 domain models
- Async/await architecture
- Type hints throughout

