# Runbook — Wave 1 Step 3 Deploy + 24h Watch

**Last reviewed:** 2026-05-22 (S3.1 Phase C — post PR #89 merge).

**Назначение:** безопасно задеплоить Wave 1 step 3 (Surface Parity: P-1/P-2 HTTP API, ENH-9, BUG-022, ADR 0009 idempotency) на production VPS и открыть 24h watch window.

**Когда применять:** первый деплой PR [#89](https://github.com/AlexEfimov/TG_parser/pull/89) (`a30abd5`) или hot-fix на watchlist/digest HTTP / idempotency middleware.

**Связанные runbook'и:** [`wave1_step3_idempotency_dedupe.md`](wave1_step3_idempotency_dedupe.md), [`F5C_DEPLOY_AND_WATCH.md`](F5C_DEPLOY_AND_WATCH.md) (structural precedent), [`SAFE_MIGRATION_ON_DEV.md`](SAFE_MIGRATION_ON_DEV.md).

**VPS:** `ssh -p 2296 user@212.72.189.15`, repo `~/TG_parser` (см. [`SERVER_ARCHITECTURE.md`](../SERVER_ARCHITECTURE.md)).

---

## Pre-deploy checklist

| # | Что | Как проверить |
|---|---|---|
| 1 | `main` @ `a30abd5` (или позже) | `git log -1 --oneline` на VPS после `git pull` |
| 2 | CI green на merge-коммите | GitHub PR #89 checks |
| 3 | Ingestion Alembic head **до** наката = `e9f0a1b2c3d5` | `docker compose exec tg_parser tg-parser db current --db ingestion` |
| 4 | **Нет duplicate natural keys** | SQL из [`wave1_step3_idempotency_dedupe.md` § 1](wave1_step3_idempotency_dedupe.md) — migration `f1a2b3c4d5e6` abort'ит при дубликатах |
| 5 | Контейнеры healthy | `docker compose ps` — `tg_parser`, `mcp`, `tg_bot` Up (healthy) |

> **2026-05-22 prod note:** на проде найдено 3 группы `(user_id, title)` дубликатов (inactive soft-deleted rows). Dedupe по runbook § 2 выполнен до migration.

---

## Deploy

### 1. Pull + build

```bash
ssh -p 2296 user@212.72.189.15
cd ~/TG_parser
git fetch origin main && git checkout main && git pull origin main
git log -1 --oneline   # ожидается a30abd5 Merge PR #89

docker compose build tg_parser mcp tg_bot
```

### 2. Pre-migration dedupe (если нужно)

См. [`wave1_step3_idempotency_dedupe.md`](wave1_step3_idempotency_dedupe.md). Повторить inspection queries; при `COUNT > 0` — DELETE по ranked CTE **до** upgrade.

### 3. Rolling restart + migration

```bash
docker compose --profile bot up -d --no-deps tg_parser mcp tg_bot
# дождаться healthy
docker compose exec tg_parser tg-parser db upgrade --db ingestion
docker compose exec tg_parser tg-parser db current --db ingestion
# → f1a2b3c4d5e6 (head)
```

Ожидаемый лог upgrade: `Running upgrade e9f0a1b2c3d5 -> f1a2b3c4d5e6`.

### 4. Production HTTP smoke (localhost на VPS)

Использовать ключ из `API_KEYS` JSON (не путать с LLM `OPENAI_API_KEY`):

```bash
API_KEY=$(docker compose exec -T tg_parser python3 -c \
  'import json,os; print(next(iter(json.loads(os.environ["API_KEYS"]).keys())))')
BASE=http://127.0.0.1:8000/api/v1
CHAT=999001   # smoke chat_id

# 201 + created:true
curl -sS -X POST "$BASE/watchlists" -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"title":"smoke","channel_ids":["profendocrinologist"],"chat_id":'$CHAT'}'

# Idempotency-Key replay + mismatch 422 IdempotencyKeyMismatch
# Invalid cron → 422 InvalidCron
# DELETE digest → 204 then 404
# workspace_id foreign → 404 WorkspaceNotFound
```

Полный чеклист — sprint prompt § 6 + [`WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md`](../notes/WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md).

---

## 24h watch

**Window:** от timestamp рестарта `tg_parser` / `tg_parser_mcp` / `tg_parser_bot` + 24h.

**Метрики:**

| Metric | Expect |
|---|---|
| `tg_idempotency_keys_hit_total{result=hit\|miss\|mismatch}` | `mismatch` ≈ 0 |
| `tg_idempotency_keys_table_size` | снижается после hourly cleanup (`0 * * * *`) |
| `tg_watchlist_subscribe_total`, `tg_digest_subscribe_total` | emit на subscribe paths |
| `tg_api_requests_total{status=5xx}` на `/api/v1/watchlists`, `/api/v1/digests` | 0 |
| F11 `tg_watchlist_score`, F6 `tg_digest_runs_total` | no regression |

**Closure:** заполнить [`REVIEW_2026-05-21_WAVE1_STEP3_DONE.md`](../notes/REVIEW_2026-05-21_WAVE1_STEP3_DONE.md) § 2–3, § 6 после GREEN watch.

---

## Rollback (emergency)

1. `git checkout <pre-deploy-sha>` + rebuild + restart (как F5C runbook).
2. `tg-parser db downgrade --db ingestion -1` **только** если нет новых подписок с `workspace_id` / idempotency rows, которые нельзя потерять — иначе forward-fix.
3. См. migration `downgrade()` в `20260521_wave1_step3_foundation.py`.
