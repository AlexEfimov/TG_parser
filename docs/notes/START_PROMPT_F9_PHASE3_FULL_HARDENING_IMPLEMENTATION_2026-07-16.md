# START_PROMPT — F9 Phase 3: Full Security Hardening (IMPLEMENTATION)

**Created:** 2026-07-16. **Revised:** 2026-07-16 (post self-review — **final for impl**).
**Type:** IMPLEMENTATION start-prompt. Design from planning gap-audit; **NO code changed yet**.
**Status:** `open` / **design-in-prompt** / **ready for impl session**.
**Branch base:** `main`. **Repo:** `/Users/alexanderefimov/TG_parser`.
**HEAD this note targets:** re-verify at impl start with `git rev-parse --short HEAD` (planning audited `5e1612d`; Phase 2 merge `7fd888c`).
**Prod:** confirm Phase 2 (+ later commits) on deploy host before assuming live baseline.
**Tracking:** F9 Phase 3 in [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) § F9; Wave 4 prerequisite before F7. No new BUG id unless regression found.
**Estimated effort:** ~1–1.5 session (catalog); prune already removed pin-deps + API-key hashing.
**Planning source (reference only):** [`PLAN_F9_PHASE3_FULL_HARDENING_2026-07-16.md`](PLAN_F9_PHASE3_FULL_HARDENING_2026-07-16.md).

> **This prompt is the SOURCE OF TRUTH for the implementation session.** Read first, in order:
> 1. This document — warnings, ship bar, locked design, acceptance, workflow.
> 2. [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) § **F9** Phase 3 catalog + “перед F7” (context only).
> 3. Workflow: commit only on explicit ask; PR merge = merge-commit + `--delete-branch`; ЗК = `ruff check` + `ruff format --check` + pytest default + `TEST_POSTGRES=1` ([`HANDOFF_2026-07-16.md`](HANDOFF_2026-07-16.md)).

### Self-review revisions locked into this final

- **Encrypt enablement locked:** encryption is **on iff** `TELEGRAM_SESSION_KEY` is set (non-empty). No separate `TELEGRAM_SESSION_ENCRYPT` flag.
- **Key format locked:** Fernet key from `Fernet.generate_key()` (url-safe base64 32-byte key). **Not** a free-form passphrase / HKDF in MVP.
- **Threat model honesty locked:** protect **at-rest / idle / backup** theft of the bind-mount. While any container holds an open Telethon SQLite session, a working `.session` (plus WAL sidecars) may exist plaintext on the shared volume — do **not** claim live multi-container confidentiality.
- **Module paths locked:** session crypto → `tg_parser/ingestion/telegram/session_crypto.py`; audit helper → `tg_parser/auth/audit.py` (`record_audit_event`). Still **no** `tg_parser/security/` package.
- **`actor_user_id`:** `UUID` nullable, aligned with `users.id` (ingestion).
- **Auth-reject MVP narrowed:** API invalid-key paths in `api/auth.py` only. MCP bearer reject is framework-level → **out of MVP** (document as follow-up in PR if not trivially hookable).
- **Channel wiring:** no shared ChannelService today — wire **bot + MCP** edges for lifecycle events; prefer thin wrapper calling `record_audit_event` to avoid copy-paste drift.
- **Timebox order locked:** drop S1 first; then drop admin user/auth audit events; **never** drop M1/M2/M3. Within channel events, keep `add`/`remove` over `pause`/`resume` if still over budget.
- **`cryptography`:** already transitive in lock — **import without** editing `pyproject.toml`. If packaging/policy forces a direct dep, **stop and ask owner** (forbidden path).
- Prompt is **self-contained**; PLAN file is optional background, not a second SoT.

---

## CRITICAL OPERATIONAL WARNINGS — READ FIRST

