# DRAFT — Next contract (post-γ closeout): track-selection brief

> 🔒 **STATUS 2026-08-11 — SUPERSEDED.** Треки **δ/ε/ζ исполнены**; F5-C #15 core (#1–#5, #10) отгружен; T7 keep-`21` closed. Актуальный decision-input: [`DRAFT_NEXT_CONTRACT_PRE_WAVE3_2026-08-11.md`](DRAFT_NEXT_CONTRACT_PRE_WAVE3_2026-08-11.md) + planning prompt [`START_PROMPT_PLANNING_WAVE3_2026-08-11.md`](START_PROMPT_PLANNING_WAVE3_2026-08-11.md). Текст ниже — **исторический decision-record** (2026-07-20); не читать как текущий план.
>
> **DRAFT — decision-input после закрытия post-Wave-2 треков (α/β/γ), 2026-07-20.** Это **не** контракт и **не** START_PROMPT — standalone черновик, из которого владелец выбирает следующий спринт, вместо того чтобы стартовать с нуля. Ничего здесь **не** применяется к ROADMAP / существующим планам без явного go-ahead. Формального ярлыка «Wave 3» **нет** — секция Wave 3 в ROADMAP появляется только после явного решения о контракте.

**Тип документа:** planning draft / track-selection brief (docs-only).
**Branch:** `main` (working branch `docs/draft-next-contract-post-gamma-closeout`). **Режим:** docs-only, ноль кода/тестов; commit/PR — **только** по явному запросу пользователя ([`AGENTS.md`](../../AGENTS.md)).
**Goal (одной строкой):** зафиксировать post-γ состояние (все α/β/γ разрешены; T7 watch в полёте) и предложить 2–3 готовых к выбору трека (mini-contracts) + рекомендованный default с явными блокерами.

**Predecessor:** [`DRAFT_NEXT_CONTRACT_POST_WAVE2_2026-06-18.md`](DRAFT_NEXT_CONTRACT_POST_WAVE2_2026-06-18.md) — SUPERSEDED / все треки разрешены.

---

## 0. TL;DR (executive)

- **Post-Wave-2 треки исчерпаны.** α1/α2 DONE, β/F5-B Phase 1 **Rejected**, γ2/T7 LIVE + ops-enablement DONE, γ3 debt-audit DONE. SoT: [`ROADMAP` § Post-Wave-2](ROADMAP_KARPATHY_LIKE_LIVING_KB.md), [`REPORT_GAMMA3_DEBT_AUDIT_2026-07-20.md`](REPORT_GAMMA3_DEBT_AUDIT_2026-07-20.md).
- **T7 watch активен (пассивный ops):** knob `RESUMMARIZE_MAX_AGE_DAYS=14` LIVE с **2026-07-19 20:36Z** (Кипр ≈ 19.07 23:36 EEST). Окно **24–48 ч**: +24ч ≈ **20.07 23:36 EEST**, +48ч ≈ **21.07 23:36 EEST**. Live: `ratio14d≈0.504`, alert `ResummarizeAgeTriggerGateF5CPhase2` = `pending` (`for:12h` → возможный `firing` ≈ **21.07 03:37 EEST**). Cost низкий; это сигнал «оценить knob», не инцидент.
  - **Update 2026-07-22 (δ closed):** +48h watch **PASSED**; re-snapshot `ratio14d≈0.989`, alert **firing** → verdict **bump `14 → 21`** applied on prod (`up -d`). SoT: [`DELTA_T7_VERDICT_2026-07-22.md`](DELTA_T7_VERDICT_2026-07-22.md). Строки про `0.504`/`pending` выше — историческая draft-time фиксация.
