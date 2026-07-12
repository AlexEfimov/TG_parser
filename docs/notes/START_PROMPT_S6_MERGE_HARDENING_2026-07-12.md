# START PROMPT — S6 **implementation**: Merge-hardening топикизации (F-12 / F-13 / O-10)

**Дата:** 2026-07-12 · **Для:** implementation-сессии (отдельное окно).  
**Planning:** **не требуется** — нет read-only симуляции; сразу код + unit-тесты (PLAN §S6, WORKFLOW §3).

---

## Prerequisites

| Предпосылка | Статус |
|---|---|
| **S4 deployed** | PR #304 → `b1e4c7b`; threshold 0.32; 2807 links post-rebuild ([`S4_TOPIC_EMBEDDING_THRESHOLD_SIMULATION_2026-07-11.md`](S4_TOPIC_EMBEDDING_THRESHOLD_SIMULATION_2026-07-11.md)) |
| **S5** | in progress / merged — **soft sequencing only**; post-deploy validation S5 **не блокирует** S6 |
| **S0 baseline** | [`S0_BASELINE_PROCESSING_METRICS_2026-07-07.md`](S0_BASELINE_PROCESSING_METRICS_2026-07-07.md) |

**Нормативные документы (при расхождении — они первичны):**
- План: [`PLAN_REMEDIATION_SESSIONS_PROCESSING_ALGORITHMS_2026-07-07.md`](PLAN_REMEDIATION_SESSIONS_PROCESSING_ALGORITHMS_2026-07-07.md) §S6, §2 (граф: S6 после S4/S5, жёсткой зависимости нет).
- Отчёт: [`CODE_REVIEW_PROCESSING_ALGORITHMS_FABLE5_2026-07-07.md`](CODE_REVIEW_PROCESSING_ALGORITHMS_FABLE5_2026-07-07.md) — F-12/F-13 (§3 A6), O-10 (§5).
- Процесс: [`WORKFLOW_REMEDIATION_SESSIONS_AGREEMENTS_2026-07-07.md`](WORKFLOW_REMEDIATION_SESSIONS_AGREEMENTS_2026-07-07.md) §3 (отдельный PR), §5 (цикл), §7 (без контрактов/миграций).
- Проект: [`AGENTS.md`](../../AGENTS.md).

---

<role>
Ты — senior-инженер tg_parser. Закрываешь **O-10** в `_merge_topics`: детерминированная пост-обработка ответа merge-LLM без молчаливой потери тем и без отката целого чанка из-за одного кривого ID.

**Одна функция, один PR.** Fallback «вернуть `all_batch_topics` без слияния» при пустых группах / JSON-fail / truncation сохраняется без изменений. Промпт `merge.yaml` и архитектура §6.1 не трогаем.
</role>

<context>
## F-12 / F-13 — что ломается сейчас

Full-run топикизация: после `_generate_topics_batch` по чанку вызывается `_merge_topics` — LLM возвращает только `groups` (массивы ID), метаданные собираются программно.

**Size / risk (PLAN §S6):** S/M, low risk; fallbacks preserved.

### F-12 (Medium, качество) — произвольный primary + молчаливая потеря тем

```1546:1580:tg_parser/processing/topicization.py
        merged_topics = []
        for group in groups:
            member_ids = group if isinstance(group, list) else group.get("member_ids", [])
            valid_ids = [mid for mid in member_ids if 0 <= mid < len(all_batch_topics)]
            if not valid_ids:
                continue

            primary = all_batch_topics[valid_ids[0]]
            ...
        return merged_topics
```

1. **Primary = первый валидный член группы** (`valid_ids[0]`) — title/summary/scope самой информативной темы могут быть потеряны. O-10: primary = член с **максимумом якорей** (tie-break: первый по порядку в группе). **Minimal deliverable:** primary-by-max-anchors only; **не** union `scope_in`/keywords unless trivially adjacent to primary selection (otherwise defer).
2. **Темы, чьи ID LLM не вернул ни в одной группе, исчезают** — `merged_topics` содержит только упомянутые группы; orphan IDs не добавляются как синглтоны.

### F-13 (Low, качество) — строковый ID откатывает чанк

Тот же фильтр `0 <= mid < len(...)` на строковом ID (`"5"`) даёт `TypeError`. Обработчик выше перехватывает его как **clean resumable halt** — чанк не коммитится, merge-токены потеряны:

```1056:1078:tg_parser/processing/topicization.py
                except (TypeError, AttributeError) as e:
                    # BUG-077 (F2): ... STRING group ids that crash the group-id loop's
                    # ``0 <= mid`` comparison ...
                    ...
                    _record_chunk_failed("malformed_merge")
                    break
```

O-10: **`int(mid)`-коэрция** со **скипом** некорректных ID (вне диапазона, не парсятся) — один кривой ID не должен валить чанк. **Non-numeric strings** (`"a"`, `"b"`) are **not** coercible → skip member; empty group → orphan pass emits all batch topics as singletons; chunk **succeeds**, `malformed_merge` metric **unchanged**. Numeric strings (`"0"`, `"1"`) coerce and merge normally. После фикса E2E `test_malformed_merge_reply_is_clean_resumable_halt` (**ожидаемо**) меняет контракт: halt только при иных фатальных ошибках (billing/timeout), не на string IDs.

### Что не меняем

- Fallback при пустых `groups`, JSON parse fail, truncation → `return all_batch_topics` (`:1542–1544`, `:1513–1516`, `:1537`).
- BUG-077 halt path для billing/timeout merge (`:1035–1055`).
- F-17 truncation split (`_generate_topics_batch_after_truncation` shrink, `:1372–1408`) — out of scope, диспозиция S7.
</context>

---

## Target behavior (O-10)