1. **Do NOT reopen Dependabot/Renovate** without revisiting ADR [`0017-dependency-management-policy.md`](../adr/0017-dependency-management-policy.md) §7 and an explicit owner decision.
2. **Do NOT touch** `docs/methodology/**`. Do **not** edit `pyproject.toml` / `requirements.txt` / `uv.lock` without **explicit owner ask**.
3. **Do NOT weaken** Phase 1 auth/CORS/logging, Phase 2 prompt-defense (`input_sanitizer` / `prompt_render` / injection metrics), confirm-flow / BUG-009, or tenant scoping.
4. **Do NOT claim** “fully hardened” / “pentest-proof” / “encrypted while live on shared volume” in docs or PR copy — defense-in-depth + at-rest only.
5. **Migrations:** Alembic-only. Add `audit_log` on the **ingestion** branch + mirror `Table(...)` in `INGESTION_METADATA`. No `init_*_schema` revival.
6. **Secrets / sessions:** never dump live `.session` bytes, Fernet keys, or `.env` values into notes/PR/tests. Treat `data/sessions/*` as high-sensitivity. Test fixtures = synthetic bytes only.
7. **Session lock invariant:** encryption must compose with BUG-070 — `telethon_session_lock` / `telethon_session_lock_guard` + `_WALSQLiteSession`. Do not open a second concurrent Telethon SQLite path around decrypt/seal.
8. **WAL sidecars:** when sealing, ensure `-wal` / `-shm` / journal leftovers are not left beside a sealed blob as a plaintext leak; when unsealing, start from a clean working set.
9. **Deploy** only after reviewed PR + explicit owner approval. Prod: run **ingestion** migration; set `TELEGRAM_SESSION_KEY` before relying on at-rest seal.
10. **Out of this PR:** F7 Billing, F8-B Redis, F4-A expansion, vault product, CSP middleware, Phase 2 carry-forwards (OutputValidator / destructive rate-limit / remaining `.format`), MCP auth-reject audit (unless trivial).

---

## TL;DR

Phase 1 (auth) and Phase 2 (prompt-defense) are shipped. Catalog Phase 3 had 8 steps; **2 DONE** (pins, API-key hashing), Dependabot **OUT**, CSP **N/A**, vault **deferred**. This session ships the **MUST** bar for the F7 path:

1. **M1** Telethon session **at-rest** encryption  
2. **M2** immutable **audit_log** MVP (ingestion)  
3. **M3** penetration-testing runbook (+ `.env` hardening checklist)

**SHOULD:** report-only `pip-audit` CI (drop first if timeboxed).

**Ship bar:** M1 + M2 + M3 green. No pretence of complete hardening.

---

## Locked decisions (D1–D9)

| ID | Lock |
|----|------|
| D1 | Encrypt session **file at rest** (app-managed Fernet). Telethon 1.43.2 has no native encrypt. Keep `_WALSQLiteSession` on the working SQLite path after unseal. |
| D2 | Env **`TELEGRAM_SESSION_KEY`** = Fernet key (`Fernet.generate_key()` output). Host file perms 600 for `.env` / session dir. Encrypt **iff** key non-empty. |
| D3 | Audit MVP write-set: channel add/remove/pause/resume; llm_config set/reset; **API** `auth.api_key_rejected`; admin user.register / user.update / user.auth_add / user.auth_remove |
| D4 | Retention **forever** (MVP) |
| D5 | CSP **OUT** |
| D6 | Vault **OUT** (`.env` checklist inside pentest runbook) |
| D7 | pip-audit **report-only SHOULD**; Dependabot OUT |
| D8 | Phase 2 carry-forwards = **follow-up**, not this PR |
| D9 | MUST = M1 + M2 + M3 |

---

## Prune / baseline (do not re-litigate)

