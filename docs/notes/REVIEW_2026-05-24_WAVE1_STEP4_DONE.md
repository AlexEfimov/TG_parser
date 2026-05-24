# REVIEW — Wave 1 Step 4 (Shareable Digest / ADR 0008)

**Status:** IMPLEMENTATION COMPLETE — **24h watch PENDING** (pre-merge marker).

**Branch:** `feat/wave1-step4-shareable-digest-2026-05-24` (uncommitted at session end).

## Summary

ADR 0008 Option B implemented: polymorphic `target` on digest + watchlist subscribe across HTTP, MCP, Bot, CLI; channel digest publish with best-effort deactivation; migration `a8b7c6d5e4f3`.

## Quality gates (local)

| Gate | Result |
|---|---|
| Default pytest | 2246 passed, 0 failed (post Phase 9 self-review +32) |
| `TEST_POSTGRES=1` | 2560 passed, 0 failed (post Phase 9 self-review +42) |
| Ruff | clean on all branch-touched files (1 pre-existing UP038 in `tg_parser/services/scheduler_service.py` from `main`, unrelated) |
| `prompts/bot.yaml` diff | version bump + `target_kind_semantics` only |

### Phase 9 self-review additions (2026-05-24)

Strengthened test coverage in a follow-up self-review pass before merge:

- **`tests/test_subscribe_legacy_chat_id.py`** — added neither/instance-passthrough/invalid-dict edge cases, watch-interest round-trips (chat + channel), storage-field symmetry, and an explicit unresolvable-target guardrail.
- **`tests/test_digest_channel_publish.py`** — parametrised over all known permanent-error fragments, asserted `record_digest_channel_publish` labels for `success` / `permission_denied` / `failed`, fallback-DM happy path, fallback-DM-fails-and-is-swallowed path, and chat-target failure propagation (no soft-deactivate).
- **`tests/test_alembic_subscription_target_migration.py`** — symmetric `watch_interests` columns, `pg_enum` value pin, idempotent re-upgrade, downgrade success when no channel rows, downgrade-blocks-on-channel-rows guardrail.
- **`tests/test_contracts_subscription_target.py`** — additional negative cases (extra fields, type mismatch, channel_id on chat variant) + self-consistency check on `examples`.
- **`tests/test_api_digests.py` + `tests/test_api_watchlists.py`** — explicit HTTP `target=channel` happy path, explicit `target=chat`, `chat_id`+`target` 422 conflict, neither-set 422, idempotent replay with `target=channel`.

One small lint hygiene fix in production code: `tests/test_subscribe_legacy_chat_id.py` revealed UP038 on `isinstance(target, (TargetChat, TargetChannel))` in `tg_parser/domain/models.py` → switched to `TargetChat | TargetChannel` (no behaviour change).

## Not in this sprint (per anti-scope)

- PATCH target update; test-publish endpoints; middleware broadening; `kind=webhook`; BUG-025/026/027 bot UX.

## Next

1. User-requested commit + PR
2. Deploy per [`docs/runbooks/WAVE1_STEP4_DEPLOY_AND_WATCH.md`](../runbooks/WAVE1_STEP4_DEPLOY_AND_WATCH.md)
3. 24h watch → flip this marker to GREEN
