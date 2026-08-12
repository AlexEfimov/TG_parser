# Тестовый доступ для нескольких пользователей — runbook оператора

**Версия:** 4.4.0 | **Аудитория:** оператор инстанса (admin) | **Проверено:** 2026-08-12 на живом prod-MCP

Как выдать N людям доступ к работающему инстансу TG_parser так, чтобы они подключились сами, ничего не сломали и доступ отзывался одной командой.

Подстановки: `{MCP_URL}` — HTTPS-эндпоинт MCP (`https://mcp.<домен>/mcp`), `{BOT_USERNAME}` — юзернейм бота. Живые значения — в приватных ops-заметках, не в репозитории.

**Короткий путь (MCP-доступ трём тестировщикам):**

```bash
export TGP_MCP_URL="{MCP_URL}"
export TGP_ADMIN_MCP_TOKEN="<ваш admin-токен>"

.venv/bin/python scripts/onboard_test_users.py issue alice bob carol --max-channels 3
```

Скрипт создаёт пользователей, генерирует токены, **сам проверяет вход под каждым новым токеном** и печатает готовые сообщения для отправки. Дальше — детали, границы и уборка.

---

## §0 Как здесь устроен доступ

Доступ — это **две** записи в БД. Одной недостаточно:

| Запись | Чем создаётся | Что даёт |
|---|---|---|
| `users` | `register_user(name, role, max_channels)` | личность: роль, лимит каналов, владение каналами |
| `user_auth_mappings` | `add_user_auth(user_id, auth_type, identifier)` | сам вход: по чему система узнаёт пользователя |

Пользователь без mapping'а существует и ничего не может — он не аутентифицируется ни на одной поверхности. Это самая частая ошибка онбординга: `register_user` прошёл, человеку сказали «готово», а подключиться нечем.

Три типа входа, независимые друг от друга:

| `auth_type` | Поверхность | `identifier` | Как проверяется |
|---|---|---|---|
| `mcp_token` | MCP (Cursor, Claude, любой MCP-клиент) | случайный токен, в БД лежит `sha256` | `Authorization: Bearer <токен>` |
| `telegram` | Telegram-бот | числовой Telegram user id (не юзернейм) | id отправителя сообщения |
| `api_key` | HTTP API | ключ, в БД лежит `sha256` | заголовок API-ключа |

Сырой токен нигде не хранится — ни в БД, ни (по умолчанию) в ledger'е скрипта. Потерян — выдавайте новый, восстановить нельзя.

**Никогда не выдавайте тестировщику токен из `MCP_AUTH_TOKENS`.** Это статический fallback-маппинг уровня `.env`; всё, что приходит с таким токеном, работает **от имени админа** (`tg_parser/mcp_server.py::BearerTokenVerifier` → static fallback → default admin). Токены тестировщиков создаются только через `add_user_auth`.

---

## §1 Выберите режим — от него зависит всё остальное

| | **A. MCP-куратор (свои каналы)** | **B. Читатель digest'ов** | **C. Полный доступ к вашей базе** |
|---|---|---|---|
| Кому | тем, кто тестирует продукт целиком: подключение, добавление канала, поиск, Q&A | тем, кому нужен результат, а не интерфейс | тем, кто должен искать по **вашим** 19 каналам |
| Роль | `user`, `max_channels` 1–3 | `user`, `max_channels=0` | `admin` — других вариантов нет |
| Что видит | только свои каналы, свою базу | только присланные сводки | всё, включая write-операции |
| Стоимость LLM | обработка их каналов на ваших ключах | ноль (сводки уже считаются) | ноль дополнительной |
| Риск | ограниченный (см. §6) | нет | **высокий**: может менять LLM-конфиг, удалять каналы, читать чужие данные |
| Инструкция | §§2–5 этого файла | §9 + [`DIGEST_CONSUMER.md`](../guides/DIGEST_CONSUMER.md) | §9, только доверенным людям |

**Ключевое ограничение, которое ломает наивные ожидания:** пользователь с ролью `user` **не может** получить доступ к каналам, которые ему не принадлежат. Шаринга нет: ни на канал, ни на workspace, ни на топик. `owner_id` у канала один. Поэтому «дать пятерым потестировать поиск по моей базе знаний» решается не MCP-доступом, а digest'ами (режим B) — либо ценой выдачи роли `admin` (режим C).

