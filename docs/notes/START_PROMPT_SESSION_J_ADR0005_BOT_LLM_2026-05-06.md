# Session J — ADR 0005 mini-refactor + BOT_LLM_FALLBACK runbook (2026-05-06)

---

## Pre-flight status — READY (после 24h watch Session I)

**Создан:** 2026-05-06 ~19:40 UTC+4 (планирующая сессия после Session I deploy).

**Предусловия (оба должны быть закрыты до старта кодинга Session J):**

1. **Telegram smoke § 5.4 Session I — GREEN.** Выполняется вручную через
   реального бота сразу после Session I deploy:
   - `list_channels` → каналы отображаются с `channel_username`
   - «удали канал AgeManagment» → preview (НЕ «Channel not found»)
   - «пауза канала AgeManagment» → preview, «нет» → cancel
   - «темы канала AgeManagment» → «5 главных тем» → channel-scoped (BUG-011 не сломали)
   - «запусти пайплайн» (без channel_id) → бот просит уточнить (BUG-009 не сломали)

   Если что-то FAIL — Session J не стартует, делаем hot-fix или rollback Session I.

2. **24h watch + Final Gate-1 verification — GREEN.** Через ≥24h после Session I deploy
   (`2026-05-06 ~19:39 UTC+4`):

```bash
ssh -p 2296 user@212.72.189.15 'docker exec tg_parser_prometheus wget -qO- \
  "http://localhost:9090/api/v1/query?query=up{service=\"bot\"}" \
  | python3 -m json.tool | grep -A2 "value"'
# Expected: result vector live, value="1"

ssh -p 2296 user@212.72.189.15 \
  'echo "confirm_flow_mismatch: $(docker logs --since 24h tg_parser 2>&1 | grep -cE confirm_flow_mismatch)" && \
   echo "gemini_errors: $(docker logs --since 24h tg_parser 2>&1 | grep -cE "gemini_empty|gemini_no_candidates|gemini_blocked")"'
# Expected: confirm_flow_mismatch: 0 / gemini_errors: 0
```

| Check | Expected | Actual (заполнить при старте Session J) | Status |
|---|---|---|---|
| Telegram smoke § 5.4 (Session I closure proof) | все 5 шагов GREEN | TBD | TBD |
| Prometheus `up{service="bot"}` | `value: "1"` | TBD | TBD |
| `confirm_flow_mismatch` grep 24h | `0` | TBD | TBD |
| `gemini_empty\|..._blocked` grep 24h | `0` | TBD | TBD |

**Если любой check FAIL — остановить сессию, расследовать регрессию до начала кода.**
Не двигаться дальше пока все четыре строки таблицы не GREEN.

### Session J GH issue

Создать при старте сессии (готовая команда):

```bash
gh issue create \
  --title "feat(bot): bot-scope LLM config — ADR 0005 implementation (Session J)" \
  --body "$(cat <<'EOF'
ADR 0005 (docs/adr/0005-bot-llm-provider-flexibility.md) Variant A —
mini-refactor implementation.

Scope:
- Add "bot" to LLM_SCOPES in tg_parser/config/settings.py
- LLMConfigManager.set("bot", ...) validates provider == "gemini"
- LLMConfigManager.resolve("bot") returns Gemini static defaults
- GeminiAgent._resolved_model() reads llm_config.resolve("bot") on every _call_gemini
- TOOL_DECLARATIONS + MCP docstrings updated for set_llm_config + reset_llm_config
- docs/runbooks/BOT_LLM_FALLBACK.md created (manual procedure for Gemini outage)

Locked decisions:
- D-1: "bot" scope is immune to global override (Gemini-only constraint)
- D-2: "bot" scope is model-only — temperature/max_tokens overrides rejected

Tracker for Session J planning doc:
docs/notes/START_PROMPT_SESSION_J_ADR0005_BOT_LLM_2026-05-06.md
EOF
)"
```

### Session opener (вставить в новый чат)

> Стартую Session J — ADR 0005 mini-refactor + BOT_LLM_FALLBACK runbook.
> Сначала выполни pre-flight § 0:
> (1) проверь что Session I Telegram smoke § 5.4 был GREEN (если нет —
>     спроси меня перед продолжением);
> (2) запусти Final Gate-1 verification (3 SSH-команды), заполни таблицу
>     результатов в этом промпте — все 4 строки должны быть GREEN.
> Если всё GREEN — прочитай дальше:
> `docs/notes/START_PROMPT_SESSION_J_ADR0005_BOT_LLM_2026-05-06.md` целиком +
> `docs/adr/0005-bot-llm-provider-flexibility.md` + `tg_parser/config/settings.py`
> L837–1041 + `tg_parser/bot/agent.py` + `tg_parser/bot/main.py` L160–250.
> Затем исполни § 3 (commit 1: bot-scope config + agent; commit 2: runbook).
> Branch: `feat/session-j-adr0005-bot-llm-2026-05-06`.
> Locked decisions D-1 (global immunity) и D-2 (model-only) — не обсуждать,
> исполнять.

