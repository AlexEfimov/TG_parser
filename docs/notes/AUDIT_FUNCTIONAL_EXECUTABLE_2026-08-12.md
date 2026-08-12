# AUDIT — исполняемый функционал (Session #1)

**Когда:** 2026-08-12, 11:01–11:20 UTC · **main@:** `f821e53` · **Метод:** прогон на проде (MCP `tg-parser-vps`, HTTP `127.0.0.1:8000`, Prometheus, логи, БД read-only).
**Scope:** [`DECISION_AUDIT_AND_STRATEGY_SESSIONS_2026-08-12.md`](DECISION_AUDIT_AND_STRATEGY_SESSIONS_2026-08-12.md) §1 · **План:** [`PLAN_SESSION_AUDIT_FUNCTIONAL_1_2026-08-12.md`](PLAN_SESSION_AUDIT_FUNCTIONAL_1_2026-08-12.md).
**Правило:** доказательство — только прогон. Ни одна строка ниже не опирается на текст документации.

---

## TL;DR

**Counts (42 строки матрицы):** `pass` 16 · `partial` 18 · `fail` 2 · `not_run` 6.

Продукт в целом жив: поиск, RAG, навигация, workspaces, дайджесты и версионирование тем работают на проде и отвечают осмысленными данными. Два плеча сломаны молча, и оба — «последняя миля», то есть ровно то место, где пользователь получает ценность.

1. **Алерты watchlist не доставляются с 2026-06-15.** Совпадения исправно считаются и пишутся (последнее — сегодня 06:14 UTC), но 76 матчей, созданных после 06-16 у активных интересов с заданным `chat_id`, имеют `notified=false`. Все 16 активных интересов — `notify_mode='instant'`; суточный `watchlist_batch_flush` штатно обрабатывает пустое множество `batch` за 0.11 с и создаёт видимость работающего планировщика. F11 доезжает до БД и не доезжает до человека.
2. **Экспорт, созданный через MCP, невозможно скачать.** Джоба завершается, `get_export_status` отдаёт `download_url`, но GET по этому URL → 404: файл лежит в `tg_parser_mcp:/app/output/`, а отдаёт его контейнер `tg_parser`. Та же джоба, созданная через HTTP, скачивается (200, 236 002 байта). Дополнительно `file_path` у обеих джоб — `output/raw_messages.json`: путь относительный и не привязан к `job_id`, то есть параллельные экспорты одного уровня перетирают друг друга. **Privacy-инвариант при этом соблюдён:** в выгрузке 95 сообщений, ключа `raw_payload` нет ни как поля, ни как подстроки.
3. **«Деградация» пайплайна на 8 из 14 каналов — ложная тревога, но с реальным ценником.** За 12 часов 81 документ из 85 попал в `failed`, и ровно 81 раз сработал `dedup_db_duplicate`; настоящих ошибок ноль (`failed: 0` во внутренних счётчиках батча). Дубликаты отбраковываются **после** вызова LLM — токены уже оплачены. Побочный эффект: `fail_count` дорос до 1050, а `last_error` рассказывает про «processed 0 of N», хотя обрабатывать было нечего.
4. **`list_channels` показывает `coverage_percent = 0.0` по всем 14 каналам.** Это не данные, а деградация BUG-066: агрегат покрытия падает с `QueryCanceledError: canceling statement due to statement timeout` при **каждом** вызове (3 из 3 за сессию), и покрытие молча подменяется нулём без признака деградации в ответе. `get_cross_channel_stats` считает то же покрытие другим путём и отдаёт 81.6–100%.
5. **Стоимость недели измерена и она примерно в семь раз выше записанной ранее оценки:** **$33.23** за 7 суток против «$4–5/неделя» из prep. При этом за последние сутки run-rate — $2.32/день (≈$16/неделя): неделя включала бэкфилл-всплеск.

**Cost one-liner:** 12.06 MTok за 7 суток ≈ **$33.23** (Haiku 4.5 $18.65 + Sonnet 4.6 $14.58) при 1068 обработанных документах ≈ **$0.031 за документ all-in**; полное восстановление из бэкапа — **$215–380** ([ADR-0021](../adr/0021-backup-and-recovery-requirements.md) §1).

