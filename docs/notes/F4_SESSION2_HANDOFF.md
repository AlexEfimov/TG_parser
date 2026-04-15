# F4 Multi-Tenancy Session 2 — Handoff

**Дата**: 15 апреля 2026  
**Ветка**: `feature/f4-multi-tenancy-phase1-2`  
**Коммит**: `be6616a` — `feat(f4): implement multi-tenancy Phase 3 + Phase 4`  
**Тесты**: 1105 passed, 42 skipped (PostgreSQL-only), 0 failures

---

## Что сделано в Session 2

### Phase 3 — Channel Ownership Enforcement ✅

| Компонент | Изменения |
|-----------|-----------|
| `tg_parser/auth/ownership.py` | **Новый файл.** `PermissionDenied`, `assert_channel_access`, `assert_admin`, `check_channel_limit` |
| `tg_parser/auth/__init__.py` | Re-export новых хелперов |
| Bot chain | `main.py` → `UserResolutionMiddleware`, `handlers.py` → `current_user` param, `agent.py` → пробрасывает `current_user`, `tools.py` → все `_exec_*` принимают `current_user` |
| MCP tools | Все tools принимают `ctx: Context`, резолвят `CurrentUser` через `resolve_mcp_user` |
| API routes | Все routes переведены с `verify_api_key` на `Depends(resolve_current_user)` |
| Admin-only | `set_llm_config`, `reset_llm_config`, `reload_prompts`, все `/agents/*` endpoints |
| Channel ownership | `add_channel` → `owner_id=user.id`, `remove/pause/resume` → `assert_channel_access`, `list_channels` → scoped |
| Per-user limits | `MAX_ACTIVE_SOURCES` удалён, заменён на `user.max_channels` |
| Exception handler | `PermissionDenied` → HTTP 403 в `api/main.py` |

### Phase 4 — Scoped Data Access ✅

| Компонент | Изменения |
|-----------|-----------|
| Services | `retrieval_service.search/answer`, `analytics_service`, `channel_service`, `topic_linking_service` — все принимают `allowed_channel_ids: list[str] \| None` |
| Repo: TopicCardRepo | Новый метод `list_by_channels()` — SQL LIKE фильтрация по `sources_json` |
| Repo: EmbeddingRepo | `SET ivfflat.probes = 20` при наличии `channel_ids` фильтра |
| MCP data tools | `search_knowledge_base`, `ask_question`, `list_topics`, `get_topic_details`, `get_document`, `get_related_topics`, `get_cross_channel_stats` — передают `user.allowed_channel_ids` |
| Bot data tools | `_exec_search`, `_exec_ask`, `_exec_list_topics`, `_exec_get_document` и др. — scoping по `current_user.allowed_channel_ids` |
| API data routes | `rag.py`, `topics.py`, `documents.py`, `export.py`, `process.py`, `channels.py` — scoping + access checks |
| `/health`, `/status` | Остались публичными (без auth) |

### Тесты ✅

| Файл | Тестов | Покрытие |
|------|--------|----------|
| `tests/test_f4_ownership.py` | 21 | Ownership helpers, MCP add/remove/pause/resume/list, admin-only, bot add_channel |
| `tests/test_f4_scoped_access.py` | 15 | Service scoping, bot document access, bot admin-only, API admin-only |
| `tests/test_f4_vector_search_isolation.py` | 9 | SQL channel filter, IVFFlat probes, channel intersection, cross-channel topics |
| Обновлены existing | 5 файлов | `test_agents_observability`, `test_bot_tools_v12`, `test_mcp_management`, `test_mcp_server`, `test_f5a_topic_rag` |

---

## Что осталось сделать

### Phase 5 — User Management Tools + Migration Script (Session 3)

Prompt: `docs/prompts/F4_MULTI_TENANCY_SESSION3_PROMPT.md`

- **MCP tools**: `register_user`, `update_user`, `list_users`, `whoami`, `add_user_auth`, `remove_user_auth` (admin-only)
- **Bot tools**: Соответствующие `_exec_*` функции + `TOOL_DECLARATIONS` для Gemini
- **API routes**: `tg_parser/api/routes/users.py` — CRUD users + `/me`
- **Bot UX**: `/start` проверяет регистрацию, показывает персональное приветствие
- **Migration CLI**: `tg-parser migrate-users` — маппинг существующих API keys/MCP tokens/bot user IDs на admin
- **Tests**: ~15 тестов в `tests/test_f4_user_management.py`

---

## Архитектурные решения

1. **`assert_channel_access` — async**: Сделано async для единообразия, хотя текущая реализация синхронная (будущее расширение для проверки через БД).
2. **Фильтрация topics в search**: Добавлена двойная фильтрация — по `channel_id` (single-channel search) и по `allowed_channel_ids` (tenant scoping).
3. **IVFFlat probes**: Повышены до 20 при наличии `channel_ids` фильтра для улучшения recall при ограниченной выборке.
4. **`list_by_channels` — SQL LIKE**: Используется `LIKE '%"channel_id"%'` по JSON-строке `sources_json` вместо jsonb-оператора, т.к. sources хранятся как JSON text.
5. **Default admin fallback**: Все `_exec_*` функции бота используют `current_user or await get_default_admin()` для обратной совместимости.

---

## Структура ветки

```
feature/f4-multi-tenancy-phase1-2
├── 096d79b feat(f4): Phase 1 (data model) + Phase 2 (auth resolution)  ← Session 1
└── be6616a feat(f4): Phase 3 (ownership) + Phase 4 (scoped access)     ← Session 2 (текущий)
```

---

## Как продолжить

```bash
# 1. Перейти в ветку
git checkout feature/f4-multi-tenancy-phase1-2

# 2. Убедиться что тесты проходят
.venv/bin/python -m pytest tests/ -q --tb=short -k "not (postgres or test_db)"
# Ожидание: 1105 passed, 42 skipped, 0 failures

# 3. Начать Session 3
# Открыть docs/prompts/F4_MULTI_TENANCY_SESSION3_PROMPT.md
```

---

## 42 пропущенных теста

Все — PostgreSQL-only интеграционные тесты из Session 1 (Phase 1–2):
- `test_f4_user_model.py` (25) — CRUD таблицы users, маппинг User → CurrentUser
- `test_f4_embedding_channel_ids.py` (14) — миграция channel_ids, фильтрация &&, IVFFlat
- `test_f4_auth_resolution.py` (3) — резолвинг по API key и Telegram ID через реальную БД

Включить: `TEST_POSTGRES=1 .venv/bin/python -m pytest tests/`
