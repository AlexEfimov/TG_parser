@AGENTS.md

# Claude Code — поправки к AGENTS.md

`AGENTS.md` — общий файл для всех агентов (Claude Code, Codex, Cursor). Ниже — то, что для Claude Code читается иначе. При расхождении для Claude Code действует этот файл.

## Что в AGENTS.md относится только к Cursor

- **Песочница, `required_permissions: ["all"]`, `block_until_ms`, Cursor Cloud, «Move to Cloud»** — механика Cursor. У Claude Code песочницы нет: `ssh prod`, `gh`, `docker compose` выполняются напрямую, но через подтверждение владельца (правила в `.claude/settings.json`). Ложный `MISS ssh prod` из песочницы Cursor здесь не возникает: если `dev_doctor.sh` пишет `MISS`, это настоящая проблема.
- **Отдельные окна / инстансы Cursor на сессию** — здесь это отдельная сессия Claude Code (при параллельной работе — в своём worktree). Self-review «агентом со свежим контекстом» — субагент.
- **Bugbot** остаётся: он ревьюит PR на GitHub независимо от того, кто их создал. Цикл — skill `/bugbot-loop`.

## Режим работы

- Только локально на Mac (`AGENTS.md` → «Режим работы»): PR standard требует живого Postgres.
- Для вопросов о структуре кода — `.claude/rules/graphify.md`.

## Прод

- Каналы — только `ssh prod` (репозиторий на хосте — `/home/user/TG_parser`) и прод-MCP `tg-parser`. Одна прод-команда — один вызов, целиком видимый в карточке; remote-команда — в одинарных кавычках; чтение и запись в одной команде не смешивать.
- Чего нет в списке чтения ниже — до вызова объяснить в тексте, почему это чтение, и дождаться ответа владельца. Карточка `ssh` вопросом не считается.
- **До GO — только чтение:**
  - внутри remote-команды — только двойные кавычки: одинарная закрывает внешнюю;
  - git на хосте: `rev-parse`, `log`; `status` и `diff` — только `git --no-optional-locks …` или `git diff <A> <B>` между коммитами; без `fetch`/`pull`, `--output`, `--ext-diff`, `--no-index`;
  - docker и хост: `ps`, `images`, `stats --no-stream` (мгновенное значение), `logs` с `--since`/`--tail` и `2>&1` перед `| grep` (`tg_parser_mcp` и `tg_parser_bot` пишут в stderr), `uptime`, `free -m`; `inspect` — только с `--format` по нужным полям;
  - окружение контейнера — только с фильтром по началу имени: `ssh prod 'docker exec tg_parser env | grep "^TOPICIZATION_"'`; фильтр не должен захватывать `*_KEY`, `*_TOKEN`, `*PASSWORD*`, `*SECRET*`. Секреты печатают: `env`/`printenv` без фильтра, `inspect` без `--format` или с `.Config.Env` без фильтра, `docker compose config`, `/proc/*/environ`;
  - метрики — `docker exec tg_parser_prometheus wget -qO- "http://localhost:9090/api/v1/query?query=<PromQL в URL-кодировке>"`, только GET: без `--post-data`, `/-/reload` и admin API. busybox wget сам ничего не кодирует;
  - `.env` на хосте — только имена ключей (`grep -o "^[A-Z0-9_]*=" /home/user/TG_parser/.env`), значения не читать и не печатать;
  - прод-MCP: read-инструменты из `allow` в `.claude/settings.json`. `search_knowledge_base` (платный запрос embeddings) и `ask_question` (тратит LLM) — тоже чтение, но через карточку. `get_export_status` — не чтение: первый вызов в процессе MCP выполняет `CREATE TABLE/INDEX IF NOT EXISTS` для `api_jobs`, поэтому только по GO, как `export_channel`.
