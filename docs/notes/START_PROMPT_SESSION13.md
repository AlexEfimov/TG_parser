# Session 13: v1.2 Testing & Documentation Agent

## Роль

Привет! Ты Testing & Documentation Agent для финализации версии **v1.2.0** проекта TG_parser и подготовки к v2.0.

Твоя задача:
1. **Провести расширенное тестирование** v1.2.0 на реальных данных
2. **Завершить документацию** для v1.2.0
3. **Подготовить переход** к v2.0 (GPT-5 / Platform)

---

## 📋 Контекст

### Что выполнено в Session 12 (v1.2.0)

✅ **Multi-LLM Support**
- AnthropicClient (Claude)
- GeminiClient (Google Gemini)
- OllamaClient (локальные LLM)
- Factory pattern для создания клиентов
- CLI флаги `--provider` и `--model`

✅ **Performance**
- Параллельная обработка (`--concurrency`)
- Ускорение в 3-5x

✅ **Infrastructure**
- Dockerfile + docker-compose.yml
- GitHub Actions CI/CD
- 126 тестов (все проходят)

✅ **Initial Testing**
- Unit тесты: 126/126 ✅
- Factory pattern: работает ✅
- Pipeline integration: работает ✅
- PromptLoader: работает ✅
- Ollama (qwen3:8b): протестирован, качество хорошее ✅

### Что нужно сделать в Session 13

❗ **Расширенное тестирование на реальных данных**
❗ **Финализация документации**
❗ **Подготовка к v2.0**

---

## 🧪 План тестирования v1.2.0

### Этап 1: Baseline тестирование (30 мин)

**Цель**: Проверить, что Multi-LLM работает на реальном канале

#### 1.1 Подготовка тестовых данных

```bash
# Проверить доступные данные
sqlite3 raw_storage.sqlite "SELECT channel_id, COUNT(*) FROM raw_telegram_messages GROUP BY channel_id;"
sqlite3 processing_storage.sqlite "SELECT channel_id, COUNT(*) FROM processed_documents GROUP BY channel_id;"
```

**Критерии**:
- [ ] Есть минимум 10 raw сообщений для теста
- [ ] Или можем собрать новые через `ingest --limit 20`

#### 1.2 Тест OpenAI (baseline)

```bash
# С реальным API ключом (добавить в .env)
python -m tg_parser.cli process --channel <channel> \
  --provider openai \
  --model gpt-4o-mini \
  --limit 10
```

**Критерии успеха**:
- [ ] 10/10 сообщений обработано успешно
- [ ] JSON валидный
- [ ] Summary, topics, entities извлечены корректно
- [ ] Время обработки < 60 секунд

#### 1.3 Тест Anthropic Claude

```bash
python -m tg_parser.cli process --channel <channel> \
  --provider anthropic \
  --model claude-3-5-sonnet-20241022 \
  --limit 10 \
  --force
```

**Критерии успеха**:
- [ ] 10/10 сообщений обработано
- [ ] Качество сравнимо с OpenAI
- [ ] Время обработки < 90 секунд

#### 1.4 Тест Ollama (локально)

```bash
# Убедиться что Ollama запущен
ollama serve &

python -m tg_parser.cli process --channel <channel> \
  --provider ollama \
  --model qwen3:8b \
  --limit 10 \
  --force
```

**Критерии успеха**:
- [ ] 10/10 сообщений обработано
- [ ] JSON валидный (локальные модели иногда возвращают markdown)
- [ ] Время обработки < 180 секунд

---

### Этап 2: Performance тестирование (45 мин)

**Цель**: Проверить параллельную обработку и производительность

#### 2.1 Последовательная обработка (baseline)

```bash
time python -m tg_parser.cli process --channel <channel> \
  --provider ollama \
  --model qwen3:8b \
  --concurrency 1
```

**Замерить**: Время обработки N сообщений

#### 2.2 Параллельная обработка (concurrency=3)

