# START_PROMPT — F9 Phase 3: Full Security Hardening (**PLANNING**)

**Created:** 2026-07-16.
**Type:** **PLANNING** start-prompt (design / gap-audit / ranked backlog). **NO production code changes** in this session until an IMPLEMENTATION START_PROMPT is written and the owner switches sessions.
**Branch base:** `main`. **Repo:** `/Users/alexanderefimov/TG_parser`.
**HEAD this note targets:** `7fd888c` (`Merge pull request #321` — F9 Phase 2 prompt-defense). Verify with `git rev-parse --short HEAD`.
**Prod:** `main` = prod = `7fd888c` (Phase 2 deployed 2026-07-16: rebuild + recreate app + Prometheus). Confirm on deploy host before assuming anything else is live.
**Status:** `done` (planning + self-review 2026-07-16). Final impl SoT: [`START_PROMPT_F9_PHASE3_FULL_HARDENING_IMPLEMENTATION_2026-07-16.md`](START_PROMPT_F9_PHASE3_FULL_HARDENING_IMPLEMENTATION_2026-07-16.md) (`ready for impl session`). Background: [`PLAN_F9_PHASE3_FULL_HARDENING_2026-07-16.md`](PLAN_F9_PHASE3_FULL_HARDENING_2026-07-16.md).
**Tracking:** F9 Phase 3 in [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) § F9; Wave 4 item before F7 Billing. No new BUG id unless a regression is found during later impl.
**Estimated effort (this planning session):** ~0.3–0.5 session. **Impl (after):** ~1–1.5 session (catalog) — may shrink after prune + MUST ranking.

> **This prompt is the SOURCE OF TRUTH for the planning session.** Read first, in order:
> 1. [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) § **F9** — Phase 3 catalog (8 steps) + “перед F7”.
> 2. [`START_PROMPT_F9_PHASE2_PROMPT_DEFENSE_2026-07-16.md`](START_PROMPT_F9_PHASE2_PROMPT_DEFENSE_2026-07-16.md) — Phase 2 ship bar + **Phase 3 prune** table + carry-forwards (F3/F5 / remaining `.format`).
> 3. ADR [`0017-dependency-management-policy.md`](../adr/0017-dependency-management-policy.md) §7 — Renovate/Dependabot **deferred** (do not reopen casually).
> 4. This document — preliminary gap snapshot + decision forks + planning deliverables.
> 5. Workflow: commit only on explicit ask; ЗК only if planning produces code (it should not); no deploy from planning.

### Sibling / do-not-conflate

- **Phase-1 watch t2** (Cursor Automation, BUG-084 soak) runs in parallel — **not** part of F9 Phase 3. Do not burn this session on W2 S3 verdict docs unless owner redirects.
- **F8-B Redis / F4-A Multi-User / F7 Billing** — downstream Wave 4; Phase 3 is a **prerequisite for F7**, not a substitute for Redis/multi-user.

---

## CRITICAL OPERATIONAL WARNINGS — READ FIRST

1. **PLANNING ONLY.** Do **not** implement Telethon session encryption, `audit_log` migrations, CSP middleware, vault wiring, `pip-audit` CI, or pentest docs **as production changes** in this session. Output = design artifacts + (optional) draft IMPLEMENTATION START_PROMPT.
2. **Do NOT touch** `pyproject.toml`, `requirements.txt`, `docs/methodology/**` unless the planning outcome *explicitly* requires a later impl note (still no edit here without owner ask).
3. **Do NOT reopen Dependabot/Renovate** without revisiting ADR 0017 §7 and an explicit owner decision. Optional `pip-audit` CI job is a **separate** discussable item (manual audit ≠ bot PRs).
4. **Do NOT weaken** Phase 1 auth, Phase 2 prompt-defense, confirm-flow / BUG-009, or tenant scoping as “hardening side effects”.
5. **Do NOT claim** “fully hardened” / “pentest-proof” in any draft docs — defense-in-depth language only.
6. **Migrations:** any `audit_log` design must respect Alembic-only schema (no `init_*_schema` revival). Flag multi-DB branch impact (`processing` / auth) early.
7. **Secrets / sessions on prod:** treat `data/sessions/*.session` and `.env` as high-sensitivity; planning may inspect **paths and code**, not dump live session contents into notes.
8. **Deploy** only after a future impl PR + explicit owner approval (same convention as Phase 2).

