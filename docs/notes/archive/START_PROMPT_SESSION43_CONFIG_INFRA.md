# Session 43: Конфигурация и инфраструктура (Tech Debt A)

**Дата:** [дата запуска]  
**Тип сессии:** Tech Debt — Config & Infrastructure  
**Предыдущая сессия:** Session 42 (Tech Debt Cleanup — SQLite*Repo rename, dead import)  
**План:** `docs/notes/TECH_DEBT_CLOSURE_PLAN.md` → Session 43 (A)  
**Roadmap:** `docs/notes/DEVELOPMENT_ROADMAP.md`

---

## Цель сессии

Исправить высокоприоритетные проблемы конфигурации: консолидировать env-шаблоны, синхронизировать pyproject.toml, обновить Dockerfile и CI. По итогу — единый корректный `.env.example`, работающий `pip install -e .`, актуальный Dockerfile.

---

## Контекст проекта

### Текущее состояние (после Session 42)

- **Pipeline:** ingest → process → topicize → embed → export → search/ask
- **Database:** PostgreSQL 17.9 (Docker: `pgvector/pgvector:pg17`), pgvector 0.8.2
- **Тесты:** 538 passed, 24 skipped, 0 failures
- **Последний коммит:** `a70cec5` (Sessions 38-42)

### Ключевые файлы для этой сессии

```
.env.example              # Основной шаблон — нужно обновить
env.example               # Устаревший дубль — нужно удалить
pyproject.toml            # [project.dependencies] неполный
requirements.txt          # Канонический список зависимостей
Dockerfile                # Устаревший комментарий про SQLite
.github/workflows/ci.yml  # Дублирующий pip install
.gitignore                # Нет output_*/
tg_parser/config/settings.py  # Текущие Settings поля (для справки)
```

---

## Задачи

### Задача A1: Консолидация `.env` шаблонов (HIGH)

**Проблема:**
1. `env.example` ссылается на `DB_TYPE=sqlite` — этого поля нет в `settings.py` (удалено в Session 39)
2. `.env.example` содержит реалистичные Telegram credentials (строки 16-18):
   ```
   TELEGRAM_API_ID=37408407
   TELEGRAM_API_HASH=993af7cf48ab188b0e2d9b602d6ad3ad
   TELEGRAM_PHONE=+79197779997
   ```
3. `.env.example` имеет устаревшую секцию "Database Paths" (строки 106-113) с SQLite-путями

**Что сделать:**
1. Удалить `env.example`
2. В `.env.example`:
   - Строки 16-18: заменить Telegram credentials на плейсхолдеры
   - Строки 106-113: заменить секцию "Database Paths" на PostgreSQL:
     ```
     DB_HOST=localhost
     DB_PORT=5432
     DB_NAME=tg_parser
     DB_USER=tg_parser_user
     DB_PASSWORD=your_secure_password_here
     DB_POOL_SIZE=5
     DB_MAX_OVERFLOW=10
     ```
   - Добавить новую секцию после "Custom Prompts":
     ```
     # Embedding / RAG Configuration (P5)
     # EMBEDDING_PROVIDER=openai
     # EMBEDDING_MODEL=text-embedding-3-small
     # EMBEDDING_BATCH_SIZE=100
     ```

**Справка:** Актуальные поля Settings — в `tg_parser/config/settings.py`.

---

### Задача A2: Синхронизация `pyproject.toml` с `requirements.txt` (HIGH)

**Проблема:** `[project.dependencies]` содержит только часть зависимостей. `pip install -e .` недостаточно для запуска приложения.

**Что сделать:**
1. Прочитать `requirements.txt` — это канонический источник
2. Синхронизировать `[project.dependencies]` с `requirements.txt` (все runtime-зависимости)
3. В `[project.optional-dependencies].dev` добавить `pytest-cov` (используется в CI)

**Важно:** Не менять version ranges — скопировать как есть из `requirements.txt`.

---

### Задача A3: Обновить Dockerfile (MEDIUM)

**Проблема:** Строка 38-39:
```dockerfile
# Create data directory for SQLite databases
RUN mkdir -p /app/data
```

**Что сделать:** Обновить комментарий. Директория `/app/data` может быть нужна для промптов/экспорта, но комментарий про SQLite устарел.

---

### Задача A4: Добавить `output_*/` в `.gitignore` (MEDIUM)

**Проблема:** `output_session29/` и подобные директории не gitignored, появляются в `git status`.

**Что сделать:** Добавить в `.gitignore`:
```
output_*/
output_full/
```

---

### Задача A5: Убрать дублирующий `pip install` в CI (LOW)

**Проблема:** `.github/workflows/ci.yml` строки 47:
```yaml
pip install pytest pytest-cov pytest-asyncio ruff
```
Все эти пакеты уже есть в `requirements.txt` (после A2 — в `pyproject.toml` тоже).

**Что сделать:** Убрать дублирующую строку. Оставить только `pip install -r requirements.txt`.

---

## Порядок выполнения

| # | Задача | Файлы | Зависимость |
|---|--------|-------|-------------|
| 1 | A4: `.gitignore` | `.gitignore` | — |
| 2 | A1: `.env` шаблоны | `.env.example`, `env.example` | — |
| 3 | A2: `pyproject.toml` | `pyproject.toml`, `requirements.txt` | — |
| 4 | A3: Dockerfile | `Dockerfile` | — |
| 5 | A5: CI | `.github/workflows/ci.yml` | A2 |
| 6 | Тесты | — | Все задачи |

---

## Критерии завершения

- [ ] `env.example` удалён
- [ ] `.env.example` не содержит реальных credentials, имеет PostgreSQL и RAG секции
- [ ] `pip install -e .` устанавливает все зависимости
- [ ] `output_*/` в `.gitignore`
- [ ] Dockerfile без упоминания SQLite
- [ ] CI без дублирующего pip install
- [ ] Все 538+ тестов проходят
- [ ] Технический коммит

---

**Подготовлено:** Session 42  
**Следующий шаг:** Начать с A4 (.gitignore) → A1 (.env) → далее по порядку
