# Template — full incident / RCA file

Use this when an INBOX entry outgrows a five-line note: real timeline, SQL
outputs, stacktraces, lessons learned. File name pattern:

```
docs/quality/incidents/YYYY-MM-DD_<short-kebab-slug>.md
```

`YYYY-MM-DD` = date the incident was **observed** (not when written up). Slug
= ≤5 words, e.g. `genotek_topicization_silent_failure`.

Link to this file from `INBOX.md` (one-liner) and from `TRIAGED.md` (after
decision about what sprint absorbs the fix).

---

```markdown
# <One-line headline — what happened, in past tense>

**Date:** YYYY-MM-DD
**Observed in:** production (VPS) / local / CI
**Component(s):** <from TAXONOMY.md — usually 1–3 of bot/mcp/processing/…>
**Severity:** P0 / P1 / P2 / P3
**Status:** investigating | triaged → Sprint X.Y | fixed → <commit> | wontfix
**Author:** <who wrote this up>

---

## Summary

Two-to-four sentences. What the user saw, what the system did, what the damage
was. Written so a future maintainer grokking the repo can decide in 20 seconds
whether this incident is relevant to their current problem.

---

## Timeline (UTC unless noted)

| Time | Event |
|------|-------|
| HH:MM | Trigger / first external signal |
| HH:MM | First automated / manual detection |
| HH:MM | Investigation / mitigation step |
| HH:MM | Resolution / workaround applied |
| HH:MM | Post-incident state confirmed |

---

## Root cause

One-paragraph technical explanation. Include file paths and, if possible,
line-precise references: `tg_parser/services/topicization_service.py:142`.

If multiple contributing causes — list them separately (primary / secondary /
latent defect) — RCAs with a single “root cause” usually miss contributing
factors.

---

## Evidence

### Logs

    <paste relevant loglines, stripped of PII; use fenced code blocks>

### SQL / state snapshots

```sql
-- queries you ran to confirm the damage
```

### Stacktraces / API responses

```text
<verbatim — these age well and are hard to reconstruct later>
```

---

## Impact

- **Users affected:** number / roles / channels
- **Data affected:** tables / rows / entities; is it recoverable?
- **Downstream impact:** did other subsystems degrade as a result?
- **Duration:** from first failure to full recovery

---

## What we did (mitigation)

Chronological actions taken to restore service. Include exact commands where
they matter — these become the basis for a runbook entry later.

---

## What still needs to happen (follow-ups)

Numbered list. Each item should be concrete enough to become a sprint scope bullet.

1. …
2. …
3. …

Mark which of these are absorbed into which sprint in `TRIAGED.md`.

---

## Lessons / latent defects exposed

Separate this from *root cause*. Root cause is “what caused this specific
incident”; lessons are “what this incident **revealed** about the system that
would have bitten us even if this trigger had not fired.”

Bullet list, one defect per bullet, each a candidate for its own sprint /
PR / INBOX entry.

---

## Cross-references

- INBOX entry: `docs/quality/INBOX.md` → `<date + headline>`
- Triage entry: `docs/quality/TRIAGED.md` → `<sprint>`
- Related incidents: `docs/quality/incidents/<file>.md`
- Related future-features section: `docs/notes/FUTURE_FEATURES.md` § `<anchor>`
- Related roadmap section: `docs/notes/ROADMAP_V3_PRODUCTION_FIRST.md` § `<anchor>`
```
