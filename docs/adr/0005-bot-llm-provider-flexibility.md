# ADR 0005 – Гибкость LLM-провайдера для Telegram-бота

## Статус
Accepted (2026-05-02)

## Контекст

Telegram-бот (`tg_bot` сервис) — единственный компонент системы, у которого
отсутствует абстракция LLM-провайдера. В отличие от пяти стадий пайплайна
(`processing`, `topicization`, `rag`, `digest`, `resummarize`), которые
проходят через `LLMConfigManager` и `create_llm_client(...)` (см.
`tg_parser/processing/llm/factory.py`), бот реализован отдельным классом
`GeminiAgent` с прямыми `httpx`-вызовами Gemini REST API
(`tg_parser/bot/agent.py`).

Конкретные точки жёсткой привязки:

- `GeminiAgent.__init__(api_key, model="gemini-2.5-flash", ...)` —
  модель и провайдер зашиты в имени класса и URL.
- `tg_parser/bot/main.py` — hard-fail при отсутствии `GEMINI_API_KEY` со
  специфическим сообщением «The bot agent requires Gemini for reasoning
  and tool-calling».
- `LLM_SCOPES = ("global", "processing", "topicization", "rag", "digest",
  "resummarize")` в `tg_parser/config/settings.py` — скоупа `"bot"` нет,
  поэтому MCP-tool `set_llm_config` не может изменить конфигурацию бота
  в runtime.
- Порт `LLMClient` (`tg_parser/processing/ports.py`) умеет только
  `generate(prompt, system_prompt, ...)` — function-calling в нём не
  предусмотрен. Бот использует Gemini-specific `functionDeclarations` /
  `functionCall` payload, которого нет в существующей абстракции.

Это создаёт явное **натяжение с ADR 0004** (Hexagonal/Clean
Architecture), который декларирует «смена LLM-провайдера выполняется
заменой адаптера при неизменных контрактах и портах». Бот — текущий
исключитель этого правила, и нужно зафиксировать решение по этому долгу.

### Исторический контекст выбора Gemini

- **Phase 3 (3 апреля 2026)** — выбор провайдера зафиксирован в
  `docs/notes/PHASE3_IMPLEMENTATION_PLAN.md` § «Принятые решения». Три
  основания: (1) Gemini уже поддерживался в pipeline, биллинг настроен;
  (2) function-calling «из коробки», что требовалось для агентского слоя;
  (3) cross-LLM абстракция для бота явно отложена как «большой refactor,
  out of scope».
- **Session E / BUG-006 (29 апреля 2026)** — research-spike
  (`docs/notes/START_PROMPT_FIX_BUG006_BOT_GEMINI_2026-04-29.md` § 3.1)
  рассматривал три опции для закрытия empty-`parts=[]` бага: A
  (`maxOutputTokens` bump), B (`thinkingBudget=0`), C (миграция модели).
  Выбраны A+B, C явно отклонён.
- **Sessions F/G (30 апреля – 1 мая 2026)** — закрыли BUG-005-B,
  BUG-007 (read-hardening) и BUG-009 (execute-tool ConfirmFlow guard).
  Все четыре bot-bug'а, найденные в первый месяц прода (BUG-002 / -004 /
  -006 / -009), оказались **не provider-class** (FSM / prompt / config),
  и multi-provider абстракция не предотвратила бы ни одного.

### Production observations (на момент решения)

- `tg_bot_gemini_empty_parts_total` после Session E hardening — пустой
  вектор за весь post-deploy наблюдательный период.
- Нет зафиксированных Google API outage'ов, повлиявших на бот, за всю
  историю Phase 3.
- `prompts/bot.yaml` прошёл четыре итерации (v1.0 → v1.4) за 30 дней,
  каждая в ответ на конкретную production-проблему — ни одна из них не
  была связана с провайдером.

## Рассмотренные альтернативы

### Вариант A — Mini-refactor: скоуп `"bot"` в `LLMConfigManager`

Добавить `"bot"` в `LLM_SCOPES`, расширить `LLMConfigManager.resolve` для
скоупа `"bot"` с валидацией `provider == "gemini"` (только смена модели
внутри Gemini-семейства). `GeminiAgent.__init__` читает модель через
`resolve("bot")` вместо прямого `settings.bot_gemini_model`.

- Стоимость: ~50–80 LOC, ~5–8 тестов, низкий риск (не трогает
  `process_message` loop, FSM-контракт, 67 FSM-тестов).
- Что даёт: runtime-смена модели Gemini через
  `set_llm_config(scope="bot", provider="gemini", model="gemini-2.5-pro")`
  без рестарта tg_bot; устранение «снежинки» в LLM-конфигурации;
  capability prerequisite для возможной будущей C.
