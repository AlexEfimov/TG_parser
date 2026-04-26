# Review Merge — Post-Living-KB Audit Consolidation

**Назначение:** стартовый промпт для **merge-сессии**, которая сводит deliverable'ы двух независимых review-окон (см. [`START_PROMPT_REVIEW_POST_LIVING_KB.md`](START_PROMPT_REVIEW_POST_LIVING_KB.md)) в один итоговый план исправлений `docs/notes/REVIEW_2026-04-26_MERGED_PLAN.md`. Из этого плана юзер потом откроет GitHub-issues и запустит fix-спринт.

**Тип сессии:** read-only consolidation. **Никаких изменений в код / документы / production.** Только синтез двух чужих deliverable'ов в третий, итоговый.

**Дата подготовки промпта:** 26 апреля 2026.

**Когда использовать:** **только** после того, как **оба** review-окна завершили работу (см. § 1.1 — preflight).

---

## 1. Pre-flight (обязательная проверка перед стартом)

### 1.1 Сколько deliverable доступно

```bash
ls -la docs/notes/REVIEW_2026-04-26_POST_LIVING_KB__*.md
```

В зависимости от количества файлов:

| Найдено | Что делать |
|---|---|
| **0** | **Остановиться**: «Не найдено ни одного review-deliverable. Сначала запусти review-окна по `START_PROMPT_REVIEW_POST_LIVING_KB.md`.» |
| **1** | **Degraded mode** — см. § 1.1a |
| **2** | **Full ensemble mode** — основной сценарий, по этому промпту целиком |
| **>2** | Спросить юзера какие **ровно два** мерджить (по mtime — новейшие? по REVIEWER_ID?). Не продолжать без явного указания. |

### 1.1a Degraded mode (один deliverable)

Если найден ровно **один** review-deliverable, второй ревьюер не запустился / упал / сильно задержался. Юзер мог решить не ждать. В этом случае:

1. **Подтвердить намерение** у юзера явным сообщением:

   > «Найден только один review-deliverable: `<filename>` (REVIEWER_ID=`<id>`). Второй ревьюер отсутствует. В этом режиме merge-сессия даёт ОЧЕНЬ ОГРАНИЧЕННУЮ ценность — severity calibration по матрице § 3.2 не применима, conflict resolution не нужен, dedupe-ratio = 0%. Я могу:
   >  
   > **(a)** Произвести degraded-merge — добавить шапку, executive summary, перенумеровать findings в формат § 4.3 со status=`single` для всех. Это не калибровка, а просто структурная доводка.
   >  
   > **(b)** Остановиться и подождать второго ревьюера.
   >  
   > Что выбираешь?»

2. **Не продолжать без явного ответа.**

3. Если выбрано (a) — degraded-merge:
   - **Шапка** (§ 4.1) содержит явное `**Mode: DEGRADED — single reviewer**` и `**Source statistics:** Reviewer 2 missing`.
   - **§ 2 Confirmed findings** — пуст (нечем подтверждать).
   - **§ 3 Single findings** — все findings из доступного deliverable, статус `single` для каждого.
   - **§ 4 Contested findings** — пуст.
   - **Severity** не пересчитывать — оставить как у ревьюера, **но** в § 1 (Executive summary) явное предупреждение: «Severity не калибровано через ensemble — fix-агент должен относиться к critical/major консервативно».
   - **§ 5 Recommendation** — copy from reviewer's deliverable as-is, плюс примечание: «второе мнение отсутствует, рекомендуется верифицировать через быстрый sanity-check перед стартом sprint'а».
   - **§ 6 Tech-debt backlog** — copy from reviewer's deliverable, без re-prioritization.
   - **§ 8 OPEN QUESTIONS** — обязательно содержит первым пунктом: «Запустить ли второго ревьюера post-hoc на том же base commit, чтобы получить полную ensemble-калибровку?»

   Commit message: `docs(review): degraded-merge from <REVIEWER_ID> only — N findings, single-reviewer mode`.

