# Post-Living-KB Audit — Reviewer gpt55

**Reviewer model:** Claude Opus 4.7 (handshake said `REVIEWER_ID=gpt55`; model-string passed as-is — no other interpretation made)
**Reviewer window:** gpt55
**Started (UTC):** 2026-04-26T11:30:00Z
**Finished (UTC):** 2026-04-26T12:10:00Z
**Base commit:** `ef952b4`
**Time spent:** ~3.5h Side A + ~2h Side B (continued from a summarised earlier window — same session, same base commit)
**Scope coverage:** 8/8 code zones (with caveats — see § 1 Open Questions for sandbox-blocked checks), 8/8 docs zones
**Findings count:** 15, of which: critical=1, major=4, minor=10
**Open questions:** 4 (see § 1)

---

## 1. Executive summary

Wave 1 closes cleanly: the three sprints (D.1 / F11 / F5-C) are functionally complete and the
Living-KB contract is effectively closed. Code-side, the F5-C core (`ResummarizationService`,
`TopicCardRepo.commit_resummary`, advisory-lock flow, append-only `topic_card_versions`) is
well-shaped and the F11 hook chain is consistent with D.1's silent-log pattern. The audit
surfaces **one critical** code-vs-docs contract mismatch (`error_message` truncation:
500 chars in code vs 4096 promised in CHANGELOG / ARCHITECTURE / D.1 sprint notes — cuts
RCA evidence and breaks the post-D.1 promise of truthful `source_attempts`), **four
major** items (one promised-but-missing F11 metric, three docs-stale buckets including
`PRODUCTION_DEPLOYMENT.md` lacking any reference to F5-C/F11, and `ROADMAP_V3` showing
F11/F5-C as future), and ten minor cleanups (dependency-graph smell `services → api`, dead
`if`-branch in scheduler hook, structlog format-string drift, per-call LLM client
construction in `ResummarizationService`, and several documentation accuracy nits).

**Recommendation:** **debt-fix sprint** before any new feature scope (high confidence) — see § 5.

**Open questions:**

1. **Watch cron-log on prod** — sandbox blocks `ssh prod cat ~/f5c-watch/cron.log`; cannot
   confirm GREEN/TRIPWIRE verdict count from this window. Reviewer recommends merge agent
   pulls the latest verdicts before final calibration.
2. **GitHub issue #15 (F5-C P2 backlog)** — sandbox blocks `gh issue view 15`; cannot
   verify cross-link integrity between `FUTURE_FEATURES.md § Level C` and the GH issue body.
3. **Live coverage numbers (`pytest --cov`)** — not run in this window (no PG, sandbox can
   start `pytest` but `pytest-cov` was not verified to be installed; per § 3.1 — “if not
   installed, record as OPEN QUESTION”). Test-file enumeration was used as a proxy
   (90 test files; 6 F5-C, 5 F11+score+service for F11). Coverage gaps for hot-paths not
   independently measured here.
4. **`sonnet45` deliverable** — `ls docs/notes/REVIEW_2026-04-26_POST_LIVING_KB__*.md`
   returned no other file at start, so isolation of perspectives is preserved. If the
   parallel window committed during this review, merge-agent should treat that as a
   normal disclosure event (§ 15.3); no contamination occurred from this side.

---

## 2. Code findings

### 6.5 Error handling consistency

#### gpt55-001 — critical | error-handling | confidence: high

**Where:** `tg_parser/services/scheduler_service.py:744`

**Zone:** 6.5 Error handling consistency

**Observation:** `_truncate_error_message` truncates to **500** characters
(`message: str, max_len: int = 500`), but `CHANGELOG.md:131` (Sprint D.1 § Truthful
`source_attempts`), `docs/notes/ARCHITECTURE_INCREMENTAL_TOPICIZATION.md` Sprint D.1
section, and the D.1 planning prompt all state the error_message is truncated to
**4096** characters. There is no env-var or settings binding for this limit — it is
a magic number embedded in the helper signature.

```744:745:tg_parser/services/scheduler_service.py
def _truncate_error_message(message: str, max_len: int = 500) -> str:
    return message[:max_len]
```

**Why it matters:** D.1's central promise was “any failure on any stage is recorded
truthfully in the database”. A 500-char cap silently elides Anthropic billing
messages, full Telegram error envelopes, and stack-trace fragments — precisely the
content RCA needs. The discrepancy is also a documentation-vs-implementation contract
break; on-call engineers reading CHANGELOG/ARCHITECTURE will assume they have ~8× more
context than they actually do, and may stop scrolling in a triage window. The mismatch
predates this audit (D.1 deploy 2026-04-25) but had not been caught.

**Suggested action (draft PR description):**
`fix(scheduler): align error_message truncation with documented 4096-char contract`
Either bump `_truncate_error_message`'s default to 4096 (matches CHANGELOG/ARCH) or
make it a setting (`error_message_max_len: int = 4096`) and update CHANGELOG line 131
plus ARCH if the policy changes. Add one regression test:
`tests/test_scheduler_service.py::test_record_attempt_truncates_at_documented_limit`
asserting a >4096-char message gets stored intact up to the documented limit.

