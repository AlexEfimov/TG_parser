# tg-parser — Investigation Log

**Session date:** 2026-05-14
**Investigator:** alexanderefimov + Claude (read-only mode)
**Original trigger:** добавлен канал `@profendocrinologist`, не появился в обработке через 5 минут

---

## Цель документа

Зафиксировать методику и хронологию расследования. Этот документ — methodological reference: какие шаги в каком порядке привели к каким выводам, какие гипотезы оказались верными/неверными. Полезен:
- Для будущих похожих расследований
- Для обучения других участников проекта
- Как пример того, как **легко неправильно диагностировать** silent failure

---

## Хронология (UTC)

### Phase 1: Initial state setup (05:30 – 05:43)

| Время | Действие | Результат |
|---|---|---|
| 05:40:50 | `create_workspace "Лабораторная диагностика"` | id `a1a7584c-...` |
| 05:40:54 | `create_workspace "Longevity"` | id `fb59c536-...` |
| 05:40:55 – 05:41:00 | 8× `add_workspace_source` | 4 канала → Лабдиагностика, 4 → Longevity |
| 05:43:47 | `create_workspace "Эндокринология"` | id `00ccbfb0-...` |
| 05:44:xx | `add_channel "profendocrinologist"` | success, status=active |
| 05:44:xx | `add_workspace_source` для profendocrinologist | added to Эндокринология |
| 05:44:xx | `trigger_pipeline(profendocrinologist)` | `{triggered: true}` |
| 05:50:xx | `get_pipeline_status` через 5 минут | `last_attempt_at: null` ⚠️ |

### Phase 2: First wrong hypothesis (06:00 – 06:30)

**Гипотеза:** silent failure в MCP `trigger_pipeline`. Сразу предложен bug report.

**Тест 1:** Дёрнули `trigger_pipeline` ещё раз → тот же результат.

**Анализ через MCP:**
- `scheduler_enabled: true`, `default_interval_seconds: 3600`
- Решено подождать естественный тик scheduler

**SSH-исследование:**
```
docker compose ps
→ tg_parser (api), tg_bot, tg_parser_mcp, postgres, grafana, prometheus
```

Обратили внимание: **MCP в отдельном контейнере**.

```
docker compose logs tg_parser | grep scheduler
```

Найдены APScheduler джобы:
- `health_check` (5m) — тикает
- `cleanup_expired_records`
- `incremental_pipeline` (1h)
- `incremental_embedding` (1h)

В 20:28 UTC (через час после старта 19:28) `incremental_pipeline` сработал. Следующий — 05:28 UTC. Затем 06:28 UTC.

**Вывод фазы 2:** Шедулер работает корректно. Мы попали в межтиковое окно. **Первоначальное наблюдение «канал не обработался» было false alarm.**

### Phase 3: Discovery of real silent failure (06:30 UTC tick)

После тика в 06:28 UTC:
```
list_channels(profendocrinologist) → raw_messages: 3443 ✅
get_pipeline_status → last_success_at: 06:30:47
```

**Канал обработан шедулером в штатном режиме.** Но при этом:

В логах **нет ни одной строки** про `trigger_pipeline` вызовы в 05:44 и 06:00. То есть MCP → tg_parser **реально не передало запрос**. Это и есть настоящий **ISSUE-1: silent no-op в MCP**.

Архитектурный root cause: MCP в отдельном контейнере, без канала связи к шедулеру в tg_parser. `asyncio.create_task` локально в MCP-процессе либо умирает после возврата ответа, либо клиента Telethon в mcp-контейнере просто нет.

### Phase 4: Second wrong hypothesis — `--skip-topicize` (06:30 – 07:30)

**Наблюдение:** `processed_documents=0` после ingest для `profendocrinologist`. Топиков нет.

**В логах видно:** `[3/4] Topicization skipped (--skip-topicize)` для **каждого канала** в каждом тике.

**Гипотеза:** флаг `--skip-topicize` был включён как mitigation на время билинг-инцидента (вспомнили RCA по genotek) и забыли снять.

**Юзер пополнил баланс → ждём следующего тика.**

В тике 06:28 UTC обработка идёт **с tokens=4929, tokens=11112, tokens=1841** — то есть processing-этап теперь использует Anthropic API. Билинг-инцидент решён. Но `[3/4] Topicization skipped` — всё ещё везде.

**Поиск флага в коде:**
```
grep -rn "skip-topicize\|skip_topicize" --include="*.py" ~/TG_parser/
```

Найдено:
```
tg_parser/services/scheduler_service.py:112: skip_topicize=True,
```