### Locked decisions (обязательные, не обсуждаемые в Session J)

ADR 0005 фиксирует **«Variant A mini-refactor»**, но конкретные подкассы
(как именно вести себя при global override; принимать ли temperature/
max_tokens в "bot" scope) — design call, который Session J planning
закрывает заранее.

- **D-1 (locked) — Global override immunity для "bot" scope.** Когда
  admin делает `set_llm_config(scope="global", provider="anthropic", ...)`,
  это **НЕ должно** влиять на bot. `resolve("bot")` всегда возвращает
  Gemini provider (либо static default `bot_gemini_model`, либо runtime
  override через `set_llm_config(scope="bot", ...)`). Обоснование: bot —
  Gemini-specific (FSM/tool-call контракт, `prompts/bot.yaml` Gemini-
  specific bullets), global переключение на anthropic должно ломать
  только pipeline стадии, не bot. Альтернативы (a) global → bot тоже
  → 404 от Google API при не-gemini provider; (b) `_validate_provider`
  raises на set('global', 'anthropic') если bot Gemini-only → admin
  не может global переключить — обе плохие. (iii) Immunity единственная
  разумная.
- **D-2 (locked) — "bot" scope is model-only.** `set_llm_config(scope="bot",
  provider="gemini", temperature=0.5)` или `max_tokens=16384` должно
  raise ValueError. Обоснование: ADR 0005 § «Что НЕ меняется этим ADR»
  фиксирует «`BOT_GEMINI_MAX_OUTPUT_TOKENS`, `BOT_GEMINI_THINKING_BUDGET`
  сохраняются как defaults», без runtime override. Принять
  temperature/max_tokens в `set("bot", ...)` без их использования в
  `_resolved_model()` — silent UX failure (admin думает что
  переключил, ничего не меняется). Лучше явный ValueError. Расширение
  до `_resolved_config()` с поддержкой `max_tokens` — opportunistic
  при следующем bot-touch.

---

## 0. Где Session J сидит в roadmap'е

```
Session H (BUG-011) ✅ PR #58 / 993451d
    ↓
Session I (BUG-010) ✅ PR #59 / 69243e6  ← deployed 2026-05-06
    ↓ 24h watch
Session J (ADR 0005) ← сейчас планируем
    ↓ deploy + 24h watch
Wave 1 step 1 DONE marker → REVIEW_2026-05-XX_WAVE1_STEP1_DONE.md
```

**Packaging (decision A3):** Session J — single PR, **2 atomic commits**:
- commit 1: `feat(bot): bot-scope LLM config + GeminiAgent.resolve("bot")`
- commit 2: `docs(runbooks): BOT_LLM_FALLBACK manual procedure`

---

## 1. Контекст и диагностика (обязательные чтения)

### 1.1 Что зафиксировано в ADR 0005

ADR принят **2026-05-02** (`docs/adr/0005-bot-llm-provider-flexibility.md`).
**Вариант A** (mini-refactor) — единственное решение к реализации.

Конкретные точки жёсткой привязки, которые нужно устранить:

| Место | Текущее (жёсткое) | Нужное (через config) |
|---|---|---|
| `LLM_SCOPES` в `settings.py:837` | `("global", ..., "resummarize")` — нет "bot" | Добавить `"bot"` |
| `LLMConfigManager.set()` в `settings.py:916` | `scope not in LLM_SCOPES` → ValueError (но "bot" нет) | Принять "bot", валидировать `provider == "gemini"` |
| `LLMConfigManager.resolve()` в `settings.py:938` | Для "bot": нет static defaults → упадёт на `getattr` → вернёт global | Добавить специальный путь для "bot" → возвращает `("gemini", key, bot_gemini_model)` |
| `GeminiAgent._call_gemini` в `agent.py:349` | `url = f"{GEMINI_API_BASE}/{self._model}:generateContent"` — `self._model` задаётся один раз при init | Читать модель динамически из `llm_config.resolve("bot")` на каждый вызов |
| `main.py:213` | `model=settings.bot_gemini_model` | `model=settings.bot_gemini_model` как fallback default при init (LLMConfigManager за резолв отвечает в runtime) |
| `TOOL_DECLARATIONS` `set_llm_config` scope description | Перечисляет scopes без "bot" | Добавить "bot" в список допустимых scopes |
| `mcp_server.py set_llm_config` docstring | Аналогично | Добавить "bot" |

