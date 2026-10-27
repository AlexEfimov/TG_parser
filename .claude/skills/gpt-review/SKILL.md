---
name: gpt-review
description: Независимое ревью diff сессии TG_parser моделью OpenAI через Codex CLI по тому же контракту, что у субагента code-reviewer. Вызывать после commit и code-reviewer на закоммиченном head SHA, перед push/merge, когда diff затрагивает пути из описания code-reviewer, или когда владелец просит «GPT-ревью».
---

# /gpt-review — второе мнение не из семейства Claude

Зачем: в Cursor `code-reviewer` работал на GPT, чтобы его вердикт не коррелировал с исполнителем. В Claude Code субагенты бывают только на Claude, поэтому межвендорную независимость возвращает этот skill: тот же промпт ревьюера уходит в `codex exec` (вход по подписке ChatGPT).

## Предусловия (проверить, не предполагать)

1. `codex --version` — CLI установлен. Если нет — остановиться и сказать владельцу (`npm i -g @openai/codex` или `brew install codex`), не ставить самому.
2. Codex залогинен подпиской ChatGPT, а не API-ключом (`codex login status`). Если в окружении задан `OPENAI_API_KEY` или `CODEX_API_KEY` — остановиться и сообщить владельцу; `CODEX_API_KEY` действует именно на `codex exec`. Проверять только факт SET/unset, значения не печатать:
   ```bash
   for v in OPENAI_API_KEY CODEX_API_KEY; do printenv "$v" >/dev/null && echo "$v: SET" || echo "$v: unset"; done
   ```
3. Флаги шага «Запустить» проверены на `codex-cli 0.162.1`. Если `codex --version` показывает другую версию — сверить флаги с `codex exec --help`; при расхождении остановиться и сообщить владельцу, а не подбирать флаги самому.
4. `test -x /Library/Developer/CommandLineTools/usr/bin/git` — git из Command Line Tools на месте (на него указывает `PATH` запуска). Если нет — остановиться и сообщить владельцу.
5. `git status --porcelain` пуст — ревьюится только закоммиченное (запуск идёт на чистом клоне `HEAD`). Есть незакоммиченные правки — остановиться: сначала коммит по просьбе владельца, потом `/gpt-review`.

## Шаги

1. **Собрать три блока** — те же, что для `code-reviewer`:
   - «Требования:» — путь к START_PROMPT / PLAN / записи BUG_LOG или текст;
   - «Base/Head:» — только полные SHA, вычисленные в рабочем репо до запуска: base — `git merge-base origin/main HEAD`, head — `git rev-parse HEAD`. Вариант «uncommitted» не допускается (см. п. 5 предусловий). Имена ref (`origin/main`, `main`) не передавать: в клоне remote удалён, и они там не разрешаются;
   - «Отчёт исполнителя:» — что сделано, какие проверки и с каким результатом.
2. **Собрать промпт во временный файл вне репозитория** (иначе изменится отпечаток неотслеживаемых файлов, к которому ревьюер привязывает вердикт):
   ```bash
   SHA=$(git rev-parse --short HEAD)
   P=/tmp/gpt-review-$SHA.prompt.md
   {
     sed '1,/^---$/d' .claude/agents/code-reviewer.md   # тело без frontmatter
     cat <<'NOTE'

   ## Особенности этого запуска
   - Ты — Codex (модель OpenAI), запущен владельцем как второй независимый рецензент. Ты работаешь в чистом клоне закоммиченного head: `.venv` в нём нет (не отслеживается), `origin/main` и `main` не разрешаются (remote удалён) — base и head бери только полными SHA из блока «Base/Head»; сети до Postgres и записи тоже нет. Команды `.venv/bin/...` и PR standard поэтому недоступны — пункт «Не удалось проверить»; прогон PR standard в этом случае подтверждает Claude-ревьюер, а от тебя нужен вердикт по логике, регрессиям, безопасности и тестам по чтению кода. Для рискованного изменения без собственного прогона PASS по-прежнему невозможен — это ожидаемо.
   - Никаких изменений файлов и состояния git.
   NOTE
     printf '\n---\n\nТребования:\n%s\n\nBase/Head:\n%s\n\nОтчёт исполнителя:\n%s\n' "$REQ" "$BASEHEAD" "$REPORT"
   } > "$P"
   ```
3. **Запустить** (флаги — по п. 3 предусловий) — блок ниже дословно. Вердикт Codex пишется через `-o` в `/tmp/gpt-review-$SHA.out.md`, лог прогона — в `/tmp/gpt-review-$SHA.log`. Оба файла удаляются перед запуском, а блок последней строкой печатает `CODEX_EXIT=<код выхода codex exec>` — так вердикт от прошлого прогона того же SHA не примешь за текущий. Это может занять несколько минут — Bash с `timeout: 600000` или в фоне с ожиданием.

