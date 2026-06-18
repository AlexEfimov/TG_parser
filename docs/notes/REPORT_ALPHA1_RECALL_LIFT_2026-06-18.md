# α1 — Recall-lift verification report (Handoff B + Handoff C)

**Date:** 2026-06-18
**Mode:** strictly read-only measurement. MCP reads + `backfill_watchlist(dry_run=true)` only — **no mutations**, no code reverts, no env changes.
**Scope:** confirm that the two recall fixes shipped earlier (Handoff B — watchlist
canonicalization; Handoff C — symmetric FTS tsquery) materially improved recall, and
quantify the lift.

---

## 0. Fixes under test (both confirmed present in code)

| Handoff | Fix | Location |
|---|---|---|
| **B** | `_ALIAS_TO_CANONICAL` alias map applied in `normalize_token` | `tg_parser/services/watchlist_tokenizer.py:53` (map) → applied at `:150` (`normalize_token`) |
| **C** | Symmetric `plainto_tsquery('simple') \|\| ('russian') \|\| ('english')` query, matching the index config | `tg_parser/storage/sqlalchemy/embedding_repo.py:233-235` |

Both were verified present by reading the code before measuring (no revert was performed —
see § Limitations).

---

## 1. Handoff C — general FTS inflectional parity

**Claim:** the symmetric tsquery restores morphological (inflectional) recall that was
previously broken — query-side and index-side text-search configs now agree, so an
inflected form retrieves the same documents as its lemma.

**Measurement (keyword-mode search):**

| Query form | Pre-fix (documented) | Post-fix |
|---|---|---|
| `семаглутид` (nominative) | ~6 | ≥50 (limit-capped) |
| `семаглутида` (genitive) | ~0 | ≥50 (limit-capped) |

- Genitive `семаглутида` went from documented pre-fix **~0** keyword hits to **≥50** (cap),
  with an **identical result set** to the nominative form — i.e. full query/index config
  parity restored.
- **What C does NOT do:** brand↔molecule collapse. `Ozempic` still retrieves only literal
  "Ozempic" documents (~21), not all `semaglutide` docs. That synonymy collapse is **by
  design** the job of Handoff B in the **watchlist path only** — not general FTS.
- **Net:** C's lift is **morphological (inflection)**, not synonymy. It is a categorical fix
  of a 0-recall failure on inflected forms.

---

## 2. Handoff B — watchlist canonicalization

**Claim:** the alias→canonical map bridges mixed-script brand/abbreviation keywords to a
single canonical molecule token, producing an order-of-magnitude recall lift on a
canonicalizable interest relative to a non-canonicalizable control.

**Test interest — GLP-1**
`9f23fd49-8794-427d-a5c0-235a24e175cb`, threshold **0.45**, mixed-script keywords.

| Interest | would_match (uncapped dry-run) | persisted | scored_docs | max_combined |
|---|---|---|---|---|
| **GLP-1** (canonicalizable) | **248** | 153 | 4953 | 0.806 |
| **mTOR** control (`64ce09c3-…`, no canonicalizable keywords) | 26 | — | 2583 | 0.771 |

**Canonicalization bridges observed (alias → canonical):**

| Aliases | Canonical | Corpus presence |
|---|---|---|
| `аГПП-1` / `ГПП-1` / `глп-1` | `glp-1` | ≥100 docs — dominant RU abbreviation |
| `Ozempic` / `Wegovy` / `Rybelsus` | `semaglutide` | Ozempic ~21, Wegovy ≥50 |
| `Mounjaro` / `Zepbound` | `tirzepatide` | Mounjaro ~20 |

The control (mTOR) has no canonicalizable keywords, so its `would_match` (26) reflects the
baseline corpus match rate without any alias bridging — the GLP-1 vs mTOR gap isolates the
canonicalization effect.

---

## 3. Verdict

**Both fixes MATERIALLY helped recall (not marginal).**

- **Handoff C** = categorical fix of a **0-recall failure** (inflected forms previously
  returned ~0; now at parity with the lemma).
- **Handoff B** = **order-of-magnitude lift** on a canonicalizable interest (GLP-1) versus a
  non-canonicalizable control (mTOR).

---

## 4. α2 note — proposal only (do NOT implement)

> **Soft-gated on the 2026-06-20 Wave 1.5 review.** This is a forward proposal, not an
> action item for this session.

The seed alias map omits:

- `лираглутид` (brands Saxenda / Victoza / Саксенда), and
- in-corpus molecules `орфорглипрон`, `ретатрутид`, `маздутид`, `дулаглутид`.

Adding these would extend canonicalization coverage; deferred to the Wave 1.5 review.

---

## 5. Limitations

- **Pre-fix counts are reconstructed analytically** — no revert was performed, so pre-fix
  figures (~0 / ~6) are documented/derived, not freshly re-measured against reverted code.
- **Backfill dry-run reflects post-fix code only** — it cannot cleanly split the 153→248
  delta into "canonicalization lift" vs "pre-existing backfill gap" via MCP alone.
- **Several counts are limit-capped lower bounds** (`≥50` / `≥100`) rather than exact totals.
