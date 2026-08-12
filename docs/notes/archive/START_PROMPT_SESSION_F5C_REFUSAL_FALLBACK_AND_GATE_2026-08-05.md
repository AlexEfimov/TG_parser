# START PROMPT — F5-C: refusal-fallback (C) → gate hygiene (A) → candidate-filter (B, условный)

**Дата:** 2026-08-05 · **Тип:** ops-config (C) + observability-config PR (A) + опциональный application-code слайс (B) · **Ветки:** `main` для C (prod `.env`, репо не трогаем); `chore/f5c-gate-refusal-cooldown-hygiene` для A; `fix/f5c-skip-refusal-cooldown-candidates` для B
**Подготовлен:** 2026-08-05 из ветки `docs/t7-rewatch-closeout-2026-08-05` (docs-only, не закоммичено — коммит только по явному запросу owner'а, [`AGENTS.md`](../../../AGENTS.md)).

**Goal (одной строкой):** снять с F5-C ре-суммаризации хвост BUG-083 — сначала попытаться **вылечить** poison-pill тему сменой провайдера (C), затем сделать T7-gate честным сигналом без потери видимости poison-pill'ов (A), и только если тема осталась отравленной — перестать жечь на ней слот тика (B).

**Якоря (перечитать ДО действий):**

| Якорь | Файл | Что там |
|---|---|---|
| BUG-083 (poison-pill, refusal, fallback) | [`BUG_LOG.md`](../BUG_LOG.md) L208–224 | `resolved` 2026-07-10; § Proposed fix = контракт fallback'а; § «System prompt deliberately NOT touched» |
| T7 re-watch verdict | [`DELTA_T7_VERDICT_2026-07-22.md`](../DELTA_T7_VERDICT_2026-07-22.md) L138–176 | «Re-watch checkpoint CLOSED» — keep `=21`, bump→30 rejected, три optional follow-up'а = ровно C/A/B |
| Runbook §T7 | [`F5C_DEPLOY_AND_WATCH.md`](../../runbooks/F5C_DEPLOY_AND_WATCH.md) L543–636 | баннер CLOSED (L547), процедура re-create (L580–588), мониторинг (L600–624), rollback (L626–636) |
| Runbook § Событие B | [`F5C_DEPLOY_AND_WATCH.md`](../../runbooks/F5C_DEPLOY_AND_WATCH.md) L869+ | TTL retention — **deferred**, не эта сессия |
| ROADMAP **Next** | [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](../ROADMAP_KARPATHY_LIKE_LIVING_KB.md) L407 | δ/T7 CLOSED, re-watch CLOSED |
| Recording rule + gate | [`docker/prometheus/alerts.yml`](../../../docker/prometheus/alerts.yml) L218–261 | комментарий L218–234, `record` L241–245, `alert` L254–261 |
| BUG-078 (re-create ≠ restart) | [`BUG_LOG.md`](../BUG_LOG.md) L421+ | OS-env приоритет над bind-mounted `/app/.env` |
| BUG-089 (self-review культура + «promtool не в CI») | [`BUG_LOG.md`](../BUG_LOG.md) L100–116 | образец адверсариального self-review; L110 — `promtool` в CI **не** гоняется |

---

## Opener (вставить в новый чат Cursor)

> Работаю по `docs/notes/START_PROMPT_SESSION_F5C_REFUSAL_FALLBACK_AND_GATE_2026-08-05.md`. Прочитай его целиком перед первым действием.
>
> Порядок: **§3 (C)** → **§4 (A)** → **§5 (B, только если критерий входа выполнен)**. Каждый шаг начинается с owner-GO из §2 — без явного GO в этом чате шаг не исполняется.
>
> Режим: T7-вердикт **закрыт** (`RESUMMARIZE_MAX_AGE_DAYS=21` — не трогать), Событие B (TTL retention) **deferred** — не включать. Prod-мутации только по in-session GO, с backup и записанным rollback. `git commit` / PR — только по явному запросу (AGENTS.md). Никаких `docs/methodology/**`.
>
> Начни с §1 pre-flight re-snapshot: цифры в §0 сняты 2026-08-05 и к моменту сессии могли уехать — подтверди их заново, прежде чем на них опираться.

---

## 0. Контекст (проверено на проде 2026-08-05, read-only)

### Что было решено и **не переоткрывается**

T7 re-watch закрыт: **`RESUMMARIZE_MAX_AGE_DAYS=21` остаётся**, bump `21→30` **отклонён**, красный gate признан **info-шумом от BUG-083**. Запись: [`DELTA_T7_VERDICT_2026-07-22.md`](../DELTA_T7_VERDICT_2026-07-22.md) § «Re-watch checkpoint CLOSED», зеркала в runbook §T7 и ROADMAP **Next**. Эта сессия **исполняет** три optional follow-up'а из того вердикта, а не пересматривает его.

### Снятые цифры (prod, 2026-08-05, read-only)

| Сигнал | Значение |
|---|---|
| OS-env `tg_parser` | `RESUMMARIZE_MAX_AGE_DAYS=21`, `RESUMMARIZE_MAX_PER_TICK=10`, `RESUMMARIZE_TRIGGER_N=5`, `RESUMMARIZE_ENABLED=true` |
| `RESUMMARIZE_VERSION_*` в OS-env | **отсутствует** ⇒ retention (Событие B) выключен, kill-switch `=0` |
| `tg:resummarize_age_trigger:ratio14d` | ≈ **0.989** |
| `ALERTS{alertname="ResummarizeAgeTriggerGateF5CPhase2"}` | **firing**, `severity=info` |
| 14d mix (raw) | `trigger="age"` ≈ **365**, `trigger="counter"` ≈ **4** |
| `labdiagnostica_logical` 14d `trigger=age` | ≈ **338**, из них `outcome="refusal_cooldown"` ≈ **330** (98 %), `outcome="ok"` ≈ **8** |
| То же за 24h | 24 × `refusal_cooldown` + 1 × `ok` |
| Продуктивный mix 14d (без `refusal_cooldown`) | age `ok` ≈ **35**, counter `ok` ≈ **4** ⇒ честный ratio ≈ **0.90** |
| Токены resummarize 14d (все каналы) | ~209k prompt + ~30k completion; из них `labdiagnostica` ~37k + ~5.1k |
| Живой лог тика (~1/час) | `f5c_resummarize source=labdiagnostica_logical candidates=1 resummarized=0 skipped=1 tokens=0` |
| `f5c_resummarize_refusal` за 168h | **0 событий** — новых refusal-вызовов нет, тема скипается по cooldown (окно уже эскалировало) |
| CLI retention | `docker exec tg_parser tg-parser topic purge-versions --dry-run` → `Retention disabled (RESUMMARIZE_VERSION_RETENTION_DAYS=0)… DB untouched` |

Отравленная тема: **`topic:tg:labdiagnostica_logical:comment:8992`** — «Диагностика аллергии на ботулотоксин». Anthropic hard `stop_reason='refusal'` на медицинской терминологии, детерминированный (живой probe 2026-07-09 на всех вариантах входа: `full` / `summary`-only / `refs`-only — все refusal).

### Причинно-следственная цепочка: почему красный gate ≠ «cutoff слишком агрессивен»

1. Age-предикат в [`list_resummarize_candidates`](../../../tg_parser/storage/sqlalchemy/topic_card_repo.py) (L270–282) каждый тик отбирает `comment:8992` — у темы `new_items_since_last_summary > 0` и `last_summarized_at` старше 21 дня.
2. Так как refusal **никогда не коммитит новое summary**, `last_summarized_at` не двигается ⇒ тема пере-отбирается **каждый тик, вечно**. Это и есть poison-pill.
3. `_classify_trigger` ([`resummarization_service.py:112–136`](../../../tg_parser/services/resummarization_service.py)) присваивает `trigger="age"` **до** проверки cooldown-гарда (L352 vs L359), поэтому zero-cost скип всё равно инкрементит `tg_resummarize_total{trigger="age"}`.
4. Recording rule [`alerts.yml:241–245`](../../../docker/prometheus/alerts.yml) считает **все** `trigger="age"` без разбора `outcome` ⇒ ≈330 бесплатных скипов формируют 90 % числителя.
5. ⇒ Красный gate измеряет **«сколько раз мы пропустили одну и ту же отравленную тему»**, а не «насколько агрессивен freshness-cutoff». Bump cutoff'а на это не влияет вообще: тема остаётся кандидатом при любом `MAX_AGE_DAYS`, потому что её `last_summarized_at` заморожен на `2026-06-20`.

**Следствие, которое надо держать в голове весь шаг A:** даже после исключения `refusal_cooldown` честный ratio ≈ **0.90 ≥ 0.5** ⇒ **alert всё равно останется firing**. Шаг A делает сигнал честным, он **не** гасит алерт. Гашение — отдельное owner-решение (§4.4).

---

## 1. Pre-flight (read-only, обязателен)

```bash
git status                      # ожидаемо: незакоммиченные docs с re-watch closeout — НЕ трогать, НЕ коммитить
git rev-parse --short HEAD
```

Re-snapshot прода (все команды read-only; синтаксис — как в runbook §T7 L604–614):

```bash
ssh prod 'docker exec tg_parser env | grep -iE "^RESUMMARIZE"'
ssh prod "docker exec tg_parser_prometheus promtool query instant http://localhost:9090 'tg:resummarize_age_trigger:ratio14d'"
ssh prod "docker exec tg_parser_prometheus promtool query instant http://localhost:9090 'ALERTS{alertname=\"ResummarizeAgeTriggerGateF5CPhase2\"}'"
ssh prod "docker exec tg_parser_prometheus promtool query instant http://localhost:9090 'sum(increase(tg_resummarize_total[14d])) by (channel_id, trigger, outcome)'"
ssh prod "docker exec tg_parser_prometheus promtool query instant http://localhost:9090 'sum(increase(tg_resummarize_tokens_total[14d])) by (token_type)'"
```

**Снять текущую раскладку провайдеров по стейджам** (нужно для §3 — fallback обязан резолвиться в ДРУГОГО провайдера):

```bash
# host-side .env — источник для всех стейджей, кроме тех, что в compose allow-list
ssh prod "grep -E '^(LLM|PROCESSING_LLM|TOPICIZATION_LLM|RAG_LLM|DIGEST_LLM|RESUMMARIZE_LLM)_(PROVIDER|MODEL)=' ~/TG_parser/.env"
```
Либо через MCP-инструмент `get_llm_config` (он отдаёт effective provider/model **по каждому стейджу** с учётом runtime-оверрайдов — это надёжнее, чем читать `.env` глазами).

> ⚠️ **Не выдавать за факт то, что не снято.** В репозитории источники расходятся: runbook L595 утверждает, что дефолтная модель resummarize — дешёвый `gpt-4o-mini`, а BUG-083 наблюдал живой отказ от `claude-sonnet-4-6` на этом же стейдже. Значит эффективный провайдер задан в prod `.env`, а не в репо. **Снять живьём, не гадать.**

Прочитать перед действиями: BUG-083 (L208–224), § «Re-watch checkpoint CLOSED», runbook §T7.

---

## 2. Owner-decisions — взять ДО старта (LOCK-строки)

Исполнитель **не решает** эти пункты сам. Каждый — строка `LOCK:` в этом файле или явный GO в чате.

| # | Решение | Варианты | LOCK |
|---|---|---|---|
| **D-1** | Делаем ли шаг C вообще | да / нет (тема стоит ~0 токенов в cooldown; «вылечить» — вопрос качества KB, не стоимости) | `LOCK: ______` |
| **D-2** | Какой stage берём как fallback | `rag` / `digest` / `processing` / `topicization` — **обязан резолвиться в другого провайдера**, см. §3.1 | `LOCK: ______` |
| **D-3** | Способ обхода cooldown-гарда для эксперимента C | (a) точечный SQL-сброс маркеров у одной темы **[рекомендуется]** / (b) глобально `RESUMMARIZE_REFUSAL_BACKOFF_S=0` | `LOCK: ______` |
| **D-4** | Делаем ли fallback постоянным для scheduler'а после успеха C | да (re-create `tg_parser` + опц. зеркалирование в compose allow-list через PR) / нет (разовый CLI-эксперимент) | `LOCK: ______` |
| **D-5** | Что делаем с порогом gate после шага A (честный ratio ≈0.90 ≥ 0.5) | 4 варианта в §4.4 | `LOCK: ______` |
| **D-6** | Компенсирующий сигнал для poison-pill при шаге A | новая recording rule + info-alert / только Grafana-панель + runbook-строка / оба | `LOCK: ______` |
| **D-7** | Шаг B — только после C; критерий входа в §5.1 | исполняем / откладываем | `LOCK: ______` |

---

## 3. Шаг C — попытка вылечить тему сменой провайдера

**Тип:** ops/config. Кода не пишем — механизм уже реализован в BUG-083 (`07355ab`).

### 3.1 Как работает fallback (проверено по коду)

`resummarize_topic` ловит `stop_reason == "refusal"` на [L503](../../../tg_parser/services/resummarization_service.py) и зовёт `_try_refusal_fallback` ([L801–851](../../../tg_parser/services/resummarization_service.py)):

| Поведение | Строки | Деталь |
|---|---|---|
| Выключен, если `resummarize_refusal_fallback_stage` пуст | L818–820 | `return None` **молча**, без лога |
| Резолв провайдера | L822 | `resolve_llm_config(stage)` → [`factory.py:33–51`](../../../tg_parser/processing/llm/factory.py) → [`LLMConfigManager.resolve`, `settings.py:1798–1828`](../../../tg_parser/config/settings.py) |
| Ошибка резолва | L823–825 | лог `f5c_resummarize_fallback_resolve_failed`, `return None` |
| **Тот же провайдер ⇒ пропуск** | L826–827 | `return None` — **тоже молча, без лога**; в семействе того же вендора модель откажет снова |
| Одна повторная попытка | L831–834 | новый клиент, тот же `sys_prompt` / `user_prompt` / `model_settings` |
| Любая ошибка вызова | L835–837 | лог `f5c_resummarize_fallback_failed`, `return None` |
| Ответ снова refusal или пустой | L843–844 | `return None` **молча** |
| Успех | L845–851 | лог `f5c_resummarize_fallback_ok` (`stage`, `provider`, `model`), дальше обычный happy-path |
| Успешный commit чистит маркеры | L623–631 | `resummarize_refusal_until` / `_count` / `_at` / `_llm` удаляются из `metadata_json` |

**Приоритет резолва провайдера** ([`settings.py:1804–1828`](../../../tg_parser/config/settings.py)): stage runtime-override → global runtime-override → `{stage}_llm_provider` (static) → `llm_provider` (global static). Per-stage env: `PROCESSING_LLM_PROVIDER/_MODEL`, `TOPICIZATION_LLM_*`, `RAG_LLM_*`, `DIGEST_LLM_*`, `RESUMMARIZE_LLM_*` ([`settings.py:195–206`](../../../tg_parser/config/settings.py), примеры в [`.env.example:87–101`](../../../.env.example)).

> ⚠️ **Ловушка резолва (проверено по коду, L1822–1825).** Имя стейджа **не валидируется** — `resummarize_refusal_fallback_stage` это обычный `str` ([`settings.py:1169–1179`](../../../tg_parser/config/settings.py)). Опечатка (`"raq"`) не даст ошибки: `getattr(self._static, "raq_llm_provider", None)` вернёт `None` и резолв **молча упадёт на глобальный `LLM_PROVIDER`**. Если глобальный совпадает с refused — fallback тихо не сработает (L826, без лога); если отличается — сработает, но **не с той моделью, которую выбирал owner**. ⇒ значение `RESUMMARIZE_REFUSAL_FALLBACK_STAGE` обязано быть проверено на резолв ДО эксперимента (§3.3).
>
> Отдельно: `stage="bot"` резолвится в жёсткий `gemini` ([L1817–1820](../../../tg_parser/config/settings.py)) — формально «другой провайдер», но это вне контракта поля (`processing|topicization|rag|digest`) и вне ADR-0005-намерения bot-скоупа. **Не использовать.**

### 3.2 Ответ на открытый вопрос: блокирует ли guard ручной путь

**ДА, блокирует. Проверено по коду, все три ручных пути.**

Гард стоит внутри `resummarize_topic` ([L359–370](../../../tg_parser/services/resummarization_service.py)) — до фетча бандла и до LLM, активен при `settings.resummarize_refusal_backoff_s > 0`, возвращает `{"status": "refusal_cooldown"}`. Ни один вызывающий не передаёт флага обхода, потому что такого параметра **нет**:

| Ручной путь | Файл:строка | Вызов |
|---|---|---|
| MCP `force_resummarize` | [`mcp_server.py:2829`](../../../tg_parser/mcp_server.py) (тул 2784–2833) | `await service.resummarize_topic(topic_id)` |
| CLI `tg-parser topic resummarize` | [`cli/topic_cmd.py:402`](../../../tg_parser/cli/topic_cmd.py) (команда 340–457) | `await service.resummarize_topic(topic_id)` |
| Bot `_exec_force_resummarize` | [`bot/tools.py:3287`](../../../tg_parser/bot/tools.py) (executor 3131–3291) | `await service.resummarize_topic(topic_id)` |

Сигнатура: `resummarize_topic(self, topic_id, *, llm=None)` ([L307–311](../../../tg_parser/services/resummarization_service.py)) — единственный kwarg это инжект LLM-клиента, не bypass.

⚠️ Побочный факт, который стоит поправить в этой же сессии: docstring `resummarize_topic` ([L315–317](../../../tg_parser/services/resummarization_service.py)) перечисляет статусы `ok | locked | no_card | no_bundle | empty_scope | llm_error | db_error | version_raced` — **без** `refusal` и `refusal_cooldown`, хотя оба возвращаются (L367, L799). То же в docstring MCP-тула ([`mcp_server.py:2800–2803`](../../../tg_parser/mcp_server.py)). Правка docstring — тривиальная, но это application-code ⇒ в PR шага A/B, не в ops-шаг C.

⇒ **«Просто форснуть» тему нельзя.** Нужен один из двух обходов (D-3):

**(a) Точечный SQL-сброс маркеров — рекомендуется.** Убрать `resummarize_refusal_until` / `resummarize_refusal_count` из `topic_cards.metadata_json` только у `comment:8992`. Гард ([`_in_refusal_cooldown`, L713–730](../../../tg_parser/services/resummarization_service.py)) читает `resummarize_refusal_until`; отсутствие маркера ⇒ fail-open ⇒ тема проходит. Blast radius = одна строка. Если fallback не сработает, `_handle_refusal` ([L732–799](../../../tg_parser/services/resummarization_service.py)) просто заново поставит cooldown (со сброшенным счётчиком → база `resummarize_refusal_backoff_s`=86400, т.е. 24h вместо эскалированного окна — приемлемая и самовосстанавливающаяся цена).
⚠️ `topic_cards.metadata_json` — колонка **`Text()`**, не JSONB ([`_metadata.py:664`](../../../tg_parser/storage/sqlalchemy/_metadata.py)); любой SQL по ней требует `::jsonb`-каста. Перед UPDATE **записать текущее значение** в заметку сессии (это и есть rollback).

**(b) Глобально `RESUMMARIZE_REFUSAL_BACKOFF_S=0`.** Гард выключается (L359 — условие `> 0`), **но** и `_handle_refusal` перестаёт ставить cooldown (L754–756: `if base > 0:`) ⇒ на время эксперимента возвращается предфиксное поведение BUG-083 «retry every tick» **для всех тем сразу**. Только с немедленным откатом. Существенно шире по blast radius, чем (a).

### 3.3 Процедура (после GO по D-1/D-2/D-3)

**Порядок важен: сначала конфиг, потом снятие гарда.** Иначе тик может подхватить тему без fallback'а и просто сожжёт refusal-вызов.

1. **Backup prod `.env`:**
   ```bash
   ssh prod 'cd ~/TG_parser && cp .env .env.bak.f5c-fallback-$(date -u +%Y%m%dT%H%M%SZ) && ls -la .env.bak.f5c-fallback-*'
   ```
   Записать точное имя бэкапа в заметку сессии — оно и есть rollback.

2. **Добавить knob в prod `.env`** (значение из D-2):
   ```bash
   # ~/TG_parser/.env
   RESUMMARIZE_REFUSAL_FALLBACK_STAGE=rag      # ← подставить выбранный stage
   ```

3. **Проверить, что резолв даёт ДРУГОГО провайдера** — свежий процесс в контейнере:
   ```bash
   ssh prod 'docker exec tg_parser python -c "
   from tg_parser.config import settings
   from tg_parser.processing.llm.factory import resolve_llm_config
   st = settings.resummarize_refusal_fallback_stage
   p0,_,m0 = resolve_llm_config(\"resummarize\")
   p1,_,m1 = resolve_llm_config(st) if st else (None,None,None)
   print(\"stage=\",repr(st),\" primary=\",p0,m0,\" fallback=\",p1,m1,\" backoff_s=\",settings.resummarize_refusal_backoff_s)
   "'
   ```
   **Acceptance этого подшага:** `stage` непустой, `fallback provider != primary provider`, модель — та, что ожидал owner. Если провайдеры совпали — fallback был бы пропущен молча (L826), эксперимент бессмыслен ⇒ вернуться к D-2.

   > ⚠️ **Почему нельзя проверять через `docker exec tg_parser env | grep RESUMMARIZE`.** `RESUMMARIZE_REFUSAL_FALLBACK_STAGE` **отсутствует** в `environment:`-allow-list сервиса `tg_parser` ([`docker-compose.yml:54–148`](../../../docker-compose.yml); из семейства `RESUMMARIZE_*` там только `ENABLED`/`TRIGGER_N`/`MAX_AGE_DAYS`/`MAX_PER_TICK`, L85–88). Его в OS-env контейнера **не будет** — значение читается pydantic'ом из bind-mounted `/app/.env` ([`docker-compose.yml:42`](../../../docker-compose.yml) × [`settings.py:18–19, 84–88`](../../../tg_parser/config/settings.py), `_PROJECT_ROOT/.env` = `/app/.env` внутри образа). Пустой grep — ожидаемый результат, **не** признак ошибки.
   >
   > ⚠️ **И, зеркально, BUG-078:** команда выше запускает **новый** процесс, который перечитывает `/app/.env`. Это валидное доказательство **для CLI-пути** (§3.4 — тоже новый процесс), но **НЕ** доказательство для долгоживущего scheduler-синглтона `tg_parser`. Ровно этот false-green и был BUG-078. Для scheduler'а единственное честное доказательство — поведенческое: строка `f5c_resummarize_fallback_ok` / `_failed` в его логах после re-create.

4. **Снять гард по выбранному в D-3 способу.** Для (a) — сначала прочитать и записать текущее значение, потом UPDATE:
   ```sql
   -- READ FIRST (записать вывод в заметку — это rollback)
   SELECT metadata_json FROM topic_cards
   WHERE id = 'topic:tg:labdiagnostica_logical:comment:8992';

   -- затем снять только два маркера
   UPDATE topic_cards
   SET metadata_json = (metadata_json::jsonb
                        - 'resummarize_refusal_until'
                        - 'resummarize_refusal_count')::text
   WHERE id = 'topic:tg:labdiagnostica_logical:comment:8992'
     AND metadata_json IS NOT NULL;
   ```
   Оставить `resummarize_refusal_at` / `_llm` — это провенанс прошлого отказа, гард их не читает (L721).

5. **Форсировать попытку** — CLI, свежий процесс, читает `/app/.env`:
   ```bash
   ssh prod 'docker exec tg_parser tg-parser topic resummarize topic:tg:labdiagnostica_logical:comment:8992'
   ```
   Альтернатива — MCP `force_resummarize` (admin-only), но он исполняется в контейнере `tg_parser_mcp`, у которого `env_file: .env` ([`docker-compose.yml:181`](../../../docker-compose.yml)) ⇒ иная схема подхвата env. **Для чистоты эксперимента использовать CLI в `tg_parser`.**

   > ⚠️ **Ненулевой exit code — ожидаемый исход, а не поломка.** CLI завершает `raise typer.Exit(code=1)` для **любого** статуса, кроме `ok` и `locked` ([`topic_cmd.py:451–457`](../../../tg_parser/cli/topic_cmd.py)) — то есть и для `refusal`, и для `refusal_cooldown`. Под `ssh prod '…'` это вернёт `1`. Читать **stdout** (`• status: …`), а не код возврата; не заворачивать команду в `&&`-цепочку, которая проглотит вывод.

### 3.4 Что считать успехом и что — неудачей

| Наблюдение | Где смотреть | Вывод |
|---|---|---|
| CLI печатает `status: ok` + `new_version: 3` | stdout CLI ([`topic_cmd.py:437–446`](../../../tg_parser/cli/topic_cmd.py)) | ✅ кандидат на успех — **но одного этого мало**, см. ниже |
| `f5c_resummarize_fallback_ok stage=… provider=… model=…` | `docker logs tg_parser` | ✅ **обязательное** доказательство, что сработал именно fallback, а не первичный провайдер |
| Новая строка в `topic_card_versions` для этого `topic_id` | SQL | ✅ снапшот предыдущего summary записан ([L585–599](../../../tg_parser/services/resummarization_service.py)) |
| `metadata_json.resummarize_llm` = `fallback_provider/model` | SQL | ✅ провенанс подтверждает провайдера ([L636](../../../tg_parser/services/resummarization_service.py)) |
| Маркеры `resummarize_refusal_*` отсутствуют | SQL | ✅ commit-путь их вычистил ([L623–631](../../../tg_parser/services/resummarization_service.py)) |
| `tg_resummarize_total{channel_id="labdiagnostica_logical",outcome="ok"}` +1 | promtool | ✅ метрика подтверждает |
| CLI печатает `status: refusal` + лог `f5c_resummarize_refusal` | stdout + логи | ❌ fallback тоже отказал (или не сработал) — см. диагностику ниже |
| CLI печатает `status: refusal_cooldown` | stdout | ❌ **гард не снят** — шаг 4 не выполнен или выполнен не над той темой |
| `status: refusal`, а fallback-логов **вообще нет** | логи | ❌ Неоднозначно по построению: L818–820 (stage пуст) и L826–827 (тот же провайдер) оба возвращают `None` **без лога**. Развести только через проверку §3.3 шаг 3 — поэтому она обязательна ДО эксперимента |
| `f5c_resummarize_fallback_resolve_failed` / `_failed` | логи | ❌ конфиг битый / вызов упал — читать `error=` |

**Сроки наблюдения.** CLI даёт ответ сразу — «наблюдать 24–48 ч» здесь не нужно и было бы имитацией проверки. Что действительно требует окна:
- **+24 ч после успеха:** `tg_resummarize_total{channel_id="labdiagnostica_logical",outcome="refusal_cooldown"}` за 24h должен стать **0** (тема вышла из карантина и больше не пере-отбирается: `last_summarized_at` сдвинулся ⇒ выпала из age-предиката минимум на 21 день). Это же — вход в критерий §5.1.
- **+24 ч при неудаче:** убедиться, что cooldown встал заново (`refusal_cooldown` снова тикает ~1/час, `refusal` не повторяется) — т.е. система вернулась в известное безопасное состояние, а не в BUG-083-цикл.

### 3.5 Rollback шага C

| Что откатывать | Как |
|---|---|
| Knob в prod `.env` | `cp .env.bak.f5c-fallback-<ts> .env` (или удалить строку), затем `grep -c RESUMMARIZE_REFUSAL_FALLBACK_STAGE .env` → `0` |
| Если делали re-create (D-4=да) | `docker compose up -d tg_parser` — **RE-CREATE, НЕ `restart`** (BUG-078: `restart` не пересоздаёт контейнер и OS-env остаётся запечённым; runbook L587) |
| Если использовали (b) `RESUMMARIZE_REFUSAL_BACKOFF_S=0` | вернуть строку из бэкапа **немедленно** — иначе любая новая refusal-тема уходит в retry-every-tick (регресс BUG-083) |
| SQL-сброс маркеров (a) | формального отката нет и не нужен: при повторном отказе `_handle_refusal` ставит cooldown заново. Записанное в шаге 4 старое `metadata_json` — страховка на случай, если UPDATE задел лишнее |
| Изменённое summary темы | **необратимо в смысле «вернуть как было» одной командой**, но предыдущая версия сохранена в `topic_card_versions` (L585–599) и её текст можно восстановить вручную. Owner должен понимать это ДО GO |

---

## 4. Шаг A — гигиена сигнала T7-gate

**Тип:** правка `docker/prometheus/alerts.yml` (+ Grafana JSON) ⇒ **изменение репозитория** ⇒ ветка + PR + merge + `git pull` на проде + reload Prometheus. Образ **не** пересобирается (файл правил — bind-mount `:ro`, [`docker-compose.yml:347`](../../../docker-compose.yml)).

### 4.1 Правка PromQL

Текущее ([`alerts.yml:241–245`](../../../docker/prometheus/alerts.yml)):

```yaml
      - record: tg:resummarize_age_trigger:ratio14d
        expr: >
          sum(increase(tg_resummarize_total{trigger="age"}[14d]))
          /
          scalar(sum(increase(tg_resummarize_total{trigger=~"counter|age"}[14d])))
```

Целевое — исключить `refusal_cooldown` **из числителя И из знаменателя** (иначе ratio станет арифметически бессмысленным):

```yaml
      - record: tg:resummarize_age_trigger:ratio14d
        expr: >
          sum(increase(tg_resummarize_total{trigger="age",outcome!="refusal_cooldown"}[14d]))
          /
          scalar(sum(increase(tg_resummarize_total{trigger=~"counter|age",outcome!="refusal_cooldown"}[14d])))
```

Ожидаемый эффект на живых числах: `(365−330) / (369−330) = 35/39 ≈ **0.897**` (было ≈0.989).

**Эффект наступает сразу, без 14-дневного лага.** `increase(...[14d])` пересчитывается из сырого `tg_resummarize_total` на каждой оценке правила; исторические значения записанной серии `tg:resummarize_age_trigger:ratio14d` остаются как есть, но alert читает свежую точку. Ждать прокрутки окна не нужно — этим шаг A принципиально отличается от bump'а knob'а 2026-07-22.

**Оставить имя правила `tg:resummarize_age_trigger:ratio14d` без изменений.** Потребители (§4.3) ссылаются по имени; переименование = отдельный слайс с обходом всех потребителей.

### 4.2 Обновить устаревшие тексты (не косметика — они лгут оператору)

| Файл:строки | Что не так | Правка |
|---|---|---|
| [`alerts.yml:220–225`](../../../docker/prometheus/alerts.yml) | комментарий говорит `RESUMMARIZE_MAX_AGE_DAYS=14`; live = **21** | перефразировать без хардкода числа (`RESUMMARIZE_MAX_AGE_DAYS` как имя knob'а, без значения) — иначе цифра снова протухнет при следующем bump'е |
| [`alerts.yml:229–234`](../../../docker/prometheus/alerts.yml) | описан только исключённый bucket `"-"`; про `refusal_cooldown` ничего | добавить абзац: почему `refusal_cooldown` исключён и **где** он теперь виден (ссылка на компенсирующий сигнал §4.4) |
| [`alerts.yml:260–261`](../../../docker/prometheus/alerts.yml) | `summary`/`description` алерта содержат `RESUMMARIZE_MAX_AGE_DAYS=14` и «14d freshness cutoff» | убрать `=14`; в `description` добавить, что `refusal_cooldown` не учитывается |
| [`wave2_observation.json:174`](../../../docker/grafana/dashboards/wave2_observation.json) | **заголовок row'а** дашборда: `T7 F5-C P2 — Re-summarize freshness (RESUMMARIZE_MAX_AGE_DAYS=14)` — самый заметный протухший текст, виден оператору первым | убрать значение из заголовка |
| [`wave2_observation.json:295`](../../../docker/grafana/dashboards/wave2_observation.json) | описание панели trigger-split: `RESUMMARIZE_MAX_AGE_DAYS=14` | синхронизировать |
| [`wave2_observation.json:316`](../../../docker/grafana/dashboards/wave2_observation.json) | описание панели counter-vs-age 24h: `RESUMMARIZE_MAX_AGE_DAYS=14` | синхронизировать |
| [`wave2_observation.json:337`](../../../docker/grafana/dashboards/wave2_observation.json) | описание stat-панели: `RESUMMARIZE_MAX_AGE_DAYS=14`, «14d freshness cutoff» | синхронизировать с новой формулировкой |
| [`wave2_observation.json:371`](../../../docker/grafana/dashboards/wave2_observation.json) | описание timeseries-панели | то же |
| [`wave2_observation.json:182`](../../../docker/grafana/dashboards/wave2_observation.json) | перечисление outcome'ов `{ok, locked, no_card, no_bundle, empty_scope, llm_error, version_raced, unknown}` — **нет** `refusal`, `refusal_cooldown`, `db_error` | привести к фактическому набору из кода |
| [`F5C_DEPLOY_AND_WATCH.md:583`](../../runbooks/F5C_DEPLOY_AND_WATCH.md) | инструкция «как включить» всё ещё показывает `RESUMMARIZE_MAX_AGE_DAYS=14` как значение к постановке, хотя live `=21` | пометить как historical **или** обновить; **не** ретушировать соседний баннер L545, где `14 → 21` — записанная история |
| [`resummarization_service.py:315–317`](../../../tg_parser/services/resummarization_service.py) | docstring статусов без `refusal` / `refusal_cooldown` | дополнить |
| [`mcp_server.py:2800–2803`](../../../tg_parser/mcp_server.py) | то же в docstring тула | дополнить |
| [`F5C_DEPLOY_AND_WATCH.md:618–624`](../../runbooks/F5C_DEPLOY_AND_WATCH.md) | «14д cutoff», acceptance «age-доля стабильно < 50 %» | обновить под новое определение ratio и решение D-5 |

**Фактический перечень outcome'ов — из кода**, не из документации. `record_resummarize_outcome` ([`metrics.py:568–620`](../../../tg_parser/api/metrics.py)) пишет то, что ему передали; реальные значения на call-site'ах `resummarization_service.py`:
`ok` (L687) · `locked` (L337) · `no_card` (L342) · `no_bundle` (L374) · `empty_scope` (L570) · `llm_error` (L421, L473, L534, L559) · `db_error` (L270, L473) · `version_raced` (L610, L655) · `refusal` (L791) · `refusal_cooldown` (L360).
Метка `trigger` ∈ `{counter, age, "-"}` ([`_classify_trigger`, L112–136](../../../tg_parser/services/resummarization_service.py)).

### 4.3 Потребители `tg:resummarize_age_trigger:ratio14d` — сверить, не сломать

Полный список в репозитории (grep по имени правила):

| Потребитель | Файл:строки | Действие |
|---|---|---|
| Alert `ResummarizeAgeTriggerGateF5CPhase2` | [`alerts.yml:254–261`](../../../docker/prometheus/alerts.yml) | выражение алерта **не меняется** (`>= 0.5`), меняется смысл читаемой серии; текст — §4.2 |
| Grafana stat «age-trigger 14d share» | [`wave2_observation.json:362`](../../../docker/grafana/dashboards/wave2_observation.json) | expr не меняется; description — §4.2 |
| Grafana timeseries + 50 % threshold | [`wave2_observation.json:395`](../../../docker/grafana/dashboards/wave2_observation.json) | то же; порог-линию править только при D-5 ≠ «оставить 0.5» |
| Runbook §T7 | [`F5C_DEPLOY_AND_WATCH.md:620–624`](../../runbooks/F5C_DEPLOY_AND_WATCH.md) | текст — §4.2 |
| Исторические заметки | `C2_T7_LIVE_SNAPSHOT_2026-07-20.md`, `DELTA_T7_VERDICT_2026-07-22.md`, `DRAFT_NEXT_CONTRACT_POST_GAMMA_CLOSEOUT_2026-07-20.md`, `PLAN_/START_PROMPT_SESSION_DELTA_T7_*`, `START_PROMPT_SESSION_C_T7_OPS_ENABLEMENT_2026-07-20.md`, `REVIEW_WAVE1_5_1_2026-06-20.md`, `START_PROMPT_BREAK_2026-06-20.md` | **НЕ ретушировать** — это записанные наблюдения на свои даты (прецедент BUG-089 § Artifacts: исторические записи с ошибочными именами метрик сознательно оставлены как есть) |

**Тестов, пиннящих правила Prometheus или тексты алертов, нет.** Единственный тест, читающий `alerts.yml`, — [`tests/test_metrics_instrumentation.py`](../../../tests/test_metrics_instrumentation.py) (`_ALERTS_YML`, L90): он извлекает только имена `tg_parser_http_*` и сверяет их с `/metrics` (BUG-089). Правил F5-C он не касается ⇒ шаг A его не задевает, но прогнать надо (per-file vacuity floor, L314–322, чувствителен к содержимому файла).

**`promtool` в CI не гоняется** — подтверждено записью BUG-083-соседа [BUG-089 § «Why CI didn't catch»](../BUG_LOG.md) (L110) и отсутствием упоминаний в [`.github/workflows/ci.yml`](../../../.github/workflows/ci.yml). ⇒ синтаксис правил **обязан** быть проверен вручную (§4.5), иначе битый YAML доедет до прода и Prometheus откажется применить конфиг.

### 4.4 OWNER-DECISION D-5: порог gate

**Проблема, которую нельзя замолчать.** После §4.1 честный ratio ≈ **0.90**, порог `>= 0.5` ⇒ **alert остаётся firing**. Шаг A сам по себе gate не гасит. Это не баг правки — это факт: на тихих каналах age-ветка действительно даёт большинство *продуктивных* re-summarize (35 против 4), при абсолютном объёме ~2.5 успешных age/день на всю систему.

| Вариант | Что делаем | Плюсы | Минусы |
|---|---|---|---|
| **V1 — принять age-доминирование как норму, gate снять/перевести в чистый recording** | Удалить `alert:`-блок, оставить recording rule + панели | Честно: сигнал «оценить cutoff» уже отработал (T7 закрыт), держать вечно-красный info-алерт = приучать игнорировать алерты | Теряется автоматический триггер на будущую переоценку cutoff'а; нужен явный ручной cadence в runbook |
| **V2 — поднять порог** (напр. `>= 0.95`) | `expr: … >= 0.95` | Gate зеленеет сейчас, механизм остаётся | Число подогнано под текущие данные, а не выведено из требования; при падении counter-трафика снова покраснеет без изменения сути |
| **V3 — считать только `outcome="ok"`** | `outcome="ok"` вместо `outcome!="refusal_cooldown"` в обеих частях | Самый чистый смысл: «доля age среди **успешных** re-summarize» | На текущих данных даёт тот же ≈0.90 ⇒ алерт всё равно firing; прячет `llm_error`/`empty_scope`-паттерны из знаменателя |
| **V4 — сменить ось: не доля, а абсолютный объём** | Новый gate на `sum(increase(tg_resummarize_total{trigger="age",outcome="ok"}[14d])) > N` | Ловит именно то, ради чего был gate — **стоимость** age-ветки, а не её долю; при 35/14д любой разумный N зелёный | Новое правило = новое имя, надо обойти потребителей; требует калибровки N owner'ом |

**Не выбирать за владельца.** `LOCK: ______`

> ⚠️ **D-6 — компенсирующий сигнал, обязателен при любом варианте.** Точная формулировка проблемы (проверено grep'ом, без преувеличения): слово `refusal` **не встречается ни разу** ни в [`alerts.yml`](../../../docker/prometheus/alerts.yml), ни в [`wave2_observation.json`](../../../docker/grafana/dashboards/wave2_observation.json). То есть **алерта** на `refusal` / `refusal_cooldown` не существует вовсе, а `ResummarizeLLMErrorRate` (L170–181) их не считает — у него в числителе только `llm_error`. Видимость сегодня есть только **пассивная**: панели «Re-summarize rate by channel & outcome» и «outcomes 24h» ([L181–216](../../../docker/grafana/dashboards/wave2_observation.json)) агрегируют `by (outcome)` и потому отрисуют `refusal_cooldown` — но лишь если человек откроет дашборд. Единственный сигнал, который сегодня **сам** приходит к оператору при росте poison-pill'ов, — это красный T7-gate; шаг A его именно от этого и отвязывает. Без компенсации A превращается в «починили метрику, спрятав проблему» — прямой антипаттерн проекта. Минимум:
> ```yaml
>       - record: tg:resummarize_refusal_cooldown:count14d
>         expr: sum(increase(tg_resummarize_total{outcome="refusal_cooldown"}[14d])) by (channel_id)
> ```
> плюс info-alert на устойчивый рост (порог — owner), **или** выделенная Grafana-панель + строка в runbook § Мониторинг с явным «что делать, если растёт». Acceptance шага A **не считается выполненным**, пока компенсирующий сигнал не существует.
>
> Смежное наблюдение (в scope A **не берём**, зафиксировать как follow-up): знаменатель `ResummarizeLLMErrorRate` — `sum(rate(tg_resummarize_total[30m]))` по **всем** outcome'ам, включая ~24/день бесплатных `refusal_cooldown`. Это разбавляет долю и делает tripwire менее чувствительным. Отдельное решение owner'а.

### 4.5 Деплой A (после merge PR)

```bash
# 1. Валидация ДО прода — promtool в CI не гоняется, это единственный синтаксический гейт
ssh prod 'cd ~/TG_parser && git pull --ff-only'
ssh prod 'docker exec tg_parser_prometheus promtool check rules /etc/prometheus/alerts.yml'

# 2. Reload. Порт Prometheus наружу НЕ опубликован (в docker-compose.yml у сервиса нет `ports:`),
#    поэтому сначала пробуем hot-reload изнутри контейнера (`--web.enable-lifecycle` включён,
#    docker-compose.yml:352); если в образе нет curl/wget — падаем на re-create.
ssh prod 'docker exec tg_parser_prometheus wget -q -O- --post-data="" http://localhost:9090/-/reload' \
  || ssh prod 'cd ~/TG_parser && docker compose up -d prometheus'
```

> ℹ️ **Почему для Prometheus `restart`/`up -d` безопасны, а для `tg_parser` нет.** BUG-078 — про OS-env, запекаемый compose-интерполяцией в момент **создания** контейнера. `alerts.yml` — bind-mount (`docker-compose.yml:347`), он перечитывается процессом при старте, никакой интерполяции. Так что здесь ограничение BUG-078 не применяется; hot-reload предпочтителен просто как zero-downtime.

**Post-deploy verify (обязательно pre/post-пара, оба значения записать):**

```bash
# ДО правки (снять в §1) и ПОСЛЕ reload — значения ДОЛЖНЫ отличаться
ssh prod "docker exec tg_parser_prometheus promtool query instant http://localhost:9090 'tg:resummarize_age_trigger:ratio14d'"
# компенсирующий сигнал существует и НЕ нулевой
ssh prod "docker exec tg_parser_prometheus promtool query instant http://localhost:9090 'sum(increase(tg_resummarize_total{outcome=\"refusal_cooldown\"}[14d]))'"
# правило реально загружено с новым выражением
ssh prod "docker exec tg_parser_prometheus promtool query instant http://localhost:9090 'ALERTS{alertname=\"ResummarizeAgeTriggerGateF5CPhase2\"}'"
```

**Мутационная проверка acceptance (обязательна).** Спросить себя: «если исполнитель не изменит ничего и просто прогонит verify — упадёт ли acceptance?»
- ✅ Да: pre/post пара по `ratio14d` (`≈0.989` → `≈0.90`) — при бездействии значения совпадут.
- ❌ Нет, если ограничиться «`promtool check rules` прошёл» или «алерт всё ещё firing» — то и другое верно и без правки. **Такие формулировки в acceptance не допускать.**
- Если шаг C уже вылечил тему, `refusal_cooldown` за 14d начнёт спадать, и разница pre/post станет меньше ⇒ **снимать pre-значение в §1 непосредственно перед правкой**, а не переиспользовать цифры из §0.

### 4.6 Rollback A

`git revert` PR-коммита → `git pull --ff-only` на проде → тот же reload. Данные не затрагиваются: recording rule ничего не удаляет, исторические точки серии остаются.

---

## 5. Шаг B — не выбирать cooldown-темы в кандидатах (**условный**)

### 5.1 Критерий входа (проверяется, а не предполагается)

Шаг B исполняется **только если все три условия** выполнены после C:

1. Шаг C выполнен и **не вылечил** тему (`status: refusal` или fallback недоступен по D-2), **или** owner отклонил C (D-1 = нет);
2. За 24h после C `tg_resummarize_total{channel_id="labdiagnostica_logical",outcome="refusal_cooldown"}` по-прежнему ≈ 24 (тема продолжает занимать слот тика);
3. Owner дал GO по D-7.

Если C вылечил тему — B **не нужен**: `last_summarized_at` сдвинулся, тема выпала из age-предиката минимум на `RESUMMARIZE_MAX_AGE_DAYS` дней.

> Экономическая честность: сам по себе cooldown-скип стоит **0 токенов** (гард стоит до фетча бандла и до LLM, L359). Реальная цена B — один из `RESUMMARIZE_MAX_PER_TICK=10` слотов на канал за тик. При `candidates=1` в живом логе слот-давления сейчас **нет**. ⇒ B оправдан не экономией, а чистотой сигнала и защитой от роста популяции poison-pill'ов. Это надо сказать owner'у прямо, а не продавать B как экономию.

### 5.2 Два места правки

**Вариант B1 — предикат на SQL-уровне** ([`topic_card_repo.py:270–282`](../../../tg_parser/storage/sqlalchemy/topic_card_repo.py)):

добавить в `WHERE` условие вида «нет активного `resummarize_refusal_until`».

| + | − |
|---|---|
| `[:cap_topics]` (L231) режет уже отфильтрованный список ⇒ недобора нет | `metadata_json` — **`Text()`**, не JSONB ([`_metadata.py:664`](../../../tg_parser/storage/sqlalchemy/_metadata.py)) ⇒ нужен `::jsonb`-каст, индекса по нему нет |
| Один источник правды для кандидатов | Сравнение ISO-времени: в metadata лежит `datetime.isoformat()` c tz (L762) — сравнивать через `::timestamptz`, аккуратно с NULL и битым значением |
| Top-level `new_items_since_last_summary > 0` сохраняется ⇒ partial-index `idx_topic_cards_resummarize_candidates` остаётся ([`_metadata.py:690`](../../../tg_parser/storage/sqlalchemy/_metadata.py), миграция `migrations/versions/processing/20260426_add_topic_card_versions.py:81`) | Каст на **битом** JSON бросит ошибку на всю выборку — нужен guard (`metadata_json IS NULL OR metadata_json::jsonb ->> … IS NULL OR …`), fail-open как у `_in_refusal_cooldown` (L723–726) |
| | `list_resummarize_candidates` — часть порта [`storage/ports.py:761`](../../../tg_parser/storage/ports.py); менять семантику метода = менять контракт |

**Вариант B2 — пост-фильтр с over-fetch** ([`resummarization_service.py:205–231`](../../../tg_parser/services/resummarization_service.py)):

| + | − |
|---|---|
| Переиспользует уже существующий и протестированный `_in_refusal_cooldown` (L713–730) — одна логика, один источник правды по формату маркера | Наивный пост-фильтр **до** `candidates[:cap_topics]` (L231) недоберёт: отфильтровав k тем из первых `cap_topics`, получим `cap_topics − k` работ вместо `cap_topics` ⇒ **обязателен over-fetch** (запрашивать больше и резать после фильтра) |
| Никакого SQL по `Text()`-колонке, никаких кастов | Over-fetch = лишние строки из БД; при большой популяции cooldown-тем — неограниченный |
| Изменение локально в сервисе, порт не трогаем | Логика отбора расползается между repo и service |

**Рекомендация к обсуждению (не решение):** B1 корректнее по смыслу (кандидат, который заведомо будет скипнут, кандидатом не является), B2 дешевле и безопаснее по типам. Выбор — owner/исполнитель на месте, с записью обоснования.

### 5.3 Инвариант: ручной путь обязан остаться рабочим

`force_resummarize` (MCP / CLI / bot) **не проходит** через `list_resummarize_candidates` — он зовёт `resummarize_topic` напрямую (§3.2). ⇒ B не должен ничего добавлять в `resummarize_topic`. Гард L359 остаётся как есть, включая свойство «ручной вызов по теме в cooldown возвращает `refusal_cooldown`».
**Не «чинить» это заодно.** Изменение поведения ручного пути — отдельное решение owner'а с отдельным обоснованием; смешивать его с B нельзя.

### 5.4 Набросок тестов

Расширить `TestRefusalPoisonPillGuard` ([`tests/test_f5c_resummarization_service.py:1448+`](../../../tests/test_f5c_resummarization_service.py); образцы: cooldown-скип ~L1516–1552, fallback-recovery L1554–1609, same-provider skip L1610–1645).

| # | Тест | Красный до правки? |
|---|---|---|
| 1 | Тема с **активным** `resummarize_refusal_until` не попадает в результат `run_for_channel` (`candidates` её не содержит) | ✅ да |
| 2 | Тема с **истёкшим** `resummarize_refusal_until` **попадает** — фильтр не должен быть «навсегда» | ✅ да (иначе фильтр слишком широкий) |
| 3 | **Cap-недобор (главный тест варианта B2):** `cap_topics=2`, первые 2 кандидата в cooldown, есть 3-й и 4-й здоровые ⇒ должно быть ре-суммаризовано **2**, не 0 | ✅ да — именно этот тест ловит наивный пост-фильтр |
| 4 | Битый / отсутствующий `metadata_json` не роняет выборку и не исключает тему (fail-open, зеркало L723–726) | ✅ да для B1 без guard'а |
| 5 | `force_resummarize` по теме в cooldown **по-прежнему** возвращает `refusal_cooldown` (инвариант §5.3) | ❌ нет — зелёный и до, и после. Это **pin**, а не red→green; помечать как таковой |
| 6 | При B1: `EXPLAIN` подтверждает index scan по `idx_topic_cards_resummarize_candidates`, не seq scan | — ручная проверка на проде/staging |

**Мутационная проверка (обязательна, культура BUG-089):** после того как тесты зелёные — руками откатить фильтр в коде и убедиться, что тесты 1–4 **краснеют**. Если тест зелёный при откаченной правке — он ничего не пиннит.

### 5.5 Деплой B

Это **application code** ⇒ merge PR не меняет прод сам по себе. Нужны: `git pull` на проде → `docker compose build tg_parser` → **`docker compose up -d tg_parser` (re-create, НЕ `restart`)** → проверить `docker inspect tg_parser --format '{{.State.StartedAt}}'` (изменился) и `.State.Health.Status` = `healthy`. Прецедент: BUG-088/BUG-089 — «merged ≠ deployed».

**Rollback B:** `git revert` → rebuild → re-create. Схему БД B не трогает ⇒ миграций и отката миграций нет.

---

## 6. Hard OUT / anti-scope

| Запрещено | Почему |
|---|---|
| Менять `RESUMMARIZE_MAX_AGE_DAYS` (в т.ч. `21→30`) | T7 re-watch **CLOSED**, bump отклонён — [`DELTA_T7_VERDICT_2026-07-22.md`](../DELTA_T7_VERDICT_2026-07-22.md) § «Re-watch checkpoint CLOSED» |
| Включать **Событие B** / TTL retention (`RESUMMARIZE_VERSION_RETENTION_DAYS`) | **deferred** тем же вердиктом; включение = отдельный owner GO с backup + dry-run (runbook § Событие B, L869+). Hard-DELETE необратим |
| Трогать системный промпт `resummarize` (`prompts/resummarize.yaml`) | Owner решил не хардкодить доменную специфику — BUG-083 § Proposed fix: «System prompt deliberately NOT touched» (проект может обслуживать немедицинские домены) |
| Править `pyproject.toml` / `requirements.txt` / добавлять зависимости | [`AGENTS.md`](../../../AGENTS.md) § Forbidden actions |
| `git commit` / открывать PR без явного запроса owner'а | [`AGENTS.md`](../../../AGENTS.md) |
| Создавать `docs/methodology/**` | Методология живёт в отдельном worktree |
| Ретушировать исторические заметки под новые числа | Прецедент BUG-089 § Artifacts — наблюдения на свою дату остаются как есть; расхождения оформляются датированным `CORRECTION`-абзацем |
| Переименовывать `tg:resummarize_age_trigger:ratio14d` | Ломает потребителей; отдельный слайс |
| Менять поведение `force_resummarize` относительно cooldown | Отдельное owner-решение (§5.3) |
| Чинить знаменатель `ResummarizeLLMErrorRate` заодно с A | Смежная находка, отдельное решение (§4.4) |
| Смешивать C, A и B в один PR | Разные типы изменений (ops-config / observability-config / application code) и разные rollback'и |

---

## 7. Acceptance + что писать в документы

### 7.1 Acceptance по шагам

**Шаг C** (если D-1 = да):
- [ ] Backup prod `.env` создан, точное имя файла записано в заметке сессии
- [ ] §3.3 шаг 3 выполнен: `fallback provider != primary provider`, оба записаны
- [ ] Обход гарда выполнен способом из D-3; для (a) — **прежнее** `metadata_json` записано до UPDATE
- [ ] CLI-вызов сделан, `status` записан дословно
- [ ] При `ok`: подтверждены **все четыре** независимых признака — лог `f5c_resummarize_fallback_ok`, новая строка в `topic_card_versions`, `metadata_json.resummarize_llm` = fallback provider/model, маркеры `resummarize_refusal_*` отсутствуют
- [ ] При `refusal`: зафиксировано, какая именно ветка (`_resolve_failed` / `_failed` / same-provider-skip / fallback тоже отказал) — с опорой на проверку §3.3 шаг 3, а не на догадку
- [ ] +24h: `refusal_cooldown` за 24h = 0 (успех) **или** cooldown встал заново без цикла `refusal` (неудача, безопасное состояние)
- [ ] Rollback либо выполнен, либо явно оставлен по D-4 с записью решения

**Шаг A:**
- [ ] `promtool check rules` зелёный (**необходимое, не достаточное**)
- [ ] pre/post пара `ratio14d` записана и **значения различаются** (`≈0.989` → `≈0.90` на текущих данных)
- [ ] Компенсирующий сигнал (D-6) существует и возвращает ненулевое значение
- [ ] Все устаревшие тексты из таблицы §4.2 обновлены. Контрольный прогон: `rg -n 'MAX_AGE_DAYS=14' docker/ docs/runbooks/`. **Эталон на момент подготовки промпта — 8 попаданий:** `alerts.yml:220,261`; `wave2_observation.json:174,295,316,337`; `F5C_DEPLOY_AND_WATCH.md:545,583`. После A должны остаться **только исторические**: `F5C_DEPLOY_AND_WATCH.md:545` (запись про bump `14 → 21`) и, по решению исполнителя, `:583`, если помечено как historical. Любое оставшееся попадание в `docker/` = недоделка
- [ ] Решение D-5 записано, и правка/её отсутствие ему соответствует
- [ ] `pytest tests/test_metrics_instrumentation.py -q` зелёный
- [ ] Все потребители §4.3 сверены; исторические заметки **не** тронуты

**Шаг B** (если D-7 = да):
- [ ] Тесты 1–4 §5.4 были красными до правки и зелёные после (мутационно перепроверено)
- [ ] Тест 5 (инвариант ручного пути) зелёный, помечен как pin
- [ ] Для B1: `EXPLAIN` показывает index scan
- [ ] Прод: rebuild + **re-create** (не `restart`), `StartedAt` изменился, health `healthy`
- [ ] +24h: `candidates` по `labdiagnostica_logical` = 0, `refusal_cooldown` больше не тикает, здоровые каналы продолжают давать `ok`

### 7.2 Что писать в документы

| Документ | Что |
|---|---|
| [`BUG_LOG.md`](../BUG_LOG.md) § BUG-083 | Датированный `Update 2026-08-XX` **внутрь существующей записи** (статус `resolved` не менять — исходный фикс не регрессировал): результат эксперимента C (вылечена / нет, каким провайдером), решение по A, был ли исполнен B. Если C провалился — это новый **проверенный факт** о детерминизме отказа уже на другом вендоре, он ценен сам по себе |
| [`CHANGELOG.md`](../../../CHANGELOG.md) `## [Unreleased]` | Для A: отдельная `### Observability` секция — что именно перестал считать gate и **где теперь виден** poison-pill (компенсирующий сигнал). Для B: `### Fixed`. Для C — **не** писать: prod-config, не изменение репозитория |
| [`F5C_DEPLOY_AND_WATCH.md`](../../runbooks/F5C_DEPLOY_AND_WATCH.md) §T7 | Новое определение `ratio14d`, обновлённый acceptance, строка в § Мониторинг про компенсирующий сигнал и «что делать, если `refusal_cooldown` растёт». Если исполнялся C — короткая deploy-строка по образцу существующих |
| [`DELTA_T7_VERDICT_2026-07-22.md`](../DELTA_T7_VERDICT_2026-07-22.md) | В блоке «Optional follow-ups» (L171–174) — отметить исполненные пункты со ссылкой на PR/эту сессию. Сам вердикт **не переписывать** |
| Заметка сессии в `docs/notes/` | Снятые числа с UTC-таймстампами, дословные `status`, имя backup-файла, прежнее `metadata_json`, точные rollback-команды |

---

## 8. Открытые вопросы (взять у owner'а / снять живьём)

| # | Вопрос | Как снять |
|---|---|---|
| **Q-1** | Какой провайдер/модель **фактически** на стейдже `resummarize` в проде? | `get_llm_config` (MCP) или §1 grep по prod `.env`. **Не выведено из репозитория:** runbook L595 говорит `gpt-4o-mini`, BUG-083 наблюдал `claude-sonnet-4-6` — источники противоречат друг другу, значит значение задано в prod `.env` |
| **Q-2** | Какие стейджи реально настроены **другим** провайдером? | То же. `.env.example:92–101` показывает лишь *пример* (processing/topicization → anthropic, rag/digest → openai), а не прод |
| **Q-3** | Точная команда hot-reload Prometheus в этом образе | В `prom/prometheus:v3.13.2` может не быть `curl`/`wget`. `--web.enable-lifecycle` включён ([`docker-compose.yml:352`](../../../docker-compose.yml)), порт наружу не опубликован. Проверить в сессии; гарантированный fallback — `docker compose up -d prometheus` |
| **Q-4** | Надо ли зеркалить `RESUMMARIZE_REFUSAL_FALLBACK_STAGE` в compose allow-list и в `SCHEDULER_CRITICAL_ENV` | Сейчас **нет** ни там, ни там ([`docker-compose.yml:54–148`](../../../docker-compose.yml); [`tests/test_compose_env_propagation.py:151–165`](../../../tests/test_compose_env_propagation.py)). Без зеркала значение читается из bind-mounted `/app/.env` и **работает** — но тогда `docker exec tg_parser env` его не покажет, т.е. штатной ops-проверки нет. Зеркалирование = правка `docker-compose.yml` + теста ⇒ отдельный мини-PR. Owner-решение, привязано к D-4 |
| **Q-5** | Порог/ось gate после A | D-5, §4.4 — 4 варианта, не выбирать за owner'а |
| **Q-6** | Форма компенсирующего сигнала | D-6, §4.4 |
| **Q-7** | Приемлемо ли, что при успехе C summary темы перезапишется моделью другого вендора | Провенанс сохраняется (`topic_card_versions` + `metadata.resummarize_llm`), но стиль/качество могут отличаться от остальной KB. Owner должен знать до GO |

---

## 9. Self-review (адверсариальный второй проход, 2026-08-05)

Проведён по образцу [BUG-089 § «Self-review: the first version of the guard was the same bug»](../BUG_LOG.md) (L112) и BUG-088. Фиксируем найденное, а не молча правим.

### Что нашёл и что исправлено

| # | Находка | Что было / что стало |
|---|---|---|
| **S-1** | **Открытый вопрос про guard был бы выдан как догадка.** Первичный набросок формулировал «вероятно, гард блокирует и ручной путь». | Проверено по коду **всех трёх** call-path'ов (`mcp_server.py:2829`, `topic_cmd.py:402`, `bot/tools.py:3287`) + сигнатура `resummarize_topic` (L307–311, bypass-параметра нет). Ответ в §3.2 — **факт со ссылками**, а не гипотеза. |
| **S-2** | **Пропущен BUG-078-класс в обе стороны.** Набросок предлагал верифицировать knob через `docker exec tg_parser env \| grep RESUMMARIZE` — что дало бы **пустой вывод**, ошибочно прочитанный как «не применилось». | `RESUMMARIZE_REFUSAL_FALLBACK_STAGE` **отсутствует** в compose allow-list (L54–148) ⇒ его в OS-env не будет **по построению**; значение читается из bind-mounted `/app/.env`. Добавлены оба предупреждения в §3.3 шаг 3: пустой grep ожидаем, **и** проверка через свежий `python -c` валидна для CLI-пути, но **не** доказывает конфиг долгоживущего scheduler'а (ровно false-green BUG-078). Единственное честное доказательство для scheduler'а — поведенческий лог. |
| **S-3** | **Шаг A в исходном виде был «починкой метрики через сокрытие».** Исключение `refusal_cooldown` убирает единственное место, где рост poison-pill'ов виден автоматически. | Проверено: алертов на `refusal`/`refusal_cooldown` в `alerts.yml` **нет** (grep — ноль), `ResummarizeLLMErrorRate` (L170–181) их не считает. Введён **обязательный** D-6: компенсирующий сигнал, без которого acceptance A не засчитывается (§4.4). |
| **S-4** | **Acceptance шага A прошёл бы при полном бездействии.** Формулировки «`promtool check rules` зелёный» и «алерт firing» истинны и без правки. | Заменено на **pre/post пару значений `ratio14d`, которые обязаны различаться** (§4.5), плюс явный раздел «мутационная проверка acceptance» с перечислением запрещённых вакуумных формулировок. Дополнительно: pre-значение снимать непосредственно перед правкой, потому что успешный шаг C сам двигает числа. |
| **S-5** | **Ошибка в описании шага A: «правка prod `alerts.yml`».** Файл — bind-mount из репозитория (`docker-compose.yml:347`) ⇒ это **изменение репозитория**, требующее ветки/PR/merge/`git pull`, а не ad-hoc правка на проде. | §4 переписан: A — PR-слайс, деплой = `git pull` + reload, образ не пересобирается. |
| **S-6** | **Ложное применение BUG-078 к Prometheus.** Черновик требовал «только re-create, не restart» и для Prometheus. | Неверно: BUG-078 — про OS-env, запекаемый при **создании** контейнера; правила — bind-mount, перечитываются при старте процесса. В §4.5 добавлено явное разграничение, чтобы правило не карго-культилось. |
| **S-7** | **Не был отмечен молчаливый резолв при опечатке в имени стейджа.** | `resummarize_refusal_fallback_stage` — необязательный `str` без валидации; `LLMConfigManager.resolve` (L1822–1825) для неизвестного стейджа **молча** падает на глобальный `LLM_PROVIDER`. Опечатка не даёт ошибки, а даёт не ту модель. Добавлено в §3.1 как ловушка + обязательная проверка резолва §3.3 шаг 3. Заодно зафиксирован `stage="bot"` → жёсткий `gemini` (L1817–1820) как формально работающий, но вне контракта — с явным «не использовать». |
| **S-8** | **Неотличимые режимы отказа в диагностике C.** Три разные ветки `_try_refusal_fallback` (`stage` пуст — L818; тот же провайдер — L826; ответ снова refusal — L843) возвращают `None` **вообще без лога**. | «Логов нет» неинформативно по построению. Таблица §3.4 честно помечает этот случай как неоднозначный, и именно поэтому проверка резолва §3.3 шаг 3 объявлена **обязательной до** эксперимента, а не опциональной. |
| **S-9** | **Не был указан rollback для двух мутирующих действий.** SQL-сброс маркеров и перезапись summary темы. | Добавлено в §3.5: для SQL — «прочитать и записать прежнее `metadata_json` до UPDATE» как явный подшаг §3.3 шаг 4; для summary — честно сказано, что одной командой не откатывается, но предыдущая версия лежит в `topic_card_versions`, и owner должен знать это **до** GO (Q-7). |
| **S-10** | **Порядок действий в C был небезопасен.** В черновике гард снимался раньше, чем прописывался fallback ⇒ окно, в котором тик мог сжечь refusal-вызов без fallback'а. | Порядок зафиксирован явно (§3.3): backup → конфиг → проверка резолва → снятие гарда → форс. |
| **S-11** | **Опасность варианта (b) `BACKOFF_S=0` была недооценена.** | Проверено по коду: `base = settings.resummarize_refusal_backoff_s; if base > 0:` (L754–756) ⇒ при `0` **и** гард выключен, **и** новые cooldown'ы не ставятся — т.е. полный откат к предфиксному BUG-083 «retry every tick» **для всех тем**. Вариант (a) поднят до рекомендуемого, (b) помечен как широкий blast radius с немедленным откатом. |
| **S-12** | **B продавался как экономия — это неправда.** | Cooldown-скип стоит **0 токенов** (гард до LLM, L359). Реальная цена — слот тика, а при живом `candidates=1` слот-давления нет. В §5.1 добавлен абзац «экономическая честность»: B оправдан чистотой сигнала, не экономией. |
| **S-13** | **Тест «force_resummarize по cooldown-теме возвращает `refusal_cooldown`» выглядел как red→green, но зелёный и до, и после B.** | Помечен в §5.4 как **pin**, а не как red→green (иначе создаётся иллюзия покрытия — та же патология, что в BUG-089 § «Why CI didn't catch»). Добавлен тест №3 (cap-недобор) как единственный, который реально ловит наивный пост-фильтр B2. |
| **S-14** | **Не проверен тип колонки под SQL-фильтр B1.** | `topic_cards.metadata_json` — **`Text()`**, не JSONB (`_metadata.py:664`) ⇒ нужен `::jsonb`-каст, индекса нет, битый JSON уронит **всю** выборку. Добавлено в минусы B1 + требование fail-open guard'а по образцу `_in_refusal_cooldown` (L723–726) + тест №4. |
| **S-15** | **Устаревшие тексты предлагалось заменить на новое число (`=21`).** | Это воспроизводит тот же класс протухания. Заменено требованием убрать хардкод значения и оставить имя knob'а. Дополнительно найдены не заявленные в задаче артефакты: `wave2_observation.json:182` (перечень outcome'ов без `refusal`/`refusal_cooldown`/`db_error`) и docstring'и `resummarization_service.py:315–317` + `mcp_server.py:2800–2803` (тот же неполный перечень) — добавлены в §4.2. |
| **S-16** | **Риск противоречия закрытому вердикту T7.** | Сверено с [`DELTA_T7_VERDICT_2026-07-22.md`](../DELTA_T7_VERDICT_2026-07-22.md) L138–176 и runbook L547: промпт **исполняет** три optional follow-up'а того вердикта и нигде не пересматривает `=21`, не воскрешает bump→30 и не включает Событие B. Все три пункта продублированы в Hard OUT §6. |
| **S-17** | **Owner-decisions были размазаны по тексту.** | Сведены в §2 семь пронумерованных решений с `LOCK:`-строками; в §4.4 четыре варианта порога даны с плюсами/минусами и явным «не выбирать за владельца». |
| **S-18** | **Номера строк перепроверены после написания.** | Все `путь:строки` в этом файле сверены повторно против рабочего дерева на `docs/t7-rewatch-closeout-2026-08-05`. Заявляемые числа (0.989 / 365 / 4 / 338 / 330 / 35 / 0.90) — из §0, снятые с прода **2026-08-05**; §1 требует re-snapshot перед опорой на них. Три ошибки, найденные именно этим проходом, — S-19…S-21 ниже. |
| **S-19** | **Первая версия §4.2 покрывала протухшие тексты не полностью — «починка» была бы половинчатой.** Я перечислил 2 места в Grafana, опираясь на предыдущий grep по имени recording rule. | Прогон `rg -n 'MAX_AGE_DAYS=14' docker/ docs/runbooks/` дал **8** попаданий, включая пропущенный **заголовок row'а дашборда** `wave2_observation.json:174` («…Re-summarize freshness (RESUMMARIZE_MAX_AGE_DAYS=14)») — самый заметный оператору текст из всех, — плюс описания панелей L295 и L316 и инструкцию runbook L583. Все добавлены в §4.2. В §7.1 вместо расплывчатого «ни одного оставшегося» зафиксирован **эталон из 8 попаданий** с явным списком тех, что законно остаются историческими. Урок ровно тот же, что в S-4: проверка, сформулированная как «посмотреть, всё ли обновлено», проходит при неполной работе; проверка с пересчётом — нет. |
| **S-20** | **Ошибка в цитируемом диапазоне строк.** Указал `topic_cmd.py:340–451` для CLI-команды. | Фактически команда занимает **340–457** (конец файла, 457 строк). Исправлено в §3.2. Мелочь, но именно такие расхождения обесценивают якоря `путь:строки`. |
| **S-21** | **Пропущено операционно значимое поведение CLI: ненулевой exit code на штатном исходе.** | `topic_cmd.py:451–457` — `raise typer.Exit(code=1)` для любого статуса, кроме `ok` и `locked`, т.е. **и для `refusal`, и для `refusal_cooldown`**. Под `ssh prod '…'` это вернёт `1`, что исполнитель может прочитать как «команда сломалась» и начать чинить не то. Предупреждение добавлено в §3.3 шаг 5. |
| **S-22** | **Утверждение в §4.4 было преувеличено.** Написал, что gate — «единственное место, где рост poison-pill'ов виден». | Неточно: панели «rate by channel & outcome» и «outcomes 24h» (`wave2_observation.json:181–216`) агрегируют `by (outcome)` и `refusal_cooldown` отрисуют. Формулировка уточнена: слово `refusal` действительно отсутствует и в `alerts.yml`, и в дашборде (grep — ноль), **алерта** нет вовсе, но пассивная видимость на панелях есть; единственный **сам приходящий** сигнал — красный gate. Вывод (D-6 обязателен) не меняется, но обоснование теперь точное, а не риторическое. |

### Что осталось непроверенным (и это сказано явно)

| Не подтверждено | Почему |
|---|---|
| Фактический provider/model стейджа `resummarize` и остальных стейджей на проде | Прод read-only не опрашивался при подготовке промпта; в репозитории источники противоречат (Q-1, Q-2) |
| Наличие `curl`/`wget` в `prom/prometheus:v3.13.2` для `/-/reload` | Не проверяется из репозитория; дан гарантированный fallback (Q-3) |
| Что fallback другого вендора **вылечит** тему | Детерминизм отказа доказан только для Anthropic (BUG-083, probe 2026-07-09). Поведение OpenAI/Gemini на этом контенте **неизвестно** — в этом и смысл эксперимента C. Промпт нигде не обещает успеха |
| Точное значение `ratio14d` после правки A | `≈0.897` — арифметика по числам §0; фактическое зависит от состояния окна на момент reload. Поэтому acceptance требует **различия** pre/post, а не попадания в конкретное число |
