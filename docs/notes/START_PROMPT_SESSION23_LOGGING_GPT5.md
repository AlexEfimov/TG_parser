# Session 23: Structured JSON Logging + GPT-5 (Responses API)

**Дата**: 29 декабря 2025+  
**Версия**: v3.1.0-alpha.1 → v3.1.0-alpha.2  
**Фаза**: Phase 4B — Production Hardening  
**Приоритет**: 🔴 High  
**Время**: ~7 часов  
**Milestone**: 🔶 Logging-ready Staging + GPT‑5 ready

---

## 📋 Предыдущая сессия (Session 22 - что сделано)

**Status**: ✅ Завершена (67% задач выполнено)

**Выполнено**:
- ✅ Alembic Migrations Setup (multi-database support)
- ✅ CLI команды `db` (upgrade/downgrade/current/history/stamp)
- ✅ `init` команда обновлена для использования Alembic
- ✅ RetrySettings класс добавлен в config/settings.py (4 ENV параметра)
- ✅ Документация обновлена (README, CHANGELOG, current-state.md)
- ✅ Архивация устаревших docs

**Отложено на Session 23**:
- ⏳ Интеграция RetrySettings в LLM clients
- ⏳ Тесты RetrySettings (2+ тестов)

**Известные ограничения**:
- Alembic миграции создают только version tables
- Основные таблицы пока создаются через fallback DDL
- Требуется финализация для production

См.: `SESSION22_SUMMARY.md` для деталей

---

## 🎯 Цели сессии

### Основные задачи
1. **Structured JSON logging** (structlog) для API/CLI/Agents
2. **Correlation IDs**: `request_id` (API) + единый контекст логов
3. **GPT‑5 models support** (`gpt-5.2`, `gpt-5-mini`, `gpt-5-nano`) через **Responses API** (`/responses`)

### Задачи из Session 22 (Tech Debt)
4. **RetrySettings Integration** — использовать `retry_settings` в LLM clients
5. **RetrySettings Tests** — написать тесты для retry конфигурации

### Документация
6. Обновить документацию и примеры для эксплуатации на staging

---

## ✅ Definition of Done (критерии готовности)

### Logging
- [ ] JSON логи в production mode (Docker/server)
- [ ] Human-readable логи в development mode
- [ ] `request_id` присутствует во всех API логах (включая errors)
- [ ] Логи содержат минимум: `timestamp`, `level`, `logger`, `message`, `request_id` (для API)
- [ ] Документация: как фильтровать/искать в логах (jq examples)

### GPT‑5 / OpenAI (Responses API)
- [ ] `LLM_MODEL=gpt-5.2` работает (без изменения бизнес-логики pipeline/agents)
- [ ] Для `gpt-5.*` запросы идут через `POST /v1/responses` (а не `/chat/completions`)
- [ ] Поддержаны параметры (config-driven):
  - [ ] `LLM_REASONING_EFFORT` → `reasoning.effort`
  - [ ] `LLM_VERBOSITY` → `verbosity`
- [ ] Backward compatibility: `gpt-4o-mini` продолжает работать как раньше
- [ ] Добавлены тесты на формирование payload и парсинг ответа (без реального API вызова)

### RetrySettings Integration (Tech Debt from Session 22)
- [ ] `retry_settings` используется в `ProcessingPipelineImpl`
- [ ] `retry_settings` используется во всех LLM clients (где применимо)
- [ ] Hardcoded retry параметры заменены на `retry_settings.*`
- [ ] Написаны тесты для RetrySettings (минимум 2)
- [ ] `.env.example` содержит примеры RETRY_* переменных

---

## 🔧 Задача 1: Structured JSON Logging (structlog) (2-3 часа)

### Минимальный scope
- Подключить `structlog` и сделать единый конфиг логирования
- Поддержать переключение формата (JSON/text) через env/config (например `LOG_FORMAT=json|text`)
- В middleware FastAPI добавить `request_id` (если нет — генерировать)
- Для CLI/Agents: прокидывать correlation-id в контекст, где возможно

