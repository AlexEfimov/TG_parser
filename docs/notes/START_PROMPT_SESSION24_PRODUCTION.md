# Session 24: Production Ready (PostgreSQL + Multi-user)

**Версия:** v3.1.0-alpha.2 → v3.1.0  
**Дата создания:** 29 декабря 2025  
**Оценка времени:** ~10 часов  
**Приоритет:** 🔥 HIGH (Production blocker)

---

## 🎯 Цель Session 24

**Сделать TG_parser полностью production-ready:**
- PostgreSQL вместо SQLite
- Connection pooling
- Multi-user support
- Production deployment configuration
- Финальные тесты перед деплоем

**Результат:** v3.1.0 — готов к production деплою на сервер

---

## 📋 Scope Session 24

### 1. PostgreSQL Support (Приоритет: CRITICAL)

#### 1.1. Database Configuration
- [ ] Добавить `psycopg2-binary` в `requirements.txt`
- [ ] Создать `PostgresSettings` в `tg_parser/config/settings.py`
- [ ] Добавить ENV переменные:
  ```env
  DB_TYPE=postgresql  # или sqlite (для обратной совместимости)
  DB_HOST=localhost
  DB_PORT=5432
  DB_NAME=tg_parser
  DB_USER=tg_parser_user
  DB_PASSWORD=secure_password
  
  # Connection Pool Settings
  DB_POOL_SIZE=5
  DB_MAX_OVERFLOW=10
  DB_POOL_TIMEOUT=30
  DB_POOL_RECYCLE=3600
  ```

#### 1.2. SQLAlchemy Engine Factory
- [ ] Создать `tg_parser/storage/engine_factory.py`
- [ ] Функция `create_engine_from_settings()`:
  - SQLite fallback для development
  - PostgreSQL для production
  - Connection pooling для PostgreSQL
  - Retry logic для connection errors
- [ ] Обновить все storage модули:
  - `ingestion_storage.py`
  - `raw_storage.py`
  - `processing_storage.py`
  - `agent_storage.py`

#### 1.3. Alembic Migrations для PostgreSQL
- [ ] Создать новые миграции с PostgreSQL-specific типами
- [ ] Поддержка обоих backends (SQLite + PostgreSQL)
- [ ] Тесты миграций для PostgreSQL

#### 1.4. Data Migration Script
- [ ] Создать `scripts/migrate_sqlite_to_postgres.py`
- [ ] Функции:
  - Экспорт данных из SQLite
  - Валидация данных
  - Импорт в PostgreSQL
  - Rollback strategy
- [ ] Dry-run режим
- [ ] Progress reporting

---

### 2. Connection Pooling (Приоритет: HIGH)

#### 2.1. SQLAlchemy Pool Configuration
- [ ] QueuePool для PostgreSQL
- [ ] Параметры:
  ```python
  pool_size=5          # Базовое количество connections
  max_overflow=10      # Дополнительные connections при нагрузке
  pool_timeout=30      # Таймаут получения connection
  pool_recycle=3600    # Переиспользование connection (1 час)
  pool_pre_ping=True   # Проверка connection перед использованием
  ```

#### 2.2. Connection Health Checks
- [ ] Pre-ping перед каждым query
- [ ] Graceful reconnection при потере связи
- [ ] Логирование pool metrics

---

### 3. Multi-user Support (Приоритет: MEDIUM)

#### 3.1. Database Indexes
- [ ] Оптимизировать indexes для concurrent access:
  ```sql
  -- ingestion_state
  CREATE INDEX idx_ingestion_source_id ON ingestion_state(source_id);
  
  -- raw_messages
  CREATE INDEX idx_raw_source_channel ON raw_messages(source_ref, channel_id);
  CREATE INDEX idx_raw_date ON raw_messages(date);
  
  -- processed_documents
  CREATE INDEX idx_processed_source ON processed_documents(source_ref);
  CREATE INDEX idx_processed_channel ON processed_documents(channel_id);
  
  -- topics
  CREATE INDEX idx_topics_channel ON topics(channel_id);
  
  -- agent_registry (v3.0)
  CREATE INDEX idx_agents_type ON agent_registry(agent_type);
  CREATE INDEX idx_agents_active ON agent_registry(is_active);
  ```

#### 3.2. Concurrency Testing
- [ ] Тесты с concurrent writes (2-5 processes)
- [ ] Проверка isolation levels
- [ ] Race conditions тесты

---

### 4. Production Configuration (Приоритет: HIGH)