---

## TL;DR

F9 Phase 1 (auth/CORS/logging) and Phase 2 (prompt-injection defense-in-depth) are **shipped**. Catalog Phase 3 still lists 8 steps, but gap-audit already shows **2 DONE** and **Dependabot OUT**. This planning session must:

1. Re-verify prune at HEAD `7fd888c`.
2. Rank remaining OPEN items into **MUST-for-ship / SHOULD / NICE / DEFER-to-enterprise**.
3. Lock decisions on the hard forks (session encryption approach, audit_log schema + write sites, CSP applicability, vault vs stay-on-`.env`, pip-audit yes/no).
4. Decide whether Phase 2 **carry-forwards** (OutputValidator, destructive rate-limit, remaining `.format`) enter the same impl PR or stay follow-ups.
5. Emit a **draft IMPLEMENTATION START_PROMPT** with ship bar + acceptance + file anchors — ready for a separate impl session.

**Success of planning ≠ merge.** Success = owner-approved ranked backlog + locked forks + impl prompt draft.

---

## Catalog vs prune (preliminary — re-verify in session)

Source catalog: [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) § F9 Phase 3. Prune evidence from Phase 2 START_PROMPT (confirm still true at `7fd888c`).

| # | Catalog item | Preliminary status | Notes / anchors |
|---|--------------|--------------------|-----------------|
| 1 | Pin dependencies (`uv lock`) | **DONE — prune** | `uv.lock`; ADR 0017; `deps-lock-guard` CI |
| 2 | CI security scanning (`pip-audit` / Dependabot / Snyk) | **SPLIT** | Dependabot/Renovate **OUT** (ADR 0017 §7). Optional **`pip-audit` job** = discuss (SHOULD/NICE). Snyk not in repo today |
| 3 | API key hashing | **DONE — prune** | `hash_credential` — [`tg_parser/auth/resolvers.py`](../../tg_parser/auth/resolvers.py) ~81 |
| 4 | Telethon session encryption at rest | **OPEN — likely MUST** | Plain sqlite session under `data/sessions/` (compose bind `./data/sessions:/app/sessions`); `TELEGRAM_SESSION_NAME`; client in `tg_parser/ingestion/telegram/telethon_client.py`; CLI path check [`tg_parser/cli/app.py`](../../tg_parser/cli/app.py) ~51 |
| 5 | Audit log (immutable) | **OPEN — likely MUST for F7 path** | Mentions in runbooks only; no `audit_log` table. Write surfaces to consider: add/remove channel, LLM config change, auth register/login failures, soft-delete. Medium effort — primary schedule risk |
| 6 | CSP headers | **OPEN — probably DEFER** | No first-party web dashboard/UI app in tree (Grafana/Caddy are infra). CSP only if planning finds a real HTML surface we own; otherwise document **N/A until dashboard** |
| 7 | Secrets vault | **OPEN — likely DEFER (enterprise)** | Still `.env` + compose env. Vault (HashiCorp/AWS SM) = Medium + ops burden; personal/small-team may stay on `.env` with tighter file perms + backup policy |
| 8 | Penetration testing guide | **OPEN — SHOULD** | Docs-only runbook under `docs/runbooks/` — attack vectors for manual testing; no claim of full coverage |

### Phase 2 carry-forwards (decide IN vs OUT of Phase 3 impl)

