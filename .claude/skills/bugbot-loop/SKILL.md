---
name: bugbot-loop
description: Провести PR TG_parser через Cursor Bugbot одним прогоном — перевести черновик в ready, дождаться check, разобрать находки, при необходимости перезапустить и проверить гейт перед merge. Вызывать, когда локальные гейты (ЗК, code-reviewer, /gpt-review) пройдены и PR-черновик создан.
---

# /bugbot-loop — Bugbot как третья линия ревью

Bugbot — GitHub-ревьюер Cursor. Ему всё равно, кто создал PR: PR из Claude Code через `gh` ревьюятся так же. Каждый прогон платный, поэтому PR живёт черновиком (Bugbot черновики не смотрит — `triggers.drafts: false` в `.cursor/config/bugbot.yaml`), а в ready переводится один раз — когда всё локальное уже зелёное.

**Логин бота Bugbot:** `<не заполнен>` — при первом запуске найти (`gh api repos/AlexEfimov/TG_parser/pulls/<n>/reviews --jq '.[].user.login'` на любом прошлом PR с ревью Bugbot), показать владельцу и вписать сюда.

## Предусловия

- `gh auth status` — токен живой. Если `HTTP 401` — см. `AGENTS.md` (PAT в `~/.config/gh/hosts.yml`); не обходить.
- PR существует и он draft: `gh pr view <n> --json isDraft,headRefOid`.
- ЗК, `code-reviewer`, `/gpt-review` пройдены на текущем head SHA. Если нет — сначала они.

## Шаги

1. **Ready** (стоит денег → подтверждение владельца): `gh pr ready <n>`.
2. **Ждать check**: `gh pr checks <n> --watch` (Bash в фоне или с `timeout: 600000`). Нужен check Bugbot на **текущем** head SHA; check на другом SHA не считается.
3. **Собрать находки**:
   ```bash
   gh api repos/AlexEfimov/TG_parser/pulls/<n>/comments --paginate \
     --jq '.[] | select(.user.login=="<логин бота>") | {id, path, line, body}'
   ```
   и неразрешённые треды через GraphQL (`reviewThreads { nodes { isResolved comments(first:1){nodes{author{login} body path}} } }`).
4. **По каждой находке** — одно из двух:
   - исправить: правка → ЗК → при изменении кода заново `code-reviewer` (и `/gpt-review` для рискованных изменений) → commit по просьбе владельца → push;
   - не согласиться: ответ в треде с доказательством (`gh api …/pulls/comments/<id>/replies -f body=…`), без правок.
   Ссылки «Fix in Cursor» не использовать — они запускают агента Cursor с оплатой по API.
5. **Повторный прогон** — только если код менялся: `gh pr comment <n> --body "bugbot run"` (подтверждение владельца — это ещё один платный прогон), затем снова шаги 2–4.
6. **Гейт перед merge** — «зелёный Bugbot» означает: check Bugbot завершён на текущем head SHA **и** неразрешённых тредов Bugbot нет. `neutral` с открытыми тредами — не зелёный.
7. **Merge** — только по явной просьбе владельца (`gh pr merge` требует подтверждения в `.claude/settings.json`).

## Учёт для решения по пилоту

После каждого прогона дописать строку в отчёт сессии: PR, число находок Bugbot, сколько из них не поймали `code-reviewer` и `/gpt-review`. По этим данным через 1–2 месяца решается, оставлять ли Bugbot.
