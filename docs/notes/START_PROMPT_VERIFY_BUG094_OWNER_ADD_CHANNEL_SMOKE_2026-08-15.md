# START PROMPT — R9 verify: живой owner-`add_channel` на проде (хвост BUG-094)

**Дата:** 2026-08-15 · **Сессия:** хвост R9 (verify, не фикс) по [`PLAN_REMEDIATION_BOT_MCP_2026-08-12.md`](PLAN_REMEDIATION_BOT_MCP_2026-08-12.md) §R9, §4 · **Баг:** [BUG-094](BUG_LOG.md) (уже `resolved`)
**Ветка:** `main`. Новой ветки нет.

**Goal (одной строкой):** owner повторно вызывает `add_channel` без лишних полей на канале с историей — курсор и служебные поля байт-в-байт, кроме `updated_at` и намеренного `status=active`.

> Это **verify**, не фикс. Ноль правок app-code. До явного GO владельца в том чате — только чтения и снимок. Коммит протокола smoke — по запросу владельца в **той** сессии, не заранее. Прод: `ssh prod` только с `required_permissions: ["all"]`; `dev_doctor` из песочницы печатает ложный `MISS ssh prod`. Не recreate `tg_parser` / mcp / bot. Не начинать R4.

---

## 0. Opener (вставить в новый чат)

> Стартую verify-сессию R9 — живой owner-`add_channel` на проде после деплоя BUG-094. Это verify, не фикс; до GO только чтение.
>
> Прочитай:
> 1. `docs/notes/START_PROMPT_VERIFY_BUG094_OWNER_ADD_CHANNEL_SMOKE_2026-08-15.md` — **этот файл целиком**
> 2. `docs/runbooks/BUG094_R9_DEPLOY.md` — деплой и read-only smoke уже сделаны; живого вызова там нет
> 3. `docs/notes/BUG_LOG.md`, запись **BUG-094** — workaround, цепочка `last_post_id=NULL` → полный re-fetch, блок «R9 что сделано». Статус уже `resolved` — не откатывать в in-progress
> 4. `docs/notes/PLAN_REMEDIATION_BOT_MCP_2026-08-12.md` §R9, §4 — R9 закрыта, следующая код-сессия R4; эта сессия R4 **не** начинает
> 5. `docs/runbooks/TEST_ACCESS_MULTI_USER.md` §6 — workaround для операторов (после зелёного smoke — обновить фразу «открыт»)
> 6. `docs/adr/0009-idempotency.md` — `add_channel` идемпотентен, reanimates soft-deleted
>
> Начни с `bash scripts/dev_doctor.sh`, сверка `main` vs прод, затем read-only снимок выбранного канала. Вызов — только после явного GO. Bot-арм BUG-099, R4, recreate — **вне scope**.
>
> Строки ниже — перечитанные 2026-08-15 с `main` / прод (`0137b70`). Если код, образ или `last_post_id` уже не такие — скажи вслух, не чини исчезнувшее.

**Состояние на входе** (сверить, а не поверить; inspect 2026-08-15 ~08:13 UTC, `required_permissions: ["all"]`):

| Факт | Что ждать на 2026-08-15 утро |
|---|---|
| Очередь | R9 задеплоена. Код-сессия закрыта. Эта — хвост verify. **Следующая код-сессия — R4**, её здесь не начинать. Параллельно: R12, R6. Bot-арм BUG-099 открыт, не чинить |
| `main` vs прод | Оба **`0137b70`** (docs-closeout `#425`, `docs(bug094): record the R9 deploy`). Код фикса — `8d870e5` / `#424`. Это не drift |
| Образы | `mcp` и `tg_bot` — **`2478721db563`**, healthy, StartedAt `2026-08-14T21:27Z`. `tg_parser` — **`63de8a1123c5`** (R2), StartedAt `2026-08-14T13:29:31Z`, не recreate. Тег `tg_parser:latest` на хосте уже R9 (`2478721db563`); крутящийся parser держит старый id — **не** «выравнивать» recreate |
| Read-only smoke | уже сделан 2026-08-14: хелпер в site-packages mcp/bot, сигнатура `include_comments`/`batch_size` = `None`/`None`, курсоры не тронуты. Живого owner-вызова не было |
| Курсоры (08:13 UTC) | `medportal_rfed.last_post_id=123`; `mediamedics.last_post_id=15396`. Оба `status=active`, `include_comments=f`, `batch_size=100`, `channel_username` пустой, `fail_count=0`, `backfill_completed_at` NULL, `owner_id=c59d42b4-…`, `deleted_at` NULL. Тик 07:30 UTC был incremental, не re-fetch |
| Тик | `incremental_pipeline` — interval 3600 с от старта parser (урок R10). 08:13 UTC: last job `07:30:45Z`, next run **`2026-08-15 08:29:44 UTC`**. К моменту сессии число устареет — перечитай `docker logs tg_parser` (`next run at` / идёт ли тик). Не вызывать в середине чужого тика |
| Живая MCP-схема | prod MCP (`user-tg-parser`): `include_comments` / `batch_size` / `channel_username` — `default: null`. Опущенное поле валидно |
| `TEST_ACCESS` §6 | фраза «BUG-094 (открыт)» **устарела** (статус `resolved` с 2026-08-14). Не править до зелёного smoke; после — одна фраза, что workaround снят |
| Не ждать | Пересечения с R4 нет. Прод-записи до GO нет. Коммит этого стартового промпта не обязателен |

