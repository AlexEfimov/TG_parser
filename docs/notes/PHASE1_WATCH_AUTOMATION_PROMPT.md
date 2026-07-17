# Phase-1 watch automation — agent prompt (copy into Automations editor)

Use this as the automation instructions field. Keep in sync when changing the watch procedure.

```
You are running a scheduled Phase-1 observation re-snapshot for the TG_parser project (repo AlexEfimov/TG_parser, base main). Read-only prod metric collection; deliver analysis via a docs PR (do NOT merge).

0. FIRST (mandatory): run `bash scripts/cursor_cloud_setup_prod_ssh.sh`. Confirm `ssh prod` works (`ssh -o BatchMode=yes prod 'echo ok'`). If SSH fails, stop and open a docs-PR documenting Gap #5 — do not fabricate metrics. Do not skip this step even if install already ran.
1. Read docs/notes/PHASE1_WATCH_BASELINE_2026-07-15.md for the t0 baseline (t0=2026-07-15T12:22:05Z), the t1/t2 re-snapshot sections, the EXACT Prometheus queries, and the PASS/FAIL criteria for the three watches: W1 (BUG-084 embedding quota/alert soak), W2 (S3 pre-LLM dedup), W3 (S5/S6 post-deploy).
2. SSH to prod (`ssh prod`, 212.72.189.15:2296, repo /home/user/TG_parser) and query the Prometheus HTTP API using the SAME queries to capture a new snapshot. Record the UTC timestamp and elapsed time since t0. See docs/runbooks/S1_S3_DEPLOY_AND_WATCH.md and docs/runbooks/CURSOR_CLOUD_PROD_SSH.md.
3. Analyze t0 -> t1 -> latest per watch; give each a PASS / FAIL / INTERIM / INCONCLUSIVE verdict. Focus on W2/S3: billing-clean window, target 48–72h after t0; FINAL only inside/after that window with live data.
4. Append a dated re-snapshot section to docs/notes/PHASE1_WATCH_BASELINE_2026-07-15.md (docs-only). Open a docs PR against main — do NOT merge.
5. In the PR body: state clearly whether W2 is FINAL or not, and whether the automation should stay ENABLED (stay enabled until W2 FINAL).
6. Never fabricate Prometheus values. Never merge the PR. Never disable the automation yourself unless W2 has a FINAL verdict from live data.
```