### 1.2 Что НЕ меняется

- `GeminiAgent.__init__` параметры (`api_key`, `model`, `timeout`, ...) — не меняются
- `bot/main.py` передаёт `api_key` и начальную `model` — остаётся, `model` продолжает браться из `settings.bot_gemini_model` как fallback
- `self._model` в `GeminiAgent` остаётся (используется в metrics/logs как "init-time default")
- Существующие `BOT_GEMINI_MODEL`, `BOT_GEMINI_MAX_OUTPUT_TOKENS`, `BOT_GEMINI_THINKING_BUDGET` env-переменные — не трогать (defaults)
- `temperature` / `max_tokens` через `set_llm_config(scope="bot", ...)` — **отвергаются с ValueError per D-2**, не игнорируются (см. § 2.1 пункт A «Изменение 5»)
- 67 FSM-тестов в `test_bot_fsm.py` — не трогать (не меняем process_message loop). **Pre-test verification обязателен** (см. § 3.5 Step 4.0): тесты должны пройти ДО написания новых, иначе сломали fallback path в `_resolved_model()`
- `prompts/bot.yaml` — не трогать (Gemini-specific, ADR явно говорит что prompt stays)

### 1.3 Обязательные файлы для чтения перед кодингом

1. `docs/adr/0005-bot-llm-provider-flexibility.md` — полностью
2. `tg_parser/config/settings.py` L837–1041 — `LLM_SCOPES`, `LLMConfigManager` целиком
3. `tg_parser/bot/agent.py` — `GeminiAgent.__init__` (L123–138) + `_call_gemini` (L337–конец)
4. `tg_parser/bot/main.py` L160–250 — текущее создание `GeminiAgent`
5. `tg_parser/bot/tools.py` L423–464 — `set_llm_config` TOOL_DECLARATIONS entry
6. `tg_parser/mcp_server.py` L1618–1685 — `get_llm_config` + `set_llm_config` MCP functions
7. Существующие LLM config tests — `grep -rn "LLMConfigManager\|set_llm_config\|resolve_llm_config" tests/` — для паттерна

---

## 2. Архитектурный дизайн (locked)

### 2.1 Commit 1 — изменения кода (~70 LOC)

#### A. `tg_parser/config/settings.py`

**Изменение 1** — Добавить `"bot"` в `LLM_SCOPES`:
```python
LLM_SCOPES = ("global", "processing", "topicization", "rag", "digest", "resummarize", "bot")
```

**Изменение 2** — См. «Изменение 5» ниже (provider-validation объединён с D-2 guard в single branch для clarity).

**Изменение 3** — В `LLMConfigManager.resolve()` добавить специальный путь для "bot":
```python
def resolve(self, stage: str) -> tuple[str, str | None, str | None]:
    with self._lock:
        stage_ov = self._overrides.get(stage)
        global_ov = self._overrides.get("global")

    if stage_ov:
        provider = stage_ov["provider"]
        model = stage_ov.get("model")
    elif global_ov and stage != "bot":
        # ADR 0005: global override does NOT affect "bot" scope —
        # bot is Gemini-only; a global switch to "anthropic" must not
        # silently break the bot agent.
        provider = global_ov["provider"]
        model = global_ov.get("model")
    elif stage == "bot":
        # ADR 0005 Variant A: bot static defaults — always Gemini
        provider = "gemini"
        model = self._static.bot_gemini_model
    else:
        provider = (
            getattr(self._static, f"{stage}_llm_provider", None) or self._static.llm_provider
        )
        model = getattr(self._static, f"{stage}_llm_model", None) or self._static.llm_model

    api_key = self._api_key_for_provider(provider)
    return provider, api_key, model
```

Примечание D-1: "bot" scope намеренно **иммунен к global override** — если admin переключает глобально на "anthropic", бот должен продолжить работать на Gemini (Gemini-specific FSM/tool-call контракт). Изолируем "bot" от глобальных изменений.

**Изменение 4** — `get_all()` уже вызывает `_stage_config(stage) for stage in LLM_SCOPES if stage != "global"`, что после добавления "bot" автоматически включит "bot" в output. **Без изменений** (работает автоматически).

**Изменение 5 (D-2)** — В `LLMConfigManager.set()` добавить guard для bot-scope против `temperature`/`max_tokens`:

```python
def set(self, scope: str, provider: str, model=None, temperature=None, max_tokens=None) -> dict[str, Any]:
    if scope not in LLM_SCOPES:
        raise ValueError(...)

    # ADR 0005 D-2 (Session J): bot scope is model-only.
    if scope == "bot":
        if provider != "gemini":
            raise ValueError(
                "scope='bot' only supports provider='gemini' (ADR 0005 Variant A). "
                "Use set_llm_config(scope='bot', provider='gemini', model='gemini-2.5-pro') "
                "to switch Gemini model at runtime."
            )
        if temperature is not None or max_tokens is not None:
            raise ValueError(
                "scope='bot' is model-only (ADR 0005 D-2). "
                "temperature/max_tokens overrides are not supported — "
                "they are pinned to BOT_GEMINI_* env vars at startup. "
                "Pass only model= for runtime model switching."
            )
    self._validate_provider(provider)
    ...
```

Объединяет «Изменение 2» (provider-validation) и D-2 guard в один branch.

#### B. `tg_parser/bot/agent.py`

Добавить метод `_resolved_model()` и использовать его в `_call_gemini`:

```python
def _resolved_model(self) -> str:
    """Return current model from LLMConfigManager (BUG-safe fallback to init default).

    Called on every _call_gemini invocation so runtime set_llm_config(scope='bot')
    takes effect immediately without agent restart (ADR 0005 Session J).
    """
    try:
        from tg_parser.config import llm_config
        _, _, model = llm_config.resolve("bot")
        return model or self._model
    except Exception:
        return self._model
```

В `_call_gemini` (L349) заменить:
```python
# БЫЛО:
url = f"{GEMINI_API_BASE}/{self._model}:generateContent"

# СТАЛО:
url = f"{GEMINI_API_BASE}/{self._resolved_model()}:generateContent"
```

Метрики (`record_bot_gemini_empty_parts(..., model=self._model, ...)`) оставить на `self._model` — это "init-time default", нормально для observability.

#### C. `tg_parser/bot/tools.py` — TOOL_DECLARATIONS (две декларации — set + reset)

**C.1** — `set_llm_config` scope description (~L432–440):
```python
"description": (
    "Which config to change. One of: 'global', 'processing', "
    "'topicization', 'rag', 'digest', 'resummarize', 'bot'. "
    "'global' is the fallback used by every pipeline stage that has no "
    "explicit override (does NOT affect 'bot' scope — bot is Gemini-only). "
    "'bot' controls the Gemini model used by the Telegram bot agent at runtime "
    "(provider must be 'gemini'; ONLY model can be overridden — temperature/"
    "max_tokens for bot scope are not supported and will be rejected)."
),
```

**C.2** — `reset_llm_config` scope description (~L477–481):
```python
"description": (
    "Scope to reset. One of: 'global', 'processing', "
    "'topicization', 'rag', 'digest', 'resummarize', 'bot'. "
    "Omit to reset ALL overrides."
),
```

#### D. `tg_parser/mcp_server.py` — docstrings (set + reset)

**D.1** — `set_llm_config` docstring `scope` argument (~L1645):
```python
    scope: Which config to change: 'global', 'processing', 'topicization', 'rag',
           'digest', 'resummarize', or 'bot'. 'bot' controls the Gemini model for
           the Telegram bot agent (provider must be 'gemini'; temperature and
           max_tokens are not supported for bot scope per ADR 0005 D-2).
```

**D.2** — `reset_llm_config` docstring `scope` argument (~L1691):
```python
        scope: Scope to reset ('global', 'processing', 'topicization', 'rag',
               'digest', 'resummarize', or 'bot'). If omitted, resets ALL overrides.
```

### 2.2 Commit 2 — runbook (~1 страница, 0 code changes)

`docs/runbooks/BOT_LLM_FALLBACK.md` — manual procedure для оператора при Google Gemini outage.

Содержание:
1. **Когда использовать** — триггеры из ADR 0005 § Conditions (outage ≥30 min)
2. **Pre-flight** — что проверить перед переключением
3. **Процедура** — `set_llm_config(scope="bot", provider="gemini", model="gemini-2.0-flash")` (downgrade) или временная смена модели
4. **Rollback** — `reset_llm_config(scope="bot")`
5. **Post-procedure check** — smoke через Telegram
6. **Quarterly drill** — как тестировать runbook без реального outage
7. **Re-evaluation triggers** — ссылка на ADR 0005 § Условия пересмотра

---

## 3. Implementation plan

### 3.1 Ветка

```bash
git checkout main && git pull --ff-only origin main
git checkout -b feat/session-j-adr0005-bot-llm-2026-05-06
```

### 3.2 Step 1 — settings.py (20 мин)