---

## Матрица

Колонки: per-surface вердикт. Итоговый `вердикт` — worst среди **исполненных** поверхностей (`fail` > `partial` > `pass`); `not_run` / `n/a` в агрегацию не входят (DECISION §1.3). Колонка **bot** — только наличие имени в `TOOL_DECLARATIONS` (`tg_parser/bot/tools.py`, 35 деклараций); live Telegram не запускался, поэтому `partial` там означает «объявлено, не исполнено».

### Навигация / KB

| возможность | MCP | bot | HTTP | pipeline | способ | вердикт | заметка |
|---|---|---|---|---|---|---|---|
| `list_channels` | partial | partial | n/a | n/a | MCP | **partial** | 14 активных каналов, 27 671 документ; `coverage_percent=0.0` по всем — деградация, см. findings §4 |
| `list_topics` | pass | partial | n/a | n/a | MCP | **partial** | 84 темы у `labdiagnostica_logical`, пагинация и `has_more` корректны |
| `get_topic_details` | pass | partial | n/a | n/a | MCP | **partial** | anchors + 19 bundle items + `summary_version=5` |
| `get_document` | pass | partial | n/a | n/a | MCP | **partial** | `text_clean` / `summary` / `topics`; `raw_payload` отсутствует |
| `get_related_topics` | pass | partial | n/a | n/a | MCP | **partial** | 14 связей из 8 каналов, score 0.32–0.42 |
| `get_cross_channel_stats` | pass | partial | n/a | n/a | MCP | **partial** | 1277 тем, 4325 связей, покрытие 81.6–100% — противоречит `list_channels` |

### Search / RAG

| возможность | MCP | bot | HTTP | pipeline | способ | вердикт | заметка |
|---|---|---|---|---|---|---|---|
| `search_knowledge_base` (hybrid) | pass | partial | pass | n/a | MCP + `POST /api/v1/search` | **partial** | HTTP 200 за 4.0 с; в выдаче topic-хит с `summary=null`, `channel_id=null` |
| `ask_question` | pass | partial | pass | n/a | MCP + `POST /api/v1/ask` | **partial** | HTTP 200 за 17.0 с; ответ с корректными ссылками на `source_ref` |
| HTTP auth | n/a | n/a | pass | n/a | curl без ключа / с чужим | **pass** | 401 без ключа, 403 с неверным |

### Workspaces F4-B

| возможность | MCP | bot | HTTP | pipeline | способ | вердикт | заметка |
|---|---|---|---|---|---|---|---|
| `list_workspaces` | pass | n/a | n/a | n/a | MCP | **pass** | baseline 3 |
| `create_workspace` | pass | n/a | n/a | n/a | MCP | **pass** | smoke-имя с UTC-суффиксом |
| `add_workspace_source` | pass | n/a | n/a | n/a | MCP | **pass** | `changed=true` |
| `list_workspace_sources` | pass | n/a | n/a | n/a | MCP | **pass** | отдаёт `channel_id`, а не `source_id` |
| read-tool с `workspace_id` | pass | n/a | n/a | n/a | MCP | **pass** | сужение точное: 48 тем = ровно `kdl_ru` |
| `rename_workspace` | pass | n/a | n/a | n/a | MCP | **pass** | `updated_at` обновился |
| `remove_workspace_source` | pass | n/a | n/a | n/a | MCP | **pass** | `changed=true` |
| `delete_workspace` | pass | n/a | n/a | n/a | MCP | **pass** | cleanup подтверждён: снова 3 workspace |
| `list_all_workspaces` (admin) | pass | n/a | n/a | n/a | MCP | **pass** | `whoami` = admin |
| неизвестный `workspace_id` | partial | n/a | n/a | n/a | MCP | **partial** | утечки существования нет, но отдаётся пустой список, а описание сервера обещает «404-like error» |

### Digests F6

