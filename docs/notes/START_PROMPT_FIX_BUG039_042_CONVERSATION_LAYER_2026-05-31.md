# START PROMPT — bot conversational-layer bug cluster (BUG-039 Severe + BUG-040 Severe + BUG-041 Medium + BUG-042 Minor)

**Prepared:** 2026-05-31. **Repo:** `/Users/alexanderefimov/TG_parser`. **Branch:** `main`.
**`main` HEAD at prep time:** `658be87` (pre-PR). **Note:** the doc-PR that introduces these notes
(`docs/smoke-results-bug039-042-startprompt`) adds three files only — this start prompt,
the BUG-039..042 entries in `BUG_LOG.md`, and the `SMOKE_TEST … § Results 2026-05-31` section.
Once that PR merges, `main` HEAD will move past `658be87`; re-run `git rev-parse HEAD` after
`git pull --ff-only` to anchor your baseline. **No code changed in the doc-PR.**

**Post-merge update:** `main` HEAD is now `473eed3` — PR #152 merged, so this start prompt, the
BUG-039..042 entries, and the smoke `Results 2026-05-31` section are ALREADY committed on `main`.
Re-anchor with `git pull --ff-only origin main` then `git rev-parse HEAD`.

**Purpose:** fix the four NEW conversational-layer defects — **BUG-039 (Severe)**,
**BUG-040 (Severe)**, **BUG-041 (Medium)**, **BUG-042 (Minor)** — that surfaced during the
2026-05-31 production real-fire smoke of the (now-closed) BUG-031/032/033/034 `subscribe_digest`
cluster. This document is fully self-contained: the next agent starts in a fresh window with no
access to the chat that produced it.

---

## ⚠️ READ THIS FIRST — these are NEW residual gaps, not regressions

The BUG-031/032/033/034 cluster is **closed and real-fire verified**. On 2026-05-31 a human
operator ran the smoke runbook (`docs/notes/SMOKE_TEST_BUG031_034_2026-05-30.md`) in the real
Telegram group `vps-watch-test-grp` (chat_id `-5279672667`) against bot `@Tgingest_bot`, with the
prod container **provably fresh on SHA `39b6ba2`** (the deploy was already confirmed, not pending).
All four original traces were observed closed (preview-before-write, affirmative tokens accepted,
embedded-space channel name rejected, real group chat_id bound — BUG-033 verified via live
`list_digests` chat_id `-5279672667`).

**Because the deploy was confirmed fresh, the four issues below are genuine residual gaps in the
shipped code — NOT stale-deploy artifacts and NOT regressions.** They live one layer up from the
fixed executor: in the **conversational / clarification layer** (the bot agent loop + FSM routing),
which the original cluster never touched.

**This session IS a fix-from-(near)-scratch engineering session** (unlike the BUG-033 cluster
start prompt, which was verification-only). The root causes are already code-traced (HIGH
confidence) and summarized below, but no fix code exists yet.

**Source of truth (read each in full before coding):**
- `docs/notes/BUG_LOG.md` § **BUG-039 / BUG-040 / BUG-041 / BUG-042** — full root-cause + suggested-fix
  entries (filed 2026-05-31).
- `docs/notes/SMOKE_TEST_BUG031_034_2026-05-30.md` § **Results 2026-05-31** — the real-fire transcript
  evidence (PASS verdicts on the original cluster + the new-bug table with timestamps).

---

## Current state table

| Item | Status |
|---|---|
| `main` HEAD (prep) | `658be87` (pre-PR; doc-PR `docs/smoke-results-bug039-042-startprompt` adds these notes) |
| BUG-031 / 032 / 033 / 034 — code | ✅ merged & **real-fire verified 2026-05-31** on prod `39b6ba2` |
| Prod deployed SHA at smoke time | `39b6ba2` (confirmed fresh — contains all four cluster fixes) |
| BUG-039 (Severe) — clarification dead-end + opaque fallback | ⛔ open (this session) |
| BUG-040 (Severe) — stateless agent misroutes bare channel name | ⛔ open (this session) |
| BUG-041 (Medium) — LLM strips space upstream of the guard | ⛔ open (this session) |
| BUG-042 (Minor) — LLM-paraphrased preview truncates cron | ⛔ open (this session) |

---

## Common thread — READ THIS BEFORE PICKING A FIX

Three of the four (039 / 040 / 042) share two systemic roots:

1. **The bot agent is stateless across turns.** `GeminiAgent.process_message` rebuilds `contents`
   fresh on every call as `[{"role": "user", "parts": [{"text": user_message}]}]`
   (`tg_parser/bot/agent.py:181-183`) — no prior user/model turns are carried. The ONLY cross-turn
   memory today is (a) the FSM states `ConfirmFlow` / `PaginationFlow`
   (`tg_parser/bot/handlers.py:325-337`) and (b) the read-side `read_context` last-`channel_id` hint
   injected into the system prompt (`tg_parser/bot/agent.py:377-392`). Neither covers a mid-subscribe
   clarification. So a bare reply («да», a channel name) reaches Gemini with no anchoring context.

2. **Preview / clarification text is LLM-authored, not deterministic.** The tool returns a correct
   structured `message`, but it goes back to the agent loop as a `functionResponse`
   (`tg_parser/bot/agent.py:330-337`) and the user-facing text is **re-authored by Gemini**
   (`tg_parser/bot/agent.py:267-275` → `tg_parser/bot/handlers.py:376-381`). That paraphrase layer is
   where the cron got truncated (BUG-042) and where the clarification carries no FSM state (BUG-039).

**A coherent fix likely centers on:** (1) carrying short conversational context and/or arming an
explicit clarify/confirm FSM on clarification prompts (closes 039 + 040 together); and (2) making
preview/confirmation text deterministic (send the tool's own `message` verbatim / template-render)
rather than LLM-paraphrased (closes 042, hardens the preview surface). **Evaluate fixing 039/040/042
together** under one statefulness+determinism change. BUG-041 is a prompt-hardening + defense-in-depth
guard task that rides alongside.

---

## Per-bug breakdown

> Source of truth for all four: `docs/notes/BUG_LOG.md` § BUG-039 / 040 / 041 / 042 — read each in
> full. Evidence transcript: `docs/notes/SMOKE_TEST_BUG031_034_2026-05-30.md` § Results 2026-05-31.
> All four were filed 2026-05-31 from the same real-fire smoke in group `vps-watch-test-grp`
> (chat_id `-5279672667`) against prod SHA `39b6ba2`.

### BUG-039 — Severe — channel-name clarification is a dead-end; the opaque «не совсем понимаю» resurfaces
- **Trace (real-fire):** 23:49:52 bot «Канал «pro fendocrinologist» содержит пробелы … Возможно, вы
  имели в виду «profendocrinologist»?» → 23:50:03 user «да» → 23:50:04 bot «Я не совсем понимаю ваш
  ответ. Пожалуйста, переформулируйте ваш запрос…» (repeated 23:52:11 / 23:52:23).
- **Root cause:** the BUG-034 clarification («…содержит пробелы… Возможно, вы имели в виду X?») is
  returned as a tool **error** (`error_class="InvalidChannelUsername"` + `suggestion`,
  `tg_parser/utils/channel_id.py:181-195`; returned verbatim by `_exec_subscribe_digest` at
  `tg_parser/bot/tools.py:2556-2558`), **not** a `{"preview": True}`. Because it's an error, the agent
  loop never sets `preview_pending` (`tg_parser/bot/agent.py:306-319`), so the handler never arms
  `ConfirmFlow.awaiting_confirmation` (`tg_parser/bot/handlers.py:391-392`). The user's «да» then
  arrives with `current_state is None` (`tg_parser/bot/handlers.py:325-331`), bypasses
  `classify_confirmation_token` (scoped strictly to `ConfirmFlow.awaiting_confirmation` —
  `tg_parser/bot/handlers.py:329, 445`), hits a stateless LLM turn (`tg_parser/bot/agent.py:181-183`),
  and returns the opaque «Я не совсем понимаю ваш ответ» — note this phrase now originates LLM-side:
  the deterministic code path that used to emit it was removed by the BUG-032 fix, and the phrase
  survives only as the closure example at `prompts/bot.yaml:48` / `handlers.py:502-517`. Net: the
  suggestion is a dead-end and the opaque message BUG-032 tried to kill resurfaces on this surface.
- **Impact:** user cannot recover from a single channel-name typo inside the flow — the exact UX
  failure BUG-032 was filed to eliminate, re-exposed on the clarification surface.

### BUG-040 — Severe — bare channel-name reply mid-flow routed to the WRONG intent, non-deterministically
- **Trace (real-fire):** 23:50:31 user «profendocrinologist» → 23:50:32 bot «Подтвердите, пожалуйста,
  обновление канала profendocrinologist…» (mis-routed to **`update_channel`** preview); 23:53:05 user
  «profendocrinologist» → 23:53:13 bot «Показываю топ-20 тем канала profendocrinologist…» (mis-routed
  to **`list_topics`**). Identical input, two different intents.
- **Root cause:** `process_message` is stateless across messages — `contents` is rebuilt fresh each
  call with no history (`tg_parser/bot/agent.py:181-183`); cross-turn memory is only FSM states +
  read-side `read_context` (`tg_parser/bot/agent.py:377-392`), neither covering a mid-subscribe
  clarification (see BUG-039 — no FSM armed). A bare «profendocrinologist» reaches Gemini context-free
  under `functionCallingConfig.mode="AUTO"` (`tg_parser/bot/agent.py:398-400`) at `temperature=0.2`,
  so the guessed intent is non-deterministic. `read_context` can even bias toward `list_topics`.
- **Impact:** mid-flow replies are silently misclassified, including into a write-intent preview
  (`update_channel`). Still confirm-gated (no unconfirmed side effect occurred), so impact is
  correctness-of-intent + UX, not data loss — but Severe because the root cause is a **systemic**
  absence of conversational context, shared with BUG-039.

### BUG-041 — Medium — deterministic BUG-034 space-guard is bypassable (LLM strips the space upstream)
- **Trace (real-fire):** «pro fendocrinologist» **rejected** for the space at 23:49:52 / 23:51:54 /
  23:52:39 (correct guard), but the **identical** input produced a direct `profendocrinologist`
  preview at 23:53:37 / 23:54:09 (silently auto-corrected, no clarification).
- **Root cause (LLM-side, not code-side):** `channel_ids` comes from Gemini's `functionCall.args`
  (`tg_parser/bot/agent.py:283, 296-303`), validated only at `tg_parser/bot/tools.py:2554-2560`. When
  the model passes the literal `["pro fendocrinologist"]`, the validator sees the space and rejects
  (`tg_parser/utils/channel_id.py:181-195`) — correct. But Gemini frequently **pre-normalizes** to
  `["profendocrinologist"]` before emitting the call, so the validator never sees a space and a preview
  shows. Sampling (`temperature=0.2`, stateless per BUG-040) makes whether the space survives
  non-deterministic. The code guard is correct but **bypassable upstream**.
- **Impact:** Medium — the deterministic guarantee BUG-034 advertises is actually probabilistic. A
  different typo the LLM "corrects" to a *wrong* valid-looking username would bypass the guard
  silently. No bad persistence observed in this smoke (the correction matched the intended channel).

### BUG-042 — Minor — preview cron truncated to «0» (LLM-paraphrased preview); creation message is correct
- **Trace (real-fire):** preview rendered «по расписанию `0     (Europe/Moscow)`» (just "0") while the
  post-confirmation creation message correctly showed «Расписание: 0 * * * *».
- **Root cause:** the preview tool returns a correct full `message` (`tg_parser/bot/tools.py:2635-2639`)
  but it goes back as a `functionResponse` (`tg_parser/bot/agent.py:330-337`); the user-facing preview
  text is **re-authored by Gemini** (`tg_parser/bot/agent.py:267-275` → `tg_parser/bot/handlers.py:376-381`),
  which truncated «0 * * * *» to «0». The creation confirmation is emitted deterministically by code
  (`tg_parser/bot/tools.py:2704-2713`), bypassing the LLM, so it's correct; the stored cron is fine.
- **Impact:** Minor / cosmetic — the previewed schedule is misleading but the created subscription uses
  the correct expression. No correctness impact on the stored row or delivery cadence.

---

## Suggested approach & order

> Fix-from-scratch (no fix code exists yet). Root causes are code-traced; confirm them yourself by
> reading the entry points, then write failing regression tests FIRST (must fail on pre-fix code).

0. **Baseline.** `git checkout main && git pull --ff-only origin main`; `git rev-parse HEAD`; create a
   fresh `fix/...` branch. Run the existing bot suites green (below). Read all four BUG_LOG entries +
   the smoke Results section in full.
1. **Tackle the shared statefulness + determinism first (underlies 039 / 040 / 042).** Decide between
   (a) arming a clarify/confirm FSM when `validate_channel_username` returns a `suggestion` (mirror the
   BUG-002 / BUG-031 FSM-arming pattern) so an affirmative «да» re-runs the previewed `subscribe_digest`
   with the corrected channel id; and/or (b) introducing bounded conversational memory (carry the last
   N user/model turns into `contents`, or a structured "active intent" hint). A single FSM/context
   mechanism should close **BUG-039 and BUG-040** together. Keep all write-intent routing defensible
   server-side — do not rely on LLM discipline.
2. **Make the preview surface deterministic (BUG-042, and hardens 039).** Send the preview using the
   tool's own `message` field verbatim (the way the creation confirmation is already sent at
   `tg_parser/bot/tools.py:2704-2713`), or render the cron inside `<code>…</code>` / a pre-formatted
   human label so the LLM cannot drop fields. This removes the LLM-paraphrase layer that both truncated
   the cron and stripped FSM state.
