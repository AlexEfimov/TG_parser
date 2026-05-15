# tg-parser — Data Quality Report

**Snapshot date:** 2026-05-14 (после Phase 8 — финальное состояние сессии)
**Total:** 9 каналов, 3 workspaces, 11,220 documents, **641 topics**, **746 topic links**, **795 keyword overlaps**, 4 watchlists, 1 digest

---

## 1. Состояние каналов

| Канал | Workspace | Raw | Processed | Topics | Coverage | Singletons | Clusters |
|---|---|---:|---:|---:|---:|---:|---:|
| Lab4health | Лабдиагностика | 1 845 | 1 827 | **171** | **99.78%** | 131 | 40 |
| **profendocrinologist** | Эндокринология | 3 443 | 3 442 | 111 | 98.66% | **7** ✨ | 104 |
| AgeManagment | Longevity | 1 105 | 1 100 | 89 | 94.64% | 27 | 62 |
| labdiagnostica_logical | Лабдиагностика | 1 164 | 1 148 | 84 | 94.16% | 13 | 71 |
| **kdl_ru** | Лабдиагностика | 842 | 841 | 46 | 90.49% | 12 | 34 |
| mind_rise | Longevity | 1 111 | 1 111 | 45 | 98.47% | 8 | 37 |
| LongevityClub | Longevity | 339 | 339 | 38 | 99.12% | 21 | 17 |
| genotek | Лабдиагностика | 1 109 | 1 104 | 36 | 99.00% | 6 | 30 |
| foodf4thought | Longevity | 310 | 308 | 21 | **80.52%** | 3 | 18 |
| **ИТОГО** | | **11 268** | **11 220** | **641** | **средн. ~95%** | **228** | **413** |

✨ — у profendocrinologist singletons появились после Phase 8 incremental (раньше было 0). Аномалия A1 разрешена.

### Эволюция за сессию

| Канал | Topics до → после | Coverage до → после |
|---|---|---|
| Lab4health | 166 → **171** | 93.05% → **99.78%** |
| profendocrinologist | 0 (new) → **111** | 0% → 98.66% |
| AgeManagment | 75 → **89** | 74.73% → **94.64%** |
| labdiagnostica_logical | 79 → **84** | 77.61% → **94.16%** |
| kdl_ru | 0 (new) → **46** | 0% → 90.49% |
| mind_rise | 43 → **45** | 86.86% → 98.47% |
| LongevityClub | 36 → **38** | 89.38% → 99.12% |
| genotek | 32 → **36** | 84.15% → **99.00%** |
| foodf4thought | 10 → **21** | 53.90% → **80.52%** |
| **Всего** | **до сессии: 441 → финал: 641 (+200)** | **средн. ~95%** |

### Аномалии — состояние

#### A1 (РАЗРЕШЕНА): profendocrinologist singletons

Раньше: `singleton_count: 0`. Сейчас: **7 singletons**. Гипотеза подтвердилась: full без cross-channel даёт 0 singletons, incremental с cross-channel context — создаёт singletons естественно. См. O-11 в enhancements.md.

#### A2 (РАЗРЕШЕНА): profendocrinologist coverage

Раньше: 75.60% при 92 темах. Сейчас: **98.66%** при 111 темах. Incremental + cross-channel дотянул coverage почти до потолка системы. Оставшиеся 1.34% — это нормальный «хвост» (короткие посты, объявления).

#### A3 (ЧАСТИЧНО РАЗРЕШЕНА): foodf4thought slabое звено

Coverage поднялся с 53.9% до **80.5%**, top keywords улучшились: появились **предметные термины** `mind-body`, `wellness-туризм`, `велнеса` (см. O-12 в enhancements.md). Но **65 docs остаются unassignable** — это реальный потолок для канала. Возможно, контент слишком короткий и общий. Дальнейшие улучшения возможны через full `--force` или принять как baseline.

#### A4 (НОВАЯ, ОТКРЫТА): «Topic failed quality criteria, skipping» — silent reject

В incremental режиме на AgeManagment, labdiagnostica_logical и genotek наблюдалось отбрасывание предлагаемых тем без указания причины. Может скрывать полезных кандидатов. См. ISSUE-11 в bug-report.md.

