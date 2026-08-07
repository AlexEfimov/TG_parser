# Runbook — Wave 1 Step 4 VPS Watch Window: OPERATOR MANUAL ACTIONS

**Audience:** operator во время открытого VPS watch window (T+0 = `2026-05-24T10:50:10Z`, T+24h = `2026-05-25T10:50:10Z`).

**Purpose:** перечень действий, которые **НЕЛЬЗЯ автоматизировать через Cursor Automations** (нет direct Telegram MTProto access, нет SSH egress, нет UI control), и поэтому оператор выполняет их **руками** по чеклисту ниже. Дополняет автоматические задачи (см. [`WAVE1_STEP4_VPS_WATCH_AUTOMATIONS.md`](WAVE1_STEP4_VPS_WATCH_AUTOMATIONS.md)) и подробный exercise plan (см. [`WAVE1_STEP4_VPS_WATCH_SESSION_EXERCISE_PLAN.md`](WAVE1_STEP4_VPS_WATCH_SESSION_EXERCISE_PLAN.md)).

**Safety preamble:** перед началом — прочитать § 0 «SAFETY preamble — PRODUCTION CONSTRAINTS» в exercise plan (S-1…S-7). Особенно **S-1** (не трогать `digest_94483db9`) и **S-2** (не использовать `chat_id=5445781511`).

---

## 0. Что автоматизировано (для контекста)

| Automation ID | Триггер | Что делает | Где смотреть результат |
|---|---|---|---|
| `2bd25769-52b1-4525-a0c5-239d589d231f` | cron `5 6 25 5 *` (UTC) = `2026-05-25T06:05Z` | P0-4 verifier: проверяет `digest_94483db9` (target_kind='chat', last_sent_at ≥ 06:00Z); открывает GitHub issue при regression | https://cursor.com/automations/2bd25769-52b1-4525-a0c5-239d589d231f + GitHub issues `AlexEfimov/TG_parser` |
| `f93e557a-a3ef-4dc0-9d2d-b4cb9f879c7f` | cron `50 10 25 5 *` (UTC) = `2026-05-25T10:50Z` | T+24h closure reminder: открывает GitHub issue со closure-чеклистом C-1…C-8 | https://cursor.com/automations/f93e557a-a3ef-4dc0-9d2d-b4cb9f879c7f + GitHub issues |
| `7b35ca01-a7d1-4c3a-bb8b-940918e506d6` | webhook URL (получить из UI после создания) | Incident ingress: парсит Grafana/Sentry/curl webhook payload, открывает GitHub issue если real incident | https://cursor.com/automations/7b35ca01-a7d1-4c3a-bb8b-940918e506d6 + GitHub issues |

⚠️ **Перед стартом watch:** оператор должен **открыть `2bd25769`** в UI и добавить MCP server `tg-parser-vps` (URL `https://mcp.tgp.efimov.mobi`, auth с секретом, хранящим personal API key — secret name по соглашению `TG_PARSER_VPS_MCP_KEY`). Без этого шага cron-запуск откроет issue «P0-4 verifier blocked: MCP server tg-parser-vps not configured» вместо реальной проверки.

⚠️ Если используется webhook ingress (`7b35ca01`) — открыть в UI, скопировать сгенерированный webhook URL и (опционально) добавить его как `alertmanager.receiver` в Prometheus / `notification.policies` в Grafana / `--data-urlencode` в operator's curl ad-hoc.

---

## 1. ОПЕРАТОР ДЕЛАЕТ РУКАМИ — full checklist

### M-1. Pre-flight (T+0…T+1h) — **обязательно, иначе остальное бесполезно**

