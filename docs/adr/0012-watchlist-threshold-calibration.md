# ADR 0012 – Watchlist threshold auto-calibration at interest creation (S2)

## Статус

**Accepted (2026-06-09).** Landed at code level in the S2 implementation
sub-session. When a new F11 interest is created without an explicit
``threshold``, the service scores the channel corpus (ADR-0011 full-corpus
path) and auto-sets a corpus-derived cutoff instead of the historical
``watchlist_default_threshold`` (0.6). Explicit thresholds bypass calibration.
Local change — **not yet deployed**.

## Контекст

After S1 (ADR-0010 top-k keyword aggregation) and S3 (ADR-0011 full-corpus
backfill), the remaining onboarding failure mode is an **unreachable default
threshold**: ``watchlist_default_threshold = 0.6`` is often above the combined-
score ceiling for Russian medical corpora (semantic weight 0.6, cosine ~0.7
cap), so new interests appear "dead" until an operator manually tunes the
cutoff. Operators had no signal about what threshold is realistic for their
interest + channels.

S2 adds **corpus-based threshold suggestion** at creation time, reusing the
same ``compute_watch_score`` path as backfill and the scheduler (no scoring-
model change).

## Decision

### R1 — Algorithm: target match volume (fraction of corpus)

**Strategy ``target_fraction`` (default):** after scoring the full corpus,
target ``N = clamp(round(fraction × corpus_size), min_matches, max_matches)``
and set ``threshold`` to the **Nth-highest** non-excluded combined score.
Default ``fraction = 0.03`` (~3% of corpus), clamped to
``[10, 150]`` matches.

Alternative **``percentile``** strategy (config knob): threshold at the
configured percentile of the score distribution (default 97 → top ~3%).

Rationale: reference interests at the same nominal threshold (0.5) yield
match volumes differing by an order of magnitude (§7 START_PROMPT S2) — a
**volume-target** cutoff is more stable than a single global magic number.

Knee/gap detection deferred (fragile on small samples).

### R2 — Separate calibration pass (not BackfillResult extension)

New ``WatchlistService.calibrate_threshold`` + pure
``suggest_threshold_from_scores`` share the scoring loop via
``_collect_corpus_combined_scores`` (same gather + batched embeddings as
``backfill_interest``). ``BackfillResult`` stays aggregate-only; calibration
returns ``ThresholdCalibration`` with advisory metadata.

### R3 — Auto-set when omitted; explicit bypass

- ``threshold=None`` on **new create** → calibrate and **auto-set**
  ``suggested_threshold`` on the row (replaces blind 0.6 default).
- Explicit ``threshold`` → use as-is, no calibration.
- **Updates** (idempotent ``subscribe`` replay): ``threshold=None`` leaves the
  stored value unchanged (does not re-resolve to 0.6).
- Calibration metadata returned in ``SubscribeResult.threshold_calibration``
  and MCP ``threshold_calibration`` for operator transparency (advisory layer).

No separate ``--yes`` gate: setting a threshold is part of create, not a bulk
retroactive mutation (contrast ADR-0011 apply).

### R4 — Synchronous at create

Full-corpus scoring runs synchronously during create (after eager embedding).
Current corpus sizes (~8.5k docs/interest) are in-memory and cheap after
ADR-0011 batched embedding fetch. Sampling deferred.

### R5 — Fallbacks

| Condition | Behaviour |
|---|---|
| Empty corpus | ``watchlist_default_threshold``, ``fallback_used=True`` |
| Calibration disabled | ``watchlist_default_threshold`` |
| No embedding client | keyword-only scoring still calibrates |
| Small corpus | calibrate but ``confidence=low`` |

### R6 — Settings knobs

``watchlist_calibration_enabled``, ``watchlist_calibration_strategy``,
``watchlist_calibration_target_fraction``, min/max match counts,
``watchlist_calibration_min_corpus_size``, ``watchlist_calibration_percentile``.

## Contracts check

No JSON Schema pins ``SubscribeWatchlistResult`` or ``threshold`` calibration
I/O. MCP adds optional ``threshold_calibration`` dict on the existing result
model. Persisted ``watch_interests.threshold`` column unchanged.

## Test strategy

- Pure ``suggest_threshold_from_scores`` on synthetic distributions.
- ``calibrate_threshold`` / subscribe-without-threshold integration with fakes.
- Explicit threshold bypasses calibration.
- Empty-corpus fallback.
- Existing watchlist / F11 tests remain green.

## Последствия

### Положительные

- New interests get a realistic cutoff without operator guesswork.
- Reuses ADR-0011 full-corpus scoring — trustworthy distribution.
- Explicit override preserved; calibration can be disabled via settings.

### Отрицательные / accepted debt

- Create latency grows with corpus size (sync scoring). Acceptable at current
  scale; streaming scorer deferred.
- Recalibration on interest **update** (text-field change) deferred to a
  follow-up (R5 in START_PROMPT).

## Ссылки

- ADR 0010 (keyword aggregation) — calibration runs on top-k scores.
- ADR 0011 (backfill rework) — shared full-corpus scoring path.
- `tg_parser/services/watchlist_service.py` — ``calibrate_threshold``,
  ``suggest_threshold_from_scores``, ``ThresholdCalibration``.
- `tg_parser/config/settings.py` — ``watchlist_calibration_*`` fields.

## История

| Дата | Изменение |
|------|-----------|
| 2026-06-09 | Created and Accepted. Target-fraction calibration on new create; auto-set when threshold omitted; advisory metadata in subscribe result; settings knobs; MCP/CLI/bot surfaces pass ``None`` for auto-calibrate. |