| Catalog item | Status | Anchors |
|--------------|--------|---------|
| Pin deps (`uv.lock`) | **DONE** | ADR 0017; CI `deps-lock-guard` |
| API key hashing | **DONE** | `hash_credential` — [`tg_parser/auth/resolvers.py`](../../tg_parser/auth/resolvers.py) ~81 |
| Dependabot / Renovate | **OUT** | ADR 0017 §7 |
| Session at rest | **OPEN → M1** | `_WALSQLiteSession` — [`telethon_client.py`](../../tg_parser/ingestion/telegram/telethon_client.py); CLI — [`cli/app.py`](../../tg_parser/cli/app.py) ~51; compose `./data/sessions:/app/sessions` |
| Audit log | **OPEN → M2** | Missing table; users on **ingestion** — [`_metadata.py`](../../tg_parser/storage/sqlalchemy/_metadata.py) |
| CSP | **OUT** | No owned HTML app in `tg_parser/` |
| Vault | **OUT** | Still `.env` + compose |
| Pentest guide | **OPEN → M3** | New runbook under `docs/runbooks/` |

Auth reject today (log only): `invalid_api_key_attempt` — [`tg_parser/api/auth.py`](../../tg_parser/api/auth.py) ~63, ~86.  
LLM mutations: [`api/routes/llm_config.py`](../../tg_parser/api/routes/llm_config.py) + MCP/bot `set_llm_config` / `reset_llm_config`.  
Channel lifecycle: bot [`tools.py`](../../tg_parser/bot/tools.py) + MCP [`mcp_server.py`](../../tg_parser/mcp_server.py) (duplicated edges — wire both).

---

## Scope IN — ranked backlog

### M1 — Session encryption at rest `[MUST]`

**Module (locked):** [`tg_parser/ingestion/telegram/session_crypto.py`](../../tg_parser/ingestion/telegram/session_crypto.py) (new). Wire from `TelethonClient.connect` / `disconnect` and CLI `auth` as needed.

**Goal.** Offline theft of `data/sessions/` (backup, stopped stack, copied volume) must not yield a usable Telethon session without `TELEGRAM_SESSION_KEY`.

**Protocol (normative).**

1. Durable sealed form: e.g. `<session_path>.session.enc` (exact suffix OK to choose; document it).
2. **Unseal before** constructing `_WALSQLiteSession` (working path = existing `TELEGRAM_SESSION_NAME` + `.session` convention Telethon already uses).
3. **Seal after** clean disconnect / successful `tg-parser auth` when key is set; delete/zero working plaintext and WAL/shm leftovers after verified seal.
4. **Migration:** plaintext `.session` exists + key set → unseal path no-ops; after verified open (or auth), one-shot seal. Document break-glass: decrypt → plaintext for recovery.
5. **Missing key:** if only `.enc` exists and key empty/missing → **fail closed** with a clear error (do not silently leave encrypted blob unusable without message). If only plaintext exists and key empty → legacy behavior (no encrypt) for one release; PR notes that prod should set the key.
6. **Do not** invent cross-container file locks unless tests prove a seal/unseal race; note residual shared-volume risk in PR (threat model above).

**Settings / docs.** Add placeholder to `.env.example` only (no real key). Operator one-liner: how to `python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`.

**Tests.** Seal/unseal round-trip; plaintext→encrypted migration; missing-key + `.enc` present fails clearly; connect path still uses `_WALSQLiteSession` (mock Telethon OK). No live session material in fixtures.

### M2 — Audit log MVP `[MUST]`

**Helper (locked):** [`tg_parser/auth/audit.py`](../../tg_parser/auth/audit.py) — `record_audit_event(...)`. Repo/insert helper may live under `tg_parser/storage/sqlalchemy/` if cleaner; public write API stays in `auth/audit.py`.

**Schema (ingestion DB) — minimal normative columns:**

| Column | Type / notes |
|--------|----------------|
| `id` | `UUID`, `gen_random_uuid()` |
| `created_at` | `timestamptz`, default `now()` |
| `actor_user_id` | `UUID` **nullable** (no strict FK required in MVP if it complicates auth-reject; prefer FK to `users.id` ON DELETE SET NULL when easy) |
| `action` | `text` — use the names in D3 |
| `resource_type` / `resource_id` | `text` nullable |
| `outcome` | `text` — `success` \| `failure` \| `denied` |
| `meta` | `jsonb` nullable — **non-secret** only (scope, provider, channel_id, `key_prefix` like existing logs) |

