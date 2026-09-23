# Runbook — BUG-108 (a): расход LLM по стадиям, алерт на сутки, ротация логов (R13)

**Создан:** 2026-09-23 (сессия R13). **Статус: подготовлен, деплой — по GO владельца.** Факты исполнения вписываются в колонки «Факт».

**Что деплоим:**

- лейбл `stage` на `tg_parser_llm_tokens_total` / `tg_parser_llm_requests_total`;
- размер каталога, длина промпта и токены в логе каждого вызова Phase 2 discover;
- исправленная строка `[3/4]`;
- алерт `LLMDailySonnetSpendHigh` (> 1M Sonnet за скользящие 24 ч): эталон в Prometheus, доставляемая копия — в Grafana с Telegram;
- ротация логов трёх контейнеров приложения, `json-file` 50m × 6.

Подробности и известные дыры — [BUG-108](../notes/BUG_LOG.md) § «(a) — что сделано» / «(a) — известные дыры».

**Не docs-only:** меняется код (метрики, фабрика LLM-клиента, топикизация, пайплайн), compose (logging, env Grafana), provisioning Grafana и правила Prometheus. Миграции **нет**. `.env` на проде **меняется**: две новые переменные для Telegram.

---

## 0. Перед деплоем

| Проверка | Команда / ожидание | Факт |
|---|---|---|
| Прод и `main` сходятся | `ssh prod 'cd /home/user/TG_parser && git rev-parse --short HEAD'` против `git rev-parse --short origin/main` | |
| Улики с логов сняты | Пересоздание стирает логи всех трёх контейнеров (Known constraint 2026-08-04). Нужное из текущего окна снять **до** `up -d` | |
| Редакция BUG-087 / BUG-088 в образе | фиксы `#362` / `#366` — предки `origin/main`; новый образ собирается из `main` | ✅ проверено 2026-09-23 при подготовке |
| LogConfig до | `for c in tg_parser tg_parser_bot tg_parser_mcp; do docker inspect -f '{{json .HostConfig.LogConfig}}' $c; done` → `10m` × `3` (дефолт из `/etc/docker/daemon.json`) | 2026-09-23 08:50Z: у всех шести контейнеров `{"max-file":"3","max-size":"10m"}` |
| Точка отката | `ssh prod 'docker tag tg_parser:latest tg_parser:pre-r13-2026-09-23'` и записать id. **Внимание:** `tg_parser` / `tg_parser_mcp` сейчас на `5924dcfc43c3`, а `tg_bot` и тег `latest` — на `d5699530e59e` (BUG-099 bot arm). Для отката parser / mcp нужен **их** id, а не `latest` | |
| Фаза тика до | `docker logs tg_parser 2>&1 \| grep 'incremental_pipeline' \| grep 'next run' \| tail -1` | 2026-09-23: фаза `:31:31` UTC |
| Серии токенов до | `count by (job,provider,model,token_type) (tg_parser_llm_tokens_total)` — 4 серии без `stage` | 2026-09-23: 4 серии, `job=tg_parser_api` |
| Куда слать алерт | Решение владельца 2026-09-23: **основной бот** и **личка владельца**. `GRAFANA_TELEGRAM_BOT_TOKEN` = значение `TELEGRAM_BOT_TOKEN` из прод-`.env` (копировать на хосте, не выводя на экран); `GRAFANA_TELEGRAM_CHAT_ID` = Telegram user id владельца из `BOT_ALLOWED_USERS`. Личка с основным ботом уже открыта — владелец им пользуется | |

## 1. Деплой

Процедура — [`PRODUCTION_DEPLOYMENT.md`](../../PRODUCTION_DEPLOYMENT.md). Контейнеры пересоздаются, **не** `restart` (BUG-078); `--force-recreate` обязателен (BUG-090); бот — под `--profile bot`.

```bash
ssh prod 'cd /home/user/TG_parser && git pull --ff-only'
# .env: бэкап, затем две строки (значения — по решению §0)
ssh prod 'cd /home/user/TG_parser && cp -p .env .env.bak-pre-r13-$(date -u +%Y%m%dT%H%M%SZ)'
#   GRAFANA_TELEGRAM_BOT_TOKEN=…
#   GRAFANA_TELEGRAM_CHAT_ID=…
ssh prod 'cd /home/user/TG_parser && docker compose build tg_parser'
ssh prod 'cd /home/user/TG_parser && docker compose --profile bot up -d --no-deps --force-recreate tg_parser mcp tg_bot'
ssh prod 'cd /home/user/TG_parser && docker compose up -d --no-deps --force-recreate grafana'
ssh prod 'docker exec tg_parser_prometheus wget -qO- --post-data= http://localhost:9090/-/reload'
```

