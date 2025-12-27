# Session 12: v1.2 Developer Agent — "Multi-LLM & Performance"

## Роль

Привет! Ты Developer Agent для реализации версии **v1.2.0** проекта TG_parser. Твоя задача — реализовать **Multi-LLM Support** и улучшить производительность системы.

---

## 📋 Контекст проекта

**TG_parser** — production-ready система для сбора контента из Telegram-каналов, обработки через LLM и экспорта структурированных данных.

### Текущее состояние (v1.1)
- ✅ **Стабильность**: 99.76% успешность на 846 реальных сообщениях
- ✅ **Тесты**: 103 теста, 100% проходят
- ✅ **Configurable Prompts**: YAML файлы в `prompts/`
- ✅ **PromptLoader**: готов к Multi-LLM
- ✅ **TODOs**: 0 в коде
- ⚠️ **Только OpenAI**: нет поддержки Claude/Gemini/Ollama
- ⚠️ **Последовательная обработка**: 30 мин на 846 сообщений

### Архитектура
```
tg_parser/
├── cli/           # Typer CLI (7 команд)
├── config/        # Pydantic-settings
├── domain/        # Доменные модели (Pydantic v2)
├── ingestion/     # Telethon client
├── processing/    # LLM processing ← ОСНОВНОЙ ФОКУС
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── openai_client.py   # Существующий
│   │   ├── anthropic_client.py  # ⭐ NEW
│   │   ├── gemini_client.py     # ⭐ NEW
│   │   ├── ollama_client.py     # ⭐ NEW
│   │   └── factory.py           # ⭐ NEW
│   ├── prompt_loader.py     # v1.1 — готов
│   ├── pipeline.py
│   ├── prompts.py
│   ├── topicization_prompts.py
│   └── topicization.py
├── storage/       # SQLite репозитории
└── export/        # Экспорт KB entries + topics
```

---

## 📚 Документы для получения информации

### 🔴 ОБЯЗАТЕЛЬНО прочитать перед началом работы

| Документ | Описание | Приоритет |
|----------|----------|-----------|
| `DEVELOPMENT_ROADMAP.md` | **План v1.2** — детальные задачи и критерии | ⭐⭐⭐ |
| `docs/notes/SESSION_HANDOFF_v1.1.md` | Что сделано в v1.1 | ⭐⭐⭐ |
| `tg_parser/processing/llm/openai_client.py` | Текущая реализация LLM — образец для новых | ⭐⭐⭐ |
| `tg_parser/processing/ports.py` | Интерфейс LLMClient | ⭐⭐⭐ |
| `tg_parser/processing/prompt_loader.py` | PromptLoader — использовать для промптов | ⭐⭐ |

### 🟡 Для контекста и понимания системы

| Документ | Описание |
|----------|----------|
| `README.md` | Общий обзор, CLI команды |
| `CHANGELOG.md` | История изменений |
| `docs/architecture.md` | Архитектура системы |
| `docs/LLM_PROMPTS.md` | Текущие промпты |
| `prompts/README.md` | Формат YAML промптов |

### 🟢 Для справки по реализации

| Документ | Описание |
|----------|----------|
| `tg_parser/processing/pipeline.py` | Processing pipeline |
| `tg_parser/config/settings.py` | Настройки — добавить новые API keys |
| `tests/test_processing_pipeline.py` | Существующие тесты |

---

## 📤 Документы для передачи информации следующим агентам

### Обязательно обновить после завершения

| Документ | Что обновить |
|----------|--------------|
| `docs/notes/SESSION_HANDOFF_v1.2.md` | ⭐ **СОЗДАТЬ** — handoff для v2.0 агента |
| `DEVELOPMENT_ROADMAP.md` | Отметить выполненные задачи v1.2 |
| `CHANGELOG.md` | Добавить v1.2 изменения |
| `docs/notes/current-state.md` | Обновить текущее состояние |

---

## 🎯 Задачи v1.2.0 (приоритизированы)

### Неделя 1-2 — High Priority

