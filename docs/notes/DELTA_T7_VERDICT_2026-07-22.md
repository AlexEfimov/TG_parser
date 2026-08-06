# δ / T7 gate verdict — keep-14 vs bump (2026-07-22)

**Дата:** 2026-07-22 · **Тип:** ops read-only re-snapshot → owner GO → prod bump applied · **Режим:** prod **мутирован** по явному in-session owner GO (bump `14 → 21`, re-create через `docker compose up -d tg_parser`). Артефакты: этот note + обновления runbook §T7 / ROADMAP **Next** / DRAFT Track δ.

> **✅ APPLIED 2026-07-22T19:49:08Z (owner GO «GO 21»).** Prod `.env` + container OS-env = `RESUMMARIZE_MAX_AGE_DAYS=21`; `tg_parser` StartedAt → `2026-07-22T19:49:08Z`, health `healthy`. Backup: `~/TG_parser/.env.bak.delta-t7-20260722T194808Z`. Post-apply `ratio14d≈0.987` (ожидаемый lag — trailing-14d окно ещё не вобрало post-bump трафик; см. «Expectation after bump»). Rollback: `=14` (или `=0`) + `up -d`.

**START_PROMPT:** [`START_PROMPT_SESSION_DELTA_T7_GATE_RESPONSE_2026-07-22.md`](START_PROMPT_SESSION_DELTA_T7_GATE_RESPONSE_2026-07-22.md)

---

## TL;DR

| Item | Value |
|---|---|
| Snapshot UTC | **2026-07-22T14:56Z** (initial) · confirm **14:59:01Z** · apply **19:49:08Z** |
| Knob (`.env` + OS-env) | `RESUMMARIZE_MAX_AGE_DAYS=21` (bumped from `14` at 19:49Z; было unchanged since 2026-07-19) |
| `tg_parser` StartedAt | `2026-07-22T19:49:08Z` (re-created on bump; было `2026-07-19T20:35:59Z`) |
| `tg:resummarize_age_trigger:ratio14d` | **≈0.989** pre-bump (confirm 14:59Z: `0.988531910024928`) · **≈0.987** post-bump (lag) |
| Alert `ResummarizeAgeTriggerGateF5CPhase2` | **firing** (`severity=info`) — ожидаемо остаётся red до прокрутки trailing-14d окна |
| +48h watch | **PASSED** (~2026-07-21 23:36 EEST) |
| **Verdict** | **bump `14 → 21`** (conservative default) — **✅ APPLIED** |
| **Prod apply** | **✅ DONE 2026-07-22T19:49:08Z** (owner GO «GO 21») |

**Keep-14 rejected:** needs sustained `ratio14d < 0.5` and alert cleared — fresh data is the opposite (~0.99, firing). **Bump-30** deferred unless owner explicitly wants aggressive cost cut.

---

## Fresh metrics (read-only)

### Knob / container

> **Pre-bump read-only snapshot (14:56Z / 14:59Z), before the 19:49Z apply.** Post-apply values are `=21` / StartedAt `2026-07-22T19:49:08Z` — see header banner and «Apply path».

| Signal | Value (pre-bump) | Source |
|---|---|---|
| prod `~/TG_parser/.env` | `RESUMMARIZE_MAX_AGE_DAYS=14` → **now `21`** | `ssh prod grep` |
| container OS-env `tg_parser` | `RESUMMARIZE_MAX_AGE_DAYS=14` → **now `21`** | `docker exec tg_parser env` |
| Also present | `RESUMMARIZE_ENABLED=true`, `RESUMMARIZE_MAX_PER_TICK=10`, `RESUMMARIZE_TRIGGER_N=5` | same |
| `tg_parser` StartedAt | `2026-07-19T20:35:59Z` → **now `2026-07-22T19:49:08Z`** | `docker inspect` |

### Gate + alert

| Signal | Value |
|---|---|
| `tg:resummarize_age_trigger:ratio14d` | **0.9885319100039771** |
| `ALERTS{alertname="ResummarizeAgeTriggerGateF5CPhase2"}` | **firing**, `severity=info` → `1` |

### Age / counter triggers / 24h

`sum(increase(tg_resummarize_total[24h])) by (channel_id, trigger)` — non-zero age:

| channel_id | trigger | ≈ count / 24h |
|---|---|---|
| `labdiagnostica_logical` | age | **24.0** |
| `mediamedics` | age | **11.0** |
| `profendocrinologist` | age | **1.0** |
| (others) | age / counter | ≈ 0 |

Counter branch ≈ 0 across channels — age dominates the mix (matches ratio≈0.99).

### Tokens / 24h

`sum(increase(tg_resummarize_tokens_total[24h])) by (token_type)`:

| token_type | ≈ total |
|---|---|
| prompt | **52.9k** |
| completion | **8.5k** |

Per-channel (non-zero): `mediamedics` ≈48.3k prompt + 7.8k completion; `profendocrinologist` ≈4.6k prompt + 0.6k completion. Cost acceptable on `gpt-4o-mini` scale — gate is an **info** signal to relax cutoff, not an incident.

