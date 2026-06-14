# ADR 0017 – Dependency management policy (uv.lock as source of truth + upper-bounds + deps-lock-guard)

## Статус

**Accepted (2026-06-14).** Implemented as **Phase 2 of issue #295** (dependency
reproducibility). Phase 1 (commit `9c547d5`, prod healthy) capped
`fastapi>=0.136,<0.137` in both `pyproject.toml` and `requirements.txt` and added
the runtime regression test `tests/test_metrics_instrumentation.py`. Phase 2 (this
ADR) adopts `uv` + `uv.lock` as the resolution source of truth, adds upper-bounds
to `pyproject.toml`, regenerates `requirements.txt` as a generated pinned+hashed
export, rebuilds the `Dockerfile` to install from the lock, and adds the
`deps-lock-guard` CI job. Build backend stays **setuptools** (no switch to a uv
build backend). Local change set — **not yet committed/deployed** (awaiting owner
go-ahead; the lift of `fastapi<0.137` remains a separate gated follow-up).

## Контекст

On **2026-06-14** a clean production rebuild resolved `fastapi 0.137.0` +
`prometheus-fastapi-instrumentator 8.0.0` + transitive `starlette 1.3.1`. The
`fastapi 0.137` × instrumentator 8.0.0 combination raised
`AttributeError: '_IncludedRouter'` inside the instrumentator's `include_router`
path → every request 500 when `METRICS_ENABLED=true` (the prod default).

Root cause was a **resolution-reproducibility gap**, not a single bad pin:

- No exact pins existed anywhere except `ruff==0.15.11`. Every other dependency
  was floor-only (`>=`), so a clean build always pulled the newest compatible
  release.
- `requirements.txt` duplicated the `pyproject.toml` ranges **by hand**, with
  nothing enforcing the two stayed in sync — it gave a false sense of pinning
  (ranges, not versions) and was build-irrelevant anyway (the Docker image was
  built from `pyproject.toml` via `pip install .`).
- Transitive deps (`starlette`, `openai`) were entirely uncontrolled: even with
  `fastapi<0.137`, a clean build still resolved `starlette 1.x` + instrumentator
  `8.0.0` — an "unverified drift" of the exact class that caused the incident.

**Phase 1** closed the *runtime* half (the cap + a regression test that would 500
on the bad combination). **Phase 2** closes the *resolution-time* half: real
reproducibility via a lockfile (transitive pins + hashes), upper-bounds as a
guardrail against future silent major bumps, and a CI guard that fails on any
drift from the lock. The audit of all 30 declared deps and the full design live
in `docs/notes/DEP_PIN_AUDIT_2026-06-14.md` and
`docs/notes/PLAN_DEP_REPRODUCIBILITY_PHASE2_2026-06-14.md`.

## Решение

### 1. `uv` + `uv.lock` = source of truth for dependency resolution

`uv` (0.10.0) is the official dev + Docker toolchain. `uv.lock` is the single
reproducibility artifact: it pins **every** dependency, including transitives
(`starlette`, `openai`, …), with hashes, resolved once on Python 3.12 and
installed deterministically across local `.venv`, CI, Docker, and prod. The lock
is regenerated with `uv lock` and must be committed in sync with `pyproject.toml`.
`uv.lock` was removed from `.dockerignore` (so the Docker build context can see
it) and from `.cursorignore` (so future agent sessions can inspect resolved
pins).

### 2. Build backend stays setuptools

uv operates on the existing PEP 621 `[project]` table; it does **not** require
switching the build backend. `[build-system]` keeps
`setuptools.build_meta`. Migrating to the uv build backend is explicitly **out of
scope** — only an optional `[tool.uv]` dev-group wiring may ever be added (this
sprint did not need it: the `dev` extra stays in
`[project.optional-dependencies]`, CI installs it with `uv sync --frozen
--extra dev`, and the documented `pip install -e ".[dev]"` path keeps working).

### 3. `requirements.txt` = generated pinned+hashed export

`requirements.txt` is no longer hand-maintained. It is a **derived artifact**,
regenerated from the lock:

```bash
uv export --frozen --no-dev --no-emit-project --format requirements-txt -o requirements.txt
```

It keeps the same path (so the documented pure-pip onboarding/CI fallback keeps
working) but now carries **real `==` pins + hashes** instead of ranges. A header
banner marks it auto-generated and gives the regen command. It must never be
hand-edited and must never be deleted/renamed.

> **Banner ↔ guard invariant.** `uv export` bakes the literal `-o <path>` argument
> into its own auto-generated header line, so the committed file and the CI
> regeneration must both export straight to `requirements.txt` (not a `.tmp`
> name), then prepend the banner via a differently-named intermediate. Otherwise
> the `deps-lock-guard` diff fails on a spurious header-path mismatch.

