# Стартовый промпт: D3 — Telegram Session в Docker

## Задача

Обеспечить работу Telegram-авторизации в Docker-контейнере:
1. **D3a:** Заменить bind mount файла на Docker volume для session-файла
2. **D3b:** Создать CLI-команду `tg-parser auth` для интерактивной авторизации
3. **D3c:** Обработка expired session (реавторизация без потери данных)
4. **D3d:** Документация: первичная авторизация в Docker
5. **D3e:** Тесты для новой CLI-команды

## Контекст

В D2 Docker-стек доведён до production-ready: `docker compose up` запускает 3 сервиса (postgres, API+scheduler, MCP). Все 620+ тестов проходят. Образ собирается из `pyproject.toml`, ENTRYPOINT = `tg-parser`.

**Проблема:** При первом запуске Telethon требует интерактивного ввода кода подтверждения (`client.start(phone=...)` промптит в stdin). В Docker-контейнере это работает только через `docker compose run`, а не через `docker compose up` (где stdin закрыт). Также:
- Текущий bind mount (`./tg_parser_session.session:/app/tg_parser_session.session`) требует что файл уже существует на хосте
- Если файла нет — Docker создаёт директорию вместо файла (известная проблема bind mount)
- Session-файл — это SQLite-база Telethon, которая модифицируется при каждом подключении

## Текущее состояние файлов

### `tg_parser/ingestion/telegram/telethon_client.py` — подключение к Telegram

```python
class TelethonClient:
    def __init__(self, settings: Settings):
        if not settings.telegram_api_id or not settings.telegram_api_hash:
            raise ValueError("Missing Telegram API credentials...")
        self.settings = settings
        self.client: TelethonTelegramClient | None = None

    async def connect(self) -> None:
        if self.client:
            return
        self.client = TelethonTelegramClient(
            session=self.settings.telegram_session_name,
            api_id=self.settings.telegram_api_id,
            api_hash=self.settings.telegram_api_hash,
        )
        await self.client.start(phone=self.settings.telegram_phone)
        # ^^^ Здесь Telethon промптит код подтверждения, если нет валидной сессии
```

`client.start(phone=...)` вызывает `input()` для ввода кода — это интерактивная операция.

### `tg_parser/config/settings.py` — путь к session-файлу

```python
telegram_api_id: int | None = None
telegram_api_hash: str | None = None
telegram_phone: str | None = None
telegram_session_name: str = "tg_parser_session"

@model_validator(mode="after")
def _resolve_session_path(self) -> "Settings":
    p = Path(self.telegram_session_name)
    if not p.is_absolute():
        self.telegram_session_name = str(_PROJECT_ROOT / p)
    return self
```

`_PROJECT_ROOT` = parent.parent от `settings.py` = корень проекта. В Docker это `/app`.
Итоговый путь: `/app/tg_parser_session` → Telethon создаёт `/app/tg_parser_session.session`.

### `docker-compose.yml` — текущий mount (проблемный)

```yaml
tg_parser:
  volumes:
    - ./data:/app/data
    - ./.env:/app/.env:ro
    - ./prompts:/app/prompts:ro
    # Telegram session persistence
    - ./tg_parser_session.session:/app/tg_parser_session.session
```

Проблема: если файл `./tg_parser_session.session` не существует на хосте, Docker создаст директорию с этим именем.

### CLI — нет команды auth

В `tg_parser/cli/app.py` нет команды для Telegram-авторизации. Авторизация происходит "побочным эффектом" при первом `tg-parser ingest`.

## Что нужно сделать

### D3a: Docker volume вместо bind mount файла

Заменить проблемный bind mount файла на volume для директории с session:

```yaml
# docker-compose.yml
tg_parser:
  volumes:
    - ./data:/app/data
    - ./.env:/app/.env:ro
    - ./prompts:/app/prompts:ro
    - tg_session:/app/sessions  # <-- volume вместо файла

  environment:
    - TELEGRAM_SESSION_NAME=/app/sessions/tg_parser_session

volumes:
  tg_session:
    name: tg_parser_session
```

Или альтернатива — использовать `./data/sessions/` как bind mount директории (проще для бэкапа):

```yaml
volumes:
  - ./data/sessions:/app/sessions
environment:
  - TELEGRAM_SESSION_NAME=/app/sessions/tg_parser_session
```

Второй вариант предпочтительнее: session-файл на хосте, доступен для бэкапа и переноса.

