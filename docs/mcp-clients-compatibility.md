# Куда можно подключить tg-parser MCP сервер

**Дата исследования:** 2026-04-03
**Сервер:** `https://mcp.tgp.efimov.mobi/mcp`
**Транспорт:** Streamable HTTP, Bearer auth
**Версия:** TG_parser Knowledge Base v1.27.0

---

## Сводная таблица совместимости

| Платформа | MCP-клиент | Remote HTTP | Способ подключения | Готовность |
|-----------|-----------|-------------|-------------------|------------|
| **Claude** | claude.ai, Desktop | ✅ | Config / UI / mcp-remote | ✅ Работает |
| **ChatGPT** | chatgpt.com | ✅ | Developer Mode → Connectors | ⚠️ Нужен CORS + annotations |
| **Grok (xAI)** | API (Responses) | ✅ | tools[].server_url | ✅ Совместим |
| **Gemini** | CLI, SDK, AI Studio | ✅ | settings.json / SDK | ✅ Совместим |
| **DeepSeek** | Нет своего клиента | ❌ | Только как MCP-сервер для других | ❌ Нет MCP-клиента |
| **Cursor** | IDE | ✅ | mcp.json (url) | ✅ Совместим |
| **Windsurf** | IDE | ✅ | mcp.json (url) | ✅ Совместим |
| **VS Code Copilot** | IDE | ✅ | settings.json | ✅ Совместим |
| **Claude Code** | CLI | ✅ | claude mcp add | ✅ Совместим |

---

## 1. ChatGPT (OpenAI)

**Статус:** ⚠️ Совместим, но нужны доработки сервера

ChatGPT поддерживает подключение custom MCP-серверов через Developer Mode.
Поддерживает Streamable HTTP и HTTP+SSE транспорты.

**Как подключить:**
1. Settings → Connectors → Advanced → Developer Mode (включить)
2. Connectors → Create → указать URL `https://mcp.tgp.efimov.mobi/mcp`
3. Настроить Bearer token авторизацию

**Требования к серверу:**
- CORS headers (Access-Control-Allow-Origin) — **отсутствуют, нужно добавить**
- Tool annotations (readOnlyHint, destructiveHint) — **отсутствуют, нужно добавить**
- HTTPS — ✅ есть
- Streamable HTTP — ✅ поддерживается

**Доступность:** Pro, Plus, Team, Enterprise, Edu планы.
Без Developer Mode нужны специальные tools `search`/`fetch` для Deep Research.

**Подробный отчёт:** см. `chatgpt-mcp-compatibility.md`

---

## 2. Grok (xAI)

**Статус:** ✅ Совместим через API

Grok поддерживает Remote MCP Tools — подключение внешних MCP-серверов
напрямую через API. xAI управляет MCP-соединением от имени пользователя.

**Как подключить (через xAI API):**
```python
from xai_sdk import Client
from xai_sdk.tools import mcp

client = Client(api_key="XAI_API_KEY")
chat = client.chat.create(
    model="grok-4.20-reasoning",
    tools=[
        mcp(
            server_url="https://mcp.tgp.efimov.mobi/mcp",
            headers={"Authorization": "Bearer <TOKEN>"}
        ),
    ],
)
```

**Или через OpenAI-совместимый API:**
```python
from openai import OpenAI
client = OpenAI(api_key="XAI_API_KEY", base_url="https://api.x.ai/v1")
response = client.responses.create(
    model="grok-4.20-reasoning",
    tools=[{
        "type": "mcp",
        "server_url": "https://mcp.tgp.efimov.mobi/mcp",
        "server_label": "tg-parser",
    }],
    input="Search my Telegram knowledge base for longevity research",
)
```

**Ограничения:**
- Только через API (xAI SDK или OpenAI-совместимый Responses API)
- В веб-интерфейсе grok.com — через custom agents (Enterprise)
- Параметры `require_approval` и `connector_id` пока не поддерживаются

---

## 3. Gemini (Google)

**Статус:** ✅ Совместим через CLI и SDK

Google поддерживает MCP через Gemini CLI и Python/JS SDK.
Поддерживает stdio, SSE и HTTP транспорты.
Пока используется только `tools/list` — resources и prompts не поддерживаются.

**Как подключить через Gemini CLI (settings.json):**
```json
{
  "mcpServers": {
    "tg-parser": {
      "httpUrl": "https://mcp.tgp.efimov.mobi/mcp",
      "headers": {
        "Authorization": "Bearer <TOKEN>"
      }
    }
  }
}
```

