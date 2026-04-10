# Совместимость tg-parser MCP с ChatGPT

**Дата проверки:** 2026-04-02
**Сервер:** `https://mcp.tgp.efimov.mobi/mcp`
**Версия:** TG_parser Knowledge Base v1.27.0

---

## Общая информация

ChatGPT поддерживает подключение внешних MCP-серверов через Developer Mode.
Серверы подключаются в Settings → Connectors (Apps) → Create.

### Требования ChatGPT к MCP-серверу

- Сервер должен быть доступен по **HTTPS** (localhost не поддерживается)
- Поддерживаемые транспорты: **Streamable HTTP** (рекомендуется) и **HTTP+SSE** (legacy)
- Endpoint: единый URL, принимающий POST и GET (например `/mcp`)
- Авторизация: OAuth 2.1 или Bearer token
- CORS: обязательна поддержка preflight-запросов от `chatgpt.com`
- Tool annotations: обязательны (`readOnlyHint`, `destructiveHint`, `openWorldHint`)

### Доступность по планам

- **Pro, Plus, Team, Enterprise, Edu** — полная поддержка MCP через Developer Mode
- Без Developer Mode сервер должен иметь инструменты `search` и `fetch` (специфичные для Deep Research)
- С Developer Mode — любые инструменты принимаются

---

## Результаты проверки

### ✅ Работает (зелёная зона)

#### Streamable HTTP транспорт
Сервер корректно отвечает на POST к `/mcp`, возвращает `Content-Type: application/json`.
ChatGPT Responses API работает с remote MCP серверами, поддерживающими Streamable HTTP.

```
POST https://mcp.tgp.efimov.mobi/mcp
→ HTTP/2 200, Content-Type: application/json
```

#### Версия протокола
Сервер поддерживает несколько версий протокола:
- `2025-11-25` — новейшая (подтверждено)
- `2025-03-26` — тоже работает (подтверждено)

#### HTTPS и сертификат
- Валидный Let's Encrypt сертификат (CN=tgp.efimov.mobi)
- SAN включает `mcp.tgp.efimov.mobi`
- TLSv1.3, срок действия до 2026-07-01

#### Авторизация
- Bearer token работает корректно
- Без токена возвращается `HTTP 401` с `WWW-Authenticate` header
- Формат ответа: `Bearer error="invalid_token", error_description="Authentication required"`

#### Инструменты
Все 14 tools корректно возвращаются через `tools/list`:
- `search_knowledge_base` — семантический поиск
- `ask_question` — RAG Q&A
- `list_topics` / `get_topic_details` — навигация по темам
- `list_channels` — список каналов
- `get_document` — полный текст документа
- `get_related_topics` — связанные темы
- `get_cross_channel_stats` — кросс-канальная аналитика
- `add_channel` — добавление канала
- `pause_channel` / `resume_channel` — управление каналами
- `remove_channel` — удаление канала
- `get_pipeline_status` — статус пайплайна
- `trigger_pipeline` — запуск обработки

---

### ❌ Проблемы (нужно исправить)

#### 1. CORS headers отсутствуют (КРИТИЧНО)

**Симптом:** При запросе с `Origin: https://chatgpt.com` сервер не возвращает
CORS-заголовков. OPTIONS preflight возвращает `401` вместо `204`.

**Почему важно:** ChatGPT работает в браузере и отправляет preflight OPTIONS-запросы
перед каждым POST. Без CORS браузер блокирует запросы полностью.

**Тест:**
```bash
curl -I -X OPTIONS https://mcp.tgp.efimov.mobi/mcp \
  -H "Origin: https://chatgpt.com" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: content-type, mcp-session-id, authorization"
# Результат: HTTP/2 401 — нет CORS headers
```

**Решение — вариант A (reverse proxy на границе):**  
Для **Nginx** — блок ниже в `location /mcp`. Если TLS делает **Caddy** из репозитория (`docker/Caddyfile`, профиль `production`), добавьте те же CORS-заголовки в соответствующий site-блок для `DOMAIN_MCP`.

Добавить в Nginx `location /mcp` блок:
```nginx
# Preflight
if ($request_method = 'OPTIONS') {
    add_header 'Access-Control-Allow-Origin' '*' always;
    add_header 'Access-Control-Allow-Methods' 'POST, GET, OPTIONS, DELETE' always;
    add_header 'Access-Control-Allow-Headers' 'Content-Type, Authorization, Mcp-Session-Id' always;
    add_header 'Access-Control-Expose-Headers' 'Mcp-Session-Id' always;
    add_header 'Access-Control-Max-Age' 86400;
    return 204;
}

# Основные запросы
add_header 'Access-Control-Allow-Origin' '*' always;
add_header 'Access-Control-Allow-Methods' 'POST, GET, OPTIONS, DELETE' always;
add_header 'Access-Control-Allow-Headers' 'Content-Type, Authorization, Mcp-Session-Id' always;
add_header 'Access-Control-Expose-Headers' 'Mcp-Session-Id' always;
```