1. **Изменение 1** — добавить `"bot"` в `LLM_SCOPES` (§ 2.1 A)
2. **Изменение 5 (D-1 + D-2)** — расширить `set()` с двумя guard'ами для bot scope: `provider != "gemini"` → ValueError; `temperature is not None or max_tokens is not None` → ValueError (§ 2.1 A)
3. **Изменение 3** — добавить "bot" static-defaults path в `resolve()` с D-1 immunity (§ 2.1 A)
4. **Изменение 4** — `get_all()` не трогать (автоматически подхватит "bot")

Re-grep после правок:
```
rg -n "LLM_SCOPES|def resolve|def set\b|def clear" tg_parser/config/settings.py
```

### 3.3 Step 2 — agent.py (10 мин)

1. Добавить `_resolved_model()` метод
2. Заменить `self._model` → `self._resolved_model()` в `_call_gemini` URL строке

### 3.4 Step 3 — TOOL_DECLARATIONS + MCP docstrings (10 мин)

**ВАЖНО — обновить ОБА tool description (set + reset), не только set:**

1. `bot/tools.py` L432–440 — `set_llm_config` scope description (см. § 2.1 C.1)
2. `bot/tools.py` L477–481 — `reset_llm_config` scope description (см. § 2.1 C.2)
3. `mcp_server.py` L1645 — `set_llm_config` docstring (см. § 2.1 D.1)
4. `mcp_server.py` L1691 — `reset_llm_config` docstring (см. § 2.1 D.2)

Re-grep после правок:
```
rg -n '"description"|scope:' tg_parser/bot/tools.py | grep -A1 "llm_config"
rg -n "scope:" tg_parser/mcp_server.py | grep -E "set_llm|reset_llm" -A2 -B2
```

### 3.5 Step 4 — Tests (35 мин)

Используется паттерн из `tests/test_llm_factory.py` — `_FakeSettings` dataclass + `_clear_caches` autouse fixture (calls `LLMConfigManager.reset()` в teardown) + `_patch_llm_config(fake)` helper. **Скопировать или импортировать паттерн** — не изобретать свой.

#### Step 4.0 — Pre-test verification (5 мин, ОБЯЗАТЕЛЬНО ДО написания новых тестов)

Цель — убедиться что fallback-path в `_resolved_model()` работает корректно для существующих 67 FSM-тестов, которые НЕ инициализируют `LLMConfigManager`:

```bash
pytest tests/test_bot_fsm.py -q
```

Expected: **67 passed, 0 failures**. Если упало — fallback path в `_resolved_model()` сломан, и нужно либо (a) добавить `conftest.py` initialization для `LLMConfigManager` в test_bot_fsm scope, либо (b) пересмотреть try/except в `_resolved_model()`. Не двигаться дальше до резолва.

#### Settings layer tests — `tests/test_settings_bot_scope.py` (новый, T-1..T-8 + T-11)

#### T-1 — `test_llm_scopes_includes_bot`
```python
from tg_parser.config.settings import LLM_SCOPES
assert "bot" in LLM_SCOPES
```

#### T-2 — `test_resolve_bot_returns_gemini_defaults`
```python
manager = LLMConfigManager(mock_settings(gemini_api_key="key", bot_gemini_model="gemini-2.5-flash"))
provider, api_key, model = manager.resolve("bot")
assert provider == "gemini"
assert model == "gemini-2.5-flash"
assert api_key == "key"
```

#### T-3 — `test_set_bot_scope_gemini_succeeds`
```python
manager.set("bot", "gemini", model="gemini-2.5-pro")
_, _, model = manager.resolve("bot")
assert model == "gemini-2.5-pro"
```

#### T-4 — `test_set_bot_scope_non_gemini_raises`
```python
with pytest.raises(ValueError, match="only supports provider='gemini'"):
    manager.set("bot", "anthropic", model="claude-sonnet-4")
```

#### T-5 — `test_global_override_does_not_affect_bot_scope`

Критический тест D-1 — глобальный override не ломает бот:
```python
manager.set("global", "anthropic", model="claude-sonnet-4")
provider, _, model = manager.resolve("bot")
assert provider == "gemini"   # bot иммунен к global switch
assert model == "gemini-2.5-flash"
```

#### T-6 — `test_resolve_bot_after_runtime_set`
```python
manager.set("bot", "gemini", model="gemini-2.5-pro")
provider, key, model = manager.resolve("bot")
assert model == "gemini-2.5-pro"
```

#### T-7 — `test_clear_bot_scope_reverts_to_default`
```python
manager.set("bot", "gemini", model="gemini-2.5-pro")
manager.clear("bot")
_, _, model = manager.resolve("bot")
assert model == "gemini-2.5-flash"  # reverts to static default
```

