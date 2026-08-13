# Decision — порядок и scope аудитов / стратегии (pre-Wave 3)

**Тип:** decision-log планирующей сессии. Заменяет prep [`archive/PLANNING_AUDIT_AND_STRATEGY_PREP_2026-08-12.md`](archive/PLANNING_AUDIT_AND_STRATEGY_PREP_2026-08-12.md).
**Дата:** 2026-08-12.
**Не является:** отчётом аудита, контрактом Wave 3, START_PROMPT реализации.

**Правило исполнения:** один пункт таблицы = одна сессия агента (кроме шага 0). В сессии только её строка: вход → работа → артефакт в лимите. Не смешивать с соседними шагами.

---

## 0. Фон (не сессия агента)

**Желательно запустить до #4** (календарная задержка; **старт #1 не блокирует**):

- попытка поднять 2–3 внешних валидатора Wave 1.5 **и** минимальный market scan, **или**
- явный записанный отказ от плеч 2A/2B/2C (законно для single-operator self-host).

**Артефакт:** ≤1 стр. decision-log (запуск / отказ + обоснование).  
Без этого сессия #4 снова опирается на `0/0/0` как на «измерение».

> **Вердикт владельца 2026-08-13: выбран «запуск», не отказ.** Подключение
> нескольких внешних валидаторов Wave 1.5 — в работе, срок «в ближайшее время».
> Что это означает операционно: **сессия #4 остаётся закрытой гейтом** до одного
> из двух исходов — валидаторы подключены и дали первые сигналы, **либо** попытка
> закрыта и отказ записан. Промежуточное состояние («в работе») входом для #4 не
> является: с ним #4 снова получит на входе `0/0/0` и будет вынуждена трактовать
> отсутствие данных как измерение — ровно то, что этот шаг существует
> предотвратить. Interim default до Forced DP не меняется — continue dogfooding
> ([`DECISION_WAVE3_READINESS_2026-08-11.md`](DECISION_WAVE3_READINESS_2026-08-11.md)).
> Отдельный decision-log по шагу 0 напишется, когда появится исход; этот абзац —
> фиксация выбора, а не сам артефакт.
>
> **Не заблокировано этим вердиктом:** вся очередь исправлений
> ([`PLAN_REMEDIATION_BOT_MCP_2026-08-12.md`](PLAN_REMEDIATION_BOT_MCP_2026-08-12.md) §4)
> — она не зависит ни от шага 0, ни от даты Forced DP.

---

## Порядок сессий и scope

| # | Сессия | Scope (что входит) | Out of scope | Артефакт / лимит |
|---|--------|--------------------|--------------|------------------|
| **1** | Аудит функционала — исполняемый | Пользовательские поверхности + критичный pipeline path на **проде** (см. §1). Cost snapshot в том же прогоне. | Весь бэклог F1…F12; чтение docs как доказательство; фикс багов (только фиксация) | Матрица + cost-таблица; **≤3 стр.** narrative |
| **2** | Аудит документации | Сверка docs с матрицей #1: канон / история / противоречия; план консолидации 7 роадмапов и 5 архитектур; политика роста `BUG_LOG` / `FUTURE_FEATURES` | Переписывание 136k строк; «улучшение стиля» без эталона | **≤3 стр.** + список archive / оставить / слить |
| **3** | Код-ревью bot + MCP | Обязательно: `tg_parser/bot/tools.py`, `tg_parser/mcp_server.py`. `bot/handlers.py` — только если #1 дал fail/partial на bot UX **или** severity из первых двух файлов требует контекста handlers | Рефакторинг в той же сессии; processing/topicization (уже Fable5) | Находки `F-01…F-NN` (формат Fable5); без эссе |
| **4** | Ценность и бизнес-модели | Входы: #1 (+cost), вердикт шага 0, [`MONETIZATION_MECHANISMS`](MONETIZATION_MECHANISMS_2026-05-02.md), [`PRODUCT_STRATEGY`](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md) §3–§6/§13. Выход: ревизия оценок пригодности + закрытие **блокирующих** вопросов §9 | Новая 800-стр. стратегия; выбор фич Wave 3 | Короткий decision + обновлённые оценки; **≤4 стр.** |
| **5** | Пути развития | Parking-lot → контракт Wave 3 **или** явный «не Wave 3 / continue» с критериями выхода; ADR-0006 7-checklist на кандидата | Реализация кода | PLAN + START_PROMPT и/или pointer в ROADMAP |

**Параллельность:** #3 может идти параллельно #1–#2. Если строго последовательно — #3 после #1, до #4.