---

## 1. Почему эта сессия существует и почему она сейчас

Фикс на `mcp`/`tg_bot` с 2026-08-14. Read-only smoke доказал, что хелпер установлен и сигнатура `None`/`None`. Единственное, чего нет — живой owner-вызов на канале с историей: до фикса именно он стирал `last_post_id`, поэтому BUG-093 нарочно остановился на чужом токене.

Делать **до R4**, пока деплой свежий и в голове. Если GO откладывают — R4 не блокируется: это хвост verify, не гейт очереди. Не делать «заодно» из R4.

Цепочка, которую проверяем ([BUG-094](BUG_LOG.md)): `last_post_id=NULL` → `_ingest_posts` считает `min_id=None` → Telethon читает канал с начала. На `mediamedics` это ~11k сообщений вхолостую. `backfill_completed_at=NULL` дополнительно делает вид, что initial backfill не кончился (на обоих кандидатах это поле уже NULL — слабый оракул).

---

## 2. Что установлено (не переоткрывать)

1. **Вариант (a) выбран и задеплоен.** Overlay-хелпер [`source_for_add_channel`](../../tg_parser/storage/source_overlay.py). `upsert_source` и [ADR-0009](../adr/0009-idempotency.md) не менялись. Вариант (b) `update_channel` — parking-lot Wave 3.
2. **Read-only smoke 2026-08-14** — [`BUG094_R9_DEPLOY.md`](../runbooks/BUG094_R9_DEPLOY.md) §2. Хелпер есть в mcp/bot, нет в крутящемся `tg_parser`. Не повторять деплой и не recreate «на всякий случай».
3. **BUG-093 закрыт.** Чужой `user`-токен на `medportal_rfed` → отказ, строка не менялась. Не повторять тот вызов: он был с `include_comments=True`, `batch_size=500` и **не** проверяет «опущено». На owner-пути те же аргументы *изменили бы* настройки (`false`/`100` → `true`/`500`) даже с фиксом.
4. **HTTP `add_channel` нет.** Одна поверхность: MCP. Bot не обязателен.
5. **Статус BUG-094 = `resolved`.** Smoke не возвращает запись в in-progress.

---

## 3. Scope — строго в этом порядке

### 3.1 Read-only: doctor, SHA, тик, снимок

1. `bash scripts/dev_doctor.sh`. Песочница соврёт про `ssh prod` — перепроверь с `required_permissions: ["all"]`.
2. Сверка SHA: локальный `main` и `ssh prod 'cd /home/user/TG_parser && git rev-parse --short HEAD'` — ожидание `0137b70` (или скажи вслух, если уехало).
3. Образы не recreate'ить. Ожидание как в таблице §0. `docker inspect` / `docker images` достаточно.
4. Тик: `ssh prod 'docker logs tg_parser 2>&1 | grep -E "next run at|incremental_pipeline" | tail -20'`. Если тик **идёт** (ingestion по выбранному каналу в последних секундах, `last_attempt_at` свежий без `last_success_at`) — подожди конца. Не вызывай `trigger_pipeline`.
5. Снимок **всей** строки `sources` выбранного канала (не только `last_post_id`). Рабочий SELECT с 2026-08-15:

```bash
ssh prod 'cd /home/user/TG_parser && docker compose exec -T postgres psql -U tg_parser_user -d tg_parser -c "
SELECT source_id, channel_id, channel_username, status, include_comments, batch_size,
       last_post_id, backfill_completed_at, last_attempt_at, last_success_at,
       fail_count, last_error, rate_limit_until, comments_unavailable,
       history_from, history_to, poll_interval_seconds, owner_id,
       created_at, updated_at, deleted_at
FROM sources WHERE source_id = '\''medportal_rfed'\'';
"'
```

Сохрани результат как «до». Из него же собери rollback SQL **этой** сессии (числа из §0 к 08:13 устареют после следующего тика: `last_attempt_at` / `last_success_at` / `updated_at` едут каждый час).