#### T-8 — `test_get_all_includes_bot_stage`
```python
config = manager.get_all()
assert "bot" in config["stages"]
assert config["stages"]["bot"]["provider"] == "gemini"
```

#### T-11 — `test_set_bot_scope_with_temperature_raises` (D-2 contract)

```python
with pytest.raises(ValueError, match="model-only"):
    manager.set("bot", "gemini", model="gemini-2.5-pro", temperature=0.5)

with pytest.raises(ValueError, match="model-only"):
    manager.set("bot", "gemini", model="gemini-2.5-pro", max_tokens=16384)
```

Покрывает D-2 — `set("bot", ..., temperature=...)` или `max_tokens=...` raises ValueError.

#### Agent layer tests — `tests/test_bot_agent_resolved_model.py` (новый, T-9..T-10)

Отдельный файл потому что эти тесты mock'ают глобальный singleton `tg_parser.config.llm_config`, что концептуально отличается от чистых settings-тестов выше.

#### T-9 — `test_gemini_agent_resolved_model_uses_llm_config`

```python
from unittest.mock import patch
from tg_parser.bot.agent import GeminiAgent
from tg_parser.config.settings import LLMConfigManager

# Setup: fresh LLMConfigManager with bot static default = "gemini-2.5-flash"
LLMConfigManager.reset()
fake = _FakeSettings(bot_gemini_model="gemini-2.5-flash", gemini_api_key="key")
mgr = LLMConfigManager(fake)
mgr.set("bot", "gemini", model="gemini-2.5-pro")  # runtime override

agent = GeminiAgent(api_key="key", model="gemini-2.5-flash")  # init-time default
with patch("tg_parser.config.llm_config", mgr):
    assert agent._resolved_model() == "gemini-2.5-pro"  # runtime wins
```

#### T-10 — `test_gemini_agent_resolved_model_falls_back_on_error`

```python
LLMConfigManager.reset()  # singleton not initialized
agent = GeminiAgent(api_key="key", model="gemini-2.5-flash")
# No patch — _resolved_model() lazy-imports llm_config, raises RuntimeError
# inside try/except, falls back to self._model
assert agent._resolved_model() == "gemini-2.5-flash"
```

### 3.6 Step 5 — BUG_LOG + CHANGELOG (5 мин)

- `CHANGELOG.md` → новая запись Session J
- Нет BUG-010 entry — это ADR feature, не bug fix

### 3.7 Step 6 — Runbook (15 мин)

Создать `docs/runbooks/BOT_LLM_FALLBACK.md` (commit 2).

---

## 4. Verification gates

### 4.1 Self-review checklist

```
[ ] "bot" присутствует в LLM_SCOPES
    rg -c '"bot"' tg_parser/config/settings.py  → ≥2 matches

[ ] set("bot", "anthropic", ...) raises ValueError (D-1 part 1)
    (covered by T-4)

[ ] set("bot", "gemini", temperature=0.5) raises ValueError (D-2)
    (covered by T-11)

[ ] resolve("bot") без overrides возвращает ("gemini", ..., bot_gemini_model)
    (covered by T-2)

[ ] global override НЕ влияет на "bot" scope (D-1 part 2)
    (covered by T-5 — КРИТИЧНО)

[ ] _resolved_model() в agent.py использует llm_config.resolve("bot")
    (covered by T-9)

[ ] _resolved_model() fallback на self._model при ошибке singleton
    (covered by T-10)

[ ] _call_gemini URL использует self._resolved_model() не self._model
    rg -n "_resolved_model|self\._model.*generateContent" tg_parser/bot/agent.py

[ ] BOTH set_llm_config + reset_llm_config TOOL_DECLARATIONS содержат "bot"
    rg -nB1 -A6 'name": "set_llm_config"|name": "reset_llm_config"' tg_parser/bot/tools.py

[ ] BOTH set_llm_config + reset_llm_config MCP docstrings содержат "bot"
    rg -n "scope:" tg_parser/mcp_server.py | grep -E "set_llm|reset_llm" -A2 -B2

[ ] docs/runbooks/BOT_LLM_FALLBACK.md существует
    ls docs/runbooks/BOT_LLM_FALLBACK.md

[ ] pytest tests/test_bot_fsm.py -q → 67 passed (pre-test verification)

[ ] pytest tests/test_settings_bot_scope.py -v  → 9 passed (T-1..T-8 + T-11)

[ ] pytest tests/test_bot_agent_resolved_model.py -v  → 2 passed (T-9..T-10)

[ ] pytest --tb=short -q  → baseline 2035 + 11 новых = 2046, 0 regressions

[ ] ruff check . && ruff format --check .  → 0 violations
```

