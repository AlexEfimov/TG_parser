# Hotfix Sprint — BUG-028 Digest Cron PromptLoader None Regression (2026-05-23)

**Назначение:** короткая hotfix-сессия, закрывающая root cause **BUG-028** — `digest_task` падает с `PromptLoaderError: prompt file not found: /app/None/processing.yaml`, потому что `Settings.prompts_dir` по умолчанию `None`, а `scheduler_service.py:560` оборачивает его в `str(...)` без guard. На проде уже стоит env-workaround (`PROMPTS_DIR=/app/prompts` на `tg_bot`); этот PR убирает workaround как обязательную меру и закрывает дефект на уровне кода.

**Тип сессии:** writing — code, tests, PR. Один branch, один (или два) commit, прямой target `main`.

**Когда использовать:** сразу после context-limit разрыва родительской сессии — workaround на проде уже активен с `2026-05-23T09:49:15Z`, ближайший risk-tick `2026-05-24T06:00:00Z` (09:00 MSK). Hotfix должен быть merged + deployed до этого окна, иначе цикл «прод снова на голом workaround'е» затянется.

---

## 1. Context (essential — fresh session, всё ниже обязательно к прочтению/учёту)

### 1.1 Current repo state

- **Branch / HEAD:** `main` @ `2774890` — `docs(bug-log): BUG-028 prod workaround applied (PROMPTS_DIR env on tg_parser_bot)`.
- **Working tree:** clean.
- **Wave 1 step 3 closure:** DONE (GREEN verdict, commit `ed6d69e`); step 3.1 + follow-ups deployed (`b875faf` + `d143e5d`). Не трогать.

### 1.2 Prod state (на момент написания)

- **Workaround активен:** в `docker-compose.yml` на VPS у сервиса `tg_bot` добавлен env `PROMPTS_DIR=/app/prompts`. Контейнер `tg_parser_bot` перезапущен `2026-05-23T09:49:15Z`, healthy.
- **Compose backup на VPS:** `~/TG_parser/docker-compose.yml.bak-bug028-20260523-114830`. **НЕ трогать**, кроме сценария rollback.
- **Воспроизведение бага без workaround'а:** см. `BUG_LOG.md` § BUG-028 (evidence trace, git blame, severity High, Layer A/B/C/D рекомендации).

### 1.3 Обязательные чтения (в этом порядке)

1. `docs/notes/BUG_LOG.md` § **BUG-028** — целиком: evidence trace, root cause, рекомендованные Layer A/B/C/D.
2. `docs/notes/REVIEW_2026-05-21_WAVE1_STEP3_DONE.md` § **4a Open Items #5** — упоминание BUG-028 hotfix как следующего шага.
3. `tg_parser/services/scheduler_service.py` — целиком функцию `digest_task` (около строки 540–620), особенно строка 560 (call-site `PromptLoader(...)`).
4. `tg_parser/config/settings.py` строки 283–288 — определение `prompts_dir: Path | None = None`.
5. `tg_parser/processing/prompt_loader.py` — целиком `PromptLoader.__init__` и `.load(...)`; понять текущее поведение при `prompts_dir="None"` (literal string).
6. `tests/test_prompt_loader.py` — существующие fixture-паттерны, чтобы новый тест следовал стилю.
7. `tests/test_scheduler_service.py` — fixture-паттерны для `digest_task`-related тестов.
8. `docker-compose.yml` (workspace) — секции `tg_parser`, `tg_bot`, `mcp`: проверить какие env уже прокинуты в `tg_bot` (`PROMPTS_DIR=${PROMPTS_DIR:-/app/prompts}` уже должен быть).

---

## 2. Hotfix scope (locked — рамки зафиксированы родительской сессией)

**Branch:** `fix/bug-028-digest-cron-prompt-loader`.

### 2.1 Layer A — mandatory (~2 LOC), `tg_parser/services/scheduler_service.py:560`

```python
prompt_loader = PromptLoader(prompts_dir=str(settings.prompts_dir))
```

→ заменить на:

```python
prompt_loader = PromptLoader(
    prompts_dir=str(settings.prompts_dir) if settings.prompts_dir is not None else None,
)
```

