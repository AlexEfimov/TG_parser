# START PROMPT — Wave 1 полное закрытие (merge + Step 5 ops + hygiene)

> **Status: IMPLEMENTED / Wave 1 fully closed 2026-06-06** — blocking DoD met (PRs [#175](https://github.com/AlexEfimov/TG_parser/pull/175) / [#197](https://github.com/AlexEfimov/TG_parser/pull/197)); optional `v4.4.0` tag + README narrative in PR final closure. Aggregate authority: [`REVIEW_2026-06-03_WAVE1_DONE.md`](REVIEW_2026-06-03_WAVE1_DONE.md).

> **Назначение.** Самодостаточный промпт для следующей сессии, которая **доводит Wave 1 closure от ~90% до 100%**: мержит уже подготовленную closure-ветку в `main`, закрывает Step 5 prod observability (Grafana webhook token + E2E + post-closure cleanup), синхронизирует hygiene-drift в BUG_LOG / PLANNING / PARITY / WATCH header, опционально режет `v4.4.0`. После этой сессии Wave 1 формально закрыт; Wave 1.5 dogfooding и Wave 2 planning — **отдельные** будущие сессии.

| Метаданные | Значение |
|---|---|
| **Дата подготовки промпта** | 2026-06-06 |
| **Тип сессии** | Closure (multi-track: deploy + ops + docs hygiene) |
| **Wave** | 1 (audience-driven steps 1–4 + Step 5 ops tail) |
| **Working branch** | `docs/wave1-closure-2026-06-03` (HEAD `282a20b`, **не влита**) |
| **Target branch** | `main` (HEAD `2c0a187` на момент написания промпта) |
| **Prod baseline** | VPS HEAD `ea826b7` (2 коммита behind `main`; см. § 3) |
| **Last semver tag** | `v4.3.0` (нет `v4.4.0`) |
| **Parent сессия (audit)** | 2026-06-06 audit-сессия (этот промпт) |
| **Aggregate authority** | [`docs/notes/REVIEW_2026-06-03_WAVE1_DONE.md`](REVIEW_2026-06-03_WAVE1_DONE.md) |
| **Статус промпта** | `IMPLEMENTED` (Wave 1 fully closed 2026-06-06) |
| **Format-precedent** | [`START_PROMPT_SPRINT_WAVE1_STEP4_2026-05-23.md`](START_PROMPT_SPRINT_WAVE1_STEP4_2026-05-23.md), [`START_PROMPT_SPRINT_WAVE1_STEP3_2026-05-21.md`](START_PROMPT_SPRINT_WAVE1_STEP3_2026-05-21.md) |

---

## §1 — TL;DR

Wave 1 (steps 1–4 + Step 5 ops) **по коду готов**: 4 канонических шага DONE, post-watch кластер BUG-029…053 закрыт, ADR 0001–0009 Accepted, 0 TODO/FIXME, 0 Critical/Severe open bugs. **Что не сделано:** (1) closure-ветка `docs/wave1-closure-2026-06-03` не влита в `main`; (2) Step 5 prod observability incomplete — нет `GRAFANA_WEBHOOK_TOKEN` на проде, E2E alert path не проверен; (3) hygiene-drift: WATCH header `_pending_`, BUG-027 status не синхронизирован с aggregate § 5. Эта сессия закрывает три трека параллельно и (опционально) режет `v4.4.0` tag + обновляет `README.md`.

---

## §2 — Контекст: где остановились

### Что уже сделано в closure-ветке `docs/wave1-closure-2026-06-03` (HEAD `282a20b`, +1 коммит к `main`, 6 файлов, +193/−31)

| Артефакт | Что |
|---|---|
| [`docs/notes/REVIEW_2026-06-03_WAVE1_DONE.md`](REVIEW_2026-06-03_WAVE1_DONE.md) | **Aggregate marker.** Cross-links на 4 step-DONE; § 6 gates (Decision Point external signals «not met»); § 5.3 matrix через § 7; § 12 verdict «DONE with documented caveats» |
| [`docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) | Добавлены step 3 / step 4 DONE rows + aggregate closure §; убран stale «step 3 NEXT» |
| [`docs/notes/BUG_LOG.md`](BUG_LOG.md) | BUG-025 / BUG-026 status `open` → `open — deferred to Wave 2` (с cross-link на aggregate § 5); BUG-036 / BUG-038 → `resolved` |
| `CHANGELOG.md` | Секция «Wave 1 aggregate closure (2026-06-03)» в `[Unreleased]` (см. также секцию PR #171) |
| `START_PROMPT_PRESERVE_TG_URLS_2026-06-02.md` + `START_PROMPT_POST_BUG050_FOLLOWUPS_2026-06-02.md` | SUPERSEDED / IMPLEMENTED banners (audit trail только) |

### Что НЕ сделано (приоритизировано — это и есть scope этой сессии)

1. **[BLOCKING — Wave 2 gate]** `docs/wave1-closure-2026-06-03` не влита в `main`. PR не открыт.
2. **[BLOCKING — prod observability]** Step 5 Grafana: `GRAFANA_WEBHOOK_TOKEN` отсутствует в prod `.env`; alert path end-to-end не подтверждён; post-closure cleanup runbook [`WAVE1_STEP4_VPS_POST_CLOSURE_CLEANUP.md`](../runbooks/WAVE1_STEP4_VPS_POST_CLOSURE_CLEANUP.md) § A–D не исполнен; prod на `ea826b7` (2 коммита behind `main`).
3. **[HYGIENE]** [`WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md`](WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md): header `Closed: _pending_` + footer `Status: OPEN`.
4. **[HYGIENE]** Drift:
   - **BUG-027** (`docs/notes/BUG_LOG.md`) — статус `open` (sic), но в aggregate § 5 указан как `deferred → Wave 2`.
   - **BUG-022** в § Resolved bugs — row следует подсветить как `resolved` через ADR 0009 (cross-link явный).
   - [`PARITY_DECISION_TRACKING.md`](PARITY_DECISION_TRACKING.md) — обновить header status «closed post-Wave-1 2026-06-06» (дата closure-сессии).
   - [`PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md`](PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md) — добавить «closed 2026-06-03» в шапку Status.
5. **[OPTIONAL]** Cut `[Unreleased]` → `v4.4.0` блок + git tag `v4.4.0` (только после merge).
6. **[OPTIONAL]** `README.md` — короткая секция о Wave 1 closure / audience-driven narrative.

### Open BUGs за рамками closure (контекст — НЕ задача этой сессии)

- **BUG-008** (MCP hang spike, diagnostic) — Wave 2 backlog.
- **BUG-019 / BUG-020 / BUG-021** — backlog (LLM JSON retry, Anthropic backoff, cross-channel stats).
- **BUG-025 / BUG-026 / BUG-027** — deferred Wave 2 (bot UX cluster, step 4.1 scope-lock not executed).

---

## §3 — Pre-flight checklist

> Прогнать ДО первого действия. Любой FAIL → STOP, surface, не патчить молча.

### Local environment

```bash
cd /Users/alexanderefimov/TG_parser

git fetch origin
git status
# Ожидаемо: clean working tree на ветке docs/wave1-closure-2026-06-03

git rev-parse HEAD
# Ожидаемо: 282a20b (если ничего не landed в эту ветку с 2026-06-06)

git log --oneline main..HEAD
# Ожидаемо: 1 коммит — "docs(wave1): aggregate closure marker + Grafana prod verify sync"

git rev-parse origin/main
# Ожидаемо: 2c0a187 (или новее — если в main прилетели свежие PR, см. § 6 Risk register R-1)

git diff main --stat
# Ожидаемо: 6 файлов / +193 / −31 (CHANGELOG / BUG_LOG / REVIEW_*_WAVE1_DONE / ROADMAP_KARPATHY_LIKE_LIVING_KB + 2 banner edits на старых START_PROMPT)
```

### Tooling

```bash
gh auth status
# Ожидаемо: logged in as @AlexEfimov для AlexEfimov/TG_parser

uvx ruff@0.15.11 format --check . && uvx ruff@0.15.11 check .
# Ожидаемо: clean (closure-ветка не трогает код, но CI всё равно прогонит)

.venv/bin/pytest -q --tb=line 2>&1 | tail -3
# Ожидаемо: ≥ baseline post-PR #171; closure-ветка docs-only → не должно быть регрессий
```

### Prod access

```bash
ssh -p 2296 user@212.72.189.15 'hostname && cd ~/TG_parser && git rev-parse HEAD'
# Ожидаемо: redboxtgbot + HEAD = ea826b7 (PR #171 на проде; 2 коммита behind main = 2c0a187)
```

### Anti-scope sanity

- НЕ начинаем Wave 2 planning.
- НЕ начинаем Wave 1.5 dogfooding (отдельная привычка / отдельная сессия).
- НЕ трогаем **код** BUG-008 / 019 / 020 / 021 / 025 / 026 / 027 (Wave 2 backlog — bot UX fixes / LLM retry / Anthropic backoff / cross-channel stats / MCP hang diagnostic).
- **Docs-only status sync** (например, флип BUG-027 status row на `open — deferred to Wave 2` в `BUG_LOG.md`, синхронизация PLANNING / PARITY header'ов) — **in-scope hygiene** (см. § 5.4). Anti-scope относится только к code fixes, не к docs sync.
- НЕ создаём `docs/methodology/**`.
- НЕ правим `pyproject.toml` / `requirements.txt` / `uv.lock`.

---

## §4 — Цели сессии (по приоритету)

| # | Цель | Приоритет | Time budget | DoD |
|---|---|---|---|---|
| **1** | Открыть PR `docs/wave1-closure-2026-06-03 → main`, прогнать CI, влить (squash или merge — § 5.2) | **BLOCKING** (Wave 2 gate) | S (15–30 мин активной работы + CI ~5 мин) | PR merged; aggregate marker в `main` |
| **2** | Step 5 prod observability: token + E2E + cleanup runbook § A–D + prod pull `2c0a187+` | **BLOCKING** (prod observability) | M (60–120 мин, включая ожидания alert path) | `GRAFANA_WEBHOOK_TOKEN` set; synthetic alert reaches GitHub issue; prod на свежем SHA |
| **3** | Hygiene batch: WATCH header CLOSED, BUG_LOG drift (BUG-027, BUG-022), PLANNING / PARITY status, aggregate marker §2/§8/§9 patch, hygiene PR + merge | **BLOCKING** (DoD requires merged hygiene PR) | M (55–80 мин: 30–45 мин edits + ~10 мин aggregate marker patch + 5 мин ruff/commit + 5–10 мин PR + 5 мин CI + 2 мин merge) | См. § 5.4 DoD-чеклист |
| **4** | (Optional) `[Unreleased]` → `v4.4.0` блок + git tag `v4.4.0` | OPTIONAL | S (15 мин) | `git tag v4.4.0` + push; CHANGELOG имеет dated header |
| **5** | (Optional) `README.md` короткая секция о Wave 1 closure / audience-driven narrative | OPTIONAL | S (20 мин) | README отражает v4.4.0 + F4-B / closure |
| **6** | Финальная верификация: aggregate marker в `main`, ROADMAP актуален, prod GREEN, hygiene PR merged | BLOCKING | S (15 мин) | См. § 5.6 |

**Сводный time budget:** S+M+M+S = **2.5–3.5 часа** активной работы (без optional 4/5). Optional 4/5 добавляют ~35 мин → **3–4 часа** с optional.

---

## §5 — Последовательность шагов (workflow)

### Шаг 1 — Подготовка PR + merge в `main`

**1.1 Rebase / sync (если `main` ушёл вперёд за время audit'а):**

```bash
git fetch origin main
git log --oneline docs/wave1-closure-2026-06-03..origin/main
# Если пусто — main не двигался; можно мержить как fast-forward по сути.
# Если есть коммиты — см. § 6 R-1 (merge conflict risk).

# При drift'е в main:
git checkout docs/wave1-closure-2026-06-03
git rebase origin/main
# Конфликты ожидаются только в BUG_LOG / CHANGELOG / ROADMAP_KARPATHY_LIKE_LIVING_KB.md.
# Resolve вручную, сохраняя aggregate-marker cross-links.
```

**1.2 Push (если ещё не запушено):**

```bash
git push origin docs/wave1-closure-2026-06-03
```

**1.3 Создать PR через `gh`:**

```bash
gh pr create \
  --base main \
  --head docs/wave1-closure-2026-06-03 \
  --title "docs(wave1): aggregate closure marker + Grafana prod verify sync" \
  --body "$(cat <<'EOF'
## Summary

Closes Wave 1 (audience-driven steps 1–4 + partial Step 5 ops) per `docs/notes/REVIEW_2026-06-03_WAVE1_DONE.md`.

- **Aggregate DONE marker** with cross-links to all four step-DONE markers, gates table (§ 6), and § 12 verdict «DONE with documented caveats».
- **ROADMAP_KARPATHY_LIKE_LIVING_KB.md** — step 3 / step 4 DONE rows + aggregate closure §; stale «step 3 NEXT» removed.
- **BUG_LOG.md** — BUG-025 / BUG-026 deferred → Wave 2; BUG-036 / BUG-038 → resolved.
- **CHANGELOG.md** — `[Unreleased]` § Wave 1 aggregate closure.
- 2 banner edits on superseded START_PROMPT files (audit trail).

Docs-only PR — no code touched, no migrations, no tests added.

## Verification

- [x] `uvx ruff@0.15.11 format --check . && uvx ruff@0.15.11 check .` clean
- [x] Pytest baseline unchanged (no code touched)
- [x] Cross-links from aggregate marker resolve

## Follow-ups (separate work, not in this PR)

- Step 5 ops: `GRAFANA_WEBHOOK_TOKEN` on prod `.env` + E2E alert path (operator-driven).
- Post-closure cleanup runbook § A–D execution.
- WATCH window header close + remaining BUG_LOG / PLANNING / PARITY drift.
- Optional `v4.4.0` tag after merge.

EOF
)"
```

**1.4 Watch CI:**

```bash
gh pr view --json url,number
gh pr checks <PR_NUMBER> --watch
# Required: Test Python 3.12. Lint Documentation НЕ required — игнор если красный только он.
```

**Стоп-условия:**

- Required check red → STOP, surface red, расследовать (мало шансов — docs-only PR).
- Conflict с `main` → решать как обычный rebase (см. R-1).

---

### Шаг 2 — Merge стратегия

**Решение:** **squash merge** (или merge — см. ниже).

| Опция | Когда выбирать |
|---|---|
| **Squash** (рекомендовано) | PR содержит 1 коммит; squash сохранит чистый log в `main` с готовым subject «docs(wave1): aggregate closure marker + Grafana prod verify sync» |
| **Merge commit** | Только если оператор хочет сохранить closure-ветку как отдельную линию истории (нет такого требования сейчас) |

```bash
# После CI green:
gh pr merge <PR_NUMBER> --squash --delete-branch
# либо UI

git fetch origin main
git checkout main
git pull --ff-only
git log -1 --format='%H %s'
# Ожидаемо: новый squash-merge SHA с aggregate marker subject
```

**Дождаться ли CI до merge?** **Да.** Required = `Test Python 3.12`; нельзя мержить с failing required check. `Lint Documentation` не required → игнор если только он красный (pre-existing markdown link issues).

---

### Шаг 3 — Step 5 operator ops

**Контекст:** Aggregate marker § 2 «Step 5 ops status» = **PARTIAL**. Grafana stack healthy, provisioning-as-code verified, `GRAFANA_WEBHOOK_URL` set 2026-06-03; что осталось — bearer token + E2E + post-closure cleanup. См. также [`WAVE1_STEP4_VPS_POST_CLOSURE_CLEANUP.md`](../runbooks/WAVE1_STEP4_VPS_POST_CLOSURE_CLEANUP.md) § A–D.

**3.1 Set `GRAFANA_WEBHOOK_TOKEN` on prod:**

```bash
ssh -p 2296 user@212.72.189.15

cd ~/TG_parser
# Backup .env
cp .env .env.backup-$(date -u +%Y%m%dT%H%MZ)

# Add the token. ВАЖНО: значение = тот же `crsr_…` token что в $TG_PARSER_WATCH_WEBHOOK_AUTH
# на operator-machine; см. operator manual.
grep -q '^GRAFANA_WEBHOOK_TOKEN=' .env \
  && sed -i 's|^GRAFANA_WEBHOOK_TOKEN=.*|GRAFANA_WEBHOOK_TOKEN=crsr_<VALUE>|' .env \
  || echo 'GRAFANA_WEBHOOK_TOKEN=crsr_<VALUE>' >> .env

# Verify
grep '^GRAFANA_WEBHOOK' .env
# Ожидаемо: GRAFANA_WEBHOOK_URL=https://api2.cursor.sh/automations/webhook/7b35ca01-a7d1-4c3a-bb8b-940918e506d6
#           GRAFANA_WEBHOOK_TOKEN=crsr_***

# Recreate Grafana с новыми env
docker compose up -d --force-recreate --no-deps tg_parser_grafana
docker logs --tail 80 tg_parser_grafana | grep -iE 'provision|webhook|error'
# Ожидаемо: "finished to provision alerting" + no auth errors
```

**3.2 E2E alert verification (synthetic alert → webhook → GitHub issue):**

Вариант **A — curl synthetic Grafana payload (cheap, recommended first):**

```bash
# Из operator-machine (Mac), используя сохранённые env vars:
source ~/.zshrc
echo "$TG_PARSER_WATCH_WEBHOOK"      # URL должен быть готов (https://api2.cursor.sh/automations/webhook/7b35ca01-…)
echo "$TG_PARSER_WATCH_WEBHOOK_AUTH" # уже содержит префикс "Bearer crsr_…" (НЕ добавлять второй раз!)

# ВАЖНО: $TG_PARSER_WATCH_WEBHOOK_AUTH = "Bearer crsr_…" целиком (см. operator manual § 1.7).
# Двойной "Bearer Bearer crsr_…" → 401. Передаём header value as-is.
# Payload — flat-формат (alertname / summary / severity top-level), как в operator manual § 1.7 curl snippets.
# Grafana v9 alerts[] — fallback, automation `7b35ca01` парсит оба; flat = canonical для operator-curl.
curl -sS -X POST "$TG_PARSER_WATCH_WEBHOOK" \
  -H "Authorization: $TG_PARSER_WATCH_WEBHOOK_AUTH" \
  -H "Content-Type: application/json" \
  -d '{
    "alertname": "tg_parser_bot_down",
    "severity": "critical",
    "summary": "[smoke 2026-06-06] Synthetic alert from Wave 1 closure session",
    "description": "Synthetic smoke from closure session — close immediately, no real incident.",
    "source": "operator-curl"
  }'
# Ожидаемо: 200 OK (или 202)
# Подождать 60-120s, проверить в репо новый GitHub issue с prefix [bot down]
gh issue list --repo AlexEfimov/TG_parser --search "smoke 2026-06-06" --json number,title
# Закрыть issue сразу: gh issue close <N> --comment "synthetic; closure session smoke"
```

Вариант **B — natural fire** (например, кратковременно `docker stop tg_parser_bot` на 7+ мин чтобы триггернуть rule `tg_parser_bot_down`). **Не рекомендуется** для closure-сессии — есть real users; curl-вариант A эквивалентен по гарантиям.

**Acceptance:** webhook вернул 200/202 + новый GitHub issue в репо в окне 2–3 мин после curl.

**3.3 Post-closure cleanup runbook § A–D:**

Открыть [`docs/runbooks/WAVE1_STEP4_VPS_POST_CLOSURE_CLEANUP.md`](../runbooks/WAVE1_STEP4_VPS_POST_CLOSURE_CLEANUP.md) и пройти:

- **§ A** — Disable single-shot Cursor automations (`2bd25769`, `f93e557a`). `7b35ca01` **оставить enabled** (live monitoring).
- **§ B** — Delete 7 `[DELETE_ME] schema-probe-*` automations (operator-manual, Cursor UI).
- **§ C** — Grafana admin password rotation (operator-manual, SSH + container restart). Если оператор отложил — пометить в § 8 aggregate marker как остающийся open item, не блокирует closure.
- **§ D** — Telegram-side cleanup (R-1 / R-2 / vps-watch-test-grp) — operator discretion.

**Минимальный объём для closure:** § A обязательно (cleanup automations). § B / § C / § D — operator-discretion; задокументировать что не сделано в финальной § 8 aggregate marker.

**3.4 Update prod к `main` HEAD (после merge из шага 1):**

```bash
ssh -p 2296 user@212.72.189.15
cd ~/TG_parser

# Зафиксировать pre-deploy SHA для rollback
git rev-parse HEAD > /tmp/pre-deploy-sha.txt
cat /tmp/pre-deploy-sha.txt
# Ожидаемо: ea826b7

git fetch origin main
git checkout main
git pull --ff-only

git rev-parse HEAD
# Ожидаемо: новый squash-merge SHA из шага 1 (поверх 2c0a187)

# Closure PR docs-only → пересборка контейнеров не нужна, миграций нет.
# Достаточно убедиться что running контейнеры остаются healthy:
docker compose ps
# Ожидаемо: 6 контейнеров healthy/running как было до pull
```

**Если оператор хочет всё-таки rebuild для синхронизации (опционально):**

```bash
# NB: имена ниже = compose service names (см. docker-compose.yml services:),
# НЕ container_name. Сервис называется `mcp` (container_name=tg_parser_mcp).
docker compose up -d --build tg_parser mcp
docker compose --profile bot up -d --force-recreate --no-deps tg_bot
```

---

### Шаг 4 — Hygiene batch

> Сделать одним коммитом или 2-3 атомарными коммитами (на усмотрение closure-агента). Все правки docs-only, в feature-ветке от свежего `main`.

**4.1 Создать hygiene-ветку:**

```bash
git checkout main && git pull --ff-only
git checkout -b docs/wave1-closure-hygiene-2026-06-06
```

**4.2 Закрыть WATCH header:**

Файл: [`docs/notes/WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md`](WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md).

- **Header (≈ строка 15):** `**Closed:** _pending_ — close via аналог \`START_PROMPT_SESSION_WATCH_CLOSURE_2026-05-25.md\`.` → `**Closed:** 2026-06-06 (closure session per [\`REVIEW_2026-06-03_WAVE1_DONE.md\`](REVIEW_2026-06-03_WAVE1_DONE.md)).`
- **Footer (≈ строка 282):** в Verdict table флипнуть `Status: OPEN` → `Status: **CLOSED — PASS-WITH-CAVEATS**` + cross-link на aggregate marker.

**4.3 BUG_LOG drift:**

Файл: [`docs/notes/BUG_LOG.md`](BUG_LOG.md).

- **BUG-027 (~строка 2668)** — `| **Status** | \`open\` (filed 2026-05-23 ...)` → `| **Status** | \`open\` — **deferred to Wave 2** (Wave 1 closure 2026-06-03 per [\`REVIEW_2026-06-03_WAVE1_DONE.md\`](REVIEW_2026-06-03_WAVE1_DONE.md) § 5; step 4.1 scope-lock never executed) ...`. Шаблон — как уже сделано в closure-ветке для BUG-025 / BUG-026 (см. § 2.4 этого промпта).
- **BUG-022** (в § Resolved bugs, ~строка 4479) — убедиться что row подсвечен как `resolved` через ADR 0009 (cross-link на [`docs/adr/0009-idempotency.md`](../adr/0009-idempotency.md) + закрывающий PR SHA). Если уже есть — просто verify; иначе добавить «closed via ADR 0009 / PR #89 (Wave 1 step 3)» в row.

**4.4 PLANNING / PARITY status:**

- [`docs/notes/PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md`](PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md) — в шапке Status (`**Status:** активный operational план. ...`) добавить hard-line: `**Closed:** 2026-06-03 (Wave 1 aggregate closure — see [REVIEW_2026-06-03_WAVE1_DONE.md](REVIEW_2026-06-03_WAVE1_DONE.md)).`
- [`docs/notes/PARITY_DECISION_TRACKING.md`](PARITY_DECISION_TRACKING.md) — header status (~строка 12, **Status (2026-05-22 post-S3)**) дополнить hard-line: `**Status (2026-06-06 closure session):** closed post-Wave-1 (aggregate marker per [REVIEW_2026-06-03_WAVE1_DONE.md](REVIEW_2026-06-03_WAVE1_DONE.md), Wave 1 declared DONE 2026-06-03)`. NB: дата `2026-06-06` = дата closure-сессии (когда hygiene применяется); aggregate marker сохраняет свою дату `2026-06-03`.

**4.5 Aggregate marker patch — `REVIEW_2026-06-03_WAVE1_DONE.md` §2 / §8 / §9:**

После того как Step 5 ops (шаг 3) и hygiene edits (4.2–4.4) исполнены, aggregate marker должен отразить новое состояние — иначе authority doc формально оставляет Wave 1 «not 100%». Patch включается **в этот же hygiene PR** (один PR, не два).

Файл: [`docs/notes/REVIEW_2026-06-03_WAVE1_DONE.md`](REVIEW_2026-06-03_WAVE1_DONE.md).

- **§2 «Step 5 ops status» (~строка 22–25):** **PARTIAL → PASS** (с датой `2026-06-06` и SHA prod post-merge).
  - Verdict line: `**Verdict:** **PASS** — Grafana stack healthy, provisioning-as-code verified, webhook URL + token set on prod, E2E alert path verified end-to-end 2026-06-06.`
  - В matrix (Check table): `GRAFANA_WEBHOOK_TOKEN` row `ABSENT → PASS (2026-06-06, set during closure session)`; `Prod git HEAD vs main` row → `PASS (2026-06-06, prod на post-merge SHA <SHA>)`; `Post-closure cleanup runbook` row → `PARTIAL → § A executed 2026-06-06` (если § B/§C/§D отложены — указать «§ B/C/D deferred per § 8»).
  - «Risk items (operator action)» секцию — `GRAFANA_WEBHOOK_TOKEN` строка снимается; password rotation остаётся, если § C не сделан.
- **§8 «Remaining non-blocking items» (~строка 110–122):** completed items flip → `~~strikethrough~~ + Done 2026-06-06`:
  - `Prod .env: GRAFANA_WEBHOOK_TOKEN` → `~~Prod .env: GRAFANA_WEBHOOK_TOKEN~~ Done 2026-06-06`.
  - `Post-closure Cursor automation cleanup (§ A–B …)` → split: § A `~~Done 2026-06-06~~`; § B остаётся (если не сделан) с пометкой «Operator UI deferred».
  - `Prod pull 2c0a187 (changelog-only)` → `~~Prod pull~~ Done 2026-06-06 — prod на <post-merge SHA>`.
- **§9 «Pre-next-step readiness checklist» (~строка 125–133):** последний unchecked item `[ ] Operator prod webhook token + password rotation` → `[x] Operator prod webhook token (Done 2026-06-06); password rotation deferred per § 8`.

NB: SHA prod post-merge берётся из шага 1 (`git log -1 --format='%H'` после `git pull --ff-only` на проде в шаге 3.4). Зафиксировать локально перед редактированием.

**4.6 Ruff sanity + commit:**

```bash
uvx ruff@0.15.11 format --check . && uvx ruff@0.15.11 check .
# docs-only → должно быть clean

git add -A
git status
git diff --stat
# Ожидаемо: 5 файлов — WATCH_WINDOW_*, BUG_LOG.md, PLANNING_*, PARITY_*, REVIEW_2026-06-03_WAVE1_DONE.md
# (опционально + CHANGELOG.md / README.md если шаг 5 включён)

# Hygiene commit authorized by closure-session scope (см. § 7 DoD); это НЕ нарушение AGENTS.md,
# т.к. пользователь передал closure-prompt агенту явно, и commit включён в DoD (BLOCKING).
git commit -m "$(cat <<'EOF'
docs(wave1): closure hygiene batch — WATCH header + BUG_LOG drift + PLANNING/PARITY status + aggregate marker §2/§8/§9 sync

After Step 5 ops (token + E2E + cleanup § A) executed in closure session 2026-06-06.

- WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md: header Closed=2026-06-06; footer Status=CLOSED — PASS-WITH-CAVEATS.
- BUG_LOG.md: BUG-027 status row sync (open → deferred to Wave 2); BUG-022 closure annotation via ADR 0009.
- PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md: header Closed: 2026-06-03.
- PARITY_DECISION_TRACKING.md: header Status (2026-06-06 closure session): closed post-Wave-1.
- REVIEW_2026-06-03_WAVE1_DONE.md: §2 PARTIAL → PASS; §8 completed items flipped; §9 readiness checklist updated.

Per START_PROMPT_WAVE1_CLOSURE_2026-06-06.md § 5.4 + § 7 DoD.
EOF
)"
```

**4.7 PR create + CI watch + merge:**

```bash
git push origin docs/wave1-closure-hygiene-2026-06-06

gh pr create \
  --base main \
  --head docs/wave1-closure-hygiene-2026-06-06 \
  --title "docs(wave1): closure hygiene batch (WATCH + BUG_LOG + PLANNING/PARITY + aggregate marker sync)" \
  --body "$(cat <<'EOF'
## Summary

Hygiene batch closing the last drift items after Wave 1 closure session 2026-06-06 (Step 5 ops + aggregate sync).

- **WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md** — header `Closed: 2026-06-06`; footer Status `CLOSED — PASS-WITH-CAVEATS` + cross-link на aggregate marker.
- **BUG_LOG.md** — BUG-027 status row sync (`open` → `open — deferred to Wave 2`); BUG-022 closure annotation via ADR 0009 verified.
- **PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md** — header `Closed: 2026-06-03` (aggregate closure date).
- **PARITY_DECISION_TRACKING.md** — header `Status (2026-06-06 closure session): closed post-Wave-1`.
- **REVIEW_2026-06-03_WAVE1_DONE.md** — §2 Step 5 PARTIAL → PASS; §8 completed items flipped; §9 readiness checklist updated.

Docs-only PR — no code touched, no migrations.

## Verification

- [x] `uvx ruff@0.15.11 format --check . && uvx ruff@0.15.11 check .` clean
- [x] Pytest baseline unchanged (no code touched)
- [x] Cross-links resolve

## Follow-ups (separate work)

- Post-closure cleanup § B (schema-probe deletes), § C (Grafana password rotation), § D (Telegram cleanup) — operator-discretion, документировано в aggregate marker § 8.
- Optional `v4.4.0` tag + README narrative (см. § 5 Шаг 5 closure prompt).

EOF
)"

# Watch CI (required: Test Python 3.12; Lint Documentation НЕ required)
gh pr view --json url,number
gh pr checks <HYGIENE_PR_NUMBER> --watch

# После CI green — squash merge:
gh pr merge <HYGIENE_PR_NUMBER> --squash --delete-branch

# Sync local main
git checkout main
git pull --ff-only
git log -1 --format='%H %s'
# Ожидаемо: squash-merge SHA с hygiene batch subject
```

**Стоп-условия:** required check red → STOP, расследовать (docs-only — маловероятно). Conflict с `main` (если в `main` прилетели свежие PR между шагом 1 и 4) — rebase см. R-1.

---

### Шаг 5 — (Optional) Release tag + README

> Делаем ТОЛЬКО если оператор подтвердил scope. Если closure-сессия идёт по минимуму — пропустить и зафиксировать в § 8 aggregate marker как deferred.

**5.1 `[Unreleased]` → `v4.4.0`:**

Файл: `CHANGELOG.md`.

- Поднять `## [Unreleased]` → `## [4.4.0] — 2026-06-06`.
- Под ним добавить новый пустой `## [Unreleased]` для будущих PR.
- Сохранить все секции из [Unreleased] (Wave 1 aggregate closure + Preserve TG URLs + Wave 1 step 4) под `[4.4.0]`.

**5.2 Git tag:**

```bash
git checkout main && git pull --ff-only
git tag -a v4.4.0 -m "Wave 1 closure (audience-driven steps 1-4 + Step 5 ops PARTIAL)

See docs/notes/REVIEW_2026-06-03_WAVE1_DONE.md for closure details."
git push origin v4.4.0
# Verify
gh release list | head -5
# Опционально: gh release create v4.4.0 --notes-from-tag
```

**5.3 `README.md`:**

Добавить короткую секцию (3–5 параграфов) о текущем состоянии: Wave 1 closed, что доступно (HTTP API + MCP + Bot + CLI parity, F4-B Workspaces, F6 digest с polymorphic target chat|channel, F11 watchlist), какие audiences обслуживаются (A4 AI Agent Builder, A6 Domain Curator), куда идём дальше (Wave 1.5 dogfooding + Wave 2 planning — отдельные треки).

---

### Шаг 6 — Финальная верификация

```bash
# 1. Aggregate marker в main
git checkout main && git pull --ff-only
git log --oneline -3
# Должен быть squash-merge с aggregate marker subject

ls docs/notes/REVIEW_2026-06-03_WAVE1_DONE.md
# Файл существует в main

# 2. ROADMAP актуален
rg "step 3" docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md | head -5
# Должны быть DONE rows, не «NEXT»

# 3. Prod GREEN
ssh -p 2296 user@212.72.189.15 'cd ~/TG_parser && git rev-parse HEAD && docker compose ps | head -10'
# HEAD = post-merge SHA; все контейнеры healthy

# 4. WATCH header CLOSED
rg "^\\*\\*Closed:\\*\\*" docs/notes/WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md
# Должна быть конкретная дата, не _pending_

# 5. BUG_LOG drift синхронизирован
rg "BUG-027.*deferred|deferred.*BUG-027" docs/notes/BUG_LOG.md
# Match есть

# 6. (Optional) Tag visible
git tag -l v4.4.0
# v4.4.0 (если шаг 5 сделан)
```

---

## §6 — Scope / Anti-scope

### In-scope

- Merge `docs/wave1-closure-2026-06-03 → main`.
- Step 5 ops: token + E2E + cleanup runbook § A (минимум).
- Hygiene batch: WATCH header, BUG-027 / BUG-022 sync, PLANNING / PARITY status.
- Финальная верификация.
- (Optional) `v4.4.0` tag, README narrative.

### Anti-scope (HARD list — любой UX-soft push → STOP, log, не флипать)

| ID | Anti-scope item | Where it goes |
|---|---|---|
| **(a)** | **Wave 2 planning** (новые ADR, new sprint prompts, ENH-N triage за рамками closure) | Отдельная planning-сессия после closure |
| **(b)** | **Wave 1.5 dogfooding** activities (daily-use telemetry, A4 partner outreach) | Параллельная привычка / отдельная сессия |
| **(c)** | **BUG-008 / 019 / 020 / 021** (LLM JSON retry, Anthropic backoff, cross-channel stats, MCP hang diagnostic) | Wave 2 backlog |
| **(d)** | **BUG-025 / 026 / 027** code fix (write-tool UUID validation, standalone-UUID continuation, soft-delete wording) | Wave 2 bot UX sprint per aggregate § 5 |
| **(e)** | **`docs/methodology/**`** edits | Methodology workspace (отдельное Cursor-окно, ветка `methodology`) |
| **(f)** | **`pyproject.toml` / `requirements.txt` / `uv.lock`** edits | Никогда без явного запроса оператора |
| **(g)** | **Code touches** (tg_parser/**, tests/**) | Closure docs-only; любой code-touch → STOP, surface, отдельный PR |
| **(h)** | **New ADR / contract** files | Wave 2 (closure не вводит новых архитектурных решений) |
| **(i)** | **Migrations** (Alembic) | Не нужны для closure |
| **(j)** | **CI infrastructure** edits (workflows, hooks) | Отдельная инфра-сессия по сигналу |

---

## §7 — Definition of Done

Closure session считается завершённой, когда **все BLOCKING** критерии выполнены. OPTIONAL — bonus.

### BLOCKING (требуется для declaring «Wave 1 fully closed»)

- [ ] PR `docs/wave1-closure-2026-06-03 → main` создан, прошёл required CI (`Test Python 3.12`), squash-merged. Aggregate marker `REVIEW_2026-06-03_WAVE1_DONE.md` доступен в `main`.
- [ ] `main` HEAD на новом squash-merge SHA; closure-ветка удалена в remote.
- [ ] `GRAFANA_WEBHOOK_TOKEN` set в prod `.env`; Grafana container recreated; logs clean (`finished to provision alerting`, no auth errors).
- [ ] Synthetic alert через webhook прошёл end-to-end до GitHub issue в репо (verified в окне 2–3 мин после curl). Issue закрыт с пометкой «synthetic».
- [ ] Prod git HEAD = post-merge SHA (≥ `2c0a187+`); все контейнеры healthy.
- [ ] Post-closure cleanup § A исполнен (single-shot automations disabled).
- [ ] WATCH window file: header `Closed:` = реальная дата; footer Status `CLOSED — PASS-WITH-CAVEATS` + cross-link на aggregate marker.
- [ ] BUG-027 в `BUG_LOG.md` статус-row синхронизирован (`open — deferred to Wave 2` + cross-link на aggregate § 5).
- [ ] BUG-022 row в § Resolved bugs явно указывает закрытие через ADR 0009.
- [ ] `PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md` шапка имеет `**Closed:** 2026-06-03`.
- [ ] `PARITY_DECISION_TRACKING.md` header status дополнен `**Status (2026-06-06 closure session):** closed post-Wave-1`.
- [ ] **Aggregate marker §2 / §8 / §9 обновлён** в `REVIEW_2026-06-03_WAVE1_DONE.md` (§2 Step 5 PARTIAL → PASS с датой/SHA; §8 completed items flipped; §9 readiness checklist updated).
- [ ] **Hygiene PR merged в `main`** (squash + delete-branch; aggregate-marker patch включён в этот же PR).

### OPTIONAL (bonus — задокументировать в финальном aggregate marker если отложено)

- [ ] `v4.4.0` git tag создан и запушен; CHANGELOG разрезан `[Unreleased]` → `[4.4.0] — 2026-06-06` + новый пустой `[Unreleased]`.
- [ ] `README.md` обновлён с короткой секцией о Wave 1 closure / audience narrative.
- [ ] Post-closure cleanup § B (delete schema-probe automations), § C (Grafana password rotation), § D (Telegram cleanup) исполнены или явно отложены с записью в § 8 aggregate marker.

---

## §8 — Time budget

| Шаг | Класс | Расчёт |
|---|---|---|
| 1 — PR + CI + merge | **S** | 15 мин setup + 5–10 мин CI + 5 мин merge = ~25–30 мин |
| 2 — Merge strategy decision | (включено в шаг 1) | — |
| 3 — Step 5 ops | **M** | 15 мин token setup + 30 мин E2E ожидание + 30–60 мин cleanup § A + 15 мин prod pull = ~90–120 мин |
| 4 — Hygiene batch (incl. aggregate marker patch + PR merge) | **M** | 30–45 мин hygiene edits (5 файлов) + ~10 мин aggregate marker §2/§8/§9 patch + 5 мин ruff/commit + 5–10 мин PR create + 5 мин CI watch + 2 мин squash merge = ~55–80 мин |
| 5 — Optional release + README | **S** | 15 мин tag + 20 мин README = ~35 мин |
| 6 — Финальная верификация | **S** | 10–15 мин (set checks из § 5.6) |

**Total (без optional):** ~2.5–3.5 часа активной работы.
**Total (с optional):** ~3–4 часа.

NB: шаг 4 вырос от изначальной оценки `S (30–45 мин)` после уточнения scope (hygiene PR создаётся / мержится в этой же сессии + aggregate marker §2/§8/§9 синхронизируется в том же PR).

Большая часть «M» в шаге 3 — пассивное ожидание E2E (curl → automation → issue ≈ 60–120s) и cleanup interactions через Cursor UI / SSH.

---

## §9 — Артефакты (что должно появиться / измениться)

### Будет создано

- Новый коммит на `main` (squash-merge closure-ветки) с aggregate marker.
- (Optional) `v4.4.0` git tag.
- (Optional) GitHub release `v4.4.0` (если `gh release create` выполнен).

### Будет изменено в коммитах hygiene-ветки

- [`docs/notes/WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md`](WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md) — header + footer.
- [`docs/notes/BUG_LOG.md`](BUG_LOG.md) — BUG-027 status row, BUG-022 closure annotation.
- [`docs/notes/PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md`](PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md) — header Closed timestamp.
- [`docs/notes/PARITY_DECISION_TRACKING.md`](PARITY_DECISION_TRACKING.md) — header status hard-line.
- (Optional) `CHANGELOG.md` — `[Unreleased]` → `[4.4.0]` cut.
- (Optional) `README.md` — Wave 1 closure section.

### Будет изменено на prod VPS

- `~/TG_parser/.env` — `GRAFANA_WEBHOOK_TOKEN=crsr_…` добавлен.
- `~/TG_parser` git HEAD pulled to post-merge SHA.
- `tg_parser_grafana` контейнер recreated (для подхвата нового env).
- (Optional) compose services `tg_parser` / `mcp` / `tg_bot` rebuild + recreate (containers `tg_parser` / `tg_parser_mcp` / `tg_parser_bot`) если оператор хочет полную синхронизацию (не требуется для docs-only PR).

### Будет создано в GitHub

- 1 PR для closure-ветки (will be merged then deleted).
- 1 PR для hygiene-ветки (will be merged then deleted).
- 1 короткоживущий issue от synthetic alert (закрыт с пометкой «synthetic; closure session smoke»).

---

## §10 — Risk register

> Топ-3 риска для самой closure-сессии (не для продукта). Mitigation встроен в шаги § 5.

| ID | Risk | Severity | Likelihood | Mitigation |
|---|---|---|---|---|
| **R-1** | **Merge conflict** с свежими PR в `main` (если между audit'ом 2026-06-06 и closure-сессией кто-то landed PR'ы) | Medium | Low–Medium | Pre-flight § 3 проверяет `git log main..HEAD` + `git log HEAD..origin/main`. Конфликты ожидаются только в `BUG_LOG.md` / `CHANGELOG.md` / `ROADMAP_KARPATHY_LIKE_LIVING_KB.md` — структурно понятные диффы. Rebase вручную, сохраняя aggregate-marker cross-links. Если конфликт неразрешимо большой → STOP, surface, новая planning-сессия. |
| **R-2** | **Prod webhook auth fails** (неправильный token format, Grafana не подхватил env после recreate, или contact point misconfigured) | Medium | Low | Шаг 3.1 verify через `grep '^GRAFANA_WEBHOOK' .env` + `docker logs ... \| grep -iE 'webhook\|error'`. Шаг 3.2 — curl smoke (cheap, обратимый); если 401/403 → проверить (a) token строкой совпадает с operator `$TG_PARSER_WATCH_WEBHOOK_AUTH`, (b) Grafana contact point header настроен, (c) recreate Grafana ещё раз. Rollback: restore из `.env.backup-*`. |
| **R-3** | **Drift между local docs и prod state** (например, local `git rev-parse origin/main` ≠ что реально в `gh pr list` из-за неполного fetch, или prod HEAD ушёл вперёд из-за hotfix) | Low | Low | Pre-flight § 3 fetches origin + verifies prod HEAD. Финальная верификация § 5.6 — двойная проверка через `git log` и SSH. Если prod ушёл вперёд от ожидаемого `ea826b7` → STOP, surface, расследовать hotfix перед тем как накатывать post-merge SHA. |

### Дополнительные lesser risks

| Risk | Mitigation |
|---|---|
| CI flake на `Test Python 3.12` (network, transient) | Re-run check: `gh pr checks <N> --rerun`. |
| Grafana password rotation (§ C cleanup) забыт / отложен | Задокументировать в финальном aggregate marker § 8 как deferred operator item — не блокирует closure. |
| Optional `v4.4.0` tag pushed without `--ff-only` на main → diverged | Не выполнять `tag` до того как `git pull --ff-only` прошёл успешно. |

---

## §11 — Rollback plan

| Шаг | Что пошло не так | Rollback |
|---|---|---|
| **1 (PR/merge)** | CI красный required check, merge провалился | Не мержить. Расследовать red check. PR остаётся открытым; aggregate marker остаётся в closure-ветке. |
| **1 (PR/merge)** | Squash merge сделан, но в `main` обнаружен битый cross-link / typo | Open follow-up PR с doc-only fix; **не делать revert** squash-merge (aggregate marker уже в audit trail). |
| **3.1 (token)** | `.env` сломался (потерян old value, синтаксическая ошибка) | `cp .env.backup-<TIMESTAMP> .env` → `docker compose up -d --force-recreate --no-deps tg_parser_grafana`. |
| **3.1 (token)** | Grafana не стартует после recreate | `docker logs tg_parser_grafana` для root cause. Если provisioning сломался — `cp .env.backup-*` + recreate. Если глубже — escalate (Grafana stack независим от bot/api/mcp). |
| **3.2 (E2E)** | Curl 401 / 403 | Verify token и Cursor automation `7b35ca01` enabled; см. R-2 mitigation. Issue не создан = ничего откатывать (curl idempotent). |
| **3.2 (E2E)** | Issue создался, но с другим prefix / classifier дал mis-routing | Закрыть issue с пометкой; зафиксировать наблюдение в `INBOX.md` для будущего Step 5+ tuning. Не блокирует closure. |
| **3.3 (cleanup § A)** | Disable automation вернул ошибку | Re-check через `get_automation` schema; если automation уже disabled — игнор (idempotent). Если permissions issue / network / MCP unavailable — STOP, surface, **escalate к оператору**. § A — BLOCKING для closure (см. § 7 DoD); без disable single-shot automations Wave 1 closure не считается завершённой. § B / § C / § D — operator-discretion (документируются как deferred в § 8 aggregate marker). |
| **3.4 (prod pull)** | `git pull --ff-only` отказал (диверг) | НЕ делать `reset --hard` сразу. Сначала `git log HEAD..origin/main` и `git log origin/main..HEAD` чтобы понять что на проде локально; если только hot-fix tag на проде — discuss with operator. |
| **3.4 (prod pull)** | Контейнеры стали unhealthy после pull (хотя docs-only) | Re-pull предыдущий SHA через `git reset --hard <pre-deploy-sha>` (сохранён в `/tmp/pre-deploy-sha.txt`); `docker compose restart`. |
| **4 (hygiene)** | ruff упал на docs-only PR (mardown в Python pseudo-code?) | Проверить какой файл триггерит — закрывающие backticks / случайные code fences. Fix → re-check. |
| **5 (tag)** | `v4.4.0` запушен на не тот SHA | `git tag -d v4.4.0` локально + `git push --delete origin v4.4.0` (force-delete tag — допустимо для свежего tag без published release). Re-tag на правильный SHA. |

---

## §12 — Cross-references

| Документ | Зачем |
|---|---|
| [`docs/notes/REVIEW_2026-06-03_WAVE1_DONE.md`](REVIEW_2026-06-03_WAVE1_DONE.md) | **Aggregate authority.** § 2 Step 5 ops status (PARTIAL → PASS patch — § 5.4.5), § 5 deferred BUGs, § 8 remaining items (completed items flip — § 5.4.5), § 9 readiness checklist, § 12 verdict. |
| [`docs/notes/WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md`](WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md) | Watch-window файл который нужно закрыть (header + footer). |
| [`docs/runbooks/WAVE1_STEP4_VPS_POST_CLOSURE_CLEANUP.md`](../runbooks/WAVE1_STEP4_VPS_POST_CLOSURE_CLEANUP.md) | Step 5 cleanup checklist § A–D. |
| [`docs/runbooks/WAVE1_STEP4_VPS_OPERATOR_MANUAL_ACTIONS.md`](../runbooks/WAVE1_STEP4_VPS_OPERATOR_MANUAL_ACTIONS.md) | Реальные команды для prod ops (curl snippets, Grafana setup). |
| [`docs/runbooks/WAVE1_STEP4_VPS_WATCH_AUTOMATIONS.md`](../runbooks/WAVE1_STEP4_VPS_WATCH_AUTOMATIONS.md) | Реестр Cursor Automations (`2bd25769`, `f93e557a`, `7b35ca01`). |
| [`docs/notes/BUG_LOG.md`](BUG_LOG.md) | Backbone — нужно править BUG-027 / BUG-022 rows. |
| [`docs/notes/PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md`](PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md) | Operational план Wave 1 — добавить `Closed: 2026-06-03` в header. |
| [`docs/notes/PARITY_DECISION_TRACKING.md`](PARITY_DECISION_TRACKING.md) | Parity observations журнал — header status update. |
| [`docs/notes/PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md`](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md) | § 5.3 Decision Point matrix — reference, не правка. |
| [`docs/notes/ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) | Уже обновлён в closure-ветке; финальная верификация что step 3/4 = DONE. |
| [`docs/quality/AGENT_PLAYBOOK.md`](../quality/AGENT_PLAYBOOK.md) | Quality lifecycle conventions (no auto-commit, DONE marker structure). |
| [`AGENTS.md`](../../AGENTS.md) | Workspace rules (forbidden actions). |
| [`CHANGELOG.md`](../../CHANGELOG.md) | `[Unreleased]` имеет Wave 1 aggregate closure блок; optional cut → `[4.4.0]`. |
| [`docs/adr/0009-idempotency.md`](../adr/0009-idempotency.md) | Reference для BUG-022 closure annotation. |
| [`START_PROMPT_SPRINT_WAVE1_STEP4_2026-05-23.md`](START_PROMPT_SPRINT_WAVE1_STEP4_2026-05-23.md), [`START_PROMPT_SPRINT_WAVE1_STEP3_2026-05-21.md`](START_PROMPT_SPRINT_WAVE1_STEP3_2026-05-21.md), [`START_PROMPT_POST_BUG050_FOLLOWUPS_2026-06-02.md`](START_PROMPT_POST_BUG050_FOLLOWUPS_2026-06-02.md), [`START_PROMPT_PRESERVE_TG_URLS_2026-06-02.md`](START_PROMPT_PRESERVE_TG_URLS_2026-06-02.md) | Format-precedents этого промпта. |

---

## §13 — После закрытия (НЕ часть этой сессии)

После того как closure-сессия объявит DoD met:

1. **Wave 1.5 — Operational Dogfooding** (параллельная привычка, не sprint):
   - Daily TG_parser use → signals в `docs/quality/INBOX.md`.
   - Light external validation: A4 AI integrators с HTTP API (если signal появится).
   - Не sprint, не sub-session — это образ жизни между Wave 1 и Wave 2.
   - Открывается **отдельным** start-prompt'ом если нужно скоординировать что-то конкретное.

2. **Wave 2 — Planning session** (отдельная planning sub-session):
   - Audit бэклога: BUG-008 / 019 / 020 / 021 / 025 / 026 / 027 + любые new signals из Wave 1.5.
   - Decision: какой audience driver следующий (см. [`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 5.3](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md) Decision Point matrix).
   - Артефакт: новый `PLAN_WAVE2_*` + соответствующий `START_PROMPT_PLANNING_WAVE2_*`.
   - **Не запускать в этой closure-сессии.**

3. **Optional follow-up tickets** (если closure-сессия отложила):
   - Grafana admin password rotation (§ C cleanup).
   - Telegram-side test artifacts cleanup (§ D).
   - Schema-probe automations delete (§ B).

---

## §14 — История промпта

| Дата | Изменение |
|---|---|
| 2026-06-06 | Первая версия. Создана 2026-06-06 audit-сессией по итогам полного аудита Wave 1 closure state. Фиксирует scope трёх треков (merge / Step 5 ops / hygiene) + optional (release tag + README). Anti-scope: Wave 2 planning, Wave 1.5 dogfooding, BUG-008/019/020/021/025/026/027 code fixes, `docs/methodology/**`, `pyproject.toml`. DoD: 11 BLOCKING критериев + 3 OPTIONAL. Time budget: 2.5–3.5h без optional, 3–4h с optional. Risk register: R-1 merge conflict / R-2 webhook auth / R-3 docs-vs-prod drift. Format-precedent: `START_PROMPT_SPRINT_WAVE1_STEP4_2026-05-23.md`. |
| 2026-06-06 (rev 2 — self-review fixes) | Применены P0/P1/P2 правки по self-review: (P0) anti-scope §3 уточнён — НЕ трогаем **код** BUG-027, но docs-only status sync = in-scope hygiene; (P0) curl Authorization header не дублирует `Bearer` префикс (env-var уже содержит `Bearer crsr_…`); (P1) добавлен §5.4.5 «Aggregate marker patch» (REVIEW §2 PARTIAL→PASS, §8 completed items flip, §9 readiness checklist) + §5.4.6 commit + §5.4.7 hygiene PR create + CI + squash merge; (P1) §7 DoD получил 2 новых BLOCKING checkbox (hygiene PR merged + aggregate marker §2/§8/§9 updated); (P2) curl payload flat-формат (alertname/summary top-level), URL fix `api.cursor.com → api2.cursor.sh/automations/webhook/7b35ca01-…`, compose service `tg_parser_mcp → mcp`, time budget §4/§8 reconciled на 2.5–3.5h без optional / 3–4h с optional, PARITY header дата = `2026-06-06 closure session`, все `2026-06-XX` placeholders заменены на `2026-06-06`, rollback row § A clarified (BLOCKING — escalate operator on failure). §12 cross-ref расширен указанием sub-секций aggregate marker. Шаг 3 в §4 объединённой таблицы целей поднят с HYGIENE → BLOCKING. |
