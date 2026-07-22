# START PROMPT — Session δ: T7 gate response (keep-14 vs bump)

**Дата:** 2026-07-22 · **Тип:** ops (read-only metrics + optional prod knob bump + docs) · **Ветка:** `main` (или feature-ветка от актуального `main` для docs-only правок)

**Goal (одной строкой):** закрыть T7 watch на `RESUMMARIZE_MAX_AGE_DAYS=14` — re-snapshot prod metrics, owner-aligned verdict **keep 14** или **bump 21/30**, verify OS-env, обновить snapshot/runbook/ROADMAP.

> Рабочий режим (нормативно, [`AGENTS.md`](../../AGENTS.md)): `git commit` / PR — **только** по явному запросу пользователя. Никаких правок `docs/methodology/**`. Прод-мутация (`.env` bump) — **только** при явном in-session owner GO после re-snapshot; иначе docs-only verdict. **НЕ** `docker compose restart` для knob (BUG-078) — только `docker compose up -d tg_parser`.

**Prerequisite SoT:**
- Track δ: [`DRAFT_NEXT_CONTRACT_POST_GAMMA_CLOSEOUT_2026-07-20.md`](DRAFT_NEXT_CONTRACT_POST_GAMMA_CLOSEOUT_2026-07-20.md) §2 / §3
- Prior live snapshot: [`C2_T7_LIVE_SNAPSHOT_2026-07-20.md`](C2_T7_LIVE_SNAPSHOT_2026-07-20.md)
- Runbook §T7: [`F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md)
- Planning note (this session): [`PLAN_SESSION_DELTA_T7_GATE_RESPONSE_2026-07-22.md`](PLAN_SESSION_DELTA_T7_GATE_RESPONSE_2026-07-22.md)
- ε+ζ landed: PR #342 / `f4073a6` — **не переоткрывать**

**Watch status (DECIDED — gate satisfied):**
- Knob LIVE since **2026-07-19T20:35:59Z** (Cyprus ≈ 19.07 23:36 EEST)
- +48h full watch **PASSED** ≈ **2026-07-21 23:36 EEST**
- Last known live (~2026-07-21 21:44Z): `ratio14d≈0.984`, alert **firing**, tokens ~303k prompt + ~40k completion / 24h
- Fresh read-only (2026-07-22T14:51Z): `ratio14d≈0.989`, alert **firing**, tokens ~52.9k prompt + ~8.5k completion / 24h; age dominates (`labdiagnostica_logical`, `mediamedics`, …)

**Последовательность владельца:** ε+ζ ✅ → **эта сессия δ** → parking-lot (TTL impl / Wave E / F11 HTTP) только по отдельному GO.

---

## 0. TL;DR

| Step | Action | Type |
|---|---|---|
| 1 | Re-snapshot prod metrics (promtool + `docker exec tg_parser env`) | read-only |
| 2 | Owner-aligned recommendation: **default bump → 21** unless fresh data says keep-14 or owner wants 30 | decision |
| 3a | **GO bump:** prod `.env` → `21` (or `30`) → `docker compose up -d tg_parser` → verify OS-env | ops |
| 3b | **NO-GO keep-14:** document verdict + rationale (needs sustained `ratio14d<0.5`) | docs |
| 4 | Update snapshot note, runbook §T7 banner, ROADMAP **Next** | docs |

**Hard OUT this session:** TTL code impl, Wave E, F11 HTTP, ε rework, methodology, `pyproject.toml`.

---

## 1. Контекст

T7 freshness knob (`RESUMMARIZE_MAX_AGE_DAYS`) включён в проде с 2026-07-19. Karpathy loop (ADR-0006 #6): measure → decide. Gate alert `ResummarizeAgeTriggerGateF5CPhase2` fires when trailing-14d age-share ≥ 50% for 12h — **info signal**, not incident.

2026-07-20 owner decision: hold `=14`, continue watch (ratio marginal 0.503). Since then ratio climbed to ~0.99, alert **firing**, multiple channels age-dominated. Full +48h watch complete → **δ unblocked**.

**Default recommendation entering session:** bump **`14 → 21`** (conservative). Choose **30** only if owner wants aggressive cost cut. **Keep 14** only if fresh re-snapshot shows sustained `<0.5` and alert cleared.

---

## 2. Anchors (перечитать перед действием)

| Якорь | Файл | Примечание |
|---|---|---|
| Knob settings | `tg_parser/config/settings.py` (~1134) | `resummarize_max_age_days` |
| BUG-078 OS-env priority | runbook §T7, BUG_LOG | `restart` ≠ re-create |
| PromQL recording rule | `docker/prometheus/alerts.yml` | `tg:resummarize_age_trigger:ratio14d` |
| Grafana row | `docker/grafana/dashboards/wave2_observation.json` | T7 F5-C P2 panels |
| Rollback | runbook §T7 Rollback | `=0` or back to `=14` + `up -d` |

### Read-only commands (reproducible)

```bash
# knob (container OS-env — authoritative for scheduler)
ssh prod 'docker exec tg_parser env | grep -iE "resummarize"'
ssh prod 'grep RESUMMARIZE_MAX_AGE_DAYS ~/TG_parser/.env'

# gate + triggers + tokens + alert
ssh prod "docker exec tg_parser_prometheus promtool query instant http://localhost:9090 'tg:resummarize_age_trigger:ratio14d'"
ssh prod "docker exec tg_parser_prometheus promtool query instant http://localhost:9090 'sum(increase(tg_resummarize_total[24h])) by (channel_id, trigger)'"
ssh prod "docker exec tg_parser_prometheus promtool query instant http://localhost:9090 'sum(increase(tg_resummarize_tokens_total[24h])) by (channel_id, token_type)'"
ssh prod "docker exec tg_parser_prometheus promtool query instant http://localhost:9090 'sum(increase(tg_resummarize_tokens_total[24h])) by (token_type)'"
ssh prod "docker exec tg_parser_prometheus promtool query instant http://localhost:9090 'ALERTS{alertname=\"ResummarizeAgeTriggerGateF5CPhase2\"}'"
ssh prod "docker inspect tg_parser --format '{{.State.StartedAt}}'"
```

### Apply bump (ONLY after owner GO in session)

```bash
# on prod host ~/TG_parser
# edit .env: RESUMMARIZE_MAX_AGE_DAYS=21   # or 30
docker compose up -d tg_parser    # RE-CREATE — NOT restart
ssh prod 'docker exec tg_parser env | grep RESUMMARIZE_MAX_AGE_DAYS'
```

---

## 3. Scope — детально

### 3.1 Re-snapshot + recommendation

- Run read-only commands §2; record UTC timestamp.
- Tabulate: ratio14d, alert state, per-channel age/counter split, token totals.
- Write short recommendation memo (in snapshot note or session PR body):
  - **keep-14** if ratio sustained `<0.5` and alert not firing;
  - **bump-21** (default) if ratio ≥0.5 + alert firing + cost acceptable;
  - **bump-30** if owner explicitly prefers aggressive relaxation.

### 3.2 Prod apply (conditional on GO)

- Edit prod `~/TG_parser/.env` line `RESUMMARIZE_MAX_AGE_DAYS`.
- `docker compose up -d tg_parser` from prod compose dir.
- Verify container OS-env matches `.env`.
- Note: alert may remain firing until ratio14d window incorporates post-bump period — document expectation.

### 3.3 Docs updates

| Artifact | Update |
|---|---|
| New snapshot | `docs/notes/C2_T7_LIVE_SNAPSHOT_2026-07-22.md` or `DELTA_T7_VERDICT_2026-07-22.md` — metrics + verdict |
| Runbook §T7 banner | [`F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md) — post-verdict knob value + watch closed |
| ROADMAP **Next** | [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) — δ closed; pointer to verdict note |
| DRAFT (optional) | One-line pointer §2 Track δ → this START_PROMPT / verdict note |

