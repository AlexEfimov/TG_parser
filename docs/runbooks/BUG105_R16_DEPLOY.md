# Runbook — BUG-105: supporting по решению G и пересборка бандлов без LLM (R16)

**Создан:** 2026-11-25 (R16, этап C). **Статус: ВЫПОЛНЕНО** по GO владельца. Деплой — 2026-11-20 21:48Z, merge `26dd811` ([PR #459](https://github.com/AlexEfimov/TG_parser/pull/459)), образ `d90debb1ebb9`. Пересборка бандлов всех 18 каналов — 2026-11-22 (AgeManagment) и 2026-11-23 (остальные 17). Итог — **3.67** темы на документ против 4.90 в базе. Тем на потолке supporting по формуле — 734 вместо 1 377.

**Scope и решения:**
- [`START_PROMPT_R16_TOPICIZATION_SUPPORTING_NOISE_2026-10-08.md`](../notes/archive/START_PROMPT_R16_TOPICIZATION_SUPPORTING_NOISE_2026-10-08.md) — исходный промпт;
- [`START_PROMPT_R16_STAGE_B_IMPLEMENTATION_2026-11-19.md`](../notes/archive/START_PROMPT_R16_STAGE_B_IMPLEMENTATION_2026-11-19.md) — этап B, §6 «Этап C» и §7 DoD;
- [`START_PROMPT_R16_STAGE_C_DOCS_2026-11-24.md`](../notes/archive/START_PROMPT_R16_STAGE_C_DOCS_2026-11-24.md) — факты этапа C;
- [`R16_SUPPORTING_SIMULATION_2026-11-16.md`](../notes/R16_SUPPORTING_SIMULATION_2026-11-16.md) — §8 (решения владельца) и §10.7 (прогноз).

**Что деплоили:**
- **Решение G:** supporting считается по `topk_denom` с отдельным K = 30 (`TOPICIZATION_SUPPORTING_KEYWORD_TOPK`) и отсечкой `<=` (`TOPICIZATION_SUPPORTING_SCORE_CUT=le`) при пороге 0.10. Phase 1 не меняется (K = 3, `>=`).
- **Ручки скоринга** зеркалированы в compose (BUG-092).
- **CLI `tg-parser topic rebuild-supporting`** — пересборка бандлов без LLM. LLM-элементы сохраняются, ранее покрытые документы остаются в лучшей теме Phase 1 (решение 4a). Запись идёт через `upsert`, счётчик F5-C не меняется.
- **`max_tokens` топикизации** — 8192 → 16384 в `prompts/topicization.yaml`.

Миграции нет. `.env` не менялся.

## 0. Перед деплоем

Снимок 2026-11-20 (SQL по шаблону CLAUDE.md, `SHOW default_transaction_read_only` = `on`):

| Проверка | Факт |
|---|---|
| Ключи `.env` | из `TOPICIZATION_*` только `LLM_PROVIDER`, `LLM_MODEL`, `FULL_RUN_TOKEN_BUDGET`, `FULL_RESUME_ENABLED`, `BATCH_CONCURRENCY`, `BATCH_SIZE`. Ручек скоринга нет — воркер работает на дефолтах compose. Перепроверено 2026-11-25: `TOPICIZATION_SUPPORTING_*` в `.env` по-прежнему нет |
| Текущие бандлы (`time_from IS NULL AND time_to IS NULL`) | 1 463; `channels_json` NULL — 0, пустой — 0, многоканальных — 0 |
| Карточки | 1 463, у всех один источник и бандл; бандлов без канала своей карточки — 0. Пересборка не должна была пропустить ни одной карточки и не пропустила |

Состояние бандлов по каналам («сохранено» в §4 и §6) взято из отчёта записи. Это состояние на момент записи 2026-11-22/23, а не на день деплоя. Между деплоем и записью тик клал новые документы уже по шкале G (§2).

**Точка отката образа:** `tg_parser:pre-r16-2026-11-20` → **`6d0461e9a379`** (один тег на три сервиса).

## 1. Деплой (GO владельца, 2026-11-20)

```bash
ssh prod 'docker tag tg_parser:latest tg_parser:pre-r16-2026-11-20'
ssh prod 'cd /home/user/TG_parser && git pull --ff-only'
ssh prod 'cd /home/user/TG_parser && docker compose build tg_parser'
ssh prod 'cd /home/user/TG_parser && docker compose --profile bot up -d --no-deps --force-recreate tg_parser mcp tg_bot'
```

| Шаг | Время (UTC) | Факт |
|---|---|---|
| Тег отката | 21:45:40 | `tg_parser:pre-r16-2026-11-20` → `6d0461e9a379` |
| Код | 21:45:52 | прод → **`26dd811`** |
| Сборка | 21:47 | `tg_parser:latest` → **`d90debb1ebb9`** (`sha256:d90debb1ebb954278175f6c5dfe4be3d2117274314490d32462097f38bd9ee30`) |
| Recreate | 21:48:23 | старт 21:49:26–27; `tg_parser`, `tg_parser_mcp`, `tg_parser_bot` healthy, restarts 0 |
| Env воркера | 21:49:33 | `SUPPORTING_KEYWORD_TOPK=30`, `SUPPORTING_SCORE_CUT=le`, `SUPPORTING_MIN_SCORE=0.10`, `MAX_SUPPORTING_ITEMS=100`, `ASSIGN_KEYWORD_AGGREGATION=topk_denom`, `ASSIGN_KEYWORD_TOPK=3`, `MIN_TOKEN_LENGTH=3`, `TEXT_CLEAN_MATCH_CHARS=1000` (префикс `TOPICIZATION_`) |
| CLI и промпт | 21:49:34 | `tg-parser topic rebuild-supporting --help` есть; `/app/prompts/topicization.yaml:88` — `max_tokens: 16384`. Каталог смонтирован с хоста, значение применилось вместе с recreate |
| Тики после деплоя | с 21:50 | все `succeeded=18 failed=0 lock_contended=0`, ошибок 0 |

## 2. Бэкап бандлов (GO владельца, 2026-11-20 21:51:15Z)

| | |
|---|---|
| Команда | `pg_dump -Fc -t topic_bundles` в каталог бэкапа. Точный текст команды не сохранился, и восстанавливать его по памяти не стали |
| Файл | `/mnt/data/backups/tg_parser/pre-r16/topic_bundles_20261120.dump`, каталог `700`, 1 469 149 байт |
| sha256 | `66bd8e6b978f94ed649be5bd56f24f40080a57c9a0e348e2821f0be6c80eed82` |
| `pg_restore --list` | читается: TABLE, TABLE DATA, 4 индекса |
| Содержимое (прочитано 2026-11-25, только счётчики) | `COPY public.topic_bundles (topic_id, updated_at, time_from, time_to, items_json, channels_json, metadata_json)`; текущих строк **1 463**, snapshot 0, строк с одной датой 0 |

Бэкап снят после первого тика на новом образе (21:50:40), но до пересборки. Поэтому это точка отката **пересборки**, а не деплоя. Тик выбирает тему по Phase 1, а она не менялась. На новом образе тик меняет только score, с которым документ кладётся в бандл: решение 1A, `bundle_score` на K = 30.

## 3. Dry-run пересборки (2026-11-21, только чтение)

Согласие владельца 2026-11-21: «после тика, если выполнены все существенные условия». Первым шёл AgeManagment, остальные — по согласию после разбора первого.

```bash
ssh prod 'docker exec -e PYTHONDONTWRITEBYTECODE=1 tg_parser nice timeout 900 tg-parser topic rebuild-supporting --channel <ch> --with-base --max-mem-mb 2048 2>&1'
# mediamedics: timeout 2400 … --max-mem-mb 1536
```

- **Во всех 18 прогонах:** `read_only_check: on`, rc 0, карточки и бандлы не пропускались.
- **Порядок:**
  - AgeManagment — ~07:02Z, через 11 минут после тика 06:51;
  - остальные — по возрастанию размера, 19:36–20:04Z;
  - profendocrinologist первый раз совпал с тиком 19:49 и прогнан повторно в 19:51:30–19:52:59. Цифры совпали полностью, в таблице — повторный прогон.
- **Память контейнера `tg_parser`:**
  - базовый уровень 460–520 МБ;
  - на прогонах: Lab4health 631–652, Docma_ru 661–685, profendocrinologist до 747, mediamedics 933–977 МБ;
  - доступно на хосте — не ниже 1 160 МБ;
  - в замерах mediamedics пропуск 19:55–20:03: следующий вызов ждал подтверждения. Пик процесса взят из отчёта инструмента.

**Сверка с прогнозом §10.7, все 18 каналов:**

| | §10.7 (2026-11-19) | dry-run (2026-11-21) |
|---|---|---|
| Тем на документ, база pre-R16 | 4.90 | 4.89 |
| Тем на документ, G по формуле | 3.41 | 3.41 |
| G + 4a | ≈ 3.59 | 3.59 |
| Опустели / урезаны вдвое против базы | 5 / 507 | 5 / 506 |
| Тем на потолке, G | 734 | 734 |
| Ранее покрытые, выпавшие по формуле | 5 497 | 5 517 |

Расхождение по каналу не больше 2.3 % (BiocodebySechenov) при пороге стопа 10 %. Небольшой дрейф объясняется новыми документами с 2026-11-19.

| Канал | Док. | База §10.7 → dry-run | G §10.7 → dry-run | Δ G | Опустели / урезаны вдвое §10.7 → dry-run | dry-run, с | RSS процесса, МБ |
|---|---|---|---|---|---|---|---|
| mediamedics | 11871 | 2.24 → 2.23 | 1.98 → 1.98 | +0.0 % | 0/29 → 0/29 | 616.8 | 507 |
| profendocrinologist | 3753 | 5.22 → 5.22 | 5.05 → 5.05 | +0.0 % | 0/5 → 0/5 | 86.2 | 275 |
| Docma_ru | 3354 | 4.55 → 4.55 | 3.77 → 3.77 | +0.0 % | 0/23 → 0/23 | 68.2 | 245 |
| Lab4health | 2039 | 8.70 → 8.70 | 6.40 → 6.39 | -0.2 % | 0/51 → 0/51 | 40.4 | 211 |
| labdiagnostica_logical | 1383 | 6.42 → 6.39 | 5.10 → 5.07 | -0.6 % | 0/20 → 0/20 | 11.8 | 163 |
| AgeManagment | 1308 | 7.01 → 6.97 | 3.65 → 3.67 | +0.5 % | 0/54 → 0/53 | 13.1 | 147 |
| genotek | 1211 | 4.14 → 4.14 | 2.63 → 2.63 | +0.0 % | 0/20 → 0/20 | 8.6 | 152 |
| mind_rise | 1194 | 3.85 → 3.85 | 3.06 → 3.06 | +0.0 % | 0/9 → 0/9 | 6.2 | 153 |
| tgnikitin | 1059 | 7.90 → 7.90 | 2.53 → 2.55 | +0.8 % | 3/58 → 3/58 | 13.5 | 149 |
| kdl_ru | 918 | 5.36 → 5.35 | 4.63 → 4.62 | -0.2 % | 0/7 → 0/7 | 4.0 | 151 |
| foodf4thought | 371 | 6.34 → 6.32 | 2.46 → 2.46 | +0.0 % | 2/20 → 2/20 | 1.0 | 118 |
| LongevityClub | 340 | 14.92 → 14.92 | 6.51 → 6.51 | +0.0 % | 0/34 → 0/34 | 2.1 | 125 |
| pashaaiaiai | 243 | 19.18 → 19.03 | 5.29 → 5.24 | -0.9 % | 0/39 → 0/39 | 1.3 | 128 |
| BiocodebySechenov | 237 | 7.08 → 7.08 | 3.88 → 3.97 | +2.3 % | 0/8 → 0/8 | 0.5 | 118 |
| aiinsideteam | 194 | 25.08 → 25.08 | 4.93 → 4.93 | +0.0 % | 0/48 → 0/48 | 1.3 | 126 |
| andre_dataist | 193 | 30.49 → 30.49 | 7.22 → 7.22 | +0.0 % | 0/57 → 0/57 | 1.6 | 130 |
| medportal_rfed | 155 | 9.43 → 9.41 | 2.29 → 2.27 | -0.9 % | 0/16 → 0/16 | 0.3 | 114 |
| physics_of_business | 52 | 6.88 → 6.85 | 1.22 → 1.21 | -0.8 % | 0/9 → 0/9 | 0.1 | 110 |

## 4. Запись (отдельные GO владельца, без `--with-base`)

Префикс всех команд тот же, что у dry-run: `ssh prod 'docker exec -e PYTHONDONTWRITEBYTECODE=1 tg_parser nice timeout <N> tg-parser topic rebuild-supporting …'`. Перед `ssh` команда проверяла часы на Mac и не стартовала в окне тика (§7 п. 4).

| Запуск | Время (UTC) | Команда |
|---|---|---|
| AgeManagment | 2026-11-22 21:19:47–21:20:04 | `… --channel AgeManagment --write --max-mem-mb 2048` (`timeout 900`) |
| 15 каналов | 2026-11-23 21:15:15–21:17:03 | `… --channel physics_of_business --channel medportal_rfed --channel andre_dataist --channel aiinsideteam --channel BiocodebySechenov --channel pashaaiaiai --channel LongevityClub --channel foodf4thought --channel kdl_ru --channel tgnikitin --channel mind_rise --channel genotek --channel labdiagnostica_logical --channel Lab4health --channel profendocrinologist --write --max-mem-mb 2048` (`timeout 900`) |
| mediamedics | 2026-11-23 21:56:00–22:01:34 | `… --channel mediamedics --write --max-mem-mb 1536` (`timeout 2400`). Первая попытка в 21:38:39 не стартовала — сработала проверка часов, ничего не записано |
| Docma_ru | 2026-11-23 22:12:08–22:12:51 | `… --channel Docma_ru --write --max-mem-mb 2048` (`timeout 900`) |

Все запуски завершились с rc 0. Отметка `metadata.rebuild.at` по каналам:
- AgeManagment — 2026-11-22T21:19:58;
- 15 каналов — 2026-11-23T21:15:27–21:16:21;
- mediamedics — 21:56:13;
- Docma_ru — 22:12:16.

**Итог по 18 каналам:**
- **Бандлы:** записано 1 463, `reverted_topics` пуст везде, пропусков 0, чужих бандлов 0.
- **Покрытие:** `previously_covered_now_uncovered` = 0 везде. Из 5 521 кандидата 4a удержаны все 5 521, `fallback` 0, потерь 0.
- **LLM-элементы:** сохранено 2 543, сирот 0, `llm_replaced_formula_item` 83.
- **Тем на документ** (взвешено по документам): сохранено 3.45 → по формуле 3.41 → с 4a 3.59 → записано **3.67**.
- **Сверх потолка:** в 386 темах из 1 463 больше 100 supporting-элементов. Это за счёт LLM-элементов (их потолок не считает) и 4a, так и задумано.
- **Память:** пик процесса 534 МБ (mediamedics).

Поправка к отчёту прошлой сессии: владельцу назвали «5 531» удержанных — это ошибка сложения. Верно **5 521**.

| Канал | Док. | Тем на док.: сохранено → записано | Покрытие, % | Удержано 4a | LLM сохранено | Тем > 100 supporting | Записано | reverted | с | RSS, МБ |
|---|---|---|---|---|---|---|---|---|---|---|
| mediamedics | 11879 | 1.08 → 2.40 | 95.88 → 96.12 | 3275/3275 | 1813 | 140/262 | 262 | 0 | 324.5 | 534 |
| profendocrinologist | 3756 | 4.92 → 5.15 | 99.68 → 99.68 | 314/314 | 95 | 75/191 | 191 | 0 | 44.2 | 310 |
| Docma_ru | 3356 | 2.46 → 3.95 | 98.78 → 98.78 | 547/547 | 65 | 41/150 | 150 | 0 | 36.2 | 286 |
| Lab4health | 2041 | 7.02 → 6.49 | 99.85 → 99.85 | 166/166 | 53 | 33/175 | 175 | 0 | 21.8 | 252 |
| labdiagnostica_logical | 1385 | 5.17 → 5.31 | 94.22 → 94.22 | 248/248 | 82 | 36/87 | 87 | 0 | 6.7 | 210 |
| AgeManagment | 1312 | 3.95 → 3.91 | 96.34 → 96.34 | 165/165 | 173 | 13/90 | 90 | 0 | 5.9 | 193 |
| genotek | 1211 | 2.51 → 2.80 | 99.92 → 99.92 | 154/154 | 54 | 11/49 | 49 | 0 | 4.8 | 200 |
| mind_rise | 1194 | 3.30 → 3.21 | 99.58 → 99.58 | 146/146 | 37 | 15/45 | 45 | 0 | 3.6 | 200 |
| tgnikitin | 1059 | 5.93 → 2.91 | 91.78 → 91.78 | 322/322 | 60 | 7/82 | 82 | 0 | 7.9 | 197 |
| kdl_ru | 918 | 4.97 → 4.73 | 99.89 → 99.89 | 75/75 | 26 | 12/48 | 48 | 0 | 2.5 | 197 |
| foodf4thought | 373 | 1.82 → 2.62 | 82.57 → 82.57 | 25/25 | 47 | 0/30 | 30 | 0 | 0.8 | 178 |
| LongevityClub | 340 | 6.43 → 6.59 | 98.82 → 98.82 | 2/2 | 28 | 2/51 | 51 | 0 | 1.2 | 178 |
| pashaaiaiai | 243 | 18.91 → 5.32 | 99.59 → 99.59 | 19/19 | 0 | 0/48 | 48 | 0 | 1.1 | 178 |
| BiocodebySechenov | 238 | 3.41 → 4.02 | 98.74 → 98.74 | 5/5 | 6 | 1/17 | 17 | 0 | 0.3 | 178 |
| aiinsideteam | 194 | 24.00 → 4.99 | 100.0 → 100.0 | 12/12 | 0 | 0/50 | 50 | 0 | 0.9 | 178 |
| andre_dataist | 193 | 30.36 → 7.33 | 100.0 → 100.0 | 20/20 | 0 | 0/62 | 62 | 0 | 1.4 | 178 |
| medportal_rfed | 155 | 1.50 → 2.39 | 100.0 → 100.0 | 15/15 | 3 | 0/17 | 17 | 0 | 0.3 | 163 |
| physics_of_business | 52 | 3.63 → 1.44 | 100.0 → 100.0 | 11/11 | 1 | 0/9 | 9 | 0 | 0.2 | 160 |

**Каналы, которые расширились, — гипотеза, не проверена.** У mediamedics, Docma_ru, foodf4thought и medportal_rfed сохранённые бандлы были у́же даже старой формулы: у mediamedics база 2.23 против сохранённых 1.08. Вероятная причина — бандлы когда-то собраны полностью, а дальше тик клал новый документ только в одну тему. Владелец принял это до записи.

## 5. Проверки после записи (только чтение)

**2026-11-24 07:53Z** (SQL по шаблону):
- у всех 1 463 бандлов есть `metadata.rebuild.at`, внутри каждого канала один момент записи — тик ничего не откатил;
- тик обновил 4 бандла (по одному в Lab4health, genotek, mediamedics и profendocrinologist), добавив новые документы; отметка `rebuild.at` в них сохранилась;
- всего элементов 109 858;
- логи `tg_parser` с 21:15Z 23.11: 11 тиков `failed=0`, строк `lock_contended_proceeding` нет, строк `"level": "error"` нет.

**2026-11-24 ~13:30Z — сверка состояния:**
- хост `26dd811`; три контейнера на `sha256:d90debb1…`, healthy, restarts 0, старт 2026-11-20 21:49:26–27Z;
- тег `pre-r16-2026-11-20` = `6d0461e9a379`;
- `rebuild.at` на месте у всех 1 463 бандлов. Тик обновил ещё 6, всего 10: mediamedics 4, profendocrinologist, Lab4health, Docma_ru, labdiagnostica_logical, genotek, kdl_ru — по одному. Элементов 109 864 — естественный прирост.

**Проверки §4.1 промпта этапа C:**

| # | Проверка | Результат |
|---|---|---|
| 1 | `bug075_reconcile` — `docker logs --since 2026-11-20T22:00:00Z --until 2026-11-24T16:30:00Z tg_parser 2>&1 \| grep -E "bug075_reconcile\|Incremental pipeline completed"` с агрегацией на Mac | ✅ 90 тиков с 2026-11-20 22:50Z по 2026-11-24 15:50Z: во всех 1 620 строках `candidates=0 fed=0 tokens=0`, строк `bug075_reconcile_failed` нет, все тики `succeeded=18, failed=0, degraded=0, lock_contended=0`. Причины `all_attempted` / `all_covered`: A 658 / 188, B 336 / 96, тик 23.11 21:50 (между записью 15 каналов и mediamedics) 14 / 4, C 252 / 72; всего 1 260 / 360. Доля ≈ 78 / 22 % одна и та же во всех периодах. Роста нет. Окна периодов — в разборе длительности ниже |
| 2 | Discover — Prometheus GET `query_range`, `sum by (job,status)(tg_parser_llm_requests_total{stage="topicization_discover"})`, start `1795212000` (2026-11-20 22:00Z), step 3600 | ✅ Счётчик непрерывен с recreate (сбросов нет). `tg_parser_api` success накопительно: 0 → 1 (22.11 06:00Z) → 2 (23.11 16:00Z) → 3 (24.11 13:00Z); ошибок 0; у `tg_parser_bot` и `tg_parser_mcp` — 0. **Сутки после записи (23.11 22:13Z → 24.11 22:13Z) — 1 вызов**, закрыто повторным GET 2026-11-25 08:35Z (по 25.11 08:00Z новых вызовов нет). Фон ≈ 1.5 вызова в день |
| 3 | `get_topic_details` (прод-MCP) | ✅ andre_dataist «Прогресс в робототехнике и физическом ИИ» (`post:317`) — 13 элементов: 3 якоря, 9 по формуле (score 0.121–0.192), 1 `rebuild coverage keep: gen` (0.042). Прогноз §10.7 — 9 supporting, совпал. Шум снят. mediamedics «Уголовное преследование…» (`post:14072`, сверено через `list_topics`) наполнена, **но** раздута 4a — §8, BUG-109 |
| 4 | Длительность тиков (строка `Incremental pipeline completed: succeeded=…, duration=…s`, `scheduler_service.py:993`) | ⚠ Вне ориентира 56–95 с. Объяснение принято владельцем 2026-11-25, разбор ниже. Связи с R16 нет |

**Разбор длительности тиков.** Периоды: A — до пересборки, 2026-11-20 22:50 → 2026-11-22 20:50, 47 тиков; B — после AgeManagment, 2026-11-22 21:50 → 2026-11-23 20:50, 24 тика; C — после всех каналов, 2026-11-23 22:50 → 2026-11-24 15:50, 18 тиков. Тик 23.11 21:50 пришёлся между записями и ни в один период не входит.

| | A | B | C |
|---|---|---|---|
| Медиана тика, с | 62.4 | 67.0 | 70.9 |
| Максимум, с | 96.4 | 107.9 | **125.1** |
| Медиана тиков без топикизации, с | 61.4 | 62.5 | 59.6 |
| Запусков топикизации на тик | 0.28 | 0.67 | 0.78 |
| Элементов добавлено, всего | 13 | 17 | 15 |
| Тем пересуммаризировано | 4 | 8 | 8 |

Тики без топикизации не замедлились. Рост медианы и пиков — только в тиках со стадиями `incremental_topicization` / `resummarize`. Таких тиков стало больше, потому что период A пришёлся на субботу–воскресенье 21–22.11: 13 элементов за 47 тиков против 15 за 18. Тик 24.11 09:50 (125 с): mediamedics с топикизацией и resummarize закончил в 09:51:44, остальные каналы — к 09:50:46. Счётчик F5-C растёт на число добавленных документов (`_update_bundles_for_assignments` → `increment_resummary_counter`), выбор темы — Phase 1 без изменений.

## 6. Прогноз, dry-run и запись по каналам

«База» и «G» — только формула supporting (G — по решению G). «Записано» — то, что лежит в бандлах после записи: формула G плюс сохранённые LLM-элементы и удержание 4a. Поэтому «записано» выше «G». «Сохранено» — бандлы перед записью.

| Канал | Док. (запись) | База §10.7 / dry-run | G §10.7 / dry-run | Сохранено | Записано |
|---|---|---|---|---|---|
| mediamedics | 11879 | 2.24 / 2.23 | 1.98 / 1.98 | 1.08 | 2.40 |
| profendocrinologist | 3756 | 5.22 / 5.22 | 5.05 / 5.05 | 4.92 | 5.15 |
| Docma_ru | 3356 | 4.55 / 4.55 | 3.77 / 3.77 | 2.46 | 3.95 |
| Lab4health | 2041 | 8.70 / 8.70 | 6.40 / 6.39 | 7.02 | 6.49 |
| labdiagnostica_logical | 1385 | 6.42 / 6.39 | 5.10 / 5.07 | 5.17 | 5.31 |
| AgeManagment | 1312 | 7.01 / 6.97 | 3.65 / 3.67 | 3.95 | 3.91 |
| genotek | 1211 | 4.14 / 4.14 | 2.63 / 2.63 | 2.51 | 2.80 |
| mind_rise | 1194 | 3.85 / 3.85 | 3.06 / 3.06 | 3.30 | 3.21 |
| tgnikitin | 1059 | 7.90 / 7.90 | 2.53 / 2.55 | 5.93 | 2.91 |
| kdl_ru | 918 | 5.36 / 5.35 | 4.63 / 4.62 | 4.97 | 4.73 |
| foodf4thought | 373 | 6.34 / 6.32 | 2.46 / 2.46 | 1.82 | 2.62 |
| LongevityClub | 340 | 14.92 / 14.92 | 6.51 / 6.51 | 6.43 | 6.59 |
| pashaaiaiai | 243 | 19.18 / 19.03 | 5.29 / 5.24 | 18.91 | 5.32 |
| BiocodebySechenov | 238 | 7.08 / 7.08 | 3.88 / 3.97 | 3.41 | 4.02 |
| aiinsideteam | 194 | 25.08 / 25.08 | 4.93 / 4.93 | 24.00 | 4.99 |
| andre_dataist | 193 | 30.49 / 30.49 | 7.22 / 7.22 | 30.36 | 7.33 |
| medportal_rfed | 155 | 9.43 / 9.41 | 2.29 / 2.27 | 1.50 | 2.39 |
| physics_of_business | 52 | 6.88 / 6.85 | 1.22 / 1.21 | 3.63 | 1.44 |
| **Все 18** | | **4.90 / 4.89** | **3.41 / 3.41** | **3.45** | **3.67** |

G + 4a по прогнозу — ≈ 3.59, в dry-run — 3.59. Разница до записанных 3.67 — LLM-элементы, которых нет в формуле.

## 7. Решения владельца

1. **Dry-run на проде** — согласие 2026-11-21: «после тика, если выполнены все существенные условия». Сначала AgeManagment, остальные — по согласию после разбора первого.
2. **Запись — по отдельным GO:**
   - AgeManagment первым — 2026-11-22. Отступление от промпта этапа B §6, где первыми назначены `physics_of_business` или `aiinsideteam`;
   - остальные по схеме п. 3 — 2026-11-23;
   - Docma_ru отдельно — 2026-11-23, после того как владелец увидел рост 2.46 → 3.95.
3. **Схема записи, 2026-11-23:** 15 каналов — одной командой с повторяемым `--channel`; mediamedics — отдельной командой с `timeout 2400` и `--max-mem-mb 1536`.
4. **«Сразу после тика» заменено на «не во время тика»** (2026-11-23). Каждая команда `ssh` ждёт подтверждения, а подтверждения приходили через 4.5–17 часов.
   - Перед `ssh` команда проверяет часы на Mac (с прода ничего не читается) и не стартует в окне тика: `:45–:55`, для mediamedics — `:35–:55`.
   - Сначала проверка завершала команду (`exit 3`), потом команда стала ждать конца окна и стартовать после.
   - Защита внутри инструмента: отпечаток бандлов перед записью и сверка после commit (`reverted_topics`).
5. **2026-11-24:**
   - концентрация удержанных 4a в широких темах — наблюдение в протоколе (§8) и новая запись **BUG-109**; BUG-105 закрывается;
   - обёрнутые INFO-строки в выводе `--write` (§9 п. 5) — **BUG-110** (Low).
6. **2026-11-25:**
   - статус BUG-105 — `resolved` (словарь `BUG_LOG` и DoD исходного промпта 10-08), а не `fixed` из DoD этапа C. Строка BUG-105 остаётся в блоке «Что открыто», как у BUG-107;
   - отклонение длительности тиков от ориентира принято (§5 п. 4);
   - разрешено одной командой прочитать настоящий дамп на хосте: только заголовок `COPY` и счётчики, без записи и без вывода данных (§2, §10).

## 8. Наблюдения

**4a концентрирует удержанные документы в широких темах.** Тема mediamedics `post:14072` — 1 059 элементов:

| Состав | Элементов | score |
|---|---|---|
| якоря | 3 | |
| `incremental llm assign` | 89 | |
| по формуле (`keyword overlap`) | 100 | 0.46–0.763, медиана 0.5 |
| `rebuild coverage keep` | **867** | min 0.01, p25 0.173, медиана 0.217, p75 0.273, max 0.453; fallback 0 |

В хвосте `rebuild coverage keep` — слабые совпадения вроде «covid» и «том, что». Карточка: `new_items_since_last_summary` 4, `summary_version` 30. Ответ `get_topic_details` — 289 864 символа, MCP-клиент Claude Code его не принял.

По всем каналам 8 широких тем mediamedics держат 2 517 из 3 275 удержанных документов канала. Топ тем по 4a (удержано / всего):
- mediamedics: 14072 — 867/1059, 13108 — 437/569, 10644 — 278/657, 8520 — 275/417, 13525 — 188/584, 13180 — 182/339, 1772 — 166/322, 2954 — 124/347, 5146 — 71/205;
- Docma_ru: 257 — 122/227, 252 — 81/190, 473 — 72/173;
- mind_rise 944 — 90/193; tgnikitin 367 — 64/171; Lab4health 1036 — 56/157; labdiagnostica_logical 1042 — 55/158; profendocrinologist 3676 — 54/157.

Fallback — 0 во всех темах.

Гипотеза причины, **не проверена**: Phase 1 с K = 3 при argmax чаще выбирает тему с богатым `scope_in`. Объём ответа `get_topic_details` и форма 4a — [BUG-109](../notes/BUG_LOG.md).

## 9. Особенности и ловушки

1. **Подтверждение каждой команды `ssh`.** Правило `ask: Bash(ssh *)` срабатывает раньше `allow`, поэтому даже чтение ждёт клика. Подтверждения приходили через 4.5–17 часов. Решение — проверка часов на Mac перед `ssh` (§7 п. 4). Чтение и запись в одной команде при этом не смешиваются: время берётся с Mac.
2. **Типы колонок в SQL:**
   - в `topic_bundles` колонки `channels_json`, `items_json` и `metadata_json` — `text`, нужен `::jsonb`; `updated_at` — `varchar`, нужен `::timestamptz`;
   - в `topic_cards` нет `channel_id`: канал берётся из `sources_json` или из `channels_json` бандла.

   Две ошибки SQL в прошлой сессии были именно на этом. Обе — на чтении, прод не затронут.
3. **Время на mediamedics:** dry-run с `--with-base` — 617 с, запись — 325 с. Запаса у `timeout 900` мало, поэтому `timeout 2400`.
4. **Память хоста:** доступно 1.1–1.6 ГБ, swap занят на 0.5 ГБ. Контейнер `tg_parser` держится на 460–520 МБ, пик — 977 МБ на dry-run mediamedics. Лимита памяти у `tg_parser` в compose нет.
5. **Обёрнутые INFO-строки.** В режиме `--write` в начало вывода попадают две INFO-строки Prometheus (`"Prometheus instrumentator configured"`, `"Prometheus metrics enabled"`), обёрнутые как `{"type": "stdout", ...}`. Они появляются при инициализации `Database`. На данные не влияют, но отчёт перестаёт быть чистым JSONL — [BUG-110](../notes/BUG_LOG.md).
6. **Повтор profendocrinologist.** Первый dry-run пересёкся с тиком, а цифры совпали с повтором бит в бит. Значит, этот тик не изменил входные данные канала. Общего вывода о независимости расчёта от тика отсюда не следует.
7. **Расширение некоторых каналов** — гипотеза, не факт (§4).
8. **`SCHEDULER_CRITICAL_ENV` ничего не «замораживает».** Это allow-list в `tests/test_compose_env_propagation.py`: тест гарантирует, что ключ зеркалирован в `environment:` сервиса `tg_parser`. Recreate для смены ручки нужен по другой причине: значение подставляется в окружение при создании контейнера и читается при импорте `topicization.py` (§10).

## 10. Откат

Три уровня. Они независимы, и каждый выполняется **только по отдельному GO**. В этой сессии ничего из этого на проде не выполнялось.

### 10.1. Скоринг

Добавить в `/home/user/TG_parser/.env` (сейчас этих ключей там нет):

```
TOPICIZATION_SUPPORTING_KEYWORD_TOPK=3
TOPICIZATION_SUPPORTING_SCORE_CUT=lt
```

Затем пересоздать воркер и проверить:

```bash
ssh prod 'cd /home/user/TG_parser && docker compose up -d --no-deps --force-recreate tg_parser'
ssh prod 'docker exec tg_parser env | grep "^TOPICIZATION_SUPPORTING_"'
```

Как ключ попадает в процесс:
- compose подставляет `${VAR:-default}` из `.env` в `environment:` сервиса `tg_parser` ([`docker-compose.yml:144-145`](../../docker-compose.yml));
- `Settings` читает переменные окружения процесса;
- [`topicization.py:166-167`](../../tg_parser/processing/topicization.py) берёт значение при импорте.

Отсюда два следствия. Нужен именно recreate: `restart` окружение не перечитывает, а `.env` внутри контейнера приложение не читает (BUG-092). Пересоздавать достаточно `tg_parser`: у `mcp` и `tg_bot` есть `env_file: .env` (`docker-compose.yml:231,301`), но топикизация идёт только в `tg_parser`.

Бандлы при этом остаются пересобранными, а тик кладёт новые документы уже по старой шкале. Recreate сдвигает фазу тика: окно для отката бандлов определять заново по `Background scheduler started` в `docker logs --since`.

### 10.2. Образ

```bash
ssh prod 'docker tag tg_parser:pre-r16-2026-11-20 tg_parser:latest && cd /home/user/TG_parser && docker compose --profile bot up -d --no-deps --force-recreate tg_parser mcp tg_bot'
```

`prompts/` смонтирован с хоста, поэтому `max_tokens: 16384` останется, пока на хосте не откатят `git`; это отдельное решение. Ручек старый образ не знает и работает на K = 3 и `<`. В нём нет CLI `rebuild-supporting`, поэтому откат бандлов — до отката образа.

### 10.3. Бандлы

Оба пути — **после** отката скоринга (иначе следующий тик кладёт документы по шкале G) и **до** отката образа.

**(Б1) Мягкий путь, первый выбор.** `tg-parser topic rebuild-supporting --write` по каналам, на шкале K = 3 / `<` после §10.1 (`docker exec` наследует окружение контейнера). Команды и порядок — как в §4.
- Элементы, которые тик добавил после 2026-11-20, не теряются.
- Платного discover нет.
- Защита от гонки с тиком уже есть: отпечаток и `reverted_topics` ([`supporting_rebuild_service.py`](../../tg_parser/services/supporting_rebuild_service.py), docstring модуля).
- Результат — состав supporting по старой шкале, но не побайтно как в дампе: LLM-элементы и удержание 4a сохраняются.

**(Б2) Точный путь — из `topic_bundles_20261120.dump`**, когда нужен именно побайтный возврат. Скрипт ниже.

У `topic_bundles` нет первичного ключа. Уникальность держат два частичных индекса ([`_metadata.py`](../../tg_parser/storage/sqlalchemy/_metadata.py), таблица `topic_bundles`):
- `topic_bundles_current_unique_idx (topic_id) WHERE time_from IS NULL AND time_to IS NULL`;
- `topic_bundles_snapshot_unique_idx (topic_id, time_from, time_to) WHERE time_from IS NOT NULL AND time_to IS NOT NULL`.

`pg_restore` прямо в таблицу упрётся в эти индексы, поэтому скрипт **заменяет** строки. Восстанавливаются только текущие бандлы (обе даты NULL). Snapshot-строки не трогаются ни в дампе, ни в таблице; в дампе их 0, на проде 2026-11-25 — тоже 0.

**Как работает скрипт:**
1. Проверяет, что в контейнере Postgres есть `perl` с модулем ядра `JSON::PP` (на нём работает сверка, п. 5; в локальном `pgvector/pgvector:pg17` — perl 5.36, JSON::PP 4.07), и sha256 дампа. Временные файлы — `600` (`umask 077`), в каталоге бэкапа (`700`), а не в `/tmp`: текстовая выгрузка — десятки МБ, а `/tmp` может оказаться tmpfs при 1.1–1.6 ГБ свободной памяти. `trap` удаляет их при любом выходе.
2. `pg_restore --data-only` переводит дамп в текст COPY. Список колонок берётся из заголовка `COPY public.topic_bundles (…)` самого дампа.
3. Печатает число строк дампа по классам: текущие / snapshot / с одной датой, и сколько текущих уже несут `metadata.rebuild`. Строки с одной датой не покрыты ни одним индексом, при них — `ABORT`. Строки с `metadata.rebuild` в дампе сломали бы сверку (п. 5), при них тоже `ABORT`; в дампе от 2026-11-20 их быть не может — пересборки тогда ещё не было. Число текущих должно совпасть с `EXPECTED_ROWS`, которое оператор передаёт явно. Без переменной или при несовпадении — `ABORT` до транзакции. Первый запуск — без `EXPECTED_ROWS`, чтобы увидеть числа.
4. Одна транзакция (`psql -1`):
   - `lock_timeout = 10s`;
   - загрузка во временную таблицу;
   - `DO`-блок: темы без карточки (сироты) пропускаются с `NOTICE`; `LOCK TABLE topic_bundles IN SHARE ROW EXCLUSIVE MODE`; текущие строки тем из дампа удаляются, строки дампа вставляются;
   - самопроверка: число удалённых строк равно числу найденных, число вставленных — числу загруженных, и строки совпадают с дампом целиком (`EXCEPT` в обе стороны). Иначе `RAISE EXCEPTION`, откат целиком.
   - Бандлы тем, которых нет в дампе (появились после 2026-11-20), не трогаются.
5. Сверка после COMMIT в режиме только для чтения (`default_transaction_read_only=on`): `\copy (SELECT …) TO pstdout` текущих строк по каждой карточке, сравнение с дампом — в `perl` внутри контейнера Postgres: `items_json`, `channels_json` и `metadata_json` разбираются как JSON и сравниваются в каноническом виде, поэтому формат сериализации и порядок элементов не важны. Каждая тема дампа получает один из классов:
   - `match` — строка равна дампу;
   - `grown` — каждый элемент дампа есть среди текущих элементов (как JSON-объект целиком), `channels_json` и `metadata_json` равны дампу, добавлены только новые элементы: штатный `add_items` тика после восстановления (он меняет только список items и `updated_at`). Не ошибка;
   - `STALE <topic_id>` — в строке есть `metadata.rebuild`: тик прочитал бандл до COMMIT и записал пересобранную версию обратно. У всех 1 463 бандлов после пересборки этот ключ есть, у строк дампа его нет, а `add_items` сохраняет `metadata` прочитанного бандла;
   - `CHANGED <topic_id>` — всё остальное: элемент дампа пропал или изменён (например, другой `score` или `source_ref`), отличаются `channels_json` / `metadata_json`, или значение не разбирается как JSON. Ни одна из известных записей тика после восстановления так не делает.

   Итоговая строка — `verify: dump_current=… match=… grown=… stale=… changed=… no_card=…`; при `stale` или `changed` больше нуля — выход 1.

**Почему сверка обязательна, дважды — сразу и после следующего тика.** `add_items` в тике читает бандл без блокировки и пишет `upsert` (DELETE + INSERT, [`topic_bundle_repo.py:208-240`](../../tg_parser/storage/sqlalchemy/topic_bundle_repo.py)). Если тик прочитал бандл до COMMIT, а записал после, он молча затирает восстановленную строку пересобранной версией со своими элементами, и LOCK от этого не защищает. Такая запись может прийти и после первой сверки, пока тот тик ещё идёт.

**Что делать по результату сверки:**
- `grown` — штатно, ничего не делать.
- `STALE` — повторный запуск восстановления (по GO). Он заменяет **все** бандлы из дампа, поэтому вместе с устаревшими уйдёт и штатный рост `grown` после первого запуска; эти документы снова подберёт BUG-075 с теми же оговорками о discover, что ниже. Чтобы повтор не задевал законные записи, восстановление запускают сразу после конца тика, а вторую сверку делают сразу после конца следующего тика и до следующего за ним.
- `CHANGED` — стоп, повтор не запускать: разбор с владельцем. Это изменение, которого процедура не ожидает (например, полная перетопикизация канала или ручная правка).

**Последствия, которые надо принять до GO:**
- Элементы, которые тик добавил после 2026-11-20 21:51 в заменённые бандлы, теряются.
- Потерявшие покрытие документы подберёт сверка BUG-075. Она прогоняет непокрытые документы без маркера discover через инкрементальную топикизацию ([`topicization_service.py:2167`](../../tg_parser/services/topicization_service.py), `run_reconciliation_for_channel`). Phase 1 по ключевым словам бесплатна; LLM discover нужен только тем, кого Phase 1 не назначит. Лимит — `topicization_reconcile_max_docs = 200` на тик ([`settings.py:495`](../../tg_parser/config/settings.py)), остаток откладывается (`deferred`); возможны новые темы.
- **Оценка на 2026-11-25** (read-only SQL: документы с `processed_at > 2026-11-20 21:51:15+00` без маркера `topicization:discover_attempted:`, по способу попадания в текущие бандлы): всего **53**. Из них `incremental keyword assign` 22, `keyword overlap` 20, `rebuild coverage keep` 9 — бесплатные; `incremental llm assign` **2** — им может понадобиться discover. Цифра растёт со временем.
- Счётчик F5-C не меняется.

**Доставка и запуск.** На хосте **все** шаги ниже идут только по GO владельца, одно GO — одна строка. Ни один из них не входит в список чтения CLAUDE.md: скрипт пишет временные файлы в каталог бэкапа и выполняет `\copy`, `scp` и `rm` меняют файлы на хосте, `stat` и `sha256sum` в списке чтения тоже нет. Локальные шаги (`git show`, `shasum`) — без GO. Скрипт берётся из этого файла на закоммиченном SHA:

```bash
git show <SHA>:docs/runbooks/BUG105_R16_DEPLOY.md \
  | sed -n '/^# >>> restore_topic_bundles.sh/,/^# <<< restore_topic_bundles.sh/p' \
  > /tmp/restore_topic_bundles.sh
shasum -a 256 /tmp/restore_topic_bundles.sh                                            # локально
ssh prod 'stat -c "%U %a" /mnt/data/backups/tg_parser/pre-r16'                         # GO 1: владелец = ssh-пользователь, 700
scp /tmp/restore_topic_bundles.sh prod:/mnt/data/backups/tg_parser/pre-r16/            # GO 2: файл на хосте
ssh prod 'sha256sum /mnt/data/backups/tg_parser/pre-r16/restore_topic_bundles.sh'     # GO 3: сверить с локальной суммой
ssh prod 'bash /mnt/data/backups/tg_parser/pre-r16/restore_topic_bundles.sh'          # GO 4: счётчики, ABORT до транзакции
ssh prod 'EXPECTED_ROWS=1463 bash /mnt/data/backups/tg_parser/pre-r16/restore_topic_bundles.sh'   # GO 5: запись, сразу после тика
ssh prod 'MODE=verify bash /mnt/data/backups/tg_parser/pre-r16/restore_topic_bundles.sh'          # GO 6: сразу после следующего тика
ssh prod 'rm -f /mnt/data/backups/tg_parser/pre-r16/restore_topic_bundles.sh'         # GO 7: удалить копию
```

`EXPECTED_ROWS=1463` — число текущих строк дампа, прочитанное 2026-11-25 (§2). Второй запуск всё равно сверяет его с тем, что напечатает первый. Владельца и права каталога бэкапа в этой сессии не проверяли: `stat` нет в списке чтения. Если владелец каталога — не ssh-пользователь, `scp` и `mktemp -p` откажут, и процедура остановится до любых изменений.

```bash
# >>> restore_topic_bundles.sh — R16 rollback B2, docs/runbooks/BUG105_R16_DEPLOY.md §10
# Run on the prod host as: [MODE=verify] [EXPECTED_ROWS=<n>] bash restore_topic_bundles.sh
set -euo pipefail
umask 077
D=/mnt/data/backups/tg_parser/pre-r16/topic_bundles_20261120.dump
D_SHA256=66bd8e6b978f94ed649be5bd56f24f40080a57c9a0e348e2821f0be6c80eed82
DB=tg_parser
PGC=tg_parser_postgres
MODE=${MODE:-restore}
case "$MODE" in restore | verify) ;; *) echo "ABORT: MODE must be restore or verify"; exit 1 ;; esac
docker exec "$PGC" perl -MJSON::PP -e 1 || { echo "ABORT: perl JSON::PP not available in $PGC"; exit 1; }
W=$(dirname "$D")

echo "$D_SHA256  $D" | sha256sum -c - > /dev/null
ALL=$(mktemp -p "$W" r16-restore.XXXXXX)
CUR=$(mktemp -p "$W" r16-restore.XXXXXX)
trap 'rm -f "$ALL" "$CUR"' EXIT

# 1. Dump -> COPY text; column order is taken from the dump's own COPY header.
docker exec -i "$PGC" pg_restore --data-only -t topic_bundles -f - < "$D" > "$ALL"
COLS=$(grep -m1 '^COPY public\.topic_bundles (' "$ALL" \
  | sed -E 's/^COPY public\.topic_bundles \((.*)\) FROM stdin;$/\1/')
[ -n "$COLS" ] || { echo "ABORT: no COPY header for public.topic_bundles in the dump"; exit 1; }
BCOLS=$(printf '%s\n' "$COLS" | sed -E 's/([a-z_]+)/b.\1/g')

# 2. Classify dump rows by time_from/time_to; only current rows (both \N) go to $CUR.
STATS=$(awk -F'\t' -v cols="$COLS" -v out="$CUR" '
  BEGIN { n = split(cols, c, ", ")
          for (i = 1; i <= n; i++) {
            if (c[i] == "time_from") f = i
            if (c[i] == "time_to") t = i
            if (c[i] == "topic_id") k = i
            if (c[i] == "items_json") it = i
            if (c[i] == "metadata_json") md = i
            if (c[i] == "channels_json") ch = i } }
  /^COPY public\.topic_bundles \(/ { inb = 1; next }
  inb && $0 == "\\." { inb = 0; next }
  inb { a = ($f == "\\N"); b = ($t == "\\N")
        if (a && b) { nc++; print > out; if ($md ~ /"rebuild": *[{]/) nr++ }
        else if (!a && !b) ns++; else nh++ }
  END { if (!f || !t || !k || !it || !md || !ch) exit 3
        print nc + 0, ns + 0, nh + 0, nr + 0, k, it, md, ch }' "$ALL") \
  || { echo "ABORT: topic_id/time_from/time_to/items_json/metadata_json/channels_json not in the COPY header"; exit 1; }
set -- $STATS
NC=$1 NS=$2 NH=$3 NR=$4 K=$5 IT=$6 MD=$7 CH=$8
echo "dump topic_bundles rows: current=$NC snapshot=$NS half=$NH with_rebuild_metadata=$NR"
[ "$NH" -eq 0 ] || { echo "ABORT: $NH dump rows have exactly one of time_from/time_to"; exit 1; }
# verify() tells a stale tick write (R16-rebuilt row, carries metadata.rebuild) from
# normal tick growth; that only works if no dump row carries metadata.rebuild.
[ "$NR" -eq 0 ] || { echo "ABORT: $NR dump rows already carry metadata.rebuild"; exit 1; }

# Read-only check of every dump topic against its live current row (JSON-aware, perl JSON::PP):
#   match — equal to the dump; grown — every dump item present (compared as parsed JSON),
#   channels and metadata equal to the dump, only additions (a tick's add_items after the
#   restore, normal); STALE — row carries metadata.rebuild (a tick that read before COMMIT
#   wrote the rebuilt version back): re-run the restore; CHANGED — anything else (dump items
#   missing or altered, channels/metadata differ, unparsable): stop, review, do not re-run.
VERIFY_PL='
use strict; use warnings; use JSON::PP;
my ($k, $it, $md, $ch) = map { $_ - 1 } @ARGV;
my $J = JSON::PP->new->utf8->canonical->allow_nonref;
my %e = (b => "\b", f => "\f", n => "\n", r => "\r", t => "\t", v => "\x0b");
sub dec { my $f = shift; return undef if $f eq "\\N";
          $f =~ s/\\(.)/exists $e{$1} ? $e{$1} : $1/ge; return $J->decode($f) }
my (%want, %seen, %n);
while (my $l = <STDIN>) { chomp $l; last if $l eq "\\."; my @f = split /\t/, $l, -1; $want{$f[$k]} = $l }
while (my $l = <STDIN>) {
  chomp $l; my ($id, $rest) = split /\t/, $l, 2;
  next unless exists $want{$id};
  $seen{$id} = 1;
  if ($rest eq $want{$id}) { $n{match}++; next }
  my @c = split /\t/, $rest, -1; my @o = split /\t/, $want{$id}, -1;
  my $why = eval {
    my $cm = dec($c[$md]);
    return "STALE" if ref $cm eq "HASH" && exists $cm->{rebuild};
    my %have = map { $J->encode($_) => 1 } @{ dec($c[$it]) // [] };
    my $miss = grep { !$have{ $J->encode($_) } } @{ dec($o[$it]) };
    my $same = $J->encode([dec($o[$md]), dec($o[$ch])]) eq $J->encode([$cm, dec($c[$ch])]);
    return "grown" if !$miss && $same;
    return "CHANGED $id (dump items missing or altered: $miss" . ($same ? "" : "; channels/metadata differ") . ")";
  } // "CHANGED $id (unparsable)";
  if ($why eq "grown") { $n{grown}++ }
  elsif ($why eq "STALE") { $n{stale}++; print "STALE $id\n" }
  else { $n{changed}++; print "$why\n" }
}
my $nocard = grep { !$seen{$_} } keys %want;
printf "verify: dump_current=%d match=%d grown=%d stale=%d changed=%d no_card=%d\n",
  scalar(keys %want), map({ $n{$_} // 0 } qw(match grown stale changed)), $nocard;
exit(($n{stale} // 0) + ($n{changed} // 0) > 0 ? 1 : 0);
'
verify() {
  { cat "$CUR"; printf '%s\n' '\.'
    docker exec -i -e PGOPTIONS="-c default_transaction_read_only=on" "$PGC" \
      psql -U tg_parser_user -d "$DB" -X -q -v ON_ERROR_STOP=1 \
      -c "\\copy (SELECT c.id, $BCOLS FROM topic_cards c LEFT JOIN topic_bundles b ON b.topic_id = c.id AND b.time_from IS NULL AND b.time_to IS NULL) TO pstdout"
  } | docker exec -i "$PGC" perl -e "$VERIFY_PL" "$K" "$IT" "$MD" "$CH"
}

if [ "$MODE" = verify ]; then
  verify
  exit 0
fi

case "${EXPECTED_ROWS:-}" in
  '' | *[!0-9]*) echo "ABORT: check the counts above, then re-run with EXPECTED_ROWS=<current>"; exit 1 ;;
esac
[ "$EXPECTED_ROWS" -eq "$NC" ] || { echo "ABORT: EXPECTED_ROWS=$EXPECTED_ROWS, dump current=$NC"; exit 1; }

# 3. One transaction: load, lock, replace current rows of the dump's topics, self-check.
docker exec -i "$PGC" psql -U tg_parser_user -d "$DB" -X -q -1 -v ON_ERROR_STOP=1 \
  -c "SET LOCAL lock_timeout = '10s'" \
  -c "CREATE TEMP TABLE r (LIKE topic_bundles) ON COMMIT DROP" \
  -c "\\copy r ($COLS) FROM pstdin" \
  -c 'DO $$
DECLARE
  n_orphan bigint; n_r bigint; n_match bigint; n_del bigint; n_ins bigint; n_diff bigint;
BEGIN
  IF EXISTS (SELECT 1 FROM r WHERE time_from IS NOT NULL OR time_to IS NOT NULL) THEN
    RAISE EXCEPTION $m$non-current rows in the load set$m$;
  END IF;
  LOCK TABLE topic_bundles IN SHARE ROW EXCLUSIVE MODE;
  DELETE FROM r WHERE NOT EXISTS (SELECT 1 FROM topic_cards c WHERE c.id = r.topic_id);
  GET DIAGNOSTICS n_orphan = ROW_COUNT;
  RAISE NOTICE $m$dump bundles without a topic card, skipped: %$m$, n_orphan;
  SELECT count(*) INTO n_r FROM r;
  SELECT count(*) INTO n_match FROM topic_bundles b
   WHERE b.time_from IS NULL AND b.time_to IS NULL AND b.topic_id IN (SELECT topic_id FROM r);
  DELETE FROM topic_bundles b
   WHERE b.time_from IS NULL AND b.time_to IS NULL AND b.topic_id IN (SELECT topic_id FROM r);
  GET DIAGNOSTICS n_del = ROW_COUNT;
  INSERT INTO topic_bundles SELECT * FROM r;
  GET DIAGNOSTICS n_ins = ROW_COUNT;
  IF n_del <> n_match OR n_ins <> n_r THEN
    RAISE EXCEPTION $m$count mismatch: deleted % of %, inserted % of %$m$, n_del, n_match, n_ins, n_r;
  END IF;
  SELECT count(*) INTO n_diff FROM (
    (SELECT * FROM r
     EXCEPT SELECT * FROM topic_bundles WHERE time_from IS NULL AND time_to IS NULL)
    UNION ALL
    (SELECT * FROM topic_bundles
      WHERE time_from IS NULL AND time_to IS NULL AND topic_id IN (SELECT topic_id FROM r)
     EXCEPT SELECT * FROM r)) d;
  IF n_diff <> 0 THEN
    RAISE EXCEPTION $m$restored rows differ from the dump: %$m$, n_diff;
  END IF;
  RAISE NOTICE $m$replaced %, added %, total restored %$m$, n_del, n_ins - n_del, n_ins;
END $$' \
  < "$CUR"
echo "committed"

# 4. Immediate read-only check; repeat with MODE=verify after the next tick.
verify
# <<< restore_topic_bundles.sh
```

`INSERT … SELECT * FROM r` безопасен по порядку колонок: `r` создана как `LIKE topic_bundles`, а загрузка в неё идёт с явным списком колонок из заголовка дампа. Генерируемых колонок у `topic_bundles` нет.

**Проверка процедуры (2026-11-25/26, локально; на проде не выполнялась).** Классы сверки `grown` / `STALE` / `CHANGED` и варианты 7b, 7c, 7c′, 7d, 7e, 9 и 10 добавлены по итогам трёх кругов ревью. Первая версия сравнивала строки целиком и принимала штатный рост за расхождение. Вторая проверяла в `grown` только наличие `source_ref` и пропускала изменённый `score`. Третья искала объекты регулярным выражением, и фигурная скобка внутри строки (`"Example {covid}"`) ломала разбор. Сейчас сравнение идёт через JSON-парсер. Блок выше, извлечённый из этого файла дословно (заменены только путь к дампу, его sha256 и имя базы), прогнан на `tg_parser_test` в локальном `tg_parser_postgres` (pg17).

Засев: 6 карточек, 5 текущих бандлов и 1 snapshot. `items_json` — валидный JSON с экранированными табом, переводом строки, `\`, кавычками, не-ASCII и фигурными скобками внутри строк: так проверяются и экранирование COPY, и разбор JSON. Затем `pg_dump -Fc -t topic_bundles`. После дампа: 3 бандла изменены, у одной темы удалён бандл (карточка осталась), добавлен бандл новой темы, у одной темы из дампа удалены и карточка, и бандл (сирота).

| # | Вариант | Результат |
|---|---|---|
| 1 | Восстановление (`EXPECTED_ROWS=5`) | ✅ `skipped: 1`, `replaced 3, added 1, total restored 4`, `verify: dump_current=5 match=4 grown=0 stale=0 changed=0 no_card=1`. Текущие строки побайтно равны дампу; бандл новой темы и snapshot целы; сирота не воскрешена |
| 2 | Повторный запуск | ✅ `replaced 4, added 0`, таблица та же |
| 3 | Без `EXPECTED_ROWS` / `EXPECTED_ROWS=4` / `5x` | ✅ выход 1 до транзакции, напечатаны `current=5 snapshot=1 half=0`, таблица не тронута |
| 4 | Атомарность: дамп с дублем `topic_id` среди текущих строк (из отдельной базы без уникальных индексов) | ✅ INSERT падает на `topic_bundles_current_unique_idx` уже после DELETE; выход ≠ 0, таблица как до запуска |
| 5 | `lock_timeout`: вторая сессия держит `ROW EXCLUSIVE` (как запись тика) | ✅ ошибка `lock timeout` через 10–11 с, таблица не тронута |
| 6 | `trap` | ✅ во время ожидания файлы `-rw-------`; после падений файлов не осталось |
| 7 | Гонка с тиком: после восстановления бандл темы перезаписан пересобранной версией (`metadata.rebuild`, элементы дампа плюс лишние) | ✅ `MODE=verify` — `STALE <topic_id>`, `stale=1 changed=0`, выход 1; повторный запуск — `match=4 grown=0 stale=0 changed=0`, таблица равна результату варианта 1 |
| 7b | Элементы дампа пропали без `metadata.rebuild` | ✅ `CHANGED <topic_id> (dump items missing or altered: 2)`, выход 1 |
| 7c | У элемента дампа со скобками в `justification` (`"Example {covid} …"`) изменён `score`, добавлен новый элемент | ✅ `CHANGED <topic_id> (…: 1)`, `grown=0`, выход 1 |
| 7c′ | У того же элемента заменён `source_ref` | ✅ `CHANGED`, выход 1 |
| 7d | Изменены `channels_json` одной темы и `metadata_json` другой (без `rebuild`), items не тронуты | ✅ обе темы `CHANGED`, выход 1 |
| 7e | `items_json` не разбирается как JSON | ✅ `CHANGED <topic_id> (unparsable)`, выход 1; после повторного запуска — снова результат варианта 1 |
| 9 | Штатный рост: после восстановления в бандл добавлен новый элемент через `jsonb` (текст items пересериализован в другом формате), `metadata` дампа сохранена, как у `add_items` | ✅ `match=3 grown=1 stale=0 changed=0`, выход 0, ни `STALE`, ни `CHANGED` |
| 10 | В дампе есть текущая строка с `metadata.rebuild` | ✅ `ABORT: 1 dump rows already carry metadata.rebuild` до транзакции, таблица не тронута |
| 8 | Строка дампа с одной заданной датой | ✅ `ABORT: 1 dump rows have exactly one of time_from/time_to` до транзакции |
| — | Неверный sha256 | ✅ выход ≠ 0 до выгрузки, таблица не тронута |

После проверки `tg_parser_test` возвращена в исходное состояние: `topic_bundles` и `topic_cards` пусты, вспомогательная база удалена.

Классификацию строк настоящего дампа (шаги 1–2 скрипта) на хосте проверяли тем же правилом одной командой без записи (§2): `current=1463 snapshot=0 half=0`. Та же команда подтвердила, что `pg_restore` читает прод-дамп со stdin. Счётчик `metadata.rebuild` по настоящему дампу не снимался; скрипт проверяет его сам перед транзакцией.
