# SESSION — F5-C minimal refusal-fallback experiment (C)

**UTC:** 2026-08-05T21:43Z–21:46Z · **Тип:** ops one-shot (без записи knobs в prod `.env`, без re-create)  
**План:** минимальный вариант — `docker exec -e` + точечный SQL у одной темы.

## LOCK

| # | Решение |
|---|---|
| D-1 | да |
| D-2 | `rag` → `openai` / `gpt-4.1` только через `-e` |
| D-3 | (a) SQL точечный |
| D-4 | нет (разовый CLI) |
| D-5 / D-6 / D-7 | отложены до owner GO после C |

## Pre-check resolve (`-e`)

```
stage= 'rag'  primary= anthropic claude-sonnet-4-6  fallback= openai gpt-4.1
ACCEPT_OK
```

UTC snapshot start: `2026-08-05T22:43:45Z` (local wall; container timestamps below in Z).

## Pre-UPDATE `metadata_json` (rollback snapshot)

Topic: `topic:tg:labdiagnostica_logical:comment:8992`

```json
{"algorithm":"llm_clustering","input_scope":{"channel_id":"labdiagnostica_logical","mode":"full_history"},"model_id":"claude-sonnet-4-20250514","parameters":{"max_anchors":3,"min_cluster_anchors":2,"min_cluster_score":0.6,"min_singleton_length":300,"min_singleton_score":0.75,"temperature":0.0},"pipeline_version":"v1.0","prompt_id":"sha256:14e4721863b067a1","prompt_name":"topicization_v1","resummarize_llm":"openai/gpt-4o-mini","resummarize_prompt_version":"1.0.0","resummarize_refusal_at":"2026-07-25T14:14:56.774932+00:00","resummarize_refusal_count":5,"resummarize_refusal_llm":"anthropic/claude-sonnet-4-6","resummarize_refusal_until":"2026-08-10T14:14:56.774932+00:00","resummarize_run_at":"2026-06-20T06:03:09.393179+00:00","resummarize_version_no":2,"topicization_run_id":"run_20260419_092042"}
```

## SQL

Сняты только `resummarize_refusal_until` и `resummarize_refusal_count`. Provenance `_at` / `_llm` оставлены до commit-пути.

## CLI

```bash
docker exec \
  -e RESUMMARIZE_REFUSAL_FALLBACK_STAGE=rag \
  -e RAG_LLM_PROVIDER=openai \
  -e RAG_LLM_MODEL=gpt-4.1 \
  tg_parser tg-parser topic resummarize \
  topic:tg:labdiagnostica_logical:comment:8992
```

**Stdout (дословно по статусу):**

- `f5c_resummarize_fallback_ok` `stage=rag` `provider=openai` `model=gpt-4.1` @ `2026-08-05T21:46:19.668682Z`
- `status: ok`
- `new_version: 3`
- `tokens: 2922`
- `duration: ~7.38s`
- `EXIT=0`

## Post-verify

| Проверка | Результат |
|---|---|
| `f5c_resummarize_fallback_ok` openai/gpt-4.1 | да (CLI stdout) |
| `topic_card_versions` | snapshot v2 записан @ `2026-08-05 21:46:12+00` (предыдущий summary); карточка теперь v3 |
| `metadata.resummarize_llm` | `openai/gpt-4.1` |
| маркеры `resummarize_refusal_*` | отсутствуют (commit вычистил) |
| `last_summarized_at` | `2026-08-05 21:46:19.849297+00` |
| `new_items_since_last_summary` | `0` → тема вышла из age-кандидатов минимум на `MAX_AGE_DAYS=21` |
| prod `.env` | `RESUMMARIZE_REFUSAL_FALLBACK_STAGE` count=0; `RAG_LLM_*` count=0 (не трогали) |

## Rollback knobs

No-op: в `.env` ничего не писали. Scheduler не re-create.

## Вердикт

**C успешен:** Anthropic refusal обойдён fallback'ом `openai/gpt-4.1`; poison-pill тема вылечена разовым CLI.

## Следующее (ждёт owner GO)

- D-4: постоянный fallback в `.env` + re-create?
- Шаг A: гигиена T7-gate (+ D-5/D-6)
- Шаг B: не нужен по критерию §5.1 (тема вылечена)
- +24h smoke (опционально): `refusal_cooldown` по `labdiagnostica_logical` за 24h → 0