Guard против `None → "None"` строкового приведения. Это minimum-fix, который сразу убирает root cause.

### 2.2 Layer C — recommended, `tg_parser/config/settings.py:287`

```python
prompts_dir: Path | None = None  # Кастомная директория промптов (default: ./prompts)
```

→ заменить на:

```python
prompts_dir: Path | None = Path("prompts")  # Кастомная директория промптов (по умолчанию ./prompts)
```

Делает default явным; убирает «волшебное» поведение, при котором pydantic-settings возвращает `None`, а downstream-код ожидает path. Justifies Layer A guard (теперь это **defense-in-depth**, а не обязательная заглушка) — guard всё равно оставляем.

### 2.3 Layer B — defense-in-depth, optional, `tg_parser/processing/prompt_loader.py` `__init__`

Внутри `PromptLoader.__init__` после нормализации `self.prompts_dir`:

```python
if str(self.prompts_dir) == "None":
    logger.warning(
        "PromptLoader received literal 'None' string; falling back to default",
        received=str(self.prompts_dir),
    )
    self.prompts_dir = Path("prompts")
```

Защита от любого будущего call-site'а, который случайно сделает `str(None)` перед передачей. Optional — если diff раздувается, можно отложить отдельным PR.

> **NB про путь файла:** в исходном плане родительской сессии указан `tg_parser/services/prompt_loader.py` — фактически файл лежит в `tg_parser/processing/prompt_loader.py` (см. `from tg_parser.processing.prompt_loader import PromptLoader` в `scheduler_service.py:551`). Используй корректный путь.

### 2.4 Layer D extension — `docker-compose.yml`

Сейчас `PROMPTS_DIR=${PROMPTS_DIR:-/app/prompts}` стоит только у `tg_bot` (после workaround'а). Добавить тот же env у сервисов **`tg_parser`** и **`mcp`** — consistency + future-proof (даже если кодовый guard Layer A/C закрывает баг, env-default страхует от любых будущих call-site'ов и от ситуации «rollback кода, env остаётся»).

---

## 3. Tests to add

### 3.1 `tests/test_scheduler_digest_prompt_loader.py` (новый файл)

`test_digest_task_with_default_settings_loads_yaml_prompt`:

- Fixture: `Settings()` где `prompts_dir is None` (или явно `prompts_dir=None` при создании).
- Замокать `DigestService`/LLM-фабрику так, чтобы `digest_task` дошёл до строки `PromptLoader(...)` без сетевых вызовов.
- Assert: `digest_task(...)` НЕ поднимает `PromptLoaderError`; `PromptLoader.load("digest"|"processing")` отдаёт реальный YAML.

### 3.2 `tests/test_prompt_loader.py`

`test_prompt_loader_rejects_literal_None_string`:

- `PromptLoader(prompts_dir="None").load("processing")` — поведение детерминированное: либо raise `PromptLoaderError` (если Layer B не включён в этом PR), либо fallback на `Path("prompts")` (если Layer B включён).
- Главное — **никогда** не должно молча резолвиться в путь `None/processing.yaml`.
- Тест адаптируется под выбранную стратегию Layer B (см. § 2.3).

Шаблоны fixture'ов — из существующих файлов (`tests/test_prompt_loader.py`, `tests/test_scheduler_service.py`).

---

## 4. Pre-flight gates (must pass before push)

```bash
git checkout main && git pull --ff-only origin main
git checkout -b fix/bug-028-digest-cron-prompt-loader

.venv/bin/pytest -q                            # baseline ≥ 2195, ожидаем 0 failed
TEST_POSTGRES=1 .venv/bin/pytest -q            # baseline ≥ 2499, ожидаем 0 failed

ruff format --check .
ruff check .
```

**Pre-existing UP038 в `scheduler_service.py`:** если ruff его всё ещё помечает — **НЕ чинить** в этом PR. Out of scope.

---

## 5. Commit shape

Subagent сам решает — один commit или два, по объёму diff'а.

**Вариант A (рекомендован, 2 commits):**

