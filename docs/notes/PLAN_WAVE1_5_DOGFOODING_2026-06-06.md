# Wave 1.5 Operational Dogfooding — Plan & Tracker

**Тип документа:** living tracker (не sprint plan, не closure marker)

**Назначение:** operational-companion к
[`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 5.2](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md) (Wave 1.5 определение), § 5.3 (Decision Point matrix), § 9 (validation hypotheses). Strategy doc отвечает на «что мы хотим понять и почему»; этот документ отвечает на «как именно фиксируем сигналы, какая cadence, когда триггерится Decision Point».

**Дата создания:** 2026-06-06 ~14:30 UTC+4

**Branch:** `docs/wave1-5-plan-2026-06-06`

**Parent closure:** [`REVIEW_2026-06-03_WAVE1_DONE.md`](REVIEW_2026-06-03_WAVE1_DONE.md) (Wave 1 audience-driven product scope closed; tag `v4.4.0` on `6ec3574`)

**Status:** `active` (с 2026-06-06 до Decision Point — см. § 9 exit criteria)

**Expected duration:** 3–4 месяца (orientation per `PRODUCT_STRATEGY § 5.3`; **cadence-driven, не deadline-driven** — exit по любому из triggers § 9)

---

## 1. TL;DR

Wave 1.5 — это **привычка**, не sprint. Три параллельных потока (daily personal use / 2–3 external validators / 1–2 hours market research) генерируют **signal data** для матрицы Decision Point (§ 5.3 strategy). Цель — выйти к выбору Wave 2A / 2B / 2C / continue / pivot **на данных**, а не на интуиции. Документ — живой tracker с signal counter и review log; завершается отдельным `REVIEW_*_WAVE1_5_DONE.md` или встроенным Decision Point doc.

---

## 2. Disambiguation: какая Wave 1.5

В проекте исторически **два разных «Wave 1.5»**:

| | Старая Wave 1.5 | **Новая Wave 1.5 (этот документ)** |
|---|---|---|
| Источник | [`ROADMAP_V3_PRODUCTION_FIRST.md`](ROADMAP_V3_PRODUCTION_FIRST.md) | [`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 5.2](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md) |
| Scope | RAG & Prompt Config (YAML prompts, per-stage LLM, `RAG_LLM_PROVIDER`) | Operational Dogfooding (daily use + validation + market research) |
| Статус | ✅ **DONE** (давно) | 🟢 **active** (с 2026-06-06) |
| Тип | Engineering sprint | Living operational habit |

Aggregate marker явно фиксирует: *«Wave 1.5 (RAG & Prompt Config per ROADMAP_V3) was completed earlier in the project timeline and is orthogonal to this audience-driven Wave 1 sequence»* ([`REVIEW_2026-06-03_WAVE1_DONE.md:105`](REVIEW_2026-06-03_WAVE1_DONE.md)).

**Везде ниже «Wave 1.5» = новая, audience-driven, operational dogfooding.**

---

## 3. Goals

Что **должно остаться на руках** после Wave 1.5 — **до** того как стартовать Wave 2:

1. **Validated priority list** для Wave 2 — какие friction-points / feature requests реальны (≥1 раз спросили / накопились), какие просто гипотезы.
2. **Demand signal evidence** — есть ли внешний интерес, какого типа (AI integrators / content consumers / teams), сколько раз.
3. **Decision Point input** — заполненная матрица § 5.3 strategy с **конкретными ссылками** на signals (stars / DMs / search hits), а не «кажется».
4. **Внутренний baseline** — насколько TG_parser реально полезен **owner'у**: количество daily uses, количество запросов через bot/MCP, growth `docs/topics` count.

**Anti-goal:** НЕ нарастить feature surface. НЕ построить Wave 2 «на всякий случай». НЕ commit'нуться к выбору Wave 2A/B/C раньше evidence threshold (§ 7).

---

## 4. Scope: три потока

### 4.1 Поток 1 — Daily Personal Use

