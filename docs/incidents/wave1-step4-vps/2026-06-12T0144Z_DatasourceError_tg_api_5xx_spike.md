# [5xx] DatasourceError (Wave 1 step 4 VPS watch)

> **Filing context.** This markdown is the verbatim body of the GitHub issue
> that the Wave 1 step 4 VPS watch-window incident ingress (Cursor automation
> `7b35ca01-a7d1-4c3a-bb8b-940918e506d6`) would have opened in
> `AlexEfimov/TG_parser`. The automation runs in a read-only cloud-agent
> sandbox whose `gh` token has zero write scope on the target repo, so the
> deliverable is filed as a committed artifact on branch
> `cursor/vps-watch-incident-ingress-b490` for the operator to forward. Title /
> labels / sections match the agent contract.
>
> * **Intended title:** `[5xx] DatasourceError (Wave 1 step 4 VPS watch)`
> * **Intended labels:** `wave1-step4-watch`, `vps`, `alert`
> * **Group key:** `{}:{alertname="DatasourceError", grafana_folder="wave1-step4-watch"}`
> * **Fingerprints (dedupe keys, one payload = one issue):**
>   `b5a3e0633aff0a2f` (tg_api_5xx_spike), `ee79af1ca55d3c5c`
>   (tg_parser_api_down), `42fe0f4e137067ac` (tg_parser_bot_down).
> * **Re-trigger note.** The identical group/fingerprints have already been
>   filed by six prior ingress runs:
>   * branch `cursor/vps-watch-incident-ingress-8551` — trigger `2026-06-06T15:03Z`
>   * branch `cursor/vps-watch-incident-ingress-c056` — trigger `2026-06-07T07:23Z`
>   * branch `cursor/vps-watch-incident-ingress-7045` — trigger `2026-06-07T19:38Z`
>   * branch `cursor/vps-watch-incident-ingress-de76` — trigger `2026-06-08T20:08Z`
>   * branch `cursor/vps-watch-incident-ingress-e520` — trigger `2026-06-08T21:29Z`
>   * branch `cursor/vps-watch-incident-ingress-8a68` — trigger `2026-06-09T08:23Z`
>
>   This is the **same payload re-delivered** at automation trigger time
>   `2026-06-12T01:44Z`. Per the agent contract `one payload = at most one
>   issue`, a *new* delivery of the same firing group is treated as an explicit
>   re-trigger; this artifact records the new ingress run and supersedes the
>   prior ones for tracking. No additional follow-ups beyond this single file.
>   The persistence of this group across ~6 days strongly indicates a
>   **stale/leftover rule set erroring against a torn-down Prometheus** rather
>   than a live incident (see `## Next steps` — the rules should be silenced).

---

## Source

`grafana` — Grafana alerting webhook v9 payload (`[FIRING:3]`), delivered to
the Cursor automation webhook for the `cursor-watch-webhook` contact point.

