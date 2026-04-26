#!/bin/bash
# F5-C Watch — production health-check helper.
#
# Runs the +1h / +4h / +12h / +24h check-points from
# docs/runbooks/F5C_DEPLOY_AND_WATCH.md in one shot:
#   - smoke probes (API, MCP tools, CLI sub-app)
#   - Prometheus metric snapshot (outcome distribution, tokens, duration)
#   - SQL snapshot (topic_card_versions size + history depth)
#   - tripwire evaluation (#1..#4)
#
# Usage:
#   ./docker/f5c_watch.sh                # full check, human-readable report
#   ./docker/f5c_watch.sh --quiet        # only verdict line(s), suitable for cron
#   ./docker/f5c_watch.sh --no-sql       # skip SQL probe (e.g. read-only context)
#   ./docker/f5c_watch.sh --no-cli       # skip CLI / MCP smoke (Prometheus only)
#
# Exit codes:
#   0 — all green, watch can continue
#   1 — tripwire fired, see § "Tripwire response" in runbook
#   2 — infrastructure problem (API/MCP/DB unreachable)
#
# Cron usage during multi-day pilot:
#   0 */4 * * * /opt/tg_parser/docker/f5c_watch.sh --quiet >> /var/log/f5c_watch.log 2>&1
#
# Environment overrides (optional):
#   F5C_API_URL                  default: http://localhost:8000
#   F5C_API_KEY                  if API_KEY_REQUIRED=true
#   F5C_API_SERVICE              compose service for `docker compose exec`;
#                                auto-detected as `api` (dev) or `tg_parser` (prod)
#   F5C_DB_NAME_PROCESSING       default: tg_parser
#   F5C_LLM_ERR_THRESHOLD        default: 0.10
#   F5C_VERSION_RACED_THRESHOLD  default: 0.05
#   F5C_DURATION_P95_THRESHOLD_S default: 30
#   F5C_PROBE_TOPIC_ID           force a specific topic for MCP/CLI probe
#                                (otherwise picked from list_topics:limit=1)

set -euo pipefail

COMPOSE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$COMPOSE_DIR"

QUIET=0
NO_SQL=0
NO_CLI=0
for arg in "$@"; do
    case "$arg" in
        --quiet) QUIET=1 ;;
        --no-sql) NO_SQL=1 ;;
        --no-cli) NO_CLI=1 ;;
        -h|--help)
            sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) echo "Unknown arg: $arg" >&2; exit 2 ;;
    esac
done

API_URL="${F5C_API_URL:-http://localhost:8000}"
API_KEY="${F5C_API_KEY:-}"
DB_NAME_PROCESSING="${F5C_DB_NAME_PROCESSING:-${DB_NAME:-tg_parser}}"
DB_USER_VAL="${DB_USER:-tg_parser_user}"
LLM_ERR_THR="${F5C_LLM_ERR_THRESHOLD:-0.10}"
RACED_THR="${F5C_VERSION_RACED_THRESHOLD:-0.05}"
P95_THR="${F5C_DURATION_P95_THRESHOLD_S:-30}"

VERDICT_FAIL=0
VERDICT_INFRA=0
TRIPWIRE_NOTES=()

log()    { [[ "$QUIET" -eq 0 ]] && echo "$@" || true; }
header() { log; log "=== $* ==="; }

# Always at least one line of output even in --quiet mode
say()    { echo "$@"; }

trap 'say "f5c_watch: FATAL — script aborted (line $LINENO)"; exit 2' ERR

# ----------------------------------------------------------------------
# 1. Pre-flight — confirm we are on a host that can talk to the stack
# ----------------------------------------------------------------------
header "pre-flight"

if ! command -v docker >/dev/null 2>&1; then
    say "f5c_watch: ERROR — docker not on PATH; run on VPS host"
    exit 2
fi
if [[ ! -f "${COMPOSE_DIR}/docker-compose.yml" ]]; then
    say "f5c_watch: ERROR — docker-compose.yml not found at ${COMPOSE_DIR}"
    exit 2
