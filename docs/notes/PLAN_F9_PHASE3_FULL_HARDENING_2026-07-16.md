# PLAN — F9 Phase 3 Full Security Hardening (gap-audit + decisions)

**Created:** 2026-07-16.
**Type:** Planning output (read-only session). **No production code.**
**Planning prompt:** [`START_PROMPT_F9_PHASE3_FULL_HARDENING_PLANNING_2026-07-16.md`](START_PROMPT_F9_PHASE3_FULL_HARDENING_PLANNING_2026-07-16.md).
**Impl prompt (final after self-review):** [`START_PROMPT_F9_PHASE3_FULL_HARDENING_IMPLEMENTATION_2026-07-16.md`](START_PROMPT_F9_PHASE3_FULL_HARDENING_IMPLEMENTATION_2026-07-16.md) (`ready for impl session`).
**HEAD audited:** `5e1612d` (planning-prompt commit on `main`; Phase 2 merge parent `7fd888c`).
**Prod assumption:** Phase 2 live at `7fd888c`+; confirm on deploy host before impl/deploy.

### Self-review deltas folded into final impl prompt (2026-07-16)

- Encrypt iff `TELEGRAM_SESSION_KEY` set; Fernet key format (not passphrase); at-rest threat model (not live shared-volume).
- Module paths: `session_crypto.py`, `auth/audit.py`; `actor_user_id` UUID; API-only auth-reject MVP.
- Timebox drop order + channel bot+MCP dual-wire clarified; prompt made self-contained SoT.

---

## 1. Prune / status table (re-verified)

| # | Catalog item | Status | Evidence / anchors |
|---|--------------|--------|-------------------|
| 1 | Pin dependencies (`uv lock`) | **DONE — prune** | `uv.lock` present; ADR 0017; CI `deps-lock-guard` in `.github/workflows/ci.yml` |
| 2 | CI security scanning | **SPLIT** | Dependabot/Renovate **OUT** (ADR 0017 §7). No `pip-audit` / Snyk job today. Optional pip-audit = SHOULD (report-only) |
| 3 | API key hashing | **DONE — prune** | `hash_credential` — `tg_parser/auth/resolvers.py:81`; used by API/MCP/bot/dispatch |
| 4 | Telethon session encryption at rest | **OPEN — MUST** | Plain SQLite via `_WALSQLiteSession` — `telethon_client.py:142–220`; compose bind `./data/sessions:/app/sessions`; `TELEGRAM_SESSION_NAME` default `/app/sessions/tg_parser_session`. Telethon **1.43.2** has no native encrypted session (`SQLiteSession` / `StringSession` / `MemorySession` only) |
| 5 | Audit log (immutable) | **OPEN — MUST** | Mentions in runbooks only; **no** `audit_log` table / metadata. Users live on **ingestion** branch (`_metadata.py` `users` / `user_auth_mappings`) |
| 6 | CSP headers | **OUT — N/A** | No owned HTML/dashboard app (`HTMLResponse` / `StaticFiles` / Jinja absent in `tg_parser/`). Grafana + Caddy are infra; CSP would be ops config, not app middleware |
| 7 | Secrets vault | **OUT — defer enterprise** | Secrets still `.env` + compose env (+ GH secrets for CI). Vault = Medium + ops; single-VPS stays on `.env` + hardening checklist |
| 8 | Penetration testing guide | **OPEN — MUST (docs)** | No dedicated runbook; Phase 1/2 tests are regression anchors only |

### Phase 2 carry-forwards (IN vs OUT of Phase 3)

| Item | Status post-Phase 2 | Phase 3 decision |
|------|---------------------|------------------|
| F3 OutputValidator | Not shipped | **OUT — follow-up** |
| F5 Destructive-op rate limit | Skipped | **OUT — follow-up** (or later F8-B) |
| Remaining `.format` (digest / resummarize / topicization / merge / text_tools) | Still live | **OUT — follow-up** (safe-render already on RAG + processing) |

---

## 2. Gap-audit evidence (A–F)

### A — Session files