**Notes:** Detection-only — no opinion on whether 500 or 4096 is the right value;
contract should match docs. Also affects: `CHANGELOG.md:131`,
`docs/notes/ARCHITECTURE_INCREMENTAL_TOPICIZATION.md` (D.1 section). See gpt55-009
(docs side of same mismatch).

#### gpt55-004 — minor | error-handling | confidence: high

**Where:** `tg_parser/services/scheduler_service.py:256-261`

**Zone:** 6.5 Error handling consistency

**Observation:** Two consecutive `if`-blocks in the `finally` of `_process_source` test
the **same** condition (`stage_errors and isinstance(stage_errors[0][1], AnthropicBillingError)`).
The first records the metric; the second pauses the source. They could be a single
guard with two body lines.

```256:261:tg_parser/services/scheduler_service.py
if stage_errors and isinstance(stage_errors[0][1], AnthropicBillingError):
    from tg_parser.api.metrics import record_anthropic_billing_block

    record_anthropic_billing_block(stage=stage_errors[0][0])
if stage_errors and isinstance(stage_errors[0][1], AnthropicBillingError):
    await _pause_source_for_billing(source, state_repo)
```

**Why it matters:** Functionally correct today, but the duplication invites a future
edit to keep one branch and forget the other (e.g. someone moves the metric call to
`_pause_source_for_billing` and leaves the orphan `if` behind). It also obscures the
intent: “on billing error, do A and B” is one decision, not two.

**Suggested action (draft PR description):**
`refactor(scheduler): collapse duplicate AnthropicBillingError guard in _process_source`
Merge the two adjacent `if isinstance(stage_errors[0][1], AnthropicBillingError):`
blocks into one, keeping both side-effects (`record_anthropic_billing_block` and
`_pause_source_for_billing`). No behaviour change. Existing
`tests/test_scheduler_service.py` covers the path.

#### gpt55-006 — minor | error-handling | confidence: medium

**Where:** `tg_parser/services/resummarization_service.py:268-285`

**Zone:** 6.5 Error handling consistency (also touches resource lifecycle / observability)

**Observation:** `resummarize_topic` constructs a fresh LLM client per topic
(`create_llm_client(provider=..., model=...)` line 269) and `await client.close()`s it
inside a per-call `try/finally` (line 285), all under `contextlib.suppress(Exception)`.
The service-level `aclose()` does not own the LLM client — only the prompt loader.

```268:285:tg_parser/services/resummarization_service.py
provider, api_key, model = resolve_llm_config("resummarize")
client = create_llm_client(provider=provider, api_key=api_key, model=model)
model_settings = self.prompt_loader.get_model_settings("resummarize") or {}
t0 = time.perf_counter()
try:
    resp = await client.generate_with_usage(
        user_prompt,
        system_prompt=sys_prompt,
        **model_settings,
    )
finally:
    duration_s = time.perf_counter() - t0
    with contextlib.suppress(Exception):
        await client.close()
```

**Why it matters:** Two effects. (a) Per-tick perf — under the triple-cap of 10
topics/tick × ~hour cadence the overhead is small but real (HTTP keep-alive lost on
every call). (b) Suppressed `client.close()` failures are silently dropped under
`contextlib.suppress(Exception)`; if a provider regression starts leaking sockets, the
first signal will be `ulimit -n` exhaustion, not a log line. Other services use a
class-level client + `aclose()` pattern (e.g. `WatchlistService` per CHANGELOG
§ Sprint F11 line 76).

**Suggested action (draft PR description):**
`refactor(resummarize): pool LLM client at service level + log close failures`
Move `create_llm_client(...)` into `ResummarizationService.__init__` (or a lazily
cached property keyed by `(provider, model)`) and close it from `aclose()`. Replace
the `contextlib.suppress(Exception)` around `client.close()` with
`logger.exception("f5c_llm_client_close_failed", ...)` so close-side bugs surface.

**Notes:** Confidence medium because per-call construction is defensible if the
provider/model resolution result can change between ticks (runtime
`set_llm_config(scope='resummarize', ...)`). The fix should preserve that runtime
re-config path — keep a small cache keyed on `(provider, model)` rather than singleton.

### 6.1 Dependency graph hygiene

#### gpt55-003 — minor | dependency-graph | confidence: high

**Where:** `tg_parser/services/{background_scheduler.py:79, 144, 320, scheduler_service.py:257, resummarization_service.py:44, topicization_service.py:94, 290}`

**Zone:** 6.1 Dependency graph hygiene

**Observation:** Five service-layer files import from `tg_parser.api.*` (specifically
`api.metrics` and `api.health_checks`). The prompt § 6.1 #1 expectation
(`rg "from tg_parser.api" tg_parser/services/`) is empty. There is no actual cycle
(`tg_parser/api/metrics.py` does not import from `tg_parser.services`), but the
declared layering is violated.