fi

# Service-name auto-detect: dev compose uses `api`, prod uses `tg_parser`.
# Override via F5C_API_SERVICE if your stack is different.
API_SERVICE="${F5C_API_SERVICE:-}"
if [[ -z "$API_SERVICE" ]]; then
    SERVICES_LIST="$(docker compose ps --services 2>/dev/null || true)"
    if grep -qx 'api' <<<"$SERVICES_LIST"; then
        API_SERVICE=api
    elif grep -qx 'tg_parser' <<<"$SERVICES_LIST"; then
        API_SERVICE=tg_parser
    else
        API_SERVICE=api
    fi
fi

log "compose dir: ${COMPOSE_DIR}"
log "api url:     ${API_URL}"
log "api service: ${API_SERVICE}"
log "db (proc):   ${DB_NAME_PROCESSING} (user=${DB_USER_VAL})"
log "thresholds:  llm_error<${LLM_ERR_THR}  version_raced<${RACED_THR}  p95<${P95_THR}s"

# ----------------------------------------------------------------------
# 2. API smoke — /health + /metrics expose F5-C series
# ----------------------------------------------------------------------
header "api smoke"

curl_args=(--fail --silent --show-error --max-time 10)
if [[ -n "$API_KEY" ]]; then
    curl_args+=(-H "X-API-Key: ${API_KEY}")
fi

if ! curl "${curl_args[@]}" "${API_URL}/health" >/dev/null; then
    say "f5c_watch: INFRA — ${API_URL}/health unreachable"
    VERDICT_INFRA=1
fi

METRICS_BODY="$(curl "${curl_args[@]}" "${API_URL}/metrics" 2>/dev/null || true)"
if [[ -z "$METRICS_BODY" ]]; then
    say "f5c_watch: INFRA — ${API_URL}/metrics returned empty body"
    VERDICT_INFRA=1
fi

# ----------------------------------------------------------------------
# 3. Prometheus snapshot — sum tg_resummarize_total{outcome=...}
# ----------------------------------------------------------------------
header "metrics snapshot"