**Это хардкод, а не env-var. Не mitigation, а архитектурное решение.** Топикизация дорогая, шедулер тикает раз в час — by design она вне scheduled job, делается через manual `tg-parser topicize`.

**Вывод фазы 4:** Гипотеза неверна. Лог `[3/4] Topicization skipped (--skip-topicize)` вводит в заблуждение — звучит как «передан флаг», на самом деле это «шедулер не делает топикизацию by design». Это ISSUE-3'.

### Phase 5: Manual topicization (07:30 – 09:00)

**Решение:** запускать топикизацию вручную через CLI.

**Первая попытка (07:33 UTC) — kdl_ru:**
```
docker compose exec tg_parser tg-parser topicize --channel kdl_ru
```

Все 17 батчей упали одновременно с `Your credit balance is too low`. **Баланс снова закончился.**

При этом CLI вывел:
```
✅ Topicization завершён:
   • Создано тем: 0
⚠️ Темы не созданы (возможно, недостаточно данных)
```

**Это ISSUE-7** — misleading success при тотальном fail.

Деньги не потрачены: `total_tokens: 0` — API отбил pre-flight.

**Второе пополнение баланса. Вторая попытка — kdl_ru:**

Успех:
- 46 топиков
- coverage 90.49%
- input_tokens: 306,754 + output_tokens: 50,172 = $1.67

**Калибровка стоимости.** Линейный прогноз для profendocrinologist (3440 docs): ~$6.84.

**Третья попытка — profendocrinologist:**

Успех:
- 92 топика
- coverage 75.60%
- Очень содержательные темы по эндокринологии

### Phase 6: Cross-channel analysis (09:00 – конец фазы)

**`link-topics`:**
- 708 links создано из 140,485 пар
- threshold 0.3, avg similarity 0.3345
- Бесплатно (Jaccard + cosine на готовых данных)
- 40 секунд работы

**Тестирование `get_related_topics`** на эндокринологической теме «Микробиота»:
- 5 связей с 4 каналами
- Топовая связь (0.41) — keyword-overlap пустой, чистая embedding-similarity

**`get_cross_channel_stats`:**
- 718 keyword overlaps
- Идентичная картина до и после link-topics → **endpoint не использует topic_links** (ISSUE-8)
- Дублирующиеся keywords в overlap из-за отсутствия лемматизации (ISSUE-9)

### Phase 7: Subscription setup (после возобновления работы)

Настройка watchlist и digest. Получили `chat_id = 5445781511` через `@userinfobot`.

**Обнаружения по архитектуре подписок:**

1. **`subscribe_*` принимают только `channel_ids`, не `workspace_id`.** То есть «дайджест workspace» в чистом виде невозможен, нужно явное перечисление каналов. Подтверждение ENH-9 (теперь High priority).

2. **`subscribe_*` не идемпотентны.** Повторный вызов с теми же параметрами создаёт новую подписку. В отличие от `add_workspace_source` (корректный idempotent). Новый ISSUE-10.

3. **Watchlist forward-only.** После создания `get_watchlist_matches` возвращает 0 — даже хотя в системе 11,220 готовых документов. Логика инкрементальная, исторический backfill не делается. O-4, ENH-12.

4. **Description критичен для embedding.** Если не задан — embedding строится из title+keywords. Все 4 watchlist'а в сессии получили развёрнутый description. O-6.

**Созданы:**
- 4 watchlist (GLP-1, Микробиота, Биомаркеры, mTOR) — детали в data-quality-report.md
- 1 digest для Эндокринологии (ежедневно 9:00 Europe/Nicosia)

Watchlist'ы заработают со следующего scheduler tick.

### Phase 8: Massive incremental topicization + финальный link-topics

После закрытия первой версии документов решили пройти дотопикизацию всех каналов в incremental режиме, чтобы устранить аномалии (A1, A3) и повысить coverage.

**Порядок (от меньшего к большему):**

1. **`profendocrinologist` (incremental)** — 840 uncovered → Phase 1: 647 assigned (77% hit rate), Phase 2: 80 assigned + 19 new topics, 51 unassignable. Phase 3: 128 cross_links. Coverage 75.6% → **98.7%**. Появились первые 7 singletons (разрешение аномалии A1).

2. **`foodf4thought` (incremental)** — 142 uncovered → Phase 1: 6 (4% hit rate), Phase 2: 37 + 11 new, 65 unassignable. Phase 3: 31 cross_links. Coverage 53.9% → **80.5%**. **Подтверждение** что keyword extraction для канала работает плохо: только 4% hit rate в Phase 1 vs 77% у profendocrinologist.

