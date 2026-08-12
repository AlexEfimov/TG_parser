# Plan — Session #1: исполняемый аудит функционала

**Дата:** 2026-08-12 · **Тип:** plan → START_PROMPT · **Сессия:** audit #1 (pre-Wave 3)
**SoT scope:** [`DECISION_AUDIT_AND_STRATEGY_SESSIONS_2026-08-12.md`](DECISION_AUDIT_AND_STRATEGY_SESSIONS_2026-08-12.md) §1
**START_PROMPT:** [`START_PROMPT_SESSION_AUDIT_FUNCTIONAL_1_2026-08-12.md`](START_PROMPT_SESSION_AUDIT_FUNCTIONAL_1_2026-08-12.md)
**Ветка:** `cursor/audit-functional-1-7075` (только этот prefix)
**Артефакт:** `docs/notes/AUDIT_FUNCTIONAL_EXECUTABLE_<run-date>.md` — дата прогона, не планирования (≤3 стр. narrative + матрица + cost)

**Goal:** на проде доказать прогоном, какие заявленные возможности работают (MCP / HTTP / pipeline + bot-declaration), снять cost snapshot, зафиксировать матрицу — без правок кода и без docs-as-evidence.

---

## 0. Уже решено (не переоткрывать)

| Решение | Источник |
|---|---|
| Аудит = **исполнение**, не чтение `FUTURE_FEATURES` | DECISION §1 |
| Scope = §1.1 минимум; **не** весь F1…F12 | DECISION §1.1–§1.2 |
| Docs / code review / бизнес — другие сессии | DECISION #2–#5 |
| Опасные write/ops без owner GO → `not_run` | DECISION §5 |
| Артефакт ≤3 стр. narrative + таблицы | DECISION |

**Default GO (LOCKED, пока owner не скажет иначе):**

| Действие | GO? |
|---|---|
| MCP/HTTP **read** tools | ✅ |
| Workspaces smoke CRUD + cleanup (уникальное имя) | ✅ |
| Digests/watchlists: **list** + get_matches; subscribe только на owner chat_id | ❌ без chat_id → `not_run` |
| `export_channel` raw + status + **bounded download sample** + assert no `raw_payload` | ✅ |
| `get_topic_versions`, `get_topic_history_diff` | ✅ |
| `trigger_*`, `force_resummarize`, `backfill_watchlist`, `set_llm_config`, `reset_llm_config` | ❌ `not_run` |
| Bot live Telegram | ❌ `not_run`; bot-колонка = `TOOL_DECLARATIONS` only |

---

## 1. Pre-flight

```bash
git checkout main && git pull --ff-only origin main
git checkout -b cursor/audit-functional-1-7075
bash scripts/cursor_cloud_setup_prod_ssh.sh
ssh -o BatchMode=yes prod 'echo ok'
```

3. MCP prod (`tg-parser-vps`) — `whoami` / `list_channels`.
4. Reading list: DECISION §1; `FUTURE_FEATURES` сводная (гипотезы); [`S0_BASELINE_PROCESSING_METRICS_2026-07-07.md`](S0_BASELINE_PROCESSING_METRICS_2026-07-07.md); [ADR-0021](../adr/0021-backup-and-recovery-requirements.md) recovery cost.
5. Зафиксировать UTC start + `git rev-parse --short origin/main`.

**Stop conditions:** SSH или MCP недоступны → docs-артефакт с Gap, **без** выдуманных метрик/результатов; PR всё равно. Не ссылаться на «Gap #5» как на жанр — одна фраза выше достаточна.

---

## 2. Порядок прогона (обязательный)

Один проход A→I. Строку матрицы заполнять **сразу** после вызова.

Каждый tool из DECISION §1.1 = строка матрицы (или явный `not_run` + причина).

### Фаза A — identity + inventory

| # | Вызов | Ожидание |
|---|---|---|
| A1 | `whoami` | user/role/id |
| A2 | `list_channels` | ≥1 канал; сохранить 1–2 `channel_id` |
| A3 | `get_pipeline_status` | структура; fail_count / last success |
| A4 | `get_llm_config` | provider/model per stage (для cost phase H) |

### Фаза B — KB navigation

| # | Вызов | Notes |
|---|---|---|
| B1 | `list_topics` | 1–2 `topic_id` |
| B2 | `get_topic_details` | |
| B3 | `get_document` | иначе `partial` |
| B4 | `get_related_topics` | |
| B5 | `get_cross_channel_stats` | |

### Фаза C — Search / RAG (+ HTTP)

| # | Вызов | Notes |
|---|---|---|
| C1 | MCP `search_knowledge_base` mode=`hybrid` | |
| C2 | MCP `ask_question` | |
| C3–C4 | HTTP parity (ниже) | |

**HTTP (copy-paste на prod; ключ не писать в артефакт/PR):**

```bash
ssh prod 'cd /home/user/TG_parser && set -a && . ./.env && set +a && python3 - <<"PY"
import json, os, urllib.request
key = next(iter(json.loads(os.environ["API_KEYS"])))
def post(path, body):
    req = urllib.request.Request(
        "http://127.0.0.1:8000" + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "X-API-Key": key},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        print(path, r.status, r.read()[:500])
post("/api/v1/search", {"query": "диагностика", "mode": "hybrid", "limit": 3})
post("/api/v1/ask", {"question": "Что новое по диагностике?", "mode": "hybrid"})
PY'
```

Если `API_KEYS` отсутствует / 401 → HTTP = `not_run` + причина (не выдумывать pass).

### Фаза D — Workspaces F4-B (MCP-only; bot=`n/a`)

Имя: `audit_functional_1_smoke_<UTC_HHMM>` (уникальность при параллельных прогонах).

