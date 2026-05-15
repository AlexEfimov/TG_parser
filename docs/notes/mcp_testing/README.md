# MCP Testing Sessions

External testing sessions of the TG_parser MCP surface — bug reports, enhancement proposals, operational findings, and data quality assessments produced by AI agents or human operators exercising the deployed MCP tools end-to-end.

## Purpose

Each session lives in a dedicated subdirectory and is a **read-only snapshot** of the testing agent's output. Derived actions (bug filings, parity tracker updates, ADR drafts, planning artifacts) are landed via separate PRs that reference the snapshot, preserving the raw artifact's integrity for audit / regression / methodology lessons.

## Sessions

| Date | Tester | Files | Key findings | Derived-action PR |
|---|---|---|---|---|
| [2026-05-15](2026-05-15_claude_session/) | Claude (Anthropic) | 6 documents (~129 KB) | 11 issues + 13 enhancements + 12 observations + 4 data anomalies + 8 runbook procedures | _(filled when PR B lands)_ |

## Conventions

- Subdirectory: `YYYY-MM-DD_<tester>_session/` (sortable, identifies tester)
- Entry point: `README.md` inside each session subdirectory
- Numbered files: `01-bug-report.md`, `02-enhancements.md`, etc. (consistent within each session, varies across sessions as the testing scope dictates)
- **Read-only**: snapshot files are not edited after intake. Refinements happen in derived-action PRs.

## Related

- [BUG_LOG.md](../BUG_LOG.md) — current Active / Resolved bug tracker; references session findings via BUG-XXX IDs
- [PARITY_DECISION_TRACKING.md](../PARITY_DECISION_TRACKING.md) — parity gap tracker; session-discovered gaps land as O-N observations
