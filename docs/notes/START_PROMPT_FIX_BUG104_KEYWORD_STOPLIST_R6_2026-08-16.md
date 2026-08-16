# START PROMPT — R6: BUG-104, стоп-лист keywords и пересчёт линковки

**Дата:** 2026-08-16 · **Сессия:** R6 по [`PLAN_REMEDIATION_BOT_MCP_2026-08-12.md`](PLAN_REMEDIATION_BOT_MCP_2026-08-12.md) §R6, §4 · **Баг:** [BUG-104](BUG_LOG.md) (Low — data quality, F-12)
**Ветка:** prefix `cursor/fix-bug104-keyword-stoplist-r6`

**Goal (одной строкой):** `shared_keywords` и Jaccard больше не считают служебные слова; состав `topic_links` пересчитан целиком, а не «новые по новой шкале, старые со старой».

> Рабочий режим: коммит / PR — только по явному запросу владельца ([`AGENTS.md`](../../AGENTS.md)). Прод: чтения разрешены, запись и `trigger_link_topics` — **только по отдельному GO**. Основной режим — **This Mac**: PR standard (`TEST_POSTGRES=1`) обязателен (app-code repos / linking). Первый шаг — `bash scripts/dev_doctor.sh`. **Песочница:** `ssh prod` и `gh` требуют `required_permissions: ["all"]`; `dev_doctor` из песочницы печатает ложный `MISS ssh prod`. Recreate `tg_parser` сдвигает hourly tick (урок R10) — только после конца тика и по GO. Bot-арм BUG-099, смена метрики cosine+Jaccard, полный re-topicization — **вне scope**.

---

## 0. Opener (вставить в новый чат)

> Стартую сессию R6 — стоп-лист keywords и пересчёт линковки (BUG-104 / F-12).
>
> Прочитай:
> 1. `docs/notes/START_PROMPT_FIX_BUG104_KEYWORD_STOPLIST_R6_2026-08-16.md` — **этот файл целиком**
> 2. `docs/notes/BUG_LOG.md`, запись **BUG-104**
> 3. [`docs/adr/0010-watchlist-keyword-aggregation.md`](../adr/0010-watchlist-keyword-aggregation.md) — **процесс** калибровки (read-only what-if → решение → код), не содержимое watchlist-агрегации
> 4. [`docs/notes/S4_TOPIC_EMBEDDING_THRESHOLD_SIMULATION_2026-07-11.md`](S4_TOPIC_EMBEDDING_THRESHOLD_SIMULATION_2026-07-11.md) + [`scripts/s4_linking_simulation.py`](../../scripts/s4_linking_simulation.py) — ближайший образец скрипта и отчёта
> 5. `docs/notes/PLAN_REMEDIATION_BOT_MCP_2026-08-12.md` §R6, §4, §6 («не включать без пересчёта»)
> 6. `tests/README.md` — default / PR standard
>
> Начни с `bash scripts/dev_doctor.sh`, затем §3.1 (baseline + симуляция). **Код `_extract_keywords` не менять, пока нет отчёта и решения владельца по форме.** Порог симуляции — живой `settings.cross_channel_link_threshold` (**0.32** на проде), не устаревшие «0.3» из ревью и плана. `trigger_link_topics` не вызывать без GO.
>
> Строки в плане — на `f005f93`. Ниже — перечитанные 2026-08-16 с `main` (`92519a7`). Ориентируйся на имена символов; если код уже не такой — скажи вслух, не чини исчезнувшее.

**Состояние на входе** (сверить, а не поверить; inspect 2026-08-16 ~09:20 UTC, после R5 docs `#434`):

| Факт | Что ждать на 2026-08-16 |
|---|---|
| Очередь | Основная цепочка `R8→…→R5` закрыта. Эта — следующая параллельная. Bot-арм BUG-099 открыт, не чинить. BUG-008 `open` by design |
| `main` vs прод | `origin/main` = `92519a7` (docs R5). Код на проде — образ R5 (`3b6072c` / `054fceef30c0…`). Docs-only drift нормален, recreate не нужен, чтобы начать симуляцию |
| Порог | `CROSS_CHANNEL_LINK_THRESHOLD` в прод-`.env` **не задан** → код default **0.32** (S4 fine-sweep). `min(similarity_score)` на проде = **0.3200**. Ревью и план пишут «0.3» — это устарело |
| Корпус | `topic_cards` **2128**, `topic_links` **4411**, avg-sim **0.3523**, max 0.5949 |
| Живое доказательство | `get_related_topics(topic:tg:foodf4thought:post:651)`: в `shared_keywords` есть «для», «как», «его»; связь `mind_rise:550` несёт `shared_keywords=["для"]` при score 0.34 |
| Частоты токенов в `shared_keywords_json` | «для» — **280** связей (2-е место после «диагностика» 331); «при» — **149**; «как» — 35; «его» — 15. Связей, у которых единственный shared-токен = «для»: **27** |
| Workaround | Читать `shared_keywords` как «пересечение лексики», не как «общая тема». После фикса + relink workaround снимается |
| Не ждать | Ни от чего не зависит. Пересечения файлов с закрытыми сессиями нет |

