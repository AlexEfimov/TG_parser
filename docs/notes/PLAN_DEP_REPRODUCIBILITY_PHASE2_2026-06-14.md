# Dependency Reproducibility — Phase 2 Implementation Plan

**Issue:** #295
**Date:** 2026-06-14
**Status:** PLAN ONLY — analysis/design. No dependency files, Dockerfile, CI, or code were modified by this session. The only file written is this plan.
**Builds on:** [`DEP_PIN_AUDIT_2026-06-14.md`](DEP_PIN_AUDIT_2026-06-14.md) (raw audit of all 30 deps — not redone here, referenced).
**Phase 1 (shipped, commit `9c547d5`, prod healthy):** regression test `tests/test_metrics_instrumentation.py` + `fastapi>=0.136,<0.137` capped in both `pyproject.toml` and `requirements.txt`. **Do NOT cap `starlette` or `prometheus-fastapi-instrumentator`** — starlette 1.x + instrumentator 8.0.0 are confirmed good; Phase 2 pins them *exactly via the lockfile*, not via pyproject ranges.

> **AGENTS.md gate:** every edit this plan describes to `pyproject.toml`, `requirements.txt`, `Dockerfile`, and `.github/workflows/**` is a forbidden-without-approval action. The implementation session must get explicit owner sign-off before touching those files. Approval points are marked **[GATE]** throughout.

---

## 0. TL;DR for the implementer

