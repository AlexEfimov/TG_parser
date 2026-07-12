# WORKFLOW — Соглашения по remediation-сессиям (S0–S7)

**Тип документа:** process agreements (нормативно для этой серии работ).
**Дата:** 2026-07-07 · **Статус:** `active`.
**Основание:**
- Отчёт ревью: [`CODE_REVIEW_PROCESSING_ALGORITHMS_FABLE5_2026-07-07.md`](CODE_REVIEW_PROCESSING_ALGORITHMS_FABLE5_2026-07-07.md)
- План сессий: [`PLAN_REMEDIATION_SESSIONS_PROCESSING_ALGORITHMS_2026-07-07.md`](PLAN_REMEDIATION_SESSIONS_PROCESSING_ALGORITHMS_2026-07-07.md)
- Промпт-стандарт code-review: [`START_PROMPT_FABLE5_CODE_REVIEW_PROCESSING_ALGORITHMS_2026-07-07.md`](START_PROMPT_FABLE5_CODE_REVIEW_PROCESSING_ALGORITHMS_2026-07-07.md)

Цель документа — единый источник правды по процессу устранения находок ревью. К нему обращаемся в каждой сессии S1–S7.

---

## 1. Общая рамка

- Устраняем находки code-review по плану **S1 → S7** строго последовательно.
- **Каждая сессия S1–S7 выполняется в отдельном окне** (отдельный Cursor-инстанс / отдельный агент). Координация, подготовка промптов, ревью и baseline — в основном окне.
- Перед S1 выполняется **S0 — снятие базовых метрик (read-only)**.
- Каждая сессия трассируется к находкам/оптимизациям отчёта (F-01…F-18, O-1…O-10, §6.x). Новых находок не вводим.

## 2. Git-стратегия

- **Ветка на сессию**, например `fix/S1-resummarize-text`.
- Изменения оформляются **PR**.
- **Merge в `main` — только после зелёного bugbot** (и зелёных тестов).
- Base-ветка — `main`.
- Коммит/пуш — только в рамках согласованного цикла сессии (см. §5), не раньше зелёного статуса.

## 3. Каденция деплоя

- **S1–S3** выкатываются как **один безопасный блок** (низкий риск, поведенческая эквивалентность / чистые баг-фиксы).
- **S4 и S5** — деплоятся **по отдельности**, каждая с:
  - обязательной **read-only симуляцией** (в стиле ADR-0010) до включения,
  - **наблюдением метрик** после включения (сдвиг состава `TopicLink` / покрытия тем).
- S6, S7 — по готовности; каденцию уточняем по ходу.
- **Определение «деплоя» и план отката** фиксируем в начале соответствующей сессии (окружение, docker-стек, rollback).

## 4. S0 — Baseline (read-only)

До S1 снимаем точку отсчёта, чтобы измерять эффект S1/S3/S4/S5 и ловить регрессы:

- Токены по стадиям (processing, topicization, discover, resummarize) — input/output.
- Длительность тика планировщика.
- Latency RAG-запроса.
- Счётчики дедупа (exact / near-dup) и processing-вызовов.

Источник — существующие Prometheus-метрики / инструментирование и логи. Строго read-only. Если живой стек/эндпоинт недоступен — фиксируем точные имена метрик и запросы + шаблон снапшота для последующего снятия.

## 5. Цикл каждой сессии Sn

1. **Стартовый промпт** — по образцу `START_PROMPT_SPRINT_*`, в стиле Fable 5 (цель + контекст + ограничения, а не длинный сценарий). Включает: scope / out-of-scope и конкретные файлы из плана, критерий приёмки (какая метрика/поведение доказывает успех).
2. **Self-review промпта** — отдельным агентом со **свежим контекстом**.
3. **Реализация** — в отдельном окне.
4. **Тестирование:**
   - для баг-находок — сначала **падающий тест (red → green)**;
   - прогон в нужных режимах из [`tests/README.md`](../../tests/README.md): *default* (`pytest -q`), *PR standard* (`TEST_POSTGRES=1`), при E2E — *max local* (`TEST_POSTGRES=1 TEST_TESTCONTAINERS=1`);
   - именованные тест-файлы — из раздела «Test strategy» соответствующей сессии плана.
5. **Self-review тестов** — отдельным агентом со свежим контекстом.
6. **Self-review кода + bugbot** — отдельным агентом со свежим контекстом; bugbot по изменениям ветки.
7. **Обновление документации** — статус закрытых находок в [`BUG_LOG.md`](BUG_LOG.md) (в S7 — диспозиции Low-находок) как часть deliverable.
8. **Зелёные тесты + зелёный bugbot** → commit + push → PR → merge в `main` → деплой по каденции §3.

## 6. Ревью — принцип

- Все ревью (промпт, тесты, код) делаются **агентами со свежим контекстом**, а не той же реализацией, которая писала артефакт: независимый ревьюер ловит больше (подтверждено гайдами Anthropic и практикой этой серии). Bugbot — обязательный дополнительный гейт.

## 7. Ограничения по scope

- **S3** делаем **без изменения контрактов и миграций**: content-hash считаем на лету. Если потребуется персистентное raw-hash поле в схеме/контрактах — выносим отдельным согласованным решением, не внутри сессии.
- Не нарушаем `docs/contracts/**` (JSON Schema) и accepted ADR.
- Архитектурные альтернативы §6.1 / §6.4 / §6.5 — вне плана, отдельными будущими решениями.

