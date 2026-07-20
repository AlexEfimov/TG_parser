# START PROMPT — Session ε+ζ: internal-quality fill + F5-C #15 TTL skeleton (docs)

**Дата:** 2026-07-20 · **Тип:** combo — code (ε1 tiny UX) + docs (ε2/ε3 + ζ skeleton) · **Ветка:** `main` (или feature-ветка от актуального `main`)

**Goal (одной строкой):** закрыть unblocked post-γ closeout default — **ε** (DF-1 pytest UX + dogfood-discipline note + γ1′ BUG-008 recurrence checklist) **и** **ζ** (docs-only contract skeleton на F5-C #15 **TTL/retention**), **без** T7/δ (gate-response после окончания watch) и **без** реализации TTL в коде.

> Рабочий режим (нормативно, [`AGENTS.md`](../../AGENTS.md)): `git commit` / PR — **только** по явному запросу пользователя; PR = merge-commit + `--delete-branch`. Никаких правок `docs/methodology/**`. Правки `pyproject.toml` / `requirements.txt` — **не нужны** для этой сессии. Уважать `docs/adr/` (accepted) и `docs/contracts/` (JSON Schema нерушимы). Прод-мутации / bump `RESUMMARIZE_MAX_AGE_DAYS` — **OUT** (это track δ, отдельная сессия после watch).

**Prerequisite SoT:** [`DRAFT_NEXT_CONTRACT_POST_GAMMA_CLOSEOUT_2026-07-20.md`](DRAFT_NEXT_CONTRACT_POST_GAMMA_CLOSEOUT_2026-07-20.md) §2 Track ε / ζ / §3 default. Если DRAFT ещё не на `main` — сначала приземлить его (docs PR), затем эту сессию; либо вести ε+ζ на ветке, где DRAFT уже есть.

**Последовательность владельца (нормативно для агента):**  
1) **эта сессия** = skeleton docs (ζ) + internal fill (ε)  
2) **следующая** = T7/δ после завершения watch (+24ч мин / +48ч полный) — **не начинать здесь**

---

## 0. TL;DR

| Кусок | Что сделать | Тип |
|---|---|---|
| **ζ** | Contract skeleton: F5-C #15 TTL/retention для `topic_card_versions` — goal, options, blast-radius, acceptance, out-of-scope; **без** Alembic/кода | docs |
| **ε1** | DF-1: watchlist-тесты под system Python без `pymorphy3`/`structlog` → **skip/clear**, не hard-fail | code+test |
| **ε2** | Dogfood-discipline renew: короткая process-note (PLAN_WAVE1_5 и/или friction log) | docs |
| **ε3** | γ1′ checklist: что смотреть при BUG-008 recurrence (lifecycle logs vs transport H3) | docs |
| **δ / T7** | OUT — отдельная сессия после watch | — |

**Recommended session order:** ζ (docs skeleton) → ε3 → ε2 → ε1 (code last, quality gate).

---

## 1. Контекст

Источник треков: [`DRAFT_NEXT_CONTRACT_POST_GAMMA_CLOSEOUT_2026-07-20.md`](DRAFT_NEXT_CONTRACT_POST_GAMMA_CLOSEOUT_2026-07-20.md).  
γ3 closeout: [`REPORT_GAMMA3_DEBT_AUDIT_2026-07-20.md`](REPORT_GAMMA3_DEBT_AUDIT_2026-07-20.md) — DF-1 единственный promote-кандидат; DF-2/DF-3 не promote.  
Post-Wave-2 SoT: [`ROADMAP` § Post-Wave-2](ROADMAP_KARPATHY_LIKE_LIVING_KB.md). Signals 2A/2B/2C = 0 → product impl (TTL code) не стартуем; skeleton — да.