1. `fix(bug-028): guard PromptLoader against None prompts_dir + sensible default`
   - Layer A (guard в `scheduler_service.py:560`).
   - Layer C (default `Path("prompts")` в `settings.py`).
   - Layer B (если включён — fallback в `PromptLoader.__init__`).
   - Тесты § 3.1 + § 3.2.
2. `chore(compose): propagate PROMPTS_DIR env to tg_parser and mcp services`
   - Layer D extension в `docker-compose.yml`.

**Вариант B (один commit):** если общий diff < ~50 LOC — один commit `fix(bug-028): digest cron PromptLoader None regression (hotfix)` со всем сразу. Допустимо.

---

## 6. PR

- **Title:** `fix(bug-028): digest cron PromptLoader None-string regression (hotfix)`
- **Target:** `main`. **Merge:** squash (project convention).
- **Body должен содержать:**
  - Ссылку на `docs/notes/BUG_LOG.md` § BUG-028.
  - Ссылку на `docs/notes/REVIEW_2026-05-21_WAVE1_STEP3_DONE.md` § 4a Open Items #5.
  - Упоминание: «prod workaround активен с `2026-05-23T09:49:15Z` (env `PROMPTS_DIR` на `tg_bot`), снимается **после** деплоя этого PR».
  - Перечисление покрытия: Layer A (mandatory), Layer C (default), Layer B (optional / включён ли), Layer D (compose extension).
  - Test plan: оба новых теста + `.venv/bin/pytest -q` + `TEST_POSTGRES=1 .venv/bin/pytest -q` + `ruff format --check . && ruff check .`.
  - Risk: low — изменение узкое, default `Path("prompts")` совпадает с фактическим layout репо.
- **Labels (если используются):** `bug-fix`, `hotfix`, `bug-028`.

---

## 7. Post-merge ops (в свежей сессии или deferred)

1. **Deploy hotfix на прод:** `git pull` на VPS → rebuild → restart как минимум `tg_bot` (а лучше `tg_bot` + `tg_parser` + `mcp` ради Layer D).
2. **После того как hotfix live** — опционально удалить `~/TG_parser/docker-compose.yml.bak-bug028-20260523-114830` на VPS.
3. **Smoke:**
   - Env `PROMPTS_DIR` всё ещё set у `tg_bot` / `tg_parser` / `mcp` (Layer D fully applied).
   - `docker logs tg_parser_bot` — scheduler healthy, нет `PromptLoaderError`.
   - Ближайший cron-tick `2026-05-24T06:00:00Z` (09:00 MSK 24-05) — отработать без ошибок.
4. **Обновить `BUG_LOG.md` § BUG-028** → status `resolved`, прописать commit SHA(s) + PR URL.

---

## 8. What NOT to do

- **НЕ** удалять prod env-workaround `PROMPTS_DIR=/app/prompts` у `tg_bot` пока hotfix не merged + не задеплоен.
- **НЕ** трогать `docs/notes/WATCH_*` и `docs/notes/REVIEW_*` — финализированы как GREEN.
- **НЕ** трогать `uv.lock`, `pyproject.toml`, `requirements*.txt`.
- **НЕ** трогать `docs/methodology/**` (его в этом workspace нет намеренно).
- **НЕ** начинать Wave 1 step 4 planning в этой сессии.
- **НЕ** чинить pre-existing UP038 в `scheduler_service.py` (отдельный backlog).

---

## 9. Workflow внутри сессии

- Использовать **фоновые субагенты в этом же окне**, не открывать новые Cursor-окна.
- Если по ходу всплывают сторонние находки — заводить как new BUG-NN или ENH-NN в `BUG_LOG.md` отдельным мелким commit'ом (не смешивать с hotfix-commit'ом).
- В конце сессии — короткий return-summary родителю: ветка/commit SHA(s), PR URL, статус pytest/ruff, статус workaround'а, статус smoke.

---

## 10. Opener (cut-paste в новое окно)

```
Прочитай и выполни docs/notes/START_PROMPT_HOTFIX_BUG_028_2026-05-23.md полностью.
Это hotfix-сессия для BUG-028 (digest cron PromptLoader None regression).
Используй фоновые субагенты в этом же окне, не открывай новые окна.
```