Поля, которые **нельзя** затирать: `last_post_id`, `backfill_completed_at`, `last_attempt_at`, `last_success_at`, `fail_count`, `last_error`, `rate_limit_until`, `comments_unavailable`, `history_from`, `history_to`, `poll_interval_seconds`, `channel_username`, `owner_id`, `created_at`.

Намеренно могут измениться: `updated_at` (хелпер не копирует его — `Source.__init__` ставит `now()`; upsert пишет `excluded.updated_at`); `status` (если был не `active` — станет `active`; у кандидата уже `active`).

Сильные оракулы на этом канале: `last_post_id` и `rate_limit_until` (исторический, в прошлом). `backfill_completed_at` уже NULL — слабый оракул. `include_comments=false` / `batch_size=100` совпадают со старыми дефолтами инструмента: клиент, который подставит `false`/`100`, на этих двух полях даст ложный зелёный; курсор и `rate_limit_until` всё равно поймают полный upsert.

### 3.2 Выбор канала — `medportal_rfed`, не оба

| Кандидат | Почему да / нет |
|---|---|
| **`medportal_rfed`** (брать) | Референс BUG-093; уже в runbook R9; `last_post_id=123` — короткая история. Если фикс врёт, re-fetch ≈ сотни постов, не ~11k. Owner = admin `c59d42b4`. Тик 07:30 был incremental |
| `mediamedics` | Тот же owner и те же настройки, но цепочка BUG-094 прямо называет его как ~11k сообщений вхолостую. Не трогать, пока не выбран первый |

Не второй канал «для уверенности». Не канал в середине чужого тика.

### 3.3 GO, затем один вызов

До GO — стоп. После GO:

1. `whoami` на том же MCP, которым будешь писать. Ожидание: `role=admin`, id = `owner_id` строки (`c59d42b4-…`). Не вызывать чужим user-токеном.
2. Поверхность: **MCP `add_channel`**. Предпочтительный способ — уже подключённый прод-MCP владельца (`user-tg-parser` / project `tg-parser`): это тот же путь, которым owner и меняет каналы. Снимок — SQL выше (как в R9/R10/R11 runbooks). Bot не нужен.
3. Аргумент **только** `channel_id="medportal_rfed"`. Не передавать `include_comments`, `batch_size`, `channel_username` — иначе это не проверка «опущенное ≠ дефолт». Не повторять форму BUG-093 (`include_comments=True`, `batch_size=500`).
4. Если клиент в транскрипте всё же отправил `false`/`100` (ловушка FastMCP из стартового промпта фикса) — скажи вслух. Курсор всё равно оракул; на оси настроек этот канал слабый. Не выдумывать второй вызов с другими полями.
5. Не ходить в `tg_parser` контейнер за `add_channel`: там образ R2, хелпера нет. In-process fallback только в `tg_parser_mcp`, интерпретатор `docker exec -w / tg_parser_mcp /opt/venv/bin/python3` (урок BUG-092). Предпочесть живой MCP, не собирать ctx руками.

Ожидание ответа: `created=false`, сообщение «updated» / `Channel 'medportal_rfed' updated (status=active).` — ок.

### 3.4 Сверка после

Тот же SELECT. Сравни все колонки §3.1.

- Курсор или служебные съехали → **СТОП**. Не чинить app-code на проде. Откат = SQL из снимка «до» (шаблон §3.5). Запиши факт в runbook/BUG-094, статус `resolved` не трогай.
- Строка совпала (кроме `updated_at`) → успех.

### 3.5 Rollback (заполнить из снимка «до», не из этой подготовки)

Шаблон. Значения — **с твоего** SELECT до вызова. Пример с 08:13 UTC (к сессии устареет):

```sql
UPDATE sources SET
  last_post_id = '123',
  backfill_completed_at = NULL,
  last_attempt_at = '2026-08-15T07:30:32Z',
  last_success_at = '2026-08-15T07:30:32Z',
  fail_count = 0,
  last_error = NULL,
  rate_limit_until = '2026-07-15T11:21:43Z',
  comments_unavailable = false,
  history_from = NULL,
  history_to = NULL,
  poll_interval_seconds = NULL,
  channel_username = NULL,
  include_comments = false,
  batch_size = 100,
  status = 'active',
  owner_id = 'c59d42b4-8e05-42a7-be7e-50e9d1f4b951',
  created_at = '2026-06-25T10:39:35Z'
WHERE source_id = 'medportal_rfed';
```

Одной строкой: восстановить `last_post_id` и остальные служебные из снимка `UPDATE sources SET … WHERE source_id='medportal_rfed'`. `updated_at` откатывать не обязательно. Не recreate контейнеров как «откат smoke».

### 3.6 Тик — optional follow-up

После зелёной сверки строки: если следующий incremental близко — дождись и убедись, что по `medportal_rfed` снова `mode=incremental`, не полный re-fetch, `last_post_id` не ушёл в NULL. Если тик далеко — сверки строки достаточно; тик записать как optional follow-up, сессию не блокировать. Не `trigger_pipeline`.