```bash
time python -m tg_parser.cli process --channel <channel> \
  --provider ollama \
  --model qwen3:8b \
  --concurrency 3 \
  --force
```

**Критерии успеха**:
- [ ] Ускорение в 2-3x по сравнению с concurrency=1
- [ ] Все сообщения обработаны успешно
- [ ] Нет race conditions

#### 2.3 Параллельная обработка (concurrency=5)

```bash
time python -m tg_parser.cli process --channel <channel> \
  --provider ollama \
  --model qwen3:8b \
  --concurrency 5 \
  --force
```

**Критерии успеха**:
- [ ] Ускорение в 3-5x
- [ ] Rate limiting работает корректно

#### 2.4 Stress test (большой батч)

```bash
# Если есть > 100 сообщений
time python -m tg_parser.cli process --channel <channel> \
  --provider ollama \
  --concurrency 5 \
  --force
```

**Критерии успеха**:
- [ ] Обработка завершается без ошибок
- [ ] Memory usage стабилен
- [ ] Логи корректные

---

### Этап 3: Integration тестирование (30 мин)

**Цель**: Полный E2E pipeline с Multi-LLM

#### 3.1 Full pipeline с OpenAI

```bash
python -m tg_parser.cli run \
  --source <source> \
  --out ./test_output_openai \
  --provider openai \
  --skip-ingest
```

**Критерии успеха**:
- [ ] Process → Topicize → Export работает
- [ ] KB entries экспортированы
- [ ] Topics созданы

#### 3.2 Full pipeline с Anthropic

```bash
python -m tg_parser.cli run \
  --source <source> \
  --out ./test_output_anthropic \
  --provider anthropic \
  --skip-ingest \
  --force
```

**Критерии успеха**:
- [ ] Весь pipeline работает с Anthropic
- [ ] Результаты корректные

---

### Этап 4: Docker тестирование (20 мин)

**Цель**: Проверить Docker образ

#### 4.1 Docker build

```bash
docker build -t tg_parser:v1.2.0 .
```

**Критерии успеха**:
- [ ] Build завершается без ошибок
- [ ] Image size разумный (< 1GB)

#### 4.2 Docker run

```bash
docker run --rm tg_parser:v1.2.0 --help
docker run --rm tg_parser:v1.2.0 init --help
```

**Критерии успеха**:
- [ ] CLI доступен в контейнере
- [ ] Help работает

#### 4.3 Docker Compose

```bash
docker-compose build
docker-compose run tg_parser init
docker-compose run tg_parser process --channel <channel> --provider ollama
```

**Критерии успеха**:
- [ ] Compose работает
- [ ] Volumes монтируются
- [ ] ENV переменные передаются

---

## 📚 План документации

### 1. Обновить README.md (30 мин)

**Добавить секции**:
- [ ] Quick Start для v1.2 (Multi-LLM примеры)
- [ ] Installation (Docker + venv)
- [ ] Configuration (все провайдеры)
- [ ] Usage Examples (каждый провайдер)
- [ ] Performance tips (--concurrency)

### 2. Создать TESTING_RESULTS_v1.2.md (20 мин)

**Содержимое**:
- [ ] Результаты всех тестов
- [ ] Performance метрики
- [ ] Comparison таблица провайдеров
- [ ] Известные ограничения

### 3. Обновить docs/USER_GUIDE.md (15 мин)

**Добавить**:
- [ ] Секцию про Multi-LLM
- [ ] Как выбрать провайдера
- [ ] Troubleshooting для каждого провайдера

### 4. Создать MIGRATION_GUIDE_v1.1_to_v1.2.md (15 мин)

**Для пользователей v1.1**:
- [ ] Что изменилось
- [ ] Как обновиться
- [ ] Breaking changes (их нет, но указать на обратную совместимость)
- [ ] Новые возможности

### 5. Финализировать docs/notes/SESSION_HANDOFF_v1.2.md (10 мин)