3. **`AgeManagment` (incremental)** — 278 uncovered → Phase 1: 39 (14% hit rate), Phase 2: 122 + 14 new, 64 unassignable. Phase 3: 99 cross_links. Coverage 74.7% → **94.6%**.

   **Здесь впервые наблюдалось** «Topic failed quality criteria, skipping» — 6 раз за прогон. Quality filter отбрасывал некоторые предлагаемые темы, **без указания причины** (новый ISSUE-11).

4. **`labdiagnostica_logical` (incremental)** — 257 uncovered → Phase 1: 121 (47%), Phase 2: 50 + 5 new. Phase 3: 124 cross_links. Coverage 77.6% → **94.2%**.

5. **`Lab4health` (incremental)** — 127 uncovered → Phase 1: 70, Phase 2: 41 + 5 new. Phase 3: 105 cross_links. Coverage 93.0% → **99.8%** (рекорд системы).

6. **`mind_rise` (incremental)** — 146 → Coverage 86.9% → **98.5%**.

7. **`LongevityClub` (incremental)** — 36 → Coverage 89.4% → **99.1%**.

8. **`genotek` (incremental)** — 175 → Coverage 84.1% → **99.0%**.

**Финальный `link-topics`:**
- Pairs evaluated: 173 510 (было 140 485 — +23.5%)
- Cleared 746 / Created 746 — подтверждение что link-topics это **truncate-and-rebuild** (новый O-10)
- Avg similarity 0.3352 (стабильно)

**Архитектурные открытия фазы 8:**
- O-8: rate limiter auto-adjusts от 50 → 4000 rpm
- O-9: Phase 3 incremental уже создаёт cross-links — link-topics не обязателен после incremental
- O-10: link-topics семантически truncate-and-rebuild
- O-11: singletons как индикатор зрелости топикизации
- O-12: foodf4thought keywords улучшились после incremental
- ISSUE-11: «Topic failed quality criteria, skipping» — без указания причины

**Phase 1 hit rate как индикатор качества keyword extraction канала:**

| Канал | hit rate | Природа |
|---|---:|---|
| profendocrinologist | 77% | Сильная предметная лексика |
| labdiagnostica_logical | 47% | Хорошая лабораторная терминология |
| genotek | 69% | Сильные генетические термины |
| Lab4health | 55% | Хороший mix |
| mind_rise | 67% | Стабильная wellness-лексика |
| AgeManagment | 14% | Слишком специфические редкие keywords |
| LongevityClub | 11% | Слишком специфические редкие keywords |
| foodf4thought | 4% | Общая лексика, не предметная |

**Итог сессии:**
- 441 (до сессии) → 641 topics (+200 за всю сессию)
  - +46 от full kdl_ru (новый channel)
  - +92 от full profendocrinologist (новый channel)
  - +62 от Phase 8 incrementals по всем 9 каналам
- 175 → 746 cross-channel links (+571)
- 718 → 795 keyword overlaps (+77)
- Все каналы > 80% coverage, большинство > 94%
- Стоимость всех incremental + final: ~$4-5

---

## Lessons Learned

### L1: «Никаких следов» — это симптом, а не отсутствие проблемы

`last_attempt_at = null` и пустые логи — **аномалия**, не «всё в порядке». Когда что-то должно было произойти и не произошло — это всегда баг.

### L2: Сходство симптомов != причинно-следственная связь

Изначальный симптом «канал не обрабатывается» был **совпадением двух разных явлений**:
- ISSUE-1 (silent MCP failure) — реальный баг
- Межтиковое окно scheduler — норма

Час потрачен на гипотезы вокруг scheduler. Только разбор логов показал, что scheduler норм, а MCP молча проглатывает запросы.

### L3: Misleading messages дорого стоят

Сообщение `[3/4] Topicization skipped (--skip-topicize)` стоило **~2 часа времени** на проверку гипотезы про забытый mitigation. Будь сообщение `(scheduler does not auto-topicize by design)` — диагностика была бы за 30 секунд.

Аналогично: `✅ Topicization завершён` при 0 топиков создало момент когда мы могли подумать «темы не создались по data reason».

### L4: Read-only investigation работает

Весь debug сделан без единого изменения на сервере (до фазы топикизации, когда уже понимали, что делаем). Команды `docker compose logs`, `grep`, `docker compose exec ... --help` дали полную картину. **Стоимость расследования: 0.** Это сильная стратегия для production-сервисов.