| Question | Finding |
|----------|---------|
| Create / path | CLI `tg-parser auth` — `cli/app.py:51`; runtime `TelethonClient.connect` builds `_WALSQLiteSession(settings.telegram_session_name)` |
| Prod layout | Bind-mount `./data/sessions` → `/app/sessions`; env `TELEGRAM_SESSION_NAME=/app/sessions/tg_parser_session` |
| Telethon encrypt API | **None** in 1.43.2 — must wrap at rest (app crypto) or rely on disk encryption alone |
| Crypto dep | `cryptography` already pinned transitively (`requirements.txt` / lock) — Fernet viable without new top-level dep *if* we only use it; prefer declare explicit if we import it from app code (impl note: owner must approve `pyproject` touch) |
| Key mgmt (single VPS) | Env `TELEGRAM_SESSION_KEY` (Fernet key or passphrase→HKDF) + file mode 600 on host path |
| Migration | If plaintext `.session` exists and key configured: one-shot encrypt on next successful connect/auth; keep `.session-journal` / WAL sidecars consistent (encrypt primary; wipe plaintext after verify) |
| BUG-070 / locks | Encryption **must not** bypass `telethon_session_lock` / `_WALSQLiteSession`. Pattern: decrypt → open WAL session under lock → on disconnect optionally re-seal. Avoid concurrent decrypt races across app/bot/mcp containers sharing the volume |

### B — Audit log

| Question | Finding |
|----------|---------|
| DB home | **ingestion** (same branch as `users` / `sources` / ownership). Not processing/raw |
| Migrations | Alembic-only (`migrations/versions/ingestion/…` + `INGESTION_METADATA` Table mirror). No `init_*_schema` |
| MVP event set | `channel.add` / `channel.remove` / `channel.pause` / `channel.resume`; `llm_config.set` / `llm_config.reset`; `auth.api_key_rejected`; `user.register` / `user.update` / `user.auth_add` / `user.auth_remove` (admin paths) |
| Out of MVP writes | Digests/watchlists CRUD, export jobs, pipeline triggers (noise; revisit for F7) |
| Append-only | App: INSERT only. No UPDATE/DELETE helpers. Retention: forever MVP |
| PII / secrets | Never store raw API keys, confirm tokens, session bytes, full request bodies. Meta JSON: ids, scopes, outcome, truncated prefixes only (mirror `invalid_api_key_attempt` style) |
| Read surface | **Out of MVP** — no MCP/API list tool. Operator reads via SQL / future admin UI |
| Choke points | Prefer service/tool executors + `api/auth.py` / `api/routes/llm_config.py` — few writers, shared `record_audit_event(...)` helper under `tg_parser/auth/` or `tg_parser/storage/…` (not new `tg_parser/security/` package) |

### C — CSP

Confirmed: no first-party browser app serving end-user HTML. Grafana CSP = ops. **Document OUT.**

### D — Vault / secrets

Inventory (representative): Telegram API id/hash/phone; LLM provider keys; DB URLs/passwords; bot token; API/MCP credentials (hashed at rest in DB); Grafana admin; Caddy/domain. Still `.env`-centric.

**Recommendation:** defer vault; include `.env` hardening checklist in pentest runbook (perms 600, no world-readable compose secrets on disk, backup encryption for `data/sessions` + `.env`, rotate keys runbook pointer).

### E — pip-audit

Feasible as a CI job: `uv export` / `pip-audit -r` against lock export **without** Dependabot PRs. Aligns with ADR 0017 (manual freshness). Noise risk → **report-only** (`continue-on-error` or non-blocking check) for v1.

### F — Pentest guide

Outline locked for draft runbook `docs/runbooks/PENTEST_GUIDE.md` (or similar):

1. Auth bypass / missing key / wrong role
2. Tenant isolation (channel ownership / workspace_id)
3. Confirm-flow / BUG-009
4. Prompt injection (Phase 2 surfaces + monitoring)
5. Session theft (filesystem / bind-mount)
6. Export privacy (`raw_payload` never exported)
7. LLM config mutation (admin-only)
8. Pointers to `tests/test_api_security.py`, `tests/test_f9_phase2_prompt_defense.py`

