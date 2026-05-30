# Cursor Automations: обход через `cursor-app-control`

**Статус:** workaround на время недоступности MCP-сервера `cursor-backend-control`.
**Дата:** 2026-05-30.
**Контекст:** В текущих сессиях Cursor managed-сервер `cursor-backend-control` объявлен в статическом контексте инструментов, но **не регистрируется в рантайме** (вызов даёт `MCP server does not exist`). Соседние managed-серверы (`cursor-app-control`, `cursor-ide-browser`) работают, Glass Automations UI открывается. Локальные причины исключены (см. раздел «Диагностика»). Дефект — на стороне регистрации managed-сервера в клиенте/бэкенде Cursor.

---

## 1. Принципиальное ограничение

`cursor-backend-control` — **программный (API) доступ**: читает/пишет данные напрямую через бэкенд и **возвращает результат в агента**.

`cursor-app-control` — **управление UI приложения**: **открывает нужный экран** Automations (в т.ч. с предзаполнением), но **не возвращает данные в агента**. Финальное действие (сохранение, чтение результата) делает человек/UI.

> ❌ `cursor-app-control` **не может** вернуть список автоматизаций, прочитать поля существующей или подтвердить сохранение программно.
> ✅ Он **может** довести пользователя/UI до нужного экрана с подготовленными данными.

Это переход от модели «агент делает всё сам» к **human-in-the-loop**: агент готовит, человек подтверждает в UI.

---

## 2. Таблица соответствия инструментов

| `cursor-backend-control` (недоступен) | Что делал | Замена в `cursor-app-control` | Полнота |
|---|---|---|---|
| `list_automations` | список в агента | — | ❌ нет аналога |
| `get_automation(id)` | поля одной автоматизации в агента | `open_automation({automationId, view:"view"})` | ⚠️ откроет в UI, данные не вернёт |
| `create_automation(payload)` | создать программно | `open_automation({templateId?, prefillWorkflowData?})` | ✅ через UI: префилл → пользователь жмёт Save |
| `update_automation(payload)` | изменить программно | `open_automation({automationId, view:"edit"})` | ⚠️ откроет редактор; правки/сохранение в UI |
| `build_automation_prefill_url(json)` | построить URL префилла | не нужен: `open_automation` принимает `prefillWorkflowData` напрямую | ✅ лучше — без URL |

Вспомогательно: `open_resource` (открыть URL/файл в Glass) — для перехода в веб-UI Automations на `cursor.com`, если нужно посмотреть глазами.

---

## 3. Инструменты `cursor-app-control` — детально

### 3.1 `open_automation` — основной рабочий инструмент

Схема (все поля опциональны):

```json
{
  "automationId": "string (1..512)  — открыть существующую автоматизацию",
  "view": "edit | view | runs       — какой экран; ТРЕБУЕТ automationId; default edit",
  "templateId": "string (1..512)    — преселект шаблона в форме новой автоматизации",
  "prefillWorkflowData": { }
}
```

Поведение по комбинациям:

- `{}` → пустая форма **новой** автоматизации.
- `{ templateId }` → новая форма с выбранным шаблоном.
- `{ prefillWorkflowData: {...} }` → новая форма, предзаполненная. **Требует approval вызова инструмента** (by design). Payload уходит только в активный Glass-view, не в URL и не в storage.
- `{ automationId }` → существующая в режиме `edit`.
- `{ automationId, view: "view" }` → просмотр карточки.
- `{ automationId, view: "runs" }` → история запусков.

`view` без `automationId` — невалидно.

### 3.2 `open_resource` — открыть URL/файл/терминал в Glass

Открывает файлы рабочей области и всё под `~/.cursor` (правая панель), веб-ссылки (по настройке Glass-браузера), терминалы, output-каналы. Для Automations: открыть веб-дашборд на `cursor.com`, чтобы человек посмотрел список/статусы (замена `list_automations`).

> Точная JSON-схема `open_resource` и `cursor_dialog` как отдельные файлы не публикуется (только описания в инструкциях сервера). Вызывать по документированной форме, не угадывать поля.

### 3.3 Прочие (не про Automations)