---

## 1. Почему эта сессия существует и почему она сейчас

Сессия #1 увидела стоп-слова в `get_related_topics`. Сессия #3 дошла до строки и поняла, что это не косметика ярлыка: те же токены — множества Jaccard, а Jaccard — 0.4 комбинированного score. Часть связей жива благодаря служебным словам.

Основная цепочка закрыта. R6 независима и единственная, где фикс **без пересчёта делает хуже**: таблица останется со старыми score, новые пары (incremental Phase 3) пойдут по новой шкале. Поэтому симуляция — не «nice to have», а гейт на код.

---

## 2. Что установлено (не переоткрывать)

1. **Одна точка извлечения.** [`_extract_keywords`](../../tg_parser/services/analytics_service.py) `48–59`. Потребители на `92519a7`:
   - [`topic_linking_service.link_topics`](../../tg_parser/services/topic_linking_service.py) `165` — полная пересборка, `delete_all` + `upsert_batch` (`212–218`);
   - [`topicization_service`](../../tg_parser/services/topicization_service.py) same-channel merge `782` и incremental Phase 3 `_run_cross_channel_linking` `2417–2497` — Phase 3 **только upsert**, устаревшие связи **не удаляет**. Сигнатурный default `threshold=0.3` — наследство; живые вызовы из scheduler передают `settings.cross_channel_link_threshold`. **Не** «чинить» этот default в R6;
   - `get_cross_channel_analytics` `144` — считается в запросе, таблицу не читает.
   Поверхности `get_related_topics` (MCP / bot) дефекта не вносят: транслируют `shared_keywords` как есть.
2. **Сегодняшний фильтр — только `len(cleaned) >= 3`.** Теги кладутся целиком (`tag.lower().strip()`), `scope_in` режется по пробелам и `strip(".,;:!?()[]\"'")`. «по» уже отсекается (`test_short_words_filtered`); «для» / «как» / «при» проходят.
3. **Стоп-листа в `tg_parser/` нет.** `rg STOPWORDS\|stop_words\|stopword tg_parser/` по-прежнему пусто. Не чинить это импортом nltk/spacy: `pyproject.toml` / `requirements.txt` без явного запроса владельца не трогать. Список — константа в репозитории.
4. **Порог симуляции и relink — 0.32, не 0.3.** Живое значение = `settings.cross_channel_link_threshold`. В отчёте можно показать столбец 0.30 как чувствительность, но решение и `link_topics()` идут по 0.32.
5. **Jaccard от фильтра может и упасть, и вырасти.** Токен в пересечении уменьшает и ∩, и ∪; токен только в одной стороне уменьшает только ∪ — score растёт, **новые** связи выше порога возможны. Симуляция обязана считать added / removed / score_changed, не только «сколько уйдёт ниже».
6. **Incremental tick relink не заменяет.** После деплоя без полного `link_topics` старые строки с «для» останутся, Phase 3 допишет новые. Пересчёт = путь с `delete_all`: MCP `trigger_link_topics` (внутри — `settings.cross_channel_link_threshold` = **0.32**) или `link_topics(threshold=0.32)`. ⚠️ CLI [`link-topics`](../../tg_parser/cli/app.py) `657–658` имеет `typer.Option(0.3)` — голый `tg-parser link-topics` пересоберёт таблицу на **0.3** и раздует корпус. Relink только MCP или CLI с `--threshold 0.32`.
6a. **Связь с `shared_keywords=["для"]` не обязана исчезнуть.** Комбинированный score = `0.4·Jaccard + 0.6·cosine` (без векторов — чистый Jaccard). После выкидывания «для» пересечение может стать пустым → Jaccard 0 → `combined = 0.6·cosine`. Если cosine ≥ 0.32/0.6 ≈ 0.533, строка **останется** с пустым `shared_keywords`. Это не регресс. Симуляция обязана разделить «ушла ниже порога» и «осталась, ярлык очистился». `dla_alone = 0` после relink означает «больше нет пересечения ровно `["для"]`», а не «27 связей удалены».
7. **df как основной фильтр на этом корпусе опасен.** Топ `shared_keywords` — «диагностика», «здоровье», «профилактика», «медицинских»: высокая df здесь — тема, не шум. df гонять в симуляции как **контраст**, не как default-лечение. Default-кандидат — короткий ru/en стоп-лист служебных слов.
8. **ADR-0010 — про процесс, не про watchlist.** F11 считает свои keywords интереса, `_extract_keywords` не использует. Веса 0.4/0.6 и формула cosine+Jaccard — out of scope (план §R6).
9. **`scripts/` в образ не копируется.** Урок R8: `docker exec … python scripts/…` не работает. Симуляция на проде — `docker cp` скрипта **в уже запущенный** `tg_parser` (у него есть `DATABASE_URL` и сеть к Postgres), затем `docker compose exec -T tg_parser python /tmp/r6_stoplist_simulation.py`. Не `compose run --no-deps`: без сети контейнер не увидит БД. Не править Dockerfile, чтобы положить ops-скрипт в образ. S4 all-pairs на близком корпусе занял **~46 мин** — не убивать по «зависло», не запускать во время `incremental_pipeline`.
10. **Same-channel merge и полный re-topicization — не эта сессия.** Смена `_extract_keywords` повлияет на *будущие* merge; уже принятые loser/survivor не переигрывать. Полный `trigger_topicization` не нужен и не просить «на всякий случай».

