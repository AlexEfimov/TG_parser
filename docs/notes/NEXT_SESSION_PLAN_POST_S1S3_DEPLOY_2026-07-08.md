# Next-session plan — post S1–S3 deploy (2026-07-08)

**Тип:** краткий hand-off план для следующей сессии.
**Контекст:** блок S1+S2+S3 смержен (#299/#300/#301) и задеплоен на VPS prod (код `5de040d`; `origin/main`=`ed3df37`, docs-only). Пост-деплой watch выявил 2 pre-existing блокера. BUG-082 частично митигирован.
**Опорные доки:** [`WORKFLOW_REMEDIATION_SESSIONS_AGREEMENTS_2026-07-07.md`](WORKFLOW_REMEDIATION_SESSIONS_AGREEMENTS_2026-07-07.md), [`S0_BASELINE_PROCESSING_METRICS_2026-07-07.md`](S0_BASELINE_PROCESSING_METRICS_2026-07-07.md), [`../runbooks/S1_S3_DEPLOY_AND_WATCH.md`](../runbooks/S1_S3_DEPLOY_AND_WATCH.md), [`BUG_LOG.md`](BUG_LOG.md) (BUG-082).

---

## P0 — Anthropic billing block (разблокировать прод) ✅
Хронический pre-existing блокер, доминирующий ограничитель throughput; заморозил дневную обработку 2026-07-08 (`anthropic_billing_block{processing}=156` за 21h; `haiku error`=156 = все billing).
- [x] Проверить состояние аккаунта/лимитов → [`../runbooks/ANTHROPIC_BILLING_RECOVERY.md`](../runbooks/ANTHROPIC_BILLING_RECOVERY.md). **Снят 2026-07-10 evening UTC.**
- [x] Снять паузы источников после восстановления (авто-resume на след. тике; проверить `anthropic_billing_source_paused`).
- **AC:** `sum(increase(tg_parser_anthropic_billing_block_total[1h]))` → 0; `tg_parser_llm_requests_total{model=haiku,status=success}` снова растёт по тикам. **PASS 2026-07-11:** billing 24h=0, haiku success ≈1037/24h.

## P1 — Подтвердить митигейт BUG-082 ✅
Применён: `DB_POOL_SIZE` 5→10 (max 20), live на prod. Merge `6904b0b` на prod.
- [x] Проверить, что рецидива нет: `ssh prod 'cd /home/user/TG_parser && docker compose logs --since 6h tg_parser | grep -c "QueuePool limit"'` — **0 за 24h (2026-07-11).**
- [ ] Если чисто ≥12h — дописать в BUG-082 строку «mitigation applied 2026-07-08: DB_POOL_SIZE 5→10» + при желании закрыть до `mitigated`.
- [ ] Полный fix (future, опционально): выделенный engine под advisory-lock; переклассификация DB `TimeoutError` из `llm_error` в `db_error` (resummarize outcome).
- **Rollback митигейта:** restore `~/TG_parser/.env.bak_bug082_poolsize_*` + `docker compose up -d --no-deps tg_parser`.

## P2 — Чистая токен-дельта S3 (главный замер эффекта) ✅
На +24h окно измерить не удалось (простой + billing). Нужен полный день активной обработки БЕЗ billing-блоков.
- [x] После P0 — прогнать ~24h, затем снять по [`../runbooks/S1_S3_DEPLOY_AND_WATCH.md`](../runbooks/S1_S3_DEPLOY_AND_WATCH.md) § Watch:
      `tg_dedup_pre_llm_hits_total` (рост) vs `tg_parser_llm_requests_total{haiku,success}` (снижение доли), `tg_dedup_duplicates_detected_total`.
- **AC:** pre-LLM hits растёт; coverage не падает. **Вердикт 2026-07-11:** `S3 effect: PARTIAL` — 6 pre-LLM hits/7d (Prometheus), 0 в billing-clean 24h; coverage ≥ baseline (T1 OK). Детали: [`S3_DELTA_WATCH_2026-07-11.md`](S3_DELTA_WATCH_2026-07-11.md), S0 §5.

## P3 — Зафиксировать документацию (partial)
- [x] Записать `after-block` снапшот в `S0_…md` §5 (`after-block-S3-billing-clean-2026-07-11`).
- [x] Executive summary: [`S3_DELTA_WATCH_2026-07-11.md`](S3_DELTA_WATCH_2026-07-11.md).
- [x] Отметить в WORKFLOW §8: P2 watch done + ссылка на S3 delta.

## Дальше по плану remediation (когда прод стабилен)
- **S4** (F-04/F-05, топикизация) — деплой отдельно, с read-only симуляцией (WORKFLOW §3). **S5** (F-10), **S6** (F-12/F-13), **S7** (O-9b + Low-диспозиции). Порядок строго последовательный.

---

## Быстрый статус-снимок прода (скопировать в начало сессии)
```bash
ssh prod 'cd /home/user/TG_parser && echo "HEAD $(git rev-parse --short HEAD)"; docker compose ps --format "table {{.Service}}\t{{.Status}}"; M=$(curl -s localhost:8000/metrics); \
 echo "pre-LLM:"; echo "$M"|grep "^tg_dedup_pre_llm_hits_total"; \
 echo "billing:"; echo "$M"|grep "^tg_parser_anthropic_billing_block_total"; \
 echo "QueuePool 6h:"; docker compose logs --since 6h tg_parser|grep -c "QueuePool limit"; \
 echo "coverage:"; echo "$M"|grep "^tg_channel_processed_coverage_ratio"'
```

**Известные не-блокеры (не пугаться):** OpenAI embeddings `429` (отдельный rate-limit, свой backlog); watchlist `score_sum=0` при `semantic_unavailable` (BUG-060 by design).