- `rename_chat({ title })` — переименовать текущий чат.
- `create_project({ path })` — создать папку проекта + `git init`.
- `move_agent_to_root({ rootPath | rootPaths })` — сменить корневую рабочую папку агента; делает `git fetch origin <branch>` (упадёт на чисто локальной ветке).
- `move_agent_to_cloned_root({ rootPath })` — то же для sibling-клона на той же ветке (без fetch/ff-merge).
- `cursor_dialog` (item="rule", scope="user", action=list/add/update/remove) — user-rules; перед записью всегда сначала `list`.

---

## 4. Готовые паттерны вызова

### A. Создать новую автоматизацию (замена `create_automation`)

```text
cursor-app-control → open_automation
{ "prefillWorkflowData": { /* workflow JSON: триггер + действия */ } }
```
Дальше форма открывается предзаполненной → **пользователь проверяет и жмёт Save**. Агент не получает ID/подтверждения — запросить у пользователя, если нужно дальше.

### B. Открыть форму по шаблону (если точная схема workflow неизвестна)

```text
open_automation { "templateId": "<id шаблона>" }
```

### C. Отредактировать существующую (замена `update_automation`)

```text
open_automation { "automationId": "<id>", "view": "edit" }
```

### D. Посмотреть автоматизацию / запуски (частичная замена `get_automation`)

```text
open_automation { "automationId": "<id>", "view": "view" }   // карточка
open_automation { "automationId": "<id>", "view": "runs" }   // история запусков
```

### E. «Список автоматизаций» (замена `list_automations`)

Программного списка нет. Обход:
```text
open_resource { URI веб-дашборда Automations на cursor.com }
```
пользователь читает список глазами.

---

## 5. Чего ожидать и о чём предупреждать пользователя

1. **Нет данных обратно в агента** — ID/поля/статусы пользователь сообщает вручную.
2. **`automationId` агент сам не узнает** — получить от пользователя, не выдумывать.
3. **Префилл требует approval** — всплывёт запрос подтверждения инструмента (норма).
4. **Схема `prefillWorkflowData` локально не задокументирована** (это «Cursor Automation workflow JSON»). Если форма неизвестна — открывать пустую/по `templateId` и заполнять в UI, либо взять образец из существующей автоматизации (открыв её в `view`).
5. **Сохранение делает человек/UI**, не агент.

---

## 6. Рекомендованный рабочий цикл

1. Уточнить цель автоматизации (триггер, действия); для правки — запросить `automationId`.
2. Создание → `open_automation` с `templateId` и/или `prefillWorkflowData`; правка → `open_automation` с `automationId` + `view:"edit"`.
3. Сообщить пользователю: «форма открыта, проверьте и сохраните»; запросить ID/результат, если нужно для следующих шагов.
4. Чтение (list/get) → `open_resource` на веб-дашборд + ручное чтение.
5. Когда `cursor-backend-control` снова поднимется — вернуться к программной модели (list/get/create/update напрямую).

---

## 7. Диагностика (почему проблема не локальная)

Исключённые гипотезы:

| # | Гипотеза | Вердикт | Факт |
|---|---|---|---|
| 1 | `mcpAllowlist` в `~/.cursor/permissions.json` | ❌ | файла нет, allowlist нигде не задан |
| 2 | hook `beforeMCPExecution` → deny / `failClosed` | ❌ | хуков нет ни глобально, ни в проекте |
| 3 | permission-deny при вызове | ❌ | ошибка `MCP server does not exist`, не `denied` |
| 4 | перезапуск Cursor | ❌ | пробовали, не помогло |
| 5 | Privacy Mode (NO_STORAGE/UNSPECIFIED) | ❌ | режим `PRIVACY_MODE_NO_TRAINING` = storage-eligible |
| 6 | entitlement на фичу Automations | ❌ | Glass Automations UI открывается → фича доступна |

Версия Cursor на момент диагностики: **3.6.21**.

**Вывод:** дефект регистрации именно managed-сервера `cursor-backend-control` в рантайме клиента/бэкенда Cursor. Локально чинить нечего. Рекомендации: обновить Cursor; если не исчезнет — сообщить в поддержку Cursor с этими фактами.
