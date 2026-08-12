# START PROMPT — Session #1: исполняемый аудит функционала

**Дата:** 2026-08-12 · **Тип:** docs/ops audit (прогон на проде; не feature-код) · **Ветка:** `cursor/audit-functional-1-7075`
**SoT scope:** [`DECISION_AUDIT_AND_STRATEGY_SESSIONS_2026-08-12.md`](DECISION_AUDIT_AND_STRATEGY_SESSIONS_2026-08-12.md) §1
**Plan (исполнять целиком §0–§6):** [`PLAN_SESSION_AUDIT_FUNCTIONAL_1_2026-08-12.md`](PLAN_SESSION_AUDIT_FUNCTIONAL_1_2026-08-12.md)

**Goal:** матрица возможностей прогоном (MCP / HTTP / pipeline + bot-declaration) + cost snapshot → `docs/notes/AUDIT_FUNCTIONAL_EXECUTABLE_<run-date>.md`.

> Этот промпт = явный запрос на **docs-only PR**. Код / deps / methodology / ADR / contracts / deploy — нет. Опасные ops — только по plan §0 GO table.

---

## Opener (вставить в новый чат)

> Стартую Session #1 — исполняемый аудит функционала (pre-Wave 3).
>
> Прочитай:
> 1. `docs/notes/START_PROMPT_SESSION_AUDIT_FUNCTIONAL_1_2026-08-12.md`
> 2. `docs/notes/PLAN_SESSION_AUDIT_FUNCTIONAL_1_2026-08-12.md` (**§0–§6 целиком**, включая Default GO)
> 3. `docs/notes/DECISION_AUDIT_AND_STRATEGY_SESSIONS_2026-08-12.md` §1
>
> Исполни plan: pre-flight → фазы A–I → артефакт → docs PR.
> Evidence = прогон. `docs/notes/FUTURE_FEATURES.md` — только гипотезы строк.
> Hard OUT и DoD — plan §5–§6. Narrative артефакта ≤3 стр.

---

## Anchors

| | |
|---|---|
| Branch | `cursor/audit-functional-1-7075` only |
| Artifact | `docs/notes/AUDIT_FUNCTIONAL_EXECUTABLE_<run-date>.md` |
| Cost PromQL | `docs/notes/S0_BASELINE_PROCESSING_METRICS_2026-07-07.md` |
| Recovery cite | `docs/adr/0021-backup-and-recovery-requirements.md` |
| SSH setup | `bash scripts/cursor_cloud_setup_prod_ssh.sh` |

---

## Финальный ответ агента

1. Counts: pass / fail / partial / not_run  
2. ≤5 findings  
3. Cost one-liner  
4. Artifact path + PR URL  
5. not_run, где нужен owner GO / chat_id
