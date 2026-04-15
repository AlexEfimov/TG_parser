# Wave 1.5: RAG & Prompt Config — Стартовый промпт

**Версия проекта:** 4.3.0 (tag v4.3.0 на main)  
**Предыдущая сессия:** F4 Multi-Tenancy (все 5 фаз) + Documentation Audit  
**Зафиксированная последовательность:** Wave 1.5 → F8-A → F5-A

---

## Цель сессии

Подключить PromptLoader ко **всем** LLM-вызовам, добавить static env vars для RAG LLM, улучшить RAG prompt — завершить базовую управляемость промптов (F1 Levels 1+2).

---

## Контекст: текущее состояние промптной системы

### Архитектура

- **PromptLoader** (`tg_parser/processing/prompt_loader.py`): загружает `prompts/{name}.yaml` с fallback на Python-defaults
- **7 YAML файлов** в `prompts/`: processing, topicization, rag, bot, merge, incremental_discover, supporting_items
- **`reload_prompts`** MCP/bot tool (admin-only): перезагружает YAML без рестарта
- **LLM scopes**: `global`, `processing`, `topicization`, `rag` — но `rag` не имеет static env vars

### Что подключено к PromptLoader (YAML работает):

| YAML | Сервис | Полностью подключён? |
|------|--------|---------------------|
| `processing.yaml` | `pipeline.py` → `MessageProcessor` | Да |
| `rag.yaml` | `retrieval_service.py` → `answer()` | Да |
| `bot.yaml` | `bot/agent.py` → `GeminiAgent` | Да |
| `merge.yaml` | `topicization.py` → `_merge_topics()` | Да |
| `incremental_discover.yaml` | `topicization.py` → `_discover_single_batch()` | Частично (system+model из YAML, user prompt из Python) |

### Что НЕ подключено (gaps):

| YAML | Проблема |
|------|----------|
| **`topicization.yaml`** | `_generate_topics_batch()` использует hardcoded `TOPICIZATION_SYSTEM_PROMPT` и `build_topicization_prompt()` из `topicization_prompts.py`. YAML файл существует но **игнорируется**. |
| `supporting_items.yaml` | Нет LLM caller в production (programmatic scoring). Файл-заглушка — вне scope. |

### Другие gaps:

1. **`settings.prompts_dir`** объявлен в settings.py но **не подключён** к `get_prompt_loader()` — кастомная директория не работает
2. **Нет `rag_llm_provider` / `rag_llm_model`** в settings.py — RAG всегда fallback на global LLM (нет паритета с `processing_llm_*` / `topicization_llm_*`)
3. **RAG prompt quality** — roadmap отмечает как "слабейшее звено" — нужен refactor

---

## План реализации (6 фаз)

### Phase 1: Wire topicization.yaml to batch topicization

**Файл:** `tg_parser/processing/topicization.py`

В `_generate_topics_batch()` (строка ~260):
- Загрузить system prompt из `get_prompt_loader().load("topicization")` вместо `TOPICIZATION_SYSTEM_PROMPT`
- Загрузить `temperature` / `max_tokens` из YAML `model` секции
- Fallback на Python-константу если YAML не содержит нужных полей
- `prompt_id` (TR-40, конструктор ~107): тоже должен использовать loaded prompt

**Не трогаем:**
- `build_topicization_prompt()` / `build_incremental_discover_prompt()` — user prompt builders содержат сложную логику форматирования, остаются в Python
- Agent-level prompts (processing_agent.py, text_tools.py) — тесно связаны с OpenAI Agents SDK

### Phase 2: Wire settings.prompts_dir to PromptLoader

**Файл:** `tg_parser/processing/prompt_loader.py`

В `get_prompt_loader()` (строка ~375):
- При создании `PromptLoader()` передать `settings.prompts_dir` если он задан
- Lazy import `settings` чтобы избежать circular dependency

### Phase 3: Add static RAG LLM env vars

**Файл:** `tg_parser/config/settings.py`

Рядом с `processing_llm_provider` / `topicization_llm_provider` (строка ~142):
```python
rag_llm_provider: str | None = None
rag_llm_model: str | None = None
```

**Файлы:** `.env.example`, `ENV_VARIABLES_GUIDE.md` — документировать новые переменные

### Phase 4: Improve RAG prompt quality

**Файл:** `prompts/rag.yaml`
- Инструкция цитировать source_ref (`[tg:channel:post:123]`)
- Инструкция использовать topic context (summaries, tags) если присутствует
- Увеличить `context_char_limit` (1500 → 2000)

**Файл:** `tg_parser/services/retrieval_service.py`
- В `_build_context()`: включить source_ref явно для каждого документа в контексте

### Phase 5: Tests

- Тест что `topicization.yaml` загружается в `_generate_topics_batch`
- Тест что `settings.prompts_dir` подхватывается PromptLoader
- Тест что `rag_llm_provider`/`rag_llm_model` резолвятся через `resolve("rag")`
- Расширить `tests/test_rag_prompt_config.py` и `tests/test_prompt_loader.py`

### Phase 6: Documentation

- `docs/USER_GUIDE.md`: секция "Конфигурация промптов"
- `docs/MCP_AGENT_GUIDE.md`: упомянуть prompt YAML config
- `_MCP_INSTRUCTIONS` в `mcp_server.py`

---

## Ключевые файлы для изучения

| Файл | Назначение |
|------|-----------|
| `tg_parser/processing/prompt_loader.py` | PromptLoader, `get_prompt_loader()`, `set_prompt_loader()` |
| `tg_parser/processing/topicization.py` | `_generate_topics_batch()`, `_discover_single_batch()` — **основной target** |
| `tg_parser/processing/topicization_prompts.py` | `TOPICIZATION_SYSTEM_PROMPT`, builders |
| `tg_parser/services/retrieval_service.py` | `answer()`, `_build_context()`, `_call_llm()` |
| `tg_parser/config/settings.py` | Settings, LLM_SCOPES, `LLMConfigManager` |
| `prompts/rag.yaml` | RAG prompt template |
| `prompts/topicization.yaml` | Topicization prompt template (сейчас не используется!) |
| `tests/test_prompt_loader.py` | Тесты PromptLoader |
| `tests/test_rag_prompt_config.py` | Тесты RAG prompt config |

---

## Что НЕ входит в scope

- Agent-level prompts (processing_agent.py, text_tools.py) — OpenAI Agents SDK
- `supporting_items.yaml` — нет LLM caller в production
- F1 Level 3 (DB + версионирование + A/B) — Wave 3
- Вынос user prompt builders в YAML — сложная логика форматирования

---

## Критерии завершённости

1. `topicization.yaml` реально влияет на LLM-вызовы batch topicization
2. `PROMPTS_DIR=/custom/path` в .env корректно подхватывается
3. `RAG_LLM_PROVIDER` / `RAG_LLM_MODEL` работают через .env
4. RAG prompt включает source_ref и topic context
5. Все существующие тесты проходят + новые тесты для gaps
6. Документация обновлена

---

## Тесты

Запуск тестов:
```bash
.venv/bin/pytest tests/ -x -q
# Или с PostgreSQL integration:
TEST_POSTGRES=1 .venv/bin/pytest tests/ -x -q
```

Текущее состояние: **1266 тестов**, все проходят (v4.3.0).