**Добавить**:
- [ ] Результаты расширенного тестирования
- [ ] Production recommendations
- [ ] Known issues (если есть)

---

## 🚀 Подготовка к v2.0

### 1. Изучить OpenAI Agents SDK (30 мин)

**Документация**:
- https://github.com/openai/openai-python
- Responses API (GPT-5)
- Reasoning models

**Задачи**:
- [ ] Понять новый API: `Runner.run(agent, ...)`
- [ ] Изучить `reasoning.effort` параметр
- [ ] Изучить structured outputs через Pydantic
- [ ] Сравнить с текущим Chat Completions API

### 2. Создать START_PROMPT_SESSION14.md (v2.0)

**План v2.0**:
- [ ] GPT-5 Support (Agents SDK)
- [ ] HTTP API (FastAPI)
- [ ] Web Dashboard (React)
- [ ] Scheduled processing

### 3. Обновить DEVELOPMENT_ROADMAP.md

**Отметить**:
- [x] v1.2.0 — COMPLETED
- [ ] v2.0.0 — задачи и timeline

---

## ✅ Критерии готовности v1.2.0 к релизу

### Must Have (обязательно)
- [ ] ✅ Unit тесты: 126/126
- [ ] ✅ Integration тесты на реальных данных: минимум 1 провайдер работает
- [ ] ✅ Performance тест: concurrency работает
- [ ] ✅ Docker: build и run работают
- [ ] ✅ Документация: README, USER_GUIDE обновлены
- [ ] ✅ CHANGELOG.md обновлён
- [ ] ✅ SESSION_HANDOFF_v1.2.md завершён

### Nice to Have (желательно)
- [ ] Все 4 провайдера протестированы на реальных данных
- [ ] Performance метрики задокументированы
- [ ] MIGRATION_GUIDE создан
- [ ] CI/CD pipeline запущен и работает

---

## 📂 Структура документов

### Существующие (обновить)
```
README.md                           # Добавить v1.2 примеры
CHANGELOG.md                        # ✅ Обновлён
DEVELOPMENT_ROADMAP.md              # ✅ Обновлён, отметить v1.2 complete
docs/USER_GUIDE.md                  # Добавить Multi-LLM секцию
docs/notes/SESSION_HANDOFF_v1.2.md  # ✅ Создан, добавить тест результаты
```

### Новые (создать)
```
TESTING_RESULTS_v1.2.md             # Результаты расширенного тестирования
MIGRATION_GUIDE_v1.1_to_v1.2.md     # Миграция для пользователей
docs/notes/START_PROMPT_SESSION14.md # План v2.0
```

---

## 🔧 Быстрый старт для Session 13

### Шаг 1: Проверка окружения

```bash
cd /Users/alexanderefimov/TG_parser
source .venv/bin/activate

# Проверка версии Python
python --version  # Должно быть 3.12.0

# Проверка тестов
pytest --tb=short -q  # Должно быть 126 passed

# Проверка данных
sqlite3 raw_storage.sqlite "SELECT COUNT(*) FROM raw_telegram_messages;"
sqlite3 processing_storage.sqlite "SELECT COUNT(*) FROM processed_documents;"
```

### Шаг 2: Подготовка API ключей

```bash
# Проверить .env
cat .env | grep API_KEY

# Если нужно, добавить реальные ключи:
# - OPENAI_API_KEY=sk-...
# - ANTHROPIC_API_KEY=sk-ant-...
# - GEMINI_API_KEY=...
```

### Шаг 3: Выбрать тестовый канал

```bash
# Посмотреть доступные каналы
sqlite3 processing_storage.sqlite "SELECT DISTINCT channel_id FROM processed_documents;"

# Или собрать новые данные
python -m tg_parser.cli ingest --source <source> --mode snapshot --limit 20
```

### Шаг 4: Запустить базовый тест