**Почему ζ = TTL/retention (не Bot tools):** ops-adjacent после T7 freshness knob; MVP хранит все `topic_card_versions` (FUTURE_FEATURES F5-C); issue [#15](https://github.com/AlexEfimov/TG_parser/issues/15) item TTL.

**Почему ε1 сейчас:** operator friction задокументирован (DF-1, BREAK/START_PROMPT notes); system Python → hard-fail на import → ложная тревога «N failed».

---

## 2. Anchors (перечитать перед правкой)

### 2.1 ε1 — DF-1 pytest UX

| Якорь | Файл | Примечание |
|---|---|---|
| Lazy import `pymorphy3` | [`tg_parser/services/watchlist_tokenizer.py`](../../tg_parser/services/watchlist_tokenizer.py) | ~105 `from pymorphy3 import MorphAnalyzer` |
| `simplemma` Latin path | то же | ~136 |
| Watchlist tests (затронуты) | `tests/test_watchlist_*.py`, др. импортирующие tokenizer/service | hard-fail без deps |
| Shared fixtures | [`tests/conftest.py`](../../tests/conftest.py) | кандидат на early skip / dependency probe |
| DF-1 narrative | [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) § Wave 1.5 Dogfood Friction Log DF-1 | disposition KEEP / promote UX |
| Precedent note | [`START_PROMPT_BREAK_2026-06-25.md`](START_PROMPT_BREAK_2026-06-25.md), [`START_PROMPT_SESSION_I_BUG065…`](START_PROMPT_SESSION_I_BUG065_JSON_PARSE_2026-06-25.md) | «use `.venv/bin/python` ONLY» |

**Method-selection (DECIDED for session — не переоткрывать без причины):**  
prefer **central probe in `tests/conftest.py`** (или маленький `tests/_dep_guards.py` imported from conftest): if `pymorphy3` / `structlog` missing → `pytest.importorskip` / module-level skip for watchlist-related modules **or** clear `pytest.skip` with message pointing to `.venv`.  
**Reject:** silently changing production tokenizer to no-op without pymorphy3 (would mask real env bugs on prod).  
**Reject:** documenting-only (уже есть в BREAK prompts; нужен UX в pytest).

Перечитать: какие именно test modules fail under system Python — воспроизвести один раз (`python3 -m pytest tests/test_watchlist_score.py -q` вне venv) и зафиксировать список в PR.

### 2.2 ε2 — dogfood discipline

| Якорь | Файл |
|---|---|
| Cadence / R-4 prune | [`PLAN_WAVE1_5_DOGFOODING_2026-06-06.md`](PLAN_WAVE1_5_DOGFOODING_2026-06-06.md) |
| Friction log home | [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) § Wave 1.5 Dogfood Friction Log |
| γ3 disposition | [`REPORT_GAMMA3_DEBT_AUDIT_2026-07-20.md`](REPORT_GAMMA3_DEBT_AUDIT_2026-07-20.md) §3 |

**DECIDED default for ε2 text:** renew lightweight discipline («log friction when felt; no hard ≥1/week quota if solo-bias») — не раздувать process. Owner может переписать на «accept R-5» при ревью.

### 2.3 ε3 — γ1′ BUG-008 checklist

| Якорь | Файл |
|---|---|
| BUG-008 entry + mitigation + decision rule | [`BUG_LOG.md`](BUG_LOG.md) BUG-008 (esp. Update 2026-06-14: `guard_read_tool`, lifecycle logs, H3 transport) |
| Guard / middleware | [`tg_parser/mcp_server.py`](../../tg_parser/mcp_server.py) — `guard_read_tool`, `_RequestLifecycleMiddleware` |
| Tests | `tests/test_mcp_server.py::TestReadToolTimeoutGuard` |

**Выход ε3:** короткий runbook-style checklist (новый note **или** секция в существующем MCP/ops runbook — выбрать минимальный дом; prefer `docs/runbooks/` рядом с MCP/prod SSH если есть, иначе `docs/notes/BUG008_RECURRENCE_CHECKLIST.md`):

1. Reproduce? (N× `list_channels`)  
2. `docker logs tg_parser_mcp` — есть ли `mcp.request.response_sent` / `mcp.tool.timeout` / `mcp.tool.end`?  
3. Decision rule: response_sent + client hang ⇒ **transport/client (H3)**; tool.end never ⇒ **server stall** → `pg_stat_activity`  
4. Fallback: direct SQL via `ssh prod` / `docker exec tg_parser_postgres`  
5. **Не** «чинить» client timeout в этом репо

### 2.4 ζ — TTL/retention skeleton (docs-only)

| Якорь | Файл |
|---|---|
| #15 TTL item | GitHub issue #15; FUTURE_FEATURES F5-C «Что НЕ входит в MVP» |
| Table | `topic_card_versions` — schema в F5-C docs / Alembic history |
| Runbook F5-C | [`F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md) (versions growth note) |
| ADR-0006 | [#1 persistent entities, #2 provenance, #4 idempotency](../adr/0006-karpathy-like-living-kb-principles.md) |

**Deliverable ζ (DECIDED shape):** один файл  
`docs/notes/SKELETON_F5C_TTL_RETENTION_TOPIC_CARD_VERSIONS_2026-07-20.md`  
(или `docs/notes/START_PROMPT_F5C_TTL_RETENTION_SKELETON_2026-07-20.md` — skeleton **не** полный impl START_PROMPT; пометить `SKELETON / not ready to implement`).

Обязательные секции skeleton:

1. Goal one-liner  
2. Problem (unbounded `topic_card_versions` growth)  
3. Options (минимум 2–3): e.g. time-TTL vs keep-last-N vs hybrid; soft-delete vs hard DELETE  
4. Karpathy checklist impact (provenance: не терять audit без явной политики)  
5. Blast-radius (Alembic? MCP `get_topic_versions`? bot?)  
6. Acceptance / metrics to watch before/after  
7. Out of scope (Bot tools, diff API, Wave E, F11 HTTP, **code this session**)  
8. Open questions for owner GO before impl START_PROMPT  

**Запрещено в ζ:** Alembic migration, Settings knobs в коде, удаление rows на проде, «Wave 3» naming.

---

## 3. Scope — детально

### ζ (docs) — F5-C #15 TTL skeleton

- Написать skeleton-файл (§2.4).  
- Одна строка-pointer в FUTURE_FEATURES F5-C TTL bullet → skeleton (не переписывать весь Level C).  
- ROADMAP Post-Wave-2 **Next** / DRAFT ε+ζ: при необходимости отметить «ζ skeleton landed» — только если меняете статус; иначе pointer из skeleton на DRAFT достаточно.

### ε3 (docs) — BUG-008 recurrence checklist

- Checklist-файл/секция (§2.3).  
- Одна строка в BUG_LOG BUG-008 **Linked** или Update-row → checklist (не менять status `open`).

### ε2 (docs) — dogfood discipline

- Короткий banner/абзац в PLAN_WAVE1_5 **или** в шапке Dogfood Friction Log (не оба развёрнуто — один дом).  
- Зафиксировать решение: renew lightweight vs accept solo-bias (default = renew lightweight).

### ε1 (code+test) — DF-1

- Central dependency guard (§2.1).  
- Тест на сам guard (если уместно): под mock missing module → skip path; с venv deps → suite green.  
- Обновить DF-1 disposition в FUTURE_FEATURES: «UX shipped» + commit/PR ref when done.  
- **Не** менять scoring / tokenizer production behavior when pymorphy3 отсутствует на prod (prod image must keep deps).

---

## 4. Out of scope (жёстко)

- **Track δ / T7:** bump `RESUMMARIZE_MAX_AGE_DAYS`, prod `.env`, `docker compose up -d` для knob — **следующая сессия** после +24ч/+48ч watch.  
- Реализация TTL (Alembic, cron purge, Settings).  
- Wave E, F11 HTTP CRUD, webhook 2A, Bot tools / diff API.  
- Reopen ADR-0016 Phase 1.  
- «Fix» Cursor MCP client timeout (вне репо).  
- `docs/methodology/**`, `pyproject.toml` / `requirements.txt` (если ε1 потребует test-only helper — OK без dep changes).

---

## 5. Acceptance criteria

**ζ:**
- [ ] Skeleton-файл с секциями §2.4 существует; явно помечен docs-only / not-impl.  
- [ ] FUTURE_FEATURES TTL bullet → pointer на skeleton.  
- [ ] Ноль миграций / ноль prod SQL.

**ε3:**
- [ ] Checklist воспроизводит decision rule из BUG-008 Update 2026-06-14.  
- [ ] BUG_LOG linked; status BUG-008 остаётся `open`.

**ε2:**
- [ ] Одна process-note (renew lightweight default); без раздувания cadence.

**ε1:**
- [ ] Под system Python без pymorphy3: watchlist-related tests **skip** (или clear module skip), не cascade hard-fail.  
- [ ] Под `.venv` / CI: full suite без регрессии (`uv run pytest -q`; PR-standard `TEST_POSTGRES=1` если трогали conftest shared paths).  
- [ ] DF-1 disposition updated.

**Общее:**
- [ ] `uv run ruff check .` + `ruff format --check .` (если есть code).  
- [ ] δ/T7 не тронут.  
- [ ] Self-review diff; commit/PR только по запросу.

---

## 6. Quality gate

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
# если conftest / shared fixtures:
TEST_POSTGRES=1 uv run pytest -q
# DF-1 negative check (system python — expect skip, not fail):
python3 -m pytest tests/test_watchlist_score.py -q --collect-only  # or minimal run; document outcome
```

---

## 7. Decisions (уже приняты владельцем 2026-07-20)

1. Session order: **ε+ζ now**; **δ/T7 after watch** — не смешивать.  
2. ζ sub-item = **TTL/retention** (не Bot tools).  
3. ε2 default = renew lightweight discipline.  
4. ε1 = pytest UX only; production tokenizer deps unchanged.  
5. Commit/PR — по явному запросу после готовности.

---

## 8. Ссылки

- Decision-input: [`DRAFT_NEXT_CONTRACT_POST_GAMMA_CLOSEOUT_2026-07-20.md`](DRAFT_NEXT_CONTRACT_POST_GAMMA_CLOSEOUT_2026-07-20.md)  
- γ3 report: [`REPORT_GAMMA3_DEBT_AUDIT_2026-07-20.md`](REPORT_GAMMA3_DEBT_AUDIT_2026-07-20.md)  
- ROADMAP: [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) § Post-Wave-2  
- T7 watch (для следующей сессии δ): [`C2_T7_LIVE_SNAPSHOT_2026-07-20.md`](C2_T7_LIVE_SNAPSHOT_2026-07-20.md), runbook §T7  
- House format ref: [`START_PROMPT_FIX_F11_SEMANTIC_AVAILABLE_GUARD_T6_2026-06-15.md`](START_PROMPT_FIX_F11_SEMANTIC_AVAILABLE_GUARD_T6_2026-06-15.md)  
- ADR-0006, issue #15, BUG_LOG BUG-008  