1. **Tooling:** adopt **`uv` + `uv.lock`** (not pip-tools). `uv 0.10.0` is already installed and a (stale) `uv.lock` is already tracked — lowest-friction path to real reproducibility. Keep the **setuptools** build backend (uv does *not* require switching it).
2. **`requirements.txt`:** stop hand-maintaining it. Regenerate it as a **pinned + hashed export** of `uv.lock` (`uv export`). It stays at the same path so README/CI/docs keep working, but becomes a derived artifact, not a source of truth.
3. **pyproject upper bounds NOW:** add caps to the high/medium-risk floor-only declared deps (uvicorn, openai-agents, sqlalchemy, alembic, asyncpg, psycopg2-binary, telethon, aiogram, mcp, httpx + hygiene tier). **Do not** cap starlette / instrumentator (lock pins them).
4. **Dockerfile:** builder installs from the lockfile (`uv sync --frozen --no-dev`) instead of `pip install .`; transitive `starlette`/`openai` become exactly pinned for free.
5. **CI guard:** new `deps-lock-guard` job — `uv lock --check` + `uv export` diff + clean `--frozen` resolve. Fails on any drift from the lock (the resolution-time complement to Phase 1's runtime test).
6. **Maintenance:** `uv add` / `uv lock --upgrade-package` + review the `uv.lock` diff; optional Renovate.
7. **Rollout:** gated edits → baseline tests → clean Docker build → VPS deploy with pre-swap `pip freeze` check → revert-and-redeploy rollback. Keep `fastapi<0.137` until a post-8.0.0 instrumentator supports `_IncludedRouter`.

---

## 1. Current-state facts established this session

| Fact | Evidence | Consequence for the plan |
|---|---|---|
| Docker builds from `pyproject.toml` | `Dockerfile:15-19` — `COPY pyproject.toml … ` + `RUN pip install --user --no-cache-dir .` | `requirements.txt` is build-irrelevant today; the lockfile install must replace this layer. |
| `requirements.txt` == `pyproject.toml` ranges, hand-synced | both files read; spec-identical incl. `fastapi>=0.136,<0.137` | No live drift now, but pure duplication with no enforcement. |
| **A stale `uv.lock` is already git-tracked** | `git log -1 -- uv.lock` → `4952a92` **2026-04-10** ("docs: add future features roadmap"); HEAD is `9c547d5` 2026-06-14 | uv was used before and abandoned. The lock is ~2 months stale (predates the fastapi cap and many bumps). **Must be regenerated from scratch, never trusted as-is.** |
| No `[tool.uv]` section in `pyproject.toml` | `rg "tool.uv" pyproject.toml` → none | uv runs in PEP 621 "project" mode against the existing tables; a small `[tool.uv]` (dev group wiring) may be added. |
| `uv.lock` is in **`.dockerignore`** (line ~ "uv.lock") and **`.cursorignore`** (line 12) | both files read | Docker can't see the lock today → **must remove from `.dockerignore`**. `.cursorignore` hides it from agents (read-only nuisance; optional to lift). |
| `uv 0.10.0` installed; `pip-tools` absent | `uv --version` ok; `which pip-compile` → not found | uv is zero-install; pip-tools would need installing. |
| `.python-version` = `3.12`; project `requires-python = ">=3.12"`; system `python3` = 3.10.11; `.venv` present | files + shell | uv must resolve/build on **3.12**; `.python-version` already steers it. Beware the system 3.10. |
| CI installs deps in **4 jobs** via `pip install -r requirements.txt` + `pip install -e .` | `.github/workflows/ci.yml:46-50, 131-135, 266-270, 344-348` | All four must be migrated (or kept working via the generated requirements export). |
| Build backend = setuptools | `pyproject.toml:1-3` | uv supports this; **no backend switch needed** (see §3 note). |
| Docs referencing `pip install -r requirements.txt` | `README.md:77`, `docs/guides/SELF_HOST.md:105`, `docs/USER_GUIDE.md:68`, `QUICKSTART_v1.2.md:42` | Keep the path working (generated export) and/or add a uv path. |

---

## 2. Decision 1 — Tooling: `uv` (uv.lock) vs `pip-tools`

### Recommendation: **`uv` with `uv.lock`.**

**Why uv wins for THIS repo (single-owner, manual VPS deploy, setuptools backend, Docker multi-stage):**

- **Already present & abandoned mid-adoption.** `uv 0.10.0` is on the dev machine and a tracked `uv.lock` already exists (just stale). Reviving it is *less* work than introducing pip-tools from zero, and matches prior intent (CHANGELOG references `uv run pytest`).
- **One tool, no extra install.** uv does lock + resolve + venv + sync + export. pip-tools needs a separate `pip-tools` install and still needs `pip`/`venv` around it, and does not manage the environment.
- **Universal, hashed lock incl. transitives.** `uv.lock` pins every transitive (so `starlette`, `openai` are pinned automatically) with hashes, cross-platform — resolves once, installs deterministically in CI, Docker (linux), and dev (macOS).
- **No build-backend change required.** uv operates on the existing PEP 621 `[project]` table with the **setuptools** backend untouched. (See §3 note — this is a common misconception worth stating explicitly to the owner.)
- **Fast + good CI caching.** `astral-sh/setup-uv` provides first-class lock-keyed caching; clean `--frozen` installs are seconds.
- **Clean Docker story.** `uv sync --frozen --no-dev` into a venv, copied into the runtime stage — preserves multi-stage layout and layer caching.

**Migration cost:** moderate, one-time. Regenerate the stale lock, remove `uv.lock` from `.dockerignore`, rewrite the Docker install layer, swap 4 CI install steps, add one guard job, update 4 docs. No code changes. No backend change.

### Runner-up / fallback: **`pip-tools` (`pip-compile --generate-hashes`).**

Choose this only if the owner explicitly does **not** want uv as the dev/Docker toolchain. Shape:
- `pip-compile --generate-hashes --output-file=requirements.lock pyproject.toml` (prod) + a `requirements-dev.lock` from the `dev` extra.
- Dockerfile: `pip install --require-hashes -r requirements.lock` (keeps pip, no uv in image).
- CI: `pip-compile` in a guard job + `git diff --exit-code` on the lock.

**Why it's the runner-up, not the pick:** needs a new tool installed; doesn't manage the venv; produces two files to keep coherent; ignores the uv tooling/lock the repo already carries; slower. It *is* the more conservative "stay in pip-land" option, hence the fallback.

**[GATE — owner decision]** Adopt `uv` as the official dev + Docker toolchain? (Contributors would need `uv`; the generated `requirements.txt` export keeps a pure-pip fallback working — see §3.)

---

## 3. Decision 2 — `requirements.txt` source-of-truth resolution

### Recommendation: **keep the file path, change its nature — make it a generated, pinned, hashed export of `uv.lock`.**

- **Source of truth becomes:** `pyproject.toml` (human intent = ranges) → `uv.lock` (exact pins incl. transitives, the real reproducibility artifact).
- **`requirements.txt` becomes a derived artifact**, regenerated by:

```bash
uv export --frozen --no-dev --no-emit-project --format requirements-txt -o requirements.txt
```

This yields fully pinned `==` specs **with hashes** for prod deps. It replaces today's hand-maintained range copy.

**Why regenerate rather than delete:**
- Four CI jobs and four docs (`README.md:77`, `SELF_HOST.md:105`, `USER_GUIDE.md:68`, `QUICKSTART_v1.2.md:42`) reference `pip install -r requirements.txt`. A generated, hashed file keeps the pure-pip path working for contributors who don't adopt uv — without the "false pinning" the audit flagged (it'll now be real pins+hashes, not ranges).
- It also gives a non-uv install path inside Docker if the lock-native approach is ever rolled back.