#### Задача 1: ⭐ Multi-LLM Support (Chat Completions API)
**Время**: 12 часов  
**Приоритет**: HIGHEST

**Создать новые файлы:**
```
tg_parser/processing/llm/
├── anthropic_client.py  # ⭐ NEW
├── gemini_client.py     # ⭐ NEW
├── ollama_client.py     # ⭐ NEW
└── factory.py           # ⭐ NEW
```

**AnthropicClient (anthropic_client.py):**
```python
"""
Anthropic Claude LLM клиент.
Реализует LLMClient интерфейс для Claude models.
"""

import json
import logging
from typing import Any

import httpx

from tg_parser.processing.ports import LLMClient

logger = logging.getLogger(__name__)


class AnthropicClient(LLMClient):
    """
    Anthropic Claude клиент через Messages API.
    
    Поддерживаемые модели:
    - claude-3-5-sonnet-20241022
    - claude-3-5-haiku-20241022
    - claude-3-opus-20240229
    """

    BASE_URL = "https://api.anthropic.com/v1/messages"
    API_VERSION = "2023-06-01"

    def __init__(
        self,
        api_key: str,
        model: str = "claude-3-5-sonnet-20241022",
        max_tokens: int = 4096,
    ):
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self._client = httpx.AsyncClient(timeout=120.0)

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: dict | None = None,
        **kwargs,
    ) -> str:
        """
        Генерировать ответ через Anthropic Messages API.
        
        Args:
            prompt: User prompt
            system_prompt: System prompt
            temperature: Temperature (0-1)
            max_tokens: Max tokens в ответе
            response_format: {"type": "json_object"} для JSON mode
            
        Returns:
            Текст ответа
        """
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": self.API_VERSION,
            "content-type": "application/json",
        }

        messages = [{"role": "user", "content": prompt}]

        # Claude использует system prompt отдельно
        payload = {
            "model": self.model,
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": temperature,
            "messages": messages,
        }

        if system_prompt:
            payload["system"] = system_prompt

        # JSON mode hint в prompt (Claude не имеет response_format)
        if response_format and response_format.get("type") == "json_object":
            # Добавляем hint о JSON в конец prompt
            if "JSON" not in prompt:
                messages[0]["content"] = prompt + "\n\nRespond with valid JSON only."

        try:
            response = await self._client.post(
                self.BASE_URL,
                headers=headers,
                json=payload,
            )
            response.raise_for_status()

            data = response.json()
            content = data["content"][0]["text"]

            logger.debug(
                "Anthropic response received",
                extra={
                    "model": self.model,
                    "input_tokens": data.get("usage", {}).get("input_tokens"),
                    "output_tokens": data.get("usage", {}).get("output_tokens"),
                },
            )

            return content

        except httpx.HTTPStatusError as e:
            logger.error(f"Anthropic API error: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Anthropic request failed: {e}")
            raise

    async def close(self):
        """Закрыть HTTP клиент."""
        await self._client.aclose()

    def compute_prompt_id(self, system_prompt: str, user_prompt: str) -> str:
        """Compute stable hash of prompts for caching/tracking."""
        import hashlib
        combined = f"{system_prompt}||{user_prompt}"
        return hashlib.sha256(combined.encode()).hexdigest()[:16]
```

