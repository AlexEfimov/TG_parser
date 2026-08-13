# AGENTS.md — TG_parser project workspace

**Scope:** этот workspace — основная разработка проекта TG_parser. Code, tests, docs (кроме методологии), runbooks, ADR, contracts.

**Методология стандарта живёт в отдельном worktree** — `/Users/alexanderefimov/TG_parser-methodology` (ветка `methodology`). Не редактировать `docs/methodology/` отсюда — папка отсутствует на `main` намеренно.

**Branch:** `main`.

**Если задача касается методологии (структура документации, шаблоны, конвенции, agent-contracts):** переключиться в methodology workspace в отдельном Cursor-окне. Не предлагать правки `docs/methodology/**` из этого workspace.

**Project conventions (нормативно):**
- [`docs/adr/`](docs/adr/) — accepted ADR обязательны.
- [`docs/contracts/`](docs/contracts/) — JSON Schema нарушать нельзя.
- [`docs/quality/AGENT_PLAYBOOK.md`](docs/quality/AGENT_PLAYBOOK.md) — quality lifecycle.
- [`docs/notes/agents-roles.md`](docs/notes/agents-roles.md) — базовые роли.
- [`docs/notes/BUG_LOG.md`](docs/notes/BUG_LOG.md) — backbone fix-сессий.
- [`tests/README.md`](tests/README.md) — режимы pytest (default / PR / max local).

**Forbidden actions:**
- `git commit` без явного запроса пользователя.
- Создание `docs/methodology/**` в этом workspace.
- Прямые правки `pyproject.toml`, `requirements.txt` без явного запроса.

**Living document:** растёт по реальной нужде, не наугад.

### Режим работы: основной — This Mac

**Решение 2026-08-13:** интерактивная разработка ведётся локально (`Continue on: This Mac`). Облако используется точечно — для задач с чётким контрактом «репозиторий на входе, PR на выходе» и для automations по расписанию (сейчас обе выключены).

Причина в верификации, а не во вкусе: обязательный по [`tests/README.md`](tests/README.md) режим PR standard требует живого Postgres, а `.cursor/environment.json` его не поднимает и docker в облачной VM отсутствует. Пока в CI нет job'а с `TEST_POSTGRES=1`, около 500 тестов проверяются **только** локально — и именно они обязательны для app-code (bot / MCP / API / repos).

**Только локально, в облаке недостижимо:**

- Полный прогон `TEST_POSTGRES=1` и `TEST_TESTCONTAINERS=1` (нужны Postgres и Docker).
- Живой smoke с реальной доставкой в Telegram.
- Методология: worktree `/Users/alexanderefimov/TG_parser-methodology` вне репозитория.
- MCP-серверы, привязанные к машине: локальный dev-инстанс `tg-parser` и Sourcegraph (интерактивный OAuth).

**Обратный переход бесплатный.** Ничего из облачной обвязки не удалено и удалять не надо: `.cursor/environment.json`, [`scripts/cursor_cloud_setup_prod_ssh.sh`](scripts/cursor_cloud_setup_prod_ssh.sh) и секрет `PROD_SSH_PRIVATE_KEY` в дашборде остаются. Единственное требование при переключении в облако — закоммитить локальные правки: «Move to Cloud» переносит историю разговора, но не грязные файлы.

### Песочница: чем отличается «нет доступа» от «не пустили»

Команды агента по умолчанию идут в песочнице, и **все внешние каналы из неё не работают**: `ssh prod`, скрейп прод-Prometheus, прод-MCP, `gh`. Это не отсутствие доступа, а отсутствие разрешения — доступ есть, и он настроен:

- **`ssh prod`** (алиас `tg-parser-prod`) прописан в `~/.ssh/config`, репозиторий на хосте — `/home/user/TG_parser`. Работает при `required_permissions: ["all"]`. **Ловушка, стоившая сессии:** `dev_doctor.sh` пробует коннект изнутри песочницы, поэтому в агентском ране печатает `MISS ssh prod` с подсказкой «check host 'prod' in ~/.ssh/config» — подсказка ведёт не туда, хост на месте. Тот же артефакт у строки про прод-MCP. В терминале у человека тот же скрипт печатает `OK`.
- **`gh`** требует `full_network` **и** живого токена. Keyring macOS «протухает» через 10–30 минут после `gh auth login` (зафиксировано ещё в [`HANDOFF_POST_WAVE1_STEP2_2026-05-15.md`](docs/notes/HANDOFF_POST_WAVE1_STEP2_2026-05-15.md)), и тогда `gh` отвечает `HTTP 401: Bad credentials`. Устойчивый обход — положить PAT в `~/.config/gh/hosts.yml` как `oauth_token` (`chmod 600`); эффект тот же, что у `gh auth login`, но не зависит от keychain. Без токена PR создаётся вручную по ссылке `https://github.com/AlexEfimov/TG_parser/pull/new/<branch>` — `git push` для этого достаточно.

Правило простое: прежде чем записать «недоступно», перепроверить с поднятыми правами. Ложный `MISS` уже один раз уехал в план как ограничение очереди.

**Первый шаг сессии в любом режиме:** `bash scripts/dev_doctor.sh`. Скрипт сам определяет режим и печатает, что доступно, а что нет — Postgres и ключи для PR standard, граф graphify, `ssh prod`, MCP-эндпоинты — и отдельно перечисляет то, что в текущем режиме недоступно по замыслу. Смысл в том, чтобы переключение режима падало здесь, громко, а не посреди задачи.

**Инструментарий локального режима:**

- `bash scripts/graphify_bootstrap.sh` — ставит graphify и строит граф кода (~7 с, без LLM и ключей). Границы корпуса — в `.graphifyignore`; результат в `graphify-out/`, он git-ignored и пересобирается, а не коммитится. Когда графом стоит пользоваться вместо grep — в [`.cursor/rules/graphify.mdc`](.cursor/rules/graphify.mdc).
- Правила в `.cursor/rules/` — единственная агентская конфигурация, которая доезжает до **обоих** режимов; всё в `~/.cursor` остаётся на машине. Поэтому `.gitignore` держит этот каталог отслеживаемым, а `mcp.json` — намеренно нет (в нём ключи).

### Cursor Cloud specific instructions

- Runtime Secret required: `PROD_SSH_PRIVATE_KEY` (OpenSSH private key for prod).
- Before any `ssh prod` / Prometheus scrape: run `bash scripts/cursor_cloud_setup_prod_ssh.sh` (also wired via `.cursor/environment.json` install/start).
- Details: [`docs/runbooks/CURSOR_CLOUD_PROD_SSH.md`](docs/runbooks/CURSOR_CLOUD_PROD_SSH.md).
- MCP-серверы облачного рана приходят из дашборда (MCP dropdown на cursor.com/agents), а не из репозитория и не с Mac: `.cursor/mcp.json` в облако не едет. Имена серверов держать одинаковыми в обоих режимах, иначе промпты и automations начинают зависеть от режима.
