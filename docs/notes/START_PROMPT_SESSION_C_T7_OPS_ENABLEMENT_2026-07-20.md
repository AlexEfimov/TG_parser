# START PROMPT — Session C (γ2): T7 ops-enablement — включить `RESUMMARIZE_MAX_AGE_DAYS` в проде + закрыть B2-guard gap

**Дата:** 2026-07-20 · **Тип:** ops-enablement (compose/test guard + prod env rollout + anchor-refresh) · **Ветка:** `main`

**Goal (одной строкой):** OPERATIONALLY ENABLE уже-отгруженную (`b294b05`, 2026-06-14) но DORMANT в проде фичу F5-C P2 «evolving topic-summaries freshness» (Wave 2 T7) — выкатить консервативный prod-default `RESUMMARIZE_MAX_AGE_DAYS≈14`, закрыть единственную реальную B2/BUG-085-дыру (этот scheduler-critical knob **не** в `SCHEDULER_CRITICAL_ENV`), и подтвердить, что observability-петля (per-channel re-summarize cost + counter-vs-age gate) реально видна владельцу для тюнинга knob.

> Рабочий режим (нормативно, [`AGENTS.md`](../../AGENTS.md)): `git commit` / PR — **только** по явному запросу пользователя; PR = merge-commit + `--delete-branch`. Никаких правок `docs/methodology/**` из этого workspace. Правки `pyproject.toml` / `requirements.txt` — только с явного запроса (для этой задачи **не требуются**). Уважать `docs/adr/` (accepted) и `docs/contracts/` (JSON Schema нерушимы). Прод-мутация env (`RESUMMARIZE_MAX_AGE_DAYS=14`) — **gated на явный GO владельца** (cost-watch), см. §5.

---

## 0. TL;DR — ⚠️ большая часть γ2 УЖЕ ОТГРУЖЕНА (прочитать перед планированием)

> 🔺 **CORRECTION 2026-07-20 (read-only prod check):** премисса «фича DORMANT / `RESUMMARIZE_MAX_AGE_DAYS` в проде `0`» ниже — **STALE**. Live-прод: knob уже `=14`, включён 2026-07-19 20:36Z; C2 (Вариант A) фактически **уже выкачен**, age-триггер активен, age-gate `ratio14d≈0.503` (маргинально красный, alert `pending`), cost негативно не растёт. Решение владельца 2026-07-20: оставить 14, watch. Детали: [`C2_T7_LIVE_SNAPSHOT_2026-07-20.md`](C2_T7_LIVE_SNAPSHOT_2026-07-20.md). ⇒ C2 «prod rollout» / «Current prod state = DORMANT» ниже читать как исторический контекст.

Бриф γ2 сформулирован как «построить observability + runbook с нуля». **Research 2026-07-20 показал, что это НЕ так** — почти всё уже в коде на `main`. Реальный остаток session C — **тонкий ops-tail**, а не спринт. Точная карта состояния:

| Подзадача из брифа γ2 | Фактическое состояние | Anchor |
|---|---|---|
| Time-based триггер (`RESUMMARIZE_MAX_AGE_DAYS`) в коде | ✅ **DONE** (dormant, default 0) | `settings.py:1134`, `topic_card_repo.py:247`, `resummarization_service.py:112/208` |
| Per-channel metric label (`channel_id` на `tg_resummarize_total` / `_tokens_total`) | ✅ **DONE** | `metrics.py:391/418/567` |
| Compose-mirror `RESUMMARIZE_MAX_AGE_DAYS` в `tg_parser` allow-list | ✅ **DONE** (default `:-0`) | `docker-compose.yml:78` |
| **B2/BUG-085 guard: knob в `SCHEDULER_CRITICAL_ENV`** | ❌ **PENDING** — `RESUMMARIZE_MAX_AGE_DAYS` **отсутствует** в set (есть только `RESUMMARIZE_ENABLED`/`_TRIGGER_N`) | `tests/test_compose_env_propagation.py:149-162` |
| Grafana-панель per-channel re-summarize cost + trigger-split | ✅ **DONE** (row «T7 F5-C P2») | `docker/grafana/dashboards/wave2_observation.json:173-401` |
| Prometheus recording rule + gate alert (age-share) | ✅ **DONE** | `docker/prometheus/alerts.yml:241` (record), `:254` (gate), `:170` (LLM-err) |
| Runbook на включение + мониторинг + rollback | ✅ **DONE** (но stale line-anchors) | `docs/runbooks/F5C_DEPLOY_AND_WATCH.md:320-409` |
| Тесты age-триггера + channel_id label | ✅ **DONE** | `tests/test_resummarize_metrics.py`, `tests/test_f5c_topic_card_repo.py` |
| **Prod rollout значения `=14`** | ❌ **PENDING** — gated на явный GO (cost-watch) | prod `.env` (вне репо) |

