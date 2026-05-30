# START PROMPT — `subscribe_digest` / ConfirmFlow bug cluster (BUG-033 Critical + BUG-031 + BUG-032 + BUG-034)

**Prepared:** 2026-05-30. **Repo:** `/Users/alexanderefimov/TG_parser`. **Branch:** `main`.
**`main` HEAD at prep time:** `121e833` (pushed to origin).

**Purpose:** close out the bot `subscribe_digest` / FSM `ConfirmFlow` bug cluster —
**BUG-033 (Critical)**, **BUG-031 (Severe)**, **BUG-032 (Medium)**, **BUG-034 (Medium)** —
all four surfaced on 2026-05-24 during the Wave 1 Step 4 VPS watch (Test C / Test D
interactive bot sessions). This document is fully self-contained: the next agent starts
in a fresh window with no access to the chat that produced it.

---

## ⚠️ READ THIS FIRST — current state is NOT what you might assume

The code fixes for **all four bugs are already merged to `main`** (verified via
`git merge-base --is-ancestor` against HEAD `121e833`):

| Bug | Severity | Fix commit on `main` | PR | PR body |
|---|---|---|---|---|
| BUG-033 | **Critical** | `e50449b` | #108 | `docs/notes/PR_BODY_BUG_033.md` |
| BUG-034 | Medium | `6ebad33` | #109 | `docs/notes/PR_BODY_BUG_034.md` |
| BUG-031 + BUG-032 | Severe / Medium | `66e8297` | #111 | `docs/notes/PR_BODY_BUG_031_032.md` |

The regression test suites were merged with each fix (`tests/test_bot_chat_target_resolution.py`,
`tests/test_bot_channel_name_parser.py`, `tests/test_bot_confirm_flow.py`).

**BUT** the `BUG_LOG.md` entries for these four still literally say `Status: open` — the
reconcile commit `121e833` ("reconcile bug statuses") only updated BUG-029 / 030 / 035 /
ENH-001 / 037 / 038, and **skipped 031–034**. So there is a documentation/reality gap.

**Therefore the next session is NOT "implement the fixes from scratch."** Treat it as a
**verification + reconciliation + production-smoke** session:

1. **Verify** the merged code actually closes each original Test C / Test D trace (read the
   code at the entry points below, run the regression suites).