- Что не даёт: защита от Google outage; возможность тестировать
  Anthropic / OpenAI; закрытие класса Gemini-specific багов.

### Вариант B — Failover (Gemini primary + Anthropic / OpenAI fallback)

В `GeminiAgent._call_gemini` при `error` / `empty_parts` / `SAFETY` /
HTTP 5xx — попытка через второй провайдер. Требует:

- Anthropic adapter с `tool_use` (~150 LOC).
- Schema-converter `TOOL_DECLARATIONS` → Anthropic tool schema (~100 LOC,
  30+ tools с nested schemas / enum'ами).
- Унифицированный путь извлечения FSM-hint'ов (`preview_pending`,
  `pagination_pending`) поверх любого провайдера.
- Fallback-trigger logic + Prometheus метрика fallback rate + alerting.
- Tests для converter'а (~50 тестов, контракт между двумя SDK).

- Стоимость: ~500–700 LOC, ~50–60 тестов, средний риск (silent failover
  bugs — fallback-путь редко срабатывает в проде, регрессии копятся
  незаметно между deploys).
- Что даёт: реальная отказоустойчивость от Google outage и edge-case
  Gemini-багов; полу-готовая инфраструктура для возможной C.
- Что не даёт: возможность сделать Claude / GPT primary; primary
  остаётся Gemini-specific.

### Вариант C — Полный refactor: порт `BotAgent` с реализациями для всех провайдеров

Новый порт `BotAgent` в `tg_parser/bot/ports.py`, реализации
`GeminiBotAgent` / `AnthropicBotAgent` / `OpenAIBotAgent`. Унифицированный
`ToolSchema` с конвертерами в три формата function-calling (Gemini
`functionDeclarations`, Anthropic `tools`, OpenAI Responses `tools`).
Скоуп `"bot"` в `LLMConfigManager` с провайдером не ограниченным Gemini.
Параллельные prompt-шаблоны (`prompts/bot.gemini.yaml` /
`prompts/bot.anthropic.yaml` / `prompts/bot.openai.yaml`) с
синхронизацией версий. Перепись 67 FSM-тестов с Gemini-specific httpx
mock'ов на mock через порт.