---

## 3. Scope — строго в этом порядке

Строки ниже — перечитанные 2026-08-16 с `92519a7`.

### 3.1 Read-only симуляция (гейт; кода продукта ещё нет)

Повторить замер §0 (числа могли уехать на тике). Затем what-if **без записи в БД**.

Образец каркаса — [`scripts/s4_linking_simulation.py`](../../scripts/s4_linking_simulation.py): те же `_jaccard_similarity`, `_cosine_similarity`, `JACCARD_WEIGHT` / `COSINE_WEIGHT`, те же эмбеддинги, что `load_card_embeddings`. Фильтр keywords — **обёртка в скрипте** (baseline = вызов `_extract_keywords` как есть; stoplist/df = вычитание из копии множества). Продуктовый `_extract_keywords` на диске во время симуляции не менять. Не копировать S4-sweep эмбеддингов и merge-losers — другая ось. Пары канонизировать как репозиторий: `sorted((id_a, id_b))`.

Новый скрипт, например `scripts/r6_stoplist_simulation.py`. Считает на всех карточках:

| Схема | Что фильтрует |
|---|---|
| `baseline` | как сейчас (`len >= 3`) |
| `stoplist` | baseline + фиксированный ru/en набор (кандидат ниже) |
| `df` (контраст) | токены с document-frequency выше выбранных порогов (например 0.15 / 0.25 / 0.40 карточек) |

Для каждой схемы, порог **0.32** (и опционально 0.30 / 0.33 как чувствительность):

- сколько пар ≥ порога;
- snapshot-diff против текущей таблицы `topic_links`: added / removed / score_changed / unchanged;
- новый avg-sim;
- сколько сегодняшних связей держатся **только** служебным пересечением (как 27 штук с `["для"]`);
- топ токенов, которые фильтр выкинул бы из `shared_keywords`.

**Сид стоп-листа для первого прогона** (не финальный список — его можно сузить/расширить по отчёту):

```
для при как его её их это этой этот или чем что чтобы также
the and for with from that this are was were
```

Не класть сюда «здоровье», «диагностика», «влияние», «рекомендации» — это содержание корпуса. «при» и «для» — да.

Отчёт — `docs/notes/R6_STOPLIST_LINKING_SIMULATION_2026-08-16.md` (дата по факту прогона). Форма как у S4: таблицы, не проза.

**Стоп.** Показать отчёт владельцу. Форму (стоп-лист / df / оба / стоп) и порог (оставить 0.32 / сдвинуть) **не выбирать в одиночку**.

### 3.2 Решение — записать в BUG-104 до первой правки `_extract_keywords`

В карточку: какая схема, какой итоговый список/порог df, остаётся ли 0.32, прогноз added/removed. Если симуляция говорит «двигать порог» — это отдельная строка решения, не сюрприз в PR.

### 3.3 Red/green, потом правка

Красные тесты **до** изменения `_extract_keywords` (иначе не докажешь, что ловится класс):

