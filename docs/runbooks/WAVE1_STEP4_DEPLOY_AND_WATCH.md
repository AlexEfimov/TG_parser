# Runbook — Wave 1 Step 4 Deploy + 24h Watch

**Last reviewed:** 2026-05-24 (implementation session).

**Назначение:** безопасно задеплоить ADR 0008 (polymorphic subscription target + channel digest publish) и открыть 24h watch window.

**Pre-req Alembic head before deploy:** `f1a2b3c4d5e6` → after deploy: `a8b7c6d5e4f3`.

## Pre-deploy

```bash
docker exec tg_parser_postgres pg_dump -U tg_parser_user -d tg_parser \
  -t digest_subscriptions -t watch_interests > pre_step4_backup.sql
```

## Deploy

```bash
git pull && docker compose build tg_parser tg_parser_bot tg_parser_mcp
docker compose up -d
docker exec tg_parser tg-parser db upgrade --db ingestion
```

## Post-deploy smoke (T+0..15m)

| Check | Command / expectation |
|---|---|
| Legacy chat digest | `POST /api/v1/digests` with `chat_id` only → 201, `target.kind=chat` |
| Channel digest | `POST /api/v1/digests` with `target={kind:channel, channel_id:'@…'}` → 201 |
| Mutual exclusion | Both `chat_id` + `target` → 422 |
| Regression DELETE | `DELETE /api/v1/digests/{id}` → 204 |

## 24h watch

- `tg_digest_channel_publish_total{result="success"}` — operator smoke after channel subscribe
- `tg_digest_channel_publish_total{result="permission_denied"}` — expect 0 in steady state
- Existing chat-target prod digest cron — no regression (BUG-028 guard)

See [`docs/notes/START_PROMPT_SPRINT_WAVE1_STEP4_2026-05-23.md`](../notes/START_PROMPT_SPRINT_WAVE1_STEP4_2026-05-23.md) § 7.
