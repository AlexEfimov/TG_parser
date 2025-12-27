# Session 11: v1.1 Developer Agent — "Stability & Configurability"

## Роль

Привет! Ты Developer Agent для реализации версии **v1.1.0** проекта TG_parser. Твоя задача — реализовать **Configurable Prompts (YAML)** и устранить технический долг.

---

## 📋 Контекст проекта

**TG_parser** — production-ready система для сбора контента из Telegram-каналов, обработки через LLM и экспорта структурированных данных.

### Текущее состояние (v1.0)
- ✅ **Стабильность**: 99.76% успешность на 846 реальных сообщениях
- ✅ **Тесты**: 85 тестов, 100% проходят
- ✅ **Production-ready**: полный E2E pipeline работает
- ⚠️ **Промпты**: хардкожены в Python файлах
- ⚠️ **TODOs**: 2 нерешённых в коде

### Архитектура
```
tg_parser/
├── cli/           # Typer CLI (7 команд)
├── config/        # Pydantic-settings
├── domain/        # Доменные модели (Pydantic v2)
├── ingestion/     # Telethon client
├── processing/    # LLM processing ← ОСНОВНОЙ ФОКУС
│   ├── llm/       # OpenAI client
│   ├── pipeline.py
│   ├── prompts.py           ← Вынести в YAML
│   ├── topicization_prompts.py  ← Вынести в YAML
│   └── topicization.py
├── storage/       # SQLite репозитории
└── export/        # Экспорт KB entries + topics
```

---

## 📚 Документы для получения информации

### 🔴 ОБЯЗАТЕЛЬНО прочитать перед началом работы

| Документ | Описание | Приоритет |
|----------|----------|-----------|
| `DEVELOPMENT_ROADMAP.md` | **План v1.1** — детальные задачи и критерии | ⭐⭐⭐ |
| `docs/LLM_PROMPTS.md` | Текущие промпты — что нужно вынести в YAML | ⭐⭐⭐ |
| `tg_parser/processing/prompts.py` | Исходный код промптов processing | ⭐⭐⭐ |
| `tg_parser/processing/topicization_prompts.py` | Исходный код промптов topicization | ⭐⭐⭐ |

### 🟡 Для контекста и понимания системы

| Документ | Описание |
|----------|----------|
| `README.md` | Общий обзор, CLI команды |
| `DOCUMENTATION_INDEX.md` | Навигация по документации (32 документа) |
| `docs/architecture.md` | Архитектура, DDL схемы |
| `docs/pipeline.md` | Детали pipeline |
| `docs/technical-requirements.md` | Технические требования TR-* |
| `docs/DATA_FLOW.md` | Поток данных через систему |

### 🟢 Для справки по реализации

| Документ | Описание |
|----------|----------|
| `tg_parser/processing/pipeline.py` | Processing pipeline — где используются промпты |
| `tg_parser/processing/topicization.py` | Topicization — где используются промпты |
| `tg_parser/cli/export_cmd.py` | Содержит TODOs для исправления |
| `tg_parser/config/settings.py` | Текущие настройки — добавить `prompts_dir` |
| `tests/test_processing_pipeline.py` | Существующие тесты processing |

---

## 📤 Документы для передачи информации следующим агентам

### Обязательно обновить после завершения

| Документ | Что обновить |
|----------|--------------|
| `docs/notes/SESSION_HANDOFF_v1.1.md` | ⭐ **СОЗДАТЬ** — handoff для v1.2 агента |
| `DEVELOPMENT_ROADMAP.md` | Отметить выполненные задачи v1.1 |
| `docs/notes/current-state.md` | Обновить текущее состояние |
| `CHANGELOG.md` | ⭐ **СОЗДАТЬ** — история изменений |

### Структура SESSION_HANDOFF_v1.1.md

```markdown
# Session 11 Handoff — v1.1.0 Complete

## ✅ Что реализовано
- [ ] Configurable Prompts (YAML)
- [ ] list_all() в ProcessedDocumentRepo
- [ ] Usernames из IngestionStateRepo
- [ ] Auto-retry для failed messages
- [ ] Улучшенная валидация LLM

## 📁 Новые файлы
- prompts/processing.yaml
- prompts/topicization.yaml
- prompts/supporting_items.yaml
- tg_parser/processing/prompt_loader.py

## ⚠️ Известные проблемы
...

## 🚀 Готово для v1.2
- [ ] Multi-LLM support можно реализовать
- [ ] Промпты готовы для разных моделей
```

---

## 🎯 Задачи v1.1.0 (приоритизированы)

### Неделя 1 — High Priority

#### Задача 1: ⭐ Configurable Prompts (YAML)
**Время**: 6-8 часов  
**Приоритет**: HIGHEST