### 3.7 Запись

- [`BUG094_R9_DEPLOY.md`](../runbooks/BUG094_R9_DEPLOY.md) — факт smoke (до/после, SHA, образ, `created=false`). Не дублировать этот промпт целиком.
- [BUG-094](BUG_LOG.md) **Artifacts** — живой owner-вызов, курсор жив. Статус оставить `resolved`.
- [`TEST_ACCESS_MULTI_USER.md`](../runbooks/TEST_ACCESS_MULTI_USER.md) §6 — снять «открыт» / workaround, если smoke зелёный.
- Коммит этих docs — только по запросу владельца в той сессии.

### 3.8 Что не ломать / вне scope

- **R4 / BUG-096** — не начинать, даже если GO на smoke откладывают.
- **Bot-арм BUG-099** — `get_default_admin()` в исполнителях. Строку видеть и не трогать.
- Recreate `tg_parser` (сдвигает hourly tick). Recreate mcp/bot «на всякий случай».
- Второй канал. Чужой user-токен. Вызов с `include_comments` / `batch_size` / `channel_username`.
- App-code, `docs/methodology/**`, `pyproject.toml`, `requirements.txt`.
- Вариант (b) `update_channel`. Частичный SQL в `upsert_source`.

---

## 4. Acceptance criteria

1. До GO — только doctor, SHA, образы, тик, SELECT. Записи в `sources` нет.
2. После GO — один owner-MCP `add_channel("medportal_rfed")` без лишних полей. `created=false`.
3. Строка байт-в-байт с снимком «до», кроме `updated_at` (и `status`, если бы не был `active`).
4. Если курсор съехал — rollback SQL выполнен, сессия остановлена, фикс на проде не изобретался.
5. Runbook + BUG-094 Artifacts обновлены фактом. Статус BUG-094 остался `resolved`.
6. R4 не начата. Контейнеры не recreate.

---

## 5. Ограничения (CRITICAL)

- Прод-запись только после явного GO владельца в том чате. До GO — только чтения и снимок.
- Не recreate `tg_parser`. Не recreate mcp/bot «на всякий случай».
- Не вызывать `add_channel` с `include_comments` / `batch_size`, даже «как в BUG-093 smoke» — тот вызов был бы деструктивным до фикса и не проверяет «опущено».
- Не чинить bot-арм BUG-099.
- Не трогать `docs/methodology/**`, `pyproject.toml`, `requirements.txt`.
- Не начинать R4 в этой сессии.
- Коммит протокола smoke — по запросу владельца в той сессии.
- Песочница: ssh/prod только с `required_permissions: ["all"]`.
- Ноль правок app-code.

---

## 6. Финальный ответ сессии

Одним сообщением: какой канал и почему; SHA/образы на входе; снимок «до» (хотя бы `last_post_id`, `rate_limit_until`, `last_attempt_at`, `owner_id`); был ли GO; ответ `add_channel` (`created`, message); сверка «после» — что совпало, что уехало только в `updated_at`; откат — выполнен или не понадобился; тик — дождались или optional follow-up; что записано в runbook / BUG-094. Отдельной строкой: что осталось вне сессии — bot-арм BUG-099 и R4 (BUG-096).

---

## 7. Ссылки

- [BUG-094](BUG_LOG.md) — частичный `Source` × full-row upsert; R9 задеплоена; этот smoke — хвост.
- [BUG-093](BUG_LOG.md) — ownership на той же ветке; образец прод-smoke (чужой токен, не копировать аргументы).
- [ADR-0009](../adr/0009-idempotency.md) — `add_channel` идемпотентен, reanimates soft-deleted.
- [`BUG094_R9_DEPLOY.md`](../runbooks/BUG094_R9_DEPLOY.md) — деплой + read-only smoke.
- [`START_PROMPT_FIX_BUG094_ADD_CHANNEL_PARTIAL_UPDATE_R9_2026-08-14.md`](START_PROMPT_FIX_BUG094_ADD_CHANNEL_PARTIAL_UPDATE_R9_2026-08-14.md) — код-сессия; не переписывать.
- [`PLAN_REMEDIATION_BOT_MCP_2026-08-12.md`](PLAN_REMEDIATION_BOT_MCP_2026-08-12.md) §R9, §4.
- [`TEST_ACCESS_MULTI_USER.md`](../runbooks/TEST_ACCESS_MULTI_USER.md) §6.
- `tg_parser/storage/source_overlay.py` — `source_for_add_channel`.
- `tg_parser/mcp_server.py` — `add_channel` (defaults `None` / `None`).
- `tg_parser/storage/sqlalchemy/ingestion_state_repo.py` — `upsert_source` (полный ряд, не менять).
