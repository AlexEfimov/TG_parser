# SESSION — F5-C minimal refusal-fallback experiment (C)

**UTC:** 2026-08-05T21:43Z–21:46Z · **Тип:** ops one-shot (без записи knobs в prod `.env`, без re-create)  
**План:** минимальный вариант — `docker exec -e` + точечный SQL у одной темы.

## LOCK

| # | Решение |
|---|---|
| D-1 | да |
| D-2 | `rag` → `openai` / `gpt-4.1` только через `-e` |
| D-3 | (a) SQL точечный |
| D-4 | нет (разовый CLI) |
| D-5 / D-6 / D-7 | отложены до owner GO после C |

## Pre-check resolve (`-e`)

```
stage= 'rag'  primary= anthropic claude-sonnet-4-6  fallback= openai gpt-4.1
ACCEPT_OK
```

UTC snapshot start: `2026-08-05T22:43:45Z` (local wall; container timestamps below in Z).

## Pre-UPDATE `metadata_json` (rollback snapshot)

Topic: `topic:tg:labdiagnostica_logical:comment:8992`

```json
{"algorithm":"llm_clustering","input_scope":{"channel_id":"labdiagnostica_logical","mode":"full_history"},"model_id":"claude-sonnet-4-20250514","parameters":{"max_anchors":3,"min_cluster_anchors":2,"min_cluster_score":0.6,"min_singleton_length":300,"min_singleton_score":0.75,"temperature":0.0},"pipeline_version":"v1.0","prompt_id":"sha256:14e4721863b067a1","prompt_name":"topicization_v1","resummarize_llm":"openai/gpt-4o-mini","resummarize_prompt_version":"1.0.0","resummarize_refusal_at":"2026-07-25T14:14:56.774932+00:00","resummarize_refusal_count":5,"resummarize_refusal_llm":"anthropic/claude-sonnet-4-6","resummarize_refusal_until":"2026-08-10T14:14:56.774932+00:00","resummarize_run_at":"2026-06-20T06:03:09.393179+00:00","resummarize_version_no":2,"topicization_run_id":"run_20260419_092042"}
```

## SQL

Сняты только `resummarize_refusal_until` и `resummarize_refusal_count`. Provenance `_at` / `_llm` оставлены до commit-пути.

## CLI

```bash
docker exec \
  -e RESUMMARIZE_REFUSAL_FALLBACK_STAGE=rag \
  -e RAG_LLM_PROVIDER=openai \
  -e RAG_LLM_MODEL=gpt-4.1 \
  tg_parser tg-parser topic resummarize \
  topic:tg:labdiagnostica_logical:comment:8992
```

**Stdout (дословно по статусу):**

- `f5c_resummarize_fallback_ok` `stage=rag` `provider=openai` `model=gpt-4.1` @ `2026-08-05T21:46:19.668682Z`
- `status: ok`
- `new_version: 3`
- `tokens: 2922`
- `duration: ~7.38s`
- `EXIT=0`

## Post-verify

| Проверка | Результат |
|---|---|
| `f5c_resummarize_fallback_ok` openai/gpt-4.1 | да (CLI stdout) |
| `topic_card_versions` | snapshot v2 записан @ `2026-08-05 21:46:12+00` (предыдущий summary); карточка теперь v3 |
| `metadata.resummarize_llm` | `openai/gpt-4.1` |
| маркеры `resummarize_refusal_*` | отсутствуют (commit вычистил) |
| `last_summarized_at` | `2026-08-05 21:46:19.849297+00` |
| `new_items_since_last_summary` | `0` → тема вышла из age-кандидатов минимум на `MAX_AGE_DAYS=21` |
| prod `.env` | `RESUMMARIZE_REFUSAL_FALLBACK_STAGE` count=0; `RAG_LLM_*` count=0 (не трогали) |

## Rollback knobs

No-op: в `.env` ничего не писали. Scheduler не re-create.

## Вердикт

**C успешен:** Anthropic refusal обойдён fallback'ом `openai/gpt-4.1`; poison-pill тема вылечена разовым CLI.

## Решения после C