| возможность | MCP | bot | HTTP | pipeline | способ | вердикт | заметка |
|---|---|---|---|---|---|---|---|
| `list_digests` | pass | partial | n/a | pass | MCP + логи bot | **partial** | 4 активные подписки, у всех `last_sent_at` = сегодня 06:00 UTC — доставка живая |
| `subscribe_digest` / `unsubscribe_digest` | not_run | partial | n/a | n/a | — | **not_run** | нужен owner GO на реальный `chat_id` |

### Watchlist F11

| возможность | MCP | bot | HTTP | pipeline | способ | вердикт | заметка |
|---|---|---|---|---|---|---|---|
| `list_watchlists` | pass | partial | n/a | n/a | MCP | **partial** | 24 интереса, 16 активных; 8 неактивных smoke-записей с мая |
| `get_watchlist_matches` | pass | partial | n/a | n/a | MCP | **partial** | 10 матчей с 08-01, последний сегодня 06:14 UTC |
| доставка алертов | n/a | n/a | n/a | fail | SQL + логи | **fail** | 76 матчей после 2026-06-16 с `notified=false`; последний `notified=true` — 2026-06-15 |
| `subscribe_watchlist` / `unsubscribe_watchlist` | not_run | partial | n/a | n/a | — | **not_run** | нужен owner GO |
| `backfill_watchlist` | not_run | n/a | n/a | n/a | — | **not_run** | write, исключён DECISION §1.2 |

### Export F2

| возможность | MCP | bot | HTTP | pipeline | способ | вердикт | заметка |
|---|---|---|---|---|---|---|---|
| `export_channel` (level=raw) | pass | partial | pass | n/a | MCP + `POST /api/v1/export` | **partial** | обе джобы завершились за ~2 с, 236 002 байта |
| `get_export_status` | pass | n/a | pass | n/a | MCP + HTTP | **pass** | `completed`, отдаёт `download_url` и `file_size` |
| скачивание по объявленному URL | fail | n/a | pass | n/a | GET download | **fail** | MCP-джоба → 404; HTTP-джоба → 200. Файл в `tg_parser_mcp`, отдаёт `tg_parser` |
| privacy: нет `raw_payload` | pass | n/a | pass | n/a | разбор скачанного файла | **pass** | 95 сообщений; ключа и подстроки `raw_payload` нет |

### Topics F5-C

| возможность | MCP | bot | HTTP | pipeline | способ | вердикт | заметка |
|---|---|---|---|---|---|---|---|
| `get_topic_versions` | pass | partial | n/a | n/a | MCP | **partial** | версии 2–4 + текущая 5, с провенансом LLM и `prompt_version` |
| `get_topic_history_diff` | pass | partial | n/a | n/a | MCP | **partial** | v1 → current: дифф summary + added/removed по scope |
| `force_resummarize` | not_run | partial | n/a | n/a | — | **not_run** | admin-only write, нужен GO |

### Channel ops и pipeline path

| возможность | MCP | bot | HTTP | pipeline | способ | вердикт | заметка |
|---|---|---|---|---|---|---|---|
| `get_pipeline_status` | partial | partial | n/a | n/a | MCP | **partial** | планировщик включён, тик каждый час; `fail_count` до 1050 и `last_error` вводят в заблуждение (см. findings §3) |
| `trigger_pipeline` / `trigger_topicization` / `trigger_link_topics` | not_run | partial | n/a | n/a | — | **not_run** | запрещены без GO |
| ingest → process → export | n/a | n/a | n/a | partial | логи 12 ч | **partial** | цикл идёт ежечасно; 81 из 85 документов за 12 ч учтены как `failed`, хотя это дедупликация |
| инкрементальная топикизация / resummarize | n/a | n/a | n/a | pass | логи + БД | **pass** | 114 версий тем за 7 суток; последняя — 2026-08-11 |
| digest hook | n/a | n/a | n/a | pass | `last_sent_at` | **pass** | 4 из 4 отправлены сегодня 06:00 UTC |
| watchlist hook (запись матчей) | n/a | n/a | n/a | pass | БД | **pass** | матч записан сегодня 06:14 UTC |

### LLM config и cost