---

## 4. Out of scope (жёстко)

- **TTL implementation** (Alembic, purge job, Settings) — ζ skeleton only; separate GO.
- **Wave E** graph retrieval, **F11 HTTP** CRUD, webhook 2A.
- **ε rework** (DF-1, dogfood notes) — closed in #342.
- `docs/methodology/**`, `pyproject.toml` / `requirements.txt`.
- Starting unrelated tracks mid-session even if tempting.

---

## 5. Acceptance criteria

- [ ] Fresh prod metrics snapshot with UTC timestamp (ratio14d, alert, triggers, tokens, OS-env).
- [ ] Verdict recorded: **keep-14** (with evidence) **OR** bump applied with post-change OS-env `=21`/`=30`.
- [ ] Runbook §T7 banner reflects current knob + watch status (closed or passive re-watch if bumped).
- [ ] ROADMAP **Next** updated (δ no longer «pending after watch»).
- [ ] Rollback path documented (`=14` or `=0` + `up -d`).
- [ ] Zero TTL code / Wave E / F11 HTTP changes.
- [ ] Commit/PR only on explicit user request.

---

## 6. Quality / ops gate commands

```bash
# read-only pre/post (always safe)
ssh prod "docker exec tg_parser_prometheus promtool query instant http://localhost:9090 'tg:resummarize_age_trigger:ratio14d'"
ssh prod "docker exec tg_parser_prometheus promtool query instant http://localhost:9090 'ALERTS{alertname=\"ResummarizeAgeTriggerGateF5CPhase2\"}'"
ssh prod 'docker exec tg_parser env | grep RESUMMARIZE_MAX_AGE_DAYS'

# post-bump only (after up -d)
ssh prod "docker inspect tg_parser --format '{{.State.StartedAt}}'"   # should change on re-create
ssh prod 'grep RESUMMARIZE_MAX_AGE_DAYS ~/TG_parser/.env'
ssh prod 'docker exec tg_parser env | grep RESUMMARIZE_MAX_AGE_DAYS'  # must match .env

# repo quality (if any local docs/code touched)
uv run ruff check .
uv run ruff format --check .
```

