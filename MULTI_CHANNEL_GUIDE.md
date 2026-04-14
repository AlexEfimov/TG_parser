# 📚 Работа с несколькими каналами

**Версия:** 4.2  
**Обновлено:** April 2026

> ✅ **Production**: 5 каналов (labdiagnostica, Lab4health, AgeManagment, genotek, LongevityClub), 5405 документов, 401 тема, cross-channel topic linking

## 🎯 Краткий ответ

**Вопрос**: Если работать с другим каналом, данные в output заменятся?

**Ответ**: 
- ✅ **База данных (PostgreSQL)**: данные **НЕ заменятся**, будут добавлены
- ⚠️ **Export файлы (output/)**: **ЗАМЕНЯТСЯ**, если использовать ту же директорию

---

## 📊 Как система хранит данные

### 1️⃣ База данных (PostgreSQL + pgvector)

Все каналы хранятся в одной PostgreSQL базе в 3 наборах таблиц:

```
tg_parser (PostgreSQL database)
├── Ingestion tables (ingestion_state)
├── Raw storage tables (raw_messages, raw_attachments)
└── Processing tables (processed_documents, topics, etc.)
```

**Поведение (одинаковое для обоих backend):**
- ✅ При добавлении нового канала данные **добавляются**
- ✅ Старые данные **сохраняются**
- ✅ Каждый канал идентифицируется по `channel_id`
- ✅ Можно работать с множеством каналов одновременно
- ✅ **PostgreSQL**: поддерживает concurrent access от нескольких пользователей

### 2️⃣ Export файлы (временные, для экспорта)

Структура export:

```
output/
├── kb_entries.ndjson    ← Контент для RAG
├── topics.json          ← Каталог тем
└── topic_*.json         ← Детальные карточки тем
```

**Поведение**:
- ⚠️ Файлы **перезаписываются** при каждом export
- ⚠️ Если использовать ту же директорию для разных каналов, **данные предыдущего канала будут заменены**

---

## ✅ Решение: Используйте разные директории

### 🎯 Рекомендуемый подход

```bash
# Канал 1: labdiagnostica
python -m tg_parser.cli run \
  --source labdiagnostica \
  --out ./output_labdiagnostica

# Канал 2: another_channel  
python -m tg_parser.cli add-source \
  --source-id another_channel \
  --channel-id @another_channel

python -m tg_parser.cli run \
  --source another_channel \
  --out ./output_another_channel

# Канал 3: third_channel
python -m tg_parser.cli add-source \
  --source-id third_channel \
  --channel-id @third_channel

python -m tg_parser.cli run \
  --source third_channel \
  --out ./output_third_channel
```

**Результат**:
```
TG_parser/
├── (PostgreSQL)                    (3 канала в одной БД)
├── output_labdiagnostica/
│   ├── kb_entries.ndjson
│   └── topics.json
├── output_another_channel/
│   ├── kb_entries.ndjson
│   └── topics.json
└── output_third_channel/
    ├── kb_entries.ndjson
    └── topics.json
```

---

## 🔄 Альтернативные сценарии

### Сценарий 1: Сбор без export, потом раздельный export

**Шаг 1**: Собрать и обработать данные всех каналов

```bash
# Канал 1 — pipeline + export в отдельную папку
python -m tg_parser.cli run \
  --source channel1 \
  --out ./output_channel1

# Канал 2
python -m tg_parser.cli run \
  --source channel2 \
  --out ./output_channel2

# Канал 3
python -m tg_parser.cli run \
  --source channel3 \
  --out ./output_channel3
```

**Шаг 2**: Экспортировать повторно по отдельности (при необходимости)

```bash
# Export канала 1
python -m tg_parser.cli export \
  --channel channel1_id \
  --out ./output_channel1

# Export канала 2
python -m tg_parser.cli export \
  --channel channel2_id \
  --out ./output_channel2

# Export канала 3
python -m tg_parser.cli export \
  --channel channel3_id \
  --out ./output_channel3
```

### Сценарий 2: Объединённый export (все каналы в одном файле)

⚠️ **Частично реализовано** - требует доработки кода

```bash
# Export всех каналов сразу (без фильтра)
python -m tg_parser.cli export \
  --out ./output_all_channels

# В будущем: все KB entries из всех каналов в одном файле
```