```44:44:tg_parser/services/resummarization_service.py
from tg_parser.api.metrics import record_resummarize_outcome
```

```256:259:tg_parser/services/scheduler_service.py
if stage_errors and isinstance(stage_errors[0][1], AnthropicBillingError):
    from tg_parser.api.metrics import record_anthropic_billing_block

    record_anthropic_billing_block(stage=stage_errors[0][0])
```

**Why it matters:** `tg_parser.api.metrics` is observability infrastructure (Prometheus
counters and histograms), not an HTTP-facing API surface. Naming places it under
`tg_parser.api` so the “services should not depend on api” invariant looks broken on
grep, and one careless future refactor (someone moves a route handler into
`api.metrics` because the file already exists) introduces the real cycle. F5-C made
this worse by adding three direct imports (`record_resummarize_outcome`,
`record_anthropic_billing_block`, plus the F11 watchlist scoring path uses the same
module).

**Suggested action (draft PR description):**
`refactor(observability): extract metrics+health into tg_parser.observability package`
Move `tg_parser/api/metrics.py` → `tg_parser/observability/metrics.py` and
`tg_parser/api/health_checks.py` → `tg_parser/observability/health.py`. Update the
seven import sites in `tg_parser/services/*` and any `tg_parser/api/*` callers
(re-exports kept in `tg_parser/api/metrics.py` for one release cycle for backward
compatibility). After this the “services → api should be empty” invariant becomes
true and grep-checkable.

**Notes:** Detection-only; the alternative is to keep the directory layout and update
the prompt-§6.1 expectation to allow `api.metrics` / `api.health_checks` as documented
exceptions. Either is fine — but the current state is silently inconsistent with the
declared rule.

### 6.6 Observability completeness

#### gpt55-002 — major | observability | confidence: high

**Where:** `tg_parser/services/watchlist_service.py:21` (docstring),
`tg_parser/domain/models.py:714` (docstring),
`docs/notes/F11_PR_CHECKLIST.md:53`,
`docs/notes/START_PROMPT_SPRINT_F11.md:109,624`,
`docs/notes/START_PROMPT_SPRINT_F5C.md:1621`

**Zone:** 6.6 Observability completeness

**Observation:** F11's planning docs and PR checklist promise a Prometheus counter
`tg_watchlist_matches_total{interest_id, score_bucket}` (with buckets `0.6-0.7`,
`0.7-0.8`, `0.8+`) for threshold calibration. The metric is **not exported anywhere
in code**. `tg_parser/api/metrics.py` defines `RESUMMARIZE_*` counters and
`ANTHROPIC_BILLING_*` but no `WATCHLIST_*` counters. `watchlist_service.py:21`
explicitly says “a future `tg_watchlist_matches_total` metric”.

**Why it matters:** F11's threshold default is 0.6 with explicit doc-acknowledged
risk of false-positive flood (`F11_PR_CHECKLIST.md:53` calls this “karpathy-like:
closed observability loop for threshold calibration without blind LLM tuning”).
Without the metric, on-call has no way to decide whether to lower or raise the
default; F11 P2 tuning is blind. The watchlist hook itself is shipped to prod and
has been running for ~24h.

**Suggested action (draft PR description):**
`feat(watchlist): export tg_watchlist_matches_total{interest_id,score_bucket}`
Add three Counter labels in `tg_parser/api/metrics.py`:
`tg_watchlist_matches_total = Counter("tg_watchlist_matches_total", "...", ["interest_id", "score_bucket"])`
with helper `record_watchlist_match(interest_id: str, score: float)` that buckets
`score` into `0.6-0.7` / `0.7-0.8` / `0.8+`. Wire it from
`WatchlistService.check_interests` after `WatchMatch` insert. Add corresponding
PromQL example in `docs/runbooks/F5C_DEPLOY_AND_WATCH.md` (rename / new runbook for
F11 watch).

**Notes:** Without this metric, gpt55-008 (ROADMAP stale) and the F11 P2 plan
(`notify_mode=batch` triggered by metric signal) cannot proceed. So this feeds two
backlog items.

#### gpt55-005 — minor | observability | confidence: high

**Where:** `tg_parser/services/scheduler_service.py:244-249, 254, 289-295, 741, 753-757`

**Zone:** 6.6 Observability completeness

**Observation:** The structlog logger is configured project-wide, but several
log-call sites inside `scheduler_service.py` still use `%s`-style positional
formatting (which hides keys from JSON output) instead of key=value kwargs.
F5-C-era code (`resummarization_service.py:175-180`) uses the correct
key-value form, while D.1-era code that lives in the same hook chain remains
positional.

```254:254:tg_parser/services/scheduler_service.py
logger.error("Source %s failed: %s", source_id, exc, exc_info=True)
```