**Как подключить через Gemini Python SDK:**
```python
from fastmcp import Client
from google import genai
import asyncio

mcp_client = Client("https://mcp.tgp.efimov.mobi/mcp")
gemini_client = genai.Client()

async def main():
    async with mcp_client:
        response = await gemini_client.aio.models.generate_content(
            model="gemini-2.0-flash",
            contents="Search Telegram knowledge base for vitamin D",
            config=genai.types.GenerateContentConfig(
                tools=[mcp_client.session],
            ),
        )
asyncio.run(main())
```

**Ограничения:**
- В веб-интерфейсе gemini.google.com — custom MCP серверы пока НЕ поддерживаются
- Gemini CLI и SDK — поддерживаются полностью
- Google AI Studio — поддерживается
- Только tools (не resources/prompts)

---

## 4. DeepSeek

**Статус:** ❌ Не имеет собственного MCP-клиента

DeepSeek не имеет встроенной поддержки MCP как клиент.
У DeepSeek нет аналога Developer Mode или Connectors.

DeepSeek *сам* существует как MCP-сервер (community), но не как клиент.
Чтобы использовать tg-parser с моделями DeepSeek, нужно:
- Использовать DeepSeek через OpenRouter или другой прокси с MCP-поддержкой
- Или подключить tg-parser к IDE (Cursor, VS Code) и выбрать DeepSeek как модель

---

## 5. Cursor IDE

**Статус:** ✅ Полностью совместим

Cursor имеет нативную поддержку MCP с remote серверами.

**Как подключить (~/.cursor/mcp.json):**
```json
{
  "mcpServers": {
    "tg-parser": {
      "url": "https://mcp.tgp.efimov.mobi/mcp",
      "headers": {
        "Authorization": "Bearer <TOKEN>"
      }
    }
  }
}
```

Проверить: Settings → MCP → должен появиться tg-parser с 24 tools (v4.3).

---

## 6. Windsurf IDE

**Статус:** ✅ Совместим

Windsurf поддерживает MCP-серверы через конфигурационный файл.

**Как подключить (~/.windsurf/mcp.json):**
```json
{
  "mcpServers": {
    "tg-parser": {
      "url": "https://mcp.tgp.efimov.mobi/mcp",
      "headers": {
        "Authorization": "Bearer <TOKEN>"
      }
    }
  }
}
```

---

## 7. VS Code + GitHub Copilot

**Статус:** ✅ Совместим

VS Code с Copilot поддерживает MCP через settings.json.

**Как подключить (.vscode/settings.json):**
```json
{
  "github.copilot.chat.mcp.servers": {
    "tg-parser": {
      "type": "http",
      "url": "https://mcp.tgp.efimov.mobi/mcp",
      "headers": {
        "Authorization": "Bearer <TOKEN>"
      }
    }
  }
}
```

Требуется VS Code 1.101+ для remote MCP и OAuth.

---

## 8. Claude Code (CLI)

**Статус:** ✅ Совместим

**Как подключить:**
```bash
claude mcp add --transport http tg-parser \
  https://mcp.tgp.efimov.mobi/mcp \
  --header "Authorization: Bearer <TOKEN>"
```

---

## 9. Claude Desktop App

**Статус:** ⚠️ Ограниченная совместимость

Claude Desktop v1.2.234 **не поддерживает** remote MCP через config-файл
(ни `streamableHttp`, ни `sse` в `claude_desktop_config.json`).

**Рабочие варианты:**
- **stdio** (локальный сервер) — работает, проверено
- **mcp-remote** (npm-прокси) — работает, используется сейчас
- **UI интеграции** — если доступны в настройках

---

## Общие требования для всех платформ

Чтобы tg-parser работал максимально совместимо со всеми клиентами:

1. **CORS headers** — обязательно для браузерных клиентов (ChatGPT, AI Studio)
2. **Tool annotations** — обязательно для ChatGPT, рекомендуется для всех
3. **HTTPS** — ✅ уже есть
4. **Streamable HTTP** — ✅ уже поддерживается
5. **Bearer auth** — ✅ работает

---

## Приоритет подключений

1. **Claude** (claude.ai) — уже работает через mcp-remote
2. **Cursor / VS Code** — простая настройка через JSON, сразу совместим
3. **Grok API** — совместим, подключение через код
4. **Gemini CLI** — совместим, подключение через settings.json
5. **ChatGPT** — после добавления CORS и annotations
