# Changelog

All notable changes to TG_parser will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