1. `scope_in=["материалы для здоровья"]` → в множестве есть «здоровье» / «материалы», **нет** «для».
2. Тег ровно `"для"` не попадает в множество; содержательный тег («Витамин D») остаётся.
3. Jaccard-only (эмбеддингов нет): две карточки с `scope_in=["материалы для здоровья"]` и `["советы для сна"]` — единственный общий токен «для», Jaccard = 1/5 = 0.2 < 0.32 уже сегодня, связь не создаётся. Чтобы тест был красным на текущем коде, пересечение должно давать Jaccard ≥ 0.32: например оба `scope_in=["для"]` (множества `{"для"}`, Jaccard 1.0) → сейчас `link_topics` без эмбеддингов **создаст** связь; после фильтра множеств пустые → связи нет. Не писать тест, который зелёный уже на `len >= 3`.
4. Существующие [`tests/test_analytics_service.py`](../../tests/test_analytics_service.py) `TestExtractKeywords` и [`tests/test_topic_linking_service.py`](../../tests/test_topic_linking_service.py) остаются зелёными — «анализ» / «витамины» не стоп-слова.

Правка — только `_extract_keywords` (плюс константа/модуль списка рядом, не в `mcp_server.py` / `bot/tools.py`). Не менять `_jaccard_similarity`, веса, `link_topics` control flow, Phase 3.

### 3.4 Прогоны

- default;
- **PR standard (`TEST_POSTGRES=1`)** обязателен.
- `max local` не обязателен: дефект не межконтейнерный.

### 3.5 Вне scope

- Смена формулы cosine+Jaccard и весов 0.4/0.6.
- Вынос порога/стоп-листа в `.env`, если для этого нужен новый ключ: ключ обязан попасть в compose allow-list (BUG-092). Проще константа. Если всё же ключ — allow-list в том же PR.
- Новая зависимость (nltk, snowball, pymorphy).
- Полный `trigger_topicization` / same-channel re-merge.
- Bot-арм BUG-099, `get_default_admin()`.
- Watchlist F11 keywords / ADR-0010 aggregation (`topk` vs `mean`).
- Поднимать или отключать statement timeout.

---

## 4. Acceptance criteria

1. Отчёт симуляции в `docs/notes/`, числа сходятся с повторным замером §5 (порядок: карточки, текущие links, avg-sim).
2. Решение по форме и порогу записано в BUG-104 **до** merge кода.
3. Красные тесты §3.3 зелёные; revert `_extract_keywords` к `len >= 3` роняет **только** новые тесты стоп-листа.
4. `default` + PR standard зелёные.
5. После деплоя **и** полного relink (по GO): `get_related_topics` на `topic:tg:foodf4thought:post:651` не содержит токены «для» / «как» / «его» в `shared_keywords`; `dla_alone = 0`; пустой `shared_keywords` при живой связи **допустим**, если так предсказала симуляция (cosine унёс пару). Число `topic_links` в полосе отчёта, не в S4-band 1962–2942.
6. `get_cross_channel_stats` → `keyword_overlaps`: элемента с `keyword="для"` нет (считается live из карточек, проверяется сразу после recreate, ещё до relink).
7. BUG-104 → `resolved` только после п.5. Workaround снят.
8. PLAN §4: R6 задеплоена. Runbook по образцу [`BUG103_R5_DEPLOY.md`](../runbooks/BUG103_R5_DEPLOY.md).

---

## 5. Замеры: чем мерить до и после

Все read-only, `required_permissions: ["all"]`, пока нет GO на relink.

База таблицы:

```bash
ssh prod "docker exec tg_parser_postgres psql -U tg_parser_user -d tg_parser -P pager=off -c \"
SELECT count(*) AS links,
       round(avg(similarity_score)::numeric, 4) AS avg_sim,
       round(min(similarity_score)::numeric, 4) AS min_sim
FROM topic_links;
SELECT count(*) AS cards FROM topic_cards;
\""
```

База 2026-08-16: **4411** / **0.3523** / **0.3200** / **2128** карточек.

Токены-улики:

Проверено 2026-08-16 (внешние кавычки — одинарные у `ssh`, внутри SQL строки в `'\''…'\''`):

```bash
ssh prod 'docker exec tg_parser_postgres psql -U tg_parser_user -d tg_parser -P pager=off -c "
SELECT token, count(*) AS links
FROM topic_links, jsonb_array_elements_text(shared_keywords_json::jsonb) AS token
WHERE token IN ('\''для'\'','\''при'\'','\''как'\'','\''его'\'')
GROUP BY token ORDER BY links DESC;
SELECT count(*) FILTER (WHERE shared_keywords_json::jsonb = '\''[\"для\"]'\''::jsonb) AS dla_alone
FROM topic_links;
"'
```