**Factory (factory.py):**
```python
"""
LLM Client Factory.
Создаёт LLM клиент по провайдеру.
"""

from typing import Any

from tg_parser.processing.ports import LLMClient


def create_llm_client(
    provider: str,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    **kwargs: Any,
) -> LLMClient:
    """
    Создать LLM клиент по провайдеру.
    
    Args:
        provider: "openai" | "anthropic" | "gemini" | "ollama"
        api_key: API ключ провайдера
        model: Модель (default зависит от провайдера)
        base_url: Custom base URL (для Ollama или прокси)
        
    Returns:
        LLMClient instance
        
    Raises:
        ValueError: Неизвестный провайдер
    """
    provider = provider.lower()
    
    if provider == "openai":
        from .openai_client import OpenAIClient
        return OpenAIClient(
            api_key=api_key,
            model=model or "gpt-4o-mini",
            base_url=base_url,
        )
    
    elif provider == "anthropic":
        from .anthropic_client import AnthropicClient
        if not api_key:
            raise ValueError("Anthropic API key required")
        return AnthropicClient(
            api_key=api_key,
            model=model or "claude-3-5-sonnet-20241022",
        )
    
    elif provider == "gemini":
        from .gemini_client import GeminiClient
        if not api_key:
            raise ValueError("Gemini API key required")
        return GeminiClient(
            api_key=api_key,
            model=model or "gemini-2.0-flash",
        )
    
    elif provider == "ollama":
        from .ollama_client import OllamaClient
        return OllamaClient(
            base_url=base_url or "http://localhost:11434",
            model=model or "llama3.2",
        )
    
    else:
        raise ValueError(
            f"Unknown LLM provider: {provider}. "
            f"Supported: openai, anthropic, gemini, ollama"
        )
```

**Обновить settings.py:**
```python
# ==========================================================================
# LLM настройки (v1.2 Multi-LLM)
# ==========================================================================

llm_provider: str = "openai"  # openai | anthropic | gemini | ollama
llm_model: str | None = None  # Опционально: переопределение модели
llm_base_url: str | None = None  # Для OpenAI-compatible прокси или Ollama

# API keys (должны быть в ENV)
openai_api_key: str | None = None
anthropic_api_key: str | None = None
gemini_api_key: str | None = None
```

**CLI флаг:**
```python
@app.command()
def process(
    channel: str = typer.Option(...),
    force: bool = typer.Option(False),
    retry_failed: bool = typer.Option(False),
    provider: str = typer.Option(None, "--provider", help="LLM provider override"),
    model: str = typer.Option(None, "--model", help="Model override"),
):
    """Process raw messages through LLM."""
    ...
```

**Критерии готовности:**
- [ ] AnthropicClient реализован и протестирован
- [ ] GeminiClient реализован и протестирован  
- [ ] OllamaClient реализован и протестирован
- [ ] Factory создаёт клиент по `LLM_PROVIDER`
- [ ] CLI `--provider` и `--model` работают
- [ ] Тесты для каждого клиента
- [ ] Промпты работают со всеми моделями

---

#### Задача 2: Параллельная обработка сообщений
**Время**: 8 часов
**Приоритет**: HIGH

**Файл**: `tg_parser/processing/pipeline.py`

```python
import asyncio
from typing import Any

async def process_batch_parallel(
    self,
    messages: list[RawTelegramMessage],
    force: bool = False,
    concurrency: int = 5,
) -> list[ProcessedDocument]:
    """
    Параллельная обработка батча сообщений.
    
    TR-47: ошибка на одном сообщении не должна ронять весь батч.
    
    Args:
        messages: Список RawTelegramMessage
        force: Переобработать даже если уже есть processed
        concurrency: Максимальное число параллельных запросов
        
    Returns:
        Список ProcessedDocument
    """
    semaphore = asyncio.Semaphore(concurrency)
    results: list[ProcessedDocument | None] = []
    
    async def process_with_semaphore(message: RawTelegramMessage) -> ProcessedDocument | None:
        async with semaphore:
            try:
                return await self.process_message(message, force=force)
            except Exception as e:
                logger.error(f"Failed to process {message.source_ref}: {e}")
                return None
    
    # Запускаем все задачи параллельно
    tasks = [process_with_semaphore(msg) for msg in messages]
    results = await asyncio.gather(*tasks)
    
    # Фильтруем None (failed)
    successful = [r for r in results if r is not None]
    
    logger.info(
        f"Parallel batch complete: {len(successful)}/{len(messages)} successful"
    )
    
    return successful
```

**CLI флаг:**
```python
@app.command()
def process(
    ...
    concurrency: int = typer.Option(5, "--concurrency", "-c", help="Parallel requests"),
):
```