* `commonLabels.grafana_folder` = `wave1-step4-watch` (all three rules belong
  to this watch window's folder).
* `commonLabels.datasource_uid` = `prometheus`.
* Generator URLs (Grafana bound to VPS `localhost:3000`; operator must
  SSH-tunnel `-L 3000:localhost:3000` or use the configured reverse proxy —
  the ingress itself does **not** SSH):
  * `tg_api_5xx_spike` (severity=warning) →
    <http://localhost:3000/alerting/grafana/bug036_tg_api_5xx_spike/view?orgId=1>
  * `tg_parser_api_down` (severity=critical) →
    <http://localhost:3000/alerting/grafana/bug036_tg_parser_api_down/view?orgId=1>
  * `tg_parser_bot_down` (severity=critical) →
    <http://localhost:3000/alerting/grafana/bug036_tg_parser_bot_down/view?orgId=1>

## Summary

Three watch rules fired simultaneously, **all carrying `alertname =
DatasourceError`** (Grafana's meta-alert emitted when the configured
datasource returns an *error* — distinct from `DatasourceNoData`). Every alert
has `values: null` and `valueString: ""`, confirming the rule evaluator never
produced a numeric result.

| rulename | severity | summary | description |
|---|---|---|---|
| `tg_api_5xx_spike` | warning | 5xx responses on `POST /api/v1/(digests\|watchlists)` | `tg_parser_http_requests_total` 5xx rate on digests/watchlists is > 0 for 5m. |
| `tg_parser_api_down` | critical | tg_parser API is down | Prometheus scrape target `job=tg_parser_api` has reported `up==0` for 5m. |
| `tg_parser_bot_down` | critical | tg_parser bot is down | Prometheus scrape target `job=tg_parser_bot` has reported `up==0` for 5m. |

**Important caveat (what is actually firing).** This is *not* three
independent confirmed incidents. The common signal is `DatasourceError` on
`datasource_uid=prometheus` across every rule in the folder, with null values
— i.e. **Grafana could not query Prometheus**, so none of these rules could
evaluate true/false. The most likely operational meaning is a **Prometheus
datasource / scrape-pipeline outage** (Prometheus container down, wrong
datasource URL, auth failure, or Grafana→Prometheus network break), which
makes all dependent rules error at once. The underlying 5xx / api-down /
bot-down conditions are *unproven* until the datasource is healthy again. The
prefix is `[5xx]` purely by the deterministic alert-name rule (see
`## Agent contract trace`); the operator must triage the datasource first.

* `startsAt` = `2026-06-02T17:15:30Z` (all three) — within the watch window
  lineage (opened `2026-05-24T10:50:10Z`).
* `endsAt` = `0001-01-01T00:00:00Z` — *unresolved* (open-ended ⇒ still holding
  at automation trigger time `2026-06-12T01:44Z`, ~9.4 days after `startsAt`).

## Raw payload

```json
{
  "receiver": "cursor-watch-webhook",
  "status": "firing",
  "alerts": [
    {
      "status": "firing",
      "labels": {
        "alertname": "DatasourceError",
        "datasource_uid": "prometheus",
        "grafana_folder": "wave1-step4-watch",
        "ref_id": "A",
        "rulename": "tg_api_5xx_spike",
        "severity": "warning"
      },
      "annotations": {
        "description": "tg_parser_http_requests_total 5xx rate on digests/watchlists is > 0 for 5m.",
        "summary": "5xx responses on POST /api/v1/(digests|watchlists)"
      },
      "startsAt": "2026-06-02T17:15:30Z",
      "endsAt": "0001-01-01T00:00:00Z",
      "generatorURL": "http://localhost:3000/alerting/grafana/bug036_tg_api_5xx_spike/view?orgId=1",
      "fingerprint": "b5a3e0633aff0a2f",
      "silenceURL": "http://localhost:3000/alerting/silence/new?alertmanager=grafana&matcher=alertname%3DDatasourceError&matcher=datasource_uid%3Dprometheus&matcher=grafana_folder%3Dwave1-step4-watch&matcher=ref_id%3DA&matcher=rulename%3Dtg_api_5xx_spike&matcher=severity%3Dwarning&orgId=1",
      "dashboardURL": "",
      "panelURL": "",
      "values": null,
      "valueString": ""
    },
    {
      "status": "firing",
      "labels": {
        "alertname": "DatasourceError",
        "datasource_uid": "prometheus",
        "grafana_folder": "wave1-step4-watch",
        "ref_id": "A",
        "rulename": "tg_parser_api_down",
        "severity": "critical"
      },
      "annotations": {
        "description": "Prometheus scrape target job=tg_parser_api has reported up==0 for 5m.",
        "summary": "tg_parser API is down"
      },
      "startsAt": "2026-06-02T17:15:30Z",
      "endsAt": "0001-01-01T00:00:00Z",
      "generatorURL": "http://localhost:3000/alerting/grafana/bug036_tg_parser_api_down/view?orgId=1",
      "fingerprint": "ee79af1ca55d3c5c",
      "silenceURL": "http://localhost:3000/alerting/silence/new?alertmanager=grafana&matcher=alertname%3DDatasourceError&matcher=datasource_uid%3Dprometheus&matcher=grafana_folder%3Dwave1-step4-watch&matcher=ref_id%3DA&matcher=rulename%3Dtg_parser_api_down&matcher=severity%3Dcritical&orgId=1",
      "dashboardURL": "",
      "panelURL": "",
      "values": null,
      "valueString": ""
    },
    {
      "status": "firing",
      "labels": {
        "alertname": "DatasourceError",
        "datasource_uid": "prometheus",
        "grafana_folder": "wave1-step4-watch",
        "ref_id": "A",
        "rulename": "tg_parser_bot_down",
        "severity": "critical"
      },
      "annotations": {
        "description": "Prometheus scrape target job=tg_parser_bot has reported up==0 for 5m.",
        "summary": "tg_parser bot is down"
      },
      "startsAt": "2026-06-02T17:15:30Z",
      "endsAt": "0001-01-01T00:00:00Z",
      "generatorURL": "http://localhost:3000/alerting/grafana/bug036_tg_parser_bot_down/view?orgId=1",
      "fingerprint": "42fe0f4e137067ac",
      "silenceURL": "http://localhost:3000/alerting/silence/new?alertmanager=grafana&matcher=alertname%3DDatasourceError&matcher=datasource_uid%3Dprometheus&matcher=grafana_folder%3Dwave1-step4-watch&matcher=ref_id%3DA&matcher=rulename%3Dtg_parser_bot_down&matcher=severity%3Dcritical&orgId=1",
      "dashboardURL": "",
      "panelURL": "",
      "values": null,
      "valueString": ""
    }
  ],
  "groupLabels": {
    "alertname": "DatasourceError",
    "grafana_folder": "wave1-step4-watch"
  },
  "commonLabels": {
    "alertname": "DatasourceError",
    "datasource_uid": "prometheus",
    "grafana_folder": "wave1-step4-watch",
    "ref_id": "A"
  },
  "commonAnnotations": {},
  "externalURL": "http://localhost:3000/",
  "version": "1",
  "groupKey": "{}:{alertname=\"DatasourceError\", grafana_folder=\"wave1-step4-watch\"}",
  "truncatedAlerts": 0,
  "orgId": 1,
  "title": "[FIRING:3] DatasourceError wave1-step4-watch (prometheus A)",
  "state": "alerting",
  "message": "**Firing**\n\nValue: [no value]\nLabels:\n - alertname = DatasourceError\n - datasource_uid = prometheus\n - grafana_folder = wave1-step4-watch\n - ref_id = A\n - rulename = tg_api_5xx_spike\n - severity = warning\nAnnotations:\n - description = tg_parser_http_requests_total 5xx rate on digests/watchlists is > 0 for 5m.\n - summary = 5xx responses on POST /api/v1/(digests|watchlists)\nSource: http://localhost:3000/alerting/grafana/bug036_tg_api_5xx_spike/view?orgId=1\nSilence: http://localhost:3000/alerting/silence/new?alertmanager=grafana&matcher=alertname%3DDatasourceError&matcher=datasource_uid%3Dprometheus&matcher=grafana_folder%3Dwave1-step4-watch&matcher=ref_id%3DA&matcher=rulename%3Dtg_api_5xx_spike&matcher=severity%3Dwarning&orgId=1\n\nValue: [no value]\nLabels:\n - alertname = DatasourceError\n - datasource_uid = prometheus\n - grafana_folder = wave1-step4-watch\n - ref_id = A\n - rulename = tg_parser_api_down\n - severity = critical\nAnnotations:\n - description = Prometheus scrape target job=tg_parser_api has reported up==0 for 5m.\n - summary = tg_parser API is down\nSource: http://localhost:3000/alerting/grafana/bug036_tg_parser_api_down/view?orgId=1\nSilence: http://localhost:3000/alerting/silence/new?alertmanager=grafana&matcher=alertname%3DDatasourceError&matcher=datasource_uid%3Dprometheus&matcher=grafana_folder%3Dwave1-step4-watch&matcher=ref_id%3DA&matcher=rulename%3Dtg_parser_api_down&matcher=severity%3Dcritical&orgId=1\n\nValue: [no value]\nLabels:\n - alertname = DatasourceError\n - datasource_uid = prometheus\n - grafana_folder = wave1-step4-watch\n - ref_id = A\n - rulename = tg_parser_bot_down\n - severity = critical\nAnnotations:\n - description = Prometheus scrape target job=tg_parser_bot has reported up==0 for 5m.\n - summary = tg_parser bot is down\nSource: http://localhost:3000/alerting/grafana/bug036_tg_parser_bot_down/view?orgId=1\nSilence: http://localhost:3000/alerting/silence/new?alertmanager=grafana&matcher=alertname%3DDatasourceError&matcher=datasource_uid%3Dprometheus&matcher=grafana_folder%3Dwave1-step4-watch&matcher=ref_id%3DA&matcher=rulename%3Dtg_parser_bot_down&matcher=severity%3Dcritical&orgId=1\n"
}
```

## Watch context

* Watch note (VPS): <https://github.com/AlexEfimov/TG_parser/blob/main/docs/notes/WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md>
* Exercise plan + escalation matrix: <https://github.com/AlexEfimov/TG_parser/blob/main/docs/runbooks/WAVE1_STEP4_VPS_WATCH_SESSION_EXERCISE_PLAN.md>
  (agent contract cites this as §8 escalation matrix; in the current runbook
  revision the matrix is at **§7 — "Escalation matrix (VPS-specific)"** —
  follow whichever heading is present at fetch time).

## Next steps

Prefix is `[5xx]` by the deterministic alert-name rule, but the **root signal
is `DatasourceError` across all three rules** — i.e. an observability /
Prometheus datasource outage that prevents the 5xx, api-down and bot-down
conditions from evaluating. Triage the datasource first; do not assume a real
5xx spike yet. Strictly off-VPS first (no SSH from this ingress, per agent
rules).

1. **Confirm datasource health from Grafana UI only (no SSH).** Open any
   generator URL above, then Configuration → Data sources → `prometheus` →
   **Save & test**. If it errors ⇒ datasource-wide outage confirmed and *all
   three* alerts are symptoms of the same cause (not three incidents).
   * Check whether **other** rules in folder `wave1-step4-watch` are also
     `DatasourceError`. Folder-wide error ⇒ Prometheus/datasource problem.
2. **Map each rule to the escalation matrix** (`WAVE1_STEP4_VPS_WATCH_SESSION_EXERCISE_PLAN.md` §7),
   **only after** the datasource is healthy and the rules re-evaluate to a
   real value:
   * `[5xx]` — row "5xx on `/api/v1/digests` or `/api/v1/watchlists` ≥ 1":
     capture request, path, body, response; read `tg_parser` logs for the
     minute before the 5xx; document in `BUG_LOG.md` + watch note.
   * `tg_parser_api_down` — row "`up{api}` or `up{mcp}` = 0 on bucket":
     **STOP — degradation.** `docker compose ps`, `docker logs`, healthcheck
     inspect; SOSE-style postmortem if down > 5 min. Watch note "incidents"
     block.
   * `tg_parser_bot_down` — same `up==0` posture for `job=tg_parser_bot`:
     verify the bot container is alive; if genuinely down, real users lose
     digest delivery → escalate as a watch blocker.
3. **Distinguish real outage from meta-alert.** If the API/bot containers are
   actually down, the 5xx series (and all scrape targets) would also vanish —
   so a genuine outage can masquerade as `DatasourceError`. Confirm container
   liveness independently before declaring "just a Grafana glitch".
4. **Watch-window posture (strong signal this run).** Nominal close was
   `2026-05-25T10:50Z`; trigger time is `2026-06-12T01:44Z` — ~18 days past
   nominal close, Wave 1 already declared closed. The same group with identical
   fingerprints has now re-delivered **seven** times over ~6 days
   (`startsAt` frozen at `2026-06-02T17:15:30Z`, `endsAt` never set). This is
   the hallmark of **leftover rules erroring against a torn-down / reconfigured
   Prometheus**, not a live prod incident. Recommended action:
   * **Silence/disable the three rules** per
     `WAVE1_STEP4_VPS_POST_CLOSURE_CLEANUP.md` (per-rule silence URLs are in
     the raw payload). This is the most likely correct resolution and will stop
     the re-trigger storm into this ingress.
   * Only if an independent check confirms a real `up==0` for api/bot ⇒ treat
     as a live P0 regardless of watch status.
5. **Rollback gate (NOT triggered by this alert).** None of these alerts is a
   confirmed `target.kind=chat` / `digest_94483db9` regression, so the
   emergency rollback path (downgrade migration `a8b7c6d5e4f3 → f1a2b3c4d5e6`)
   is **not** indicated here. It is referenced only so the operator knows the
   distinction; rollback is never autonomous and always requires operator
   authorization. (For a `[BUG-030 elevation]` prefix the rollback candidate
   would be migration `a8b7c6d5e4f3` — not applicable to this `[5xx]` payload.)
6. **Dedupe note.** Fingerprints `b5a3e0633aff0a2f`, `ee79af1ca55d3c5c`,
   `42fe0f4e137067ac` observed by this ingress run (seventh re-delivery of the
   group already seen on branches `...-8551`, `...-c056`, `...-7045`,
   `...-de76`, `...-e520`, `...-8a68`). Per agent contract (`one payload = at
   most one issue`) this single artifact is the only deliverable for this run;
   no further follow-ups unless Grafana re-triggers with different fingerprints
   or the operator explicitly retriggers.
7. **Out of scope for this ingress** (per agent rules): no SSH to VPS, no DB
   mutation, no subscription mutation, no code push. The committed artifact /
   auto-created PR from this branch is the issue-equivalent deliverable.

---

## Agent contract trace

* **Step 1 (skip filter):** payload non-empty, `status="firing"` with 3 firing
  alerts, alertname `DatasourceError` (not `DeadMansSwitch` / `Watchdog`, not
  `{"test": true}`, not `status="resolved"`) → **proceed** (no
  `incident_ingress: skipped` log).
* **Step 2 (classify, deterministic from alert-name string only):**
  `name` = first non-empty of `alerts[0].labels.rulename` →
  **`tg_api_5xx_spike`**. Lowercased, matched in fixed order: first rule
  `name == "tg_api_5xx_spike" OR contains "5xx"` hits → prefix **`[5xx]`**.
  No PromQL/metric/rate/time-window input was used (the contract forbids it;
  reliance on those previously caused the `[5xx]`/`[alert]` flip). The
  `DatasourceError` meta-nature is preserved in `## Summary` / `## Next steps`
  rather than altering the prefix.
* **Step 3 (filing):** title `[5xx] DatasourceError (Wave 1 step 4 VPS watch)`;
  labels `wave1-step4-watch`, `vps`, `alert`; sections Source / Summary / Raw
  payload / Watch context / Next steps as above. Filed as a committed markdown
  artifact on branch `cursor/vps-watch-incident-ingress-b490` (cloud-agent
  token is read-only on `AlexEfimov/TG_parser`); the PR auto-created by the
  cloud framework carries the body.

`incident_ingress: filed [5xx] DatasourceError fingerprints=b5a3e0633aff0a2f,ee79af1ca55d3c5c,42fe0f4e137067ac`
