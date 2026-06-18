# Runbook — F5-C Deploy + 24h Watch

**Last reviewed:** 2026-05-08 (hotfix — container/service nomenclature corrected; unified deploy path with SERVER_ARCHITECTURE.md).

**Назначение:** безопасно задеплоить F5-C MVP (Evolving Topic Summaries) на VPS и в первые 24 часа отследить, что фича работает в проде так, как задумано.

**Когда применять:**
- При первом деплое F5-C MVP (тег `f5c-mvp-2026-04-26`, merge commit `29679e0`).
- При hot-fix на `topic_card_versions` / `ResummarizationService` / scheduler hook.

**Время:** ~15 минут активной работы на деплой + пассивный мониторинг 24 ч (полезно дёрнуться через 1 ч / 4 ч / 12 ч / 24 ч).

**Связанные runbook'и:** [SAFE_MIGRATION_ON_DEV.md](SAFE_MIGRATION_ON_DEV.md), [ANTHROPIC_BILLING_RECOVERY.md](ANTHROPIC_BILLING_RECOVERY.md). Tracking issue для Phase 2 — **#15**.

---

## Pre-deploy checklist

Перед началом — убедись, что выполнены **все** пункты:

| # | Что | Как проверить |
|---|---|---|
| 1 | F5-C смерджен в `main` | `git log --oneline -1 --first-parent main` → `29679e0 Merge pull request #14: feat(F5C) — Evolving Topic Summaries MVP` |
| 2 | Тег создан и запушен | `git tag -l 'f5c-mvp-*'` → `f5c-mvp-2026-04-26` |
| 3 | CI на merge-коммите зелёный | `gh pr checks 14` или Actions UI на `5038eda` |
| 4 | Alembic head на VPS соответствует `c9d8e7f6a5b4` (pre-F5C) | `ssh -p 2296 user@212.72.189.15 'cd ~/TG_parser && docker compose exec tg_parser tg-parser db current --db processing'` → должно быть `c9d8e7f6a5b4 (head)` **до** наката |
| 5 | Anthropic / OpenAI лимиты в порядке | `ANTHROPIC_BILLING_RECOVERY.md` § «health check»; иначе после деплоя F5-C начнёт ловить billing-ошибки и пометит source as paused |
| 6 | Backup processing-БД свежий | `docker compose exec postgres /docker/backup.sh` (compose service = `postgres`, container = `tg_parser_postgres`) или ваш регулярный backup-job; rollback требует восстановления из dump'a при downgrade миграции. Если `/docker/backup.sh` отсутствует — `pg_dump` напрямую (см. `SERVER_ARCHITECTURE.md`) |

