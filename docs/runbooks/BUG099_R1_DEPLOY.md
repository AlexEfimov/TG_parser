# Runbook — BUG-099 (R1): резолв идентичности MCP перестаёт деградировать в admin

**Создан:** 2026-08-14 (сессия R1). **Статус: ВЫПОЛНЕНО 2026-08-14** по GO владельца — merge `#421` → `963b16e`, smoke §3 пройден в ту же минуту. UUID без строки / с ошибкой БД даёт `PermissionError`, не default admin. Legacy не-UUID по-прежнему admin. Живой admin-токен жив.

**Что деплоим:** fail-closed резолв личности на MCP ([BUG-099](../notes/BUG_LOG.md), MCP-половина). Два случая, слитые в один `return await get_default_admin()`, разведены: форма UUID проверяется `uuid.UUID` (без БД), исход пишется в `tg_mcp_identity_resolve_total{outcome=…}`. `MCP_AUTH_ENABLED=true` + пустой `MCP_AUTH_TOKENS` теперь легальный DB-only старт; на этом деплое `.env` **не** трогали.

**Не docs-only.** Меняется `resolve_mcp_user` и cabinetry `create_mcp_server`. **Миграции нет.** Пересоздаётся **ровно** `mcp` (`tg_parser_mcp`). `tg_parser` и `tg_bot` не трогаем: правка их не касается, а recreate `tg_parser` сдвинул бы фазу hourly incremental-pipeline (урок R10).

---

## 0. Перед деплоем

| Проверка | Команда / ожидание | Факт 2026-08-14 |
|---|---|---|
| Прод и `origin/main` сходятся после мержа | `ssh prod 'cd /home/user/TG_parser && git rev-parse --short HEAD'` | ✅ после `git pull --ff-only`: прод `9013b4e` → **`963b16e`** |
| Точка отката **MCP** | тег на крутящемся образе MCP, не parser | ✅ `tg_parser:pre-r1-mcp-2026-08-14` → **`350fe325ee7f`** (контейнер жил с 2026-08-12). **Не** путать с `tg_parser:pre-r1-2026-08-14` — тот указывает на parser `bdb3292` (R11) |
| Backup | `pg_dump` до recreate | ✅ `data/backups/postgres_pre_r1_20260814_110220.sql.gz`, **368M** |
| Эскалировать некого | 5 строк `user` без `user_auth_mappings`; живой `mcp_token` только у admin | ✅ то же на входе и после smoke (`list_users` — 6 пользователей, credential не добавляли) |
| `.env` | `MCP_AUTH_ENABLED=true`, `MCP_AUTH_TOKENS` непустой | ✅ не меняли; после recreate `tokens_nonempty=True` |

---

## 1. Деплой

Процедура — [`PRODUCTION_DEPLOYMENT.md`](../../PRODUCTION_DEPLOYMENT.md) § Updating. Пересоздавать контейнер, **не** `restart` (BUG-078); `up -d` без изменения rendered spec не пересоздаёт, поэтому `--force-recreate` обязателен (BUG-090). Миграции нет — `db upgrade` не вызываем.

```bash
ssh prod 'cd /home/user/TG_parser && git pull --ff-only origin main'
ssh prod 'cd /home/user/TG_parser && docker compose build tg_parser'
# образ общий (tg_parser:latest); running parser/bot держат свои старые id, пока их не recreate
ssh prod 'cd /home/user/TG_parser && docker compose up -d --no-deps --force-recreate mcp'
```

Фактически: прод HEAD `9013b4e` → **`963b16e`**, новый образ **`5f6939dc9a5c`**, контейнер `tg_parser_mcp` пересоздан **11:18:44 UTC**, `healthy` к **11:19:04 UTC**. `tg_parser` остался на `bdb3292` (R11, 4 ч, healthy). `tg_bot` остался на `94b71337` (21 ч, healthy). Окно логов MCP с 2026-08-12 стёрто recreate — ожидаемо: замер `static_fallback_used=0` уже записан в BUG-099.

---

## 2. Настройки — ничего

Новых ключей `.env` нет. Пустой `MCP_AUTH_TOKENS` на этом деплое **не** выставляли: DB-only режим разрешён кодом, но снимать живой static-токен — отдельное решение, замер его не лицензирует.

---

## 3. Smoke (сразу, не тиком)

| Проверка | Ожидание | Факт 2026-08-14 11:19 UTC |
|---|---|---|
| Рабочий admin-токен | `whoami` / `list_users` живы | ✅ `whoami` → admin `c59d42b4`, 19 каналов; `list_users` — те же 6 пользователей |
| Выдуманный UUID | `PermissionError`, не admin | ✅ in-process `resolve_mcp_user("00000000-0000-4000-8000-000000000099")` → `PermissionError` («user UUID that did not resolve») |
| Legacy static | не-UUID по-прежнему admin | ✅ `resolve_mcp_user("claude-desktop")` → `role=admin`, `allowed=None`; в логе `static_fallback_used` |
| Счётчик | ряд на MCP `/metrics` | ✅ `tg_mcp_identity_resolve_total{outcome="resolved"} 1` после живого `whoami`. Инкремент `unresolved_uuid` на running-процессе нет: отказ гоняли через `exec`, не через HTTP |

`/health` у MCP отвечает `{"status":"degraded","database":"not_initialized"}` при HTTP 200 — это **не регресс R1**: Docker healthcheck смотрит на код ответа, синглтон `Database` в MCP-процессе не инициализируется (инструменты ходят через `user_repo()`). Так было и до этой сессии.

---

## 4. Что этот деплой НЕ закрывает

- **Bot-арм** — закрыт 2026-08-16 (`#442` → `c74fae0`). Протокол — [`BUG099_BOT_ARM_DEPLOY.md`](BUG099_BOT_ARM_DEPLOY.md).
- **HTTP-близнец** `api/auth.py` 56–63 — диспозиция в BUG-099, код не трогали.
- **60-секундный `_CACHE_TTL`** — принят как есть: после фикса удалённый пользователь получает отказ, не admin.
- **Снятие `MCP_AUTH_TOKENS` на проде** — замер (~12 аутентифицированных вызовов) этого не разрешает.

---

## 5. Откат

Только MCP. Parser и bot не откатывать этим тегом.

```bash
ssh prod 'docker tag tg_parser:pre-r1-mcp-2026-08-14 tg_parser:latest \
  && cd /home/user/TG_parser && docker compose up -d --no-deps --force-recreate mcp'
```

Цена отката — UUID без строки / с ошибкой БД снова становится admin. Миграции откатывать нечего. Полное восстановление БД — из backup §0 (на этом деплое схема не менялась).

---

## 6. Ссылки

- [BUG-099](../notes/BUG_LOG.md) — механизм, замер 08-13, диспозиции, smoke.
- [`START_PROMPT_FIX_BUG099_MCP_IDENTITY_FAILOPEN_R1_2026-08-13.md`](../notes/START_PROMPT_FIX_BUG099_MCP_IDENTITY_FAILOPEN_R1_2026-08-13.md)
- [`PRODUCTION_DEPLOYMENT.md`](../../PRODUCTION_DEPLOYMENT.md) § Updating — `--force-recreate`, не `restart`.
- [`BUG097_R11_DEPLOY_AND_WATCH.md`](BUG097_R11_DEPLOY_AND_WATCH.md) — предыдущий деплой; оттуда «не трогать MCP» (окно логов) и «не recreate `tg_parser` без нужды» (фаза тика).