### Проверка вручную
- Запустить API и сделать несколько запросов → убедиться, что `request_id` стабильно присутствует.
- Найти ERROR лог через `jq`.

---

## 🤖 Задача 2: GPT‑5 support (Responses API) (2-3 часа)

### Контекст
Сейчас OpenAI клиент в проекте использует `/chat/completions` и `max_tokens`.  
Для GPT‑5.* нужно поддержать **Responses API** и параметры `reasoning.effort` / `verbosity`.

### План реализации (минимально-инвазивный)
- В `OpenAIClient.generate()` сделать routing:
  - если `model` начинается с `gpt-5` → использовать `/responses`
  - иначе оставить текущий путь (`/chat/completions`) до отдельного решения миграции
- Добавить опциональные настройки:
  - `LLM_REASONING_EFFORT` (default: `low`)
  - `LLM_VERBOSITY` (default: `low`)
- Парсить ответ Responses API через `output_text` (или эквивалентный текстовый output)

---

## 🧪 Тесты (минимум)

### Logging
- [ ] JSON формат логов валидный (можно распарсить как JSON)
- [ ] `request_id` присутствует в логах API endpoint'ов

### GPT-5
- [ ] Unit: для `gpt-5.2` формируется payload с `reasoning`/`verbosity` и правильным endpoint
- [ ] Unit: корректный парсинг текстового ответа Responses API
- [ ] Regression: существующие тесты processing/agents не ломаются

### RetrySettings (Tech Debt)
- [ ] Test: загрузка настроек из ENV переменных
- [ ] Test: валидация диапазонов значений (ge/le constraints)
- [ ] Test: использование retry_settings в retry логике

**Итого**: минимум 8+ новых тестов

---

## 🔧 Задача 3: RetrySettings Integration (Tech Debt) (1 час)

**Контекст**: В Session 22 создан `RetrySettings` класс, но интеграция в LLM clients была отложена.

### Файлы для обновления

1. **`tg_parser/processing/pipeline.py`**:
   - Заменить hardcoded `max_attempts = 3` на `retry_settings.max_attempts`
   - Использовать `retry_settings.backoff_base`, `backoff_max`, `jitter`

2. **`tg_parser/processing/llm/openai_client.py`** (и другие clients):
   - Если есть retry логика, использовать `retry_settings`
   - Или передать `retry_settings` как параметр в `__init__`

3. **`.env.example`**:
   - Добавить примеры RETRY_* переменных с описаниями

### Тесты
- Test: `retry_settings` корректно загружается из ENV
- Test: retry логика использует настройки из `retry_settings`

---

## 📚 Документация (после реализации)

### Обновить/создать:
- `LLM_SETUP_GUIDE.md` — GPT‑5.* + параметры reasoning/verbosity
- `docs/USER_GUIDE.md` — env переменные LOG_*, RETRY_*, примеры
- `README.md` — deployment readiness: Session 23 milestone
- `.env.example` — примеры RETRY_* переменных
- `CHANGELOG.md` — добавить секцию [3.1.0-alpha.2]
- `docs/notes/current-state.md` — обновить после Session 23

---

## 🔗 Ссылки

### Предыдущая сессия
- `SESSION22_SUMMARY.md` — итоги Session 22
- `docs/notes/START_PROMPT_SESSION22_FOUNDATION.md` — промпт Session 22

### Roadmap и guides
- `DEVELOPMENT_ROADMAP.md` → Session 23 (Phase 4B)
- `LLM_SETUP_GUIDE.md` — LLM провайдеры/модели
- `.env.example` — примеры переменных

### Текущая документация
- `docs/notes/current-state.md` — текущее состояние v3.0.0
- `tg_parser/config/settings.py` — существующий RetrySettings класс