| Item | From Phase 2 | Preliminary lean |
|------|--------------|------------------|
| F3 OutputValidator | Deferred SHOULD | **Follow-up** unless cheap narrow strip fits same PR |
| F5 Destructive-op rate limit | Skipped NICE | **Follow-up** (or F8-B Redis shared limits later) |
| Remaining `.format` (digest / resummarize / topicization / merge / …) | SHOULD polish | **Follow-up** or small SHOULD if session has budget after MUST |

---

## Gap-audit checklist (planning session work)

Re-run / deepen with code evidence (read-only). Fill a short table in the planning notes or into the draft impl prompt.

### A — Session files
- [ ] Where sessions are created/rotated; backup story on prod.
- [ ] Telethon API: does current Telethon version support encrypted sessions / StringSession / external crypto wrapper?
- [ ] Key management: env-derived key vs OS keychain vs age/sops — threat model for single VPS.
- [ ] Migration path for existing plain `.session` without forcing re-login if avoidable.
- [ ] Interaction with BUG-013 / concurrent Telethon session use (locks) — encryption must not break advisory locking story.

### B — Audit log
- [ ] Which DB branch owns the table (auth vs processing)? Prefer one clear home.
- [ ] Event taxonomy (minimal MVP list) vs “log everything”.
- [ ] Append-only invariants (no UPDATE/DELETE from app; retention policy?).
- [ ] PII / secrets: never store raw API keys, confirm tokens, session bytes.
- [ ] Query///MCP surface: admin-only read? Out of MVP?
- [ ] Hook points: bot tools / API routes / MCP — prefer few choke points over scatter.

### C — CSP
- [ ] Confirm no owned browser app that serves HTML for end users.
- [ ] If only Grafana/Caddy: CSP is **ops/Grafana config**, not tg_parser app code — document OUT.

### D — Vault / secrets
- [ ] Current secret inventory (`.env`, compose, GH secrets if any).
- [ ] Cost/complexity of vault for single-node prod vs documented `.env` hardening (perms, no world-readable, backup encryption).
- [ ] Recommendation: **defer vault** unless owner signals enterprise timeline.

### E — pip-audit
- [ ] Feasibility of CI job (`uv`/`pip-audit`) without Dependabot PRs.
- [ ] Failure policy: warn vs gate merge; noise management with lockfile.
- [ ] Align with ADR 0017 (manual freshness stays if Dependabot remains deferred).

### F — Pentest guide
- [ ] Outline sections: auth bypass, tenant isolation, confirm-flow, prompt injection (Phase 2), session theft, export privacy (`raw_payload`), LLM config mutation.
- [ ] Point to existing tests (`tests/test_api_security.py`, Phase 2 tests) as regression anchors — not a substitute for manual tests.

---

## Decision forks to lock (owner + agent)

Planning must produce an explicit choice for each fork (record in draft impl prompt).

| ID | Fork | Options (sketch) | Default lean (pre-debate) |
|----|------|------------------|---------------------------|
| D1 | Session encryption | (a) Telethon-native if available (b) encrypt file at rest with app-managed key (c) OS disk encryption only + perms | Prefer (b) or (a) after Telethon research; (c) alone = weak for portable bind-mount |
| D2 | Session key storage | env `TELEGRAM_SESSION_KEY` / file mode 600 / external KMS | env on single VPS for MVP |
| D3 | Audit log MVP events | minimal write-set vs broad | **Minimal write-set** (channel lifecycle + LLM config + auth failures) |
| D4 | Audit log retention | forever vs TTL | forever for MVP (small volume); TTL later |
| D5 | CSP | implement in FastAPI middleware vs N/A | **N/A** unless dashboard found |
| D6 | Vault | implement vs defer | **Defer** (document hardening checklist instead) |
| D7 | pip-audit CI | gate / report-only / skip | **Report-only** or skip if noisy; no Dependabot |
| D8 | Phase 2 carry-forwards | same impl PR vs follow-up | **Follow-up** (keep Phase 3 PR focused) |
| D9 | Ship bar for impl | which of {session encrypt, audit_log, pentest doc, pip-audit} are MUST | Propose: **session encrypt + audit_log MVP + pentest guide**; pip-audit SHOULD; vault/CSP OUT |

