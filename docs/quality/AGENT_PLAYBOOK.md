# AGENT_PLAYBOOK — инструкция агенту по ведению `docs/quality/`

**Кому адресовано:** AI-агенту (Claude в Cursor или любому будущему агенту),
работающему с этим репозиторием. Пользователь даёт описание ситуации своими
словами — агент читает этот playbook и производит правильный артефакт в
`docs/quality/`.

**Когда активируется:** как только пользователь пишет одну из формулировок —
«замечание», «наблюдение», «заметка в quality», «инцидент», «сбой», «кейс»,
«вот что увидел», «запиши наблюдение», или аналогичное. Если непонятно,
явно спросить: *«Это наблюдение для `docs/quality/INBOX.md`?»* — один
короткий вопрос, не больше.

**Принцип:** низкий friction > идеальная классификация. Лучше записать в INBOX
с приблизительным лейблом и оставить триаж на позже, чем тормозить пользователя
серией уточняющих вопросов.

---

## 0. Decision tree — в какой артефакт писать

```
Описание от пользователя
        │
        ├── Помещается в 5 полей шаблона (≤ ~15 строк)?
        │      │
        │      ├── Да → запись в docs/quality/INBOX.md
        │      │          (перейти к §2, §3)
        │      │
        │      └── Нет — есть хронология (>3 timestamped событий)
        │               / SQL / стектрейсы / API responses
        │               / impact на >1 канал или >1 пользователя
        │               / требовался ручной ремонт
        │          │
        │          └── Да → файл docs/quality/incidents/YYYY-MM-DD_<slug>.md
        │                    + one-liner-pointer в INBOX.md
        │                    (перейти к §4)
        │
        └── Пользователь явно сказал «это уже решено, надо задокументировать
            как <fixed|wontfix|duplicate>» → запись в TRIAGED.md
            (перейти к §5)
```

**Hard rule:** если есть хоть малейшее сомнение между INBOX и incident — идём в INBOX.
Апгрейд до incident-файла позже дешевле, чем писать полную RCA для наблюдения,
которое окажется duplicate'ом.

---

## 1. Минимум уточняющих вопросов

Задаём уточнение **только если** одно из:

1. Окружение не выводится из контекста и влияет на severity (prod vs local).
   Формулировка: *«На VPS (prod) или локально?»*
2. Описание содержит **несколько** разных наблюдений — уточняем количество
   записей: *«Это три отдельных наблюдения (создаю три entry в INBOX) или
   одно связанное (одна запись)?»*
3. Симптом указывает на `P0` (data loss, prod down, corruption) — один
   вопрос подтверждения: *«Это `P0` — продуктив сейчас неисправен / данные
   повреждаются? Если да, делаем incident-файл сразу.»*

Во всех остальных случаях — **сразу пишем**, с пометкой `n/a` в тех полях
шаблона, которые не выводятся из описания. Не галлюцинируем недостающие
детали (не выдумываем стектрейсы, не додумываем шаги воспроизведения).

---

## 2. Извлечение 5 полей из произвольного текста → INBOX

Шаблон (напоминание; полный вид в [`_TEMPLATE_OBSERVATION.md`](_TEMPLATE_OBSERVATION.md)):

```
## YYYY-MM-DD HH:MM UTC — <component> · <type> · <severity>

**Что:** ...
**Как воспроизвести:** ...
**Ожидал:** ...
**Контекст:** ...
**Заметки:** ...
```

### Правила маппинга:

| Поле | Что туда идёт | Если отсутствует в описании |
|---|---|---|
| **Заголовок — время** | UTC-метка на момент написания (не момент события пользователя, если тот не указан явно). Формат `YYYY-MM-DD HH:MM UTC`. | n/a — всегда выводится из системного времени |
| **Заголовок — лейблы** | `component · type · severity`, см. §3 | — |
| **Что** | *Одно предложение*, настоящее время, что именно пользователь видит / считает неправильным. Перефразируй описание в нейтральный tech-тон, без эмоций. | n/a — если нельзя вытащить, проси уточнение |
| **Как воспроизвести** | Минимальные шаги или команда. Если пользователь сказал «один раз увидел, не повторил» — пишем явно: `"n/a — наблюдал один раз в <env>, шагов воспроизведения нет"` | `"n/a — шаги не указаны"` |
| **Ожидал** | Что, по мнению пользователя или по документации, должно было произойти. Если пользователь не сказал явно — *аккуратно* вывести из контракта (docs / AGENTS.md). Если неясно — `"n/a — ожидание не указано, требует clarification на triage"` | `"n/a — не указано"` |
| **Контекст** | Environment (VPS/local), код/commit, канал, роль пользователя. Выводится из `git_status` (commit), текущего диалога (env), `@`-references. | `"n/a"` для каждой под-графы, не лепим всё в одну «n/a» |
| **Заметки** | Свободная форма: подозреваемый модуль, ссылки на related INBOX-записи (`see 2026-MM-DD HH:MM`), на incidents (`→ incidents/...`), гипотезы. Разрешено оставлять пустой. | — |