- **Три контейнера приложения пересоздаются все** — `logging:` входит в спецификацию контейнера, и без пересоздания новый LogConfig не применяется.
- **Grafana пересоздаётся**: новые переменные окружения и новый файл provisioning. Её данные лежат в volume `grafana_data` и не теряются.
- **Postgres не трогать.** Его спецификация не менялась, поэтому `--no-deps` обязателен.
- **Prometheus не пересоздаётся** — достаточно `/-/reload`: конфиг смонтирован каталогом (BUG-090).

## 2. Проверка

| # | Что | Как | Ожидание | Факт |
|---|---|---|---|---|
| 1 | Новый LogConfig | `docker inspect` из §0 | `{"max-file":"6","max-size":"50m"}` у трёх; у postgres / prometheus — прежний `10m` × `3` | |
| 2 | Все healthy | `docker ps --format '{{.Names}} {{.Status}}'` | `tg_parser`, `tg_parser_mcp`, `tg_parser_bot` — `healthy` | |
| 3 | Правило Prometheus загружено | `wget -qO- localhost:9090/api/v1/rules` → группа `tg_parser_bug108_llm_spend` | 1 правило, `inactive`; всего 33 | |
| 4 | Grafana загрузила правило, contact point и маршрут | `GET /api/v1/provisioning/alert-rules`, `/contact-points`, `/policies` (admin, `127.0.0.1:3000`) | `bug108_llm_daily_sonnet_spend`; `owner-telegram` типа `telegram`; корень `noop-null`, дочерний маршрут `notify=owner_telegram` → `owner-telegram`, `repeat_interval` `1d` | |
| 5 | Доставка доходит | Grafana UI → Alerting → Contact points → `owner-telegram` → **Test** | тестовое сообщение пришло в чат | |
| 6 | Первый тик прошёл | ждать «старт плюс интервал» (урок R10), не сетку часов | `incremental_pipeline … executed successfully` | |
| 7 | Серии получили `stage` | `count by (stage) (tg_parser_llm_tokens_total)` после первого тика с LLM-вызовом | серия с `stage="processing"`; ни одной `stage="unknown"` | |
| 8 | Строка `[3/4]` | `docker logs tg_parser 2>&1 \| grep '\[3/4\]' \| tail -1` | `In-pipeline topicization skipped (on scheduler ticks it runs next as stage incremental_topicization; …)` | |

## 3. Отложенная проверка (не блокирует закрытие сессии)

Первый вызов Phase 2 после деплоя (раз в 1–2 дня):

- в логе `tg_parser` появились `Phase 2 discover call: … cross_channel_topics=… prompt_chars=…` и `Phase 2 batch: … input_tokens=… output_tokens=…`;
- `increase(tg_parser_llm_tokens_total{stage="topicization_discover"}[1h])` за тот же час совпадает с суммой `input_tokens + output_tokens` из лога.

Эти числа — базовая линия «до R14» (чистка удалённых каналов) и вход для выбора формы потолка в R17.

## 4. Откат

Правка аддитивна: данных не меняет, миграции нет. Откат кода — образ; откат ротации — тот же образ плюс предыдущий `docker-compose.yml`.

```bash
ssh prod 'cd /home/user/TG_parser && git checkout <prev-HEAD> -- docker-compose.yml docker/ \
  && docker tag <id parser/mcp из §0> tg_parser:latest \
  && docker compose --profile bot up -d --no-deps --force-recreate tg_parser mcp tg_bot grafana \
  && docker exec tg_parser_prometheus wget -qO- --post-data= http://localhost:9090/-/reload'
```

⚠️ После отката `tg_bot` окажется на образе parser / mcp, а не на своём `d5699530e59e`. Если откатывается весь деплой, бот вернуть отдельно: `docker tag d5699530e59e tg_parser:latest` и пересоздать `tg_bot`. Серии со `stage` остаются в TSDB до истечения retention (30 d). Алерты сумм по стадиям не зависят от лейбла, поэтому ничего не сломается.

## 5. Ссылки

- [BUG-108](../notes/BUG_LOG.md) — симптомы, (a) / (b), известные дыры.
- [`START_PROMPT_R13_LLM_COST_OBSERVABILITY_2026-09-23.md`](../notes/START_PROMPT_R13_LLM_COST_OBSERVABILITY_2026-09-23.md) — scope сессии.
- [`PLAN_POST_FORCED_DP_2026-09-23.md`](../notes/PLAN_POST_FORCED_DP_2026-09-23.md) §1 — замер, от которого калибровался порог.
- [`BUG097_R10_DEPLOY_AND_WATCH.md`](BUG097_R10_DEPLOY_AND_WATCH.md) — сдвиг фазы тика после пересоздания.
- [`BUG099_BOT_ARM_DEPLOY.md`](BUG099_BOT_ARM_DEPLOY.md) — почему бот на другом образе.
