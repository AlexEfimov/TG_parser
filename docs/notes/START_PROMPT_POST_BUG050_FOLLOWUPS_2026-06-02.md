# START PROMPT — Conversational-layer follow-ups (post BUG-047…050)

**Дата:** 2026-06-02 · **Автор контекста:** перенос из окна закрытия кластера delete/subscribe-маршрутизации.
**Предыдущий start-prompt серии:** `docs/notes/START_PROMPT_BUG047_D1_D2_DELETE_ROUTING_2026-06-01.md`.

> Рабочий режим: **Multitask Mode** (асинхронные subagents, `run_in_background: true`). Коммит — только по явному запросу пользователя (AGENTS.md). Деплой/мерж — только с отмашкой. Каждый смоук пользователь гоняет вручную в живом Telegram и присылает транскрипт.

---

## 1. Где мы сейчас (состояние на 2026-06-02 ~00:45 UTC+4)

Весь кластер разговорного слоя delete/subscribe-маршрутизации **закрыт и смержен в `main`**, задеплоен и подтверждён живыми смоуками.

| Bug | Что | PR | merge SHA | Прод-смоук |
|---|---|---|---|---|
| BUG-047 (D1) | детерминированная delete-by-name + анафора + симметричный re-resolve в `delete_suggest` + suppression sub-threshold «Ближайшее совпадение» | #162 | `cd5f4c2` | clean |
| BUG-048 (D2) | FSM intent-break (выход из armed ConfirmFlow/ClarifyFlow по явной новой команде/вопросу) + `delete_intent` TTL-snapshot, переживающий очистку FSM | #163 | `a13ad23` | clean (Part-A подтверждён 2026-06-01) |
| BUG-049 | срез кандидатов delete-by-name: bare-token / preposition-strip fallback в `_delete_name_candidates` («удали подписку на genotek» теперь армит `delete_suggest`) | #164 | `7b32570` | clean |
| BUG-050 | `subscribe_intent` TTL-router + post-agent detector + prompt v1.7.6: при LLM-обходе детерминированного channel-not-found голое имя канала **возобновляет subscribe**, а не уходит в `list_topics` | #165 | `ee250d8` | clean |

**`main` HEAD = `883bed3`** (doc-коммит BUG_LOG поверх `ee250d8`).
**Прод задеплоен на `52a8005`** (= контент `main`; отличается только doc-коммитами BUG_LOG). Rollback-точка: `7b32570`.

### Открытые записи в BUG_LOG
- **BUG-047/048/049/050 → resolved.**
- **BUG-051 (open, low/observation)** — возможная duplicate-send / async message-гонка в связке read-clarify + pagination. Симптом (смоук 2026-06-02 ~00:21–00:22): при armed read-clarify от «покажи темы enotek» быстрые повторные «genotek» давали чередование «канал не найден»-clarify и списка тем, с видимыми дублями. Подозрение — артефакт дублей/Telegram-гонок, не логический дефект (BUG-043/BUG-004 не трогали). Нужен контролируемый одиночный repro.

---

## 2. Дальнейшие шаги (бэклог, ничего срочного)

1. **BUG-051** (low) — контролируемый repro read-clarify/pagination гонки одиночными сообщениями (без спама). Сначала read-only расследование: реальная FSM-гонка или client/duplicate-send артефакт. Поверхности: `_handle_clarification_response` (`kind="read"`), `PaginationFlow` `_handle_pagination_response`, dedup/идемпотентность входящих апдейтов.
2. **BUG-050 watchlist-parity** (enhancement) — `subscribe_intent` сейчас digest-only; распространить на `subscribe_watchlist` (отложено в v1).
3. **Grafana ops-тикет** (low, не про бота) — `tg_parser_grafana` крэш-лупит из-за битого `provisioning/.../wave1_step4.yaml` (contact point `cursor-watch-webhook` без `url`, мёртвый `https://grafana.tgp.efimov.mobi`).
4. **VPS git-гигиена** (мелочь) — прод checkout на удалённой ветке `fix/bug050-subscribe-intent-resume`@`52a8005`; при следующем деплое вернуть VPS на `main` (контент идентичен, не срочно).
5. **Doc-уборка** — решить судьбу непривязанного `docs/notes/HANDOFF_PRESERVE_TG_URLS_2026-05-30.md` (untracked).

**Рекомендованный приоритет, если продолжаем:** BUG-051 (единственный реальный открытый вопрос); остальное — enhancement/ops без срочности.

---

## 3. Прод / деплой / инфра (нормативно)

