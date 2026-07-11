# S3 delta watch — executive summary (P2, 2026-07-11)

**Тип:** post-deploy measurement (read-only prod).
**Стартовый промпт:** [`START_PROMPT_P2_S3_DELTA_WATCH_2026-07-11.md`](START_PROMPT_P2_S3_DELTA_WATCH_2026-07-11.md).
**Полный снапшот:** [`S0_BASELINE_PROCESSING_METRICS_2026-07-07.md`](S0_BASELINE_PROCESSING_METRICS_2026-07-07.md) §5.

---

## Вердикт (одна строка)

```
S3 effect: PARTIAL  |  S4: GO
```

Pre-LLM dedup **работает** (6 hits/7d по Prometheus, 3 канала), но в billing-clean 24h-окне hits=0 при ~1014 post-LLM dedup и ~1037 haiku success — эффект ещё не проявился на живом трафике из-за immature `raw_content_hash` корпуса. Coverage **не регрессировал** (T1 OK). Rollback не нужен.

---

## Measurement window

| Окно | Обоснование |
|---|---|
| **Primary: billing-clean 24h** | `billing_block[24h]=0`, haiku error=0, ~1037 success/24h — первый полный день активной обработки после P0 |
| **Secondary: 7d post-deploy** | Для накопленных pre-LLM hits (6 total); confounded billing (~8196 blocks) |

Рестарт BUG-082 (`2026-07-10T19:46Z`) сбросил since-restart counters — вердикт только по `increase[]`.

---

## Ключевые цифры

| Метрика | S0 (7d) | billing-clean 24h | 7d post-deploy |
|---|---|---|---|
| pre-LLM hits | — | **0** | **≈6** |
| post-LLM dedup | ≈1559 | ≈1014 | ≈5191 |
| haiku success | ≈5617 | ≈1037 | ≈8806 |
| haiku error | ≈14968 | **0** | ≈8142 |
| billing blocks | — | **0** | ≈8196 |
| QueuePool errors | — | **0** | — |

**Per-channel pre-LLM (7d):** Docma_ru=3, labdiagnostica_logical=2, Lab4health=1.

**Coverage (T1):** Docma_ru 0.992↑, labdiagnostica 0.998↑, Lab4health 0.998↑ — все ≥ S0 baseline.

---

## Логи

- `grep pre_llm_dedup_hit` за 24h и 7d: **0 событий** (log retention ≈11h после рестарта; 6 Prometheus-hits накоплены до рестарта).
- `parallel_batch_complete.pre_llm_dedup` за 24h: всегда 0.

---

## Confounders

1. Billing простой 2026-07-07..2026-07-10 (P0 снят ~2026-07-10 evening).
2. BUG-082 restart сбрасывает counters.
3. BUG-084 embeddings 429 (229/24h) → degraded ticks, не связано с S3.
4. Immature `raw_content_hash` — старые processed_documents без hash не матчатся pre-LLM.

---

## Рекомендации

1. **Forward watch (48–72h):** повторить `increase(tg_dedup_pre_llm_hits_total[48h])` и сравнить с post-LLM dedup в том же окне.
2. **S4:** можно открывать — coverage OK, нет T1, S3 PARTIAL не блокирует.
3. **Не rollback S3** — механизм подтверждён, coverage улучшился.

---

*Prod HEAD `6904b0b`, снято 2026-07-11T07:07Z.*