**Создать структуру:**
```
prompts/
├── processing.yaml       # Processing промпты
├── topicization.yaml     # Topicization промпты
├── supporting_items.yaml # Supporting items промпты
└── README.md             # Документация формата
```

**Реализовать PromptLoader:**
```python
# tg_parser/processing/prompt_loader.py
import yaml
from pathlib import Path
from typing import Any

class PromptLoader:
    """Load prompts from YAML files with fallback to defaults."""
    
    def __init__(self, prompts_dir: Path | None = None):
        self.prompts_dir = prompts_dir or Path("prompts")
        self._cache: dict[str, dict] = {}
    
    def load(self, name: str) -> dict[str, Any]:
        """Load prompt configuration from YAML file.
        
        Args:
            name: Prompt name (e.g., "processing", "topicization")
            
        Returns:
            Dict with prompt configuration
        """
        if name in self._cache:
            return self._cache[name]
            
        path = self.prompts_dir / f"{name}.yaml"
        if path.exists():
            with open(path, encoding="utf-8") as f:
                config = yaml.safe_load(f)
        else:
            # Fallback to built-in defaults
            config = self._get_default(name)
            
        self._cache[name] = config
        return config
    
    def _get_default(self, name: str) -> dict[str, Any]:
        """Get default prompts (current hardcoded values)."""
        from . import prompts, topicization_prompts
        
        defaults = {
            "processing": {
                "system": {"prompt": prompts.PROCESSING_SYSTEM_PROMPT},
                "user": {"template": prompts.PROCESSING_USER_PROMPT_TEMPLATE},
                "model": {"temperature": 0, "max_tokens": 4096},
            },
            "topicization": {
                "system": {"prompt": topicization_prompts.TOPICIZATION_SYSTEM_PROMPT},
                "user": {"template": topicization_prompts.TOPICIZATION_USER_PROMPT_TEMPLATE},
                "model": {"temperature": 0, "max_tokens": 8192},
            },
            # ... и т.д.
        }
        return defaults.get(name, {})
    
    def get_system_prompt(self, name: str) -> str:
        """Get system prompt for specified prompt type."""
        config = self.load(name)
        return config.get("system", {}).get("prompt", "")
    
    def get_user_template(self, name: str) -> str:
        """Get user prompt template."""
        config = self.load(name)
        return config.get("user", {}).get("template", "")
    
    def get_model_settings(self, name: str) -> dict:
        """Get model settings (temperature, max_tokens, etc.)."""
        config = self.load(name)
        return config.get("model", {})
```

**Формат YAML файла (prompts/processing.yaml):**
```yaml
# TG_parser Processing Prompts
# Version: 1.0.0
# 
# Этот файл содержит промпты для обработки сообщений через LLM.
# Редактируйте для кастомизации под вашу задачу.

metadata:
  version: "1.0.0"
  description: "Prompts for processing Telegram messages"
  author: "TG_parser team"

system:
  prompt: |
    You are a text processing assistant for Telegram channel messages.
    
    Your task is to analyze the message and extract structured information.
    
    For each message, provide:
    1. text_clean: Cleaned and normalized text (remove formatting artifacts, fix typos)
    2. summary: Brief summary in 1-2 sentences (or null if message is too short)
    3. topics: List of 3-7 relevant topics/themes
    4. entities: List of named entities (people, organizations, products, etc.)
    5. language: Detected language code (ru, en, etc.)
    
    IMPORTANT:
    - Respond in the SAME language as the input message
    - Output must be valid JSON
    - All fields are required (use null for optional empty values)

user:
  template: |
    Process the following Telegram message:
    
    ---
    {text}
    ---
    
    Channel: {channel_id}
    Message ID: {message_id}
    Date: {date}
    
    Respond with JSON:
    {{
      "text_clean": "...",
      "summary": "..." or null,
      "topics": ["topic1", "topic2", ...],
      "entities": ["entity1", "entity2", ...],
      "language": "ru" or "en" or ...
    }}
    
  variables:
    - text        # Текст сообщения
    - channel_id  # ID канала
    - message_id  # ID сообщения
    - date        # Дата сообщения (опционально)

model:
  temperature: 0
  max_tokens: 4096
  
# Для GPT-5 (будущая поддержка в v2.0)
gpt5:
  reasoning_effort: low    # minimal | low | medium | high
  verbosity: low           # low | medium | high
```

**Интеграция в pipeline.py:**
```python
# tg_parser/processing/pipeline.py

from .prompt_loader import PromptLoader

class ProcessingPipeline:
    def __init__(self, llm_client, prompt_loader: PromptLoader | None = None):
        self.llm = llm_client
        self.prompts = prompt_loader or PromptLoader()
    
    async def process_message(self, message: RawTelegramMessage) -> ProcessedDocument:
        system_prompt = self.prompts.get_system_prompt("processing")
        user_template = self.prompts.get_user_template("processing")
        model_settings = self.prompts.get_model_settings("processing")
        
        user_prompt = user_template.format(
            text=message.text,
            channel_id=message.channel_id,
            message_id=message.message_id,
            date=message.date.isoformat() if message.date else "",
        )
        
        response = await self.llm.complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            **model_settings,
        )
        # ... парсинг ответа
```

