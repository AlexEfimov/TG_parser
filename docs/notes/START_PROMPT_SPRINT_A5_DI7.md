# Sprint A.5 — DI-7 (per-DB `alembic.ini` instead of runtime tempfile)

**Дата подготовки:** 19 апреля 2026 (по итогам Sprint A.4 / DI-10, Session 52).
**Тип сессии:** Refactor + lightweight verification (~0.3–0.5 сессии).
**HEAD:** `6e60477` на `origin/main` (после Sprint A.4: 1 коммит закрывает DI-10; CI зелёный — Test Python 3.12, Alembic Guardrails, Lint Documentation, Docker Build).
**Связанные задачи в `docs/notes/FUTURE_FEATURES.md`:** DI-7 (~line 2320). После A.5 разблокируется ничего нового, но runtime-магия `_build_per_db_alembic_ini` уйдёт, и A.6/A.7 строятся на чистой инфраструктуре.

**Roadmap:** A.5 (DI-7, эта) → A.6 (DI-9 phase 2, testcontainers smoke) → A.7 (DI-19, drop legacy DDL helpers). После — migration tech-debt = 0.

---

## Цель сессии

Убрать runtime-генерацию tempfile `_build_per_db_alembic_ini` в пользу трёх статических ini-файлов под каждую логическую БД. Это снимает магию string-substitution в Python, делает alembic invocation предсказуемым, и открывает дорогу к прямому `alembic -c migrations/alembic_processing.ini upgrade head` без CLI-обёртки.

**Не входит в сессию:** DI-9 phase 2 (testcontainers — следующая сессия), DI-19 (drop legacy DDL — A.7), DI-5 (operational backfill).

---

## Pre-flight (перед началом)

```bash
cd /Users/alexanderefimov/TG_parser
git pull --ff-only                              # должен быть на 6e60477
gh run list --branch main --limit 3              # CI зелёный?

# Local стек
docker compose ps                                # tg_parser_postgres — healthy
# если нет — DB_HOST=postgres docker compose up -d postgres

# Прочитать DI-7 entry в FUTURE_FEATURES.md (~line 2320)
grep -nE "^### DI-7:" docs/notes/FUTURE_FEATURES.md
```

**Critical reminder:** перед каждым `git commit` запускать `.venv/bin/ruff format <files>` и `.venv/bin/ruff check <files>` — иначе CI красный на line-length (lesson из Sprint A).

---

## Контекст: что мы знаем после аудита 19 апреля

### Текущее состояние (то, что меняем)

| Файл / место | Что делает |
|---|---|
| `migrations/alembic.ini` | Один общий ini. `script_location = migrations`, `version_locations = migrations/versions/{ingestion,raw,processing}` (все три ветки сразу). |
| `tg_parser/cli/db_cmd.py::_build_per_db_alembic_ini` (line 36) | На каждый CLI-вызов (`db upgrade`, `db check`, ...) читает `alembic.ini`, регексом подменяет `version_locations` на единственный путь, пишет в `tempfile.NamedTemporaryFile`, возвращает Path. |
| `tg_parser/cli/db_cmd.py::run_alembic_command` (line 82) | Создаёт tempfile, запускает `python -m alembic -c <tmp> -x db_name=<branch> <args>`, удаляет tempfile в `finally`. **8 callers**: upgrade / downgrade / current / heads / check / raw / stamp / revision / merge. |
| `tg_parser/cli/init_db.py::run_alembic_upgrade` (line 17) | **Второй прямой юзер `alembic.ini`** — без `_build_per_db_alembic_ini`! Вызывает `alembic -c migrations/alembic.ini -x db_name=<branch> upgrade head`. Работает только потому, что для команды `upgrade` env.py успевает переопределить `version_locations` через `set_main_option` ДО того, как ScriptDirectory сравнивает heads. **Хрупко.** |
| `migrations/env.py::run_migrations_offline/do_run_migrations` (lines 120, 143) | Динамически делает `config.set_main_option("version_locations", str(version_path))` ДО `context.configure(...)`. Это та самая защита, на которой держится `init_db.py`. |
| `.github/workflows/ci.yml::alembic-guardrail` (line 123–212) | Использует только `tg-parser db <cmd> --db <branch>` — после рефакторинга работает без изменений. |