Живой замер (тестовый `user`-токен против prod-инстанса с 19 каналами админа): `list_channels` → `[]`, `list_topics` → `total=0`, `search_knowledge_base("витамин D")` → `[]`, `pause_channel("Docma_ru")` → `No access to channel Docma_ru`. Пусто — это корректная работа изоляции, а не поломка.

---

## §2 Pre-flight (один раз, до первого тестировщика)

```bash
# 1. Сервисы живы
ssh prod 'docker ps --format "table {{.Names}}\t{{.Status}}"'
#    ожидание: tg_parser, tg_parser_mcp, tg_parser_bot, tg_parser_postgres — healthy

# 2. MCP отвечает и требует токен
curl -s -o /dev/null -w '%{http_code}\n' -X POST {MCP_URL} \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"preflight","version":"0"}}}'
#    ожидание: 401 — auth включён. 200 без токена = MCP_AUTH_ENABLED выключен, СТОП.

# 3. Ваш admin-токен действительно админский
.venv/bin/python scripts/onboard_test_users.py verify --token "$TGP_ADMIN_MCP_TOKEN"
#    ожидание: role=admin

# 4. Кто уже есть в системе
.venv/bin/python scripts/onboard_test_users.py users
```

Требования к конфигу прода: `MCP_AUTH_ENABLED=true` **и непустой** `MCP_AUTH_TOKENS` — при пустом маппинге MCP падает на старте с `RuntimeError` (защита от BUG-001b: раньше в этой ветке auth молча отключался).

Отдельно проверьте, что миграция multi-tenancy прошла: `tg-parser migrate-users --dry-run` не должен предлагать миграцию заново.

---

## §3 Выдача доступа (режим A)

### 3.1 Скриптом

```bash
export TGP_MCP_URL="{MCP_URL}"
export TGP_ADMIN_MCP_TOKEN="<admin-токен>"

# репетиция: ничего не создаётся, видно только текст приглашения
.venv/bin/python scripts/onboard_test_users.py issue alice --dry-run

# выдача — можно сразу нескольким
.venv/bin/python scripts/onboard_test_users.py issue alice bob carol \
  --max-channels 3 --bot-username {BOT_USERNAME}
```

Что происходит на каждое имя:

1. генерируется токен (`secrets.token_hex(32)`);
2. `register_user` → `user_id`;
3. `add_user_auth(auth_type="mcp_token")` → `mapping_id` (сервер хеширует токен сам);
4. **`whoami` под новым токеном** — то же самое, что сделает клиент тестировщика; если профиль не совпал, выдача считается неудачной;
5. строка в ledger (`onboarding_ledger.json`, в `.gitignore`);
6. в stdout — готовое сообщение с конфигом для Cursor / командой для Claude Code.

Токен печатается **один раз**. Скопируйте сообщение в личку тестировщику и не оставляйте его в истории терминала: `history -c` либо запуск через `--dry-run`-репетицию + ручное копирование из свежего окна.

