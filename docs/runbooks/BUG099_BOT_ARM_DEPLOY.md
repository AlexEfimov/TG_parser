# Runbook — BUG-099 (bot-арм): исполнитель без личности больше не становится admin

**Создан:** 2026-08-16 (hardening bot-арма). **Статус: ВЫПОЛНЕНО 2026-08-16** по GO владельца — merge `#442` → `c74fae0`, recreate **только** `tg_bot`. `tg_parser` и `mcp` не трогали: hourly incremental-pipeline не сдвигался (урок R10).

**Что деплоим:** fail-closed личность на bot-исполнителях ([BUG-099](../notes/BUG_LOG.md), хвост после R1). `user = current_user or await get_default_admin()` в 34 из 35 исполнителей заменён на `_require_current_user`: `current_user=None` → builtin `PermissionError`. `_exec_get_llm_config` без личности жив. Живой путь через `UserResolutionMiddleware` не менялся.

**Не docs-only.** Меняется `tg_parser/bot/tools.py` и комментарий в `handlers.py`. **Миграции нет.** `.env` не трогали.

---

## 0. Перед деплоем

| Проверка | Факт 2026-08-16 |
|---|---|
| Прод до pull | хост `302fd09` (`#440`). Образ всех трёх — R6 `5924dcfc43c3…`, healthy с 10:22–10:23 UTC |
| Откат **бота** | тег на крутящемся образе **до** build: `tg_parser:pre-bug099-bot-2026-08-16` → **`5924dcfc43c3…`** |
| `.env` / миграции | не трогали |
| Allowlist | старт бота печатает `Allowed users: 2` — `BOT_ALLOWED_USERS` на хосте **непустой**. Это замер, не доктрина |

---

## 1. Деплой

Процедура — [`PRODUCTION_DEPLOYMENT.md`](../../PRODUCTION_DEPLOYMENT.md) § Updating. Пересоздавать контейнер, **не** `restart` (BUG-078); `--force-recreate` обязателен (BUG-090). Миграции нет — `db upgrade` не вызывали. `docker compose build tg_parser` собирает общий образ; running parser/mcp держат старый id, пока их не recreate.

```bash
ssh prod 'cd /home/user/TG_parser && git pull --ff-only origin main'
ssh prod 'cd /home/user/TG_parser && docker compose build tg_parser'
ssh prod 'cd /home/user/TG_parser && docker compose --profile bot up -d --no-deps --force-recreate tg_bot'
```

Фактически: прод HEAD `302fd09` → **`c74fae0`**, новый образ **`d5699530e59e…`** только на `tg_bot`. Контейнер пересоздан **13:33:36 UTC**, `healthy` к **~13:33:50 UTC**. `tg_parser` остался на `5924dcfc43c3…` (`StartedAt` 10:22:57 UTC). `mcp` остался на `5924dcfc43c3…` (`StartedAt` 10:23:03 UTC).

---

## 2. Настройки — ничего

Новых ключей `.env` нет. Не-admin credential не заводили.

---

## 3. Smoke (сразу, не тиком)

| Проверка | Ожидание | Факт 2026-08-16 13:33 UTC |
|---|---|---|
| Bot health | `{"status":"ok"}` | ✅ in-container `http://127.0.0.1:8081/health` → `{"status":"ok"}`. Docker health = healthy |
| Хелпер в установленном bot | `_require_current_user` есть; fallback-строк 0 | ✅ 34 вызова `_require_current_user`; `current_user or await get_default_admin` = 0 |
| Голый `_exec_search(..., current_user=None)` | `PermissionError`, retrieval не идёт | ✅ `PermissionError` («without a resolved current_user») |
| `_exec_get_llm_config(..., current_user=None)` | конфиг без ошибки | ✅ `config` есть, `error` нет |
| Parser / MCP | тот же образ и `StartedAt` | ✅ оба `5924dcfc43c3…`, started 10:22 / 10:23 |
| Старт бота | allowlist, digest, watchlist flush | ✅ `Allowed users: 2`; 4 digest jobs; `watchlist_instant_flush` interval 300, watermark `2026-08-13T00:00:00+00:00` |
| Живой admin в Telegram | `/start` или «кто я» отвечает | не гоняли из этой сессии — нужен живой чат владельца |

---

## 4. Что этот деплой НЕ закрывает

- **HTTP-близнец** `api/auth.py` — диспозиция в BUG-099, код не трогали.
- **60-секундный `_CACHE_TTL`** — принят как есть.
- **Middleware empty-allowlist → admin** — dev-режим, не этот баг. На этом хосте allowlist непустой (`Allowed users: 2`).
- **CLI `get_default_admin`** — вне scope.

---

## 5. Откат

Только bot. Parser и MCP не откатывать этим тегом.

```bash
ssh prod 'docker tag tg_parser:pre-bug099-bot-2026-08-16 tg_parser:latest \
  && cd /home/user/TG_parser && docker compose --profile bot up -d --no-deps --force-recreate tg_bot'
```

Цена отката — прямой `_exec_*` с `current_user=None` снова становится admin. Миграции откатывать нечего.

---

## 6. Ссылки

- [BUG-099](../notes/BUG_LOG.md); стартовый промпт: [`START_PROMPT_FIX_BUG099_BOT_IDENTITY_FAILOPEN_2026-08-16.md`](../notes/START_PROMPT_FIX_BUG099_BOT_IDENTITY_FAILOPEN_2026-08-16.md).
- MCP-половина (закрыта 2026-08-14): [`BUG099_R1_DEPLOY.md`](BUG099_R1_DEPLOY.md).
- [`PRODUCTION_DEPLOYMENT.md`](../../PRODUCTION_DEPLOYMENT.md) § Updating — `--force-recreate`, не `restart`; bot под `--profile bot`.
