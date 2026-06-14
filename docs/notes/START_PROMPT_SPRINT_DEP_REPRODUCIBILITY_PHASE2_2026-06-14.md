# START PROMPT — Sprint: Dependency Reproducibility Phase 2 (`uv.lock` + CI guard)

**Дата создания:** 2026-06-14 · **Для:** новой (свежей) сессии в отдельном окне.
**Issue:** [#295](https://github.com/) — dependency reproducibility.
**Goal (одной строкой):** закрыть класс инцидента «clean build тянет что-то новее» полностью — адоптировать `uv` + `uv.lock` как источник правды резолюции, добавить upper-bounds в `pyproject.toml`, перестроить `Dockerfile` на установку из лока, регенерировать `requirements.txt` как pinned+hashed export, и завести CI-гард `deps-lock-guard`.

> **Рабочий режим (нормативно, [`AGENTS.md`](../../AGENTS.md)):** branch `main`; `docs/methodology/**` — не трогать. Правки `pyproject.toml` / `requirements.txt` / `Dockerfile` / `.github/workflows/**` **в обычном режиме forbidden без явного запроса — но для ЭТОГО Phase-2 scope они APPROVED** (входят в задачу по решению владельца, см. §2). **Тем не менее финальный `git commit` + деплой делаются ТОЛЬКО по явному go-ahead владельца.** Принцип: сначала регенерируем/проверяем артефакты локально → показываем диффы → коммит/деплой по команде. Scope строго по #295; unrelated-код не задевать.

> **Источник истины по дизайну:** [`PLAN_DEP_REPRODUCIBILITY_PHASE2_2026-06-14.md`](PLAN_DEP_REPRODUCIBILITY_PHASE2_2026-06-14.md) (полный план — tooling, Dockerfile-набросок, CI-гард, тиры upper-bounds, rollout) + [`DEP_PIN_AUDIT_2026-06-14.md`](DEP_PIN_AUDIT_2026-06-14.md) (аудит всех 30 зависимостей). Этот START_PROMPT — оперативная выжимка с зафиксированными решениями; при расхождении деталей план первичен.

---

## 1. Контекст — зачем это и где мы

**Инцидент (2026-06-14).** Чистый rebuild прода зарезолвил `fastapi 0.137.0` + `prometheus-fastapi-instrumentator 8.0.0` + transitive `starlette 1.x`. Комбинация `fastapi 0.137` × instrumentator 8.0.0 ловит `AttributeError: '_IncludedRouter'` → каждый запрос 500. Корень: **ни одного exact-pin нигде** (кроме `ruff`), `requirements.txt` дублировал диапазоны руками, Docker строился из `pyproject.toml` (`pip install .`) с floor-only `>=` — clean build всегда тянул новейшее.

**Phase 1 (уже отгружено, commit `9c547d5` на `main`, прод healthy на VPS):**
- `fastapi>=0.136,<0.137` закапано в `pyproject.toml` И `requirements.txt`.
- Регрессионный тест `tests/test_metrics_instrumentation.py` — metrics-path через `include_router` при `METRICS_ENABLED=true` (ловит именно тот 500).
- **starlette 1.x / instrumentator 8.0.0 подтверждены good** — Phase 2 их **НЕ** капает в pyproject (их пинит лок).

**Что Phase 2 закрывает (то, что Phase 1 НЕ закрыл):** даже с `fastapi<0.137` transitive `starlette` / instrumentator оставались floor-only → «unverified drift» того же класса. Phase 2 даёт *реальную* воспроизводимость через lockfile (пинит transitive с хэшами), + upper-bounds как guardrail против будущего `uv lock --upgrade` через мажор, + CI-гард на resolution-time (дополняет Phase-1 runtime-тест).

---

## 2. Зафиксированные решения владельца (НОРМАТИВНО — не переоткрывать)

Это решённые входы. В начале сессии **не выносить их на повторное обсуждение** — сразу реализовывать.

1. **`uv` — официальный toolchain** (dev-машины + VPS Docker build). `uv.lock` — источник правды резолюции. **Build backend остаётся `setuptools`** (никакого switch на uv build backend — это вне scope, см. §9 gotcha).
2. **`requirements.txt` остаётся, но становится GENERATED** — pinned+hashed `uv export` из лока (не правится руками, не удаляется). Это чистый pip-fallback для CI/онбординга.
3. **`openai-agents` floor поднимаем `0.6 → 0.13`** → итоговый спек `>=0.13,<0.18` (соответствует фактически используемому/прод 0.13.6).
4. **`uv.lock` снять из `.cursorignore`** И починить `.dockerignore` (убрать `uv.lock` оттуда), чтобы лок был виден агентам и доступен Docker build context.
5. **Renovate/Dependabot — отложены.** Phase 2 отгружает только lock + CI guard; боты позже.

---

## 3. Текущее состояние кода — проверенные якоря (перепроверить строки grep'ом)

| Артефакт | Где / факт |
|---|---|
| Docker строит из pyproject | [`Dockerfile`](../../Dockerfile) builder L15–19: `COPY pyproject.toml README.md ./` + `COPY tg_parser/`, `COPY prompts/` → `RUN pip install --user --no-cache-dir .`; runtime L28 копирует `/root/.local`. |
| `pyproject.toml` deps | [`pyproject.toml`](../../pyproject.toml) `[project].dependencies` L12–45; `fastapi>=0.136,<0.137` уже на L26; dev-extra L47–56 (`ruff==0.15.11` уже пинён). Backend = setuptools L1–3. |
| `requirements.txt` | spec-identичен pyproject-диапазонам, руками. |
| Стейл `uv.lock` уже git-tracked | последний коммит лока `4952a92` (2026-04-10) — **на ~2 мес устарел, предшествует fastapi-капу**. **Регенерировать с нуля, не доверять as-is.** |
| `uv.lock` в `.dockerignore` | [`.dockerignore`](../../.dockerignore) L29 — **убрать**. |
| `uv.lock` в `.cursorignore` | [`.cursorignore`](../../.cursorignore) L12 — **убрать**. |
| Нет `[tool.uv]` | uv работает в PEP 621 project-режиме; опционально добавить минимальный `[tool.uv]` (dev-group wiring). |
| CI ставит deps в 4 джобах | [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml): `test` L46–50, `compose-integration` L131–135, `alembic-guardrail` L266–270, `alembic-runtime-smoke` L344–348 — везде `pip install -r requirements.txt` + `pip install -e .`. Джоба `docker` L85–110 строит образ. |
| `.python-version` / requires-python | `3.12`; `requires-python = ">=3.12"`. Система `python3` = 3.10 — **uv обязан резолвить/собирать на 3.12** (`UV_PYTHON=3.12` в Docker; локально `.python-version`/`.venv`). |
| `uv` установлен | `uv 0.10.0` на dev-машине; `pip-tools` отсутствует. |

---

## 4. Задачи — конкретный scope (in/out), якоря, точные спеки

Порядок реализации = §8. Каждая правка файлов = по решению владельца APPROVED для этого scope, но коммит — по go-ahead.

### 4.1 — Upper bounds в `pyproject.toml` (`[project].dependencies`, L12–45)

**IN:** добавить `<`-капы к floor-only deps. Точные спеки (из плана §4 / аудита):

**Tier 1 — high-risk (MUST):**
- `uvicorn[standard]>=0.32` → `>=0.32,<0.50`
- `openai-agents>=0.6` → **`>=0.13,<0.18`** (floor поднят — решение §2.3)

**Tier 2 — medium (тот же PR):**
- `sqlalchemy[asyncio]>=2.0` → `>=2.0,<2.1`
- `alembic>=1.13` → `>=1.13,<2.0`
- `asyncpg>=0.29` → `>=0.29,<0.32`
- `psycopg2-binary>=2.9` → `>=2.9,<3.0`
- `telethon>=1.36` → `>=1.36,<2.0`
- `aiogram>=3.15` → `>=3.15,<4.0`
- `mcp>=1.25` → `>=1.25,<2.0`
- `httpx>=0.27` → `>=0.27,<0.29`

**Tier 3 — hygiene (coarse `<next-major`, тот же PR):**
- `pydantic-settings>=2.0` → `>=2.0,<3.0`
- `jsonschema>=4.0` → `>=4.0,<5`
- `typer>=0.12` → `>=0.12,<1.0`
- `pgvector>=0.3.0` → `>=0.3.0,<0.5`
- `structlog>=24.0` → `>=24.0,<27`
- `slowapi>=0.1.9` → `>=0.1.9,<0.2`
- `PyYAML>=6.0` → `>=6.0,<7`
- `python-dotenv>=1.0` → `>=1.0,<2`
- `apscheduler>=3.10` → `>=3.10,<4.0`
- `pymorphy3>=2.0` → `>=2.0,<3`
- `simplemma>=1.0` → `>=1.0,<2`
- dev-группа: `pytest>=8.0` → `>=8.0,<10`; `pytest-asyncio>=0.23` → `>=0.23,<2`; `pytest-cov>=4.0` → `>=4.0,<8`; `testcontainers[postgres]>=4.8` → `>=4.8,<5` (`ruff==0.15.11` уже пинён — не трогать).
- `pymorphy3-dicts-ru>=2.4` — оставить как есть (datapack, без `<`).

**OUT (явно НЕ капать — решено):**
- `fastapi` — оставить `>=0.136,<0.137` (Phase 1). Не трогать.
- `starlette` — **НЕ добавлять pyproject-кап** (transitive; пинит лок; 1.x подтверждён good — Phase-1 перекрывает старую `<1.0` рекомендацию аудита).
- `prometheus-fastapi-instrumentator>=7.0` — **НЕ капать** (8.0.0 подтверждён good; пинит лок; аудитная `<8.0` отменена). *(Оставляем `>=7.0` floor — лок зафиксирует именно 8.0.0.)*
- `openai` — transitive, нет записи в pyproject; пинит лок.

> Каваты в pyproject + exact-pins в `uv.lock` — комплементарны. Лок даёт воспроизводимость *сегодня*; капы не дают будущему `uv lock --upgrade` молча перейти мажор.

Опционально: минимальный `[tool.uv]` (dev-group по умолчанию для локального `uv sync`, `--no-dev` в Docker/prod).

### 4.2 — Регенерировать `uv.lock` с нуля + un-ignore

**IN:**
```bash
# из repo root, на python 3.12 (.python-version уже пинит)
uv lock                 # резолв pyproject (с новыми капами) → свежий uv.lock incl. transitives + хэши
uv lock --check         # лок синхронен с pyproject
git diff uv.lock        # ревью каждого пина: fastapi 0.136.x, starlette 1.x, instrumentator 8.0.0, openai, uvicorn
```
- Убрать `uv.lock` из [`.dockerignore`](../../.dockerignore) L29 и [`.cursorignore`](../../.cursorignore) L12 (решение §2.4).
- **Не доверять старому локу** — он стейл (§3).

### 4.3 — Регенерировать `requirements.txt` как pinned+hashed export

**IN:**
```bash
uv export --frozen --no-dev --no-emit-project --format requirements-txt -o requirements.txt
```
- Добавить header-баннер: `# AUTO-GENERATED from uv.lock by 'uv export' — DO NOT EDIT BY HAND.` + команда регена.
- Файл остаётся по тому же пути (README/CI/docs продолжают работать), но становится derived-артефактом (real pins+hashes, не диапазоны).
- **OUT:** не удалять, не переименовывать в `requirements.lock`.

### 4.4 — Переписать `Dockerfile` builder на `uv sync --frozen --no-dev`

**IN (подход 5.3-A из плана — uv-native, рекомендован):** заменить builder install-слой; venv копировать в runtime-стейдж; сохранить layer-кэширование (deps-слой ДО исходников).

```dockerfile
# ---- Builder stage ----
FROM python:3.12-slim AS builder
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.10.0 /uv /uvx /bin/
RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*
ENV UV_LINK_MODE=copy \
    UV_PYTHON=3.12 \
    UV_PROJECT_ENVIRONMENT=/opt/venv
# Layer 1: deps only (cached unless pyproject/lock change) — NO project code yet
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
# Layer 2: project source + install package (changes often, deps stay cached)
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
Ключевое: `--frozen` запрещает ре-резолв (фейлит на стейл-локе — это и есть гард); deps-слой копируется ДО исходников (кэш не инвалидируется на code-only правке); `--no-dev` исключает test/lint-группу; runtime несёт только resolved venv. Transitive `starlette`/`openai` пинятся локом автоматически.

**Fallback 5.3-B (если владелец отвергнет uv-in-image):** `pip install --require-hashes -r requirements.txt` + `pip install --no-deps .`. По умолчанию НЕ использовать — только при явном отказе от uv-в-образе.

### 4.5 — CI: добавить `deps-lock-guard` + мигрировать install-шаги

**IN — новая джоба** (в [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml), быстрая, без DB):
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
        run: uv lock --check
      - name: requirements.txt matches the lock
        run: |
          uv export --frozen --no-dev --no-emit-project \
            --format requirements-txt -o requirements.txt
          git diff --exit-code -- requirements.txt
      - name: Clean resolve from lock (no resolver freedom)
        run: uv sync --frozen --no-dev --no-install-project
```
Ловит: (a) бамп диапазона в pyproject без ре-лока, (b) дрейф сгенерированного `requirements.txt`, (c) лок не резолвится чисто. Вместе с Phase-1 runtime-тестом закрывает обе половины класса инцидента.

**IN — мигрировать 4 install-шага** (`test` L46–50, `compose-integration` L131–135, `alembic-guardrail` L266–270, `alembic-runtime-smoke` L344–348): заменить `pip install -r requirements.txt` + `pip install -e .` на:
```yaml
- uses: astral-sh/setup-uv@v4
  with: { version: "0.10.0", enable-cache: true }
- run: uv sync --frozen
```
и префиксить инвокации `uv run` (`uv run pytest …`, `uv run ruff check .`) либо активировать `.venv`. Джоба `docker` (L85–110) структурно как есть — она строит образ, который теперь ставит из лока.

> **Внимание (consistency-гард):** новый `deps-lock-guard` сам становится частью этого PR. Любая правка `pyproject.toml` после регена лока без повторного `uv lock` зафейлит джобу — это by design. Убедиться, что финальный коммит включает синхронные `pyproject.toml` + `uv.lock` + `requirements.txt`.

### 4.6 — Docs (lightweight, в том же scope)

В блоках с `pip install -r requirements.txt` (`README.md:77`, `docs/guides/SELF_HOST.md:105`, `docs/USER_GUIDE.md:68`, `QUICKSTART_v1.2.md:42`) добавить одну строку uv-альтернативы (`uv sync`) и пометку, что `requirements.txt` сгенерирован. **OUT:** масштабный рерайт онбординга — не нужен.

---

## 5. Contracts / ADR

- **Контракты JSON Schema** (`docs/contracts/`) этим scope не затрагиваются — изменений в доменных данных нет.
- **ADR-стаб уместен:** завести `docs/adr/0017-dependency-management-policy.md` (следующий свободный номер — текущие ADR идут до `0016`) — зафиксировать: uv+uv.lock как источник правды, setuptools остаётся backend, `requirements.txt` = generated export, политика upper-bounds (капы в pyproject + exact-pins в локе), `deps-lock-guard` как enforcement, lift-процедура `fastapi<0.137`. Это решение владельца на старте сессии (хочет ADR сейчас или follow-up).
- **ADR-0006** (karpathy-like Living KB) — **не релевантен** этому scope; не ссылаться.

---

## 6. Test strategy

- **Baseline ДО правок** (зафиксировать зелёный старт, вне sandbox, `required_permissions: all`):
  `TEST_POSTGRES=1 .venv/bin/python -m pytest -q` → ожидаемый baseline **3381 passed / 20 skipped / 2 deselected**. Любой новый fail/skip после правок — блокирующий.
- **Phase-1 регресс ОБЯЗАН остаться зелёным:** `tests/test_metrics_instrumentation.py` (metrics через `include_router` при `METRICS_ENABLED=true`).
- **После регена лока, локально:** `uv sync --frozen && uv run pytest -q` (и `TEST_POSTGRES=1 …` режим). Ре-синкнуть dev `.venv` через `uv sync --frozen`, чтобы local == lock == CI == prod.
- **Clean Docker build:** `docker build --no-cache -t tg_parser:phase2 .` → `docker run --rm tg_parser:phase2 --help`.
- **Pin verification (pre-swap):** `docker run --rm --entrypoint pip tg_parser:phase2 freeze | grep -Ei 'fastapi|starlette|prometheus-fastapi-instrumentator|uvicorn|openai'` → подтвердить **fastapi 0.136.x, starlette 1.x, instrumentator 8.0.0** (confirmed-good set), НЕ 0.137.
- **CI:** push ветки → `deps-lock-guard` + Phase-1 metrics-тест зелёные.
- **ruff:** `uv run ruff format .` + `uv run ruff check .` чисто на изменённых файлах.

---

## 7. Definition of Done (нормативно)

- [ ] Upper-bounds (Tier 1+2+3) добавлены в `pyproject.toml`; `fastapi<0.137` сохранён; `starlette`/`instrumentator` НЕ закапаны.
- [ ] `uv.lock` регенерирован с нуля на 3.12, `uv lock --check` зелёный, диффы отревьюены (fastapi 0.136.x / starlette 1.x / instrumentator 8.0.0 / openai пины зафиксированы).
- [ ] `uv.lock` убран из `.dockerignore` и `.cursorignore`; лок виден агентам и доступен Docker build context.
- [ ] `requirements.txt` регенерирован как pinned+hashed `uv export` + header-баннер «auto-generated».
- [ ] `Dockerfile` строит из лока (`uv sync --frozen --no-dev`), runtime несёт resolved venv, layer-кэш сохранён.
- [ ] CI: `deps-lock-guard` добавлен и зелёный; 4 install-шага мигрированы на `uv sync --frozen` + `uv run`.
- [ ] Docs-блоки `pip install -r requirements.txt` дополнены uv-альтернативой + пометкой «generated».
- [ ] Clean Docker build OK; pre-swap `pip freeze` подтверждает confirmed-good set (не 0.137).
- [ ] Baseline re-run зелёный (`TEST_POSTGRES=1 … pytest -q`, без новых fail/skip); Phase-1 metrics-тест зелёный.
- [ ] `ruff` чисто на изменённых файлах.
- [ ] **commit + deploy — ТОЛЬКО по явному go-ahead владельца.** VPS задеплоен + smoke зелёный (см. §8).
- [ ] Закрывающие строки в [`BUG_LOG.md`](BUG_LOG.md) (convention BUG-NNN/TD) + комментарий-закрытие в #295.
- [ ] **`fastapi<0.137` lift-watch** зафиксирован (см. §8) — кап остаётся, перепроверка после следующего релиза instrumentator.
- [ ] (опц.) ADR-0017 dependency-management policy заведён, если владелец захотел сейчас.

---

## 8. Rollout / VPS deploy / rollback (по go-ahead)

**Порядок реализации:** §4.1 (pyproject) → §4.2 (lock + un-ignore) → §4.3 (requirements export) → §4.4 (Dockerfile) → §4.5 (CI) → §4.6 (docs) → §6 verify → коммит (go-ahead) → деплой (go-ahead).

**VPS факты:** manual deploy — `ssh prod` (host `212.72.189.15:2296`, user `user`), реальный путь `/home/user/TG_parser`, compose project `tg_parser`.

**Процедура деплоя:**
1. `./docker/backup.sh`.
2. (ground-truth перед свапом) `docker compose exec tg_parser pip freeze > /tmp/prod_freeze_pre.txt`.
3. `git pull --ff-only`.
4. `docker compose build`.
5. **Pre-swap version check (ДО пересоздания контейнеров):** прогнать `pip freeze` нового образа, сверить с ожидаемым набором (fastapi 0.136.x, starlette 1.x, instrumentator 8.0.0 — НЕ 0.137); diff против `/tmp/prod_freeze_pre.txt` — подтвердить только намеренные дельты.
6. `db current` (зафиксировать ревизии).
7. `docker compose up -d` + `docker compose --profile bot up -d --force-recreate --no-deps tg_bot`.
8. **Smoke:** `/health` → 200, `/metrics` → 200 (это поверхность инцидента; `METRICS_ENABLED=true` — прод-дефолт), реальный `include_router`-роут не 500, логи чистые.
9. Подтвердить: VPS HEAD == pushed SHA && running image свежий.

**Rollback:** если `/health` != 200 (или `/metrics` регрессит) — ретегнуть/откатить на last-known-good образ (`docker compose up -d` на прежний tag), либо `git revert` Phase-2 коммита + rebuild. Лок детерминирован → rebuild воспроизводит ровно прежний набор.

**`fastapi<0.137` lift-watch:** кап ОСТАЁТСЯ. Перепроверять после следующего релиза `prometheus-fastapi-instrumentator` (>8.0.0), который явно поддержит fastapi 0.137 `_IncludedRouter`. Lift-процедура: `uv lock --upgrade-package fastapi --upgrade-package prometheus-fastapi-instrumentator` → `uv run pytest tests/test_metrics_instrumentation.py` → clean Docker build + `/metrics` smoke → только потом расслаблять pyproject-кап.

---

## 9. Risks / gotchas (из плана §9 — кратко)

- **Стейл `uv.lock` (2026-04-10)** — НЕ переиспользовать; `uv lock` с нуля; `--check`/clean-resolve держат честно.
- **`.dockerignore` исключает `uv.lock`** — lock-driven Dockerfile молча падает/ре-резолвит, если строку не убрать. Явный шаг §4.2.
- **Build-backend confusion** — uv НЕ форсит switch backend; setuptools остаётся. Не «мигрировать на uv build backend» — это вне scope (только опц. `[tool.uv]` dev-wiring).
- **Docker cache invalidation** — COPY `pyproject.toml`+`uv.lock` (deps-слой) ДО исходников; неправильный порядок убивает кэш.
- **Python skew** — система 3.10, проект 3.12; `UV_PYTHON=3.12` в Docker, `.python-version`/`.venv` локально. Лок, резолвнутый на 3.10, мисрезолвит.
- **Hashes + индексы** — все deps публичный PyPI → ок; приватный индекс потребовал бы конфигурации `[tool.uv]`.
- **Local `.venv` лагает** — после Phase 2 `uv sync --frozen` выравнивает .venv/CI/Docker/prod на один набор; ре-синкнуть `.venv` в rollout.

---

## 10. Артефакты для контекста (прочитать в начале)

- **План (источник правды):** [`PLAN_DEP_REPRODUCIBILITY_PHASE2_2026-06-14.md`](PLAN_DEP_REPRODUCIBILITY_PHASE2_2026-06-14.md).
- **Аудит:** [`DEP_PIN_AUDIT_2026-06-14.md`](DEP_PIN_AUDIT_2026-06-14.md).
- **Код-якоря:** [`Dockerfile`](../../Dockerfile), [`pyproject.toml`](../../pyproject.toml), [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml), [`.dockerignore`](../../.dockerignore), [`.cursorignore`](../../.cursorignore).
- **Phase-1 регресс:** `tests/test_metrics_instrumentation.py`.
- **Рабочий режим:** [`AGENTS.md`](../../AGENTS.md); режимы pytest — [`tests/README.md`](../../tests/README.md).
- **Backlog/закрытие:** [`BUG_LOG.md`](BUG_LOG.md); issue #295.

---

## 11. Стартовая реплика для новой сессии (можно скопировать)

> Берёмся за **Phase 2 — dependency reproducibility (#295)**. Прочитай [`docs/notes/START_PROMPT_SPRINT_DEP_REPRODUCIBILITY_PHASE2_2026-06-14.md`](docs/notes/START_PROMPT_SPRINT_DEP_REPRODUCIBILITY_PHASE2_2026-06-14.md), а затем план и аудит, на которые он ссылается. Решения владельца зафиксированы (не переоткрывай): **uv + uv.lock как источник правды резолюции** (setuptools backend остаётся), `requirements.txt` становится generated pinned+hashed `uv export`, `openai-agents` floor поднимаем до `>=0.13,<0.18`, `uv.lock` снимаем из `.cursorignore` и `.dockerignore`, Renovate/Dependabot откладываем. Правки `pyproject.toml`/`requirements.txt`/`Dockerfile`/`.github/workflows` для этого scope разрешены, НО финальный commit и деплой — только по моему явному go-ahead. Сделай по порядку §4/§8: добавь upper-bounds (Tier 1+2+3, `fastapi<0.137` сохранить, `starlette`/instrumentator НЕ капать), регенерируй `uv.lock` с нуля на 3.12 + `uv lock --check`, un-ignore лок, регенерируй `requirements.txt` через `uv export`, перепиши Dockerfile builder на `uv sync --frozen --no-dev`, добавь CI-джобу `deps-lock-guard` и мигрируй 4 install-шага на `uv sync`. Перед стартом сними baseline `TEST_POSTGRES=1 .venv/bin/python -m pytest -q` вне sandbox (ожидаю 3381 passed / 20 skipped / 2 deselected), после правок — clean Docker build + pre-swap `pip freeze` (подтвердить fastapi 0.136.x / starlette 1.x / instrumentator 8.0.0, не 0.137), полный прогон зелёный + Phase-1 `tests/test_metrics_instrumentation.py`, ruff чисто. DoD и VPS-деплой/rollback — в §7/§8. Спроси, заводим ли ADR-0017 dependency-management policy сейчас или follow-up.