2. **Reconcile** `BUG_LOG.md` statuses for BUG-031/032/033/034 → resolved, mirroring how
   `121e833` reconciled BUG-029/030/035 (add PR# + commit-SHA + a short resolution note).
3. **Production real-fire smoke** — re-run the Test C / Test D scenarios against the live
   bot in an actual Telegram group (this is how BUG-037 was closed; see
   `docs/notes/HANDOFF_BUG037_2026-05-30.md`). Note: prod deploy of recent `main` may be
   **pending** (operator) — confirm the deployed SHA before smoke-testing, otherwise you
   will be testing old code.
4. **Only if you find a genuine residual gap** (a trace that still reproduces, or a missing
   fix layer), open a NEW `BUG-NNN` entry and fix it on a fresh branch — do not silently
   patch a "closed" bug.

If, after step 1, you (or the operator) conclude the merged fixes are insufficient and a
real re-implementation is needed, fall back to the per-bug "suggested approach" sections
below, which preserve the original fix design from the BUG_LOG.

---

## Current state table

| Item | Status |
|---|---|
| `main` HEAD | `121e833` (pushed to origin) |
| BUG-037 (webhook classifier prefix) | ✅ resolved & real-fire verified 2026-05-30 (#146/#148 → `[5xx]`) |
| BUG-038 (live Grafana stale-metric / DatasourceNoData) | 📋 tracked, pending deploy/operator |
| ops/observability cluster (Wave 1 Step 5) | ✅ done |
| BUG-033 / 031 / 032 / 034 — **code** | ✅ merged (#108 / #111 / #109) |
| BUG-033 / 031 / 032 / 034 — **BUG_LOG status** | ⛔ still `open` (stale — needs reconcile) |
| BUG-033 / 031 / 032 / 034 — **prod real-fire verification** | ⛔ not yet done (this session) |
| Prod VPS deployed SHA | ❓ was `39b6ba2`; `656f23c` deploy **pending** (operator). Confirm it contains `e50449b`/`6ebad33`/`66e8297` before smoke — same deploy blocker as BUG-038 |

The bot `subscribe_digest` cluster is the remaining substantive thread — but the substance
left is **verification + reconciliation + prod smoke**, not greenfield engineering.

---

## Per-bug breakdown

> **Source of truth for all four: `docs/notes/BUG_LOG.md` § BUG-031 / § BUG-032 /
> § BUG-033 / § BUG-034 — read each in full.** All four were filed 2026-05-24 during the
> VPS watch OP-2 / OP-3 interactive tests (see
> `docs/notes/WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md` § T+10h45m). They form a cluster
> because Test C + Test D exercised the same `subscribe_digest` NL → FSM → executor path.
> **Shared scaffolding** = the Session D FSM `ConfirmFlow` machinery (BUG-002) + the
> `_exec_subscribe_digest` executor; this is why PRs #108/#109/#111 are tightly coupled and
> touch the same two files (`tg_parser/bot/handlers.py`, `tg_parser/bot/tools.py`).

### BUG-033 — Critical — `chat_id=123` placeholder leak in group context
- **Symptom (Test D, ~21:10Z):** user in group `vps-watch-test-grp` (real chat_id
  `-5279672667`) said «Подпиши этот чат на ежечасный дайджест канала profendocrinologist» →
  bot emitted `subscribe_digest(target={kind:chat, chat_id:123}, …)`. `123` is undeliverable;
  every cron tick would `sendMessage(chat_id=123)` and orphan the digest.
- **Root cause (per merged PR #108):** the Gemini agent has **no factual access** to
  `Message.chat.id`; the v1.7.0 prompt told the LLM to "use the current chat_id from
  context" but the framework never injected it, so the LLM **hallucinated** `123`. There is
  **no** `chat_id=123` literal in the codebase (handoff "fixture-leak" hypothesis was wrong).
- **Fix as merged:** structural fix at the executor — `_resolve_target_for_bot_subscribe`
  treats the bot-context `Message.chat.id` as the source of truth for `kind=chat`, overriding
  any LLM-supplied `chat_id` (logs `subscribe_target_chat_id_overridden` on divergence).
  Applied symmetrically to `_exec_subscribe_digest` **and** `_exec_subscribe_watchlist`.
- **Spec:** `docs/notes/BUG_LOG.md` § BUG-033 (read in full). **Address first** — Critical.

### BUG-031 — Severe — subscription persisted BEFORE confirmation (preview/confirm inverted)
- **Symptom (Test C ~20:55Z + Test D ~21:10Z):** bot replied «📰 Подписка создана» **before**
  the «Подтвердите … [да/нет]» prompt; DB row already inserted. Violates the documented
  invariant («операции записи только после явного подтверждения»). Reproduced twice.
- **Root cause:** the write-tool was invoked without first arming the FSM `ConfirmFlow`
  preview gate (LLM bypass / missing membership in `_WRITE_TOOLS_REQUIRING_CONFIRM`).
- **Fix as merged (PR #111):** require explicit affirmative confirmation before subscribe
  side-effects — server-side hard-gate mirroring the BUG-009 MCP `execute_tool` pattern, so
  the bot is defensible against LLM contract violations, not reliant on LLM discipline.
- **Spec:** `docs/notes/BUG_LOG.md` § BUG-031 (read in full). **Shared root cause with 032.**

### BUG-032 — Medium — «да» / «подтверждаю» not parsed as confirmation
- **Symptom:** after the preview prompt, user «да» → bot «Я не совсем понимаю ваш ответ»;
  same for «подтверждаю» / «yes» / «ok». User stuck at the confirm step. Compounds BUG-031.
- **Root cause:** narrow confirmation whitelist (and/or the FSM was never armed per BUG-031,
  so the bare «да» fell through to the LLM loop).
- **Fix as merged (PR #111, bundled with BUG-031):** expanded affirmative/negative token
  whitelist (case-insensitive, punctuation-tolerant), typed return instead of the opaque
  catch-all. Fixing BUG-031 closes most of BUG-032 in the deployed sense; the whitelist
  expansion handles the rest.
- **Spec:** `docs/notes/BUG_LOG.md` § BUG-032 (read in full). **Companion of 031 — batched.**

### BUG-034 — Medium — channel-name typo with whitespace → wrong `channel_ids`
- **Symptom (Test D ~21:11Z):** user typed «pro fendocrinologist» (space typo for
  `profendocrinologist`) → bot stored `channel_ids=["pro_fendocrinologist"]` (space→underscore),
  a non-existent username → silently undeliverable subscription.
- **Root cause:** space→underscore normalization (LLM- or code-side) produced an invalid
  username, and the executor did not pre-validate channel existence.
- **Fix as merged (PR #109):** in `_exec_subscribe_digest`, pre-validate each `channel_id`
  against the Telegram username spec and reject space-as-underscore; coordinate with the
  BUG-010 `get_source_by_username` resolution path.
- **Spec:** `docs/notes/BUG_LOG.md` § BUG-034 (read in full). **Companion of 033 (both Test D).**

**Ordering / dependencies:** BUG-033 (Critical) first. BUG-031 + BUG-032 share the FSM
`ConfirmFlow` surface and are batched. BUG-033 + BUG-034 share `_exec_subscribe_digest` /
the Test D trace and are batched. All four touch the same two files, so verification can be
done together; reconcile statuses in one BUG_LOG edit.

---

## Suggested approach & order (verification-first; re-implement only if needed)

0. **Confirm baseline.** `git checkout main && git pull --ff-only origin main`;
   `git rev-parse HEAD`; run the targeted suites (below) to confirm green on current `main`.
1. **BUG-033 first** (Critical). Read `_resolve_target_for_bot_subscribe` +
   `_exec_subscribe_digest` and confirm the group-context override; run
   `tests/test_bot_chat_target_resolution.py`. Confirm the original trace
   (`target.chat_id=123` from group `-5279672667`) can no longer materialize.
2. **BUG-031 + BUG-032** (batched — shared `ConfirmFlow` surface). Read
   `_handle_confirmation_response` + the confirm/reject classifier + the
   `_WRITE_TOOLS_REQUIRING_CONFIRM` gate; run `tests/test_bot_confirm_flow.py`. Confirm
   preview precedes DB insert, and «да»/«подтверждаю»/«yes»/«ok» are accepted.
3. **BUG-034** (batched with 033 — shared `_exec_subscribe_digest` / Test D). Read the
   channel pre-validation; run `tests/test_bot_channel_name_parser.py`. Confirm
   «pro fendocrinologist» is rejected, not silently underscored.
4. **Reconcile `BUG_LOG.md`** statuses for all four → resolved (PR# + commit-SHA + note),
   mirroring the `121e833` reconciliation style for BUG-029/030/035.
5. **Production real-fire smoke** in a real Telegram group. **Deploy-gated, NOT bug-gated:**
   the fixes are on `main` but prod was at `39b6ba2` with the `656f23c` deploy **pending**
   (same operator blocker as BUG-038). Confirm the deployed SHA contains
   `e50449b` / `6ebad33` / `66e8297` FIRST — if prod is behind `main`, a smoke "failure"
   means *not deployed*, not *regressed*; in that case finish steps 0–4 now and let the smoke
   ride the pending deploy.
6. **Only if a residual gap is found:** open a new `BUG-NNN`, fix on a fresh branch, follow
   the per-bug "fix as merged" designs above as the baseline.

---

## Key code entry points (verified against `main` @ `121e833`)

**Bot FSM / confirm flow**
- `tg_parser/bot/states.py` — `ConfirmFlow` (≈L33), `PaginationFlow`, `ReadContextData`.
- `tg_parser/bot/handlers.py` — `handle_text` (≈L327, routes `ConfirmFlow.awaiting_confirmation`);
  `_handle_confirmation_response` (≈L420, deterministic yes/no); confirm/reject classifier
  (≈L167) + `CONFIRM_*`/`REJECT_*` regex (≈L68); arms `ConfirmFlow.awaiting_confirmation` (≈L392).
- `tg_parser/bot/agent.py` — `AgentResult` (≈L88, structured result that drives the FSM transition).
- `tg_parser/bot/main.py` — `MemoryStorage` wired into the `Dispatcher` (≈L240).

**Confirm gate + subscribe executor (BUG-031/032/033/034 fix surface)**
- `tg_parser/bot/tools.py`:
  - `_TOOLS_NEEDING_BOT_CONTEXT` (≈L32), `_WRITE_TOOLS_REQUIRING_CONFIRM` (≈L51),
    `ConfirmFlowSnapshot` (≈L92).
  - `execute_tool` confirm-guard (≈L898–991; bot-context injection ≈L1002;
    `error_class="ConfirmFlowMismatch"`).
  - `_resolve_target_for_bot_subscribe` (≈L2391) — **BUG-033 fix** (chat_id from context).
  - `_exec_subscribe_digest` (≈L2479) — **BUG-034** channel pre-validation (≈L2548; see also
    ≈L1757) + BUG-033 target resolution.
  - `_exec_subscribe_watchlist` (symmetric BUG-033 fix; BUG-034 note ≈L2932).
  - dispatch table maps `"subscribe_digest" → _exec_subscribe_digest` (≈L3234).

**MCP server (API surface — defense-in-depth)**
- `tg_parser/mcp_server.py` — `subscribe_digest` tool (≈L2532); `get_source_by_username`
  resolution (≈L1392); MCP-side cron pre-validate (≈L2655). Check whether BUG-034 Layer C
  (server-side channel validation) was applied here or is a residual gap.

**Tests (run these to verify)**
- `tests/test_bot_chat_target_resolution.py` — BUG-033 (30 tests; helper unit + e2e).
- `tests/test_bot_channel_name_parser.py` — BUG-034.
- `tests/test_bot_confirm_flow.py` — BUG-031 / BUG-032.
- `tests/test_bot_fsm.py` — FSM `ConfirmFlow` / `PaginationFlow` scaffolding (BUG-002/004).
- `tests/test_subscribe_legacy_chat_id.py`, `tests/test_subscribe_idempotency.py`,
  `tests/test_f6_scheduled_digests.py`, `tests/test_api_digests.py` — adjacent digest surface.

**Merged PR bodies (detailed root-cause + test plan per bug)**
- `docs/notes/PR_BODY_BUG_033.md`, `docs/notes/PR_BODY_BUG_034.md`,
  `docs/notes/PR_BODY_BUG_031_032.md`.

---

## Hard constraints / conventions (from `AGENTS.md` — restated explicitly)

- **`main` branch.** Do real changes on a fresh `fix/...` branch; never commit straight to `main`.
- **Accepted ADRs in `docs/adr/` are mandatory** — esp. `docs/adr/0008-subscription-target-model.md`
  (polymorphic subscription target; the `kind=chat` / `kind=channel` surface these bugs live on).
- **JSON Schemas in `docs/contracts/` must not be violated.**
- **Quality lifecycle:** `docs/quality/AGENT_PLAYBOOK.md`. **Roles:** `docs/notes/agents-roles.md`.
- **`docs/notes/BUG_LOG.md` is the fix-session backbone** — source of truth; update it.
- **Forbidden actions:**
  - `git commit` **without explicit user request**.
  - Creating `docs/methodology/**` in this workspace (methodology lives in a separate worktree).
  - Direct edits to `pyproject.toml` / `requirements.txt` **without explicit user request**
    (if a fix needs a new dependency, flag it in the PR and wait for sign-off).

---

## Verification expectations

- **Targeted suites (fast):**
  ```bash
  .venv/bin/pytest tests/test_bot_chat_target_resolution.py \
                   tests/test_bot_confirm_flow.py \
                   tests/test_bot_channel_name_parser.py \
                   tests/test_bot_fsm.py -q
  ```
- **Full sweep before any new commit:** `.venv/bin/pytest -q 2>&1 | tail -20`
  (some Postgres-gated tests skip; `tests/test_api_digests.py` may show a pre-existing
  infra flake when Postgres is down — confirm it also fails on baseline before blaming a change).
- **Production real-fire smoke** (how BUG-037 was closed — see `HANDOFF_BUG037_2026-05-30.md`):
  confirm deployed SHA, then in a real Telegram group re-run Test C / Test D:
  1. «Подпиши этот чат на ежечасный дайджест канала <real_channel>» → expect a **preview
     first**, then «да» → subscription created with the **real** group `chat_id` (NOT `123`).
  2. «да» / «подтверждаю» / «yes» / «ok» all accepted at the confirm step.
  3. A channel name with an embedded space → bot asks to clarify / rejects, does **not**
     silently underscore it.
- **Quality lifecycle:** follow `docs/quality/AGENT_PLAYBOOK.md` (self-review-and-rerun loop;
  prove regressions fail on pre-fix code if you write new tests).
- **On closure:** reconcile `BUG_LOG.md` (statuses → resolved with PR#/SHA), and notify the
  operator with the verified SHA + which traces were confirmed closed.

---

## Paste-ready start prompt (copy into the new chat)

```text
Контекст: bot subscribe_digest / ConfirmFlow bug cluster — BUG-033 (Critical),
BUG-031 (Severe), BUG-032 (Medium), BUG-034 (Medium). Все четыре всплыли 2026-05-24
в Test C / Test D на VPS watch (Wave 1 Step 4). Source of truth: docs/notes/BUG_LOG.md
§ BUG-031 / 032 / 033 / 034 — прочитай КАЖДУЮ запись целиком. main HEAD = 121e833.

ВАЖНО — сначала сверь реальность, НЕ начинай "фиксить с нуля":
Код-фиксы всех четырёх багов УЖЕ слиты в main:
  - BUG-033 -> PR #108, commit e50449b
  - BUG-034 -> PR #109, commit 6ebad33
  - BUG-031 + BUG-032 -> PR #111, commit 66e8297
НО записи BUG_LOG.md для них всё ещё помечены Status: open (reconcile-коммит 121e833
обновил 029/030/035/037/038, а 031–034 пропустил). То есть осталась НЕ инженерная
доработка, а verification + reconciliation + прод-smoke.

Задача (порядок):
0. git checkout main && git pull --ff-only origin main; зафиксируй HEAD; прогон
   таргетных suites (зелёный baseline):
   .venv/bin/pytest tests/test_bot_chat_target_resolution.py \
     tests/test_bot_confirm_flow.py tests/test_bot_channel_name_parser.py \
     tests/test_bot_fsm.py -q
1. BUG-033 (Critical) — ПЕРВЫМ. Прочитай tg_parser/bot/tools.py
   _resolve_target_for_bot_subscribe (~L2391) + _exec_subscribe_digest (~L2479).
   Убедись, что chat_id берётся из Message.chat.id, а LLM-овский 123 не может попасть
   в БД. Прогон tests/test_bot_chat_target_resolution.py.
2. BUG-031 + BUG-032 (batched, общий ConfirmFlow). Прочитай handlers.py
   _handle_confirmation_response (~L420) + confirm/reject classifier (~L167) + гейт
   _WRITE_TOOLS_REQUIRING_CONFIRM (tools.py ~L51). Убедись: preview ДО insert,
   «да»/«подтверждаю»/«yes»/«ok» принимаются. Прогон tests/test_bot_confirm_flow.py.
3. BUG-034 (batched с 033). Прочитай channel pre-validation в _exec_subscribe_digest
   (~L2548). Убедись, что «pro fendocrinologist» отклоняется, а не превращается в
   pro_fendocrinologist. Прогон tests/test_bot_channel_name_parser.py.
4. Reconcile docs/notes/BUG_LOG.md: статусы BUG-031/032/033/034 -> resolved (PR# +
   commit-SHA + краткая resolution-заметка), в стиле reconcile-коммита 121e833 для
   029/030/035.
5. Прод real-fire smoke в реальной Telegram-группе (как закрывали BUG-037 —
   см. docs/notes/HANDOFF_BUG037_2026-05-30.md): СНАЧАЛА подтверди задеплоенный SHA
   (деплой может отставать от main!), потом повтори сценарии Test C / Test D:
   preview-then-confirm, реальный group chat_id (не 123), отклонение typo-канала.
6. Если найдёшь реальный остаточный gap (трасса всё ещё воспроизводится / не хватает
   слоя фикса) — заводи НОВЫЙ BUG-NNN и чини на свежей ветке; не патчь «закрытый» баг молча.

Жёсткие ограничения (AGENTS.md):
- Ветка main; работа в свежей fix/... ветке.
- git commit — ТОЛЬКО по моему явному запросу.
- Accepted ADR обязательны (особенно docs/adr/0008-subscription-target-model.md);
  JSON Schema в docs/contracts/ нарушать нельзя.
- НЕ создавать docs/methodology/**; НЕ править pyproject.toml / requirements.txt без
  моего явного разрешения.
- Quality lifecycle: docs/quality/AGENT_PLAYBOOK.md (self-review-and-rerun; новые тесты
  должны падать на pre-fix коде).

Справочно: подробные root-cause + test plan по каждому багу — в
docs/notes/PR_BODY_BUG_033.md, PR_BODY_BUG_034.md, PR_BODY_BUG_031_032.md.
```

---

## Key IDs & refs

| Item | Value |
|---|---|
| `main` HEAD (prep) | `121e833` (pushed) |
| BUG-033 fix | PR #108 / commit `e50449b` |
| BUG-034 fix | PR #109 / commit `6ebad33` |
| BUG-031 + BUG-032 fix | PR #111 / commit `66e8297` |
| Bot | `@Tgingest_bot` (id `8657845219`) |
| Test D group | `vps-watch-test-grp`, real chat_id `-5279672667` (placeholder leak was `123`) |
| Smoking-gun channel typo | «pro fendocrinologist» → wrong `pro_fendocrinologist` (real: `profendocrinologist`) |
| Specs | `docs/notes/BUG_LOG.md` § BUG-031 / 032 / 033 / 034 (read in full) |
| Original evidence | `docs/notes/WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md` § T+10h45m OP-2/OP-3 |
| Post-watch handoff | `docs/notes/HANDOFF_NEXT_CHAT_WAVE1_STEP4_POST_WATCH_2026-05-25.md` |
| Real-fire-verification precedent | `docs/notes/HANDOFF_BUG037_2026-05-30.md` |
| Relevant ADR | `docs/adr/0008-subscription-target-model.md` |