| Case | Current | Target |
|---|---|---|
| Primary metadata | `valid_ids[0]` | member with **max `len(anchors)`**; tie → lowest index in group |
| Orphan topic IDs | dropped | emit as **singleton** groups (one topic each) |
| String ID `"5"` | TypeError → chunk halt | coerce `int(mid)`; skip if invalid |
| ID out of range | silently skipped | skip (unchanged) |
| All IDs in group invalid | group skipped | group skipped (unchanged) |
| Empty / failed LLM response | return all unmerged | unchanged |

---

## Files to change

| File | Change |
|---|---|
| `tg_parser/processing/topicization.py` | `_merge_topics` (`~1425–1580`): helper `_coerce_merge_member_id(mid) -> int \| None`; primary-by-max-anchors; orphan singleton pass; preserve combined_anchors merge |
| `tests/test_topicization.py` **or** new `tests/test_merge_topics_hardening.py` | unit tests on `_merge_topics` with mocked LLM (edge cases below) |
| `tests/test_bug077_tokenleak_hardening.py` | update `test_malformed_merge_reply_is_clean_resumable_halt` — string IDs **coerce**, chunk **succeeds** (or narrow test to truly unrecoverable malformed payload) |

**Не трогаем:** `prompts/merge.yaml`, settings, contracts, migrations.

---

## Test anchors

### Existing (regression — must stay green)

| File | Why |
|---|---|
| `tests/test_topicization.py` | core topicization |
| `tests/test_bug077_tokenleak_hardening.py` | merge halt / token leak (`:945–984` malformed merge E2E) |
| `tests/test_bug071_topicization_truncation.py` | merge truncation grow/fallback |
| `tests/test_bug076_checkpoint_topicization.py` | checkpoint not affected |
| `tests/test_bug074_topicization_json_repair.py` | `_merge_topics` JSON repair (`:148–168`) |
| `tests/test_rag_prompt_config.py` | `_merge_topics` prompt loader (`:1082–1143`) |

### New (red → green)

| Case | Assert |
|---|---|
| Primary selection | group `[0, 2]` where topic 2 has more anchors → metadata from topic 2 |
| Orphan singleton | LLM returns `{"groups": [[0, 1]]}` for 4 topics → output len **3** (merged + singletons for 2, 3) |
| String ID coercion | groups `[["0", "1"]]` → merges without exception |
| Non-numeric string IDs | groups `[["a", "b"]]` → all IDs skipped → orphan pass → **all** batch topics emitted (singletons); chunk succeeds; no `malformed_merge` halt |
| Duplicate ID across groups | ID in two groups → **first group wins**; later occurrence ignored; each ID exactly once |
| Out-of-range skip | groups `[[0, 99]]` → merge 0 only; 99 skipped; orphan pass adds unmentioned |
| All-invalid group | groups `[[99, 100]]` → group skipped; orphans preserved |
| Dict-shaped group | `{"member_ids": [0, 1]}` → same behavior as list group (regression) |

**Modes:** *default* (`pytest -q`) достаточен; *PR standard* (`TEST_POSTGRES=1`) перед merge.

---

## Acceptance criteria

- [ ] red→green on new unit cases **before** editing `_merge_topics` production logic (WORKFLOW §5)
- [ ] Primary = max-anchors member; combined_anchors still deduped by `source_ref`
- [ ] Every input topic ID appears exactly once in output (merged or singleton) — **no silent loss**
- [ ] Duplicate ID across groups: first group wins; later duplicates ignored
- [ ] `int(mid)` coercion for numeric strings; non-numeric / invalid IDs skipped per-member, not per-chunk
- [ ] `[["a","b"]]` BUG-077 contract: chunk succeeds, all topics preserved via orphan/singleton path, no `malformed_merge` halt
- [ ] Existing fallbacks (empty groups, JSON fail, truncation) unchanged
- [ ] BUG-077 billing/timeout merge halt path unchanged
- [ ] New unit tests cover all edge cases in PLAN §S6 test strategy
- [ ] `test_bug077` updated for new string-ID contract
- [ ] PR standard green; bugbot clean
- [ ] BUG_LOG: F-12, F-13 → closed (implementation deliverable)

---

## Deploy

- Branch: **`fix/S6-merge-hardening`**
- **Отдельный PR/деплой** (WORKFLOW §3); не батчить с S5/S7
- Rollback: revert PR (pure post-processing; no env knob)
- **No simulation gate** — unlike S4/S5

---

## Post-deploy validation (PLAN §S6)

Lightweight — нет 24–48h metric watch band:

- [ ] Full-run на **dev-канале**: логи без `failed merge chunk` на кейсах string IDs; `topicization_full_run_chunk_failed_total{reason="malformed_merge"}` не растёт на бывших string-ID кейсах
- [ ] Sanity: merged topic count ≥ pre-fix lower bound на том же канале (нет регресса потери тем)
- [ ] `tg_channel_processed_coverage_ratio` — не ниже S0 §2 обл.5 (T1 регресс-стоп, как в серии)

---

## Out of scope

- **F-17** — truncation split re-sends whole batch (`_generate_topics_batch_after_truncation`, `topicization.py:1372–1408`); Low, диспозиция S7
- **`prompts/merge.yaml`** — beyond минимально необходимого (не менять)
- **§6.1** — замена LLM-кластеризации целиком (XL, gated)
- S5 top-k assign, S7 RAG pooling, contracts, DB migrations

---

## One-liner for agent window

> S6 merge-hardening: F-12/F-13 in `_merge_topics` (`topicization.py:~1425–1580`). Primary = max-anchors; orphan IDs → singletons; `int(mid)` coerce + skip. No simulation. Unit tests + update BUG-077 string-ID test. Branch `fix/S6-merge-hardening`, separate PR.
