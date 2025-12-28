# Тесты TG_parser

**Всего тестов:** 340  
**Статус:** ✅ Все проходят

## Запуск тестов

```bash
# Все тесты
pytest

# С verbose выводом
pytest -v

# С покрытием
pytest --cov=tg_parser --cov-report=term-missing

# Конкретный файл
pytest tests/test_e2e_pipeline.py -v
```

## Структура тестов

### Core модули
- **test_ids.py** — канонизация идентификаторов (TR-IF-5, TR-41, TR-IF-4, TR-61)
- **test_telegram_url.py** — резолюция Telegram URL (TR-58/TR-65)
- **test_models.py** — валидация Pydantic моделей против контрактов (TR-IF-1)

### Processing
- **test_processing_pipeline.py** — LLM processing pipeline
- **test_llm_clients.py** — Multi-LLM клиенты (OpenAI, Anthropic, Gemini, Ollama)
- **test_prompts.py** — YAML prompts loading

### Storage
- **test_storage_integration.py** — SQLite репозитории

### E2E
- **test_e2e_pipeline.py** — полный pipeline тест

### API (v2.0)
- **test_api.py** — FastAPI endpoints
- **test_api_auth.py** — API authentication
- **test_api_webhooks.py** — Webhook callbacks
- **test_api_jobs.py** — Persistent job storage

### Agents (v2.0-v3.0)
- **test_agents.py** — TGProcessingAgent, function tools
- **test_hybrid_agent.py** — Hybrid mode (agent + pipeline)
- **test_multi_agent.py** — Multi-Agent Architecture
- **test_agent_persistence.py** — Agent State Persistence (Phase 3B)
- **test_agents_observability.py** — Agent Observability (Phase 3C) ⭐ NEW

## Покрытие по фазам

| Фаза | Тесты | Описание |
|------|-------|----------|
| v1.2 | ~126 | Multi-LLM, Pipeline |
| Phase 2A-2C | ~62 | HTTP API, Agents PoC |
| Phase 2E-2F | ~70 | Hybrid, Auth, Webhooks |
| Phase 3A | ~42 | Multi-Agent Architecture |
| Phase 3B | ~25 | Agent Persistence |
| Phase 3C | ~15 | Agent Observability |
