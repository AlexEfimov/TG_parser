# START PROMPT — P2: S3 token-delta watch (pre-LLM dedup effect measurement)

**Дата создания:** 2026-07-11 · **Для:** планировочно-измерительной сессии в отдельном окне (агент **НЕ правит код** без явного owner-решения).
**Тип:** post-deploy measurement / planning (read-only prod + документация). **Не** implementation-сессия S4+.
**Предпосылки закрыты (2026-07-11):**
- **P0 billing** — снят: `increase(anthropic_billing_block_total[12h])=0`, haiku success растёт (~1037/24h).
- **P1 BUG-082** — deploy + watch PASS (~14h): `QueuePool limit=0`, `db_error` нет, HEAD prod `6904b0b`.
- **Блок S1–S3** — смержен (#299/#300/#301) и на prod с 2026-07-07; S3 (pre-LLM dedup) в коде с `8fd1ca5`.

**Нормативные документы (при расхождении — они первичны):**
- Hand-off: [`NEXT_SESSION_PLAN_POST_S1S3_DEPLOY_2026-07-08.md`](NEXT_SESSION_PLAN_POST_S1S3_DEPLOY_2026-07-08.md) § P2, § P3.
- Baseline «до»: [`S0_BASELINE_PROCESSING_METRICS_2026-07-07.md`](S0_BASELINE_PROCESSING_METRICS_2026-07-07.md) (обл.4 дедуп, обл.5 coverage, §4 шаблон снапшота).
- Watch-процедура: [`../runbooks/S1_S3_DEPLOY_AND_WATCH.md`](../runbooks/S1_S3_DEPLOY_AND_WATCH.md) § Watch (S3), § Tripwires T1/T3.
- Remediation-контекст S3: [`PLAN_REMEDIATION_SESSIONS_PROCESSING_ALGORITHMS_2026-07-07.md`](PLAN_REMEDIATION_SESSIONS_PROCESSING_ALGORITHMS_2026-07-07.md) § S3 (F-01/F-09, O-2/O-8).
- Процесс: [`WORKFLOW_REMEDIATION_SESSIONS_AGREEMENTS_2026-07-07.md`](WORKFLOW_REMEDIATION_SESSIONS_AGREEMENTS_2026-07-07.md) §5.4 (измерения как deliverable), §8 (статус блока).
- Проект: [`AGENTS.md`](../../AGENTS.md) (forbidden: `git commit` без явного цикла; эта сессия — docs-only по умолчанию).
- Инфра: [`../SERVER_ARCHITECTURE.md`](../SERVER_ARCHITECTURE.md) (prod: `ssh prod`, `/home/user/TG_parser`).

---

<role>
Ты — senior-инженер tg_parser. Твоя задача — **спланировать и выполнить read-only замер эффекта S3** (pre-LLM exact dedup, метрика `tg_dedup_pre_llm_hits_total`), сравнить с S0-baseline и зафиксировать вердикт: эффект **доказан / частичный / недостаточно данных**. Сессия заканчивается заполненным `after-block-S3` снапшотом и рекомендацией «можно ли открывать S4».

**Не пиши production-код.** Допустимы только правки `docs/notes/**` (S0 §4, NEXT_SESSION_PLAN, при необходимости краткая addendum-заметка `S3_DELTA_WATCH_2026-07-11.md`). `git commit` — только по явному запросу owner'а в конце сессии.
</role>

<context>
**Зачем P2.** S3 (O-2) должен переносить exact-репосты **до** LLM-вызова: меньше `tg_parser_llm_requests_total{model=haiku,status=success}`, рост `tg_dedup_pre_llm_hits_total`, снижение доли post-LLM `tg_dedup_duplicates_detected_total`. S0 зафиксировал «до»: post-LLM dedup 7d ≈ **1559**, haiku success 7d ≈ **5617** (error ≈14968 — в основном billing, не сравнивать с success).

**Почему замер откладывался.** После деплоя блока S1–S3 (2026-07-07) prod простаивал на **billing-блоке**; чистое 24h-окно без billing не набралось. P0 снят 2026-07-11. Дополнительно: рестарт `tg_parser` при деплое BUG-082 (**2026-07-10T19:46Z**) сбрасывает since-restart counters — **нельзя** опираться только на since-restart для итогового вердикта; нужен PromQL `increase[…]` с явно выбранным окном.

**Текущий prod-снимок (2026-07-11T06:54Z, для ориентира — перепроверь live):**

| Метрика | Значение | Комментарий |
|---|---|---|
| HEAD | `6904b0b` | BUG-082 merge включён |
| `increase(tg_dedup_pre_llm_hits_total[7d])` | **≈6** | Очень мало; NEXT_SESSION_PLAN упоминал «застрял на 18» — gated на созревание `raw_content_hash` корпуса |
| `increase(tg_dedup_duplicates_detected_total[7d])` | **≈5191** | Выше S0-baseline 1559 — больше календарных суток + billing recovery, не прямое сравнение |
| `tg_channel_processed_coverage_ratio` | Docma_ru **0.992**, labdiagnostica **0.998**, Lab4health **0.998** | Baseline: 0.987 / 0.989 / 0.997 — **регресс-стоп OK** (T1 не срабатывает) |
| Billing 12h | **0** блоков | P0 снят |
| BUG-084 embeddings `429` | периодически | `failed=7/degraded=7` на тиках, `stages_failed=[]` — **не путать** с S3 dedup; не блокер P2, но шум в tick-health |

**Гипотеза низкого pre-LLM hit-rate.** Pre-LLM dedup матчит по `metadata['raw_content_hash']`, который пишется при **новой** обработке (`pipeline.py` Phase 1.5). Старые `processed_documents` без raw-hash не матчатся до re-processing/repost. Эффект S3 **нарастает** с новым inbound-трафиком репостов, а не мгновенно на весь корпус.
</context>

<verified_anchors>
Факты по рабочей копии 2026-07-11 — при смещении строк ориентируйся на символы.

| Что | Где | Факт |
|---|---|---|
| Pre-LLM метрика | `tg_parser/api/metrics.py` (`tg_dedup_pre_llm_hits_total`, `record_pre_llm_dedup_hit`) | Появилась в S3; label `channel_id` |
| Pre-LLM dedup логика | `tg_parser/processing/pipeline.py` (`_find_pre_llm_duplicate`, `_materialize_pre_llm_mirror`, Phase 1.5 в `_process_batch_parallel`, single-path в `process_message`) | Зеркальная строка без LLM; `record_pre_llm_dedup_hit` на hit |
| Post-LLM dedup (legacy) | `pipeline.py` `_filter_duplicates` / `content_hash` post-LLM | Сохранён; S3 не отменяет post-LLM путь |
| Kill-switch S3 | `settings.dedup_enabled` / env `DEDUP_ENABLED` | T1 runbook: `false` → только post-LLM поведение |
| Регресс-стоп | `tg_channel_processed_coverage_ratio` (`api/metrics.py`) | T1: любое падение ниже baseline → расследование |
| S0 baseline дедуп | `S0_BASELINE…md` обл.4 | post-LLM 7d ≈1559; pre-LLM **не существовало** |
| S0 baseline coverage | `S0_BASELINE…md` обл.5 | 13 каналов, см. таблицу |
| Watch команды S3 | `S1_S3_DEPLOY_AND_WATCH.md` § Watch S3 | PromQL + `/metrics` coverage |
| Deploy block SHA | S1 #299 `6a07652`, S2 #300 `39fddff`, S3 #301 `8fd1ca5` | pre-block rollback `f985b9c` |
</verified_anchors>

<design_decision>
**Ключевая развилка сессии — выбор measurement window.** Зафиксируй в deliverable явно:

**Вариант A (рекомендуется): «billing-clean window»**
- Окно: с момента, когда `increase(anthropic_billing_block_total[1h])` стабильно = 0 (ориентир **≥2026-07-10 evening UTC** — верифицируй по PromQL/логам).
- Метрики: `increase(tg_dedup_pre_llm_hits_total[window])`, `increase(tg_dedup_duplicates_detected_total[window])`, `increase(tg_parser_llm_requests_total{model=haiku,status=success}[window])`.
- Плюс: сопоставимо с целью P2 («полный день активной обработки без billing»).
- Минус: окно короче 7d — мало pre-LLM hits ожидаемо.

**Вариант B: «since S3 deploy» (7d calendar)**
- Окно: с 2026-07-07 deploy блока.
- Минус: включает billing-простой → haiku error доминирует; **сравнивать только `status=success`**, error вынести в confounders appendix.

**Вариант C: «forward watch» (если A/B inconclusive)**
- Зафиксировать baseline **сейчас** (`before-forward-watch`) и повторить через 48–72h активной обработки.
- Не блокирует S4, если coverage OK и нет T1 — но S3 ROI остаётся «pending».

**Вердиктные уровни (зафиксируй один):**
1. **PROVEN** — pre-LLM hits > 0 в billing-clean window **и** логи `pre_llm_dedup_hit` коррелируют; haiku success rate не растёт аномально; coverage ≥ baseline.
2. **PARTIAL** — pre-LLM hits есть, но мало (корпус immature); качественные логи подтверждают механизм; рекомендовать forward watch, **не** rollback.
3. **INCONCLUSIVE** — 0 pre-LLM hits при активном inbound + есть репосты в логах → расследовать (dedup flag? raw_hash missing? channel mix?).
4. **REGRESSION** — coverage < baseline (T1) → kill-switch / эскалация, S4 блокируется.

**S1/S2 в том же снимке (кратко, не центр сессии):**
- S1: avg resummarize prompt-tokens/вызов vs baseline 1388 (ожидаем рост).
- S2: tick duration на сопоставимом `new_messages` vs baseline медиана ≈207s; watchlist scores без сдвига.
</design_decision>

<scope>
**Работы (порядок):**
1. **Pre-flight** — `ssh prod`, HEAD, container health, billing 24h=0, BUG-082 QueuePool=0.
2. **Выбрать window** (см. `<design_decision>`) — обосновать в тексте deliverable.
3. **Снять live snapshot** — заполнить S0 §4 шаблон (`SNAPSHOT_ID: after-block-S3-billing-clean-2026-07-11` или аналог).
4. **Сравнить с S0** — таблица delta: pre-LLM hits (new), post-LLM dedup, haiku success, coverage per channel.
5. **Качественная проверка** — `docker logs` grep `pre_llm_dedup_hit` (есть ли реальные события? какие channel_id?).
6. **Confounders appendix** — billing history, BUG-082 restart, embeddings 429 (BUG-084), degraded без stage_fail.
7. **Вердикт + gate S4** — одна строка: `S3 effect: PROVEN|PARTIAL|INCONCLUSIVE|REGRESSION`; `S4: GO|HOLD`.
8. **Обновить docs** — `NEXT_SESSION_PLAN` § P2/P3 чекбоксы; S0 §4 fill-in (или новая секция «after-block-S3»); опционально `S3_DELTA_WATCH_2026-07-11.md` (1–2 стр. executive summary).

**Файлы (ожидаемые):**
- `docs/notes/S0_BASELINE_PROCESSING_METRICS_2026-07-07.md` — §4 fill-in / новая подсекция.
- `docs/notes/NEXT_SESSION_PLAN_POST_S1S3_DEPLOY_2026-07-08.md` — отметить P2 done / P3 partial.
- `docs/notes/S3_DELTA_WATCH_2026-07-11.md` (опционально, если summary не влезает в S0).
</scope>

<out_of_scope>
- **Код, промпты, миграции, `docs/contracts/**`** — не трогать (это не S4).
- **S4/S5 implementation** — только gate-рекомендация.
- **BUG-084 fix** (embeddings 429) — упомянуть как confounder, не чинить здесь.
- **Rollback S3** — только если вердикт REGRESSION (T1); иначе не предлагать.
- **Hard rollback блока** (`f985b9c`) — только при доказанном регрессе coverage + owner approval.
</out_of_scope>

<acceptance_criteria>
Сессия принята, когда:
1. **Window выбран и обоснован** (billing-clean vs 7d vs forward).
2. **S0 §4 заполнен** live-значениями с prod (дата, `API_CONTAINER_STARTED_AT`, PromQL + `/metrics`).
3. **Таблица delta vs S0** для обл.4 (дедуп + haiku success) и обл.5 (coverage) — с явными confounders.
4. **Вердикт S3** одним из четырёх уровней + **gate S4** (GO/HOLD) с 1–2 предложениями why.
5. **Логи** — хотя бы один grep `pre_llm_dedup_hit` за выбранное окно (или явное «0 событий» с интерпретацией).
6. **Tripwires проверены:** T1 coverage OK; T4 billing 24h=0; QueuePool=0 (BUG-082).
7. **Docs обновлены** (минимум NEXT_SESSION_PLAN + S0 §4); commit — по запросу owner.
</acceptance_criteria>

<commands>
Prod read-only bundle (копировать в сессию, адаптировать `WINDOW`):

```bash
ssh prod 'cd /home/user/TG_parser && \
  echo "=== P2 S3 delta $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" && \
  echo "HEAD $(git rev-parse --short HEAD)" && \
  echo "tg_parser started: $(docker inspect -f "{{.State.StartedAt}}" tg_parser)" && \
  docker compose ps --format "table {{.Service}}\t{{.Status}}" tg_parser mcp tg_bot'

# PromQL (подставить WINDOW: 24h | 48h | 7d | billing-clean-since-TIMESTAMP)
ssh prod 'docker exec tg_parser_prometheus wget -qO- \
  "http://localhost:9090/api/v1/query?query=sum(increase(tg_dedup_pre_llm_hits_total[24h]))"'
ssh prod 'docker exec tg_parser_prometheus wget -qO- \
  "http://localhost:9090/api/v1/query?query=sum(increase(tg_dedup_duplicates_detected_total[24h]))"'
ssh prod 'docker exec tg_parser_prometheus wget -qO- \
  "http://localhost:9090/api/v1/query?query=sum%20by%20(model,status)%20(increase(tg_parser_llm_requests_total%5B24h%5D))"'
ssh prod 'docker exec tg_parser_prometheus wget -qO- \
  "http://localhost:9090/api/v1/query?query=sum(increase(tg_parser_anthropic_billing_block_total%5B24h%5D))"'

# Coverage + per-channel pre-LLM (since-restart — справочно)
ssh prod 'curl -fsS http://localhost:8000/metrics | grep -E "^tg_dedup_pre_llm|^tg_channel_processed_coverage"'

# Качественные pre-LLM hits
ssh prod 'cd /home/user/TG_parser && docker compose logs --since 24h tg_parser 2>&1 | grep pre_llm_dedup_hit | tail -20'

# Tick health (confounders)
ssh prod 'cd /home/user/TG_parser && docker compose logs --since 24h tg_parser 2>&1 | grep "Incremental pipeline completed" | tail -5'
ssh prod 'cd /home/user/TG_parser && docker compose logs --since 24h tg_parser 2>&1 | grep -c "QueuePool limit" || true'
ssh prod 'cd /home/user/TG_parser && docker compose logs --since 24h tg_parser 2>&1 | grep -c "429 Too Many Requests.*embeddings" || true'
```

**S0 baseline anchors для сравнения:**

| Метрика | S0 «до» (2026-07-07) |
|---|---|
| `increase(tg_dedup_duplicates_detected_total[7d])` | ≈ **1559** |
| `increase(tg_parser_llm_requests_total{haiku,success}[7d])` | ≈ **5617** |
| pre-LLM hits | **не существовало** |
| coverage (минимумы) | Docma_ru 0.9867, labdiagnostica 0.9893, Lab4health 0.9968 |
</commands>

<workflow>
1. Прочитать normative docs (список выше) + этот START PROMPT.
2. Pre-flight на prod → выбрать measurement window → зафиксировать в черновике вердикта.
3. Снять snapshot (commands) → заполнить S0 §4.
4. Сравнить с baseline → confounders → вердикт + gate S4.
5. Обновить `NEXT_SESSION_PLAN` (P2 ✅, P3 partial); опционально `S3_DELTA_WATCH_*.md`.
6. Self-review: не перепутаны ли billing-error с success; не спутан BUG-084 с S3; coverage проверен per-channel.
7. `git commit` — только по явному запросу owner (docs-only).
</workflow>

<recap>
| Шаг | Что | Приёмка |
|---|---|---|
| Window | billing-clean 24h+ (реком.) | обоснование в deliverable |
| Snapshot | S0 §4 fill-in live prod | дата + PromQL + coverage |
| Delta | vs S0 обл.4/5 | таблица + confounders |
| Вердикт | PROVEN / PARTIAL / INCONCLUSIVE / REGRESSION | одна строка + why |
| Gate S4 | GO / HOLD | при REGRESSION → HOLD |
| Docs | NEXT_SESSION_PLAN, S0 §4 | P2 закрыт в hand-off |
</recap>

---

*Строки кода — по рабочей копии 2026-07-11. Prod-снимок в `<context>` — ориентир; агент обязан перепроверить live в начале сессии.*
