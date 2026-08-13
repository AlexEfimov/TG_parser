# Runbook — BUG-095: восстановление доставки watchlist-алертов (деплой + watch)

**Создан:** 2026-08-13 (сессия R8). **Статус: процедура подготовлена, НЕ выполнена** — деплой и разбор бэклога требуют явного GO владельца ([START_PROMPT R8](../notes/START_PROMPT_FIX_BUG095_WATCHLIST_DELIVERY_R8_2026-08-13.md) §5).

**Что деплоим:** инстант-доставку F11 из процесса бота (форма B, [BUG-095](../notes/BUG_LOG.md)). Матчер как жил в `tg_parser`, так и живёт; новая задача `watchlist_instant_flush` в `tg_parser_bot` забирает `notified=false` матчи активных `instant`-интересов и шлёт их. Подробности решения — [ADR-0014](../adr/0014-watchlist-batch-silent-delivery.md) § «Instant delivery topology».

**Не docs-only.** Меняется код и добавляется расписание в бот-процессе. Миграции **нет**, схема не тронута.

---

## 0. Перед деплоем

| Проверка | Команда / ожидание |
|---|---|
| Прод и `main` сходятся | `ssh prod 'cd /home/user/TG_parser && git rev-parse --short HEAD'` — сверить с `git rev-parse --short origin/main`. Расхождение — не блокер, но объясняется до деплоя |
| На логах не висит чужой замер | Пересоздание контейнера стирает его логи (Known constraint 2026-08-04). Замер `mcp.auth.static_fallback_used` для R1 снят заранее 2026-08-13 11:19 UTC (BUG-099), поэтому этот деплой ничего не уносит. Перед **следующим** — проверять снова |
| Точка отката зафиксирована | `ssh prod 'docker tag tg_parser:latest tg_parser:pre-prNNN-2026-08-13'` (образец — BUG-093). Записать id образа в артефакты сессии |
| Пересчитан бэклог | Запрос из §3.3 стартового промпта. На 2026-08-13: **93 матча, 14 интересов, один чат `5445781511`**, все `instant` и `is_active` |

## 1. Деплой

Процедура — [`PRODUCTION_DEPLOYMENT.md`](../../PRODUCTION_DEPLOYMENT.md). Пересоздавать контейнер, **не** `restart` (BUG-078); помнить, что `up -d` без изменения rendered spec не пересоздаёт (BUG-090).

```bash
ssh prod 'cd /home/user/TG_parser && git pull --ff-only'
ssh prod 'cd /home/user/TG_parser && docker compose build tg_parser'
# бот — носитель фикса; tg_parser пересобирается тем же образом (общий код),
# ему из этой правки достаётся только явный лог "доставка отложена".
ssh prod 'cd /home/user/TG_parser && docker compose --profile bot up -d --no-deps --force-recreate tg_bot'
ssh prod 'cd /home/user/TG_parser && docker compose up -d --no-deps --force-recreate tg_parser'
```

**Настройки менять не обязательно** — все ключи `WATCHLIST_INSTANT_FLUSH_*` имеют рабочие дефолты (включено, 300 с). Рекомендуется закрепить один стабильный watermark, чтобы он не сдвигался на каждом рестарте бота:

```
WATCHLIST_INSTANT_FLUSH_CUTOFF=2026-08-13T00:00:00Z   # в .env, читает tg_bot через env_file
```

⚠️ Значение должно быть **тем же**, что уйдёт в `--before` на шаге 2, иначе между двумя половинами останется щель или нахлёст. Allow-list `tg_parser` для этого ключа не нужен — ловушка BUG-092 касается только его курируемого `environment:`-списка, у `tg_bot` есть `env_file`.

## 2. Разбор бэклога — сразу после деплоя, один раз

Скрипт запускается **в контейнере бота**: в `tg_parser` нет `TELEGRAM_BOT_TOKEN`.

```bash
# сначала посмотреть, что уйдёт (ничего не меняет)
ssh prod 'docker exec tg_parser_bot python scripts/watchlist_backlog_summary.py'

# отправить и закрыть историю
ssh prod 'docker exec tg_parser_bot python scripts/watchlist_backlog_summary.py --apply'
```

Ожидание: **одна** сводка в чат `5445781511` с разбивкой по 14 интересам и итогом 93. Повторный `--apply` обязан отправить ноль — идемпотентность держится на том же `notified`-watermark'е, что и доставка.

**Почему сразу после деплоя, а не до:** гейдж считает недоставленные матчи, и до разбора он показывает бэклог. Алерт дебаунсится часом (`for: 1h`) ровно затем, чтобы этот промежуток не разбудил оператора; затягивать его на часы всё же не стоит.

## 3. Проверка

| Что | Как | Ожидание |
|---|---|---|
| Задача зарегистрирована | `ssh prod 'docker logs tg_parser_bot 2>&1 \| grep watchlist_instant_flush_registered'` | одна строка, в ней `interval_seconds` и `watermark` |
| Доставка идёт | следующий матч после деплоя | сообщение в чате в пределах ~5 минут после тика |
| Watermark переключается | `SELECT count(*) FROM watch_matches WHERE notified = false;` | после разбора и первого flush'а — 0 |
| Гейдж на нуле | `curl -s localhost:8000/metrics \| grep tg_watchlist_undelivered_matches` | `0.0` |
| Батч не задет | `ssh prod 'docker logs tg_parser_bot 2>&1 \| grep watchlist_batch_flush'` | работает над своим (пустым) множеством, как и раньше |
| Молчания больше нет | `ssh prod 'docker logs tg_parser 2>&1 \| grep instant_delivery_deferred'` | строки появляются на каждом тике с матчами — это норма формы B, а не ошибка: `tg_parser` честно говорит, что доставка передана боту |

## 4. Откат

Фикс аддитивен и откатывается образом:

```bash
ssh prod 'docker tag tg_parser:pre-prNNN-2026-08-13 tg_parser:latest && cd /home/user/TG_parser && docker compose --profile bot up -d --no-deps --force-recreate tg_bot'
```

Данные откат не портит: матчи, уже помеченные `notified=true`, останутся помеченными (они действительно доставлены), а недоставленные так и лежат с `notified=false` — то есть система возвращается ровно в дофиксовое состояние. Отдельный аварийный рубильник без пересборки — `WATCHLIST_INSTANT_FLUSH_ENABLED=false` в `.env` + пересоздание бота.

## 5. Ссылки

- [BUG-095](../notes/BUG_LOG.md) — причина, решения владельца, результат сессии R8.
- [ADR-0014](../adr/0014-watchlist-batch-silent-delivery.md) § «Instant delivery topology» — нормативная топология доставки.
- [`PLAN_REMEDIATION_BOT_MCP_2026-08-12.md`](../notes/PLAN_REMEDIATION_BOT_MCP_2026-08-12.md) §2 — место R8 в очереди.
