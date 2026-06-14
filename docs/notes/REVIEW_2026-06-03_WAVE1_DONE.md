# Wave 1 — DONE marker (aggregate closure)

**Дата:** 2026-06-03
**Закрывает:** Wave 1 steps 1–4 per [`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 5.1](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md) and operational packaging per [`PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md`](PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md).
**Reviewer (agent):** Wave 1 closure session (2026-06-03).
**Reviewer (operator):** @alexanderefimov.

---

## 1. Per-step summary

| Step | Scope | DONE marker | Watch verdict |
|---|---|---|---|
| **1** — Bot UX hardening | Sessions H / I / J (BUG-011, BUG-010, ADR 0005) | [`REVIEW_2026-05-08_WAVE1_STEP1_DONE.md`](REVIEW_2026-05-08_WAVE1_STEP1_DONE.md) | GREEN (3× 24h watch) |
| **2** — F4-B Core Workspaces | 5 atomic commits, ~75 tests | [`REVIEW_2026-05-14_WAVE1_STEP2_DONE.md`](REVIEW_2026-05-14_WAVE1_STEP2_DONE.md) | GREEN |
| **3** — Surface Parity MVP | P-1 / P-2 / ENH-9 / BUG-022 / idempotency middleware; step 3.1 ADR 0007 dispatch | [`REVIEW_2026-05-21_WAVE1_STEP3_DONE.md`](REVIEW_2026-05-21_WAVE1_STEP3_DONE.md) | GREEN (T+22h09m, early close documented) |
| **4** — Shareable Digest / ADR 0008 | PR [#93](https://github.com/AlexEfimov/TG_parser/pull/93) polymorphic `target` | [`REVIEW_2026-05-24_WAVE1_STEP4_DONE.md`](REVIEW_2026-05-24_WAVE1_STEP4_DONE.md) | **PASS-WITH-CAVEATS** (C-3 untested) |
| **5** — Ops / Grafana quality (Step 5 prod verify) | BUG-036 provisioning-as-code, webhook defaults, post-step-4 hotfixes on prod | *this § 2* | **PASS** (2026-06-06 closure session) |

---

## 2. Step 5 ops status (prod verify, 2026-06-06)

**Target:** VPS `212.72.189.15:2296`, repo `~/TG_parser`.
**Verdict:** **PASS** — Grafana stack healthy, provisioning-as-code verified, webhook URL + token set on prod, E2E alert path verified end-to-end 2026-06-06 (synthetic curl → issue [#195](https://github.com/AlexEfimov/TG_parser/issues/195), closed as smoke).

| Check | Result | Evidence |
|---|---|---|
| Prod git HEAD vs `main` | **PASS** (2026-06-06, prod на post-merge SHA `b04353b`) | `git pull --ff-only` after PR [#197](https://github.com/AlexEfimov/TG_parser/pull/197) merge; all 6 containers healthy. |
| Grafana container | **PASS** | `tg_parser_grafana` Up, `/api/health` HTTP 200. Recreate 2026-06-06T08:17Z — no crash-loop, `finished to provision alerting`. |
| `GRAFANA_WEBHOOK_URL` in `.env` | **PASS** (2026-06-03) | Set to documented Cursor automation ingress (`7b35ca01-…` per runbook / handoff). Recreated Grafana container picks up URL. |
| `GRAFANA_WEBHOOK_TOKEN` in `.env` | **PASS** (2026-06-06, set during closure session) | Added `crsr_…` token (same value as `$TG_PARSER_WATCH_WEBHOOK_AUTH` without `Bearer` prefix); Grafana recreated; E2E smoke issue [#195](https://github.com/AlexEfimov/TG_parser/issues/195) confirms alert → GitHub issue path. |
| `wave1_step4.yaml` provisioning | **PASS** | File on prod. Initial restart `2026-06-02T16:55–16:58Z` hit `alert-rule.conflict` (UI duplicate); resolved `17:15:18Z`. Re-verify 2026-06-06T08:17Z — clean `finished to provision alerting`. |
| BUG-036 (noData drift) | **PASS / resolved** | PR [#140](https://github.com/AlexEfimov/TG_parser/pull/140) on prod; three rules + contact point provisioned with `noDataState: OK`. BUG_LOG flipped `resolved` 2026-06-03. |
| BUG-038 (stale 5xx metric query) | **PASS / resolved** | Provisioned query `tg_parser_http_requests_total{...,status=~"5.."}` on prod; BUG_LOG flipped `resolved` 2026-06-03. |
| Post-closure cleanup runbook | **PARTIAL** — § A **Done 2026-06-06** (operator confirmed single-shot automations `2bd25769` / `f93e557a` inactive in Cursor UI); § C **Done 2026-06-06** (Grafana admin password rotated on VPS, container recreated, `/api/health` OK — password in prod `.env` only, not in repo); § B deferred (7 schema-probe deletes — Cursor UI, no MCP delete tool); § D deferred (Telegram test artifacts kept per runbook default). `7b35ca01` remains enabled (live monitoring). |

**Risk items (operator action):**

* ~~Grafana admin password rotation (runbook § C)~~ — **Done 2026-06-06** (rotated on VPS; credential in operator-private store only).
* ~~Post-closure cleanup § A — disable single-shot automations `2bd25769` / `f93e557a`~~ — **Done 2026-06-06** (operator confirmed inactive in Cursor UI).
* Post-closure cleanup § B — delete 7 `[DELETE_ME] schema-probe-*` automations via Cursor UI (see [`WAVE1_STEP4_VPS_WATCH_AUTOMATIONS.md`](../runbooks/WAVE1_STEP4_VPS_WATCH_AUTOMATIONS.md) § 4 for IDs/names).

---

## 3. Step 4 caveats (carried into Wave 1 closure)

From [`REVIEW_2026-05-24_WAVE1_STEP4_DONE.md`](REVIEW_2026-05-24_WAVE1_STEP4_DONE.md):

* **C-3 untested:** `tg_digest_channel_publish_total{result="failed"}` increment never materialized in OP-2/OP-3 — structurally registered, not blocking closure.
* **Bot prompt v1.7.0 partial at watch close:** disambiguation GREEN; payload issues (BUG-033/034) surfaced — **subsequently resolved** in post-step-4 work (§ 4).

---

## 4. Post-step-4 work (BUG-031…053, PR #171)

Between step-4 watch closure (2026-05-25) and this marker, a **bot correctness / ops tail** landed without re-opening the step-4 DONE marker:

| ID range | Summary | Status at closure |
|---|---|---|
| **BUG-031…035** | Confirm-flow, chat_id override, channel parser, scheduler orphan job, digest race-retry, scheduler startup race | **resolved** (PRs [#108–112](https://github.com/AlexEfimov/TG_parser/pull/108), [#138–139](https://github.com/AlexEfimov/TG_parser/pull/138)) |
| **BUG-036 / BUG-038** | Grafana alert rules provisioned-as-code + corrected 5xx PromQL | **code on prod**; BUG-038 pending-deploy note obsolete after `656f23c` deploy |
| **BUG-037** | Cursor webhook title-prefix classifier | **resolved** (2026-05-30 real-fire) |
| **OBS-001 → ENH-001** | Watchlist `last_checked_at` telemetry | **resolved** (PR [#141](https://github.com/AlexEfimov/TG_parser/pull/141)) |
| **BUG-039…044, ENH-002** | Conversation-layer clarify FSM, cron humanize, read re-run fidelity | **resolved** (branch `fix/bug039-042-conversation-layer`, 2026-05-31) |
| **BUG-045…050** | Subscribe/delete routing, channel-not-found guards | **resolved** (2026-05-31…2026-06-01 sprints) |
| **BUG-051…053** | Chat serialization lock, pagination bare-token no-op, short-prefix fuzzy | **resolved** (PRs [#166–170](https://github.com/AlexEfimov/TG_parser/pull/166), prod smoke 2026-06-02) |
| **PR #171** | Preserve Telegram entity URLs through processing pipeline | **on prod** (`ea826b7`) |

Detail: [`BUG_LOG.md`](BUG_LOG.md) entries + prod smoke notes (`SMOKE_TEST_*`, `HANDOFF_BUG037_*`).

---

## 5. Step 4.1 deferred items (BUG-025 / BUG-026 / BUG-027)

**Decision (2026-06-03): defer to Wave 2** — wontfix for Wave 1 scope.

| ID | Summary | Wave 1 disposition | Rationale |
|---|---|---|---|
| **BUG-025** | `unsubscribe_watchlist` no UUID pre-validation → raw asyncpg traceback | **deferred → Wave 2** | Scoped to step 4.1 sub-sprint per [`PLAN_WAVE1_STEP4_2026-05-23.md` § 7 Q3](PLAN_WAVE1_STEP4_2026-05-23.md); step 4.1 never executed. No code fix landed (`tg_parser/bot/tools.py` still forwards arbitrary `interest_id`). Workaround: pass UUID explicitly or use MCP. Medium severity, no data corruption. |
| **BUG-026** | Standalone UUID continuation after bot suggestion (write-side BUG-011 analogue) | **deferred → Wave 2** | Same step 4.1 scope-lock. Partial mitigation exists via BUG-047+ delete confirm flows for `unsubscribe_*`, but bare-UUID continuation for arbitrary write tools remains unaddressed. Low severity — extra user turn. |
| **BUG-027** | Ambiguous «уже неактивен» wording on idempotent unsubscribe | **deferred → Wave 2** | Bundled with BUG-025/026 in Candidate B; not blocking Wave 1 product gates. |

**Re-evaluate trigger:** Wave 2 bot UX sprint or any touch to `prompts/bot.yaml` v1.8.x+ / write-tool executor validation layer.

**BUG-025/026 partially adjacent work (does NOT close them):** BUG-047+ added deterministic confirm flows for `unsubscribe_digest` / `unsubscribe_watchlist` (preview + confirm gate) — reduces accidental deletes but does not add UUID format validation (BUG-025) or standalone-UUID continuation (BUG-026).

---

## 6. Gates met / waived

| Gate | Status |
|---|---|
| Steps 1–3 DONE markers + 24h watch GREEN | **met** |
| Step 4 DONE marker PASS-WITH-CAVEATS | **met** (C-3 waived — structural only) |
| Step 5 Grafana provisioning on prod | **met** (rules provisioned; webhook env + E2E verified 2026-06-06) |
| Step 4.1 bot UX bundle (BUG-025/026/027) | **waived** → Wave 2 |
| CHANGELOG reflects PR #171 + Wave 1 closure | **met** — `[4.4.0] - 2026-06-06` cut on `main` at `6ec3574` (PR [#198](https://github.com/AlexEfimov/TG_parser/pull/198)); release tag `v4.4.0`; prod on `b04353b` |
| Decision Point external signals (stars, MCP downloads, paying interest) | **not met** — no trigger for Stage 0→1 (expected; inward-facing Wave 1) |

---

## 7. Decision Point note

Wave 1 **product scope** (steps 1–4 + ops tail) is closed. **Wave 1.5** (RAG & Prompt Config per [`ROADMAP_V3_PRODUCTION_FIRST.md`](ROADMAP_V3_PRODUCTION_FIRST.md)) was completed earlier in the project timeline and is **orthogonal** to this audience-driven Wave 1 sequence.

Decision Point evaluation per [`PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md` § 5](PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md): **no extraordinary external signals** collected during steps 1–4. Stage 0→1 monetization remains gated until explicit signal accumulation — continue lightweight cadence (GitHub stars / DM scan every 2 weeks) without blocking Wave 2 planning.

---

## 8. Remaining non-blocking items

| Item | Class | Owner |
|---|---|---|
| ~~Prod `.env`: `GRAFANA_WEBHOOK_TOKEN` (URL set 2026-06-03)~~ | Ops | Done 2026-06-06 |
| ~~Grafana admin password rotation~~ | Ops / security | Done 2026-06-06 (VPS `.env` only; not in repo) |
| ~~Post-closure Cursor automation cleanup § A (`2bd25769` / `f93e557a` disable)~~ | Ops | Done 2026-06-06 (operator UI — inactive) |
| ~~Post-closure Cursor automation cleanup § B (schema-probe deletes)~~ | Ops | ✅ **VERIFIED CLEAN 2026-06-14** — the live Automations list contains only 3 legitimate automations (incident webhook ingress [KEEP], T+24h watch closure [inactive], `digest_94483db9` [inactive prod digest]) and **zero** `[DELETE_ME] schema-probe-*` artifacts; nothing to delete. ⚠️ Caveat: the earlier 7-ID deletion checklist (`schema-probe-8/11/17/18/22/30/43`) was **stale** — derived from historical chat transcripts, not the live list (no `list_automations` tool attached, so it could not be re-verified live at filing time). |
| ~~Prod pull `2c0a187`+ (post-merge `01a3f15`)~~ | Deploy | Done 2026-06-06 (prod now `b04353b`) |
| Post-closure Telegram cleanup § D (R-1 / R-2 / `vps-watch-test-grp`) | Ops | **Deferred** — runbook default KEEP test artifacts; optional demote `@Tgingest_bot` from admin in test group |
| ~~BUG-025 / BUG-026 / BUG-027~~ | Bot UX | ~~Wave 2 sprint~~ → ✅ resolved on `main` (commit `13d2200`, closed 2026-06-13; the original § 5 decision to defer is preserved as historical record) |
| ~~BUG-036 BUG_LOG status flip to `resolved`~~ | Docs hygiene | Done 2026-06-03 |
| C-3 `failed` channel-publish counter materialization | Observability test | Optional future watch |
| Stale `START_PROMPT_*` artifacts (see § 9) | Docs hygiene | Ad hoc |
| ~~Optional `v4.4.0` tag + README Wave 1 narrative~~ | Release | Done 2026-06-06 |

---

## 9. Pre-next-step readiness checklist

- [x] Steps 1–4 DONE markers valid
- [x] Post-step-4 critical bot regressions (BUG-031…035) resolved on prod
- [x] Step 5 Grafana provisioning-as-code on prod — **DONE 2026-06-06** (webhook contact point + token deployed; E2E verified via issue [#195](https://github.com/AlexEfimov/TG_parser/issues/195); see § 2)
- [x] Aggregate closure marker produced (this document)
- [x] Cross-link in [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md)
- [x] Operator prod webhook token (Done 2026-06-06); ~~password rotation deferred per § 8~~ password rotation Done 2026-06-06

---

## 10. Lessons learned

1. **Step 4 watch surfaced more bot UX debt than step 4.1 could absorb** — post-step-4 tail (BUG-031…053) consumed ~2 weeks; deferring BUG-025/026 to Wave 2 was correct to avoid junk-drawer step 4.1 scope creep.
2. **Grafana UI-created rules fight provisioning-as-code** — first deploy of `wave1_step4.yaml` hit `alert-rule.conflict`; delete UI duplicates before enabling provisioning (documented in Step 5 verify).
3. **Compose-default webhook env prevents crash-loop but silences alerts** — distinguish «container healthy» from «alert path end-to-end live».

---

## 11. Footnote — stale START_PROMPT inventory

The following session prompts predate this closure and may reference superseded SHAs or open BUG statuses (not bulk-edited in this session):

* `START_PROMPT_SPRINT_WAVE1_STEP4_2026-05-23.md`, `START_PROMPT_SPRINT_WAVE1_STEP3_2026-05-21.md` — step planning artifacts
* `START_PROMPT_FIX_BUG033_CLUSTER_2026-05-30.md`, `START_PROMPT_FIX_BUG039_042_CONVERSATION_LAYER_2026-05-31.md` — resolved clusters
* `START_PROMPT_PRESERVE_TG_URLS_2026-06-02.md`, `START_PROMPT_POST_BUG050_FOLLOWUPS_2026-06-02.md` — landed on prod

Use this aggregate marker + per-step DONE markers as authority for Wave 1 state.

> **Pointer (2026-06-13, doc-drift cross-link):** this stale-prompt inventory is itself superseded by the Wave A–C tech-debt closure track — see [`START_PROMPT_WAVE1_TECH_DEBT_CLOSURE_2026-06-12.md`](START_PROMPT_WAVE1_TECH_DEBT_CLOSURE_2026-06-12.md) and [`WAVE1_TECH_DEBT.md`](WAVE1_TECH_DEBT.md) for the authoritative current status of the listed prompts/SHAs. The list above is not bulk-edited.

---

## 12. Sign-off

Wave 1 (audience-driven steps 1–4 + Step 5 ops) declared **DONE with documented caveats** as of **2026-06-03**; **fully closed** (blocking + optional release items) as of **2026-06-06** — aggregate marker updated, prod on `b04353b`, `v4.4.0` tagged, README narrative added. Remaining operator-discretion: § B schema-probe UI deletes, § D Telegram test-artifact hygiene (optional).

**Tech-debt addendum (2026-06-13):** the Wave 1 tech-debt track (Wave A–C — BUG-019/020/021/054/055/056/057/058/059/060, DOC-001, TD-confirm-flow-concurrency, TD-bot-confirm-coverage-completeness, TD-test-isolation-execute-tool-leak, plus the late BUG-025/026/027 bot-UX cluster) is now **closed on `main`** (see [`WAVE1_TECH_DEBT.md`](WAVE1_TECH_DEBT.md) § A for per-item commit-refs). The only item left `open` is **BUG-008** (MCP transport hang), explicitly **deferred to Wave 2**.