- **SQL до GO** — только по шаблону: `ssh prod 'docker exec -e PGOPTIONS="-c default_transaction_read_only=on -c statement_timeout=120s" tg_parser_postgres psql -X -e -v ON_ERROR_STOP=1 -U tg_parser_user -d tg_parser -c "<запрос>"'`. `PGOPTIONS` передаётся через `docker exec -e`: заданная на хосте переменная в контейнер не попадает, и сессия молча остаётся на запись.
  - Каждый вызов — новая сессия БД. Первым вызовом в рабочей сессии — `SHOW default_transaction_read_only`, ответ `on`: проверка шаблона.
  - Один `-c`, в нём одна инструкция `SELECT` / `WITH` / `EXPLAIN` / `SHOW`. Без `-f`, stdin, heredoc, `-o`, `-L`.
  - Кавычки: вся команда — в одинарных кавычках локального shell, запрос — в двойных кавычках удалённого. Одинарная кавычка строкового литерала SQL пишется как `'\''`: `-c "SELECT count(*) FROM processed_documents WHERE channel_id = '\''andre_dataist'\''"`. `-e` печатает запрос в том виде, в каком он дошёл до сервера, — сверить с задуманным.
  - Внутри двойных кавычек удалённый shell раскрывает `$`, обратную кавычку и `\`: `$$…$$` превращается в PID процесса, поэтому dollar-quoting не использовать, `$` в литералах (например, в регулярках) писать как `\$`, двойную кавычку в запросе — как `\"`. Обходить кавычки через stdin или heredoc нельзя.
  - `tg_parser_user` — суперпользователь (`POSTGRES_USER` в compose), а read-only транзакция не мешает ни shell, ни файлам сервера, ни управлению сервером. Поэтому:
    - запрещены вызовы функций с префиксами `pg_`, `lo_`, `dblink`, а также `set_config` и `current_setting` (например, `pg_read_file`, `pg_terminate_backend`, `pg_advisory_lock`);
    - обычные функции данных разрешены: агрегаты, строки, даты, математика, `json`/`jsonb`;
    - системные представления (`pg_stat_user_tables`, `pg_class` и т. п.) читать можно, кроме `pg_authid`, `pg_shadow`, `pg_user_mappings`;
    - не выбирать секреты приложения: `api_jobs.webhook_secret` (открытым текстом).
  - В psql запрещены и в такой сессии:
    - `COPY` в любой форме (`TO/FROM PROGRAM`, `TO '<файл>'`);
    - снятие read-only: `SET` / `RESET`, `BEGIN` / `START TRANSACTION READ WRITE`, `SET SESSION CHARACTERISTICS`;
    - `CREATE` / `ALTER` / `SET ROLE`;
    - метакоманды psql (`\!`, `\o`, `\g`, `\w`, `\copy`, `\gexec`, `\i` и прочие).
- **Скрипт на проде до GO** (симуляция и т. п.) — только если выполнены все условия:
  - скрипт закоммичен на ветке задачи, и на этом SHA пройдены `code-reviewer` и `/gpt-review`;
  - нет внешних вызовов (LLM, эмбеддинги, Telegram) — в окружении `tg_parser` лежат ключи; вывод — только в stdout;
  - read-only включает сам скрипт: `connect_args={"server_settings": {"default_transaction_read_only": "on"}}` при создании движка. Драйвер приложения (asyncpg) `PGOPTIONS` не читает. На старте скрипт печатает `SHOW default_transaction_read_only`, без `on` прогон не засчитывается;
  - сначала один средний канал с замером нагрузки, потом остальные. Память: у `tg_parser` в compose нет лимита, `timeout` её не ограничивает, и OOM ударит по всему хосту. `docker stats --no-stream` даёт мгновенное значение — снимать несколько раз во время прогона;
  - запуск — между тиками. Тик раз в час, фаза — от последнего старта контейнера; сверить по `ssh prod 'docker logs --since 2h tg_parser 2>&1 | grep -F "Incremental pipeline completed"'`.

  Без GO разрешены ровно четыре действия, только в `/tmp` контейнера `tg_parser`:
  1. доставка из коммита, без файла на хосте: `git archive <SHA>:scripts <файл> | ssh prod 'docker cp - tg_parser:/tmp/'`;
  2. сверка: `git show <SHA>:scripts/<файл> | shasum -a 256` против `ssh prod 'docker exec tg_parser sha256sum /tmp/<файл>'`;
  3. запуск: `ssh prod 'docker exec tg_parser timeout … nice python -B /tmp/<файл>'` (`-B` — иначе импорт пишет `__pycache__` в `/opt/venv`);
  4. удаление копии: `ssh prod 'docker exec tg_parser rm -f /tmp/<файл>'`.

  Если скрипту нужен изменённый продуктовый код, которого нет в образе, — стоп и вопрос владельцу.