### Почему сейчас runtime-tempfile

Из docstring `_build_per_db_alembic_ini` (line 41–55): для команд типа `check`, `current`, `heads` alembic создаёт `ScriptDirectory` **до** того, как `env.py` запустится. Если `version_locations` указывает на все 3 ветки — alembic видит 3 head'а одновременно и падает на «Multiple head revisions are present for given argument 'head'». Поэтому подмена ДО запуска alembic.

После DI-7 эта подмена будет статической (3 ini-файла), а не runtime tempfile.

### Hidden gotcha

`init_db.py::run_alembic_upgrade()` — **не маршрутизируется** через `db_cmd.py::run_alembic_command`. Он напрямую обращается к общему `migrations/alembic.ini`. На команде `upgrade` это работает (env.py успевает), но любая попытка вызвать оттуда `check`/`heads` упала бы. После DI-7 нужно тоже переключить `init_db.py` на per-DB ini — иначе оставим вторую копию проблемы.

---

## План шагов

### Шаг 1: Создать три статических `alembic_<db>.ini`

В `migrations/` рядом с существующим `alembic.ini` создать:

- `migrations/alembic_ingestion.ini`
- `migrations/alembic_raw.ini`
- `migrations/alembic_processing.ini`

Каждый — копия `alembic.ini` со следующими изменениями:

- `version_locations = migrations/versions/<db>` (только одна ветка).
- В шапке — короткий комментарий «Per-DB alembic config (DI-7) — branch: <db>. Generated convention; do not edit ad-hoc, see migrations/alembic.ini for shared base».
- Объяснительный комментарий про SQLite legacy убрать — ссылку на DI-7 заменить на «See `migrations/alembic.ini` for shared base».

Optional (если хочется ещё чище): извлечь shared logging/script_location в общий include — но Alembic не поддерживает `%include` natively. Скорее всего просто дублируем 80 строк × 3 = 240 строк, это нормально для config-файлов.

### Шаг 2: Переключить `db_cmd.py::run_alembic_command` на статические ini

Удалить:

- `import re`, `import tempfile` (больше не нужны).
- Функцию `_build_per_db_alembic_ini` целиком.
- `tmp_ini` cleanup в `finally`.

Заменить тело `run_alembic_command` (~30 строк) на простое:

```python
def run_alembic_command(args: list[str], db_name: str = "ingestion") -> int:
    project_root = get_project_root()
    alembic_ini = project_root / "migrations" / f"alembic_{db_name}.ini"

    if not alembic_ini.exists():
        typer.echo(f"❌ Файл конфигурации не найден: {alembic_ini}", err=True)
        return 1

    cmd = [
        sys.executable, "-m", "alembic",
        "-c", str(alembic_ini),
        "-x", f"db_name={db_name}",
        *args,
    ]
    try:
        result = subprocess.run(cmd, cwd=str(project_root), check=False)
        return result.returncode
    except FileNotFoundError:
        typer.echo("❌ Alembic не установлен. Установите: pip install alembic", err=True)
        return 1
    except Exception as e:
        typer.echo(f"❌ Ошибка при выполнении команды: {e}", err=True)
        return 1
```

### Шаг 3: Переключить `init_db.py::run_alembic_upgrade` на per-DB ini

Заменить:

```python
alembic_ini = project_root / "migrations" / "alembic.ini"
```

на:

```python
alembic_ini = project_root / "migrations" / f"alembic_{db_name}.ini"
```

Это убирает hidden race-condition (см. контекст выше).

### Шаг 4: Обновить общий `migrations/alembic.ini`

Опции:

**(a) Оставить как есть, но переописать шапку.** Пометить как «shared base / fallback» и явно сказать «при использовании tg-parser CLI / init_db автоматически выбирается `alembic_<db>.ini`. Этот файл оставлен для обратной совместимости и для случаев когда нужно посмотреть общую конфигурацию».

**(b) Удалить `migrations/alembic.ini` целиком.** Чище, но ломает любые внешние скрипты, которые могли его читать. Также `tests/test_repo_sql_references_declared_tables.py` или какая-нибудь другая статика может его трогать.

