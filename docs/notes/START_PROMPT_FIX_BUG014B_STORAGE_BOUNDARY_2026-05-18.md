# START_PROMPT — BUG-014B Fix-Sprint (storage-boundary `rate_limit_until` coerce)

**Дата:** 2026-05-18 (v1 initial draft) / 2026-05-18 (v1.1 post-self-review, this version)
**Scope:** **single-bug** sprint, narrower than joint BUG-013/14/24 (PR #79).
**Severity:** High (2 production sources in permanent fail-loop, `fail_count = 29` each, ~56 TypeErrors/day).
**Expected blast radius:** **~25-40 LOC across 3-4 files** — `tg_parser/domain/json_utils.py` (promote helper), `tg_parser/services/scheduler_service.py` (import swap), `tg_parser/storage/sqlalchemy/ingestion_state_repo.py` (broad coerce on 8 fields), + 3 test files (T-0 extension + 2 new test files).
**Watch criteria post-fix:** `kdl_ru` + `profendocrinologist` advance `last_success_at` within ≤ 2 ticks post-deploy + zero `TypeError.*offset` log lines from `orchestrator.py:110` over 24h.

**Status of this artifact:** **APPROVED FOR STEP E (implementation).** User pre-approved all 6 § 8 decisions in the self-review handoff prompt (Q1=A H-1, Q2=B broad 8 fields, Q3=A keep+comment, Q4=B 4 tests parametrised, Q5=confirm all 7 deferrals, Q6=mirror PR #79/#82 cadence). § 8 retained for historical context only — no further user-approval gate before implementation.

**Mirror:** Structurally follows [`START_PROMPT_FIX_BUG013_SCHEDULER_SESSION_2026-05-15.md`](START_PROMPT_FIX_BUG013_SCHEDULER_SESSION_2026-05-15.md) (9 sections). Adapted for narrower scope: § 3 has one subsection per design surface (helper / coerce / write-side / scheduler retention / composition); § 4 has 4 tests (helper + parametrised repo + null-guard + orchestrator regression); § 6 is single atomic commit (same as joint sprint convention).

---

## 1. Context & evidence

### 1.1 Required reads (in order, before implementation)

1. [`docs/notes/BUG_LOG.md` § BUG-014B](BUG_LOG.md) — canonical entry (filed 2026-05-18, this sprint kickoff).
2. [`docs/notes/BUG_LOG.md` § BUG-014](BUG_LOG.md) — sibling scheduler-side fix (closed via PR #79) — establishes the «Option A vs B» tradeoff context.
3. [`docs/notes/REVIEW_2026-05-16_BUG013_14_24_DONE.md` § 4.2](REVIEW_2026-05-16_BUG013_14_24_DONE.md) — known-partial classification + post-window evidence.
4. [`docs/notes/mcp_testing/2026-05-16_claude_session/analysis_and_options.md`](mcp_testing/2026-05-16_claude_session/analysis_and_options.md) — 5-option fix matrix + Option B recommendation rationale.
5. [`tg_parser/storage/sqlalchemy/ingestion_state_repo.py`](../../tg_parser/storage/sqlalchemy/ingestion_state_repo.py) lines 412-453 — `_row_to_source` builder (THE fix surface; SA-impl-internal helper, NOT a port method — see read 10).
6. [`tg_parser/domain/json_utils.py`](../../tg_parser/domain/json_utils.py) lines 80-94 — `parse_iso_datetime` (the naive-source-of-truth). Target location for promoted `coerce_aware_utc` helper.
7. [`tg_parser/services/scheduler_service.py`](../../tg_parser/services/scheduler_service.py) lines 26-47 — existing `_coerce_aware_utc` helper (will be promoted to `tg_parser.domain.json_utils.coerce_aware_utc` per Q1=A approved; scheduler retains call site as belt-and-suspenders per Q3=A approved).
8. [`tg_parser/ingestion/orchestrator.py`](../../tg_parser/ingestion/orchestrator.py) lines 100-122, 470-497 — comparison site (line 110) + write-path producing the aware-but-then-naive value (line 486, `_maybe_set_rate_limit`).
9. [`tg_parser/services/scheduler_service.py`](../../tg_parser/services/scheduler_service.py) line 873 — `_pause_source_for_billing` (companion write-path that mutates `source.rate_limit_until` via aware datetime → persists via `_format_datetime` → re-reads naive; round-trip caught by Option B on read).
10. [`tg_parser/storage/ports.py`](../../tg_parser/storage/ports.py) lines 183-236 (`Source` class — note: a regular `class` with explicit `__init__`, NOT a `@dataclass`) and lines 239-371 (`IngestionStateRepo` abstract base). **Important:** `_row_to_source` is a **private helper inside `SAIngestionStateRepo`** (`ingestion_state_repo.py:412`), NOT a port-level method. The Option B fix is **SA-impl-internal** — zero impact on the port interface; no other adapters affected (none exist today, but the layering invariant is preserved for future ones).
11. [`START_PROMPT_FIX_BUG013_SCHEDULER_SESSION_2026-05-15.md`](START_PROMPT_FIX_BUG013_SCHEDULER_SESSION_2026-05-15.md) § 3.2 — original BUG-014 planning that **explicitly deferred** the parse-time fix (Option C in this sprint's matrix) — this artifact's Option B is the more proportionate alternative.

### 1.2 Evidence summary (do not duplicate full traces; BUG_LOG has them)

| Metric | Pre-fix (28h scan, post-PR-#79) | Post-fix target |
|---|---|---|
| `TypeError.*offset-naive` count from `orchestrator.py:110` | **56** (2 sources × 28 ticks) | **0** |
| `kdl_ru.fail_count` | 29 | 0 (reset on first successful tick) |
| `profendocrinologist.fail_count` | 29 | 0 (reset on first successful tick) |
| `kdl_ru.last_success_at` | **null** since first persisted `rate_limit_until` | non-null within ≤ 2 ticks post-deploy |
| `profendocrinologist.last_success_at` | **null** since first persisted `rate_limit_until` | non-null within ≤ 2 ticks post-deploy |
| 7 healthy sources | unaffected | unaffected (non-regression invariant) |
| Joint sprint signals (§ 5.3 PR #79) | GREEN | remain GREEN (non-regression invariant) |

**Reproduction trace** (see BUG_LOG § BUG-014B for full traceback; abridged here):

```
File ".../orchestrator.py", line 110, in ingest_source
    if source.rate_limit_until and source.rate_limit_until > datetime.now(UTC):
TypeError: can't compare offset-naive and offset-aware datetimes
```

Caught by PR #79's per-task `try/except` in `_process_source` at line 201 — failure isolation works; the sources just never make progress.

---

## 2. Root cause synthesis

### 2.1 The naive-vs-aware mismatch

`_row_to_source` (line 412 of `ingestion_state_repo.py`) parses **every** datetime column from the DB row through `parse_iso_datetime` (`tg_parser/domain/json_utils.py:80-94`). `parse_iso_datetime` is **documented** to return naive UTC:

```
def parse_iso_datetime(s: str) -> datetime:
    """
    ...
    Returns:
        datetime object (naive UTC)
    """
    if s.endswith("Z"):
        s = s[:-1]
    return datetime.fromisoformat(s)
```

The write side is symmetric: `_format_datetime` (line 455-459) does `dt.strftime("%Y-%m-%dT%H:%M:%SZ")` — strips tzinfo and restores `Z` as a literal suffix. So a `Source` instance built from a DB row always has naive datetimes, regardless of whether the original code constructed any field as tz-aware before persistence.

Concretely, `_maybe_set_rate_limit` (line 486 of `orchestrator.py`) writes `datetime.now(UTC) + timedelta(seconds=wait_seconds)` (aware) → `upsert_source` formats via `_format_datetime` (strips tz) → DB stores ISO string with `Z` suffix → next read parses via `parse_iso_datetime` (strips `Z`, returns naive). The round-trip is lossy by design.

### 2.2 Why BUG-014 scheduler-side fix didn't cover this

The original [`START_PROMPT_FIX_BUG013_SCHEDULER_SESSION_2026-05-15.md` § 3.2](START_PROMPT_FIX_BUG013_SCHEDULER_SESSION_2026-05-15.md) deliberately chose a **call-site coerce** at `scheduler_service.py:142` (via `_coerce_aware_utc`) rather than a parse-time structural fix:

> «Parse-boundary structural fix in `tg_parser/domain/json_utils.parse_iso_datetime` is **deferred** (cross-cutting; would change tz-info shape for many downstream consumers — filed as a follow-up TD per planning artifact § 7).»

The assumption — «scheduler is the only consumer of `source.rate_limit_until` that needs tz-aware comparison» — was wrong. The orchestrator-side reaches `source.rate_limit_until` via the same `Source` class instance and performs the same naive-vs-aware comparison at `orchestrator.py:110`. Pre-PR-#79, this site was **unreachable** because the scheduler-side TypeError aborted the tick first. PR #79 fixed the scheduler-side site → orchestrator-side became reachable → BUG-014B materialised.

### 2.3 Why Option B (storage-boundary) wins over Option A (mole-whack at orchestrator)

**Option A** (apply `_coerce_aware_utc` at `orchestrator.py:110` directly) closes BUG-014B but suffers from the same open-ended question that produced BUG-014B from BUG-014: «what other consumers of `source.rate_limit_until` exist? what about `history_from` / `history_to` / `backfill_completed_at` / `last_attempt_at` / `last_success_at` / `created_at` / `updated_at`?». Each consumer is a future BUG-014C/D/E/...

**Option B** (storage-boundary coerce in `_row_to_source`) closes the bug at its origin: the `Source` class instance, once built, is always tz-aware. No consumer needs to know. The scheduler-side `_coerce_aware_utc` becomes a no-op identity (kept as belt-and-suspenders, see § 3.5 decision).

**Option C** (parse-time fix in `parse_iso_datetime`) is the broadest but blast-radius-unbounded: `parse_iso_datetime` is called from ~30+ sites across the codebase (per `Grep parse_iso_datetime`). Changing its return-type contract risks regressions in places where naive datetimes are expected (e.g. JSON serialisation, test fixtures, comparison-with-naive in unrelated code paths). Deferred per BUG-013 planning artifact § 7; not adopted here.

**Options D / E** (DB `TIMESTAMPTZ` migration; symmetric write-side fix in `_format_datetime`) are tracked in `analysis_and_options.md` § 5 — D is ADR-grade and deferred to a separate sprint; E is unnecessary because the write side is already aware-tolerant (the lossy roundtrip is captured on read, which Option B fixes).

---

## 3. Proposed fix design

### 3.1 Fix surface: `_row_to_source` broad coerce (Q2=B approved)

**File:** `tg_parser/storage/sqlalchemy/ingestion_state_repo.py`
**Fix function:** `SAIngestionStateRepo._row_to_source` (lines 412-453). Private SA-impl helper — NO impact on port interface (`IngestionStateRepo` abstract base at `ports.py:239-371` is unchanged).

**Approved scope (Q2=B): apply `coerce_aware_utc` to all 8 naive datetime fields parsed via `parse_iso_datetime`.** See § 3.3 for the enumeration. `deleted_at` (line 419-422) is excluded — it's handled via the TIMESTAMPTZ driver path, already aware.

**Example replacement (`rate_limit_until` — THE bug-trigger field; same pattern × 8):**

```python
# Before:
rate_limit_until=(
    parse_iso_datetime(row.rate_limit_until) if row.rate_limit_until else None
),

# After (Q1=A approved — import from tg_parser.domain.json_utils):
rate_limit_until=(
    coerce_aware_utc(parse_iso_datetime(row.rate_limit_until)) if row.rate_limit_until else None
),
```

The coerce helper is imported at the top of the file:

```python
from tg_parser.domain.json_utils import (
    coerce_aware_utc,  # NEW (Q1=A) — promoted from scheduler_service._coerce_aware_utc
    parse_iso_datetime,
    stable_json_dumps,
)
```

`coerce_aware_utc` is idempotent: identity on already-aware values, attaches UTC on naive, passes `None` through. See § 3.2 for helper migration plan.

### 3.2 Helper migration plan (Q1=A H-1 approved)

**Step 1 — Promote helper to `tg_parser/domain/json_utils.py`** (colocated with `parse_iso_datetime`; symmetric naming pair: `parse_iso_datetime` produces naive, `coerce_aware_utc` lifts to aware). Append to the existing `json_utils.py` (which currently spans lines 1-94 with `stable_json_dumps`, `stable_json_loads`, `_json_default`, `parse_iso_datetime`):

```python
# Append after parse_iso_datetime (around line 95-110):
def coerce_aware_utc(dt: datetime | None) -> datetime | None:
    """Attach UTC tzinfo to naive datetimes; identity on aware; pass through None.

    BUG-014 / BUG-014B defensive helper. :func:`parse_iso_datetime` strips
    the trailing ``Z`` and returns a tz-naive ``datetime`` for ISO-8601 UTC
    strings stored in the database. Comparing such a naive value against
    ``datetime.now(UTC)`` (tz-aware) raises ``TypeError``. This helper
    normalises any datetime read from DB to tz-aware UTC, so downstream
    comparisons are always aware-vs-aware.

    Idempotent: re-applying does not change an already-aware value.
    Used at the storage boundary (`SAIngestionStateRepo._row_to_source`,
    BUG-014B Option B) and as belt-and-suspenders at the scheduler
    call site (`scheduler_service._process_source`, BUG-014).
    """
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
```

The implementation is a verbatim copy of the existing `scheduler_service._coerce_aware_utc` (lines 26-47). UTC is imported from `datetime` (already present in `json_utils.py` line 8).

**Step 2 — Delete `scheduler_service._coerce_aware_utc` and rename call site.**

```python
# In tg_parser/services/scheduler_service.py:

# Top of file — add import:
from tg_parser.domain.json_utils import coerce_aware_utc

# Delete lines 26-47 (the local _coerce_aware_utc def + docstring).

# Line 142 — rename call site:
rate_limit_until = coerce_aware_utc(source.rate_limit_until)  # was: _coerce_aware_utc(...)
```

**Approach: rename (not alias).** Rationale: cleaner; eliminates underscored-name indirection (was module-private, now public utility); call site reads identically. No alias (`as _coerce_aware_utc`) needed because the only call site is line 142 and no external test references the private name (T-3 from PR #79 tests behaviour, not name).

**Step 3 — Import in storage layer.** See § 3.1 import block. New import line in `ingestion_state_repo.py:12-15`.

**Why this layering works:** `tg_parser.domain` is the stable internal utility module (already imported by `storage.sqlalchemy.*` per `ingestion_state_repo.py:12`). Promoting the helper there keeps the dependency arrow correct (storage → domain, services → domain — both downward into pure utility code). Layering convention preserved.

### 3.3 Approved scope: broad coerce — 8 naive datetime fields (Q2=B)

**All 8 naive datetime fields in `SAIngestionStateRepo._row_to_source` (`ingestion_state_repo.py:412-453`)** wrapped with `coerce_aware_utc(parse_iso_datetime(...))`:

| # | Field | Current line(s) | Naive (parsed via `parse_iso_datetime`) | Coerce required |
|---|---|---|---|---|
| 1 | `history_from` | 429 | ✅ yes | ✅ yes |
| 2 | `history_to` | 430 | ✅ yes | ✅ yes |
| 3 | `backfill_completed_at` | 434-436 | ✅ yes | ✅ yes |
| 4 | `last_attempt_at` | 437-439 | ✅ yes | ✅ yes |
| 5 | `last_success_at` | 440-442 | ✅ yes | ✅ yes |
| 6 | `rate_limit_until` (THE bug trigger) | 445-447 | ✅ yes | ✅ yes (primary closure) |
| 7 | `created_at` | 449 | ✅ yes | ✅ yes |
| 8 | `updated_at` | 450 | ✅ yes | ✅ yes |
| — | `deleted_at` | 419-422 | ❌ TIMESTAMPTZ-aware via SA driver (per existing comment at 415-417) | ❌ skip — already aware |
| — | `owner_id` | 451 | ❌ str | ❌ N/A |

**LOC estimate:** ~16 LOC delta (8 fields × ~2 LOC wrap; +1 import line in repo file; -14 LOC in scheduler when removing local helper, +6 LOC in `json_utils.py` when promoting).

**Rationale (Q2=B approved):** the broader scope makes the `Source` class instance an aware-datetime entity throughout the codebase, preventing future BUG-014C/D/E... at zero risk delta. The coerce is idempotent. Cost is negligible (~16 LOC); structural payoff is high.

### 3.4 Defensive write-side note (round-trip caught automatically)

Two write-path sites mutate `source.rate_limit_until` with aware datetimes:

1. [`tg_parser/ingestion/orchestrator.py:486`](../../tg_parser/ingestion/orchestrator.py) — `_maybe_set_rate_limit`: `source.rate_limit_until = datetime.now(UTC) + timedelta(seconds=wait_seconds)` (aware on assignment), persisted via `upsert_source` → `_format_datetime` (`ingestion_state_repo.py:455-459`) → `dt.strftime("%Y-%m-%dT%H:%M:%SZ")` (strips tzinfo, restores `Z` literal).

2. [`tg_parser/services/scheduler_service.py:873`](../../tg_parser/services/scheduler_service.py) — `_pause_source_for_billing`: similar aware-assignment → same `_format_datetime` lossy persist path.

After Option B, the lossy round-trip is **caught on read** by `_row_to_source` — `coerce_aware_utc` re-attaches UTC tzinfo before the `Source` instance is returned to any consumer. **No write-side change is required.** Option E in the analysis matrix (symmetric `_format_datetime` fix) is correctly identified as unnecessary. The original BUG-013 planning artifact § 3.1 § «Interaction with `_record_and_pause_on_billing`» called this trade-off correctly; Option B's storage-boundary fix completes that analysis.

**Defense-in-depth corollary:** `_format_datetime` itself does not need to change — it's allowed to be lossy on write because the read side will re-coerce. If a future maintainer changes write-side semantics (e.g. switches to `dt.isoformat()`), Option B's coerce on read is unaffected.

### 3.5 Scheduler-side `coerce_aware_utc` post-Option-B (Q3=A approved — keep + comment)

After Option B lands, `source.rate_limit_until` returned from `_row_to_source` is already aware. The scheduler-side call at `scheduler_service.py:142` (`coerce_aware_utc(source.rate_limit_until)` after rename per § 3.2 Step 2) becomes a no-op identity for the common path.

**Approved: keep call site + add belt-and-suspenders comment.** Concrete patch (replaces existing BUG-014 comment at `scheduler_service.py:137-141` and keeps the call at line 142):

```python
# BUG-014 / BUG-014B defense-in-depth. Post-PR-#79 + Option B
# (BUG-014B), ``SAIngestionStateRepo._row_to_source`` returns
# ``rate_limit_until`` as tz-aware UTC, so this call is normally
# an identity. Kept as belt-and-suspenders coerce that protects
# any future refactor accidentally bypassing the storage layer
# (e.g. raw SQL → direct ``Source`` construction in a test
# fixture; also guarantees the PR #79 closure test
# ``test_bug014_naive_rate_limit_until_does_not_crash`` stays
# GREEN — it feeds a naive ``rate_limit_until`` directly).
rate_limit_until = coerce_aware_utc(source.rate_limit_until)
```

**Justification:**

- Belt-and-suspenders is cheap (1 LOC; `dt.tzinfo is not None` short-circuits, zero runtime cost on the aware-path).
- Protects future refactors that bypass `_row_to_source` (e.g. raw SQL → direct `Source` construction in fixtures, debug snippets, migration scripts).
- The PR #79 closure test `test_bug014_naive_rate_limit_until_does_not_crash` (`tests/test_scheduler_service.py`) constructs a `Source` directly with naive `rate_limit_until` and expects the scheduler to skip rate-limited sources without raising — **removing the scheduler-side coerce would break this test**. Keep call site = test stays GREEN unchanged.

### 3.6 Composition order (for reviewer mental model)

Single atomic commit with 5 logical steps (apply in this order for clean review):

```
1. (Q1=A H-1) Promote coerce_aware_utc → tg_parser.domain.json_utils:
   - File: tg_parser/domain/json_utils.py
   - +6 LOC (function def + docstring)
   - No removal; additive.

2. (Q1=A H-1 follow-up) Refactor scheduler-side helper:
   - File: tg_parser/services/scheduler_service.py
   - DELETE lines 26-47 (the local `_coerce_aware_utc` def, -22 LOC)
   - ADD `from tg_parser.domain.json_utils import coerce_aware_utc` (+1 LOC near other imports at line 12-21)
   - RENAME call site at line 142: `_coerce_aware_utc(...)` → `coerce_aware_utc(...)` (1 line)
   - UPDATE belt-and-suspenders comment at lines 137-141 per § 3.5
   - Net: -21 LOC

3. (§ 3.1 + § 3.3 — Q2=B broad) Apply coerce in _row_to_source:
   - File: tg_parser/storage/sqlalchemy/ingestion_state_repo.py
   - ADD `coerce_aware_utc` to existing import block at line 12-15 (+1 LOC)
   - WRAP all 8 naive datetime fields at lines 429, 430, 434-436, 437-439,
     440-442, 445-447, 449, 450 with `coerce_aware_utc(...)` (+~8-16 LOC
     depending on line wrapping; idempotent)
   - Net: +~9-17 LOC

4. Tests (§ 4):
   - tests/test_json_utils.py — EXTEND with T-0 (helper contract). +~20 LOC
   - tests/test_ingestion_state_repo_datetime_coerce.py — NEW FILE with T-1
     (parametrised 8 fields) + T-2 (null guard). +~80-100 LOC
   - tests/test_orchestrator_rate_limit.py — NEW FILE with T-3
     (orchestrator regression). +~40-60 LOC

5. Docs:
   - CHANGELOG.md — append Unreleased entry (+~6 LOC)
   - docs/notes/BUG_LOG.md — append «Update <date>» closure row to BUG-014B
     entry (lines 2869-2895 of post-Step-A file, mirror BUG-014 closure
     row pattern from BUG-014 line 2661). +~3-5 LOC
   - docs/notes/START_PROMPT_FIX_BUG014B_STORAGE_BOUNDARY_2026-05-18.md
     (this artifact) — stage into commit per joint-sprint convention.
```

**Net LOC delta:** ~+150 to ~+200 across 6 files (3 source + 3 test + 2 docs), of which ~+10-20 are functional code and the rest are tests + docs.

---

## 4. Test plan (Q4=B approved — 4 tests, T-1 parametrised)

### 4.1 Test discovery (verified file existence)

| File | Status | Role |
|---|---|---|
| `tests/test_json_utils.py` | **EXISTS** (81 lines; covers `stable_json_dumps`, `stable_json_loads`, `parse_iso_datetime`, `_json_default`) | EXTEND with T-0 helper contract test |
| `tests/test_ingestion_state_repo.py` (monolith) | **DOES NOT EXIST** — convention: scope-specific files | n/a |
| `tests/test_ingestion_state_repo_username_alias.py` | exists | not modified by this sprint |
| `tests/test_ingestion_state_repo_soft_delete.py` | exists | not modified by this sprint |
| `tests/test_ingestion_state_repo_datetime_coerce.py` | **NEW FILE** | hosts T-1, T-2 |
| `tests/test_orchestrator.py` | **DOES NOT EXIST** — no orchestrator-layer test file in project today | n/a |
| `tests/test_orchestrator_rate_limit.py` | **NEW FILE** | hosts T-3 |
| `tests/test_scheduler_service.py` | exists (25 tests post-PR-#79) | must remain GREEN (regression invariant) — including `test_bug014_naive_rate_limit_until_does_not_crash` which exercises the retained scheduler-side coerce |

**Critical existing test that must remain GREEN:** `tests/test_scheduler_service.py::test_bug014_naive_rate_limit_until_does_not_crash` — confirms the scheduler-side coerce (now renamed `coerce_aware_utc`) still catches naive `rate_limit_until` when called via fixture-constructed `Source` (bypassing the repo). Q3=A approved keep-with-comment is what makes this test pass post-Option-B.

### 4.2 Test specs

**T-0 (NEW — helper contract; `tests/test_json_utils.py` EXTENSION):**

```python
# Append to tests/test_json_utils.py (after the existing parse_iso_datetime tests).
import pytest
from datetime import UTC, datetime, timezone

from tg_parser.domain.json_utils import coerce_aware_utc


class TestCoerceAwareUtc:
    """BUG-014 / BUG-014B helper contract — locks idempotent aware-coerce behavior."""

    def test_none_passes_through(self):
        assert coerce_aware_utc(None) is None

    def test_naive_gets_utc_attached(self):
        naive = datetime(2026, 5, 15, 16, 2, 4)
        assert naive.tzinfo is None  # precondition
        result = coerce_aware_utc(naive)
        assert result is not None
        assert result.tzinfo == UTC
        assert result.replace(tzinfo=None) == naive  # same wall-clock value

    def test_aware_utc_is_identity(self):
        aware = datetime(2026, 5, 15, 16, 2, 4, tzinfo=UTC)
        result = coerce_aware_utc(aware)
        assert result is aware  # identity, not a new instance

    def test_aware_non_utc_is_preserved(self):
        """If tzinfo is already set (even to non-UTC), do not override."""
        # E.g. ``deleted_at`` path in `_row_to_source` may produce non-UTC aware dt.
        tz_plus3 = timezone(timedelta(hours=3))
        aware_other_tz = datetime(2026, 5, 15, 19, 2, 4, tzinfo=tz_plus3)
        result = coerce_aware_utc(aware_other_tz)
        assert result is aware_other_tz  # identity
        assert result.tzinfo == tz_plus3  # tz unchanged
```

**T-1 (parametrised, repo-layer; `tests/test_ingestion_state_repo_datetime_coerce.py` NEW FILE):**

Asserts each of the 8 naive-datetime fields parsed by `_row_to_source` returns a tz-aware UTC value when the DB row has the corresponding column populated.

```python
# tests/test_ingestion_state_repo_datetime_coerce.py
import pytest
from datetime import UTC
from unittest.mock import AsyncMock, MagicMock

from tg_parser.storage.sqlalchemy.ingestion_state_repo import SAIngestionStateRepo


@pytest.mark.parametrize(
    "field_name",
    [
        "history_from",
        "history_to",
        "backfill_completed_at",
        "last_attempt_at",
        "last_success_at",
        "rate_limit_until",  # THE BUG-014B trigger
        "created_at",
        "updated_at",
    ],
)
def test_bug014b_row_to_source_coerces_all_naive_datetime_fields_to_aware(field_name):
    """For each of the 8 naive datetime fields parsed via parse_iso_datetime,
    _row_to_source must return a tz-aware UTC value (regardless of whether
    the DB-stored ISO string had Z suffix)."""
    row = MagicMock()
    # populate all required fields with valid defaults to avoid AttributeError
    row.source_id = "test_channel"
    row.channel_id = "test_channel"
    row.channel_username = None
    row.status = "active"
    row.include_comments = False
    row.poll_interval_seconds = 3600
    row.batch_size = 100
    row.last_post_id = None
    row.fail_count = 0
    row.last_error = None
    row.comments_unavailable = False
    row.owner_id = None
    row.deleted_at = None  # excluded from coerce path
    # set every datetime field to a naive ISO string (Z-stripped pattern)
    for f in ("history_from", "history_to", "backfill_completed_at",
              "last_attempt_at", "last_success_at", "rate_limit_until",
              "created_at", "updated_at"):
        setattr(row, f, "2026-05-15T16:02:04Z")

    repo = SAIngestionStateRepo(session=AsyncMock())
    source = repo._row_to_source(row)

    value = getattr(source, field_name)
    assert value is not None, f"{field_name} must not be None"
    assert value.tzinfo is not None, (
        f"{field_name} must be tz-aware after _row_to_source (BUG-014B Option B)"
    )
    assert value.tzinfo == UTC, f"{field_name} tzinfo must be UTC, got {value.tzinfo}"
```

**T-2 (null guard, repo-layer; same `tests/test_ingestion_state_repo_datetime_coerce.py`):**

```python
def test_bug014b_row_to_source_null_rate_limit_until_returns_none():
    """Coerce wrap must preserve None — coerce_aware_utc(None) → None."""
    row = MagicMock()
    # populate required non-datetime fields
    row.source_id = "test_channel"
    row.channel_id = "test_channel"
    row.channel_username = None
    row.status = "active"
    row.include_comments = False
    row.poll_interval_seconds = 3600
    row.batch_size = 100
    row.last_post_id = None
    row.fail_count = 0
    row.last_error = None
    row.comments_unavailable = False
    row.owner_id = None
    row.deleted_at = None
    # nullable datetime fields → None
    row.history_from = None
    row.history_to = None
    row.backfill_completed_at = None
    row.last_attempt_at = None
    row.last_success_at = None
    row.rate_limit_until = None  # the field under test
    # required non-null datetime fields (created_at / updated_at are NOT NULL in schema)
    row.created_at = "2026-05-15T16:02:04Z"
    row.updated_at = "2026-05-15T16:02:04Z"

    repo = SAIngestionStateRepo(session=AsyncMock())
    source = repo._row_to_source(row)

    assert source.rate_limit_until is None
    # but the non-null ones must still be aware (cross-check)
    assert source.created_at.tzinfo == UTC
    assert source.updated_at.tzinfo == UTC
```

**T-3 (orchestrator regression, NEW FILE `tests/test_orchestrator_rate_limit.py`):**

Mirrors PR #79 T-3 (`test_bug014_naive_rate_limit_until_does_not_crash`) for the orchestrator path. Builds a `Source` with **aware** `rate_limit_until` in the future (post-Option-B invariant), invokes `orchestrator.ingest_source(...)`, asserts `RetryableError` raised — NOT `TypeError`.

```python
# tests/test_orchestrator_rate_limit.py
import pytest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from tg_parser.ingestion.orchestrator import IngestionOrchestrator
from tg_parser.ingestion.errors import RetryableError
from tg_parser.storage.ports import Source


@pytest.mark.asyncio
async def test_bug014b_orchestrator_rate_limited_source_raises_retryable_not_typeerror():
    """Regression test for BUG-014B at orchestrator.py:110.

    Pre-Option-B: source.rate_limit_until was naive after _row_to_source,
    causing TypeError at the line-110 comparison. Post-Option-B: the value
    is aware, the comparison succeeds, RetryableError is raised (the
    correct rate-limited behavior).
    """
    aware_future = datetime.now(UTC) + timedelta(seconds=120)
    source = Source(
        source_id="kdl_ru",
        channel_id="kdl_ru",
        status="active",
        include_comments=False,
        rate_limit_until=aware_future,  # POST-FIX: aware (was naive pre-fix)
    )

    state_repo = AsyncMock()
    state_repo.get_source.return_value = source

    # Construct orchestrator with mocked dependencies (settings, client, etc.)
    # — adjust per actual IngestionOrchestrator __init__ signature discovered
    # during implementation; this is a sketch.
    orchestrator = IngestionOrchestrator(
        settings=MagicMock(),
        state_repo=state_repo,
        raw_repo=AsyncMock(),
        client=AsyncMock(),
    )

    with pytest.raises(RetryableError) as exc_info:
        await orchestrator.ingest_source(source_id="kdl_ru", mode="incremental")

    assert "rate-limited" in str(exc_info.value).lower()
    # Negative assertion: must NOT be a TypeError (the BUG-014B signature)
    assert not isinstance(exc_info.value, TypeError)
```

**Implementation note for T-3:** the exact `IngestionOrchestrator.__init__` signature must be confirmed during Step E (Read `tg_parser/ingestion/orchestrator.py:50-100` for the constructor). The stub above shows the **shape**; mock the minimum dependencies needed to reach line 110.

**T-5 (optional, deferred): testcontainers Postgres roundtrip.** Not in this sprint. Documented in commit message as «followup test idea» — defer to a future M-15-style observability hygiene sprint.

### 4.3 Test count summary

| Test | Location | Type | LOC |
|---|---|---|---|
| T-0 | `tests/test_json_utils.py` (EXTEND) | Unit (helper contract) | ~20 |
| T-1 (parametrised × 8) | `tests/test_ingestion_state_repo_datetime_coerce.py` (NEW) | Unit (repo-layer) | ~50 |
| T-2 | same as T-1 | Unit (repo-layer) | ~30 |
| T-3 | `tests/test_orchestrator_rate_limit.py` (NEW) | Regression (orchestrator-layer) | ~40-60 |
| **Total** | | | **~140-160 LOC** |

### 4.4 Regression check

- Full `pytest -x` — expect ≥ 2050 + 4 new tests pass.
- Targeted: `pytest tests/test_scheduler_service.py -v` — all 25 scheduler tests must remain GREEN (no behavior change downstream of the storage fix).
- Targeted: `pytest tests/test_json_utils.py -v` — existing + new T-0 cases all GREEN.

---

## 5. Risk / regression matrix

### 5.1 What we touch (this sprint — Q2=B broad scope approved)

| File | Change | LOC delta | Risk |
|---|---|---|---|
| `tg_parser/domain/json_utils.py` | Append `coerce_aware_utc` def (H-1 promote) | **+6** | Very Low — additive only, no behavior change to existing 4 functions |
| `tg_parser/services/scheduler_service.py` | Delete local `_coerce_aware_utc` (lines 26-47) + add import + rename call site at line 142 + update belt-and-suspenders comment at lines 137-141 | **-21 / +3 = -18 net** | Very Low — behavior identical (no-op coerce when input is already aware post-Option-B; non-no-op when input is naive — matches pre-fix scheduler behavior; PR #79 T-3 stays GREEN) |
| `tg_parser/storage/sqlalchemy/ingestion_state_repo.py` | Add import + wrap 8 naive datetime fields with `coerce_aware_utc(...)` | **+~9-17** | Low — single private builder function, idempotent wrap, no port change |
| `tests/test_json_utils.py` (EXTEND) | T-0 helper contract test (4 cases) | **+~20** | Zero — additive tests |
| `tests/test_ingestion_state_repo_datetime_coerce.py` (NEW FILE) | T-1 (parametrised 8 fields) + T-2 (null guard) | **+~80-100** | Zero — additive tests, new file |
| `tests/test_orchestrator_rate_limit.py` (NEW FILE) | T-3 (orchestrator regression) | **+~40-60** | Zero — additive tests, new file |
| `CHANGELOG.md` | Append Unreleased entry | **+~6** | Zero — docs only |
| `docs/notes/BUG_LOG.md` | Append «Update 2026-05-XX» closure row to BUG-014B entry | **+~3-5** | Zero — docs only |
| `docs/notes/START_PROMPT_FIX_BUG014B_STORAGE_BOUNDARY_2026-05-18.md` | Stage into commit per joint-sprint convention | **+~0** (already untracked, added intact) | Zero |
| **Total** | | **~+150 LOC** (of which ~+10-20 are functional code) | |

### 5.2 What we deliberately do NOT touch (this sprint)

- `parse_iso_datetime` — explicitly out of scope per § 2.3 Option C analysis.
- `_format_datetime` — already aware-tolerant per § 2.1 (write side accepts aware, strips tz on persist — Option B fixes read side, which is sufficient).
- DB column types / Alembic migrations — Option D, ADR-grade, separate sprint.
- BUG-015 (cross-container Telethon re-auth) — ADR-0007-gated, separate sprint.
- Any `tg_parser/bot/**`, `tg_parser/mcp/**` surfaces — orthogonal.
- F4-B Core workspace surfaces — orthogonal.

### 5.3 Validation matrix (acceptance signals — mirror § 5.3 PR #79 format)

| # | Signal | Pre-fix (28h) | Post-fix target (24h watch) | Verification |
|---|---|---|---|---|
| 1 | `TypeError.*offset` count from `orchestrator.py:110` | 56 | **0** | `docker compose logs tg_parser --since 24h \| grep -cE "TypeError.*offset"` |
| 2 | `kdl_ru.last_success_at` non-null | null (since first rate-limit) | non-null within ≤ 2 ticks post-deploy | MCP `get_pipeline_status(channel_id="kdl_ru")` |
| 3 | `profendocrinologist.last_success_at` non-null | null (since first rate-limit) | non-null within ≤ 2 ticks post-deploy | MCP `get_pipeline_status(channel_id="profendocrinologist")` |
| 4 | `kdl_ru.fail_count` | 29+ | 0 (auto-resets on first success) | MCP `get_pipeline_status` |
| 5 | `profendocrinologist.fail_count` | 29+ | 0 (auto-resets on first success) | MCP `get_pipeline_status` |
| 6 | 7 healthy sources non-regression | all healthy | all 7 still healthy, `succeeded=9, failed=0` per tick (was `succeeded=7, failed=2`) | per-tick `Incremental pipeline completed: ...` log |
| 7 | Joint sprint § 5.3 signals (BUG-013/14/24) | 6/6 GREEN | 6/6 still GREEN | mirror probes from REVIEW_2026-05-16_BUG013_14_24_DONE.md § 2 |
| 8 | `_row_to_source.rate_limit_until.tzinfo` for ANY non-null DB row | naive | aware UTC | unit test T-1 (CI gate) |

**Closure criterion: 8/8 GREEN over a 24h post-deploy watch window.**

---

## 6. Execution sequence

### 6.1 Branch

```
git fetch origin
git checkout -b fix/bug-014b-storage-boundary origin/main
```

Base: `origin/main` HEAD at `a8f426a` (DONE marker for BUG-013/14/24).

### 6.2 Commit structure — single atomic commit

Mirror PR #79 convention (single squash-merge with full closure context). Stage exactly:

- `tg_parser/domain/json_utils.py` — H-1 promote helper (+6 LOC)
- `tg_parser/services/scheduler_service.py` — delete local helper + import swap + rename call site + belt-and-suspenders comment (net -18 LOC)
- `tg_parser/storage/sqlalchemy/ingestion_state_repo.py` — import + 8-field coerce wrap (+9-17 LOC)
- `tests/test_json_utils.py` — EXTEND with T-0 helper contract test (+~20 LOC)
- `tests/test_ingestion_state_repo_datetime_coerce.py` — NEW FILE, T-1 parametrised + T-2 null guard (+~80-100 LOC)
- `tests/test_orchestrator_rate_limit.py` — NEW FILE, T-3 orchestrator regression (+~40-60 LOC)
- `CHANGELOG.md` — Unreleased entry (+~6 LOC)
- `docs/notes/BUG_LOG.md` — BUG-014B «Update 2026-05-XX» closure row (+~3-5 LOC)
- `docs/notes/START_PROMPT_FIX_BUG014B_STORAGE_BOUNDARY_2026-05-18.md` — this artifact (already untracked on `fix/bug-014b-storage-boundary` branch, include in commit)

Commit message template:

```
fix(scheduler): coerce naive rate_limit_until to tz-aware UTC at storage boundary (BUG-014B)

Orchestrator-side mirror of BUG-014 (PR #79). After the joint
BUG-013/14/24 fix closed the scheduler-side TypeError at
scheduler_service.py:89, the same naive-vs-aware comparison became
reachable at orchestrator.py:110 — putting kdl_ru +
profendocrinologist into a permanent fail-loop (fail_count=29 each,
56 TypeErrors/day post-deploy).

Option B (per docs/notes/mcp_testing/2026-05-16_claude_session/
analysis_and_options.md § 5): storage-boundary coerce in
SAIngestionStateRepo._row_to_source. The Source class instance is now
tz-aware on read; orchestrator-side comparison succeeds without
modification; scheduler-side _coerce_aware_utc retained as
belt-and-suspenders.

Helper promoted: tg_parser/domain/json_utils.coerce_aware_utc
(was scheduler_service._coerce_aware_utc — module-private). Single
source of truth.

Closes #83
Refs #76 (BUG-013), #77 (BUG-014), #78 (BUG-024) — joint sibling fixes
Refs REVIEW_2026-05-16_BUG013_14_24_DONE.md § 4.2 (known-partial classification)
```

### 6.3 PR template

```
## Summary
Storage-boundary tz-aware coerce for `rate_limit_until` (BUG-014B). Closes the
56-TypeError/day permanent fail-loop on `kdl_ru` + `profendocrinologist` that
surfaced after PR #79 closed the scheduler-side sibling BUG-014.

## Changes
* Promote `_coerce_aware_utc` → `tg_parser.domain.json_utils.coerce_aware_utc`
* Apply `coerce_aware_utc` in `SAIngestionStateRepo._row_to_source.rate_limit_until`
  [+ broader: all naive datetime fields, per § 3.3 decision]
* Keep scheduler-side `coerce_aware_utc` as belt-and-suspenders (with comment)
* Tests: T-1 (repo-layer), T-2 (null guard), T-3 (orchestrator regression)
  [+ T-4 parametrised, broad scope only]

## F4-B / joint-sprint non-regression
* Joint BUG-013/14/24 § 5.3 signals remain GREEN (proof via unchanged behavior
  in scheduler_service.py — only import swap, identity-coerce on already-aware).
* PR #79 T-3 (test_bug014_naive_rate_limit_until_does_not_crash) must remain
  GREEN — explicitly verified in test self-review phase.

## Test plan (CI gates)
* [ ] Ruff format + check pass
* [ ] pytest -x pass (≥ 2050 + 3-4 new)
* [ ] Docker Build pass
* [ ] Alembic Guardrails + Alembic Runtime Upgrade Smoke pass
* [ ] Lint Documentation pass

## Smoke (post-deploy 24h watch)
* `kdl_ru.last_success_at` non-null within 2 ticks
* `profendocrinologist.last_success_at` non-null within 2 ticks
* 0 `TypeError.*offset` lines from `orchestrator.py:110` over 24h
* Per-tick log shape `succeeded=9, failed=0` (was `succeeded=7, failed=2`)

## See also
* PR #79 (BUG-014 sibling, squash `5465918`)
* PR #82 (joint-sprint DONE marker, squash `a8f426a`)
* `docs/notes/mcp_testing/2026-05-16_claude_session/analysis_and_options.md` (Option B rationale)
```

### 6.4 CI gates

All 5 checks must pass (same matrix as PR #79 / #81 / #82):
- Alembic Guardrails
- Alembic Runtime Upgrade Smoke (testcontainers)
- Docker Build
- Lint Documentation
- Test Python 3.12

### 6.5 Deploy + 24h watch

Mirror PR #79 deploy playbook: squash-merge → SSH fast-forward production → `docker compose up -d --force-recreate tg_parser` → confirm container healthy → MCP probe for `kdl_ru` + `profendocrinologist` → 24h watch window per § 5.3 acceptance signals.

### 6.6 Closure

DONE marker: `docs/notes/REVIEW_2026-05-XX_BUG014B_DONE.md` (filed at 24h watch close). Mirror PR #82 structure but scoped to single bug (shorter — ~150 LOC). Then optional: bundle BUG-014B (+ joint BUG-013/14/24) Active → Resolved move into M-15 docs hygiene sprint.

---

## 7. Out-of-scope / follow-ups

| # | Item | Why deferred | Re-evaluate trigger |
|---|---|---|---|
| 1 | TD-parse-iso-datetime-aware (Option C: structural fix in `parse_iso_datetime`) | Cross-cutting blast radius; affects ~30+ callers; may break consumers expecting naive. ADR or extended test sprint candidate. | If a third naive-vs-aware bug surfaces in any non-`Source` context |
| 2 | DB column → TIMESTAMPTZ migration (Option D) | ADR-grade; requires Alembic upgrade + downgrade roundtrip test against testcontainers Postgres; affects both `tg_parser` and possibly bot/mcp containers. | M-15 docs hygiene or schema audit sprint |
| 3 | BUG-015 (cross-container Telethon code_callback EOFError) | Architectural; ADR-0007-gated separate sprint per `REVIEW_2026-05-16_BUG013_14_24_DONE.md` § 6 #2 | Wave 1 step 3 boundary or user-pain trigger from `trigger_pipeline` users |
| 4 | Engine-leak hypothesis from Claude's regression report | Out of scope for this targeted fix; P1/P2 long tail | Bundle with future scheduler observability sprint |
| 5 | Watchlist GLP-1 anomaly from Claude's regression report | Orthogonal feature surface (F11) | Bundle with F11 hardening sprint |
| 6 | `_run_pipeline_background` consolidation across `mcp_server.py` + `bot/tools.py` | Architectural — same code in two containers; potentially ADR-grade | Bundle with BUG-015 ADR-0007 sprint |
| 7 | BUG-013/14/24/14B Active → Resolved lifecycle move in `BUG_LOG.md` | Per joint-sprint convention (deferred to M-15 hygiene); BUG-014B will join the same batch when closed | M-15 sprint |

---

## 8. User-approved decisions (locked, historical context)

User pre-approved all 6 decisions in the self-review handoff prompt (2026-05-18, post-v1 draft). **No further checkpoint required before Step E.** This section is retained as historical context for future readers.

### 8.1 Locked decisions

| # | Question | Approved | Rationale |
|---|---|---|---|
| Q1 | Helper placement | **A (H-1)** — promote to `tg_parser.domain.json_utils.coerce_aware_utc` | Single source of truth, symmetric naming pair with `parse_iso_datetime`, correct layering. See § 3.2. |
| Q2 | Scope of `_row_to_source` coerce | **B (broad)** — all 8 naive datetime fields | Zero risk delta (idempotent), structural payoff, prevents future BUG-014C/D/E. See § 3.3 table. |
| Q3 | Scheduler-side coerce post-Option-B | **A (keep + comment)** — belt-and-suspenders | PR #79 T-3 test feeds naive value directly bypassing the repo; scheduler-side coerce required for it to pass. See § 3.5. |
| Q4 | Test coverage shape | **B (4 tests, parametrised T-1)** — T-0 + T-1 (×8) + T-2 + T-3 | Matches Q2=B broad scope; T-0 locks helper contract; T-1 covers all 8 fields; T-2 covers null path; T-3 covers orchestrator regression. T-5 deferred. See § 4.2. |
| Q5 | Out-of-scope deferrals | **Confirm all 7** — see § 7 | No promotion to this sprint. |
| Q6 | Sprint cadence | **Mirror PR #79 → PR #82** | Plan → implementation → test self-review → PR → CI → squash-merge → deploy → 24h watch → DONE marker. See § 6. |

### 8.2 Pre-discovery for Step E (Resolved)

Per self-review pass (v1.1):
- `tests/test_json_utils.py` — **EXISTS** (81 lines). T-0 lands as extension.
- `tests/test_ingestion_state_repo.py` (monolith) — **DOES NOT EXIST**. Convention uses scope-specific files. T-1, T-2 land in NEW `tests/test_ingestion_state_repo_datetime_coerce.py`.
- `tests/test_orchestrator.py` — **DOES NOT EXIST**. T-3 lands in NEW `tests/test_orchestrator_rate_limit.py`.
- `IngestionOrchestrator.__init__` signature — to be confirmed during Step E (Read `tg_parser/ingestion/orchestrator.py:50-100`). Mock the minimum dependencies needed to reach line 110 per T-3 stub.
- `Source` is a `class` (not `@dataclass`) per `ports.py:183` — direct construction in T-3 uses positional / keyword args matching the explicit `__init__`.

### 8.3 Step E entry conditions (all satisfied)

- [x] BUG_LOG.md § BUG-014B entry filed (lines 2869-2895)
- [x] GH issue #83 opened
- [x] Branch `fix/bug-014b-storage-boundary` created from `origin/main` HEAD `a8f426a`
- [x] Planning artifact v1.1 (this file) ready, all approved decisions reflected in § 3 / § 4 / § 6
- [x] No port-contract changes required (`_row_to_source` is SA-impl-internal)
- [x] All required source-file line numbers verified (§ 1.1 reads 5-11)

---

## 9. Changelog

| Дата | Версия | Изменение |
|---|---|---|
| 2026-05-18 ~21:15 UTC+4 | v1 (initial) | First draft. Planning-only, awaiting § 8 user OK. Filed as part of BUG-014B sprint kickoff (BUG_LOG entry + GH issue #83 + branch creation in same session). |
| 2026-05-18 ~22:30 UTC+4 | v1.1 (post-self-review) | Self-review pass over v1 found 12 substantive findings + 2 clarifications + 4 cosmetic. Key fixes: (a) `Source` is a `class` not `@dataclass` — terminology corrected throughout; (b) scheduler `_coerce_aware_utc` actual range is lines 26-47 (was incorrectly stated as 26-40); (c) `_pause_source_for_billing` lives at `scheduler_service.py:873`, NOT in orchestrator — fixed in § 3.4; (d) `tests/test_orchestrator.py` and monolithic `tests/test_ingestion_state_repo.py` do NOT exist — § 4.1 + § 6.2 updated to specify NEW files `test_ingestion_state_repo_datetime_coerce.py` and `test_orchestrator_rate_limit.py`; (e) `tests/test_json_utils.py` EXISTS — T-0 lands as extension; (f) added T-0 (helper contract test) with 4 cases — was missing entirely; (g) helper migration plan made explicit (rename, not alias) in § 3.2; (h) port-contract clarification added (`_row_to_source` is SA-impl-internal, no port change); (i) all 6 § 8 decisions consolidated as «locked» with cross-refs into § 3 / § 4 / § 6 — § 8 no longer a checkpoint; (j) field count standardised on 8 throughout (was inconsistent 7 vs 8); (k) § 5.1 file list / § 6.2 commit stage list updated to match § 4.1 verified file existence; (l) § 5.3 row 6 «succeeded=9, failed=0» verified (7+2=9 sources). **Artifact now self-contained and implementation-ready for new-window Step E.** |

---

## Appendix — Cross-references

| Документ | Зачем |
|---|---|
| [`docs/notes/BUG_LOG.md` § BUG-014B](BUG_LOG.md) | Canonical bug entry |
| [`docs/notes/BUG_LOG.md` § BUG-014](BUG_LOG.md) | Sibling scheduler-side fix (resolved via PR #79) — context for Option A vs B tradeoff |
| [`docs/notes/REVIEW_2026-05-16_BUG013_14_24_DONE.md`](REVIEW_2026-05-16_BUG013_14_24_DONE.md) | Joint-sprint DONE marker; § 4.2 = known-partial classification for BUG-014B |
| [`docs/notes/mcp_testing/2026-05-16_claude_session/analysis_and_options.md`](mcp_testing/2026-05-16_claude_session/analysis_and_options.md) | 5-option fix matrix; § 5 = Option B recommendation rationale |
| [`docs/notes/START_PROMPT_FIX_BUG013_SCHEDULER_SESSION_2026-05-15.md`](START_PROMPT_FIX_BUG013_SCHEDULER_SESSION_2026-05-15.md) | Joint-sprint planning precedent (9-section structure mirrored here); § 3.2 = original deferral rationale for parse-time fix |
| GH issue [#83](https://github.com/AlexEfimov/TG_parser/issues/83) | Tracking issue for this sprint |
| GH PR [#79](https://github.com/AlexEfimov/TG_parser/pull/79) (squash `5465918`) | Joint BUG-013/14/24 fix — sibling closed |
| GH PR [#82](https://github.com/AlexEfimov/TG_parser/pull/82) (squash `a8f426a`) | Joint-sprint DONE marker — closure precedent for this sprint's DONE marker |
| [`tg_parser/storage/sqlalchemy/ingestion_state_repo.py`](../../tg_parser/storage/sqlalchemy/ingestion_state_repo.py) lines 412-453 | `_row_to_source` builder — the fix surface (SA-impl-internal, no port change) |
| [`tg_parser/storage/sqlalchemy/ingestion_state_repo.py`](../../tg_parser/storage/sqlalchemy/ingestion_state_repo.py) lines 455-459 | `_format_datetime` — lossy write-side (no change required, see § 3.4) |
| [`tg_parser/storage/ports.py`](../../tg_parser/storage/ports.py) lines 183-236 + 239-371 | `Source` class (NOT a `@dataclass`) + `IngestionStateRepo` abstract base — verifies port-contract is unchanged |
| [`tg_parser/domain/json_utils.py`](../../tg_parser/domain/json_utils.py) lines 80-94 | `parse_iso_datetime` — the naive-source-of-truth; target location for promoted `coerce_aware_utc` |
| [`tg_parser/services/scheduler_service.py`](../../tg_parser/services/scheduler_service.py) lines 26-47 | Existing `_coerce_aware_utc` helper — to be promoted to shared utility |
| [`tg_parser/services/scheduler_service.py`](../../tg_parser/services/scheduler_service.py) line 142 | Scheduler-side call site (renamed to `coerce_aware_utc(...)` post-fix) |
| [`tg_parser/services/scheduler_service.py`](../../tg_parser/services/scheduler_service.py) line 873 | `_pause_source_for_billing` — companion write-path (aware on write, lossy on persist, caught on read post-Option-B) |
| [`tg_parser/ingestion/orchestrator.py`](../../tg_parser/ingestion/orchestrator.py) lines 100-122 | The TypeError site (`if source.rate_limit_until and source.rate_limit_until > datetime.now(UTC)`) |
| [`tg_parser/ingestion/orchestrator.py`](../../tg_parser/ingestion/orchestrator.py) lines 470-497 | `_maybe_set_rate_limit` — aware-on-write companion |
| [`tests/test_json_utils.py`](../../tests/test_json_utils.py) | EXISTS (81 lines) — T-0 lands as extension |
| `tests/test_ingestion_state_repo_datetime_coerce.py` | **NEW FILE** — T-1 + T-2 |
| `tests/test_orchestrator_rate_limit.py` | **NEW FILE** — T-3 |
| [`tests/test_scheduler_service.py`](../../tests/test_scheduler_service.py) | EXISTS — must remain GREEN (regression invariant), especially `test_bug014_naive_rate_limit_until_does_not_crash` |
| [`docs/quality/AGENT_PLAYBOOK.md`](../quality/AGENT_PLAYBOOK.md) | Quality lifecycle norms (planning → implementation → MCP-verdict → DONE marker) |
| [`AGENTS.md`](../../AGENTS.md) | Workspace conventions (no-commit-without-OK rule applies here at § 8) |
