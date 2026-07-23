# SKELETON — F5-C #15 item #2 diff API (`get_topic_history_diff`)

> **SKELETON / docs-only / decisions baked (2026-07-23).**
> Contract sketch for GitHub issue [#15](https://github.com/AlexEfimov/TG_parser/issues/15) item **#2 diff API** ([`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) L798).
> No new repo write-path, no schema change, no migration, no prod SQL in the impl-session.
> **All 6 owner-decisions resolved (§8 Decisions final).** START_PROMPT unblocked: [`START_PROMPT_SESSION_F5C_DIFF_API_2026-07-23.md`](START_PROMPT_SESSION_F5C_DIFF_API_2026-07-23.md).

**Дата:** 2026-07-23
**Branch:** `feature/f5c-ttl-retention-topic-card-versions` (docs-only planning; **не** трогать TTL-код из PR #346 — этот скелет только добавляет новые planning-заметки).
**Anchors:** [ADR-0018](../adr/0018-topic-card-versions-retention.md) (retention interaction — gaps в `version_no`); [`PLAN_SESSION_F5C_TTL_RETENTION_2026-07-22.md`](PLAN_SESSION_F5C_TTL_RETENTION_2026-07-22.md); [`F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md).

---

## 1. Goal (one-liner)

Turn stored version history into a **visible evolution**: a read-only MCP + CLI tool `get_topic_history_diff(topic_id, version_a, version_b)` that compares two versions of a topic's evolving summary and shows what changed — the `summary` text delta **plus** the `scope_in` / `scope_out` set deltas — reading from the same append-only `topic_card_versions` history table as `get_topic_versions`.

---

## 2. Context / why-now

- **Diff — естественный payoff версионирования.** F5-C уже пишет по одной строке в `topic_card_versions` на каждый успешный re-summarize (snapshot *предыдущего* состояния `TopicCard`: `summary` / `scope_in` / `scope_out` + LLM-provenance). Единственный read-path сегодня — `get_topic_versions` (список версий), который показывает **что было**, но не **что изменилось между двумя точками**.
- **TTL только что ограничил историю (ADR-0018, PR #346).** Retention делает hard-DELETE строк вне keep-last-N=50 **AND** старше M дней **AND** `version_no > 1`. Двойной floor (recent-N + genesis-pin `version_no=1`) **гарантирует**, что «genesis → recent» diff всегда осуществим: genesis (v1) и последние N присутствуют навсегда; удаляются только промежуточные версии ⇒ `version_no` может иметь **gaps**. Diff-дизайн обязан быть robust к gaps (см. §4).
- **Issue #15 item #6 (TTL) закрыт до diff (priority decision, TTL-plan §9).** Теперь history bounded, но по-прежнему meaningful на концах — идеальный момент для diff: он превращает «мы храним версии» в «пользователь видит, как тема менялась».

**Единственный read-path истории:** `TopicCardVersionRepo.list_by_topic` → MCP `get_topic_versions` + CLI `topic versions`. Diff добавляет **второй read-only** consumer той же таблицы; ни один write-path не затрагивается.

---

## 3. Anchors (verified — открыты и подтверждены 2026-07-23)

| Якорь | Файл | Строка | Роль в diff-slice |
|---|---|---|---|
| Domain model `TopicCardVersion` | [`domain/models.py`](../../tg_parser/domain/models.py) | **L431** | shape для diff-inputs: `version_no`, `summary`, `scope_in`, `scope_out`, provenance, `created_at` |
| Repo read-path `list_by_topic` | [`storage/sqlalchemy/topic_card_version_repo.py`](../../tg_parser/storage/sqlalchemy/topic_card_version_repo.py) | **L72** | reuse-кандидат: newest-first, `LIMIT` (default 50); фильтровать до 2 версий в Python **или** новый `get_two_versions` |
| Repo `count` | same | **L166** | не нужен diff'у; ссылка на паттерн |
| Repo `purge_stale` (TTL, PR #346) | same | **L102** | **НЕ трогать** — diff read-only; gaps приходят отсюда |
| Port ABC `TopicCardVersionRepo` | [`storage/ports.py`](../../tg_parser/storage/ports.py) | **L828** (`list_by_topic` L842) | если новый метод — добавить `@abstractmethod` рядом |
| MCP tool `get_topic_versions` (surface pattern to mirror) | [`mcp_server.py`](../../tg_parser/mcp_server.py) | **L2604** (`def` L2606) | зеркалить: `@guard_read_tool`, `resolve_mcp_user`, `card = get_by_id`, `assert_topic_access(user, card.sources)`, `model_dump(mode="json")` |
| Access enforcement `assert_topic_access` | [`auth/ownership.py`](../../tg_parser/auth/ownership.py) | **L50** (`PermissionDenied` L18) | visibility: доступ если хотя бы один из `card.sources` виден; admin passes |
| Visibility precedent `get_topic_details` | [`mcp_server.py`](../../tg_parser/mcp_server.py) | **L1408** (inline check L1440-1442) | тот же mental model видимости топика |
| CLI subapp `topic versions` | [`cli/topic_cmd.py`](../../tg_parser/cli/topic_cmd.py) | **L29** (`purge-versions` L97, `resummarize` L202) | зеркалить для нового `topic diff` command |
| Write-path (НЕ ломать) | [`services/resummarization_service.py`](../../tg_parser/services/resummarization_service.py) | **L582-618** (`version_no = card.summary_version` L588) | объясняет семантику `version_no` (см. §4) |
| FUTURE_FEATURES diff bullet | [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) | **L798** (MCP/CLI surface L782-783) | описание фичи; обновить → DONE/partial в impl |
| Retention interaction | [ADR-0018](../adr/0018-topic-card-versions-retention.md) | §4 double-floor / L110-112 | «gaps = policy, не потеря; genesis всегда present ⇒ не 500» |

---

## 4. Критическая семантика `version_no` (must-read перед дизайном)

Write-path ([`resummarization_service.py`](../../tg_parser/services/resummarization_service.py) L588) пишет `version_no = card.summary_version` — то есть snapshot **предыдущего** состояния, взятый *до* инкремента `summary_version`. Следствия для diff:

1. **Genesis = `version_no = 1`** — это snapshot summary из topicization (первый materialized row, пишется при *первом* re-summarize). TTL genesis-pin гарантирует его вечное присутствие ⇒ «genesis → …» всегда осуществим.
2. **Dual-source «current» (DECIDED — both_allowed, §8 D4).** Таблица версий хранит snapshot'ы **предыдущего** состояния (`version_no` = v1..v(N−1)); **живой текущий** summary (vN) лежит **только** на `topic_cards.summary` / `scope_in` / `scope_out` (`summary_version = N`) и в таблице версий **отсутствует**. Diff поддерживает **обе** правые стороны:
   - **архивная пара** — оба `version_no` из `topic_card_versions` (snapshots v1..v(N−1));
   - **`current`/`latest`** токен справа → читает **живую карточку** (`topic_cards`, через `card_repo.get_by_id`, те же поля, что отдаёт [`get_topic_details`](../../tg_parser/mcp_server.py) L1463-1465).
   `get_topic_versions` уже возвращает `current_version` (= `card.summary_version`) **отдельно** от `versions[]`. **Default-пара при отсутствии args = genesis (v1) → current (live card).**
3. **Gaps робастность (ADR-0018, DECIDED §8 D5).** После purge промежуточные `version_no` могут отсутствовать. Запрос purged/несуществующего `version_no` (любая сторона) → **типизированный not-found** («version not found / reclaimed by retention policy»), **не** 500. Genesis (v1) + последние N всегда present ⇒ default-пара genesis→current **всегда** резолвится.

---

## 5. Design axes (DECIDED — see §8 for final answers)

| Ось | Решение (final) |
|---|---|
| **Diff granularity** | **BOTH** — text-diff (`difflib`) на `summary` + structured set-diff (added/removed) на `scope_in`/`scope_out` |
| **Output format** | **BOTH** — MCP отдаёт structured JSON; CLI рендерит human-readable; **общий diff-helper** строит structured result, CLI его форматирует |
| **Repo access** | новый read-only `get_two_versions(topic_id, a, b)` (recommend) **или** reuse `list_by_topic` + filter; для `current`-стороны — `card_repo.get_by_id` (живая карточка). `purge_stale`/`list_by_topic`/`count` не менять |
| **Surfaces** | **MCP + CLI вместе** (зеркало `get_topic_versions`) |
| **Version selection** | **both_allowed** — архивные пары по `version_no` **И** `current`/`latest` токен → живая карточка. Default = **v1 → current** |
| **Missing/purged version** | **explicit typed not-found** («reclaimed by retention policy»), никогда 500 (любая сторона) |
| **Text-diff алгоритм** | **stdlib `difflib`** — новых deps нет (ADR-0017) |
| **Bot surface** | **OUT** — item #5 Bot tools |

---

## 6. Blast-radius (sketch — что тронуто vs нет)

| Surface | Touch? | Notes |
|---|---|---|
| Domain diff helper (shared) | **Yes (small, pure)** | `diff_topic_versions(a, b) -> dict` в domain (чистая функция: `difflib` для summary + set-diff для scopes). Без I/O. Общий для MCP (JSON) и CLI (render). |
| `TopicCardVersionRepo` port + SA impl | **Maybe** | read-only `get_two_versions(topic_id, version_a, version_b)` (recommend) **или** reuse `list_by_topic`. `list_by_topic` / `purge_stale` / `count` **не меняются**. |
| `TopicCardRepo.get_by_id` (live card) | **Read reuse** | `current`-сторона читает живую карточку (`card.summary`/`scope_in`/`scope_out`, `summary_version=N`) — та же карточка, что уже грузится для access-check. **Кода не менять**, только читать. |
| MCP tool | **Yes** | новый `get_topic_history_diff` (зеркало `get_topic_versions`: guard, user-resolve, access). Возврат — structured JSON. |
| CLI | **Yes** | новый `topic diff <topic_id> [--version-a] [--version-b]` в [`cli/topic_cmd.py`](../../tg_parser/cli/topic_cmd.py) — rendered-вывод из общего helper'а. |
| Alembic / schema | **No** | read-only; zero schema-change, no migration. |
| Write-path (`resummarization_service`) | **No** | diff не пишет. |
| TTL `purge_stale` / scheduler / Settings retention knobs (PR #346) | **No** | не расширять PR #346. |
| `get_topic_versions` / `list_by_topic` | **No code change** | diff — независимый второй consumer. |
| F11 / F6 digest / RAG / workspaces / Bot | **No** | diff в Bot — **OUT** (item #5, §8 D6). |
| Prod data | **No mutation** | pure read; никакого backup/GO не требуется. |

---

## 7. Karpathy checklist impact (ADR-0006)

| Принцип | Impact |
|---|---|
| **#1 Persistent entities** | Diff читает first-class version-rows; ничего не демотирует. ✅ |
| **#2 Provenance/evidence** | Diff **усиливает** provenance: делает evolution видимой. Должен корректно подписывать stored-snapshot vs live-card источники (§4.2). |
| **#4 Idempotency** | Read-only ⇒ тривиально идемпотентен; не пересекается с write-path advisory-lock. |
| **#6 Observability** | Опционально: тривиальный лог/метрика вызовов diff (не обязательно для read-tool; см. impl-plan). |

---

## 8. Decisions (final — owner GO 2026-07-23)

Все 6 owner-decisions разрешены; baked в этот skeleton + [plan](PLAN_SESSION_F5C_DIFF_API_2026-07-23.md) + [START_PROMPT](START_PROMPT_SESSION_F5C_DIFF_API_2026-07-23.md).

- **D1. Granularity = BOTH** — text-diff (stdlib `difflib`, ADR-0017 — no new deps) на `summary` **+** structured set-diff (added/removed) на `scope_in`/`scope_out`.
- **D2. Output = BOTH** — MCP tool возвращает structured JSON (added/removed/changed); CLI рендерит human-readable; **общий diff-helper** строит structured result, CLI его форматирует.
- **D3. Surfaces = MCP + CLI вместе** — зеркало `get_topic_versions` (у которого оба surface парны).
- **D4. Version selection = both_allowed** —
  - архивные пары по `version_no` из `topic_card_versions` (snapshot'ы предыдущего состояния, v1..v(N−1));
  - **PLUS** спец-токен `current`/`latest` справа → живая карточка (`topic_cards.summary`/`scope_in`/`scope_out`, `summary_version = N`), которой **нет** в таблице версий;
  - **default-пара при отсутствии args = genesis (v1) → current (live card)**;
  - dual-source семантика явно задокументирована (§4.2): tool принимает числа версий и токен `current`/`latest`; при правой стороне `current` читается живая карточка, иначе обе стороны — из таблицы версий.
- **D5. Missing/purged `version_no` = explicit typed not-found** («reclaimed by retention policy»), никогда 500. Применяется к **любой** стороне. Post-TTL gaps interaction: genesis v1 + last-N всегда present ⇒ default genesis→current всегда осуществим.
- **D6. Bot surface = OUT** — это item #5 (Bot tools).

---

## 9. Out of scope (жёстко — impl-сессия не расширяет без нового GO)

- **#5 Bot tools** (diff/versions в Telegram — D6 OUT), **#9 HTTP endpoints**, **#3 F6 topic-level digest**, **#6 type-promotion**, **#7 topic dedup**, **#8 bundle-item GC**.
- **Любая мутация / write-path**: renumber или «уплотнение» `version_no`, materialize живой карточки как строки версии, скрытие gaps от API.
- **TTL-изменения** (ADR-0018 / PR #346): не расширять retention, не менять `purge_stale` / knobs / cron / Settings retention.
- **Schema-change / Alembic-миграция** — diff read-only, не нужен.
- **Wave E** graph retrieval, **F11 HTTP CRUD**, **webhook 2A (ADR-0008)**.
- `docs/methodology/**`, `pyproject.toml`, `requirements.txt` (ADR-0017 — новых deps не нужно; `difflib` — stdlib).

---

## 10. Acceptance / to-verify (sketch — детально в plan §7 / START_PROMPT §5)

- [ ] Default-пара при отсутствии args = **genesis (v1) → current**; `current`/`latest` читает **живую карточку** (`topic_cards`, `summary_version=N`), не таблицу версий.
- [ ] Diff robust к `version_no` gaps: purged/missing версия (любая сторона) → типизированный not-found «reclaimed by retention policy», **никогда** 500.
- [ ] Присутствуют **оба**: text-diff (`difflib`) на `summary` **и** set-diff (added/removed) на `scope_in`/`scope_out`.
- [ ] MCP отдаёт structured JSON; CLI рендерит; оба через **общий** diff-helper.
- [ ] Read-only: **нет** write-path, schema-change, миграции, TTL-изменений.
- [ ] Visibility зеркалит `get_topic_details` / `get_topic_versions` (`assert_topic_access` по `card.sources`).
- [ ] Нет новых deps (`difflib` stdlib; ADR-0017).
- [ ] `ruff check` + `ruff format --check` + `TEST_POSTGRES=1 uv run pytest -q` — green.
- [ ] Commit/PR — только по явному запросу пользователя.

---

## 11. Нужен ли новый ADR?

**НЕТ (подтверждено после D4).** Diff — **read-only additive surface** над уже существующей (и уже нормированной ADR-0018) историей: не меняет retention-контракт, не вводит нового нормативного решения о том, что хранится/удаляется. Решение D4 (`current` = живая карточка) **не** вводит новый storage-контракт — оно лишь **читает** уже существующие `topic_cards`-колонки (`summary`/`scope_in`/`scope_out`), ровно как это делает `get_topic_details`; никакой новой сущности, миграции или изменения инвариантов. Проект ведёт ADR-per-decision (0009 idempotency, 0017 dep-policy, 0018 retention) — diff не decision этого класса. Достаточно plan + START_PROMPT + FUTURE_FEATURES bullet.

---

## 12. Pointers

- Issue [#15](https://github.com/AlexEfimov/TG_parser/issues/15) item #2 diff API; [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) L798
- Retention interaction: [ADR-0018](../adr/0018-topic-card-versions-retention.md); [`PLAN_SESSION_F5C_TTL_RETENTION_2026-07-22.md`](PLAN_SESSION_F5C_TTL_RETENTION_2026-07-22.md); [`SKELETON_F5C_TTL_RETENTION_TOPIC_CARD_VERSIONS_2026-07-20.md`](SKELETON_F5C_TTL_RETENTION_TOPIC_CARD_VERSIONS_2026-07-20.md)
- Runbook: [`F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md)
- ADR [0006](../adr/0006-karpathy-like-living-kb-principles.md) (#1/#2/#4/#6), [0017](../adr/0017-dependency-management-policy.md) (dep policy)
- Companion plan: [`PLAN_SESSION_F5C_DIFF_API_2026-07-23.md`](PLAN_SESSION_F5C_DIFF_API_2026-07-23.md)

---

## 13. Self-review fixes applied (skeleton)

_(заполнено в self-review pass — см. §13 в конце после первичной черновой версии.)_

1. **`version_no` семантика вынесена в отдельный §4** — при первом проходе «latest» подавался как очевидный; re-open write-path ([`resummarization_service.py`](../../tg_parser/services/resummarization_service.py) L588) показал: строки = snapshot *предыдущего* состояния, `version_no = summary_version`; живой current summary — на `topic_cards`, не в таблице. Это переведено в explicit OPEN QUESTION #4 (что есть «latest»).
2. **Anchor line-numbers перепроверены по факту** — `list_by_topic` L72 (не L102, где теперь `purge_stale` из PR #346), `count` L166, port L828, MCP tool L2604/2606, `assert_topic_access` L50, `get_topic_details` L1408, CLI `versions` L29, domain L431, FUTURE_FEATURES L798. Уточнено, что `purge_stale` (L102) — TTL-код PR #346, diff его **не трогает**.
3. **Gaps-robastность привязана к ADR-0018 §4** — явно: genesis (v1) + last-N pinned ⇒ default-пара всегда резолвится; purged → typed not-found, не 500.
4. **`difflib` = stdlib зафиксирован** — снимает риск нарушения ADR-0017 (никаких новых deps); отражено в §5/§9/§10.
5. **Branch-note добавлен** — docs-only на `feature/f5c-ttl-retention-topic-card-versions`; TTL-код PR #346 не трогаем.

### Decision-bake pass (2026-07-23, owner GO — 6 решений)

6. **§8 OPEN QUESTIONS → Decisions (final)** — все 6 переписаны как D1-D6 с финальными ответами; header/§5/§6/§10/§11 согласованы.
7. **D4 both_allowed + live-card read-path baked** — §4.2 переписан: dual-source (архив v1..v(N−1) из `topic_card_versions` **+** `current`/`latest` → живая карточка `topic_cards`). Re-open [`mcp_server.py`](../../tg_parser/mcp_server.py) L1463-1465 подтвердил: `get_topic_details` читает `card.summary`/`card.scope_in`/`card.scope_out`; та же карточка уже грузится в `get_topic_versions` для access-check ⇒ `current`-сторона почти бесплатна. `TopicCard` domain L190 (поля L204-206, `summary_version` L230).
8. **Blast-radius §6** — добавлена строка `TopicCardRepo.get_by_id (live card) — Read reuse` (кода не менять); domain helper повышен Likely→Yes; CLI-row из conditional → Yes (surfaces=MCP+CLI). 
9. **Acceptance §10** — добавлены testable-пункты: default v1→current; `current` = живая карточка; typed not-found на любой стороне; оба diff-вида present; MCP JSON / CLI render через общий helper.
10. **Out-of-scope §9** — bot (#5, D6) и HTTP (#9) вынесены вперёд; renumber/write-path/TTL-changes подтверждены.
11. **ADR §11 = НЕТ подтверждён после D4** — `current`=live card только читает существующие `topic_cards`-колонки (как `get_topic_details`), не вводит storage-контракт ⇒ ADR не нужен.