3. **Harden the channel-name guard (BUG-041).** Add a hard rule in `prompts/bot.yaml`
   channel-resolution forbidding the LLM from normalising/guessing channel names (pass the user token
   verbatim; never strip embedded whitespace) so the deterministic validator always adjudicates. Add
   defense-in-depth: have the executor verify channel existence via `get_source_by_username` (BUG-010
   pattern) so an LLM-"corrected" but non-existent channel is still rejected.
4. **Reconcile `BUG_LOG.md`** statuses for the bugs you close → resolved (PR# + commit-SHA + short
   resolution note), mirroring prior reconcile style.
5. **Production real-fire smoke** (mirror the BUG-037 / BUG-031..034 precedent): confirm deployed SHA,
   then in the real group re-run the 039/040/041/042 traces (clarification «да» now actionable; bare
   channel name retained in-flow; «pro fendocrinologist» deterministically rejected; preview cron shows
   the full expression).

---

## Key code entry points (consolidated — verify against your post-pull HEAD; line numbers ~)

**Bot agent loop — `tg_parser/bot/agent.py`**
- `process_message` statelessness — `contents` rebuilt fresh each call, no history — **L181-183** (root of 039 + 040).
- tool args come straight from the model `functionCall.args` — **L283, L296-303** (041).
- `preview_pending` set only on `{"preview": True}`, not on error — **L306-319** (039).
- `functionResponse` loop — tool `message` returned to the model, not sent verbatim — **L330-337** (042).
- LLM re-authors the user-facing text — **L267-275** (042, 039).
- read-side `read_context` hint injected into system prompt — **L377-392** (040 bias).
- `functionCallingConfig.mode="AUTO"` — context-free intent guessing — **L398-400** (040).