- Стоимость: ~1000–1400 LOC, ~80–100 тестов (включая переписку
  существующих), высокий риск — затрагивает код, содержавший BUG-002 /
  -004 / -006 / -009; требует preliminary research-spike (Anthropic
  tool_use на 30+ tools может deg'ить под natural-language ответы).
- Что даёт: полная архитектурная согласованность с ADR 0004;
  optionality для A/B-тестирования качества Q&A на разных моделях;
  независимость от Google billing / privacy / SLA.
- Что не даёт сразу: автоматический failover (нужна отдельная логика
  поверх C); A/B-testing capability (нужен experiment framework
  дополнительно ~200–400 LOC).

## Решение

Принять **Вариант A** в качестве архитектурного выбора на текущем
горизонте, с двумя дополнительными элементами и явными условиями
пересмотра.

### Decision

**A — mini-refactor.** Добавить скоуп `"bot"` в `LLMConfigManager`,
ограничить провайдер `"gemini"` в валидации `set_llm_config(scope="bot",
...)`, перевести `GeminiAgent` на чтение модели через `resolve("bot")`.
Объём: ~50–80 LOC, ~5–8 тестов. Без hot-reload в живом процессе и без
Prometheus-метрики смены модели — это вынесено в opportunistic
доработку при следующем bot-touch.

### Operational complement (вместо B)

Не реализовывать failover-код. Вместо этого создать **manual fallback
runbook** в `docs/runbooks/BOT_LLM_FALLBACK.md`: документированную
процедуру переключения бота на резервный провайдер через config + env
за ≤30 минут. Runbook должен быть отрепетирован (drill) ежеквартально.
Стоимость: ~50 LOC + 1 страница документа. Это даёт бизнес-непрерывность
без накопления silent-failover-debt.

### Opportunistic C

Не реализовывать C как самостоятельный refactor. Откладывать до
следующего крупного bot-рефакторинга, который и так потребует трогать
`process_message` (например, F10 multimodal — изображения и voice
требуют переделки payload structure; major prompt redesign;
прокидывание новых классов FSM-контекста). Тогда отделение порта
`BotAgent` будет стоить на ~30–40% меньше за счёт уже идущей переработки
тестов.

## Последствия

### Положительные

- Бот получает symmetric runtime-конфигурацию с остальными LLM-стадиями
  (одна и та же `LLMConfigManager`-абстракция).
- Архитектурная инвестиция масштаба ~1 рабочего дня вместо 2-3 sprint'ов.
- Сохранение product velocity для F12 / F5-B / F9 phase 3 / F10 в
  `docs/notes/FUTURE_FEATURES.md`, не отвлечённой на инфраструктурный
  рефакторинг с неочевидным ROI.
- Operational runbook покрывает реалистичный outage-сценарий за
  стоимость на порядок ниже B.

### Отрицательные / принятый долг

- ADR 0004 нарушение остаётся: `GeminiAgent` — единственный LLM-клиент
  без порта. Будущим разработчикам / сессиям виден прецедент. Снижается
  через явную ссылку из `docs/architecture.md` на этот ADR (см. § Ссылки).
- Bus factor по Gemini остаётся: Google policy / billing / SLA-инцидент
  на >30 минут потребует ручного действия по runbook'у.
- Без C мы не имеем infrastructure для A/B-тестирования качества Q&A —
  оптимизируем вслепую под одного провайдера.

### Что НЕ меняется этим ADR

- `prompts/bot.yaml` остаётся single-provider (Gemini-specific bullets
  про `confirm=True` / `error_class="ConfirmFlowMismatch"`).
- 67 FSM-тестов в `tests/test_bot_fsm.py` продолжают mock'ать
  Gemini-specific httpx response shape.
- Существующие env-переменные `BOT_GEMINI_MODEL`,
  `BOT_GEMINI_MAX_OUTPUT_TOKENS`, `BOT_GEMINI_THINKING_BUDGET`
  сохраняются как defaults; runtime override через
  `set_llm_config(scope="bot", ...)` имеет приоритет.

## Условия пересмотра (re-evaluation triggers)

Любое из следующих наблюдений запускает пересмотр этого ADR — promote
к B (failover-код) или сразу к C (полный refactor), в зависимости от
типа триггера:

1. **Outage frequency.** Зафиксированный Google API outage ≥1 раза за
   квартал, длительностью ≥30 минут, влияющий на бот. Источник:
   incident log + `tg_bot_gemini_empty_parts_total` с `finish_reason ∈
   {"no_candidates", "blocked", "OTHER"}`.
2. **Gemini-quirk не лечится config'ом.** Появление BUG-006-like класса
   (`parts=[]` / `finishReason` mismatch / silent context drop), для
   которого `thinkingBudget` / `maxOutputTokens` / prompt-tuning не
   являются достаточным решением.
3. **Бизнес-требование «не Google».** Клиент в контексте F4
   (multi-tenancy) или F7 (monetization) требует non-Google провайдер по
   compliance / privacy / regional причинам.
4. **Документированное преимущество альтернативы.** Manual research-spike
   (~1 день) показал ≥15% улучшение качества Q&A на Claude / GPT для
   нашего tool-calling workload (метрика: % правильных tool-calls на
   репрезентативной test-suite, +/− latency / cost).

При срабатывании триггера 1 или 2 — приоритет B (failover для
бизнес-непрерывности). При срабатывании 3 или 4 — приоритет C (полная
смена primary).

## Ссылки

- ADR 0004 (Hexagonal architecture, port-adapter principle):
  `docs/adr/0004-hexagonal-architecture-and-module-boundaries.md` —
  декларирует то правило, к которому это ADR фиксирует исключение.
- Phase 3 implementation plan (выбор Gemini): `docs/notes/PHASE3_IMPLEMENTATION_PLAN.md`.
- BUG-006 research-spike (отклонённая ранняя миграция):
  `docs/notes/START_PROMPT_FIX_BUG006_BOT_GEMINI_2026-04-29.md` § 3.1.
- BUG-009 closure (Session G structural guard):
  `docs/notes/START_PROMPT_FIX_BUG009_EXECUTE_TOOL_GUARD_SESSION_G_2026-05-01.md`.
- Bot agent implementation: `tg_parser/bot/agent.py` (`GeminiAgent`).
- Bot startup wiring: `tg_parser/bot/main.py` (Gemini hard-fail check).
- LLM scope configuration: `tg_parser/config/settings.py`
  (`LLM_SCOPES`, `LLMConfigManager`).
- LLM client factory: `tg_parser/processing/llm/factory.py`.
- LLM port: `tg_parser/processing/ports.py` (`LLMClient`).
- Bot system prompt (Gemini-specific bullets): `prompts/bot.yaml` v1.4.0.
- Future features backlog: `docs/notes/FUTURE_FEATURES.md` (F4 / F7 / F10
  как потенциальные триггеры).