```bash
ROOT="$(git rev-parse --show-toplevel)"
R="/tmp/gpt-review-$SHA"
OUT="/tmp/gpt-review-$SHA.out.md"
LOG="/tmp/gpt-review-$SHA.log"
rm -rf "$R"
rm -f "$OUT" "$LOG"
git clone -q "$ROOT" "$R"
git -C "$R" checkout -q --detach "$SHA"
git -C "$R" remote remove origin
codex exec --ignore-user-config --ignore-rules --ephemeral \
  --disable apps --disable plugins --disable remote_plugin --disable memories --disable hooks \
  --disable computer_use --disable browser_use --disable browser_use_external --disable browser_use_full_cdp_access \
  --disable in_app_browser --disable image_generation --disable multi_agent \
  --disable skill_mcp_dependency_install --disable tool_suggest \
  -c web_search='"disabled"' \
  -c default_permissions='"gpt-review"' \
  -c 'permissions.gpt-review={filesystem={":minimal"="read", "/Library/Developer/CommandLineTools"="read", ":workspace_roots"={"."="read", ".env"="deny", "**/*.env"="deny", "**/*.session*"="deny", "**/*.sqlite*"="deny", "**/*.log"="deny", "**/*.ndjson"="deny"}}}' \
  -c 'shell_environment_policy.inherit="core"' \
  -c 'shell_environment_policy.set={PATH="/Library/Developer/CommandLineTools/usr/bin:/usr/bin:/bin:/usr/sbin:/sbin", GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1"}' \
  -m gpt-6.1-sol -c model_reasoning_effort='"high"' \
  -C "$R" -o "$OUT" - < "$P" > "$LOG" 2>&1
RC=$?
rm -rf "$R"
echo "CODEX_EXIT=$RC"
```

**Почему так и что запрещено:**

- Ревьюится закоммиченный `$SHA` на чистом клоне в `/tmp`. В клоне только отслеживаемые файлы. Живой репо (секреты окружения, файлы сессий Telegram, локальные БД, выгрузки, логи) лежит вне workspace профиля `gpt-review` и недоступен. Незакоммиченные правки Codex не видит.
- Профиль `gpt-review`: только чтение — клона (кроме `.env`, `*.env`, `*.session*`, `*.sqlite*`, `*.log`, `*.ndjson`), Command Line Tools и системного минимума `:minimal`; записи нет, сеть для команд Codex выключена. `web_search` и перечисленные `--disable`-возможности Codex выключены.
- `inherit="core"` плюс чистый `PATH`: в команды Codex не попадает окружение пользователя; `git` и `python3` берутся из Command Line Tools, глобальный gitconfig не читается.
- Модель `gpt-6.1-sol`, effort `high` — выбор владельца; менять только по согласованию.
- Запрещено: флаг `--sandbox` в любом виде (он переключает Codex на старую песочницу и отключает профиль, а старая песочница читает весь диск); `--approve-for-me`; любые `--dangerously-*`; `--add-dir`; `--worktree`; `-C` на рабочее дерево репо; убирать `--ignore-user-config`, профиль или `--disable`-флаги; `codex exec review` и интерактивный `codex`.
- Каждый запуск `codex exec` из Claude Code идёт через запрос подтверждения; владелец сверяет флаги в карточке с этим блоком.
- Вердикт принимается только от успешного текущего прогона: `$OUT` и `$LOG` удаляются до запуска, код выхода `codex exec` сохраняется до очистки клона и печатается как `CODEX_EXIT`.

4. **Проверить запуск:** блок напечатал `CODEX_EXIT=0` и `test -s "$OUT"` успешен. Иначе — стоп: показать владельцу код выхода и `tail -n 20` лога, вердикт не читать и не пересказывать. **Затем прочитать вердикт `/tmp/gpt-review-$SHA.out.md` целиком** и показать владельцу: вердикт, привязку к хешу, подтверждённые находки по уровням, «Не удалось проверить».
5. **Разобрать находки.** По каждой Critical/High/Medium — исправить (и заново пройти локальные гейты) или ответить с доказательством, почему это не дефект. Молча не отбрасывать. Если код изменился — вердикт устарел, повторить `code-reviewer` и `/gpt-review`.

## Чего не делать

- Не подменять вердикт Codex своим пересказом — цитировать раздел «Вердикт» и находки.
- Не передавать Codex `.env`, ключи, содержимое `*.session`.
- Не давать Codex права записи никаким способом: флаг `--sandbox` запрещён полностью, профиль только на чтение, `--add-dir` и `--worktree` запрещены — см. раздел «Почему так и что запрещено».