Сломавшаяся выдача одного человека не рвёт партию: остальные обрабатываются, в конце печатается список неудач и код возврата 1. Повторный `issue` для того же имени пропускается (в ledger'е есть активная выдача) — нужен второй токен, используйте `--allow-duplicate`.

### 3.2 Вручную (если скрипт недоступен)

Те же четыре шага любым MCP-клиентом от имени админа:

```
register_user(name="alice", role="user", max_channels=3)
→ user_id = "…uuid…"

add_user_auth(user_id="…uuid…", auth_type="mcp_token",
              identifier="<токен из openssl rand -hex 32>",
              client_name="alice-cursor")
→ mapping_id = "…uuid…"   # ЗАПИШИТЕ: без него не отозвать
```

`mapping_id` больше нигде не отдаётся: ни один MCP-tool не перечисляет auth-mapping'и. Потеряли — достаётся только SQL'ем (§7).

---

## §4 Что делает тестировщик

Отправленное сообщение самодостаточно, но полная версия для него — [`docs/guides/MCP_CONNECT.md`](../guides/MCP_CONNECT.md). Порядок:

1. прописать MCP-сервер в клиенте (`~/.cursor/mcp.json` для Cursor, `claude mcp add …` для Claude Code, Settings → Connectors для Claude Desktop);
2. перезапустить клиент, вызвать `whoami` — увидеть своё имя и `role=user`;
3. `add_channel(channel_id="@публичный_канал")`;
4. `get_pipeline_status(channel_id="@…")` — ждать непустой `last_success_at` (5–30 минут на первом проходе; можно ускорить, попросив вас вызвать `trigger_pipeline`);
5. `search_knowledge_base` / `ask_question` по своему каналу.

Что важно сказать заранее, иначе придёт как жалоба:

- **приватные каналы не подключатся** — сбор идёт под Telegram-аккаунтом сервера, а не под их аккаунтом; аккаунт сервера должен быть подписан на канал;
- **сразу после `add_channel` база пуста** — это cold start, а не ошибка;
- **чужие каналы не видны** — включая ваши; пустой ответ на поиск в первые минуты нормален.

---

## §5 Проверка оператором

| Проверка | Команда | Ожидание |
|---|---|---|
| Токен работает | `onboard_test_users.py verify --token <токен>` | `name`, `role=user`, `max_channels` как выдавали |
| Пользователь виден | `onboard_test_users.py users` | новая строка, `owned_channels_count=0` |
| Изоляция чтения | клиентом тестировщика `list_channels` | `[]` (или только их каналы) |
| Изоляция админских tools | `list_users` под их токеном | `success=false`, `Admin access required` |
| Изоляция write'ов | `pause_channel("<ваш канал>")` под их токеном | `No access to channel …` |
| Канал заведён | `get_pipeline_status()` под их токеном | их канал в `sources` |
| Обработка пошла | то же, через 5–30 мин | непустой `last_success_at` |

Замеренный результат такого прогона на живом проде (пробный пользователь, затем отозван) — в описании PR к этому runbook'у.

---

## §6 Границы и риски — прочитать до выдачи

**Деньги.** Каналы тестировщиков ингестятся и обрабатываются LLM'ом **на ваших ключах**: каждый добавленный канал — реальный расход (обработка + топикизация + эмбеддинги, дальше re-summarize на каждом тике). Отсюда `--max-channels 3` по умолчанию и просьба начинать с маленького публичного канала. Держите под наблюдением расход провайдера и дашборды LLM-метрик в Grafana; при неприятном сюрпризе — `pause_channel` на их канале (админ может) либо `update_user(max_channels=0)`.

**Что тестировщик с ролью `user` может сделать вам:**

| Может | Не может |
|---|---|
| завести до `max_channels` своих каналов → расход LLM | увидеть ваши каналы, топики, документы |
| запускать `trigger_pipeline` на **своих** каналах | запускать pipeline на ваших каналах |
| читать `get_llm_config` — какие провайдеры/модели включены (ключей там нет) | `set_llm_config`, `reset_llm_config`, `reload_prompts`, `export_channel`, `force_resummarize`, любые user-management tools |
| подписывать свои каналы на digest / watchlist, писать в свой chat_id | подписаться на ваши `channel_ids` |

**BUG-093 (исправлен в этой ветке, требует деплоя).** До фикса `add_channel` с id **существующего** канала попадал в `upsert_source` в обход проверки владения: чужой токен не получал доступ на чтение (`owner_id` сохранялся), но молча перезаписывал `status`, `include_comments` и `batch_size` вашего канала, а в боте ещё и показывал его текущий статус в preview. Пока прод не обновлён — считайте это причиной не выдавать токены недоверенным людям и держите под рукой `audit_log` (`action='channel.add'`).

**Роль `admin` — это не «расширенный тестировщик».** Админский токен снимает изоляцию целиком: чтение чужих данных, `remove_channel`, `set_llm_config` на весь инстанс, регистрация пользователей. Выдавайте только тем, кому доверили бы SSH.

---

## §7 Отзыв и уборка

```bash
# по имени из ledger'а
.venv/bin/python scripts/onboard_test_users.py revoke alice

# если ledger потерян — по mapping_id
.venv/bin/python scripts/onboard_test_users.py revoke --mapping-id <uuid>
```

`mapping_id` из БД, когда ledger'а нет:

```bash
ssh prod 'docker exec tg_parser_postgres psql -U <DB_USER> -d <DB_NAME> -c "
  SELECT m.id AS mapping_id, u.name, m.auth_type, m.client_name, m.created_at
  FROM user_auth_mappings m JOIN users u ON u.id = m.user_id
  ORDER BY m.created_at;"'
```

Что происходит после отзыва:

- MCP отдаёт **401** `invalid_token` — как на запрос вообще без токена (проверено);
- **кеш резолвера живёт до 60 с** (`tg_parser/auth/resolvers.py::_CACHE_TTL`): если тестировщик только что делал запросы, один-два ещё могут пройти. Отзыв «под ноль» — отозвать и подождать минуту;
- сами каналы тестировщика продолжают ингестится и жечь токены. Отзыв доступа их не останавливает: `pause_channel` или `remove_channel` на каждый их канал — отдельным действием;
- **строку в `users` удалить нечем** — ни MCP, ни бот, ни CLI не умеют удалять пользователей. Аккуратный минимум: `update_user(name="zz-retired-<кто>-<дата>", max_channels=0)`, чтобы `list_users` оставался читаемым. Жёсткое удаление — только SQL (`DELETE FROM user_auth_mappings WHERE user_id=…; DELETE FROM users WHERE id=…;`) и только когда каналов у пользователя нет.

---

## §8 Troubleshooting

| Симптом | Причина | Действие |
|---|---|---|
| `401 invalid_token` на всё | токен неверен/отозван, либо клиент не отправляет заголовок | `verify --token`; проверить `Authorization: Bearer …` в конфиге клиента |
| Инструменты не появились в Cursor | не тот файл конфига / клиент не перезапущен | `~/.cursor/mcp.json` или `.cursor/mcp.json` в проекте, затем reload MCP |
| `Admin access required` | админский tool под токеном тестировщика | так и должно быть |
| Пользователь создан, но войти не может | нет `add_user_auth` | добавить mapping (§3.2) |
| `search`/`ask` пусто | cold start либо чужие каналы | `get_pipeline_status`; ждать `last_success_at` |
| `last_success_at` не появляется | приватный канал / аккаунт сервера не подписан | публичный канал; смотреть `last_error` в статусе |
| `add_channel` отклонён по лимиту | достигнут `max_channels` | `update_user(max_channels=…)` или снять лишний канал |
| Бот: «Вы не зарегистрированы» | нет mapping'а `telegram` | §9 |
| Бот молчит совсем | бот заблокирован пользователем / не запущен контейнер | `/start`; `docker ps` по `tg_parser_bot` |

---

## §9 Другие режимы, коротко

**Бот (режим B private / ручное тестирование бота).** Нужен mapping `telegram` с **числовым** id (узнать: `@userinfobot`). Достаточно:

```
register_user(name="bob", role="user", max_channels=0)
add_user_auth(user_id="…", auth_type="telegram", identifier="<числовой id>")
```

Правку `.env` и рестарт бота это **не** требует: `BOT_ALLOWED_USERS` работает лишь как переключатель «отклонять незарегистрированных» (`UserResolutionMiddleware`), а зарегистрированный в БД пользователь проходит независимо от списка — legacy-`AllowlistMiddleware` в диспетчер не подключён. После этого человек делает `/start`. Дальше — [`BOT_USER.md`](../guides/BOT_USER.md).

**Digest'ы (режим B).** Каналом: бот-администратор с правом Post Messages в канале + `subscribe_digest(target={"kind":"channel", …})`, подписчикам достаточно ссылки. В личку: mapping `telegram` (выше) + `subscribe_digest(target={"kind":"chat","chat_id":<id>})`. Пошагово — [`WAVE1_5_VALIDATOR_ONBOARD.md`](WAVE1_5_VALIDATOR_ONBOARD.md) §§ Track C1/C2.

**HTTP API.** Тот же механизм с `auth_type="api_key"`; тестировщику отдаётся ключ и Swagger — см. [`PRODUCTION_DEPLOYMENT.md`](../../PRODUCTION_DEPLOYMENT.md).

---

## Связанные документы

- [`WAVE1_5_VALIDATOR_ONBOARD.md`](WAVE1_5_VALIDATOR_ONBOARD.md) — программа внешней валидации (треки B/C, шаблоны приглашений, teardown)
- [`docs/guides/MCP_CONNECT.md`](../guides/MCP_CONNECT.md) — инструкция для самого тестировщика
- [`docs/GETTING_STARTED.md`](../GETTING_STARTED.md) — развилка треков для нового пользователя
- [`docs/USER_GUIDE.md`](../USER_GUIDE.md) — multi-tenancy, digest'ы, publish
- [`scripts/onboard_test_users.py`](../../scripts/onboard_test_users.py) — утилита из §3