**Bot handlers / FSM routing — `tg_parser/bot/handlers.py`**
- `handle_text` routing; `current_state is None` falls through to stateless LLM — **L325-331** (039).
- `classify_confirmation_token` scoped to `ConfirmFlow.awaiting_confirmation` — **L329, L445** (039).
- preview/clarification rendered from LLM text — **L376-381** (042, 039).
- arms `ConfirmFlow.awaiting_confirmation` (only on a real preview) — **L391-392** (039).

**Subscribe executor / validation — `tg_parser/bot/tools.py`**
- channel-id validation in `_exec_subscribe_digest` — **L2554-2560** (041; clarification error returned at L2556-2558, 039).
- preview `message` (correct full string, but LLM-paraphrased downstream) — **L2635-2639** (042).
- deterministic creation confirmation via `bot.send_message` (the determinism template to copy) — **L2704-2713** (042).

**Username validator — `tg_parser/utils/channel_id.py`**
- `validate_channel_username` — space rejection + `suggestion` — **L181-195** (039, 041).

**Prompt — `prompts/bot.yaml`**
- opaque «Я не совсем понимаю ваш ответ» fallback — **L48** (039); channel-resolution hardening target (041).

---

## Hard constraints / conventions (from `AGENTS.md` — restated explicitly)

- **`main` branch.** Do real changes on a fresh `fix/...` branch; **never commit straight to `main`**.
- **`git commit` only on explicit user request.**
- **New regression tests MUST fail on pre-fix code** (prove the trace reproduces before the fix), per
  `docs/quality/AGENT_PLAYBOOK.md` (self-review-and-rerun loop).
- **Accepted ADRs in `docs/adr/` are mandatory** — esp. `docs/adr/0008-subscription-target-model.md`
  (the `subscribe_digest` target surface these bugs sit on).
- **JSON Schemas in `docs/contracts/` must not be violated.**
- **`docs/notes/BUG_LOG.md` is the fix-session backbone** — source of truth; reconcile it on closure.
- **Forbidden:** creating `docs/methodology/**` in this workspace (methodology lives in a separate
  worktree); direct edits to `pyproject.toml` / `requirements.txt` without explicit user request
  (flag any new dependency in the PR and wait for sign-off); force-push.