**Рекомендую (a)** — zero-risk, и оставляет single-place для shared logging config. Можно явно сказать «не использовать как `-c <ini>` напрямую — `version_locations` указывает на все 3 ветки, упадёт на multiple-heads». В шапке оставить ссылку «see `alembic_<db>.ini` for actual per-branch invocation».

### Шаг 5: Добавить `tests/test_alembic_ini_consistency.py`

Маленький guardrail (~30 строк):

```python
"""Statics: alembic_<db>.ini files must declare a single, correct version_locations."""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = REPO_ROOT / "migrations"

@pytest.mark.parametrize("db_name", ["ingestion", "raw", "processing"])
def test_per_db_alembic_ini_exists_and_is_scoped(db_name):
    ini_path = MIGRATIONS / f"alembic_{db_name}.ini"
    assert ini_path.exists(), f"Missing per-DB alembic ini: {ini_path}"

    content = ini_path.read_text(encoding="utf-8")
    matches = re.findall(r"^version_locations\s*=\s*(.*)$", content, re.MULTILINE)
    assert len(matches) == 1, f"{ini_path} must declare exactly one version_locations line"
    assert matches[0].strip() == f"migrations/versions/{db_name}", (
        f"{ini_path} version_locations must be migrations/versions/{db_name}, got {matches[0]!r}"
    )
```

Это zero-cost защита от случайного rebreaking (например, кто-то скопировал ini, забыл поменять путь).

### Шаг 6: Smoke

```bash
# 1) heads/current/check для каждой ветки — должны видеть только свои ревизии
for db in ingestion raw processing; do
  echo "--- $db ---"
  tg-parser db heads --db "$db"
  tg-parser db current --db "$db"
  tg-parser db check --db "$db"
done

# 2) Полный upgrade → downgrade → upgrade на каждой ветке
for db in ingestion raw processing; do
  tg-parser db upgrade --db "$db"
done
for db in ingestion raw processing; do
  tg-parser db downgrade --db "$db" --yes base
done
for db in ingestion raw processing; do
  tg-parser db upgrade --db "$db"
done

# 3) Прямой вызов alembic (теперь должен работать без обёртки)
.venv/bin/alembic -c migrations/alembic_processing.ini -x db_name=processing heads
.venv/bin/alembic -c migrations/alembic_processing.ini -x db_name=processing check
```

### Шаг 7: Тесты

```bash
.venv/bin/pytest tests/test_alembic_ini_consistency.py tests/test_cli_db_downgrade.py tests/test_migrations.py tests/test_migrations_self_contained.py tests/test_repo_sql_references_declared_tables.py -x -v
```

Особое внимание — `tests/test_cli_db_downgrade.py` мокает `run_alembic_command`, должен пройти без правок.

### Шаг 8: Lint + format

```bash
.venv/bin/ruff format migrations/*.ini  # ruff игнорирует .ini, но прогон не вредит
.venv/bin/ruff format tg_parser/cli/db_cmd.py tg_parser/cli/init_db.py tests/test_alembic_ini_consistency.py
.venv/bin/ruff check tg_parser/ tests/ migrations/
```

### Шаг 9: Обновить документацию

| Файл | Что обновить |
|---|---|
| `docs/runbooks/DEV_RESURRECTION.md` | FAQ — заменить упоминание `_build_per_db_alembic_ini` на «`tg-parser db ...` использует `migrations/alembic_<db>.ini`. Для прямого alembic invoke — `alembic -c migrations/alembic_<db>.ini -x db_name=<db> <cmd>`». |
| `docs/runbooks/SAFE_MIGRATION_ON_DEV.md` | Если упоминает _build_per_db_alembic_ini — обновить на новый flow. |
| `migrations/alembic.ini` | Шапка: «See `alembic_<db>.ini`. Don't use this file with `-c` directly — `version_locations` references all three branches and alembic will fail on multiple heads.» |

### Шаг 10: FUTURE_FEATURES.md → close DI-7

