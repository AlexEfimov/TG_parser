# START — Wave 1 Step 3 — closure 24h watch (2026-05-23)

> **Открой этот файл в новом Cursor-чате** (fresh context). Workspace:
> `/Users/alexanderefimov/TG_parser`. Запускать строго **после ~14:25 MSK
> 2026-05-23** (когда окно реально закроется).

---

## 1. Назначение сессии

Закрыть 24h watch для **Wave 1 step 3** (`a30abd5`, PR #89), накрытого сверху
step 3.1 (`b875faf`, PR #90) и follow-ups (`d143e5d`, PR #91), и **финализировать
DONE marker**.

**НЕ начинать step 4** (Shareable Digest, ADR 0008) в этой же сессии — отдельный
планирующий промпт создаётся уже после GREEN verdict.

Контекст и предыстория — handoff:
[`HANDOFF_WAVE1_STEP3_1_AND_FOLLOWUPS_2026-05-22.md`](HANDOFF_WAVE1_STEP3_1_AND_FOLLOWUPS_2026-05-22.md).

---

## 2. Пре-флайт

```bash
cd /Users/alexanderefimov/TG_parser
git fetch origin
git checkout main
git pull --ff-only origin main
git rev-parse HEAD     # ≥ 816661d (handoff note); прод уже на d143e5d
```

**Окно watch (UTC):**

| Поле | Значение |
|---|---|
| OPEN (declared) | `2026-05-22T11:25:47Z` (~14:25 MSK 22-05) |
| CLOSE (declared) | `~2026-05-23T11:25:47Z` (~14:25 MSK 23-05) |
| Фактический START / END | взять из `docker inspect` рестартов на prod (см. § 3, шаг 1) |

**Прод HEAD на VPS** (для справки, в этой сессии **не передеплоиваем**):

| Время | HEAD | Что |
|---|---|---|
| `2026-05-22T14:01:40Z` | `b875faf` | step 3.1 deploy (PR #90) |
| `2026-05-22T17:42:42Z` | `d143e5d` | follow-ups deploy (PR #91) |

**Pytest baseline (информативно, не блокер):** `2195 / 311 / 0` default;
`2499 / 9 / 0` `TEST_POSTGRES=1` — зафиксировано в handoff после `d143e5d`.

**Не трогать:** `pyproject.toml`, `requirements*.txt`, `uv.lock`, `docs/methodology/**`.

---

## 3. Шаги closure (последовательно)

### Step 1 — Prometheus queries (24h range)

Сначала вытащить фактические START/END из рестартов `tg_parser` на prod:

```bash
ssh -p 2296 user@212.72.189.15 \
  'docker inspect -f "{{.State.StartedAt}}" tg_parser tg_parser_mcp tg_parser_bot'
# самый ранний из трёх StartedAt после follow-ups deploy = START
# START + 24h = END (или now() если выходим раньше — но цель именно 24h)
```

Затем три запроса (заменить `$START`, `$END` ISO-таймштампами с `Z`):

```bash
# 1) up{service="api"} — gap-detection
ssh -p 2296 user@212.72.189.15 'docker exec tg_parser_prometheus wget -qO- \
  "http://localhost:9090/api/v1/query_range?query=up{service=\"api\"}&start='"$START"'&end='"$END"'&step=900"'

# 2) idempotency hits/misses/mismatches (counter, по labels result)
ssh -p 2296 user@212.72.189.15 'docker exec tg_parser_prometheus wget -qO- \
  "http://localhost:9090/api/v1/query_range?query=tg_idempotency_keys_hit_total&start='"$START"'&end='"$END"'&step=900"'

# 3) idempotency table size (gauge, обновляется после hourly cleanup)
ssh -p 2296 user@212.72.189.15 'docker exec tg_parser_prometheus wget -qO- \
  "http://localhost:9090/api/v1/query_range?query=tg_idempotency_keys_table_size&start='"$START"'&end='"$END"'&step=900"'
```

Сохранить JSON ответы в локальные файлы (`/tmp/watch_*_2026-05-23.json` или
inline в WATCH_WINDOW).

### Step 2 — Log scan

```bash
ssh -p 2296 user@212.72.189.15 \
  "docker logs --since '$START' --until '$END' tg_parser 2>&1 \
   | grep -iE '/api/v1/(watchlists|digests|pipeline)' \
   | grep -iE 'error|5xx|exception'"
```

Ожидание GREEN: **пусто** или только известные `409 JobAlreadyRunning` /
`422 IdempotencyKeyMismatch` / `429` (это **не** 5xx).

### Step 3 — Заполнить WATCH_WINDOW

В [`WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md`](WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md):

- Фактические ISO START / END (из § 3, шаг 1).
- Краткая сводка по каждому из 3 prometheus-запросов (числа / последняя точка).
- Результат log scan (count матчей, или «empty»).
- В блоке **Verdict**: `Status: CLOSED`, `Final verdict: GREEN` (или `RED` со
  ссылкой на BUG-XXX и hotfix-план — см. § 5).

### Step 4 — Финализировать DONE marker

В [`REVIEW_2026-05-21_WAVE1_STEP3_DONE.md`](REVIEW_2026-05-21_WAVE1_STEP3_DONE.md):

- **§ 2 «Acceptance signals»** — обновить колонку «Watch verdict» для строк 5–6
  (idempotency metrics) c `pending 24h` → `PASS` (с цифрами).
- **§ 3 «Post-watch state»** — добавить prometheus snapshot summary, log scan
  результат, обязательно отметить что `Idempotency-Key` replay на prod уже
  возвращает `created: false` (зафиксировано в immediate smoke после `d143e5d` —
  батарея A из handoff).
- **§ 6 «Lessons learned»** — 3–5 буллитов в стиле Wave 1 step 2 precedent
  (`REVIEW_2026-05-14_WAVE1_STEP2_DONE.md`): отделить «new bug surfaced by watch»
  от «regression introduced» через `git diff a30abd5^ a30abd5`.

Снять **STATUS NOTE** stub-блок в шапке файла.

### Step 5 — Commit + push на `main`

Doc-only direct push на `main`. **Прецеденты:** `84f63ff`
(`docs(wave1): S3.1 planning ...`), `816661d` (`docs(wave1): handoff note ...`).

```bash
git add docs/notes/WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md \
        docs/notes/REVIEW_2026-05-21_WAVE1_STEP3_DONE.md
git commit -m "docs(milestone): wave1 step 3 DONE — 24h watch GREEN"
git push origin main
git log -1 --oneline   # зафиксировать SHA для отчёта
```

Если verdict **RED** — заголовок другой: см. § 5.

---

## 4. GREEN критерии

| # | Признак | Источник |
|---|---|---|
| 1 | Нет 5xx / error spikes на `/api/v1/(watchlists\|digests\|pipeline)` за окно | log scan (§ 3, шаг 2) |
| 2 | `tg_idempotency_keys_hit_total` инкрементируется (есть `result=hit` / `result=miss`) | prometheus q-2 |
| 3 | `tg_idempotency_keys_table_size` — gauge ненулевой, обновлялся после T+1h cleanup | prometheus q-3 |
| 4 | `up{service="api"}` без длительных gap'ов (>1 scrape интервал подряд) | prometheus q-1 |

Все 4 — `PASS` → verdict **GREEN**, шаг 5 = commit с заголовком DONE.

---

## 5. Если RED

1. **НЕ закрывать** DONE marker (`REVIEW_2026-05-21_WAVE1_STEP3_DONE.md` остаётся
   stub'ом, status note **не снимать**).
2. Завести запись в [`BUG_LOG.md`](BUG_LOG.md) → следующий `BUG-NNN` (после
   BUG-022 / последнего активного — проверить grep'ом), severity по последствиям,
   `Discovered: 2026-05-23 (24h watch closure)`.
3. Открыть hotfix-ветку: `fix/wave1-step3-watch-red-2026-05-23`.
4. Rollback (если нужен немедленный откат) —
   [`docs/runbooks/WAVE1_STEP3_DEPLOY_AND_WATCH.md` § Rollback](../runbooks/WAVE1_STEP3_DEPLOY_AND_WATCH.md).
   Целевые SHA для отката:
   - `b875faf` — step 3.1 (откат только follow-ups).
   - `a30abd5` — step 3 baseline (полный откат сурфэйса 3 + 3.1).
5. Commit message для finalization-commit в этом случае:
   `docs(milestone): wave1 step 3 watch — RED, hotfix BUG-NNN`,
   и в DONE marker `§ 3` явно зафиксировать verdict RED + ссылку на BUG и
   hotfix-ветку.

---

## 6. Что НЕ делать

- Не начинать планирование **step 4** (Shareable Digest, ADR 0008) в этой сессии
  — отдельный планирующий промпт после GREEN, в следующем окне.
- Не трогать `uv.lock`, `pyproject.toml`, `requirements*.txt`,
  `docs/methodology/**` (workspace [`AGENTS.md`](../../AGENTS.md) hard rules).
- Не запускать на VPS `docker compose build` / `pull` / migration —
  прод уже на `d143e5d`, ничего пересобирать не нужно.
- Не создавать новые PR в этой сессии — closure идёт **direct doc-only push** на
  `main` (прецеденты `84f63ff`, `816661d`).

---

## 7. Дальше

- **После GREEN closure:** планирующая сессия Wave 1 step 4 (Shareable Digest,
  ADR 0008) — re-read ADR 0008 § Options, [`PARITY_DECISION_TRACKING.md` § 3](PARITY_DECISION_TRACKING.md),
  audience hints A2. Output → `docs/notes/START_PROMPT_SPRINT_WAVE1_STEP4_*.md`.
- **Compose-integration в CI** (harness уже в дереве, `@compose_only` marker
  есть) — остаётся в backlog (`HANDOFF...md` § Open items #3): отдельный PR с CI
  job (compose up → `pytest -m compose_only` → tear-down).

---

## История

| Дата | Событие |
|---|---|
| 2026-05-22 | Step 3.1 deploy `b875faf` (14:01 UTC) → follow-ups `d143e5d` (17:42 UTC); handoff `816661d`. |
| 2026-05-22 | START prompt для closure сессии создан (этот файл). |