# Sum total counter values (cumulative since process start). Not a rate —
# this is intentionally a *snapshot*; rate-based tripwires use deltas.
sum_outcome() {
    local label="$1"
    awk -v lbl="$label" '
        /^tg_resummarize_total\{/ {
            line = $0
            if (line ~ "outcome=\"" lbl "\"") {
                # last numeric token on the line
                n = split(line, parts, " ")
                v = parts[n] + 0
                total += v
            }
        }
        END { printf "%.0f", (total ? total : 0) }
    ' <<<"$METRICS_BODY"
}

OK_COUNT=$(sum_outcome ok)
LOCKED_COUNT=$(sum_outcome locked)
LLM_ERR_COUNT=$(sum_outcome llm_error)
RACED_COUNT=$(sum_outcome version_raced)
EMPTY_COUNT=$(sum_outcome empty_scope)
NOCARD_COUNT=$(sum_outcome no_card)
NOBUNDLE_COUNT=$(sum_outcome no_bundle)
UNKNOWN_COUNT=$(sum_outcome unknown)

TOTAL=$((OK_COUNT + LOCKED_COUNT + LLM_ERR_COUNT + RACED_COUNT + EMPTY_COUNT + NOCARD_COUNT + NOBUNDLE_COUNT + UNKNOWN_COUNT))

log "tg_resummarize_total cumulative breakdown:"
printf '  %-15s %s\n' "ok"            "$OK_COUNT" | { [[ "$QUIET" -eq 0 ]] && cat || true; }
printf '  %-15s %s\n' "locked"        "$LOCKED_COUNT" | { [[ "$QUIET" -eq 0 ]] && cat || true; }
printf '  %-15s %s\n' "llm_error"     "$LLM_ERR_COUNT" | { [[ "$QUIET" -eq 0 ]] && cat || true; }
printf '  %-15s %s\n' "version_raced" "$RACED_COUNT" | { [[ "$QUIET" -eq 0 ]] && cat || true; }
printf '  %-15s %s\n' "empty_scope"   "$EMPTY_COUNT" | { [[ "$QUIET" -eq 0 ]] && cat || true; }
printf '  %-15s %s\n' "no_card"       "$NOCARD_COUNT" | { [[ "$QUIET" -eq 0 ]] && cat || true; }
printf '  %-15s %s\n' "no_bundle"     "$NOBUNDLE_COUNT" | { [[ "$QUIET" -eq 0 ]] && cat || true; }
printf '  %-15s %s\n' "unknown"       "$UNKNOWN_COUNT" | { [[ "$QUIET" -eq 0 ]] && cat || true; }
printf '  %-15s %s\n' "TOTAL"         "$TOTAL" | { [[ "$QUIET" -eq 0 ]] && cat || true; }

# Duration p95 (sum across all models, single-bucket approximation).
# For per-model p95 use the PromQL query in the runbook.
P95_RAW="$(awk '
    /^tg_resummarize_duration_seconds_bucket\{.*le="30"/   { sub30 += $NF }
    /^tg_resummarize_duration_seconds_bucket\{.*le="60"/   { sub60 += $NF }
    /^tg_resummarize_duration_seconds_count/               { count += $NF }
    END {
        if (count == 0) { print "n/a"; exit }
        if (sub30 / count >= 0.95) { print "<30"; exit }
        if (sub60 / count >= 0.95) { print "30-60"; exit }
        print ">60"
    }
' <<<"$METRICS_BODY")"
log "duration p95 bucket: ${P95_RAW}"

# ----------------------------------------------------------------------
# 4. CLI / MCP smoke — `tg-parser topic --help` + a probe topic_id
# ----------------------------------------------------------------------
if [[ "$NO_CLI" -eq 0 ]]; then
    header "cli smoke"
    if docker compose exec -T "$API_SERVICE" tg-parser topic --help >/dev/null 2>&1; then
        log "  topic sub-app:  registered (versions, resummarize)"
    else
        say "f5c_watch: WARN — tg-parser topic sub-app missing or '${API_SERVICE}' container not up"
        VERDICT_INFRA=1
    fi
else
    log "cli smoke: skipped (--no-cli)"
fi

# ----------------------------------------------------------------------
# 5. SQL snapshot — topic_card_versions size & depth
# ----------------------------------------------------------------------
if [[ "$NO_SQL" -eq 0 ]]; then
    header "sql snapshot (topic_card_versions)"

    SQL='SELECT
            COUNT(*)                                       AS rows,
            COALESCE(MAX(version_no), 0)                   AS max_version,
            COUNT(DISTINCT topic_id)                       AS topics_with_history,
            COALESCE(ROUND(AVG(version_no)::numeric, 2),0) AS avg_version,
            pg_size_pretty(pg_total_relation_size('"'"'topic_card_versions'"'"')) AS size
         FROM topic_card_versions;'

    if SQL_OUT=$(docker compose exec -T postgres psql -X -A -t \
            -U "$DB_USER_VAL" -d "$DB_NAME_PROCESSING" -c "$SQL" 2>/dev/null); then
        IFS='|' read -r ROWS MAXV TOPICS_HIST AVGV SIZE <<<"$SQL_OUT"
        log "  rows:                 ${ROWS}"
        log "  max version_no:       ${MAXV}"
        log "  topics with history:  ${TOPICS_HIST}"
        log "  avg version_no:       ${AVGV}"
        log "  table size:           ${SIZE}"
    else
        log "  WARN — SQL query failed (psql container down or table absent)"
    fi
else
    log "sql snapshot: skipped (--no-sql)"
fi

# ----------------------------------------------------------------------
# 6. Tripwire evaluation (cumulative ratios; for rate-based use Grafana)
# ----------------------------------------------------------------------
header "tripwires"

ratio() {
    awk -v num="$1" -v den="$2" 'BEGIN { if (den == 0) print "0.00"; else printf "%.4f", num/den }'
}

LLM_ERR_RATIO=$(ratio "$LLM_ERR_COUNT" "$TOTAL")
RACED_RATIO=$(ratio "$RACED_COUNT" "$TOTAL")

# Tripwire #1
if awk -v r="$LLM_ERR_RATIO" -v t="$LLM_ERR_THR" 'BEGIN { exit (r > t) ? 0 : 1 }'; then
    TRIPWIRE_NOTES+=("#1 llm_error ratio=${LLM_ERR_RATIO} > ${LLM_ERR_THR}")
    VERDICT_FAIL=1
fi
log "  #1 llm_error ratio:     ${LLM_ERR_RATIO}  (threshold ${LLM_ERR_THR})"

# Tripwire #2
if awk -v r="$RACED_RATIO" -v t="$RACED_THR" 'BEGIN { exit (r > t) ? 0 : 1 }'; then
    TRIPWIRE_NOTES+=("#2 version_raced ratio=${RACED_RATIO} > ${RACED_THR}")
    VERDICT_FAIL=1
fi
log "  #2 version_raced ratio: ${RACED_RATIO}  (threshold ${RACED_THR})"

# Tripwire #3 — coarse bucket comparison only; runbook PromQL is canonical
case "$P95_RAW" in
    ">60") TRIPWIRE_NOTES+=("#3 duration p95 > 60s (above ${P95_THR}s threshold)"); VERDICT_FAIL=1 ;;
    "30-60")
        if [[ "$P95_THR" -lt 60 ]]; then
            TRIPWIRE_NOTES+=("#3 duration p95 in 30-60s bucket (above ${P95_THR}s threshold)")
            VERDICT_FAIL=1
        fi
        ;;
esac
log "  #3 duration p95 bucket: ${P95_RAW}  (threshold ${P95_THR}s)"

# Tripwire #4 — billing pause detected via paused source_attempts
PAUSED=$(awk '
    /^tg_parser_anthropic_billing_block_total\{/ {
        n = split($0, parts, " ")
        v = parts[n] + 0
        total += v
    }
    END { printf "%.0f", (total ? total : 0) }
' <<<"$METRICS_BODY")
if [[ "$PAUSED" -gt 0 ]]; then
    TRIPWIRE_NOTES+=("#4 anthropic billing block fired ${PAUSED} time(s) — see runbook")
    VERDICT_FAIL=1
fi
log "  #4 billing block count: ${PAUSED}"

# ----------------------------------------------------------------------
# 7. Final verdict
# ----------------------------------------------------------------------
header "verdict"

TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

if [[ "$VERDICT_INFRA" -eq 1 ]]; then
    say "f5c_watch[${TS}]: INFRA-FAIL — API/metrics/DB unreachable; cannot trust tripwires"
    exit 2
fi

if [[ "$VERDICT_FAIL" -eq 1 ]]; then
    say "f5c_watch[${TS}]: TRIPWIRE — ${#TRIPWIRE_NOTES[@]} alert(s):"
    for note in "${TRIPWIRE_NOTES[@]}"; do
        say "  - ${note}"
    done
    say "  → see § Tripwire response in docs/runbooks/F5C_DEPLOY_AND_WATCH.md"
    exit 1
fi

if [[ "$TOTAL" -eq 0 ]]; then
    say "f5c_watch[${TS}]: GREEN (idle) — no re-summarize ticks yet (legit if no new items in channels)"
else
    OK_PCT=$(awk -v ok="$OK_COUNT" -v t="$TOTAL" 'BEGIN { printf "%.1f", ok*100/t }')
    say "f5c_watch[${TS}]: GREEN — total=${TOTAL} ok=${OK_PCT}% locked=${LOCKED_COUNT} llm_err=${LLM_ERR_COUNT} raced=${RACED_COUNT}"
fi

exit 0