---

## 7. Decisions (already taken — do not re-open without cause)

1. **Watch complete** — +48h passed (~2026-07-21 23:36 EEST); δ is **now**, not date-gated.
2. **Default bump target = 21** unless fresh evidence supports keep-14 or owner chooses 30.
3. **Alert firing + ratio≥0.5** → prefer bump if cost acceptable (not an incident).
4. **Prod mutation** requires clear in-session owner GO; planning alone does not bump.
5. **Re-create path only** — `docker compose up -d tg_parser`, never `restart` (BUG-078).
6. **Commit/PR** — explicit user request only.

---

## 8. Ссылки

- Planning note: [`PLAN_SESSION_DELTA_T7_GATE_RESPONSE_2026-07-22.md`](PLAN_SESSION_DELTA_T7_GATE_RESPONSE_2026-07-22.md)
- DRAFT δ: [`DRAFT_NEXT_CONTRACT_POST_GAMMA_CLOSEOUT_2026-07-20.md`](DRAFT_NEXT_CONTRACT_POST_GAMMA_CLOSEOUT_2026-07-20.md) §2
- Prior snapshot: [`C2_T7_LIVE_SNAPSHOT_2026-07-20.md`](C2_T7_LIVE_SNAPSHOT_2026-07-20.md)
- Runbook §T7: [`F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md)
- ROADMAP: [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) § Post-Wave-2
- ε+ζ START_PROMPT (format ref): [`START_PROMPT_SESSION_EPS_ZETA_INTERNAL_FILL_TTL_SKELETON_2026-07-20.md`](START_PROMPT_SESSION_EPS_ZETA_INTERNAL_FILL_TTL_SKELETON_2026-07-20.md)
- ADR-0006 (#6 freshness loop), issue #15 stale-detector context