**What updates, and how:**
- **Header banner** added to the generated file: `# AUTO-GENERATED from uv.lock by 'uv export' — DO NOT EDIT BY HAND. Run: uv export --frozen --no-dev ... -o requirements.txt`.
- **CI** (`ci.yml`): the four `pip install -r requirements.txt` steps either (a) migrate to `uv sync --frozen` (preferred for the test/alembic jobs), or (b) keep `pip install -r requirements.txt` but the file is now the generated hashed export. Pick (a) for the Python test jobs to exercise the same resolution as prod; keep the generated file primarily as a fallback + docs install path. The new guard job (§6) asserts it never drifts from the lock.
- **Docs**: add a one-line uv alternative (`uv sync`) next to the existing `pip install -r requirements.txt` blocks; note the file is generated.

**Alternative considered (delete entirely):** cleaner conceptually, but breaks the documented pip onboarding flow and forces every contributor onto uv immediately. Rejected for a single-owner project that still advertises a pip Quick Start. (Owner may override — see open questions.)

**Optional rename:** `requirements.txt` → `requirements.lock` to signal "generated/pinned". Not recommended (touches 8 references for cosmetic gain); keep the name.

---

## 4. Decision 3 — Upper bounds to add in `pyproject.toml` NOW

These caps constrain what `uv lock` is *allowed* to resolve on the next refresh — the guardrail that complements the lock. Specs taken from the audit §1 table.

**Tier 1 — high-risk, MUST (web/ASGI + SDKs):**

| Dep | Current | → New spec | Rationale |
|---|---|---|---|
| `uvicorn[standard]` | `>=0.32` | `>=0.32,<0.50` | 0.42→0.49 unbounded; 0.x minors carry behavior changes. |
| `openai-agents` | `>=0.6` | `>=0.13,<0.18` | pre-1.0 SDK, floor 0.6 is 4 minors stale vs installed 0.13.6. **[GATE-confirm]** raising the floor 0.6→0.13 (matches installed/prod). If owner prefers, keep floor: `>=0.6,<0.18`. |

**Tier 2 — medium, recommended in the same PR (DB / Telegram / clients):**

| Dep | Current | → New spec |
|---|---|---|
| `sqlalchemy[asyncio]` | `>=2.0` | `>=2.0,<2.1` |
| `alembic` | `>=1.13` | `>=1.13,<2.0` |
| `asyncpg` | `>=0.29` | `>=0.29,<0.32` |
| `psycopg2-binary` | `>=2.9` | `>=2.9,<3.0` |
| `telethon` | `>=1.36` | `>=1.36,<2.0` |
| `aiogram` | `>=3.15` | `>=3.15,<4.0` |
| `mcp` | `>=1.25` | `>=1.25,<2.0` |
| `httpx` | `>=0.27` | `>=0.27,<0.29` |

