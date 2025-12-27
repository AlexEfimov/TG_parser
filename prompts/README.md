# TG_parser Prompts

Эта директория содержит конфигурируемые промпты для LLM обработки.

## Файлы

| Файл | Описание |
|------|----------|
| `processing.yaml` | Промпты для обработки сообщений (extraction) |
| `topicization.yaml` | Промпты для кластеризации в темы |
| `supporting_items.yaml` | Промпты для поиска supporting items |

## Формат YAML

Каждый файл имеет следующую структуру:

```yaml
metadata:
  version: "1.0.0"
  description: "Description of prompts"
  author: "TG_parser team"

system:
  prompt: |
    System prompt text...

user:
  template: |
    User prompt template with {variables}...
  
  variables:
    - variable_name  # Описание переменной

model:
  temperature: 0
  max_tokens: 4096
```

## Секции

### metadata

Информация о версии и авторе промптов. Используется для трекинга.

### system

- `prompt`: System prompt, отправляемый LLM

### user

- `template`: Шаблон user prompt с плейсхолдерами `{variable}`
- `variables`: Список переменных, используемых в шаблоне

### model

- `temperature`: Температура (0 для детерминизма)
- `max_tokens`: Максимальное количество токенов в ответе

## Использование

### Через CLI

```bash
# Использовать кастомную директорию промптов
python -m tg_parser.cli process --channel @mychannel --prompts-dir ./custom_prompts
```

### В коде

```python
from tg_parser.processing.prompt_loader import PromptLoader

# Загрузить из кастомной директории
loader = PromptLoader(prompts_dir="./my_prompts")

# Получить промпты
system_prompt = loader.get_system_prompt("processing")
user_template = loader.get_user_template("processing")
model_settings = loader.get_model_settings("processing")

# Использовать шаблон
user_prompt = user_template.format(text="Message text here")
```

## Кастомизация

### 1. Скопируйте файл

```bash
cp prompts/processing.yaml prompts/processing_custom.yaml
```

### 2. Отредактируйте промпт

Измените `system.prompt` или `user.template` под вашу задачу.

### 3. Используйте

Переименуйте обратно или укажите через `--prompts-dir`.

## Fallback

Если YAML файл не найден, используются встроенные defaults из:
- `tg_parser/processing/prompts.py`
- `tg_parser/processing/topicization_prompts.py`

Это обеспечивает обратную совместимость.

## Примеры кастомизации

### Добавить extraction доменных сущностей

```yaml
system:
  prompt: |
    You are a medical text processing assistant...
    
    Extract:
    - Diseases mentioned
    - Medications
    - Symptoms
    - Medical procedures
    
    Output JSON:
    {
      "text_clean": "...",
      "medical_entities": [
        {"type": "disease", "value": "...", "icd10": "..."},
        {"type": "medication", "value": "...", "atc": "..."}
      ]
    }
```

### Изменить язык вывода

```yaml
system:
  prompt: |
    ...
    
    IMPORTANT: All output fields MUST be in English, regardless of input language.
```

### Добавить дополнительные поля

```yaml
user:
  template: |
    Process this message:
    
    Channel: {channel_name}
    Date: {date}
    Text: {text}
    
    Additional context: {context}
  
  variables:
    - channel_name
    - date
    - text
    - context
```

## Версионирование

При изменении промптов рекомендуется:

1. Увеличить версию в `metadata.version`
2. Добавить комментарий с датой изменения
3. Сохранить старые версии для воспроизводимости

```yaml
metadata:
  version: "1.1.0"  # 2025-01-15: Added medical entity extraction
```

## Связанные документы

- [docs/LLM_PROMPTS.md](../docs/LLM_PROMPTS.md) - Полная документация промптов
- [docs/pipeline.md](../docs/pipeline.md) - Pipeline документация
- [docs/technical-requirements.md](../docs/technical-requirements.md) - TR-38 (детерминизм)