**Критерии готовности:**
- [ ] `--concurrency N` флаг работает
- [ ] Rate limiting соблюдается
- [ ] Обработка в 3-5x быстрее
- [ ] Тесты параллельной обработки

---

#### Задача 3: Интеграция PromptLoader в pipeline
**Время**: 4 часа
**Приоритет**: HIGH

**Файл**: `tg_parser/processing/pipeline.py`

```python
from tg_parser.processing.prompt_loader import PromptLoader, get_prompt_loader

class ProcessingPipelineImpl(ProcessingPipeline):
    def __init__(
        self,
        llm_client: LLMClient,
        processed_doc_repo: ProcessedDocumentRepo,
        failure_repo: ProcessingFailureRepo | None = None,
        prompt_loader: PromptLoader | None = None,  # NEW
        ...
    ):
        ...
        self.prompt_loader = prompt_loader or get_prompt_loader()
    
    async def _process_single_message(self, message: RawTelegramMessage) -> ProcessedDocument:
        # Загружаем промпты из YAML
        system_prompt = self.prompt_loader.get_system_prompt("processing")
        user_template = self.prompt_loader.get_user_template("processing")
        model_settings = self.prompt_loader.get_model_settings("processing")
        
        # Форматируем user prompt
        user_prompt = user_template.format(text=message.text)
        
        # Вызываем LLM
        response_text = await self.llm_client.generate(
            prompt=user_prompt,
            system_prompt=system_prompt,
            **model_settings,
        )
        ...
```

**CLI флаг:**
```python
@app.callback()
def main(
    prompts_dir: Path = typer.Option(
        None, "--prompts-dir", help="Custom prompts directory"
    ),
):
    if prompts_dir:
        from tg_parser.processing.prompt_loader import PromptLoader, set_prompt_loader
        set_prompt_loader(PromptLoader(prompts_dir))
```

---

#### Задача 4: Dockerfile
**Время**: 4 часа

**Файл**: `Dockerfile`

```dockerfile
# Multi-stage build for production
FROM python:3.12-slim AS builder

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Production stage
FROM python:3.12-slim

WORKDIR /app

# Copy dependencies from builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Copy application
COPY tg_parser/ ./tg_parser/
COPY prompts/ ./prompts/
COPY pyproject.toml .

# Install package
RUN pip install --no-cache-dir -e .

# Default command
ENTRYPOINT ["python", "-m", "tg_parser.cli"]
CMD ["--help"]
```

**Файл**: `docker-compose.yml`

```yaml
version: '3.8'

services:
  tg_parser:
    build: .
    volumes:
      - ./data:/app/data
      - ./.env:/app/.env:ro
      - ./prompts:/app/prompts:ro
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - LLM_PROVIDER=${LLM_PROVIDER:-openai}
    command: ["run", "--source", "${SOURCE_ID}", "--out", "/app/data/output"]
```

---

#### Задача 5: GitHub Actions CI
**Время**: 4 часа

**Файл**: `.github/workflows/ci.yml`

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'
      
      - name: Install dependencies
        run: |
          pip install -e ".[dev]"
          pip install pytest-cov
      
      - name: Run linting
        run: ruff check .
      
      - name: Run tests
        run: pytest --tb=short -v --cov=tg_parser
      
      - name: Upload coverage
        uses: codecov/codecov-action@v4
        with:
          fail_ci_if_error: false

  docker:
    runs-on: ubuntu-latest
    needs: test
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Build Docker image
        run: docker build -t tg_parser:test .
      
      - name: Test Docker image
        run: docker run tg_parser:test --help
```

---

### Неделя 3-4 — Medium Priority

#### Задача 6: Progress bars и цвета в CLI
**Время**: 4 часа

```bash
pip install rich
```

```python
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.console import Console

console = Console()

with Progress(
    SpinnerColumn(),
    TextColumn("[progress.description]{task.description}"),
    transient=True,
) as progress:
    task = progress.add_task("Processing messages...", total=len(messages))
    for msg in messages:
        await pipeline.process_message(msg)
        progress.advance(task)