- **D-4 — нет.** Постоянный cross-vendor fallback потребовал бы второго chat-LLM аккаунта; это против модели single-operator / self-host (сегмент A1). `RESUMMARIZE_REFUSAL_FALLBACK_STAGE` остаётся опцией, выключенной по умолчанию.
- **Шаг B — не нужен.** Критерий входа §5.1 не выполнен: тема вылечена, слот тика не занимает.
- **Шаг A — исполнен** (см. ниже). D-5 = **V1** (gate-алерт снят), D-6 = recording rule + info-alert + runbook.

---

# Шаг A — гигиена T7-gate (2026-08-06)

## Что изменено

| Файл | Правка |
|---|---|
| `docker/prometheus/alerts.yml` | `ratio14d` без `refusal_cooldown` (обе части); alert `ResummarizeAgeTriggerGateF5CPhase2` **снят**; добавлены `tg:resummarize_refusal_cooldown:count24h` + `ResummarizeRefusalCooldownPoisonPill` (info, `>=12`/24h/канал, `for: 6h`) |
| `docker/grafana/dashboards/wave2_observation.json` | панели age-share → observation-only (снят красный порог 0.5), убран `MAX_AGE_DAYS=14`, перечень outcome'ов приведён к коду |
| `docs/runbooks/F5C_DEPLOY_AND_WATCH.md` | §T7 мониторинг/acceptance переписаны; добавлен раздел «что делать, если `refusal_cooldown` растёт»; исправлено `gpt-4o-mini` → живой `anthropic/claude-sonnet-4-6`; `=14` помечен historical |
| docstrings | `resummarize_topic` и MCP `force_resummarize` — добавлены `refusal` / `refusal_cooldown` (+ `db_error` в MCP) |
| `CHANGELOG.md`, `DELTA_T7_VERDICT`, `BUG_LOG` | записи о решении |

## Acceptance (снято 2026-08-06T07:50:58Z, прод read-only)

| Проверка | Результат |
|---|---|
| `promtool check rules` | SUCCESS. **30 правил на HEAD → 31 после правки** — мутационное доказательство, что файл действительно изменён |
| pre/post `ratio14d` (одни и те же прод-данные) | старое выражение **0.9887** → новое **0.8824**. Значения различаются ⇒ acceptance непустой |
| Компенсирующий сигнал 24h | `labdiagnostica_logical` = **14** (≥ порога 12) — это остаток окна ДО лечения (тик ~1/ч × ~14 ч); подтверждает, что порог достижим живым poison-pill'ом |
| Тот же сигнал за 14d (сырое) | **320** — ненулевое |
| `labdiagnostica_logical` за 10 ч после лечения | `refusal_cooldown` = **0**, `ok/age` = **1** ⇒ сигнал самогасится после лечения, как и задумано окном 24h |
| `rg 'MAX_AGE_DAYS=14' docker/ docs/runbooks/` | было 7 → в `docker/` **0**; в runbook остался только помеченный historical блок |
| `pytest tests/test_metrics_instrumentation.py` | 3 passed |
| `ruff check` по изменённым .py | clean |

## Self-review шага A (адверсариальный проход, 2026-08-06)

Bugbot по diff'у ветки — **чисто**. Собственный проход нашёл три вещи; все три исправлены до PR-ревью, а не замолчаны.

| # | Находка | Что стало |
|---|---|---|
| **A-1** | **Числа, которых никто не мерил.** В `alerts.yml`, CHANGELOG, runbook и DELTA_T7 я написал «честная доля ≈0.90». Это **арифметика по снапшоту 2026-08-05** (35/39), а не замер. Живой замер того же выражения 2026-08-06 дал **0.8824**, и продуктивный mix за сутки съехал (age `ok` ≈28, не ≈35). Ровно тот класс, что и протухшее `MAX_AGE_DAYS=14`, который эта же правка вычищает. | Везде проставлено измеренное значение **с датой замера**. Историческая запись в `DELTA_T7_VERDICT` L164 (≈0.90 на 2026-08-05) **не тронута** — это наблюдение на свою дату (прецедент BUG-089 § Artifacts); расхождение оформлено отдельной датированной строкой. |
| **A-2** | **Неверная дата снятия алерта.** Писал «СНЯТ 2026-08-05» — шаг C был 08-05, а шаг A сделан **08-06 UTC**. Дата в комментарии правила и в описаниях панелей ведёт оператора не к тому дню при разборе. | Исправлено на 2026-08-06 в `alerts.yml`, обеих панелях, CHANGELOG и runbook. Датированные наблюдения про сам poison-pill (≈330/365 на 2026-08-05) оставлены как есть — они верны на свою дату. |
| **A-3** | **Непроверенная семантика `outcome!="refusal_cooldown"`.** В PromQL `!=` матчит и серии, **у которых метки нет вовсе** (пустая строка ≠ значению). Если бы часть `tg_resummarize_total` писалась без `outcome`, такие серии молча попали бы в обе части дроби. | Проверено живьём: `count(tg_resummarize_total) by (outcome)` возвращает только `{outcome="ok"}` и `{outcome="refusal_cooldown"}` — серий без метки нет. Риск снят фактом, а не рассуждением. |

