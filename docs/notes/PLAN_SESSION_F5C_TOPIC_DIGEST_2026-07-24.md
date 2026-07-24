# Plan — Session: F5-C #15 item #3 — F6 topic-level digest (digest на `topic.summary`)

**Дата:** 2026-07-24 · **Тип:** implementation planning note (**decisions-resolved**, **START_PROMPT authored**) · **Branch:** `docs/f5c-topic-digest-planning` (docs-only planning; commit/PR — **только** по явному запросу пользователя, [`AGENTS.md`](../../AGENTS.md)).

**Goal (одной строкой):** спроектировать topic-scoped дайджест, контент которого — **эволюционирующая сводка темы** («что нового/что изменилось по теме X»), а не raw per-document summaries, доставляемый по **уже существующему F6 пути** (subscription + scheduler + bot-push); естественный payload одной записи topic-дайджеста — это выход только что зашедшего diff-API (#2, `diff_topic_summaries`).

> **Статус решений (2026-07-24):** owner **разрешил все 7 форков Q1-Q7** — §9 теперь полностью **DECIDED** (Pre-baked P1-P6 + owner-resolved Q1-Q7). START_PROMPT написан: [`START_PROMPT_SESSION_F5C_TOPIC_DIGEST_2026-07-24.md`](START_PROMPT_SESSION_F5C_TOPIC_DIGEST_2026-07-24.md). **Ключевое следствие:** в отличие от read-only diff-API (#2), эта фича — **with-migration deploy** (Q5 = schema-add `mode`+`topic_ids` на `digest_subscriptions`) ⇒ нужны **pre-deploy backup + `db upgrade`** и **малый ADR (F6 subscription-addendum, ADR-0019)**. Это **НЕ** read-only.

> Этот документ развивает [`SKELETON_F5C_TOPIC_DIGEST_2026-07-24.md`](SKELETON_F5C_TOPIC_DIGEST_2026-07-24.md) в исполнимый бриф-скелет: контекст, anchored read-paths, blast-radius, decided-форки, acceptance. Impl-код (и написание ADR-0019) — в отдельной реализующей сессии по START_PROMPT.

---

## 1. Контекст и why-now

- **F6 сегодня document-scoped.** Подписка ([`DigestSubscription`](../../tg_parser/domain/models.py) L763) несёт `channel_ids[]` (L788) + `last_digest_cursor` (`processed_at`-timestamp, L810). Каждый tick [`DigestService.generate`](../../tg_parser/services/digest_service.py) L351 тянет новые `ProcessedDocument` (`processed_at > last_digest_cursor`, строгий `>`, docstring L10-20), рендерит per-channel блок raw-сводок ([`_render_channels_block`](../../tg_parser/services/digest_service.py) L631) и просит LLM собрать digest ([`prompts/digest.yaml`](../../prompts/digest.yaml)). Контент = **raw new-document summaries за окно времени**.
- **F5-C сделал темы живыми.** Успешный re-summarize: `commit_resummary` ([`topic_card_repo.py`](../../tg_parser/storage/sqlalchemy/topic_card_repo.py) L286) бампит `summary_version`, обновляет `summary`/`scope_in`/`scope_out`/`last_summarized_at`; snapshot *предыдущего* состояния уходит в `topic_card_versions` (`version_no = card.summary_version`, [`resummarization_service.py`](../../tg_parser/services/resummarization_service.py) L585-599; live `summary_version = N` на карточке). `topic.summary` — теперь first-class evolving synthesis ([ADR-0006](../adr/0006-karpathy-like-living-kb-principles.md) #1/#2/#5).
- **diff-API (#2) только что зашёл — это недостающий кирпич.** `diff_topic_summaries(left, right)` ([`domain/topic_history_diff.py`](../../tg_parser/domain/topic_history_diff.py) L114) уже считает «что изменилось» между двумя snapshot'ами темы (text-diff `summary` через stdlib `difflib` + set-diff `scope_in`/`scope_out`), читая archival-версии через `get_two_versions` ([`topic_card_version_repo.py`](../../tg_parser/storage/sqlalchemy/topic_card_version_repo.py) L102) **и** живую карточку (`current`-сторона, `snapshot_from_card` L74). **«Что нового по теме X» = один вызов `diff_topic_summaries`** ⇒ topic-digest — в основном композиция уже зашедших read-path'ов + F6 delivery.
- **Priority.** [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) L799 (#15 item #3, «требует тюнинга промпта digest») + F6-секция L1022 (Per-topic digest) / L1031 (F5-C: «использовать обновлённые topic summaries вместо raw doc summaries»). TTL (#1) и diff (#2) закрыты раньше; topic-digest (#3) — следующий composed slice.

**Разница одной строкой:** F6 today = *`channel_ids` × raw ProcessedDocument summaries × `processed_at`-окно*; topic-digest = *topic-scope × delta эволюционирующей `topic_card.summary` × `last_summarized_at`/version-окно*.

---

## 2. Существующий F6 — что переиспользуется (anchored, verified 2026-07-24)

**Delivery / lifecycle — reuse без изменений:**

| Кусок | Anchor | Reuse |
|---|---|---|
| `run_for_subscription` (generate → deliver → advance cursor only on success) | [`digest_service.py`](../../tg_parser/services/digest_service.py) L549 | as-is — cursor advance semantics идентичны |
| `deliver` / `_publish_to_target` (bot push, split >4096, MarkdownV2 escape, channel-permission soft-deactivate) | L443 / L471 | as-is (ADR-0008 targets) |
| `subscribe` (idempotent upsert на `(owner_id, name)`, workspace-validation) | L180 | as-is |
| scheduler job lifecycle (`register_digest_subscription`, `_digest_job_id`, `CronTrigger.from_crontab`) | [`background_scheduler.py`](../../tg_parser/services/background_scheduler.py) L492 / L487 / L130-140 | as-is |
| task entry (`run_scheduled_digests_task`: resolve sub → build service → run) | [`scheduler_service.py`](../../tg_parser/services/scheduler_service.py) L1093 | as-is — **Q3=cron reuse** (тот же путь, mode-branch внутри service) |
| MCP surface (`subscribe_digest`/`list_digests`/`unsubscribe_digest`) | [`mcp_server.py`](../../tg_parser/mcp_server.py) L3101/L3335/L3388 | **extend** `subscribe_digest` доп. args `mode`/`topic_ids` (Q1=both modes); `list_digests`/`unsubscribe_digest` reuse |
| repo CRUD (`create`/`update`/`list_active`/`find_by_owner_and_name`) | [`digest_subscription_repo.py`](../../tg_parser/storage/sqlalchemy/digest_subscription_repo.py) L27/L106/L206 (`_SELECT_COLUMNS` L14) | reuse + **+2 колонки** (`mode`,`topic_ids`) в `_SELECT_COLUMNS`/`create`/`update` — Q5=schema-add |

**Genuinely new work (2 куска):**

1. **Content selection** — «какие темы изменились с cursor». Паттерн-зеркало: [`list_resummarize_candidates`](../../tg_parser/storage/sqlalchemy/topic_card_repo.py) L247 (его скорость — от **partial-index `idx_topic_cards_resummarize_candidates WHERE new_items_since_last_summary > 0`**, а НЕ от `last_summarized_at`). Новый read-only `list_topics_changed_since(scope, cursor)` — key = **`topic_cards.last_summarized_at > :cursor`** (Q6=a, строгий `>`, reuse `last_digest_cursor`), scope = channel/workspace/`topic_ids` (Q1=both modes; channel-фильтр — non-sargable `sources_json LIKE '%"cid"%'`, идиома `list_by_channels` L201). ⚠️ **`last_summarized_at` НЕ проиндексирован** нигде + LIKE non-sargable ⇒ full/seq-scan. Приемлемо на текущем объёме тем, но **index НЕ заявляем** (в отличие от `list_resummarize_candidates`). Partial-index на `last_summarized_at` — возможный deferred/OUT при росте объёма (в этот slice не бюджетируем).
2. **Payload composition** — на каждую изменившуюся тему собрать «what's new» через **reuse `diff_topic_summaries` (prior → current)** (Q2=a, diff-of-summaries); `prior` = состояние-на-cursor из `list_by_topic` (Q7=B cumulative, §3.3/§4.2). **Ноль нового diff-кода И ноль нового repo-метода.**

---

## 3. Критическая семантика (design-defining)

1. **Строгий `>` на cursor.** F6 намеренно фильтрует `processed_at > cursor` (не `>=`), т.к. repo отдаёт `>=` ([`digest_service.py`](../../tg_parser/services/digest_service.py) docstring L10-20, filter L382-393). Topic-вариант повторяет строгий `>` на своём cursor-ключе — **`topic_cards.last_summarized_at > last_digest_cursor`** (Q6=a, reuse существующего поля), иначе последняя тема ре-включается каждый tick.
2. **`version_no` = snapshot предыдущего.** Archival-строки хранят v1..v(N−1); живой current (`summary_version = N`) — только на `topic_cards`, в таблице версий его **нет** ([`resummarization_service.py`](../../tg_parser/services/resummarization_service.py) L585-599 + commit-bump L665). diff-API уже решает это dual-source (`current` = живая карточка через `snapshot_from_card` L74). Topic-digest наследует эту семантику **бесплатно**: `current` всегда = живая карточка; `prior` = состояние-на-cursor, выбранное перечислением `list_by_topic` (см. §3.3, §4.2).
3. **TTL gaps (ADR-0018) — Q7=B (cumulative prior via `list_by_topic`).** `purge_stale` ([`topic_card_version_repo.py`](../../tg_parser/storage/sqlalchemy/topic_card_version_repo.py) L142) может удалить промежуточные версии (`version_no` gaps; genesis v1 + last-N pinned). `prior`-сторона («состояние, которое пользователь видел на прошлый digest») выбирается перечислением **существующего** `list_by_topic(topic_id, limit=keep_last_n)` ([`topic_card_version_repo.py`](../../tg_parser/storage/sqlalchemy/topic_card_version_repo.py) L72, newest-first, WITH `created_at`) → в Python берём новейшую версию с **`created_at ≤ last_digest_cursor`** (at-or-before, не ≥). Если ни одна не выжила (все выпилены TTL) → самая старая сохранившаяся версия, иначе genesis (v1). **никогда 500 by construction** — диффим то, что физически выжило (отсутствующие строки лишь сдвигают fallback, а не роняют lookup); timestamp→version SQL-метод **НЕ** нужен. NB: `prior` **не** выбирается через `get_two_versions` (point-lookup по `version_no`, он не умеет маппить cursor-timestamp в версию — это и был BLOCKER).
4. **Advance cursor only on success.** Reuse F6: пустой результат → advance (не реиграть окно); delivery raises → **не** advance ([`run_for_subscription`](../../tg_parser/services/digest_service.py) L549-615). Topic-вариант наследует.

---

## 4. Design — форма (все форки DECIDED; см. §9)

### 4.1 Content-selection read-path (Q6=a — DECIDED)
Новый read-only `TopicCardRepo.list_topics_changed_since(scope, cursor) -> list[TopicCard]` — зеркало [`list_resummarize_candidates`](../../tg_parser/storage/sqlalchemy/topic_card_repo.py) L247:
- **scope (Q1=both modes):** `mode='channel'` → все active-темы в `channel_ids`/`workspace_id` (reuse `list_by_channels` LIKE-паттерн [`topic_card_repo.py`](../../tg_parser/storage/sqlalchemy/topic_card_repo.py) L201); `mode='topic'` → explicit `topic_ids[]`.
- **cursor key (Q6=a):** `last_summarized_at > :cursor` — поле уже на карточке, **reuse существующего `last_digest_cursor`** (не добавляем новое поле). Строгий `>` (см. §3.1). ⚠️ `last_summarized_at` НЕ проиндексирован ⇒ seq-scan (index НЕ заявляем; см. §2). **Mode-change reset:** при смене `mode` существующей подписки cursor **сбрасывается в NULL** (§4.4 / §9 Q6).
- **NULL-safety (m1):** never-re-summarized / pre-F5-C темы имеют `last_summarized_at = NULL` ⇒ `NULL > :cursor` = false ⇒ они исключаются candidate-фильтром. Именно это (а **не** ADR-0018 double-floor) — реальный safety mechanism «тема никогда не приходит без версий». NB для implementer: docstring `TopicCardVersion` ([`domain/models.py`](../../tg_parser/domain/models.py) ~L436, «first version is never materialised») вводит в заблуждение — не доверять ему как источнику инварианта.
- **Delivery-time visibility filter (M4).** На каждом tick в topic-mode content-selection отбрасывать любую тему, чьи `card.sources` больше **не** пересекаются с allowed-channels владельца на момент tick (отзыв доступа не должен утекать evolving topic summaries). NB: существующий channel-mode F6 доступ на доставке **не** перепроверяет — это намеренное parity-улучшение для более чувствительного topic-summary контента. Visibility покрыта на **обоих** этапах: subscribe (`assert_topic_access` [`auth/ownership.py`](../../tg_parser/auth/ownership.py) L50) **и** delivery (source-intersection filter).
- write-path (`commit_resummary` [`topic_card_repo.py`](../../tg_parser/storage/sqlalchemy/topic_card_repo.py) L286) **не** трогаем.

### 4.2 Payload composition (Q2=a — DECIDED) — reuse diff-API
Для каждой изменившейся темы — **diff-of-summaries**:
- `prior` = состояние, которое пользователь видел на прошлый digest: `list_by_topic(topic_id, limit=keep_last_n)` ([`topic_card_version_repo.py`](../../tg_parser/storage/sqlalchemy/topic_card_version_repo.py) L72, newest-first WITH `created_at`) → в Python новейшая версия с `created_at ≤ last_digest_cursor`; `right` = живая карточка (`current`). Один вызов `diff_topic_summaries(snapshot_from_version(prior), snapshot_from_card(card))` ([`topic_history_diff.py`](../../tg_parser/domain/topic_history_diff.py) L114/L56/L74) — text-diff `summary` + set-diff `scope_in`/`scope_out`. **Ноль нового/ре-имплементированного diff-кода И ноль нового repo-метода** (`list_by_topic` уже существует). Это **cumulative** «что изменилось с прошлого digest» (state-at-cursor → current), **НЕ** last-delta v(N−1)→current: если тема ре-суммаризовалась k× с прошлого digest, все k дельт попадают в один diff (prior = состояние-на-cursor).
- **Q7=B fallback** на TTL-gaps: если ни одна версия не удовлетворяет `created_at ≤ cursor` (всё выпилено TTL) → самая старая сохранившаяся версия, иначе genesis→current, с пометкой «baseline shifted (retention)»; **никогда 500 by construction** — диффим то, что физически выжило (см. §3.3). NB: prior **не** выбирается через `get_two_versions` (point-lookup по `version_no` не маппит cursor-timestamp в версию); timestamp→version SQL-метод (`version_at_or_before`-подобный) **НЕ** нужен.

### 4.3 Render + prompt (Q4=a — DECIDED)
- Новый `_render_topic_block` (зеркало `_render_channels_block` [`digest_service.py`](../../tg_parser/services/digest_service.py) L631): на тему — title + summary-delta (diff-lines/added-removed scope) + provenance.
- Prompt: **новый `prompts/topic_digest.yaml`** (отдельный файл — тюнится без правки channel-digest prompt), reuse существующего `DigestFormat` enum (summary/bullets/detailed, [`domain/models.py`](../../tg_parser/domain/models.py) L755) для output-стиля; placeholders в стиле `{format,language,from_iso,to_iso,topics_block}` (зеркало `digest.yaml` L50-60); config-only (`reload_prompts`), no code coupling. Roadmap явно требует тюнинга (L799).

### 4.4 Subscription model (Q1+Q5=a — DECIDED, schema-add)
- **Schema-add (DECIDED):** `mode VARCHAR` (`'channel'|'topic'`, default `'channel'`) + `topic_ids TEXT[]` на `digest_subscriptions` через **новую Alembic-миграцию**. Меняет F6 subscription data-model ⇒ **малый ADR обязателен** (ADR-0019, §11). ⚠️ **m2:** `20260418_add_digest_subscriptions.py` (revision `f6a1b2c3d4e5`) — только **структурный precedent** (форма ADD COLUMN), **не** chaining-target. Миграции разбиты на ветки `ingestion/` и `processing/` ⇒ `alembic heads` возвращает **несколько** heads; новая ревизия чейнится от текущего **ingestion**-head (запустить `alembic heads`, взять ingestion-head), а НЕ от `f6a1b2c3d4e5`.
- `DigestSubscription` ([`domain/models.py`](../../tg_parser/domain/models.py) L763) + `_SELECT_COLUMNS`/`create`/`update` ([`digest_subscription_repo.py`](../../tg_parser/storage/sqlalchemy/digest_subscription_repo.py) L14/L27/L106) + port ([`storage/ports.py`](../../tg_parser/storage/ports.py) L1525) расширяются двумя полями. `mode='channel'` без `topic_ids` = сегодняшний raw-doc digest bit-for-bit (no regression). Result-DTO **тоже** расширяются (см. §4.6 — не только repo/model/port).
- **Cursor reset on mode-change (M3, Q6).** `subscribe` idempotent-upsert на `(owner_id, name)`, а `last_digest_cursor` — единый TIMESTAMPTZ с двумя семантиками (channel = `processed_at`; topic = `last_summarized_at`). При смене `mode` существующей подписки stale cursor несёт **неверную** семантику → неверное первое окно. ⇒ на mode-change `last_digest_cursor` **сбрасывается в NULL** (перезапуск first-run lookback для новой семантики). Явно в acceptance §7.

### 4.5 Scheduler (Q3=a — DECIDED, cron reuse)
- **Cron reuse:** тот же `run_scheduled_digests_task` ([`scheduler_service.py`](../../tg_parser/services/scheduler_service.py) L1093) на F6 cadence; topic vs channel — branch **внутри** `DigestService` по `sub.mode`. **Zero scheduler-plumbing change, нет риска дубль-доставки.**
- Event-on-resummarize (hook `run_resummarize_for_channel` [`scheduler_service.py`](../../tg_parser/services/scheduler_service.py) L1173) — **explicitly OUT / fast-follow** (§8): новый plumbing + риск дубль-доставки (нужен свой cursor/lock).

### 4.6 Surface (Q1=both modes — DECIDED)
- MCP: **extend `subscribe_digest`** ([`mcp_server.py`](../../tg_parser/mcp_server.py) L3101) доп. args `mode` (`'channel'|'topic'`) + `topic_ids: list[str] | None`; `list_digests` L3335 / `unsubscribe_digest` L3388 reuse. **m3:** чтобы `mode`/`topic_ids` появились в результатах `list_digests` и subscribe, нужно обновить **result-DTO тоже** (напр. `SubscribeDigestResult` + сериализация результата `subscribe_digest` возле [`mcp_server.py`](../../tg_parser/mcp_server.py) L3090-3097) — не только repo/model/port.
- CLI: зеркало в [`cli/digest_cmd.py`](../../tg_parser/cli/digest_cmd.py) (`@app.command` паттерн, `add` L24) — те же `--mode`/`--topics` опции.
- Bot: **OUT** (§8).

---

## 5. Blast-radius

| Surface | Touch? | Notes |
|---|---|---|
| `DigestSubscription` + `digest_subscriptions` schema | **Yes (Q1/Q5=schema-add)** | +2 колонки `mode VARCHAR` + `topic_ids TEXT[]` → **новая миграция** (precedent `20260418_add_digest_subscriptions.py`). Меняет F6 subscription data-model. |
| Subscription repo (port L1525 + SA L21) | **Yes** | `_SELECT_COLUMNS` L14 + `create` L27 + `update` L106 расширить двумя полями; port ABC L1525 sync. |
| `TopicCardRepo` | **Yes (read-only)** | новый `list_topics_changed_since` (зеркало `list_resummarize_candidates` L247). Write-path не трогаем. |
| `diff_topic_summaries` / `list_by_topic` | **Read reuse (no change)** | payload-builder + prior-selection (Q7=B: новейшая версия с `created_at ≤ cursor` из `list_by_topic` L72) as-is; **`get_two_versions` для topic-digest НЕ используется** (by-`version_no` point-lookup не маппит cursor). |
| `purge_stale` (TTL) | **No** | topic-digest — read-only consumer gaps; retention не расширяем (Q7=a′ fallback). |
| `DigestService` | **Yes** | новый content-selection + `_render_topic_block`; `mode`-branch; delivery/`run_for_subscription`/cursor-advance reuse. |
| Digest prompt | **Yes (config-only)** | новый `prompts/topic_digest.yaml` (Q4=a); `reload_prompts`. Channel `digest.yaml` не трогаем. |
| Scheduler | **No change (Q3=a cron reuse)** | тот же `run_scheduled_digests_task` L1093; mode-branch внутри service. Zero scheduler plumbing. |
| MCP / CLI | **Yes** | extend `subscribe_digest` (`mode`/`topic_ids`) + CLI зеркало. |
| Bot tools | **No (OUT)** | §8. |
| Delivery / ADR-0008 targets / bot-push | **No code change** | reuse. |
| Существующий raw-doc digest (`mode='channel'`) | **No regression** | параллельный режим, bit-for-bit (default `mode='channel'`). |
| Alembic | **Yes (Q5=schema-add)** | новая ревизия (+2 колонки, additive, nullable/default → безопасный upgrade). |
| **ADR** | **Yes (ADR-0019)** | малый F6 subscription-addendum — schema меняет контракт подписки (§11). Пишется в impl-сессии. |
| Settings | **Maybe** | возможные topic-digest caps (reuse `digest_max_docs_per_run` L1050 / `first_run_lookback_hours` L1056). |
| Prod data | **No mutation content-select; schema migration** | content-selection read-only, **но** deploy требует `db upgrade` + pre-deploy backup (with-migration, §10). |

**Concurrency:** read-only content-selection в отдельной read-транзакции; не пересекается с F5-C write-path advisory-lock ни с TTL-purge. Cron reuse (Q3=a) наследует F6 job-lifecycle — нет нового idempotency/cursor и **нет риска дубль-доставки** (event-on-resummarize, который его бы потребовал, вынесен в OUT/fast-follow §8).

---

## 6. Session steps (execution outline — все решения baked; детальный порядок — START_PROMPT §0)

1. **Migration + schema** — новая Alembic-ревизия: `mode VARCHAR` (default `'channel'`) + `topic_ids TEXT[]` на `digest_subscriptions` (precedent `20260418_add_digest_subscriptions.py`); `DigestSubscription` model + repo `_SELECT_COLUMNS`/`create`/`update` + port sync (Q1/Q5=a).
2. **Content-selection read-path** — `list_topics_changed_since(scope, cursor)` (зеркало `list_resummarize_candidates` L247); key = `last_summarized_at > :cursor` (Q6=a); unit-тест (changed vs unchanged; строгий `>`; channel/workspace/topic scope).
3. **Payload composition** — на изменившуюся тему `diff_topic_summaries(prior→current)` (Q2=a); `prior` = новейшая версия с `created_at ≤ cursor` из `list_by_topic` (Q7=B cumulative), fallback → oldest-surviving/genesis. Unit-тест payload + multi-bump cumulative + gap-fallback (никогда 500).
4. **Render + prompt** — `_render_topic_block` + новый `prompts/topic_digest.yaml` (Q4=a, reuse `DigestFormat`); `reload_prompts`-совместимо.
5. **Subscription surface** — extend `subscribe_digest` MCP (`mode`/`topic_ids`) + CLI зеркало (both modes, Q1).
6. **Scheduler** — cron reuse (Q3=a, zero plumbing); mode-branch внутри `DigestService`. Skip-if-empty + advance-on-success reuse.
7. **ADR** — написать **малый ADR-0019** (F6 subscription-addendum): schema-add `mode`/`topic_ids` меняет контракт подписки (§11).
8. **Docs** — FUTURE_FEATURES L799 → DONE/partial + F6 §L1031 note; skeleton → «landed» pointer.
9. **Quality gate** — `uv run ruff check .` / `ruff format --check .` / `TEST_POSTGRES=1 uv run pytest -q` (трогаем migration/repo/service/MCP/CLI). Runner-нота: [`tests/README.md`](../../tests/README.md) L76 предпочитает `.venv/bin/python -m pytest`; `uv run pytest` — принятый эквивалент.
10. **Deploy (with-migration)** — pre-deploy backup + `db upgrade` (см. §10). **Не** read-only.
11. **Commit/PR** — только по явному запросу пользователя.

---

## 7. Acceptance criteria (impl-сессия done when — concrete, финализуется в START_PROMPT §5)

- [ ] **Both modes (Q1):** подписка с `mode='topic'` + `topic_ids[]` выбирает явные темы; `mode='channel'` — все active-темы в scope (channel/workspace). Tick эмитит digest, контент которого — **delta эволюционирующей сводки темы** (Q2=a diff), **не** raw doc summaries.
- [ ] **Schema-add (Q5):** миграция добавляет `mode`+`topic_ids`; upgrade/downgrade идемпотентны; `mode='channel'` без `topic_ids` = сегодняшний F6 bit-for-bit.
- [ ] **Content-selection (Q6):** `list_topics_changed_since` отдаёт только темы с `last_summarized_at > last_digest_cursor` (строгий `>`, нет ре-включения); cursor advance **только** на успешной доставке/empty-skip.
- [ ] **Cumulative prior + TTL-gap robust (Q7=B):** `prior` = новейшая версия с `created_at ≤ last_digest_cursor` из `list_by_topic` (cumulative «с прошлого digest», покрывает multi-bump); all-purged → oldest-surviving/genesis→current с пометкой «baseline shifted (retention)», **никогда 500 by construction**. `get_two_versions`/timestamp→version SQL-метод НЕ используется.
- [ ] **Diff-reuse (Q2=a):** payload вызывает зашедший `diff_topic_summaries` (нет ре-имплементации diff-логики).
- [ ] **Prompt (Q4=a):** новый `prompts/topic_digest.yaml`, reuse `DigestFormat`; channel `digest.yaml` не тронут; `reload_prompts`-совместим.
- [ ] **Scheduler (Q3=a):** тот же `run_scheduled_digests_task` cron path; нет нового scheduler plumbing; нет дубль-доставки.
- [ ] Существующий raw-doc digest (`mode='channel'`) **не изменён** (bit-for-bit no regression).
- [ ] **Cursor reset on mode-change (M3):** смена `mode` существующей подписки сбрасывает `last_digest_cursor` в NULL (перезапуск first-run lookback новой семантики); без reset stale cursor неверной семантики → неверное первое окно.
- [ ] **Visibility на ОБОИХ этапах (M4):** subscribe — `assert_topic_access` (тема видна если user видит ≥1 из `card.sources`); delivery — topic-mode content-selection отбрасывает тему, чьи `card.sources` больше не пересекаются с allowed-channels владельца на момент tick (revoked access не утекает). Deliberate parity-улучшение vs channel-mode F6 (который на доставке не перепроверяет).
- [ ] **Нет новых deps** (`difflib` stdlib, ADR-0017); delivery/scheduler/subscription-lifecycle reused (минимум net-new кода).
- [ ] `uv run ruff check .` + `ruff format --check .` + `TEST_POSTGRES=1 uv run pytest -q` — green.
- [ ] **ADR-0019** (F6 subscription-addendum) написан и accepted; FUTURE_FEATURES / skeleton pointer обновлены.
- [ ] **Deploy (with-migration):** pre-deploy backup снят + `db upgrade` прогнан (§10) — **не** read-only.
- [ ] Commit/PR только по явному запросу пользователя.

---

## 8. Out of scope (жёстко — impl-сессия не расширяет без нового GO)

- **Bot tools** для topic-digest / F5-C (#5) — this slice = MCP/CLI + scheduler.
- **Event-on-resummarize trigger (Q3-b)** — explicitly OUT / fast-follow: только cron reuse (Q3=a) в этом slice; event-hook = отдельный slice (новый plumbing + свой idempotency/cursor против дубль-доставки).
- **Email / webhook delivery** — только bot-push (ADR-0008: chat/channel).
- **Per-topic / cross-topic dedup** — F5-B concern.
- **Schema rewrite of F6** — только **additive** +2 колонки (`mode`/`topic_ids`); full redesign / переработка существующих колонок OUT.
- **New LLM deps** — reuse LLM factory + `difflib` stdlib (ADR-0017).
- **Изменения raw-doc digest path** — `mode='channel'` bit-for-bit, no regression.
- **TTL / retention changes** (ADR-0018 / `purge_stale`) — read-only consumer gaps.
- **diff-API changes** — `diff_topic_summaries` / `list_by_topic` reuse as-is (no new diff surface, no new repo-метод).
- **#6 type-promotion, #7 topic dedup, #8 bundle-item GC, #9 HTTP endpoints** — separate #15 items.
- **Wave E** graph retrieval, **F11 HTTP CRUD**, **webhook 2A (ADR-0008)**.
- `docs/methodology/**`, `pyproject.toml`, `requirements.txt`.

---

## 9. Decisions

### Pre-baked (зафиксировано до owner-раунда — следствия ADR/priority/reuse)
- **P1. Priority:** topic-digest (#3) — следующий #15 item после TTL (#1) и diff (#2). ✅
- **P2. Reuse F6 delivery surface:** subscription lifecycle, scheduler job-registration, bot-push (ADR-0008 targets), cursor-advance-only-on-success, idempotent `subscribe` — переиспользуются **без изменений**; net-new = content-selection + payload + prompt. ✅
- **P3. Reuse shipped diff-API как payload-builder:** `diff_topic_summaries` / `list_by_topic` (prior-selection, Q7=B) / dual-source `current`=live card — no re-implementation, no new diff surface, no new repo-метод (когда Q2=diff). ✅
- **P4. No new deps / read-only content-selection:** `difflib` stdlib (ADR-0017); content-selection — SQL по `last_summarized_at` без LLM на тему (ADR-0006 #3); zero write-path/retention change. ✅
- **P5. TTL-gap robustness — обязательна:** purged версия → fallback, никогда 500 (ADR-0018). *Требование* baked; точная форма fallback owner-visible (Q7). ✅
- **P6. No regression существующего F6:** raw-doc `mode='channel'` bit-for-bit. ✅

### Owner-resolved (DECIDED 2026-07-24 — baked, вошли в START_PROMPT)
- **Q1. Subscription granularity = BOTH modes.** Подписка несёт `mode` (`'channel'|'topic'`); channel/workspace "all active topics" mode **И** explicit `topic_ids[]` (для topic-mode). ✅
- **Q2. "What's new" semantics = (a) diff-of-summaries.** Reuse зашедшего `diff_topic_summaries` ([`topic_history_diff.py`](../../tg_parser/domain/topic_history_diff.py) L114) — text-diff `summary` + set-diff `scope_in`/`scope_out`. Нет ре-имплементации diff-логики. ✅
- **Q3. Trigger = (a) reuse F6 cron cadence.** Тот же `run_scheduled_digests_task` ([`scheduler_service.py`](../../tg_parser/services/scheduler_service.py) L1093); zero scheduler-plumbing change; нет дубль-доставки. Event-on-resummarize — explicitly OUT/fast-follow (§8). ✅
- **Q4. Delivery format = (a) new `prompts/topic_digest.yaml`.** Отдельный prompt-файл (тюнится без правки channel-digest prompt), reuse `DigestFormat` enum (summary/bullets/detailed, [`domain/models.py`](../../tg_parser/domain/models.py) L755) для output-стиля. ✅
- **Q5. Schema shape = (a) add columns to `digest_subscriptions`.** `mode VARCHAR` + `topic_ids TEXT[]` через новую Alembic-миграцию (precedent [`20260418_add_digest_subscriptions.py`](../../migrations/versions/ingestion/20260418_add_digest_subscriptions.py)). Меняет F6 subscription data-model ⇒ **малый ADR обязателен** (ADR-0019, §11). ✅
- **Q6. Cursor = (a) `topic_cards.last_summarized_at > cursor` (строгий `>`), reuse `last_digest_cursor`.** Advance-only-on-success (mirrors channel digest). **Новое** cursor-поле НЕ добавляем. **Mode-change reset (M3):** т.к. `subscribe` idempotent-upsert на `(owner_id, name)` и `last_digest_cursor` — единый TIMESTAMPTZ с двумя семантиками (channel=`processed_at`, topic=`last_summarized_at`), при смене `mode` существующей подписки cursor **сбрасывается в NULL** (перезапуск first-run lookback новой семантики) — иначе stale cursor неверной семантики → неверное первое окно. ✅
- **Q7. Prior-side + TTL-gap robustness = (B) cumulative prior via `list_by_topic`.** `prior` = состояние-на-cursor: `list_by_topic(topic_id, limit=keep_last_n)` ([`topic_card_version_repo.py`](../../tg_parser/storage/sqlalchemy/topic_card_version_repo.py) L72, newest-first WITH `created_at`) → новейшая версия с `created_at ≤ last_digest_cursor` (at-or-before); если ни одна не выжила → самая старая сохранившаяся, иначе genesis (v1). `current` всегда = живая карточка. Это **TRUE cumulative** «что изменилось с прошлого digest» — покрывает multi-bump-between-ticks. **никогда 500 by construction** — диффим то, что физически выжило (отсутствующие строки лишь сдвигают fallback). **Ноль нового repo-метода** (`list_by_topic` уже существует). NB: `get_two_versions` (by-`version_no` point-lookup) для prior-выбора **не** используется — он не маппит cursor-timestamp в версию (это был BLOCKER); `version_at_or_before`-подобный SQL-метод **НЕ** нужен. Cost: ≤ keep_last_n (≤50) version-строк на подписанную тему за tick — незначительно на digest-cadence. ✅

---

## 10. Quality / ops gate commands

```bash
# repo quality (local, всегда)
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
# PR-standard (трогаем repo/service/MCP/CLI paths → нужен Postgres):
TEST_POSTGRES=1 uv run pytest -q
# Runner note: tests/README.md L76 предпочитает `.venv/bin/python -m pytest`;
# `uv run pytest` — принятый эквивалент (те же режимы). Один runner в обоих доках.

# Deploy (with-migration — В ОТЛИЧИЕ от read-only diff-API #2):
# 1) pre-deploy backup БД (schema-change);
# 2) alembic upgrade head (новая ревизия: +2 колонки mode/topic_ids, additive/nullable).
```
_**With-migration deploy:** content-selection сам read-only, **но** фича добавляет 2 колонки в `digest_subscriptions` ⇒ нужны **pre-deploy backup + `db upgrade`**. Это **НЕ** read-only (в отличие от diff-API #2). Доставка = существующий F6 bot-push._

---

## 11. Нужен ли новый ADR? — **ДА, ADR-0019 (F6 subscription-addendum)**

**Q5=schema-add ⇒ ADR ОБЯЗАТЕЛЕН.** Добавление `mode`/`topic_ids` на `digest_subscriptions` делает их **нормативной частью** F6 digest data-model — меняется, что есть «подписка» (channel-scoped → channel|topic-scoped). Это decision класса ADR-per-decision (как 0008 subscription-target-model, 0009 idempotency, 0017 dep-policy, 0018 retention).

- **Номер:** следующий свободный = **ADR-0019** (последний в [`docs/adr/`](../adr/) — 0018-topic-card-versions-retention; проверено 2026-07-24).
- **Scope ADR-0019:** F6 subscription addendum — `mode` discriminator + `topic_ids[]`; topic-mode reuse `last_digest_cursor` (Q6=a, с reset-to-NULL при смене mode); отношение к ADR-0008 (delivery targets неизменны), ADR-0006 (#1/#5 living-KB), ADR-0018 (Q7=B cumulative prior via `list_by_topic`).
- **Когда пишется:** **в impl-сессии** (шаг §6.7 / START_PROMPT step), не в этой planning-сессии.

_(Контраст: diff-API #2 остался ADR-free — он лишь **читал** существующие колонки. Topic-digest **добавляет** колонки ⇒ ADR нужен.)_

---

## 12. Self-review fixes applied (plan)

**Finalization pass (2026-07-24) — owner разрешил Q1-Q7; decisions baked, START_PROMPT написан.** Критический pass (internal consistency skeleton↔plan↔START_PROMPT / anchor re-verify / testable acceptance / explicit OUT / TTL-gap robustness / reuse of shipped diff-API / with-migration consequence):

1. **Q1-Q7 перенесены OPEN → DECIDED (§9)** — Q1=both modes, Q2=a diff, Q3=a cron reuse, Q4=a new `topic_digest.yaml`, Q5=a schema-add, Q6=a `last_summarized_at`/reuse cursor (+reset-to-NULL при смене mode, M3), Q7=B cumulative prior via `list_by_topic` (state-at-cursor → current). Header, §2, §3, §4, §5, §6, §7, §8, §10, §11 приведены в соответствие; ни одной секции, всё ещё считающей форк открытым.
2. **With-migration consequence зафиксировано (§10, §5, header, §11)** — в отличие от read-only diff-API #2, Q5=schema-add ⇒ **pre-deploy backup + `db upgrade`** + **ADR-0019**. Явно противопоставлено diff-API везде.
3. **Anchor re-verify пофайловым чтением (2026-07-24)** — `diff_topic_summaries` L114 / `snapshot_from_version` L56 / `snapshot_from_card` L74; `list_resummarize_candidates` L247 (`last_summarized_at` L275) / `list_by_channels` L201 / `commit_resummary` L286; `digest_service` `generate` L351 / `run_for_subscription` L549 / `_render_channels_block` L631 / `subscribe` L180 / docstring L10-20 / filter L382-393; `DigestSubscription` L763 / `DigestFormat` L755 / `TopicCard` L190 (`last_summarized_at` L226, `summary_version` L230); `digest_subscription_repo` `_SELECT_COLUMNS` L14 / `create` L27 / `update` L106; port `DigestSubscriptionRepo` L1525; MCP `subscribe_digest` L3101 / `list_digests` L3335 / `unsubscribe_digest` L3388 / `get_topic_details` L1408; scheduler `run_scheduled_digests_task` L1093 / `run_resummarize_for_channel` L1173; `register_digest_subscription` L492 / `_digest_job_id` L487; `get_two_versions` L102 / `purge_stale` L142; `assert_topic_access` L50; migration precedent `20260418_add_digest_subscriptions.py`; `prompts/digest.yaml` placeholders L50-60; CLI `digest_cmd.py` `add` L24. Ни одного invented symbol; line-numbers актуальны.
4. **ADR-0019 верифицирован как next-free** — `ls docs/adr/` → последний 0018; 0019 свободен (§11).
5. **Testable acceptance §7 сделан concrete** — каждый пункт привязан к Q-решению (both-modes, schema-add idempotent, changed-since-cursor строгий `>`, gap-fallback-never-500, diff-reuse-no-reimpl, new-prompt-no-channel-regression, cron-no-dup, no-deps) + ADR-0019 + backup/upgrade gate.
6. **Explicit OUT §8 согласован со skeleton §9 + добавлен event-on-resummarize (Q3-b)** — Bot(#5)/event-hook/email-webhook/dedup/schema-rewrite(non-additive)/new-deps/raw-doc-regression/TTL-diff-changes/#6-#9.
7. **Cron reuse (Q3=a) устраняет дубль-доставку** — §4.5/§5 concurrency: нет нового idempotency/cursor; event-путь (который бы его требовал) вынесен OUT.
8. **START_PROMPT написан** — [`START_PROMPT_SESSION_F5C_TOPIC_DIGEST_2026-07-24.md`](START_PROMPT_SESSION_F5C_TOPIC_DIGEST_2026-07-24.md), в стиле diff-API START_PROMPT; §13 links обновлён.

---

## 13. Links

- Companion skeleton: [`SKELETON_F5C_TOPIC_DIGEST_2026-07-24.md`](SKELETON_F5C_TOPIC_DIGEST_2026-07-24.md)
- Implementation START_PROMPT (decisions baked): [`START_PROMPT_SESSION_F5C_TOPIC_DIGEST_2026-07-24.md`](START_PROMPT_SESSION_F5C_TOPIC_DIGEST_2026-07-24.md)
- Issue [#15](https://github.com/AlexEfimov/TG_parser/issues/15) item #3; [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) L799 / F6 §L884-1033 (L1022 Per-topic, L1031 F5-C reuse)
- Diff-API (#2, building block): [`PLAN_SESSION_F5C_DIFF_API_2026-07-23.md`](PLAN_SESSION_F5C_DIFF_API_2026-07-23.md), [`SKELETON_F5C_DIFF_API_TOPIC_HISTORY_2026-07-23.md`](SKELETON_F5C_DIFF_API_TOPIC_HISTORY_2026-07-23.md); helper [`domain/topic_history_diff.py`](../../tg_parser/domain/topic_history_diff.py) L114
- TTL/retention (#1, gaps): [ADR-0018](../adr/0018-topic-card-versions-retention.md), [`PLAN_SESSION_F5C_TTL_RETENTION_2026-07-22.md`](PLAN_SESSION_F5C_TTL_RETENTION_2026-07-22.md)
- F6 (shipped): [`F6_SCHEDULED_DIGESTS_PLAN.md`](../plans/F6_SCHEDULED_DIGESTS_PLAN.md); service [`digest_service.py`](../../tg_parser/services/digest_service.py) L148/L351/L549/L631; repo [`digest_subscription_repo.py`](../../tg_parser/storage/sqlalchemy/digest_subscription_repo.py) L21; MCP [`mcp_server.py`](../../tg_parser/mcp_server.py) L3101; scheduler [`scheduler_service.py`](../../tg_parser/services/scheduler_service.py) L1093 / [`background_scheduler.py`](../../tg_parser/services/background_scheduler.py) L492; prompt [`prompts/digest.yaml`](../../prompts/digest.yaml)
- Topic read-path: [`topic_card_repo.py`](../../tg_parser/storage/sqlalchemy/topic_card_repo.py) `list_resummarize_candidates` L247, `get_by_id` L142, `list_by_channels` L201; models [`domain/models.py`](../../tg_parser/domain/models.py) `TopicCard` L190 (`last_summarized_at` L226, `summary_version` L230), `TopicCardVersion` L431, `DigestSubscription` L763, `DigestFormat` L755
- Access: [`auth/ownership.py`](../../tg_parser/auth/ownership.py) `assert_topic_access` L50; visibility precedent `get_topic_details` [`mcp_server.py`](../../tg_parser/mcp_server.py) L1408
- ADR [0006](../adr/0006-karpathy-like-living-kb-principles.md), [0008](../adr/0008-subscription-target-model.md), [0017](../adr/0017-dependency-management-policy.md), [0018](../adr/0018-topic-card-versions-retention.md)
