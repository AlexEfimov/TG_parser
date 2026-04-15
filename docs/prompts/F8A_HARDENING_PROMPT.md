# F8-A: Hardening — Placeholder

**Статус:** Placeholder (детальный план — в начале сессии реализации)  
**Prerequisites:** Wave 1.5 (RAG & Prompt Config)  
**Effort:** ~1 сессия

---

## Цель

Стабильность и наблюдаемость системы под нагрузкой: unified retry policy, DB pool metrics, circuit breaker для LLM, graceful degradation.

## Scope

| Область | Что сделать |
|---------|-------------|
| **Unified retry** | Заменить разрозненные retry-логики (pipeline, topicization, retrieval) единым подходом с exponential backoff и configurable limits |
| **DB pool metrics** | Connection pool stats в Prometheus (active, idle, overflow, wait time) |
| **LLM circuit breaker** | Автоматическое переключение на fallback provider при серии ошибок |
| **Graceful degradation** | Частичные ответы вместо полного отказа при недоступности LLM / DB |
| **Health check enrichment** | `/health` и `/status/detailed` отражают реальное здоровье компонентов (DB pool, LLM availability, scheduler) |

## Ключевые файлы (предварительно)

- `tg_parser/processing/pipeline.py` — retry при обработке сообщений
- `tg_parser/processing/topicization.py` — retry при topicization
- `tg_parser/services/retrieval_service.py` — retry при RAG
- `tg_parser/config/settings.py` — retry/circuit breaker config
- `tg_parser/api/routes/health.py` — health checks
- LLM clients (`llm_client.py`, `anthropic_client.py`, `gemini_client.py`)

## Что НЕ входит

- Horizontal scaling (F8-B)
- Redis/queue (F8-B)
- Kubernetes (F8-C)

## Зависимости от Wave 1.5

- Промптная система стабилизирована (YAML для всех LLM-вызовов)
- RAG scope в LLMConfigManager полностью работает
- Retry config может быть добавлен в YAML model sections
