# START PROMPT — Wave 3 planning readiness (scope selection)

**Дата создания:** 2026-08-11 · **Для:** планирующей сессии Wave 3 (design-first; **не** sprint реализации).
**Goal (одной строкой):** на актуальном SoT (post-δ/ε/ζ + F5-C #15 core) выбрать **следующий контракт** или явно зафиксировать **continue dogfooding** — и только после выбора произвести ROADMAP «Wave 3» entry + implementation START_PROMPT. **Эта сессия не пишет feature-код.**

> **Рабочий режим ([`AGENTS.md`](../../AGENTS.md)):** `git commit` / деплой — только по явному запросу; `docs/methodology/**` не трогать; `pyproject.toml` / `requirements.txt` не трогать. Planning = документы (decision-log + PLAN + implementation START_PROMPT). Реализация — отдельная сессия.

---

## 1. Контекст — где мы сейчас

- **Wave 2 CLOSED**; post-Wave-2 α/β/γ/δ/ε/ζ **все resolved**.
- **Tech-debt gate перед планированием отсутствует** (γ3 audit + WAVE1 inventory closed; BUG-008 open by-design).
- **F5-C #15 core (#1–#5, #10) shipped**; remainder #6–#9 = parking-lot.
- Decision-input: [`DRAFT_NEXT_CONTRACT_PRE_WAVE3_2026-08-11.md`](DRAFT_NEXT_CONTRACT_PRE_WAVE3_2026-08-11.md).
- SoT roadmap: [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) § Post-Wave-2 / Next.
- Wave 1.5 tracker: [`PLAN_WAVE1_5_DOGFOODING_2026-06-06.md`](PLAN_WAVE1_5_DOGFOODING_2026-06-06.md) — **2A/2B/2C = 0/0/0** (re-check 2026-08-11).

**Deprecated historical Wave 3 label** in [`ROADMAP_V3_PRODUCTION_FIRST.md`](ROADMAP_V3_PRODUCTION_FIRST.md) («F6 enhancements, F1 full») — **не SoT**. F6 topic-digest уже DONE (ADR-0019); F1 Full остаётся parking-lot.

---

## 2. Уже решено (не пере-решать)

- Не переоткрывать F5-B Phase 1 (ADR-0016 Rejected).
- Не менять `RESUMMARIZE_MAX_AGE_DAYS=21` без нового measurement cycle.
- Не flip'ать Event B retention без owner GO + backup + dry-run (would_purge≈0).
- Не путать parking-lot с уже отгруженным F5-C #1–#5/#10.
- Karpathy 7-checklist ([ADR-0006](../adr/0006-karpathy-like-living-kb-principles.md)) обязателен для любого product кандидата.

---

## 3. Что должна решить эта сессия

1. **Signal verdict:** подтвердить или обновить 2A/2B/2C counters + owner friction.
2. **Track choice (ровно один headline):**
   - **A — Continue dogfooding** (recommended default при 0/0/0) — **без** ROADMAP «Wave 3» секции; обновить Next pointer + Forced DP reminder.
   - **B — Internal-quality mini-contract** (ops hygiene slice из draft §4) — маленький PLAN/START_PROMPT; ярлык Wave 3 **не обязателен**.
   - **C — Product Wave 3 contract** — выбрать 1–N кандидатов из parking-lot; написать PLAN + implementation START_PROMPT; **тогда** добавить `## YYYY-MM-DD — Wave 3: <title>` в ROADMAP.
3. **Decision-log** (`REVIEW_*` или секция в PLAN) — почему выбран A/B/C.

---

## 4. Recommended default (если сигналов нет)

**A — Continue dogfooding.** Rationale = Wave 2 Fork 5 weighting при 2A/2B/2C = 0. Forced Decision Point ~2026-09-01 (§7 Wave 1.5). Optional parallel: tiny ops from draft §4 (не Event B).

---

## 5. Parking-lot reading list (для выбора C)

| Candidate | Anchor |
|---|---|
| Wave E graph | ROADMAP Wave E; PLANNING_NEXT_CONTRACT_PREP |
| F11 HTTP CRUD | WAVE1_TECH_DEBT §C |
| Webhook 2A | ADR-0008 |
| F1 Full | FUTURE_FEATURES F1 |
| F5-C #6–#9 | issue #15 / FUTURE_FEATURES Level C |
| force_resummarize bot | issue #15 item #5 remainder |

---

## 6. Deliverables (DoD planning session)

| If choice | Must produce |
|---|---|
| **A** | Short decision note + ROADMAP Next pointer update («continue dogfooding; Wave 3 unnamed») |
| **B** | PLAN + START_PROMPT mini; ROADMAP Next update; Wave 3 naming optional |
| **C** | PLAN_WAVE3_*.md + START_PROMPT_SPRINT_WAVE3_*.md + ROADMAP `## … — Wave 3: …` section |

**Hard OUT:** feature code, migrations, Event B flip without GO, inventing Wave 3 title without choosing A/B/C, `docs/methodology/**`.

---

## 7. Pre-flight checklist

- [ ] Read DRAFT_PRE_WAVE3 + ROADMAP Next + PLAN_WAVE1_5 §5/§11
- [ ] Confirm 2A/2B/2C counters
- [ ] Owner picks A / B / C
- [ ] Produce deliverables for that choice only
- [ ] Do **not** name Wave 3 unless C (or explicit owner override)
