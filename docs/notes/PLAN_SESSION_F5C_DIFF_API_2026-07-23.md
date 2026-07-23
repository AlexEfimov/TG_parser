# Plan — Session: F5-C #15 item #2 diff API (`get_topic_history_diff`)

**Дата:** 2026-07-23 · **Тип:** implementation planning note (pre-START_PROMPT) · **Branch:** `feature/f5c-ttl-retention-topic-card-versions` (docs-only planning; commit/PR — **только** по явному запросу пользователя, [`AGENTS.md`](../../AGENTS.md); **не** расширять TTL-код PR #346).

**Goal (одной строкой):** спроектировать read-only MCP + CLI diff-инструмент `get_topic_history_diff(topic_id, version_a, version_b)`, сравнивающий две версии evolving summary темы (текстовый дифф `summary` + set-дифф `scope_in`/`scope_out`) поверх append-only `topic_card_versions`, robust к `version_no` gaps после TTL-purge — без write-path, schema-change и миграции.

> **Статус решений:** все **6 owner-decisions ПРИНЯТЫ** (2026-07-23, см. §9 Decisions final) — план полностью специфицирован. **START_PROMPT написан:** [`START_PROMPT_SESSION_F5C_DIFF_API_2026-07-23.md`](START_PROMPT_SESSION_F5C_DIFF_API_2026-07-23.md). Impl-код выполняется в отдельной реализующей сессии; сам план — docs-only.

> Этот документ = **план сессии реализации** (что и как делать, финальные решения, blast-radius, acceptance). Он развивает ζ-скелет [`SKELETON_F5C_DIFF_API_TOPIC_HISTORY_2026-07-23.md`](SKELETON_F5C_DIFF_API_TOPIC_HISTORY_2026-07-23.md) в исполнимый бриф.

---

## 1. Контекст и why-now

- **Diff — payoff версионирования.** F5-C пишет по одной строке в `topic_card_versions` на каждый успешный re-summarize (snapshot *предыдущего* `TopicCard`: `summary` / `scope_in` / `scope_out` + LLM-provenance, [`resummarization_service.py`](../../tg_parser/services/resummarization_service.py) L582-618). Сегодняшний read-path `get_topic_versions` показывает **что было** списком, но не **что изменилось** между двумя точками. Diff закрывает этот gap: «мы храним версии» → «пользователь видит, как тема менялась».
- **TTL только что ограничил историю (ADR-0018, PR #346 на этой ветке).** `purge_stale` hard-DELETE'ит строки вне keep-last-N=50 **AND** старше M дней **AND** `version_no > 1`. Двойной floor (recent-N + genesis-pin `version_no = 1`) **гарантирует** осуществимость «genesis → recent» diff; удаляются только промежуточные версии ⇒ `version_no` может иметь **gaps**. Diff обязан быть robust к gaps (§4, §9 D5).
- **Priority.** TTL (item #6/#1) закрыт первым (TTL-plan §9 decision #6). diff (#2) — следующий естественный slice: история теперь bounded, но по-прежнему meaningful на концах (genesis + recent).

**Единственный read-path истории:** `TopicCardVersionRepo.list_by_topic` ([`topic_card_version_repo.py`](../../tg_parser/storage/sqlalchemy/topic_card_version_repo.py) L72) → MCP `get_topic_versions` + CLI `topic versions`. Diff добавляет **второй read-only** consumer; write-path не затрагивается.

---

## 2. Схема и текущее поведение (anchored, verified 2026-07-23)

`topic_card_versions` (migration `a4b5c6d7e8f9`; см. TTL-plan §2 для полной таблицы). Для diff релевантны колонки: `version_no` (per-topic монотонный), `summary`, `scope_in_json`, `scope_out_json`, `llm_provider`/`llm_model`/`prompt_version`, `created_at`. Domain-модель — [`TopicCardVersion`](../../tg_parser/domain/models.py) **L431** (`scope_in`/`scope_out` — `list[str]`, `min_length=1`).

**Read-path (reuse-кандидат):** [`list_by_topic(topic_id, limit=50)`](../../tg_parser/storage/sqlalchemy/topic_card_version_repo.py) L72 — `ORDER BY created_at DESC, version_no DESC LIMIT :limit`. Возвращает `list[TopicCardVersion]`. Port ABC — [`ports.py`](../../tg_parser/storage/ports.py) **L828** (`list_by_topic` L842; `purge_stale` L847-875 — **TTL, не трогать**; `count` L877).

**MCP surface pattern to mirror** — [`get_topic_versions`](../../tg_parser/mcp_server.py) **L2604** (`def` L2606):
```
@mcp.tool() / @guard_read_tool
user = await resolve_mcp_user(_extract_authenticated_user_id(ctx))
card = await card_repo.get_by_id(topic_id)   # None → {"error": "Topic not found", ...}
await assert_topic_access(user, card.sources) # PermissionDenied → {"error": e.message, ...}
versions = await version_repo.list_by_topic(topic_id, limit=limit)
return {..., "versions": [v.model_dump(mode="json") for v in versions]}
```
Access-enforcement — [`assert_topic_access`](../../tg_parser/auth/ownership.py) **L50** (доступ, если виден хотя бы один `card.sources`; admin passes; `PermissionDenied` L18). Тот же mental model, что и [`get_topic_details`](../../tg_parser/mcp_server.py) **L1408** (inline visibility L1440-1442).

**CLI surface pattern to mirror** — [`cli/topic_cmd.py`](../../tg_parser/cli/topic_cmd.py) `topic versions` **L29** (+ `purge-versions` L97, `resummarize` L202): typer-subapp `topic`, `resummarization_repos()` context, `Database.close_instance()` в finally, `typer.echo` рендер.

---

## 3. Критическая семантика `version_no` (design-defining)

Write-path ([`resummarization_service.py`](../../tg_parser/services/resummarization_service.py) **L588**): `version_no = card.summary_version` — snapshot **предыдущего** состояния, взятый *до* инкремента. Три следствия для diff:

1. **Genesis = `version_no = 1`** = snapshot summary из topicization (первый materialized row, пишется при *первом* re-summarize). TTL genesis-pin ⇒ вечно present ⇒ «genesis → …» всегда резолвится.
2. **Dual-source «current» (DECIDED — both_allowed, §9 D4).** Последняя строка таблицы имеет `version_no = (live summary_version − 1)`; **живой** current summary — на `topic_cards.summary` / `scope_in` / `scope_out` (`summary_version = N`), в таблице версий **отсутствует**. `get_topic_versions` уже возвращает `current_version` (= `card.summary_version`) **отдельно** от `versions[]`. Diff поддерживает **обе** правые стороны:
   - **архивная пара** — оба `version_no` из `topic_card_versions` (snapshots v1..v(N−1));
   - **`current`/`latest`** токен справа → **живая карточка** (`card_repo.get_by_id` → `card.summary`/`card.scope_in`/`card.scope_out`, `summary_version = N`) — ровно те поля, что читает [`get_topic_details`](../../tg_parser/mcp_server.py) L1463-1465.
   **Default-пара при отсутствии args = genesis (v1) → current (live card).** Живая карточка **уже** грузится в tool'е (для access-check по `card.sources`), поэтому `current`-сторона почти бесплатна.
3. **Gaps робастность (ADR-0018 §4 / L110-112).** После purge промежуточные `version_no` могут отсутствовать (`UNIQUE(topic_id, version_no)`, монотонный, **не** renumber). Запрос purged/несуществующего `version_no` (**любая** сторона) → типизированный not-found «reclaimed by retention policy», **не** 500. Genesis (v1) + last-N всегда present ⇒ default-пара genesis→current **всегда** резолвится (§9 D5).

---

## 4. Design — финальная форма (decisions §9 baked)

### 4.1 Domain diff helper (pure, no I/O) — shared (D1, D2)
Общая чистая функция в domain (напр. `tg_parser/domain/topic_history_diff.py`), одна и та же для MCP (JSON) и CLI (render):
```python
def diff_topic_summaries(
    left: TopicSummarySnapshot, right: TopicSummarySnapshot
) -> dict:
    # summary: unified/line-level text diff (stdlib difflib)
    # scope_in / scope_out: set-diff -> {"added": [...], "removed": [...], "unchanged_count": int}
    # + provenance обеих сторон (label, version_no|"current", created_at, llm_provider/model, prompt_version)
```
- Работает над лёгким value-object (обе стороны нормализуются к общей форме `{summary, scope_in, scope_out, provenance}`): архивная сторона — из `TopicCardVersion`; `current`-сторона — из живого `TopicCard` (`card.summary`/`scope_in`/`scope_out`). Это устраняет разницу типов (`TopicCardVersion` vs `TopicCard`) в helper'е.
- **Text-diff:** stdlib `difflib` (`unified_diff` / `ndiff`) — **новых deps нет** (ADR-0017).
- **Set-diff scopes:** `scope_in`/`scope_out` — `list[str]` → сравнить как упорядоченные множества (added / removed / unchanged_count).
- Порядок (left,right) нормализуется вызывающим (left = старее, right = новее; `current` — всегда правая сторона).

### 4.2 Repo / read-path (D4 both_allowed)
- **Архивные стороны:** read-only `get_two_versions(topic_id, version_a, version_b) -> dict[int, TopicCardVersion]` (recommend — точечный SELECT по `(topic_id, version_no IN (a,b))`; отсутствующий `version_no` → пропущен в dict ⇒ typed not-found на уровне tool; **robust к gaps by construction**). **Альтернатива:** reuse [`list_by_topic`](../../tg_parser/storage/sqlalchemy/topic_card_version_repo.py) L72 (`limit=big`) + фильтр в Python (проще, без port-изменения, но упирается в cap). Impl выбирает; acceptance требует только gaps-robastности.
- **`current`-сторона:** `card_repo.get_by_id(topic_id)` (уже вызывается для access-check) → `card.summary`/`scope_in`/`scope_out`. **Кода репозитория не менять** — только чтение.
- `list_by_topic` / `purge_stale` (L102, TTL PR #346) / `count` (L166) — **без изменений**.

### 4.3 MCP tool `get_topic_history_diff` (D2 structured JSON, D3)
Зеркало `get_topic_versions` (§2): `@mcp.tool()` + `@guard_read_tool`, `resolve_mcp_user`, `card = get_by_id` (None → not-found), `assert_topic_access(user, card.sources)`. Args: `topic_id`, `version_a: int | None`, `version_b: int | str | None` (число **или** токен `"current"`/`"latest"`). Резолв: `None,None` → default `1 → "current"`; собрать обе стороны (архив через `get_two_versions`; `current` из уже загруженной `card`), затем `diff_topic_summaries`. Возврат — **structured JSON**: `{"topic_id", "left": {...}, "right": {...}, "summary_diff": [...], "scope_in": {"added":[],"removed":[]}, "scope_out": {...}}`. Missing/purged version (любая сторона) → `{"error": "version not found (reclaimed by retention policy)", "topic_id": ..., "missing_version": N}` — **не** exception, **не** 500 (D5).

### 4.4 CLI `topic diff` (D2 rendered, D3)
`tg-parser topic diff <topic_id> [--version-a N] [--version-b N|current]` в [`cli/topic_cmd.py`](../../tg_parser/cli/topic_cmd.py) — зеркало `versions`/`resummarize` (context, finally-close, `typer.echo`). Default `--version-a 1 --version-b current`. Вывод — **human-rendered** diff (summary unified-diff + `+ added` / `- removed` scope-строки) из **того же** `diff_topic_summaries`, что и MCP. Missing version → печать typed not-found + `typer.Exit(1)`.

---

## 5. Blast-radius

| Surface | Touch? | Notes |
|---|---|---|
| Domain diff helper (shared) | **Yes (small, pure)** | новая чистая функция `diff_topic_summaries` (`difflib` + set-diff), общая для MCP+CLI. Без I/O, unit-тестируема изолированно. |
| `TopicCardVersionRepo` port + SA impl | **Maybe** | read-only `get_two_versions` (recommend) **или** reuse `list_by_topic` L72. `list_by_topic` / `purge_stale` (L102) / `count` (L166) **не меняются**. |
| `TopicCardRepo.get_by_id` (live card) | **Read reuse** | `current`-сторона: читает `card.summary`/`scope_in`/`scope_out` (та же карточка, что грузится для access-check). **Кода не менять.** |
| MCP tool | **Yes** | новый `get_topic_history_diff` ([`mcp_server.py`](../../tg_parser/mcp_server.py), зеркало `get_topic_versions` L2604) — structured JSON. |
| CLI | **Yes** | новый `topic diff` ([`cli/topic_cmd.py`](../../tg_parser/cli/topic_cmd.py) L29) — rendered из общего helper'а. |
| Alembic / schema | **No** | read-only; zero schema-change, no migration. |
| Write-path (`resummarization_service`) | **No** | diff не пишет; advisory-lock не затрагивается. |
| TTL `purge_stale` / scheduler / retention Settings (PR #346) | **No** | не расширять — diff read-only consumer gaps. |
| `get_topic_versions` / `list_by_topic` | **No code change** | независимый второй consumer. |
| Settings | **No** | diff без knobs (default-пара `1 → current` — константа, не env). |
| Metrics | **Optional** | read-tool обычно без спец-метрик; лог вызова — nice-to-have, не обязателен. |
| F11 / F6 digest / RAG / workspaces / Bot | **No** | diff в Bot — **OUT** (item #5, §9 D6). |
| Prod data | **No mutation** | pure read; backup/owner-GO **не** требуются (в отличие от TTL). |

**Concurrency:** read-only, отдельная сессия/транзакция чтения; не пересекается с write-path advisory-lock и с TTL-purge (purge удаляет sealed строки; diff читает по `version_no`, missing → not-found).

---

## 6. Session steps (execution outline для impl-сессии — после разрешения §9)

1. **Domain helper** — `diff_topic_summaries(left, right)` (`difflib` summary + set-diff scopes) над нормализованным value-object + unit-тесты (identical → пустой diff; added/removed scope; summary line-change; `current`-сторона из `TopicCard` даёт ту же форму).
2. **Repo (если → `get_two_versions`)** — port `@abstractmethod` (ports.py рядом с L842) + SA impl (SELECT `version_no IN (a,b)`); missing → отсутствует в результате. Unit-тест: gap → not-found; genesis (v1) resolves. _Если reuse `list_by_topic` — шаг пропускается._
3. **MCP tool** — `get_topic_history_diff` (зеркало `get_topic_versions`: guard/user/access); args `version_a:int|None`, `version_b:int|str|None` (число / `"current"`); default `1→current`; `current` из уже загруженной `card`; structured JSON; typed not-found на missing version. Test: default v1→current happy-path, archival pair, purged-version → not-found (не 500), no-access → error-shape, topic-not-found.
4. **CLI** — `topic diff <topic_id> [--version-a N] [--version-b N|current]` rendered-вывод (тот же domain-helper); default `1→current`. Smoke-тест.
5. **Docs** — FUTURE_FEATURES L798 bullet → DONE/partial + surface list (MCP+CLI); ROADMAP **Next** (в impl-сессии); skeleton → «landed» pointer; `get_topic_versions`/runbook нота «diff — companion read-tool, `current` = live card». ADR — **не** пишем (§11).
6. **Quality gate** — `uv run ruff check .` / `ruff format --check .` / `TEST_POSTGRES=1 uv run pytest -q` (трогаем repo/MCP/CLI paths). Runner-нота: [`tests/README.md`](../../tests/README.md) L76 предпочитает `.venv/bin/python -m pytest`; `uv run pytest` — принятый эквивалент.
7. **Commit/PR** — только по явному запросу пользователя.

---

## 7. Acceptance criteria (impl-сессия done when)

- [ ] **Default-пара при отсутствии args = genesis (v1) → current**; `current`/`latest` читает **живую карточку** (`topic_cards`, `card.summary`/`scope_in`/`scope_out`, `summary_version=N`), **не** таблицу версий.
- [ ] **Both version modes:** архивная пара по `version_no` (v1..v(N−1)) **и** `current`-режим справа — оба работают.
- [ ] Diff **robust к `version_no` gaps**: purged/missing версия (**любая** сторона) → типизированный not-found («reclaimed by retention policy»), **никогда** 500.
- [ ] «genesis (v1) → current» всегда резолвится (double-floor ADR-0018 гарантия).
- [ ] **Read-only:** нет write-path, нет schema-change, нет миграции, нет изменений TTL-кода (PR #346 не тронут), нет renumber `version_no`.
- [ ] Visibility зеркалит `get_topic_details` / `get_topic_versions`: `assert_topic_access(user, card.sources)`; topic-not-found и no-access возвращают структурированный `{"error": ...}`, не exception.
- [ ] Domain diff-helper даёт **оба**: summary text-diff (`difflib`) + `scope_in`/`scope_out` set-diff (added/removed); unit-тесты на identical / added / removed / summary-change / `current`-сторона.
- [ ] **Нет новых deps** — `difflib` stdlib (ADR-0017).
- [ ] MCP возвращает structured JSON; CLI — rendered; **оба** используют один domain-helper.
- [ ] `uv run ruff check .` + `uv run ruff format --check .` + `TEST_POSTGRES=1 uv run pytest -q` — green.
- [ ] FUTURE_FEATURES / ROADMAP / skeleton pointer обновлены.
- [ ] Commit/PR только по явному запросу пользователя.

---

## 8. Out of scope (жёстко — impl-сессия не расширяет без нового GO)

- **#5 Bot tools** (diff/versions в Telegram — §9 D6 OUT), **#9 HTTP endpoints**, **#3 F6 topic-level digest**, **#6 type-promotion**, **#7 topic dedup**, **#8 bundle-item GC**.
- **Любая мутация / write-path:** renumber или «уплотнение» `version_no`, materialize живой карточки как строки версии, скрытие gaps от API.
- **TTL-изменения (ADR-0018 / PR #346):** не расширять retention, не менять `purge_stale` / knobs / cron / Settings retention.
- **Schema-change / Alembic-миграция** — diff read-only, не нужен.
- **Новый ADR** — не пишем (§11).
- **Wave E** graph retrieval, **F11 HTTP CRUD**, **webhook 2A (ADR-0008)**.
- `docs/methodology/**`, `pyproject.toml`, `requirements.txt`, «Wave 3» naming.

---

## 9. Owner decisions

### Pre-baked (зафиксировано до owner-раунда — следствия ADR/priority)
- **P1. Priority:** diff (#2) — следующий #15 item после TTL (#6/#1), закрытого первым (TTL-plan §9 decision #6). ✅
- **P2. Read-only контракт:** diff читает историю + живую карточку; **никакого** write-path/schema-change/миграции. ✅
- **P3. No new deps:** текстовый diff — stdlib `difflib` (ADR-0017; `pyproject`/`requirements` не трогаем). ✅

### DECIDED (owner GO 2026-07-23 — все 6)
- **D1. Granularity = BOTH** — text-diff (`difflib`) на `summary` **+** structured set-diff (added/removed) на `scope_in`/`scope_out`.
- **D2. Output = BOTH** — MCP отдаёт structured JSON (added/removed/changed); CLI рендерит human-readable; **общий diff-helper** строит structured result, CLI его форматирует.
- **D3. Surfaces = MCP + CLI вместе** — зеркало `get_topic_versions` (оба surface парны).
- **D4. Version selection = both_allowed** — архивные пары по `version_no` из `topic_card_versions` (v1..v(N−1)) **PLUS** токен `current`/`latest` справа → живая карточка (`topic_cards.summary`/`scope_in`/`scope_out`, `summary_version=N`, которой нет в таблице версий). **Default-пара = genesis (v1) → current (live card).** Dual-source семантика задокументирована в §3.2/§4.
- **D5. Missing/purged `version_no` = explicit typed not-found** («reclaimed by retention policy»), никогда 500 — **любая** сторона. Post-TTL gaps: genesis v1 + last-N всегда present ⇒ default genesis→current всегда осуществим.
- **D6. Bot surface = OUT** — item #5 (Bot tools); этот slice = MCP/CLI.

---

## 10. Quality / ops gate commands

```bash
# repo quality (local, всегда)
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
# PR-standard (трогаем repo/MCP/CLI paths → нужен Postgres):
TEST_POSTGRES=1 uv run pytest -q
# Runner note: tests/README.md L76 предпочитает `.venv/bin/python -m pytest` для real runs;
# `uv run pytest` — принятый эквивалент (те же режимы default / TEST_POSTGRES=1). Один runner в обоих доках.

# manual smoke (после impl):
tg-parser topic diff <topic_id>                        # default genesis(v1) -> current (live card)
tg-parser topic diff <topic_id> --version-a 1 --version-b 5     # archival pair
tg-parser topic diff <topic_id> --version-b current            # explicit current mode
```
_Prod-мутации / backup / owner-GO — **не требуются** (diff read-only, в отличие от TTL)._

---

## 11. Нужен ли новый ADR?

**НЕТ (подтверждено после D4).** Diff — **read-only additive surface** над историей, уже нормированной [ADR-0018](../adr/0018-topic-card-versions-retention.md): не меняет retention-контракт, не вводит нового нормативного решения о том, что хранится/удаляется/как долго. D4 (`current` = живая карточка) **не** вводит storage-контракт: tool лишь **читает** уже существующие `topic_cards`-колонки (`summary`/`scope_in`/`scope_out`) — ровно как `get_topic_details` — без новой сущности, миграции или изменения инвариантов. Проект ведёт **ADR-per-decision** (0009 idempotency, 0017 dep-policy, 0018 retention) — diff не decision этого класса, а surface поверх уже принятых. Достаточно plan + START_PROMPT + FUTURE_FEATURES bullet.

---

## 12. Self-review fixes applied (plan)

Критический pass (internal consistency skeleton↔plan / anchor-correctness re-open / testable acceptance / explicit OUT / TTL-gaps interaction / no invented symbols):

1. **`version_no` семантика (§3) сверена с write-path** — re-open [`resummarization_service.py`](../../tg_parser/services/resummarization_service.py) L588 подтвердил `version_no = card.summary_version` (snapshot предыдущего). ⇒ «latest» неоднозначен (stored `N−1` vs live `N`); переведено в §9 Q4 с обоими вариантами вместо тихого допущения «latest = последняя строка».
2. **Anchor line-numbers перепроверены пофайлово** — `list_by_topic` **L72** (не L102: там теперь `purge_stale` из PR #346), `count` L166, port L828, MCP `get_topic_versions` L2604/def L2606, `assert_topic_access` L50 (`PermissionDenied` L18), `get_topic_details` L1408, CLI `versions` L29, domain `TopicCardVersion` L431, FUTURE_FEATURES diff bullet L798. Ни одного invented symbol.
3. **Repo-метод помечен Maybe, не обязателен** — §4.2/§5 разведены: `get_two_versions` (recommend) vs reuse `list_by_topic`; выбор связан с §9 Q3 (surfaces). Acceptance не требует конкретного метода — только gaps-robastности.
4. **Gaps-контракт согласован skeleton↔plan** — оба: purged → typed not-found (не 500), genesis+last-N floor гарантирует default-пару (ADR-0018 §4/L110-112). §9 Q5 default = explicit not-found.
5. **ADR-decision явно НЕТ + условие пересмотра** — §11 согласован со skeleton §11; единственный trigger — Q4 «latest = live card» как нормативный контракт.
6. **DECIDED vs OPEN split выверен** — priority/read-only/gaps-robust/no-deps = DECIDED (следствия уже принятых решений/ADR-0017/0018); granularity/format/surfaces/default-pair/missing-behavior/bot = OPEN (продуктовый выбор owner). START_PROMPT сознательно отложен до resolution §9.
7. **CLI-row помечен conditional** — §5 blast-radius CLI зависит от §9 Q3; acceptance §7 «CLI если в scope» — не жёсткое требование, чтобы не предрешать MCP-only вариант.

### Decision-bake pass (2026-07-23, owner GO — 6 решений)

8. **OPEN QUESTIONS → DECIDED** — §9 переписан: Q1-Q6 стали D1-D6 (baked); прежние «DECIDED» переименованы в «Pre-baked» P1-P3 (следствия ADR/priority), чтобы не путать с owner-раундом. Header-статус: «6 ПРИНЯТЫ, START_PROMPT написан».
9. **D4 both_allowed + live-card read-path** — §3.2/§4 переписаны на dual-source: архив (v1..v(N−1) из `topic_card_versions`) **+** `current` → живая карточка. Re-open подтвердил read-path: [`get_topic_details`](../../tg_parser/mcp_server.py) L1463-1465 читает `card.summary`/`card.scope_in`/`card.scope_out` (+ `summary_version` L1473); `TopicCard` domain L190 (поля L204-206, L230). Отмечено: `current`-сторона переиспользует карточку, уже загруженную для access-check ⇒ без доп. repo-вызова.
10. **Helper generalised** — `diff_topic_versions(a,b)` → `diff_topic_summaries(left,right)` над нормализованным value-object, т.к. `current`-сторона — `TopicCard`, а не `TopicCardVersion` (разные типы). Это устранило потенциальный type-mismatch в helper'е (catch).
11. **MCP arg-type уточнён** — `version_b: int | str | None` (число **или** токен `"current"`/`"latest"`); default `1→current`; §4.3/§6/§10 согласованы; missing → `{"error": ..., "missing_version": N}`, не 500 (D5, любая сторона).
12. **Blast-radius §5** — CLI из conditional → **Yes** (D3); добавлена строка live-card `get_by_id` **Read reuse** (кода не менять); Settings → **No** (default — константа `1→current`).
13. **Acceptance §7** — добавлены testable-пункты: default v1→current; both modes (archival + current); `current` читает живую карточку; typed not-found на любой стороне; оба diff-вида present; no renumber.
14. **ADR §11 = НЕТ подтверждён после D4** — `current`=live card только читает существующие `topic_cards`-колонки (как `get_topic_details`); не storage-контракт ⇒ ADR не нужен; условный триггер снят.

---

## 13. Links

- ζ skeleton (companion): [`SKELETON_F5C_DIFF_API_TOPIC_HISTORY_2026-07-23.md`](SKELETON_F5C_DIFF_API_TOPIC_HISTORY_2026-07-23.md)
- Issue [#15](https://github.com/AlexEfimov/TG_parser/issues/15) item #2 diff API; [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) L798 (surface L782-783)
- Retention interaction: [ADR-0018](../adr/0018-topic-card-versions-retention.md); TTL plan [`PLAN_SESSION_F5C_TTL_RETENTION_2026-07-22.md`](PLAN_SESSION_F5C_TTL_RETENTION_2026-07-22.md); TTL skeleton [`SKELETON_F5C_TTL_RETENTION_TOPIC_CARD_VERSIONS_2026-07-20.md`](SKELETON_F5C_TTL_RETENTION_TOPIC_CARD_VERSIONS_2026-07-20.md)
- Runbook: [`F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md)
- ADR [0006](../adr/0006-karpathy-like-living-kb-principles.md) (#1/#2/#4/#6), [0017](../adr/0017-dependency-management-policy.md) (dep policy — no new deps)
- Anchors: repo [`topic_card_version_repo.py`](../../tg_parser/storage/sqlalchemy/topic_card_version_repo.py) L72 (`purge_stale` L102, TTL); port [`ports.py`](../../tg_parser/storage/ports.py) L828; MCP `get_topic_versions` [`mcp_server.py`](../../tg_parser/mcp_server.py) L2604, live-card read `get_topic_details` L1463-1465; access [`auth/ownership.py`](../../tg_parser/auth/ownership.py) L50; CLI [`cli/topic_cmd.py`](../../tg_parser/cli/topic_cmd.py) L29; domain `TopicCardVersion` [`domain/models.py`](../../tg_parser/domain/models.py) L431, `TopicCard` L190 (`summary` L204, `scope_in/out` L205-206, `summary_version` L230); write-path [`resummarization_service.py`](../../tg_parser/services/resummarization_service.py) L588
- START_PROMPT (companion): [`START_PROMPT_SESSION_F5C_DIFF_API_2026-07-23.md`](START_PROMPT_SESSION_F5C_DIFF_API_2026-07-23.md)
