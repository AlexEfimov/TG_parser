# ADR 0013 – Watchlist threshold absolute precision floor (extends ADR 0012 R1)

## Статус

**Accepted (2026-06-10).** Extends ADR-0012 R1 (target-fraction calibration).
Landed at code level; calibration now returns
``threshold = max(target_fraction_threshold, floor)`` with ``floor`` default
``0.45``. Additive and backward-compatible — defaults preserve ADR-0012
behaviour for every interest whose volume-target cutoff already sits above the
floor. Local change — **not yet deployed**.

## Контекст

ADR-0012 (S2, live) auto-calibrates a new interest's threshold from the channel
corpus score distribution via ``suggest_threshold_from_scores`` (strategy
``target_fraction = 0.03``, match clamp ``[10, 150]``). The cutoff is the
Nth-highest combined score, where ``N = clamp(round(fraction × corpus_size),
min_matches, max_matches)``.

A data-driven review of live calibrations found the **volume-target overshoots
NARROW interests**. When an interest genuinely matches only a handful of docs,
the corpus has a *thin tail*: the top few scores are real, then the
distribution collapses into a low "noise band" (combined ≈ 0.1–0.3, driven by
the semantic floor on an unrelated RU-medical corpus). Because the
``min_matches = 10`` clamp forces the target down to the 10th-highest score,
that 10th score lands **inside the noise band**, dragging the threshold far
below where precision holds. The interest then matches the whole low cluster.

Observed overshoot (matches at the calibrated cutoff vs. the precision-justified
count) for the worst NARROW interests:

| Interest profile | Target (volume) | Real on-topic | Overshoot |
|---|---|---|---|
| Narrow A (thin tail) | ~10 | ~1–2 | **7.9×** |
| Narrow B | ~10 | ~3 | ~3× |
| Narrow C | ~10 | ~4 | ~2.5× |
| Broad (healthy) | ~10–60 | ~10–60 | ~1× (no issue) |

Broad interests — whose tail stays above ~0.45 out to the 10th score — are
unaffected: their volume-target cutoff is already a precise cutoff.

## Decision

### Absolute precision floor: ``threshold = max(fraction, floor)``

After the strategy (``target_fraction`` or ``percentile``) picks a
volume-target threshold, apply an **absolute floor**:

```
threshold = max(target_fraction_threshold, min_threshold)   # min_threshold = 0.45
would_match = count(scores >= threshold)                     # recomputed post-floor
```

- ``target_matches`` is kept as the **PRE-floor** volume target (transparency:
  operators see what volume the corpus *would* have produced).
- ``would_match`` is **recomputed** against the floored threshold (the honest
  count operators will actually receive).
- Advisory metadata ``floor_applied`` / ``pre_floor_threshold`` is added to
  ``ThresholdCalibration`` (and the MCP ``threshold_calibration`` payload) so an
  operator can see *when the floor — not the volume target — set the cutoff*.

This cuts the worst NARROW overshoot from **7.9× → ~2×** and leaves every BROAD
interest **bit-for-bit unchanged**.

### Floor-vs-``min_matches`` precedence — the floor WINS (precision-first)

If applying the floor pulls ``would_match`` below ``target_min_matches``, the
floor **still wins**: the threshold is **not** lowered back down to recover the
missing matches. A few precise matches are better than many noisy ones — a
NARROW interest that legitimately matches 2 docs should notify on 2 docs, not on
10 noise-band docs. This is the deliberate, documented trade-off (code comment +
dedicated test ``test_floor_wins_over_min_matches``). ``min_matches`` remains a
*ceiling-side* clamp on the volume target only; it never overrides the floor.

### Why knee/gap (percentile-knee) detection was rejected

A knee/gap detector (find the largest drop in the sorted score curve and cut
there) was prototyped and **rejected**:

- **Fragile on small / thin-tailed samples** — exactly the NARROW case it would
  need to fix. The "knee" is ill-defined when the tail is one or two points.
