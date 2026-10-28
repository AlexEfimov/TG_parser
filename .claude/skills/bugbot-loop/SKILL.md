---
name: bugbot-loop
description: Провести PR TG_parser через Cursor Bugbot — перевести черновик в ready, дождаться check `Cursor Bugbot` на head SHA, разобрать находки и треды, при необходимости перезапустить и проверить гейт перед merge. Вызывать, когда локальные гейты пройдены на закоммиченном head (ЗК; code-reviewer и /gpt-review — по условиям из их описаний) и PR-черновик создан.
---

# /bugbot-loop — Bugbot как третья линия ревью

Bugbot — GitHub-ревьюер Cursor. Ему всё равно, кто создал PR: PR из Claude Code через `gh` ревьюятся так же. Каждый прогон расходует usage Cursor (сначала включённый объём, потом on-demand), поэтому PR живёт черновиком и переводится в ready один раз — когда всё локальное уже зелёное.

Черновики Bugbot не смотрит: Drafts Off в дашборде (установка и личные настройки), после merge PR миграции — ещё и `triggers.drafts: false` в `.cursor/config/bugbot.yaml`. Этот файл Bugbot читает с base-ветки PR, поэтому на PR, который его меняет, он не действует. Автозапуск — один раз на PR (Once per PR); после новых коммитов прогон только вручную (шаг 6).

## Идентификаторы Bugbot (проверено на PR #456)

- Check-run: имя `Cursor Bugbot`, приложение `cursor` (`.app.slug`).
- Автор ревью и комментариев: REST — `cursor[bot]`, GraphQL — `cursor`.

## Предусловия

- `gh auth status` — токен живой. Если `HTTP 401` — см. `AGENTS.md`; не обходить.
- PR существует и он draft: `gh pr view <n> --json isDraft,headRefOid`.
- ЗК пройдены; `code-reviewer` и `/gpt-review` — по условиям из их описаний (состав diff) — пройдены на текущем head SHA. Если нет — сначала они.

## Команды

Head SHA:
```bash
SHA=$(gh pr view <n> --json headRefOid --jq .headRefOid)
```

Check Bugbot на этом SHA (последний прогон):
```bash
gh api "repos/AlexEfimov/TG_parser/commits/$SHA/check-runs?check_name=Cursor%20Bugbot" \
  --jq '[.check_runs[] | select(.app.slug=="cursor")] | sort_by(.started_at) | last
        | {id, head_sha, status, conclusion, started_at, completed_at, title: .output.title, summary: .output.summary}'
```
`gh pr checks` для вердикта не использовать: он показывает `neutral` как skipped.

История «failed to post» по всем коммитам PR (последний check-run на текущем SHA её не показывает — ни прогоны того же SHA до `bugbot run`, ни прогоны прошлых коммитов):
```bash
COMMITS=$(gh pr view <n> --json commits --jq '.commits[].oid') || echo "STOP: gh pr view failed"
echo "commits=$(printf '%s\n' "$COMMITS" | grep -c .)"
printf '%s\n' "$COMMITS" | grep . | while read -r C; do
  gh api --paginate "repos/AlexEfimov/TG_parser/commits/$C/check-runs?check_name=Cursor%20Bugbot&filter=all&per_page=100" \
    --jq '.check_runs[] | select(.app.slug=="cursor")
          | select(((.output.summary // "") + " " + (.output.text // "")) | test("failed to post"; "i"))
          | {head_sha, id, started_at, conclusion}' || echo "STOP: check-runs failed for $C"
done
```
`filter=all` обязателен: по умолчанию (`latest`) API отдаёт только последний прогон на коммит, и «failed to post» перед `bugbot run` на том же SHA не виден. Результат принимается, только если `commits=` равно числу коммитов PR (больше нуля) и нет ни одной строки `STOP` — иначе стоп, к владельцу. Тогда пустой список находок значит, что случаев не было. Каждый найденный случай закрывается только одним из двух способов из п. 3в: полный прогон (Incremental Review выключен, `bugbot run`) после него с разобранным результатом — или решение владельца принять риск, записанное в отчёт.

Ревью Bugbot (нужно ревью с `commit_id` = `$SHA`):
```bash
gh api repos/AlexEfimov/TG_parser/pulls/<n>/reviews --paginate \
  --jq '.[] | select(.user.login=="cursor[bot]") | {id, commit_id, state, submitted_at}'
```

Треды Bugbot (все страницы: `--paginate` сам проходит по `endCursor`, пока `hasNextPage`):
```bash
gh api graphql --paginate -f o=AlexEfimov -f r=TG_parser -F n=<n> -f query='
query($o:String!,$r:String!,$n:Int!,$endCursor:String){repository(owner:$o,name:$r){pullRequest(number:$n){
  reviewThreads(first:100, after:$endCursor){pageInfo{hasNextPage endCursor} nodes{id isResolved isOutdated
    comments(first:1){nodes{databaseId author{login} path line body}}}}}}}' \
  --jq '.data.repository.pullRequest.reviewThreads.nodes[]
        | select(.comments.nodes[0].author.login=="cursor")
        | {thread: .id, isResolved, isOutdated, comment: .comments.nodes[0].databaseId, path: .comments.nodes[0].path, line: .comments.nodes[0].line}'
```