```289:295:tg_parser/services/scheduler_service.py
logger.info(
    "source=%s: stages_ok=%s, stages_failed=%s, outcome=%s",
    source_id,
    stages_ok,
    [s for s, _ in stage_errors],
    "success" if success else "failure",
)
```

**Why it matters:** Mixed log conventions in one hook chain mean that
Loki/JSON consumers see structured fields for some events and a raw rendered
string for others — same scheduler tick, different shape. Dashboards filtering
by `event="source_failed"` will miss the D.1 lines.

**Suggested action (draft PR description):**
`refactor(scheduler): unify structlog usage on key-value form`
Replace all `logger.{info,error,warning}("msg %s", val)` calls in
`scheduler_service.py` (lines 244, 254, 289, 741, 753) with
`logger.{level}("event_name", source_id=..., new_messages=..., ...)` per the
F5-C convention. Add a project-level lint rule (`ruff` custom plugin or `grep`
in CI) to prevent regression.

**Notes:** Same drift may exist elsewhere (out-of-scope for this audit but
flagged for awareness).

### 6.2 Dead code / dead exports

#### gpt55-007 — minor | dead-code | confidence: medium

**Where:** `tg_parser/cli/topic_cmd.py:191-199`

**Zone:** 6.2 Dead code / dead exports

**Observation:** The CLI defensively reads two keys when consuming
`ResummarizationService.resummarize_topic` outcome: `version_no` (the actual
contract — service returns this on line 421 of `resummarization_service.py`)
and `summary_version` (legacy fallback that nothing in code emits).

```191:199:tg_parser/cli/topic_cmd.py
status = outcome.get("status", "unknown")
typer.echo(f"   • status:    {status}")
# Accept both `version_no` (current ResummarizationService contract) and
# `summary_version` (legacy / future-proof in case the field is renamed
# to match the topic_cards column).  Without this dual-key read, the
# CLI silently dropped the version on every successful run because the
# service returns `version_no`, not `summary_version`.
new_version = outcome.get("version_no", outcome.get("summary_version"))
```

**Why it matters:** The `summary_version` branch is dead today (no caller
emits it), and the comment hints at a real bug fix (CHANGELOG line 42 confirms
this was a missed CLI version-printing bug). Carrying the fallback hides the
service contract — readers can't tell if `summary_version` is reserved for
some other code path or pure scar tissue. Either codify a single key or
canonicalise the rename.

**Suggested action (draft PR description):**
`chore(cli): canonicalise outcome key as version_no (drop summary_version fallback)`
Drop the `outcome.get("summary_version")` fallback. Pin the contract in
`ResummarizationService.resummarize_topic`'s docstring (line 199-208) so the
key name is explicit. Existing test `tests/test_f5c_cli.py` already pins
`version_no`.

**Notes:** Confidence medium — fallback may be a deliberate forward-compat hedge;
verify with author before removal.

### 6.3 Test coverage map

#### gpt55-013 — minor | test-coverage | confidence: high

**Where:** `CHANGELOG.md:91`, `tests/test_f11_watchlist_repo.py:333` (vs missing
`tests/test_f11_watch_match_repo.py`)

**Zone:** 6.3 Test coverage map (also docs-side mirror in § 7.3)

**Observation:** CHANGELOG line 91 references `tests/test_f11_watch_match_repo.py`
as a separate file with “`mark_notified` batch, `since_iso` фильтр” coverage. The
file does not exist; instead a `class TestWatchMatchRepo:` lives at
`tests/test_f11_watchlist_repo.py:333` and provides the same tests.

**Why it matters:** Code coverage as documented overstates by one file. Anyone
running `pytest tests/test_f11_watch_match_repo.py` (e.g. from the CHANGELOG
copy-paste) will get “no tests collected”. Minor on its own; pattern-of-drift if
combined with other docs-vs-reality nits in this audit.

**Suggested action (draft PR description):**
`docs(changelog): correct F11 test-file reference (TestWatchMatchRepo lives in test_f11_watchlist_repo.py)`
Edit CHANGELOG.md line 91 to reference `tests/test_f11_watchlist_repo.py::TestWatchMatchRepo`
(or split the class into a separate file if that was the intent). Either is fine —
docs and code must match.

### 6.4 Schema hygiene

(No critical or major findings — schema is in good shape.)

**Verified clean:**
- Alembic linearity ingestion: `f6a1b2c3d4e5 → ac6a4414ac58 (D.1) → c8e9f0a1b2c3 (F11)` — single chain, two same-day revisions are linearised correctly.
- Processing chain: `b8e2f7c1d9a3 → c9d8e7f6a5b4 → a4b5c6d7e8f9 (F5-C)` — single head.
- Raw chain: `5c658f04eff0` (no changes since Dec 2025).
- F5-C three new columns on `topic_cards` (`last_summarized_at`, `summary_version`, `new_items_since_last_summary`) all read/write at runtime (`storage/sqlalchemy/topic_card_repo.py:34-39`).
- F5-C partial index `idx_topic_cards_resummarize_candidates WHERE new_items_since_last_summary > 0` documented in migration docstring.
- `topic_card_versions UNIQUE(topic_id, version_no)` + FK CASCADE per migration.
- F5-C upsert correctly excludes `summary_version` / `last_summarized_at` / `new_items_since_last_summary` from `ON CONFLICT` reset (preserves F5-C contract).