⇒ **Реальный actionable scope session C = три тонких куска:**
1. **C1 (B2 guard, code+test):** добавить `RESUMMARIZE_MAX_AGE_DAYS` в `SCHEDULER_CRITICAL_ENV` (compose-строка уже есть → guard-тест позеленеет сразу). **Единственная настоящая дыра.**
2. **C2 (prod rollout, gated ops):** механизм default'а **DECIDED — Вариант A** (§5.1, владелец 2026-07-20): prod `.env`=14, compose-fallback остаётся `:-0`; по GO — выкатить (`docker compose up -d tg_parser`, НЕ `restart`) и отвотчить.
3. **C3 (runbook fix, docs, опц.):** починить stale line-anchors (C3a) **и** `restart`→`up -d` deploy-команды (C3b) в T7-разделе runbook (см. §4/§6).

**Current prod state (одной строкой):** фича **DORMANT** — `RESUMMARIZE_MAX_AGE_DAYS` в проде unset/`0` (counter-only триггер, bit-for-bit MVP); age-ветка кандидат-отбора не срабатывает; `tg_resummarize_total{trigger="age"}` ≈ 0.

---

## 1. Контекст / мотивация (γ2, из source-of-truth)

Track γ2 определён в [`DRAFT_NEXT_CONTRACT_POST_WAVE2_2026-06-18.md`](DRAFT_NEXT_CONTRACT_POST_WAVE2_2026-06-18.md) §2 (Track γ) / §3: *«F5-C P2 freshness landed с env `RESUMMARIZE_MAX_AGE_DAYS` (default disabled) + per-channel `tg_resummarize_total{channel_id}` metric. Ops-задача: задокументировать/выкатить консервативный prod-default (~14д), добавить Grafana panel / runbook на per-channel re-summarize cost, чтобы owner мог тюнить knob. Size ~0.3–0.5, risk LOW.»* Метод/rationale закреплён в [`PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md`](PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md) §4 T7 (esp. #10 per-channel metric — cardinality note: ~10–13 активных каналов → приемлемо, fallback `"-"`).

**Что делает knob (verified 2026-07-20):** `RESUMMARIZE_MAX_AGE_DAYS` — **time-based** триггер re-summarize, **дополняющий** (не заменяющий) counter-триггер `RESUMMARIZE_TRIGGER_N`. При `> 0` тема дополнительно становится кандидатом, если её последнее summary старше N дней **И** у неё есть ≥1 новый item (`new_items_since_last_summary > 0`), даже если counter не дошёл до `RESUMMARIZE_TRIGGER_N`. Ловит low-volume темы, которые морально устаревают, ни разу не набрав порог. `0` = disabled (counter-only, bit-for-bit MVP). Консервативный prod-start ~14 (согласован со stale-detector из tracking-issue **#15** «> 14 days»).

**Почему karpathy-петля (ADR-0006 #6):** turn a knob → watch its per-channel cost. Наблюдаемость (Grafana + gate) уже построена именно под 14д — панели/алерты дословно хардкодят `RESUMMARIZE_MAX_AGE_DAYS=14`. То есть инфраструктура наблюдения ждёт, пока knob включат; session C замыкает петлю.

---

## 2. Code anchors (VERIFIED 2026-07-20 — перечитать и подтвердить перед правкой)

> ⚠️ Все line-numbers проверены чтением файлов 2026-07-20. Для длинных файлов (`settings.py`, `metrics.py`, `resummarization_service.py`) — **перечитать и подтвердить** перед записью в тесты/правки.

### 2.1 Feature (уже в коде — read-only reference для этой задачи)

| Якорь | Файл | Линия |
|---|---|---|
| `resummarize_max_age_days` field (default **0**, `ge=0, le=3650`, описание #15 #4 + «Conservative prod start ~14») | [`tg_parser/config/settings.py`](../../tg_parser/config/settings.py) | 1134-1145 |
| `_classify_trigger(card)` → `counter` / `age` / `-` (зеркалит OR-предикат repo; `age`-ветка гейтит `max_age_days > 0 and new_items > 0 and last_summarized_at < now - Ndays`) | [`tg_parser/services/resummarization_service.py`](../../tg_parser/services/resummarization_service.py) | 112-136 |
| `run_for_channel` — передаёт `max_age_days=settings.resummarize_max_age_days` в candidate-query (LLM на отборе НЕ вызывается) | то же | 205-209 |
| `metric_channel = card.sources[0] if card.sources else "-"` (откуда берётся `channel_id` label) | то же | 261, **348** |
| `list_resummarize_candidates(channel_id, *, threshold, max_age_days=0)` — SQL OR-предикат; **top-level `WHERE new_items_since_last_summary > 0` сохранён → остаётся под partial-index** `idx_topic_cards_resummarize_candidates`; `max_age_days=0` ⇒ counter-only bit-for-bit | [`tg_parser/storage/sqlalchemy/topic_card_repo.py`](../../tg_parser/storage/sqlalchemy/topic_card_repo.py) | 247-284 (index-note 252-256, SQL 270-282, top-level predicate 272) |
| `list_resummarize_candidates` (abstract port — держать сигнатуры синхронно) | [`tg_parser/storage/ports.py`](../../tg_parser/storage/ports.py) | 753-774 |
| `RESUMMARIZE_TOTAL` (`tg_resummarize_total{channel_id, outcome, trigger}`) | [`tg_parser/api/metrics.py`](../../tg_parser/api/metrics.py) | 391-416 |
| `RESUMMARIZE_TOKENS_TOTAL` (`{channel_id, provider, model, token_type}`) | то же | 418-425 |
| `record_resummarize_outcome(*, topic_id, status, channel_id="-", trigger="-", …)` (empty → `"-"` нормализация; per-channel token-cost) | то же | 567-619 |

### 2.2 Ops surface (ЗДЕСЬ живёт правка session C)

| Якорь | Файл | Линия |
|---|---|---|
| **`SCHEDULER_CRITICAL_ENV` set** — ❌ `RESUMMARIZE_MAX_AGE_DAYS` ОТСУТСТВУЕТ (есть `RESUMMARIZE_ENABLED`:155, `RESUMMARIZE_TRIGGER_N`:156) — **C1 добавляет сюда** | [`tests/test_compose_env_propagation.py`](../../tests/test_compose_env_propagation.py) | 149-162 |
| Параметризованный guard-тест `test_tg_parser_mirrors_scheduler_critical_env` (`_service_env_keys` helper :43-60) | то же | 165-175 |
| **compose-mirror `- RESUMMARIZE_MAX_AGE_DAYS=${RESUMMARIZE_MAX_AGE_DAYS:-0}`** — ✅ УЖЕ ЕСТЬ (F5-C блок c BUG-078-комментарием 74-79) | [`docker-compose.yml`](../../docker-compose.yml) | 78 |
| `.env.example` — `# RESUMMARIZE_MAX_AGE_DAYS=0  # …0=disabled, ~14 prod` (закомментирован) | [`.env.example`](../../.env.example) | 233 |
| **Grafana dashboard** — row «T7 F5-C P2 — Re-summarize freshness (RESUMMARIZE_MAX_AGE_DAYS=14)» + панели (rate by channel&outcome, outcomes 24h, tokens by channel rate+cumulative, duration p50/p95, trigger split counter-vs-age, age-trigger 14d share vs 50% gate); datasource uid `prometheus` | [`docker/grafana/dashboards/wave2_observation.json`](../../docker/grafana/dashboards/wave2_observation.json) | 173-401 |
| Grafana dashboards provisioning (path `/var/lib/grafana/dashboards`, folder `TG_parser`) | [`docker/grafana/provisioning/dashboards/dashboards.yml`](../../docker/grafana/provisioning/dashboards/dashboards.yml) | 1-13 |
| Grafana datasource (uid `prometheus`, url `http://prometheus:9090`) | [`docker/grafana/provisioning/datasources/prometheus.yml`](../../docker/grafana/provisioning/datasources/prometheus.yml) | 1-10 |
| **Prometheus** recording rule `tg:resummarize_age_trigger:ratio14d` = `age / (counter+age)` за 14д (`-` исключён) | [`docker/prometheus/alerts.yml`](../../docker/prometheus/alerts.yml) | 241-245 |
| Gate alert `ResummarizeAgeTriggerGateF5CPhase2` (info, `for:12h`, `ratio14d >= 0.5`) | то же | 254-261 |
| `ResummarizeLLMErrorRate` (info, `for:30m`, `llm_error`-доля > 20%) | то же | 170-181 |
| **Runbook T7-раздел** — «Включение `RESUMMARIZE_MAX_AGE_DAYS`» (⚠ содержит **stale** line-anchors — C3) | [`docs/runbooks/F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md) | 320-409 |

---

## 3. Scope — C1 (B2 / BUG-085 guard: единственная реальная code/test-правка)

**Проблема (verified 2026-07-20):** `RESUMMARIZE_MAX_AGE_DAYS` — scheduler-critical knob: scheduler-синглтон читает OS-env на старте, а pydantic-settings отдаёт приоритет OS-env над bind-mounted `/app/.env` (документированный **BUG-078/BUG-085** gotcha). Compose уже зеркалит его (`docker-compose.yml:78`, default `:-0`), **но** `SCHEDULER_CRITICAL_ENV` (`tests/test_compose_env_propagation.py:149-162`) его **не** содержит. Значит: если кто-то в будущем удалит compose-строку 78, compose-parity guard это **не** поймает → knob тихо провалится в code-default (0) в работающем воркере, и prod-`.env`-override (`=14`) будет молча проигнорирован. Ровно та патология, ради которой B2/BUG-085 guard и создавался.

**Место (нормативно — здесь, house-style):** расширить curated set `SCHEDULER_CRITICAL_ENV`. Это минимальная дельта в существующем стиле (комментарий уже фиксирует правило «add to BOTH compose block AND this set»).

**⚠️ Reconcile с «FINAL curated set» (обязательно — иначе комментарий станет самопротиворечивым):** inline-комментарий на `tests/test_compose_env_propagation.py:147-148` объявляет set замороженным: *«DECIDED 2026-07-19 (§7 #4): this is the FINAL curated set. Do NOT expand to unrelated DB/LLM keys.»*. Здесь ВАЖНО: `RESUMMARIZE_MAX_AGE_DAYS` — **scheduler-critical knob** (scheduler-синглтон читает его OS-env на старте), **НЕ** DB/LLM-ключ. То есть это **легитимное** расширение curated set, которое запрет «do NOT expand to unrelated DB/LLM keys» **не** покрывает (запрет про НЕсвязанные DB/LLM-ключи, а не про новые scheduler-critical knobs). Поэтому C1 обязан **не только добавить член set, но и ОБНОВИТЬ комментарий 147-148**, чтобы он не читался как «FINAL / do not expand» над только что добавленным 13-м членом.

**Method-selection — DECIDED (MVP, зеркалит §7 #3/#4 предыдущего START_PROMPT):** явный curated set (одна строка), **НЕ** вывод инварианта из единого источника (`.env.example` diff / полный `Settings`-diff отклонены как brittle/зашумлённые — отложено до возможного будущего ADR).

```python
# tests/test_compose_env_propagation.py — в SCHEDULER_CRITICAL_ENV (после RESUMMARIZE_TRIGGER_N):
    "RESUMMARIZE_MAX_AGE_DAYS",  # γ2/T7: scheduler-critical age-trigger knob; mirrored docker-compose.yml:78

# И ОБНОВИТЬ inline-комментарий 147-148 (снять противоречие с «FINAL / do NOT expand»), напр.:
#   # FINAL set as of 2026-07-19; γ2/T7 adds RESUMMARIZE_MAX_AGE_DAYS — scheduler-critical,
#   # not the DB/LLM expansion the clause forbids. Still: do NOT expand to unrelated DB/LLM keys.
```

**Инвариант правки:** compose-строка 78 УЖЕ существует → после добавления в set параметризованный `test_tg_parser_mirrors_scheduler_critical_env[RESUMMARIZE_MAX_AGE_DAYS]` **сразу зелёный** (в отличие от `SCHEDULER_DEFAULT_INTERVAL` в предыдущем B2, где compose-строку приходилось ДОБАВЛЯТЬ). Подтвердить: guard упал бы, если убрать `docker-compose.yml:78`.

> **Проверить перед правкой:** прочитать `docker-compose.yml:78` и убедиться, что строка `- RESUMMARIZE_MAX_AGE_DAYS=${RESUMMARIZE_MAX_AGE_DAYS:-0}` на месте. Per Вариант A (DECIDED §5.1) `<default>` **остаётся `:-0`** — compose-fallback не меняем, реальное `14` ставится в prod `.env`.

---

## 4. Scope — C3 (runbook fix: anchor-refresh + `restart`→`up -d` deploy-command bug, docs-only, опц.)

**C3a — stale line-anchors.** T7-раздел runbook (`F5C_DEPLOY_AND_WATCH.md:320-409`) уже полон и корректен по смыслу, но содержит **stale line-anchors** (drift после роста файлов):

| Место в runbook | Написано (stale) | Верно на 2026-07-20 |
|---|---|---|
| `:~326` | `settings.resummarize_max_age_days`, `settings.py:658` | `settings.py:1134` |
| `:~329` | `resummarization_service.py:165` (`run_for_channel` передаёт `max_age_days`) | `resummarization_service.py:208` |
| `:~330` | `_classify_trigger`, `resummarization_service.py:75` | `resummarization_service.py:112` |

Обновить эти три ссылки (docs-only, ноль поведения). Grafana/Prometheus-ссылки в runbook (`wave2_observation.json`, `alerts.yml`) — **файловые, без номеров строк** → менять не нужно.

**C3b — `restart`→`up -d` deploy-command bug (унаследован runbook'ом, тот же класс, что H1 §5.2).** Runbook в разделе «Как включить» (`F5C_DEPLOY_AND_WATCH.md:~359`) и в «Rollback» (`:~406`) использует `docker compose restart tg_parser`. Это **та же ошибка**, что была найдена self-review'ом в §5.2/§5.3: `restart` НЕ пересоздаёт контейнер → старый baked OS-env (`RESUMMARIZE_MAX_AGE_DAYS=0`) остаётся, интерполяция `${RESUMMARIZE_MAX_AGE_DAYS:-0}` перечитывается только на RE-CREATE, а pydantic (BUG-078: OS-env приоритетнее bind-mounted `/app/.env`) читает старый `0` → включение/rollback тихо no-op. Поменять оба вхождения на `docker compose up -d tg_parser` (или `--force-recreate` для жёсткой гарантии).

> Обе правки (C3a + C3b) — docs-only, ноль изменений в поведении кода. Если владелец предпочитает **не** трогать runbook в этой сессии — C3 можно отложить (не блокирует C1/C2), но C3b — фактический баг деплой-инструкции, стоит закрыть вместе с §5.2. Отметить как known-drift, если откладывается.

---

## 5. Scope — C2 (prod rollout `RESUMMARIZE_MAX_AGE_DAYS=14`) — ⚠️ GATED на явный GO

> 🚦 **НЕ включать без явного GO владельца** (cost-watch — риск cost-spike на первом тике, весь хвост stale-тем фитит age-предикат разом). Runbook `F5C_DEPLOY_AND_WATCH.md:322` уже помечает раздел как GATED. Session C **готовит** решение/выкат, но прод-мутацию env делает только по команде.

### 5.1 КАК ставится default — ✅ DECIDED: Вариант A (владелец, 2026-07-20)

**✅ РЕШЕНО (владелец, 2026-07-20): Вариант A.** Prod `.env` `RESUMMARIZE_MAX_AGE_DAYS=14`; compose-fallback **остаётся** `${RESUMMARIZE_MAX_AGE_DAYS:-0}` (`docker-compose.yml:78`, `<default>`=`:-0` не трогаем); var добавляется в `SCHEDULER_CRITICAL_ENV` (C1) — так значение из prod `.env` реально доходит до scheduler-синглтона через OS-env-mirror. Dev/CI/локально фича остаётся disabled (`0`, bit-for-bit MVP). Вариант B **отклонён** (decision-record ниже).

Оба варианта эквивалентны по эффекту «включить в проде», но отличаются по «single source of truth»:

- **Вариант A — ✅ CHOSEN (минимальный blast-radius):** compose-fallback остаётся `${RESUMMARIZE_MAX_AGE_DAYS:-0}` (`docker-compose.yml:78`); реальное значение ставится **явно в prod `.env`** (`RESUMMARIZE_MAX_AGE_DAYS=14`). Плюс: dev/CI/локально фича остаётся disabled (bit-for-bit MVP) — включение = осознанное prod-действие. Минус: prod-значение живёт вне репо (как и прочие prod-секреты/тюны).
  - **⚠️ Один `.env`, две роли (почему нужен RE-CREATE, не restart):** prod project-root `~/TG_parser/.env` — это ОДНОВРЕМЕННО (1) источник compose-интерполяции `${RESUMMARIZE_MAX_AGE_DAYS:-0}` (задаёт **OS-env** контейнера при create) И (2) bind-mounted `/app/.env`, который читает pydantic. По BUG-078 OS-env приоритетнее bind-mount, поэтому **фактически включает фичу именно OS-env-mirror** → значение подхватится только при **пере-создании** контейнера (`docker compose up -d`), а не при `restart` (см. §5.2 H1).
- **Вариант B — ❌ REJECTED (decision-record):** bump compose-fallback `:-0` → `:-14`. Плюс: «14 по умолчанию» задокументировано в коде. Минус: включает age-ветку **везде**, где `.env` не переопределяет (в т.ч. любой fresh deploy) — меняет MVP-дефолт глобально, шире, чем ops-enablement одного прод-инстанса. **Дополнительный минус (drift):** compose-fallback `:-14` начинает **расходиться** с code-default поля `settings.py:1135` (`resummarize_max_age_days` Field `default=0`) — два объявленных «дефолта» противоречат друг другу, и эффективный default зависит от пути запуска (docker-интерполяция даёт 14, а bare `python`/pytest никогда не видит compose → получает 0). Именно поэтому B отклонён в пользу A.

### 5.2 Deploy steps (по GO; canonical путь из runbook)

Полная процедура — [`F5C_DEPLOY_AND_WATCH.md` §T7](../runbooks/F5C_DEPLOY_AND_WATCH.md) «Как включить (когда будет go)». Кратко:

1. **Pre-flight cost baseline** (снять ДО включения — с чем сравнивать):
   ```promql
   sum(increase(tg_resummarize_total[24h])) by (channel_id, trigger)     # trigger="age" ≈ 0 (knob off)
   sum(increase(tg_resummarize_tokens_total[24h])) by (channel_id, token_type)
   ```
   + SQL-прикидка размера хвоста stale-тем (см. runbook §T7 «Pre-flight»).
2. **Включить env** (Вариант A): `RESUMMARIZE_MAX_AGE_DAYS=14` в prod `~/TG_parser/.env` → `docker compose up -d tg_parser` (при необходимости `--force-recreate`) — **НЕ `restart`** (без миграции, без рестарта DB).
   ```bash
   # ~/TG_parser/.env: RESUMMARIZE_MAX_AGE_DAYS=14
   docker compose up -d tg_parser          # пере-создаёт контейнер → перечитывает интерполяцию
   # docker compose up -d --force-recreate tg_parser   # жёсткая гарантия
   ```
   > ⚠️ **Почему `up -d`, а не `restart` (H1, тот же BUG-078-класс, ради которого делается C1):** значение доходит до воркера через compose-интерполяцию `${RESUMMARIZE_MAX_AGE_DAYS:-0}` (`docker-compose.yml:78`), которая запекается в **OS-env** контейнера в момент CREATE. `docker compose restart` не пересоздаёт контейнер → старый baked OS-env (`=0`) сохраняется; а pydantic по BUG-078 берёт OS-env приоритетнее bind-mounted `/app/.env` → значение `14` из `.env` **молча игнорируется**, фича остаётся DORMANT. Только `docker compose up -d` (re-create при изменившейся интерполяции) реально включает knob.
3. **Grafana/Prometheus provisioning-recreate — если C1/C2 меняли provisioned-файлы.** Панели/алерты УЖЕ provisioned и задеплоены (если прод на актуальном `main`); отдельная правка dashboard/alerts в session C **не планируется**. НО: этот проект **force-recreate**'ит Prometheus на изменение rule-файла (прецедент из ingestion-observability START_PROMPT §7; Wave 1 step 5 / `wave1_step4.yaml` — аналогичный шаг для Grafana). Если сессия C всё же тронет `docker/prometheus/alerts.yml` или `docker/grafana/**`, то **обязателен** force-recreate соответствующего контейнера, иначе provisioning не перечитается:
   ```bash
   docker compose up -d --force-recreate prometheus   # при правке alerts.yml / recording rule
   docker compose up -d --force-recreate grafana      # при правке dashboards/** или provisioning/**
   ```
   Если C1 (только `SCHEDULER_CRITICAL_ENV` + prod `.env`) и НЕ трогает provisioned-файлы — recreate Prometheus/Grafana **не нужен**. Но сам `tg_parser` для env-изменения (Вариант A) всё равно нужно поднимать через `docker compose up -d tg_parser` (re-create), **не** `restart` (см. H1 в шаге 2).
4. **Watch 24–48 ч** (особенно ПЕРВЫЙ тик — там вскрывается накопленный хвост): раздел § «Мониторинг» ниже.

### 5.3 Watch / acceptance (observability-петля — уже provisioned)

- **Grafana:** dashboard `TG_parser — Wave 2 Observation (F5-B / T7)` (uid `tg-parser-wave2-observation`), row «T7 F5-C P2» — per-channel token cost (rate + cumulative), trigger split counter-vs-age, **age-trigger 14d share vs 50% gate**.
- **Gate signal:** `tg:resummarize_age_trigger:ratio14d` (recording rule) — green `< 0.5`, red `>= 0.5` = age-триггер даёт большинство re-summarize → **сигнал удлинить `RESUMMARIZE_MAX_AGE_DAYS`, НЕ инцидент**. Alert `ResummarizeAgeTriggerGateF5CPhase2` (info, `for:12h`).
- **Acceptance после включения:** `age`-доля стабильно `< 50%` (gate зелёный) И per-channel token-cost в пределах baseline + ожидаемого хвоста. Cost-spike-митигация — существующий triple-cap (`RESUMMARIZE_MAX_PER_TICK=10` / `_MAX_DURATION_S=60` / `_MAX_TOKENS_PER_TICK=50000` per channel/tick) + fair-scheduling `ORDER BY new_items DESC, updated_at DESC`: per-tick потолок cost knob НЕ повышает, только растягивает backlog на несколько тиков.
- **Rollback (мгновенный):** `RESUMMARIZE_MAX_AGE_DAYS=0` в `.env` → `docker compose up -d tg_parser` (re-create, **не** `restart` — та же H1-причина: `restart` сохранит baked OS-env `14`, откат молча не применится); counter-триггер MVP работает как раньше (bit-for-bit). Кода/миграции откатывать не нужно.

---

## 6. Acceptance criteria (Definition of Done)

**C1 (обязательно, code+test):**
- [ ] `RESUMMARIZE_MAX_AGE_DAYS` добавлен в `SCHEDULER_CRITICAL_ENV` (`tests/test_compose_env_propagation.py`) с поясняющим inline-комментарием.
- [ ] **Inline-комментарий 147-148 «FINAL curated set / do NOT expand» ОБНОВЛЁН** (M1): зафиксировано, что `RESUMMARIZE_MAX_AGE_DAYS` — легитимное scheduler-critical расширение, которое запрет «unrelated DB/LLM keys» не покрывает (комментарий больше не противоречит 13-му члену set).
- [ ] Параметризованный `test_tg_parser_mirrors_scheduler_critical_env[RESUMMARIZE_MAX_AGE_DAYS]` зелёный (compose-строка 78 уже есть).
- [ ] Подтверждено (ручной negative-check при ревью): убрать `docker-compose.yml:78` → guard-тест падает на этом var.
- [ ] Compose-`<default>` на строке 78 = `:-0` (Вариант A DECIDED §5.1 — fallback НЕ трогаем; реальное `14` живёт в prod `.env`).

**C2 (gated ops — только по GO):**
- [ ] Вариант A зафиксирован (§5.1 DECIDED 2026-07-20) — отражён в отчёте/PR-описании (compose `:-0`, prod `.env`=14, var в `SCHEDULER_CRITICAL_ENV`).
- [ ] (по GO) prod `.env` содержит `RESUMMARIZE_MAX_AGE_DAYS=14`; `tg_parser` **пере-создан через `docker compose up -d tg_parser`** (re-create, НЕ `restart` — H1); baseline снят ДО; первый тик отвотчен.
- [ ] (по GO) age-gate зелёный (`ratio14d < 0.5`) через ≥24–48 ч, per-channel cost в пределах baseline + хвост.

**C3 (docs, опц.):**
- [ ] **C3a** — три stale line-anchor в `F5C_DEPLOY_AND_WATCH.md:~326-330` обновлены (`settings.py:1134`, `resummarization_service.py:208`, `resummarization_service.py:112`).
- [ ] **C3b** — `docker compose restart tg_parser` в runbook (`F5C_DEPLOY_AND_WATCH.md:~359` включение, `:~406` rollback) заменён на `docker compose up -d tg_parser` (H1-класс, тот же баг, что §5.2).

**Общее:**
- [ ] Поведение pipeline / кода фичи байт-в-байт НЕ изменено (C1 — только test-set; фича-код read-only reference). `RESUMMARIZE_MAX_AGE_DAYS=0` остаётся bit-for-bit MVP до prod-rollout.
- [ ] ЗК/quality gate (§7) зелёный.

---

## 7. ЗК / Quality gate (перед объявлением готовности)

```bash
# lint + format (нормативно)
uv run ruff check .
uv run ruff format --check .

# default suite (integration-фильтр; PG-тесты пропускаются)
uv run pytest -q

# PR standard — обязателен, т.к. трогаем compose-parity guard + (опц.) storage-adjacent тесты
TEST_POSTGRES=1 uv run pytest -q
```

Прицельно проверить затронутые/смежные тесты:
- `tests/test_compose_env_propagation.py` — B2-parity (новый param `RESUMMARIZE_MAX_AGE_DAYS`).
- Существующие F5-C тесты (регрессия, поведение не должно измениться):
  - `tests/test_f5c_resummarization_service.py`, `tests/test_f5c_scheduler_hook.py` (hook/service).
  - `tests/test_resummarize_metrics.py` — channel_id + trigger label (`test_trigger_age_label_recorded`, `test_classify_trigger_age`, `test_tokens_counter_carries_channel_label`).
  - `tests/test_f5c_topic_card_repo.py` (**`TEST_POSTGRES=1`**) — age-триггер + partial-index: `test_max_age_days_zero_is_counter_only`, `test_time_based_includes_stale_below_threshold`, `test_time_based_excludes_when_no_new_items` и др.
- **Partial-index invariant:** time-based OR-ветка ДОЛЖНА оставаться под `idx_topic_cards_resummarize_candidates` (partial, `WHERE new_items_since_last_summary > 0`). Top-level предикат `new_items_since_last_summary > 0` уже сохранён (`topic_card_repo.py:272`); эта задача его НЕ меняет — но при любом касании candidate-query перепроверить query-shape (EXPLAIN — index scan, не seq scan).
- **Grafana dashboard тест — отсутствует.** `tests/test_grafana_alerting_provisioning.py` валидирует ТОЛЬКО alerting-provisioning `wave1_step4.yaml`, НЕ dashboard-JSON (`wave2_observation.json`). Значит правки dashboard-JSON никакой pytest не покрывает (прецедент realign — `8e943d5`). Session C дашборд трогать не планирует; если тронет — валидировать вручную (JSON-parse + Grafana UI после force-recreate).

> promtool (alerts.yml) — **ручной** gate (не в CI/pytest). Нужен ТОЛЬКО если session C тронет `docker/prometheus/alerts.yml` (не планируется):
> ```bash
> promtool check rules docker/prometheus/alerts.yml
> promtool test rules docker/prometheus/alerts_test.yml
> ```

Плюс: self-review диффа + (по желанию владельца) прогон **Bugbot** по локальным изменениям перед просьбой о коммите.

---

## 8. Out of scope / decisions

**Out of scope:**
- Изменение логики candidate-отбора / `_classify_trigger` / scoring — фича-код read-only.
- Построение Grafana-панелей / recording rule / gate alert — **уже отгружено** (`f0a1512`, `5eec247`); session C их только использует/описывает, не пересоздаёт.
- Изменение MVP-дефолта фичи глобально (Вариант B §5.1) — **отклонён** владельцем (2026-07-20); compose-fallback остаётся `:-0`, dev/CI/pytest — disabled bit-for-bit.
- Правки `pyproject.toml` / `requirements.txt` / `docs/methodology/**`.
- Per-topic label на метриках (cardinality); прод-rollout других F5-C knobs.
- Prometheus/Grafana force-recreate как самостоятельный шаг — нужен ТОЛЬКО при правке provisioned-файлов (не планируется в C1).

**Decisions:**
1. **Prod-default механизм (§5.1): ✅ DECIDED — Вариант A (владелец, 2026-07-20)** — prod `.env`=14, compose-fallback `:-0` не трогаем, var в `SCHEDULER_CRITICAL_ENV`. Вариант B отклонён (global MVP-default shift + `settings.py:1135`(0)-vs-compose(`:-14`) drift). ⇒ `<default>` в `docker-compose.yml:78` = `:-0`.
2. **Точное значение: 14** (согласовано с #15 «>14 days») — DEFAULT для GO; при большом хвосте stale-тем допустимо поднять (21/30) по SQL-прикидке из runbook §T7 pre-flight (решение при GO).
3. **C3 (runbook fix: anchor-refresh C3a + `restart`→`up -d` C3b) — делать в этой сессии или отложить как known-drift?** (открытый вопрос владельцу.)
4. **GO на C2 prod-rollout** — сейчас (после C1) или отдельным окном под cost-watch? (открытый вопрос владельцу.)

---

## 9. Ссылки

- **Source-of-truth γ2:** [`DRAFT_NEXT_CONTRACT_POST_WAVE2_2026-06-18.md`](DRAFT_NEXT_CONTRACT_POST_WAVE2_2026-06-18.md) §2 Track γ (γ2) / §3; [`PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md`](PLAN_WAVE2_DOGFOOD_QUALITY_2026-06-14.md) §4 T7 (#10 per-channel metric, cardinality note ~10–13 каналов → fallback `"-"`).
- **Runbook (включение + watch + rollback, УЖЕ содержит T7-раздел):** [`docs/runbooks/F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md) §T7 (:320-409).
- **Commits:** `b294b05` (Wave-2 combo — F5-C P2 freshness + per-channel metric, 2026-06-14); `f0a1512` (Wave 2 observability — per-channel token cost + counter/age trigger label + Grafana dashboard + gate alert); `5eec247` (T7 14d-freshness parity с F5-B 7d gate); `8e943d5` (прецедент Grafana provisioning test realign).
- **B2/BUG-085 прецедент (тот же guard-механизм):** [`START_PROMPT_TECHDEBT_B_INGESTION_OBSERVABILITY_2026-07-19.md`](START_PROMPT_TECHDEBT_B_INGESTION_OBSERVABILITY_2026-07-19.md) §4 (B2 curated set + BUG-078 gotcha + force-recreate deploy step §7); [`BUG_LOG.md`](BUG_LOG.md) BUG-085 / BUG-078.
- **House-format reference:** [`START_PROMPT_FIX_F11_SEMANTIC_AVAILABLE_GUARD_T6_2026-06-15.md`](START_PROMPT_FIX_F11_SEMANTIC_AVAILABLE_GUARD_T6_2026-06-15.md).
- **ADR:** [`0006`](../adr/0006-karpathy-like-living-kb-principles.md) (#6 «turn a knob → watch its cost»; #7 graceful). Tracking issue Phase 2 — **#15** (item #4 time-based триггер, #10 per-channel metric).
- **Convention:** [`AGENTS.md`](../../AGENTS.md); [`docs/quality/AGENT_PLAYBOOK.md`](../quality/AGENT_PLAYBOOK.md); [`tests/README.md`](../../tests/README.md); [`WORKFLOW_REMEDIATION_SESSIONS_AGREEMENTS_2026-07-07.md`](WORKFLOW_REMEDIATION_SESSIONS_AGREEMENTS_2026-07-07.md) (commit/PR — только по запросу; PR = merge-commit + `--delete-branch`; ЗК = ruff + pytest default + `TEST_POSTGRES=1`).
