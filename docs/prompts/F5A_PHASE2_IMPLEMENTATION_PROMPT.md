# F5-A Phase 2 Implementation — Стартовый промпт

**Версия проекта:** 4.5.0+ (после мёрджа Phase 1 в `main` — PR #2, ветка `feat/f5a-phase1-hybrid-search`)
**Ветка:** `feat/f5a-phase2-relevance-tuning` (создать от обновлённого `main`)
**План реализации:** [`docs/plans/F5A_PHASE2_IMPLEMENTATION_PLAN.md`](../plans/F5A_PHASE2_IMPLEMENTATION_PLAN.md) — **читать первым**
**Design-doc:** [`docs/plans/F5A_PERSISTENT_KB_PLAN.md`](../plans/F5A_PERSISTENT_KB_PLAN.md) §4

---

## Цель

Добавить **relevance tuning** и **topic-weighted RAG context**:

1. Settings `fts_min_rank`, `rag_topic_quota`, `rag_search_overfetch_factor`.
2. `retrieval_service.answer(topic_quota=..., ...)` — квотирование с fallback при underflow.
3. `_build_context` — два структурных раздела `## Related Topics` и `## Source Messages`.
4. `prompts/rag.yaml` → v1.2.0 с описанием новой структуры контекста и правил цитирования.
5. MCP tools `search_knowledge_base` и `ask_question` принимают `mode` (semantic|keyword|hybrid).

---

## Коротко об архитектуре

```
question → answer(mode, topic_quota, limit)
           │
           ├── search(limit=limit * overfetch)        ← hybrid/keyword/semantic (Phase 1)
           │       └── keyword_search(min_rank=settings.fts_min_rank)
           │
           ├── _apply_type_quotas(raw, limit, topic_quota)
           │       ├── top-K topics (up to quota)
           │       ├── fill remainder with messages
           │       └── underflow fallback (backfill either direction)
           │
           └── _build_context(sources, char_limit)
                   ├── ## Related Topics     [T1] [T2] ...
                   └── ## Source Messages    [M1] [M2] ...
```

Новые pure-functions (юнит-тесты без БД):
- `_apply_type_quotas(results, limit, topic_quota) -> list[SearchResult]`
- Обновлённый `_build_context(results, char_limit) -> str`.

---

## Ключевые уточнения (после разведки)

- `retrieval_service.search()` **уже** принимает `mode` и `threshold` после Phase 1 (строка 49 в `tg_parser/services/retrieval_service.py`). `threshold` применяется только к semantic branch через `emb_repo.similarity_search`.
- `emb_repo.keyword_search(min_rank=0.0)` **уже** есть (Phase 1). Service сейчас **не пробрасывает** — добавляем pipeline в Commit 1.
- `answer()` (строка 239) сейчас: `search(limit=limit)` → `_build_context(results, char_limit)`. Phase 2 вставляет `_apply_type_quotas` между ними и overfetch.
- `_build_context` меняет формат — **ломает ~17 тестов** (~50 ассертов): 9 в `tests/test_f5a_topic_rag.py` + 8 в `tests/test_rag_prompt_config.py`. Обновление включено в scope Commit 2.
- MCP tools НЕ имеют `mode` — Phase 1 явно отложила. Добавляем в Commit 2.
- Bot/CLI `search`/`answer` — `mode` **не добавляем** в Phase 2 (вне scope, неявный дефолт `hybrid` достаточен).
- `_MCP_INSTRUCTIONS` (строки 44–77 `mcp_server.py`) сейчас говорит "search_knowledge_base for **semantic** search" — обновить блок Search & Q&A (строки 50–51) под hybrid + mode.
- **Visible behavior change для bot/CLI:** `answer()` теперь возвращает `AnswerResult.sources` уже после квотирования (≤ `limit`), не после raw search (`limit * overfetch`). Это **намеренно** — потребители видели именно `limit` записей и до Phase 2.

---

## Структура работы (2 коммита)

### Коммит 1 — Relevance tuning (min_score + quotas)

**Файлы:**
- [`tg_parser/config/settings.py`](../../tg_parser/config/settings.py) — `fts_min_rank`, `rag_topic_quota`, `rag_search_overfetch_factor`.
- `.env.example` — новые ENV-переменные.
- [`tg_parser/services/retrieval_service.py`](../../tg_parser/services/retrieval_service.py):
  - `search(fts_min_rank=None)` — новый опциональный параметр; проброс в `keyword_search.min_rank`.
  - `answer(topic_quota=None)` — новый опциональный параметр; overfetch + `_apply_type_quotas`.
  - Новая pure-function `_apply_type_quotas`.
- `tests/test_f5a_phase2_tuning.py` (new) — классы:
  - `TestApplyTypeQuotas` (~8 unit)
  - `TestAnswerQuotas` (~4 mocked)
  - `TestFtsMinRankPipeline` (~3 mocked)
  - `TestSettingsPhase2` (~3)

**Commit message:**
```
feat(f5a-phase2): add RAG type quotas and FTS min_rank pipeline
```

### Коммит 2 — Structured context + MCP mode passthrough

**Файлы:**
- [`tg_parser/services/retrieval_service.py`](../../tg_parser/services/retrieval_service.py) — переписать `_build_context` в двухсекционный формат.
- [`prompts/rag.yaml`](../../prompts/rag.yaml) → v1.2.0 с описанием `## Related Topics` / `## Source Messages` и правил цитирования `[T1]`/`[M1]` → ref.
- [`tg_parser/mcp_server.py`](../../tg_parser/mcp_server.py):
  - `search_knowledge_base(mode: str = "hybrid")` + validation + проброс.
  - `ask_question(mode: str = "hybrid")` + validation + проброс.
  - Обновить блок Search & Q&A в `_MCP_INSTRUCTIONS` (строки 50–51): "semantic search" → "hybrid search (mode=semantic|keyword|hybrid)".
- Обновление существующих тестов под новый формат:
  - [`tests/test_f5a_topic_rag.py`](../../tests/test_f5a_topic_rag.py) — строки ~540–617, ~1109–1140.
  - [`tests/test_rag_prompt_config.py`](../../tests/test_rag_prompt_config.py) — строки ~287–400.
- `tests/test_f5a_phase2_tuning.py` — дополнить классами:
  - `TestStructuredContext` (~8)
  - `TestMcpModePassthrough` (~5)
  - `TestRagPromptV12` (~2)
- Документация:
  - [`docs/USER_GUIDE.md`](../../docs/USER_GUIDE.md) — новая подсекция "RAG context structure & type quotas".
  - [`docs/MCP_AGENT_GUIDE.md`](../../docs/MCP_AGENT_GUIDE.md) — `mode` в MCP-tools.
  - [`ENV_VARIABLES_GUIDE.md`](../../ENV_VARIABLES_GUIDE.md) — `FTS_MIN_RANK`, `RAG_TOPIC_QUOTA`, `RAG_SEARCH_OVERFETCH_FACTOR`.
  - [`docs/plans/F5A_PERSISTENT_KB_PLAN.md`](../plans/F5A_PERSISTENT_KB_PLAN.md) — Phase 2 DONE.
  - [`docs/LLM_PROMPTS.md`](../../docs/LLM_PROMPTS.md) — упоминание версии `rag.yaml` 1.2.0.

**Commit message:**
```
feat(f5a-phase2): structured topic-weighted RAG context + MCP mode passthrough
```

---

## Settings шпаргалка

```python
# В tg_parser/config/settings.py, секция после fts_languages (~488)

fts_min_rank: float = Field(
    default=0.0,
    description="Default ts_rank_cd cutoff for keyword search (0.0 = no cutoff)",
    ge=0.0,
)
rag_topic_quota: int = Field(
    default=2,
    description="Number of topic cards reserved in answer() context before filling with messages",
    ge=0,
    le=20,
)
rag_search_overfetch_factor: int = Field(
    default=2,
    description="answer() fetches limit * factor before applying quotas for headroom",
    ge=1,
    le=10,
)
```

---

## `_apply_type_quotas` спецификация

```python
def _apply_type_quotas(
    results: list[SearchResult],
    limit: int,
    topic_quota: int,
) -> list[SearchResult]:
    """
    Rules:
    - Take up to `topic_quota` topics (score order preserved from search()).
    - Fill remaining slots (limit - len(picked_topics)) with messages.
    - Underflow: if not enough messages, backfill shortfall with extra topics.
    - Output order: ALL topics first, then ALL messages.
    - Never exceeds `limit`.
    - Returns [] if results empty.
    """
```

Ключевые кейсы для тестов:
- `test_empty_results_returns_empty`
- `test_topic_underflow_backfills_with_messages` (было 1 тема, нужно 2; берём 1 тему + заполняем сообщениями)
- `test_message_underflow_backfills_with_topics` (было 0 сообщений, квота топиков 2, limit=5; берём до 5 топиков если есть)
- `test_topic_quota_zero_returns_only_messages` (`topic_quota=0` — только сообщения)
- `test_order_within_type_preserved` (score-order внутри каждой секции)

---

## Обновлённый `_build_context` — формат

**До (Phase 1):**
```
[1] channel: ch1 | ref: tg:ch1:post:1 | score: 0.89
Title: ...
Text: ...
---
[2] [TOPIC] channels: ch1, ch2 | ref: topic:t1 | score: 0.85
Title: ...
Summary: ...
```

**После (Phase 2):**
```
## Related Topics

[T1] ref: topic:t1 | channels: ch1, ch2 | score: 0.850
Title: Topic Title
Summary: Topic summary...
Scope: anchor_a, anchor_b
Tags: tag1, tag2

---

[T2] ref: topic:t2 | channels: ch1 | score: 0.720
Title: ...
Summary: ...

## Source Messages

[M1] channel: ch1 | ref: tg:ch1:post:1 | score: 0.890
Title: Summary or first 80 chars
Text: Full text truncated to char_limit...
Topics: topic1, topic2

---

[M2] channel: ch2 | ref: tg:ch2:post:5 | score: 0.820
Title: ...
Text: ...
```

**Правила:**
- Пустые секции **не выводятся** (no trailing `## Related Topics\n\n` без контента).
- Между блоками одной секции — `\n\n---\n\n`.
- Между секциями — `\n\n`.
- Score отображается с 3 знаками (`{r.score:.3f}`).
- Сортировка внутри секции **не меняется** — уже score-desc из `search()`.

---

## `prompts/rag.yaml` v1.2.0 — патч

Обновить `metadata.version` до `"1.2.0"` и `system.prompt` (полный draft в плане §2.2). Ключевые добавления:

1. Описание двух секций `## Related Topics` / `## Source Messages`.
2. Правила цитирования: `[T1]`/`[M1]` — только визуальные метки, цитировать через `ref` value.
3. Guidance: topics для thematic framing, messages для factual claims.

Остальные блоки (`user.template`, `no_results`, `model`) — без изменений.

---

## MCP tools `mode` — сигнатура

```python
from typing import get_args
from tg_parser.services.retrieval_service import SearchMode

_VALID_MODES = set(get_args(SearchMode))  # ("semantic", "keyword", "hybrid")


@mcp.tool()
async def search_knowledge_base(
    query: str,
    channel_id: str | None = None,
    limit: int = 10,
    mode: str = "hybrid",  # NEW
    ctx: Context | None = None,
) -> list[SearchResultItem]:
    """...
    Args:
        ...
        mode: Retrieval strategy — 'semantic' (pgvector cosine), 'keyword' (FTS), or 'hybrid' (RRF fusion, default).
    """
    if mode not in _VALID_MODES:
        raise ValueError(f"invalid mode: {mode!r}; expected one of {sorted(_VALID_MODES)}")
    # ... проброс в search(mode=mode)
```

`SearchMode` импортируем из `retrieval_service` — single source of truth, нет дублирования литералов. Аналогично для `ask_question`. Затем обновить блок Search & Q&A в `_MCP_INSTRUCTIONS` (`mcp_server.py` строки 50–51).

---

## Тесты

Новый файл `tests/test_f5a_phase2_tuning.py` (шаблон — `tests/test_f5a_hybrid_search.py`):

| Класс | Кейсов | Requires pg? |
|---|---|---|
| `TestApplyTypeQuotas` | ~8 | no |
| `TestAnswerQuotas` | ~5 | no (mocked search) |
| `TestFtsMinRankPipeline` | ~3 | no (mocked repo) |
| `TestSettingsPhase2` | ~3 | no |
| `TestStructuredContext` | ~8 | no |
| `TestMcpModePassthrough` | ~5 | no (mocked search/answer) |
| `TestRagPromptV12` | ~2 | no |

**Плюс обновление существующих:**
- `tests/test_f5a_topic_rag.py` — 9 методов с `_build_context` assertions (строки 540, 556, 570, 593, 605, 611, 1108, 1121, 1134).
- `tests/test_rag_prompt_config.py` — 8 методов (строки 286, 305, 320, 338, 342, 356, 377, 1401).

**Запуск:**
```bash
# Phase 2 unit + integration
.venv/bin/pytest tests/test_f5a_phase2_tuning.py -x -q

# _build_context regression (после обновления ассертов)
.venv/bin/pytest tests/test_f5a_topic_rag.py tests/test_rag_prompt_config.py -x -q

# Полный regression
TEST_POSTGRES=1 .venv/bin/pytest tests/ -x -q
```

**Ожидаемо:** 1384 → ~1410 тестов.

---

## Критерии готовности

1. `settings.fts_min_rank`, `rag_topic_quota`, `rag_search_overfetch_factor` читаются из env; валидаторы отвергают негативные/out-of-range.
2. `search(fts_min_rank=...)` пробрасывает в `keyword_search.min_rank` в keyword/hybrid путях; semantic ветка не затронута.
3. `answer(topic_quota=...)` вызывает `search(limit=limit * overfetch)` и применяет `_apply_type_quotas`.
4. `_apply_type_quotas` — pure function; ≥8 unit-тестов включая underflow fallback для обоих направлений.
5. `_build_context` выдаёт `## Related Topics` + `## Source Messages` с префиксами `[T1]`/`[M1]`; пустые секции опущены.
6. `prompts/rag.yaml` — версия `1.2.0`, system prompt описывает две секции и правила цитирования через `ref`.
7. MCP `search_knowledge_base` и `ask_question` принимают `mode: str = "hybrid"`; невалидный → `ValueError`; проброс в сервис.
8. Существующие `_build_context` тесты (`test_f5a_topic_rag.py`, `test_rag_prompt_config.py`) обновлены под новый формат.
9. Новый файл `tests/test_f5a_phase2_tuning.py` ~25–30 тестов; все проходят.
10. Полный regression `TEST_POSTGRES=1 pytest tests/ -x -q` — не менее 1410 passed.
11. Документация: USER_GUIDE (подсекция), MCP_AGENT_GUIDE (mode), ENV_VARIABLES_GUIDE (3 новых env), LLM_PROMPTS (версия), F5A_PERSISTENT_KB_PLAN (Phase 2 DONE).
12. Два коммита с указанными messages.

---

## Что НЕ входит в scope

- Deduplication (content hash, near-duplicate) — Phase 3.
- Cross-encoder / LLM re-ranking — вне F5-A.
- Linear fusion как альтернатива RRF.
- `mode` в bot tools / CLI (`tg_parser/bot/tools.py`, `tg_parser/cli/app.py`).
- GIN по `topic_cards.channel_ids` — Phase 3 candidate.
- Автодетекция языка запроса для FTS.
- Adaptive quotas (динамическое подстраивание под распределение типов в корпусе).
- Изменение формы `SearchResultItem` в API/MCP (preview chars и т.п.).

---

## Рекомендации исполнения

1. **Plan mode** первым — сверка с актуальным `main` после мёрджа Phase 1. Проверить номера строк `retrieval_service.py`, `mcp_server.py`, `settings.py`.
2. **TDD для `_apply_type_quotas`** — pure function, пишем 8 тестов сразу, затем имплементация.
3. **Порядок Commit 1:** settings → `_apply_type_quotas` → `fts_min_rank` pipeline → `answer` wiring. Каждый шаг gated тестами.
4. **Для `_build_context` нового формата** — сначала написать `TestStructuredContext`, потом переписать функцию, **затем** исправить старые ассерты в `test_f5a_topic_rag.py` / `test_rag_prompt_config.py`. Если сначала менять функцию — тесты сломаются массово и это затруднит review.
5. **MCP тесты** — моделировать по образцу `tests/test_mcp_server.py` (patches на `retrieval_service.search`/`answer`).
6. **Prompt reload** — после правки `rag.yaml` убедиться что hot-reload работает (`PromptLoader` уже имеет этот механизм).
7. **Backward compat в ответах** — `AnswerResult.sources` и `SearchResult` структура **не меняется**. Меняется только внутренний формат `_build_context` строки, идущей в LLM.
8. **Score precision bump** с `.2f` → `.3f` — мелкое изменение UX, может сломать хрупкие regex-тесты. Отдельно проверить.