| | |
|---|---|
| **Что делать** | Использовать TG_parser ежедневно для собственных каналов (bot + MCP + occasional CLI). Реальный workflow: `ask`, `search_knowledge_base`, `list_topics`, digest подписки, watchlist подписки, export. |
| **Как фиксировать** | Каждое «бесит, что нельзя X» → запись в [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) с тэгом `[wave1.5-dogfood]`. Каждый bug → запись в [`BUG_LOG.md`](BUG_LOG.md) (severity по обычным правилам). |
| **Owner** | Solo |
| **Cadence** | Ежедневно, естественное use. Не блокирующее. |
| **Anti-scope** | НЕ строить новые фичи прямо сейчас. НЕ исправлять non-critical bugs (только log). НЕ переписывать на «как должно быть» без real friction. |
| **Success criteria** | ≥1 запись/неделю в `FUTURE_FEATURES` или `BUG_LOG` с тэгом `[wave1.5-dogfood]`. Рост content (см. § 8 baseline). |

### 4.2 Поток 2 — Light External Validation

| | |
|---|---|
| **Что делать** | Дать 2–3 знакомым попробовать минимум через MCP server (если AI users) или подписку на digest channel (если consumers). Без формального onboarding. |
| **Как фиксировать** | Friction observations → этот документ, секция § 11 (review log) или отдельный `WAVE1_5_VALIDATION_LOG.md` (создавать только при ≥3 observations, чтобы не плодить пустые файлы). |
| **Owner** | Solo (setup); validators — внешние (друзья / коллеги / подписчики). |
| **Cadence** | Onboard каждого один раз → пассивно слушать. **НЕ опрашивать активно.** |
| **Anti-scope** | НЕ строить focus group. НЕ обещать timeline. НЕ давать roadmap. НЕ просить структурированные feedback forms. |
| **Success criteria** | ≥2 активных validator'а (хоть одно реальное interaction за месяц). ≥3 friction observations за 4 недели. |

### 4.3 Поток 3 — Light Market Research

| | |
|---|---|
| **Что делать** | Прогнать конкретный список search terms (§ 6) по HN / Reddit / GitHub / PyPI / MCP marketplaces. Зафиксировать competitors (direct / indirect) и demand signals. |
| **Как фиксировать** | Один документ-snapshot: `WAVE1_5_MARKET_SCAN_2026-MM-DD.md` (создаётся после deep dive). Hits / no-hits / sample links. |
| **Owner** | Solo. |
| **Cadence** | **Один deep dive (1–2 часа)** в первый месяц + lightweight monitoring (subscribed на relevant subreddits / HN keywords). |
| **Anti-scope** | НЕ инвестировать недели. НЕ делать product-market fit research в рамках Wave 1.5 (это Wave 2 territory). НЕ строить competitive matrix на 50 продуктов. |
| **Success criteria** | Документ с validated hypothesis по каждому пункту § 6: «competitors есть/нет, почему». |

---

## 5. Decision Point matrix (по § 5.3 strategy)

Эта секция — **источник истины** для принятия решения о Wave 2 направлении. Обновляется при каждом 2-week review (см. § 8).

| Signal pattern | Wave 2 direction | Counter | Threshold | Evidence (links / dates) |
|---|---|---|---:|---|
| Пользователи AI-ассистентов (Cursor/Claude) ставят MCP server; GitHub stars начинают появляться | **2A (A4: integrators)** | 0 | ≥3 distinct signals | _empty_ |
| Знакомые / подписчики digest-канала пишут «а где смотреть подробнее?» / просят web view | **2B (A5/A6: web consumer)** | 0 | ≥3 distinct asks | _empty_ |
| Кто-то **реально просит** team-collaboration / sharing workspaces | **2C (A3: team)** | 0 | ≥1 strong/serious ask (не «было бы прикольно») | _empty_ |
| Никто не растёт, но **owner активно использует** | continue dogfooding, не строить publicity | n/a | ongoing baseline | _baseline check § 8_ |
| Никто не растёт **и** owner тоже не использует активно | **hard signal к pivot или паузе** | n/a | критический | _trigger immediate review_ |

