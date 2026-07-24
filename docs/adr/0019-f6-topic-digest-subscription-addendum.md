# ADR 0019 – F6 subscription addendum: topic-scoped digest (`mode` + `topic_ids`)

## Статус

**Accepted (2026-07-24).** F5-C #15 item #3. Реализация (Alembic-миграция
`d1e2f3a4b5c6` + `DigestSubscription` model/repo/port + read-only
`TopicCardRepo.list_topics_changed_since` + payload через зашедший
`diff_topic_summaries` + новый `prompts/topic_digest.yaml` + MCP/CLI surface +
scheduler mode-branch) landed в impl-сессии. Это **with-migration** deploy
(pre-deploy backup + `db upgrade`), в отличие от read-only diff-API (#2).
Sources of truth:
[`PLAN_SESSION_F5C_TOPIC_DIGEST_2026-07-24.md`](../notes/PLAN_SESSION_F5C_TOPIC_DIGEST_2026-07-24.md),
[`START_PROMPT_SESSION_F5C_TOPIC_DIGEST_2026-07-24.md`](../notes/START_PROMPT_SESSION_F5C_TOPIC_DIGEST_2026-07-24.md).

## Контекст

F6 Scheduled Digests (shipped) — **document-scoped**: подписка
([`DigestSubscription`](../../tg_parser/domain/models.py)) несёт `channel_ids[]`
+ `last_digest_cursor` (`processed_at`-timestamp); каждый tick
[`DigestService.generate`](../../tg_parser/services/digest_service.py) тянет новые
`ProcessedDocument` (`processed_at > cursor`), рендерит per-channel блок raw-сводок
и просит LLM собрать digest. Контент = raw new-document summaries за окно.

F5-C сделал темы «живыми»: `commit_resummary` бампит `summary_version`, обновляет
`summary`/`scope_in`/`scope_out`/`last_summarized_at`, а snapshot *предыдущего*
состояния уходит в `topic_card_versions`. diff-API (#2, ADR-free — он лишь
**читал** существующие колонки) дал `diff_topic_summaries(left, right)` —
«что изменилось» между двумя snapshot'ами темы (text-diff `summary` + set-diff
scopes).

«Что нового по теме X» = один вызов `diff_topic_summaries`. Естественный payload
topic-дайджеста — выход этого diff. Но чтобы подписка знала, что она topic-scoped,
нужно **расширить контракт подписки** — а это меняет F6 subscription data-model
(что есть «подписка»: channel-scoped → channel|topic-scoped). Decision класса
ADR-per-decision (как ADR-0008 subscription-target-model, ADR-0018 retention) ⇒
ADR обязателен. Контраст: diff-API #2 остался ADR-free (read-only); topic-digest
**добавляет** 2 колонки ⇒ ADR нужен.

## Решение

### 1. Schema-add: `mode` + `topic_ids` на `digest_subscriptions`

Новая Alembic-ревизия `d1e2f3a4b5c6` (chain от текущего **ingestion**-head
`c0d1e2f3a4b5` — миграции разбиты на ветки `ingestion/`+`processing/`, поэтому
`alembic heads` multi-head; `20260418_add_digest_subscriptions.py` — только
структурный precedent формы ADD COLUMN, **не** down_revision-target):

- `mode VARCHAR NOT NULL DEFAULT 'channel'` — content-дискриминатор.
- `topic_ids TEXT[]` (nullable) — явные topic-id для topic-mode.

Additive / nullable / defaulted ⇒ безопасный upgrade; каждый legacy-row
бэкфилится в `mode='channel'`. downgrade дропает обе колонки. Обе стороны
идемпотентны (`IF [NOT] EXISTS`).

### 2. Семантика `mode` (нормативно)

- **`channel`** (default) — существующий raw-document F6 digest, **bit-for-bit**.
  Контент = raw new-document summaries; cursor = `processed_at`; scope =
  `channel_ids`. `topic_ids` в channel-mode запрещён (модель нормализует в NULL /
  отвергает непустой список). **No regression**: каждая существующая подписка
  после миграции = `mode='channel'` ⇒ ведёт себя как сегодня.
- **`topic`** — evolving topic-summary-delta digest. Контент = per-topic
  `diff_topic_summaries(prior → current)`; cursor = `last_summarized_at`;
  scope = explicit `topic_ids` (когда непустой) **или** channel-scoped (все
  active-темы в `channel_ids`, если `topic_ids` пуст — реализовано в read-path,
  surface в этом slice требует непустой `topic_ids`).

> **Note (resolved brief-contradiction).** Планировочные заметки в одном месте
> описывали «channel/workspace all-active-topics» как `mode='channel'`, что
> прямо конфликтует с hard-invariant «`mode='channel'` = raw-doc bit-for-bit».
> Разрешено в пользу no-regression: `mode='channel'` остаётся raw-doc; topic-scope
> (explicit **и** channel-scoped) живёт под `mode='topic'`. Channel-scoped
> topic-digest поддержан в `list_topics_changed_since`, но на surface в этом
> slice — explicit `topic_ids` (fast-follow для channel-scoped surface).

### 3. Content-selection (read-only) — `last_summarized_at > cursor`

