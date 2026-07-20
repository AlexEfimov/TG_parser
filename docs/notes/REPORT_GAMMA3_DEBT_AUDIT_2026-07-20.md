# REPORT — γ3 parking-lot prune / debt audit (2026-07-20)

**Тип:** docs-only closeout report (не START_PROMPT) · **Ветка:** `docs/gamma3-debt-audit`  
**Goal:** закрыть γ3 из [`DRAFT_NEXT_CONTRACT_POST_WAVE2`](DRAFT_NEXT_CONTRACT_POST_WAVE2_2026-06-18.md) — пройтись по [`WAVE1_TECH_DEBT.md`](WAVE1_TECH_DEBT.md) + `[wave1.5-dogfood]` в [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md), отсеять stale, поднять реальный owner-friction; формально закрыть трек в ROADMAP.

> Предшественники: Wave 1.5 review #1 (2026-06-20) нашёл **0** tagged friction → discipline start; DF-1/2/3 filed `6eded89` (2026-06-24). Этот отчёт — formal closeout после post-Wave-2 reconcile.

---

## 1. Verdict (одной строкой)

**γ3 = DONE.** Wave-1 actionable debt inventory почти целиком закрыт (остаётся только BUG-008 / γ1′); единственный stale-текст — §C F5-B «GATED» (фактически Rejected); dogfood-лог живой (3 DF), но не требует product-backlog promotions. Реальный next-contract материал — не «долги Wave 1», а signal-gated parking-lot + owner-friction DF-1 (опц.).

---

## 2. WAVE1_TECH_DEBT — triage

| Секция / item | Вердикт | Действие |
|---|---|---|
| §A все кроме BUG-008 | KEEP as closed ledger | не удалять историю |
| **BUG-008** | KEEP open | out of γ3 → γ1′ monitoring / H3 |
| §B by-design (все) | KEEP | ADR-shield, не debt |
| §C F5-B «Phase 1 GATED» | **PRUNE text → Rejected** | выровнять ADR-0016 / ROADMAP (`26c53e2`) |
| §C F5-C remainder (#15 без #4/#10) | KEEP parking-lot | signal-gated |
| §C Bot-UX TD-D-01/02/03 | KEEP DONE | уже помечено |
| §C F11 HTTP / S4 / F1 / webhook | KEEP parking-lot | signal-gated (2A/2B/2C) |
| §C T6 semantic alert | KEEP DONE | `eead91e` |

---

## 3. `[wave1.5-dogfood]` — triage

| ID | Вердикт | Promote? |
|---|---|---|
| **DF-1** pytest system-Python hard-fail watchlist | KEEP; реальный ops friction | **опц.** tiny UX: skip/clear error если нет pymorphy3 — **не** в этом PR |
| **DF-2** Cursor sandbox no SSH to prod | KEEP; attenuated (Cloud SSH path exists) | **нет** — ops/boundary |
| **DF-3** single-interest α2 Δ=0 expected | KEEP as measurement note | **нет** — не product gap |
| Discipline ≥1 tag/week | Owner call | renew vs accept R-5 solo-bias — **не** backlog item |

---

## 4. FUTURE_FEATURES outline drift (same-pass)

| Target | Вердикт |
|---|---|
| Summary **F9** (выглядел open) | mark Phase 1–3 DONE |
| Summary **F5** | note Phase 0 obs / Phase 1 Rejected / F5-C MVP+P2#4+#10 DONE |
| Intro «пока не запланированных» | soften — много shipped |
| DF section | disposition tags (KEEP / optional promote) |
| Ancient `TECH_DEBT_PLAN.md` / `technical-debt-roadmap.md` | **out of γ3** (не трогать) |

---

## 5. Edits landed with this report

1. [`WAVE1_TECH_DEBT.md`](WAVE1_TECH_DEBT.md) — §C F5-B → Rejected; inventory-closed banner.
2. [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) — summary F5/F9; DF disposition; intro date/status.
3. [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) — γ3 → DONE + link this report.

---

## 6. What γ3 does **not** do

- Не чинит BUG-008 (γ1′).
- Не меняет T7 knob / `ratio14d` watch.
- Не выбирает Wave 3 / next contract (TBD).
- Не реализует DF-1 pytest UX (опциональный follow-up, owner GO).

---

## 7. Recommended next after γ3

| Priority | Item |
|---|---|
| 1 | **T7 watch** (passive) — hold `=14`; revisit if `ratio14d` sustains ≥0.5 |
| 2 | **Next-contract brief** — выбрать Wave 3 / sprint из parking-lot + owner friction |
| 3 | **γ1′** — BUG-008 live-recurrence / H3 (только при recurrence) |
| 4 | (опц.) DF-1 pytest skip/clear — tiny code UX |

---

## 8. Ссылки

- DRAFT γ3 definition: [`DRAFT_NEXT_CONTRACT_POST_WAVE2_2026-06-18.md`](DRAFT_NEXT_CONTRACT_POST_WAVE2_2026-06-18.md) §2 Track γ.
- Review #1 empty γ3: [`REVIEW_WAVE1_5_1_2026-06-20.md`](REVIEW_WAVE1_5_1_2026-06-20.md).
- DF-1/2/3: commit `6eded89`.
- Post-Wave-2 SoT: [`ROADMAP` § Post-Wave-2](ROADMAP_KARPATHY_LIKE_LIVING_KB.md).
