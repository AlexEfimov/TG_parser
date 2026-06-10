# ADR 0014 – Watchlist batch + silent delivery (F11 P2)

## Статус

**Accepted (2026-06-10).** Wires the two `NotifyMode` values reserved since
F11 MVP — `BATCH` and `SILENT` — into real delivery behaviour. Additive and
backward-compatible: `INSTANT` interests are byte-equivalent in behaviour
(delivery is now routed through a shared per-group helper extracted from
`notify`, with no change to the instant path). No schema change, no migration.
Local change — **not yet deployed**.

## Контекст

F11 (ADR 0010–0013) shipped the matcher, scoring, calibration, and the
**instant** push: `check_interests` scores new docs per tick, persists matches
to `watch_matches`, and `notify` immediately pushes one grouped Telegram
message per interest. `NotifyMode` already had three members:

```python
class NotifyMode(StrEnum):
    INSTANT = "instant"
    BATCH = "batch"      # reserved
    SILENT = "silent"    # reserved
```

`BATCH` and `SILENT` were accepted/stored by `subscribe` but had no runtime
behaviour: `notify` skipped any non-instant interest (`skipped_non_instant`),
so a BATCH match was persisted (`notified=False`) and never delivered, and a
SILENT match was persisted and never delivered either. P2 makes both modes
real:

- **BATCH** — matches accumulate and are delivered together on a fixed cadence
  (one grouped message per interest per flush), reducing push frequency for
  high-volume interests.
- **SILENT** — matches are journaled only: visible in match history
  (`get_watchlist_matches` / `list_for_interest`) but never pushed and never
  batched.

## Решение

### The `notified` flag — normative meaning across all three modes

`watch_matches.notified` (boolean, default `false`) is the single source of
truth for "has this match been delivered / does it still need delivery". P2
formalises it as the **batch watermark**:

| Mode | `notified` at creation | Delivery | Watermark transition |
|---|---|---|---|
| INSTANT | `false` | instant push in `notify` (same tick) | → `true` after a successful send (`mark_notified`) |
| BATCH | `false` | grouped push in `flush_batch` (next cron tick) | → `true` after a successful send only |
| SILENT | `true` | none (journal-only) | n/a — born delivered |
| backfill (ADR-0011) | `true` | none (silent materialization) | n/a |

The flush selects `notified=false` rows; SILENT (and backfill) rows are born
`notified=true`, so they are structurally excluded from any push. A failed send
never advances the watermark, so the matches stay pending and the next flush
retries them.

### The six forks (locked, user-approved)

**Fork 1 — Cadence: ONE global cron flush task.**
Not per-F6-subscription, not per-interest. A single APScheduler cron job
(`watchlist_batch_flush`) registered in `setup_default_tasks` flushes *all*
active batch-mode interests each tick. Cadence is env-configurable
(`watchlist_batch_cron`, default daily `"0 9 * * *"`; `watchlist_batch_timezone`,
default `UTC`). *Rationale:* a per-interest schedule would require a new
`watch_interests` column + migration and N scheduler jobs; F6-subscription
coupling would conflate two unrelated features. A single global cadence is the
minimal, migration-free design and matches the idempotency-cleanup cron
precedent. `max_instances=1` (the scheduler job default) prevents a slow flush
from overlapping itself.

**Fork 2 — Format: reuse `compose_match_notification`.**
Batch delivery uses the exact instant composer (per-interest grouping, top-N
inline previews, "+N more" overflow footer, 4096-char Telegram limit). No LLM,
no separate batch template. *Rationale:* the instant message format is already
tuned and tested; a batch is just "the same message, more matches".

**Fork 3 — Silent = journal.**
In `check_interests`, when `interest.notify_mode == NotifyMode.SILENT`, the
inserted `WatchMatch` is built with `notified=True` (mirrors the backfill
convention, ADR-0011). It is skipped by the instant `notify` path (non-instant)
and never selected by the flush (`notified=false` filter). Net effect:
journal-only, fully visible in history.

**Fork 4 — Dedup: the `notified` flag IS the watermark.**
The flush selects `notified=false` for active batch-mode interests, sends, then
calls `mark_notified` **only after a successful send**. Two consecutive flushes
with no new matches in between → the second is a no-op (the first flipped every
row to `notified=true`). A failed send leaves matches pending.

**Fork 5 — Paused interests = flush-on-resume.**
The flush query filters `is_active=true`. A paused (soft-deleted) interest's
pending matches keep `notified=false` (never stranded, never dropped); they are
simply skipped while inactive and flush naturally on the next tick after the
interest is resumed (re-subscribe flips `is_active` back to true). No special
resume hook is needed — the `is_active` filter yields flush-on-resume for free.

**Fork 6 — Empty window = no-op.**
No `notified=false` rows for the active batch-mode interests → the flush sends
nothing and returns an empty outcome dict. No empty / "0 new" message is ever
sent.

### Blocked chat — shared failure handling

