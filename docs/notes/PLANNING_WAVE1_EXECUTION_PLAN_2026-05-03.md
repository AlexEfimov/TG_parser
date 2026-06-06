# Wave 1 Execution Plan — operational decisions для шагов 1–4

**Назначение:** operational-companion к
[`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 5.1](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md)
(Wave 1 sequence). Strategy doc отвечает на «что и для кого делаем»;
этот документ отвечает на «как именно packaging'уем sessions, какой
quality bar, как фиксируем DONE marker, где собираем signals для
Decision Point».

**Дата создания:** 2026-05-03 ~14:30 UTC+4 (после планирующей сессии
в окне ожидания Session H, parent transcript «Pre-Session-H planning
+ audience-driven strategy review + parity tracker»).

**Status:** активный operational план. Действует до закрытия Wave 1
(~3–4 рабочих недели от Session H start, с учётом 24h watch'ей между
deploy'ями).

**Closed:** 2026-06-03 (Wave 1 aggregate closure — see [REVIEW_2026-06-03_WAVE1_DONE.md](REVIEW_2026-06-03_WAVE1_DONE.md)).

**Когда использовать:**

- Перед стартом каждой следующей session (I / J / planning F4-B Core
  / F4-B sprint / planning Surface Parity / Surface Parity sprint /
  Shareable Digest) — sanity-check что packaging + quality bar
  выполнены.
- При закрытии каждого Wave 1 step — produce DONE marker по template
  § 4 ниже.
- При появлении любого signal'а к Decision Point — записать по
  template § 5.

**Что НЕ делает этот документ:**

- НЕ замещает strategy doc — там высокоуровневая логика и audience
  фильтр.
- НЕ диктует код Sessions H/I/J — это в их собственных prompt'ах.
- НЕ заменяет [`PLANNING_F4B_WORKSPACES_PREP.md`](PLANNING_F4B_WORKSPACES_PREP.md)
  для F4-B Core scope — Q1–Q8 решения там.

---

## 1. Wave 1 step 1 — Bot UX hardening (extended scope)

### 1.1 Sequence + packaging (decision A3)

Зафиксировано 2026-05-03: **гибрид packaging** — bug-fix отдельным
PR, ADR adoption + runbook одним PR.

```
Session H (BUG-011 read-context)         — single PR ~250 LOC + ~14 tests
    ↓ deploy + 24h watch
Session I (BUG-010 username alias)       — single PR ~80 LOC + ~4 tests
    ↓ deploy + 24h watch
Session J — single PR with 2 atomic commits:
    commit 1: feat(bot): bot-scope LLM config + GeminiAgent.resolve("bot")
              (ADR 0005 mini-refactor — ~50–80 LOC + 5–8 tests)
    commit 2: docs(runbooks): BOT_LLM_FALLBACK manual procedure
              (~50 LOC + 1 страница, no deploy implications)
    ↓ deploy + 24h watch
Wave 1 step 1 DONE marker
    → REVIEW_2026-05-XX_WAVE1_STEP1_DONE.md (см. § 4)
```

**Обоснование A3:**

- Bug-fix (BUG-010) — user-facing UX issue, заслуживает own deploy +
  watch для атомарного rollback.
- ADR 0005 mini-refactor + runbook — natural pair (оба про ADR 0005
  implementation), но runbook docs-only → в одном PR с 2 atomic
  commits review-friendly.
- Total = 3 deploy-cycle = ~3-4 рабочих дня с 24h watch между.

### 1.2 Quality bar для каждого session (mirror Session G pattern)

После каждого deploy — 24h watch со SSH-проверкой трёх Prometheus / log
сигналов:

```bash
ssh prod 'docker exec tg_parser_prometheus wget -qO- \
  "http://localhost:9090/api/v1/query?query=up{service=\"bot\"}" \
  | python3 -m json.tool'
# Expected: result vector live, value=1

ssh prod 'docker logs --since 24h tg_parser_bot 2>&1 \
  | grep -cE "confirm_flow_mismatch"'
# Expected: 0 (Session G guard hold)

ssh prod 'docker logs --since 24h tg_parser_bot 2>&1 \
  | grep -cE "gemini_empty|gemini_no_candidates|gemini_blocked"'
# Expected: 0 (Session E hold)
```

Дополнительные session-specific проверки — в каждом session prompt
(§ 5.4 verify-after-deploy блок).

### 1.3 GH issues per session

| Session | GH issue | Notes |
|---|---|---|
| Session H | TBD при старте сессии (analogous к Session G #49) | TD-bot-read-context-preservation tracker |
| Session I | существующий **#50** (filed Session F closure backlog) | TD-bot-source-username-alias |
| Session J | TBD при старте — file new (ADR 0005 implementation tracker) | Reference ADR 0005 в issue body |

---

## 2. Wave 1 step 2 — F4-B Core Workspaces

### 2.1 Planning sub-session (~0.3 сессии)

**Когда:** сразу после Wave 1 step 1 DONE marker.

**Чат:** fresh (не продолжение Session H/I/J — F4-B это новый контекст,
не bug-fix).

**Что делать:**

1. Прочитать [`PLANNING_F4B_WORKSPACES_PREP.md`](PLANNING_F4B_WORKSPACES_PREP.md)
   целиком, особое внимание на § 4 Q2 + Q4 (refined 2026-05-03 deep-dive).
2. Confirm: Q1 = B (opt-in), Q3 = skip-bot-MVP, Q5 = A (M2M shared),
   Q6 = A (mirror F4-A), Q7 = C (skip F11), Q8 = C (skip F6) —
   preliminary recs из strategy § 8.
3. Apply: Q2 + Q4 detailed semantics (3 edge cases + atomicity decision)
   как **locked** для F4-B Core MVP.
4. Produce `START_PROMPT_SPRINT_F4B_CORE_<date>.md` по образцу
   [`START_PROMPT_SPRINT_F11.md`](START_PROMPT_SPRINT_F11.md) (~700 строк,
   5 фаз: schema → service → MCP/CLI → scoping → tests).

### 2.2 Sprint (~2.5 сессии)

Single PR с 5 atomic commits (mirror Session F pattern, не F11
multi-PR). Pre-flight gate-1 = Wave 1 step 1 DONE marker valid + Bot
24h watch GREEN over 72h cumulative.

**Quality bar:** дополнительно к § 1.2 — `tests/test_f4b_*.py` все
PASS в default mode + Postgres mode; baseline +новые тесты ~25-30; 0
regressions по существующим F4-A тестам.

### 2.3 DONE marker

Аналогично § 4: `REVIEW_2026-05-XX_WAVE1_STEP2_DONE.md`. Дополнительно:
**refresh** `PARITY_DECISION_TRACKING.md` с observations, появившимися
во время F4-B Core (например «watchlist subscription наследует/не
наследует workspace_id» — это будет input для step 3).

---

## 3. Wave 1 step 3 + step 4 (skeleton — детали по факту)

### 3.1 Step 3 — Surface Parity

- Planning (~0.3 сессии): re-read `PARITY_DECISION_TRACKING.md` —
  pre-references P-1..P-5 + observations from steps 1, 2. Выбрать
  пакет (текущая гипотеза — P-1 watchlist API parity или P-2 digest
  API parity, актуальность подтвердится по signals).
- Sprint (~1-2 сессии): single PR pattern.
- DONE marker: `REVIEW_2026-05-XX_WAVE1_STEP3_DONE.md`.

### 3.2 Step 4 — Shareable Digest via TG-channel

- Light extension F6 (~0.3 сессии): `subscribe_digest(...,
  publish_to_channel="@my_curated_digest")`.
- Может быть совмещён со step 3 если scope позволит — оценить на
  step 3 planning.

---

## 4. Wave 1 step DONE marker template (decision C1)

Каждый step (1, 2, 3, 4) при закрытии produce документ
`REVIEW_2026-05-XX_WAVE1_STEP<N>_DONE.md` со следующей структурой
(~150–200 строк):

```markdown
# Wave 1 Step <N> — DONE marker

**Дата:** YYYY-MM-DD
**Закрывает:** Wave 1 step <N> per
[`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 5.1](...)

## 1. Что закрыто

| Session | PR | Squash SHA | Deployed | 24h watch verdict |
|---|---|---|---|---|
| H | #XX | a1b2c3d | YYYY-MM-DD HH:MM UTC | GREEN / yellow / FAIL |
| I | #XX | ... | ... | ... |
| J | #XX | ... | ... | ... |

## 2. Monitoring-only / unresolved

| Item | Reason | Re-evaluate trigger |
|---|---|---|
| BUG-012 | Cosmetic, mitigated в prompt v1.5.0 | New sighting in production |

## 3. Accumulated observations

### 3.1 Parity tracker entries
*Cross-link на PARITY_DECISION_TRACKING.md observations добавленных
в этот step.*

### 3.2 New FUTURE_FEATURES items (если есть)

### 3.3 Signals collected (для Decision Point — § 5 этого документа)

## 4. Pre-next-step readiness checklist

- [ ] All deploys 24h watch GREEN
- [ ] 0 регрессий по существующим тестам
- [ ] CHANGELOG.md обновлён под Unreleased
- [ ] Cross-link на этот marker в ROADMAP_KARPATHY_LIKE_LIVING_KB.md

## 5. Lessons learned (опционально)
*1–3 пункта, что узнали в процессе, что повлияет на следующий step.*
```

**Precedent для шаблона:**
[`REVIEW_2026-04-26_MERGED_PLAN.md`](REVIEW_2026-04-26_MERGED_PLAN.md)
+ adapted под step-marker (не контракт).

---

## 5. Decision Point signals collection (decision D2)

### 5.1 Where to record

**До накопления 5+ signals** — ad-hoc запись в § 3.3 каждого step DONE
marker'а (см. § 4 template). Никаких отдельных файлов.

**После 5+ signals** — выделить в `DECISION_POINT_2026-XX_SIGNALS.md`
(когда подойдёт время Wave 1 closure ~3-4 месяца).

### 5.2 Signal taxonomy (per strategy § 5.3 matrix)

| Signal type | Что считается | Indicator для |
|---|---|---|
| **GitHub stars / forks** | Старт от 0 → ≥10 за 4 недели = strong; ≥3 = weak | A4 (AI integrators) |
| **MCP downloads** | Если зарегистрированы в Smithery / Cline marketplace (Wave 1.5 task) | A4 |
| **Прямые DM / email** | «Как использовать» / «можно ли team» / «как support'ать» | Mixed; depends on content |
| **Owner usage rate** | Daily check-ins, личные queries в собственный bot | A1 (sanity check, что owner ещё в сегменте) |
| **Sponsors revenue** (если включён Stage 0→1) | $/mo float | A1 + signal к Stage 1→2 |
| **Reddit / HN mentions** | Search alerts на «telegram rag», «telegram knowledge base» | Adjacent communities |

### 5.3 Cadence

- **При каждом step DONE marker** — запись в § 3.3.
- **Раз в 2 недели** — ad-hoc проверка GitHub stars + DM scan (не
  блокирует step work, lightweight).
- **При появлении явного signal'а** (≥3 DM по одному запросу типа за
  неделю; первый paying customer interest) — extraordinary entry в
  следующий DONE marker + flag для Decision Point ускорения.

### 5.4 Stage 0→1 monetization trigger watcher

Strategy § 5.4 trigger = «Wave 1 done + ≥10 GitHub stars OR ≥3
запроса 'как support'ать?'».

**Gating:** stage 0→1 не активируется до Wave 1 done **даже** если
trigger condition выполнена раньше — это сознательное ограничение
(focus на product polish).

**Watcher:** раз в 2 недели включён в § 5.3 cadence. Если trigger
условие выполнено **до** Wave 1 done — записать в нakопительной
секции «Pre-Wave-1-done signals» в DONE markers, но не действовать.

---

## 6. Anti-paths для Wave 1 execution

| Anti-pattern | Почему НЕ |
|---|---|
| Skip 24h watch для «маленького» deploy'я | Прецедент Session B+ M3 SQL bug: «маленький» change оказался critical SQL bug, поймал только smoke-test после deploy. 24h watch — non-negotiable |
| Combine multiple sessions в один PR ради скорости | Session F precedent — 6 atomic commits в одном PR были justified общим scope (read-hardening). Sessions H/I/J имеют разный scope (read-context / username alias / LLM config) → разные PR'ы лучше для review + rollback |
| Modify F4-A `CurrentUser` контракт во время F4-B Core | F4-B накладывается СВЕРХУ на F4-A. См. [`docs/plans/F4_MULTI_TENANCY_FULL_PLAN.md`](../plans/F4_MULTI_TENANCY_FULL_PLAN.md) |
| Stage 0→1 включение раньше Wave 1 done | Распыление focus'а; см. § 5.4 |
| Skip refresh PARITY_DECISION_TRACKING после step 2 | Step 3 planning теряет input → возвращаемся к 68K-prep'у |
| Создавать `WAVE1_SIGNALS_LOG.md` сейчас | Premature — пустует пока signals не появятся; D2 решение |

---

## 7. Связанные документы

| Документ | Зачем |
|----------|-------|
| [`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md`](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md) | Strategy + Wave 1 sequence (что делаем). Этот документ — операционный «как» |
| [`PLANNING_F4B_WORKSPACES_PREP.md`](PLANNING_F4B_WORKSPACES_PREP.md) | Q1–Q8 для F4-B Core — Q2/Q4 refined 2026-05-03 |
| [`PARITY_DECISION_TRACKING.md`](PARITY_DECISION_TRACKING.md) | Журнал observations для Wave 1 step 3 planning |
| [`START_PROMPT_FIX_BUG011_READ_CONTEXT_SESSION_H_2026-05-02.md`](START_PROMPT_FIX_BUG011_READ_CONTEXT_SESSION_H_2026-05-02.md) | Session H sprint prompt — § 0.5 cross-link сюда |
| [`MONETIZATION_MECHANISMS_2026-05-02.md`](MONETIZATION_MECHANISMS_2026-05-02.md) § 5.4 | Stage 0→1 trigger detail (упоминается в § 5.4 этого документа) |
| [`docs/notes/BUG_LOG.md`](BUG_LOG.md) | BUG-010 / BUG-011 / BUG-012 entries — input для Sessions H/I |
| [`docs/adr/0005-bot-llm-provider-flexibility.md`](../adr/0005-bot-llm-provider-flexibility.md) | ADR — input для Session J |

---

## 8. История

| Дата | Изменение |
|------|-----------|
| 2026-05-03 | Первая версия. Создана как ответ на запрос «зафиксируй достигнутые в этом чате соглашения документально» после deep-dive Q2+Q4 для F4-B Core и подтверждения 4 развилок (A3 packaging / B3 process / C1 done-marker format / D2 signals collection). |

---

## 9. Когда удалить этот файл

После Wave 1 closure (~3-4 месяца) — этот файл либо архивируется
(`PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03_archived.md` со ссылкой
на `REVIEW_2026-XX-XX_WAVE1_DONE.md`), либо удаляется. На усмотрение
закрывающей сессии.

Если Wave 1 затянется или будет переоценено в процессе — обновлять
этот файл inline (с записью в § 8 история), не плодить вторую
версию.