База: для 280, при 149, как 35, его 15, `dla_alone` **27**.

Живая поверхность (после relink — те же id):

- MCP `get_related_topics(topic_id="topic:tg:foodf4thought:post:651")`
- MCP `get_cross_channel_stats` — keyword overlaps без «для»

После relink ожидание: `dla_alone` = 0; «для»/«как»/«его»/«при» не в топ-40 shared; count links ≈ прогноз симуляции, не 4411 «на глаз». Падение count на 27 — **не** критерий: часть `dla_alone` удержит cosine.

---

## 6. Деплой и пересчёт (после merge, по GO)

Миграции нет. Общий образ → recreate `tg_parser` + `mcp` + `tg_bot` (`--force-recreate`, не `restart`). Backup + тег `pre-r6-…` как в R5.

`trigger_link_topics` — **второй GO**, в списке опасных прогонов [`DECISION_AUDIT_AND_STRATEGY_SESSIONS_2026-08-12.md`](DECISION_AUDIT_AND_STRATEGY_SESSIONS_2026-08-12.md) §5.3. Не запускать, пока в логах `tg_parser` идёт `incremental_pipeline` или другой `link_topics`: `delete_all` гоняется с Phase 3 upsert. Якорь сетки — `Scheduler started` + 3600 с. MCP `channel_id` — только RBAC, линковка всеканальная. CLI без `--threshold 0.32` — запрещён (§2.6). Relink all-pairs на 2k карточек — минуты, не секунды; ориентир S4 ~46 мин на симуляцию, запись короче, но не «сразу».

Откат кода: тег образа. Откат таблицы: повторный `link_topics` на старом образе (backup `topic_links` до relink — дешевле, чем полный postgres dump, но dump по `PRODUCTION_DEPLOYMENT.md` всё равно делается перед recreate).

---

## 7. Ограничения (CRITICAL)

- Не менять `_extract_keywords` до отчёта симуляции и решения в BUG-104.
- Не вызывать `trigger_link_topics` / `trigger_topicization` / `trigger_pipeline` без GO.
- Не подменять порог 0.32 «как в ревью, 0.3». Не запускать CLI `link-topics` без `--threshold 0.32`.
- Не включать df основным фильтром, не показав, что он не выкидывает «здоровье» / «диагностика».
- Не добавлять зависимости и не править `pyproject.toml` / `requirements.txt`.
- Не трогать `docs/methodology/**`.
- Не трогать `get_default_admin()` и bot-арм BUG-099.
- Коммит и PR — по явному запросу владельца.

---

## 8. Финальный ответ сессии

Одним сообщением: какая схема выбрана и почему не другая; таблицы симуляции (added/removed/avg-sim @ 0.32); результаты двух прогонов; что сделано с `_extract_keywords`; отдельной строкой — нужен ли GO на relink сейчас и какой прогноз по числу связей. Если relink ещё не было — BUG-104 остаётся не `resolved`.

---

## 9. Ссылки

- [BUG-104](BUG_LOG.md); ревью F-12 — [`CODE_REVIEW_BOT_MCP_2026-08-12.md`](CODE_REVIEW_BOT_MCP_2026-08-12.md).
- [`PLAN_REMEDIATION_BOT_MCP_2026-08-12.md`](PLAN_REMEDIATION_BOT_MCP_2026-08-12.md) §R6, §4, §6.
- [`docs/adr/0010-watchlist-keyword-aggregation.md`](../adr/0010-watchlist-keyword-aggregation.md) — процесс what-if.
- [`docs/adr/0016-near-duplicate-dedup.md`](../adr/0016-near-duplicate-dedup.md) — исторический avg-sim 0.33 (корпус с тех пор вырос).
- `tg_parser/services/analytics_service.py` — `_extract_keywords` `48–59`.
- `tg_parser/services/topic_linking_service.py` — `_jaccard_similarity` `100–107`, `link_topics` `126–231`.
- `tg_parser/services/topicization_service.py` — merge `782`, `_run_cross_channel_linking` `2417–2497`.
- `tg_parser/cli/app.py` — `link-topics` default **0.3** `657–658` (ловушка relink).
- `tg_parser/config/settings.py` — `cross_channel_link_threshold` default **0.32** `605–610`.
- `tests/test_analytics_service.py`, `tests/test_topic_linking_service.py`, `tests/test_cross_channel_topicization.py`.
- [`tests/README.md`](../../tests/README.md).
