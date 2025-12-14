# Промпт для начальной настройки TG_parser в Cursor

```text
Ты – старший Python‑инженер, работающий в Cursor с доступом к терминалу и редактированию файлов.
Проект: TG_parser – инструмент, который собирает сообщения из Telegram‑каналов, обрабатывает их с помощью ИИ и формирует тематическую базу знаний (в MVP — через CLI‑экспорт артефактов).
Твоя задача: с нуля подготовить рабочую структуру проекта, окружение, документацию и каркас кода так, чтобы после твоей работы можно было сразу начинать реализацию.

Иcходные данные:
- Локальный путь: /Users/alexanderefimov/TG_parser
- Репозиторий GitHub: https://github.com/AlexEfimov/TG_parser
- Python: использовать 3.12 и виртуальное окружение .venv в корне проекта.

Сделай последовательно следующее (используй терминал и правку файлов самостоятельно):

1) Git и рабочая копия
   - В /Users/alexanderefimov/TG_parser убедись, что это git‑репозиторий, привязанный к origin https://github.com/AlexEfimov/TG_parser (ветка main).
   - Если каталог пустой или неинициализирован – клонируй репозиторий так, чтобы в итоге проект соответствовал origin/main.

2) Python 3.12 и .venv
   - Создай/обнови файл `.python-version` со значением `3.12`.
   - Создай виртуальное окружение `.venv` с Python 3.12 (например, `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -m venv .venv`).
   - Внутри `.venv` проверь: `python --version` → 3.12.x и `which python` → `/Users/alexanderefimov/TG_parser/.venv/bin/python`.
   - В конце явно напомни пользователю: в Cursor выбрать интерпретатор через Command Palette → `Python: Select Interpreter` → путь к `.venv/bin/python`.

3) Структура документации в `docs/`
   Создай (если отсутствует) или обнови каталог `docs/` и заполни его минимально осмысленными стартовыми версиями:

   - `architecture.md` – обзор архитектуры (цель, подсистемы: Ingestion/Processing/Storage/Access / Export, поток MVP: Telegram → RawTelegramMessage → ProcessedDocument (+ Topic*) → CLI‑экспорт → KnowledgeBaseEntry, основные нефункциональные требования).
   - `pipeline.md` – описание пайплайна (планировщик → ingestion → processing → storage → CLI‑экспорт, режимы backfill и регулярный).
   - `testing-strategy.md` – уровни тестов (unit/integration/E2E), базовые сценарии, тестовые данные, метрики.

   Подкаталог `docs/contracts/` с JSON‑схемами:
   - `raw_telegram_message.schema.json` – поля: id, message_type, source_ref, channel_id, date (date-time), text; опционально parent_message_id, thread_id, language, raw_payload; `additionalProperties: true`.
   - `processed_document.schema.json` – id, source_ref, source_message_id, channel_id, processed_at (date-time), text_clean; опционально summary, topics[], entities[{type,value,confidence?}], language, metadata.
   - `knowledge_base_entry.schema.json` – id, source{type, channel_id?, message_id?, message_type?, source_ref?, topic_id?}, created_at, title, content; опционально topics[], tags[], vector[number], metadata.

   Подкаталог `docs/adr/`:
   - `0001-overall-architecture.md` – общая архитектура TG_parser (Context/Decision/Consequences).
   - `0002-telegram-ingestion-approach.md` – подход к Telegram ingestion (отдельный модуль, учёт offset, режимы backfill/online).
   - `0003-storage-and-indexing.md` – подход к хранилищу и индексации (логическая модель KB entry, поддержка разных БД и векторного индекса).

   Бизнес‑ и тех‑документы в корне `docs/`:
   - `product-overview.md` – бизнес‑описание (назначение, целевая аудитория, ключевые сценарии, ценность, ссылки на другие документы).
   - `business-requirements.md` – бизнес‑требования (BR‑1.., основные use cases, ограничения, бизнес‑метрики).
   - `tech-stack.md` – выбор и фиксация стека (Python 3.12 + venv, Telegram‑клиент, облачный LLM, хранилище SQLite→PostgreSQL, инфраструктурные элементы).
   - `technical-requirements.md` – технические требования (TR‑1.., нефункциональные требования, требования к интерфейсам и observability, обязательная привязка к `docs/contracts/*.schema.json`).

   Подкаталог `docs/notes/`:
   - `docs-structure-and-templates.md` – краткое описание структуры `docs/` и назначения всех перечисленных файлов.

4) Роли ИИ‑агентов и чаты Cursor
   - В `docs/notes/agents-roles.md` опиши рекомендованные постоянные чаты и добавь короткие стартовые сообщения (чтобы пользователь мог их копировать в первый запрос каждого чата):
     - Product / BA (`TG_parser – Product`) – формулирует бизнес‑описание и бизнес‑требования, работает с `product-overview.md` и `business-requirements.md`, не меняет архитектуру/код.
     - Tech & Stack (`TG_parser – Tech & Stack`) – поддерживает актуальность `technical-requirements.md` и фиксирует/уточняет `tech-stack.md` (включая выбор LLM‑провайдера пользователем).
     - Architecture & ADR (`TG_parser – Architecture & ADR`) – поддерживает `architecture.md`, `pipeline.md`, `contracts/*.schema.json`, ADR в `docs/adr/`, не противоречит бизнес/тех‑докам.
     - Implementation (`TG_parser – Implementation`) – пишет и меняет только код, строго следуя контрактам и ADR, не редактирует бизнес/тех‑доки без явного запроса.
     - Tests & QA (`TG_parser – Tests & QA`) – опирается на `testing-strategy.md` и контракты, проектирует и пишет unit/integration/E2E‑тесты и фикстуры.

5) Минимальный каркас кода пакета `tg_parser`
   Создай пакет `tg_parser/` с такой структурой и минимумом кода:

   - `tg_parser/__init__.py` – краткое описание пакета и перечисление подсистем.

   - `tg_parser/domain/__init__.py` – заглушка.
   - `tg_parser/domain/models.py` – датаклассы:
     - `RawTelegramMessage` (id, message_type, source_ref, channel_id, date: datetime, text, parent_message_id?, thread_id?, language?, raw_payload?).
     - `Entity` (type, value, confidence?).
     - `ProcessedDocument` (id, source_ref, source_message_id, channel_id, processed_at, text_clean, summary?, topics: list[str], entities: list[Entity], language?, metadata?).
     - `KnowledgeBaseEntrySource` (type, channel_id?, message_id?, message_type?, source_ref?, topic_id?).
     - `KnowledgeBaseEntry` (id, source, created_at, title, content, topics: list[str], tags: list[str], vector?: sequence[float], metadata?).
     - типы‑алиасы: `RawMessages`, `ProcessedDocuments`, `KnowledgeBaseEntries`.

   - `tg_parser/ingestion/__init__.py` и `tg_parser/ingestion/interfaces.py`:
     - Протокол `TelegramIngestion` с методами `fetch_history() -> RawMessages` и `fetch_new() -> RawMessages`.

   - `tg_parser/processing/__init__.py` и `tg_parser/processing/interfaces.py`:
     - Протокол `ProcessingPipeline` с методом `process(messages: RawMessages) -> ProcessedDocuments`.

   - `tg_parser/storage/__init__.py` и `tg_parser/storage/interfaces.py`:
     - Протокол `KnowledgeBaseWriter` с методом `upsert(entries: KnowledgeBaseEntries) -> None`.

   - `tg_parser/config/__init__.py` – пустой модуль с комментариями, что здесь будет конфигурация.

   На этом этапе не подключай конкретные библиотеки Telegram, БД или LLM – только доменные модели и интерфейсы.

6) Проверки и git
   - Кратко проверь, что пакет импортируется: внутри `.venv` выполни `python -c "import tg_parser; print(tg_parser.__name__)"`.
   - Убедись, что `git status` показывает только ожидаемые изменения, затем:
     - `git add` всех новых/изменённых файлов;
     - `git commit` с осмысленным сообщением (например, `"Bootstrap project docs and domain interfaces"`);
     - `git push origin main`.

7) Финальный отчёт
   - В конце одним сообщением опиши:
     - что сделано с окружением и Python;
     - какая структура у `docs/`;
     - как устроен пакет `tg_parser/`;
     - какие роли и стартовые сообщения рекомендованы для чатов Cursor;
     - какие следующие шаги по реализации (реализация ingestion, уточнение стека, написание первых тестов).

Всегда придерживайся принципов KISS, Clean Architecture, SOLID и разделения доменной логики и инфраструктуры.
```