| # | Вызов | Notes |
|---|---|---|
| D1 | `list_workspaces` | baseline |
| D2 | `create_workspace` | smoke name |
| D3 | `add_workspace_source` + `list_workspace_sources` | |
| D4 | read tool с `workspace_id` | |
| D5 | rename → remove source → `delete_workspace` | **обязательный cleanup** |
| D6 | `list_workspaces` — smoke исчез | |

`list_all_workspaces` — только если admin; иначе `not_run`.

### Фаза E — Digests F6 / Watchlist F11

| # | Вызов | Notes |
|---|---|---|
| E1 | `list_digests` | |
| E2 | `list_watchlists` | |
| E3 | `get_watchlist_matches` | иначе `not_run` |
| E4 | scheduler evidence (Prom/logs) | не выдумывать |
| E5 | subscribe_* | только owner chat_id |
| E6 | `backfill_watchlist` | **not_run** без GO (§1.2) |

### Фаза F — Export F2 + Topics F5-C

| # | Вызов | Notes |
|---|---|---|
| F1 | `export_channel(..., level=raw, format=json)` | один канал |
| F2 | poll `get_export_status` → completed | затем **обязательно** bounded sample download |
| F3 | Assert: в скачанном JSON/NDJSON **нет** ключа `raw_payload` (и нет в status/tool result) | `python -c` / `rg` по файлу; без sample → не ставить `pass` на privacy |
| F4 | Export job/file после проверки **не purge** (нет безопасной cleanup-доки) — только отметить job_id | |
| F5 | `get_topic_versions` | |
| F6 | `get_topic_history_diff` | default genesis→current |
| F7 | `force_resummarize` | **not_run** без GO |

### Фаза G — Pipeline (observability, не trigger)

| # | Доказательство | Notes |
|---|---|---|
| G1 | `get_pipeline_status` (A3) | |
| G2 | Prometheus activity (S0 queries) | |
| G3 | optional scheduler log line | |
| G4 | `trigger_*` | **not_run** |

`pass` = свежий successful path evidence; `partial` = status ok, метрики старые; `fail` = broken.

### Фаза H — Cost snapshot

| Метрика | Как |
|---|---|
| Tokens 7d | на prod: `docker exec tg_parser_prometheus wget -qO- 'http://localhost:9090/api/v1/query?query=sum by (model,token_type) (increase(tg_parser_llm_tokens_total[7d]))'` (S0). Если пусто — since-restart / `/metrics` fallback |
| $/week | tokens × pinned prices ниже; зафиксировать дату |
| $/doc topicization | считать только если есть знаменатель (docs processed в окне); иначе **`not_recomputed`** — **не** цитировать archived prep |
| Recovery | ADR-0021: **$215–380** cite |
| Каналов | из `list_channels` |

**Pinned prices (override only with dated URL in artifact):** Anthropic Sonnet input/output и Haiku — взять из публичного pricing page на дату прогона **или** если model из `get_llm_config` иной — указать model + price row. Не угадывать.

### Фаза I — Bot column

`TOOL_DECLARATIONS` present/absent. Live = `not_run`. Итог: `partial` (declared) / `n/a` (MCP-only) / `fail` только если §1.1 tool ожидается в bot и отсутствует в declarations.

---

## 3. Формат артефакта

`docs/notes/AUDIT_FUNCTIONAL_EXECUTABLE_<run-date>.md`

```markdown
# AUDIT — исполняемый функционал (Session #1)
**Когда:** <UTC> · **main@:** <sha> · **Метод:** прогон

## TL;DR
- counts; ≤5 findings; cost one-liner

## Матрица
| возможность | MCP | bot | HTTP | pipeline | способ | вердикт | заметка |

## Cost
| метрика | значение | дата | команда/источник |

## Cleanup
- workspace smoke created/deleted; export job_id left in place

## Follow-ups
- bugs → propose BUG_LOG id (do not fix)
- not_run needing GO / chat_id
```

Агрегация `вердикт` — DECISION §1.3. Narrative ≤3 стр. вне таблиц. Без сырых JSON dumps; ключи/секреты не в файл.

---

## 4. Вердикты

| Вердикт | Когда |
|---|---|
| `pass` | успех + осмысленный результат; для F2 ещё privacy assert на sample |
| `fail` | ошибка / 5xx / утечка `raw_payload` / сломанный контракт / ожидаемый bot tool absent |
| `partial` | оговорка (bot declared-only; пустой валидный list; stale metrics) |
| `not_run` | нет GO / нет данных / stop / auth gap |
| `n/a` | поверхность не существует |

---

## 5. Hard OUT

- Правки `tg_parser/**`, тестов, промптов, ADR, contracts (кроме audit artifact).
- Сессии #2–#5.
- `trigger_*`, `force_resummarize`, `backfill_watchlist`, `set_llm_config`, `reset_llm_config` без GO.
- Subscribe без owner chat_id; live Telegram без GO.
- Docs-as-evidence; narrative >3 стр.; merge без PR; deploy; purge export jobs.

---

## 6. DoD

- [ ] Каждая возможность/tool из DECISION §1.1 — строка матрицы (или `not_run` + причина)
- [ ] Фазы A–I пройдены; F2 privacy assert на download sample (или явный non-pass)
- [ ] Cost-таблица заполнена (prices dated)
- [ ] Smoke workspace удалён (или fail cleanup записан)
- [ ] Артефакт + docs PR в `main`
- [ ] Финальный ответ: counts + path + PR + not_run needing GO

---

## 7. Downstream

| Сессия | Берёт из #1 |
|---|---|
| #2 docs | матрица-эталон |
| #3 code review | fail/partial bot/MCP |
| #4 business | cost + «что есть» |
| #5 | через #4 |
