# Hotfix — Runbook container/service nomenclature (2026-05-08)

---

## Что это

Срочный docs-only hotfix двух production runbook'ов, в которых имена docker-сервисов
и контейнеров **не соответствуют фактическому `docker-compose.yml`**. Применять
такие команды напрямую = либо смотреть не тот контейнер (false-GREEN observability),
либо `docker compose: service "X" not found` ошибка.

**Обнаружено:** в self-review актуальной документации проекта 2026-05-07 (после Session J).
Issue фиксирует **C-1** и **C-2** из общего аудит-отчёта.

**Скоп:** docs-only, **никаких** code changes / migrations / deploy. Применять можно
**в параллель** с 24h watch Session J (не блокирует ни Session K, ни F4-B planning).

---

## Опеner (вставить в новый чат)

> Стартую mini-hotfix runbook nomenclature.
> Прочитай `docs/notes/START_PROMPT_HOTFIX_RUNBOOK_NOMENCLATURE_2026-05-08.md` целиком +
> `docker-compose.yml` (строки 1-220, особенно `services:` keys и `container_name:`).
> Затем исполни § 2 (правки `BOT_LLM_FALLBACK.md`) и § 3 (правки `F5C_DEPLOY_AND_WATCH.md`).
> Branch: `docs/hotfix-runbook-nomenclature-2026-05-08`.
> Single PR, 1 atomic commit (либо 2 — fixed BOT + fixed F5C — на твой выбор).
> **НЕ** трогать код / миграции / docker-compose.yml.
> **НЕ** трогать другие runbook'и (DEV_RESURRECTION, ANTHROPIC_BILLING, SAFE_MIGRATION) —
> они в self-review были помечены как «совпадают с compose» (минимально).

---

## 0. Pre-flight (минимальный — это docs-only)

```bash
# 1. Убедиться что мы на main и worktree чистый
git status
git checkout main
git pull --ff-only origin main

# 2. Подтвердить container_name / service mapping (не должно меняться)
grep -E '^  [a-z_-]+:$|container_name:' docker-compose.yml | head -25
# Expected:
#   postgres → tg_parser_postgres
#   tg_parser → tg_parser (API)
#   mcp → tg_parser_mcp
#   tg_bot → tg_parser_bot   (profile: bot)
#   prometheus → tg_parser_prometheus
#   grafana → tg_parser_grafana
```

Никаких production checks не нужно.

---

## Карта compose-имён (canonical reference)

| Назначение | service (`docker compose ...`) | container_name (`docker logs ...`) | profile |
|---|---|---|---|
| API + scheduler | `tg_parser` | `tg_parser` | — (default) |
| MCP server | `mcp` | `tg_parser_mcp` | — (default) |
| Telegram bot | `tg_bot` | `tg_parser_bot` | **`bot`** |
| PostgreSQL | `postgres` | `tg_parser_postgres` | — |
| Prometheus | `prometheus` | `tg_parser_prometheus` | — |
| Grafana | `grafana` | `tg_parser_grafana` | — |
| Caddy | `caddy` | `tg_parser_caddy` | `caddy` |
| Ollama | `ollama` | `tg_parser_ollama` | `ollama` |

> **Правило для runbook'ов:**
> - В `docker compose <verb> <X>` — использовать **service** (`tg_parser`, `mcp`, `tg_bot`).
> - В `docker logs <X>` / `docker exec <X>` — использовать **container_name** (`tg_parser`, `tg_parser_mcp`, `tg_parser_bot`).
> - Для bot — **всегда** добавлять `--profile bot` (или `COMPOSE_PROFILES=bot`),
>   иначе `docker compose up tg_bot` молча не сделает ничего.

---

## 1. Branch + GH issue

