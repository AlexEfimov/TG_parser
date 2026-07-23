# START PROMPT — Session: F5-C #15 item #2 diff API (`get_topic_history_diff`)

**Дата:** 2026-07-23 · **Тип:** implementation (domain helper + read-only repo + MCP tool + CLI + docs) · **Ветка:** `feature/f5c-ttl-retention-topic-card-versions` (или feature-ветка от актуального `main`)

**Goal (одной строкой):** реализовать read-only diff-инструмент `get_topic_history_diff(topic_id, version_a, version_b)` (MCP) + `tg-parser topic diff` (CLI), сравнивающий две версии evolving summary темы — text-diff (`difflib`) на `summary` + set-diff на `scope_in`/`scope_out` — с поддержкой **архивных** пар (`version_no` из `topic_card_versions`) **и** `current`/`latest` (живая карточка `topic_cards`), robust к post-TTL `version_no` gaps, **без** write-path/schema-change/миграции.

> **✅ Design decisions final (2026-07-23).** Все 6 owner-decisions приняты (см. §7) — бриф полностью специфицирован. Diff — **read-only, non-destructive**: нет prod-мутации, backup/owner-GO **не** требуются (в отличие от TTL). Единственный gate — commit/PR.

> **Рабочий режим (нормативно, [`AGENTS.md`](../../AGENTS.md)):** `git commit` / PR — **только** по явному запросу пользователя (PR = merge-commit + `--delete-branch`). Никаких правок `docs/methodology/**`. `pyproject.toml` / `requirements.txt` — **не трогать** (ADR-0017; `difflib` — stdlib, новых deps нет). Уважать `docs/adr/` (accepted binding) и `docs/contracts/` (JSON Schema нерушимы). **Не трогать TTL-код PR #346** (`purge_stale` / retention Settings / cron) — diff лишь read-only consumer его gaps.

**Prerequisite SoT (перечитать перед кодом):**
- Plan (this session): [`PLAN_SESSION_F5C_DIFF_API_2026-07-23.md`](PLAN_SESSION_F5C_DIFF_API_2026-07-23.md) — финальные решения, blast-radius, acceptance.
- Skeleton: [`SKELETON_F5C_DIFF_API_TOPIC_HISTORY_2026-07-23.md`](SKELETON_F5C_DIFF_API_TOPIC_HISTORY_2026-07-23.md).
- Retention interaction (gaps): [ADR-0018](../adr/0018-topic-card-versions-retention.md) §4 (double-floor: genesis v1 + last-N всегда present).

---

## 0. TL;DR

| Step | Действие | Тип |
|---|---|---|
| 1 | Domain helper `diff_topic_summaries(left, right)` (`difflib` summary + set-diff scopes) над нормализованным value-object + unit-тесты | code+test |
| 2 | Repo read-path для архивных сторон: `get_two_versions(topic_id, a, b)` (recommend) **или** reuse `list_by_topic` | code(+test) |
| 3 | MCP tool `get_topic_history_diff` (зеркало `get_topic_versions`: guard/user/access), args `version_a`/`version_b` (int \| `"current"`), default `1→current`, structured JSON, typed not-found | code+test |
| 4 | CLI `tg-parser topic diff <id> [--version-a N] [--version-b N\|current]` — rendered из общего helper'а | code+test |
| 5 | Docs: FUTURE_FEATURES L798 → DONE/partial (+ MCP/CLI surface); ROADMAP **Next**; skeleton→landed pointer; runbook/`get_topic_versions` нота «diff companion, `current`=live card» | docs |
| 6 | Quality gate: ruff + `TEST_POSTGRES=1 uv run pytest -q` | gate |