### 6.7 Prompt drift

(No findings.) Verified: nine `prompts/*.yaml` files including new `resummarize.yaml`
(73 lines, version `1.0.0`, system/user/model sections per convention). Prompt
metadata.version is read by `ResummarizationService` (line 248-249) and persisted
into `topic_card_versions.prompt_version` (line 331).

### 6.8 Migration replay

(No findings.) Verified: `tests/test_migrations_runtime_upgrade.py` includes
`topic_card_versions` in `EXPECTED_TABLES` per CHANGELOG line 43 (test file exists
and was updated in F5-C 2/2 commit).

---

## 3. Docs findings

### 7.1 ROADMAP_V3_PRODUCTION_FIRST.md

#### gpt55-008 — major | roadmap-stale | confidence: high

**Where:** `ROADMAP_V3_PRODUCTION_FIRST.md` (multiple sections — `F11 Topic Watchlist`,
`F5-C Evolving Topic Summaries`, Wave 3 priorities table)

**Zone:** 7.1 ROADMAP_V3 stale

**Observation:** F11 and F5-C are referenced as planned/medium-priority/future in
Wave 3 sections of the document, despite both being marked DONE in CHANGELOG (F11
2026-04-25; F5-C 2026-04-26) and in `ROADMAP_KARPATHY_LIKE_LIVING_KB.md`. F4 is
marked complete-but-low-priority — internally inconsistent. The Wave 1 closure
(D.1 + F11 + F5-C) is not headline-summarised.