Ответ в треде и резолв (запись на GitHub — только с подтверждения владельца):
```bash
gh api repos/AlexEfimov/TG_parser/pulls/<n>/comments/<comment>/replies -f body='<ответ с доказательством>'
gh api graphql -f id=<thread> -f query='mutation($id:ID!){resolveReviewThread(input:{threadId:$id}){thread{isResolved}}}'
```
Треды Bugbot сами не резолвятся — ни после фикса, ни после ответа.

## Шаги

1. **Ready** (расход usage → подтверждение владельца): `gh pr ready <n>`. Это запускает единственный автоматический прогон.
2. **Ждать check**: `gh pr checks <n> --watch` (Bash в фоне или с `timeout: 600000`) — только как ожидание. Вердикт — командой «Check Bugbot»: `status` = `completed`, `head_sha` = `$SHA`. Check на другом SHA не считается.
3. **Классифицировать результат** по `conclusion`, по наличию ревью Bugbot с `commit_id` = `$SHA` и по `title`/`summary` (при необходимости — `.output.text` того же check-run):
   - `success` — находок нет, старых неразрешённых тредов нет → шаг 7.
   - `failure` — находки есть → шаг 4.
   - `neutral` и есть ревью на `$SHA` — находки есть → шаг 4.
   - `neutral` без ревью на `$SHA` — разобрать по summary:
     - **3а.** Прогон отменён новым коммитом или внутренняя ошибка Bugbot → не зелёный; повторить (шаг 6).
     - **3б.** Новых находок нет, но висят неразрешённые треды прошлых прогонов → разобрать эти треды (шаг 4), затем шаг 7.
     - **3в.** «failed to post» — находка есть, но не опубликована → **стоп, к владельцу.** Incremental-прогон смотрит только изменения после прошлого ревью и эту находку не покажет; его `success` после «failed to post» ничего не доказывает. Варианты для владельца: временно выключить Incremental Review в Bugbot Automations и сделать `bugbot run` (полное ревью), либо принять риск с записью в отчёт.
   - Summary непонятен → стоп, показать владельцу `title` и `summary` дословно; не трактовать в пользу «зелёного».
4. **По каждому неразрешённому треду Bugbot** — одно из двух, затем резолв треда:
   - исправить: правка → ЗК → commit по просьбе владельца → при изменении кода на закоммиченном head SHA заново `code-reviewer` и `/gpt-review` — по условиям из их описаний (состав diff); оба ревьюят только закоммиченное → при новых находках — правка, commit и повтор ревью на новом SHA → push → ответ в треде со ссылкой на коммит → резолв. Новый коммит меняет head SHA — для гейта нужен новый прогон (шаг 6);
   - не согласиться: ответ в треде с доказательством, без правок → резолв.

   Ссылки «Fix in Cursor» и «Fix in Web» не использовать — они запускают агента Cursor мимо прав Claude Code и с оплатой по API.
5. **Проверить треды** командой «Треды Bugbot»: неразрешённых тредов Bugbot быть не должно.
6. **Повторный прогон** — только если код менялся после последнего ревью, в случае 3а или по решению владельца в случае 3в: `gh pr comment <n> --body "bugbot run"` (подтверждение владельца — ещё один прогон с расходом usage). После push Bugbot сам не запускается. Затем снова шаги 2–5.
7. **Гейт перед merge.** «Зелёный Bugbot» — последний check `Cursor Bugbot` на текущем head SHA: `status` = `completed`, `head_sha` = `$SHA`, и одно из:
   - `conclusion` = `success`;
   - `conclusion` = `neutral`, на `$SHA` есть ревью Bugbot, и все его треды разрешены ответом с доказательством (без новых коммитов);
   - случай 3б: summary прямо говорит, что новых находок нет, и все треды Bugbot разрешены.

   В любом случае — ноль неразрешённых тредов Bugbot и выполнена команда «История failed to post»: каждый найденный случай закрыт по п. 3в. Не зелёный: 3а, 3в, незакрытый «failed to post» на любом коммите PR, check на другом SHA, `status` не `completed`, любой неразрешённый тред.
8. **Merge** — только по явной просьбе владельца (`gh pr merge` требует подтверждения в `.claude/settings.json`).

## Диагностика: `verbose=true`

`gh pr comment <n> --body "bugbot run verbose=true"` — прогон с таблицей подключённых правил и Request ID. Тоже расходует usage → только с подтверждения владельца. Когда: после merge PR миграции (проверка, что Bugbot видит `.cursor/BUGBOT.md`) и при непонятном поведении Bugbot. Request ID — в отчёт.

## Учёт для решения по пилоту

После каждого прогона дописать строку в отчёт сессии: PR, head SHA, `conclusion`, сколько прогонов на PR (включая ручные и `verbose`), число находок Bugbot, сколько из них не поймали `code-reviewer` и `/gpt-review`, случаи 3а–3в. По этим данным через 1–2 месяца решается, оставлять ли Bugbot. Расход — в дашборде Cursor, Usage, записи `github_bugbot`.