### 4. Upper-bounds policy in `pyproject.toml`

Explicit `<next-major` (or tighter) caps are added to declared deps as a
**guardrail**, complementary to the exact pins in the lock: the lock delivers
reproducibility *today*; the caps stop a future `uv lock --upgrade` from silently
crossing a major boundary. Tiers applied this sprint:

- **Tier 1 (high-risk):** `uvicorn[standard]>=0.32,<0.50`,
  `openai-agents>=0.13,<0.18`.
- **Tier 2 (medium):** `sqlalchemy[asyncio]<2.1`, `alembic<2.0`, `asyncpg<0.32`,
  `psycopg2-binary<3.0`, `telethon<2.0`, `aiogram<4.0`, `mcp<2.0`, `httpx<0.29`.
- **Tier 3 (hygiene, coarse `<next-major`):** `pydantic-settings<3.0`,
  `jsonschema<5`, `typer<1.0`, `pgvector<0.5`, `structlog<27`, `slowapi<0.2`,
  `PyYAML<7`, `python-dotenv<2`, `apscheduler<4.0`, `pymorphy3<3`, `simplemma<2`,
  and the dev group (`pytest<10`, `pytest-asyncio<2`, `pytest-cov<8`,
  `testcontainers[postgres]<5`).

**Deliberately not capped:** `starlette` and `prometheus-fastapi-instrumentator`
(both transitive-or-confirmed-good and pinned exactly by the lock — `starlette
1.3.1`, instrumentator `8.0.0`); `openai` (transitive, lock-pinned);
`pymorphy3-dicts-ru` (datapack); `ruff` (already exact-pinned). `fastapi` keeps
its Phase-1 `>=0.136,<0.137` cap (see §6).

### 5. `deps-lock-guard` CI job (resolution-time enforcement)

A fast, DB-less CI job complements the Phase-1 runtime test by failing the PR on
any drift from the lock. It asserts three things:

- `uv lock --check` — the lock is in sync with `pyproject.toml` (a range bump
  without a re-lock fails here).
- `uv export … -o requirements.txt` + banner + `git diff --exit-code` — the
  committed generated `requirements.txt` matches the lock.
- `uv sync --frozen --no-dev --no-install-project` — the lock resolves cleanly
  with no resolver freedom.

The four existing install steps (`test`, `compose-integration`,
`alembic-guardrail`, `alembic-runtime-smoke`) were migrated from
`pip install -r requirements.txt` + `pip install -e .` to
`astral-sh/setup-uv@v4` + `uv sync --frozen --extra dev`, with host-side
invocations prefixed `uv run`. The `docker` job is structurally unchanged (it
builds the image, which now installs from the lock).

### 6. `openai-agents` floor + `fastapi<0.137` lift procedure

