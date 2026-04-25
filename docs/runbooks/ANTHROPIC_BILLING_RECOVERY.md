# Runbook — Anthropic billing pause: восстановление источника

**Назначение:** оператор замечает, что один или несколько источников «застряли» (нет новых документов / нет роста `topic_cards` / срабатывает алерт на `tg_parser_anthropic_billing_block_total`). Этот runbook — пошаговый план: подтвердить, что причина действительно billing-pause; устранить корневую причину (пополнить баланс Anthropic); вручную или автоматически снять паузу; верифицировать, что pipeline пошёл дальше.

**Когда применять:** Sprint D.1 ввёл явную обработку Anthropic `400 invalid_request_error: credit balance is too low` (см. `tg_parser/processing/llm/errors.py::AnthropicBillingError`). При такой ошибке scheduler ставит источник в паузу `rate_limit_until = now + BILLING_BLOCK_BACKOFF_S` (default 1 час) и инкрементит метрику `tg_parser_anthropic_billing_block_total{stage=...}`. Pipeline retry-loops такую ошибку **не** ретраят — это намеренно, чтобы не сжигать API-вызовы и не размазывать ошибку по логам.

**Время:** ~5–15 минут (основное время — пополнение баланса в Anthropic Console и ожидание следующего scheduler-tick'а).

**Связанные:**
- Implementation: Sprint D.1 (`docs/notes/START_PROMPT_SPRINT_D1_TOPICIZATION_HARDENING.md`)
- Incident, который привёл к появлению этого механизма: `docs/quality/incidents/2026-04-20_genotek_topicization_silent_failure.md`
- Архитектура incremental-пути и checkpointing'а: `docs/notes/ARCHITECTURE_INCREMENTAL_TOPICIZATION.md` § Sprint D.1
- Конфигурация: `BILLING_BLOCK_BACKOFF_S` в `ENV_VARIABLES_GUIDE.md`

---

## Симптомы

Любой из этих сигналов:

1. **Алерт на метрику** `tg_parser_anthropic_billing_block_total` ползёт вверх (Prometheus / Grafana).
2. **Источник перестал обновляться** — в `get_pipeline_status` `last_run_at` старее, чем интервал scheduler'а.
3. **`source_attempts` показывают сбой** — последняя строка для источника:

   ```sql
   SELECT source_id, attempt_at, success, failed_stage, error_class, error_message
   FROM source_attempts
   WHERE source_id = '<channel>'
   ORDER BY attempt_at DESC
   LIMIT 5;
   ```

   Ожидаем `success=false`, `error_class='AnthropicBillingError'`, `failed_stage IN ('topicize','incremental_topicization','process')`, `error_message` содержит `credit balance is too low`.
4. **`sources.rate_limit_until`** в будущем — источник пропускается scheduler-тиком.
5. **В логах** worker'а есть строка `anthropic.billing_error_short_circuit` (или эквивалентная) с ID источника.

---

## Шаги

### 1. Подтвердить причину

Не наугад снимать паузу — проверь, что это именно billing, а не другая ошибка:

```bash
# Проверить метрику (должно быть > 0, желательно посмотреть на скорость роста)
docker compose exec tg_parser curl -s http://localhost:8000/metrics | grep tg_parser_anthropic_billing_block_total

# Проверить таблицу attempts
docker compose exec postgres psql -U tg_parser_user -d tg_parser -c "
  SELECT source_id, attempt_at, success, failed_stage, error_class,
         LEFT(error_message, 200) AS error_excerpt
  FROM source_attempts
  WHERE error_class = 'AnthropicBillingError'
     OR failed_stage IN ('topicize','incremental_topicization','process')
  ORDER BY attempt_at DESC
  LIMIT 10;
"

# Проверить какие источники сейчас в паузе
docker compose exec postgres psql -U tg_parser_user -d tg_parser -c "
  SELECT source_id, name, status, rate_limit_until,
         (rate_limit_until - NOW()) AS until_release
  FROM sources
  WHERE rate_limit_until IS NOT NULL
    AND rate_limit_until > NOW();
"
```

Если `error_class != 'AnthropicBillingError'` — это **другая** проблема, этот runbook не подходит. Смотри `error_message` и общий процесс расследования.

### 2. Устранить корневую причину (Anthropic)

1. Зайти в [Anthropic Console](https://console.anthropic.com/) → **Plans & Billing**.
2. Пополнить баланс / включить auto-recharge / повысить лимиты.
3. Убедиться, что нет **organisation-level** suspension (если используется shared-org-key) — иногда баланс есть, но ключ заблокирован.
4. (Опционально, если используется fallback) проверить, не настроен ли в `ANTHROPIC_API_KEY_FALLBACK` второй ключ — он может «маскировать» исчерпание основного.

> **Не снимать паузу до пополнения** — иначе следующий tick снова упадёт в ту же ошибку и снова запаузит источник.

### 3. Снять паузу

Один из вариантов:

#### Вариант A — подождать (минимальный риск)

`rate_limit_until` истечёт автоматически через `BILLING_BLOCK_BACKOFF_S` (default 3600 секунд). Следующий scheduler tick подхватит источник. Используй, если не торопишься и баланс уже пополнен.

#### Вариант B — снять паузу вручную (быстрее, рекомендуется после проверки баланса)

```bash
docker compose exec postgres psql -U tg_parser_user -d tg_parser -c "
  UPDATE sources
  SET rate_limit_until = NULL, updated_at = NOW()
  WHERE source_id IN ('<channel_1>', '<channel_2>')
    AND rate_limit_until > NOW();
"
```

Опционально — для всех залипших источников разом:

```sql
UPDATE sources
SET rate_limit_until = NULL, updated_at = NOW()
WHERE rate_limit_until > NOW();
```

После UPDATE дождаться следующего scheduler-тика (по умолчанию ~1 час incremental, см. `SCHEDULER_INCREMENTAL_INTERVAL_*`) либо вручную дёрнуть pipeline:

```bash
# CLI на worker (НЕ через MCP — MCP-путь требует Telegram secrets, см. incident § 6)
docker compose exec tg_parser tg-parser ingest --channel <channel> --mode incremental
docker compose exec tg_parser tg-parser process --channel <channel> --mode incremental
docker compose exec tg_parser tg-parser topicize --channel <channel> --mode incremental
```

### 4. Если incremental не «оживляет» источник — escalate to full

Если на момент billing-pause канал был ещё ни разу не топикизирован (в `topic_cards` для этого источника 0 записей) — Sprint D.1 § 5.1 fall-through автоматически вызывает full-mode из incremental. Проверь:

```sql
SELECT source_id, COUNT(*) AS card_count
FROM topic_cards, jsonb_array_elements_text(sources_json::jsonb) AS source_id
WHERE source_id = '<channel>'
GROUP BY source_id;
```

Если `card_count=0` и incremental-tick прошёл без эскалации — это регрессия, открыть инцидент. Иначе ручной escalate:

```bash
docker compose exec tg_parser tg-parser topicize --channel <channel> --mode full
```

### 5. Верификация

```sql
-- Pause снята?
SELECT source_id, rate_limit_until FROM sources WHERE source_id = '<channel>';
-- ожидаемо: NULL

-- Последний attempt успешен?
SELECT attempt_at, success, failed_stage, error_class
FROM source_attempts
WHERE source_id = '<channel>'
ORDER BY attempt_at DESC LIMIT 3;
-- ожидаемо: success=true, failed_stage IS NULL

-- Темы появляются?
SELECT source_id, COUNT(*) AS topics
FROM topic_cards, jsonb_array_elements_text(sources_json::jsonb) AS source_id
WHERE source_id = '<channel>'
GROUP BY source_id;
```

И посмотреть что метрика **перестала** расти:

```bash
# Через 5–10 минут после восстановления — counter должен быть стабилен (новых инкрементов нет)
docker compose exec tg_parser curl -s http://localhost:8000/metrics | grep tg_parser_anthropic_billing_block_total
```

### 6. Зафиксировать инцидент

Если billing-pause — следствие новой проблемы (изменение pricing, перебой, organisation suspension), завести запись в `docs/quality/INBOX.md` (см. `docs/quality/AGENT_PLAYBOOK.md`). Если «штатное» исчерпание баланса — достаточно записи в операционном логе.

---

## Что НЕ делать

- ❌ **Не ретраить руками сразу же** до пополнения баланса. Pipeline retry-loops намеренно не ретраят `AnthropicBillingError`; ручной retry без пополнения = повторная пауза.
- ❌ **Не понижать `BILLING_BLOCK_BACKOFF_S` ниже 60 секунд** — это даёт оператору окно времени на пополнение. Ниже 60s заблокировано валидацией в `Settings`.
- ❌ **Не запускать топикизацию через MCP-tool `trigger_pipeline` для repair** — он требует `TELEGRAM_API_ID/HASH` (это путь ingestion + topicize); для одного только re-topicize в worker-контейнере используй CLI `tg-parser topicize`. Подробности — incident § 6.
- ❌ **Не удалять/править руками `topic_cards` или `source_attempts`** для «обнуления» состояния. Все нужные пути восстановления реализованы в коде (incremental → full fall-through, per-batch checkpointing).

---

## Ссылки

- Реализация ошибки: `tg_parser/processing/llm/errors.py`, `tg_parser/processing/llm/anthropic_client.py`
- Scheduler-логика паузы: `tg_parser/services/scheduler_service.py` (`_pause_source_for_billing`, проверка `rate_limit_until` в начале тика)
- Метрика: `tg_parser/api/metrics.py::ANTHROPIC_BILLING_BLOCK_TOTAL`
- Тесты: `tests/test_anthropic_client_billing.py`, `tests/test_scheduler_service.py::test_billing_error_pauses_source_and_marks_failure`
- Конфиг: `tg_parser/config/settings.py::Settings.billing_block_backoff_s`