```bash
git checkout -b docs/hotfix-runbook-nomenclature-2026-05-08

# Опционально — GH issue для traceability
gh issue create \
  --title "docs(runbooks): fix container/service nomenclature in BOT_LLM_FALLBACK + F5C_DEPLOY_AND_WATCH" \
  --label "documentation,priority/p0" \
  --body "Self-review 2026-05-07 обнаружил что pre-flight checks Sessions H/I/J и runbook deploy команды используют неверные compose service / container names. См. \`docs/notes/START_PROMPT_HOTFIX_RUNBOOK_NOMENCLATURE_2026-05-08.md\`."
```

---

## 2. `docs/runbooks/BOT_LLM_FALLBACK.md` — правки

### 2.1 Список замен

| # | Где | Было | Стало | Причина |
|---|---|---|---|---|
| 1 | § 2 (pre-flight, line ~31) | `docker logs --since 30m tg_parser 2>&1 \| grep -E "gemini_*"` | `docker logs --since 30m tg_parser_bot 2>&1 \| grep -E "gemini_*"` | bot-метрики живут в bot-контейнере |
| 2 | § 3.4 (full rebuild, line ~84-86) | `cd ~/TG_parser && GEMINI_API_KEY=... docker compose up -d --no-deps --force-recreate tg_parser` | `cd ~/TG_parser && GEMINI_API_KEY=... docker compose --profile bot up -d --no-deps --force-recreate tg_bot` | bot service = `tg_bot`, требует `--profile bot` |
| 3 | § 5 (post-procedure, line ~111-112) | `docker logs --since 30m tg_parser 2>&1 \| grep -cE "gemini_*"` | `docker logs --since 30m tg_parser_bot 2>&1 \| grep -cE "gemini_*"` | то же что #1 |

### 2.2 Дополнения (новые блоки)

**Добавить после § 3.2 «Применить runtime override»** (перед § 3.3 smoke test):

```markdown
> **ADR 0005 D-1 reminder.** `set_llm_config(scope="global", ...)` **не** влияет на
> бота — global override игнорируется для `scope="bot"` (verified в
> `LLMConfigManager.resolve()`). Для смены модели бота используйте только
> `scope="bot"`. Это by design (см. ADR 0005 § «Решение D-1»).
```

**Добавить новый § 4.5 «Rollback после env-recreate (§ 3.4)»** перед § 5:

```markdown
### 4.5 Rollback после env-recreate (§ 3.4)

Если применяли § 3.4 (рестарт bot-контейнера с другим `GEMINI_API_KEY`) — `reset_llm_config(scope="bot")`
**недостаточно** (это runtime override, не env). Полный rollback:

\```bash
# 1. Вернуть основной ключ в .env (либо просто удалить override-line)
ssh -p 2296 user@212.72.189.15 'cd ~/TG_parser && \
  sed -i "/^GEMINI_API_KEY=/c\GEMINI_API_KEY=<original_key>" .env'

# 2. Recreate bot-контейнер чтобы подхватил .env
ssh -p 2296 user@212.72.189.15 'cd ~/TG_parser && \
  docker compose --profile bot up -d --no-deps --force-recreate tg_bot'

# 3. Verify
ssh -p 2296 user@212.72.189.15 'docker exec tg_parser_bot env | grep GEMINI_API_KEY'
\```
```

### 2.3 Update header `Last reviewed`

```markdown
**Last reviewed:** 2026-05-08 (hotfix — container/service nomenclature corrected per docker-compose.yml).
```

---

## 3. `docs/runbooks/F5C_DEPLOY_AND_WATCH.md` — правки

### 3.1 Список замен

