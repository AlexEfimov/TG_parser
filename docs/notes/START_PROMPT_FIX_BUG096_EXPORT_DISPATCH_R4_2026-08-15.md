# START PROMPT — R4: BUG-096, MCP-экспорт скачивается по объявленному URL

**Дата:** 2026-08-15 · **Сессия:** R4 по [`PLAN_REMEDIATION_BOT_MCP_2026-08-12.md`](PLAN_REMEDIATION_BOT_MCP_2026-08-12.md) §R4, §4 · **Баг:** [BUG-096](BUG_LOG.md) (Medium — F2 export)
**Ветка:** prefix `cursor/fix-bug096-export-dispatch-r4`

**Goal (одной строкой):** `download_url`, который вернул MCP-`export_channel`, открывается (200), и две выгрузки одного уровня больше не пишут в один файл.

> Рабочий режим: коммит / PR — только по явному запросу владельца ([`AGENTS.md`](../../AGENTS.md)). Прод: правки только по явному GO; чтения разрешены. Основной режим — **This Mac**: PR standard (`TEST_POSTGRES=1`) требует живого Postgres, в облаке его нет. Перед merge — **max local** (`TEST_TESTCONTAINERS=1`) **и** `COMPOSE_INTEGRATION=1` (дефект межконтейнерный). Первый шаг — `bash scripts/dev_doctor.sh`. **Песочница:** `ssh prod` и `gh` требуют `required_permissions: ["all"]`; `dev_doctor` из песочницы печатает ложный `MISS ssh prod`. R4 — **не** деплой-сессия. Деплой потом заденет `tg_parser` **и** `mcp` (урок R10: recreate parser сдвигает hourly tick — только после конца тика и по GO). Bot-арм BUG-099, R3, объектное хранилище — **вне scope**.

---

## 0. Opener (вставить в новый чат)

> Стартую сессию R4 — MCP-экспорт перестаёт отдавать мёртвый `download_url` (BUG-096, вариант b: HTTP-dispatch по ADR-0007).
>
> Прочитай:
> 1. `docs/notes/START_PROMPT_FIX_BUG096_EXPORT_DISPATCH_R4_2026-08-15.md` — **этот файл целиком**
> 2. `docs/notes/BUG_LOG.md`, запись **BUG-096** — 404, столкновение `file_path`, решение владельца (b), F-03
> 3. [`docs/adr/0007-mcp-scheduler-dispatch.md`](../adr/0007-mcp-scheduler-dispatch.md) — MCP/Bot as thin HTTP clients; образец уже живёт в `trigger_*`
> 4. `docs/notes/PLAN_REMEDIATION_BOT_MCP_2026-08-12.md` §R4 (scope), §4 (очередь: R9 закрыта, эта — следующая; дальше R3)
> 5. `tests/README.md` — default / PR standard / max local / `COMPOSE_INTEGRATION=1`
>
> Начни с `bash scripts/dev_doctor.sh`, затем §3.1 (путь по `job_id`), §3.2 (MCP больше не вызывает `_run_export_job`), §3.3 (ноль импортов из `api.routes.export` в `mcp_server.py`). Вариант (a) общий том, (c) object storage, bot-арм BUG-099, форма ответов R3 — **вне scope**.
>
> Строки в плане — на `f005f93` / ранний draft. Ниже — перечитанные 2026-08-15 с `main` (`0a463d8`). Ориентируйся на имена символов; если код уже не такой — скажи вслух, не чини исчезнувшее.

**Состояние на входе** (сверить, а не поверить; inspect 2026-08-15 утро, после owner-smoke BUG-094):

