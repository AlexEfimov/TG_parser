# Changelog

All notable changes to TG_parser will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