> ⚠️ **F5-C не катится** без п.5 — `RESUMMARIZE_LLM_PROVIDER` по умолчанию наследует от `LLM_PROVIDER`; если на проде `anthropic` / `openai` упёрлись в лимит — F5-C сам пометит source as paused через `_pause_source_for_billing`. Это by design (Decision #13), но лучше деплоить когда LLM-провайдеры здоровы.

---

## Deploy

### 1. Pull кода на VPS

```bash
ssh -p 2296 user@212.72.189.15
cd ~/TG_parser  # canonical deploy path (см. SERVER_ARCHITECTURE.md)
git fetch --tags origin
git checkout main
git pull origin main

# Sanity check
git log --oneline -1 --first-parent  # должно показать 29679e0 Merge pull request #14
git describe --tags --exact-match     # должно показать f5c-mvp-2026-04-26
```

### 2. Накатить миграцию (без рестарта сервисов)

F5-C добавляет одну миграцию `a4b5c6d7e8f9` в processing-ветку: 3 колонки в `topic_cards` + partial index + новая таблица `topic_card_versions`.

```bash
# Pre-flight: убедимся, что нет drift'a
tg-parser db check --db processing  # → "No new upgrade operations detected." на старой схеме

# Накат
tg-parser db upgrade --db processing  # → applies a4b5c6d7e8f9

# Post-check: head обновился
tg-parser db current --db processing  # → "a4b5c6d7e8f9 (head)"
tg-parser db check --db processing    # → "No new upgrade operations detected."
```

> 📊 На большой БД bootstrap-step может занять секунды-минуты: ставит `last_summarized_at = updated_at::timestamptz` для всех существующих `topic_cards`. Партициализация: миграция содержит fallback на `NOW()` если `updated_at` не парсится как ISO-8601 (см. gotcha #11). Локов на READ нет — миграция использует `ALTER TABLE ... ADD COLUMN` с дефолтом, а не table rewrite (Postgres 11+).

### 3. Перезапустить сервисы (rolling — если возможно)

```bash
docker compose pull
# Compose services: tg_parser (API + scheduler), mcp, tg_bot (profile=bot).
# Container_name'ы: tg_parser, tg_parser_mcp, tg_parser_bot.
docker compose --profile bot up -d --no-deps tg_parser mcp tg_bot
docker compose ps  # все сервисы Up (healthy)
```

> 📦 Если стек single-node — будет ~5-секундный downtime между остановкой старого контейнера и запуском нового. Telegram bot переподключится автоматически (long-polling). Webhook'и (если есть) пропустят 1-2 update'a.

### 4. Smoke tests (через 30 секунд после рестарта)

```bash
# (a) API живой и метрики экспортируются
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/metrics | grep -c '^tg_resummarize_'  # → 0 пока не было ни одного re-summarize, это норма

# (b) Новые F5-C MCP-инструменты доступны
docker compose exec tg_parser tg-parser mcp list-tools | grep -E "get_topic_versions|force_resummarize"
# → должно вывести две строки

# (c) Новый CLI sub-app зарегистрирован
docker compose exec tg_parser tg-parser topic --help
# → должно показать команды `versions` и `resummarize`

# (d) Probe: попробовать прочитать audit-trail для существующей темы (ожидаем пустой,
# потому что F5-C ещё не пробежал ни разу)
docker compose exec tg_parser tg-parser topic versions <известный topic_id>
# → "history rows: 0 (limit=10)" + current_version: 1 + last_summarized_at: <updated_at>

# (e) Pipeline-tick test (best effort): дождаться следующего scheduler-tick'a
# и проверить, что в логах появился f5c_resummarize lines
docker compose logs -f tg_parser | grep -i "f5c_resummarize"
# → "f5c_resummarize source=... candidates=N resummarized=M skipped=K tokens=T"
# Ctrl-C через 1-2 минуты после первого попадания
```

Если **(a)–(e) все зелёные** — деплой считается успешным, переходим к watch.

---

## 24h Watch

После деплоя — **минимум 24 часа** мониторим следующие сигналы. Все метрики уже инструментированы в `tg_parser/api/metrics.py` и попадают в Prometheus через `/metrics` endpoint.

### Чек-поинты

| Время после деплоя | Что смотрим | Acceptance criteria |
|---|---|---|
| **+1 ч** | Просто запустился ли F5-C хотя бы раз | `sum(tg_resummarize_total) > 0` (если в каналах был incremental ingest, должны быть кандидаты) |
| **+4 ч** | Распределение outcome'ов | `outcome=ok` доминирует (>80% от total). `llm_error` / `version_raced` редкие (<5%) |
| **+12 ч** | Cost monitoring | Сумма `tg_resummarize_tokens_total` в день / канал не выходит за бюджет (см. ниже) |
| **+24 ч** | Stability | Ни одного source с `_pause_source_for_billing` (если был — открываем `ANTHROPIC_BILLING_RECOVERY.md`); размер `topic_card_versions` растёт линейно, не экспоненциально |

### PromQL queries

#### Health: rate of successful re-summaries

```promql
rate(tg_resummarize_total{outcome="ok"}[5m])
```
**Ожидание:** >0 на каналах с incremental трафиком; в idle-каналах может быть 0 (нет новых items → нет триггера).

#### Outcome distribution

```promql
sum by(outcome) (rate(tg_resummarize_total[15m]))
```
**Ожидание:** `ok` доминирует. Допустимая аномалия `locked` — две force-resummarize одной темы подряд (advisory-lock). `no_card` / `no_bundle` — чаще всего race c удалением канала. `empty_scope` — LLM вернул пустой scope, fallback на старый отработал.

#### Tripwire: error rates

```promql
# Tripwire #1 — LLM-ошибки выше 10%
sum(rate(tg_resummarize_total{outcome="llm_error"}[15m]))
  / sum(rate(tg_resummarize_total[15m])) > 0.1

# Tripwire #2 — version_raced > 5% (значит advisory-lock не спасает)
sum(rate(tg_resummarize_total{outcome="version_raced"}[15m]))
  / sum(rate(tg_resummarize_total[15m])) > 0.05

# Tripwire #3 — duration p95 близок к таймауту
histogram_quantile(0.95, rate(tg_resummarize_duration_seconds_bucket[15m])) > 30
```

Любой из этих 3 — **сигнал тревоги**, см. § Tripwire response ниже.

#### Cost (LLM tokens) per provider+model

```promql
# Tokens / hour
rate(tg_resummarize_tokens_total[1h]) * 3600

# Estimated cost / day (для openai/gpt-4o-mini = $0.15/1M input, $0.60/1M output)
sum by (model) (
  rate(tg_resummarize_tokens_total{model="gpt-4o-mini", token_type="prompt"}[1d]) * 86400 * 0.15 / 1e6
  + rate(tg_resummarize_tokens_total{model="gpt-4o-mini", token_type="completion"}[1d]) * 86400 * 0.60 / 1e6
)
```
**Ожидание (per Roadmap):** TCO upper bound ~1.2M tokens/day/channel в худшем случае (cap = `RESUMMARIZE_MAX_TOKENS_PER_TICK=50000` × 24 tick/day). На практике — десятки центов / месяц / канал. Если уехало в доллары/день — провёрнуть `RESUMMARIZE_TRIGGER_N` повыше или `RESUMMARIZE_INPUT_WINDOW_N` пониже.

#### Размер audit-trail таблицы

```sql
-- Запускать на processing-БД через ssh / docker exec, не Prometheus.
SELECT
  COUNT(*)                     AS rows,
  pg_size_pretty(pg_total_relation_size('topic_card_versions')) AS size,
  COUNT(DISTINCT topic_id)     AS topics_with_history,
  MAX(version_no)              AS max_version,
  AVG(version_no)::numeric(10,2) AS avg_version
FROM topic_card_versions;
```
**Ожидание (24 ч):** rows ≈ суммарное `tg_resummarize_total{outcome="ok"}` за сутки. Размер должен быть в МБ, не ГБ. Если рост слишком быстрый — это сигнал к Phase 2 пункту #1 (TTL/retention).

### F11 watchlist health (TD-02 — добавлено в post-Living-KB Phase 1)

F11 watchlist делит scheduler tick с F5-C; следующие PromQL-снипеты позволяют убедиться что F11 живой и помогают калибровать threshold перед F11 P2.

**Match-flow по 1 часу:**
```promql
rate(tg_watchlist_matches_total{result="delivered"}[1h])
rate(tg_watchlist_matches_total{result="filtered_threshold"}[1h])
rate(tg_watchlist_matches_total{result="filtered_keywords"}[1h])
```
Если `delivered = 0` и `filtered_threshold > 0` — порог слишком высок (либо реально нет совпадений). Если `filtered_keywords` высокий — exclude-keywords агрессивно режут.

**Distribution of combined scores (calibration для F11 P2):**
```promql
histogram_quantile(0.5, sum by (le) (rate(tg_watchlist_score_bucket[1h])))
histogram_quantile(0.9, sum by (le) (rate(tg_watchlist_score_bucket[1h])))
```
Использовать после ≥ 24 ч продакшн-сигнала чтобы выбрать sane default threshold (текущий 0.6 — placeholder).

> ⚠️ **BUG-060 — keyword-only rows skew `tg_watchlist_score` (preventive).** Гистограмма `tg_watchlist_score` смешивает keyword-only и hybrid строки. Когда `semantic_available=False` (нет эмбеддингов / семантический бэкенд недоступен), строка **by design** имеет `combined=keyword` и `semantic=0.0` (ADR-0010/0011; см. [`WAVE1_TECH_DEBT.md` § B](../notes/WAVE1_TECH_DEBT.md)). Сейчас НЕ существует provisioned alert на `tg_watchlist_score`, поэтому ложных срабатываний нет. Но **любое будущее alert-выражение, которое предполагает blended-формулу `kw_weight·keyword + sem_weight·semantic` (defaults 0.4/0.6), ОБЯЗАНО гейтить на `semantic_available`** (или явно исключать keyword-only строки), иначе keyword-only строки с `semantic=0.0` дадут ложные positives. Это сознательно отложенный preventive-долг (BUG-060): добавлять реальное правило здесь нельзя без этого гейта.

**Delivery success rate:**
```promql
rate(tg_watchlist_delivery_total{outcome="sent"}[1h])
rate(tg_watchlist_delivery_total{outcome="blocked"}[1h])
rate(tg_watchlist_delivery_total{outcome="error"}[1h])
```
`blocked` > 0 значит юзер заблокировал бота — interest soft-deleted автоматически. `error` > 0 — Telegram rate-limit / транзиентные ошибки; систематически > 5% → проверять bot токен / network.

**Active interests:**
```promql
tg_watchlist_active_interests
```
Gauge. Падение к нулю при non-empty `subscribe_watchlist` calls — индикатор массового soft-delete (например после длительного `blocked` storm).

**Tripwire (для F11):** `rate(tg_watchlist_delivery_total{outcome="error"}[5m]) > 0.1` — открыть hot-fix issue.

**Score-ceiling из логов (2026-06-07).** На no-match тике scheduler теперь пишет структурную строку `watchlist.score_ceiling` (per-interest max combined/keyword/semantic против threshold) — диагностика persistent zero-matches без захода в `tg_watchlist_score` гистограмму:
```bash
docker logs tg_parser_bot | jq 'select(.event == "watchlist.score_ceiling")'
```
Если потолок стабильно ниже threshold → понизить порог интереса **или** ребалансить веса через `WATCHLIST_KEYWORD_WEIGHT` / `WATCHLIST_SEMANTIC_WEIGHT` (combined = `kw_weight·keyword + sem_weight·semantic`, defaults 0.4/0.6). `WATCHLIST_DEFAULT_THRESHOLD` (default 0.6) — порог для новых интересов без явного threshold. См. [`docs/notes/DIAG_WATCHLIST_ZERO_MATCHES_2026-06-07.md`](../notes/DIAG_WATCHLIST_ZERO_MATCHES_2026-06-07.md).

**Retroactive backfill (DIAG B2).** Scheduler скорит только per-tick новые документы, поэтому корпус, заингещенный до создания интереса, не матчится. Проверить/закрыть разрыв (dry-run по умолчанию):
```bash
tg-parser watchlist backfill <interest_id>            # preview: would_match / max_combined
tg-parser watchlist backfill <interest_id> --apply --notify
```
То же через MCP — `backfill_watchlist(interest_id, dry_run=True)`. Идемпотентно.

> ⚠️ **Гайдрейл: ручной / ретроактивный backfill запускай БЕЗ `limit` (uncapped).** `limit` — это newest-first кап на число скоримых документов; для multi-channel интересов он **молча undercount'ит** исторические матчи, потому что реально релевантный контент часто старый и выпадает за пределы newest-N окна. ADR-0011 default — uncapped (весь matched corpus); `limit` оставлен только как newest-first preview-кап. Замер 2026-06-15: Микробиота с `limit=450` → `would_match=0` (`max_combined=0.331`); без `limit` (весь корпус, 8004 docs) → `would_match=33` (`max_combined=0.789`). Прошлая сессия с `limit=450` записала ~8 матчей суммарно по 5 интересам — uncapped-перепрогон дал 342. Для preview используй `dry_run=true` БЕЗ `limit`; откатывайся на `limit` только если uncapped-прогон реально упал в таймаут (на практике uncapped-прогоны до `scored_docs=8536` проходили без таймаута — `limit` изначально добавляли «против таймаута», которого не случилось).

### Где смотреть в Grafana

Если Grafana уже настроена (см. `docker/grafana/provisioning/`) — можно собрать панель ad-hoc прямо в UI:

1. **Panel 1: F5-C Outcomes (stacked area)** — `sum by(outcome) (rate(tg_resummarize_total[5m]))`.
2. **Panel 2: F5-C Token cost per hour** — `sum by(model, token_type) (rate(tg_resummarize_tokens_total[5m]) * 3600)`.
3. **Panel 3: F5-C Duration p50 / p95 / p99** — `histogram_quantile(0.5/0.95/0.99, ...)`.
4. **Panel 4: topic_card_versions row count** — Prometheus не покрывает; либо PostgreSQL exporter (если есть), либо ручной SQL.

> 💡 После 1-2 недель прода — эти панели можно зашить в provisioning JSON для постоянного дашборда (отдельная задача в Phase 2 issue).

---

## Tripwire response

### Tripwire #1 — `llm_error` > 10%

**Что значит:** LLM возвращает невалидный JSON / падает при парсинге / hits rate-limit.

**Действия:**
1. Проверить логи: `docker compose logs tg_parser | grep -E 'f5c_resummarize_failed|InvalidJSON|RateLimit'`.
2. Если rate-limit — снизить `RESUMMARIZE_MAX_PER_TICK` (например, с 10 до 3) через env-var и `docker compose restart tg_parser`. Изменение не требует миграции / рестарта DB.
3. Если систематический InvalidJSON на конкретной модели — переключить scope на другую модель runtime через MCP: `set_llm_config(scope="resummarize", provider="openai", model="gpt-4o-mini")`. Изменение применяется к новым LLM-вызовам без рестарта.
4. Если #2 / #3 не помогают — kill-switch: `RESUMMARIZE_ENABLED=false` в `.env` + `docker compose restart tg_parser`. F5-C выключится, counter `new_items_since_last_summary` продолжит инкрементироваться (eventual consistency сохранится — после re-enable F5-C подхватит накопившихся кандидатов).

### Tripwire #2 — `version_raced` > 5%

**Что значит:** advisory-lock + UNIQUE constraint срабатывают чаще, чем ожидалось — две одинаковые темы пытаются re-summarize одновременно. Это не data corruption, но потеря работы (LLM-токены потрачены, summary не сохранён).

**Действия:**
1. Проверить, не запущены ли два worker'а параллельно: `docker compose ps | grep -E 'tg_parser'` (scheduler работает внутри `tg_parser` контейнера, отдельного compose-сервиса нет). Должна быть только одна реплика.
2. Если scheduler один — проверить, не дёргает ли кто-то `force_resummarize` через MCP / CLI на тех же темах одновременно с автоматическим тиком. Сообщить admin'ам.
3. Если ни #1, ни #2 — это **бага**, открыть GH issue с logs + PromQL screenshot. Decision #2 / #5 / #4d должны были это исключить — нужен post-mortem.

### Tripwire #3 — `duration p95 > 30 s`

**Что значит:** одна re-summarize заняла >30 с (почти таймаут scheduler tick'a).

**Действия:**
1. Проверить per-model breakdown: `histogram_quantile(0.95, rate(tg_resummarize_duration_seconds_bucket{model="gpt-4o-mini"}[15m]))`. Если только один model — переключиться через `set_llm_config`.
2. Снизить `RESUMMARIZE_INPUT_WINDOW_N` (например, с 10 до 5) — меньше items в prompt → быстрее LLM.
3. Если LLM здоров, но duration высокий — проверить network latency между API и LLM-провайдером (могут быть IPv6 / DNS проблемы на VPS).

### Tripwire #4 — source paused via `_pause_source_for_billing`

**Что значит:** `AnthropicBillingError` всплыл *внутри текущего интервала между cron-тиками*, scheduler пометил source как paused — F5-C сделал свою работу (Decision #13).

**Семантика alarm-а (после TD-NEW-B, 2026-04-27):**
- Alarm срабатывает на **delta** `tg_parser_anthropic_billing_block_total` между двумя последовательными запусками `f5c_watch.sh`, не на абсолютное значение counter-а.
- State хранится в `${F5C_WATCH_STATE_DIR:-~/.f5c-watch}/billing_block_state` (single-line ASCII number).
- **Первый запуск после деплоя**: no baseline → alarm подавлен (warm-up), state записывается для следующего тика. Ожидается одна `first run, no baseline` строка в `cron.log`.
- **Container restart** (counter reset, prev > current): delta clamped to 0, alarm подавлен. Любые *новые* billing events после рестарта tripp-нут на следующем тике.
- **Cumulative counter ≠ 0 but delta = 0**: означает, что billing-инцидент уже случился, но в текущем окне новых не было — это GREEN. До TD-NEW-B такая ситуация показывала false-positive TRIPWIRE до перезапуска API.

**Действия при настоящем delta > 0:** см. [`ANTHROPIC_BILLING_RECOVERY.md`](ANTHROPIC_BILLING_RECOVERY.md). После восстановления баланса — снять pause через MCP / CLI, F5-C автоматически возобновится на следующем тике (счётчик не потерял значение, но и delta вернётся к 0 как только новые pause-ы перестанут происходить).

---

## Rollback

Если деплой пошёл совсем плохо — F5-C спроектирован под backward-compatible откат:

```bash
# 1. Остановить F5-C через kill-switch (мгновенно, без миграции)
echo "RESUMMARIZE_ENABLED=false" >> ~/TG_parser/.env
docker compose restart tg_parser

# 2. Если нужен hard rollback (вернуть код):
cd ~/TG_parser
git checkout <commit-before-f5c>  # например, e1b7ba1 (последний pre-F5C)
docker compose pull && docker compose --profile bot up -d --no-deps tg_parser mcp tg_bot

# 3. Откат миграции (опасно — теряются audit-trail rows; обычно НЕ нужен,
# потому что F11/F6 изолированы от F5-C):
tg-parser db downgrade --db processing --revisions 1 --yes
# → drops topic_card_versions + 3 columns from topic_cards
# → IMPORTANT: исторические версии тем теряются навсегда; для MVP допустимо.
```

Backward-compat проверена: F11 watchlist + F6 digest продолжают работать без F5-C-колонок (см. Sprint F5-C planning § «Migration / Backward»).

---

## T7 — Включение `RESUMMARIZE_MAX_AGE_DAYS` (freshness, консервативный prod-default ~14д)

> 🚦 **GATED — НУЖЕН ЯВНЫЙ GO ПОЛЬЗОВАТЕЛЯ (cost-watch).** Этот раздел **готовит** выкат, но **не включает** его. `RESUMMARIZE_MAX_AGE_DAYS` остаётся `0` (disabled) в проде до отдельного явного решения владельца по результатам cost-watch. Документация ниже — операционная инструкция «как включить, когда будет go», а не сигнал «включай сейчас». Дефолт `0` сохраняет bit-for-bit MVP-поведение (counter-only триггер).

### Что делает knob

`RESUMMARIZE_MAX_AGE_DAYS` (env, `settings.resummarize_max_age_days`, `tg_parser/config/settings.py:658`) — **time-based** триггер re-summarize, который **дополняет, а не заменяет** counter-триггер `RESUMMARIZE_TRIGGER_N`. При `> 0` тема дополнительно становится кандидатом, если её последнее summary старше N дней **И** у неё есть хотя бы один новый item (`new_items_since_last_summary > 0`) — даже если counter ещё не дошёл до `RESUMMARIZE_TRIGGER_N`. Это ловит low-volume темы, которые морально устаревают, ни разу не набрав порог счётчика.

- Предикат `new_items > 0` сохранён умышленно → candidate-query остаётся под partial-index `idx_topic_cards_resummarize_candidates` (без full-scan).
- Отбор кандидатов — чистый SQL OR-предикат в `TopicCardRepo.list_resummarize_candidates` (`run_for_channel` передаёт `max_age_days=settings.resummarize_max_age_days`, `tg_parser/services/resummarization_service.py:165`); LLM на этапе отбора не вызывается.
- Почему именно при отборе селектится «age»: см. `_classify_trigger` (`tg_parser/services/resummarization_service.py:75`) — `counter` (counter ≥ N) / `age` (только time-based ветка) / `-` (force или путь без card).
- Хук тот же, что у MVP: `run_resummarize_for_channel`. Начиная с decoupling-правки он вызывается **в каждом** scheduler-тике (включая «тихие» тики без новых документов) — он вынесен ИЗ блока `if new_doc_refs:` (зеркало ENH-001 для F11 watchlist), чтобы age-ветка могла сработать на low-volume каналах, которые никогда не добирают counter-порог. Порядок сохранён: хук по-прежнему идёт ПЕРЕД F11 watchlist, поэтому при наличии новых документов matcher всё так же скорит по самому свежему summary (`tg_parser/services/scheduler_service.py`, вызов `rs_summary = await run_resummarize_for_channel(...)`). Нового surface нет.

### Рекомендованный консервативный prod-default ≈ 14 дней (rationale)

- Согласован со stale-detector из tracking-issue #15 («> 14 days»): тема, не обновлявшаяся 2 недели, при появлении новых items считается «морально устаревшей».
- Достаточно длинный, чтобы НЕ ре-суммаризировать активные темы повторно (их и так гоняет counter-триггер) — age-ветка добивает только хвост low-volume тем.
- KB вырос ~2× (≈745 топиков) → доля low-volume тем, стареющих без counter-триггера, реально значима; 14д — это «добивающий», а не «основной» триггер.
- Граница оценки агрессивности зашита в gate (см. ниже): если age-ветка начинает давать **большинство** re-summarize, default 14д надо удлинять.

### Как включить (когда будет go) — безопасно, поэтапно

1. **Pre-flight cost baseline.** Снять текущий per-channel re-summarize cost (24ч) ДО включения — будет с чем сравнивать:
   ```promql
   sum(increase(tg_resummarize_total[24h])) by (channel_id, trigger)
   sum(increase(tg_resummarize_tokens_total[24h])) by (channel_id, token_type)
   ```
   Ожидание до включения: `trigger="age"` ≈ 0 (knob disabled). Прикинуть размер хвоста stale-тем:
   ```sql
   -- processing-БД; сколько тем разом станут age-кандидатами на первом тике
   SELECT COUNT(*) FROM topic_cards
   WHERE new_items_since_last_summary > 0
     AND new_items_since_last_summary < 5            -- < RESUMMARIZE_TRIGGER_N
     AND last_summarized_at < NOW() - INTERVAL '14 days';
   ```
2. **Включить env (один knob, без миграции, без рестарта DB):**
   ```bash
   # ~/TG_parser/.env  — поставить значение явно (НЕ оставлять 0)
   RESUMMARIZE_MAX_AGE_DAYS=14
   docker compose restart tg_parser   # подхватывается на следующем тике
   ```
   Триггер и каппинг тюнятся тем же стеком env, что у MVP — менять DB / схему не нужно.
3. **Наблюдать первые 24–48 ч** по разделу § Мониторинг ниже (особенно первый тик после рестарта — там вскрывается накопленный хвост stale-тем).

> ⚠️ **Главный риск — cost-spike на ПЕРВОМ включении.** Весь хвост stale-тем фитит age-предикат одновременно → всплеск кандидатов на первых тиках. Митигируется существующим triple-cap (`RESUMMARIZE_MAX_PER_TICK=10` / `RESUMMARIZE_MAX_DURATION_S=60` / `RESUMMARIZE_MAX_TOKENS_PER_TICK=50000` per channel per tick) + fair-scheduling (`ORDER BY new_items DESC, updated_at DESC`): backlog растягивается на несколько тиков, абсолютный per-tick потолок cost **не меняется** от включения knob. Можно дополнительно занизить `RESUMMARIZE_MAX_PER_TICK` на время «переваривания» хвоста, затем вернуть.

### Cost implications (LLM-вызовы за тик)

- Каждый re-summarize = **1 LLM-вызов** (scope `resummarize`, дефолтная модель дешёвая — `gpt-4o-mini`, наследуется через `RESUMMARIZE_LLM_PROVIDER`/`RESUMMARIZE_LLM_MODEL`).
- Включение age-триггера **повышает объём** re-summarize (добавляет хвост low-volume тем), но **не повышает per-tick потолок**: triple-cap бьёт по числу тем / wall-time / токенам на тик per channel независимо от того, какой предикат отобрал тему.
- Абсолютный TCO upper bound тот же, что у MVP: `RESUMMARIZE_MAX_TOKENS_PER_TICK=50000` × 24 тика/день ≈ ~1.2M tokens/day/channel в худшем случае; на практике — десятки центов / месяц / канал (см. § Cost выше).
- Тюнинг при перерасходе: поднять `RESUMMARIZE_MAX_AGE_DAYS` (реже триггерит хвост), либо понизить `RESUMMARIZE_INPUT_WINDOW_N` (дешевле prompt), либо поднять `RESUMMARIZE_TRIGGER_N`.

### Мониторинг (per-channel cost + freshness gate)

Метрики уже инструментированы (Wave 2 #10 — реальный `channel_id` в зарезервированном label):

```promql
# Доля «age»-триггера в общем re-summarize-миксе (cost от включения knob)
sum(rate(tg_resummarize_total{trigger="age"}[1h]))
  / sum(rate(tg_resummarize_total{trigger=~"counter|age"}[1h]))

# Per-channel re-summarize rate (какой канал гонит spend)
sum(rate(tg_resummarize_total[1h])) by (channel_id, trigger)

# Per-channel token-cost (channel_id="-" = card неизвестен)
sum(rate(tg_resummarize_tokens_total[1h])) by (channel_id, token_type)
```

Готовые панели и алерты **уже provisioned** (этот раздел их только описывает, дублировать JSON не нужно):

- **Grafana:** dashboard `docker/grafana/dashboards/wave2_observation.json`, row **«T7 F5-C P2 — Re-summarize freshness»** — панели: re-summarize rate by channel & outcome, outcomes 24h, **tokens by channel (rate + cumulative)**, duration p50/p95, **trigger split counter-vs-age** (rate + 24h), и **age-trigger 14d share vs 50% gate** (stat + timeseries).
- **Prometheus:** `docker/prometheus/alerts.yml` —
  - recording rule `tg:resummarize_age_trigger:ratio14d` = `age / (counter + age)` за trailing 14д (bucket `-` исключён);
  - **T7 GATE** `ResummarizeAgeTriggerGateF5CPhase2` (info, `for: 12h`): фитит при `ratio14d >= 0.5` — «age-триггер даёт большинство re-summarize → оценить, не слишком ли агрессивен 14д cutoff» (паритет с F5-B 7d gate; это сигнал на оценку, не инцидент);
  - `ResummarizeLLMErrorRate` (info, `for: 30m`): `outcome="llm_error"` доля > 20% за 30м — health LLM-провайдера re-summarize.

Acceptance после включения: `age`-доля стабильно `< 50%` (gate зелёный) и per-channel token-cost в пределах baseline + ожидаемого хвоста. Если gate краснеет — **не инцидент**, а сигнал удлинить `RESUMMARIZE_MAX_AGE_DAYS`.

### Rollback (мгновенный, без миграции)

```bash
# Вернуть knob в disabled — age-триггер выключается на следующем тике,
# counter-триггер MVP продолжает работать как раньше (bit-for-bit).
# ~/TG_parser/.env
RESUMMARIZE_MAX_AGE_DAYS=0
docker compose restart tg_parser
```

Откат миграции/кода НЕ требуется — это чистый env-knob поверх уже задеплоенной P2-инфраструктуры. Полный kill-switch фичи (если нужно) — `RESUMMARIZE_ENABLED=false` (см. § Rollback выше). `topic_card_versions` и накопленный counter не трогаются — после повторного включения age-триггер просто перестаёт/начинает добивать хвост.

---

## Helper-скрипт `docker/f5c_watch.sh`

В каждом чек-поинте можно дёрнуть единый скрипт вместо ручного PromQL/SQL — он печатает то же, что таблица выше, и возвращает структурированный exit-code:

```bash
ssh -p 2296 user@212.72.189.15 'cd ~/TG_parser && ./docker/f5c_watch.sh'           # человеко-читаемый отчёт
ssh -p 2296 user@212.72.189.15 'cd ~/TG_parser && ./docker/f5c_watch.sh --quiet'   # одна строка-вердикт для лога
```

Exit codes: `0` — все четыре tripwire'а молчат, `1` — сработал ≥1 tripwire (см. § Tripwire response), `2` — инфраструктурная проблема (API/MCP/DB недоступны). Параметры через ENV: `F5C_API_URL`, `F5C_API_KEY`, `F5C_LLM_ERR_THRESHOLD`, `F5C_VERSION_RACED_THRESHOLD`, `F5C_DURATION_P95_THRESHOLD_S`, `F5C_DB_NAME_PROCESSING` (см. шапку скрипта).

Для multi-day pilot можно повесить на cron:

```cron
0 */4 * * * /home/user/TG_parser/docker/f5c_watch.sh --quiet >> /var/log/f5c_watch.log 2>&1
```

> Use the absolute path of the deploy user's home (`~/TG_parser` expands to
> `/home/user/TG_parser` for the canonical deploy user) — cron does not expand `~`
> reliably across shell wrappers.

> Скрипт делает coarse-grained проверку (cumulative ratios + bucket-приближение для p95). Для точного rate-based анализа за окно — Grafana / PromQL из § PromQL queries выше.

---

## Post-watch report (через 24 ч)

После 24 ч успешного watch'a — закрыть пилот:

1. Снять метрики:
   ```promql
   sum by(outcome) (increase(tg_resummarize_total[24h]))
   sum by(model) (increase(tg_resummarize_tokens_total[24h]))
   histogram_quantile(0.5, rate(tg_resummarize_duration_seconds_bucket[24h]))
   histogram_quantile(0.95, rate(tg_resummarize_duration_seconds_bucket[24h]))
   ```
2. Снять SQL-снапшот размера `topic_card_versions` (rows + size MB).
3. Пост в Phase 2 issue **#15**: цифры за 24 ч + рекомендации по приоритизации Phase 2 (например, «после 24 ч 100k rows и 50 MB — пункт #1 TTL приоритет 1»).
4. Если всё OK — F5-C MVP считается **производственно стабильным**, можно стартовать любой пункт Phase 2 по сигналу.

### Post-watch report — шаблон комментария для issue #15

Скопировать в комментарий к [F5-C Phase 2 tracking issue](https://github.com/AlexEfimov/TG_parser/issues/15), подставить значения вместо `<...>`. Вердикт по каждому пункту — один из `green` / `yellow` / `red` (объяснить если не green).

```markdown
## F5-C MVP — 24h post-watch report

**Период:** `<deploy-time>` … `<deploy-time + 24h>` (UTC)
**Релиз:** tag `f5c-mvp-2026-04-26` / merge commit `29679e0`
**Скрипт:** `docker/f5c_watch.sh` (последний run: `<timestamp> exit=<code>`)

### 1. Outcome distribution (PromQL `sum by(outcome) (increase(tg_resummarize_total[24h]))`)

| outcome          | count | %     | comment |
|------------------|-------|-------|---------|
| ok               | <N>   | <pct> |         |
| locked           | <N>   | <pct> |         |
| llm_error        | <N>   | <pct> |         |
| version_raced    | <N>   | <pct> |         |
| empty_scope      | <N>   | <pct> |         |
| no_card          | <N>   | <pct> |         |
| no_bundle        | <N>   | <pct> |         |
| unknown          | <N>   | <pct> |         |
| **TOTAL**        | <N>   | 100%  |         |

**Acceptance:** `ok` ≥ 80% от total → **<green/yellow/red>**.

### 2. Cost (PromQL `sum by(model) (increase(tg_resummarize_tokens_total[24h]))`)

| model           | prompt tokens | completion tokens | est. USD |
|-----------------|---------------|-------------------|----------|
| gpt-4o-mini     | <N>           | <N>               | $<N>     |
| <other>         | <N>           | <N>               | $<N>     |

**Расчёт:** gpt-4o-mini = `$0.15/1M prompt + $0.60/1M completion`.
**Acceptance:** ниже планируемого upper bound (1.2M tokens/day/channel) → **<green/yellow/red>**.

### 3. Duration

- p50: `<N>s` (PromQL `histogram_quantile(0.5, rate(tg_resummarize_duration_seconds_bucket[24h]))`)
- p95: `<N>s` (тот же query, `0.95`)
- p99: `<N>s`

**Acceptance:** p95 < 30s → **<green/yellow/red>**.

### 4. SQL snapshot — `topic_card_versions`

```sql
SELECT COUNT(*), pg_size_pretty(pg_total_relation_size('topic_card_versions')),
       COUNT(DISTINCT topic_id), MAX(version_no), AVG(version_no)::numeric(10,2)
FROM topic_card_versions;
```

| rows | size | topics_with_history | max_version | avg_version |
|------|------|---------------------|-------------|-------------|
| <N>  | <X>  | <N>                 | <N>         | <N>         |

**Acceptance:** rows ≈ counter(`outcome=ok`); size в МБ, не ГБ → **<green/yellow/red>**.

### 5. Tripwires fired

- [ ] `#1 llm_error > 10%` — **<no/yes (детали)>**
- [ ] `#2 version_raced > 5%` — **<no/yes>**
- [ ] `#3 duration p95 > 30s` — **<no/yes>**
- [ ] `#4 anthropic billing pause` — **<no/yes>**

### 6. Производственный сигнал → приоритет Phase 2

| Пункт #15 | Сигнал из 24h | Приоритет |
|-----------|---------------|-----------|
| #1 TTL для `topic_card_versions` | rows growth `<rows/day>`, projected `<GB/year>` | <P0/P1/P2/-> |
| #4 Time-based триггер | темы с `last_summarized_at < deploy_time AND new_items > 0` | <P0/P1/P2/-> |
| #5 Bot tools | UX-запрос: <none/<details>> | <P0/P1/P2/-> |
| #10 Per-channel метрика | если виден skew по каналам | <P0/P1/P2/-> |
| иные пункты | — | -- |

### 7. Финальный вердикт

- [ ] **GREEN** — F5-C MVP **производственно стабилен**, watch закрыт; новый спринт можно стартовать.
- [ ] **YELLOW** — есть warnings, но не блокеры; watch продлить ещё на 24 ч.
- [ ] **RED** — сработал tripwire, требуется hot-fix или rollback.

### 8. Артефакты

- Snapshot всех графиков Grafana (`.png` в комментарии).
- Если что-то меняли в env-tunable конфиге — указать новые значения в `<...>`.
```

---

## FAQ

### Q: F5-C ничего не делает после деплоя — `tg_resummarize_total = 0`. Сломан?

**A:** Скорее всего — нет. После decoupling-правки сам хук `run_resummarize_for_channel` вызывается в **каждом** тике (даже без новых документов), поэтому «не было ingestion в этом тике» больше НЕ объясняет нулевой `tg_resummarize_total` — реальный гейт это наличие кандидатов. Проверь:
1. Идут ли вообще scheduler-тики? `tg-parser pipeline status` или `docker compose logs tg_parser | grep _process_source` — должны быть регулярные тики (если их нет — проблема в scheduler, а не в F5-C).
2. Есть ли темы-кандидаты? Counter-ветка: `SELECT COUNT(*) FROM topic_cards WHERE new_items_since_last_summary >= 5;`. Age-ветка (только если `RESUMMARIZE_MAX_AGE_DAYS > 0`): темы старше N дней с `new_items_since_last_summary > 0`.
3. Если #2 = 0 — F5-C bypass'ится **legitимно**: нет кандидатов, нет работы. Дождись накопления новых items в темах (а при включённой age-ветке — устаревания low-volume тем).
4. Если #2 > 0, но `tg_resummarize_total` всё ещё 0 — проверь `RESUMMARIZE_ENABLED` в env (`grep RESUMMARIZE_ENABLED .env`). Если установлен в `false` — это и есть причина.

### Q: Force-resummarize через CLI работает, а scheduler tick — нет.

**A:** Force-resummarize обходит порог (Decision #1) и kill-switch (`RESUMMARIZE_ENABLED=false` его НЕ блокирует — это admin-tool). Если force работает, а tick — нет, значит проблема в scheduler (не в F5-C самом). Проверь `docker compose logs tg_parser | grep _process_source` — должны быть регулярные тики.

### Q: Хочу включить F5-C только для одного канала на пилоте.

**A:** Не поддерживается в MVP. F5-C — global on/off через `RESUMMARIZE_ENABLED`. Если нужен per-channel pilot — это пункт-кандидат для Phase 2 (можно добавить в issue #15 как item #11).