**Tier 3 — hygiene, coarse `<next-major` (optional, same PR):**
`pydantic-settings>=2.0,<3.0`, `jsonschema>=4.0,<5`, `typer>=0.12,<1.0`, `pgvector>=0.3.0,<0.5`, `structlog>=24.0,<27`, `slowapi>=0.1.9,<0.2`, `PyYAML>=6.0,<7`, `python-dotenv>=1.0,<2`, `apscheduler>=3.10,<4.0`, `pymorphy3>=2.0,<3`, `simplemma>=1.0,<2`. Dev group: `pytest>=8.0,<10`, `pytest-asyncio>=0.23,<2`, `pytest-cov>=4.0,<8`, `testcontainers[postgres]>=4.8,<5` (`ruff==0.15.11` already pinned).

**Explicitly NOT capped (decided):**
- `fastapi` — already `>=0.136,<0.137` (Phase 1). Keep.
- `starlette` — **do not add a pyproject cap.** It is transitive; the lockfile pins it exactly (currently the confirmed-good 1.x). Phase-1 finding overrides the audit's old `<1.0` suggestion.
- `prometheus-fastapi-instrumentator` — **do not cap.** 8.0.0 confirmed good; lock pins it exactly. (Audit's `<8.0` suggestion is superseded.)
- `openai` — transitive; pinned by the lock, no pyproject entry.

> Note: caps in pyproject + exact pins in `uv.lock` are complementary. The lock delivers reproducibility *today*; the caps stop a future `uv lock --upgrade` from silently crossing a major boundary.

---

## 5. Decision 4 — Lockfile generation + Dockerfile rewrite

### 5.1 Regenerate the lock (do NOT trust the stale one)

```bash
# from repo root, on python 3.12 (.python-version already pins 3.12)
uv lock                 # resolves pyproject (with new caps) → fresh uv.lock incl. transitives + hashes
uv lock --check         # sanity: lock is in sync with pyproject
uv export --frozen --no-dev --no-emit-project --format requirements-txt -o requirements.txt
git diff uv.lock requirements.txt   # human review of every pin, esp. fastapi 0.136.x, starlette, instrumentator, openai
```

Optionally add a minimal `[tool.uv]` to `pyproject.toml` to formalize the dev group as the default dev dependencies (so `uv sync` installs dev by default locally, `--no-dev` in Docker/prod). Keep `[project.optional-dependencies].dev` as-is or mirror into `[dependency-groups]`.

### 5.2 Un-ignore the lock for Docker

`.dockerignore` currently lists `uv.lock` → the build context can't see it. **Remove that line** (it's between the "Data and runtime artifacts" and "Tests and documentation" blocks). Leave `.cursorignore`'s `uv.lock` as-is unless the owner wants agents to read it (optional; harmless to keep).

### 5.3 Dockerfile diff sketch (multi-stage, lock-driven, cache-friendly)

Replace the builder install layer. Two viable approaches; **5.3-A (uv-native) recommended.**

**5.3-A — `uv sync --frozen` (recommended):**

```dockerfile
# ---- Builder stage ----
FROM python:3.12-slim AS builder
WORKDIR /app

# uv binary (pinned digest in real impl), no separate pip needed
COPY --from=ghcr.io/astral-sh/uv:0.10.0 /uv /uvx /bin/

RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

ENV UV_LINK_MODE=copy \
    UV_PYTHON=3.12 \
    UV_PROJECT_ENVIRONMENT=/opt/venv

# Layer 1: deps only (cached unless pyproject/lock change) — NO project code yet
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# Layer 2: project source + install the package itself (changes often, deps stay cached)
COPY tg_parser/ ./tg_parser/
COPY prompts/ ./prompts/
RUN uv sync --frozen --no-dev --no-editable

# ---- Production stage ----
FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1
COPY tg_parser/ ./tg_parser/
COPY prompts/ ./prompts/
COPY migrations/ ./migrations/
RUN mkdir -p /app/data
ENTRYPOINT ["tg-parser"]
CMD ["api", "--host", "0.0.0.0", "--port", "8000"]
```

