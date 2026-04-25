# Template — single INBOX entry

Copy the block below into `docs/quality/INBOX.md` at the **top** (newest-first)
and fill in the fields. Target: ~30 seconds per entry. Five fields, all required
except `Repro` (may be "n/a — observed once in production").

For big incidents that need a full timeline / SQL / stacktrace, use
`_TEMPLATE_INCIDENT.md` instead and link to it from INBOX with `→ incidents/...`.

---

```markdown
## 2026-MM-DD HH:MM UTC — <component> · <type> · <severity>

**Что:** one sentence, present tense. What is wrong or suspect.

**Как воспроизвести:** minimal steps or a command. If not reproducible, say so.

**Ожидал:** what the correct / intended behaviour is, briefly.

**Контекст:** environment (VPS / local), code version / commit, channel name,
user role — anything that narrows the scope. Leave `n/a` if irrelevant.

**Заметки:** free-form — related observations, suspected module, links to
other INBOX entries (`see 2026-04-22 09:10`), guesses. Safe to leave empty.

---
```

**Taxonomy labels** (see `TAXONOMY.md` for full list):

- `component`: `bot` · `mcp` · `api` · `ingestion` · `processing` · `topicization` · `rag` · `dedup` · `migrations` · `scheduler` · `infra` · `cli` · `docs` · `tests`
- `type`: `bug` · `ux` · `docs` · `perf` · `reliability` · `security` · `observability` · `question`
- `severity`: `P0` · `P1` · `P2` · `P3`

**When to upgrade this to a full incident file (`incidents/…`):**

- The observation involves a multi-step timeline (>3 timestamped events).
- You have SQL output, tracebacks, API response bodies worth preserving verbatim.
- Impact is >1 channel / >1 user, or required manual repair.
- Investigation time already spent exceeds ~15 minutes.

Short observations stay in `INBOX.md`; big ones get their own file under
`incidents/YYYY-MM-DD_<short-slug>.md` and the INBOX entry becomes a one-liner
pointer: `→ incidents/2026-04-20_genotek_topicization_silent_failure.md`.