| # | Действие | Команда / шаг | Acceptance |
|---|---|---|---|
| M-1.1 | Проверить, что VPS жив и step-4 deploy штатный | `ssh -p 2296 user@212.72.189.15 'docker compose ps'` | 5 контейнеров `Up`, `tg_parser_*` все healthy |
| M-1.2 | Получить `API_KEY` для prod HTTP API | `API_KEY=$(ssh -p 2296 user@212.72.189.15 'docker compose exec -T tg_parser python3 -c "import json,os; print(next(iter(json.loads(os.environ[\"API_KEYS\"]).keys())))"')` | непустая строка |
| M-1.3 | Получить свой `OPERATOR_CHAT_ID` (не `5445781511`!) | DM боту в Telegram `/start` → `ssh ... 'docker logs --since 10m tg_parser_bot \| grep "from_user"'` или `@userinfobot` | `OPERATOR_CHAT_ID=<your_id>` записать в локальную переменную/sticky note |
| M-1.4 | Создать **R-1** = operator-owned Telegram channel, бот добавлен admin с Post messages | Telegram UI: Create Channel → Add Member (bot username) → Channel Settings → Administrators → bot → Post Messages ✓ | `R1_CHANNEL_ID=-100...` или `@username_test1` записать |
| M-1.5 | Создать **R-2** = operator-owned channel, бот **НЕ добавлен** | Telegram UI: Create Channel → НЕ добавлять бота | `R2_CHANNEL_ID=-100...` записать; **проверить:** бот НЕ в member list |
| M-1.6 | Привязать MCP server в P0-4 automation | https://cursor.com/automations/2bd25769-52b1-4525-a0c5-239d589d231f → Edit → MCP servers → Add → name `tg-parser-vps`, URL `https://mcp.tgp.efimov.mobi/mcp` (с `/mcp` суффиксом!), Headers `Authorization: Bearer <token>` (скопировать из `~/.cursor/mcp.json` поле `tg-parser.headers.Authorization`). **NB:** per-tool checkbox-allowlist на уровне automation НЕ существует — agent видит все tools прикреплённого MCP server и сам выбирает нужный (`list_digests`) по prompt-у. | Save success; `get_automation(2bd25769)` показывает `actionTypes: ["mcp"]`. ✅ Confirmed via test run 2026-05-24T12:42Z. |
| M-1.7 | Webhook URL для incident ingress automation — сохранить в env | см. § 1.7 ниже | `echo $TG_PARSER_WATCH_WEBHOOK` непуст |
| M-1.8 | (опционально) Grafana Contact point + alert rules | см. § 1.8 ниже | Grafana test ping не открыл GitHub issue (= фильтр test-pings работает); первый real alert открыл issue |

**STOP-condition:** если M-1.1 или M-1.2 fail — НЕ продолжать watch checklist, поднять deploy issue. Шаги M-1.7 / M-1.8 — `nice-to-have`, не блокируют watch.

---

### 1.7. Webhook URL → env var (1-2 минуты, MUST для удобного манyального ingress)