#### 4.1. Docker Compose для Production
- [ ] Обновить `docker-compose.yml`:
  ```yaml
  version: "3.8"
  services:
    postgres:
      image: postgres:16-alpine
      environment:
        POSTGRES_DB: tg_parser
        POSTGRES_USER: tg_parser_user
        POSTGRES_PASSWORD: ${DB_PASSWORD}
      volumes:
        - postgres_data:/var/lib/postgresql/data
      healthcheck:
        test: ["CMD-SHELL", "pg_isready -U tg_parser_user"]
        interval: 10s
        timeout: 5s
        retries: 5
    
    tg_parser:
      build: .
      depends_on:
        postgres:
          condition: service_healthy
      environment:
        - DB_TYPE=postgresql
        - DB_HOST=postgres
        - DB_PORT=5432
        - DB_NAME=tg_parser
        - DB_USER=tg_parser_user
        - DB_PASSWORD=${DB_PASSWORD}
        - LOG_FORMAT=json
        - LOG_LEVEL=INFO
      volumes:
        - ./data:/app/data
      ports:
        - "8000:8000"
  
  volumes:
    postgres_data:
  ```

#### 4.2. Environment Templates
- [ ] Обновить `.env.example` с PostgreSQL настройками
- [ ] Создать `.env.production.example`
- [ ] Создать `.env.development.example` (SQLite)

#### 4.3. Production Deployment Guide
- [ ] Создать `PRODUCTION_DEPLOYMENT.md`:
  - Server requirements
  - Docker setup
  - SSL/TLS configuration
  - Backup strategy
  - Monitoring setup
  - Rollback procedures

---

### 5. Health Checks Enhancement (Приоритет: MEDIUM)

#### 5.1. Database Health Check
- [ ] Обновить `/health` endpoint:
  ```python
  {
    "status": "healthy",
    "version": "3.1.0",
    "database": {
      "type": "postgresql",
      "status": "connected",
      "pool": {
        "size": 5,
        "checked_out": 2,
        "overflow": 0
      }
    },
    "llm_provider": "openai",
    "timestamp": "2025-12-29T12:00:00Z"
  }
  ```

#### 5.2. Readiness Check
- [ ] `/health/ready` — проверка готовности:
  - Database connection
  - Migrations applied
  - LLM API доступен (optional)

---

### 6. Testing (Приоритет: CRITICAL)

#### 6.1. PostgreSQL Integration Tests
- [ ] `tests/test_postgres_storage.py`
- [ ] `tests/test_postgres_migrations.py`
- [ ] `tests/test_connection_pool.py`
- [ ] `tests/test_concurrent_access.py`

#### 6.2. E2E Tests с PostgreSQL
- [ ] Полный pipeline с PostgreSQL
- [ ] Migration test (SQLite → PostgreSQL)
- [ ] Rollback test

#### 6.3. Performance Tests
- [ ] Сравнение SQLite vs PostgreSQL
- [ ] Connection pool overhead
- [ ] Concurrent writes performance

---

### 7. Documentation (Приоритет: HIGH)

#### 7.1. Обновления документации
- [ ] `README.md` — добавить PostgreSQL setup
- [ ] `ENV_VARIABLES_GUIDE.md` — все DB_* переменные
- [ ] `docs/USER_GUIDE.md` — PostgreSQL configuration
- [ ] `PRODUCTION_DEPLOYMENT.md` (новый) — полное руководство

#### 7.2. Migration Guide
- [ ] `MIGRATION_GUIDE_SQLITE_TO_POSTGRES.md`:
  - Когда нужна миграция
  - Пошаговая инструкция
  - Troubleshooting
  - Rollback

---

## 🔄 Migration Path

### Для новых пользователей:
```bash
# 1. Docker Compose с PostgreSQL (recommended)
docker-compose up -d

# 2. Migrations
docker-compose exec tg_parser tg-parser db upgrade --db all

# 3. Start using
docker-compose exec tg_parser tg-parser add-source --source-id my_channel
```

### Для существующих пользователей (SQLite → PostgreSQL):
```bash
# 1. Backup SQLite данных
cp *.sqlite backup/

# 2. Setup PostgreSQL
docker-compose up -d postgres

# 3. Migrate data
python scripts/migrate_sqlite_to_postgres.py \
  --sqlite-dir . \
  --postgres-url postgresql://user:pass@localhost/tg_parser \
  --verify

# 4. Switch config
DB_TYPE=postgresql
DB_HOST=localhost
DB_PORT=5432

# 5. Restart services
docker-compose restart tg_parser
```

---

## ✅ Критерии завершения Session 24

### Must Have (Блокеры production):
- [x] PostgreSQL работает с тремя БД
- [x] Connection pooling настроен и протестирован
- [x] Alembic migrations работают для PostgreSQL
- [x] Docker Compose готов к production
- [x] Migration script (SQLite → PostgreSQL) работает
- [x] Health checks включают database status
- [x] Минимум 30 новых тестов (PostgreSQL)
- [x] Все существующие тесты проходят с PostgreSQL