4. Если выбрано (b) — завершить сессию без правок:
   - Сообщить юзеру: «Ожидаю второй deliverable. Перезапусти merge-сессию когда оба будут готовы.»
   - Никаких файлов не создавать.

### 1.2 Calibration anchor check (machine-parseable шапка § 8.2)

Прочитать **только шапки** обоих файлов (первые ~15 строк) и сравнить:

| Поле | Reviewer 1 | Reviewer 2 | OK? |
|---|---|---|---|
| Base commit | ... | ... | если разные → **disclosure event**, отметить в § 4 финального плана |
| Started UTC | ... | ... | если интервал > 48ч → возможен дрейф ground truth, отметить |
| Findings count (total) | ... | ... | для информации |
| Findings count (critical/major/minor) | C/M/m | C/M/m | для калибровки § 3.2 |
| Open questions count | ... | ... | для § 5 |

Если base commit'ы разные — это **штатно** (между двумя сессиями могло пройти время), но требует особого внимания при сравнении findings, ссылающихся на конкретные строки (line numbers могли сместиться).

### 1.3 Watch-state check

```bash
ssh prod 'cat ~/f5c-watch/cron.log'
```

Получить актуальный статус F5-C watch'a (verdict-строки). Это войдёт в § 6 финального плана как «оперативная картинка на момент merge».

---

## 2. Out of scope (что НЕ делать в merge-сессии)

| Категория | Запрещено |
|---|---|
| **Файловая запись** | `Write`, `StrReplace`, `Delete` для любых файлов кроме итогового `docs/notes/REVIEW_2026-04-26_MERGED_PLAN.md` |
| **Правка deliverable'ов** | Не редактировать `REVIEW_2026-04-26_POST_LIVING_KB__<X>.md` ни под каким предлогом — даже опечатки |
| **GitHub** | Не открывать issues / PRs / комментариев |
| **Production** | Только read-only `ssh prod cat ...` для watch-state'а |
| **Code / docs fix** | Никаких правок исходного кода и документации проекта — это работа fix-спринта по итогам merged plan'а |
| **Самостоятельный re-review** | Не «проверять» findings ревьюеров походом в код. Если есть сомнение — ставь `merge-status: contested`, не подменяй своим суждением. Исключение — § 4.3 (verification of conflicts) |

---

## 3. Merge methodology (как сводить findings)

Это самая ответственная часть. Цель — **не «сложить два списка»**, а получить **калиброванный** итог: каждый finding имеет правильную severity (на основании того, увидели ли его оба ревьюера), правильный priority (на основе severity × confidence × scope), и конкретный suggested action.

### 3.1 Алгоритм deduplication

Для каждой пары findings из двух deliverable'ов проверить, не **одинаковая ли проблема**. Критерии «одинаковости» (нужно совпадение **обоих**):

1. **Substantive overlap:** оба finding'а описывают одну и ту же фактическую проблему (тот же файл, та же логическая ошибка / gap / inconsistency). Не путать с «оба упомянули один файл» — нужно совпадение **наблюдения**.
2. **Same root cause:** если предлагаемые fixes совместимы (один не отменяет другой) — это **дубликат**. Если fixes разные / противоречивые — это **conflict** (§ 3.3).

Категории merge-status:

| Status | Когда | Severity calibration |
|---|---|---|
| `confirmed` | Оба ревьюера независимо нашли; substantive overlap есть; fixes совместимы | если хотя бы один указал `critical` — финал `critical`; если оба `major` — финал `major` (повышение); если один `major`, другой `minor` — финал `major` (точка зрения «нашёл два раза» весомее) |
| `single` | Только один ревьюер нашёл | финал = severity ревьюера, **минус 1** уровень если confidence у него `low`; иначе как есть |
| `contested` | Оба ревьюера упомянули, но **противоречат** друг другу (один говорит «X сломан», другой говорит «X работает корректно») | финал — отдельная секция § 4 с обоими наблюдениями + рекомендация юзеру верифицировать |

### 3.2 Severity calibration matrix

