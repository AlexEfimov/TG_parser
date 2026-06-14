# Dependency Pinning Audit — 2026-06-14

**Issue:** #295
**Mode:** READ-ONLY analysis. No dependency files, Dockerfile, or code were modified. This report only *informs* a later, owner-approved pinning change (per AGENTS.md, dependency-file edits require explicit owner approval).
**Author context:** automated audit run from local `.venv` + PyPI JSON API.

---

## 0. TL;DR

- **27 dependencies are floor-only (`>=`)**, 0 unbounded, 1 pinned-exact (`ruff==0.15.11`), 2 already range-bounded (`pydantic`, `fastapi`).
- The **Docker image is built from `pyproject.toml`** (`RUN pip install --user --no-cache-dir .`), so `requirements.txt` is **not used by the build**. Any cap in `requirements.txt` is cosmetic. `pyproject.toml` is the only build source of truth.
- `pyproject.toml` and `requirements.txt` are currently **spec-identical** (including the `fastapi>=0.115,<0.137` cap), but nothing enforces this — `requirements.txt` is hand-maintained duplication and gives a **false sense of pinning** (no exact versions anywhere).
- **The fastapi cap alone does not close the incident class.** Even with `fastapi<0.137`, a clean rebuild today still pulls `prometheus-fastapi-instrumentator==8.0.0` and transitive `starlette==1.3.1` (both floor-only / uncapped), which differ from the locally-installed 7.1.0 / 0.52.1. The exact same "clean build resolves something newer" mechanism remains live for the rest of the web stack.
- **Top high-risk floor-only deps to cap first:** `prometheus-fastapi-instrumentator`, `starlette` (transitive, currently uncapped), `uvicorn`, `openai-agents`, `sqlalchemy`.
- **fastapi cap follow-up:** the cap **cannot yet be lifted** by bumping the instrumentator. The newest instrumentator is `8.0.0` (released 2026-05-29, *before* fastapi 0.137 on 2026-06-14); no release yet fixes the `_IncludedRouter` break against fastapi 0.137 / starlette 1.x. Re-check after the next instrumentator release.

---

## 1. Summary table

Installed = local `.venv` (`python 3.12.0`). **Prod anchor: fastapi 0.136.3** (commit `48b0e70`); local venv is older (0.135.1) and generally lags a clean build. Latest = PyPI as of 2026-06-14.

Gap legend: `=` same · `patch` · `minor` · `MAJOR` (incl. 0.x minor treated as breaking per SemVer-0).