Отдельно проверено и **не** является проблемой:

- **Ложное срабатывание нового алерта сразу после деплоя.** Сейчас `count24h` по `labdiagnostica_logical` = 14 (≥ порога 12) — это хвост окна ДО лечения темы. Условию нужно держаться **непрерывно 6 ч** (`for: 6h`), а значение падает ~1/час и опустится ниже 12 примерно к 09:50Z. Деплой после этого момента не даст ложного firing; деплой раньше — максимум короткий info-алерт по уже вылеченной теме.
- **Деление на ноль после исключения cooldown.** Знаменатель — глобальная сумма по всем каналам, а не по одному, так что обнулиться он может только если вся система целиком в карантине. В этом случае получается NaN (нет сэмпла) — та же семантика «no data», что была до правки; алерта поверх дроби больше нет, паника невозможна.
- **Порядок правил в группе.** Recording rule объявлена **до** алерта, который её читает: внутри группы Prometheus вычисляет правила последовательно.

## Деплой шага A (2026-08-06, выполнен)

PR [#370](https://github.com/AlexEfimov/TG_parser/pull/370) смержен в `main` (merge-commit `5ff7475`, CI зелёный на `ef1a0b9`).

**По дороге вскрылась ловушка — [BUG-090](BUG_LOG.md).** Задокументированная процедура (`git pull` → `promtool check` → hot-reload) деплоила **ничего**, и все шаги при этом рапортовали успех:

| Шаг | Наблюдение |
|---|---|
| `git pull --ff-only` на проде | HEAD `5ff7475`, на хосте 3 вхождения `resummarize_refusal_cooldown` |
| `promtool check rules /etc/prometheus/alerts.yml` **внутри контейнера** | `SUCCESS: 30 rules` — **старое** число; проверка валидировала устаревший файл |
| `docker exec … grep -c resummarize_refusal_cooldown /etc/prometheus/alerts.yml` | **0** при 3 на хосте ⇒ контейнер держит старый inode |
| `docker compose up -d prometheus` | `Container tg_parser_prometheus Running` — **не** пересоздал, в контейнере всё ещё 0 |
| `docker compose up -d --force-recreate prometheus` | `Recreated` / `Started`; в контейнере 3, `SUCCESS: 31 rules`, `StartedAt=2026-08-06T08:07:08Z` |

Причина: bind-mount **одиночного файла** привязан к inode, а `git pull` файл не правит на месте — он его пересоздаёт. Родственник BUG-078. Мой собственный текст в PR утверждал обратное («BUG-078 здесь не применяется, hot-reload достаточно») — утверждение было структурно логичным и фактически неверным; исправлено в runbook § T7.

**Post-deploy verify (прод, 2026-08-06):**

| Проверка | Результат |
|---|---|
| pre/post `ratio14d` | **0.9887** (08:06:09Z, старое правило) → **0.8824** (08:07:38Z, новое) — значения различаются |
| `ResummarizeAgeTriggerGateF5CPhase2` | отсутствует в `/api/v1/rules`; из `ALERTS` ушёл после прокрутки lookback-окна (проверено в 08:13:31Z — пусто) |
| `tg:resummarize_refusal_cooldown:count24h` | загружена, отдаёт `labdiagnostica_logical = 14` |
| `ResummarizeRefusalCooldownPoisonPill` | `alertstate="pending"` — ожидаемо: значение 14 ≥ 12, но `for: 6h`, а счётчик падает ~1/час и уйдёт ниже порога ~09:50Z ⇒ до `firing` не дойдёт. Это остаток окна ДО вчерашнего лечения темы, а не новый poison-pill |