```bash
# Тест с Ollama (не требует API key)
python -m tg_parser.cli process --channel <channel> \
  --provider ollama \
  --model qwen3:8b \
  --limit 10
```

### Шаг 5: Утвердить план тестирования

**Вопросы для уточнения**:
1. Какие провайдеры тестировать? (OpenAI, Anthropic, Gemini, Ollama — все или выборочно?)
2. Сколько сообщений для теста? (10, 50, 100, 846?)
3. Нужен ли stress test на большом объёме?
4. Какие метрики важны? (время, качество, стоимость?)
5. Нужен ли сравнительный анализ качества разных моделей?

---

## 📊 Шаблон отчёта о тестировании

```markdown
# TG_parser v1.2.0 — Testing Results

## Test Environment
- Date: YYYY-MM-DD
- Python: 3.12.0
- Test Channel: <channel_id>
- Messages Count: N
- API Keys: OpenAI (✅/❌), Anthropic (✅/❌), Gemini (✅/❌)

## Test Results

### Unit Tests
- Total: 126
- Passed: 126
- Status: ✅ PASSED

### Integration Tests

#### OpenAI
- Provider: openai
- Model: gpt-4o-mini
- Messages processed: X/N
- Success rate: XX%
- Average time: XX seconds per message
- Quality: (summary/topics/entities)
- Status: ✅/❌

#### Anthropic Claude
- Provider: anthropic
- Model: claude-3-5-sonnet-20241022
- Messages processed: X/N
- Success rate: XX%
- Average time: XX seconds per message
- Quality: (better/same/worse than OpenAI)
- Status: ✅/❌

#### Google Gemini
- Provider: gemini
- Model: gemini-2.0-flash-exp
- Messages processed: X/N
- Success rate: XX%
- Average time: XX seconds per message
- Quality: (rating)
- Status: ✅/❌

#### Ollama
- Provider: ollama
- Model: qwen3:8b
- Messages processed: X/N
- Success rate: XX%
- Average time: XX seconds per message
- Quality: (rating)
- Status: ✅/❌

### Performance Tests

#### Sequential Processing (concurrency=1)
- Messages: N
- Time: XX seconds
- Rate: XX msg/sec

#### Parallel Processing (concurrency=3)
- Messages: N
- Time: XX seconds
- Rate: XX msg/sec
- Speedup: Xx

#### Parallel Processing (concurrency=5)
- Messages: N
- Time: XX seconds
- Rate: XX msg/sec
- Speedup: Xx

### Docker Tests
- Build: ✅/❌
- Run: ✅/❌
- Compose: ✅/❌

## Recommendations
- Production provider: <recommended>
- Optimal concurrency: N
- Known issues: ...

## Conclusion
v1.2.0 is ready/not ready for release because...
```

---

## 💬 Следующие шаги после Session 13

После успешного завершения тестирования и документации:

1. **Создать git tag v1.2.0**
2. **Запустить GitHub Actions CI** (если ещё не запущен)
3. **Опубликовать релиз** (GitHub Releases)
4. **Начать Session 14** — v2.0 Development

---

## 🔗 Связанные документы

- [SESSION_HANDOFF_v1.2.md](SESSION_HANDOFF_v1.2.md) — результаты Session 12
- [DEVELOPMENT_ROADMAP.md](../../DEVELOPMENT_ROADMAP.md) — полный roadmap
- [LLM_SETUP_GUIDE.md](../../LLM_SETUP_GUIDE.md) — настройка LLM провайдеров
- [QUICKSTART_v1.2.md](../../QUICKSTART_v1.2.md) — быстрый старт

---

**Version**: 1.0  
**Created**: 27 декабря 2025  
**Target**: v1.2.0 Testing & Release  
**Previous**: Session 12 (v1.2 Development)  
**Next**: Session 14 (v2.0 GPT-5 / Platform)

---

**Готов к тестированию! Начни с утверждения плана тестирования.** 🚀

