# TAXONOMY — Labels vocabulary for `docs/quality/`

**Purpose:** fixed, small vocabulary of labels used on every observation / incident
entry. Keeps `INBOX.md` greppable and makes triage groupings mechanical.

> **Для AI-агента:** алгоритм выбора лейблов из произвольного пользовательского
> описания — в [`AGENT_PLAYBOOK.md`](AGENT_PLAYBOOK.md) §3 (keyword-эвристики
> для `component` / `type` / `severity` + tie-breaker'ы). Этот файл — словарь;
> playbook — как им пользоваться.

**Usage:** three labels per entry, space-separated or dot-delimited, in the order
`component · type · severity`:

```
## 2026-04-21 08:45 UTC — bot · ux · P2
```

Do **not** invent labels outside the sets below. If a new label is genuinely
needed, add it here first (one-line commit) and then use it in `INBOX.md`.

---

## `component` — which subsystem the observation is about

| Label | Scope |
|---|---|
| `bot` | Telegram bot (`tg_parser/bot/`), including handlers, scheduler, message formatting |
| `mcp` | MCP server (`tg_parser/mcp_server.py`), tool definitions, agent-facing API |
| `api` | HTTP API (`tg_parser/api/`), REST endpoints, middleware, auth |
| `ingestion` | Raw ingestion (`tg_parser/ingestion/`), Telethon, rate limiting, raw storage |
| `processing` | Per-message processing (`tg_parser/processing/`), LLM calls, dedup, embeddings |
| `topicization` | Topic discovery + card generation (`tg_parser/processing/topicization.py`, `services/topicization_service.py`) |
| `rag` | Retrieval + Q&A (`tg_parser/retrieval/`, RAG prompts, hybrid search) |
| `dedup` | Content-hash deduplication (F5-A Phase 3) |
| `migrations` | Alembic, schema, `_metadata.py` drift |
| `scheduler` | Background scheduler (`tg_parser/services/background_scheduler.py`, `scheduler_service.py`), incremental pipeline, digests |
| `infra` | Docker, compose, VPS, monitoring (Prometheus / Grafana / Caddy), backups |
| `cli` | Command-line surface (`tg_parser/cli/`) |
| `docs` | Documentation files, runbooks, prompts |
| `tests` | Test suite, fixtures, CI |

---

## `type` — nature of the observation

| Label | Meaning |
|---|---|
| `bug` | Behaviour deviates from documented / expected contract. Has reproduction. |
| `ux` | Surface works, but is confusing, inconsistent, or hard to use. No data loss. |
| `docs` | Documentation is missing, stale, or misleading. |
| `perf` | Works correctly but slow / wasteful (latency, cost, resource usage). |
| `reliability` | Fragility: works today but likely to fail under realistic load / conditions. |
| `security` | Confidentiality / integrity / auth / privacy concerns. Prefer `P0`/`P1`. |
| `observability` | Missing metric, log, alert, or audit trail needed to diagnose / prevent. |
| `question` | Open question or investigation needed; not yet a confirmed defect. |

---

## `severity` — impact-based priority

| Label | When |
|---|---|
| `P0` | Production is down or corrupting data. Drop everything. |
| `P1` | A feature is broken for users but the system is up. Fix within the current sprint. |
| `P2` | Quality gap — functionality works, but output is wrong, slow, or confusing. Fix within 1–2 sprints. |
| `P3` | Nice-to-have polish. Ship when convenient. |

**Tie-breakers:**
- **Silent failure** (no error surfaced, incorrect state persists) ⇒ bump one level up from what functional impact alone would suggest. A P2 bug that fails silently becomes P1.
- **Affects data integrity** ⇒ minimum `P1`.
- **Affects onboarding / first-impression user path** ⇒ minimum `P2`.

---

## Status (set during triage, not on capture)

Used in `TRIAGED.md` and sometimes inline in `INBOX.md` after triage:

| Status | Meaning |
|---|---|
| `open` | In INBOX, not yet triaged. |
| `triaged → <Sprint-ID>` | Converted to a sprint scope item (new sprint prompt or addition to existing). |
| `fixed → <commit>` | Landed on main; commit hash for audit. |
| `wontfix` | Decided not to address; rationale must be in `TRIAGED.md`. |
| `duplicate → <INBOX-entry-id>` | Merged into an earlier entry. |

---

## Adding a new label

If none of the above fits, **do not silently improvise.** Append the new label
to the relevant table here in a single doc-only commit, then use it. This keeps
downstream tooling (grep-based triage, future bot-command intake, metrics on
incident clusters) reliable.