**Forced Decision Point:** свести в SoT одну дату (трекер Wave 1.5: **2026-09-01**; формула §7 даёт окно 09-06…10-06). До сессии #4 зафиксировать выбранную дату в трекере одной строкой.

---

## 1. Scope сессии #1 — поверхности (детализация)

Гипотезы строк — сводная таблица [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md); **истина — только прогон**.

**Bot в #1:** live Telegram = **out**, пока owner не даст GO. Колонка bot = наличие имени в `TOOL_DECLARATIONS` (`partial` если declared+unexecuted, `n/a` если MCP-only).

### 1.1 Входит (обязательный минимум)

| Область | Что прогонять | Доказательство |
|---------|---------------|----------------|
| **Навигация / KB** | `list_channels`, `list_topics`, `get_topic_details`, `get_document`, `get_related_topics`, `get_cross_channel_stats` | MCP; bot = declaration only |
| **Search / RAG** | `search_knowledge_base` (hybrid), `ask_question` | MCP; HTTP `/api/v1/search` + `/api/v1/ask` |
| **Workspaces F4-B** | `list_workspaces` / create-rename-delete / add-remove source / read tools с `workspace_id` | MCP only (bot = `n/a`) |
| **Digests F6** | `list_digests`; subscribe/unsubscribe только на owner chat_id | MCP (+ scheduler evidence на проде) |
| **Watchlist F11** | `list_watchlists`, `get_watchlist_matches`; subscribe только на owner chat_id | MCP (+ matches/alerts evidence, если есть) |
| **Export F2** | `export_channel` level=`raw` + `get_export_status` + **sample download** (нет ключа `raw_payload`) | MCP (+ HTTP download если URL относительный) |
| **Topics F5-C** | `get_topic_versions`, `get_topic_history_diff`; `force_resummarize` — только по GO | MCP; bot = declaration |
| **Channel ops** | `list_channels` status; `get_pipeline_status`; trigger_* — без GO не стрелять | MCP / Prometheus |
| **Pipeline path** | ingest → process → topicization → (digest \| watchlist hook) | метрики / логи / last success tick |
| **LLM config surface** | `get_llm_config` (read-only); `set_llm_config` / `reset_llm_config` — без GO | MCP |
| **Cost snapshot** | $/неделя из tokens; $/doc если считается иначе `not_recomputed`; recovery из ADR-0021 | таблица в том же артефакте |

### 1.2 Не входит в #1

- F3, F7, F8, F10, F12 и прочий нереализованный / commercial бэклог (кроме пометки «не заявлено как done»).
- F-Prereq-1 (legal) — учёт в #4.
- `backfill_watchlist` — write; `not_run` без GO.
- Channel write/admin: `add/pause/resume/remove_channel`, user-admin tools, `reload_prompts` — вне минимума (не раздувать scope).
- Глубокий security audit F9; в #1 — только если всплывёт на прогоне.
- Правка документации и кода (кроме артефакта аудита).

### 1.3 Формат строки матрицы

Мульти-колоночный (SoT = plan §3):

`возможность | MCP | bot | HTTP | pipeline | способ | вердикт | заметка`

- Per-surface: `pass` / `fail` / `partial` / `not_run` / `n/a`.
- **`вердикт` (итог строки)** = worst среди **исполненных** поверхностей (`fail` > `partial` > `pass`); `not_run`/`n/a` в агрегацию не входят. Если все поверхности `not_run`/`n/a` → итог `not_run`.

---

## 2. Scope сессии #3 — уточнение

| Файл | Статус |
|------|--------|
| `tg_parser/bot/tools.py` (~5k LOC) | **in scope** |
| `tg_parser/mcp_server.py` (~4.6k LOC) | **in scope** |
| `tg_parser/bot/handlers.py` (~2.9k LOC) | **условный** — см. таблицу порядка |
| Processing / topicization | **out** — Fable5 2026-07-07 |

Критерии ревью: correctness, privacy (`raw_payload`), concurrency/locks, drift от contracts/ADR, tool-surface vs заявленный behavior из #1.

---

## 3. Артефакты и гигиена docs

- Один короткий `REVIEW_*` / `AUDIT_*` на сессию; путь: `docs/notes/`.
- Дата в имени артефакта — **дата прогона**, а не дата планирования. Если сессия идёт позже — имя берёт свою дату, а внутри стоит ссылка на этот decision.
- Каждый новый артефакт **вытесняет или архивирует** устаревший указатель; не плодить параллельные SoT.
- Числа в текстах — порядок величины + дата + команда пересчёта, не вечные перечни файлов.
- Prep в [`archive/PLANNING_AUDIT_AND_STRATEGY_PREP_2026-08-12.md`](archive/PLANNING_AUDIT_AND_STRATEGY_PREP_2026-08-12.md) (**SUPERSEDED**); этот файл — SoT по порядку/scope.