Key points: `--frozen` forbids re-resolution (fails if lock is stale → exactly the guard we want); deps layer is copied **before** source so the expensive resolve/install stays cached across code changes; `--no-dev` excludes the test/lint group; runtime stage carries only the resolved venv (mirrors today's `/root/.local` copy pattern). Transitive `starlette`/`openai` are pinned by `uv.lock` automatically.

**5.3-B — fallback (no uv in image):** keep `pip` but install the hashed export:
```dockerfile
COPY requirements.txt ./
RUN pip install --user --no-cache-dir --require-hashes -r requirements.txt
COPY tg_parser/ ./tg_parser/ ...
RUN pip install --user --no-cache-dir --no-deps .
```
`--require-hashes` enforces the pins; `--no-deps` on the project install avoids re-resolving. Use only if the owner rejects uv-in-image.

**[GATE]** Dockerfile + `.dockerignore` edits.

---

## 6. Decision 5 — CI drift guard

### New job: `deps-lock-guard` (resolution-time guard; complements Phase-1 runtime test)

Add to `.github/workflows/ci.yml`. Runs on every push/PR, fast (no DB service).

```yaml
  deps-lock-guard:
    name: Dependency Lock Guard
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install uv
        uses: astral-sh/setup-uv@v4
        with:
          version: "0.10.0"
          enable-cache: true
      - name: Lock is in sync with pyproject
        run: uv lock --check          # fails if pyproject changed without re-locking
      - name: requirements.txt matches the lock
        run: |
          uv export --frozen --no-dev --no-emit-project \
            --format requirements-txt -o requirements.txt
          git diff --exit-code -- requirements.txt   # fails if the committed export drifted
      - name: Clean resolve from lock (no resolver freedom)
        run: uv sync --frozen --no-dev --no-install-project
```

**What it catches:** a future `fastapi 0.137`-style surprise enters only via a `uv lock`/`uv lock --upgrade`; this job fails the PR if (a) someone bumps a range in pyproject but forgets to re-lock, (b) the generated `requirements.txt` is out of sync, or (c) the lock can't resolve cleanly. Combined with Phase 1's runtime test (which would 500 on the bad fastapi/instrumentator combo) this closes both the resolution-time and run-time halves of the incident class.

### Migrate existing install steps
In the `test`, `compose-integration`, `alembic-guardrail`, `alembic-runtime-smoke` jobs, replace:
```yaml
pip install -r requirements.txt
pip install -e .
```
with the uv equivalent (preferred — same resolution as prod):
```yaml
- uses: astral-sh/setup-uv@v4
  with: { version: "0.10.0", enable-cache: true }
- run: uv sync --frozen   # installs deps + dev group + project (editable) on 3.12
```
then prefix test/tool invocations with `uv run` (e.g. `uv run pytest …`, `uv run ruff check .`) or activate `.venv`. Keep the `docker` build job as-is structurally (it builds the image, which now installs from the lock).

**[GATE]** CI workflow edits.

---

## 7. Decision 6 — Lockfile maintenance workflow (going forward)

**Add a dependency:**
```bash
uv add "somepkg>=X,<Y"      # edits pyproject [project].dependencies + updates uv.lock
# (dev dep)  uv add --dev "pytest-foo>=1,<2"
uv export --frozen --no-dev --no-emit-project --format requirements-txt -o requirements.txt
uv run pytest -q            # verify
git add pyproject.toml uv.lock requirements.txt && # commit (owner-gated)
```

**Upgrade one dep (e.g. lift the instrumentator once a fix ships):**
```bash
uv lock --upgrade-package prometheus-fastapi-instrumentator
uv export ... -o requirements.txt
uv run pytest tests/test_metrics_instrumentation.py -q   # the Phase-1 guard
```

**Upgrade everything within ranges:** `uv lock --upgrade` (review the full diff).

**Review step (always):** read the `uv.lock` diff — confirm no unexpected major crossings (the pyproject caps should prevent them; the diff is the audit trail). Re-run the relevant test mode from `tests/README.md` before committing.

**Optional Renovate** (`renovate.json`, low priority for single-owner):
```json
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "extends": ["config:recommended"],
  "lockFileMaintenance": { "enabled": true, "schedule": ["before 5am on monday"] },
  "packageRules": [
    { "matchManagers": ["pep621"], "rangeStrategy": "widen" }
  ]
}
```
Renovate natively understands `uv.lock`. Dependabot also supports uv but is noisier here; prefer Renovate or skip automation entirely until the owner wants it.

---

## 8. Decision 7 — Rollout, verification, rollback

Ordered implementation-session checklist. **All file edits below are [GATE] — get explicit owner approval first** (AGENTS.md forbids unrequested `pyproject.toml`/`requirements.txt`/Dockerfile/CI edits).

1. **Pre-flight (no edits):** confirm owner decisions on §2 (adopt uv), §3 (requirements disposition), §4 Tier-1 `openai-agents` floor.
2. **Baseline (no edits):** run the standard suite to capture a green baseline before touching deps:
   `TEST_POSTGRES=1 .venv/bin/python -m pytest -q` (expect ~3222 passed per `tests/README.md`).
3. **[GATE] Edit `pyproject.toml`:** add §4 upper bounds (Tier 1+2, optionally 3). Optionally add `[tool.uv]` dev wiring.
4. **Regenerate lock + export (§5.1):** `uv lock` → `uv lock --check` → `uv export … -o requirements.txt`. Review diffs (fastapi pinned 0.136.x, starlette/instrumentator/openai exact pins captured).
5. **[GATE] `.dockerignore`:** remove the `uv.lock` line.
6. **[GATE] Rewrite Dockerfile (§5.3-A).**
7. **[GATE] CI (§6):** add `deps-lock-guard`; migrate the 4 install steps to `uv sync --frozen` + `uv run`.
8. **Verify locally:**
   - `uv sync --frozen && uv run pytest -q` (and `TEST_POSTGRES=1 …` mode).
   - **Clean Docker build:** `docker build --no-cache -t tg_parser:phase2 .` then `docker run --rm tg_parser:phase2 --help`.
   - **Pin verification:** `docker run --rm --entrypoint pip tg_parser:phase2 freeze | grep -Ei 'fastapi|starlette|prometheus-fastapi-instrumentator|uvicorn|openai'` → confirm fastapi 0.136.x, starlette 1.x, instrumentator 8.0.0 (the confirmed-good set), not 0.137.
   - Push branch → confirm `deps-lock-guard` + Phase-1 metrics test pass in CI.
9. **VPS deploy (pre-swap version check):**
   - Capture current prod set first: `docker compose exec tg_parser pip freeze > /tmp/prod_freeze_pre.txt` (ground-truth the audit said was missing).
   - Build the new image on/for the VPS, then **before** switching traffic: run the new image's `pip freeze` and diff against `/tmp/prod_freeze_pre.txt` — confirm only intended deltas.
   - `docker compose up -d --build tg_parser mcp` (+ `tg_bot` if enabled); watch `/health` on 8000/8080 and `/metrics` (the incident surface — `METRICS_ENABLED=true` is the prod default; confirm `include_router` routes return 200, not 500).
10. **Rollback:** if `/health` or `/metrics` regress — `git revert` the Phase-2 commit(s) and `docker compose up -d --build` the prior image (the lock-pinned previous build is reproducible), OR `docker compose up -d` pointing at the last-good image tag. Because the lock is deterministic, the rollback rebuild reproduces the exact previously-running set.

**`fastapi<0.137` lift-watch:** keep the cap. Re-check after the next `prometheus-fastapi-instrumentator` release (>8.0.0) that explicitly supports fastapi 0.137 `_IncludedRouter`. Lift procedure: `uv lock --upgrade-package fastapi --upgrade-package prometheus-fastapi-instrumentator` → run `tests/test_metrics_instrumentation.py` → clean Docker build + `/metrics` smoke → only then relax the pyproject cap. (See audit §6.)

---

## 9. Risks / gotchas

- **Stale tracked `uv.lock` (2026-04-10).** Do **not** reuse it — it predates the fastapi cap and ~2 months of bumps. Regenerate from scratch (`uv lock`) as step 4; the `--check` and clean-resolve guards then keep it honest.
- **`.dockerignore` excludes `uv.lock`.** The lock-driven Dockerfile silently fails (or falls back to re-resolution) if this line isn't removed. Explicit step 5.
- **`.cursorignore` excludes `uv.lock`.** Future agent sessions can't read the lock to reason about pins (this session couldn't). Optional: drop it from `.cursorignore` so dependency-debugging sessions can inspect resolved versions.
- **Hash-pinning + transitive/index deps.** `uv export --generate-hashes`-style output requires every wheel/sdist hash to be resolvable from the configured indexes (PyPI here). All deps are public PyPI — fine. If a private/extra index is ever added, hashes + index URLs must be configured in `[tool.uv]` or `--require-hashes` installs fail.
- **Docker build-cache invalidation.** Copy `pyproject.toml`+`uv.lock` (deps layer) **before** source so a code-only change doesn't re-run the dep install. The sketch in §5.3-A does this; getting the COPY order wrong negates caching.
- **Build-backend confusion.** uv does **not** force a backend switch — setuptools stays. Don't let the implementer "migrate to the uv build backend"; that's out of scope and would change `[build-system]`. Only `[tool.uv]` (optional, dev-group wiring) may be added.
- **Dev-machine uv adoption.** uv is installed locally, but other contributors / the VPS need it. Mitigation: the generated hashed `requirements.txt` keeps a pure-pip install path (`pip install --require-hashes -r requirements.txt`) for anyone without uv. Update CONTRIBUTING/README with both paths.
- **Python version skew.** System `python3` is 3.10.11; the project needs 3.12. `.python-version`=3.12 steers uv, but ensure `uv lock`/`uv sync` actually run on 3.12 (`UV_PYTHON=3.12` in Docker; locally rely on `.python-version` or `.venv`). A lock resolved on 3.10 would mis-resolve.
- **Local `.venv` lagging prod.** The audit noted `.venv` runs older versions than a clean build. After Phase 2, `uv sync --frozen` makes `.venv`, CI, Docker, and prod install the **same** locked set — closing that drift. Re-sync the dev `.venv` (`uv sync --frozen`) as part of rollout so local matches the lock.
- **CI cost.** `deps-lock-guard` is cheap (no DB, cached uv). Migrating other jobs to `uv sync` should be net-neutral or faster than `pip install` with the uv cache.

