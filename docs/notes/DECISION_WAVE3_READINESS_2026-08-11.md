# DECISION — Wave 3 planning readiness (2026-08-11)

**Тип:** decision-log / readiness closeout (не product-контракт).
**Статус:** **interim default зафиксирован** — continue dogfooding; ярлык «Wave 3» **не** добавлен в ROADMAP.

---

## Решение

1. **Tech-debt gate перед планированием Wave 3 = отсутствует** (подтверждено reconcile γ-closeout vs SoT).
2. **Wave 1.5 signals 2A/2B/2C = 0/0/0** (re-check 2026-08-11) → product Wave 3 вслепую не стартуем.
3. **Interim owner-default (choice A из planning prompt):** **continue dogfooding / internal-quality** до Forced Decision Point (~2026-09-01) или до появления threshold signals / explicit product GO.
4. **Wave 3 naming отложен** до planning session choice **C** (product contract) через [`START_PROMPT_PLANNING_WAVE3_2026-08-11.md`](START_PROMPT_PLANNING_WAVE3_2026-08-11.md).

Это не блокирует owner переопределить default на B (ops mini) или C (product) в следующей planning-сессии — артефакты для выбора готовы.

---

## Почему A (не C)

Тот же метод, что Wave 2 Fork 5: при нулевых внешних signals product pivot проигрывает continue dogfooding. Parking-lot жив (Wave E, F11 HTTP, webhook 2A, F1 Full, F5-C #6–#9) — кандидаты задокументированы в [`DRAFT_NEXT_CONTRACT_PRE_WAVE3_2026-08-11.md`](DRAFT_NEXT_CONTRACT_PRE_WAVE3_2026-08-11.md) §2.

---

## Ops hygiene закрытый в том же проходе

| Item | Outcome |
|---|---|
| `ResummarizeLLMErrorRate` denominator | fixed — exclude `refusal_cooldown` |
| Event B retention flip | deferred (prod still `RETENTION_DAYS=0`; would_purge≈0) |
| BUG-088/087 bot deploy | verified prod 2026-08-11 (container Created 2026-08-04; truncation + redact live) |
| BUG-090 residuals / nginx vendor | documented; not acted (owner-call / low) |

---

## Артефакты

- [`DRAFT_NEXT_CONTRACT_PRE_WAVE3_2026-08-11.md`](DRAFT_NEXT_CONTRACT_PRE_WAVE3_2026-08-11.md)
- [`START_PROMPT_PLANNING_WAVE3_2026-08-11.md`](START_PROMPT_PLANNING_WAVE3_2026-08-11.md)
- ROADMAP / PLAN_WAVE1_5 / WAVE1_TECH_DEBT §C updates
- γ-closeout draft → SUPERSEDED banner
