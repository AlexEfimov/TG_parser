# BOT_LLM_FALLBACK — Manual Fallback Runbook for Google Gemini Outage

**ADR reference:** `docs/adr/0005-bot-llm-provider-flexibility.md` — Operational complement (вместо Variant B failover).

**Last reviewed:** 2026-05-07 (Session J, initial creation).

---

## 1. Когда использовать

Этот runbook применяется при **Google Gemini API outage**, когда:

- Telegram-бот перестаёт отвечать на сообщения (агент возвращает «Произошла ошибка при обращении к LLM»).
- Метрика `tg_bot_gemini_empty_parts_total` с `finish_reason ∈ {"no_candidates", "blocked", "OTHER"}` резко растёт.
- Google API Status Page ([status.cloud.google.com](https://status.cloud.google.com)) или Gemini API отображает инцидент.
- Outage длится ≥30 минут (более короткие инциденты — wait-and-see; Gemini обычно восстанавливается быстро).

**НЕ применять** при:
- Единичных ошибках / таймаутах (≤5 минут) — нормальный jitter API.
- Проблемах с `BOT_GEMINI_API_KEY` — это billing/key issue, не provider outage.
- Pipeline-ошибках processing/rag/digest — они не влияют на бот-агент.

---

## 2. Pre-flight проверка

Перед переключением убедитесь, что проблема именно в провайдере:

```bash
# 1. Проверить текущий статус бота
ssh -p 2296 user@212.72.189.15 'docker logs --since 30m tg_parser 2>&1 | grep -E "gemini_empty|gemini_no_candidates|gemini_blocked|gemini_api_error" | tail -20'

# 2. Убедиться, что контейнер живёт
ssh -p 2296 user@212.72.189.15 'docker exec tg_parser_prometheus wget -qO- \
  "http://localhost:9090/api/v1/query?query=up{service=\"bot\"}" \
  | python3 -m json.tool | grep -A2 "value"'
# Expected: value="1"

# 3. Проверить текущую конфигурацию LLM через MCP (если MCP доступен)
# Вызвать get_llm_config через Cursor MCP → stages.bot.provider должен быть "gemini"
```

---

## 3. Процедура переключения (downgrade модели)

Так как Telegram-бот — Gemini-only (ADR 0005 D-1), переключение на другой провайдер невозможно. **Единственная операция** — смена модели внутри Gemini-семейства (например, downgrade с `gemini-2.5-flash` на `gemini-2.0-flash` если outage затрагивает только 2.5-серию).

### Шаг 3.1 — Определить резервную модель

| Основная модель | Резервная модель | Когда применять |
|---|---|---|
| `gemini-2.5-flash` | `gemini-2.0-flash` | Outage специфичен для 2.5-серии |
| `gemini-2.5-pro` | `gemini-2.5-flash` | Downgrade при quota/capacity issues |
| любая | `gemini-1.5-flash` | Последний резерв при широком outage |

### Шаг 3.2 — Применить runtime override (без рестарта)

Через Telegram-бота (если бот частично работает) или через MCP-инструмент:

```
# Через MCP (Cursor):
set_llm_config(scope="bot", provider="gemini", model="gemini-2.0-flash")

# Через Telegram-бота (если у вас admin rights):
set_llm_config scope=bot provider=gemini model=gemini-2.0-flash
```

Проверить немедленно через `get_llm_config` — `stages.bot.model` должен показать новую модель.

### Шаг 3.3 — Smoke test

Отправить боту простой Q&A запрос через Telegram:
- «какие есть каналы?» — должен вернуть список
- «главные темы» — должен вернуть топ-5 тем

Если ответ получен — переключение успешно, переходите к § 5 (мониторинг).

### Шаг 3.4 — Если runtime override не помогает (полный Gemini outage)

При полном недоступном Gemini API (все модели) единственный вариант — **рестарт с другим ключом** (другой Google проект/billing account):

```bash
ssh -p 2296 user@212.72.189.15 'cd ~/TG_parser && \
  GEMINI_API_KEY="<backup_key>" docker compose up -d --no-deps --force-recreate tg_parser'
```

> **Примечание:** Backup-ключ должен быть подготовлен заранее и храниться в защищённом месте (password manager / secrets vault). При наличии — добавьте как `GEMINI_API_KEY_BACKUP` в `.env`.

---

## 4. Rollback

После восстановления основного Gemini API вернуть исходную модель:

```
# Через MCP или Telegram-бота:
reset_llm_config(scope="bot")
```

Проверить через `get_llm_config` — `stages.bot.model` должен показать значение из `.env` (`BOT_GEMINI_MODEL`).

Финальный smoke test (аналогично § 3.3).

---

## 5. Post-procedure мониторинг (≥30 минут после переключения)

```bash
# Убедиться что ошибки пропали
ssh -p 2296 user@212.72.189.15 'docker logs --since 30m tg_parser 2>&1 \
  | grep -cE "gemini_empty|gemini_no_candidates|gemini_api_error"'
# Expected: 0

# Проверить Prometheus метрики
ssh -p 2296 user@212.72.189.15 'docker exec tg_parser_prometheus wget -qO- \
  "http://localhost:9090/api/v1/query?query=tg_bot_gemini_empty_parts_total" \
  | python3 -m json.tool'
```

---

## 6. Quarterly drill (тест без реального outage)

Раз в квартал проверять runbook работоспособность:

1. Выбрать нагрузку < 5 пользователей (желательно в нерабочее время).
2. Применить override на 5 минут: `set_llm_config(scope="bot", provider="gemini", model="gemini-2.0-flash")`.
3. Отправить 2-3 тестовых запроса — убедиться что работает.
4. Откатить: `reset_llm_config(scope="bot")`.
5. Записать результат в `docs/notes/BUG_LOG.md` (раздел «Quarterly drills»).

**Цель drill:** убедиться что резервная модель (`gemini-2.0-flash`) доступна и принимает наши tool_declarations. API может изменить deprecation/availability между дрилами.

---

## 7. Условия пересмотра решения

Если этот runbook применялся ≥1 раза за квартал с outage ≥30 минут — это **триггер пересмотра ADR 0005** (условие пересмотра #1 в ADR). В этом случае рассмотреть Variant B (автоматический failover) или Variant C (полный refactor BotAgent).

Подробнее: `docs/adr/0005-bot-llm-provider-flexibility.md` § «Условия пересмотра».
