# START PROMPT — Session #3: код-ревью bot + MCP

> **Отработал 2026-08-12.** Артефакт сессии — [`CODE_REVIEW_BOT_MCP_2026-08-12.md`](../CODE_REVIEW_BOT_MCP_2026-08-12.md).
> Переехал в `archive/` тем же PR по правилу [`AUDIT_DOCUMENTATION_2026-08-12.md`](../AUDIT_DOCUMENTATION_2026-08-12.md) §4.
> Пути в блоке Opener ниже указаны от корня `docs/notes/` и относятся к моменту прогона.

**Дата:** 2026-08-12 · **Тип:** статическое код-ревью (read-only; артефакт — единственный выход) · **Ветка:** prefix `cursor/code-review-bot-mcp-3-…-7075`
**SoT scope:** [`DECISION_AUDIT_AND_STRATEGY_SESSIONS_2026-08-12.md`](../DECISION_AUDIT_AND_STRATEGY_SESSIONS_2026-08-12.md) (строка #3, §2)
**Plan (исполнять целиком §0–§8):** [`PLAN_SESSION_CODE_REVIEW_BOT_MCP_3_2026-08-12.md`](PLAN_SESSION_CODE_REVIEW_BOT_MCP_3_2026-08-12.md)

**Goal:** находки `F-01…F-NN` (severity, якоря, Verified/Not verified) по `tg_parser/bot/tools.py` и `tg_parser/mcp_server.py` — единственной неревьюированной поверхности — → `docs/notes/CODE_REVIEW_BOT_MCP_<run-date>.md`.

> **Read-only.** Никаких правок кода, никаких прогонов на проде: runtime-эталон — матрица #1. Чего нельзя доказать статически — помечается `needs runtime`, не утверждается.

---

## Opener (вставить в новый чат)

> Стартую Session #3 — код-ревью bot + MCP (pre-Wave 3).
>
> Прочитай:
> 1. `docs/notes/START_PROMPT_SESSION_CODE_REVIEW_BOT_MCP_3_2026-08-12.md`
> 2. `docs/notes/PLAN_SESSION_CODE_REVIEW_BOT_MCP_3_2026-08-12.md` (**§0–§8 целиком**)
> 3. `docs/notes/AUDIT_FUNCTIONAL_EXECUTABLE_2026-08-12.md` — runtime-эталон (42 строки + «мелочи для #3»)
> 4. `docs/notes/AUDIT_DOCUMENTATION_2026-08-12.md` §6 — вход для #3
> 5. `docs/notes/BUG_LOG.md` — записи BUG-093…098 как **классы** для свипов
> 6. `docs/notes/CODE_REVIEW_PROCESSING_ALGORITHMS_FABLE5_2026-07-07.md` — формат-прецедент
>
> Порядок: замер §2 → проходы P0–P7 → артефакт → docs-only PR (+ перенести PLAN/START этой сессии в `docs/notes/archive/` тем же PR).
>
> **Ядро мандата — P1 (ownership-свип всех 35+47 инструментов) и P4 (8 адресов с готовыми доказательствами).** P0, P1, P4 не режутся.
> `handlers.py` — только по триггеру plan §4, и только вовлечённые пути.
> Каждое число — с командой (`^@mcp\.tool`, не `@mcp\.tool` — план объясняет почему). Формат находки и лимит ≤2000 слов — plan §5–§6.

---

## Anchors

| | |
|---|---|
| Артефакт | `docs/notes/CODE_REVIEW_BOT_MCP_<run-date>.md` |
| In scope | `tg_parser/bot/tools.py` (5 017) · `tg_parser/mcp_server.py` (4 605) |
| Условно | `tg_parser/bot/handlers.py` — plan §4 |
| OUT | processing/topicization (Fable5 07-07); правки; прод; BUG-заведение |
| Свипы-классы | ownership (BUG-093) · write-shape (BUG-094) · unlabeled degradation (BUG-098) · недостижимый контракт (BUG-096) |
| Формат находки | plan §5; оси: correctness · authz · write-shape · parity · privacy · concurrency · contract-drift |
| Нормативы | ADR-0004 · ADR-0007 · ADR-0009 · ADR-0020 · `docs/contracts/` |

---

## Финальный ответ агента

1. Counts находок по severity
2. Топ-3 находки одной строкой каждая
3. handlers.py: подключался или нет
4. Artifact path + PR URL
5. Что срезано по бюджету (P2/P3/P5–P7)