## 8. Статус-трекинг серии

| Сессия | Находки | Статус |
|--------|---------|--------|
| S0 | baseline | done — [`S0_BASELINE_PROCESSING_METRICS_2026-07-07.md`](S0_BASELINE_PROCESSING_METRICS_2026-07-07.md) |
| S1 | F-02 (+O-9a) | **merged** — PR #299 → `main` `6a07652` (bugbot clean, CI green) |
| S2 | F-03/F-07/F-08 | **merged** — PR #300 → `main` `39fddff` (bugbot clean, CI green) |
| S3 | F-01/F-09 | **merged** — PR #301 (bugbot clean, CI green) |
| S4 | F-04/F-05 | **deployed** — PR #304 → `b1e4c7b` (2026-07-11); threshold 0.32; 2807 links post-rebuild ([`S4_TOPIC_EMBEDDING_THRESHOLD_SIMULATION_2026-07-11.md`](S4_TOPIC_EMBEDDING_THRESHOLD_SIMULATION_2026-07-11.md)) |
| S5 | F-10 | **merged** — PR #305 → `main` `dffd767` (bugbot clean, CI green); read-only симуляция — [`S5_TOPK_ASSIGN_SIMULATION_2026-07-11.md`](S5_TOPK_ASSIGN_SIMULATION_2026-07-11.md); дефолт `topk_denom` (knob `topicization_assign_keyword_aggregation`) |
| S6 | F-12/F-13 | **merged** — PR #306 → `main` `1c00ee1` (bugbot clean, CI green); pure post-processing, no simulation gate (PLAN §S6) |
| S7 | O-9b + Low-диспозиции | pending |

Обновляется по мере прохождения сессий.

**Блок S1–S3 (деплой одним блоком, §3):** runbook деплоя/отката — [`../runbooks/S1_S3_DEPLOY_AND_WATCH.md`](../runbooks/S1_S3_DEPLOY_AND_WATCH.md). Rollback-цель (pre-block `main`) — `f985b9c`. Блок без миграций и без изменений `docs/contracts/**` (§7).

**P2 S3 delta watch (2026-07-11):** billing-clean 24h снят; вердикт `S3 effect: PARTIAL`, `S4: GO`. Снапшот — [`S0_BASELINE_PROCESSING_METRICS_2026-07-07.md`](S0_BASELINE_PROCESSING_METRICS_2026-07-07.md) §5; executive summary — [`S3_DELTA_WATCH_2026-07-11.md`](S3_DELTA_WATCH_2026-07-11.md). Forward watch 48–72h рекомендован для накопления pre-LLM hit-rate.

**S5/S6 post-deploy (2026-07-12) — `deployed, GO`.** Prod пре-деплойный HEAD фактически был `dffd767` (S5 уже жил на проде, не `b1e4c7b`/S4) — этим выкатом реально доехал только **S6** (`1c00ee1`). Prod ff-обновлён до `1f9c656`; образ `tg_parser` **пересобран из исходников** (`docker compose build`, т.к. image билдится локально, не тянется из registry) + recreate `tg_parser/mcp/tg_bot` — все healthy, `/health` ok, лог чистый (без трейсбеков). **S6-проверка чистая:** `topicization_full_run_chunk_failed_total{reason="malformed_merge"}` = 0 samples, `failed merge chunk` в логах нет. **S5 coverage-baseline и «боевая» S6-merge под нагрузкой** заполнятся на ближайшем часовом тике (~13:18 UTC; scheduler cadence 3600s) — ручной trigger не форсировали (требует прод-API-ключ + реальная LLM-нагрузка).
- **S6** (lightweight, без watch-band, PLAN §S6): full-run на dev-канале → нет `failed merge chunk` на бывших string-ID кейсах; `topicization_full_run_chunk_failed_total{reason="malformed_merge"}` не растёт; merged topic count ≥ pre-fix; coverage ≥ S0.
- **S5** (деплой отдельно + metric watch, §3): сдвиг доли Phase-1-assign / discover-вызовов и покрытия тем (дефолт `topk_denom`; knob `topicization_assign_keyword_aggregation=mean` — мгновенный откат). Sim-предсказание — [`S5_TOPK_ASSIGN_SIMULATION_2026-07-11.md`](S5_TOPK_ASSIGN_SIMULATION_2026-07-11.md).
- **Pre-deploy live baseline (read-only через MCP, 2026-07-12 ~12:03Z):** 13 каналов active, processed≈raw (~99.7%: e.g. `mediamedics` 11124/11127, `Docma_ru` 3210/3234); topics_count популированы (mediamedics 259, profendocrinologist 188, Lab4health 172); `list_channels.coverage_percent=0.0` по всем — это отдельное непопулированное поле обзора, не T1-метрика (реальный processing-coverage ≈ raw). Per-tick `degraded (fail_ratio=100% на N=1–24)` на части каналов — **пред-существующий** BUG-082/BUG-083 (concurrency-budget + refusal poison-pill), не связан с S5/S6. Снапшот — точка отсчёта для post-deploy diff.