### Should Have (Желательно):
- [ ] Performance benchmarks (SQLite vs PostgreSQL)
- [ ] Concurrent access тесты (5+ processes)
- [ ] Grafana dashboard для pool metrics
- [ ] Automatic backups setup

### Nice to Have (Можно отложить):
- [ ] Read replicas support
- [ ] Connection string encryption
- [ ] Advanced monitoring (Prometheus)

---

## 📊 Expected Metrics

### Testing:
- **Тесты:** 405 → 435+ (30+ новых)
- **Coverage:** все новые модули
- **PostgreSQL integration:** 100% протестировано

### Performance:
- **Connection pool:** < 10ms overhead
- **Concurrent writes:** 5+ processes без deadlocks
- **Migration:** < 5 минут для 1000 сообщений

### Documentation:
- **Новые документы:** 2 (PRODUCTION_DEPLOYMENT.md, MIGRATION_GUIDE)
- **Обновленные:** 5+ (README, USER_GUIDE, ENV_GUIDE, etc.)

---

## 🚀 Post-Session 24: Production Deployment

### Deployment Checklist:
```bash
# Server Setup (Ubuntu 22.04 recommended)
✓ Docker 24+ installed
✓ Docker Compose v2+ installed
✓ SSL certificates (for HTTPS)
✓ Domain/subdomain configured
✓ Firewall rules (port 8000 or 443)

# Configuration
✓ .env.production configured
✓ DB_PASSWORD secure (32+ chars)
✓ API_KEY secure
✓ LOG_FORMAT=json
✓ LOG_LEVEL=INFO

# Initial Deploy
✓ docker-compose up -d
✓ Health checks passing
✓ Migrations applied
✓ First channel added
✓ Test run successful

# Monitoring
✓ Logs forwarding (CloudWatch/Datadog)
✓ Health check monitoring (UptimeRobot)
✓ Alerts configured
✓ Backup schedule (daily)
```

---

## 🎯 Session 25-27 (Post-Production)

После деплоя можно добавлять features на production:

### Session 25: Comments Support (v3.1.1)
- Парсинг и обработка комментариев
- Comment threads
- Sentiment analysis

### Session 26: Advanced Monitoring (v3.1.2)
- Grafana dashboards
- Prometheus exporters
- Distributed tracing

### Session 27: Scaling (v3.2.0)
- Redis для кэширования
- Kubernetes deployment
- Horizontal scaling

---

## 📚 Reference Documents

**Текущее состояние:**
- [docs/notes/current-state.md](current-state.md)
- [DEVELOPMENT_ROADMAP.md](../../DEVELOPMENT_ROADMAP.md)
- [SESSION23_QUICK_REFERENCE.md](SESSION23_QUICK_REFERENCE.md)

**Технические требования:**
- [docs/architecture.md](../architecture.md)
- [docs/technical-requirements.md](../technical-requirements.md)

**Тестирование:**
- [docs/testing-strategy.md](../testing-strategy.md)
- [REAL_CHANNEL_TEST_RESULTS.md](../../REAL_CHANNEL_TEST_RESULTS.md)

---

## 💡 Implementation Notes

### Priority Order:
1. **PostgreSQL Engine Factory** (2ч) — критичный фундамент
2. **Storage Refactoring** (2ч) — использование engine factory
3. **Alembic для PostgreSQL** (1ч) — миграции
4. **Docker Compose** (1ч) — production setup
5. **Migration Script** (2ч) — SQLite → PostgreSQL
6. **Testing** (1.5ч) — integration + E2E
7. **Documentation** (0.5ч) — guides + updates

**Total:** ~10 часов

### Риски:
| Риск | Вероятность | Митигация |
|------|-------------|-----------|
| PostgreSQL type mismatches | Средняя | Тщательное тестирование типов |
| Connection pool issues | Низкая | Следовать best practices SQLAlchemy |
| Migration data loss | Низкая | Dry-run + validation + backup |
| Performance regression | Низкая | Benchmarks before/after |

### Dependencies:
- ✅ Session 22 (Alembic) — completed
- ✅ Session 23 (Logging, Retries) — completed
- ✅ All tests passing (405/405)

---

## 🎉 Success Criteria

**Session 24 считается успешным, если:**

1. ✅ PostgreSQL полностью заменяет SQLite в production
2. ✅ Connection pooling работает без утечек
3. ✅ Docker Compose поднимает весь stack одной командой
4. ✅ Migration script успешно мигрирует тестовые данные
5. ✅ Все 435+ тестов проходят (PostgreSQL + SQLite)
6. ✅ Документация обновлена и покрывает все сценарии
7. ✅ Ready для production деплоя на сервер

**После Session 24 → PRODUCTION DEPLOY 🚀**

---

**Prepared by:** AI Assistant (Claude Sonnet 4.5)  
**Date:** 29 декабря 2025  
**Version:** v3.1.0-alpha.2 → v3.1.0