### Что **НЕ** делать при извлечении:

- Не резюмировать эмоциональные формулировки пользователя как факты («бот тупит» → *нет*, пиши конкретный симптом; если симптом не назван — уточни).
- Не додумывать стек (`вероятно в scheduler_service.py:146`) без обоснования — это идёт только если из описания ясно видно источник (лог, трейс).
- Не ставить `severity` выше указанного пользователем — если сказано «минорный», ставим `P3`, даже если нам кажется иначе. Можно в `Заметки` добавить `[agent note: возможно P2 из-за <rationale>]`.
- Не удалять комментарий-пример в `INBOX.md` (`<!-- Example entry ... -->`) — он остаётся для следующих авторов.
- **Не коммитить** изменения без прямого запроса пользователя (см. [`making_code_changes` в системных правилах]).

---

## 3. Алгоритм выбора лейблов

Лейблы берутся **только** из [`TAXONOMY.md`](TAXONOMY.md). Если ни один не
подходит — **не изобретать**, а добавить в TAXONOMY сначала (отдельная
docs-only-правка) и потом использовать.

### 3.1 `component` — эвристика по ключевым словам в описании

| Пользовательская формулировка содержит | `component` |
|---|---|
| «бот», «/ask», «/help», «/digest», Telegram DM, «прислал», «не отвечает в чате» | `bot` |
| «MCP», «в Claude вызвал tool», «`tg-parser:<name>`», «агент из Cursor» | `mcp` |
| «API», «curl», «HTTP 500», «endpoint`/<path>`» | `api` |
| «Telethon», «FloodWait», «не парсит», «ingest застрял», «raw сообщения» | `ingestion` |
| «обработка сообщения», «LLM вернула пусто», «embedding не посчитался», «dedup пропустил» | `processing` |
| «темы», «topic_cards», «0 тем», «topicization», «coverage» | `topicization` |
| «`/ask` дал не тот ответ», «RAG», «search_knowledge_base», «retrieval» | `rag` |
| «дубликат пропустили», «одинаковые сообщения в базе» | `dedup` |
| «alembic», «migration», «schema drift», «DuplicateTableError» | `migrations` |
| «scheduler», «каждый час», «cron», «digest не пришёл в назначенное время» | `scheduler` |
| «docker», «VPS», «prometheus», «grafana», «caddy», «backup», «ssh» | `infra` |
| «CLI», «`tg-parser <cmd>`», «команда упала» | `cli` |
| «в README неправильно», «в runbook не хватает шага», «старт-prompt устарел» | `docs` |
| «тест упал», «CI красный», «фикстура» | `tests` |

Если описание задевает **несколько** component'ов — ставим **тот, где корень проблемы**.
Напр. «бот выдал «Нет данных», хотя канал добавлен» — корень обычно в
`topicization` или `rag`, не в `bot` (бот лишь отображает). В `Заметки`
можно написать `surface: bot, root: topicization (suspected)`.

### 3.2 `type` — эвристика по глаголам / тону

| Формулировка | `type` |
|---|---|
| «крашится», «кидает исключение», «возвращает 500», «повреждает данные», «неправильный ответ на <конкретный> вход» | `bug` |
| «непонятно», «неочевидно», «странно что <X>, а не <Y>», «чувствую себя глупо когда <…>» | `ux` |
| «в docs нет», «в runbook неправильно», «старт-prompt устарел», «AGENTS.md противоречит коду» | `docs` |
| «медленно», «много ест памяти», «дорого по токенам», «занимает 2 минуты вместо 10 секунд» | `perf` |
| «работает сейчас, но когда нагрузка вырастет — сломается», «fragile», «race condition», «no retry» | `reliability` |
| «секреты в логах», «юзер видит чужие данные», «без авторизации», «injection» | `security` (bump to `P1+`) |
| «не вижу в метриках», «непонятно из логов что произошло», «нет алерта» | `observability` |
| «а правда ли что <X>», «не уверен, это баг или фича», «хочу разобраться» | `question` |

