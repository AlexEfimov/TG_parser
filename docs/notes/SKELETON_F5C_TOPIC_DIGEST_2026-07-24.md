# SKELETON — F5-C #15 item #3: F6 topic-level digest (digest на `topic.summary`)

> **SKELETON / docs-only / decisions-resolved (still skeleton).**
> Contract sketch for GitHub issue [#15](https://github.com/AlexEfimov/TG_parser/issues/15) item **#3 "F6 digest на topic.summary"** ([`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) L799; F6 integration note L1031).
> **Update 2026-07-24:** owner **разрешил все 7 форков Q1-Q7** — §8 теперь фиксирует DECIDED-набор (consistent с plan §9). START_PROMPT написан: [`START_PROMPT_SESSION_F5C_TOPIC_DIGEST_2026-07-24.md`](START_PROMPT_SESSION_F5C_TOPIC_DIGEST_2026-07-24.md). Детали реализации — в plan + START_PROMPT; этот файл остаётся высокоуровневым skeleton/contract-sketch.
> **Ключевое следствие:** Q5=schema-add ⇒ фича — **with-migration deploy** (backup + `db upgrade`) + **малый ADR-0019** (F6 subscription-addendum). **НЕ** read-only (в отличие от diff-API #2). No feature code / migration / prod SQL **in this planning session** (impl — отдельная сессия).

**Дата:** 2026-07-24
**Branch:** `docs/f5c-topic-digest-planning` (docs-only planning; commit/PR/START_PROMPT — **только** по явному запросу пользователя, [`AGENTS.md`](../../AGENTS.md)).
**Anchors:** F6 shipped surface (subscription + scheduler + bot-push); F5-C evolving-summary read-path; just-shipped diff-API (#2) as the natural payload builder; [ADR-0006](../adr/0006-karpathy-like-living-kb-principles.md) (Living-KB), [ADR-0008](../adr/0008-subscription-target-model.md) (delivery targets), [ADR-0017](../adr/0017-dependency-management-policy.md) (deps), [ADR-0018](../adr/0018-topic-card-versions-retention.md) (retention/gaps).

---

## 1. Goal (one-liner)

A scheduled (or on-demand) digest whose content is the **evolving topic summary** — *"what changed / what's new about topic X"* — instead of raw per-document summaries, delivered over the **existing F6 subscription + scheduler + bot-push path**. The natural payload of a topic-digest entry is exactly the just-shipped diff-API output (`diff_topic_summaries`, item #2): the delta of a topic's `summary` / `scope_in` / `scope_out` between the last digest and now.

---

## 2. Context / why-now

- **F6 today is document-scoped.** A `DigestSubscription` carries `channel_ids[]` and a `last_digest_cursor` (a `processed_at` timestamp). Each tick, [`DigestService.generate`](../../tg_parser/services/digest_service.py) L351 fetches new `ProcessedDocument`-s (`processed_at > last_digest_cursor`), renders a per-channel block of raw doc summaries ([`_render_channels_block`](../../tg_parser/services/digest_service.py) L631), and asks the LLM for a digest ([`prompts/digest.yaml`](../../prompts/digest.yaml)). Content = **raw new-document summaries over a time window**.
- **F5-C made topics "living".** Each successful re-summarize bumps `topic_cards.summary_version`, refreshes `summary` / `scope_in` / `scope_out` / `last_summarized_at` ([`commit_resummary`](../../tg_parser/storage/sqlalchemy/topic_card_repo.py) L286), and appends the *previous* snapshot to `topic_card_versions` ([`resummarization_service.py`](../../tg_parser/services/resummarization_service.py) L585-599, `version_no = card.summary_version`). A topic's summary is now a **first-class evolving synthesis** — the Living-KB payoff ([ADR-0006](../adr/0006-karpathy-like-living-kb-principles.md) #1/#2/#5).
- **The diff-API (#2) just shipped and is the missing building block.** `diff_topic_summaries(left, right)` ([`domain/topic_history_diff.py`](../../tg_parser/domain/topic_history_diff.py) L114) already computes "what changed" between two topic-summary snapshots (text-diff on `summary` + set-diff on scopes), reading archival versions via `get_two_versions` ([`topic_card_version_repo.py`](../../tg_parser/storage/sqlalchemy/topic_card_version_repo.py) L102) **and** the live card (`current` side). **"What's new about topic X" is exactly one `diff_topic_summaries` call** — so a topic-digest is largely composition of already-shipped read-paths + the F6 delivery surface.
- **Roadmap slot.** [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) L799 lists this as #15 item #3 ("F6 digest на topic-level summary … требует тюнинга промпта digest"); the F6 section flags it under both "Дополнительные возможности → Per-topic digest" (L1022) and "Связь с другими функциями → F5-C" (L1031: *"использовать обновлённые topic summaries вместо raw doc summaries"*). TTL (#6/#1) and diff-API (#2) landed first; topic-digest (#3) is the next composed slice.

**Difference in one line:** today's F6 = *`channel_ids` × raw ProcessedDocument summaries × `processed_at` window*; topic-digest = *topic-scoped × evolving `topic_card.summary` delta × `last_summarized_at` / version window*.

---

## 3. Anchors (verified — read & confirmed 2026-07-24)

| Якорь | Файл | Строка | Роль в topic-digest slice |
|---|---|---|---|
| F6 backlog line (#3) | [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) | **L799** | описание фичи; обновить → DONE/partial в impl |
| F6 section (schema/service/plan) | [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) | **L884-1033** (schema L936-953, DigestService API L957-979, план L1000-1010) | нормативный контекст существующего F6 |
| F6 ↔ F5-C integration note | [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) | **L1022** (Per-topic digest), **L1031** (F5-C reuse) | прямое обоснование фичи |
| Living-KB principles | [ADR-0006](../adr/0006-karpathy-like-living-kb-principles.md) | #1 L52 (digests/subscriptions = persistent), #2 L62, #5 L102, #7 L127 | checklist §7 |
| **DigestService** (compose+deliver) | [`services/digest_service.py`](../../tg_parser/services/digest_service.py) | class **L148**; `generate` **L351**; `run_for_subscription` **L549**; `_render_channels_block` **L631**; `_call_llm` **L668**; `subscribe` **L180** | reuse-хребет: заменяется/дополняется content-selection + rendering |
| Digest cursor invariant (strict `>`) | [`services/digest_service.py`](../../tg_parser/services/digest_service.py) | **L10-20** (docstring), `last_digest_cursor` filter L382-393 | cursor-семантика для topic-варианта |
| DigestSubscription model | [`domain/models.py`](../../tg_parser/domain/models.py) | class **L763** (`channel_ids` L788, `workspace_id` L789, `format` L803, `last_digest_cursor` L810) | точка расширения subscription-модели |
| DigestFormat enum | [`domain/models.py`](../../tg_parser/domain/models.py) | **L755** (`summary`/`bullets`/`detailed`) | reuse или новый topic-format |
| Subscription repo (SA) | [`storage/sqlalchemy/digest_subscription_repo.py`](../../tg_parser/storage/sqlalchemy/digest_subscription_repo.py) | class **L21** (`_SELECT_COLUMNS` L14, `create` L27, `update` L106, `list_active` L206) | добавить колонку/режим — если пойдём schema-путём |
| Subscription repo port | [`storage/ports.py`](../../tg_parser/storage/ports.py) | `DigestSubscriptionRepo` **L1525** | ABC при новом методе/колонке |
| Migration (F6 schema) | [`migrations/versions/ingestion/20260418_add_digest_subscriptions.py`](../../migrations/versions/ingestion/20260418_add_digest_subscriptions.py) | — | precedent для (возможной) миграции колонки |
| Digest prompt YAML | [`prompts/digest.yaml`](../../prompts/digest.yaml) | placeholders `{format,language,from_iso,to_iso,channels_block}` L50-60 | prompt-tuning для topic-level синтеза |
| MCP F6 tools | [`mcp_server.py`](../../tg_parser/mcp_server.py) | `subscribe_digest` **L3101**, `list_digests` **L3335**, `unsubscribe_digest` **L3388** | surface к расширению |
| Scheduler task entry | [`services/scheduler_service.py`](../../tg_parser/services/scheduler_service.py) | `run_scheduled_digests_task` **L1093**; resummarize hook `run_resummarize_for_channel` **L1173** (invoked in tick L656) | Q3=a **cron reuse** (this entry); event-on-resummarize hook = OUT/fast-follow |
| Scheduler cron wiring | [`services/background_scheduler.py`](../../tg_parser/services/background_scheduler.py) | `register_digest_subscription` **L492**, `_digest_job_id` **L487**, `CronTrigger.from_crontab` **L130-140** | job lifecycle reuse |
| **diff helper (payload)** | [`domain/topic_history_diff.py`](../../tg_parser/domain/topic_history_diff.py) | `diff_topic_summaries` **L114**, `snapshot_from_version` **L56**, `snapshot_from_card` **L74**, `TopicSummarySnapshot` **L38**, `CURRENT_LABEL` L35 | «what changed about X» = один вызов; reuse as-is |
| Versions read-path | [`storage/sqlalchemy/topic_card_version_repo.py`](../../tg_parser/storage/sqlalchemy/topic_card_version_repo.py) | `get_two_versions` **L102**, `list_by_topic` **L72**, `count` L206, `purge_stale` **L142** (TTL — не трогать) | archival side для diff-payload; gaps приходят из purge_stale |
| Topic read-path | [`storage/sqlalchemy/topic_card_repo.py`](../../tg_parser/storage/sqlalchemy/topic_card_repo.py) | `get_by_id` **L142**, `list_by_channels` **L201**, `list_resummarize_candidates` **L247** (`last_summarized_at` branch L275) | «какие темы изменились» — паттерн выборки по `last_summarized_at` |
| TopicCard model | [`domain/models.py`](../../tg_parser/domain/models.py) | class **L190** (`summary` L204, `scope_in/out` L205-206, `sources` L213, `last_summarized_at` **L226**, `summary_version` **L230**) | live-side snapshot + content-selection key |
| TopicCardVersion model | [`domain/models.py`](../../tg_parser/domain/models.py) | class **L431** (`created_at` L456) | archival snapshot + alt content-selection key |
| Topic visibility | [`auth/ownership.py`](../../tg_parser/auth/ownership.py) | `assert_topic_access` **L50**, `assert_channel_access` **L39**, `PermissionDenied` **L18** | access для topic-scoped subscription |
| get_topic_details (visibility precedent) | [`mcp_server.py`](../../tg_parser/mcp_server.py) | **L1408** (inline check L1440-1442) | тот же mental model видимости топика |
| Settings knobs (F6 + F5-C) | [`config/settings.py`](../../tg_parser/config/settings.py) | `digest_max_docs_per_run` L1050, `digest_first_run_lookback_hours` L1056, `resummarize_trigger_n` L1098, `resummarize_version_retention_days` L1180 | reuse cadence/caps; TTL-gap interaction |

---

## 4. Как это ложится на существующий F6 (reuse map)

| F6-компонент (сегодня) | Topic-digest (что меняется) |
|---|---|
| `DigestSubscription.channel_ids[]` | **+ `mode` (`'channel'|'topic'`) + `topic_ids[]`** — channel/workspace "all active topics" mode **И** explicit topics — **DECIDED Q1=both modes** (schema-add Q5) |
| `last_digest_cursor` = `processed_at` окно | **cursor = `topic_cards.last_summarized_at > last_digest_cursor`** (reuse существующего поля, строгий `>`) — **DECIDED Q6=a** |
| content = new `ProcessedDocument` summaries | content = **evolving topic-summary delta** — reuse `diff_topic_summaries` (diff-of-summaries) — **DECIDED Q2=a** |
| `_render_channels_block` → `prompts/digest.yaml` | **новый `_render_topic_block` + новый `prompts/topic_digest.yaml`** (reuse `DigestFormat` enum) — **DECIDED Q4=a** |
| cron via `run_scheduled_digests_task` | **reuse F6 cron cadence** (mode-branch внутри service); event-on-resummarize — OUT/fast-follow — **DECIDED Q3=a** |
| delivery: `run_for_subscription` → bot push (ADR-0008 targets) | **reuse as-is** (bot push, split, MarkdownV2 escape, channel-permission handling) — **BAKED (plan §9 P2)** |
| idempotent `subscribe` on `(owner_id, name)` | **reuse as-is** (idempotency + workspace validation) — **BAKED (plan §9 P2)** |

**Key insight:** delivery, subscription lifecycle, scheduler job-registration, cursor-advance-only-on-success — all reusable **unchanged**. The genuinely new work is (a) **content selection** ("which topics changed since cursor", Q6=a), (b) **payload composition** (diff-of-summaries reuse, Q2=a) + new prompt (Q4=a), and (c) the **schema-add** (`mode`/`topic_ids`, Q1/Q5=a) which makes this a **with-migration** deploy (+ ADR-0019). Everything else is F6 plumbing already in prod.

---

## 5. Scope (sketch — детально в plan §4/§6 + START_PROMPT §0/§3)

- **Subscription model (Q1/Q5=a — DECIDED).** `mode` discriminator on `digest_subscriptions` (`'channel'` | `'topic'`, default `'channel'`) **+** an explicit `topic_ids TEXT[]` column, via a **new Alembic migration**. Both modes supported. This changes the F6 subscription data-model ⇒ **ADR-0019** required (§11). ⚠️ **m2:** [`20260418_add_digest_subscriptions.py`](../../migrations/versions/ingestion/20260418_add_digest_subscriptions.py) (revision `f6a1b2c3d4e5`) is only a **structure precedent** (ADD COLUMN shape), **not** the chaining target — migrations are split into `ingestion/` and `processing/` branches so `alembic heads` returns multiple heads; chain the new revision from the current **ingestion** head (run `alembic heads`), not from `f6a1b2c3d4e5`.
- **Content selection (Q6=a — DECIDED).** "Which topics changed since `last_digest_cursor`" — new `list_topics_changed_since(scope, cursor)` read-path, mirroring the `list_resummarize_candidates` pattern ([`topic_card_repo.py`](../../tg_parser/storage/sqlalchemy/topic_card_repo.py) L247), keyed on **`topic_cards.last_summarized_at > :cursor`** (strict `>`, reusing the existing `last_digest_cursor` field — no new cursor column). ⚠️ `last_summarized_at` is **unindexed** + channel-scope uses a non-sargable `sources_json LIKE` ⇒ seq-scan (do **not** claim index support — see §6 #3). On a **mode-change** of an existing subscription, reset `last_digest_cursor` to NULL (M3, §8 Q6).
- **Payload composition (Q2=a — DECIDED).** Per changed topic, build a "what's new" entry by **reusing `diff_topic_summaries`** (prior → current) — no re-implemented diff logic. **Q7=B (cumulative prior):** `prior` = the summary state the user last saw at `last_digest_cursor` — picked from the existing `list_by_topic(topic_id, limit=keep_last_n)` enumeration ([`topic_card_version_repo.py`](../../tg_parser/storage/sqlalchemy/topic_card_version_repo.py) L72, newest-first WITH `created_at`) as the newest version with **`created_at ≤ cursor`**; all-purged → oldest-surviving/genesis→current ("baseline shifted (retention)"); `current` always = live card. This is **cumulative** change-since-last-digest (covers multi-bump-between-ticks), **never 500 by construction** (we diff whatever physically survived), and needs **no new repo method**. `get_two_versions` (by-`version_no` point-lookup) is **not** used for prior-selection.
- **Prompt tuning (Q4=a — DECIDED).** A **new `prompts/topic_digest.yaml`** (separate file so it tunes independently of the channel-digest prompt), reusing the `DigestFormat` enum (summary/bullets/detailed) for output style — roadmap flags "требует тюнинга промпта" (L799). Prompt is config-only (`reload_prompts`), no code coupling.
- **Surface (Q1=both — DECIDED).** MCP: **extend `subscribe_digest`** with `mode`/`topic_ids` args ([`mcp_server.py`](../../tg_parser/mcp_server.py) L3101); `list_digests`/`unsubscribe_digest` reuse. CLI mirror ([`cli/digest_cmd.py`](../../tg_parser/cli/digest_cmd.py)). Bot (out — see §9). **m3:** surfacing `mode`/`topic_ids` in `list_digests` + subscribe results also requires updating the **result-DTOs** (e.g. `SubscribeDigestResult` + `subscribe_digest` result serialization near [`mcp_server.py`](../../tg_parser/mcp_server.py) L3090-3097), not just repo/model/port.
- **Scheduler integration (Q3=a — DECIDED).** **Reuse `run_scheduled_digests_task` cron path** ([`scheduler_service.py`](../../tg_parser/services/scheduler_service.py) L1093); mode-branch inside `DigestService`. Event-on-resummarize (hook L1173) is OUT/fast-follow (§9).

---

## 6. Karpathy checklist impact (ADR-0006)

| Принцип | Impact |
|---|---|
| **#1 Persistent entities** | Subscriptions/digests уже first-class ([ADR-0006](../adr/0006-karpathy-like-living-kb-principles.md) #1 L52). Topic-digest **не** вводит новую сущность — расширяет `digest_subscriptions` двумя колонками (`mode`/`topic_ids`, Q1/Q5=a), не новую таблицу; но т.к. меняет subscription-контракт ⇒ **ADR-0019 required** (§11). |
| **#2 Provenance/evidence** | Payload = topic-summary delta с provenance обеих сторон (`diff_topic_summaries` уже echoes `version_no`/`created_at`/`llm_*`). Digest трассируется до `topic_card` / `topic_card_versions`. |
| **#3 Cheap retrieval** | Content-selection — SQL по `last_summarized_at` (индексируемо, как `list_resummarize_candidates`), **без** LLM на тему. Один LLM-вызов на digest (как F6 сегодня). ✅ |
| **#4 Idempotency** | Cursor-advance-only-on-success reuse из F6 (`run_for_subscription`). Topic-cursor должен быть строгим `>` (та же ловушка, что digest §L10-20). |
| **#5 Living loop** | Естественно встраивается: тема ре-суммаризуется в tick → на следующем **cron** попадает в topic-digest (Q3=a cron reuse; event-on-resummarize — OUT/fast-follow). |
| **#6 Observability** | Reuse digest-метрик + возможный `tg_topic_digest_*` counter; outcome-классы (delivered/skipped-empty/delivery_failed) уже есть в `run_scheduled_digests_task`. |
| **#7 Graceful degradation** | Reuse F6: bot-blocked → soft-deactivate; TTL-purged версия (Q7=a′) → digest **никогда** не 500 — fallback nearest-available ≥ cursor, иначе genesis→current, «baseline shifted (retention)» (ADR-0018 gaps). |

---

## 7. Blast-radius (sketch — что тронуто vs нет)

| Surface | Touch? | Notes |
|---|---|---|
| `DigestSubscription` model + `digest_subscriptions` schema | **Yes (Q1/Q5=a)** | +2 колонки `mode VARCHAR` + `topic_ids TEXT[]` → **новая миграция**. Меняет F6 subscription data-model ⇒ ADR-0019. |
| Subscription repo (port + SA) | **Yes** | `_SELECT_COLUMNS` L14 + `create` L27 + `update` L106 + port L1525 расширить двумя полями. |
| Topic read-path (`TopicCardRepo`) | **Yes (small, read-only)** | новый `list_topics_changed_since(scope, cursor)` (зеркало `list_resummarize_candidates` L247). Write-path не трогаем. |
| diff helper `diff_topic_summaries` | **Read reuse (no change)** | payload-builder as-is (L114); тонкий adapter для "prior→current" выбора (Q2=a). |
| Versions read-path (`get_two_versions`/`list_by_topic`) | **Read reuse** | archival side для diff; `purge_stale` (TTL) **не** трогаем (Q7=a′ fallback). |
| `DigestService` | **Yes** | новый content-selection + `_render_topic_block` + `mode`-branch; delivery/`run_for_subscription`/cursor-advance **reuse**. |
| Digest prompt | **Yes (config-only)** | новый `prompts/topic_digest.yaml` (Q4=a); `reload_prompts`. Channel `digest.yaml` не трогаем. |
| Scheduler | **No change (Q3=a)** | reuse `run_scheduled_digests_task` (zero plumbing); mode-branch внутри service. |
| MCP / CLI surface | **Yes** | extend `subscribe_digest` (`mode`/`topic_ids`) + CLI зеркало. |
| Bot tools | **No (OUT)** | §9 — Bot F5-C/topic-digest tools отдельный slice. |
| Delivery / bot-push / ADR-0008 targets | **No code change** | reuse полностью. |
| Raw-doc digest path (существующий F6) | **No regression** | topic-digest — параллельный режим; `mode='channel'` bit-for-bit. |
| Alembic | **Yes (Q5=a)** | новая ревизия (+2 колонки, additive/nullable/default → безопасный upgrade). |
| **ADR** | **Yes (ADR-0019)** | малый F6 subscription-addendum (§11); пишется в impl-сессии. |
| Prod data | **No mutation content; schema migration** | content-selection read-only, **но** deploy = pre-deploy backup + `db upgrade` (with-migration). |

---

## 8. Design decisions (owner-resolved 2026-07-24 — DECIDED, consistent с plan §9)

> Все 7 форков разрешены owner'ом. Detail/anchors — plan §4/§9 + START_PROMPT §0/§7. Здесь — canonical DECIDED-набор.

- **Q1. Subscription granularity = BOTH modes.** Подписка несёт `mode` (`'channel'|'topic'`); channel/workspace "all active topics in scope" mode **И** explicit `topic_ids[]` (topic-mode). Drives Q5 schema-add + surface (extend `subscribe_digest`, not a new tool).
- **Q2. "What's new" semantics = (a) diff-of-summaries.** Reuse `diff_topic_summaries(prior → current)` ([`domain/topic_history_diff.py`](../../tg_parser/domain/topic_history_diff.py) L114) — text-diff `summary` + set-diff scopes. Pure reuse of shipped #2; no re-implemented diff logic.
- **Q3. Trigger = (a) reuse F6 cron cadence.** Same `run_scheduled_digests_task` ([`scheduler_service.py`](../../tg_parser/services/scheduler_service.py) L1093), zero scheduler-plumbing change, no double-delivery risk. Event-on-resummarize (hook L1173) is **explicitly OUT / fast-follow** (§9).
- **Q4. Delivery format = (a) new `prompts/topic_digest.yaml`.** Separate prompt file (tunes independently of channel `digest.yaml`), reusing the `DigestFormat` enum (`summary`/`bullets`/`detailed`, [`domain/models.py`](../../tg_parser/domain/models.py) L755) for output style.
- **Q5. Schema shape = (a) add columns to `digest_subscriptions`.** `mode VARCHAR` + `topic_ids TEXT[]` via a new Alembic migration (precedent [`20260418_add_digest_subscriptions.py`](../../migrations/versions/ingestion/20260418_add_digest_subscriptions.py)). Changes the F6 subscription contract ⇒ **small ADR required = ADR-0019** (§11). This makes the feature **with-migration** (§7/§10).
- **Q6. Cursor semantics = (a) `topic_cards.last_summarized_at > cursor` (strict `>`), reusing `last_digest_cursor`.** Advance-only-on-success (mirrors channel digest). No new cursor column.
- **Q7. TTL-gap robustness (ADR-0018) = (a′) nearest-available ≥ cursor, else genesis→current**, with a "baseline shifted (retention)" note; **never 500.** `get_two_versions` ([`topic_card_version_repo.py`](../../tg_parser/storage/sqlalchemy/topic_card_version_repo.py) L102) returns absent keys ⇒ fallback clean by construction (ADR-0018 double-floor: genesis v1 + last-N always present).

---

## 9. Out of scope (жёстко — impl-сессия не расширяет без нового GO)

- **Bot tools** для topic-digest / F5-C (Telegram-side subscribe UX) — item #5 (Bot tools); this slice = MCP/CLI + scheduler.
- **Event-on-resummarize trigger (Q3-b)** — explicitly OUT / fast-follow: только cron reuse (Q3=a); event-hook = отдельный slice (новый plumbing + свой idempotency/cursor против дубль-доставки).
- **Email / webhook delivery** — только bot-push (ADR-0008 targets: chat/channel).
- **Per-topic dedup** across subscriptions / cross-topic dedup — F5-B concern, not here.
- **Schema rewrite of F6** — только **additive** +2 колонки (`mode`/`topic_ids`, Q5=a); переработка существующих колонок / full redesign OUT.
- **New LLM deps** — reuse existing LLM factory + `difflib` (stdlib); no new `pyproject`/`requirements` (ADR-0017).
- **Changes to raw-doc digest path** — существующий `mode='channel'` F6 bit-for-bit; no regression.
- **TTL / retention changes** (ADR-0018 / `purge_stale`) — topic-digest is a read-only consumer of gaps, не расширяет retention.
- **diff-API changes** — `diff_topic_summaries` / `get_two_versions` reuse as-is; no new diff surface.
- **#6 type-promotion, #7 topic dedup, #8 bundle-item GC, #9 HTTP endpoints** — separate #15 items.
- `docs/methodology/**`, `pyproject.toml`, `requirements.txt` (AGENTS.md / ADR-0017).

---

## 10. Acceptance / to-verify (детально в plan §7 / START_PROMPT §5)

- [ ] **Both modes (Q1):** subscription с `mode='topic'`+`topic_ids[]` selects explicit topics; `mode='channel'` — all active topics in scope. Tick emits digest whose content is the **evolving topic-summary delta** (Q2=a diff), not raw doc summaries.
- [ ] **Schema-add (Q5):** migration adds `mode`+`topic_ids`; upgrade/downgrade idempotent; `mode='channel'` без `topic_ids` = сегодняшний F6 bit-for-bit.
- [ ] **Content-selection (Q6):** returns only topics with `last_summarized_at > last_digest_cursor` (strict `>`, no re-include); cursor advances **only on successful delivery/empty-skip**.
- [ ] **TTL-gap robust (Q7=a′):** purged intermediate side → **nearest-available ≥ cursor, else genesis→current** with "baseline shifted (retention)" note, **never 500** (ADR-0018 double-floor).
- [ ] **Diff-reuse (Q2=a):** payload reuses shipped `diff_topic_summaries` (no re-implemented diff logic).
- [ ] **Prompt (Q4=a):** new `prompts/topic_digest.yaml`, reuse `DigestFormat`; channel `digest.yaml` untouched; `reload_prompts`-compatible.
- [ ] **Scheduler (Q3=a):** same `run_scheduled_digests_task` cron path; no new scheduler plumbing; no double-delivery.
- [ ] Existing raw-doc digest (`mode='channel'`) **unchanged** (bit-for-bit no regression).
- [ ] Visibility mirrors `get_topic_details` / `assert_topic_access` (topic visible if user sees ≥1 of `card.sources`).
- [ ] No new deps; delivery/scheduler/subscription-lifecycle reused (minimal net-new code).
- [ ] `ruff check` + `ruff format --check` + `TEST_POSTGRES=1 uv run pytest -q` — green.
- [ ] **ADR-0019** written & accepted; FUTURE_FEATURES / skeleton pointer updated.
- [ ] **Deploy (with-migration):** pre-deploy backup + `db upgrade` — NOT read-only.
- [ ] Commit/PR — only on explicit user request.

---

## 11. Нужен ли новый ADR? — **ДА, ADR-0019 (F6 subscription-addendum)**

**Q5=schema-add ⇒ ADR ОБЯЗАТЕЛЕН.** Добавление `mode`/`topic_ids` на `digest_subscriptions` делает их нормативной частью F6 digest data-model — меняет, что есть «подписка» (channel-scoped → channel|topic-scoped). Decision класса ADR-per-decision (как ADR-0008 subscription-target-model, 0018 retention).

- **Номер:** next-free = **ADR-0019** (last in [`docs/adr/`](../adr/) = 0018-topic-card-versions-retention; verified 2026-07-24).
- **Scope:** F6 subscription addendum — `mode` discriminator + `topic_ids[]`; topic-mode reuse `last_digest_cursor` (Q6=a); relation to ADR-0008 (delivery targets unchanged), ADR-0006 (#1/#5), ADR-0018 (Q7=a′ gap fallback).
- **Когда:** written **during the impl session** (не в этой planning-сессии).

_(Контраст: diff-API #2 остался ADR-free — лишь **читал** существующие колонки. Topic-digest **добавляет** колонки ⇒ ADR нужен.)_

---

## 12. Pointers

- Issue [#15](https://github.com/AlexEfimov/TG_parser/issues/15) item #3 F6 topic-digest; [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) L799 / F6 §L884-1033 (L1022, L1031)
- Companion plan: [`PLAN_SESSION_F5C_TOPIC_DIGEST_2026-07-24.md`](PLAN_SESSION_F5C_TOPIC_DIGEST_2026-07-24.md)
- Implementation START_PROMPT (decisions baked): [`START_PROMPT_SESSION_F5C_TOPIC_DIGEST_2026-07-24.md`](START_PROMPT_SESSION_F5C_TOPIC_DIGEST_2026-07-24.md)
- Diff-API (#2, building block): [`PLAN_SESSION_F5C_DIFF_API_2026-07-23.md`](PLAN_SESSION_F5C_DIFF_API_2026-07-23.md), [`SKELETON_F5C_DIFF_API_TOPIC_HISTORY_2026-07-23.md`](SKELETON_F5C_DIFF_API_TOPIC_HISTORY_2026-07-23.md)
- TTL/retention (#1, gaps): [ADR-0018](../adr/0018-topic-card-versions-retention.md), [`PLAN_SESSION_F5C_TTL_RETENTION_2026-07-22.md`](PLAN_SESSION_F5C_TTL_RETENTION_2026-07-22.md)
- F6 plan (shipped): [`F6_SCHEDULED_DIGESTS_PLAN.md`](../plans/F6_SCHEDULED_DIGESTS_PLAN.md)
- ADR [0006](../adr/0006-karpathy-like-living-kb-principles.md), [0008](../adr/0008-subscription-target-model.md), [0017](../adr/0017-dependency-management-policy.md), [0018](../adr/0018-topic-card-versions-retention.md)

---

## 13. Self-review fixes applied (skeleton)

**Finalization pass (2026-07-24) — owner разрешил Q1-Q7; skeleton flipped to DECIDED (still skeleton).** Критический pass (internal consistency skeleton↔plan↔START_PROMPT / anchor re-verify / testable acceptance / explicit OUT / TTL-gap robustness / reuse of shipped diff-API / no invented symbols):

1. **§8 OPEN → DECIDED** — Q1=both modes, Q2=a diff, Q3=a cron reuse, Q4=a new `topic_digest.yaml`, Q5=a schema-add, Q6=a `last_summarized_at`/reuse cursor, Q7=a′ nearest-≥-cursor→genesis. Banner, §4 reuse-map, §5 scope, §6 checklist, §7 blast-radius, §9 OUT, §10 acceptance, §11 ADR — все приведены в соответствие; ни одной секции с «OPEN» форком.
2. **With-migration + ADR-0019 зафиксированы** — Q5=schema-add ⇒ pre-deploy backup + `db upgrade` + малый ADR-0019 (F6 subscription-addendum). Явно противопоставлено read-only diff-API #2 (banner/§7/§11).
3. **Anchor re-verify пофайловым чтением (2026-07-24)** — verified: `DigestService` `generate` L351 / `run_for_subscription` L549 / `_render_channels_block` L631 / `subscribe` L180 / docstring L10-20 / filter L382-393; `digest_subscription_repo` `_SELECT_COLUMNS` L14 / `create` L27 / `update` L106; port L1525; `prompts/digest.yaml` placeholders L50-60; MCP `subscribe_digest` L3101 / `list_digests` L3335 / `unsubscribe_digest` L3388 / `get_topic_details` L1408; `run_scheduled_digests_task` L1093 / `run_resummarize_for_channel` L1173; `register_digest_subscription` L492 / `_digest_job_id` L487; `diff_topic_summaries` L114 / `snapshot_from_version` L56 / `snapshot_from_card` L74; `get_two_versions` L102 / `purge_stale` L142; `list_resummarize_candidates` L247 (`last_summarized_at` L275) / `list_by_channels` L201 / `commit_resummary` L286; `TopicCard` L190 (`last_summarized_at` L226, `summary_version` L230), `TopicCardVersion` L431, `DigestSubscription` L763, `DigestFormat` L755; `assert_topic_access` L50; migration precedent `20260418_add_digest_subscriptions.py`; CLI `digest_cmd.py` `add` L24. Ни одного invented symbol; line-numbers актуальны.
4. **ADR-0019 = next-free** — `ls docs/adr/` → last 0018 ⇒ 0019 свободен (§11).
5. **Testable acceptance §10 сделан concrete** — каждый пункт привязан к Q-решению + migration idempotency + ADR-0019 + backup/upgrade gate.
6. **Hard OUT §9 подтверждён + event-on-resummarize добавлен** — Bot(#5), event-hook(Q3-b), email/webhook, dedup, non-additive schema-rewrite, new deps, raw-doc regression, TTL/diff-API changes; согласовано с plan §8.
7. **Consistency skeleton↔plan↔START_PROMPT** — все три дока согласны на Q1-Q7, with-migration/backup + ADR-0019 consequence, reuse of shipped diff-API. START_PROMPT: [`START_PROMPT_SESSION_F5C_TOPIC_DIGEST_2026-07-24.md`](START_PROMPT_SESSION_F5C_TOPIC_DIGEST_2026-07-24.md).