### 4.2 CI (PR open)

Все 5 checks GREEN. PR description contains reference to GH issue (ADR 0005 implementation).

### 4.3 Deploy (§ 5.3)

```bash
ssh -p 2296 user@212.72.189.15 'cd ~/TG_parser && git pull --ff-only origin main \
  && docker compose build tg_parser \
  && docker compose up -d --no-deps --force-recreate tg_parser mcp'
```

Примечание: `mcp_server.py` docstring изменён, `bot/tools.py` TOOL_DECLARATIONS изменён, `agent.py` изменён → rebuild и restart `tg_parser` (бот) и `mcp` (MCP сервер) обязательны.

### 4.4 Smoke (post-deploy)

**ADR 0005 regression:**
1. `get_llm_config` (MCP или бот) → output включает "bot" stage с provider="gemini"
2. `set_llm_config(scope="bot", provider="gemini", model="gemini-2.5-flash")` → success
3. `set_llm_config(scope="bot", provider="anthropic", ...)` → error с readable сообщением
4. `reset_llm_config(scope="bot")` → reverts

**Bot regressions (не сломали):**
5. Любой Q&A запрос → бот отвечает нормально (GeminiAgent всё ещё работает)
6. BUG-011: «темы канала X» → «5 главных тем» → channel-scoped
7. BUG-010: «пауза канала X» → preview (не "not found")

---

## 5. PR / commit plan

**Branch:** `feat/session-j-adr0005-bot-llm-2026-05-06`

**Commit 1:**
```
feat(bot): bot-scope LLM config + GeminiAgent.resolve (ADR 0005 Session J)

Add "bot" to LLM_SCOPES; LLMConfigManager.resolve("bot") returns Gemini
defaults from static settings; set("bot", ...) validates provider=="gemini"
(Variant A constraint); global override exempt from "bot" scope (D-1
immunity); set("bot", ..., temperature=...) / max_tokens=... raises
ValueError per D-2 (model-only).
GeminiAgent._resolved_model() reads llm_config.resolve("bot") on every
_call_gemini invocation, enabling runtime model switch without restart;
falls back to init-time self._model on lazy-import errors.
TOOL_DECLARATIONS + MCP docstrings updated for BOTH set_llm_config and
reset_llm_config tools (scope list now includes "bot").
Tests: 9 settings (T-1..T-8 + T-11) + 2 agent (T-9..T-10).
Refs #<issue>.
```

**Commit 2:**
```
docs(runbooks): BOT_LLM_FALLBACK manual procedure (ADR 0005 Session J)

Add BOT_LLM_FALLBACK.md: step-by-step operator runbook for Google Gemini
outage — runtime model downgrade via set_llm_config(scope="bot"), rollback,
smoke check, quarterly drill procedure. Refs #<issue>.
```

**PR title:** `feat(bot): ADR 0005 mini-refactor — bot-scope LLM config + fallback runbook (Session J)`

---

## 6. Risks

**R-1** — `get_all()` итерируется по `LLM_SCOPES` (L1027). Добавление "bot" в скоуп автоматически включает "bot" в `_stage_config()` iteration. `_stage_config()` вызывает `resolve(stage)`, что корректно вернёт Gemini defaults. **Нет дополнительных изменений нужно.**

**R-2** — `LLMConfigManager` singleton. В тестах нужно вызывать `LLMConfigManager.reset()` в `teardown` чтобы не загрязнять другие тесты. Паттерн уже есть в существующих тестах — использовать его.

**R-3** — `_resolved_model()` в `GeminiAgent` делает lazy import `from tg_parser.config import llm_config`. Если LLMConfigManager не инициализирован (например, в юнит-тестах), это вызовет ошибку. **Mitigation:** try/except в `_resolved_model()` с fallback на `self._model` — уже заложено в дизайне.

**R-4** — Global override immunity (D-1). Если admin вызовет `set_llm_config(scope="global", provider="anthropic")`, а потом удивится что бот остался на Gemini — это ожидаемое поведение по ADR 0005. Важно описать это в TOOL_DECLARATIONS description.

**R-5** — `reset_llm_config(scope="bot")` — нужно убедиться что `clear("bot")` работает корректно (L1032–1040 в settings.py). Код: `self._overrides.pop("bot", None)` — корректен.

---

## 7. Out of scope