---

## 2. Состояние workspaces

### Лабораторная диагностика (4 канала)

| Метрика | Значение |
|---|---:|
| Каналов | 4 |
| Documents | 4 920 |
| Topics | **337** (было 323) |
| Avg coverage | **95.86%** (было 86.43%) |

Каналы: Lab4health, labdiagnostica_logical, kdl_ru, genotek.

Сильный workspace. Тематика сфокусирована: лабораторные методы, диагностика, маркеры. Все каналы > 90% coverage. Кросс-связи внутри workspace очень содержательные (helicobacter+pylori, anti+aller, B12, etc.).

### Longevity (4 канала)

| Метрика | Значение |
|---|---:|
| Каналов | 4 |
| Documents | 2 858 |
| Topics | **193** (было 164) |
| Avg coverage | **93.19%** (было 76.22%) |

Каналы: AgeManagment, mind_rise, LongevityClub, foodf4thought.

После Phase 8 workspace выровнялся. foodf4thought всё ещё отстаёт (80.5%), но остальные > 94%. Самый концентрированный канал — LongevityClub (38 топиков на 339 docs, 99.1% coverage).

### Эндокринология (1 канал)

| Метрика | Значение |
|---|---:|
| Каналов | 1 |
| Documents | 3 442 |
| Topics | **111** (было 92) |
| Avg coverage | **98.66%** (было 75.60%) |

Один канал, но самый большой. После incremental прошёл с 75.6% до 98.66% coverage, появились 7 singleton-тем. Высокоспециализированный профессиональный канал, теперь полностью топикизирован.

---

## 3. Cross-channel связность

### По keywords (через `get_cross_channel_stats`)

- **Total overlaps:** **795** (было 718, +77)
- Большинство — между парами/тройками каналов
- Сквозные (5-7 каналов): `анализ`, `активность`, `безопасность`, `covid-19`

### По topic_links (через `link-topics`)

- **Total links:** **746** (было 708, +38)
- **Threshold:** 0.3
- **Avg similarity:** 0.3352 (было 0.3345)
- **Pairs evaluated:** **173 510** (было 140 485)
- **Семантика:** truncate-and-rebuild (Cleared 746 = Created 746 — см. O-10)

Сильные пары (по наблюдению, без полного перебора):
- profendocrinologist ↔ kdl_ru (микробиота, B12)
- profendocrinologist ↔ LongevityClub (GLP-1, метаболизм)
- kdl_ru ↔ labdiagnostica_logical (методы, маркеры)

### ⚠️ Note: Phase 3 incremental тоже создаёт links

Из сессии 2026-05-14: каждый incremental-прогон создаёт cross-channel links для новых тем (см. O-9). За Phase 8 было создано:
- profendocrinologist: 128 links
- labdiagnostica_logical: 124
- Lab4health: 105
- AgeManagment: 99
- mind_rise: 68
- foodf4thought: 31
- LongevityClub: 26
- genotek: 26
- **Итого Phase 3 (incremental): 607 links** перед финальным link-topics

После финального truncate-and-rebuild `link-topics` все эти links были пересозданы вместе с links для существующих тем. Финал: 746 links.

### ⚠️ Limitation

`get_cross_channel_stats` сейчас не использует `topic_links` (см. ISSUE-8). Реальная семантическая связность недооценена в текущем endpoint'е.

---

## 4. Top keywords by channel — экспертная оценка

### Высоко содержательные (профессиональная лексика)

**profendocrinologist:**
`17-гсдг-3, 46,xy, bimagrumab, 25(oh)d, bethesda, BRAF`
→ узкоспециальные эндокринологические термины.

**labdiagnostica_logical:**
`b12, clia, helicobacter, igg, mar-тест, mchc, pandas, prisca, pylori, авидность`
→ лабораторные методы и маркеры.

**genotek:**
`car-t, crispr, herc2, oca2, polg-мутации, t-лимфоцитов, y-хромосома`
→ генетика, иммунология.

### Средне содержательные

**Lab4health, kdl_ru, mind_rise, AgeManagment, LongevityClub** — смесь предметной лексики и общих слов.

### Низко содержательные (но улучшаются итеративно)