```
                        Reviewer 1 severity
                  critical | major  | minor
              ┌──────────┬────────┬───────┐
critical      │ critical │critical│ major │
              ├──────────┼────────┼───────┤
Reviewer 2:   major      │ critical │ major  │ major │
              ├──────────┼────────┼───────┤
              minor      │  major   │ major  │ minor │
              └──────────┴────────┴───────┘
```

Логика: если **оба** нашли — это сильный сигнал, поднимаем severity. Если **один** нашёл `critical`, второй пропустил — оставляем `critical` (один ревьюер мог пропустить из-за случайной слепой зоны). Если один нашёл `minor`, второй `critical` — финал `major` (расхождение слишком большое, нужна осторожность).

### 3.3 Conflict resolution

Если два ревьюера **противоречат** (`contested`):

1. **Verify quickly** — открыть упомянутый файл, посмотреть конкретную строку, понять кто прав.
2. Если verification занимает > 5 минут — **не верифицировать**, оставить `contested` с заметкой для юзера: «требует ручной проверки, оба наблюдения сохранены».
3. Если оба наблюдения логически совместимы (например, ревьюер A видел проблему с одной стороны, B — с другой) — переклассифицировать в `confirmed` с расширенным observation.

### 3.4 Tech-debt backlog merge

В каждом deliverable есть § 4 (Tech-debt backlog → predicted issues). При merge:

1. Собрать TD-items обоих ревьюеров.
2. Если TD-items ссылаются на **одинаковые finding'и** (после deduplication по § 3.1) — объединить в один TD с расширенным «source findings» полем.
3. Recompute scope (S/M/L): консервативный — если оба сошлись на S, финал S; если разошлись — финал по большему (M если S/M, L если M/L).
4. Recompute priority (P0/P1/P2): консенсусом; если расхождение — снизить уровень («лучше мягче, чем агрессивнее») кроме случая когда merged severity = `critical` (тогда P0).

### 3.5 Recommendation merge

В § 5 каждого deliverable — рекомендация на следующий спринт + confidence.

| Сценарий | Что в финал |
|---|---|
| Оба рекомендуют одно и то же | финальная рекомендация = эта; confidence = max(обе) |
| Расходятся, но один с low confidence | финал = рекомендация с higher confidence; вторая упоминается как «alternative» |
| Расходятся с одинаковым confidence (high/high или medium/medium) | **не выбирать самолично** — § 5 финального плана содержит **обе альтернативы** + объективные критерии за/против каждой; финальный выбор — за юзером |
| Один рекомендует «debt-fix-sprint», второй — feature-sprint | если merged plan имеет ≥ 2 P0 debt items — финал «debt-fix-sprint»; иначе вторая рекомендация |

---

## 4. Deliverable — структура `docs/notes/REVIEW_2026-04-26_MERGED_PLAN.md`

### 4.1 Шапка (machine-parseable, по аналогии с § 8.2 review-промпта)

```markdown
# Post-Living-KB Audit — Merged Plan

**Merged from:**
- `docs/notes/REVIEW_2026-04-26_POST_LIVING_KB__<reviewer-1-id>.md` (commit {SHA-where-it-landed})
- `docs/notes/REVIEW_2026-04-26_POST_LIVING_KB__<reviewer-2-id>.md` (commit {SHA-where-it-landed})

**Merge agent:** {model name}
**Merged (UTC):** {ISO timestamp}
**Base commit at merge:** {git rev-parse --short HEAD}
**Watch state at merge:** {N verdict-строк, последняя: '...'}

**Source statistics:**
- Reviewer 1 ({id}): C={X}/M={Y}/m={Z}, OQ={K}
- Reviewer 2 ({id}): C={X}/M={Y}/m={Z}, OQ={K}

**Merged statistics:**
- Confirmed (both reviewers): {N} findings (C={X}/M={Y}/m={Z})
- Single (one reviewer only): {N} findings (C={X}/M={Y}/m={Z})
- Contested (conflict): {N} findings
- Total dedupe ratio: {(N1+N2-Nfinal)/(N1+N2)*100}%

**Disclosure events (если есть):** {список или «none»}

---
```

### 4.2 Body sections

