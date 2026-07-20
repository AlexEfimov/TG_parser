# C2 / T7 live prod snapshot — `RESUMMARIZE_MAX_AGE_DAYS` уже выкачен (read-only)

**Дата:** 2026-07-20 · **Тип:** read-only prod snapshot + correction of stale premise · **Режим:** строго read-only prod (Prometheus HTTP API через `tg_parser_prometheus` + `docker exec ... env` / `docker inspect`). Ни один сервис не запускался/останавливался; прод-`.env` не менялся. Единственный записанный артефакт — этот документ (+ runbook-баннер `F5C_DEPLOY_AND_WATCH.md` §T7).

## TL;DR — premise «DORMANT» была stale

START_PROMPT session-C (`START_PROMPT_SESSION_C_T7_OPS_ENABLEMENT_2026-07-20.md` §0) и построенный по нему план C2 исходили из того, что фича F5-C P2 freshness **DORMANT** (`RESUMMARIZE_MAX_AGE_DAYS` в проде unset/`0`, age-триггер ≈ 0). **Live-прод 2026-07-20 показал обратное: knob уже `=14` и age-триггер активно работает.** C2 (Вариант A prod-rollout) фактически **уже выполнен** — включён ещё вечером **2026-07-19 20:36Z** (до даты написания START_PROMPT). Шаг «enable» из плана — moot; «pre-flight baseline с age≈0» снять уже нельзя.

## Что на проде (live, read-only)

| Сигнал | Значение | Источник |
|---|---|---|
| prod `~/TG_parser/.env` | `RESUMMARIZE_MAX_AGE_DAYS=14` (строка 79) | `ssh prod grep` |
| контейнерный OS-env `tg_parser` (то, что реально читает scheduler-синглтон) | `RESUMMARIZE_MAX_AGE_DAYS=14` | `docker exec tg_parser env` |
| `tg_parser` StartedAt | `2026-07-19T20:35:59Z` (knob активен ~19ч на момент снапшота) | `docker inspect` |
| age-gate `tg:resummarize_age_trigger:ratio14d` | **0.503** (маргинально `>= 0.5` gate) | promtool instant |
| alert `ResummarizeAgeTriggerGateF5CPhase2` | `pending` (ещё не выдержал `for:12h` → не `firing`) | promtool `ALERTS{...}` |

**age-триггеры за 24ч (`sum(increase(tg_resummarize_total[24h])) by (channel_id, trigger)`):**
- `labdiagnostica_logical` = 23 (доминирует хвост), `AgeManagment` = 1, `Lab4health` = 1, остальные ≈ 0.
- counter-триггеры ≈ 0 (ожидаемо для low-volume каналов).

**token-cost за 24ч (`sum(increase(tg_resummarize_tokens_total[24h])) by (channel_id, token_type)`):**
- Суммарно ~21.5k prompt + ~2.3k completion на все каналы → копейки на `gpt-4o-mini`. **Cost-риска нет.**

## Трактовка

- Gate `0.503` — по дизайну (runbook §T7 / ADR-0006 #6) это **НЕ инцидент**, а сигнал «age-ветка даёт большинство re-summarize → 14д, возможно, слишком агрессивен, рассмотреть удлинение knob». Значение ровно на границе 0.5 и доминируется одним каналом (`labdiagnostica_logical`), т.е. может быть шумом.
- Единственный cost-риск C2 (spike на первом включении) уже прошёл (~19ч аптайма, cost негативно не растёт).

## Решение владельца (2026-07-20)

1. **Оставить `RESUMMARIZE_MAX_AGE_DAYS=14`, продолжить watch** — прод-мутацию НЕ делаем (0.503 на границе). Пересмотреть при устойчивом `ratio14d >= 0.5` (alert перейдёт `pending → firing` после 12ч).
2. Если решим снижать агрессивность — bump `14 → 21`/`30` тем же re-create-путём (`.env` + `docker compose up -d tg_parser`, НЕ `restart`; см. runbook §T7).
3. Зафиксировать факт live-состояния в runbook-баннере §T7 (сделано) и здесь.

## Read-only команды (для воспроизводимости)

```bash
# knob (container OS-env — то, что читает worker)
ssh prod 'docker exec tg_parser env | grep -iE "resummarize"'
# gate + trigger split + tokens
ssh prod "docker exec tg_parser_prometheus promtool query instant http://localhost:9090 'tg:resummarize_age_trigger:ratio14d'"
ssh prod "docker exec tg_parser_prometheus promtool query instant http://localhost:9090 'sum(increase(tg_resummarize_total[24h])) by (channel_id, trigger)'"
ssh prod "docker exec tg_parser_prometheus promtool query instant http://localhost:9090 'sum(increase(tg_resummarize_tokens_total[24h])) by (channel_id, token_type)'"
# alert state
ssh prod "docker exec tg_parser_prometheus promtool query instant http://localhost:9090 'ALERTS{alertname=\"ResummarizeAgeTriggerGateF5CPhase2\"}'"
```

## Ссылки

- Runbook §T7 (баннер обновлён): [`F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md).
- Session-C бриф (stale premise §0): [`START_PROMPT_SESSION_C_T7_OPS_ENABLEMENT_2026-07-20.md`](START_PROMPT_SESSION_C_T7_OPS_ENABLEMENT_2026-07-20.md).
- C1 guard + C3 runbook fix: PR #336 (merge `b6ca9df`).