### D3b: CLI-команда `tg-parser auth`

Добавить в `tg_parser/cli/app.py` команду `auth` для интерактивной авторизации:

```python
@app.command()
def auth():
    """Авторизоваться в Telegram (интерактивный ввод кода).
    
    Создаёт session-файл для последующих запусков ingestion.
    Используйте при первом запуске или при expired session.
    
    В Docker:
        docker compose run --rm tg_parser auth
    """
    import asyncio
    from tg_parser.config import settings
    from tg_parser.ingestion.telegram.telethon_client import TelethonClient
    
    client = TelethonClient(settings)
    try:
        asyncio.run(client.connect())
        typer.echo("✅ Авторизация успешна! Session сохранена.")
    finally:
        asyncio.run(client.disconnect())
```

Ключевое: `docker compose run --rm tg_parser auth` даёт интерактивный stdin, в отличие от `docker compose up`.

### D3c: Обработка expired session

Telethon при expired session вызывает `client.start()` снова с промптом кода. Нужно:
- Проверить текущее поведение: что происходит при expired session в `telethon_client.py`
- Добавить в `tg-parser auth` опцию `--force` для принудительной реавторизации (удалить старый session-файл и создать новый)
- Добавить понятное сообщение об ошибке при неинтерактивном запуске (когда `input()` невозможен)

### D3d: Документация

Обновить `PRODUCTION_DEPLOYMENT.md` — добавить секцию "Telegram Authorization":

```markdown
### First-Time Telegram Authorization

# 1. Configure credentials in .env
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=your_hash
TELEGRAM_PHONE=+1234567890

# 2. Run interactive auth
docker compose run --rm tg_parser auth

# 3. Enter the code from Telegram
# Session file saved to ./data/sessions/

# 4. Now ingestion will work non-interactively
docker compose run --rm tg_parser ingest --source my_channel
```

### D3e: Тесты

- Unit-тест CLI `auth` команды (mock TelethonClient)
- Тест что session path корректно резолвится с абсолютным путём
- Тест `--force` опции (удаление старого session)

## Тестирование

### Юнит-тесты
```bash
.venv/bin/python -m pytest tests/ --ignore=tests/test_postgres_integration.py --ignore=tests/test_postgres_concurrency.py --ignore=tests/test_migrations.py --ignore=tests/test_storage_integration.py -v
```

### Проверка в Docker
```bash
# 1. Создать директорию для sessions
mkdir -p data/sessions

# 2. Запустить авторизацию
docker compose run --rm tg_parser auth

# 3. Проверить что session создана
ls -la data/sessions/

# 4. Проверить что ingestion работает
docker compose run --rm tg_parser ingest --source labdiagnostica_logical --limit 5
```

## Файлы для изменения

| Файл | Что делать |
|------|-----------|
| `docker-compose.yml` | D3a: volume вместо bind mount файла |
| `tg_parser/cli/app.py` | D3b: команда `auth` |
| `PRODUCTION_DEPLOYMENT.md` | D3d: секция Telegram Authorization |
| `.env.example` | D3d: обновить TELEGRAM_SESSION_NAME |
| `env.production.example` | D3d: обновить TELEGRAM_SESSION_NAME |
| `tests/test_cli_auth.py` (новый) | D3e: тесты auth команды |

## Чего НЕ делать

- **Не менять** `telethon_client.py` — он уже корректно работает с session
- **Не менять** `ingestion_service.py` — авторизация происходит в `client.start()`
- **Не добавлять** автоматическую авторизацию при `docker compose up` — это должно быть явным шагом
- **Не хранить** session в Docker image — это секрет, он должен быть в volume

## Порядок выполнения

1. **D3a** (15 мин) — volume в docker-compose.yml
2. **D3b** (30 мин) — CLI команда `auth`
3. **D3c** (20 мин) — обработка expired session, --force
4. **D3e** (30 мин) — тесты
5. **D3d** (15 мин) — документация

## Критерии приёмки

1. `docker compose run --rm tg_parser auth` выполняет интерактивную авторизацию
2. Session-файл сохраняется в `./data/sessions/` на хосте (или в Docker volume)
3. Последующие `tg-parser ingest` работают без повторной авторизации
4. `tg-parser auth --force` удаляет старую session и авторизуется заново
5. При неинтерактивном запуске (docker compose up) с expired session — понятное сообщение об ошибке
6. Все 620+ существующих тестов проходят
7. Новые тесты для `auth` команды проходят