Cursor webhook endpoint требует `Authorization: Bearer crsr_...` header (без него — `401 Invalid API key or missing required scope`). Подтверждено [official docs](https://cursor.com/docs/cloud-agent/automations) + [forum](https://forum.cursor.com/t/webhook-trigger-endpoint-returns-401/155752). Поэтому нужны ДВЕ env var.

#### Шаги setup

1. **Сгенерировать auth header** — открыть https://cursor.com/automations/7b35ca01-a7d1-4c3a-bb8b-940918e506d6 → **Edit** → секция **Webhook trigger** → кнопка **Generate auth header** (или **Copy auth header**) → скопировать целиком значение формата `Bearer crsr_xxxxx`.
2. **Добавить env var-ы в `~/.zshrc` локально** (на operator's Mac, не на VPS):
   ```bash
   echo '' >> ~/.zshrc
   echo '# TG_parser Wave 1 step 4 watch window incident webhook (automation 7b35ca01)' >> ~/.zshrc
   echo 'export TG_PARSER_WATCH_WEBHOOK="https://api2.cursor.sh/automations/webhook/7b35ca01-a7d1-4c3a-bb8b-940918e506d6"' >> ~/.zshrc
   echo 'export TG_PARSER_WATCH_WEBHOOK_AUTH="Bearer crsr_ЗДЕСЬ_СГЕНЕРИРОВАННЫЙ_ТОКЕН"' >> ~/.zshrc
   source ~/.zshrc
   ```
3. **Smoke test (test-ping должен быть skip-нут automation-ом → НЕ создаст issue):**
   ```bash
   curl -X POST "$TG_PARSER_WATCH_WEBHOOK" \
     -H "Authorization: $TG_PARSER_WATCH_WEBHOOK_AUTH" \
     -H 'Content-Type: application/json' \
     -d '{"test": true, "summary": "smoke test from operator"}'
   ```
   Ожидание: `2xx` ответ, GitHub issues в `AlexEfimov/TG_parser` без новых записей.

⚠️ **Security:** `TG_PARSER_WATCH_WEBHOOK_AUTH` секретен. `~/.zshrc` НЕ должен попадать в git. Не показывать в чате/PR/issue.

⚠️ **Known regression:** иногда даже с правильным токеном Cursor webhook возвращает 401 (server-side regression). Workaround: нажать **Regenerate auth header** в UI → обновить env var → повторить.

#### Готовые `curl` snippets для основных сценариев

Использование во время watch — когда оператор заметил что-то глазами / в логах / в MCP, бьёт curl → automation `7b35ca01` парсит payload → открывает GitHub issue с правильным title prefix.

```bash
# Сценарий A: BUG-030 recurrence (digest_scheduler_initial_load_failed повторился после initial self-heal)
curl -X POST "$TG_PARSER_WATCH_WEBHOOK" \
  -H "Authorization: $TG_PARSER_WATCH_WEBHOOK_AUTH" \
  -H 'Content-Type: application/json' \
  -d '{
    "alertname": "digest_scheduler_initial_load_failed_recurrence",
    "severity": "warning",
    "summary": "BUG-030: digest_scheduler_initial_load_failed fired again after initial self-heal",
    "description": "T+<XX>h since deploy. Inspect: ssh -p 2296 user@212.72.189.15 docker logs --since 1h tg_parser_bot | grep digest_scheduler_initial_load_failed",
    "source": "operator-curl"
  }'

# Сценарий B: channel-publish-fail (tg_digest_channel_publish_total{result="failed"} > 0)
curl -X POST "$TG_PARSER_WATCH_WEBHOOK" \
  -H "Authorization: $TG_PARSER_WATCH_WEBHOOK_AUTH" \
  -H 'Content-Type: application/json' \
  -d '{
    "alertname": "tg_digest_channel_publish_failed",
    "severity": "warning",
    "summary": "channel-publish-fail counter incremented unexpectedly",
    "description": "Prometheus: tg_digest_channel_publish_total{result=\"failed\"}. Inspect logs: docker logs tg_parser_bot | grep _publish_to_target",
    "source": "operator-curl"
  }'

# Сценарий C: unexpected soft-deactivation (permission_denied вне ожидаемого P0-2 теста)
curl -X POST "$TG_PARSER_WATCH_WEBHOOK" \
  -H "Authorization: $TG_PARSER_WATCH_WEBHOOK_AUTH" \
  -H 'Content-Type: application/json' \
  -d '{
    "alertname": "tg_digest_unexpected_soft_deactivation",
    "severity": "warning",
    "summary": "permission_denied counter incremented outside P0-2 controlled test window",
    "description": "Real subscription могла быть soft-deactivated. Проверить: MCP list_digests / list_watchlists на is_active=false subscriptions, и какие именно. Cross-check timestamps в digest_dispatch logs.",
    "source": "operator-curl"
  }'

# Сценарий D: 5xx spike на /api/v1/(digests|watchlists)
curl -X POST "$TG_PARSER_WATCH_WEBHOOK" \
  -H "Authorization: $TG_PARSER_WATCH_WEBHOOK_AUTH" \
  -H 'Content-Type: application/json' \
  -d '{
    "alertname": "tg_api_5xx_spike",
    "severity": "critical",
    "summary": "5xx responses on POST /api/v1/(digests|watchlists)",
    "description": "Inspect: docker logs --since 30m tg_parser | grep -E POST.*/(digests|watchlists).* 5[0-9][0-9]. Возможный регресс DigestCreateRequest/WatchlistCreateRequest validator или target backward-compat shim.",
    "source": "operator-curl"
  }'

# Сценарий E: digest_94483db9 next-tick anomaly (если operator заметил раньше automation 2bd25769)
curl -X POST "$TG_PARSER_WATCH_WEBHOOK" \
  -H "Authorization: $TG_PARSER_WATCH_WEBHOOK_AUTH" \
  -H 'Content-Type: application/json' \
  -d '{
    "alertname": "digest_94483db9_anomaly",
    "severity": "critical",
    "summary": "digest_94483db9 P0-4 legacy-chat regression suspected (manual sighting)",
    "description": "Operator manual sighting before automation 2bd25769 cron fires at 06:05Z. Document: MCP list_digests output для 94483db9-... + текущий timestamp.",
    "source": "operator-curl"
  }'

# Сценарий F: bot health degradation (operator увидел /help не отвечает)
curl -X POST "$TG_PARSER_WATCH_WEBHOOK" \
  -H "Authorization: $TG_PARSER_WATCH_WEBHOOK_AUTH" \
  -H 'Content-Type: application/json' \
  -d '{
    "alertname": "tg_parser_bot_unresponsive",
    "severity": "critical",
    "summary": "Bot не отвечает на /help в operator DM",
    "description": "Manual sighting. Cross-check: docker ps tg_parser_bot status + последние логи. Возможно polling drop или Telegram API throttle.",
    "source": "operator-curl"
  }'

# Сценарий G: free-form (всё что не подходит под A-F)
curl -X POST "$TG_PARSER_WATCH_WEBHOOK" \
  -H "Authorization: $TG_PARSER_WATCH_WEBHOOK_AUTH" \
  -H 'Content-Type: application/json' \
  -d '{
    "alertname": "manual_escalation",
    "severity": "warning",
    "summary": "<твоё описание ОДНОЙ строкой>",
    "description": "<полный контекст: что увидел, где, какие команды дали что>",
    "source": "operator-curl"
  }'
```

**Дедуп:** automation `7b35ca01` НЕ имеет встроенной дедупликации — один curl = один issue. Если жмёшь дважды по той же причине — будет два issue. Это OK: операторская дисциплина важнее «умной» автоматики.

**Skip-фильтр:** payload с `{"test": true}` или `alertname == "DeadMansSwitch"` / `"Watchdog"` — automation `7b35ca01` сама skip-нёт (вшито в prompt). Это для безопасного `curl` smoke-test.

---

### 1.8. Grafana Contact point + alert rules (опционально, ~15-20 минут, SHOULD для long-term наблюдения)

> На VPS Grafana развёрнута (`docker-compose.yml:303`), экспонирована наружу **реверс-прокси на хосте** (system nginx + certbot), а не Caddy — контейнера Caddy на VPS нет вовсе (проверено 2026-08-07, см. [`BUG_LOG.md`](../notes/BUG_LOG.md) § BUG-090). Публичный адрес — grafana-vhost на хосте; посмотреть живьём: `ls /etc/nginx/sites-enabled/`. Alerting rules **не** provisioned (`docker/grafana/provisioning/` содержит только `dashboards/` + `datasources/`), поэтому настройка — руками один раз. Заменяет Alertmanager (которого в `docker-compose.yml` нет — используется Grafana Unified Alerting с v8+).

#### Шаги

1. **Login:** `https://grafana.tgp.efimov.mobi` → `${GRAFANA_ADMIN_USER}` / `${GRAFANA_ADMIN_PASSWORD}` из VPS `.env`.
2. **Alerting → Contact points → + New contact point:**
   * Name: `cursor-watch-webhook`
   * Integration: `Webhook`
   * URL: `https://api2.cursor.sh/automations/webhook/7b35ca01-a7d1-4c3a-bb8b-940918e506d6`
   * HTTP Method: `POST`
   * Content-Type: `application/json` (default; **не менять**)
   * **HTTP Headers** (раскрыть Optional settings → Add header) — **обязательно**, иначе 401:
     * Header name: `Authorization`
     * Header value: `Bearer crsr_<тот_же_токен_что_в_$TG_PARSER_WATCH_WEBHOOK_AUTH>`
   * Save → **Test** → должен прийти test ping в automation `7b35ca01` → в GitHub issues `AlexEfimov/TG_parser` НЕ должно появиться нового issue (фильтр test-pings работает). Если **401** — токен не прокидывается, проверить header config; если **200 + issue** — поправить prompt automation, чтобы skip-фильтр был агрессивнее.
3. **Alerting → Notification policies → Default policy → Edit → Default contact point:** `cursor-watch-webhook`.
4. **Alerting → Alert rules → + New alert rule** — создать минимум 3 правила (`alertname` должен матчиться с buckets в prompt-е `7b35ca01` для правильного title prefix):

| Rule name (`alertname`) | Promql expression | For | Severity | Title prefix в issue |
|---|---|---|---|---|
| `tg_parser_bot_down` | `up{job="tg_parser_bot"} == 0` | 5m | critical | `[bot down]` |
| `tg_parser_api_down` | `up{job="tg_parser_api"} == 0` | 5m | critical | `[api down]` |
| `tg_api_5xx_spike` | `sum(rate(tg_api_requests_total{path=~"/api/v1/(digests\|watchlists).*",status=~"5.."}[5m])) > 0` | 5m | warning | `[5xx]` |

(опционально) Доп. правила, если есть Prometheus counter для них:

| Rule name | Expression | Title prefix |
|---|---|---|
| `digest_scheduler_initial_load_failed_recurrence` | `increase(digest_scheduler_initial_load_failed_total[10m]) > 0` | `[BUG-030 elevation]` |
| `tg_digest_channel_publish_failed_rate` | `rate(tg_digest_channel_publish_total{result="failed"}[10m]) > 0` | `[channel-publish-fail]` |
| `tg_digest_unexpected_permission_denied` | `rate(tg_digest_channel_publish_total{result="permission_denied"}[10m]) > 0.01` (порог отстраивает baseline после P0-2) | `[soft-deactivation]` |

**Проверка end-to-end:** после save alert rule — временно загрубить условие (`for: 1m` + порог чуть выше текущего baseline) → дождаться firing → проверить, что в `7b35ca01` пришло, в GitHub issue открыт с правильным prefix → восстановить boevoy threshold.

---

### M-2. Channel publish — success path (P0-1 из exercise plan) — **РУКАМИ через MCP клиент или HTTP**

> **Почему руками:** automation не имеет MCP `subscribe_digest` write-privilege в этом контексте (риск зацикливания при ошибочной нагрузке). Mutating MCP calls делает оператор.

| # | Действие | Команда | Acceptance |
|---|---|---|---|
| M-2.1 | Subscribe digest на R-1 (operator-owned, бот admin) | MCP: `subscribe_digest(name="vps_watch_p0_1_success", channel_ids=[<real_kb_channel_id>], target={"kind":"channel","channel_id":"@username_test1"}, cron_expression="*/2 * * * *", language="ru", format="summary")` | возвращает `subscription_id`; записать как `SUB_P0_1` |
| M-2.2 | Подождать **3 минуты** (≥ один tick) | wall-clock | — |
| M-2.3 | Проверить, что сообщение пришло в R-1 | открыть @username_test1 в Telegram, последнее сообщение от бота | ✅ есть свежий summary digest, метка времени в окне M-2.1 + 0..2 мин |
| M-2.4 | Проверить, что счётчик success на VPS увеличился | `ssh -p 2296 user@212.72.189.15 'docker exec tg_parser_prometheus wget -qO- "http://localhost:9090/api/v1/query?query=tg_digest_channel_publish_total%7Bresult%3D%22success%22%7D"'` | `value` ≥ 1; вырос относительно baseline до M-2.1 |
| M-2.5 | Записать timestamp + result в watch note секцию «24h watch observations» | edit `docs/notes/WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md` | сохранён |
| M-2.6 | **CLEANUP** — отписать `SUB_P0_1` | MCP: `unsubscribe_digest(subscription_id=SUB_P0_1)` | success |

---

### M-3. Channel publish — permission_denied path (P0-2) — **РУКАМИ**

| # | Действие | Команда | Acceptance |
|---|---|---|---|
| M-3.1 | Subscribe digest на R-2 (бот НЕ admin) | MCP: `subscribe_digest(name="vps_watch_p0_2_denied", channel_ids=[<kb_channel_id>], target={"kind":"channel","channel_id":"@username_test2"}, cron_expression="*/2 * * * *", language="ru", format="summary")` | `subscription_id` записать как `SUB_P0_2` |
| M-3.2 | Подождать 3 минуты | wall-clock | — |
| M-3.3 | Проверить, что сообщения в R-2 **НЕТ** | открыть @username_test2 в Telegram | ✅ нет сообщения от бота |
| M-3.4 | Проверить fallback DM в operator's chat | открыть DM с ботом в Telegram | ✅ пришло fallback сообщение типа «I tried to publish to @username_test2 but I'm not admin there — soft-deactivating subscription» (точный текст из `_publish_to_target`) |
| M-3.5 | Проверить soft-deactivation в DB | MCP: `list_digests()` → найти `SUB_P0_2` | `is_active == false` |
| M-3.6 | Проверить metric counter | `ssh -p 2296 user@212.72.189.15 'docker exec tg_parser_prometheus wget -qO- "http://localhost:9090/api/v1/query?query=tg_digest_channel_publish_total%7Bresult%3D%22permission_denied%22%7D"'` | `value` ≥ 1, вырос |
| M-3.7 | Записать в watch note | edit watch note | сохранён |
| M-3.8 | **CLEANUP** — `unsubscribe_digest(SUB_P0_2)` (уже soft-deactivated, но удалить запись) | MCP | success |

---

### M-4. Watchlist channel target (P0-3) — **РУКАМИ**

> Аналог M-2 для `subscribe_watchlist`. Один success path достаточен — `permission_denied` логика идентична (общий `_publish_to_target`).

| # | Действие | Команда | Acceptance |
|---|---|---|---|
| M-4.1 | Subscribe watchlist на R-1 | MCP: `subscribe_watchlist(title="vps_watch_p0_3_watchlist", channel_ids=[<kb_channel_id>], target={"kind":"channel","channel_id":"@username_test1"}, keywords=["test"], threshold=0.1)` | `interest_id` записать как `WL_P0_3` |
| M-4.2 | Триггернуть pipeline tick если нужно | MCP: `trigger_pipeline()` (admin only — если нет роли, просто подождать естественного tick'а) | accepted |
| M-4.3 | Проверить, что match-уведомление пришло в R-1 | Telegram @username_test1 | ✅ есть watch-match сообщение (если есть matching content в KB) |
| M-4.4 | Записать в watch note | edit | сохранён |
| M-4.5 | **CLEANUP** — `unsubscribe_watchlist(WL_P0_3)` | MCP | success |

---

### M-5. P0-4 — **PASSIVE observation digest_94483db9** (overlaps with automation `2bd25769`)

> ⚠️ **S-1: НЕ ТРОГАТЬ.** Оператор только наблюдает. Automation проверяет автоматически в 06:05Z.

| # | Действие | Команда | Acceptance |
|---|---|---|---|
| M-5.1 | (опционально) До 06:00Z — pre-state baseline | MCP: `list_digests()` → запись `94483db9-...` → snapshot полей `target_kind`, `chat_id`, `last_sent_at`, `is_active` | записан как `digest_94483db9_pre.json` в watch note |
| M-5.2 | В **06:01Z…06:10Z** оператор НЕ делает ничего — automation `2bd25769` сработает в 06:05Z | — | — |
| M-5.3 | В **~06:15Z** проверить GitHub issues `AlexEfimov/TG_parser` | https://github.com/AlexEfimov/TG_parser/issues?q=is%3Aissue+digest_94483db9 | если issue открыт — RED (см. § 4 escalation в exercise plan); если нет issue — GREEN, automation прошла без regression |
| M-5.4 | (опционально, для двойного подтверждения) Manually verify | MCP: `list_digests()` → `94483db9-...` → проверить `target_kind=='chat'`, `chat_id==5445781511`, `is_active==true`, `last_sent_at >= 2026-05-25T06:00:00Z` | matches automation's assertion |
| M-5.5 | Записать pre+post snapshot в watch note | edit | сохранён |

---

### M-6. Bot natural-language tests (P1-1, P1-2) — **ТОЛЬКО РУКАМИ** (бот = Telegram MTProto, automation не имеет доступа)

> **Почему руками:** Cursor Automations не имеют MTProto SDK + не залогинены как operator. Любое сообщение боту = real Telegram message.

#### M-6.1 — NL для channel target (P1-1)

| Шаг | Действие | Acceptance |
|---|---|---|
| 1 | Открыть DM с prod ботом в Telegram | bot отвечает на `/help` |
| 2 | Отправить natural-language prompt: `«Хочу получать дайджест в канал @username_test1 раз в час про новости медицины»` | bot отвечает clarification или confirmation prompt |
| 3 | Если бот спрашивает «куда?» — ответить `@username_test1` | bot подтверждает intent |
| 4 | Бот должен confirm: «Created subscription `vps_watch_*` to channel @username_test1 with cron ...» | ✅ confirmation message |
| 5 | Проверить в MCP `list_digests()` — должна быть свежая subscription с `target_kind="channel"`, `channel_id=="@username_test1"` | ✅ |
| 6 | **CLEANUP** — отправить боту `/unsubscribe <subscription_id>` ИЛИ напрямую `unsubscribe_digest(...)` через MCP | success |
| 7 | Записать в watch note: «P1-1 GREEN/RED, prompt v1.7.0 target_kind_semantics correctly disambiguated channel intent» | сохранён |

#### M-6.2 — NL для chat target (P1-2)

| Шаг | Действие | Acceptance |
|---|---|---|
| 1 | В том же DM отправить: `«Хочу получать дайджест мне в личку каждое утро в 8»` | bot отвечает clarification |
| 2 | Бот должен confirm создание subscription с `target_kind="chat"`, `chat_id=<OPERATOR_CHAT_ID>`, cron `0 8 * * *` | ✅ |
| 3 | Проверить через MCP `list_digests()` | ✅ запись с `target_kind="chat"` |
| 4 | **CLEANUP** — `unsubscribe_digest(...)` | success |
| 5 | Записать в watch note | сохранён |

---

### M-7. HTTP mutual-exclusion test (P1-3) — **РУКАМИ через curl**

> Можно автоматизировать, но требует sandbox curl access + сохранённого `API_KEY` — проще руками за 30 секунд.

```bash
ssh -p 2296 user@212.72.189.15 'curl -s -X POST https://localhost:8001/api/v1/digests \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"vps_watch_p1_3_validation\",\"channel_ids\":[1],\"target\":{\"kind\":\"chat\",\"chat_id\":123},\"chat_id\":456}"'
```

**Ожидание:** 422 Unprocessable Entity с сообщением «target and chat_id are mutually exclusive» (или эквивалент по схеме `DigestCreateRequest.target__chat_id_validator`).

**Acceptance:** статус 422; non-202.

---

### M-8. Passive monitoring loop (T+1h, T+6h, T+12h, T+18h) — **РУКАМИ**, ~5 минут каждый раз

Спот-чек, записать timestamp + результат в watch note:

```bash
# 1. up{} 
ssh -p 2296 user@212.72.189.15 'docker exec tg_parser_prometheus wget -qO- "http://localhost:9090/api/v1/query?query=up%7Bjob%3D~%22tg_parser_.%2A%22%7D"'

# 2. channel-publish counters
ssh -p 2296 user@212.72.189.15 'docker exec tg_parser_prometheus wget -qO- "http://localhost:9090/api/v1/query?query=tg_digest_channel_publish_total"'

# 3. 5xx scan
ssh -p 2296 user@212.72.189.15 'docker logs --since 1h tg_parser | grep -E " 5[0-9][0-9] " | head'

# 4. BUG-030 recurrence check
ssh -p 2296 user@212.72.189.15 'docker logs --since 1h tg_parser_bot | grep digest_scheduler_initial_load_failed'
```

**Acceptance:** all `up == 1`; counters monotonic; нет 5xx; нет recurrence BUG-030. Если что-то fail — **STOP**, документировать в watch note + (опционально) `curl` в `INCIDENT_WEBHOOK_URL` чтобы поднять issue через automation `7b35ca01`.

---

### M-9. Closure session (T+24h, ~13:50 MSK 25-05) — **полу-автоматизировано**

| Шаг | Что делает кто | Что делает оператор |
|---|---|---|
| 1 | Automation `f93e557a` сработает в 10:50Z, откроет GitHub issue со closure чеклистом C-1…C-8 | Открыть issue, использовать как live чеклист |
| 2 | Automation `2bd25769` (запустилась в 06:05Z) уже либо открыла regression issue (RED), либо нет (GREEN) | Прочитать результат P0-4 (один из этих исходов) |
| 3 | Прогнать C-1…C-8 руками через ssh + Prometheus queries (см. body issue) | Записать каждый чек pass/fail в issue body |
| 4 | Зафайлить **BUG-029** и **BUG-030** как отдельные issues если ещё не зафайлены | Создать issues с label `bug`, link на `BUG_LOG.md` |
| 5 | Если все C-1…C-8 GREEN — обновить `docs/notes/REVIEW_2026-05-24_WAVE1_STEP4_DONE.md` секцию «Closure» с результатом; close closure issue | commit + push отдельной PR |
| 6 | Если RED — следовать § 8 escalation matrix в [`WAVE1_STEP4_VPS_WATCH_SESSION_EXERCISE_PLAN.md`](WAVE1_STEP4_VPS_WATCH_SESSION_EXERCISE_PLAN.md) | rollback decision tree |
| 7 | Disable обе scheduled automations (`2bd25769`, `f93e557a`) после closure чтобы не fire'или повторно если оставить watch открытым на больше | `update_automation(automationId, enabled=false)` через MCP, ИЛИ UI toggle |
| 8 | (Опционально) Оставить webhook automation `7b35ca01` enabled для long-tail incident detection | — |

---

## 2. Что **не делать руками** (potential trap)

| Анти-действие | Почему trap |
|---|---|
| `tg-parser db downgrade` без operator authorization | Real prod data |
| `unsubscribe_digest(94483db9-9351-4f99-9aec-46949d9ddd09)` | S-1 — это real user's subscription |
| `subscribe_*(... chat_id=5445781511 ...)` | S-2 — будет спамить real user'а |
| `subscribe_*(... target={"kind":"channel", "channel_id":<real_owner_channel>} ...)` | S-3 — real owner не давал consent |
| `force_resummarize` или `trigger_pipeline` без admin role | 403; даже с admin role — повышает blast radius во время watch |
| Прямые SQL `UPDATE digest_subscriptions ...` | Bypass'ит business invariants + audit_log |
| Force-trigger digest_94483db9 cron для ускоренной проверки P0-4 | Меняет real-prod observable; нарушает passive observation principle |
| Тротлинг `cron_expression='* * * * *'` (каждую минуту) на test subscription | DDoS prod publish path + LLM bills |

---

## 3. Связанные документы

* Watch note: [`docs/notes/WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md`](../notes/WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md)
* Full exercise plan: [`docs/runbooks/WAVE1_STEP4_VPS_WATCH_SESSION_EXERCISE_PLAN.md`](WAVE1_STEP4_VPS_WATCH_SESSION_EXERCISE_PLAN.md)
* Automations registry: [`docs/runbooks/WAVE1_STEP4_VPS_WATCH_AUTOMATIONS.md`](WAVE1_STEP4_VPS_WATCH_AUTOMATIONS.md)
* Deploy runbook: [`docs/runbooks/WAVE1_STEP4_DEPLOY_AND_WATCH.md`](WAVE1_STEP4_DEPLOY_AND_WATCH.md)
* ADR 0008: [`docs/adr/0008-subscription-target-model.md`](../adr/0008-subscription-target-model.md)