---

## 3. Locked decisions (D1–D9)

Status: **agent recommendations locked into draft impl prompt**. Owner may override before marking impl prompt `ready`.

| ID | Choice | Rationale |
|----|--------|-----------|
| **D1** | **(b) Encrypt session file at rest** with app-managed crypto; keep `_WALSQLiteSession` after decrypt. Not (a) — Telethon has no native encrypt. Not (c) alone — bind-mount is portable/stealable | Matches threat model for `./data/sessions` on VPS |
| **D2** | Env **`TELEGRAM_SESSION_KEY`** (required when encryption enabled); host file perms 600 | Single-VPS MVP; no KMS |
| **D3** | **Minimal write-set** (channel lifecycle + LLM config + auth reject + admin user/auth mutations) | Fits ~1 session with session encrypt |
| **D4** | **Forever** retention for MVP | Low volume; TTL later |
| **D5** | **CSP N/A / OUT** | No owned HTML surface |
| **D6** | **Defer vault**; document `.env` hardening in pentest guide | Enterprise timeline not signaled |
| **D7** | **pip-audit report-only SHOULD** (not merge gate); Dependabot stays OUT | ADR 0017 §7 |
| **D8** | Phase 2 carry-forwards = **follow-up PRs**, not Phase 3 | Keep PR focused |
| **D9** | Ship bar **MUST:** session encrypt + audit_log MVP + pentest guide. **SHOULD:** pip-audit report-only + `.env` checklist (inside/near pentest doc). **OUT:** vault, CSP, Dependabot, F7/F8-B/F4-A expansion | Fits catalog ~1–1.5 session after prune |

---

## 4. Ranked impl backlog

### MUST-for-ship

1. **Session encryption at rest** — seal/unseal around Telethon connect; migrate existing plaintext; tests with tmp session + key; docs for `TELEGRAM_SESSION_KEY` + auth CLI.
2. **Audit log MVP** — Alembic ingestion migration + metadata Table; `record_audit_event`; wire minimal write-set; unit/integration tests (insert-only, no secret leakage).
3. **Pentest guide** — `docs/runbooks/…` attack-vector checklist; defense-in-depth language only.

### SHOULD

4. **pip-audit CI** report-only job (no Dependabot).
5. **`.env` / sessions hardening checklist** (can be a section of the pentest runbook).

### NICE / follow-up (not Phase 3)

- OutputValidator; destructive rate-limit; remaining `.format` → `render_prompt`.
- Broader audit events; audit read API; retention TTL; vault; CSP when dashboard exists.

### OUT (crystal-clear)

- Dependabot / Renovate (unless ADR 0017 revisited).
- Secrets vault implementation.
- CSP middleware in FastAPI.
- F7 Billing, F8-B Redis, F4-A Multi-User expansion.
- Reverting Phase 1 M3 tool-args INFO logging.
- Re-doing Phase 2 prompt-defense.
- `docs/methodology/**`.
- New `tg_parser/security/` package (prefer `tg_parser/auth/` + ingestion/telethon helpers).

---

## 5. Effort / risk notes for impl

- **Schedule risk #1:** audit_log multi-surface wiring + migration + metadata sync.
- **Schedule risk #2:** session encrypt × shared volume × WAL × three containers (app/bot/mcp) — must design seal timing carefully under existing lock.
- If timeboxed: ship audit_log + pentest first, session encrypt as same-PR stretch with feature flag `TELEGRAM_SESSION_ENCRYPT=1` default-on when key set.
- **`pyproject.toml`:** only if Fernet import requires promoting `cryptography` to a direct dep — **ask owner before editing** (workspace forbidden without explicit ask).

---

## 6. Planning acceptance checklist

- [x] Updated prune table at current HEAD
- [x] D1–D9 choices recorded (owner may override)
- [x] Ranked MUST / SHOULD / OUT + ship bar
- [x] Draft IMPLEMENTATION START_PROMPT written → **finalized post self-review** (`ready for impl session`)
- [x] OUT list explicit
- [x] No production code / no commit (unless owner asks)