**foodf4thought:**

До Phase 8 incremental: `благополучие, вебинары, влияние, восприятие, врачей, гормональное, городской, для, доказательная` → почти все — общая лексика.

После Phase 8 incremental: `mind-body, wellness-туризм, активация, активный, благополучие, вебинары, велнеса, вкус, влияние, влияния` → появились предметные термины `mind-body`, `wellness-туризм`, `велнеса`.

**Подтверждено:** keyword extraction зависит от существующих topic-cards канала, и itерacция incremental → новые темы → keywords из их title постепенно улучшает quality. См. O-12 в enhancements.md.

---

## 5. Keyword overlap noise

В выдаче `get_cross_channel_stats` много шумовых overlap-записей:

### Стоп-слова (нужна фильтрация):
- `анализ` (7 каналов)
- `активность` (6)
- `безопасность` (6)
- `аспекты` (4)
- `влияние`, `влияния`, `восприятие` (foodf4thought-driven)

### Грамматические дубли (нужна лемматизация, см. ISSUE-9):
- `аллергия` / `аллергии` / `аллергические`
- `анализ` / `анализа` / `анализам` / `анализов` / `анализы`
- `адаптация` / `адаптации`
- `бад` / `бады`
- `бактерии` / `бактериальные`
- `белки` / `белков`

После лемматизации `overlap_count` снизится с 795 до ~550-600 при сохранении информативности.

---

## 6. Готовность системы

### ✅ Готово
- Все 9 каналов прошли ingest + process + topicize
- Все 3 workspaces полностью затопикизированы
- Topic links построены (746)
- Coverage везде > 80%, у 7 из 9 каналов > 94%
- Cross-channel analytics работает (с оговорками)
- 4 watchlist + 1 digest активны

### ⚠️ Требует внимания
- ISSUE-3': `--skip-topicize` в шедулере → новые посты не топикизируются автоматически (by design, но мешает)
- ISSUE-8: `get_cross_channel_stats` не отражает реальной связности (не использует topic_links)
- ISSUE-11: «Topic failed quality criteria, skipping» — отбрасывание без causa
- foodf4thought упирается в 80% coverage (см. A3)

### ❌ Известные проблемы
- ISSUE-1: MCP `trigger_pipeline` silent no-op
- ISSUE-7: CLI `topicize` рапортует success при fail
- ISSUE-9: keywords не лемматизированы
- ISSUE-10: subscribe_* не идемпотентны

---

## 7. Активные подписки

### Watchlists (4 шт.)

| Title | Каналов | Threshold | UUID |
|---|---:|---:|---|
| GLP-1 агонисты и семаглутид | 3 | 0.6 | `9f23fd49-8794-427d-a5c0-235a24e175cb` |
| Микробиота и кишечный микробиом | 6 | 0.6 | `62a994b2-e166-491c-8e2e-065c7bf5be78` |
| Биомаркеры старения | 5 | 0.6 | `ab6ab349-89a5-453e-864d-f6396d63630c` |
| mTOR и геропротекторы | 3 | 0.6 | `42df2709-0055-4398-b866-67ee4ad05f6f` |

**chat_id:** 5445781511 (личный диалог owner с ботом)

**Параметры:**
- Все active, threshold 0.6, notify_mode `instant`
- Description прописан везде (улучшает embedding-based recall)
- Channel selection делается тематически, не «все 9»

### Digest (1 шт.)

| Name | Каналы | Schedule | Timezone | Format |
|---|---|---|---|---|
| Эндокринология — ежедневный дайджест | profendocrinologist | `0 9 * * *` | Europe/Nicosia | summary |

UUID: `94483db9-9351-4f99-9aec-46949d9ddd09`

### Покрытие каналов подписками

| Канал | В скольких watchlist'ах | Digest |
|---|---:|---|
| profendocrinologist | 2 (GLP-1, Микробиота) | ✅ |
| LongevityClub | 4 (все) | — |
| AgeManagment | 3 (GLP-1, Биомаркеры, mTOR) | — |
| mind_rise | 3 (Микробиота, Биомаркеры, mTOR) | — |
| Lab4health | 2 (Микробиота, Биомаркеры) | — |
| kdl_ru | 1 (Микробиота) | — |
| foodf4thought | 1 (Микробиота) | — |
| genotek | 1 (Биомаркеры) | — |
| labdiagnostica_logical | 0 | — |