- **Только по явному GO, одно GO — одно названное действие:**
  - деплой (`pull`, build, recreate) и рестарты;
  - любые записи в БД;
  - write-инструменты прод-MCP, в т. ч. `export_channel`;
  - бэкап и восстановление;
  - любые изменения файлов на хосте;
  - `docker exec` с записью.
- Отклонённую команду (карточка «No», deny-правило) не обходить другой формой: остановиться и спросить.

## Как вести задачу

- Старт: прочитать START_PROMPT задачи → `bash scripts/dev_doctor.sh` (первая команда любой сессии) → сверка «состояния на входе» из промпта. Расхождение — сказать вслух, не чинить исчезнувшее.
- Работа — этапами из START_PROMPT, каждый этап начинается в plan mode. План до показа владельцу проверяет субагент со свежим контекстом (сверка с START_PROMPT и этим файлом); замечания вносятся в план.
- Точка решения владельца из START_PROMPT — остановка: варианты и данные владельцу, дальше — только после ответа. Принятое решение записывается в документ задачи (заметка, протокол, PR), а не только в чат.
- Дальше — «Гейты перед push / merge».

## Ветки и коммиты

- Имя ветки: `claude/<type>-<id>-<slug>`, например `claude/fix-bug105-supporting-noise`, `claude/docs-r16-deploy`. Типы — как в истории: `fix`, `docs`, `feat`, `chore`, `test`. Старые ветки `cursor/…` не переименовывать.
- Commit — только по явной просьбе владельца (`AGENTS.md` → Forbidden actions). Трейлер `Co-Authored-By: Claude …` оставлять.
- PR создаётся черновиком (`gh pr create --draft`), в ready — после всех локальных гейтов (см. ниже), чтобы Bugbot отработал один раз.

## Гейты перед push / merge

Порядок: правка → ЗК → commit (по просьбе владельца) → `code-reviewer` и `/gpt-review` на закоммиченном head SHA → push → PR → `/bugbot-loop`. Ревью идёт только по закоммиченному: `/gpt-review` клонирует SHA и при незакоммиченных изменениях останавливается. Правка после ревью — новый commit и новый круг ревью на новом SHA; push — только когда на текущем head получены вердикты всех нужных ревью: `code-reviewer` и `/gpt-review` — по условиям из их описаний (состав diff).

1. До commit — ЗК из `docs/notes/WORKFLOW_REMEDIATION_SESSIONS_AGREEMENTS_2026-07-07.md` §5 п. 8: `ruff check .`, `ruff format --check .`, тесты в режиме по `tests/README.md` (для app-code — PR standard `TEST_POSTGRES=1` с фиктивными ключами).
2. Субагент `code-reviewer` — когда diff затрагивает пути из его описания. Промпт вызова: «Требования:», «Base/Head:», «Отчёт исполнителя:».
3. `/gpt-review` — когда diff затрагивает пути из описания `code-reviewer` (или по просьбе владельца): тот же ревью-контракт на модели OpenAI через Codex CLI, ради вердикта, не коррелированного с Claude.
4. `/bugbot-loop` — после `gh pr ready`.

## MCP

- `tg-parser` — прод (`https://mcp.tgp.efimov.mobi/mcp`), `tg-parser-local` — локальный dev-инстанс (stdio). Имена разные намеренно: раньше оба назывались `tg-parser`, и локальный перекрывал прод.
- Write-инструменты обоих серверов (`trigger_*`, `set_llm_config`, `add_channel`, `force_resummarize` и т. п.) требуют подтверждения.