| Dependency | Spec (pyproject) | Class | Installed (venv) | Latest (PyPI) | Gap | Risk | Recommended bound |
|---|---|---|---|---|---|---|---|
| pydantic | `>=2.0,<3.0` | bounded | 2.12.5 | 2.13.4 | minor | low | keep `<3.0` |
| pydantic-settings | `>=2.0` | floor | 2.13.1 | 2.14.1 | minor | low | `>=2.0,<3.0` |
| jsonschema | `>=4.0` | floor | 4.26.0 | 4.26.0 | = | low | `>=4.0,<5` |
| httpx | `>=0.27` | floor | 0.28.1 | 0.28.1 | = | medium | `>=0.27,<0.29` |
| typer | `>=0.12` | floor | 0.24.1 | 0.26.7 | minor(0.x) | low | `>=0.12,<1.0` |
| sqlalchemy[asyncio] | `>=2.0` | floor | 2.0.48 | 2.0.50 | patch | **medium** | `>=2.0,<2.1` |
| asyncpg | `>=0.29` | floor | 0.31.0 | 0.31.0 | = | medium | `>=0.29,<0.32` |
| psycopg2-binary | `>=2.9` | floor | 2.9.11 | 2.9.12 | patch | low | `>=2.9,<3.0` |
| alembic | `>=1.13` | floor | 1.18.4 | 1.18.4 | = | medium | `>=1.13,<2.0` |
| pgvector | `>=0.3.0` | floor | 0.4.2 | 0.4.2 | = | low | `>=0.3,<0.5` |
| telethon | `>=1.36` | floor | 1.42.0 | 1.43.2 | minor | medium | `>=1.36,<2.0` |
| structlog | `>=24.0` | floor | 25.5.0 | 26.1.0 | MAJOR | low | `>=24,<27` |
| **fastapi** | `>=0.115,<0.137` | bounded | 0.135.1 (prod 0.136.3) | 0.137.0 | minor(0.x) blocked | **high** | keep `<0.137` (see §6) |
| uvicorn[standard] | `>=0.32` | floor | 0.42.0 | 0.49.0 | minor(0.x) | **high** | `>=0.32,<0.50` |
| slowapi | `>=0.1.9` | floor | 0.1.9 | 0.1.10 | patch(0.x) | low | `>=0.1.9,<0.2` |
| **openai-agents** | `>=0.6` | floor | 0.13.6 | 0.17.5 | minor(0.x) ×4 | **high** | `>=0.13,<0.18` |
| PyYAML | `>=6.0` | floor | 6.0.3 | 6.0.3 | = | low | `>=6.0,<7` |
| python-dotenv | `>=1.0` | floor | 1.2.2 | 1.2.2 | = | low | `>=1.0,<2` |
| **prometheus-fastapi-instrumentator** | `>=7.0` | floor | 7.1.0 | 8.0.0 | MAJOR | **high** | `>=7.0,<8.0` (or pin to tested 8.0.0) |
| apscheduler | `>=3.10` | floor | 3.11.2 | 3.11.2 | = | low | `>=3.10,<4.0` |
| mcp | `>=1.25` | floor | 1.27.0 | 1.27.2 | patch | medium | `>=1.25,<2.0` |
| aiogram | `>=3.15` | floor | 3.27.0 | 3.29.0 | minor | medium | `>=3.15,<4.0` |
| pymorphy3 | `>=2.0` | floor | 2.0.6 | 2.0.6 | = | low | `>=2.0,<3` |
| pymorphy3-dicts-ru | `>=2.4` | floor | 2.4.417150.4580142 | (same) | = | low | `>=2.4` |
| simplemma | `>=1.0` | floor | 1.2.0 | 1.2.0 | = | low | `>=1.0,<2` |
| **starlette** (transitive via fastapi/instrumentator) | *(none — uncapped)* | unbounded(transitive) | 0.52.1 | 1.3.1 | **MAJOR (0.x→1.x)** | **high** | constrain via lockfile / cap instrumentator |
| openai (transitive via openai-agents) | *(none)* | unbounded(transitive) | 2.31.0 | 2.41.1 | minor | medium | constrain via lockfile |
| **dev** pytest | `>=8.0` | floor | 9.0.2 | 9.1.0 | minor | low | `>=8.0,<10` |
| **dev** pytest-asyncio | `>=0.23` | floor | 1.3.0 | 1.4.0 | minor | low | `>=0.23,<2` |
| **dev** pytest-cov | `>=4.0` | floor | 7.1.0 | 7.1.0 | = | low | `>=4.0,<8` |
| **dev** testcontainers[postgres] | `>=4.8` | floor | 4.14.2 | 4.14.2 | = | low | `>=4.8,<5` |
| **dev** ruff | `==0.15.11` | pinned | 0.15.11 | 0.15.17 | patch | low | already pinned (good) |

> Note on `starlette`/`openai`: these are **not** declared in `pyproject.toml`; they are pulled transitively and are therefore *completely uncontrolled* on a clean build. `starlette` is the single most dangerous one — the 0.x→1.x major jump is exactly what a clean rebuild now resolves.

---

## 2. The incident, re-explained with the resolution data

The 2026-06-14 outage was a **runtime** incompatibility, not a pip resolver conflict:

- fastapi `0.136.3`, `0.137.0` all declare only `starlette>=0.46.0` (**no upper cap**). A clean build therefore resolves the newest starlette → `1.3.1`.
- `prometheus-fastapi-instrumentator` requirements changed across the 7→8 boundary:
  - `7.1.0` → `starlette<1.0.0,>=0.30.0`
  - `8.0.0` → `starlette<2.0.0,>=1.0.0`  *(released 2026-05-29)*