**Silent failure** (работает «успешно» но производит неправильный результат без
ошибки / лога / метрики) → `reliability` + `observability` (двойной лейбл
разрешён в секции «Заметки», но в заголовке — один основной; обычно
`reliability` главный).

### 3.3 `severity` — приоритет

Базовые правила в [`TAXONOMY.md`](TAXONOMY.md) §severity. Дополнительно для агента:

- Если пользователь явно назвал severity — **используем его**, не пересматриваем в заголовке.
  Своё мнение можно записать в `Заметки` как `[agent note: …]`.
- Если severity не назван — оцениваем по функциональному impact'у + tie-breaker'ы
  из TAXONOMY (`silent failure → +1`, `data integrity → min P1`, `onboarding path → min P2`).
- При сомнении между двумя уровнями — **берём более низкий**. Upgrade на triage
  дешевле, чем downgrade (создаёт впечатление «агент паникует»).

### 3.4 Порядок в заголовке

Всегда: `component · type · severity`. Разделитель — ` · ` (пробел-middle-dot-пробел).
Не использовать `/`, `,`, `-` как разделитель — они ломают grep-based triage.

---

## 4. Создание incident-файла

### 4.1 Имя файла

`docs/quality/incidents/YYYY-MM-DD_<kebab-slug>.md`, где:

- `YYYY-MM-DD` — день **наблюдения** инцидента (не день записи). Если
  пользователь даёт описание поздно (например, через 2 дня после события) —
  берём день события.
- `<kebab-slug>` — ≤ 5 слов, lowercase, через подчёркивание **между словами**,
  но дефисы внутри составных слов допустимы. Примеры:
  - `genotek_topicization_silent_failure`
  - `ingestion_floodwait_cascade`
  - `digest_missed_dst_transition`

### 4.2 Содержимое

Основа — [`_TEMPLATE_INCIDENT.md`](_TEMPLATE_INCIDENT.md). Обязательные секции:

1. **Front-matter** (Date, Observed in, Component(s), Severity, Status, Author).
2. **Summary** — 2–4 предложения.
3. **Timeline** — таблица `| Time | Event |`.
4. **Root cause** — с file:line-precise references, если возможно.
5. **Evidence** — логи, SQL, стектрейсы *дословно*, без пересказа.
6. **Impact** — users / data / downstream / duration.
7. **Mitigation** — что сделали, дословные команды.
8. **Follow-ups** — нумерованный список, каждый пункт = кандидат в sprint-scope.
9. **Lessons / latent defects** — отдельно от root-cause.
10. **Cross-references** — минимум 4 ссылки:
    - INBOX-entry (если был)
    - TRIAGED-entry (если уже триажировано)
    - related incidents
    - related roadmap / future-features anchors

Если какая-то секция пуста — оставляем заголовок + текст `_n/a — данных нет._` (курсив).
Не удаляем секцию — это ломает diff при следующих правках.

### 4.3 После создания incident-файла

1. Вставить в `INBOX.md` one-liner-pointer **сверху** под `## Open entries`:
   ```markdown
   ## YYYY-MM-DD HH:MM UTC — <component> · <type> · <severity>

   → [`incidents/<filename>.md`](incidents/<filename>.md)

   Короткое резюме в одну строку — почему это важно. Детали в incident-файле.
   ```
2. Если пользователь сказал «это уже решено» или есть явная диспозиция —
   добавить запись в `TRIAGED.md` (см. §5).
3. Если incident требует нового sprint'а — см. §6.

---

## 5. Запись в `TRIAGED.md`

**Когда:**
- Пользователь явно сказал «триажируй» / «это пойдёт в Sprint X» / «wontfix» / «это duplicate <prev>».
- Инцидент создаётся сразу с известной диспозицией (как было с `genotek`).
- Batch-triage (пользователь говорит «давай обработаем INBOX»).