Новый `TopicCardRepo.list_topics_changed_since(cursor, channel_ids|topic_ids)` —
зеркало `list_resummarize_candidates`; ключ = `last_summarized_at > :cursor`
(строгий `>`, зеркалит F6 cursor-инвариант; равенство ре-включало бы последнюю
тему каждый tick). NULL `last_summarized_at` (never-re-summarized / pre-F5-C)
исключены by construction (`NULL > x` = never true) — это **реальный** safety
mechanism «тема не приходит без версий». ⚠️ `last_summarized_at` НЕ
проиндексирован + channel-scope non-sargable `sources_json LIKE` ⇒ seq-scan;
index НЕ заявляем (приемлемо на текущем объёме; partial-index — deferred при
росте). Write-path (`commit_resummary`) не тронут.

### 4. Cursor reuse + mode-change reset (M3)

Topic-mode переиспользует **существующее** поле `last_digest_cursor` (новое
cursor-поле НЕ добавляем). Но это единый TIMESTAMPTZ с **двумя** семантиками
(channel=`processed_at`, topic=`last_summarized_at`). `subscribe` —
idempotent-upsert на `(owner_id, name)`; при смене `mode` существующей подписки
stale cursor несёт неверную семантику → неверное первое окно ⇒ на mode-change
`last_digest_cursor` **сбрасывается в NULL** (`update(..., reset_cursor=True)`),
перезапуская first-run lookback. **Тот же reset на смене `topic_ids`**: cursor —
единый `last_summarized_at`-watermark на весь topic-set, поэтому добавленная тема
с `last_summarized_at ≤ cursor` иначе молча пропускалась бы до следующего своего
изменения. Advance-cursor-only-on-success + skip-if-empty наследуются из F6.

### 5. Payload = cumulative prior via `list_by_topic` (Q7=B), никогда 500

`current` = живая карточка (`snapshot_from_card`). `prior` = состояние-на-cursor:
из `list_by_topic(topic_id, limit=keep_last_n)` (newest-first WITH `created_at`)
берём в Python новейшую версию с `created_at ≤ cursor`. Fallback на TTL-gaps:
если ни одна не подходит → oldest-surviving версия (`baseline_shifted='retention'`
когда `version_no>1`, иначе `'genesis'`); нет версий вовсе → весь current как
новый (`'genesis'`). **никогда 500 by construction** — диффим то, что физически
выжило. Это TRUE cumulative «с прошлого digest» (покрывает multi-bump). `prior`
**не** выбирается через `get_two_versions` (by-`version_no` point-lookup не маппит
cursor-timestamp в версию — это был BLOCKER); `version_at_or_before`-подобный SQL
НЕ нужен; нового repo-метода нет. `diff_topic_summaries` переиспользован as-is.

### 6. Visibility на ОБОИХ этапах (M4)

- **subscribe** — `assert_topic_access` (тема видна, если caller видит ≥1 из
  `card.sources`); topic-not-found / no-access → структурированный `{"error": ...}`.
- **delivery** — topic-mode content-selection отбрасывает тему, чьи `card.sources`
  больше не пересекаются с channel-scope подписки на момент tick (revoked access
  не утекает evolving topic summaries). Намеренное parity-улучшение: channel-mode
  F6 на доставке не перепроверяет.

### 7. Prompt + scheduler + surface

- Новый `prompts/topic_digest.yaml` (reuse `DigestFormat` enum; placeholders
  `{format,language,from_iso,to_iso,topics_block}`; `reload_prompts`-совместим);
  channel `digest.yaml` не тронут.
- Scheduler: тот же `run_scheduled_digests_task` cron path; mode-branch внутри
  `DigestService.generate`; топ-репо строятся на той же processing-сессии, что и
  processed-repo (zero новый scheduler-plumbing, нет дубль-доставки).
- Surface: extend `subscribe_digest` MCP (`mode`/`topic_ids`) + `DigestSubscriptionInfo`
  DTO + CLI `digest add --mode/--topics`; `list_digests`/`unsubscribe_digest` reuse.

## Отношение к другим ADR

- **ADR-0008 (subscription-target-model)** — delivery targets (chat/channel)
  **неизменны**; topic-digest не трогает доставку, только content/scope.
- **ADR-0006 (Karpathy living-KB)** — #1 (persistent subscriptions — не новая
  сущность, +2 колонки), #2 (provenance — payload несёт `version_no`/`created_at`/
  `llm_*` обеих сторон), #5 (living loop — тема ре-суммаризуется → на следующем
  cron попадает в topic-digest), #7 (graceful degradation — never-500 fallback).
- **ADR-0017 (dependency policy)** — новых deps нет (`difflib` stdlib);
  `pyproject`/`requirements` не тронуты.
- **ADR-0018 (retention/gaps)** — topic-digest — read-only consumer gaps; Q7=B
  cumulative prior fallback честно диффит выжившее; retention не расширяем.

## Последствия

- **With-migration deploy:** pre-deploy backup + `alembic upgrade head`
  (`d1e2f3a4b5c6`, +2 колонки). Content-selection сам read-only, но deploy трогает
  schema ⇒ backup обязателен. **НЕ** read-only.
- **No regression:** `mode='channel'` bit-for-bit; raw-doc path не менялся кроме
  дешёвого mode-branch на входе `generate`.
- **Deferred/OUT:** event-on-resummarize trigger (свой idempotency/cursor);
  channel-scoped topic-digest на surface; per-topic dedup; email/webhook; Bot
  tools; partial-index на `last_summarized_at`. См. plan §8.