---

## 4. START_PROMPT

Короткий `START_PROMPT_*` на сессию (opener + pointers); детали исполнения — в PLAN. Этот decision = SoT scope.

**Session #1:**
- Plan: [`PLAN_SESSION_AUDIT_FUNCTIONAL_1_2026-08-12.md`](PLAN_SESSION_AUDIT_FUNCTIONAL_1_2026-08-12.md)
- START: [`START_PROMPT_SESSION_AUDIT_FUNCTIONAL_1_2026-08-12.md`](START_PROMPT_SESSION_AUDIT_FUNCTIONAL_1_2026-08-12.md)

**Session #2** (✅ отработала 2026-08-12 — артефакт [`AUDIT_DOCUMENTATION_2026-08-12.md`](AUDIT_DOCUMENTATION_2026-08-12.md)):
- Plan: [`PLAN_SESSION_AUDIT_DOCUMENTATION_2_2026-08-12.md`](PLAN_SESSION_AUDIT_DOCUMENTATION_2_2026-08-12.md)
- START: [`START_PROMPT_SESSION_AUDIT_DOCUMENTATION_2_2026-08-12.md`](START_PROMPT_SESSION_AUDIT_DOCUMENTATION_2_2026-08-12.md)

**Session #3** (✅ отработала 2026-08-12 — артефакт [`CODE_REVIEW_BOT_MCP_2026-08-12.md`](CODE_REVIEW_BOT_MCP_2026-08-12.md)):
- Plan: [`archive/PLAN_SESSION_CODE_REVIEW_BOT_MCP_3_2026-08-12.md`](archive/PLAN_SESSION_CODE_REVIEW_BOT_MCP_3_2026-08-12.md)
- START: [`archive/START_PROMPT_SESSION_CODE_REVIEW_BOT_MCP_3_2026-08-12.md`](archive/START_PROMPT_SESSION_CODE_REVIEW_BOT_MCP_3_2026-08-12.md)

---

## 5. Открытые владельцу (не блокируют старт #1)

1. ~~Вердикт шага 0 (запуск vs отказ)~~ — **решено 2026-08-13: «запуск»**, валидаторы в работе (§0). Остаётся ждать **исхода**: он и есть вход для #4.
2. Одна дата Forced DP в трекере Wave 1.5. **Открыто:** в [`PLAN_WAVE1_5_DOGFOODING_2026-06-06.md`](PLAN_WAVE1_5_DOGFOODING_2026-06-06.md) дата стоит как «~2026-09-01» (тильда — и есть незафиксированность), а формула §7 даёт окно 09-06…10-06. До #4 свести к одной.
3. GO на опасные прогоны в #1: `trigger_*`, `force_resummarize`, `backfill_watchlist`, subscribe на реальный chat_id, `set_llm_config` / `reset_llm_config`, live Telegram bot smoke. **Дополнительно понадобится в fix-очереди:** R1 — прод-smoke с одноразовым `user`-токеном (по образцу BUG-093), R6 — пересчёт линковки после стоп-листа.

---

## 6. Downstream сессии #3 (добавлено 2026-08-13)

Ревью [`CODE_REVIEW_BOT_MCP_2026-08-12.md`](CODE_REVIEW_BOT_MCP_2026-08-12.md) отработало и передало вниз два артефакта:

| Кому | Что |
|---|---|
| fix-сессии | [`PLAN_REMEDIATION_BOT_MCP_2026-08-12.md`](PLAN_REMEDIATION_BOT_MCP_2026-08-12.md) — статус `accepted`, очередь `BUG-095 → R1 → R2 → BUG-094 → R4a → R4b → R3 → R5` + параллельный трек `BUG-097`, `BUG-098(b)`, `R6`. Находки заведены как `BUG-099…104` |
| #4 business | severity-карта поверхности: 2 High, 5 Medium, 5 Low, ноль Critical. Оба High — мультиарендность, оба латентны только потому, что не-admin-токенов на проде нет. Практический вход для #4: доступ второму арендатору нельзя продавать до закрытия BUG-099 и BUG-100 |
| #5 пути развития | два аргумента к выбору контракта Wave 3: несоблюдённая граница адаптеров (BUG-096 — `trigger_*` живут по ADR-0007, экспорт нет) и отсутствие описанного контракта tool-ответа (BUG-102 + BUG-098 (a) — три проявления одного пробела) |
