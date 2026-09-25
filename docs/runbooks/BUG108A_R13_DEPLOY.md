# Runbook — BUG-108 (a): расход LLM по стадиям, алерт на сутки, ротация логов (R13)

**Создан:** 2026-09-23 (сессия R13). **Статус: ВЫПОЛНЕНО 2026-09-23** по GO владельца — merge `4e8b72c` ([PR #445](https://github.com/AlexEfimov/TG_parser/pull/445)), контейнеры пересозданы 19:33:34–19:34:02 UTC. Факты — в колонках «Факт». Тестовое сообщение Telegram дошло 2026-09-24 (§2 п. 5), root URL Grafana применён 2026-09-24 ([PR #446](https://github.com/AlexEfimov/TG_parser/pull/446), `54350bc`), отложенная проверка §3 пройдена 2026-09-24. **Открытых пунктов нет.**

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
| Прод и `main` сходятся | `ssh prod 'cd /home/user/TG_parser && git rev-parse --short HEAD'` против `git rev-parse --short origin/main` | ✅ прод `bd03d3e` → после pull **`4e8b72c`** = `origin/main`. ⚠️ `git pull` упёрся бы в неотслеживаемый `docs/notes/AUDIT_TOPICIZATION_KEYWORD_NOISE_2026-08-31.md` (на `main` он стал отслеживаемым в #444); прод-копия — ранний черновик (−219 строк, без раздела «Верификация»), перенесена в `/home/user/AUDIT_TOPICIZATION_KEYWORD_NOISE_2026-08-31.prod-draft.md`, не удалена |
| Улики с логов сняты | Пересоздание стирает логи всех трёх контейнеров (Known constraint 2026-08-04). Нужное из текущего окна снять **до** `up -d` | ✅ единственный вызов Phase 2 в окне — 2026-09-23 10:32:40→10:32:54Z, `medportal_rfed`, **2285** карточек каталога, 1 док → 1 assigned; Prometheus: **~290k** prompt / ~100 completion Sonnet. Вызов длился **14 с** — меньше интервала скрейпа, ровно случай, ради которого серии праймятся с нуля |
| Редакция BUG-087 / BUG-088 в образе | фиксы `#362` / `#366` — предки `origin/main`; новый образ собирается из `main` | ✅ проверено 2026-09-23 при подготовке |
| LogConfig до | `for c in tg_parser tg_parser_bot tg_parser_mcp; do docker inspect -f '{{json .HostConfig.LogConfig}}' $c; done` → `10m` × `3` (дефолт из `/etc/docker/daemon.json`) | 2026-09-23 08:50Z: у всех шести контейнеров `{"max-file":"3","max-size":"10m"}` |
| Точка отката | `ssh prod 'docker tag tg_parser:latest tg_parser:pre-r13-2026-09-23'` и записать id — ожидается **`d5699530e59e`**. `tg_parser` / `tg_parser_mcp` сейчас на более старом `5924dcfc43c3` (собран из `261f178`), `tg_bot` и `latest` — на `d5699530e59e` (из `c74fae0`, BUG-099 bot arm). Между ними в коде отличаются только `tg_parser/bot/handlers.py` и `tools.py` (`git diff --stat 261f178 c74fae0 -- tg_parser`), поэтому общая точка отката для всех трёх — `d5699530e59e`. **Не** откатываться на `5924dcfc43c3`: compose даёт трём сервисам один тег, и `tg_bot` уехал бы на образ без фикса BUG-099 (fail-open идентичности) | ✅ `tg_parser:pre-r13-2026-09-23` → **`d5699530e59e`** |
| Фаза тика до | `docker logs tg_parser 2>&1 \| grep 'incremental_pipeline' \| grep 'next run' \| tail -1` | 2026-09-23: фаза `:31:31` UTC. Тик 19:31 дождались до пересоздания: `succeeded=18, failed=0`, 87 с |
| Серии токенов до | `count by (job,provider,model,token_type) (tg_parser_llm_tokens_total)` — 4 серии без `stage` | 2026-09-23 19:08Z: 4 серии, `job=tg_parser_api`; Sonnet prompt 2 731 146 / completion 141 791, Haiku 613 650 / 466 695 (значения процесса, жившего с 2026-09-12) |
| Куда слать алерт | Решение владельца 2026-09-23: **основной бот** и **личка владельца**. `GRAFANA_TELEGRAM_BOT_TOKEN` = значение `TELEGRAM_BOT_TOKEN` из прод-`.env` (копировать на хосте, не выводя на экран); `GRAFANA_TELEGRAM_CHAT_ID` = Telegram user id владельца. В `BOT_ALLOWED_USERS` может быть несколько id (тестировщики) — брать id учётки с ролью admin, сверив по `list_users` / `auth` типа telegram, а не первый в списке. Личка с основным ботом уже открыта — владелец им пользуется | ✅ у `admin` две telegram-привязки (`user_auth_mappings`); с ботом общается одна — **`5445781511`** (150 упоминаний в логе бота, последнее 2026-09-23 06:00Z — доставка дайджеста, то есть бот в этот чат писать может), вторая — 0 упоминаний. Токен скопирован из `TELEGRAM_BOT_TOKEN` на хосте, на экран не выводился; бэкап `.env.bak-pre-r13-20260923T191016Z`; `docker compose config` видит оба значения. ⚠️ Бэкап был сделан **внутри** рабочей копии, и git его не игнорирует (как и старый `.env.bak-pre-pr413-20260813T155734Z`), то есть оба были в одном `git add -A` от коммита всех прод-секретов. Найдено ревью 2026-09-24; оба перенесены в `/home/user/env-backups/` (`700`, файлы `600`), рабочая копия чистая. Команда в §1 исправлена |

## 1. Деплой

Процедура — [`PRODUCTION_DEPLOYMENT.md`](../../PRODUCTION_DEPLOYMENT.md). Контейнеры пересоздаются, **не** `restart` (BUG-078); `--force-recreate` обязателен (BUG-090); бот — под `--profile bot`.

```bash
ssh prod 'cd /home/user/TG_parser && git pull --ff-only'
# .env: бэкап, затем две строки (значения — по решению §0)
# бэкап — ВНЕ рабочей копии: .gitignore защищает только точное имя .env
ssh prod 'install -d -m 700 /home/user/env-backups && cp -p /home/user/TG_parser/.env /home/user/env-backups/.env.bak-pre-r13-$(date -u +%Y%m%dT%H%M%SZ)'
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

**Фактически (2026-09-23):**

- образ `tg_parser:latest` → **`a6977308e61d`**, сборка 19:21–19:22Z, около 80 с;
- пересоздание дождалось конца тика 19:31, затем три контейнера приложения и Grafana пересозданы 19:33:34–19:34:02Z, `/-/reload` вернул 0;
- `Background scheduler started` в **19:34:08Z** — новая фаза тика `:34`.

⚠️ Первая попытка «проверка env + build» одной SSH-командой повисла на стороне агента на 10 минут и ничего не запустила на хосте: образ остался августовским, процессов compose нет. Повторена по шагам без побочных эффектов.

## 2. Проверка

| # | Что | Как | Ожидание | Факт |
|---|---|---|---|---|
| 1 | Новый LogConfig | `docker inspect` из §0 | `{"max-file":"6","max-size":"50m"}` у трёх; у postgres / prometheus — прежний `10m` × `3` | ✅ `tg_parser`, `tg_parser_bot`, `tg_parser_mcp` — `a6977308e61d`, `{"max-file":"6","max-size":"50m"}`; grafana / prometheus / postgres — `10m` × `3` |
| 2 | Все healthy | `docker ps --format '{{.Names}} {{.Status}}'` | `tg_parser`, `tg_parser_mcp`, `tg_parser_bot` — `healthy` | ✅ все три `healthy` через ~1 мин |
| 3 | Правило Prometheus загружено | `wget -qO- localhost:9090/api/v1/rules` → группа `tg_parser_bug108_llm_spend` | 1 правило, `inactive`; всего 33 | ✅ 33 правила, `LLMDailySonnetSpendHigh` — `inactive` |
| 4 | Grafana загрузила правило, contact point и маршрут | `GET /api/v1/provisioning/alert-rules`, `/contact-points`, `/policies` (admin). ⚠️ Grafana на хосте — **`127.0.0.1:3001`** (`GRAFANA_PORT=3001` в прод-`.env`); на `:3000` — Flowise. Доступ: `ssh -N -L 3300:127.0.0.1:3001 prod`, затем `http://localhost:3300` | `bug108_llm_daily_sonnet_spend`; `owner-telegram` типа `telegram`; корень `noop-null`, дочерний маршрут `notify=owner_telegram` → `owner-telegram`, `repeat_interval` `1d` | ⚠️ **API недоступен агенту:** `GF_SECURITY_ADMIN_PASSWORD` из env действует только при первой инициализации БД Grafana, пароль admin сменён в UI → 401. Сбрасывать пароль ради проверки не стали. Косвенно: лог `finished to provision alerting` без ошибок (единственная `level=error` — отсутствующий `provisioning/plugins`, было и раньше); `/metrics` Grafana — `rule_evaluation_failures_total 0`, все алерты `normal`. Тот же provisioning проверен через API на локальной Grafana 13.1.1 при подготовке |
| 5 | Доставка доходит | Grafana UI → Alerting → Contact points → `owner-telegram` → **Test** | тестовое сообщение пришло в чат | ✅ **2026-09-24 ~19:32Z** — владелец получил в личке от основного бота `Firing` / `alertname = TestAlert` / `summary = Notification test`. По пути: старый пароль admin не подошёл (в логе `password-auth.invalid`, логин верный; сброс по почте — 500, SMTP нет), сброшен владельцем через `grafana cli admin reset-admin-password --password-from-stdin`. Ссылка «Silence» в сообщении ведёт на `http://localhost:3000/…` — `GF_SERVER_ROOT_URL` не задан, а на `:3000` хоста — Flowise. Исправление — в [PR #446](https://github.com/AlexEfimov/TG_parser/pull/446): в compose `GF_SERVER_ROOT_URL=${GRAFANA_ROOT_URL:-http://localhost:${GRAFANA_PORT:-3000}/}`. ✅ **Применено 2026-09-24 20:08–20:09Z** по §5: прод `4e8b72c` → `54350bc`, бэкап `/home/user/env-backups/.env.bak-pre-root-url-20260924T200857Z`, `GRAFANA_ROOT_URL=http://localhost:3300/` в `.env`, пересоздана только `grafana`; `printenv GF_SERVER_ROOT_URL` → `http://localhost:3300/`, `finished to provision alerting`. Повторный **Test** 2026-09-25 ~06:40Z: ссылка Silence — `http://localhost:3300/alerting/silence/new?…` |
| 6 | Первый тик прошёл | ждать «старт плюс интервал» (урок R10), не сетку часов | `incremental_pipeline … executed successfully` | ✅ 20:34:08→20:35:23Z: `succeeded=18, failed=0, degraded=0`, 75 с; следующий — 21:34:08. Первые токены после деплоя легли под своей стадией: `stage="resummarize"`, Sonnet, 5377. Phase 2 в этом тике не было |
| 7 | Серии получили `stage` и созданы заранее | `count by (job, stage) (tg_parser_llm_tokens_total)` — **сразу** после старта, до первого вызова | по каждому из трёх job серии всех шести стадий со значением 0 (прайминг на старте); ни одной `stage="unknown"`. Без прайминга серия рождается первым вызовом, и `increase()` этот вызов не видит | ✅ через минуту после старта: `tg_parser_api`, `tg_parser_mcp`, `tg_parser_bot` × 6 стадий, по 2 серии (prompt / completion) на каждую; `unknown` — нет |
| 8 | Строка `[3/4]` | `docker logs tg_parser 2>&1 \| grep '\[3/4\]' \| tail -1` | `In-pipeline topicization skipped (on scheduler ticks it runs next as stage incremental_topicization; …)` | ✅ дословно, по строке на источник |

## 3. Отложенная проверка (не блокирует закрытие сессии)

Первый вызов Phase 2 после деплоя (раз в 1–2 дня):

- в логе `tg_parser` появились `Phase 2 discover call: … cross_channel_topics=… prompt_chars=…` и `Phase 2 batch: … input_tokens=… output_tokens=…`;
- разница **сырых** значений `sum(tg_parser_llm_tokens_total{stage="topicization_discover"})` до и после вызова (instant-запросы с `time=` по обе стороны от строки `Phase 2 batch:`) совпадает с суммой `input_tokens + output_tokens` из лога. Сравнивать с `increase(…[1h])` не нужно: он экстраполирует к границам окна и расходится с логом на несколько процентов.

Эти числа — базовая линия «до R14» (чистка удалённых каналов) и вход для выбора формы потолка в R17.

**Факт — ✅ пройдена 2026-09-24.** Первый вызов после деплоя: 17:33:14→17:33:27Z, 13 с.

```text
Phase 2 discover call: channel=mediamedics docs=1 own_topics=260 cross_channel_topics=2042 prompt_chars=757515
Phase 2 batch: 1 assigned, 0 new topics, 0 unassignable (channel=mediamedics input_tokens=290961 output_tokens=94)
```

| `sum by (token_type) (tg_parser_llm_tokens_total{stage="topicization_discover"})` | prompt | completion |
|---|---:|---:|
| `time=17:33:00Z` | 0 | 0 |
| `time=17:34:00Z` | **290 961** | **94** |

Сошлось с логом до токена. Серия стояла на 0 до вызова — это работа прайминга. Вызов короче 15-секундного скрейпа, без прайминга серия родилась бы сразу со значением 290 961, и `increase()` не увидел бы этот вызов вовсе. Для сравнения, `increase(…[1h])` в 18:00Z даёт 292 214 (+0.4 %, экстраполяция).

**Базовая линия «до R14»:** один вызов Phase 2 — около **291k** prompt-токенов Sonnet при каталоге 2302 карточки (260 своих + 2042 чужих) и промпте 757 515 символов. Около 330 символов на карточку, около 2.6 символа на токен.

⚠️ **Хост перезагружался 2026-09-24 05:30:54Z** (`uptime -s`), причина не выяснялась. Контейнеры поднялись через `restart: unless-stopped` в 05:31:21Z, `RestartCount=0`, все healthy. Рестарт без пересоздания логи не стирает, а серии стадий на старте праймятся заново. Фаза тика после этого — `:31`.

## 4. Откат

Правка аддитивна: данных не меняет, миграции нет. Откатывается только **образ**. Остальное от кода не зависит и откатывать его незачем:

- ротация логов безвредна при любом образе;
- правило в Grafana и Prometheus суммирует по всем стадиям, поэтому работает и по сериям без `stage`.

```bash
ssh prod 'docker tag tg_parser:pre-r13-2026-09-23 tg_parser:latest \
  && cd /home/user/TG_parser \
  && docker compose --profile bot up -d --no-deps --force-recreate tg_parser mcp tg_bot'
```

Точка отката — `d5699530e59e` для всех трёх, почему именно она — §0. Если нужно выключить ещё и Telegram-доставку, достаточно убрать две переменные из `.env` и пересоздать `grafana`: на заглушках contact point загружается, но ничего не отправляет. Серии со `stage` остаются в TSDB до истечения retention (30 d) и ничему не мешают.

## 5. Доступ к Grafana

Grafana опубликована только на `127.0.0.1:3001` хоста: в прод-`.env` задан `GRAFANA_PORT=3001`, а `:3000` занят Flowise. Снаружи в неё попадают через туннель:

```bash
ssh -N -L 3300:127.0.0.1:3001 prod    # затем http://localhost:3300, логин admin
```

`GRAFANA_ROOT_URL` в прод-`.env` задаёт `GF_SERVER_ROOT_URL`. От него строятся ссылки **Silence** / **View** в сообщениях алертов. Значение должно совпадать с локальным концом туннеля: при `http://localhost:3300/` ссылки открываются при поднятом туннеле выше. Без переменной действует дефолт `http://localhost:${GRAFANA_PORT}/`, и на этом хосте он неверен. Применить или сменить значение:

```bash
ssh prod 'install -d -m 700 /home/user/env-backups \
  && cp -p /home/user/TG_parser/.env /home/user/env-backups/.env.bak-pre-root-url-$(date -u +%Y%m%dT%H%M%SZ) \
  && cd /home/user/TG_parser \
  && (grep -q "^GRAFANA_ROOT_URL=" .env || echo "GRAFANA_ROOT_URL=http://localhost:3300/" >> .env) \
  && docker compose up -d --no-deps --force-recreate grafana'
```

Проверка:

```bash
ssh prod 'docker exec tg_parser_grafana printenv GF_SERVER_ROOT_URL'   # → http://localhost:3300/
```

Ссылка **Silence** в тестовом сообщении (**Test** у `owner-telegram`) должна вести на `http://localhost:3300/…`. Бэкапы `.env` класть только в `/home/user/env-backups/`, не в рабочую копию: `.gitignore` защищает лишь точное имя `.env`.

Кнопка **Test** у provisioned contact point есть, но её не сразу видно. Если пароль admin утерян, сброс по почте не работает: SMTP не настроен, запрос отвечает 500. Сброс делается на хосте, пароль вводится скрытым вводом:

```bash
ssh -t prod 'read -rsp "New Grafana admin password: " p; echo; printf "%s" "$p" | docker exec -i tg_parser_grafana grafana cli admin reset-admin-password --password-from-stdin'
```

## 6. Ссылки

- [BUG-108](../notes/BUG_LOG.md) — симптомы, (a) / (b), известные дыры.
- [`START_PROMPT_R13_LLM_COST_OBSERVABILITY_2026-09-23.md`](../notes/archive/START_PROMPT_R13_LLM_COST_OBSERVABILITY_2026-09-23.md) — scope сессии.
- [`PLAN_POST_FORCED_DP_2026-09-23.md`](../notes/PLAN_POST_FORCED_DP_2026-09-23.md) §1 — замер, от которого калибровался порог.
- [`BUG097_R10_DEPLOY_AND_WATCH.md`](BUG097_R10_DEPLOY_AND_WATCH.md) — сдвиг фазы тика после пересоздания.
- [`BUG099_BOT_ARM_DEPLOY.md`](BUG099_BOT_ARM_DEPLOY.md) — почему бот на другом образе.