Batch sends route through the **same** failure handling as the instant push. A
shared per-group helper `WatchlistService._send_group(interest, matches,
docs_by_ref, bot)` was extracted from `notify` and is reused by both `notify`
(instant) and `flush_batch`. It owns: compose → `bot.send_message` → on
`_BOT_PERMANENT_FAILURE_FRAGMENTS` ("chat not found" / "bot was blocked" /
"user is deactivated" / "forbidden") soft-delete the orphaned interest +
`record_watchlist_delivery(outcome="blocked")`, on transient error
`record_watchlist_delivery(outcome="error")`, on success `mark_notified` +
`record_watchlist_delivery(outcome="sent")`. The instant path's behaviour is
unchanged — it now calls the helper after its mode checks instead of inlining
the body.

### Bot availability

`run_watchlist_batch_flush` guards on `get_bot()`: with no live `Bot` the tick
is a no-op (`skipped_reason="no_bot"`) and no matches are consumed — their
`notified=false` watermark is preserved for the next flush.

### Flood guard

`flush_batch` caps the number of batch-mode interests handled per tick at
`watchlist_batch_max_interests_per_tick` (default 500; `<= 0` disables the cap).
Interests beyond the cap are deferred to the next tick (matches stay pending).

## Settings

| Knob | Default | Meaning |
|---|---|---|
| `watchlist_batch_enabled` | `true` | Register the global flush cron in this process (set False in API/CLI schedulers to avoid double delivery; disabling strands no data). |
| `watchlist_batch_cron` | `"0 9 * * *"` | 5-field cron for the global flush (daily 09:00). |
| `watchlist_batch_timezone` | `"UTC"` | IANA timezone for the cron. |
| `watchlist_batch_max_interests_per_tick` | `500` | Flood guard on interests per flush tick. |

## Contracts check

No JSON Schema pins watchlist match / delivery I/O. No DB schema change: the
existing `watch_matches.notified` column carries the watermark and the
`idx_watch_matches_interest_created (interest_id, created_at)` index backs the
new `list_unnotified_for_interests` query. `NotifyMode.BATCH` / `SILENT` were
already valid persisted values. Purely additive — **no contract impact, no
migration**.

## Тестовая стратегия

`tests/test_watchlist_batch.py` (new) + regression coverage in the existing
watchlist suites:

- flush sends one grouped message per batch interest, flips `notified=true`;
- SILENT never sends but the match appears in history with `notified=true`;
- dedup across two consecutive flushes (second is a no-op);
- blocked-chat → soft-delete interest + matches preserved (`notified=false`);
- empty window → no-op (no send);
- paused interest not flushed, then flushed after resume;
- instant mode unchanged (regression — full `notify` suite still green);
- scheduler hook `run_watchlist_batch_flush` builds the service, calls
  `flush_batch(get_bot())`, `aclose()`s, and no-ops when the bot is unavailable.

## Последствия

### Положительные

- BATCH and SILENT modes are now real, closing the F11 `NotifyMode` gap.
- Single auditable cadence + single shared send path (instant ≡ batch failure
  handling); no duplicated delivery logic.
- Zero migration, zero contract impact, instant behaviour preserved.

### Отрицательные / accepted debt

- One global cadence for all batch interests (no per-interest schedule) — a
  deliberate MVP simplification; per-interest cadence would need a column +
  migration and is deferred.
- A flush that exceeds `max_interests_per_tick` defers the overflow to the next
  tick, so on a very large batch population delivery latency can exceed one
  cadence period (bounded, observable; raise the cap or cadence to mitigate).

## Ссылки

- ADR 0010 (keyword aggregation), ADR 0011 (backfill rework — `notified=true`
  silent-materialization convention reused by SILENT), ADR 0012 (threshold
  calibration), ADR 0013 (precision floor).
- `tg_parser/services/watchlist_service.py` — `check_interests` (SILENT
  `notified=true`), `_send_group` (shared helper), `flush_batch`.
- `tg_parser/services/scheduler_service.py` — `run_watchlist_batch_flush`.
- `tg_parser/services/background_scheduler.py` — `setup_default_tasks`
  (`watchlist_batch_flush` cron registration).
- `tg_parser/storage/ports.py` + `tg_parser/storage/sqlalchemy/watch_match_repo.py`
  — `list_unnotified_for_interests`.
- `tg_parser/config/settings.py` — `watchlist_batch_*`.

## История

| Дата | Изменение |
|------|-----------|
| 2026-06-10 | Created and Accepted. Wires `NotifyMode.BATCH` (one global cron flush, `notified` watermark, shared `_send_group` send path) and `NotifyMode.SILENT` (journal-only, `notified=true` at creation). Six forks locked: global cron cadence, reuse `compose_match_notification`, silent=journal, notified-flag dedup, paused=flush-on-resume, empty-window no-op. New `list_unnotified_for_interests` repo query; `watchlist_batch_*` settings. No schema change, no migration, no contract impact. Not yet deployed. |