**Invariants.**

- App: **INSERT only** (no update/delete helpers).
- Never store raw API keys, MCP tokens, confirm tokens, session bytes, full prompts/bodies.
- Best-effort on auth-reject path: audit failure must **not** change the 401 response (log + continue).

**Wire map.**

| Event family | Where to hook |
|--------------|---------------|
| `channel.*` | Bot executors **and** MCP handlers for add/remove/pause/resume (shared tiny helper recommended) |
| `llm_config.*` | `api/routes/llm_config.py` **and** MCP/bot set/reset after successful mutation |
| `auth.api_key_rejected` | [`tg_parser/api/auth.py`](../../tg_parser/api/auth.py) invalid-key paths only |
| `user.*` / `user.auth_*` | Admin register/update/add_user_auth/remove_user_auth on bot **and** MCP success paths |

**Out of MVP:** read API/MCP; digests/watchlists/export/pipeline; TTL; MCP bearer-reject audit.

**Tests.** Alembic upgrade on ingestion; helper unit test; ≥1 integration each for channel, llm_config, api auth-reject (assert no raw secret in `meta`); auth-reject still 401 if audit insert raises.

### M3 — Penetration testing guide `[MUST]`

**Path (locked):** [`docs/runbooks/PENTEST_GUIDE.md`](../runbooks/PENTEST_GUIDE.md).

**Required sections:**

1. Auth bypass / role checks  
2. Tenant isolation / `workspace_id`  
3. Confirm-flow + BUG-009  
4. Prompt injection (Phase 2) + `tg_parser_prompt_injection_suspect_total`  
5. Session file theft / at-rest encryption expectations (incl. live shared-volume caveat)  
6. Export privacy (`raw_payload` never exported)  
7. LLM config mutation (admin-only)  
8. Regression anchors: [`tests/test_api_security.py`](../../tests/test_api_security.py), [`tests/test_f9_phase2_prompt_defense.py`](../../tests/test_f9_phase2_prompt_defense.py), [`tests/test_telethon_session_lock.py`](../../tests/test_telethon_session_lock.py)  
9. **`.env` / sessions hardening checklist** (D6 substitute): perms 600, no committing secrets, backup expectations, key rotation pointer for `TELEGRAM_SESSION_KEY`

Language: manual vectors + expected defenses — **not** full coverage / not “pentest-proof”.

### S1 — pip-audit CI `[SHOULD]`

Report-only job against lock export in `.github/workflows/ci.yml` (or sibling). **No** Dependabot. Non-blocking (`continue-on-error` or non-required check). Defer with PR note if noisy/timeboxed — ship bar still green.

---

## Scope OUT

- F7 Billing; F8-B Redis; F4-A Multi-User expansion.
- Vault implementation; CSP / security-headers middleware.
- Dependabot / Renovate.
- Phase 2 carry-forwards: OutputValidator; destructive-op rate limit; remaining `.format` (digest / resummarize / topicization / merge / text_tools).
- Reverting Phase 1 M3 tool-args INFO logging.
- Re-doing Phase 2 sanitizer / safe-render / monitoring.
- MCP bearer-token reject → audit_log (follow-up).
- Audit read/query tools.
- `docs/methodology/**`; `tg_parser/security/` package.
- Editing `pyproject.toml` / `requirements.txt` / `uv.lock` without owner ask.

---

## Acceptance criteria