**Структура записи** (копируется из существующих entry'ев в `TRIAGED.md`):

```markdown
## YYYY-MM-DD — <one-line headline>

**Labels:** <то же, что в INBOX / incident>
**Incident file:** [`incidents/<file>.md`](incidents/<file>.md)  (если применимо)
**Disposition:** triaged → Sprint X.Y | duplicate → <INBOX-date+headline> | wontfix | fixed → <commit-sha>
**Status:** <current state — e.g. "mitigated manually on YYYY-MM-DD, code fix pending">
**Sprint prompt:** [`../notes/START_PROMPT_SPRINT_<X>.md`](...)  (если создан)

### Why <выбранная диспозиция>
<1–3 предложения rationale>

### Scope absorbed into <Sprint>
<bullet list пунктов, которые sprint закроет>

### Out of scope (deferred)
<bullet list того, что решили НЕ делать в этом sprint'е и почему>
```

**После записи в TRIAGED:** INBOX-entry **не удаляется**, а помечается (см. §7).

---

## 6. Когда создаётся новый Sprint

**Условия** (все должны быть выполнены):

1. Объём работы ≥ ~0.5 сессии (не один bug-fix).
2. Несколько связанных дефектов формируют кластер (≥ 2 пункта follow-up из incident'а или ≥ 3 связанных INBOX-записей).
3. Пользователь не сказал явно «это одним мелким PR'ом».

**Что делает агент:**

1. Создаёт `docs/notes/START_PROMPT_SPRINT_<letter>.<n>_<TOPIC>.md` — структура
   из [`START_PROMPT_SPRINT_A7_DI19.md`](../notes/START_PROMPT_SPRINT_A7_DI19.md)
   или [`START_PROMPT_SPRINT_D1_TOPICIZATION_HARDENING.md`](../notes/START_PROMPT_SPRINT_D1_TOPICIZATION_HARDENING.md).
2. Добавляет строку в таблицу `docs/notes/FUTURE_FEATURES.md` § соответствующего
   Sprint-трека (A — migration, D — production hardening, E+ — future tracks).
   Если подходящей секции нет — создаёт новую по образцу «Sprint D».
3. Вставляет slot в порядок работ в `docs/notes/ROADMAP_V3_PRODUCTION_FIRST.md`
   (таблица «# / Шаг / Effort / Обоснование»), с обоснованием почему на этой позиции.
4. Прописывает cross-references:
   - Sprint prompt → INBOX-запись / incident-файл
   - INBOX / incident → Sprint prompt
   - TRIAGED → Sprint prompt + commit после фикса

**Чего не делает:** не открывает PR, не делает git commit, не пушит. Только документы.

---

## 7. Жизненный цикл INBOX-записи

```
INBOX.md (секция "Open entries")
        │
        │ batch-triage (agent + user)
        ▼
TRIAGED.md — новая запись с disposition
INBOX.md — запись **перенесена** (cut-paste) в блок "Triaged — moved to TRIAGED.md"
         в самом низу INBOX.md, с сохранением оригинального текста.
```

**Механика переноса** (агент делает во время batch-triage):

1. Скопировать entry из `## Open entries` в `TRIAGED.md` **верхом** (newest-first).
2. В `TRIAGED.md` добавить блок с disposition / sprint / rationale.
3. В `INBOX.md`:
   - Убрать entry из `## Open entries`.
   - Добавить в секцию `## Triaged (moved to TRIAGED.md)` в конце файла
     (создать секцию если её нет) **один-liner-pointer**:
     ```markdown
     - YYYY-MM-DD HH:MM UTC — <labels> — <headline> → [`TRIAGED.md`](TRIAGED.md#<anchor>)
     ```
4. Исходный полный текст уже сохранён в git-history через move, дублирования не нужно.

**Правило:** агент **никогда** не удаляет entry из INBOX навсегда. Удаление
невозможно-reversible и ломает audit-trail.

---

## 8. Commit-message конвенции (когда пользователь попросит закоммитить)

Форматы:

| Операция | Commit message |
|---|---|
| Добавлена одна INBOX-запись | `docs(quality): log observation — <short headline>` |
| Создан incident-файл | `docs(quality): capture <slug> incident RCA` |
| Batch-triage (≥ 2 записи перенесены в TRIAGED) | `docs(quality): triage INBOX batch — <N> entries → <disposition-summary>` |
| Создан sprint-prompt по итогам incident'а | `docs(sprint): scope Sprint <X.Y> — <topic>` |
| Обновлены roadmap / future-features по итогам triage | `docs(roadmap): insert Sprint <X.Y> before <next>` |
| Всё вместе одним атомарным коммитом | `feat(quality): <headline>` с HEREDOC-body, перечисляющим изменения |

Агент **не делает commit автоматически**. Ждёт явного запроса
(«закоммить», «commit», «пуш»). См. системные правила git-safety.

---

## 9. Пример end-to-end

### Ввод пользователя

> Попробовал /ask в боте про AgeManagment, спросил "что они пишут про метформин",
> а бот ответил что не знает. Но темы же есть, я проверил через list_channels.
> Это на VPS, через @my_bot в личке. Кажется hybrid-search что-то не так делает.

### Классификация агента

1. **INBOX или incident?** Помещается в 5 полей, нет стектрейсов, одна
   репродукция → **INBOX**.
2. **Component?** Поверхность — `bot` (`/ask` handler), но подозрение на
   `rag` (hybrid-search). Корень скорее в RAG → `rag`. В `Заметки`:
   `surface: bot /ask, root: rag (suspected hybrid-search)`.
3. **Type?** Неправильный ответ на конкретный вход, контракт нарушен →
   `bug`.
4. **Severity?** Отдельный канал / отдельный вопрос, system up, нет data loss,
   но затрагивает основной user-path (RAG-ответ) → `P2`.
5. **Время заголовка:** текущее UTC на момент записи.

### Результат — вставка сверху в `INBOX.md`

```markdown
## 2026-04-20 22:15 UTC — rag · bug · P2

**Что:** `/ask` про AgeManagment возвращает "не знаю" для вопроса, на который
в канале есть темы (подтверждено через `list_channels`).

**Как воспроизвести:** в DM `@my_bot` на VPS: `/ask что они пишут про метформин`.
Канал `AgeManagment`.

**Ожидал:** осмысленный ответ с reference'ами на посты канала, либо явное
«по этому вопросу в канале ничего не найдено, ближайшие темы: …».

**Контекст:** prod (VPS `redboxtgbot`), main @ <текущий HEAD>, канал
AgeManagment (75 topic_cards, coverage 74.52% по данным из RCA genotek §2),
пользователь = owner.

**Заметки:** surface: `bot /ask handler`, root: `rag (suspected hybrid-search)`.
Связанные места в коде: `tg_parser/retrieval/hybrid_search.py`,
`tg_parser/bot/handlers/ask.py`. Возможно пересекается с §5.5 из
incidents/2026-04-20_genotek_topicization_silent_failure.md
(разная трактовка coverage). [agent note: не исключаю, что "не знаю" —
это артефакт prompt'а, а не retrieval; проверить prompt в
`prompts/rag/*.yaml` на triage].
```

### Что агент **не** делает на этом шаге

- Не создаёт incident-файл (5 полей достаточно).
- Не пишет в TRIAGED (пользователь не давал диспозицию).
- Не создаёт sprint-prompt (одно наблюдение ≠ sprint).
- Не коммитит (не было запроса).
- Не ставит severity `P1`, даже если «основной user-path» — таких
  наблюдений может быть много, downgrade через `P2` → batch-triage.

---

## 10. Quick-reference — частые ошибки агента

| Ошибка | Правило |
|---|---|
| Галлюцинация деталей («видимо это в `scheduler_service.py:146`») без обоснования | Только если из описания явно виден источник (лог, трейс). Иначе — `[agent note: suspected …]` в Заметках. |
| Изобретение нового лейбла | Обновить TAXONOMY отдельной правкой, потом использовать |
| Удаление example-комментария в INBOX.md | Оставляем; заменяем только содержимое `## Open entries` |
| Создание incident-файла для наблюдения в 3 строки | INBOX. Incident только при хронологии / evidence / impact |
| Запись с severity выше, чем у пользователя | Уважаем пользователя; agent-note в Заметках, если есть обоснование |
| Автокоммит | Никогда. Только по запросу |
| Удаление triaged INBOX-entry | Только перенос в секцию `## Triaged` в конце INBOX, с one-liner-pointer |

---

## 11. Maintenance этого playbook'а

Playbook живой — если агент встречает ситуацию, не покрытую §0–§10, он:

1. Записывает эту ситуацию в `docs/quality/INBOX.md` как `type=docs · P3`
   с `Заметки: playbook gap — <описание>`.
2. На следующем batch-triage рассматриваем — нужен ли апдейт playbook'а.
3. Апдейт playbook'а = отдельный docs-only-коммит `docs(quality): refine
   agent playbook — <что изменили>`.

**Правило консервативности:** не раздуваем playbook наугад. Добавляем
только то, что уже сбойнуло на практике.
