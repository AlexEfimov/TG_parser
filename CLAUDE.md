@AGENTS.md

# Claude Code — поправки к AGENTS.md

`AGENTS.md` — общий файл для всех агентов (Claude Code, Codex, Cursor). Ниже — то, что для Claude Code читается иначе. При расхождении для Claude Code действует этот файл.

## Что в AGENTS.md относится только к Cursor

- **Песочница, `required_permissions: ["all"]`, `block_until_ms`, Cursor Cloud, «Move to Cloud»** — механика Cursor. У Claude Code песочницы нет: `ssh prod`, `gh`, `docker compose` выполняются напрямую, но через подтверждение владельца (правила в `.claude/settings.json`). Ложный `MISS ssh prod` из песочницы Cursor здесь не возникает: если `dev_doctor.sh` пишет `MISS`, это настоящая проблема.
- **Отдельные окна / инстансы Cursor на сессию** — здесь это отдельная сессия Claude Code (при параллельной работе — в своём worktree). Self-review «агентом со свежим контекстом» — субагент.
- **Bugbot** остаётся: он ревьюит PR на GitHub независимо от того, кто их создал. Цикл — skill `/bugbot-loop`.

## Режим работы

- Только локально на Mac (`AGENTS.md` → «Режим работы»): PR standard требует живого Postgres.
- Первый шаг сессии: `bash scripts/dev_doctor.sh`.
- Прод — только `ssh prod`; до явного GO владельца — только чтение.
- Для вопросов о структуре кода — `.claude/rules/graphify.md`.

## Ветки и коммиты

- Имя ветки: `claude/<type>-<id>-<slug>`, например `claude/fix-bug105-supporting-noise`, `claude/docs-r16-deploy`. Типы — как в истории: `fix`, `docs`, `feat`, `chore`, `test`. Старые ветки `cursor/…` не переименовывать.
- Commit — только по явной просьбе владельца (`AGENTS.md` → Forbidden actions). Трейлер `Co-Authored-By: Claude …` оставлять.
- PR создаётся черновиком (`gh pr create --draft`), в ready — после всех локальных гейтов (см. ниже), чтобы Bugbot отработал один раз.

## Гейты перед commit / push / merge

1. ЗК из `docs/notes/WORKFLOW_REMEDIATION_SESSIONS_AGREEMENTS_2026-07-07.md` §5 п. 8: `ruff check .`, `ruff format --check .`, тесты в режиме по `tests/README.md` (для app-code — PR standard `TEST_POSTGRES=1` с фиктивными ключами).
2. Субагент `code-reviewer` — когда diff затрагивает пути из его описания. Промпт вызова: «Требования:», «Base/Head:», «Отчёт исполнителя:».
3. `/gpt-review` — тот же ревью-контракт на модели OpenAI через Codex CLI, ради вердикта, не коррелированного с Claude.
4. `/bugbot-loop` — после `gh pr ready`.

## MCP

- `tg-parser` — прод (`https://mcp.tgp.efimov.mobi/mcp`), `tg-parser-local` — локальный dev-инстанс (stdio). Имена разные намеренно: раньше оба назывались `tg-parser`, и локальный перекрывал прод.
- Write-инструменты обоих серверов (`trigger_*`, `set_llm_config`, `add_channel`, `force_resummarize` и т. п.) требуют подтверждения.