| # | Где | Было | Стало |
|---|---|---|---|
| 1 | Pre-deploy table row 4 | `ssh prod 'cd app && tg-parser db current --db processing'` | `ssh -p 2296 user@212.72.189.15 'cd ~/TG_parser && docker compose exec tg_parser tg-parser db current --db processing'` |
| 2 | Pre-deploy table row 6 | `docker compose exec postgres-processing /docker/backup.sh` | `docker compose exec postgres /docker/backup.sh` (или скорректировать на actual путь backup-скрипта) |
| 3 | § 1 «Pull кода» (line ~37-38) | `ssh prod` + `cd /opt/tg_parser` | `ssh -p 2296 user@212.72.189.15` + `cd ~/TG_parser` (consistent с `SERVER_ARCHITECTURE.md` и BOT_LLM_FALLBACK) |
| 4 | § 3 «Перезапустить сервисы» (line ~70) | `docker compose up -d --no-deps api mcp bot` | `docker compose --profile bot up -d --no-deps tg_parser mcp tg_bot` |
| 5 | § 4 «Smoke tests» line ~84, 88, 93 | `docker compose exec api ...` | `docker compose exec tg_parser ...` |
| 6 | § 4 line ~98 | `docker compose logs -f api \| grep -i "f5c_resummarize"` | `docker compose logs -f tg_parser \| grep -i "f5c_resummarize"` |
| 7 | Tripwire #1 (line ~236) | `docker compose logs api \| grep -E ...` | `docker compose logs tg_parser \| grep -E ...` |
| 8 | Tripwire #1 (line ~237) | `docker compose restart api` | `docker compose restart tg_parser` |
| 9 | Tripwire #1 (line ~239) | `docker compose restart api` | `docker compose restart tg_parser` |
| 10 | Tripwire #2 (line ~246) | `docker compose ps \| grep -E 'api\|scheduler'` | `docker compose ps \| grep -E 'tg_parser'` (scheduler внутри `tg_parser` контейнера, отдельного сервиса нет) |
| 11 | Tripwire #3 (line ~257) | `docker compose logs api ...` | `docker compose logs tg_parser ...` |
| 12 | Rollback line ~281 | `docker compose restart api` | `docker compose restart tg_parser` |
| 13 | Rollback line ~286 | `docker compose pull && docker compose up -d --no-deps api mcp bot` | `docker compose pull && docker compose --profile bot up -d --no-deps tg_parser mcp tg_bot` |
| 14 | Helper-script line ~304-305 | `ssh prod 'cd /opt/tg_parser && ./docker/f5c_watch.sh'` | `ssh -p 2296 user@212.72.189.15 'cd ~/TG_parser && ./docker/f5c_watch.sh'` |
| 15 | Cron line ~313 | `/opt/tg_parser/docker/f5c_watch.sh` | `~/TG_parser/docker/f5c_watch.sh` (или абсолютный путь домашней директории — uniform с git pull location) |

> **Важно — paths.** В существующем тексте смешаны `/opt/tg_parser` и `app`; в
> SERVER_ARCHITECTURE.md и в BOT_LLM_FALLBACK.md используется `~/TG_parser`.
> Унифицировать на `~/TG_parser` (рекомендация). Если фактический deploy path
> другой — verify через `ssh -p 2296 user@212.72.189.15 'pwd && ls TG_parser/docker-compose.yml'` **до** правки runbook'а.

### 3.2 Update Last reviewed (если есть header — добавить)

```markdown
**Last reviewed:** 2026-05-08 (hotfix — container/service nomenclature corrected;
unified deploy path with SERVER_ARCHITECTURE.md).
```

---

## 4. Cross-runbook sweep (опционально, low priority)

**ANTHROPIC_BILLING_RECOVERY.md** + **DEV_RESURRECTION.md** + **SAFE_MIGRATION_ON_DEV.md**:

```bash
# Quick check
grep -nE 'docker compose.*(api|bot)\b' docs/runbooks/*.md | \
  grep -vE 'tg_parser|tg_bot'
```

Если grep найдёт matches — применить тот же mapping. Из self-review известно что
ANTHROPIC + SAFE_MIGRATION чистые, DEV_RESURRECTION уже использует правильные имена.

**НЕ обязательно** — основной impact в BOT_LLM_FALLBACK + F5C; остальные могут пойти
opportunistically в следующий runbook touch.