1. **M1:** With `TELEGRAM_SESSION_KEY` set, durable form is sealed; working plaintext is not the long-term rest form; WAL leftovers not left as leak after seal; round-trip + migration tests green; BUG-070 lock + `_WALSQLiteSession` still used; threat-model caveat documented in runbook/PR.
2. **M2:** `audit_log` on ingestion via Alembic + metadata mirror; D3 events written from listed choke points (API auth-reject + channel + llm + admin user/auth, unless timebox dropped admin only); INSERT-only; no raw secrets in `meta`; 401 path resilient to audit failures.
3. **M3:** `docs/runbooks/PENTEST_GUIDE.md` with required sections + `.env` checklist; no “pentest-proof” claims.
4. **S1:** report-only pip-audit **or** explicit deferral note in PR.
5. **Regressions:** `tests/test_api_security.py`, `tests/test_f9_phase2_prompt_defense.py`, `tests/test_telethon_session_lock.py` green.
6. **ЗК:** `ruff check` + `ruff format --check` + `pytest` (default) + `TEST_POSTGRES=1` pytest.
7. **Self-review + Bugbot** clean before merge.
8. **Docs:** PR body = ship bar + OUT + residual shared-volume session risk; `FUTURE_FEATURES.md` one-liner only if owner asks.

---

## Suggested implementation order

```text
1. M2 migration + INGESTION_METADATA + tg_parser/auth/audit.py + unit tests
2. M2 wire: api/auth.py → llm_config (API+MCP+bot) → channel (bot+MCP) → admin user/auth
3. M1 session_crypto.py + settings/.env.example + telethon connect/disconnect + auth CLI + tests
4. M3 docs/runbooks/PENTEST_GUIDE.md
5. S1 pip-audit report-only if time remains
6. Self-review → Bugbot → PR → owner approve merge/deploy
```

**Timebox drops (in order):** S1 → admin `user.*` audit events → channel `pause`/`resume` audit (keep add/remove). **Never** drop M1, M2 core, or M3.

---

## Workflow (implementation session)

1. Branch from `main`: e.g. `feat/f9-phase3-full-hardening`.
2. Implement per order; keep PR focused (no F7/F8-B/Phase-2 rework).
3. ЗК locally before push.
4. Open PR; wait for CI + Bugbot; address findings.
5. Merge with **merge commit** + `--delete-branch`.
6. Deploy **only** after explicit owner approval:
   - alembic upgrade **ingestion**
   - set `TELEGRAM_SESSION_KEY` on host; one controlled seal migration / reconnect smoke
   - verify ≥1 audit row via SQL after a benign admin action (or staging equivalent)

**Commit:** only when the user explicitly asks.

---

## OUT / next after this PR

- Follow-ups: OutputValidator; remaining `.format` → `render_prompt`; destructive rate limits (or F8-B); MCP auth-reject audit; broader audit events / read API / TTL.
- Enterprise: vault; CSP when first-party dashboard exists; Dependabot only after ADR 0017 revisit.
- **F7 Billing** only after this Phase 3 ship bar is on prod (per FUTURE_FEATURES).

---

## Refs

- Planning background: [`PLAN_F9_PHASE3_FULL_HARDENING_2026-07-16.md`](PLAN_F9_PHASE3_FULL_HARDENING_2026-07-16.md)
- Catalog: [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) § F9 Phase 3
- ADR 0017: [`../adr/0017-dependency-management-policy.md`](../adr/0017-dependency-management-policy.md)
- Phase 2 precedent: [`START_PROMPT_F9_PHASE2_PROMPT_DEFENSE_2026-07-16.md`](START_PROMPT_F9_PHASE2_PROMPT_DEFENSE_2026-07-16.md)
- Sessions: [`../prompts/D3-telegram-session-docker.md`](../prompts/D3-telegram-session-docker.md), [`telethon_client.py`](../../tg_parser/ingestion/telegram/telethon_client.py)
- Handoff / ЗК: [`HANDOFF_2026-07-16.md`](HANDOFF_2026-07-16.md)

---

## Copy-paste opener for the impl chat

```text
Открой docs/notes/START_PROMPT_F9_PHASE3_FULL_HARDENING_IMPLEMENTATION_2026-07-16.md
и веди IMPLEMENTATION-сессию F9 Phase 3 по нему (это SOURCE OF TRUTH; status = ready).
Коммит только по моей явной просьбе. Деплой — только после моего approve.
```