---

## Verification expectations

- **New regression tests reproducing each trace (must fail on pre-fix code):**
  - **BUG-039** — clarification «да» is actionable: after a space-typo clarification, a follow-up «да»
    re-runs the subscribe with the suggested channel (no opaque «не совсем понимаю»).
  - **BUG-040** — bare-channel-name context retention: a bare channel token mid-subscribe is interpreted
    within the in-flight subscribe flow, not re-classified to `update_channel` / `list_topics`.
  - **BUG-041** — deterministic space rejection: «pro fendocrinologist» is rejected regardless of LLM
    normalisation (test the guard + the prompt rule + the existence-check defense-in-depth).
  - **BUG-042** — deterministic preview cron: the preview renders the full `0 * * * *` (assert the tool
    `message` is sent verbatim / cron not truncated).
- **Targeted bot suites (run green first, then with new tests):**
  ```bash
  .venv/bin/pytest tests/test_bot_confirm_flow.py \
                   tests/test_bot_channel_name_parser.py \
                   tests/test_bot_chat_target_resolution.py \
                   tests/test_bot_fsm.py -q
  ```
- **Full sweep before any new commit:** `.venv/bin/pytest -q 2>&1 | tail -20` (some Postgres-gated tests
  skip; confirm any failure also fails on baseline before blaming a change).
- **Production real-fire smoke** (mirror `docs/notes/HANDOFF_BUG037_2026-05-30.md` + the
  BUG-031..034 runbook): confirm deployed SHA, then re-run the four traces in the real group.