В DI-7 entry (~line 2320) добавить `**[FIXED 19 апреля 2026, Sprint A.5]**` блок с описанием:
- Что сделано (3 статических ini, удалена `_build_per_db_alembic_ini`, добавлен guardrail-test).
- Что упростилось (`run_alembic_command` стал на 30 строк короче, `init_db.py` больше не race-condition'ит на дефолтном ini).
- Verification: smoke + tests pass, CI зелёный.

### Шаг 11: Commit + push

Один атомарный коммит (рекомендую):

```bash
git add migrations/alembic_*.ini migrations/alembic.ini \
        tg_parser/cli/db_cmd.py tg_parser/cli/init_db.py \
        tests/test_alembic_ini_consistency.py \
        docs/runbooks/DEV_RESURRECTION.md \
        docs/runbooks/SAFE_MIGRATION_ON_DEV.md \
        docs/notes/FUTURE_FEATURES.md
git commit -m "refactor(migrations): per-DB alembic.ini instead of runtime tempfile (DI-7)"
git push origin main
gh run watch
```

---

## Risks & rollback

| Risk | Likelihood | Mitigation |
|---|---|---|
| Сломали `alembic check` для какой-то ветки (drift detection) | Low | Шаг 6 smoke — `tg-parser db check --db all` после рефакторинга. |
| Внешний скрипт читает `migrations/alembic.ini` напрямую | Very low | Файл оставлен как shared base (Шаг 4 опция a); только содержимое шапки обновлено. |
| `init_db.py` где-то ещё косвенно используется и сломается | Low | Шаг 7 тесты + smoke `init_databases_sync` через docker entrypoint (если он есть в pipeline). |
| Drift между 3 ini-файлами (logging/script_location рассогласован) | Medium со временем | Шаг 5 guardrail-test проверяет хотя бы `version_locations`. Опционально: добавить ассерт что `script_location = migrations` одинаковый везде. |

**Rollback:** `git revert <commit>`. Никаких миграций не создаётся, никаких schema changes — pure refactor.

---

## PR checklist

- [ ] Три файла `migrations/alembic_<db>.ini` созданы, каждый с правильным `version_locations`.
- [ ] `db_cmd.py::_build_per_db_alembic_ini` удалена. Импорты `re`, `tempfile` убраны.
- [ ] `init_db.py::run_alembic_upgrade` использует `alembic_<db>.ini`.
- [ ] `tests/test_alembic_ini_consistency.py` зелёный (3 параметризованных теста).
- [ ] `tg-parser db check --db all` — `No new upgrade operations detected` × 3.
- [ ] `tg-parser db heads --db all` — exactly 1 head на ветку.
- [ ] Smoke `upgrade → downgrade base → upgrade` на каждой ветке зелёный.
- [ ] Прямой `alembic -c migrations/alembic_processing.ini check` работает.
- [ ] `pytest tests/test_cli_db_downgrade.py tests/test_migrations*.py tests/test_repo_sql_references_declared_tables.py` зелёный.
- [ ] `ruff format` + `ruff check` чистые.
- [ ] `migrations/alembic.ini` шапка обновлена с предупреждением «не использовать напрямую».
- [ ] Runbook'и (`DEV_RESURRECTION.md`, `SAFE_MIGRATION_ON_DEV.md`) обновлены.
- [ ] `FUTURE_FEATURES.md` DI-7 → FIXED, описано что и как.
- [ ] CI зелёный после push.

---

## После DI-7 — Sprint A.6 / DI-9 phase 2

Следующая сессия — testcontainers-based smoke:
- Поднять testcontainer postgres + pgvector в pytest fixture (session-scoped).
- Прогнать `alembic upgrade head` на каждой ветке.
- Сравнить `pg_dump --schema-only` против БД, поднятой через legacy `init_*_schema()`. Должны быть identical (если нет — DI-19 не безопасен).
- Прогнать одинарные SELECT/INSERT по каждой таблице, чтобы поймать missing column / wrong type drift на runtime-уровне (не только AST как DI-9 phase 3).

См. `docs/notes/FUTURE_FEATURES.md` DI-9 entry (phase 2 detail) и DI-19 entry для shared infrastructure rationale.
