# ADR 0014 – Watchlist batch + silent delivery (F11 P2)

## Статус

**Accepted (2026-06-10), amended 2026-08-13 (BUG-095 — see § "Instant delivery
topology").** Wires the two `NotifyMode` values reserved since F11 MVP —
`BATCH` and `SILENT` — into real delivery behaviour. Additive and
backward-compatible: `INSTANT` interests are byte-equivalent in behaviour
(delivery is now routed through a shared per-group helper extracted from
`notify`, with no change to the instant path). No schema change, no migration.

> **The amendment changes what `INSTANT` promises.** Delivery is no longer
> synchronous with the matcher tick; the claim of byte-equivalence above held
> only for a process that has a `Bot`, and production has never been one. The
> normative statement is § "Instant delivery topology" below.

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

### Instant delivery topology (amendment 2026-08-13, BUG-095)

The original decision assumed `notify` could deliver where it was called. It
cannot: `check_interests` runs inside the incremental pipeline in the
`tg_parser` process, `get_bot()` is a process-local singleton filled only by the
bot's own startup, and `TELEGRAM_BOT_TOKEN` is not in that container's
environment. So the instant push was a no-op in the only process that ever ran
it — silently, because the code read `if bot is not None`. Matches were recorded
correctly and never delivered from 2026-06-15 until 2026-08-13.

The same trap had already been found and fixed for BATCH: Fork 1 above says the
cron is registered in `setup_default_tasks`, and that has been **stale since
2026-06-11** (commit `52a2ea8`), when the registration was moved to the bot
process precisely to remove a flush that always skipped with
`skipped_reason="no_bot"`. The knowledge existed; it was applied to one of the
two paths.

**Normative statement, superseding "instant push in `notify` (same tick)" in
the watermark table above:**

| | |
|---|---|
| **Where matching happens** | `tg_parser` (incremental pipeline tick). Records the match with `notified=false`; delivery from here is impossible and is now logged as `watchlist.instant_delivery_deferred reason="no_bot"`. |
| **Where delivery happens** | The bot process, task `watchlist_instant_flush`, registered in `bot/main.py` next to the batch flush. It selects `notified=false` matches of active INSTANT interests and sends them through the same `_send_group`. |
| **What `instant` means** | "within one flush interval of the matching tick" (`watchlist_instant_flush_interval_seconds`, default 300 s) — **not** "synchronous with it". This is a real weakening of the ADR-0010 contract, accepted knowingly: the alternative on offer was the status quo, in which nothing arrived at all. |
| **Where it must not be registered** | `setup_default_tasks`. That is the API/`tg_parser` path where `get_bot()` is always `None`; registering either flush there reproduces BUG-095 exactly. |

`notify` is kept and still delivers synchronously when a caller does supply a
`Bot` (tests, and any future process that holds one). It is no longer the
production delivery path; the flush is, and a match delivered by `notify`
carries `notified=true`, so the flush cannot deliver it twice.

**Watermark on the selector.** `list_unnotified_for_interests` has no date bound
by design — safe while every pending row is fresh, fatal once a backlog exists.
The instant flush therefore passes `since=<activation watermark>`
(`watchlist_instant_flush_cutoff`, or the moment of registration): without it
the first tick after the fix would have delivered ninety-three matches, some two
months old, in one burst. Rows older than the watermark belong to
`scripts/watchlist_backlog_summary.py`, which closes them with one summary per
chat. The two partitions are disjoint by construction, so their order of
execution does not matter — deliberately, because ordering discipline does not
survive a redeploy or a rollback.

**Observability.** `tg_watchlist_undelivered_matches` counts matches still
`notified=false` past one flush interval; `WatchlistMatchesUndelivered` alerts
on a non-zero value sustained for an hour. Delivery counters alone could not
have caught BUG-095: they measure failed sends, and no send was ever attempted.

## Settings

| Knob | Default | Meaning |
|---|---|---|
| `watchlist_batch_enabled` | `true` | Register the global flush cron in this process (set False in API/CLI schedulers to avoid double delivery; disabling strands no data). |
| `watchlist_batch_cron` | `"0 9 * * *"` | 5-field cron for the global flush (daily 09:00). |
| `watchlist_batch_timezone` | `"UTC"` | IANA timezone for the cron. |
| `watchlist_batch_max_interests_per_tick` | `500` | Flood guard on interests per flush tick. |
| `watchlist_instant_flush_enabled` | `true` | Register the instant flush in this process (BUG-095). Bot process only. |
| `watchlist_instant_flush_interval_seconds` | `300` | Instant-delivery cadence — the latency budget behind the word "instant". |
| `watchlist_instant_flush_max_interests_per_tick` | `500` | Flood guard on instant interests per flush tick. |
| `watchlist_instant_flush_cutoff` | unset | ISO-8601 watermark; matches older than it are never delivered by the flush. Unset → captured at registration, which moves on every restart. |

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

Amendment (BUG-095): `tests/test_bug095_watchlist_instant_delivery.py` states the
cause as a test (`bot=None` records but never sends) and pins the flush,
including the watermark; `tests/test_bug095_instant_flush_wiring.py` pins the
topology itself — that the flush is registered in the bot process and not in
`setup_default_tasks`, that it refuses to run without a bot or a watermark, and
that the backlog reconciliation is idempotent and disjoint from the flush.

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
- **(2026-08-13)** `instant` no longer means synchronous: delivery lags the
  matching tick by up to one flush interval. ADR-0010's original wording still
  describes instant push and is superseded on this point by the section above.
- **(2026-08-13)** With `watchlist_instant_flush_cutoff` unset, the watermark is
  captured per process start, so matches created while the bot is down fall
  outside every delivery window. They are not lost — they are counted by
  `tg_watchlist_undelivered_matches` and closed by re-running the backlog
  script. Pin the setting to remove the window entirely.

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
| 2026-08-13 | Amended (BUG-095, session R8): § "Instant delivery topology". `INSTANT` delivery moves to a `watchlist_instant_flush` task in the bot process — the matcher runs where no `Bot` exists, so the original in-tick push was a silent no-op for two months. `instant` is redefined as "within one flush interval" (default 300 s). `list_unnotified_for_interests` gains `since`/`before` bounds so the flush cannot ship the accumulated backlog; the backlog is closed once by `scripts/watchlist_backlog_summary.py`. Adds `watchlist_instant_flush_*` settings, the `tg_watchlist_undelivered_matches` gauge and the `WatchlistMatchesUndelivered` alert. Corrects Fork 1's registration site, stale since `52a2ea8` (2026-06-11). Still no schema change, no migration, no contract impact. |