**Решение — вариант B (FastMCP / приложение):**
Если используется FastMCP, добавить CORS middleware:
```python
from starlette.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "Mcp-Session-Id"],
    expose_headers=["Mcp-Session-Id"],
)
```

#### 2. Tool annotations отсутствуют (ВАЖНО)

**Симптом:** Ни один из 14 инструментов не содержит поля `annotations`.

**Почему важно:** OpenAI требует tool annotations для определения уровня
воздействия инструмента. Без них ChatGPT может:
- Отклонить сервер
- Требовать подтверждение для каждого вызова (даже read-only)
- Некорректно классифицировать инструменты

**Тест:**
```bash
curl -s -X POST https://mcp.tgp.efimov.mobi/mcp \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  | python3 -c "import sys,json; data=json.load(sys.stdin); \
    [print(f\"{t['name']}: annotations={'YES' if 'annotations' in t else 'NO'}\") \
    for t in data['result']['tools']]"
# Результат: все 14 tools — annotations=NO
```

**Решение — добавить annotations к каждому tool:**

Read-only инструменты (не изменяют данные):
```python
annotations = {
    "readOnlyHint": True,
    "openWorldHint": False,
}
```
Применить к: `search_knowledge_base`, `ask_question`, `list_topics`,
`get_topic_details`, `list_channels`, `get_document`, `get_related_topics`,
`get_cross_channel_stats`, `get_pipeline_status`

Write-инструменты (изменяют данные, но не деструктивные):
```python
annotations = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "openWorldHint": False,
}
```
Применить к: `add_channel`, `trigger_pipeline`, `pause_channel`, `resume_channel`

Деструктивные инструменты (удаляют данные):
```python
annotations = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "openWorldHint": False,
}
```
Применить к: `remove_channel`

#### 3. Нет MCP-Session-Id (НЕКРИТИЧНО)

**Симптом:** Сервер не возвращает `Mcp-Session-Id` header в ответах.

**Почему может быть важно:** Без Session-Id ChatGPT не сможет поддерживать
stateful-сессии между запросами. Для stateless-серверов это допустимо.

**Решение:** По спецификации MCP, stateless mode (`sessionIdGenerator: undefined`)
явно поддерживается. Если нужен stateful — добавить генерацию Session-Id.

---

## Как подключить tg-parser к ChatGPT

### Предварительные условия
- Аккаунт ChatGPT (Pro, Plus, Team, Enterprise или Edu)
- Developer Mode включён в настройках

### Шаги подключения

1. В ChatGPT перейти в **Settings → Connectors → Advanced → Developer Mode** (включить)
2. Вернуться в **Connectors** → нажать **Create**
3. Заполнить:
   - **Connector name:** TG Parser Knowledge Base
   - **Description:** Semantic search and Q&A across Telegram channel knowledge base
   - **Connector URL:** `https://mcp.tgp.efimov.mobi/mcp`
4. Настроить авторизацию (Bearer token)
5. Нажать **Create** — должен появиться список инструментов
6. В новом чате: нажать **+** → **More** → **Developer Mode** → **Add sources** → выбрать коннектор

### Важные ограничения ChatGPT MCP

- Нельзя подключить localhost — только публичный HTTPS
- Write-операции требуют ручного подтверждения пользователем (если не `readOnlyHint: true`)
- Рекомендуется не более 30–40 tools на сервер (иначе деградация производительности)
- Коннектор нужно обновлять вручную (Refresh) после изменения tools

---

## Сводная таблица

| Проверка | Статус | Примечание |
|----------|--------|------------|
| HTTPS | ✅ | Let's Encrypt, TLSv1.3 |
| Streamable HTTP | ✅ | POST /mcp → 200 JSON |
| Protocol version | ✅ | 2025-11-25 и 2025-03-26 |
| Bearer auth | ✅ | 401 без токена |
| tools/list | ✅ | 14 инструментов |
| CORS headers | ❌ | Нет Access-Control-Allow-Origin |
| OPTIONS preflight | ❌ | 401 вместо 204 |
| Tool annotations | ❌ | Отсутствуют у всех tools |
| MCP-Session-Id | ⚠️ | Отсутствует (некритично) |

---

## Приоритет исправлений

1. **CORS** — без этого ChatGPT не сможет отправить ни одного запроса
2. **Tool annotations** — без этого ChatGPT может отклонить сервер или неправильно обрабатывать вызовы
3. **MCP-Session-Id** — опционально, для stateful-сессий
