# Plan — Session #1: исполняемый аудит функционала

**Дата:** 2026-08-12 · **Тип:** plan → START_PROMPT · **Сессия:** audit #1 (pre-Wave 3)
**SoT scope:** [`DECISION_AUDIT_AND_STRATEGY_SESSIONS_2026-08-12.md`](DECISION_AUDIT_AND_STRATEGY_SESSIONS_2026-08-12.md) §1
**START_PROMPT:** [`START_PROMPT_SESSION_AUDIT_FUNCTIONAL_1_2026-08-12.md`](START_PROMPT_SESSION_AUDIT_FUNCTIONAL_1_2026-08-12.md)
**Артефакт сессии:** `docs/notes/AUDIT_FUNCTIONAL_EXECUTABLE_2026-08-12.md` (≤3 стр. narrative + матрица + cost)

**Goal (одной строкой):** на проде доказать прогоном, какие заявленные пользовательские возможности реально работают (MCP / HTTP / pipeline), снять cost snapshot, зафиксировать матрицу — без правок кода и без «доказательств из docs».

---

## 0. Уже решено (не переоткрывать)

| Решение | Источник |
|---|---|
| Аудит = **исполнение**, не чтение `FUTURE_FEATURES` | DECISION §1; prep §1 |
| Scope = пользовательские поверхности + critical pipeline + cost; **не** весь F1…F12 | DECISION §1.1–§1.2 |
| Docs / code review / бизнес — **другие** сессии | DECISION порядок #2–#5 |
| Опасные write/ops без owner GO → `not_run` | DECISION §5 п.3 |
| Артефакт ≤3 стр. narrative + таблицы | DECISION § порядок |

**Default GO (LOCKED для сессии, пока owner не скажет иначе):**

| Действие | GO? |
|---|---|
| MCP/HTTP **read** tools | ✅ да |
| Workspaces: create/rename/add-source/remove/delete на **smoke-имени** + cleanup | ✅ да (как Wave1 watch) |
| Digests/watchlists: **list** + get_matches; subscribe только на chat_id, который дал owner | ❌ без chat_id → `not_run` |
| `export_channel` level=`raw` на **одном** существующем канале + poll status | ✅ да (проверить отсутствие `raw_payload`) |
| `trigger_*`, `force_resummarize`, `set_llm_config` / `reset_llm_config` | ❌ `not_run` |
| Bot live Telegram smoke | ❌ `not_run` (нет driver); bot-колонка = declaration presence → `partial` / `n/a` |

---

## 1. Pre-flight

1. Sync `main`, ветка `docs/audit-functional-1-7075` (или `cursor/audit-functional-1-7075`).
2. `bash scripts/cursor_cloud_setup_prod_ssh.sh` → `ssh -o BatchMode=yes prod 'echo ok'`.
3. MCP prod: сервер `tg-parser-vps` (или локальный `tg-parser`, если указывает на тот же бэкенд) — `whoami` / `list_channels` smoke.
4. Прочитать только:
   - DECISION §1 (этот scope);
   - сводную таблицу `FUTURE_FEATURES.md` — **как гипотезы строк**, не как истину;
   - [`S0_BASELINE_PROCESSING_METRICS_2026-07-07.md`](S0_BASELINE_PROCESSING_METRICS_2026-07-07.md) — шаблон PromQL для cost;
   - [ADR-0021](../adr/0021-backup-and-recovery-requirements.md) § стоимость recovery (~$215–380) — для cost-таблицы «порядок величины», не пересчитывать с нуля без данных.
5. Зафиксировать UTC timestamp старта и `git rev-parse --short origin/main`.