| Факт | Что ждать на 2026-08-15 |
|---|---|
| Очередь | R9 закрыта (`8d870e5` / `#424`, owner-smoke `0a463d8`). Следующая — эта. Дальше R3. Параллельно: R12, R6. Bot-арм BUG-099 открыт, не чинить |
| Решение владельца | Вариант **(b)** HTTP-dispatch. **(a)** общий том и **(c)** object storage отклонены. R4a+R4b **слиты** — не дробить заново |
| `main` vs прод | `origin/main` = `0a463d8` (docs smoke R9). Прод-хост мог остаться на `0137b70` до docs-only pull — это не drift кода. Образы: `mcp`/`tg_bot` `2478721db563`, `tg_parser` R2 `63de8a1123c5` |
| Латентность | 404 воспроизведён 2026-08-12: MCP-джоба `1561b9da-…` completed + URL, GET → 404; HTTP-джоба `9e3408af-…` → 200. Обе нарочно оставлены, `file_path` у обеих `output/raw_messages.json` |
| Workaround | Экспорт для скачивания — через HTTP, не MCP. После фикса workaround снимается |
| Не ждать | Пересечения с R12/R6 нет. Bot-арм не блокирует. `get_default_admin()` в `_exec_export_channel` **не трогать** |

---

## 1. Почему эта сессия существует и почему она сейчас

Фича заканчивается успехом и вручает мёртвую ссылку. `get_export_status` говорит `completed` + `file_size`, GET по `download_url` — 404. HTTP-тот же канал скачивается. Хуже, чем громкий отказ: нечему поверить, кроме самой ссылки.

Два дефекта в одном пути, оба живы:

1. **Writer ≠ reader.** MCP пишет файл в `tg_parser_mcp`, URL отдаёт `tg_parser`. Тома `output/` нет: `settings.output_dir` = `Path("output")` (cwd контейнера, `/app/output`), а bind `./data:/app/data` этот каталог не покрывает. Общий том лечил бы симптом и оставлял бы импорт приватного символа через границу `api` → `mcp`.
2. **`file_path` без `job_id`.** Оба писателя кладут `output/raw_messages.json`. Две выгрузки одного уровня перетирают файл внутри контейнера. Это отдельно от split'а и переживает любой фикс тома.

Почему (b), а не «одна из трёх опций»: [`mcp_server.py`](../../tg_parser/mcp_server.py) — единственный write-инструмент MCP, который не тонкий HTTP-клиент. Соседние `trigger_*` уже ходят через [`pipeline_dispatch_client`](../../tg_parser/services/pipeline_dispatch_client.py) по [ADR-0007](../adr/0007-mcp-scheduler-dispatch.md). В известных deviations [ADR-0004](../adr/0004-hexagonal-architecture-and-module-boundaries.md) экспорта нет — это не задокументированный shortcut, а дыра. (b) возвращает к принятому ADR.

R9 закрыта. R4 ничего не блокирует и ничем не блокируется. Bot-арм — hardening, не гейт этой сессии.

---

## 2. Что установлено (не переоткрывать)

