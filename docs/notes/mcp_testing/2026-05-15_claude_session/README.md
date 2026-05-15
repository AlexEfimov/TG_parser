# tg-parser — Session 2026-05-14: Documents Index

Полный набор документов, созданных по итогам сессии расследования и работы с tg-parser 2026-05-14.

## Документы в этой папке

| # | Файл | Назначение |
|---|---|---|
| 01 | `01-bug-report.md` | 11 issue (1 retracted, 10 активных) для bug tracker |
| 02 | `02-enhancements.md` | 13 предложений по улучшениям + 12 архитектурных наблюдений |
| 03 | `03-investigation-log.md` | Хронология расследования (8 фаз) + lessons learned |
| 04 | `04-operational-runbook.md` | 8 типовых операций с системой |
| 05 | `05-data-quality-report.md` | Финальный снапшот данных, метрик и активных подписок |

---

## Финальная статистика системы (2026-05-14, конец сессии)

| Метрика | Значение |
|---|---:|
| Каналов | 9 |
| Workspaces | 3 |
| Total documents | 11 220 |
| Total topics | **641** |
| Cross-channel topic links | **746** |
| Keyword overlaps | **795** |
| Watchlists | 4 |
| Digests | 1 |
| **Coverage** | **средн. ~95%** (от 80.5% до 99.8%) |
| Затраты на сессию | ~$15 |

---

## Priority items для следующей итерации

### Critical (нужно решить до production scale)

1. **ISSUE-1** — MCP `trigger_pipeline` silent no-op
   Главный архитектурный баг. Без фикса MCP-интеграция неполноценна.

2. **ISSUE-7** — CLI `topicize` рапортует ✅ при тотальном fail
   Опасно для автоматизации.

3. **ISSUE-10** — `subscribe_*` не идемпотентны
   Опасно для automation. Повторный запуск скрипта создаёт дубли подписок → двойные пуши.

### High (UX и safety)

4. **ISSUE-3'** — misleading log `[3/4] Topicization skipped (--skip-topicize)`
   Один из главных «time-sink» багов сессии. Простой фикс.

5. **ENH-5** — Cost-control flag (`--max-cost-usd`) для топикизации
   Защита от непреднамеренных расходов. Особенно важно учитывая auto-adjusted rate limit (O-8).

6. **ENH-1** — MCP `trigger_topicization`
   Закрывает architectural gap, позволит автоматизировать weekly maintenance.

7. **ENH-9** — Workspace-bound subscriptions (digest + watchlist)
   Сейчас подписки только на channel_ids; добавление каналов в workspace не отражается.

### Medium

8. **ISSUE-4** — `last_attempt_at` не обновляется
9. **ISSUE-8** — `get_cross_channel_stats` игнорирует `topic_links`
10. **ISSUE-11** — «Topic failed quality criteria, skipping» без указания причины
11. **ENH-12** — Backfill scan для watchlists на исторические данные
12. **ENH-13** — Preview / dry-run для watchlist перед созданием
13. **ENH-3** — Health-check для stuck active sources
14. **ENH-6** — Pre-flight cost estimate

### Low

15. Остальные ISSUE и ENH — по мере возможности

---

## Quick-win plan

Самое полезное за минимум усилий:

1. ✅ **Поправить misleading log** (ISSUE-3') — 5 минут, экономит часы будущих debug-сессий
2. ✅ **Поправить CLI exit code при failed batches** (ISSUE-7) — 30 минут, защищает от silent failure в автоматизации
3. ✅ **Добавить idempotency на subscribe_*** (ISSUE-10) — 1 час, защищает от дублей в автоматизации
4. ✅ **Логировать reason для "Topic failed quality criteria"** (ISSUE-11) — 30 минут
5. ✅ **Логировать rate_limit adjustment как WARN, не INFO** (часть O-8) — 5 минут
6. ✅ **Добавить billing alert в Anthropic Console** — 2 минуты (не часть кода)

После этого — браться за ISSUE-1 (это уже архитектурное изменение, требует продумывания) и ENH-1.

---

## Operational status — что сделано в сессии

| Действие | Результат |
|---|---|
| Создан workspace «Лабораторная диагностика» | ✅ 4 канала |
| Создан workspace «Longevity» | ✅ 4 канала |
| Создан workspace «Эндокринология» | ✅ 1 канал |
| Добавлен канал `@profendocrinologist` | ✅ ingest + process |
| Топикизирован `kdl_ru` (full) | ✅ 46 тем, $1.67 |
| Топикизирован `profendocrinologist` (full) | ✅ 92 тем, ~$7 |
| Топикизированы все 9 каналов (Phase 8 incremental) | ✅ +62 новых тем, ~$5 |
| Запущен `link-topics` × 2 | ✅ 708 → **746 связей** |
| Создан watchlist «GLP-1 и семаглутид» | ✅ 3 канала |
| Создан watchlist «Микробиота» | ✅ 6 каналов |
| Создан watchlist «Биомаркеры старения» | ✅ 5 каналов |
| Создан watchlist «mTOR и геропротекторы» | ✅ 3 канала |
| Создан digest «Эндокринология» | ✅ 9:00 ежедневно Europe/Nicosia |
| Зафиксированы 10 активных issue + 13 enhancement + 12 observations | ✅ Эти документы |

**Total cost:** ~$15 за всю сессию.

---

## Контекст для будущих сессий

### Что знать про систему

- **Шедулер** (APScheduler в `tg_parser` container) тикает `incremental_pipeline` раз в час
- **Топикизация автоматически НЕ делается** — by design (`--skip-topicize` хардкод в scheduler_service.py:112), нужно вручную через CLI
- **Cross-channel linking** запускается отдельно через `link-topics`, бесплатно, быстро (~46 сек)
- **Phase 3 incremental** уже создаёт cross-links для новых тем (см. O-9) — link-topics не нужен после обычного incremental
- **link-topics — truncate-and-rebuild** (см. O-10) — Cleared = Created, любые edits будут утеряны
- **Rate limit auto-adjusts** от 50 → 4000 rpm (см. O-8) — может скрытно поднять burst cost
- **MCP — отдельный контейнер**, имеет архитектурную асимметрию (см. ISSUE-1)
- **Subscriptions forward-only**, не сканируют исторические данные (см. O-4, ENH-12)

### Что знать про данные

- **641 топиков, 11 220 документов, 746 cross-channel links** на 2026-05-14 (финал сессии)
- **9 каналов** в 3 workspaces, все coverage > 80%
- **profendocrinologist** — крупнейший канал (3442 docs, 111 топиков, coverage 98.7%)
- **foodf4thought** — упирается в 80% coverage из-за слабого keyword extraction (A3)
- **Phase 1 hit rate** — индикатор предметности keywords (77% у profendocrinologist vs 4% у foodf4thought)
- **Singletons** — индикатор зрелости топикизации (full → 0, incremental → 5-15%)

### Что знать про стоимость

- **~$0.0020 за document** на full topicize (Sonnet 4)
- **~$0.003 за uncovered document** на incremental topicize (только Phase 2)
- **~$4-5/неделя** на maintenance via incremental по всем каналам
- **~$23** на полную re-topicization всей системы
- **<$1/день** на incremental updates при текущем темпе
- **Watchlist / digest / link-topics / Phase 3 incremental — $0** (используют готовые данные, без LLM)

---

## Передача в Cursor

Все эти документы предназначены для копирования в проект (например `docs/sessions/2026-05-14/`) или в систему задач:

```bash
# Скопировать в проект:
cp /path/to/these/docs ~/TG_parser/docs/sessions/2026-05-14/

# Или открыть в Cursor для интеграции с issue tracker
```

Для bug tracker особенно полезен файл `01-bug-report.md` — каждый ISSUE отформатирован под перенос в отдельный тикет.

Документ `04-operational-runbook.md` — рабочая инструкция для maintenance: добавление каналов, инкрементальные апдейты, восстановление после инцидентов.

Документы `02-enhancements.md` и `05-data-quality-report.md` — материал для planning следующих итераций разработки и улучшения качества данных.
