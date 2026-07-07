# Runbook — S1+S2+S3 Deploy + Watch (remediation block)

**Тип документа:** deploy/rollback runbook (нормативно для выката блока S1–S3).
**Дата:** 2026-07-07 · **Статус:** `active`.
**Основание:**
- Каденция: [`../notes/WORKFLOW_REMEDIATION_SESSIONS_AGREEMENTS_2026-07-07.md`](../notes/WORKFLOW_REMEDIATION_SESSIONS_AGREEMENTS_2026-07-07.md) §3 (S1–S3 выкатываются **одним безопасным блоком**).
- Baseline «до»: [`../notes/S0_BASELINE_PROCESSING_METRICS_2026-07-07.md`](../notes/S0_BASELINE_PROCESSING_METRICS_2026-07-07.md).
- Находки: [`../notes/CODE_REVIEW_PROCESSING_ALGORITHMS_FABLE5_2026-07-07.md`](../notes/CODE_REVIEW_PROCESSING_ALGORITHMS_FABLE5_2026-07-07.md), план [`../notes/PLAN_REMEDIATION_SESSIONS_PROCESSING_ALGORITHMS_2026-07-07.md`](../notes/PLAN_REMEDIATION_SESSIONS_PROCESSING_ALGORITHMS_2026-07-07.md).
- Образец процедуры: [`F5C_DEPLOY_AND_WATCH.md`](F5C_DEPLOY_AND_WATCH.md), [`SERVER_ARCHITECTURE.md`](../SERVER_ARCHITECTURE.md).

> ⚠️ **Ключевое отличие от F5-C:** блок S1–S3 **не содержит миграций и не меняет `docs/contracts/**`** (WORKFLOW §7). Деплой = `git pull` + рестарт контейнеров. Откат = `git checkout <pre-block>` + рестарт. Шага `db upgrade`/`db downgrade` НЕТ.

---

## Что входит в блок