**Threshold rationale:** 1 signal = anecdote, 3 signals = pattern. Для 2C — порог ниже (1 strong ask), потому что team collab — это binary signal (либо есть запрос, либо нет; обычно люди не просят такое случайно).

**Evidence форматы:**
- AI integrators: GitHub stars (ссылка на repo activity), MCP marketplace mentions, Twitter / blog references
- Consumer: DM / message / quote (анонимизированный текст + дата)
- Team: explicit запрос с use case (кто, для какой команды, почему MCP/digest не покрывает)

---

## 6. Validation hypotheses (skopировано из § 9 strategy)

Прогнать **один раз** в течение первого месяца как market research deep dive. Чек-боксы — для tracking что проверено.

### 6.1 Direct competitor search

- [ ] **GitHub:** `telegram rag`, `telegram knowledge base`, `telegram channel embeddings`, `telegram mcp server`, `telegram chat history rag`
- [ ] **PyPI:** те же ключевые слова
- [ ] **npm:** те же ключевые слова
- [ ] **MCP marketplaces:** [Smithery](https://smithery.ai), Cline marketplace (`docs.cline.bot/mcp-servers/mcp-marketplace`), [Anthropic MCP directory](https://github.com/modelcontextprotocol/servers)

### 6.2 Indirect / adjacency

- [ ] `tlgur.com`, `tgstat.ru`, `combot.org` — analytics, не RAG, но смежная аудитория
- [ ] [Recall.ai](https://recall.ai), Glasp (`glasp.co`) — capture + annotate web/youtube
- [ ] [Pocket](https://getpocket.com), [Readwise](https://readwise.io) — capture + AI summarize
- [ ] [Notion AI](https://notion.so), [Mem.ai](https://mem.ai) — general KB с RAG

### 6.3 Demand signal

- [ ] **Reddit:** `r/Telegram`, `r/LocalLLaMA`, `r/ObsidianMD`, `r/SideProject`, `r/SaaS` — search `telegram RAG`, `telegram knowledge base`, `telegram extract data`
- [ ] **HN:** [Algolia search](https://hn.algolia.com) by `telegram channel`, `telegram rag`, `telegram archive`
- [ ] **Telegram-сообщества:** Python / AI / RAG developer chats — поиск «у меня каналов накопилось, как искать»

### 6.4 Anti-pattern note

> «Нет конкурентов» часто означает «нет рынка», а не «огромная возможность». Нужно понять **почему** нет (technical barrier? legal — § 7.1 strategy grey area? просто нет спроса?). Это информирует strategic positioning. — `PRODUCT_STRATEGY § 9`

Зафиксировать в research-snapshot **гипотезу почему**, не только список hits/no-hits.

---

## 7. Definition of "Wave 1.5 complete" / exit criteria

Wave 1.5 завершается **одним из** triggers (что наступит первым):

1. **5+ signals одного типа** в § 5 таблице → **trigger Decision Point session** → выбор Wave 2X с обоснованием.
2. **3–4 месяца прошло с 2026-06-06** → **forced Decision Point** даже с минимумом signals (фиксируем «не нашли catalyst → continue dogfooding или pause»).
3. **Hard pivot signal** (owner inactive **и** no growth) → **немедленная пауза** + re-evaluate (см. § 7.1 strategy про legal, § 4.6 про OSS vs commercial).
4. **Внешний catalyst** (большая внешняя возможность — например, MCP стандарт реально взлетает, или появляется paying customer) → override timing, fast-track в Wave 2.

**Каждый exit пишет:**
- Отдельный `REVIEW_YYYY-MM-DD_WAVE1_5_DONE.md` со ссылкой на этот документ (если exit clean)
- Или встроенный Decision Point doc `DECISION_POINT_YYYY-MM-DD.md` (если выбор Wave 2 происходит немедленно после)

После закрытия — этот документ архивируется (status `closed`, banner `SUPERSEDED` сверху, как делали для START_PROMPT после implementation).

---

## 8. Operational cadence

| Cadence | Action | Output |
|---|---|---|
| **Daily** | Просто использовать продукт; log friction immediately в `FUTURE_FEATURES` / `BUG_LOG` с тэгом `[wave1.5-dogfood]` | живые записи |
| **Weekly (опционально)** | Quick check: что добавилось за неделю; sanity check growth (docs / topics count) | mental note |
| **2-week review (обязательно)** | Structured retro: append секцию в § 11 review log | row в § 11 |
| **Monthly** | Дашборд: Prometheus / Grafana — growth `docs` (baseline 5405+), `topics` (baseline 401+), `topic_links` (baseline 264+); latency baselines | row в § 11 |
| **At month 3** OR **на любом ≥5 signals одного типа** OR **hard pivot signal** | Триггер Decision Point session | exit per § 7 |

### 8.1 2-week review template (для § 11)

```
| <date> | period N (YYYY-MM-DD to YYYY-MM-DD) | <X friction entries added> | <X validators active> | <market signal y/n> | <DP status: not triggered / X signals / triggered> | <free-form notes> |
```

### 8.2 Baseline (на момент создания, 2026-06-06)

| Метрика | Baseline | Источник |
|---|---|---|
| Documents in KB | 5405+ | aggregate marker / README |
| Topics | 401+ | aggregate marker / README |
| Topic links | 264+ | aggregate marker / README |
| Prod git HEAD | `b04353b` (Wave 1 closure SHA) | aggregate § 2 |
| Tag | `v4.4.0` | 2026-06-06 |
| Open BUGs (non-deferred) | 4 (BUG-008, 019, 020, 021) | post-closure audit |
| Deferred BUGs → Wave 2 | 3 (BUG-025, 026, 027) | aggregate § 5 |
| MCP tools | 43 | README |
| Bot tools | 32 | README |

Growth метрики против этого baseline = индикатор «owner активно использует» (§ 5 row 4–5).

---

## 9. Anti-scope (что Wave 1.5 НЕ делает)

- ❌ **НЕ начинаем Wave 2 work** до Decision Point exit
- ❌ **НЕ строим Web UI / OAuth / team sharing** «на всякий случай»
- ❌ **НЕ опрашиваем агрессивно** валидаторов (только observation)
- ❌ **НЕ строим формальный customer development / interview pipeline**
- ❌ **НЕ инвестируем больше 1–2 часов** в market research deep dive
- ❌ **НЕ исправляем non-critical bugs** (только log в `BUG_LOG` / `FUTURE_FEATURES`)
- ❌ **НЕ создаём marketing / outreach** (Wave 2A territory)
- ❌ **НЕ commit'имся к Wave 2 направлению** на первом signal — нужен threshold (§ 5)
- ❌ **НЕ создаём `docs/methodology/**`** — нормативная конвенция [`AGENTS.md`](../../AGENTS.md)

---

## 10. Risk register

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R-1 | **Wave 1.5 «забудется»** — нет sprint-cadence enforcement | Medium | 2-week review reminder в § 11; minimum row в review log каждые 2 недели даже если «ничего нет» |
| R-2 | **False signals** — один знакомый ≠ market | High | Threshold ≥3 distinct signals в § 5; для 2C — explicit «strong/serious» quality bar |
| R-3 | **Premature Wave 2 commit** — паника при первом signal | High | 5-signal threshold; принудительная задержка на 2 review cycles перед triggering DP досрочно |
| R-4 | **Backlog growth без фильтра** — FUTURE_FEATURES раздувается | Medium | Severity tag на новых entries: `[wave1.5-dogfood]`; ежемесячный prune (remove если duplicate / низкий impact) |
| R-5 | **Solo bias** — owner использует только сам, не приглашает validators | High | Weekly self-check: «делаю ли setup для 2–3 validator'ов»; если 0 — escalate в § 11 notes |
| R-6 | **Market scan procrastination** — research deep dive откладывается > 1 месяца | Low | Hard deadline: market scan до 2026-07-06 (1 месяц от создания); если не сделан — record «skipped» в § 11 |
| R-7 | **Production degradation** во время dogfooding | Low | Monthly Prometheus / Grafana check; обычные runbooks ([`docs/runbooks/`](../runbooks/)) если что-то сломается |

---

## 11. Review log (живая секция)

| Date | Period | Friction added (`FUTURE_FEATURES` / `BUG_LOG`) | External validators active | Market signal observed | DP signal counter (2A / 2B / 2C) | DP status | Notes |
|---|---|---|---|---|---|---|---|
| 2026-06-06 | — (created) | 0 | 0 | baseline | 0 / 0 / 0 | not triggered | document created on `docs/wave1-5-plan-2026-06-06` |
| _next: 2026-06-20_ | period 1 | | | | | | _to fill at first 2-week review_ |
| _next: 2026-07-04_ | period 2 | | | | | | |
| _next: 2026-07-18_ | period 3 | | | | | | |
| _next: 2026-08-01_ | period 4 | | | | | | |
| _next: 2026-08-15_ | period 5 | | | | | | _3 months reached — forced DP check_ |
| _next: 2026-09-01_ | period 6 | | | | | | _4 months — hard exit per § 7_ |

---

## 12. Связанные документы

### Strategic

| Документ | Зачем |
|---|---|
| [`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md`](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md) | § 5.2 Wave 1.5 определение, § 5.3 Decision Point matrix, § 9 validation hypotheses |
| [`REVIEW_2026-06-03_WAVE1_DONE.md`](REVIEW_2026-06-03_WAVE1_DONE.md) | Parent closure — что shipped в Wave 1 |
| [`ROADMAP_KARPATHY_LIKE_LIVING_KB.md`](ROADMAP_KARPATHY_LIKE_LIVING_KB.md) | Current direction snapshot |
| [`MONETIZATION_MECHANISMS_2026-05-02.md`](MONETIZATION_MECHANISMS_2026-05-02.md) | Если signals будут pricing-related — здесь модели per-segment |

### Signal capture

| Документ | Что капчим |
|---|---|
| [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) | Feature requests / «бесит что нельзя X» |
| [`BUG_LOG.md`](BUG_LOG.md) | Bugs / friction technical |
| `WAVE1_5_MARKET_SCAN_YYYY-MM-DD.md` | One-shot market research snapshot (создаётся после deep dive) |
| `WAVE1_5_VALIDATION_LOG.md` | External validator observations (создаётся при ≥3 records, не сразу) |

### Disambiguation / historical

| Документ | Что |
|---|---|
| [`ROADMAP_V3_PRODUCTION_FIRST.md`](ROADMAP_V3_PRODUCTION_FIRST.md) | **Старая** Wave 1.5 (RAG & Prompt Config) — DONE, для disambiguation |

### Operational

| Документ | Когда смотреть |
|---|---|
| [`AGENTS.md`](../../AGENTS.md) | Forbidden actions (commit без запроса, methodology, pyproject) |
| [`docs/quality/AGENT_PLAYBOOK.md`](../quality/AGENT_PLAYBOOK.md) | DONE-marker template для exit |

---

## 13. История документа

| Date | Author / agent | Change |
|---|---|---|
| 2026-06-06 | Solo + foreground agent | Document created on `docs/wave1-5-plan-2026-06-06` (after subagent OOM on first attempt). Initial scope: § 1–§ 12. |

---

> **Reminder:** этот документ — **живой tracker**. Каждый 2-week review добавляет row в § 11. Decision Point trigger пишет exit doc (§ 7). НЕ переписывать структуру без явной необходимости.