---

## 5. Verification

### 5.1 Self-review checklist

```
[ ] docs/runbooks/BOT_LLM_FALLBACK.md — все 3 замены применены
[ ] docs/runbooks/BOT_LLM_FALLBACK.md — § 4.5 (rollback after env recreate) добавлен
[ ] docs/runbooks/BOT_LLM_FALLBACK.md — D-1 reminder добавлен
[ ] docs/runbooks/F5C_DEPLOY_AND_WATCH.md — все 15 замен применены
[ ] grep "tg_parser " (с пробелом) docs/runbooks/*.md — нет упоминаний `api`/`bot` как compose service-имён
[ ] grep "/opt/tg_parser" docs/runbooks/F5C_DEPLOY_AND_WATCH.md — заменены на `~/TG_parser`
[ ] grep "ssh prod" docs/runbooks/F5C_DEPLOY_AND_WATCH.md — заменены на `ssh -p 2296 user@212.72.189.15`
[ ] grep "postgres-processing" — 0 matches (заменено на `postgres`)
```

### 5.2 No-code verification

```bash
git diff --stat origin/main..HEAD
# Expected: ONLY docs/runbooks/BOT_LLM_FALLBACK.md + docs/runbooks/F5C_DEPLOY_AND_WATCH.md
# 0 changes in tg_parser/, tests/, docker-compose.yml, prompts/, migrations/
```

### 5.3 (опционально) Live smoke на проде

После merge — на VPS прогнать «новые» pre-flight команды чтобы убедиться что они
выдают данные:

```bash
ssh -p 2296 user@212.72.189.15 \
  'docker logs --since 30m tg_parser_bot 2>&1 | grep -cE "gemini_empty|gemini_no_candidates|gemini_blocked|gemini_api_error"'
# Expected: число (вероятно 0)

ssh -p 2296 user@212.72.189.15 \
  'docker compose --profile bot ps tg_bot'
# Expected: tg_parser_bot Up
```

### 5.4 CI

Все 5 checks должны пройти (lint docs, test python — no code change).

---

## 6. PR / commit plan

**Branch:** `docs/hotfix-runbook-nomenclature-2026-05-08`

**Commit option A — single atomic:**
```
docs(runbooks): fix container/service nomenclature in BOT_LLM_FALLBACK + F5C

Pre-flight checks Sessions H/I/J + F5-C deploy commands использовали неверные
compose service names (`api`, `bot` вместо `tg_parser`, `tg_bot`) и container
names (`tg_parser` вместо `tg_parser_bot` для bot-метрик), приводя к false-GREEN
observability и compose service-not-found ошибкам.

- BOT_LLM_FALLBACK.md: pre-flight + post-procedure grep targets `tg_parser_bot`,
  full rebuild через `docker compose --profile bot up tg_bot`. Добавлен D-1
  reminder + § 4.5 rollback после env recreate.
- F5C_DEPLOY_AND_WATCH.md: 15 замен compose service / container names; pre-deploy
  postgres backup, smoke tests, tripwire responses, rollback команды переведены на
  фактические имена. Унифицирован SSH access pattern и deploy path с
  SERVER_ARCHITECTURE.md (~/TG_parser, ssh -p 2296).

Refs: self-review актуальной документации 2026-05-07 (C-1, C-2).
docker-compose.yml services: postgres, tg_parser, mcp, tg_bot (profile=bot),
prometheus, grafana. Container names — pattern tg_parser_*.
```

**Commit option B — два атомарных** (если PR-review требует separation):
1. `docs(runbooks): BOT_LLM_FALLBACK — fix container nomenclature + add D-1 reminder + env-rollback`
2. `docs(runbooks): F5C_DEPLOY_AND_WATCH — fix compose service/container names + unify deploy path`

Predпочтительно **option A** — это всё одна логическая правка от одного root cause.