```markdown
## 1. Executive summary
5-10 строк. Общий вердикт. Top-3 critical findings (короткой строкой каждый, с merge-status).
Recommendation на следующий спринт + confidence.

## 2. Confirmed findings (both reviewers)
Группировка по category (controlled vocab — § 8.5 review-промпта).
Каждый finding по формату § 4.4.

## 3. Single findings (one reviewer only)
Группировка по category.
Те же поля, но дополнительно: `Found by: <REVIEWER_ID>` и комментарий, почему второй пропустил
(если можно объяснить — например, «covers a Side B zone that R2 spent less time on»; если нет — просто «not noticed»).

## 4. Contested findings (conflict)
Каждый contested-finding содержит **оба** наблюдения дословно + резолюцию merge-агента
(если возможна быстрая verification) или явный hint юзеру для ручной проверки.

## 5. Recommendation для следующего спринта
- Если ревьюеры сошлись — одна Recommendation + обоснование.
- Если расходятся — обе альтернативы с pro/contra, выбор за юзером.
- Watch verdict (из § 1.3 этого промпта).

## 6. Tech-debt backlog (merged)
Таблица:

| ID | Title | Source findings | Status (confirmed/single/contested) | Scope (S/M/L) | Priority (P0/P1/P2) |
|---|---|---|---|---|---|
| TD-01 | ... | C-001, A-007 (R1) + B-014 (R2) | confirmed | S | P0 |
...

Каждый TD должен быть actionable — title как commit-message-prefix, не «надо подумать про X».

## 7. Action plan для юзера
1. Какие GitHub issues открыть (по TD-items с priority P0/P1)
2. Что делать с contested findings (если есть)
3. Каким спринтом стартовать (по § 5)
4. (опционально) что **не делать** — например, если ревьюеры предлагали breaking-changes которые лучше отложить

## 8. OPEN QUESTIONS (юзеру)
Объединённый список OPEN QUESTIONS обоих ревьюеров + любые вопросы, возникшие при merge'е.
Группировка по тому, что блокирует action plan (§ 7) и что просто требует решения позже.

## 9. Metrics snapshot (на момент merge)
- HEAD: {git rev-parse --short HEAD}
- Watch cron-log: {K} verdict-строк, последний vehicl: '...'
- Tests: (если есть смысл перепроверить, иначе цитата из одного из deliverable'ов)
- Gap from review baseline: {commit diff R1.base..merge OR R2.base..merge}
```

### 4.3 Standardized merged finding format

```markdown
#### {merged-id} — {final-severity} | {category} | merge-status: {confirmed|single|contested}

**Where:** `path/to/file.py:LINE` (если ревьюеры указали разные строки — основная + список альтернатив в Notes)

**Source findings:**
- {reviewer-1-id}-NNN (severity: {critical|major|minor}, confidence: {high|medium|low})
- {reviewer-2-id}-MMM (severity: ..., confidence: ...)
[или только один, если single]

**Merged observation:** объединённое описание (если оба нашли — синтез наблюдений; если single — дословно).

**Why it matters (merged):** консолидированная мотивация. Если ревьюеры аргументировали по-разному — обе аргументации сохранить.

**Suggested action (merged):** если оба ревьюера предложили совместимые fixes — синтез; если предложили разные — лучший по критериям (минимально инвазивный, не ломающий обратную совместимость).

**Notes:** opt — расхождения в attribution (line numbers), альтернативные fixes от ревьюеров, ссылки на прецеденты.
```

### 4.4 Merged finding ID format

`{C|S|X}-NNN` где:
- `C` = confirmed, `S` = single, `X` = contested
- NNN — sequential per status (например, `C-001`, `C-002`, ..., `S-001`, ..., `X-001`)

Это позволит юзеру / fix-агенту быстро отфильтровать.

---

## 5. Open questions handling

В § 8 финального плана собрать **все** OPEN QUESTIONS из обоих deliverable'ов **дословно** (не интерпретировать), плюс свои вопросы, которые возникли при merge'е (например, «ревьюеры расходятся в trade-off X / Y, какое предпочтение у юзера?»).

