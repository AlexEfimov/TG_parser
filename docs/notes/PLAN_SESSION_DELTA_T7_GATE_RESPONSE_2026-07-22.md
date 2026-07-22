# Plan — Session δ: T7 gate response (keep-14 vs bump)

**Дата:** 2026-07-22 · **Тип:** ops planning note (pre-START_PROMPT) · **Branch:** `docs/delta-t7-start-prompt` (docs-only; commit/PR — только по явному запросу)

**Goal (одной строкой):** закрыть karpathy-петлю T7 — после полного +48h watch решить **keep `RESUMMARIZE_MAX_AGE_DAYS=14`** или **bump → 21/30**, задокументировать вердикт и обновить ops-доки.

---

## 1. Evidence (live + watch milestones)

| Milestone | When (Cyprus EEST) | Status |
|---|---|---|
| Knob LIVE `=14` | 2026-07-19 23:36 | ✅ |
| +24h watch min | 2026-07-20 23:36 | ✅ passed |
| +48h watch full | 2026-07-21 23:36 | ✅ passed |
| Alert `pending → firing` | ≈ 2026-07-21 03:37 | ✅ firing since |

**Prior snapshot (2026-07-21 ~21:44Z):** `ratio14d≈0.984`, alert **firing**, tokens ~303k prompt + ~40k completion / 24h; age triggers dominate (`mediamedics`, `Docma_ru`, `labdiagnostica_logical`, …).

**Fresh read-only prod (2026-07-22T14:51:51Z):**

| Signal | Value |
|---|---|
| `RESUMMARIZE_MAX_AGE_DAYS` (OS-env) | `14` |
| `tg_parser` StartedAt | `2026-07-19T20:35:59Z` (unchanged) |
| `tg:resummarize_age_trigger:ratio14d` | **0.989** |
| `ResummarizeAgeTriggerGateF5CPhase2` | **firing** (`severity=info`) |
| Age triggers / 24h | `labdiagnostica_logical`≈24, `mediamedics`≈11, `profendocrinologist`≈1; counter≈0 |
| Tokens / 24h (all channels) | ~52.9k prompt + ~8.5k completion |

**Interpretation:** Gate criterion met decisively — age-ветка даёт ~99% re-summarize mix за trailing 14d. Alert firing >12h через полное watch-окно. Cost снизился vs пик 2026-07-21 (backlog частично переварен), но остаётся ops-значимым на `mediamedics`; не инцидент, а сигнал удлинить cutoff per runbook §T7 / ADR-0006 #6.

---

## 2. Decision matrix — keep-14 vs 21 vs 30

| Option | When | Pros | Cons |
|---|---|---|---|
| **Keep 14** | `ratio14d` стабильно <0.5, alert green/pending кратко, cost negligible | Минимальная freshness latency | **Не соответствует текущим данным** (0.989, firing) |
| **Bump → 21** | `ratio14d≥0.5` устойчиво + cost acceptable + owner GO | Консервативный шаг (+50% cutoff); снижает age-share без kill-switch; rollback trivial | Может потребовать повторной оценки через 7–14d |
| **Bump → 30** | Aggressive cost cut OR 21 still red после watch | Максимально режет age-триггеры | Слабее alignment с #15 «>14 days» stale detector; bigger freshness gap |

**Planning verdict (default recommendation for session):** **bump `14 → 21`** при in-session owner GO.

**Rationale:**
1. Hard gate +48h watch complete — δ unblocked.
2. `ratio14d≈0.99` и alert **firing** — не marginal 0.503 как 2026-07-20.
3. Несколько каналов age-dominated (не один `labdiagnostica_logical`).
4. Cost приемлем (`gpt-4o-mini`, ~$0.x/day scale) но gate по дизайну = «оценить knob», не «терпеть red forever».
5. **21** — conservative default per DRAFT §2 δ и runbook; **30** — только если owner явно хочет aggressive cut или post-21 re-watch still red.

**Keep-14** — только если fresh re-snapshot в начале δ-сессии покажет sustained `<0.5` **и** alert cleared (маловероятно по текущим данным).

---

## 3. Session steps (execution outline)

1. **Re-snapshot (read-only)** — promtool queries из [`C2_T7_LIVE_SNAPSHOT_2026-07-20.md`](C2_T7_LIVE_SNAPSHOT_2026-07-20.md); зафиксировать timestamp + таблицу.
2. **Owner-aligned recommendation** — one-pager: keep vs bump, chosen value, rollback plan.
3. **Apply OR document:**
   - **GO bump:** edit prod `~/TG_parser/.env` → `RESUMMARIZE_MAX_AGE_DAYS=21` (or 30) → `docker compose up -d tg_parser` (**NOT** `restart`, BUG-078) → verify container OS-env.
   - **NO-GO keep-14:** write verdict note explaining why evidence supports hold (requires strong ratio drop).
4. **Post-change verify (if bumped):** OS-env, optional 1h ratio trend, alert state expectation (may stay firing until ratio14d window rolls).
5. **Docs:** new snapshot note (`C2_T7_*` or `DELTA_T7_VERDICT_*`), runbook §T7 banner, ROADMAP Post-Wave-2 **Next** (δ closed / passive re-watch if bumped).

---

## 4. Out of scope (hard)

- TTL / F5-C #15 **implementation** (ζ skeleton only; code next explicit GO).
- Wave E, F11 HTTP CRUD, webhook 2A, ε rework.
- `docs/methodology/**`, `pyproject.toml` / `requirements.txt`.
- Prod mutation **в этой planning-сессии** (только docs); bump — в δ execution session с owner GO.

---

## 5. Acceptance (δ session done when)

- [ ] Fresh metrics snapshot recorded with timestamp.
- [ ] Verdict documented: keep-14 **or** bump applied + OS-env verified.
- [ ] Runbook §T7 banner reflects post-verdict state.
- [ ] ROADMAP **Next** updated (δ closed; optional passive re-watch note if bumped).
- [ ] No scope creep (TTL code, Wave E, F11 HTTP untouched).
- [ ] Commit/PR only if owner explicitly requests.

---

## 6. Self-review fixes applied (plan)

1. Added **fresh live fetch** (2026-07-22T14:51Z) alongside prior 2026-07-21 chat snapshot — avoids stale 0.503 premise.
2. Explicit **keep-14 bar** = sustained `<0.5` + alert cleared — makes default bump path unambiguous.
3. **21 vs 30** — default 21 unless owner opts 30; tied to DRAFT + #15 stale-detector alignment.
4. **BUG-078** called out in apply step (`up -d`, not `restart`).
5. Separated **planning session** (docs only) from **execution session** prod mutation — matches user constraint.

---

## 7. Links

- Track δ definition: [`DRAFT_NEXT_CONTRACT_POST_GAMMA_CLOSEOUT_2026-07-20.md`](DRAFT_NEXT_CONTRACT_POST_GAMMA_CLOSEOUT_2026-07-20.md) §2
- Prior snapshot: [`C2_T7_LIVE_SNAPSHOT_2026-07-20.md`](C2_T7_LIVE_SNAPSHOT_2026-07-20.md)
- Runbook: [`F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md) §T7
- START_PROMPT: [`START_PROMPT_SESSION_DELTA_T7_GATE_RESPONSE_2026-07-22.md`](START_PROMPT_SESSION_DELTA_T7_GATE_RESPONSE_2026-07-22.md)
