# Roadmap развития TG_parser (после Session 37)

**Дата:** 24 марта 2026  
**Версия:** v3.4.0 (инкрементальная топикизация, CLI polish)  
**Статус:** Утверждён

---

## Текущее состояние

- Full pipeline работает: ingest → process → topicize → export
- PostgreSQL backend (локальный Homebrew), Anthropic Claude Sonnet 4
- Services layer, чистая архитектура после рефакторинга Session 29
- Тестовый канал @labdiagnostica_logical: 1130 raw, 1128 processed, 80 тем
- Coverage: 77.4% (875/1130 документов покрыты темами)
- Успешность обработки: 99.82%
- Инкрементальная топикизация: Phase 1 (keyword) + Phase 2 (LLM discover)

---

## Завершённые этапы

### P1: Инкрементальная обработка ✅ (Session 30)

- Scheduled pipeline (ingest → process → topicize) по расписанию
- `run_incremental_for_all_sources()` для активных источников
- APScheduler интеграция, `poll_interval_seconds`

### P2: Параллельная обработка ✅ (Session 31)

- `--concurrency` CLI, rate limiter, батчевая обработка
- Default concurrency 3-5, обработка 1000+ за минуты

### P3: Улучшение обработки комментариев ✅ (Session 32)

- Robust parsing для коротких/пустых комментариев
- Контекст родительского поста при обработке

### P4: Топикизация — fix bundles ✅ (Session 33)

- 80 тем (68 cluster + 12 singleton), coverage 77.4%
- Bundles содержат anchors + supporting items
- Programmatic keyword matching для supporting items

### Инкрементальная топикизация ✅ (Sessions 34-37)

Полный цикл реализован — от архитектуры до CLI:

**Session 34 — Планирование:**
- Архитектурный план в `ARCHITECTURE_INCREMENTAL_TOPICIZATION.md`
- Двухфазный подход: keyword assign (0 tokens) + LLM discover (~20K tokens)

**Session 35 — Phase 1 (Keyword Assign):**
- `assign_documents_to_topics()` — программное сопоставление по keywords
- `_tokenize_topic_card()`, `_tokenize_document()`, `_compute_match_score()`
- Strong tokens (topics/summary) + weak tokens (text_clean) с весами
- `add_items()` — инкрементальное обновление bundles
- Scheduler интеграция: автоматический Phase 1 при новых документах

**Session 36 — Phase 2 (LLM Discover):**
- `discover_new_topics()` — LLM анализ для unassigned документов
- Три исхода: assign to existing, create new topic, mark unassignable
- Retry: 3 попытки на JSONDecodeError, fallback → all unassignable
- Промпты: `INCREMENTAL_DISCOVER_SYSTEM_PROMPT`, `build_incremental_discover_prompt`
- `TopicCard.metadata.origin = "discovered"` для новых тем

**Session 37 — Интеграция и CLI:**
- CLI `topicize --mode incremental` — Phase 1 + Phase 2 для uncovered docs
- CLI `topicize --mode assign-only` — только Phase 1 (0 LLM tokens)
- CLI `topicize --force` — полная re-topicization
- `run_incremental_topicization_for_uncovered()` — CLI entry point
- `_run_assign_only()` — Phase 1-only mode
- E2E тест: 10 topics, 20 docs (10 covered + 10 new), Phase 1 + Phase 2
- 39 тестов: 27 unit + 5 E2E + 2 uncovered-docs + 5 CLI dispatch
- Все 471+ тестов проходят, 0 regressions

---

## CLI-команды topicization

```bash
# Полная topicization (default)
tg-parser topicize --channel <id>

# Полная re-topicization (пересоздание всех тем)
tg-parser topicize --channel <id> --force

# Incremental: Phase 1 + Phase 2 для uncovered docs
tg-parser topicize --channel <id> --mode incremental

# Assign-only: только Phase 1, 0 LLM tokens
tg-parser topicize --channel <id> --mode assign-only
```

---

## Текущие метрики

| Метрика | Значение |
|---------|----------|
| Documents | 1130 (906 posts + 224 comments) |
| TopicCards | 80 (68 cluster + 12 singleton) |
| Coverage | 77.4% (875/1130) |
| Avg items/bundle | 86.4 |
| Tests | 471+ passed, 0 regressions |

---

## Следующие этапы

### P5: RAG-интеграция (Next)

**Цель:** Векторный поиск по базе знаний, Q&A чат-бот по контенту каналов.

**Зависит от:** P1-P4 + инкрементальная топикизация (всё завершено).

**Что нужно:**
- Embeddings (OpenAI/Anthropic)
- Векторное хранилище (pgvector или ChromaDB)
- Retrieval pipeline
- Q&A endpoint

**Влияние:** KB из файла на диске превращается в рабочий инструмент — можно задавать вопросы на естественном языке.

---

### P6: Веб-интерфейс / дашборд

**Цель:** Визуализация результатов обработки.

**Что нужно:** Frontend (React/Vue/Streamlit), API endpoints для тем/документов/статистики.

---

### P7: Мульти-канальная аналитика

**Цель:** Кросс-канальные темы, сравнение каналов, единая база знаний.

---

### P8: Мониторинг и метрики

**Цель:** Prometheus exporters, Grafana дашборды, алерты на ошибки LLM.

---

## Оставшийся технический долг

Не блокирует разработку фич. Устранять при появлении реальной потребности:

- `tokens_used` в IncrementalTopicizeResult пока 0 — требуется изменение LLM client API для доступа к usage из API response
- Batch splitting для `--mode incremental` при > 50 unassigned docs — текущий канал ~255 uncovered, при необходимости нужен split
- `processing/` читает global config (3 файла) — optional DI уже есть
- `api/` и `services/` импортируют конкретные repo вместо ports — единственная реализация

---

**Подготовлено:** Session 37  
**Следующий шаг:** P5 — RAG-интеграция
