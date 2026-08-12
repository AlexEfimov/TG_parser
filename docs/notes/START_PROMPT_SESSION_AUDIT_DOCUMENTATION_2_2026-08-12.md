# START PROMPT — Session #2: аудит документации

**Дата:** 2026-08-12 · **Тип:** docs audit (сверка с эталоном #1; не переписывание корпуса) · **Ветка:** prefix `cursor/audit-documentation-2-…-7075`
**SoT scope:** [`DECISION_AUDIT_AND_STRATEGY_SESSIONS_2026-08-12.md`](DECISION_AUDIT_AND_STRATEGY_SESSIONS_2026-08-12.md) (строка #2)
**Plan (исполнять целиком §0–§9):** [`PLAN_SESSION_AUDIT_DOCUMENTATION_2_2026-08-12.md`](PLAN_SESSION_AUDIT_DOCUMENTATION_2_2026-08-12.md)

**Goal:** разделить документацию на канон / историю / ложь по эталону из #1, назначить диспозиции роадмап- и архитектурному жанру, задать политику роста гигантам → `docs/notes/AUDIT_DOCUMENTATION_<run-date>.md`.

> **Эталон в `main`:** [`AUDIT_FUNCTIONAL_EXECUTABLE_2026-08-12.md`](AUDIT_FUNCTIONAL_EXECUTABLE_2026-08-12.md) — 42 строки, pass 16 / partial 18 / fail 2 / not_run 6.

> Этот промпт = явный запрос на **docs-only PR**. Код / тесты / ADR / contracts / methodology / deploy — нет.

---

## Opener (вставить в новый чат)

> Стартую Session #2 — аудит документации (pre-Wave 3).
>
> Прочитай:
> 1. `docs/notes/START_PROMPT_SESSION_AUDIT_DOCUMENTATION_2_2026-08-12.md`
> 2. `docs/notes/PLAN_SESSION_AUDIT_DOCUMENTATION_2_2026-08-12.md` (**§0–§9 целиком**)
> 3. `docs/notes/DECISION_AUDIT_AND_STRATEGY_SESSIONS_2026-08-12.md` (строка #2)
> 4. `docs/notes/AUDIT_FUNCTIONAL_EXECUTABLE_2026-08-12.md` — **эталон**
>
> Порядок: замер §2 → W1 → W1-b → W2 → W3 → артефакт → docs PR.
>
> **Первым делом прогони блок команд §2 и вставь его вывод в артефакт.** Ни одно число в тексте не появляется без своей команды — план объясняет в §2, почему это правило написано кровью.
> Эталон = матрица #1; `FUTURE_FEATURES` / `ROADMAP_*` / `USER_GUIDE` — **предмет проверки**, не источник.
> Расхождения искать в **обе** стороны: и «заявлено done, а не работает», и «работает, а числится в бэклоге».
> Начни с шести адресов plan §3 W1 — они подтверждены прогоном.
> Бюджет и DoD — plan §9; W1 и W1-b не режутся.

---

## Anchors

| | |
|---|---|
| Артефакт | `docs/notes/AUDIT_DOCUMENTATION_<run-date>.md` |
| Эталон | `docs/notes/AUDIT_FUNCTIONAL_EXECUTABLE_2026-08-12.md` |
| Scope | `docs/**` **и** `*.md` в корне репозитория (13 файлов, включая `README` / `PRODUCTION_DEPLOYMENT` / `ENV_VARIABLES_GUIDE`) |
| Классы W1 | `agrees` · `contradicts` · `silent` · `stale-status` · `no-reference` (только для 6 строк `not_run`) |
| Правки в сессии | только `fix-pointer`, ≤10 штук |
| Числа | все из блока plan §2, ни одного «по памяти» |

---

## Финальный ответ агента

1. Counts: agrees / contradicts / silent / stale-status / no-reference
2. ≤5 находок
3. Вердикт по канону: есть / нет / частично
4. Artifact path + PR URL
5. Что отложено и что срезано по бюджету