- **Non-monotonic / unstable** — small corpus changes move the detected knee
  discontinuously, making calibrations hard to reason about or reproduce.
- The absolute floor is a single, auditable magic number that achieves the same
  precision win with none of the instability. ADR-0012 already deferred
  knee/gap detection for the same fragility reason; this ADR closes it out as
  *rejected*, not merely deferred.

### The floor is a model/corpus-specific magic number (caveat)

``0.45`` is **not** universal. It is calibrated for:

- embedding model **OpenAI ``text-embedding-3-small``**,
- the **RU-medical** corpus,
- hybrid **semantic weight 0.6** / keyword weight 0.4 (cosine ≈ 0.7 cap).

It must be **re-derived** if the embedding model, corpus language, or hybrid
weights change. It is exposed as a settings knob
(``watchlist_calibration_min_threshold``) so it can be retuned without a code
change, and validated to ``[0, 1]``.

## Settings

``watchlist_calibration_min_threshold: float = 0.45`` (range ``[0, 1]``), added
beside the other ``watchlist_calibration_*`` knobs. Threaded through
``_load_calibration_settings`` (safe-fallback default ``0.45``) →
``calibrate_threshold`` → ``suggest_threshold_from_scores(min_threshold=...)``.
Setting it to ``0.0`` restores exact ADR-0012 behaviour.

## Contracts check

No JSON Schema pins ``SubscribeWatchlistResult`` or threshold-calibration I/O.
``ThresholdCalibration`` gains two **additive, defaulted** fields
(``floor_applied: bool = False``, ``pre_floor_threshold: float | None = None``);
the MCP ``threshold_calibration`` dict gains the same optional keys. Persisted
``watch_interests.threshold`` column unchanged. No contract impact.

## Test strategy

Extends the ADR-0012 / S2 block in ``tests/test_watchlist_service.py``:

- NARROW synthetic distribution (thin tail, most scores < 0.45) → floored to
  ``min_threshold``; ``floor_applied=True``; ``would_match`` recomputed small.
- BROAD synthetic distribution (fraction threshold already > 0.45) → UNAFFECTED;
  ``floor_applied=False``; bit-for-bit identical to the no-floor call.
- Floor-vs-``min_matches`` precedence: flooring drops ``would_match`` below
  ``target_min_matches`` → threshold stays at the floor (floor wins).
- Backward-compat: default ``min_threshold=0.0`` is a no-op; the settings
  default surfaces as ``0.45``; explicit thresholds still bypass calibration.

## Последствия

### Положительные

- Worst NARROW overshoot 7.9× → ~2×; broad interests unchanged.
- Precision-first behaviour matches operator intent for niche interests.
- Single auditable knob; advisory metadata makes the floor's effect visible.

### Отрицательные / accepted debt

- ``0.45`` is embedding-model/corpus/weights-specific — must be re-derived on
  any of those changes (documented caveat + settings knob).
- A genuinely narrow interest may receive *fewer* matches than the nominal
  ``min_matches`` volume target — this is the intended precision trade-off.

## Ссылки

- ADR 0010 (keyword aggregation) — calibration runs on top-k keyword scores.
- ADR 0011 (backfill rework) — shared full-corpus scoring path.
- ADR 0012 (threshold auto-calibration) — this ADR extends R1.
- `tg_parser/services/watchlist_service.py` — ``suggest_threshold_from_scores``,
  ``calibrate_threshold``, ``ThresholdCalibration``, ``_load_calibration_settings``.
- `tg_parser/config/settings.py` — ``watchlist_calibration_min_threshold``.
- NARROW-overshoot calibration investigation (data table above).

## История

| Дата | Изменение |
|------|-----------|
| 2026-06-10 | Created and Accepted. Absolute precision floor ``max(fraction, 0.45)`` on calibration; floor wins over ``min_matches`` (precision-first); knee/gap detection rejected (fragile); ``floor_applied`` / ``pre_floor_threshold`` advisory metadata in calibration + MCP; ``watchlist_calibration_min_threshold`` settings knob. Not yet deployed. |