---

## 10. Open questions for the owner (need a decision before implementation)

1. **[Tooling]** Adopt **`uv`** as the official dev + Docker toolchain (vs the pip-tools fallback in §2)? Contributors would need `uv` (the generated `requirements.txt` keeps a pip fallback).
2. **[requirements.txt]** Keep the path as a **generated hashed export** (§3, recommended), or delete it entirely and move all onboarding to uv?
3. **[openai-agents floor]** OK to raise floor `0.6→0.13` (`>=0.13,<0.18`, matches installed/prod), or keep `>=0.6,<0.18`?
4. **[.cursorignore]** Drop `uv.lock` from `.cursorignore` so future agent sessions can inspect resolved pins? (Optional.)
5. **[Renovate]** Want the optional Renovate config now, or defer automation entirely?

---

## 11. Provenance / scope

- Read-only inspection of `Dockerfile`, `pyproject.toml`, `requirements.txt`, `.github/workflows/ci.yml`, `docker-compose.yml`, `.dockerignore`, `.cursorignore`, `README.md`, `CONTRIBUTING.md`, `tests/README.md`, `tests/test_metrics_instrumentation.py`, and `git`/`uv` metadata. PyPI was **not** queried this session (version facts taken from the prior audit, which fetched PyPI on 2026-06-14).
- No `pyproject.toml` / `requirements.txt` / `Dockerfile` / CI / code changes; no commits, pushes, or deploys. Only this plan file was written. This document stays untracked under `docs/notes/` until the owner commits it.