---

## Decision matrix → recommendation

| Option | Evidence fit | Choice |
|---|---|---|
| Keep 14 | Requires sustained `ratio14d < 0.5` + alert not firing | **No** — ratio≈0.99, alert firing |
| **Bump → 21** | `ratio ≥ 0.5` + firing + cost OK; conservative +50% cutoff | **Yes (default)** |
| Bump → 30 | Aggressive cost cut / post-21 still red | Only if owner prefers |

**Rationale (ADR-0006 #6 / runbook §T7):**
1. Full +48h watch complete → δ unblocked.
2. Gate decisively red (`≈0.99`, not marginal 0.503 of 2026-07-20).
3. Multiple channels age-dominated (`labdiagnostica_logical`, `mediamedics`, …).
4. Cost down vs 2026-07-21 peak (~303k prompt) but still ops-relevant on `mediamedics`.
5. **21** is the conservative DRAFT/runbook default; rollback trivial.

---

## Apply path (✅ executed 2026-07-22T19:49:08Z)

On prod host `~/TG_parser` (owner GO «GO 21»):

```bash
cp .env .env.bak.delta-t7-20260722T194808Z          # backup (done)
sed -i 's/^RESUMMARIZE_MAX_AGE_DAYS=14$/RESUMMARIZE_MAX_AGE_DAYS=21/' .env
docker compose up -d tg_parser    # RE-CREATE — NOT restart (BUG-078)
docker exec tg_parser env | grep RESUMMARIZE_MAX_AGE_DAYS   # → 21 ✅
docker inspect tg_parser --format '{{.State.StartedAt}}'    # → 2026-07-22T19:49:08Z ✅ (changed)
docker inspect tg_parser --format '{{.State.Health.Status}}'  # → healthy ✅
```

**Post-apply verify:** `.env`=21, container OS-env=21, StartedAt changed, health `healthy`, `ratio14d≈0.987`.

**Expectation after bump:** alert / `ratio14d` **stay red** until the trailing-14d window incorporates post-bump traffic — this is expected lag, not instant green. Passive re-watch: re-check `ratio14d` trend over the next ~1–2 weeks; expect age-share to decline as the `>21d` cutoff triggers fewer low-volume topics.

### Rollback

**Must edit `~/TG_parser/.env` first** — compose bakes OS-env from host `.env` at re-create; `up -d` alone (with `.env` still `=21`) does **not** roll back (BUG-078 class).

```bash
cd ~/TG_parser
# restore backup … (recommended)
cp .env.bak.delta-t7-20260722T194808Z .env      # → RESUMMARIZE_MAX_AGE_DAYS=14
# … OR edit in place to target value
sed -i 's/^RESUMMARIZE_MAX_AGE_DAYS=21$/RESUMMARIZE_MAX_AGE_DAYS=14/' .env   # or =0 to disable age branch
grep '^RESUMMARIZE_MAX_AGE_DAYS=' .env           # confirm target BEFORE up -d
docker compose up -d tg_parser                   # RE-CREATE — NOT restart (BUG-078)
docker exec tg_parser env | grep RESUMMARIZE_MAX_AGE_DAYS   # must match .env
```

---

## Session status vs acceptance

| Criterion | Status |
|---|---|
| Fresh snapshot with UTC timestamp | ✅ this note |
| Verdict keep-14 **or** bump applied | ✅ **bump-21 APPLIED** (owner GO 2026-07-22T19:49:08Z); OS-env verified =21 |
| Runbook §T7 / ROADMAP updated | ✅ companion edits in same session |
| Rollback path documented | ✅ `=14` or `=0` + `up -d` |
| Zero TTL / Wave E / F11 HTTP | ✅ |
| Commit/PR | on explicit user request (requested this session) |

---

## ✅ Re-watch checkpoint CLOSED — 2026-08-05 (`=21` OK; gate noisy due to BUG-083)

> **Verdict (owner GO this session):** keep **`RESUMMARIZE_MAX_AGE_DAYS=21`**. Do **not** bump `21 → 30`. Follow-up **closed**. Gate `ResummarizeAgeTriggerGateF5CPhase2` may stay `firing` — treat as **info noise**, not a freshness-cutoff failure.

**Когда снято:** 2026-08-05 (~18:00 UTC+2 / ~16:00 UTC). Bump `14 → 21` был 2026-07-22T19:49Z → trailing-14d окно **полностью post-bump** (lag-объяснение больше не держится).

**Снято (read-only, prod):**

| Signal | Value |
|---|---|
| `RESUMMARIZE_MAX_AGE_DAYS` (OS-env) | `21` |
| `tg:resummarize_age_trigger:ratio14d` | **≈0.989** |
| `ALERTS{alertname="ResummarizeAgeTriggerGateF5CPhase2"}` | **firing** (`severity=info`) |
| 14d mix raw | `age`≈365 / `counter`≈4 |

**Почему raw-ratio не означает «21 слишком агрессивен».** Почти весь age-счётчик — **не успешные re-summarize**, а zero-cost quarantine skips из BUG-083:

| Slice (14d) | Value |
|---|---|
| `labdiagnostica_logical` `trigger=age` | ≈338 |
| of which `outcome=refusal_cooldown` | **≈330 (98%)** |
| of which `outcome=ok` | ≈8 |
| Live tick pattern | `f5c_resummarize source=labdiagnostica_logical candidates=1 resummarized=0 skipped=1 tokens=0` (~1/hour) |

Это тот же poison-pill, что закрывал BUG-083: `topic:tg:labdiagnostica_logical:comment:8992` («Диагностика аллергии на ботулотоксин») — Anthropic hard `stop_reason='refusal'` на медицинской терминологии; cooldown экономит Sonnet, но recording rule `tg:resummarize_age_trigger:ratio14d` считает **все** `trigger="age"`, включая `refusal_cooldown`, поэтому gate остаётся красным.

**Продуктивный mix (исключая `refusal_cooldown`, 14d):** age `ok`≈**35**, counter `ok`≈**4** → ratio≈0.90 при абсолютном объёме ~2.5 успешных age/день на всю систему. Age-ветка делает свою работу на quiet channels; bump cutoff эту картину не чинит и poison-pill не убирает.

**Решения на checkpoint:**
- [x] **Keep `=21`** (steady-state). Bump `→30` **rejected** for this window.
- [x] Красный T7 gate **adjudicated** as BUG-083 metric noise (info), not an incident and not a cutoff regression.
- [x] **Событие B (TTL retention) — deferred** (не включаем сейчас). CLI: `Retention disabled (RESUMMARIZE_VERSION_RETENTION_DAYS=0)… DB untouched` (Event A live, Event B off). Rows старше 180d ещё не ожидаются (~таблица с 2026-04-26 ⇒ порог ≈ конец октября 2026); baseline 2026-07-23 would_purge=0. Включение — отдельный owner GO, когда появятся реальные кандидаты или как safety bound без срочности. См. runbook § «Событие B».

**Optional follow-ups (не блокер закрытия T7; отдельный hygiene slice):**
- ✅ **Исполнено 2026-08-06.** Исключить `outcome="refusal_cooldown"` из recording rule / gate (чтобы ratio отражал реальные re-summarize). Исключён из **обеих** частей дроби; замер на одних и тех же прод-данных 2026-08-06: `ratio14d` **0.9887 → 0.8824** (оценка ≈0.90 выше — арифметика по снапшоту 2026-08-05; за сутки окно съехало). Заодно принято owner-решение по порогу: gate-алерт `ResummarizeAgeTriggerGateF5CPhase2` **снят** (вариант V1 — вердикт закрыт, вечно-красный info-алерт вреден), взамен добавлен компенсирующий сигнал `tg:resummarize_refusal_cooldown:count24h` + alert `ResummarizeRefusalCooldownPoisonPill`.
- ⛔ **Не понадобилось.** Или не выбирать cooldown-темы в `list_resummarize_candidates` (не жечь слот тика на known poison-pill). Критерий входа не выполнен: единственная отравленная тема вылечена, `candidates` по каналу больше не содержит её. Само по себе это стоило 0 токенов (гард до LLM) — оправданием был бы только рост популяции poison-pill'ов.
- ✅ **Проверено живьём 2026-08-05, постоянным не делаем.** Опц. `RESUMMARIZE_REFUSAL_FALLBACK_STAGE` для попытки вылечить тему другим провайдером. Разовый CLI-эксперимент (`-e`, без записи в prod `.env` и без re-create) вылечил `topic:tg:labdiagnostica_logical:comment:8992` через `openai/gpt-4.1`: `status: ok`, `new_version: 3`, лог `f5c_resummarize_fallback_ok`. Постоянный fallback (D-4) **отклонён** owner'ом — он требовал бы второго chat-LLM аккаунта, что противоречит модели single-operator/self-host (A1). Knob остаётся опцией, выключенной по умолчанию. Запись: [`SESSION_F5C_MINIMAL_FALLBACK_2026-08-05.md`](SESSION_F5C_MINIMAL_FALLBACK_2026-08-05.md).

**Anchor updates:** runbook §T7 баннер снят → CLOSED; ROADMAP **Next** обновлён.

---

## Links

- Prior snapshot: [`C2_T7_LIVE_SNAPSHOT_2026-07-20.md`](C2_T7_LIVE_SNAPSHOT_2026-07-20.md)
- Plan: [`PLAN_SESSION_DELTA_T7_GATE_RESPONSE_2026-07-22.md`](PLAN_SESSION_DELTA_T7_GATE_RESPONSE_2026-07-22.md)
- Runbook §T7: [`F5C_DEPLOY_AND_WATCH.md`](../runbooks/F5C_DEPLOY_AND_WATCH.md)
- DRAFT Track δ: [`DRAFT_NEXT_CONTRACT_POST_GAMMA_CLOSEOUT_2026-07-20.md`](DRAFT_NEXT_CONTRACT_POST_GAMMA_CLOSEOUT_2026-07-20.md) §2
- ROADMAP: [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md)