- `openai-agents` floor was raised `0.6 → >=0.13,<0.18` (the old floor was four
  minors stale vs. installed/prod). The lock currently resolves the top of that
  range, **0.17.5** (up from prod's 0.13.6); the full suite validates the bump.
- `fastapi<0.137` is **retained**. It may only be lifted once a
  `prometheus-fastapi-instrumentator` release **>8.0.0** explicitly supports the
  fastapi 0.137 `_IncludedRouter` change. Lift procedure (gated):
  `uv lock --upgrade-package fastapi --upgrade-package prometheus-fastapi-instrumentator`
  → `uv run pytest tests/test_metrics_instrumentation.py` →
  clean Docker build + `/metrics` smoke → only then relax the `pyproject.toml`
  cap.

### 7. Renovate / Dependabot deferred

Automated bump PRs are explicitly **out of scope** for now. The lock + caps +
`deps-lock-guard` make future bumps safe and reviewable; automation can be added
later (Renovate understands `uv.lock` natively) without changing this policy.

## Contracts check

No JSON Schema in `docs/contracts/` is affected — there are no domain-data
changes. The change set is limited to dependency declarations, the lockfile, the
generated export, the Dockerfile, CI workflow, the two ignore files, and four
doc install blocks. No contract break.

## Тестовая стратегия

- **Baseline (pre-edit):** `TEST_POSTGRES=1 .venv/bin/python -m pytest -q` →
  `3381 passed, 20 skipped, 2 deselected` (green start recorded).
- **Post-edit (clean lock-synced venv):** `uv sync --frozen --extra dev` then
  `TEST_POSTGRES=1 uv run pytest -q` → identical `3381 passed, 20 skipped,
  2 deselected` (zero regressions).
- **Phase-1 regression:** `tests/test_metrics_instrumentation.py` → green
  (metrics `include_router` path on the locked `fastapi 0.136.3` /
  instrumentator `8.0.0` / starlette `1.3.1` set).
- **`deps-lock-guard` (simulated locally):** `uv lock --check` clean;
  `requirements.txt` regeneration is byte-identical (round-trip OK); clean
  `--frozen` resolve OK.
- **Clean Docker build:** `docker build --no-cache -t tg_parser:phase2 .` →
  success; `docker run --rm tg_parser:phase2 --help` works. Pin verification (the
  uv-native image has no `pip`, so via `importlib.metadata`): `fastapi 0.136.3`,
  `starlette 1.3.1`, `prometheus-fastapi-instrumentator 8.0.0`, `uvicorn 0.49.0`
  — the confirmed-good set, **not** 0.137.
- **ruff:** `uv run ruff check .` clean; no Python source files were touched by
  this sprint (pre-existing `ruff format` drift in unrelated files is out of
  scope).

## Последствия

### Положительные

- Real reproducibility **today**: a clean build (local, CI, Docker, prod)
  installs one identical, hash-verified set from `uv.lock` — closing the
  transitive-`starlette`/`openai` drift the Phase-1 cap could not.
- Upper-bounds prevent a future `uv lock --upgrade` from silently crossing a
  major boundary; the lock diff is the audit trail for every intended bump.
- `deps-lock-guard` enforces, at resolution time, that `pyproject.toml`,
  `uv.lock`, and `requirements.txt` never drift apart — the complement to the
  Phase-1 runtime test, closing both halves of the incident class.
- `requirements.txt` keeps the pure-pip fallback working, now with real
  pins+hashes instead of misleading ranges.

### Отрицательные / accepted debt

- Contributors and the VPS now need `uv` for the first-class path (the generated
  hashed `requirements.txt` remains a pip fallback).
- `requirements.txt` must always be **regenerated** from the lock, never
  hand-edited; any manual edit is caught by `deps-lock-guard` but is friction.
- The lock must be regenerated and reviewed on every dependency change (this is
  the intended workflow, but it is a step that did not exist before).
- `openai-agents` jumped prod 0.13.6 → locked 0.17.5 (within the approved range);
  validated by the suite, but a larger delta than a patch bump. It pulls a new
  transitive `griffelib` (ships the `griffe` import package).
- `fastapi<0.137` remains a known, documented cap (lift-watch in §6) until a
  fixed instrumentator ships.
- Renovate/Dependabot deferred → dependency freshness stays a manual, periodic
  task for now.

## Ссылки

- Issue **#295** (dependency reproducibility); `docs/notes/BUG_LOG.md` (closing
  lines pending owner go-ahead).
- `docs/notes/DEP_PIN_AUDIT_2026-06-14.md` — audit of all 30 deps.
- `docs/notes/PLAN_DEP_REPRODUCIBILITY_PHASE2_2026-06-14.md` — full Phase 2
  design (primary source).
- `docs/notes/START_PROMPT_SPRINT_DEP_REPRODUCIBILITY_PHASE2_2026-06-14.md` —
  operational summary with fixed owner decisions (§5 = this ADR).
- Phase-1 regression: `tests/test_metrics_instrumentation.py`.
- Code/artifact anchors: `pyproject.toml` (`[project.dependencies]`),
  `uv.lock`, `requirements.txt` (banner header), `Dockerfile` (uv-native
  builder), `.github/workflows/ci.yml` (`deps-lock-guard` + migrated steps),
  `.dockerignore`, `.cursorignore`.

## История

| Дата | Изменение |
|------|-----------|
| 2026-06-14 | Created and Accepted as Phase 2 of #295. Adopts `uv` + `uv.lock` as the resolution source of truth (transitive pins + hashes); setuptools build backend retained. `requirements.txt` becomes a generated pinned+hashed `uv export` artifact (pip fallback, never hand-edited). Upper-bounds policy: explicit `<next-major` caps in `pyproject.toml` (Tier 1+2+3) as a guardrail complementary to the lock; `starlette`/`prometheus-fastapi-instrumentator`/`openai` intentionally not capped (lock-pinned), `fastapi<0.137` retained with a gated lift procedure. `deps-lock-guard` CI job enforces lock↔pyproject sync, `requirements.txt` drift, and clean resolve; four install steps migrated to `uv sync --frozen`. `openai-agents` floor raised to `>=0.13,<0.18` (locked 0.17.5). Renovate/Dependabot deferred. Verified: baseline + post-edit suites `3381 passed`, Phase-1 metrics test green, clean Docker build pins the confirmed-good set (not 0.137). Local change set — not yet committed/deployed. |