**PR title:** `docs(runbooks): fix container/service nomenclature in BOT_LLM_FALLBACK + F5C`

PR body:
- Краткий контекст («self-review нашёл расхождение между runbook'ами и docker-compose.yml»);
- Канонический mapping (см. § «Карта compose-имён» этого промпта);
- No-code verification ссылка;
- Closes optional GH issue if created in § 1.

---

## 7. Risks

**R-1 — Deploy path фактически другой (`/opt/...` vs `~/TG_parser`).** Mitigation:
verify до правки `ssh -p 2296 user@212.72.189.15 'pwd && ls TG_parser/docker-compose.yml'`.
Если другой path — оставить runbook на actual path и обновить SERVER_ARCHITECTURE.md
в отдельном commit (доп. scope).

**R-2 — `docker compose exec postgres /docker/backup.sh` — фактического `/docker/backup.sh` может не быть.**
Mitigation: до commit'а verify через `ssh ... 'docker compose exec postgres ls /docker/'`. Если script отсутствует —
заменить на актуальную процедуру backup'а из SERVER_ARCHITECTURE.md или на `pg_dump` напрямую.

**R-3 — `--profile bot` забыт где-то ещё.** Mitigation: § 4 cross-runbook sweep (опционально).

---

## 8. Anti-scope

- **НЕ** трогать `docker-compose.yml` (любые правки там — отдельный sprint).
- **НЕ** трогать `SERVER_ARCHITECTURE.md` (его scrape targets fix запланирован в Session K extended scope).
- **НЕ** трогать ADR 0005 (Variant A finalization тоже в Session K).
- **НЕ** включать в этот PR никакой code change / migration / config / prompt yaml.
- **НЕ** запускать live deploy / smoke на проде (§ 5.3 — опционально и read-only).

---

## 9. Appendix — Key references

| Документ | Зачем |
|---|---|
| `docker-compose.yml` | Source of truth для services / container_name / profiles |
| `docs/SERVER_ARCHITECTURE.md` | SSH access + deploy path canonical |
| `docs/adr/0005-bot-llm-provipovider-flexibility.md` § «Решение D-1» | D-1 global immunity reminder для BOT runbook |
| Self-review report (chat 2026-05-07) | Источник C-1 / C-2 issues |
| Session J pre-flight check `tg_parser` mistake | Симптом, который привёл к detection (false-GREEN-by-luck) |

---

## Appendix B — История правок

| Дата | Изменение |
|---|---|
| 2026-05-08 ~XX:XX UTC+4 | Первая версия. Источник: self-review актуальной документации проекта 2026-05-07 (C-1, C-2 в общем отчёте). Создан как **срочный pre-Session-K hotfix**, чтобы production runbook'и BOT_LLM_FALLBACK и F5C_DEPLOY_AND_WATCH не содержали неверные compose-имена при ближайшем incident response. |
| 2026-05-08 ~00:00 UTC+4 | **Сессия выполнена.** Branch `docs/hotfix-runbook-nomenclature-2026-05-08`, single atomic commit `827078c` (option A — preferred per § 6), PR [#63](https://github.com/AlexEfimov/TG_parser/pull/63) (`Closes #62`). Применены все 18 замен (3 BOT § 2.1 + 15 F5C § 3.1) + дополнительно 2 FAQ-замены `docker compose logs api` → `... tg_parser` для consistency с § 5.1 self-review требованием «нет упоминаний `api`/`bot` как compose service-имён». Добавлены: D-1 reminder в BOT § 3.2, § 4.5 env-rollback в BOT, Last reviewed `2026-05-08` в обоих файлах, Last reviewed header в F5C (раньше отсутствовал). Cross-runbook sweep clean (false-positive `--profile bot` в DEV_RESURRECTION.md — flag, не service). `git diff --stat` = только `docs/runbooks/` (2 files, +63 / −28). Issue #62 ожидает auto-close при merge PR #63. |