**Наблюдение:** `labdiagnostica_logical` не покрыт ни одним watchlist. Это сознательно: канал про методы лабдиагностики (масс-спектрометрия, ИФА), темы из watchlist'ов туда плохо ложатся. Если в будущем добавятся темы вроде «лабораторная диагностика гормональных нарушений» — стоит включить.

### ⚠️ Известные ограничения

1. **Forward-only:** watchlist'ы не сканируют исторические 11,220 документов (O-4). Match'и появятся со следующего scheduler tick (~через час) и только для новых постов.
2. **Не идемпотентны** (ISSUE-10): повторный subscribe создаст дубль.
3. **Не workspace-bound** (O-5, ENH-9): подписки на каналы, а не workspaces.

---

## 8. Метрики, которые стоит регулярно отслеживать

### Дневные
- Сумма raw_messages во всех каналах (прирост в день)
- Сумма tokens spent на Anthropic API (через processing-этап pipeline_service логи)
- fail_count по каналам

### Недельные
- coverage_percent по каналам (должен расти или быть стабильным)
- topics_count по каналам (должен расти при добавлении новых постов)
- total_links после link-topics (растёт с topics, но нелинейно — pairs масштабируются квадратично, ratio ~0.4-0.5% от всех пар при threshold 0.3)
- avg_similarity links (стабилен ~0.33, дрейф вверх/вниз — сигнал изменения характера системы)

### При необходимости
- average items_count per topic (если стабильно 102-103 — проверить, не упирается ли в технический потолок)
- ratio singletons/clusters (по каналам — драматическое изменение сигналит о смене характера канала)
- **Phase 1 hit rate при incremental** (низкие значения < 20% — сигнал слабого keyword extraction для канала)
- **Quality filter rejected count** при incremental (если ISSUE-11 будет исправлен)

---

## 9. Capacity & Cost forecasting

### Current state cost (итог сессии 2026-05-14)

Полная стоимость, инвестированная в данные:
- Processing (один scheduler tick всех каналов): ~$2
- kdl_ru full topicize: **$1.67** (факт)
- profendocrinologist full topicize: **~$7** (приблиз.)
- Phase 8: 8 incremental по всем каналам (кроме profendocrinologist первого прогона): **~$4-5**
- link-topics × 2: **$0**
- Watchlist + digest setup: **$0**
- **Total: ~$15** за всю сессию

### Калибровка

После сессии 2026-05-14 есть надёжные точки калибровки:
- **Full topicize:** ~$0.0020 за document
- **Incremental topicize:** **~$0.003 за uncovered document** (Phase 2 LLM cost; Phase 1 + Phase 3 бесплатны)
- **Pre-flight estimate:** см. раздел 7 в operational-runbook.md

### Forecast при росте

| Сценарий | Triggered cost |
|---|---|
| +1 small channel (300 docs) | $0.60 full topicize + $0.10 process per cycle |
| +1 medium channel (1500 docs) | $3.00 full topicize + $0.50 process per cycle |
| Full re-topicization всей системы (11 220 docs) | ~$23 |
| **Maintenance — incremental по всем 9 каналам раз в неделю** | **~$4-5/неделя** |
| Daily processing (incremental, scheduler) | <$1/day |

### Стратегические выводы по стоимости

1. **Full только при первом добавлении канала** — больше никогда (если не нужен полный re-topicize)
2. **Maintenance via incremental — основной паттерн** для актуализации
3. **link-topics — бесплатный** инструмент, не сдерживайтесь от частого использования при изменениях
4. **При мониторинге Anthropic balance** держите минимум $30 запас (3× недельный maintenance + queue для emergencies)

### Recommendations

1. **Поставить billing alert** в Anthropic Console на $10 минимум, $50 рекомендуемо
2. **Не запускать `--force` re-topicize** без оценки
3. **Отслеживать `tokens=` в логах процессинга** — резкий рост значит больше новых постов (нормально) или дрейф в длину постов (внимание)