### L5: Калибровка > прогноз

Прогноз стоимости топикизации `profendocrinologist` сначала был «$15-30», после калибровки на kdl_ru — точно $6.84 (реальный результат пока неизвестен, но порядок верный). **Один малый канал → точная экстраполяция на большой.**

### L6: Сетевая изоляция — баг и фича одновременно

Контейнер MCP отделён от tg_parser сетью внутри docker-compose. Это:
- ✅ безопасно (MCP не имеет доступа к Telethon session)
- ❌ создаёт architectural gap (MCP не может триггерить ingest)

Решение должно быть осознанным: либо MCP вызывает HTTP API tg_parser (новый interface), либо MCP получает доступ к shared queue / event bus.

### L7: by-design vs not-yet-implemented

Несколько раз думали «это баг», на деле — by design:
- `--skip-topicize` хардкод в шедулере → by design (cost control)
- `get_cross_channel_stats` без topic_links → likely just not-yet-implemented (it should know about them after link-topics)

Граница между «фича не сделана» и «фича не нужна по дизайну» неявная. **Любой API должен явно документировать своё поведение.**

### L8: Гипотезы про данные надо проверять, а не доказывать

В Data Quality Report A1 была сформулирована как «у profendocrinologist 0 singletons, возможная причина — full без cross-channel». В Phase 8 эта гипотеза **была явно проверена** — один прогон incremental с cross-channel, singletons появились (0 → 7). Аномалия разрешена.

Это пример хорошего цикла: документ → гипотеза → эксперимент → ответ → обновление документа. Не все аномалии нужно немедленно объяснять — иногда правильно записать «возможная причина» и проверить позже.

### L9: Инкрементальный режим — основная стратегия maintenance

До Phase 8 не было ясно, насколько часто и в каких сценариях запускать incremental. Сейчас понятно:
- Phase 1 hit rate показывает, насколько канал «созревший» в keyword extraction
- Каждый incremental прогон стоит **~$0.0030/uncovered doc**, что в 5-7× дешевле full
- Phase 3 incremental уже делает cross-channel links — link-topics нужен реже, чем казалось
- Quality filter работает молчаливо (ISSUE-11)

**Главный рабочий паттерн:** weekly incremental по всем каналам. Полная сеть из 9 каналов держится за ~$4-5/неделя.

### L10: Многослойные «потолки» в production-системе

В Phase 8 наблюдали несколько технических потолков, которые проявились естественно:
- `items_count` ≈ 100-103 у большинства тем (potential bundle ceiling, O-3)
- foodf4thought ≈ 80% coverage (keyword extraction ceiling, A3)
- rate_limit_rpm = 4000 (после auto-adjust, O-8)
- Phase 1 hit rate от 4% до 77% (предметность лексики канала)

Эти потолки **не баги**, а свойства системы. Полезно их фиксировать в Data Quality Report как baseline — чтобы при следующем замере можно было сразу понять, изменилось ли что-то.

---

## Time accounting

| Фаза | Длительность | Ценность |
|---|---|---|
| Phase 1 (setup) | ~15 мин | High — workspaces созданы |
| Phase 2 (wrong hypothesis scheduler) | ~30 мин | Low — гипотеза не подтвердилась |
| Phase 3 (real bug found) | ~5 мин | High — ISSUE-1 идентифицирован |
| Phase 4 (wrong hypothesis flag) | ~60 мин | Medium — нашли ISSUE-3', но долго |
| Phase 5 (topicization) | ~90 мин | High — оба канала обработаны |
| Phase 6 (cross-channel) | ~30 мин | High — данные ценные |
| Phase 7 (subscriptions) | ~15 мин | High — 4 watchlist + 1 digest активны |
| Phase 8 (massive incremental + final link-topics) | ~25 мин | High — coverage 80-100% везде, +62 topics (incremental), +571 links |
| **Total** | **~4 часа 10 мин** | |

**Производительность recovery:** если бы log message `[3/4] Topicization skipped` был ясным, фаза 4 сократилась бы до 5 минут (= экономия ~50 минут). Это reinforces ROI фикса ISSUE-3'.

**ROI вывод по Phase 8:** массовая incremental-фаза заняла ~25 минут и дала очень большой прирост качества системы (coverage везде > 80%, новый граф 746 cross-channel links). Стоимость — ~$4-5. **Этот workflow можно автоматизировать** через ENH-1 (MCP `trigger_topicization`) + cron — раз в неделю incremental для всех каналов, что поддержит систему в актуальном состоянии.
