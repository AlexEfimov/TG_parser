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
То же через MCP — `backfill_watchlist(interest_id, dry_run=True)`. Идемпотентно; кап 2000 docs.

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

**A:** Скорее всего — нет. Проверь:
1. Был ли incremental ingestion за последний tick? `tg-parser pipeline status` или `docker compose logs tg_parser | grep run_incremental_topicization`.
2. Есть ли темы, набравшие ≥ `RESUMMARIZE_TRIGGER_N` новых items? `SELECT COUNT(*) FROM topic_cards WHERE new_items_since_last_summary >= 5;`.
3. Если #2 = 0 — F5-C bypass'ится **legitимно**: нет триггеров, нет работы. Дождись новых сообщений в каналах.
4. Если #2 > 0, но `tg_resummarize_total` всё ещё 0 — проверь `RESUMMARIZE_ENABLED` в env (`grep RESUMMARIZE_ENABLED .env`). Если установлен в `false` — это и есть причина.

### Q: Force-resummarize через CLI работает, а scheduler tick — нет.

**A:** Force-resummarize обходит порог (Decision #1) и kill-switch (`RESUMMARIZE_ENABLED=false` его НЕ блокирует — это admin-tool). Если force работает, а tick — нет, значит проблема в scheduler (не в F5-C самом). Проверь `docker compose logs tg_parser | grep _process_source` — должны быть регулярные тики.

### Q: Хочу включить F5-C только для одного канала на пилоте.

**A:** Не поддерживается в MVP. F5-C — global on/off через `RESUMMARIZE_ENABLED`. Если нужен per-channel pilot — это пункт-кандидат для Phase 2 (можно добавить в issue #15 как item #11).