- With `prometheus-fastapi-instrumentator>=7.0` floor-only, a clean build pulls `8.0.0` + `starlette 1.x`. Combined with **fastapi 0.137.0** (released 2026-06-14, after instrumentator 8.0.0 was tested), the instrumentator hit `AttributeError: '_IncludedRouter'` → every request 500.

**Why the current cap is necessary but insufficient:**
- `fastapi<0.137` correctly pins the framework back to 0.136.x.
- BUT `prometheus-fastapi-instrumentator>=7.0` and transitive `starlette` are still floor-only/uncapped. A clean build today = `fastapi 0.136.3` + `instrumentator 8.0.0` + `starlette 1.3.1` — a combination the local venv has **never run** (it has 7.1.0 / 0.52.1). It is *probably* fine (8.0.0 was built against fastapi 0.136.x), but it is unverified drift of the exact kind that caused the incident.

---

## 3. `pyproject.toml` vs `requirements.txt` drift

**Finding: currently spec-identical, structurally fragile.**

- Every package in `requirements.txt` matches the `pyproject.toml` spec one-for-one, **including** the `fastapi>=0.115,<0.137` cap and the `ruff==0.15.11` pin. There is no live disagreement today.
- However:
  1. **The Dockerfile builds from `pyproject.toml` only** (`COPY pyproject.toml ...` + `RUN pip install --user --no-cache-dir .`). `requirements.txt` is never copied or installed in the image. → **`requirements.txt` has zero effect on the production artifact.**
  2. The two files are kept in sync **by hand**. Nothing (no test, no CI) enforces it. The next person who edits one and forgets the other creates silent drift, and because `requirements.txt` looks authoritative, it becomes **actively misleading**.
  3. Neither file pins exact versions (except `ruff`), so neither delivers reproducibility regardless of which is "authoritative."

**Reconcile recommendation (pick one):**
- **Preferred:** make `pyproject.toml` the single declared source of intent, and **delete or auto-generate** `requirements.txt`. If a `requirements.txt` is still wanted (e.g. for tooling), generate it from `pyproject.toml` via `pip-compile`/`uv pip compile` as a *pinned lockfile* (with hashes), not a hand-edited copy of the same ranges.
- Do **not** keep two hand-maintained range files. That is pure drift surface with no benefit.

---

## 4. Reproducibility strategy options

| Option | What it does | Pros | Cons | Fit for this repo |
|---|---|---|---|---|
| **(a) Upper bounds in `pyproject.toml`** | Add `<` caps to floor-only deps | Cheap, no new tooling, stops uncontrolled majors, fixes the build-source-of-truth | Doesn't pin *exact* versions (patch/minor drift remains); transitive deps (`starlette`, `openai`) still uncapped unless added explicitly | **Do this now** — minimum viable fix |
| **(b) Lockfile / constraints** | `uv lock` or `pip-compile` → fully pinned, hashed lockfile; Dockerfile installs from it | True reproducibility incl. transitives; hash-verified; clean builds become deterministic | New tooling + workflow; must regenerate on each bump; Dockerfile must change to install from lock (currently `pip install .`) | **Do this next** — the real fix for transitive `starlette` |
| **(c) CI clean-cache build guard** | CI builds image with no cache and fails if resolved versions differ from a committed manifest | Catches drift before deploy; would have caught this incident | Needs CI minutes + a baseline manifest; meaningful only alongside (a)/(b) | Worthwhile once (b) exists (diff lockfile) |
| **(d) Dependabot/Renovate** | Automated, reviewable bump PRs | Controlled upgrades, changelog visibility, batches | Noise for a single-owner repo; only useful if bounds/lock exist to bump | Optional; low priority at this scale |

**Recommended combination for this repo (single-owner, manual deploy):**
1. **Now (option a):** add conservative upper bounds to the high/medium-risk floor-only deps in `pyproject.toml` (web/ASGI stack, DB, SDKs). This is the cheapest, highest-leverage change and directly closes the "clean build resolves something newer" class for declared deps.
2. **Soon (option b):** introduce `uv lock` (or `pip-compile --generate-hashes`) and switch the Dockerfile to install from the lockfile. This is the only thing that pins **transitive** `starlette`/`openai` and makes builds bit-for-bit reproducible. Decommission the hand-maintained `requirements.txt` in the same change (generate it if still needed).
3. **Then (option c):** a lightweight CI job that does a clean (`--no-cache`) build and diffs the resolved set against the committed lockfile, failing on unexpected deltas.
4. **(d) optional:** Renovate later for batched, reviewable bumps once (a)+(b) make bumps safe.