Группировка:

1. **Blocking** — без ответа нельзя запустить fix-спринт (например, conflict в § 4)
2. **Non-blocking** — можно отложить, но требуют решения до конца Wave 2

---

## 6. Acceptance criteria

Merge-сессия считается завершённой, если:

- [ ] Оба deliverable существуют и прочитаны (но не изменены)
- [ ] Calibration anchors сравнены (§ 1.2)
- [ ] Watch state снят на момент merge'а (§ 1.3)
- [ ] Все findings прошли deduplication по § 3.1
- [ ] Severity calibrated по § 3.2
- [ ] Conflicts разрешены или явно помечены (§ 3.3)
- [ ] Tech-debt backlog merged по § 3.4
- [ ] Recommendation merged по § 3.5
- [ ] Финальный plan записан в `docs/notes/REVIEW_2026-04-26_MERGED_PLAN.md` по структуре § 4
- [ ] Plan закоммичен с message: `docs(review): merged audit plan — N findings (C={X}/S={Y}/X={Z}), recommendation: <X>`
- [ ] Финальное сообщение юзеру содержит:
  - путь к merged plan
  - top-3 confirmed-critical findings (одной строкой каждый)
  - top-1 contested finding (если есть) — для немедленного внимания
  - финальную recommendation (или дилемму, если ревьюеры разошлись)
  - dedupe ratio (показывает, сильно ли пересекались работы ревьюеров)

---

## 7. После прохождения

1. **Юзер** открывает GitHub issues по таблице § 6 финального плана (TD-items с priority P0/P1):
   - label: `tech-debt`, `post-living-kb-review`
   - body: цитата из § 2 (confirmed findings) или § 3 (single findings) merged plan'а
2. **Юзер** заполняет post-watch comment в issue #15 (шаблон в `docs/runbooks/F5C_DEPLOY_AND_WATCH.md` § «Post-watch report») — со ссылкой на § 9 (Metrics snapshot) merged plan'а
3. **Юзер** запускает следующий sprint по § 5 (Recommendation) merged plan'а — это уже **fix-сессия** с правом писать код, отдельный промпт

---

## 8. Ground rules для merge-агента

1. **Не правь findings** ревьюеров. Если их формулировка неудачна — оставь как есть в § 2/3/4 финального плана. Свободу формулировок имеешь только в § 1 (executive summary), § 5 (recommendation), § 7 (action plan), § 8 (OPEN QUESTIONS).
2. **Не верифицируй findings своим походом в код** — кроме § 3.3 (conflict resolution с быстрой проверкой ≤ 5 минут). Твоя задача — синтез, не «третий ревьюер».
3. **Не предлагай новые findings** — даже если по ходу merge'а заметил что-то, что оба ревьюера пропустили. Записать в § 8 OPEN QUESTIONS и оставить для следующего ревью / fix-сессии.
4. **Не меняй severity «по интуиции»** — только по матрице § 3.2. Если матрица даёт спорный результат — оставь как есть в § 3 (single) или § 4 (contested).
5. **Сохраняй verifiability** — каждый merged finding должен сохранять ссылки на source-finding ID'ы (§ 4.3).
6. **При сомнении в дедупе — НЕ сливай.** Лучше два single-finding'а с похожим описанием, чем одно confirmed где их нельзя разделить обратно.
7. **Выходные форматы строгие.** Шапка § 4.1 и формат findings § 4.3 должны быть machine-parseable — fix-агент будет это читать программно.

---

## 9. Citation back

- **Этот промпт:** `docs/notes/START_PROMPT_REVIEW_MERGE.md`
- **Review-промпт ревьюеров:** `docs/notes/START_PROMPT_REVIEW_POST_LIVING_KB.md` (его § 8 — формат findings; § 15 — ensemble protocol)
- **Транскрипт-источник:** UUID `518d7766-dd0b-4f5d-bc6c-5bfb478264da` (где обсуждали ensemble-режим и доработали review-промпт)

Эти ссылки — для подтягивания контекста, не для копипасты в финальный plan.
