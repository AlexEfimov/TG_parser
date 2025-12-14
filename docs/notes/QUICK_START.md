# Quick Start для нового агента

## 📋 Что нужно знать за 5 минут

### Статус: Processing Pipeline работает, но есть 4 бага

**Файл с деталями**: `docs/notes/SESSION_HANDOFF.md` (609 строк)

---

## 🐛 4 БАГА (требуют немедленного исправления)

### 1. `.gitignore` строка 57
```diff
- run s/
+ runs/
```

### 2. `tg_parser/processing/__init__.py` строки 21-27
Удалить дублирующий блок `__all__` (оставить только первый)

### 3. `tg_parser/processing/pipeline.py` строка 137
```diff
- await self.failure_repo.clear_failure(message.source_ref)
+ await self.failure_repo.delete_failure(message.source_ref)
```

### 4. `tg_parser/processing/pipeline.py` строки 167-172
```diff
  await self.failure_repo.record_failure(
      source_ref=message.source_ref,
-     error_type=type(last_error).__name__,
+     channel_id=message.channel_id,
+     attempts=max_attempts,
+     error_class=type(last_error).__name__,
      error_message=str(last_error),
-     attempts=max_attempts,
  )
```

---

## ✅ После исправления

```bash
# 1. Запустить тесты
pytest

# 2. Проверить форматирование
ruff format .

# 3. Коммит
git add -A
git commit -m "Fix 4 bugs in processing pipeline"
```

---

## 🎯 Следующие задачи (по приоритету)

1. **Исправить 4 бага** (15 мин)
2. **ProcessingFailureRepo** (2 часа)
3. **CLI export** (3 часа)
4. **Topicization** (7 часов)
5. **Ingestion** (15 часов)

---

## 📚 Ключевые документы

- `docs/notes/SESSION_HANDOFF.md` — **полная документация** (читать первым!)
- `docs/architecture.md` — DDL схемы
- `docs/pipeline.md` — алгоритмы
- `docs/technical-requirements.md` — TR-* требования

---

## 💻 Основные команды

```bash
# Setup
source .venv/bin/activate
python -m tg_parser.cli init

# Тестирование
python scripts/add_test_messages.py
python -m tg_parser.cli process --channel test_channel
python scripts/view_processed.py --channel test_channel

# Тесты
pytest                                    # Все (53 теста)
pytest tests/test_processing_pipeline.py  # Только processing (16 тестов)
```

---

## ⚠️ Важно

- ✅ Код **РАБОТАЕТ** в production
- ✅ Все 53 теста проходят
- ⚠️ Но есть 4 бага в edge cases
- ⚠️ Баги 3-4 проявятся только когда `failure_repo` будет реально использоваться

---

**Начни с**: Прочитать `SESSION_HANDOFF.md`, затем исправить 4 бага.