**CLI флаг:**
```python
# tg_parser/cli/app.py

@app.callback()
def main(
    prompts_dir: Path = typer.Option(
        None,
        "--prompts-dir",
        help="Custom prompts directory (default: ./prompts)",
    ),
):
    """TG_parser CLI."""
    if prompts_dir:
        # Сохранить в контексте для использования командами
        ctx.obj["prompts_dir"] = prompts_dir
```

**Критерии готовности:**
- [ ] Структура `prompts/` создана с 3 YAML файлами
- [ ] `PromptLoader` реализован с fallback на defaults
- [ ] `pipeline.py` использует `PromptLoader`
- [ ] `topicization.py` использует `PromptLoader`
- [ ] CLI флаг `--prompts-dir` работает
- [ ] `prompts/README.md` документирует формат
- [ ] Тесты для `PromptLoader` написаны
- [ ] Существующие тесты проходят

---

#### Задача 2: Добавить `list_all()` в ProcessedDocumentRepo
**Время**: 2 часа

**Файл**: `tg_parser/storage/sqlite/processed_document_repo.py`

```python
async def list_all(self, limit: int | None = None) -> list[ProcessedDocument]:
    """Return all processed documents across all channels.
    
    Args:
        limit: Maximum number of documents to return (None = all)
        
    Returns:
        List of ProcessedDocument objects
    """
    async with self._session() as session:
        query = select(ProcessedDocumentTable)
        if limit:
            query = query.limit(limit)
        result = await session.execute(query)
        rows = result.scalars().all()
        return [self._to_domain(row) for row in rows]
```

**Обновить export_cmd.py:**
```python
# Убрать TODO на строке 82
if channel:
    docs = await repo.list_by_channel(channel)
else:
    docs = await repo.list_all()  # Теперь работает!
```

---

#### Задача 3: Получение usernames из IngestionStateRepo
**Время**: 3 часа

**Файл**: `tg_parser/cli/export_cmd.py` (строка 99)

```python
# Получить username из источника для лучших Telegram URLs
async def get_channel_username(source_id: str) -> str | None:
    """Get channel username from ingestion state."""
    source = await ingestion_repo.get_source(source_id)
    return source.channel_username if source else None

# Использовать в export
channel_username = await get_channel_username(source_id)
telegram_url = resolve_telegram_url(
    channel_id=channel_id,
    message_id=message_id,
    channel_username=channel_username,  # Передать username!
)
```

---

#### Задача 4: Auto-retry для failed messages
**Время**: 4 часа

**Файл**: `tg_parser/cli/process_cmd.py`

```python
@app.command()
async def process(
    channel: str = typer.Option(...),
    retry_failed: bool = typer.Option(False, "--retry-failed", help="Retry failed messages"),
    force: bool = typer.Option(False, "--force"),
):
    """Process raw messages through LLM."""
    if retry_failed:
        # Получить failed messages
        failures = await failure_repo.list_by_channel(channel)
        messages_to_process = [
            await raw_repo.get_by_source_ref(f.source_ref)
            for f in failures
        ]
        typer.echo(f"Retrying {len(messages_to_process)} failed messages...")
    else:
        # Обычная логика
        ...
```

---

#### Задача 5: Улучшенная валидация ответов LLM
**Время**: 3 часа

**Файл**: `tg_parser/processing/pipeline.py`

```python
def _validate_llm_response(self, response: dict) -> dict:
    """Validate and fix LLM response.
    
    Args:
        response: Parsed JSON from LLM
        
    Returns:
        Validated response with defaults for missing fields
        
    Raises:
        ValueError: If critical fields are missing
    """
    required_fields = ["text_clean"]
    optional_fields = {
        "summary": None,
        "topics": [],
        "entities": [],
        "language": "unknown",
    }
    
    # Проверить required
    for field in required_fields:
        if field not in response or not response[field]:
            raise ValueError(f"LLM response missing required field: {field}")
    
    # Заполнить defaults для optional
    for field, default in optional_fields.items():
        if field not in response:
            response[field] = default
            logger.warning(f"LLM response missing optional field '{field}', using default")
    
    return response
```

---

### Неделя 2-3 — Medium Priority

#### Задача 6: Обновить current-state.md
**Время**: 2 часа

Синхронизировать `docs/notes/current-state.md` с реальным состоянием кода.

#### Задача 7: Архивировать устаревшие документы
**Время**: 1 час