**Why it matters:** ROADMAP is the single document new contributors and reviewers
read first to understand “where we are, what's next”. Stale roadmap gives wrong
priorities (someone may pick up F11 thinking it's the next sprint). It also makes
merge-agent's Recommendation harder to calibrate — § 5 of the merge prompt assumes
ROADMAP reflects current ground truth.

**Suggested action (draft PR description):**
`docs(roadmap): mark Wave 1 (D.1+F11+F5-C) closed; re-prioritise Wave 2 entries`
Add a top-of-document banner: “Wave 1 closed 2026-04-26 — Living-KB contract
satisfied. Wave 2 entry candidates below.” Move F11 / F5-C / D.1 into a “Done”
section. Re-rank Wave 2 entries (F1 Full / F10-A / F12-A / F11 P2 / F5-C P2) per
the next-sprint decision from this review's merge step.

**Notes:** Touches several sections — keep PR scoped to status updates only,
no scope changes.

### 7.5 PRODUCTION_DEPLOYMENT.md

#### gpt55-010 — major | deploy-stale | confidence: high

**Where:** `PRODUCTION_DEPLOYMENT.md` (entire file)

**Zone:** 7.5 PRODUCTION_DEPLOYMENT.md / runbooks deploy

**Observation:** `PRODUCTION_DEPLOYMENT.md` (the canonical operator-facing deploy
guide) contains **zero** references to `F5-C`, `F11`, `RESUMMARIZE_*`, or
`watchlist`. No mention of the three migrations shipped in Wave 1, no env-vars
listing, no F5-C/F11 verification commands. (Verified via
`rg "F5-C|F11|RESUMMARIZE_|watchlist" PRODUCTION_DEPLOYMENT.md` → no matches.)

**Why it matters:** Operators following this guide cold (DR scenario, new VPS
setup, onboarding contractor) will deploy a stack that lacks the seven F5-C cap
env-vars (`RESUMMARIZE_TRIGGER_N`, `MAX_PER_TICK`, `MAX_DURATION_S`,
`MAX_TOKENS_PER_TICK`, `INPUT_WINDOW_N`, plus per-stage LLM provider/model) and
cannot verify F5-C / F11 health post-deploy. F5-C ships kill-switch
`RESUMMARIZE_ENABLED=true` defaulting on — operator should at least know it
exists. Conversely, `docs/runbooks/F5C_DEPLOY_AND_WATCH.md` covers F5-C-specific
deploy steps but is referenced from neither `PRODUCTION_DEPLOYMENT.md` nor
`README.md`.

**Suggested action (draft PR description):**
`docs(deploy): add F5-C/F11/D.1 sections to PRODUCTION_DEPLOYMENT.md`
Add three subsections under § Application Deployment:
(1) D.1 — `failed_stage` migration `ac6a4414ac58`, billing-pause behaviour;
(2) F11 — watchlist migration `c8e9f0a1b2c3`, env-vars (`MAX_DOCS_PER_TICK`),
verification SQL (`SELECT count(*) FROM watch_interests`);
(3) F5-C — migration `a4b5c6d7e8f9`, seven env-vars, verification curl
(`/metrics | grep tg_resummarize`), kill-switch `RESUMMARIZE_ENABLED=false`,
link to `docs/runbooks/F5C_DEPLOY_AND_WATCH.md` for the full watch protocol.

### 7.3 CHANGELOG.md

#### gpt55-009 — major | changelog-incomplete | confidence: high

**Where:** `CHANGELOG.md:131` (and matching docs)

**Zone:** 7.3 CHANGELOG.md

**Observation:** CHANGELOG § Sprint D.1 line 131 says
“Любой сбой на любом этапе пишется в БД (`error_message` усечено до 4096
символов).” — but `tg_parser/services/scheduler_service.py:744` truncates at 500.
Same number repeats in `docs/notes/ARCHITECTURE_INCREMENTAL_TOPICIZATION.md`
Sprint D.1 § 1, and the D.1 sprint planning prompt.

**Why it matters:** This is the docs-side mirror of gpt55-001. CHANGELOG is the
post-deploy sign-off contract; if the contract says 4096 and reality is 500,
either the code is wrong (PR to bump) or the changelog is wrong (PR to correct
to 500 and document why). Either way must be a single coordinated change.

**Suggested action (draft PR description):**
`docs(changelog): align error_message truncation reality with CHANGELOG/ARCH`
Either (a) update CHANGELOG line 131 and ARCH D.1 § 1 to “500 chars” + add an
explanation comment in `_truncate_error_message`, or (b) bump the code limit to
4096 (paired with gpt55-001). Pick one in coordination with the maintainer; do
not split.

**Notes:** Treated as separate finding from gpt55-001 because the merge-agent
needs to track docs-stale vs code-error as different categories. Both findings
must close together.

### 7.2 ROADMAP_KARPATHY_LIKE_LIVING_KB.md

#### gpt55-011 — minor | roadmap-stale | confidence: high

**Where:** `ROADMAP_KARPATHY_LIKE_LIVING_KB.md` (top-of-document banner)

**Zone:** 7.2 ROADMAP_KARPATHY

**Observation:** Wave C (F5-C) is correctly marked as implemented on 2026-04-26
in the body of the document, but there is no top-level “**Living KB contract:
CLOSED 2026-04-26 (D.1 + F11 + F5-C)**” banner, which the prompt § 7.2 expects
explicitly.

**Why it matters:** A reader scanning only the top table will not see that the
contract is closed unless they cross-read all three Waves and reconcile dates.
Adding one banner line resolves the ambiguity.

**Suggested action (draft PR description):**
`docs(roadmap): add Living-KB-contract-CLOSED banner at top of KARPATHY roadmap`
Insert one line at the top: `> **Living-KB contract: CLOSED 2026-04-26**
> (D.1 hardening + F11 watchlist + F5-C evolving summaries — see Wave-A/B/C below)`.
No body change.

### 7.4 FUTURE_FEATURES.md

#### gpt55-015 — minor | future-features-stale | confidence: low

**Where:** `docs/notes/FUTURE_FEATURES.md` § Level C / F5-C P2 backlog

**Zone:** 7.4 FUTURE_FEATURES

**Observation:** F5-C P2 backlog lists 9 deferred items in `docs/notes/FUTURE_FEATURES.md`,
but no individual items reference `issue #15`. The prompt § 7.4 expects
each item to map to issue #15. Cannot independently verify the GH issue body
from this sandbox (open question § 1 #2).

**Why it matters:** When the next planning agent picks up an F5-C P2 item, it has
to do its own cross-reference dance to find the GH issue. Adding a single ref-line
or anchor-link saves that step.

**Suggested action (draft PR description):**
`docs(future-features): cross-link F5-C P2 backlog to GitHub issue #15`
Add a one-line ref at the top of § Level C → F5-C P2 backlog:
`> **Tracked in GitHub:** [issue #15 — F5-C Phase 2 deferred items]`. Verify
issue #15 body lists matching items; if they diverge, sync.

**Notes:** Confidence low because GH access is sandbox-blocked from this session;
the missing cross-link may already be in the GH issue from the other direction
(issue body referencing the file). Merge-agent should verify before opening a PR.

### 7.6 runbooks

(No major findings — runbooks are well-shaped.)

#### gpt55-012 — minor | changelog-incomplete | confidence: high

**Where:** `docs/notes/ARCHITECTURE_INCREMENTAL_TOPICIZATION.md` § Ключевые файлы

**Zone:** 7.6 runbook-stale (document is architectural reference; using nearest
controlled-vocab category)

**Observation:** `ARCHITECTURE_INCREMENTAL_TOPICIZATION.md` describes Sprint D.1
in detail (line 269-271 covers per-batch checkpointing, escalation, billing-error
handling) but the “Ключевые файлы” section does not list F5-C-introduced
`tg_parser/services/resummarization_service.py` or F11's
`tg_parser/services/watchlist_service.py`, despite both running in the same
incremental tick after D.1 (verified — scheduler hook chain is
`run_topic_embedding → run_resummarize_for_channel → run_watchlist_check_for_channel`,
ARCH does not show F5-C/F11 fitting in).

**Why it matters:** New contributors reading this architecture doc to understand
the incremental flow will miss two of the three services that run in it. F5-C and
F11 are first-class participants in the post-incremental tick chain, not external
features.

**Suggested action (draft PR description):**
`docs(architecture): include F5-C+F11 in incremental-topicization key-files list`
Append to § Ключевые файлы:
- `tg_parser/services/resummarization_service.py` (F5-C — runs after embedding)
- `tg_parser/services/watchlist_service.py` (F11 — runs after F5-C)
Add a one-paragraph note to § Sprint D.1 explaining the post-D.1 hook chain
(reference CHANGELOG § Sprint F5-C line 23).

### 7.7 notes archive

#### gpt55-014 — minor | notes-archive | confidence: high

**Where:** `docs/notes/` (directory)

**Zone:** 7.7 notes archive

**Observation:** `docs/notes/` contains **105** markdown files (verified via
`ls docs/notes/ | wc -l`); the prompt § 4 ground-truth cited 100. The five-file
delta is harmless but the broader observation stands: the directory mixes active
sprint prompts (e.g. this audit's `START_PROMPT_REVIEW_POST_LIVING_KB.md`) with
~40+ played-out `START_PROMPT_SESSION{1..47}_*.md` and `START_PROMPT_SPRINT_*.md`
files. There is no `docs/notes/archive/` subdirectory.

**Why it matters:** Search-and-find for active context is degraded — every
`Glob "**/START_PROMPT_*.md"` or `rg` returns dozens of stale results. Onboarding
contributors hit the same noise. An archive subdirectory + INDEX.md gives clear
boundaries between “active” and “historical”.

**Suggested action (draft PR description):**
`docs(notes): introduce docs/notes/archive/ + INDEX for played-out prompts`
Move `START_PROMPT_SESSION*.md`, played `START_PROMPT_SPRINT_*.md` (D.1, F11,
F5-C planning + sprint + checklist files) into `docs/notes/archive/2026-04/`.
Create `docs/notes/archive/INDEX.md` listing each by date + outcome (`fixed`,
`obsoleted`, `superseded by …`). Keep this audit's file in `docs/notes/` (it's
active until merge-session finishes). Estimated 30-50 file moves; pure
restructuring, no content edits.

**Notes:** A lower-effort alternative is to leave files in place but add a
SECTION-divider in `docs/notes/README.md` (or new INDEX.md at root of notes/).

### 7.8 quality/INBOX & TRIAGED

(No findings.) Verified: `INBOX.md` empty (per template). `TRIAGED.md` has the
single genotek-RCA entry, status `fixed in production` since D.1 deploy. Cadence
note (“triage before each sprint-planning session”) is respected.

---

## 4. Tech-debt backlog → predicted issues

| ID | Source finding(s) | Title | Predicted scope | Priority |
|---|---|---|---|---|
| TD-01 | gpt55-001, gpt55-009 | Align `error_message` truncation: code-vs-CHANGELOG (4096 vs 500) | S | P0 |
| TD-02 | gpt55-002 | Export `tg_watchlist_matches_total{interest_id, score_bucket}` (F11 prereq for P2) | S | P0 |
| TD-03 | gpt55-008 | Refresh `ROADMAP_V3_PRODUCTION_FIRST.md` to reflect Wave 1 closure | S | P0 |
| TD-04 | gpt55-010 | Add F5-C/F11/D.1 sections to `PRODUCTION_DEPLOYMENT.md` | M | P0 |
| TD-05 | gpt55-003 | Move `tg_parser.api.metrics` + `health_checks` to `tg_parser.observability.*` | M | P1 |
| TD-06 | gpt55-005 | Unify structlog usage on key-value form (scheduler_service + audit other services) | M | P1 |
| TD-07 | gpt55-006 | Pool LLM client at `ResummarizationService` level + log close failures | S | P1 |
| TD-08 | gpt55-004 | Collapse duplicate `AnthropicBillingError` guard in `_process_source` | S | P1 |
| TD-09 | gpt55-011, gpt55-012 | Documentation banner + architecture-doc cross-reference for Wave 1 closure | S | P1 |
| TD-10 | gpt55-007 | Drop `summary_version` legacy fallback in CLI; pin `version_no` contract | S | P2 |
| TD-11 | gpt55-013 | Correct CHANGELOG F11 test-file reference (`test_f11_watch_match_repo.py`) | S | P2 |
| TD-12 | gpt55-014 | Introduce `docs/notes/archive/` + INDEX, move played-out prompts | M | P2 |
| TD-13 | gpt55-015 | Cross-link F5-C P2 backlog to GitHub issue #15 (verify both directions) | S | P2 |

Scope key: `S` ≤ 1h, `M` ≤ 4h, `L` > 4h.
Priority: `P0` next-sprint blocker / `P1` next-sprint nice-to-have / `P2` later.

---

## 5. Recommendation для следующего спринта

- **Watch verdict:** Cannot read prod cron-log from this sandbox window (open question § 1 #1).
  CHANGELOG plus the prompt's ground-truth § 4 indicate first verdict GREEN at deploy time;
  merge-agent should pull the latest verdicts (≥ 4 expected at the 16-24h mark) before
  finalising recommendation.
- **Top-2 P0 debt items:** TD-01 (`error_message` truncation contract — critical
  observability/RCA) + TD-02 (`tg_watchlist_matches_total` metric — F11 P2 unblocker).
  TD-03 (`ROADMAP_V3` stale) and TD-04 (`PRODUCTION_DEPLOYMENT.md` missing F5-C/F11) are
  also P0-rated but doc-only.
- **Choice:** **Debt-fix sprint (recommended).** A 1.5-2 day sprint covering all four
  P0 items + TD-05/06/07 (P1 architectural) clears the entire backlog identified here
  without touching new feature scope. After this sprint Wave 2 starts on a clean
  baseline that *actually* matches the documentation.
  - **Alternative:** F11 P2 (`notify_mode=batch`/`silent`) is the closest-shot feature
    sprint, but it is **explicitly blocked** by TD-02 (no calibration metric → no signal
    on whether default 0.6 needs tuning → no informed P2 design). Picking F11 P2 over
    debt-fix means doing TD-02 first inside that sprint anyway, with less hygiene
    payoff. Same applies to F5-C P2 (#4 time-based / #5 TTL) — it inherits a 500-char
    `error_message` cap that makes failure-mode debugging harder than necessary.
- **Confidence in this recommendation:** **high.** The critical (gpt55-001) and the
  blocking-major (gpt55-002) cost <0.5 day to fix and unblock everything else. The
  doc-stale items (TD-03, TD-04) are <1 day combined. None of this is invisible; one
  reviewer is enough to surface them, but their cumulative effect on Wave 2 startup
  velocity is non-trivial.

---

## 6. Metrics snapshot (на момент завершения review)

- **HEAD:** `ef952b4` (2 commits ahead of prompt's stated `eb9756a` — both new commits add
  review protocol files only, no code/doc changes affecting this audit)
- **Tests:** **1881 passed, 4 skipped, 1 deselected** per CHANGELOG line 47-50 (no-PG mode);
  not independently re-run from this window — see § 1 OPEN QUESTION #3.
- **LOC:** `tg_parser/` = **41,668** (matches prompt's ~41,700); `tests/` = **43,070**
  (matches prompt's ~43,000 — tests still slightly outweigh production code, healthy).
- **Alembic heads:** `processing@a4b5c6d7e8f9` (F5-C), `ingestion@c8e9f0a1b2c3` (F11) —
  single chain confirmed: `f6a1b2c3d4e5 → ac6a4414ac58 (D.1) → c8e9f0a1b2c3 (F11)`,
  `raw@5c658f04eff0` (no changes since Dec 2025).
- **INBOX/TRIAGED entries:** **0** open in INBOX (template-only), **1** entry in TRIAGED
  (genotek topicization silent failure — `fixed in production` via D.1 deploy
  `33d9f48`).
- **Watch cron-log:** **N/A** for this window — sandbox blocks `ssh prod cat ~/f5c-watch/cron.log`.
  Latest verdict from CHANGELOG context: deploy-time GREEN. Merge-agent should pull live.
- **Counts independently verified during this window:**
  - `docs/notes/` files: **105** (prompt said 100; +5 net since prompt drafted; minor)
  - `docs/contracts/` files: **6** (prompt said 5; new `topic_card_version.schema.json`
    is the +1, expected per F5-C)
  - `prompts/*.yaml`: **9** files (matches prompt; new `resummarize.yaml` 73 lines, v1.0.0)
  - `docs/runbooks/`: **4** files (matches prompt: `ANTHROPIC_BILLING_RECOVERY`,
    `DEV_RESURRECTION`, `F5C_DEPLOY_AND_WATCH`, `SAFE_MIGRATION_ON_DEV`)
  - F5-C test files: **6** (`test_f5c_cli`, `_counter_increment`, `_mcp_tools`,
    `_resummarization_service`, `_scheduler_hook`, `_topic_card_repo`)
  - F11 test files: **5** F11-prefixed + `test_watchlist_service.py` +
    `test_watchlist_score.py` = **7** total watchlist-related test files
    (CHANGELOG line 91 mentions a `test_f11_watch_match_repo.py` that does not exist —
    see gpt55-013).

---

*End of deliverable — Reviewer gpt55, 2026-04-26.*