| Сессия | Находки (O-code) | Суть | Риск |
|---|---|---|---|
| **S1** | F-02 / O-1 (+O-9a) | Re-summarize LLM теперь получает текст документов (`summary` + срез `text_clean`); один LLM-клиент на тик. | Низкий (баг-фикс: фича перестаёт быть no-op'ом; **+токены/вызов** by design). |
| **S2** | F-03 / F-07 / F-08 (O-3/O-6/O-7) | refs-only загрузка в тике (O(N²)→O(N)); single-pass watchlist-лемматизация (O(I×D)→O(D)); model-scoped LLM cache-key. | Низкий (поведенческая эквивалентность). |
| **S3** | F-01 / F-09 (O-2/O-8) | Pre-LLM дедуп по raw-hash (мирроры вместо оплаченного LLM-вызова); батч-lookup'ы вместо per-message `exists()`. | Низкий (post-LLM дедуп сохранён; `dedup_enabled`/`force` учтены). |

**Merge-коммиты блока (`main`, first-parent):**
- S1 — PR #299 → `6a07652`
- S2 — PR #300 → `39fddff`
- S3 — PR #301 → `8fd1ca5`
- **Rollback-цель (pre-block `main`):** `f985b9c` (`chore(ci): apply ruff 0.15.11 format across repo (#302)`).

---

## Pre-deploy checklist

| # | Что | Как проверить |
|---|---|---|
| 1 | Все три PR смерджены в `main` | `git log --oneline --first-parent -4 main` → merge-коммиты #301/#300/#299 |
| 2 | CI на tip `main` зелёный | `gh run list --branch main --limit 1` / Actions UI |
| 3 | Нет незакоммиченных миграций | `git diff f985b9c..main -- 'tg_parser/**/alembic/**' 'tg_parser/**/migrations/**'` → **пусто** (блок без миграций) |
| 4 | LLM-провайдеры здоровы (S1 повышает resummarize-токены) | [`ANTHROPIC_BILLING_RECOVERY.md`](ANTHROPIC_BILLING_RECOVERY.md) § health check; `curl -s localhost:8000/metrics \| grep anthropic_billing_block` |
| 5 | Снят снапшот `before-block` (S0 §4) | значения из § Watch ниже зафиксированы ДО рестарта |
| 6 | Известен pre-block SHA для отката | `f985b9c` (см. выше) |

---

## Deploy

Хост и путь — из S0 §1 / [`SERVER_ARCHITECTURE.md`](../SERVER_ARCHITECTURE.md): ssh-хост `prod`, canonical path `/home/user/TG_parser`.

### 1. Pull кода на prod

```bash
ssh prod
cd /home/user/TG_parser
git fetch origin
git checkout main
git pull --ff-only origin main

# Sanity
git log --oneline --first-parent -4   # должны быть merge-коммиты #299/#300/#301
git rev-parse --short HEAD             # запомнить как post-block SHA (для отчёта)
```

### 2. Рестарт сервисов (миграций НЕТ)

```bash
docker compose pull
# Compose services: tg_parser (API + scheduler), mcp, tg_bot (profile=bot).
docker compose --profile bot up -d --no-deps tg_parser mcp tg_bot
docker compose ps    # все Up (healthy)
```

> 📦 Single-node → ~5s downtime; бот переподключится (long-polling). Миграции не накатываются — схема БД не менялась.

### 3. Smoke tests (через ~30s)

```bash
# (a) API живой + метрики
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/metrics | grep -c '^tg_dedup_pre_llm_hits_total'  # ≥1 (серия зарегистрирована; значение может быть 0 до первого хита)

# (b) один scheduler-тик отработал без ошибок
docker compose logs --since 10m tg_parser | grep "Incremental pipeline completed"
# → строка(и) с duration=…; без трейсбеков рядом

# (c) дедуп-путь жив (S3): после тика с репостами
curl -fsS http://localhost:8000/metrics | grep -E '^tg_dedup_(pre_llm_hits|duplicates_detected)_total'
```

Если (a)–(c) зелёные — деплой успешен, переходим к Watch.

---

## Watch — дельты к S0-baseline

Снимать по шаблону S0 §4 через ~1ч / ~4ч / ~24ч. Все запросы read-only (PromQL через `tg_parser_prometheus`, `/metrics`, `docker logs`).

### S1 — resummarize обогатился (ожидаем рост токенов/вызов)

```bash
curl -s http://127.0.0.1:8000/metrics | grep -E '^tg_resummarize_(tokens_total|total|duration_seconds_(count|sum))'
```
- **Acceptance:** avg prompt-tokens/вызов вырос с baseline **≈1388** до ≈+1.5–3.5K; `outcome=ok` доминирует; в рамках 50K/tick cap. Регресс-стоп: доля `llm_error` не выросла.

### S2 — длительность тика не выросла; watchlist байт-в-байт

```bash
docker logs tg_parser --since 48h 2>&1 | grep 'Incremental pipeline completed'
curl -s http://127.0.0.1:8000/metrics | grep -E '^tg_watchlist_(score_(count|sum)|matches_total)'
```
- **Acceptance:** на тиках с сопоставимым `details.new_messages` duration **не выше** baseline (медиана ≈207s). Watchlist score распределение и `matches_total` — **без сдвига** (O-7 = поведенческая эквивалентность).

### S3 — pre-LLM дедуп срабатывает, processing-вызовы падают

```bash
docker exec tg_parser_prometheus wget -qO- \
  'http://localhost:9090/api/v1/query?query=sum(increase(tg_dedup_pre_llm_hits_total[7d]))'      # НОВАЯ — ожидаем >0
docker exec tg_parser_prometheus wget -qO- \
  'http://localhost:9090/api/v1/query?query=sum(increase(tg_dedup_duplicates_detected_total[7d]))'  # post-LLM — ожидаем СНИЖЕНИЕ vs 1559
docker exec tg_parser_prometheus wget -qO- \
  'http://localhost:9090/api/v1/query?query=sum by (model,status) (increase(tg_parser_llm_requests_total[7d]))'  # haiku success — ожидаем СНИЖЕНИЕ vs 5617
```
- **Acceptance:** `tg_dedup_pre_llm_hits_total > 0`; экзакт-репосты уходят в pre-LLM счётчик, `tg_parser_llm_requests_total{model=haiku,status=success}` снижается пропорционально доле репостов.
- **Регресс-стоп (обязательный):** `tg_channel_processed_coverage_ratio` per-channel **не падает** ниже baseline (S0 §2 обл.5). Падение coverage = дедуп режет лишнее → откат S3.

```bash
curl -s http://127.0.0.1:8000/metrics | grep '^tg_channel_processed_coverage_ratio'
```

---

## Tripwires → действия

| Tripwire | Сигнал | Действие |
|---|---|---|
| **T1 — coverage упал** | любой канал `coverage_ratio` < baseline | kill-switch S3: `DEDUP_ENABLED=false` в `.env` + `docker compose restart tg_parser` (вернётся к post-LLM-only поведению; pre-LLM дедуп выключится). Затем разобрать причину. |
| **T2 — resummarize llm_error вырос** | `outcome=llm_error` доля > baseline | S1: `RESUMMARIZE_ENABLED=false` (kill-switch фичи) или снизить `RESUMMARIZE_INPUT_WINDOW_N`; см. [`F5C_DEPLOY_AND_WATCH.md`](F5C_DEPLOY_AND_WATCH.md) § Tripwire #1. |
| **T3 — длительность тика выросла** | duration на сопоставимом `new_messages` > baseline | проверить логи тика на N+1/повторные загрузки; если регресс из S2 — hard rollback блока (ниже). |
| **T4 — billing pause** | `anthropic_billing_block_total` delta > 0 | [`ANTHROPIC_BILLING_RECOVERY.md`](ANTHROPIC_BILLING_RECOVERY.md). S1 повышает resummarize-спенд — проверить лимиты. |

---

## Rollback

Блок **backward-compatible** и **без миграций** → откат кода достаточен.

### Мягкий (пофичный kill-switch, мгновенно)

```bash
cd /home/user/TG_parser
# S3 — выключить дедуп (в т.ч. pre-LLM):
echo "DEDUP_ENABLED=false" >> .env
# S1 — выключить re-summarize:
echo "RESUMMARIZE_ENABLED=false" >> .env
docker compose restart tg_parser
```
(S2 — чистый рефактор без флага; отдельного kill-switch нет — откатывается только hard-rollback'ом.)

### Жёсткий (вернуть весь блок к pre-block `main`)

```bash
cd /home/user/TG_parser
git checkout f985b9c          # pre-block main (до #299/#300/#301)
docker compose pull && docker compose --profile bot up -d --no-deps tg_parser mcp tg_bot
docker compose ps
# Миграции откатывать НЕ нужно — блок их не вводил.
git log --oneline --first-parent -1   # подтвердить f985b9c
```

> После стабилизации вернуться на `main` (`git checkout main && git pull`) — откат через detached HEAD временный.

---

## Post-watch (через ~24ч)

1. Снять дельты S1/S2/S3 из § Watch (before-block vs after-block).
2. Зафиксировать в отдельном after-снапшоте по шаблону S0 §4 (`SNAPSHOT_ID: after-block-S1S3`).
3. Обновить статус в [`../notes/WORKFLOW_REMEDIATION_SESSIONS_AGREEMENTS_2026-07-07.md`](../notes/WORKFLOW_REMEDIATION_SESSIONS_AGREEMENTS_2026-07-07.md) §8 (эффект блока подтверждён / регрессов нет).
4. Если coverage не просел и токен-эффект виден — блок считается производственно-стабильным; переходить к S4 (по каденции §3 — отдельно, с read-only симуляцией).