```bash
mkdir -p docs/notes/archive
mv SESSION_COMPLETE.md docs/notes/archive/
mv PROCESSING_COMPLETE.md docs/notes/archive/
```

#### Задача 8: Добавить E2E тесты
**Время**: 4 часа

**Файл**: `tests/test_e2e_scenarios.py`

```python
import pytest
from pathlib import Path

class TestE2EScenarios:
    """End-to-end tests for typical usage scenarios."""
    
    @pytest.mark.asyncio
    async def test_custom_prompts_directory(self, tmp_path):
        """Test using custom prompts from directory."""
        # Создать кастомные промпты
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "processing.yaml").write_text("""
system:
  prompt: "Custom system prompt"
user:
  template: "Process: {text}"
model:
  temperature: 0
""")
        
        # Запустить с кастомными промптами
        loader = PromptLoader(prompts_dir)
        assert "Custom system prompt" in loader.get_system_prompt("processing")
    
    @pytest.mark.asyncio
    async def test_fallback_to_default_prompts(self):
        """Test fallback to default prompts when YAML not found."""
        loader = PromptLoader(Path("/nonexistent"))
        
        # Должен вернуть default промпт
        system_prompt = loader.get_system_prompt("processing")
        assert system_prompt  # Не пустой
        assert "text processing" in system_prompt.lower()
```

#### Задача 9: Улучшенное логирование
**Время**: 3 часа

```python
import logging
import structlog

# Настройка structlog
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
)

logger = structlog.get_logger(__name__)

# Использование
logger.info("processing_message", 
    source_ref=message.source_ref,
    channel_id=message.channel_id,
)
```

---

## 🧪 Тестирование

```bash
# Активировать окружение
source .venv/bin/activate

# Запустить все тесты
pytest

# Запустить конкретный тест
pytest tests/test_prompt_loader.py -v

# С покрытием
pytest --cov=tg_parser --cov-report=html

# Проверить линтинг
ruff check .
ruff format .
```

---

## ✅ Критерии готовности v1.1.0

### Must Have
- [ ] ⭐ Промпты вынесены в YAML (3 файла)
- [ ] ⭐ `PromptLoader` реализован с fallback
- [ ] Все TODOs устранены (0 в коде)
- [ ] Error rate < 0.1%
- [ ] Auto-retry работает

### Should Have
- [ ] Документация промптов (`prompts/README.md`)
- [ ] E2E тесты для кастомных промптов
- [ ] Улучшенное логирование
- [ ] `current-state.md` обновлён

### Nice to Have
- [ ] Устаревшие документы архивированы
- [ ] CHANGELOG.md создан

---

## 📊 Success Metrics

| Метрика | Текущее | Цель |
|---------|---------|------|
| **Prompts in YAML** | 0 | 3 |
| Error rate | 0.24% | < 0.1% |
| TODOs в коде | 2 | 0 |
| Test count | 85 | 95+ |

---

## 🚀 Команды для быстрого старта

```bash
# 1. Прочитать roadmap
cat DEVELOPMENT_ROADMAP.md | head -300

# 2. Посмотреть текущие промпты
cat tg_parser/processing/prompts.py
cat tg_parser/processing/topicization_prompts.py

# 3. Проверить TODOs
grep -r "TODO" tg_parser/

# 4. Запустить тесты
pytest --tb=short -q

# 5. Создать структуру prompts/
mkdir -p prompts
```

---

## ⚠️ Важные ограничения

1. **Не ломать существующие тесты** — все 85 должны проходить
2. **Backward compatibility** — если `prompts/` нет, использовать defaults
3. **YAML формат** — не JSON (обсуждено с заказчиком)
4. **Не менять API** — только внутренняя реализация

---

## 🔗 Связанные документы

- [DEVELOPMENT_ROADMAP.md](../../DEVELOPMENT_ROADMAP.md) — полный roadmap
- [docs/LLM_PROMPTS.md](../LLM_PROMPTS.md) — текущие промпты
- [REAL_CHANNEL_TEST_RESULTS.md](../../REAL_CHANNEL_TEST_RESULTS.md) — результаты тестирования
- [docs/architecture.md](../architecture.md) — архитектура системы

---

## 💬 Контакт для следующего агента

После завершения создай файл `docs/notes/SESSION_HANDOFF_v1.1.md` с:
1. Списком выполненных задач
2. Списком новых файлов
3. Известными проблемами
4. Инструкциями для v1.2 агента

---

**Version**: 1.0  
**Created**: 26 декабря 2025  
**Target**: v1.1.0 release  
**ETA**: 2-3 недели  
**Previous session**: Session 10 (Planning)  
**Next session**: Session 12 (v1.2 Multi-LLM)

---

**Готов к реализации! Начни с Задачи 1 — Configurable Prompts (YAML).** 🚀