---

## Suggested planning order

```text
1. Verify HEAD/prod = 7fd888c; skim Phase 2 prune still accurate
2. Deepen gap-audit A–F (read-only); fill evidence table
3. Debate D1–D9 with owner; lock choices in writing
4. Draft ranked backlog MUST / SHOULD / NICE / OUT for impl
5. Write draft START_PROMPT_F9_PHASE3_*_IMPLEMENTATION_*.md
   (warnings, ship bar, file anchors, acceptance, ЗК, no Phase-2 regressions)
6. Self-review the planning artifacts (consistency, no scope creep into F7/F8-B)
7. Stop — wait for owner to open impl session from the draft prompt
```

---

## Planning deliverables (acceptance for *this* session)

1. **Updated prune/status table** at current HEAD (DONE / OPEN / OUT) with file anchors.
2. **Locked decisions** D1–D9 (or explicit “parked — needs owner input” with recommendation).
3. **Ranked impl backlog** with ship bar (~1–1.5 session fit).
4. **Draft IMPLEMENTATION START_PROMPT** path under `docs/notes/` (new file; status `draft` until owner marks ready).
5. **OUT list** crystal-clear: Dependabot, vault (if deferred), CSP (if N/A), F7 billing work, F8-B Redis.
6. **No production code merge** required; optional docs-only PR for the planning notes + draft impl prompt **only if owner asks to commit**.

---

## Scope OUT (planning and later impl unless reopened)

- F7 Billing implementation.
- F8-B Redis / shared rate limits (may absorb F5 destructive limits later).
- F4-A Multi-User expansion.
- Reverting Phase 1 M3 tool-args INFO logging.
- Re-doing Phase 2 prompt-defense (already shipped).
- Dependabot/Renovate enablement without ADR 0017 revisit.
- `docs/methodology/**`.
- Creating `tg_parser/security/` package without an explicit locked decision (prefer small utils / existing auth modules unless audit_log needs a clear home).

---

## Refs

- [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) § F9 Phase 3
- [`HANDOFF_2026-07-16.md`](HANDOFF_2026-07-16.md) — update mentally: Phase 2 done @ `7fd888c`; Phase 3 planning is next code track
- Phase 2 impl + prune: [`START_PROMPT_F9_PHASE2_PROMPT_DEFENSE_2026-07-16.md`](START_PROMPT_F9_PHASE2_PROMPT_DEFENSE_2026-07-16.md)
- ADR 0017: [`../adr/0017-dependency-management-policy.md`](../adr/0017-dependency-management-policy.md)
- Auth hashing: [`tg_parser/auth/resolvers.py`](../../tg_parser/auth/resolvers.py)
- Sessions: compose `data/sessions`, [`docs/prompts/D3-telegram-session-docker.md`](../prompts/D3-telegram-session-docker.md), Telethon client under `tg_parser/ingestion/telegram/`
- API security tests (extend later): [`tests/test_api_security.py`](../../tests/test_api_security.py)
- Phase 2 tests: [`tests/test_f9_phase2_prompt_defense.py`](../../tests/test_f9_phase2_prompt_defense.py)
- Format precedent (planning-only): [`START_PROMPT_S5_TOPK_ASSIGN_PLANNING_2026-07-11.md`](START_PROMPT_S5_TOPK_ASSIGN_PLANNING_2026-07-11.md)

---

## Copy-paste opener for the planning chat

```text
Открой docs/notes/START_PROMPT_F9_PHASE3_FULL_HARDENING_PLANNING_2026-07-16.md
и веди PLANNING-сессию F9 Phase 3 по нему.
Код prod не меняй. Цель: gap-audit → lock D1–D9 → ranked MUST/SHOULD →
черновик IMPLEMENTATION START_PROMPT.
Коммит только по моей явной просьбе.
```
