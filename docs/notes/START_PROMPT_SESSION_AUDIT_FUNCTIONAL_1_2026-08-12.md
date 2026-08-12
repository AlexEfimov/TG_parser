# START PROMPT — Session #1: исполняемый аудит функционала

**Дата:** 2026-08-12 · **Тип:** docs/ops audit (read+execute на проде; **не** feature-код) · **Ветка:** `cursor/audit-functional-1-7075` от актуального `main`
**SoT scope:** [`DECISION_AUDIT_AND_STRATEGY_SESSIONS_2026-08-12.md`](DECISION_AUDIT_AND_STRATEGY_SESSIONS_2026-08-12.md) §1
**Plan (исполнять по нему):** [`PLAN_SESSION_AUDIT_FUNCTIONAL_1_2026-08-12.md`](PLAN_SESSION_AUDIT_FUNCTIONAL_1_2026-08-12.md)

**Goal (одной строкой):** прогоном на проде заполнить матрицу возможностей (MCP / HTTP / pipeline + bot-declaration) и cost snapshot; записать короткий артефакт — без правок продукта и без веры в docs как evidence.

> **Рабочий режим ([`AGENTS.md`](../../AGENTS.md)):** этот промпт = явный запрос на docs PR с артефактом аудита. Код / `pyproject.toml` / `requirements.txt` / `docs/methodology/**` / ADR / contracts — **не трогать**. Deploy — нет. Опасные write (`trigger_*`, `force_resummarize`, `set_llm_config`, subscribe без owner chat_id) — **запрещены**, пока owner не даст GO в чате.

---

## Opener (вставить в новый чат Cursor)

> Стартую Session #1 — исполняемый аудит функционала (pre-Wave 3).
>
> Прочитай целиком:
> 1. `docs/notes/START_PROMPT_SESSION_AUDIT_FUNCTIONAL_1_2026-08-12.md`
> 2. `docs/notes/PLAN_SESSION_AUDIT_FUNCTIONAL_1_2026-08-12.md`
> 3. `docs/notes/DECISION_AUDIT_AND_STRATEGY_SESSIONS_2026-08-12.md` §1
>
> Затем исполни plan §1–§6 ровно: pre-flight → фазы A–I → артефакт → docs PR.
>
> **Evidence = прогон.** `FUTURE_FEATURES` — только гипотезы строк.
> **Hard OUT:** фикс багов, сессии #2–#5, опасные ops без GO, narrative артефакта >3 стр.
> **Commit/PR:** да, docs-only артефакт в `main` через PR.

---

## 0. Контекст (не переоткрывать)

- Порядок аудитов зафиксирован: #1 functional → #2 docs → #3 bot/MCP review → #4 business → #5 paths.
- Документация уже врала (prep 2026-08-12); поэтому #1 не читает статус фич из notes как истину.
- Tech-debt gate перед Wave 3 снят; эта сессия — **данные** для Forced DP / #4, не выбор Wave 3.

---

## 1. Pre-flight

```bash
git checkout main && git pull --ff-only origin main
git checkout -b cursor/audit-functional-1-7075
bash scripts/cursor_cloud_setup_prod_ssh.sh
ssh -o BatchMode=yes prod 'echo ok'
```

- MCP: `tg-parser-vps` (prod) — первый вызов `whoami`.
- Если SSH или MCP недоступны → артефакт с Gap, **без** выдуманных цифр; PR всё равно.

Reading list (только это):

| Файл | Зачем |
|---|---|
| DECISION §1 | scope строк матрицы |
| Plan §2 фазы A–I | порядок вызовов |
| `FUTURE_FEATURES` сводная таблица | гипотезы, не evidence |
| `S0_BASELINE_PROCESSING_METRICS_2026-07-07.md` | PromQL cost |
| ADR-0021 recovery cost | $215–380 cite |

---

## 2. Исполнение

Следуй **plan §2** фазам A→I в указанном порядке.

**Краткий чеклист (детали — в plan):**

1. **A** whoami / list_channels / pipeline_status / get_llm_config  
2. **B** list_topics → details → document → related → cross_channel_stats  
3. **C** search hybrid + ask_question + HTTP `/api/v1/search` sample  
4. **D** workspace smoke `audit_functional_1_smoke` + cleanup (bot = `n/a`)  
5. **E** list digests/watchlists + matches; scheduler evidence; subscribe = not_run без chat_id  
6. **F** export raw + status (no `raw_payload`); get_topic_versions; force_resummarize = not_run  
7. **G** pipeline via metrics/logs — **не** trigger  
8. **H** cost table (tokens 7d → $/week; $/doc; recovery cite)  
9. **I** bot column = TOOL_DECLARATIONS presence only  

Заполняй матрицу **по ходу**, не в конце.

---

## 3. Deliverable

Создать:

`docs/notes/AUDIT_FUNCTIONAL_EXECUTABLE_2026-08-12.md`

Структура — plan §3. Лимит narrative ≤3 стр. вне таблиц.

DoD — plan §6.

```bash
git add docs/notes/AUDIT_FUNCTIONAL_EXECUTABLE_2026-08-12.md
git commit -m "docs: executable functional audit (session #1)"
git push -u origin cursor/audit-functional-1-7075
# PR → main (docs-only)
```

---

## 4. Hard OUT (повторить)

| OUT | Почему |
|---|---|
| Правки кода / тестов / промптов | другая сессия / bugfix |
| Аудит документации (#2) | нет эталона до этого артефакта |
| Code review bot/MCP (#3) | параллель/следующая; здесь только fail signals |
| Business / Wave 3 (#4–#5) | нужен этот артефакт + шаг 0 |
| `trigger_*`, `force_resummarize`, `set_llm_config` | DECISION: GO only |
| Subscribe на чужой/неизвестный chat_id | риск спама / orphan |
| Docs как proof | класс ошибок prep 2026-08-12 |

---

## 5. Формат финального ответа агента

1. Counts: `pass` / `fail` / `partial` / `not_run`  
2. Top findings (≤5 bullets)  
3. Cost one-liner  
4. Путь к артефакту + PR URL  
5. Список `not_run`, где нужен owner GO / chat_id