- Failover (Вариант B) — явно отклонён ADR 0005
- Полный refactor `BotAgent` port (Вариант C) — opportunistic, defer
- `maxOutputTokens` / `thinkingBudget` через "bot" scope — не в ADR 0005 scope, opportunistic
- A/B-тестирование провайдеров — требует experiment framework (+200–400 LOC), defer
- Обновление 67 FSM-тестов — не нужно (не меняем httpx mock контракт)

---

## 8. Appendix — Key code locations (актуальные на Session I HEAD `69243e6`)

| File | Location | What |
|---|---|---|
| `tg_parser/config/settings.py` | L837 | `LLM_SCOPES` tuple — добавить "bot" |
| `tg_parser/config/settings.py` | L916 | `set()` scope validation + bot-scope guard (D-1 + D-2) |
| `tg_parser/config/settings.py` | L938–961 | `resolve()` — добавить "bot" static-defaults path (D-1 immunity) |
| `tg_parser/config/settings.py` | L1027 | `get_all()` — автоматически подхватит "bot" через LLM_SCOPES |
| `tg_parser/bot/agent.py` | L123–138 | `GeminiAgent.__init__` (без изменений) |
| `tg_parser/bot/agent.py` | L337–L349+ | `_call_gemini` — `url = f".../{self._model}:..."` → `{self._resolved_model()}` |
| `tg_parser/bot/agent.py` | новый метод | `_resolved_model()` рядом с `__init__` или перед `_call_gemini` |
| `tg_parser/bot/main.py` | L211–217 | `GeminiAgent(...)` instantiation (без изменений) |
| `tg_parser/bot/tools.py` | L423–464 | `set_llm_config` TOOL_DECLARATIONS (C.1) |
| `tg_parser/bot/tools.py` | L466–490 | `reset_llm_config` TOOL_DECLARATIONS (C.2) |
| `tg_parser/mcp_server.py` | L1630–1685 | `set_llm_config` MCP function docstring (D.1) |
| `tg_parser/mcp_server.py` | L1684–1710 | `reset_llm_config` MCP function docstring (D.2) |
| `docs/runbooks/` | — | Создать `BOT_LLM_FALLBACK.md` |
| `docs/architecture.md` | check | ADR 0005 § «Отрицательные» требует backref. Pre-grep перед стартом |

Re-grep перед стартом (line numbers могли сдвинуться с момента написания этого промпта):
```bash
rg -n "LLM_SCOPES|def resolve|def set\b|def clear" tg_parser/config/settings.py
rg -n "self\._model|_call_gemini|def __init__" tg_parser/bot/agent.py
rg -n "bot_gemini_model|GeminiAgent\(" tg_parser/bot/main.py
rg -n 'name": "set_llm_config"|name": "reset_llm_config"' tg_parser/bot/tools.py
rg -n "def set_llm_config|def reset_llm_config" tg_parser/mcp_server.py

# Pre-flight check: does docs/architecture.md mention bot agent and link to ADR 0005?
rg -n "GeminiAgent|bot.*agent|0005" docs/architecture.md || echo "no references — opportunistic backref в Session J не требуется"
```

---

## Appendix B — История правок

| Дата | Изменение |
|---|---|
| 2026-05-06 ~19:40 UTC+4 | Первая версия. Создана в планирующей сессии после Session I deploy. Решения D-1 (global override immunity), `_resolved_model()` dynamic dispatch, runbook structure зафиксированы. |
| 2026-05-06 ~20:05 UTC+4 | Self-review iteration. Добавлены: (1) D-2 locked decision — "bot" scope is model-only (raise ValueError на temperature/max_tokens); (2) Locked decisions § перенесены наверх в § 0; (3) расширен scope: TOOL_DECLARATIONS + MCP docstrings обновляются для BOTH `set_llm_config` И `reset_llm_config` (G-1 fix); (4) Step 4.0 — pre-test verification `test_bot_fsm.py` ОБЯЗАТЕЛЕН до новых тестов; (5) тесты разделены на settings (T-1..T-8+T-11) и agent (T-9..T-10), отдельные файлы; (6) T-11 добавлен (D-2 contract); (7) concrete `gh issue create` команда; (8) `_FakeSettings` паттерн из `test_llm_factory.py` явно прописан как reference; (9) Pre-grep `docs/architecture.md` для ADR 0005 backref проверки. |
| 2026-05-06 ~20:14 UTC+4 | Pre-flight расширен: (1) Session I Telegram smoke § 5.4 явно перечислен как pre-requirement #1; (2) Final Gate-1 verification оформлен как таблица с placeholders «Actual / Status» (mirror Session I prompt § 0); (3) явная инструкция «остановить сессию при FAIL»; (4) Session opener обновлён — сначала pre-flight checks, потом чтение, потом код. |