```

#### Задача 7: Dry-run mode
**Время**: 3 часа

```python
@app.command()
def process(
    ...
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without changes"),
):
    if dry_run:
        console.print("[yellow]DRY RUN MODE[/yellow]")
        console.print(f"Would process {len(messages)} messages")
        return
```

---

## 🧪 Тестирование

```bash
# Активировать окружение
source .venv/bin/activate

# Запустить все тесты
pytest

# Тесты конкретного модуля
pytest tests/test_llm_clients.py -v

# С покрытием
pytest --cov=tg_parser --cov-report=html

# Проверить линтинг
ruff check .
ruff format .

# Тестировать Docker
docker build -t tg_parser:test .
docker run tg_parser:test --help
```

---

## ✅ Критерии готовности v1.2.0

### Must Have
- [ ] ⭐ AnthropicClient работает
- [ ] ⭐ OllamaClient работает
- [ ] Factory создаёт клиенты по провайдеру
- [ ] `--provider` и `--model` в CLI
- [ ] Параллельная обработка (`--concurrency`)
- [ ] PromptLoader интегрирован в pipeline

### Should Have
- [ ] GeminiClient работает
- [ ] Dockerfile работает
- [ ] GitHub Actions CI
- [ ] Progress bars в CLI
- [ ] Обработка 846 сообщений < 10 мин

### Nice to Have
- [ ] docker-compose.yml
- [ ] Dry-run mode
- [ ] LLM response caching
- [ ] CONTRIBUTING.md

---

## 📊 Success Metrics

| Метрика | Текущее | Цель |
|---------|---------|------|
| **LLM providers** | 1 (OpenAI) | 4 (+ Anthropic, Gemini, Ollama) |
| **Processing time** | 30 мин / 846 msgs | < 10 мин |
| **Test count** | 103 | 120+ |
| **Docker support** | ❌ | ✅ |
| **CI/CD** | ❌ | ✅ |

---

## 🚀 Команды для быстрого старта

```bash
# 1. Прочитать handoff v1.1
cat docs/notes/SESSION_HANDOFF_v1.1.md

# 2. Посмотреть текущий OpenAI client (образец)
cat tg_parser/processing/llm/openai_client.py

# 3. Посмотреть интерфейс LLMClient
cat tg_parser/processing/ports.py

# 4. Запустить тесты
pytest --tb=short -q

# 5. Проверить settings
cat tg_parser/config/settings.py
```

---

## ⚠️ Важные ограничения

1. **Не ломать существующие тесты** — все 103 должны проходить
2. **Backward compatibility** — OpenAI должен работать как раньше
3. **Единый интерфейс** — все LLM клиенты реализуют `LLMClient`
4. **Rate limiting** — учитывать лимиты каждого провайдера
5. **API keys в ENV** — не хардкодить в коде

---

## 🔗 Связанные документы

- [DEVELOPMENT_ROADMAP.md](../../DEVELOPMENT_ROADMAP.md) — полный roadmap
- [docs/notes/SESSION_HANDOFF_v1.1.md](SESSION_HANDOFF_v1.1.md) — результаты v1.1
- [CHANGELOG.md](../../CHANGELOG.md) — история изменений
- [prompts/README.md](../../prompts/README.md) — формат промптов

---

## 💬 Контакт для следующего агента

После завершения создай файл `docs/notes/SESSION_HANDOFF_v1.2.md` с:
1. Списком выполненных задач
2. Списком новых файлов
3. Инструкциями по настройке разных LLM провайдеров
4. Известными проблемами
5. Инструкциями для v2.0 агента (GPT-5 / Agents SDK)

---

**Version**: 1.0  
**Created**: 26 декабря 2025  
**Target**: v1.2.0 release  
**ETA**: 4 недели  
**Previous session**: Session 11 (v1.1 Configurable Prompts)  
**Next session**: Session 13 (v2.0 GPT-5 / Agents SDK)

---

**Готов к реализации! Начни с Задачи 1 — Multi-LLM Support.** 🚀