- **Wave 1.5:** continue dogfooding; Decision-Point signals **2A/2B/2C = 0/0/0** — product pivot / parking-lot impl вслепую не стартуем.
- **Предложено 3 трека** (§2): **δ** T7 gate response (ops), **ε** internal-quality / dogfood fill, **ζ** product-prep skeleton (F5-C #15 TTL, docs-only). **Рекомендованный default (§3): ε сейчас ‖ δ сразу после +24ч/+48ч watch.** ζ — parallel docs-only по GO, не блокирует ε/δ.

---

## 1. Current state (anchored)

### 1.1 Closed since Wave 2 / post-Wave-2 (не переоткрывать)

| Item | Состояние | Anchor |
|---|---|---|
| Wave 2 Dogfood-Quality combo | ✅ CLOSED | `b294b05`, T6 `eead91e` |
| α1 recall-lift / α2 seed-map | ✅ DONE | `e9dfb11`, `284436c` |
| β F5-B Phase 1 | ✅ Rejected (rate ≪ 5%) | ADR-0016, `26c53e2` |
| γ2 T7 ops-enablement | ✅ DONE — knob LIVE `=14` | PR #336/`b6ca9df`, #337/`b0784e6` |
| γ3 debt-audit | ✅ DONE | [`REPORT_GAMMA3…`](REPORT_GAMMA3_DEBT_AUDIT_2026-07-20.md), PR #339 |
| F9 Phase 2–3 / S1–S7 / BUG-064…085 | в основном ✅ | ROADMAP § Post-Wave-2 |

### 1.2 Active / date-gated now → ✅ RESOLVED (δ closed 2026-07-22)

> **Update 2026-07-22 (δ closed):** T7 watch **завершён** — таблица ниже историческая (draft-time date-gates). Оба ops-watch окна PASSED; verdict **bump `14 → 21`** applied. Актуальный статус: [`DELTA_T7_VERDICT_2026-07-22.md`](DELTA_T7_VERDICT_2026-07-22.md), ROADMAP **Next**.

| Gate / watch | Когда | Что разблокирует | Anchor |
|---|---|---|---|
| **T7 ops-watch (+24ч мин)** | ≈ **2026-07-20 23:36 EEST** | минимальный вердикт keep-14 vs bump | runbook §T7, StartedAt `2026-07-19T20:35:59Z` |
| **T7 ops-watch (+48ч полный)** | ≈ **2026-07-21 23:36 EEST** | полный acceptance / close watch | то же |
| **Alert `ResummarizeAgeTriggerGateF5CPhase2`** | `pending` с `activeAt=2026-07-20T12:37:34Z`; `for:12h` → ≈ **21.07 03:37 EEST** если `ratio14d≥0.5` | info-сигнал «evaluate MAX_AGE_DAYS», не авто-bump | `docker/prometheus/alerts.yml`, [`C2_T7_LIVE_SNAPSHOT`](C2_T7_LIVE_SNAPSHOT_2026-07-20.md) |

### 1.3 Deferred / parking-lot (pickup по нужде или signal)

| Item | Статус | Источник |
|---|---|---|
| Wave E graph retrieval | deferred — gated на 2A/2B/2C > 0 | PLAN_WAVE2 / ROADMAP |
| F11 HTTP CRUD | deferred — signal-gated | WAVE1_TECH_DEBT §C |
| Webhook 2A (ADR-0008) | deferred — signal-gated | PLAN_WAVE2 |
| S4 multilang / F1 Full | deferred — signal-gated | WAVE1_TECH_DEBT §C |
| F5-C #15 remainder (TTL, diff-API, F6 topic-digest, bot-tools, …) | open backlog; #4+#10 DONE | issue #15, FUTURE_FEATURES F5-C |
| D2 watchlist scoring formula | deferred — NO ADR-stub (D1 RARE) | HANDOFF §6 D |
| Handoff F/G/H | deferred by user | HANDOFF §6 |
| **γ1′ BUG-008** | H1-fix shipped; `open` by-design — только при live recurrence (+ H3 transport) | BUG_LOG BUG-008, `5165875` |

---

## 2. Candidate tracks (mini-contracts)

> Каждый трек — кандидат на следующий спринт. Выбор делает владелец (§3). Формат: goal · scope · size/risk · deps/gates · why-now.

### Track δ — T7 gate response (ops)

> **Session prompt (2026-07-22):** [`START_PROMPT_SESSION_DELTA_T7_GATE_RESPONSE_2026-07-22.md`](START_PROMPT_SESSION_DELTA_T7_GATE_RESPONSE_2026-07-22.md) · plan: [`PLAN_SESSION_DELTA_T7_GATE_RESPONSE_2026-07-22.md`](PLAN_SESSION_DELTA_T7_GATE_RESPONSE_2026-07-22.md). Watch +48h **PASSED**; **verdict note:** [`DELTA_T7_VERDICT_2026-07-22.md`](DELTA_T7_VERDICT_2026-07-22.md) — bump `14 → 21` **✅ APPLIED** 2026-07-22T19:49Z (δ CLOSED).

- **Goal (одной строкой):** закрыть karpathy-петлю на `RESUMMARIZE_MAX_AGE_DAYS=14` — после окна watch решить **keep 14** или **bump 21/30** (re-create через `docker compose up -d tg_parser`, **не** `restart`).
- **Scope:**
  - Снять `tg:resummarize_age_trigger:ratio14d`, `ALERTS{alertname="ResummarizeAgeTriggerGateF5CPhase2"}`, per-channel tokens/outcomes.
  - Если `ratio14d` устойчиво ≥ 0.5 (alert `firing` или устойчивый pending через полное окно) **и** cost приемлем → bump `.env` → `up -d` → verify OS-env=21/30.
  - Иначе → close watch as «14 OK»; оставить knob; документировать вердикт (короткая note или update snapshot).
- **Rough size/risk:** ~0.2 сессии, LOW (ops-only; rollback = `=0` или обратно `=14` + `up -d`).
- **Deps/gates:** **HARD** — не стартовать bump до +24ч (мин.); предпочтительно дождаться +48ч. Alert `firing` усиливает сигнал, но не заменяет owner GO.
- **Why-now:** knob уже LIVE; gate на границе (0.504); без вердикта observability-loop T7 не закрыт (ADR-0006 #6).

### Track ε — Internal-quality / dogfood fill (unblocked) — DEFAULT headline

- **Goal (одной строкой):** закрыть дешёвые owner-felt хвосты, не зависящие от внешнего signal, пока δ ждёт конец watch и product-pivot нет.
- **Scope (cherry-pick):**
  - **ε1 — DF-1 pytest UX:** при запуске watchlist-тестов под system Python без `pymorphy3` — skip/clear error вместо hard-fail «9 failed» (единственный promote-кандидат из γ3 disposition). См. FUTURE_FEATURES Dogfood Friction Log DF-1.
  - **ε2 — dogfood-discipline renew:** короткая process-note (PLAN_WAVE1_5 / friction log) — renew vs accept R-5 solo-bias; **не** код.
  - **ε3 — γ1′ checklist:** docs «что смотреть при BUG-008 recurrence» (логи, transport H3); код — только если hang вернётся.
- **Rough size/risk:** ~0.3–0.5 сессии, LOW, обратимо. ε1 — единственный code-touch; ε2/ε3 — docs.
- **Deps/gates:** **НЕТ**.
- **Why-now:** 2A/2B/2C = 0; прецедент Wave 2 Fork «internal-quality пока нет внешнего роста» ([PLAN_WAVE2 §3](PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md)); γ3 оставил DF-1 как единственный реальный promote.

### Track ζ — Product-prep skeleton (pre-write only)

- **Goal (одной строкой):** иметь готовый contract skeleton на один parking-lot slice **без реализации**, чтобы следующий product-GO не начинался с нуля.
- **Pinned candidate:** F5-C issue [#15](https://github.com/AlexEfimov/TG_parser/issues/15) remainder — default sub-item **TTL/retention** (самый ops-adjacent после freshness knob). На GO владелец может заменить на Bot tools / diff-API.
- **Scope (docs-only):**
  - Набросать START_PROMPT/ADR-touch skeleton: goal, schema/retention policy options, migration blast-radius, acceptance, out-of-scope.
  - **Не** писать Alembic/код; **не** брать Wave E / F11 HTTP в этот трек (остаются в parking-lot table §1.3).
- **Rough size/risk:** ~0.3 сессии, LOW (docs).
- **Deps/gates:** skeleton — unblocked; **реализация** — explicit owner product GO (+ soft: signal или явная owner-боль). Отдельный START_PROMPT после GO.
- **Why-now:** дешевле skeleton сейчас, чем product sprint вслепую при 0/0/0; TTL логично продолжает T7 freshness-петлю.

---

## 3. Recommended default + per-track blockers

**Рекомендованный default: ε (internal fill) сейчас ‖ δ (T7 verdict) сразу после +24ч/+48ч watch.** ζ — parallel docs-only только если владелец хочет заранее skeleton; не блокирует ε/δ.

> **Owner sequence 2026-07-20:** (1) session ε+ζ — START_PROMPT [`START_PROMPT_SESSION_EPS_ZETA_INTERNAL_FILL_TTL_SKELETON_2026-07-20.md`](START_PROMPT_SESSION_EPS_ZETA_INTERNAL_FILL_TTL_SKELETON_2026-07-20.md); (2) session δ/T7 — после окончания watch (+24ч/+48ч).

**Rationale (один абзац):** Per Wave-2 weighting ([PLAN_WAVE2 §3 Fork 5](PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md): #1 data-readiness, #2 product-friction, #3 karpathy-coherence, #4 cost/risk) — при **2A/2B/2C = 0** product pivot проигрывает. **ε** unblocked и закрывает единственный γ3 promote (DF-1). **δ** замыкает уже-включённый T7 knob (измерить → решить), но hard-gated на конец watch — поэтому идёт **сразу после** вехи, не вместо ε. **ζ** не стартует impl без GO; skeleton опционален.

**Что каждый трек blocked on:**

| Track | Blocked on | Когда разблокируется |
|---|---|---|
| **ε** internal fill | **ничего** | **сейчас** (recommended immediate) |
| **δ** T7 gate response | watch window (+24ч мин / +48ч полный) + ratio/alert/cost evidence | после **20.07 23:36 EEST** (мин.) / **21.07 23:36 EEST** (полный) |
| **ζ** skeleton docs | ничего (docs) | сейчас (optional parallel) |
| **ζ** impl | explicit owner product GO (+ soft signal) | после GO → отдельный START_PROMPT |

---

## 4. Open ADR / ROADMAP actions

- **ADR-0016:** Phase 0 Implemented (permanent observability); Phase 1 Rejected — **не переоткрывать** без нового сигнала.
- **Новых ADR этот brief не предлагает** (decision-input).
- **ROADMAP:** формального «Wave 3» entry **нет** и **не добавлять** из этого brief. После выбора трека владельцем — либо START_PROMPT на ε/δ, либо (при product GO) ζ skeleton → контракт с возможным ярлыком Wave 3.
- **D2 / Handoff F–H / Wave E / F11 HTTP:** остаются parking-lot; не в default.

---

## 5. Out of scope этого brief

- Реализация DF-1 / prod bump knob / любой product code.
- Именование «Wave 3» как секции ROADMAP.
- Reopen ADR-0016 Phase 1; Wave E / F11 HTTP impl.
- Commit/PR этого файла — только по явному запросу.

---

## 6. Ссылки

- SoT post-Wave-2: [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) § «Post-Wave-2 треки».
- Predecessor DRAFT: [`DRAFT_NEXT_CONTRACT_POST_WAVE2_2026-06-18.md`](DRAFT_NEXT_CONTRACT_POST_WAVE2_2026-06-18.md).
- γ3 closeout: [`REPORT_GAMMA3_DEBT_AUDIT_2026-07-20.md`](REPORT_GAMMA3_DEBT_AUDIT_2026-07-20.md).
- T7 live: [`C2_T7_LIVE_SNAPSHOT_2026-07-20.md`](C2_T7_LIVE_SNAPSHOT_2026-07-20.md); runbook [`F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md) §T7.
- Wave 1.5: [`PLAN_WAVE1_5_DOGFOODING_2026-06-06.md`](PLAN_WAVE1_5_DOGFOODING_2026-06-06.md); review #1 [`REVIEW_WAVE1_5_1_2026-06-20.md`](REVIEW_WAVE1_5_1_2026-06-20.md).
- Wave 2 method: [`PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md`](PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md).
- Debt map: [`WAVE1_TECH_DEBT.md`](WAVE1_TECH_DEBT.md) §C; DF-1 in [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) Dogfood Friction Log.
- ADR: [0006](../adr/0006-karpathy-like-living-kb-principles.md) (#6), [0016](../adr/0016-near-duplicate-dedup.md) (Phase 1 Rejected).
- Issue #15 — F5-C Phase 2 backlog (TTL default for ζ).