- **On closure:** reconcile `BUG_LOG.md` (statuses → resolved with PR#/SHA + note), notify the operator
  with the verified SHA + which traces were confirmed closed.

---

## Paste-ready start prompt (copy into the new chat)

```text
Контекст: НОВЫЙ кластер багов разговорного слоя бота — BUG-039 (Severe), BUG-040 (Severe),
BUG-041 (Medium), BUG-042 (Minor). Всплыли 2026-05-31 во время прод real-fire smoke уже
ЗАКРЫТОГО кластера BUG-031/032/033/034 (subscribe_digest / ConfirmFlow). Деплой был
подтверждённо свежий на проде SHA 39b6ba2 — значит это РЕАЛЬНЫЕ остаточные пробелы, НЕ
регрессии. Source of truth: docs/notes/BUG_LOG.md § BUG-039 / 040 / 041 / 042 (прочитай
КАЖДУЮ запись целиком) + docs/notes/SMOKE_TEST_BUG031_034_2026-05-30.md § Results 2026-05-31
(транскрипт-улики с таймстампами). Полный self-contained брифинг:
docs/notes/START_PROMPT_FIX_BUG039_042_CONVERSATION_LAYER_2026-05-31.md.

Это ИНЖЕНЕРНАЯ сессия фикса с нуля (фикс-кода ещё нет; root-cause уже code-traced).

Общий корень (важно): 039/040/042 — следствие двух системных проблем:
  (1) агент бота СТЕЙТЛЕСС между сообщениями — process_message каждый раз пересобирает
      contents с нуля, истории нет (tg_parser/bot/agent.py:181-183); межтёрновая память
      только через FSM (ConfirmFlow/PaginationFlow, handlers.py:325-337) и read_context
      (agent.py:377-392), а они не покрывают clarification внутри subscribe;
  (2) текст preview/clarification РЕ-АВТОРИТСЯ LLM-ом (tool message -> functionResponse
      agent.py:330-337 -> LLM-текст agent.py:267-275 -> handlers.py:376-381), а не
      детерминирован.

Порядок:
0. git checkout main && git pull --ff-only origin main; зафиксируй HEAD; свежая fix/... ветка;
   прогон bot-suites зелёным:
   .venv/bin/pytest tests/test_bot_confirm_flow.py tests/test_bot_channel_name_parser.py \
     tests/test_bot_chat_target_resolution.py tests/test_bot_fsm.py -q
1. Сначала общий стейт+детерминизм (BUG-039 + BUG-040 вместе). Когда validate_channel_username
   возвращает suggestion (channel_id.py:181-195; tools.py:2556-2558), это сейчас ERROR, не
   {"preview": True} -> preview_pending не ставится (agent.py:306-319), ConfirmFlow не
   армится (handlers.py:391-392), «да» приходит с current_state is None (handlers.py:325-331),
   минует classify_confirmation_token (handlers.py:329,445) и падает в стейтлесс-LLM
   (agent.py:181-183) -> опять «Я не совсем понимаю» (prompts/bot.yaml:48). Заведи
   clarify/confirm FSM (паттерн BUG-002/BUG-031) и/или ограниченную conversational memory,
   чтобы «да» переисполняло subscribe с подсказанным каналом, а голый «profendocrinologist»
   трактовался внутри активного flow (не уезжал в update_channel/list_topics через
   mode="AUTO" agent.py:398-400). Роутинг write-интентов держать серверно.
2. Детерминированный preview (BUG-042): отправлять preview из tool message ВЕРБАТИМ (как уже
   делает creation-сообщение tools.py:2704-2713) либо рендерить cron в <code>…</code>, чтобы
   LLM не обрезал «0 * * * *» до «0». (message формируется в tools.py:2635-2639.)
3. Харднинг guard'а (BUG-041): жёсткое правило в prompts/bot.yaml — LLM НЕ нормализует/не
   угадывает имя канала (передаёт токен дословно, не срезает пробелы), чтобы детерминированный
   валидатор всегда отрабатывал (channel_ids приходит из functionCall.args agent.py:283,
   296-303; валидируется tools.py:2554-2560). Defense-in-depth: проверка существования через
   get_source_by_username (паттерн BUG-010).
4. Reconcile docs/notes/BUG_LOG.md: статусы закрытых -> resolved (PR# + commit-SHA + заметка).
5. Прод real-fire smoke в реальной группе (как закрывали BUG-037 / BUG-031..034): подтверди
   задеплоенный SHA, повтори 4 трассы.

Жёсткие ограничения (AGENTS.md):
- Ветка main; работа в свежей fix/... ветке; git commit — ТОЛЬКО по моему явному запросу.
- Новые регресс-тесты ДОЛЖНЫ падать на pre-fix коде (docs/quality/AGENT_PLAYBOOK.md).
- Accepted ADR обязательны (особенно docs/adr/0008-subscription-target-model.md);
  JSON Schema в docs/contracts/ нарушать нельзя.
- НЕ создавать docs/methodology/**; НЕ править pyproject.toml / requirements.txt без явного
  разрешения; без force-push.

Справочно: бот @Tgingest_bot (id 8657845219); тест-группа vps-watch-test-grp chat_id
-5279672667; реальный канал profendocrinologist; typo «pro fendocrinologist».
```

---

## Key IDs & refs

| Item | Value |
|---|---|
| `main` HEAD (prep, pre-PR) | `658be87` |
| Prod deployed SHA at smoke time | `39b6ba2` (confirmed fresh; contains the BUG-031..034 fixes) |
| Bot | `@Tgingest_bot` (id `8657845219`) |
| Test group | `vps-watch-test-grp`, real chat_id `-5279672667` |
| Real channel | `profendocrinologist` |
| Smoking-gun typo | «pro fendocrinologist» (embedded space) → wrong `pro_fendocrinologist` |
| BUG-039 (Severe) | `docs/notes/BUG_LOG.md` § BUG-039 — clarification dead-end + opaque fallback resurfaces |
| BUG-040 (Severe) | `docs/notes/BUG_LOG.md` § BUG-040 — stateless agent misroutes bare channel name |
| BUG-041 (Medium) | `docs/notes/BUG_LOG.md` § BUG-041 — LLM strips space upstream of the guard |
| BUG-042 (Minor) | `docs/notes/BUG_LOG.md` § BUG-042 — LLM-paraphrased preview truncates cron |
| Smoke runbook | `docs/notes/SMOKE_TEST_BUG031_034_2026-05-30.md` |
| Smoke results (evidence) | `docs/notes/SMOKE_TEST_BUG031_034_2026-05-30.md` § Results 2026-05-31 |
| Closed precursor cluster | `docs/notes/BUG_LOG.md` § BUG-031 / 032 / 033 / 034 (resolved, real-fire verified) |
| Closure precedent (real-fire) | `docs/notes/HANDOFF_BUG037_2026-05-30.md` |
| Cluster start-prompt precedent (gold standard) | `docs/notes/START_PROMPT_FIX_BUG033_CLUSTER_2026-05-30.md` |
| Relevant ADR | `docs/adr/0008-subscription-target-model.md` |
| FSM-arming precedent | BUG-002 (`ConfirmFlow`); BUG-031 (confirm-gate) |
| Defense-in-depth precedent | BUG-010 (`get_source_by_username` existence check) |