**Hard OUT:** write-path/мутация, renumber `version_no`, schema-change/Alembic, TTL-изменения (PR #346), **#5 Bot tools**, **#9 HTTP endpoints**, #3 F6 topic-digest, #6/#7/#8, Wave E, F11 HTTP, webhook 2A, methodology, pyproject/requirements, «Wave 3» naming, **новый ADR** (§8).

**Recommended order:** 1 → 2 → 3 → 4 → 5 → 6. Helper перед surfaces (переиспользуется обоими); docs после кода.

---

## 1. Контекст

F5-C пишет по одной строке в `topic_card_versions` на каждый успешный re-summarize — snapshot **предыдущего** состояния `TopicCard` (`summary`/`scope_in`/`scope_out` + LLM-provenance). Read-path сегодня — `get_topic_versions` (список). Diff (#2) превращает «мы храним версии» в «пользователь видит, как тема менялась». TTL (#15 item #1) только что ограничил историю (ADR-0018, PR #346): hard-DELETE вне keep-last-N=50 **AND** старше M дней **AND** `version_no > 1`; genesis-pin (v1) + recent-N floor ⇒ `version_no` может иметь **gaps**, но genesis и последние N всегда present ⇒ diff обязан быть robust к gaps.

**Критическая семантика `version_no` (design-defining):** write-path ([`resummarization_service.py`](../../tg_parser/services/resummarization_service.py) L588) пишет `version_no = card.summary_version` — snapshot предыдущего состояния. Значит таблица хранит v1..v(N−1); **живой** current summary (vN) лежит **только** на `topic_cards.summary`/`scope_in`/`scope_out` (`summary_version = N`) и в таблице версий отсутствует. Отсюда решение D4 (both_allowed): `current`/`latest` справа читает живую карточку.

---

## 2. Anchors (перечитать перед правкой — verified 2026-07-23)

| Якорь | Файл | Строка | Роль |
|---|---|---|---|
| Domain `TopicCardVersion` | [`domain/models.py`](../../tg_parser/domain/models.py) | **L431** (`summary` L444, `scope_in`/`out` L445-446) | архивная сторона diff |
| Domain `TopicCard` (live card) | [`domain/models.py`](../../tg_parser/domain/models.py) | **L190** (`summary` L204, `scope_in`/`out` L205-206, `summary_version` L230) | `current`-сторона diff |
| Repo read-path `list_by_topic` | [`topic_card_version_repo.py`](../../tg_parser/storage/sqlalchemy/topic_card_version_repo.py) | **L72** | reuse-кандидат / рядом добавить `get_two_versions` |
| Repo `purge_stale` (TTL PR #346) | same | **L102** | **НЕ трогать** — источник gaps |
| Repo `count` | same | **L166** | не нужен diff'у |
| Port ABC `TopicCardVersionRepo` | [`storage/ports.py`](../../tg_parser/storage/ports.py) | **L828** (`list_by_topic` L842, `purge_stale` L847) | `@abstractmethod get_two_versions` рядом (если выбран) |
| **MCP surface to mirror** `get_topic_versions` | [`mcp_server.py`](../../tg_parser/mcp_server.py) | **L2604** (`def` L2606) | `@guard_read_tool`, `resolve_mcp_user`, `card = get_by_id`, `assert_topic_access`, `model_dump(mode="json")` |
| **Live-card read-path** `get_topic_details` | [`mcp_server.py`](../../tg_parser/mcp_server.py) | **L1436** (`get_by_id`), **L1463-1465** (`card.summary`/`scope_in`/`scope_out`), **L1473** (`summary_version`) | как читать живую карточку для `current`-стороны |
| Access enforcement `assert_topic_access` | [`auth/ownership.py`](../../tg_parser/auth/ownership.py) | **L50** (`PermissionDenied` L18) | доступ если виден ≥1 из `card.sources`; admin passes |
| CLI subapp `topic` | [`cli/topic_cmd.py`](../../tg_parser/cli/topic_cmd.py) | **L29** `versions` (`purge-versions` L97, `resummarize` L202) | зеркалить для `topic diff` |
| Write-path (НЕ ломать) `version_no = summary_version` | [`resummarization_service.py`](../../tg_parser/services/resummarization_service.py) | **L582-618** (L588) | объясняет dual-source семантику |
| FUTURE_FEATURES diff bullet | [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) | **L798** (MCP/CLI surface L782-783) | обновить → DONE/partial |
| Retention interaction | [ADR-0018](../adr/0018-topic-card-versions-retention.md) | §4 / L110-112 | «gaps = policy; genesis present ⇒ не 500» |

---

## 3. Scope — детально

### 3.1 Domain diff helper (code+test) — shared, pure (D1, D2)
- Новый модуль (напр. `tg_parser/domain/topic_history_diff.py`): `diff_topic_summaries(left, right) -> dict`.
- Обе стороны нормализуются к общей форме `{summary: str, scope_in: list[str], scope_out: list[str], provenance: {...}}`: архивная — из [`TopicCardVersion`](../../tg_parser/domain/models.py) L431; `current` — из живого [`TopicCard`](../../tg_parser/domain/models.py) L190. Это снимает разницу типов в helper'е.
- **summary** → text-diff через stdlib `difflib` (`unified_diff` / `ndiff` — impl выбирает; фиксировать в тесте). **scope_in/scope_out** → set-diff `{"added": [...], "removed": [...], "unchanged_count": int}`.
- Порядок нормализует вызывающий (left = старее, right = новее; `current` — всегда справа).
- Unit-тесты: identical → пустой diff; summary line-change; scope added/removed; `current`-сторона (из `TopicCard`) даёт ту же структуру, что архивная.

### 3.2 Repo read-path (code, +test если новый метод) (D4)
- **Архивные стороны (recommend):** `get_two_versions(topic_id, version_a, version_b) -> dict[int, TopicCardVersion]` — port `@abstractmethod` в [`ports.py`](../../tg_parser/storage/ports.py) рядом с L842 + SA impl рядом с [`list_by_topic`](../../tg_parser/storage/sqlalchemy/topic_card_version_repo.py) L72 (SELECT `WHERE topic_id=:t AND version_no IN (:a,:b)`); отсутствующий `version_no` просто не попадает в результат ⇒ typed not-found на уровне tool. **Robust к gaps by construction.** Unit-тест: gap → not в результате; v1 (genesis) resolves.
- **Альтернатива (без port-изменения):** reuse `list_by_topic(topic_id, limit=big)` + фильтр в Python (упирается в cap `limit`; проще). Impl выбирает; acceptance требует только gaps-robastности, не конкретный метод.
- **`current`-сторона:** `card_repo.get_by_id(topic_id)` — карточка **уже** загружена в tool'е для access-check ⇒ доп. вызова нет. **Кода репозитория для этого не добавлять.**
- `list_by_topic` / `purge_stale` (L102) / `count` (L166) — **без изменений**.

### 3.3 MCP tool `get_topic_history_diff` (code+test) (D2 JSON, D3, D5)
- Зеркало `get_topic_versions` ([`mcp_server.py`](../../tg_parser/mcp_server.py) L2604): `@mcp.tool()` + `@guard_read_tool`; `user = await resolve_mcp_user(...)`; `card = await card_repo.get_by_id(topic_id)` (None → `{"error": "Topic not found: ...", "topic_id": ...}`); `await assert_topic_access(user, card.sources)` (PermissionDenied → `{"error": e.message, ...}`).
- **Args:** `topic_id: str`, `version_a: int | None = None`, `version_b: int | str | None = None`. Резолв: `(None, None)` → default `1 → "current"`; `version_b == "current"|"latest"` → живая `card`; иначе обе стороны из `get_two_versions`.
- Собрать `left`/`right` value-objects → `diff_topic_summaries`. Возврат — **structured JSON**: `{"topic_id", "left": {label,version_no|"current",...}, "right": {...}, "summary_diff": [...], "scope_in": {"added":[],"removed":[]}, "scope_out": {...}}`.
- **Missing/purged version (любая сторона)** → `{"error": "version not found (reclaimed by retention policy)", "topic_id": ..., "missing_version": N}` — **не** exception, **не** 500 (D5).
- Tests: default v1→current happy-path; archival pair (v1→v3); purged-version → typed not-found (не 500); no-access → error-shape; topic-not-found.

### 3.4 CLI `topic diff` (code+test) (D2 rendered, D3)
- `tg-parser topic diff <topic_id> [--version-a N] [--version-b N|current]` в [`cli/topic_cmd.py`](../../tg_parser/cli/topic_cmd.py) — зеркало `versions` (L29): `resummarization_repos()` context, `Database.close_instance()` в finally, `typer.echo`. Default `--version-a 1 --version-b current`.
- Вывод — **human-rendered** (summary unified-diff + `+ added` / `- removed` scope-строки) из **того же** `diff_topic_summaries`. Missing version → typed not-found message + `raise typer.Exit(1)`.

### 3.5 Docs (docs)
- FUTURE_FEATURES L798 diff bullet → DONE/partial + surface list (MCP `get_topic_history_diff` + CLI `topic diff`). ROADMAP **Next**. Skeleton → «landed» pointer. Нота в `get_topic_versions` docstring / runbook: «diff — companion read-tool; `current` = live card (`topic_cards`), archival = `topic_card_versions`; gaps = retention policy». **ADR не пишем** (§8).

---

## 4. Out of scope (жёстко)

- **#5 Bot tools** (diff/versions в Telegram — D6 OUT), **#9 HTTP endpoints**, **#3 F6 topic-level digest**, **#6 type-promotion**, **#7 topic dedup**, **#8 bundle-item GC**.
- **Любая мутация / write-path:** renumber или «уплотнение» `version_no`, materialize живой карточки как строки версии, скрытие gaps от API.
- **TTL-изменения (ADR-0018 / PR #346):** `purge_stale` / retention Settings / cron / knobs — не трогать.
- **Schema-change / Alembic-миграция** — diff read-only, не нужен.
- **Новый ADR** — не пишем (§8).
- **Wave E** graph retrieval, **F11 HTTP CRUD**, **webhook 2A (ADR-0008)**.
- `docs/methodology/**`, `pyproject.toml`, `requirements.txt`, «Wave 3» naming.

---

## 5. Acceptance criteria

- [ ] **Default-пара при отсутствии args = genesis (v1) → current**; `current`/`latest` читает **живую карточку** (`topic_cards`, `card.summary`/`scope_in`/`scope_out`, `summary_version=N`), не таблицу версий.
- [ ] **Both version modes** работают: архивная пара по `version_no` (v1..v(N−1)) **и** `current`-режим справа.
- [ ] Diff **robust к `version_no` gaps**: purged/missing версия (**любая** сторона) → типизированный not-found «reclaimed by retention policy», **никогда** 500.
- [ ] «genesis (v1) → current» всегда резолвится (double-floor ADR-0018).
- [ ] Domain helper даёт **оба**: summary text-diff (`difflib`) + `scope_in`/`scope_out` set-diff (added/removed); unit-тесты identical / added / removed / summary-change / `current`-сторона.
- [ ] MCP возвращает **structured JSON**; CLI — **rendered**; оба используют **один** `diff_topic_summaries`.
- [ ] Visibility зеркалит `get_topic_details` / `get_topic_versions`: `assert_topic_access(user, card.sources)`; topic-not-found и no-access → структурированный `{"error": ...}`, не exception.
- [ ] **Read-only:** нет write-path, schema-change, миграции, изменений TTL-кода (PR #346), renumber `version_no`.
- [ ] **Нет новых deps** — `difflib` stdlib (ADR-0017; `pyproject`/`requirements` не тронуты).
- [ ] `uv run ruff check .` + `uv run ruff format --check .` + `TEST_POSTGRES=1 uv run pytest -q` — green.
- [ ] FUTURE_FEATURES / ROADMAP / skeleton pointer обновлены.
- [ ] Commit/PR только по явному запросу пользователя.

---

## 6. Quality / ops gate commands

```bash
# repo quality (local, всегда)
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
# PR-standard (трогаем repo/MCP/CLI paths → нужен Postgres):
TEST_POSTGRES=1 uv run pytest -q
# Runner note: tests/README.md L76 предпочитает `.venv/bin/python -m pytest` для real runs;
# `uv run pytest` — принятый эквивалент (те же режимы default / TEST_POSTGRES=1). Один runner в обоих доках.

# manual smoke (после impl, read-only safe):
tg-parser topic diff <topic_id>                            # default genesis(v1) -> current (live card)
tg-parser topic diff <topic_id> --version-a 1 --version-b 5    # archival pair
tg-parser topic diff <topic_id> --version-b current           # explicit current mode
```
_Prod-мутации / backup / owner-GO — **не требуются** (diff read-only)._

---

## 7. Decisions (final — все 6 owner-решений приняты 2026-07-23; см. plan §9)

1. **Granularity = BOTH** — text-diff (stdlib `difflib`, ADR-0017 no new deps) на `summary` **+** structured set-diff (added/removed) на `scope_in`/`scope_out`.
2. **Output = BOTH** — MCP structured JSON (added/removed/changed); CLI human-rendered; **общий** `diff_topic_summaries` строит structured result, CLI форматирует.
3. **Surfaces = MCP + CLI вместе** — зеркало `get_topic_versions` (оба surface парны).
4. **Version selection = both_allowed** — архивные пары по `version_no` из `topic_card_versions` (v1..v(N−1)) **PLUS** токен `current`/`latest` справа → живая карточка (`topic_cards`, `summary_version=N`, вне таблицы версий). **Default = genesis (v1) → current.** Dual-source семантика: tool принимает числа версий и токен `current`/`latest`; при правой стороне `current` читает живую карточку, иначе обе стороны — из таблицы версий.
5. **Missing/purged `version_no` = explicit typed not-found** («reclaimed by retention policy»), никогда 500 — любая сторона. Post-TTL gaps: genesis v1 + last-N всегда present ⇒ default genesis→current всегда осуществим.
6. **Bot surface = OUT** — item #5 (Bot tools).

**Execution-gate (не design-решение):** commit/PR — только по явному запросу пользователя. Diff read-only ⇒ prod-мутации/backup/GO **не** применяются.

---

## 8. Нужен ли новый ADR? — **НЕТ (обосновано)**

Diff — **read-only additive surface** над историей, уже нормированной [ADR-0018](../adr/0018-topic-card-versions-retention.md): не меняет retention-контракт, не вводит нового нормативного решения о том, что хранится/удаляется/как долго. D4 (`current` = живая карточка) **не** вводит storage-контракт — tool лишь **читает** уже существующие `topic_cards`-колонки (`summary`/`scope_in`/`scope_out`), ровно как `get_topic_details`; без новой сущности, миграции или изменения инвариантов. Проект ведёт ADR-per-decision (0009 idempotency, 0017 dep-policy, 0018 retention) — diff не decision этого класса. Достаточно plan + этот START_PROMPT + FUTURE_FEATURES bullet.

---

## 9. Self-review fixes applied (START_PROMPT)

Критический pass (internal consistency vs plan+skeleton / anchor-correctness re-open / testable acceptance / explicit OUT / TTL-gaps + live-card read-path):

1. **Anchor line-numbers verified пофайлово** — `TopicCardVersion` L431, `TopicCard` L190 (поля L204-206/L230), repo `list_by_topic` **L72** (`purge_stale` L102 = TTL, не трогать; `count` L166), port L828, MCP `get_topic_versions` L2604/def L2606, live-card read `get_topic_details` `get_by_id` L1436 + `card.summary`/`scope_in`/`scope_out` L1463-1465 + `summary_version` L1473, `assert_topic_access` L50 (`PermissionDenied` L18), CLI `versions` L29, write-path L588, FUTURE_FEATURES L798. Ни одного invented symbol.
2. **Live-card read-path подтверждён** — `current`-сторона использует `card_repo.get_by_id` → `card.summary`/`card.scope_in`/`card.scope_out`; карточка уже грузится для access-check ⇒ без доп. вызова (согласовано с plan §3.2/§4.2).
3. **Dual-source (D4) + типы** — helper обобщён до `diff_topic_summaries(left, right)` над нормализованным value-object, т.к. `current` — `TopicCard`, а архив — `TopicCardVersion` (устранён type-mismatch). MCP arg `version_b: int | str | None` (число \| `"current"`).
4. **Gaps-контракт (D5)** — typed not-found на **любой** стороне, не 500; default genesis→current всегда осуществим (ADR-0018 §4/L110-112). Согласовано skeleton §8 / plan §9.
5. **Repo-метод optional** — `get_two_versions` (recommend) vs reuse `list_by_topic`; acceptance требует gaps-robастности, не конкретного символа (не предрешаем).
6. **OUT + ADR=НЕТ** — bot (#5), HTTP (#9), write/renumber, TTL-changes, schema/migration вынесены в §4; ADR §8 = НЕТ (read-only, не storage-контракт). Согласовано с plan §8/§11 и skeleton §9/§11.
7. **Read-only ⇒ нет prod-gate** — в отличие от TTL START_PROMPT, убраны backup/dry-run/owner-GO шаги; единственный gate — commit/PR.

---

## 10. Ссылки

- Plan: [`PLAN_SESSION_F5C_DIFF_API_2026-07-23.md`](PLAN_SESSION_F5C_DIFF_API_2026-07-23.md)
- Skeleton: [`SKELETON_F5C_DIFF_API_TOPIC_HISTORY_2026-07-23.md`](SKELETON_F5C_DIFF_API_TOPIC_HISTORY_2026-07-23.md)
- Retention interaction: [ADR-0018](../adr/0018-topic-card-versions-retention.md); TTL plan [`PLAN_SESSION_F5C_TTL_RETENTION_2026-07-22.md`](PLAN_SESSION_F5C_TTL_RETENTION_2026-07-22.md); TTL START_PROMPT (format ref) [`START_PROMPT_SESSION_F5C_TTL_RETENTION_2026-07-22.md`](START_PROMPT_SESSION_F5C_TTL_RETENTION_2026-07-22.md)
- Issue [#15](https://github.com/AlexEfimov/TG_parser/issues/15) item #2 diff API; [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) L798
- ADR [0006](../adr/0006-karpathy-like-living-kb-principles.md) (#1/#2/#4/#6), [0017](../adr/0017-dependency-management-policy.md) (dep policy — no new deps), [0018](../adr/0018-topic-card-versions-retention.md) (retention/gaps)
- Anchors: repo [`topic_card_version_repo.py`](../../tg_parser/storage/sqlalchemy/topic_card_version_repo.py) L72; port [`ports.py`](../../tg_parser/storage/ports.py) L828; MCP [`mcp_server.py`](../../tg_parser/mcp_server.py) L2604 / live-card L1463-1465; access [`auth/ownership.py`](../../tg_parser/auth/ownership.py) L50; CLI [`cli/topic_cmd.py`](../../tg_parser/cli/topic_cmd.py) L29; domain [`domain/models.py`](../../tg_parser/domain/models.py) L431 / L190