1. **Вариант выбран.** (b) HTTP-dispatch. (a) общий том — нет. (c) object storage — нет. Не предлагать заново. Не добавлять volume `output/` «на всякий случай» — это (a) контрабандой.
2. **Одна сессия, не две.** Дробление R4a/R4b существовало, пока выбор (a)/(b)/(c) был открыт. Выбор сделан — путь и dispatch едут вместе, иначе путь придётся трогать дважды.
3. **Писателей три, не два.** API [`_run_export_job`](../../tg_parser/api/routes/export.py) + `_resolve_export_file`; MCP сегодня вызывает ту же `_run_export_job` у себя в процессе; bot [`_exec_export_channel`](../../tg_parser/bot/tools.py) собирает путь сам, **джобу не создаёт**, файл шлёт в чат. Bot остаётся синхронным. Ему нужна только уникальность каталога, не HTTP-dispatch.
4. **`POST /api/v1/export` уже создаёт джобу.** [`start_export`](../../tg_parser/api/routes/export.py) `220–281`: uuid, `Job` в store, `background_tasks.add_task(_run_export_job, …)`, ответ `pending`. MCP сегодня **дублирует** это у себя (`3045–3066`: свой `create_job` + `create_task(_run_export_job)`). После фикса MCP **не** создаёт `Job` и **не** запускает task. Только POST, `job_id` из ответа API. Иначе две строки на один вызов.
5. **`get_export_status` уже кросс-контейнерный.** `Job` живёт в Postgres. 404 — про файл, не про запись. HTTP-GET статуса **не** делать: `ExportResponse` не несёт `channel_id` / `file_size`, а `ExportStatusResult` несёт — растягивать HTTP-контракт в этой сессии нельзя. «Сюда же get_export_status» из плана = убрать `from tg_parser.api.routes.export import …`. Deliverable плана «последний импорт приватного символа `api`» — это `_run_export_job` / `_resolve_job_level` / `_export_job_visible_to`, **не** `api.job_store` / `api.schemas` / `api.metrics`. Хелперы вынести в модуль вне `api.routes` (например `tg_parser/services/export_job_access.py`); API и MCP импортируют оттуда. `job_store` MCP читать может. [`test_bug101_export_job_owner.py`](../../tests/test_bug101_export_job_owner.py) импортирует `_export_job_visible_to` из `api.routes.export` (четыре места) — обновить импорт на новый модуль **или** оставить однострочный реэкспорт в `export.py`. Молча обещать «тесты зелёные» без одного из двух — нельзя.
6. **`run_export` пишет фиксированные имена в `output_dir`.** [`export_service.py`](../../tg_parser/services/export_service.py) `183–191`: `raw_messages.{json,ndjson}` / `kb_entries.ndjson` / `topics.json`. Сигнатуру не расширять. `run_export` уже делает `mkdir(parents=True)`. Уникальность = `output_dir=str(Path(settings.output_dir) / job_id)` (у bot — `Path(settings.output_dir) / <uuid4>`). **`Path(...)` обязателен:** F2-тесты патчат `settings.output_dir` в `str` — голый `settings.output_dir / uuid` даст `TypeError`. `_resolve_export_file` резолвит тот же путь.
7. **Старые джобы.** Session #1 оставила `1561b9da-f93d-4db2-ab33-91da6c8c9ab3` и `9e3408af-714e-4960-918f-b4abda887495` с `file_path = output/raw_messages.json`. [`download_export`](../../tg_parser/api/routes/export.py) `350–355` уже открывает `job.file_path` как есть. Так и оставить: новый layout только для новых джоб. Тест: completed job с плоским относительным `file_path`, файл на месте → 200. Не изобретать `output/{old_job_id}/…` для старых строк.
8. **Образец dispatch уже есть.** [`post_pipeline_trigger`](../../tg_parser/services/pipeline_dispatch_client.py) `74–170`: `pipeline_dispatch_base_url` (default `http://tg_parser:8000`), `extract_mcp_dispatch_api_key`, `X-API-Key`, таймаут 30 с, классы ошибок. Для экспорта — соседняя функция в **том же** модуле (`post_export` или имя по месту), тот же base URL и ключ. Не второй `*_base_url`. Не пихать export в `PipelineJobKind` — это enum pipeline-trigger.
8a. **`X-API-Key` — load-bearing, compose его не проверяет.** CI compose ставит `MCP_AUTH_ENABLED=false` и `API_KEY_REQUIRED=false` ([`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) ~207, [`docker-compose.yml`](../../docker-compose.yml) `152`). POST без заголовка там проходит как default admin. На проде `API_KEY_REQUIRED` включён — тот же клиент без ключа даст **401**, джоба не создастся, URL снова мёртвый. Копировать `trigger_*` целиком: `extract_mcp_dispatch_api_key` → заголовок. [`resolve_current_user`](../../tg_parser/api/auth.py) `65–70` уже принимает forwarded MCP bearer через `resolve_user_by_auth("mcp_token", …)` — новый маппинг не нужен, токен не обязан быть в `API_KEYS`. Unit-тест клиента **обязан** assert'ить `X-API-Key`, как [`tests/test_pipeline_dispatch_client.py`](../../tests/test_pipeline_dispatch_client.py) `90`. Compose-happy-path этого не заменяет.
9. **Локальный ownership-check на MCP оставить.** Как у `trigger_*`: `assert_channel_access` до POST, чужой канал → `status="rejected"`, `job_id=""` без HTTP. API всё равно проверит ещё раз. Тест `test_mcp_export_channel_ownership_denied` должен остаться зелёным. HTTP-ошибки dispatch (401/403/4xx/5xx) → тот же `status="rejected"`, `job_id=""`, причина в `message`. Не вводить `failed` / `error_class` в `ExportChannelResult` — клиентский контракт `pending` | `rejected`.
10. **Существующие MCP-тесты патчат `_run_export_job`.** [`test_f2_parse_only_export.py`](../../tests/test_f2_parse_only_export.py) `test_mcp_export_channel_submits_job` / `_defaults_to_raw_json` (`1088–1167`) — после фикса они красные **правильно**. Переписать на мок dispatch-клиента: POST ушёл, локальный `create_job` не вызывался. Не сохранять патч исчезнувшего импорта.
11. **Bot-тесты пишут в `Path(output_dir) / "raw_messages.json"`.** Если bot передаёт в `run_export` уже уникальный каталог, фейки продолжают работать. Проверить, что два последовательных bot-экспорта не делят путь. `get_default_admin()` на строке `3676` не трогать.
12. **CI compose job не на каждый PR.** [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) `compose-integration` `169–172`: `schedule` или `push` в `main` (BUG-059, стоимость). Гейт **не** расширять на все PR. Добавить download-плечо в тот же job / в [`test_compose_pipeline_dispatch_integration.py`](../../tests/test_compose_pipeline_dispatch_integration.py). Сессия **обязана** прогнать `COMPOSE_INTEGRATION=1` локально до merge — иначе класс снова невидим.
13. **Privacy.** `raw_payload` не входит ни на одном level. Прод-smoke и compose-assert это проверяют. Не ослаблять.
14. **Docs этой сессии.** [`MCP_AGENT_GUIDE.md`](../MCP_AGENT_GUIDE.md) `377–379` и `948–951` станут правдой — оговорку «MCP → 404» **не** писать (AUDIT §6.2 ждал фикса; пункт можно пометить снятым). В BUG-096 — факт после merge/деплоя, статус `resolved` только когда URL живой на проде. Остальной AUDIT §6 (F5-C, счётчики README) — R3. `TEST_ACCESS` этот баг не упоминает.
15. **HTTP `export` и CLI** — не третья копия бага. CLI сам выбирает `--output`. Не переписывать.

---

## 3. Scope — строго в этом порядке

Строки ниже — перечитанные 2026-08-15 с `0a463d8`.

### 3.1 Red: два экспорта одного уровня → два файла

**Сегодня** (`_resolve_export_file` `83–97`, `_run_export_job` `125–148`):

```
output_dir = Path(settings.output_dir)          # "output"
export_file = output_dir / "raw_messages.json"  # без job_id
job.file_path = str(export_file)
```

Два `POST /api/v1/export` подряд на один `channel_id`+`level` → второй затирает первый.

**Нужно:** `output/{job_id}/raw_messages.json` (и аналоги для processed/full). `run_export(..., output_dir=str(Path(settings.output_dir) / job_id))`. `run_export` сам делает `mkdir`. `job.file_path` — этот путь. `download_url` по-прежнему `/api/v1/export/download/{job_id}`.

Тест (новый файл, например `tests/test_bug096_export_job_path.py`): два последовательных HTTP-экспорта одного канала и уровня → `file_path` разные, оба файла читаются. Red до правки `_resolve_export_file` / `_run_export_job`.

### 3.2 Red: MCP не исполняет джобу у себя

**Сегодня** (`export_channel` `2993–3066`):

```
from tg_parser.api.routes.export import _run_export_job
job_store.create_job(...)
create_task(_run_export_job(job_id, request))
```

**Нужно:** как `_mcp_trigger_pipeline_job` `2093–2118`: ключ через `extract_mcp_dispatch_api_key` → `X-API-Key`, POST `/api/v1/export` с тем же телом (`channel_id`, `level`, `format`, `from_date`, `to_date`), вернуть `job_id` / `pending` из ответа. HTTP 4xx/5xx → `status="rejected"`, `job_id=""`, причина в `message` (не `pending`, не новый enum). Локальный `create_job` / `create_task` / `_background_tasks` на этом пути — ноль.

Тест: мок клиента, не мок `_run_export_job`. Assert: клиент вызван **с `X-API-Key`**, `ensure_job_store_initialized` на submit-пути нет. Ownership-denied без клиента — как сейчас. Образец заголовка — `tests/test_pipeline_dispatch_client.py`.

### 3.3 Ноль импортов `api.routes.export` из `mcp_server.py`

**Сегодня** ещё `get_export_status` `3103`: `_export_job_visible_to`, `_resolve_job_level`.

Вынести оба хелпера из `api/routes/export.py`. API-роуты и MCP импортируют новый модуль. Поведение BUG-101 (`Job.client == user.name`, чужой/unknown = один 404 / `status="unknown"`) не менять. В [`test_bug101_export_job_owner.py`](../../tests/test_bug101_export_job_owner.py) четыре импорта `_export_job_visible_to` из `api.routes.export` — перецелить на новый модуль или оставить реэкспорт в `export.py`; без этого файл красный.

Сторож класса: AST или простой тест «в `mcp_server.py` нет `tg_parser.api.routes.export`». `api.job_store`, `api.schemas`, `api.metrics` оставить — это не «приватный символ `api`» из deliverable плана.

### 3.4 Bot: уникальный каталог, джобы нет

**Сегодня** `3756–3762` — те же фиксированные имена в `settings.output_dir`.

`run_export` в `Path(settings.output_dir) / uuid4()`. В чат уходит файл из этого каталога. Большой файл (>50 MB) по-прежнему не шлётся, в summary — новый путь. HTTP и `Job` не появляются. `current_user or await get_default_admin()` не трогать.

Тест: два последовательных `_exec_export_channel` не делят `export_file`.

### 3.5 Старый `file_path` скачивается

`download_export` открывает `job.file_path`, если файл есть. Тест с плоским путём (как у джоб session #1). Не резолвить старые id в новый layout.

### 3.6 Переписать F2 MCP-тесты, которые держат старый путь

`test_mcp_export_channel_submits_job`, `test_mcp_export_channel_defaults_to_raw_json` — мок dispatch. Invalid level/format и ownership — без изменений по смыслу.

Bot-тесты: поправить только если сломает смена каталога; не переписывать delivery/size-gate.

### 3.7 Compose: download-плечо

В [`test_compose_pipeline_dispatch_integration.py`](../../tests/test_compose_pipeline_dispatch_integration.py) (или соседний файл с теми же маркерами): MCP `export_channel` на засеянный канал → poll `get_export_status` до `completed` → `GET http://127.0.0.1:8000{download_url}` → **200**, путь содержит `job_id`. **Пустой канал для privacy не годится:** `{}` / `[]` без `raw_payload` — ложный зелёный. Засеять хотя бы одну raw-строку (или подложить фикстурный файл с полем, которого в выгрузке быть не должно) и assert'ить, что ключа `raw_payload` в теле нет. Нулевой файл допустим только как проверка «не 404»; privacy — отдельный assert на непустом теле.

Гейт CI-джобы не менять. Локально до merge:

```bash
COMPOSE_INTEGRATION=1 .venv/bin/python -m pytest \
  tests/test_compose_pipeline_dispatch_integration.py \
  -m "integration and compose_only" -q
```

плюс max local (`TEST_POSTGRES=1 TEST_TESTCONTAINERS=1`).

### 3.8 Docs

`MCP_AGENT_GUIDE` `377–379` / `948–951`: утверждение о download оставить (оно станет верным). Не добавлять оговорку про 404. В BUG-096 — статус после merge/деплоя; workaround снять когда URL живой на проде. AUDIT §6.2 можно пометить «снято фиксом», остальное §6 не трогать.

### 3.9 Что не ломать / вне scope

- Bot-арм BUG-099 (`get_default_admin` в исполнителях, в т.ч. export).
- R3 / BUG-102 / BUG-098a, счётчики README, секции F5-C.
- Общий том `output/`, S3, стриминг вместо файла.
- `ExportResponse` shape, пагинация, `process.py` jobs.
- Гейт `compose-integration` на каждый PR.
- Recreate прод-контейнеров в этой сессии. `docs/methodology/**`, `pyproject.toml`, `requirements.txt`.
- Вариант (a)/(c). Дробление обратно на R4a/R4b.

---

## 4. Acceptance criteria

1. MCP `export_channel` не импортирует и не вызывает `_run_export_job`. Submit = HTTP POST `/api/v1/export` с `X-API-Key` (unit-тест заголовка зелёный).
2. В `mcp_server.py` нет `from tg_parser.api.routes.export import …`. `api.job_store` остаётся.
3. Два последовательных экспорта одного канала и уровня → два разных файла, оба скачиваются.
4. `download_export` для джобы с плоским старым `file_path` → 200, если файл на диске.
5. Bot пишет в уникальный подкаталог, остаётся sync, в чат по-прежнему шлёт файл (или size-gate).
6. Compose-тест download-плеча зелёный локально (`COMPOSE_INTEGRATION=1`). Default + PR standard зелёные. Перед merge — max local.
7. Privacy: в скачанном **непустом** теле нет `raw_payload` (пустой `{}` / `[]` не считается).
8. R3 и bot-арм не начаты. Контейнеры на проде эта сессия не recreate.

---

## 5. Ограничения (CRITICAL)

- Коммит / PR / прод — только по явному запросу / GO.
- Не общий том. Не object storage. Не второй dispatch-base-url.
- Не создавать `Job` в MCP и потом ещё раз в API.
- Не переводить `get_export_status` на HTTP из-за несовпадения shape. Не вычищать `api.job_store` «за компанию».
- Не отправлять POST без `X-API-Key`: compose это проглотит, прод — нет.
- Не трогать `get_default_admin()` в bot.
- Не менять `if:` у CI compose job.
- Recreate `tg_parser` на проде — отдельный GO, после конца incremental-тика.
- Ноль правок `docs/methodology/**`, `pyproject.toml`, `requirements.txt`.

---

## 6. Финальный ответ сессии

Одним сообщением: как MCP теперь диспатчит (клиент, URL, кто создаёт `Job`); как выглядит новый `file_path`; что стало с импортами `api.routes.export`; как bot уникализирует каталог; что с старыми джобами; какие тесты красные→зелёные (unit + compose); прогнан ли max local и `COMPOSE_INTEGRATION=1`; что записано в BUG-096 / guide. Отдельной строкой: деплой не делался — нужен GO на recreate `tg_parser`+`mcp` (tick сдвинется); bot-образ — если хотите path-fix на боте в том же выкате. Вне сессии: bot-арм BUG-099 и R3.

---

## 7. Ссылки

- [BUG-096](BUG_LOG.md) — 404 + collision; вариант (b); F-03.
- [ADR-0007](../adr/0007-mcp-scheduler-dispatch.md) — thin HTTP client.
- [ADR-0004](../adr/0004-hexagonal-architecture-and-module-boundaries.md) — граница `api` → `mcp`; экспорта в deviations нет.
- [`PLAN_REMEDIATION_BOT_MCP_2026-08-12.md`](PLAN_REMEDIATION_BOT_MCP_2026-08-12.md) §R4, §1b, §4.
- [`AUDIT_DOCUMENTATION_2026-08-12.md`](AUDIT_DOCUMENTATION_2026-08-12.md) §6.2 — оговорка к `download_url`, снимается этим фиксом.
- `tg_parser/api/routes/export.py` — `_resolve_export_file`, `_run_export_job`, `start_export`, `download_export`.
- `tg_parser/mcp_server.py` — `export_channel` `2959–3088`, `get_export_status` `3091–3141`.
- `tg_parser/bot/tools.py` — `_exec_export_channel` `3653+`, путь `3756–3762`.
- `tg_parser/services/pipeline_dispatch_client.py` — образец POST.
- `tg_parser/services/export_service.py` — `run_export`, фиксированные имена файлов.
- `tests/test_f2_parse_only_export.py`, `tests/test_bug101_export_job_owner.py`, `tests/test_compose_pipeline_dispatch_integration.py`.
- `tests/README.md` — PR standard + max local + compose.
