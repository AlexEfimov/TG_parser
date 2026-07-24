# START PROMPT — Session: F5-C #15 item #3 — F6 topic-level digest (digest на `topic.summary`)

**Дата:** 2026-07-24 · **Тип:** implementation (Alembic migration + schema/model/repo + read-only content-selection + payload composition (reuse diff-API) + new prompt + MCP/CLI surface + scheduler reuse + **новый ADR-0019** + docs) · **Ветка:** feature-ветка от актуального `main` (напр. `feature/f5c-topic-digest`)

**Goal (одной строкой):** реализовать topic-scoped дайджест, контент которого — **эволюционирующая сводка темы** («что нового/что изменилось по теме X»), доставляемый по **уже существующему F6 пути** (subscription + scheduler + bot-push); payload каждой темы = один вызов зашедшего diff-API (`diff_topic_summaries`), с robust-fallback на TTL-gaps; подписка расширяется двумя режимами (`mode` = `'channel'|'topic'` + `topic_ids[]`) через новую миграцию.

> **✅ Design decisions final (2026-07-24).** Owner разрешил **все 7 форков Q1-Q7** (см. §7 + plan §9). Бриф полностью специфицирован. **ВАЖНО — это with-migration deploy:** в отличие от read-only diff-API (#2), фича **добавляет 2 колонки** в `digest_subscriptions` (Q5=a) ⇒ нужны **pre-deploy backup + `db upgrade`** и **малый ADR-0019** (F6 subscription-addendum). Это **НЕ** read-only.

> **Рабочий режим (нормативно, [`AGENTS.md`](../../AGENTS.md)):** `git commit` / PR — **только** по явному запросу пользователя (PR = merge-commit + `--delete-branch`). Никаких правок `docs/methodology/**`. `pyproject.toml` / `requirements.txt` — **не трогать** (ADR-0017; `difflib` — stdlib, новых deps нет). Уважать `docs/adr/` (accepted binding) и `docs/contracts/` (JSON Schema нерушимы). **Не трогать TTL-код** (`purge_stale` / retention Settings / cron, ADR-0018) — topic-digest лишь read-only consumer его gaps. **Не трогать raw-doc digest path** (`mode='channel'` bit-for-bit).

**Prerequisite SoT (перечитать перед кодом):**
- Plan (this feature): [`PLAN_SESSION_F5C_TOPIC_DIGEST_2026-07-24.md`](PLAN_SESSION_F5C_TOPIC_DIGEST_2026-07-24.md) — финальные решения §9, blast-radius §5, acceptance §7, ADR-need §11.
- Skeleton: [`SKELETON_F5C_TOPIC_DIGEST_2026-07-24.md`](SKELETON_F5C_TOPIC_DIGEST_2026-07-24.md) — reuse-map §4, DECIDED §8.
- Diff-API (#2, building block — payload builder): [`PLAN_SESSION_F5C_DIFF_API_2026-07-23.md`](PLAN_SESSION_F5C_DIFF_API_2026-07-23.md) + helper [`domain/topic_history_diff.py`](../../tg_parser/domain/topic_history_diff.py) L114.
- ADR: [ADR-0006](../adr/0006-karpathy-like-living-kb-principles.md) (#1/#5 living-KB, persistent subscriptions), [ADR-0008](../adr/0008-subscription-target-model.md) (delivery targets — неизменны), [ADR-0017](../adr/0017-dependency-management-policy.md) (no new deps), [ADR-0018](../adr/0018-topic-card-versions-retention.md) §4 (double-floor: genesis v1 + last-N всегда present ⇒ TTL-gap fallback чист).

---

## 0. TL;DR

| Step | Действие | Тип |
|---|---|---|
| 1 | **Migration + schema.** Новая Alembic-ревизия: `ALTER TABLE digest_subscriptions ADD COLUMN mode VARCHAR NOT NULL DEFAULT 'channel'` + `ADD COLUMN topic_ids TEXT[]` (nullable). ⚠️ **m2:** `20260418_add_digest_subscriptions.py` (rev `f6a1b2c3d4e5`) — только **структурный precedent** (форма ADD COLUMN), **НЕ** chaining-target; миграции разбиты на ветки `ingestion/`+`processing/` ⇒ `alembic heads` отдаёт **несколько** heads → `down_revision` = текущий **ingestion**-head (`alembic heads`, взять ingestion), а НЕ `f6a1b2c3d4e5`. Расширить `DigestSubscription` ([`domain/models.py`](../../tg_parser/domain/models.py) L763) двумя полями + `_SELECT_COLUMNS`/`create`/`update` ([`digest_subscription_repo.py`](../../tg_parser/storage/sqlalchemy/digest_subscription_repo.py) L14/L27/L106) + port ABC ([`storage/ports.py`](../../tg_parser/storage/ports.py) L1525) + result-DTO (m3) sync | code+test (migration up/down) |
| 2 | **Content-selection read-path (Q6=a).** Новый read-only `TopicCardRepo.list_topics_changed_since(scope, cursor) -> list[TopicCard]` — зеркало [`list_resummarize_candidates`](../../tg_parser/storage/sqlalchemy/topic_card_repo.py) L247; key = `last_summarized_at > :cursor` (строгий `>`); scope = channel/workspace non-sargable `sources_json LIKE` (reuse `list_by_channels` L201) **или** explicit `topic_ids`. ⚠️ `last_summarized_at` НЕ индексирован ⇒ seq-scan (index НЕ заявляем — см. §3.2). Write-path (`commit_resummary` L286) не трогаем | code+test |
| 3 | **Payload composition (Q2=a + Q7=B cumulative).** На изменившуюся тему: `prior` = состояние-на-cursor из `list_by_topic(topic_id, limit=keep_last_n)` ([`topic_card_version_repo.py`](../../tg_parser/storage/sqlalchemy/topic_card_version_repo.py) L72, newest-first WITH `created_at`) — новейшая версия с `created_at ≤ last_digest_cursor` → `diff_topic_summaries(snapshot_from_version(prior), snapshot_from_card(card))` ([`topic_history_diff.py`](../../tg_parser/domain/topic_history_diff.py) L114/L56/L74). Cumulative (state-at-cursor → current), покрывает multi-bump. Fallback: all-purged → oldest-surviving/genesis→current, пометка «baseline shifted (retention)»; **никогда 500 by construction**. `get_two_versions`/новый repo-метод НЕ нужен | code+test |
| 4 | **Render + prompt (Q4=a).** Новый `_render_topic_block` (зеркало `_render_channels_block` [`digest_service.py`](../../tg_parser/services/digest_service.py) L631) + **новый `prompts/topic_digest.yaml`** (reuse `DigestFormat` enum [`domain/models.py`](../../tg_parser/domain/models.py) L755; placeholders `{format,language,from_iso,to_iso,topics_block}` в стиле `digest.yaml` L50-60); `reload_prompts`-совместим. Channel `digest.yaml` **не** трогаем | code+test |
| 5 | **Subscription surface (Q1=both).** Extend `subscribe_digest` MCP ([`mcp_server.py`](../../tg_parser/mcp_server.py) L3101) доп. args `mode` + `topic_ids: list[str] | None`; `list_digests` L3335 / `unsubscribe_digest` L3388 reuse. CLI зеркало ([`cli/digest_cmd.py`](../../tg_parser/cli/digest_cmd.py) `add` L24) — `--mode`/`--topics` | code+test |
| 6 | **Scheduler reuse (Q3=a).** `mode`-branch внутри `DigestService.run_for_subscription`/`generate` ([`digest_service.py`](../../tg_parser/services/digest_service.py) L549/L351); тот же `run_scheduled_digests_task` ([`scheduler_service.py`](../../tg_parser/services/scheduler_service.py) L1093). Zero scheduler-plumbing change. Skip-if-empty + advance-cursor-only-on-success reuse | code(+test) |
| 7 | **Написать малый ADR-0019** (F6 subscription-addendum): `mode`+`topic_ids` меняют subscription-контракт; topic-mode reuse `last_digest_cursor`; отношение к ADR-0008/0006/0018. Файл `docs/adr/0019-f6-topic-digest-subscription-addendum.md` | docs (ADR) |
| 8 | **Docs.** FUTURE_FEATURES L799 → DONE/partial (+ MCP/CLI surface); F6 §L1031 note; skeleton → «landed» pointer | docs |
| 9 | **Quality gate.** ruff + `TEST_POSTGRES=1 uv run pytest -q` (трогаем migration/repo/service/MCP/CLI) | gate |
| 10 | **Deploy (with-migration).** pre-deploy backup БД + `alembic upgrade head`. **НЕ** read-only | ops |

**Recommended order:** 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9. Migration/schema первым (всё остальное зависит от полей); ADR + docs после кода; deploy — отдельным шагом по запросу.

**Hard OUT:** см. §4.

---

## 1. Контекст

F6 сегодня document-scoped: подписка ([`DigestSubscription`](../../tg_parser/domain/models.py) L763) несёт `channel_ids[]` (L788) + `last_digest_cursor` (`processed_at`-timestamp, L810); каждый tick [`DigestService.generate`](../../tg_parser/services/digest_service.py) L351 тянет новые `ProcessedDocument` (`processed_at > cursor`, строгий `>`, docstring L10-20, filter L382-393), рендерит per-channel блок raw-сводок (`_render_channels_block` L631) и просит LLM собрать digest ([`prompts/digest.yaml`](../../prompts/digest.yaml)). Контент = raw new-document summaries за окно.

F5-C сделал темы живыми: `commit_resummary` ([`topic_card_repo.py`](../../tg_parser/storage/sqlalchemy/topic_card_repo.py) L286) бампит `summary_version`, обновляет `summary`/`scope_in`/`scope_out`/`last_summarized_at`; snapshot *предыдущего* состояния уходит в `topic_card_versions`. `topic.summary` — first-class evolving synthesis (ADR-0006 #1/#5).

diff-API (#2) зашёл — недостающий кирпич: `diff_topic_summaries(left, right)` ([`domain/topic_history_diff.py`](../../tg_parser/domain/topic_history_diff.py) L114) считает «что изменилось» между двумя snapshot'ами (text-diff `summary` через stdlib `difflib` + set-diff `scope_in`/`scope_out`), читая archival-версии через `get_two_versions` ([`topic_card_version_repo.py`](../../tg_parser/storage/sqlalchemy/topic_card_version_repo.py) L102) **и** живую карточку (`snapshot_from_card` L74). **«Что нового по теме X» = один вызов `diff_topic_summaries`** ⇒ topic-digest — композиция уже зашедших read-path'ов + F6 delivery + schema-add для scope.

**Разница одной строкой:** F6 today = `channel_ids` × raw ProcessedDocument summaries × `processed_at`-окно; topic-digest = topic-scope (`mode`/`topic_ids`) × delta эволюционирующей `topic_card.summary` × `last_summarized_at`-окно.

**Критическая семантика `version_no` (design-defining):** write-path ([`resummarization_service.py`](../../tg_parser/services/resummarization_service.py) L585-599) пишет `version_no = card.summary_version` — snapshot **предыдущего** состояния; живой current (vN) лежит **только** на `topic_cards` и в таблице версий отсутствует. diff-API уже решает это dual-source (`current` = живая карточка через `snapshot_from_card`) ⇒ topic-digest наследует бесплатно.

---

## 2. Anchors (перечитать перед правкой — verified 2026-07-24)

| Якорь | Файл | Строка | Роль |
|---|---|---|---|
| `DigestSubscription` (расширить `mode`/`topic_ids`) | [`domain/models.py`](../../tg_parser/domain/models.py) | **L763** (`channel_ids` L788, `workspace_id` L789, `format` L803, `last_digest_cursor` L810) | subscription-модель + reuse cursor (Q6) |
| `DigestFormat` enum (reuse для output-стиля) | [`domain/models.py`](../../tg_parser/domain/models.py) | **L755** (`summary`/`bullets`/`detailed`) | Q4=a — output style без нового enum |
| `TopicCard` (live-side snapshot + content-selection key) | [`domain/models.py`](../../tg_parser/domain/models.py) | **L190** (`summary` L204, `scope_in`/`out` L205-206, `sources` L213, `last_summarized_at` **L226**, `summary_version` **L230**) | `current`-сторона diff + cursor-key |
| `TopicCardVersion` (archival snapshot) | [`domain/models.py`](../../tg_parser/domain/models.py) | **L431** | prior-сторона diff |
| Subscription repo (SA) — расширить | [`storage/sqlalchemy/digest_subscription_repo.py`](../../tg_parser/storage/sqlalchemy/digest_subscription_repo.py) | **L21** (`_SELECT_COLUMNS` **L14**, `create` **L27**, `update` **L106**, `list_active` L206) | +2 колонки в SELECT/create/update |
| Subscription repo port (ABC sync) | [`storage/ports.py`](../../tg_parser/storage/ports.py) | `DigestSubscriptionRepo` **L1525** | сигнатуры/поля sync |
| Migration **structure** precedent (F6 schema) | [`migrations/versions/ingestion/20260418_add_digest_subscriptions.py`](../../migrations/versions/ingestion/20260418_add_digest_subscriptions.py) | revision `f6a1b2c3d4e5` | **только форма** ADD COLUMN, **НЕ** down_revision-target; chain от ingestion-head (`alembic heads`, multi-head) — m2 |
| **DigestService** (compose/deliver/render) | [`services/digest_service.py`](../../tg_parser/services/digest_service.py) | class **L148**; `subscribe` **L180**; `generate` **L351**; filter L382-393; `run_for_subscription` **L549**; `_render_channels_block` **L631** (зеркалить → `_render_topic_block`) | reuse-хребет + mode-branch |
| Digest cursor invariant (строгий `>`) | [`services/digest_service.py`](../../tg_parser/services/digest_service.py) | docstring **L10-20** | cursor-семантика для topic (Q6) |
| Content-selection паттерн | [`storage/sqlalchemy/topic_card_repo.py`](../../tg_parser/storage/sqlalchemy/topic_card_repo.py) | `list_resummarize_candidates` **L247** (`last_summarized_at` branch **L275**); `list_by_channels` **L201** (LIKE scope); `commit_resummary` **L286** (НЕ трогать) | зеркало для `list_topics_changed_since` |
| **diff helper (payload)** | [`domain/topic_history_diff.py`](../../tg_parser/domain/topic_history_diff.py) | `diff_topic_summaries` **L114**, `snapshot_from_version` **L56**, `snapshot_from_card` **L74** | «what changed» = один вызов; reuse as-is |
| Versions read-path (prior-selection + gaps) | [`storage/sqlalchemy/topic_card_version_repo.py`](../../tg_parser/storage/sqlalchemy/topic_card_version_repo.py) | **`list_by_topic` L72** (newest-first WITH `created_at`); `purge_stale` **L142** (TTL — НЕ трогать) | Q7=B prior-selection (новейшая версия с `created_at ≤ cursor`); `get_two_versions` (L102, by-`version_no`) для prior **НЕ** используется |
| MCP F6 tools (extend) | [`mcp_server.py`](../../tg_parser/mcp_server.py) | `subscribe_digest` **L3101**, `list_digests` **L3335**, `unsubscribe_digest` **L3388** | Q1 — `mode`/`topic_ids` args |
| Topic visibility (precedent) | [`mcp_server.py`](../../tg_parser/mcp_server.py) | `get_topic_details` **L1408** | mental model видимости топика |
| Access enforcement | [`auth/ownership.py`](../../tg_parser/auth/ownership.py) | `assert_topic_access` **L50** | доступ если виден ≥1 из `card.sources` |
| Scheduler task entry (reuse) | [`services/scheduler_service.py`](../../tg_parser/services/scheduler_service.py) | `run_scheduled_digests_task` **L1093**; `run_resummarize_for_channel` **L1173** (event-hook — OUT) | Q3=a cron reuse |
| Scheduler cron wiring (reuse) | [`services/background_scheduler.py`](../../tg_parser/services/background_scheduler.py) | `register_digest_subscription` **L492**, `_digest_job_id` **L487** | job-lifecycle reuse |
| CLI subapp `digest` (зеркалить) | [`cli/digest_cmd.py`](../../tg_parser/cli/digest_cmd.py) | `add` **L24** (`@app.command`) | CLI зеркало для both modes |
| Channel digest prompt (reference, НЕ трогать) | [`prompts/digest.yaml`](../../prompts/digest.yaml) | placeholders **L50-60** | форма для нового `topic_digest.yaml` |
| Retention interaction (Q7 basis) | [ADR-0018](../adr/0018-topic-card-versions-retention.md) | §4 | «gaps = policy; genesis + last-N present ⇒ не 500» |

---

## 3. Scope — детально

### 3.1 Migration + schema (Q1/Q5=a — code+test)
- Новая Alembic-ревизия в `migrations/versions/ingestion/`: additive `ALTER TABLE digest_subscriptions ADD COLUMN mode VARCHAR NOT NULL DEFAULT 'channel'` + `ADD COLUMN topic_ids TEXT[]` (nullable). `downgrade` дропает обе колонки. ⚠️ **m2:** `down_revision` определить через `alembic heads` — миграции разбиты на ветки `ingestion/` и `processing/`, поэтому `alembic heads` возвращает **несколько** heads; чейниться от текущего **ingestion**-head. `20260418_add_digest_subscriptions.py` (`f6a1b2c3d4e5`) — только **структурный precedent** формы ADD COLUMN (idempotent guards), **НЕ** сам down_revision.
- `DigestSubscription` ([`domain/models.py`](../../tg_parser/domain/models.py) L763): `mode: str = 'channel'` (или узкий `StrEnum` `DigestMode`), `topic_ids: list[str] | None = None`.
- Repo: `_SELECT_COLUMNS` L14 + `create` L27 + `update` L106 ([`digest_subscription_repo.py`](../../tg_parser/storage/sqlalchemy/digest_subscription_repo.py)) — добавить оба поля; port ABC ([`storage/ports.py`](../../tg_parser/storage/ports.py) L1525) sync. **m3:** result-DTO (`SubscribeDigestResult` + `subscribe_digest` result serialization возле [`mcp_server.py`](../../tg_parser/mcp_server.py) L3090-3097) тоже расширить `mode`/`topic_ids` (§3.5).
- **Invariant:** `mode='channel'` без `topic_ids` = сегодняшний raw-doc digest bit-for-bit (no regression). Валидация: `mode='topic'` требует непустой `topic_ids`.

### 3.2 Content-selection read-path (Q6=a — code+test)
- Новый read-only `TopicCardRepo.list_topics_changed_since(scope, cursor) -> list[TopicCard]` — зеркало [`list_resummarize_candidates`](../../tg_parser/storage/sqlalchemy/topic_card_repo.py) L247 (тот же `_row_to_model`). ⚠️ NB: скорость `list_resummarize_candidates` — от **partial-index `idx_topic_cards_resummarize_candidates WHERE new_items_since_last_summary > 0`**; здесь же фильтр `last_summarized_at > :cursor` **НЕ проиндексирован**, а channel-scope — non-sargable `sources_json LIKE '%"cid"%'` (идиома `list_by_channels`) ⇒ full/seq-scan. Приемлемо на текущем объёме; **index НЕ заявляем** (partial-index на `last_summarized_at` — deferred/OUT при росте, в этот slice не бюджетируем).
- **cursor key:** `last_summarized_at > :cursor` (строгий `>`; см. §L10-20 — repo может отдавать `>=`, фильтровать строго). `cursor is None` (first run **или** mode-change reset, M3) → reuse F6 `first_run_lookback_hours` семантику.
- **scope:** `mode='channel'` → `sources_json LIKE` по каждому channel в `channel_ids`/workspace (reuse `list_by_channels` L201 паттерн); `mode='topic'` → `id IN (:topic_ids)`.
- **NULL-safety (m1):** never-re-summarized / pre-F5-C темы имеют `last_summarized_at = NULL` ⇒ `NULL > :cursor` = false ⇒ они исключаются фильтром. Именно это (а **не** ADR-0018 double-floor) — реальный safety mechanism «тема никогда не приходит без версий». NB implementer: docstring `TopicCardVersion` ([`domain/models.py`](../../tg_parser/domain/models.py) ~L436, «first version is never materialised») вводит в заблуждение — не доверять как источнику инварианта.
- **Delivery-time visibility filter (M4):** на каждом tick в topic-mode отбрасывать тему, чьи `card.sources` больше **не** пересекаются с allowed-channels владельца на момент tick (revoked access не должен утекать evolving topic summaries). Существующий channel-mode F6 на доставке НЕ перепроверяет — это намеренное parity-улучшение. Visibility покрыта на **обоих** этапах: subscribe (`assert_topic_access` §3.5) + delivery (source-intersection filter здесь).
- Unit-тест: changed vs unchanged (строгий `>`); channel-scope; workspace-scope; explicit topic-scope; empty cursor lookback; NULL `last_summarized_at` исключён; revoked-access тема отброшена на delivery.

### 3.3 Payload composition (Q2=a + Q7=B cumulative — code+test)
- На каждую изменившуюся тему: `right` = живая карточка (`snapshot_from_card(card)` L74); `prior` = состояние, которое пользователь видел на прошлый digest — из `list_by_topic(topic_id, limit=keep_last_n)` ([`topic_card_version_repo.py`](../../tg_parser/storage/sqlalchemy/topic_card_version_repo.py) L72, newest-first WITH `created_at`) берём в Python **новейшую версию с `created_at ≤ last_digest_cursor`** (at-or-before, не ≥). Один вызов `diff_topic_summaries(snapshot_from_version(prior), right_snapshot)` ([`topic_history_diff.py`](../../tg_parser/domain/topic_history_diff.py) L114). **Ноль нового/ре-имплементированного diff-кода И ноль нового repo-метода** (`list_by_topic` уже существует).
- Это **cumulative** «что изменилось с прошлого digest» (state-at-cursor → current), **НЕ** last-delta v(N−1)→current: если тема ре-суммаризовалась k× с прошлого digest, все k дельт попадают в один diff (prior = состояние-на-cursor).
- **Q7=B fallback** на TTL-gaps: если ни одна выжившая версия не удовлетворяет `created_at ≤ cursor` (всё выпилено TTL) → самая старая сохранившаяся версия, иначе **genesis (v1) → current** с пометкой в payload `baseline_shifted: "retention"`. **никогда 500 by construction** — диффим то, что физически выжило (отсутствующие строки лишь сдвигают fallback, не роняют lookup). NB: `prior` **не** выбирается через `get_two_versions` (point-lookup по `version_no` не маппит cursor-timestamp в версию — это был BLOCKER); `version_at_or_before`-подобный timestamp→version SQL-метод **НЕ** нужен.
- **Cost:** `list_by_topic` грузит ≤ keep_last_n (≤50) version-строк на подписанную тему за tick — незначительно на digest-cadence.
- Unit-тест: happy diff (newest ≤ cursor); multi-bump-between-ticks (k дельт cumulative); purged-intermediate → корректный prior из выживших; all-purged → oldest-surviving/genesis→current + `baseline_shifted`; no-change тема исключена.

### 3.4 Render + prompt (Q4=a — code+test)
- Новый `_render_topic_block` (зеркало `_render_channels_block` [`digest_service.py`](../../tg_parser/services/digest_service.py) L631): на тему — title + summary-delta (unified-diff-строки) + added/removed scope + provenance (version_no/`current` labels из diff-result).
- Новый файл `prompts/topic_digest.yaml` — форма [`prompts/digest.yaml`](../../prompts/digest.yaml) L50-60 (system.prompt + user.template + model), placeholders `{format,language,from_iso,to_iso,topics_block}`, reuse `DigestFormat` (L755) для стиля. `reload_prompts`-совместим. Channel `digest.yaml` **не** трогаем.

### 3.5 Subscription surface (Q1=both — code+test)
- MCP: extend `subscribe_digest` ([`mcp_server.py`](../../tg_parser/mcp_server.py) L3101) — доп. args `mode: str = 'channel'`, `topic_ids: list[str] | None = None`; провалидировать (topic-mode ⇒ topic_ids непустой; каждый topic visible через `assert_topic_access` [`auth/ownership.py`](../../tg_parser/auth/ownership.py) L50). `list_digests` L3335 / `unsubscribe_digest` L3388 — reuse.
- **m3 (result DTOs):** чтобы `mode`/`topic_ids` реально появились в результатах `list_digests` и subscribe, обновить и **result-DTO** — напр. `SubscribeDigestResult` + сериализацию результата `subscribe_digest` возле [`mcp_server.py`](../../tg_parser/mcp_server.py) L3090-3097 (не только repo/model/port).
- **M3 (cursor reset on mode-change):** `subscribe` idempotent-upsert на `(owner_id, name)`; при смене `mode` существующей подписки сбросить `last_digest_cursor` в NULL (одно поле — две семантики: channel=`processed_at`, topic=`last_summarized_at`; stale cursor неверной семантики → неверное первое окно).
- CLI: зеркало в [`cli/digest_cmd.py`](../../tg_parser/cli/digest_cmd.py) (`add` L24) — `--mode`, `--topics` (csv, reuse `_split_csv`).
- Tests: subscribe topic-mode happy; channel-mode unchanged; topic-mode без topic_ids → error; no-access topic → error-shape; mode-change → cursor reset to NULL; DTO carries `mode`/`topic_ids`.

### 3.6 Scheduler reuse (Q3=a — code, +test)
- `mode`-branch внутри `DigestService` (`generate`/`run_for_subscription` L351/L549): `mode='topic'` → content-selection §3.2 + payload §3.3 + render §3.4; `mode='channel'` → существующий путь bit-for-bit.
- Тот же `run_scheduled_digests_task` ([`scheduler_service.py`](../../tg_parser/services/scheduler_service.py) L1093) + `register_digest_subscription` (L492) — **zero** scheduler-plumbing change. Advance-cursor-only-on-success + skip-if-empty reuse.

### 3.7 ADR-0019 (docs)
- `docs/adr/0019-f6-topic-digest-subscription-addendum.md`: F6 subscription addendum — `mode`/`topic_ids` как нормативная часть digest data-model; topic-mode reuse `last_digest_cursor` (Q6, reset-to-NULL при смене mode); отношение к ADR-0008 (delivery targets неизменны), ADR-0006 (#1/#5), ADR-0018 (Q7=B cumulative prior via `list_by_topic`). Status: accepted (или proposed→accepted по процессу).

### 3.8 Docs (docs)
- FUTURE_FEATURES L799 → DONE/partial + surface (MCP `subscribe_digest` mode/topic + CLI). F6 §L1031 note (topic-digest landed). Skeleton → «landed» pointer.

---

## 4. Out of scope (жёстко)

- **#5 Bot tools** (topic-digest subscribe UX в Telegram) — this slice = MCP/CLI + scheduler.
- **Event-on-resummarize trigger (Q3-b)** — hook `run_resummarize_for_channel` ([`scheduler_service.py`](../../tg_parser/services/scheduler_service.py) L1173): OUT / fast-follow (новый plumbing + свой idempotency/cursor против дубль-доставки). Только cron reuse (Q3=a).
- **Email / webhook delivery** — только bot-push (ADR-0008 targets: chat/channel).
- **Per-topic / cross-topic dedup** — F5-B concern.
- **Non-additive schema-rewrite** — только additive +2 колонки; переработка существующих колонок / full redesign OUT.
- **Raw-doc digest regression** — существующий `mode='channel'` bit-for-bit; путь не менять кроме mode-branch.
- **TTL / retention changes** (ADR-0018 / `purge_stale` L142 / retention Settings / cron) — read-only consumer gaps.
- **diff-API changes** — `diff_topic_summaries` / `list_by_topic` reuse as-is; нового diff surface нет, нового repo-метода нет.
- **New deps** — `difflib` stdlib (ADR-0017); `pyproject`/`requirements` не трогать.
- **#6 type-promotion, #7 topic dedup, #8 bundle-item GC, #9 HTTP endpoints** — separate #15 items. **Wave E** graph retrieval, **F11 HTTP CRUD**, **webhook 2A (ADR-0008)**.
- `docs/methodology/**`, `pyproject.toml`, `requirements.txt`.

---

## 5. Acceptance criteria

- [ ] **Both modes (Q1):** подписка `mode='topic'`+`topic_ids[]` выбирает явные темы; `mode='channel'` — все active-темы в scope. Tick эмитит digest, контент = **delta эволюционирующей сводки темы** (Q2=a diff), **не** raw doc summaries.
- [ ] **Schema-add (Q5):** миграция добавляет `mode`+`topic_ids`; `upgrade`/`downgrade` идемпотентны; `mode='channel'` без `topic_ids` = сегодняшний F6 bit-for-bit (no regression).
- [ ] **Content-selection (Q6):** `list_topics_changed_since` отдаёт только темы с `last_summarized_at > last_digest_cursor` (строгий `>`, нет ре-включения); cursor advance **только** на успешной доставке/empty-skip; **новое** cursor-поле НЕ добавлено (reuse `last_digest_cursor`). NULL `last_summarized_at` темы исключены (m1 safety).
- [ ] **Cursor reset on mode-change (M3):** смена `mode` существующей подписки сбрасывает `last_digest_cursor` в NULL (перезапуск first-run lookback новой семантики); без reset stale cursor неверной семантики → неверное первое окно.
- [ ] **Cumulative prior + TTL-gap robust (Q7=B):** `prior` = новейшая версия с `created_at ≤ last_digest_cursor` из `list_by_topic` (cumulative «с прошлого digest», покрывает multi-bump); all-purged → oldest-surviving/genesis→current с `baseline_shifted: retention`, **никогда 500 by construction**. `get_two_versions`/timestamp→version SQL-метод НЕ используется.
- [ ] **Diff-reuse (Q2=a):** payload вызывает зашедший `diff_topic_summaries` (нет ре-имплементации diff-логики).
- [ ] **Prompt (Q4=a):** новый `prompts/topic_digest.yaml`, reuse `DigestFormat`; channel `digest.yaml` не тронут; `reload_prompts`-совместим.
- [ ] **Scheduler (Q3=a):** тот же `run_scheduled_digests_task` cron path; нет нового scheduler plumbing; нет дубль-доставки.
- [ ] **Visibility на ОБОИХ этапах (M4):** subscribe — `assert_topic_access` (тема видна если user видит ≥1 из `card.sources`); delivery — topic-mode content-selection отбрасывает тему, чьи `card.sources` больше не пересекаются с allowed-channels владельца на момент tick (revoked access не утекает). Deliberate parity-улучшение vs channel-mode F6 (не перепроверяет на доставке). topic-not-found / no-access → структурированный `{"error": ...}`, не exception.
- [ ] **Нет новых deps** (`difflib` stdlib, ADR-0017; `pyproject`/`requirements` не тронуты); delivery/scheduler/subscription-lifecycle reused.
- [ ] `uv run ruff check .` + `uv run ruff format --check .` + `TEST_POSTGRES=1 uv run pytest -q` — green.
- [ ] **ADR-0019** (F6 subscription-addendum) написан и accepted; FUTURE_FEATURES / skeleton pointer обновлены.
- [ ] **Deploy (with-migration):** pre-deploy backup снят + `alembic upgrade head` прогнан (§6) — **НЕ** read-only.
- [ ] Commit/PR только по явному запросу пользователя.

---

## 6. Quality / ops gate commands

```bash
# repo quality (local, всегда)
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
# PR-standard (трогаем migration/repo/service/MCP/CLI paths → нужен Postgres):
TEST_POSTGRES=1 uv run pytest -q
# Runner note: tests/README.md L76 предпочитает `.venv/bin/python -m pytest` для real runs;
# `uv run pytest` — принятый эквивалент (те же режимы default / TEST_POSTGRES=1).

# migration sanity (before deploy):
alembic heads                     # определить актуальный head для down_revision
alembic upgrade head              # применить новую ревизию (+2 колонки)
alembic downgrade -1              # проверить обратимость (в dev)

# manual smoke (после impl):
tg-parser digest add --user <uuid> --chat-id 123 --name "AI topics" \
    --mode topic --topics topic:abc,topic:def --channels @c1
```

_**With-migration deploy (В ОТЛИЧИЕ от read-only diff-API #2):** 1) pre-deploy **backup** БД (schema-change); 2) `alembic upgrade head` (новая ревизия — additive/nullable/default ⇒ безопасный upgrade). Content-selection сам read-only, но deploy трогает schema ⇒ backup + upgrade **обязательны**._

---

## 7. Decisions (final — все 7 owner-решений приняты 2026-07-24; см. plan §9)

1. **Q1. Subscription granularity = BOTH modes** — `mode` (`'channel'|'topic'`) + `topic_ids[]`; channel/workspace "all active topics" mode **И** explicit topics.
2. **Q2. "What's new" = (a) diff-of-summaries** — reuse `diff_topic_summaries` (text-diff `summary` + set-diff scopes); нет ре-имплементации diff-логики.
3. **Q3. Trigger = (a) reuse F6 cron cadence** — тот же `run_scheduled_digests_task`; zero scheduler-plumbing change; нет дубль-доставки. Event-on-resummarize — OUT/fast-follow.
4. **Q4. Delivery format = (a) new `prompts/topic_digest.yaml`** — отдельный prompt-файл, reuse `DigestFormat` enum для output-стиля.
5. **Q5. Schema shape = (a) add columns** — `mode VARCHAR` + `topic_ids TEXT[]` на `digest_subscriptions` через новую миграцию. Меняет F6 subscription data-model ⇒ **малый ADR-0019 обязателен**.
6. **Q6. Cursor = (a) `topic_cards.last_summarized_at > cursor` (строгий `>`), reuse `last_digest_cursor`** — advance-only-on-success; новое cursor-поле НЕ добавляем. **Mode-change reset (M3):** т.к. `subscribe` idempotent-upsert на `(owner_id, name)` и `last_digest_cursor` — единый TIMESTAMPTZ с двумя семантиками (channel=`processed_at`, topic=`last_summarized_at`), при смене `mode` существующей подписки cursor **сбрасывается в NULL** (перезапуск first-run lookback новой семантики) — иначе stale cursor неверной семантики → неверное первое окно.
7. **Q7. Prior-side + TTL-gap robustness = (B) cumulative prior via `list_by_topic`.** `prior` = состояние-на-cursor: `list_by_topic(topic_id, limit=keep_last_n)` (L72, newest-first WITH `created_at`) → новейшая версия с `created_at ≤ last_digest_cursor`; all-purged → oldest-surviving/genesis→current, пометка «baseline shifted (retention)»; `current` всегда = живая карточка. TRUE cumulative (покрывает multi-bump-between-ticks), **никогда 500 by construction** (диффим то, что физически выжило), **ноль нового repo-метода**. `get_two_versions` (by-`version_no`) для prior НЕ используется; `version_at_or_before`-подобный SQL-метод НЕ нужен.

**Consequence (нормативно):** это **with-migration** deploy — нужен `db upgrade` + pre-deploy backup + **новый ADR-0019**. **НЕ** read-only (в отличие от diff-API #2). **Execution-gate:** commit/PR — только по явному запросу пользователя.

---

## 8. Нужен ли новый ADR? — **ДА, ADR-0019 (F6 subscription-addendum)**

Q5=schema-add ⇒ ADR **обязателен**: `mode`/`topic_ids` становятся нормативной частью F6 digest data-model — меняется, что есть «подписка» (channel-scoped → channel|topic-scoped). Decision класса ADR-per-decision (как ADR-0008 subscription-target-model, 0018 retention). **Next-free номер = ADR-0019** (last in [`docs/adr/`](../adr/) = 0018-topic-card-versions-retention; verified 2026-07-24 via `ls docs/adr/`). Файл пишется **в этой impl-сессии** (step §0.7). Контраст: diff-API #2 остался ADR-free — он лишь **читал** существующие колонки; topic-digest **добавляет** колонки.

---

## 9. Self-review fixes applied (START_PROMPT)

Критический pass (internal consistency vs plan+skeleton / anchor-correctness re-open пофайлово / testable acceptance / explicit OUT / TTL-gap robustness / reuse of shipped diff-API / with-migration consequence):

1. **Q1-Q7 baked consistently** — §0/§3/§5/§7 согласованы с plan §9 и skeleton §8: Q1=both, Q2=a, Q3=a, Q4=a, Q5=a, Q6=a (+reset-to-NULL при смене mode, M3), Q7=B (cumulative prior via `list_by_topic`). Ни одного места, считающего форк открытым.
2. **Anchor-correctness re-verify пофайловым чтением (2026-07-24)** — `DigestSubscription` L763 (`channel_ids` L788, `workspace_id` L789, `format` L803, `last_digest_cursor` L810), `DigestFormat` L755, `TopicCard` L190 (`last_summarized_at` L226, `summary_version` L230), `TopicCardVersion` L431; `digest_subscription_repo` `_SELECT_COLUMNS` L14 / `create` L27 / `update` L106; port L1525; migration precedent `f6a1b2c3d4e5`; `DigestService` `subscribe` L180 / `generate` L351 / filter L382-393 / `run_for_subscription` L549 / `_render_channels_block` L631 / docstring L10-20; `list_resummarize_candidates` L247 (`last_summarized_at` L275) / `list_by_channels` L201 / `commit_resummary` L286; `diff_topic_summaries` L114 / `snapshot_from_version` L56 / `snapshot_from_card` L74; `get_two_versions` L102 / `purge_stale` L142; MCP `subscribe_digest` L3101 / `list_digests` L3335 / `unsubscribe_digest` L3388 / `get_topic_details` L1408; `assert_topic_access` L50; scheduler `run_scheduled_digests_task` L1093 / `run_resummarize_for_channel` L1173; `register_digest_subscription` L492 / `_digest_job_id` L487; CLI `digest_cmd.py` `add` L24; `prompts/digest.yaml` L50-60. Ни одного invented symbol.
3. **ADR-0019 verified next-free** — `ls docs/adr/` → last 0018 ⇒ 0019 свободен (§8); ADR пишется в impl-сессии как step §0.7, не сейчас.
4. **With-migration consequence явно противопоставлено diff-API #2** — banner, §6 deploy note, §7 consequence, acceptance §5: backup + `db upgrade` обязательны; НЕ read-only.
5. **Q7=B cumulative prior конкретизирован и testable** — `prior` = новейшая версия с `created_at ≤ cursor` из `list_by_topic` (cumulative, покрывает multi-bump) → all-purged oldest-surviving/genesis→current → `baseline_shifted: retention`; **никогда 500 by construction**; §3.3 unit-тесты покрывают ветки; `get_two_versions`/timestamp→version SQL-метод НЕ используется (BLOCKER-fix).
6. **diff-API reused as-is + zero new repo-метод** — payload = один вызов `diff_topic_summaries` (§3.3), prior из существующего `list_by_topic`; нет нового diff surface; в OUT явно «diff-API changes».
7. **Explicit OUT §4** — Bot(#5), event-on-resummarize(Q3-b), email/webhook, dedup, non-additive schema-rewrite, raw-doc regression, TTL/diff changes, new deps, #6-#9, methodology/pyproject. Согласовано с plan §8 / skeleton §9.
8. **Governance block** — commit/PR только по запросу; no methodology/pyproject/requirements edits; ADR/contracts respected. Приведено в header (нормативный блок).
9. **Adversarial-review resolutions applied (2026-07-24, owner-decided).** B1+M1: Q7 a′→**B cumulative prior via `list_by_topic`** — prior = новейшая версия с `created_at ≤ cursor` (§0 step3/§3.3/§7 Q7); `get_two_versions`/`version_at_or_before` SQL-метод убран (BLOCKER: by-`version_no` не маппит cursor→version); never-500 by construction честно; cumulative (multi-bump), не v(N−1). M2: ложный "partial-index-friendly/cheap" claim убран — `last_summarized_at` unindexed + non-sargable `sources_json LIKE` ⇒ seq-scan (§0 step2/§3.2). M3: mode-change → cursor reset to NULL (§3.5/§5/§7 Q6). M4: delivery-time visibility filter (§3.2/§5). m1: NULL-`last_summarized_at` exclusion = safety mechanism + docstring-warning ~L436 (§3.2). m2: multi-head alembic — chain от ingestion-head, не `f6a1b2c3d4e5` (§0 step1/§2/§3.1). m3: result-DTO (`SubscribeDigestResult` + serialization L3090-3097) расширить `mode`/`topic_ids` (§3.1/§3.5).

---

## 10. Ссылки

- Plan: [`PLAN_SESSION_F5C_TOPIC_DIGEST_2026-07-24.md`](PLAN_SESSION_F5C_TOPIC_DIGEST_2026-07-24.md)
- Skeleton: [`SKELETON_F5C_TOPIC_DIGEST_2026-07-24.md`](SKELETON_F5C_TOPIC_DIGEST_2026-07-24.md)
- Diff-API (#2, building block): [`PLAN_SESSION_F5C_DIFF_API_2026-07-23.md`](PLAN_SESSION_F5C_DIFF_API_2026-07-23.md), START_PROMPT (format ref) [`START_PROMPT_SESSION_F5C_DIFF_API_2026-07-23.md`](START_PROMPT_SESSION_F5C_DIFF_API_2026-07-23.md); helper [`domain/topic_history_diff.py`](../../tg_parser/domain/topic_history_diff.py) L114
- TTL/retention (#1, gaps): [ADR-0018](../adr/0018-topic-card-versions-retention.md); [`PLAN_SESSION_F5C_TTL_RETENTION_2026-07-22.md`](PLAN_SESSION_F5C_TTL_RETENTION_2026-07-22.md)
- Issue [#15](https://github.com/AlexEfimov/TG_parser/issues/15) item #3; [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) L799 / F6 §L884-1033 (L1022 Per-topic, L1031 F5-C reuse)
- ADR [0006](../adr/0006-karpathy-like-living-kb-principles.md), [0008](../adr/0008-subscription-target-model.md), [0017](../adr/0017-dependency-management-policy.md), [0018](../adr/0018-topic-card-versions-retention.md); **ADR-0019** (to write this session)
- Anchors: models [`domain/models.py`](../../tg_parser/domain/models.py) L763/L755/L190/L431; repo [`digest_subscription_repo.py`](../../tg_parser/storage/sqlalchemy/digest_subscription_repo.py) L14/L27/L106; port [`ports.py`](../../tg_parser/storage/ports.py) L1525; service [`digest_service.py`](../../tg_parser/services/digest_service.py) L351/L549/L631; topic repo [`topic_card_repo.py`](../../tg_parser/storage/sqlalchemy/topic_card_repo.py) L247/L201/L286; diff [`topic_history_diff.py`](../../tg_parser/domain/topic_history_diff.py) L114; versions [`topic_card_version_repo.py`](../../tg_parser/storage/sqlalchemy/topic_card_version_repo.py) L102/L142; MCP [`mcp_server.py`](../../tg_parser/mcp_server.py) L3101/L1408; scheduler [`scheduler_service.py`](../../tg_parser/services/scheduler_service.py) L1093; access [`auth/ownership.py`](../../tg_parser/auth/ownership.py) L50; CLI [`cli/digest_cmd.py`](../../tg_parser/cli/digest_cmd.py) L24