- **VPS:** `ssh -p 2296 user@212.72.189.15`, репо `~/TG_parser`.
- **Деплой (Variant B):** `git fetch origin <branch/main>` → checkout → `git reset --hard <SHA>` → `docker compose up -d --build` → **обязательно** `docker compose --profile bot up -d --force-recreate --no-deps tg_bot` (бот под профилем `bot` — обычный `up` его НЕ пересоздаёт). Верифицировать `git rev-parse HEAD == <SHA>`, здоровье контейнеров, наличие нового кода в running-контейнере, чистые стартап-логи. Эти правки — только bot-Python/prompts/tests/docs → **миграций нет**.
- **CI gate:** required = `Test Python 3.12`. `Lint Documentation` (markdown link-checker) — НЕ required, красный на пред-существующих ссылках → игнор, если только он.
- **ruff:** CI пиннут `ruff==0.15.11`. Локальный может врать → **всегда** `uvx ruff@0.15.11 format --check . && uvx ruff@0.15.11 check .` перед коммитом.
- **Известный non-blocker:** `tg_parser_grafana` crash-loop (см. бэклог п.3) — к боту отношения нет.

## 4. Ключевые файлы и текущая архитектура диспетчинга

**Dispatch order в `handle_text` (`tg_parser/bot/handlers.py`):**
`ConfirmFlow` (+intent-break на входе) → `ClarifyFlow` (+intent-break для subscribe/read; selective для delete-kinds) → `PaginationFlow` → `_handle_delete_prerouter` → `_handle_delete_intent_router` (BUG-048) → `_handle_subscribe_intent_router` (BUG-050) → `agent.process_message`.

- `tg_parser/bot/states.py` — `ReadContextData`, `LastSubscriptionData`, `DeleteIntentData` (BUG-048), `SubscribeIntentData` (BUG-050); FSM-группы `ConfirmFlow`/`ClarifyFlow`/`PaginationFlow`.
- `tg_parser/bot/handlers.py`:
  - delete: `_handle_delete_prerouter`, `_delete_name_candidates` (+`_DELETE_PREPOSITION_PREFIX`, BUG-049), `_best_delete_match`, `_route_delete_match`, `_handle_delete_suggest_selection`, `_handle_delete_disambig_selection`.
  - intent-break (BUG-048): `COMMAND_VERB_PATTERN`, `QUESTION_PATTERN`, `_looks_like_new_intent`, `_release_fsm_and_reroute`; helpers `_set/_clear/_delete_intent_for_router`, `_handle_delete_intent_router`.
  - subscribe (BUG-050): `_detect_subscribe_create_intent`, `_parse_subscribe_channel`, `_parse_subscribe_schedule`, `_subscribe_partial_args`, `_default_subscribe_name`; helpers `_set/_clear/_subscribe_intent_for_router`, `_handle_subscribe_intent_router`; post-agent detector в FSM-transition блоке.
  - TTL: `_is_stale`, `READ_CONTEXT_TTL_SECONDS` (15 мин — общий для read_context/last_subscription/delete_intent/subscribe_intent).
- `tg_parser/bot/tools.py` — `unsubscribe_*`/`subscribe_*`, `resolve_subscription_by_name`/`_match_subscription_items` (`_SUGGEST_FUZZY_CUTOFF=0.5`, closest gated тем же cutoff после BUG-047 D1), `_reject_nonexistent_channel`/`_build_subscribe_clarify_pending` (G2/BUG-045), `_build_read_clarify_pending` (BUG-043), confirm-gate `_WRITE_TOOLS_REQUIRING_CONFIRM` (BUG-046).
- `tg_parser/bot/agent.py` — `process_message` (stateless single-turn `contents`, `mode="AUTO"`, temp 0.2), read-context инъекция, `clarify_pending`/`preview_pending`/`pagination_pending` capture.
- `prompts/bot.yaml` — **v1.7.6** (BUG-050 hard rules: всегда звать `subscribe_digest` при возможно-неверном канале; голое имя канала после create = продолжение subscribe; relay clarify verbatim).
- `docs/notes/BUG_LOG.md` — backbone; BUG-047…050 resolved, BUG-051 open.
- Тесты: `tests/test_bot_delete_routing_bug047.py`, `tests/test_bot_intent_break_bug048.py`, `tests/test_bot_delete_candidate_slicing_bug049.py`, `tests/test_bot_subscribe_channel_resume_bug050.py`, `tests/test_bot_unsubscribe_confirm_gate_g1.py`, `tests/test_bot_conversation_layer_bug039_042.py`, `tests/test_bot_confirm_flow.py`, `tests/test_f11_bot_tools.py`, `tests/test_cron_humanize.py`.

## 5. Первое действие в новом окне
Подтвердить, что бэклог актуален, и (если продолжаем) запустить **BUG-051**: read-only расследование read-clarify/pagination гонки на контролируемом одиночном repro — определить, реальная ли это FSM-гонка или артефакт дублей/Telegram, затем дизайн (идемпотентность/dedup входящих апдейтов или защита состояния) → failing-first → деплой → смоук.

**Конвенции (AGENTS.md):** ветка `main`; не коммитить без явного запроса; не создавать `docs/methodology/**`; не править `pyproject.toml`/`requirements.txt` без запроса; ADR (`docs/adr/`) и контракты (`docs/contracts/`) нормативны.
