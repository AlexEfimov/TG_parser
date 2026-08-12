# Decision — порядок и scope аудитов / стратегии (pre-Wave 3)

**Тип:** decision-log планирующей сессии. Заменяет prep [`archive/PLANNING_AUDIT_AND_STRATEGY_PREP_2026-08-12.md`](archive/PLANNING_AUDIT_AND_STRATEGY_PREP_2026-08-12.md).
**Дата:** 2026-08-12.
**Не является:** отчётом аудита, контрактом Wave 3, START_PROMPT реализации.

**Правило исполнения:** один пункт таблицы = одна сессия агента (кроме шага 0). В сессии только её строка: вход → работа → артефакт в лимите. Не смешивать с соседними шагами.

---

## 0. Фон (не сессия агента)

**Запустить до сессии #1** (календарная задержка):

- попытка поднять 2–3 внешних валидатора Wave 1.5 **и** минимальный market scan, **или**
- явный записанный отказ от плеч 2A/2B/2C (законно для single-operator self-host).

**Артефакт:** ≤1 стр. decision-log (запуск / отказ + обоснование).  
Без этого сессия #4 снова опирается на `0/0/0` как на «измерение».

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

### 1.1 Входит (обязательный минимум)

| Область | Что прогонять | Доказательство |
|---------|---------------|----------------|
| **Навигация / KB** | `list_channels`, `list_topics`, `get_topic_details`, `get_document`, `get_related_topics`, `get_cross_channel_stats` | MCP (+ bot-эквивалент, если есть) |
| **Search / RAG** | `search_knowledge_base` (hybrid), `ask_question` | MCP; при parity — HTTP |
| **Workspaces F4-B** | `list_workspaces` / create-rename-delete / add-remove source / read tools с `workspace_id` | MCP |
| **Digests F6** | `list_digests`; subscribe/unsubscribe только если безопасно на тестовом chat_id | MCP (+ scheduler health / последний успешный run на проде) |
| **Watchlist F11** | `list_watchlists`, `get_watchlist_matches`; subscribe только на безопасном chat_id | MCP (+ факт матчей/алертов на проде, если есть) |
| **Export F2** | `export_channel` level=`raw` + `get_export_status` (без утечки `raw_payload`) | MCP |
| **Topics F5-C** | `get_topic_versions`; `force_resummarize` — admin-only, по GO или dry observation | MCP |
| **Channel ops** | `list_channels` status; `get_pipeline_status`; trigger_* — **не** стрелять в прод без GO (достаточно status + метрики) | MCP / Prometheus |
| **Pipeline path** | Доказательство живого path: ingest → process → topicization → (digest \| watchlist hook) | метрики / логи / последний successful tick на проде |
| **LLM config surface** | `get_llm_config` (read-only); set/reset — **не** в аудите без GO | MCP |
| **Cost snapshot** | $/документ топикизации; $/неделя на текущий набор каналов; порядок recovery cost (из ADR-0021 / свежий замер) | таблица в том же артефакте |

### 1.2 Не входит в #1

- F3, F7, F8, F10, F12 и прочий нереализованный / commercial бэклог (кроме пометки «не заявлено как done»).
- F-Prereq-1 (legal) — не исполняемый функционал; учёт в #4.
- Глубокий security audit F9 (отдельный жанр); в #1 — только smoke доступа/изоляции, если всплывёт на прогоне.
- Правка документации и кода.

### 1.3 Формат строки матрицы

`возможность | поверхность (MCP/bot/HTTP/pipeline) | способ прогона | pass / fail / partial / not_run | заметка`

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
- Каждый новый артефакт **вытесняет или архивирует** устаревший указатель; не плодить параллельные SoT.
- Числа в текстах — порядок величины + дата + команда пересчёта (как в prep §5), не вечные перечни файлов.
- Prep перенесён в [`archive/PLANNING_AUDIT_AND_STRATEGY_PREP_2026-08-12.md`](archive/PLANNING_AUDIT_AND_STRATEGY_PREP_2026-08-12.md) (**SUPERSEDED**); этот файл — единственный SoT по порядку/scope.

---

## 4. START_PROMPT

На каждую сессию #1–#5 — **короткий** `START_PROMPT_*` (цель, вход, scope из этого файла, лимит артефакта, out-of-scope). Этот decision = SoT scope; второй prep не писать.

---

## 5. Открытые владельцу (не блокируют старт #1)

1. Вердикт шага 0 (запуск vs отказ) — желательно до #4.
2. Одна дата Forced DP в трекере Wave 1.5.
3. GO на опасные прогоны в #1: `trigger_*`, `force_resummarize`, subscribe на реальный chat_id, `set_llm_config`.
