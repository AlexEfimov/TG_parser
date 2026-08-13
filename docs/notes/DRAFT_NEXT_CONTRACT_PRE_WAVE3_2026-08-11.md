# DRAFT — Next contract (pre-Wave-3 readiness): track-selection brief

> **DRAFT — decision-input 2026-08-11.** Reconcile после закрытия post-γ треков δ/ε/ζ и F5-C #15 core. Это **не** контракт и **не** sprint START_PROMPT — brief, из которого owner выбирает следующий шаг. Формального ярлыка «Wave 3» **нет** — секция Wave 3 в ROADMAP появляется только после явного решения о контракте.
>
> **Predecessor:** [`DRAFT_NEXT_CONTRACT_POST_GAMMA_CLOSEOUT_2026-07-20.md`](DRAFT_NEXT_CONTRACT_POST_GAMMA_CLOSEOUT_2026-07-20.md) — **SUPERSEDED** (δ/ε/ζ и F5-C #15 #1–#5+#10 уже исполнены; T7 keep-21 closed).

**Тип документа:** planning draft / readiness + track-selection brief (docs-first).
**Goal (одной строкой):** зафиксировать, что **техдолговый гейт перед планированием Wave 3 отсутствует**, обновить живой parking-lot и предложить default при 2A/2B/2C = 0/0/0.

---

## 0. TL;DR (executive)

- **Жёсткого tech-debt gate нет.** Wave-1 actionable inventory closed (γ3); post-Wave-2 α/β/γ/δ/ε/ζ closed; F5-C #15 core shipped.
- **Wave 1.5 signals 2A/2B/2C = 0/0/0** (re-check 2026-08-11) → product pivot вслепую не стартуем.
- **Рекомендованный default:** **continue dogfooding / internal-quality** до Forced Decision Point (~2026-09-01 per [`PLAN_WAVE1_5`](PLAN_WAVE1_5_DOGFOODING_2026-06-06.md) §7/§11) **или** до ≥ threshold signals. Именовать «Wave 3» в ROADMAP — только после owner GO на конкретный контракт.
- Planning session prompt: [`START_PROMPT_PLANNING_WAVE3_2026-08-11.md`](START_PROMPT_PLANNING_WAVE3_2026-08-11.md).

---

## 1. Closed since γ-closeout draft (не переоткрывать)

| Item | Состояние | Anchor |
|---|---|---|
| δ T7 gate response | ✅ CLOSED — bump `14→21` applied; re-watch keep `=21` | [`DELTA_T7_VERDICT_2026-07-22.md`](DELTA_T7_VERDICT_2026-07-22.md) |
| ε internal fill (DF-1 + dogfood renew + BUG-008 checklist) | ✅ DONE | #342 / `f4073a6` |
| ζ TTL skeleton → implementation | ✅ CODE DONE (prod-gated); Event A deployed | ADR-0018 |
| F5-C #15 #2 diff-API | ✅ DONE | 2026-07-23 |
| F5-C #15 #3 topic-digest | ✅ DONE + DEPLOYED | ADR-0019 |
| F5-C #15 #5 bot read-tools | ✅ DONE + DEPLOYED | PR #355 |
| T7 gate hygiene / refusal_cooldown | ✅ DEPLOYED | PR #370 / `ba7d66d` |
| BUG-087 / BUG-088 / BUG-089 / BUG-090 (structural) | ✅ resolved; bot image re-created **2026-08-04** (prod verified 2026-08-11) | BUG_LOG |

---

## 2. Living parking-lot (кандидаты на Wave 3 / later)

> Не долг. Pickup по signal (2A/2B/2C) или explicit owner GO.

| Candidate | Gate | Notes |
|---|---|---|
| Wave E graph retrieval | 2A/2B/2C > 0 or GO | PLAN_WAVE2 / ROADMAP |
| F11 HTTP CRUD | signal-gated | WAVE1_TECH_DEBT §C |
| Webhook 2A (ADR-0008) | signal-gated | |
| S4 multilang / F1 Full (DB prompts + A/B) | signal-gated | |
| F5-C #15 #6–#9 | signal / GO | type promotion, topic dedup, supporting-item removal, HTTP API |
| `force_resummarize` in bot | UX signal | deferred by design after #5 read-tools |
| D2 watchlist scoring formula | data gate | D1 RARE — no ADR stub yet |
| Handoff F/G/H | deferred by user | HANDOFF watchlist calibration |
| **Разделить `add_channel` на `add_channel` + `update_channel`** | **explicit owner GO** — добавлен 2026-08-13 | Вариант **(b)** из [BUG-094](BUG_LOG.md): семантика чище и инструмент самодокументирован, но это изменение поверхности (MCP 47 → 48, bot 35 → 36 деклараций, `prompts/bot.yaml`, `MCP_AGENT_GUIDE`, 13 тестовых файлов) **плюс правка принятого [ADR-0009](../adr/0009-idempotency.md)**, где `add_channel` записан идемпотентным «UPSERT … (reanimates soft-deleted source)». Требует решить, кто оживляет soft-deleted канал, — сегодня это делает повторный `add_channel`, и `prompts/bot.yaml` обещает это пользователю. Сам дефект BUG-094 закрывается вариантом (a) без всего этого, поэтому здесь кандидат стоит как улучшение семантики, а не как фикс |

**Не путать с закрытым:** F6 topic-digest (#3) и Bot read-tools (#5) — **не** parking-lot.

---

## 3. Recommended default + blockers

| Track | Status | Blocked on |
|---|---|---|
| **Continue dogfooding** (default) | **unblocked now** | nothing — renew Wave 1.5 cadence until Forced DP / signals |
| **Internal-quality mini** (ops hygiene) | optional parallel | owner pick from §4 |
| **Product Wave 3 contract** | blocked | owner GO + preferably 2A/2B/2C signal or Forced DP |
| **Name «Wave 3» in ROADMAP** | blocked | explicit contract choice (START_PROMPT + PLAN) |

**Rationale:** тот же weighting, что Wave 2 Fork 5 — при 0/0/0 product pivot проигрывает continue dogfooding / cheap internal fill.

---

## 4. Optional ops hygiene (не gate планирования)

| Item | Status 2026-08-11 | Action |
|---|---|---|
| **Событие B** (`RESUMMARIZE_VERSION_RETENTION_DAYS=180`) | still `=0` on prod; dry-run «Retention disabled»; would_purge≈0 until ~Oct 2026 | **defer** — owner GO + backup + dry-run |
| **`ResummarizeLLMErrorRate` denominator** | diluted by free `refusal_cooldown` | **fix in this PR** — exclude `refusal_cooldown` from denominator (numerator stays `llm_error`) |
| **BUG-090 residuals** | `init-db.sh` file-mount (low); `.env`×3 ↔ BUG-078 | keep documented; no DB-container recreate |
| **nginx configs вне git** | interim backup + weekly cron DONE 2026-08-07 | vendor-in-repo = owner-call |
| **BUG-008** | `open` by-design; H1 mitigation live | only on live recurrence |
| **BUG-088/087 bot deploy** | **verified prod** 2026-08-11 — container Created `2026-08-04`, code has truncation + `redact_tool_args` | closed as ops concern |

---

## 5. Out of scope этого brief

- Именование «Wave 3» без owner GO.
- Product impl (Wave E / F11 HTTP / F1 Full / Event B flip).
- Reopen ADR-0016 Phase 1; change `RESUMMARIZE_MAX_AGE_DAYS=21`.

---

## 6. Ссылки

- SoT: [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) § Post-Wave-2 / Next.
- Planning prompt: [`START_PROMPT_PLANNING_WAVE3_2026-08-11.md`](START_PROMPT_PLANNING_WAVE3_2026-08-11.md).
- Wave 1.5: [`PLAN_WAVE1_5_DOGFOODING_2026-06-06.md`](PLAN_WAVE1_5_DOGFOODING_2026-06-06.md).
- γ3 audit: [`REPORT_GAMMA3_DEBT_AUDIT_2026-07-20.md`](REPORT_GAMMA3_DEBT_AUDIT_2026-07-20.md).
- Issue [#15](https://github.com/AlexEfimov/TG_parser/issues/15) F5-C P2 remainder #6–#9.
