# START PROMPT — Session #2: аудит документации

**Дата:** 2026-08-12 · **Тип:** docs audit (сверка с эталоном #1; не переписывание корпуса) · **Ветка:** `cursor/audit-documentation-2-7075`
**SoT scope:** [`DECISION_AUDIT_AND_STRATEGY_SESSIONS_2026-08-12.md`](DECISION_AUDIT_AND_STRATEGY_SESSIONS_2026-08-12.md) (строка #2)
**Plan (исполнять целиком §0–§9):** [`PLAN_SESSION_AUDIT_DOCUMENTATION_2_2026-08-12.md`](PLAN_SESSION_AUDIT_DOCUMENTATION_2_2026-08-12.md)

**Goal:** разделить документацию на канон / историю / ложь по эталону из #1, назначить диспозиции 7 роадмапам и 5 архитектурам, задать политику роста трём гигантам → `docs/notes/AUDIT_DOCUMENTATION_<run-date>.md`.

> **Эталон готов:** `docs/notes/AUDIT_FUNCTIONAL_EXECUTABLE_2026-08-12.md` ([PR #393](https://github.com/AlexEfimov/TG_parser/pull/393), 42 строки: pass 16 / partial 18 / fail 2 / not_run 6). Если PR не смержен — читать из его ветки. **Правило на будущее:** нет матрицы → сессия не стартует, потому что иначе docs сверяются с docs.

> Этот промпт = явный запрос на **docs-only PR**. Код / тесты / ADR / contracts / methodology / deploy — нет.

---

## Opener (вставить в новый чат)

> Стартую Session #2 — аудит документации (pre-Wave 3).
>
> Прочитай:
> 1. `docs/notes/START_PROMPT_SESSION_AUDIT_DOCUMENTATION_2_2026-08-12.md`
> 2. `docs/notes/PLAN_SESSION_AUDIT_DOCUMENTATION_2_2026-08-12.md` (**§0–§9 целиком**)
> 3. `docs/notes/DECISION_AUDIT_AND_STRATEGY_SESSIONS_2026-08-12.md` (строка #2)
> 4. Артефакт #1 — `docs/notes/AUDIT_FUNCTIONAL_EXECUTABLE_2026-08-12.md` (**эталон**)
>
> Исполни plan: перемерить числа → W1 truth-check → W2 структура → W3 политика роста → артефакт → docs PR.
>
> Эталон = матрица #1. `FUTURE_FEATURES` / `ROADMAP_*` / `BUG_LOG` — **предмет проверки**, не источник.
> Расхождения искать в **обе** стороны: и «заявлено done, а не работает», и «работает, а числится в бэклоге».
> Начни с пяти адресов из plan §3 W1 — они уже подтверждены прогоном.
> Hard OUT и DoD — plan §8–§9. Narrative артефакта ≤3 стр.

---

## Anchors

| | |
|---|---|
| Branch | `cursor/audit-documentation-2-7075` only |
| Artifact | `docs/notes/AUDIT_DOCUMENTATION_<run-date>.md` |
| Эталон | `docs/notes/AUDIT_FUNCTIONAL_EXECUTABLE_*.md` (из #1) |
| Роадмап-жанр | 7 файлов — plan §3 W2 |
| Архитектурный жанр | 5 файлов — plan §3 W2 |
| Гиганты | `BUG_LOG` 5784 · `FUTURE_FEATURES` 3311 · `USER_GUIDE` 2840 |
| Правки в сессии | только `fix-pointer`, ≤10 штук |

---

## Финальный ответ агента

1. Counts: agrees / contradicts / silent / stale-status
2. ≤5 находок
3. Вердикт по канону: есть / нет / частично
4. Artifact path + PR URL
5. Что отложено в исполнительную сессию