---

## 5. Prioritized action list

**HIGH — cap before next clean build (web/ASGI stack + SDKs):**
1. `prometheus-fastapi-instrumentator` → `>=7.0,<8.0` *(or pin `==8.0.0` after a smoke test against the running fastapi 0.136.x)*. Directly part of the incident; 7→8 is a major with a hard `starlette` floor change.
2. `starlette` — **add an explicit cap** (it is currently transitive/uncapped): pin `<1.0` while on instrumentator 7.x, OR accept `1.x` only via a lockfile. This 0.x→1.x jump is the live danger.
3. `uvicorn[standard]` → `>=0.32,<0.50`. 0.42→0.49 unbounded; uvicorn 0.x minors carry behavior changes.
4. `openai-agents` → `>=0.13,<0.18`. Pre-1.0 SDK, 0.6→0.17 floor is extremely loose; four minor jumps behind latest.
5. `fastapi` — keep `<0.137` (already capped). See §6 for lift conditions.

**MEDIUM — cap opportunistically (DB / Telegram / clients):**
6. `sqlalchemy[asyncio]` → `<2.1` (ORM core).
7. `alembic` → `<2.0`; `asyncpg` → `<0.32`; `psycopg2-binary` → `<3.0` (migration/DB drivers).
8. `telethon` → `<2.0`; `aiogram` → `<4.0` (Telegram core — a 2.0/4.0 major would break ingestion/bot).
9. `mcp` → `<2.0`; `httpx` → `<0.29`; `openai` (transitive) → constrain via lockfile.

**LOW — tidy up with the same change:**
10. `pydantic-settings`, `jsonschema`, `typer`, `pgvector`, `structlog`, `slowapi`, `PyYAML`, `python-dotenv`, `apscheduler`, `pymorphy3*`, `simplemma`, and the dev group → add coarse `<next-major` caps for hygiene.

**Structural:**
11. Decide source of truth: keep `pyproject.toml`, generate/delete `requirements.txt`.
12. Add a lockfile (option b) and switch Dockerfile to install from it — the only fix for transitive `starlette`.

---

## 6. fastapi cap follow-up — can `<0.137` be lifted by bumping the instrumentator?

**Not yet.**

- Latest `prometheus-fastapi-instrumentator` is **`8.0.0`, released 2026-05-29** — *before* fastapi `0.137.0` (2026-06-14). There is **no instrumentator release that postdates / fixes the `_IncludedRouter` break** introduced by fastapi 0.137.
- `8.0.0` already supports starlette 1.x (`starlette<2.0.0,>=1.0.0`), so the starlette side is ready; the blocker is the fastapi 0.137 internal API change that `8.0.0` does not yet handle.
- **Action:** keep `fastapi<0.137`. Re-check after the next `prometheus-fastapi-instrumentator` release (>8.0.0). The lift is safe only once: (1) a new instrumentator version explicitly supports fastapi 0.137+, and (2) a clean build + request smoke test passes. Until then, lifting the cap reintroduces the outage.

---

## 7. Data provenance / caveats

- **Installed versions:** local `.venv` (`python 3.12.0`), `pip freeze`. The venv lags a clean build (e.g. fastapi 0.135.1, instrumentator 7.1.0, starlette 0.52.1). **Prod anchor is fastapi 0.136.3** per the issue; other prod versions were not read from the VPS container in this run (local venv used as proxy). For ground truth, `docker compose exec tg_parser pip freeze` on prod would confirm the instrumentator/starlette combo actually running.
- **Latest versions & requires_dist:** PyPI JSON API (`https://pypi.org/pypi/<pkg>/json`), fetched 2026-06-14.
- No files other than this report were written. No commits, pushes, or deploys.