---

## 📋 Практические примеры

### Пример 1: Два канала одновременно

```bash
# 1. Добавить оба источника
python -m tg_parser.cli add-source \
  --source-id tech_news \
  --channel-id @tech_channel

python -m tg_parser.cli add-source \
  --source-id science_news \
  --channel-id @science_channel

# 2. Собрать данные
python -m tg_parser.cli run \
  --source tech_news \
  --out ./output_tech

python -m tg_parser.cli run \
  --source science_news \
  --out ./output_science

# 3. Результат
# output_tech/     - данные tech_channel
# output_science/  - данные science_channel
# PostgreSQL       - оба канала в одной БД
```

### Пример 2: Переэкспорт существующего канала

```bash
# У вас уже есть labdiagnostica в БД (844 сообщения)

# Экспорт в новую папку (старые данные сохранятся)
python -m tg_parser.cli export \
  --channel labdiagnostica_logical \
  --out ./output_labdiagnostica_v2

# Теперь у вас два export:
# output_final/              - первый export
# output_labdiagnostica_v2/  - второй export
```

### Пример 3: Инкрементальное обновление

```bash
# Добавление новых сообщений из существующего канала
python -m tg_parser.cli run \
  --source labdiagnostica \
  --out ./output_labdiagnostica_latest \
  --mode incremental

# Соберёт только новые сообщения с момента последнего запуска
```

---

## 🔍 Проверка состояния БД

### Посмотреть все каналы в базе

```bash
docker compose exec postgres psql -U tg_parser_user -d tg_parser -c \
  "SELECT DISTINCT channel_id, COUNT(*) as count 
   FROM raw_messages 
   GROUP BY channel_id;"
```

### Посмотреть обработанные документы

```bash
docker compose exec postgres psql -U tg_parser_user -d tg_parser -c \
  "SELECT channel_id, COUNT(*) as count 
   FROM processed_documents 
   GROUP BY channel_id;"
```

### Посмотреть темы по каналам

```bash
docker compose exec postgres psql -U tg_parser_user -d tg_parser -c \
  "SELECT channel_id, COUNT(*) as count 
   FROM topic_cards 
   GROUP BY channel_id;"
```

---

## 🎓 Рекомендации Best Practices

### ✅ Хорошо

```bash
# Используйте осмысленные имена директорий
--out ./output_medical_channel
--out ./output_tech_channel

# Используйте временные метки для версионности
--out ./output_$(date +%Y%m%d)
--out ./output_channel1_v2

# Группируйте по темам
--out ./exports/medical/channel1
--out ./exports/tech/channel2
```

### ❌ Плохо

```bash
# НЕ используйте одну директорию для всех каналов
--out ./output  # данные будут перезаписываться!

# НЕ используйте случайные имена
--out ./temp
--out ./test
```

---

## 💡 Итоговые рекомендации

1. **Всегда используйте разные директории** для export разных каналов:
   ```bash
   --out ./output_channel1
   --out ./output_channel2
   ```

2. **Базы данных**: не беспокойтесь, все каналы хранятся вместе и не конфликтуют

3. **Структура проекта**:
   ```
   TG_parser/
   ├── (PostgreSQL)      # Все каналы в одной БД
   ├── output_channel1/  # Export канала 1
   ├── output_channel2/  # Export канала 2
   └── output_channel3/  # Export канала 3
   ```

4. **Переэкспорт**: можно в любой момент переэкспортировать любой канал в новую папку

5. **Инкрементальное обновление**: работает корректно для всех каналов независимо

---

## 🔗 См. также

- [README.md](README.md) — основная документация
- [OUTPUT_FORMATS.md](OUTPUT_FORMATS.md) — форматы выходных файлов
- [REAL_CHANNEL_TEST_RESULTS.md](REAL_CHANNEL_TEST_RESULTS.md) — результаты тестирования
- [COMPLETION_SUMMARY.md](COMPLETION_SUMMARY.md) — краткий итог
- [DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md) — полное оглавление документации

---

**Вывод**: Работайте с любым количеством каналов! Просто используйте разные директории для export, и всё будет отлично. 🚀

---

**Версия**: 1.1  
**Последнее обновление**: 28 декабря 2025