**Stop conditions:** SSH fail → артефакт с Gap (как Phase-1 Gap #5), без выдуманных метрик. MCP auth fail → то же для MCP-строк.

---

## 2. Порядок прогона (обязательный)

Один проход сверху вниз. Каждая строка матрицы заполняется **сразу** после вызова. Не копить «потом опишу».

### Фаза A — identity + inventory (5 мин)

| # | Вызов | Ожидание |
|---|---|---|
| A1 | `whoami` | user/role/id |
| A2 | `list_channels` | ≥1 канал; сохранить 1–2 `channel_id` для дальнейших шагов |
| A3 | `get_pipeline_status` | структура ответа; fail_count / last success если есть |
| A4 | `get_llm_config` | read-only; записать provider/model per stage |

### Фаза B — KB navigation (read)

| # | Вызов | Notes |
|---|---|---|
| B1 | `list_topics` (без workspace / с лимитом) | взять 1–2 `topic_id` |
| B2 | `get_topic_details(topic_id)` | |
| B3 | `get_document` на doc из topic/bundle если доступен | иначе `partial` |
| B4 | `get_related_topics(topic_id)` | |
| B5 | `get_cross_channel_stats` | |

### Фаза C — Search / RAG (+ HTTP parity)

| # | Вызов | Notes |
|---|---|---|
| C1 | `search_knowledge_base` mode=`hybrid`, короткий query по домену каналов | |
| C2 | `ask_question` тот же query-класс | LLM-path; зафиксировать latency/ошибку |
| C3 | HTTP `POST /api/v1/search` (через `ssh prod` curl localhost API) | parity sample; auth как на проде |
| C4 | HTTP ask-эквивалент, если endpoint доступен с тем же auth | иначе `not_run` + причина |

### Фаза D — Workspaces F4-B (MCP-only surface)

Bot **не** имеет workspace tools — в матрице bot = `n/a`.

| # | Вызов | Notes |
|---|---|---|
| D1 | `list_workspaces` | baseline count |
| D2 | `create_workspace(name="audit_functional_1_smoke")` | |
| D3 | `add_workspace_source` + `list_workspace_sources` | один реальный channel_id |
| D4 | read tool с `workspace_id` (напр. `list_topics` или `list_channels`) | сужение scope |
| D5 | `rename_workspace` → `remove_workspace_source` → `delete_workspace` | **обязательный cleanup** |
| D6 | `list_workspaces` — smoke исчез | |

Admin-only `list_all_workspaces` — только если `whoami` = admin; иначе `not_run`.

### Фаза E — Digests F6 / Watchlist F11

| # | Вызов | Notes |
|---|---|---|
| E1 | `list_digests` | |
| E2 | `list_watchlists` | |
| E3 | `get_watchlist_matches` на существующий interest_id если есть | иначе `not_run` |
| E4 | Prod evidence scheduler: Prometheus/logs — последний successful digest/watchlist tick | ssh + PromQL / docker logs; не выдумывать |
| E5 | subscribe_* | **только** при owner chat_id; иначе `not_run` |

### Фаза F — Export F2 + Topics F5-C

| # | Вызов | Notes |
|---|---|---|
| F1 | `export_channel(channel_id, level=raw, format=json)` | |
| F2 | poll `get_export_status` до completed/failed | скачать **не** обязательно; проверить контракт: нет `raw_payload` в tool result / status |
| F3 | `get_topic_versions(topic_id)` | topic с историей предпочтителен |
| F4 | `force_resummarize` | **not_run** без GO |

### Фаза G — Pipeline path (observability, не trigger)

| # | Доказательство | Notes |
|---|---|---|
| G1 | `get_pipeline_status` уже в A3 | |
| G2 | Prometheus: recent activity — messages processed / topicization / LLM tokens (7d или since-restart) | шаблон S0 |
| G3 | Опционально: docker logs scheduler last success line | |
| G4 | `trigger_*` | **not_run** без GO |

Вердикт pipeline: `pass` если есть свежий successful path evidence; `partial` если status ok, но метрики старые/неясные; `fail` если pipeline broken.

### Фаза H — Cost snapshot

В той же сессии, не отдельным документом:

| Метрика | Как получить |
|---|---|
| Token burn 7d (или since-restart, если 7d пуст) | PromQL `sum by (model, token_type) (increase(tg_parser_llm_tokens_total[7d]))` на prod Prometheus |
| Оценка $/неделя | tokens × актуальные цены провайдера (зафиксировать price source + дату) |
| $/документ топикизации | если есть docs processed / topics created за окно — иначе порядок величины из prep (~$0.002) с пометкой «не пересчитано / пересчитано» |
| Recovery order-of-magnitude | ADR-0021: **$215–380** — цитировать, не переизобретать |
| Каналов в работе | из `list_channels` |

### Фаза I — Bot surface column (без Telegram)

Для каждой возможности из матрицы, где есть bot tool:

- `rg` / чтение `TOOL_DECLARATIONS` в `bot/tools.py` → declaration **present / absent**.
- Live bot = `not_run` (нет driver).
- Итог колонки bot: `partial` (declared, unexecuted) или `n/a` (MCP-only, напр. workspaces).

---

## 3. Формат артефакта

Файл: `docs/notes/AUDIT_FUNCTIONAL_EXECUTABLE_2026-08-12.md`

```markdown
# AUDIT — исполняемый функционал (Session #1)

**Когда:** <UTC> · **main@:** <sha> · **Поверхности:** MCP / HTTP / pipeline / bot-decl
**Метод:** прогон; docs не evidence.

## TL;DR
- pass / fail / partial counts
- 3–5 главных находок (одной строкой каждая)
- cost: $/week order, recovery cite

## Матрица
| возможность | MCP | bot | HTTP | pipeline | способ | вердикт | заметка |

## Cost
| метрика | значение | дата | команда/источник |

## Cleanup
- что создано и удалено (workspace smoke и т.п.)

## Follow-ups (не чинить здесь)
- баги → предложить BUG_LOG id; не фиксить
- not_run с причиной (нужен GO / chat_id)
```

**Лимит:** ≤3 страницы narrative вне таблиц. Без копипасты сырых JSON в файл (краткий excerpt в заметке ок).

---

## 4. Вердикты

| Вердикт | Когда |
|---|---|
| `pass` | вызов успешен, результат осмыслен (не пустая ошибка-обёртка) |
| `fail` | ошибка, 5xx, пустой critical path, утечка `raw_payload`, сломанный контракт |
| `partial` | работает с оговоркой (напр. bot только declared; HTTP auth не проверен; пустой но валидный список) |
| `not_run` | нет GO / нет данных / stop condition |
| `n/a` | поверхность не существует для этой возможности |

---

## 5. Hard OUT

- Правки `tg_parser/**`, тестов, промптов, ADR, contracts (кроме docs-артефакта аудита).
- Сессии #2–#5 (docs audit, code review, business, Wave 3).
- `trigger_*`, `force_resummarize`, `set/reset_llm_config` без явного GO в чате.
- Subscribe digest/watchlist на произвольный chat_id.
- «Доказательство» цитатой из FUTURE_FEATURES / USER_GUIDE.
- Артефакт >3 стр. narrative или второй параллельный SoT.
- Merge в `main` без PR; deploy.

---

## 6. DoD

- [ ] Матрица заполнена по фазам A–I (пустые строки только как `not_run` с причиной)
- [ ] Cost-таблица заполнена
- [ ] Smoke workspace удалён (или зафиксирован fail cleanup)
- [ ] Артефакт в `docs/notes/AUDIT_FUNCTIONAL_EXECUTABLE_2026-08-12.md`
- [ ] PR в `main` (docs-only)
- [ ] В конце ответа агента: counts pass/fail/partial/not_run + путь к артефакту

---

## 7. Связь с следующими сессиями

| Сессия | Что забирает из #1 |
|---|---|
| #2 docs | матрица как эталон сверки |
| #3 code review | fail/partial на bot/MCP → приоритет handlers / tools |
| #4 business | cost + «что реально есть» |
| #5 Wave 3 | не напрямую; через #4 |