| возможность | MCP | bot | HTTP | pipeline | способ | вердикт | заметка |
|---|---|---|---|---|---|---|---|
| `get_llm_config` | pass | partial | n/a | n/a | MCP | **partial** | runtime-переопределений нет; processing = Haiku 4.5, остальное = Sonnet 4.6, bot = Gemini 2.5 Flash |
| `set_llm_config` / `reset_llm_config` | not_run | partial | n/a | n/a | — | **not_run** | запрещены без GO |
| cost snapshot | pass | n/a | n/a | n/a | Prometheus + БД | **pass** | таблица ниже |

---

## Cost

| метрика | значение | дата / окно | команда / источник |
|---|---|---|---|
| Токены, 7 суток | 12.06 MTok: Haiku 4.5 — 4.99M prompt / 2.73M completion; Sonnet 4.6 — 4.20M prompt / 0.13M completion | 2026-08-05 … 08-12 | `sum by (model,token_type) (increase(tg_parser_llm_tokens_total[7d]))` на prod Prometheus |
| Глубина данных Prometheus | ≥ 7 суток (offset-проверка вернула 604 791 с) | 2026-08-12 | `timestamp(m) - timestamp(m offset 7d)` |
| Цены (pinned) | Haiku 4.5 — $1 / $5 за MTok; Sonnet 4.6 — $3 / $15 за MTok | сверено 2026-08-12 | [anthropic.com/pricing#api](https://www.anthropic.com/pricing#api), раздел Legacy models для Sonnet 4.6 |
| **Стоимость, 7 суток** | **$33.23** (Haiku $18.65 + Sonnet $14.58) | 2026-08-05 … 08-12 | токены × pinned prices |
| Run-rate последних суток | $2.32/сутки ≈ $16.25/неделя | 2026-08-11 … 08-12 | тот же запрос с `[1d]` |
| Документов обработано | 1068 за 7 суток; 17 за сутки; 45 727 всего | 2026-08-12 | `SELECT count(*) … processed_documents WHERE processed_at > now() - interval '7 days'` |
| Стоимость processing на документ | $18.65 / 1068 ≈ **$0.0175** | 7 суток | Haiku — единственная модель стадии processing |
| All-in на документ | $33.23 / 1068 ≈ **$0.031** | 7 суток | включает топикизацию, RAG, дайджесты, resummarize |
| $/документ **топикизации** отдельно | `not_recomputed` | — | у метрики токенов нет лейбла стадии; Sonnet делится между топикизацией, RAG, дайджестами и resummarize — разделить прогоном нельзя |
| Каналов в работе | 14 активных (19 в `owned_channels`, включая тестовые и снятые) | 2026-08-12 | `list_channels`, `whoami` |
| Полное восстановление из бэкапа | $215–380 | цитата | [ADR-0021](../adr/0021-backup-and-recovery-requirements.md) §1 — не пересчитывалось |
| LLM-запросы за 7 суток | 5571 успешных, 1 ошибка | 2026-08-05 … 08-12 | `increase(tg_parser_llm_requests_total[7d])` |

**Оговорка к цене недели.** $33.23 — факт за окно, а не устойчивый run-rate: 1068 документов за неделю против 17 за последние сутки означают бэкфилл-всплеск внутри окна. Для планирования корректнее брать обе цифры: $33 — «неделя с догоном», $16 — «неделя в текущем ритме».

---

## Cleanup

- Workspace `audit_functional_1_smoke_1107` создан, переименован, наполнен и **удалён**; `list_workspaces` снова отдаёт 3 записи. Канал `kdl_ru` после удаления workspace на месте (48 тем) — каскад снёс только membership.
- Две export-джобы **оставлены** намеренно (безопасной процедуры очистки нет, plan §F4): `1561b9da-f93d-4db2-ab33-91da6c8c9ab3` (через MCP) и `9e3408af-714e-4960-918f-b4abda887495` (через HTTP). Обе писали в один и тот же путь `output/raw_messages.json` в своих контейнерах.
- Никаких `trigger_*`, `force_resummarize`, `set_llm_config`, `backfill_watchlist`, subscribe и деплоев не выполнялось. Правок кода нет — артефакт этой сессии docs-only.

---

## Follow-ups (не чинить здесь)

Предлагаемые id — следующие свободные после BUG-092. Заводит их владелец; эта сессия только фиксирует.

| предлагаемый id | severity | суть | доказательство |
|---|---|---|---|
| **BUG-093** | High — F11 UX | Матчи watchlist не доставляются в Telegram с 2026-06-15; `notified` остаётся `false` у всех 76 матчей после 06-16 при активных интересах и заданном `chat_id`. Суточный `watchlist_batch_flush` не при чём: все 16 активных интересов — `notify_mode='instant'` | SQL по `watch_matches` × `watch_interests`; логи bot 09:00 UTC |
| **BUG-094** | Medium — F2 | Экспорт, созданный через MCP, не скачивается по объявленному `download_url` (404): файл пишется в контейнер MCP, отдаёт его контейнер API. Плюс `file_path` относительный и не привязан к `job_id` — параллельные экспорты перетирают файл | GET 404 против GET 200 для HTTP-джобы; `api_jobs.file_path` = `output/raw_messages.json` у обеих |
| **BUG-095** | Medium — cost + наблюдаемость | Дубликаты отбраковываются после вызова LLM (токены оплачены) и учитываются как `failed`, из-за чего 8 из 14 источников постоянно в «degraded», `fail_count` дорос до 1050, а `last_error` описывает несуществующий сбой. За 12 ч: 81 «отказ» = 81 `dedup_db_duplicate`, настоящих отказов 0 | логи `tg_parser` за 12 ч; `parallel_batch_complete` с `failed: 0` при `[2/4] failed=81` |
| **BUG-096** | Low/Medium — данные | `list_channels` всегда отдаёт `coverage_percent=0.0`: агрегат покрытия падает по statement timeout при каждом вызове, деградация подменяет значение нулём и никак не помечает это в ответе. `get_cross_channel_stats` в тот же момент отдаёт 81.6–100% | 3 из 3 вызовов → `QueryCanceledError` в логах `tg_parser_mcp` |

**Мелочи, недостойные отдельного бага, но полезные сессии #3 (код-ревью bot/MCP):**

- `list_digests` и `list_watchlists` дублируют весь payload в двух ключах сразу (`subscriptions`/`interests` **и** `items`), удваивая размер ответа: 44.4 КБ на 24 интереса.
- В гибридной выдаче встречается topic-хит с `summary=null`, `text_preview=null`, `channel_id=null` — строка без пользы для читающего.
- `shared_keywords` в `get_related_topics` содержит стоп-слова («для», «участников»), что завышает видимую осмысленность связи.
- 8 неактивных smoke-интересов watchlist с мая 2026 живут в проде и попадают в выдачу `list_watchlists`.
- Описание MCP-сервера обещает «404-like error» на неизвестный `workspace_id`, фактически возвращается пустой список.

**`not_run`, где нужен owner GO:** `trigger_pipeline` / `trigger_topicization` / `trigger_link_topics`, `force_resummarize`, `set_llm_config` / `reset_llm_config`, `backfill_watchlist`, а также `subscribe_digest` / `subscribe_watchlist` и их `unsubscribe` — последним нужен явно названный владельцем `chat_id`. Live-smoke Telegram-бота не запускался: драйвера нет, колонка bot заполнена только по декларациям.

---

## Что забирают следующие сессии

- **#2 (аудит документации):** матрица выше — эталон сверки. Точки, где документация расходится с прогоном: покрытие каналов, поведение на неизвестный `workspace_id`, обещание доставки алертов F11, стоимость недели ($4–5 против измеренных $33).
- **#3 (код-ревью bot + MCP):** приоритет по находкам — `mcp_server.py` (дублирование payload, контракт download URL), `bot/tools.py` (35 деклараций, live не проверялся). Оба `fail` — на стыке MCP и доставки, а не в processing.
- **#4 (ценность и бизнес-модели):** cost-таблица целиком; ключевое для юнит-экономики — $0.031 all-in на документ и то, что около 95% расхода стадии processing в текущем ритме уходит на документы, которые затем отбраковываются как дубликаты.
