#!/bin/bash
# #359 / ADR-0020 watch — one command per check-point of the 24h watch.
#
# Collects, in ONE ssh round-trip to prod, everything the check-point needs:
#   - provenance header (host, container id, StartedAt, window actually covered)
#   - event tally for ^write_intent_ / ^fsm_confirm_
#   - the DENOMINATOR (user_message / agent_tool_call) — without it a tally of
#     zeros is an observability ceiling, not a clean watch (see BUG-086 shadow
#     mode precedent in docs/runbooks/F5C_DEPLOY_AND_WATCH.md)
#   - error count + total log lines (dump is field-whitelisted — BUG-087)
#   - explicit call-outs: write_intent_router_failed,
#     write_intent_router_execute_failed, every fsm_confirm_execute
#   - control-topic SQL compared against the recorded baseline (PASS/CHANGED)
#   - verdict block against the closing criteria
#
# Runs FROM YOUR WORKSTATION: it opens the ssh session itself instead of
# assuming you are already on the VPS. That is the whole point — pasted into a
# local terminal the hand-run commands produce `No such container` on stderr,
# `2>&1` feeds that one line into the pipeline, jq matches nothing and prints an
# innocuous empty tally, and `grep -Eic` counts the error line as `1`. Every
# probe below therefore fails LOUDLY rather than emitting a zero.
#
# Usage:
#   ./docker/watch_359.sh                       # full check-point report
#   ./docker/watch_359.sh --since 2026-08-01T06:00:00Z   # ad-hoc window
#   ./docker/watch_359.sh --since 30m           # anything `docker logs --since` takes
#   ./docker/watch_359.sh --quiet               # verdict lines only
#   ./docker/watch_359.sh --help
#
# Options:
#   --since <ts>       override the window start (default: the #359 re-create)
#   --container <name> override the bot container (default: tg_parser_bot)
#   --ssh <user@host>  override the prod target (default: user@212.72.189.15)
#   --port <n>         override the ssh port (default: 2296)
#   --quiet            suppress the narrative sections, keep the verdict
#
# Exit codes:
#   0 — every closing criterion met, watch can continue
#   1 — at least one criterion not met / inconclusive, read the verdict block
#   2 — the watch itself is void (no ssh, no container, unparseable log stream,
#       control topic missing). NOT a clean result — nothing was measured.
#
# Read-only by construction: docker inspect / docker logs / SELECT-only psql.
# No restart, no writes, no bot interaction. Re-runnable, no state files.

set -euo pipefail

SSH_TARGET="user@212.72.189.15"
SSH_PORT="2296"
CONTAINER="tg_parser_bot"
PG_CONTAINER="tg_parser_postgres"
QUIET=0

# Window start = the #359 re-create. The bot log stream begins here anyway;
# passing it explicitly makes the covered window assertable instead of implied.
SINCE="2026-07-31T18:18:43Z"
SINCE_DEFAULT=1
EXPECT_STARTED="2026-07-31T18:18:43.120880542Z"
WATCH_DEADLINE="2026-08-01T18:18:00Z"

# Control topic — must be bit-for-bit unchanged. Baseline from the deploy
# record (§ "Сверка БД — не тронута") in docs/runbooks/F5C_DEPLOY_AND_WATCH.md.
TOPIC="topic:tg:AgeManagment:post:977"
BASE_VER="3"
BASE_MD5="7a3ab3d2ff399f9d73c5f8b7301b843b"
BASE_TS="2026-07-22 14:37:34.29482+00"
BASE_ROWS="2"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --since)     SINCE="${2:?--since needs a value}"; SINCE_DEFAULT=0; shift 2 ;;
        --container) CONTAINER="${2:?--container needs a value}"; shift 2 ;;
        --ssh)       SSH_TARGET="${2:?--ssh needs a value}"; shift 2 ;;
        --port)      SSH_PORT="${2:?--port needs a value}"; shift 2 ;;
        --quiet)     QUIET=1; shift ;;
        -h|--help)
            sed -n '2,45p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) echo "watch_359: unknown arg: $1 (try --help)" >&2; exit 2 ;;
    esac
done

# The remote body is a quoted heredoc so nothing expands here; parameters are
# injected as a printf %q prelude. In particular $POSTGRES_PASSWORD below must
# survive two hops untouched and expand inside the postgres container.
REMOTE_BODY=$(cat <<'REMOTE_EOF'
set -euo pipefail

FAIL=0
NOTES=()
say()  { printf '%s\n' "$*"; }
log()  { [[ "$QUIET" -eq 0 ]] && printf '%s\n' "$*" || true; }
head_() { log; log "=== $* ==="; }

NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# ---------------------------------------------------------------- provenance
if ! INSPECT="$(docker inspect \
        -f '{{.Id}}|{{.State.Status}}|{{.State.StartedAt}}|{{.Image}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' \
        "$CTR" 2>&1)"; then
    say "watch_359: VOID — container '$CTR' does not exist on $(hostname)."
    say "  docker inspect: ${INSPECT}"
    say "  Refusing to print a tally. Zeros from a missing container are not a"
    say "  clean watch — they are no measurement at all."
    exit 2
fi
IFS='|' read -r C_ID C_STATUS C_STARTED C_IMAGE C_HEALTH <<<"$INSPECT"

head_ "provenance"
log "  host:          $(hostname)   (ssh ${SSH_DESC})"
log "  container:     ${CTR}  ${C_ID:0:12}  status=${C_STATUS}  health=${C_HEALTH}"
# Informational, not compared: a different image implies a re-create, which the
# StartedAt assertion below already catches — the same running process cannot
# have changed image underneath it. A second baseline would add no coverage.
log "  image:         ${C_IMAGE:0:19}  (informational — not compared)"
log "  StartedAt:     ${C_STARTED}"
log "  window --since ${SINCE}   →   now ${NOW}"

if [[ "$C_STARTED" != "$EXPECT_STARTED" ]]; then
    say ""
    say "  ##############################################################"
    say "  ##  StartedAt MISMATCH — the container was RE-CREATED."
    say "  ##    expected: ${EXPECT_STARTED}"
    say "  ##    actual:   ${C_STARTED}"
    say "  ##  The 24h watch window RESETS from the actual StartedAt."
    say "  ##  Everything below covers only the new container's stream;"
    say "  ##  the pre-recreate log is gone. Do not close the watch on it."
    say "  ##############################################################"
    FAIL=1
    NOTES+=("container re-created — watch window resets from ${C_STARTED}")
else
    log "  StartedAt matches the #359 re-create — window is continuous."
fi

# Only absolute timestamps get a covered-hours figure. GNU date happily parses
# a relative form like `20m` into something plausible-looking and wrong.
if [[ "$SINCE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T ]] && SINCE_EPOCH="$(date -u -d "$SINCE" +%s 2>/dev/null)"; then
    NOW_EPOCH="$(date -u +%s)"
    COVERED_H="$(awk -v a="$SINCE_EPOCH" -v b="$NOW_EPOCH" 'BEGIN{printf "%.1f",(b-a)/3600}')"
    log "  covered:       ${COVERED_H} h of 24 h"
    if DL_EPOCH="$(date -u -d "$DEADLINE" +%s 2>/dev/null)"; then
        REMAIN_H="$(awk -v a="$NOW_EPOCH" -v b="$DL_EPOCH" 'BEGIN{printf "%.1f",(b-a)/3600}')"
        log "  deadline:      ${DEADLINE}  (${REMAIN_H} h remaining)"
    fi
else
    COVERED_H="n/a"
    log "  covered:       n/a (relative --since, ad-hoc window)"
fi

# ------------------------------------------------------------------ log pull
# One pull, reused by every probe below. 2>&1 is applied here, once: structlog
# writes to stdout but third-party libraries write to stderr, and dropping
# stderr would silently narrow the error count.
if ! LOGS="$(docker logs --since "$SINCE" "$CTR" 2>&1)"; then
    say "watch_359: VOID — 'docker logs --since ${SINCE} ${CTR}' failed:"
    printf '%s\n' "$LOGS" | sed 's/^/    /'
    exit 2
fi

TOTAL_LINES=0
if [[ -z "$LOGS" ]]; then
    if [[ "$SINCE_DEFAULT" -eq 1 ]]; then
        # The default window starts at the re-create, so it must contain the
        # startup banner. Its absence means the stream is wrong, not quiet.
        say "watch_359: VOID — the log stream for ${CTR} since ${SINCE} is EMPTY."
        say "  That window starts at container creation, so it must contain the"
        say "  startup banner. An empty stream means the stream was truncated or"
        say "  redirected — not that nothing happened."
        exit 2
    fi
    say ""
    say "  ⚠ ad-hoc window since ${SINCE} contains ZERO log lines. That is not a"
    say "    clean result — nothing was observed in it. Counts below are all 0 by"
    say "    absence of data; the control-topic check still runs."
else
    TOTAL_LINES="$(printf '%s\n' "$LOGS" | wc -l | tr -d ' ')"
fi

# jq is always fed as raw text with fromjson? — bare jq aborts on the first
# non-JSON line (startup noise, third-party output), which looks exactly like
# "no events" and is the failure mode this script exists to prevent.
jqf() { printf '%s\n' "$LOGS" | jq -Rr "$@"; }

JSON_LINES="$(jqf 'fromjson? | objects | "."' | wc -l | tr -d ' ')"
if [[ "$TOTAL_LINES" -gt 0 && "$JSON_LINES" -eq 0 ]]; then
    say "watch_359: VOID — ${TOTAL_LINES} log line(s) but ZERO parsed as structlog JSON."
    say "  The filter pipeline is broken (or this is not the bot container)."
    say "  First 3 lines, verbatim:"
    # awk instead of `head -3`: head closes the pipe early, which under pipefail
    # turns the upstream SIGPIPE into exit 141 and pre-empts the exit 2 below.
    printf '%s\n' "$LOGS" | awk 'NR<=3' | sed 's/^/    /'
    exit 2
fi
log "  log lines:     ${TOTAL_LINES} total, ${JSON_LINES} structlog JSON"

# `awk NR==1` without `exit` reads the stream to the end, so jq is never killed
# by SIGPIPE (exit 141 under pipefail) once the log exceeds the pipe buffer. A
# genuine jq failure still propagates and aborts, which `|| true` would mask.
FIRST_TS="$(jqf 'fromjson? | objects | .timestamp // empty' | awk 'NR==1')"
LAST_TS="$(jqf  'fromjson? | objects | .timestamp // empty' | tail -1)"
log "  first event:   ${FIRST_TS:-<none>}"
log "  last event:    ${LAST_TS:-<none>}"

ev_count() {
    jqf --arg e "$1" 'fromjson? | objects | select((.event // "") == $e) | "."' | wc -l | tr -d ' '
}

# -------------------------------------------------------------------- tally
head_ "event tally  (^write_intent_ | ^fsm_confirm_)"
TALLY="$(jqf 'fromjson? | objects | (.event // "") | select(test("^write_intent_|^fsm_confirm_"))' \
         | sort | uniq -c | awk '{printf "  %-36s %s\n", $2, $1}')"
MATCHED="$(jqf 'fromjson? | objects | (.event // "") | select(test("^write_intent_|^fsm_confirm_"))' | wc -l | tr -d ' ')"
if [[ -n "$TALLY" ]]; then
    log "$TALLY"
else
    log "  (none in this window)"
fi
log "  ----"
log "  $(printf '%-36s %s' 'TOTAL #359 events' "$MATCHED")"

# --------------------------------------------------------------- denominator
head_ "denominator  (load-bearing — never omit)"
UM="$(ev_count user_message)"
ATC="$(ev_count agent_tool_call)"
log "  $(printf '%-36s %s' 'user_message' "$UM")"
log "  $(printf '%-36s %s' 'agent_tool_call' "$ATC")"
DENOM=$((UM + ATC))
if [[ "$DENOM" -eq 0 ]]; then
    say "  ⚠ DENOMINATOR = 0 — there was no conversational traffic in this window."
    say "    The tally above is therefore INCONCLUSIVE, not clean: zero events out"
    say "    of zero turns measures nothing. This is the exact failure that forced"
    say "    the BUG-086 shadow layer to be replaced rather than tuned."
    FAIL=1
    NOTES+=("denominator=0 — window is inconclusive, not clean")
elif [[ "$DENOM" -lt 20 ]]; then
    log "  sample is THIN (${DENOM} turns) — real, but do not read much into it."
    NOTES+=("thin sample: denominator=${DENOM}")
else
    log "  denominator non-zero (${DENOM} turns) — the zeros above are real zeros."
fi

# --------------------------------------------------------------------- errors
head_ "errors"
ERRS="$(printf '%s\n' "$LOGS" | grep -Eic 'error|warn|traceback|exception|critical' || true)"
ERRS="${ERRS:-0}"
log "  $(printf '%-36s %s' 'matching lines' "$ERRS")"
log "  $(printf '%-36s %s' 'of total log lines' "$TOTAL_LINES")"
if [[ "$ERRS" -ne 0 ]]; then
    say "  ⚠ ${ERRS} error/warn line(s) in the window:"

    # This dump is meant to be pasted into a check-point note, and BUG-087 records
    # that this container logs value-bearing fields (tool_validation_error carries
    # message=str(exc), which echoes the offending input; fsm_confirm_unknown_token
    # carries the user's whole reply). Structlog lines are therefore rendered from
    # a whitelist and every other key is reported BY NAME ONLY: the operator still
    # sees what broke and where the detail lives, without the value on screen.
    ERR_FILTER='["timestamp","level","event"] as $head
      | ["logger","tool","chat_id","error_class","arg_keys","rendered_verbatim"] as $tail
      | (try fromjson catch null) as $o
      | if ($o | type) == "object"
        then "\($o.timestamp // "?")  \($o.level // "?")  \($o.event // "?")"
             + ([ $o | to_entries[] | select(.key as $k | $tail | index($k))
                  | "  \(.key)=\(.value | if type == "array" then map(tostring) | join(",") else tostring end)" ] | add // "")
             + ([ $o | keys_unsorted[] | . as $k | select(($head + $tail) | index($k) | not) ] as $sup
                | if ($sup | length) > 0 then "  [suppressed: \($sup | join(","))]" else "" end)
        else "[non-JSON] \(.)"
        end'

    # awk instead of `head -20`: see the SIGPIPE/pipefail note above.
    ERR_SHOWN="$(printf '%s\n' "$LOGS" | grep -Ei 'error|warn|traceback|exception|critical' | awk 'NR<=20')"
    if ERR_DUMP="$(printf '%s\n' "$ERR_SHOWN" | jq -Rr "$ERR_FILTER" 2>&1)"; then
        ERR_RAW_N="$(printf '%s\n' "$ERR_DUMP" | grep -c '^\[non-JSON\]' || true)"
        say "    (REDACTED view: whitelisted fields only, the rest named but not"
        say "     printed — BUG-087, these logs can carry user text and secrets."
        say "     Read a full line on prod; do not paste one into a note.)"
        if [[ "${ERR_RAW_N:-0}" -gt 0 ]]; then
            say "    ⚠ ${ERR_RAW_N} of them are NOT structlog JSON (third-party stderr /"
            say "      traceback) and cannot be whitelisted — they appear VERBATIM below,"
            say "      truncated to 240 chars. Review those before pasting anywhere."
        fi
        printf '%s\n' "$ERR_DUMP" | cut -c1-240 | sed 's/^/      /'
    else
        # Redaction unavailable — say so rather than falling back to raw lines.
        say "    ⚠ could not render the redacted view (jq failed):"
        printf '%s\n' "$ERR_DUMP" | awk 'NR<=3' | cut -c1-240 | sed 's/^/        /'
        say "      The ${ERRS} line(s) are NOT shown, because unredacted output from"
        say "      this container is not safe to paste. Read them on prod."
    fi
    FAIL=1
    NOTES+=("${ERRS} error/warn line(s) in the bot log")
fi

# ------------------------------------------------------------------ call-outs
head_ "explicit call-outs"
RF="$(ev_count write_intent_router_failed)"
REF="$(ev_count write_intent_router_execute_failed)"
log "  $(printf '%-36s %s  (expected 0)' 'write_intent_router_failed' "$RF")"
log "  $(printf '%-36s %s  (expected 0)' 'write_intent_router_execute_failed' "$REF")"
if [[ "$RF" -ne 0 || "$REF" -ne 0 ]]; then
    say "  ⚠ a router-failure counter is non-zero — this is a bug, not noise."
    say "    (unlike the error dump above, error= below is printed VERBATIM: on"
    say "     this path it IS the diagnostic. Read it before pasting anywhere.)"
    jqf 'fromjson? | objects
         | select((.event // "") | test("^write_intent_router_(failed|execute_failed)$"))
         | "      \(.timestamp // "?")  \(.event)  tool=\(.tool // "?")  error=\(.error // "-")"'
    FAIL=1
    NOTES+=("router failures: failed=${RF} execute_failed=${REF}")
fi

EXECS="$(ev_count fsm_confirm_execute)"
log ""
log "  $(printf '%-36s %s' 'fsm_confirm_execute' "$EXECS")"
if [[ "$EXECS" -gt 0 ]]; then
    log "  Every one MUST be explainable by a deliberate confirmation:"
    # `args` deliberately not printed: for tools like add_user_auth it carries
    # raw values, unlike the arg_keys-only write_intent_* events.
    jqf 'fromjson? | objects | select((.event // "") == "fsm_confirm_execute")
         | "    \(.timestamp // "?")  tool=\(.tool // "?")  chat_id=\(.chat_id // "?")"'
    NOTES+=("${EXECS} fsm_confirm_execute — operator must account for each")
else
    log "  none — no mutation was confirmed in this window."
fi

# --------------------------------------------------------------- control topic
head_ "control topic  ${TOPIC}"
SQL="SELECT tc.summary_version, md5(tc.summary), tc.last_summarized_at,
            (SELECT COUNT(*) FROM topic_card_versions v WHERE v.topic_id = tc.id)
     FROM topic_cards tc WHERE tc.id = '${TOPIC}';"

# The sh -c body is single-quoted on purpose: POSTGRES_* resolve inside the
# postgres container, and the SQL travels as argv rather than through a third
# layer of quoting.
if ! SQL_RAW="$(docker exec "$PG_CTR" sh -c \
        'PGPASSWORD="$POSTGRES_PASSWORD" exec psql -X -A -t -F "|" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$1"' \
        _ "$SQL" 2>&1)"; then
    say "watch_359: VOID — control-topic query failed against ${PG_CTR}:"
    printf '%s\n' "$SQL_RAW" | sed 's/^/    /'
    exit 2
fi
SQL_OUT="$(printf '%s\n' "$SQL_RAW" | sed '/^[[:space:]]*$/d' | awk 'NR==1')"

if [[ -z "$SQL_OUT" ]]; then
    say "watch_359: VOID — control topic returned NO ROWS."
    say "  ${TOPIC} is absent from topic_cards. That is an error condition, not a"
    say "  pass: an empty result set is indistinguishable from a clean one, which"
    say "  is exactly how a watch run against the wrong database reads as green."
    exit 2
fi

IFS='|' read -r G_VER G_MD5 G_TS G_ROWS <<<"$SQL_OUT"
CTRL_OK=1
cmp_field() {
    local name="$1" got="$2" want="$3"
    if [[ "$got" == "$want" ]]; then
        log "  $(printf '%-22s %-34s PASS' "$name" "$got")"
    else
        say "  $(printf '%-22s %-34s CHANGED (baseline: %s)' "$name" "$got" "$want")"
        CTRL_OK=0
    fi
}
cmp_field "summary_version"   "$G_VER"  "$BASE_VER"
cmp_field "md5(summary)"      "$G_MD5"  "$BASE_MD5"
cmp_field "last_summarized_at" "$G_TS"  "$BASE_TS"
cmp_field "topic_card_versions" "$G_ROWS" "$BASE_ROWS"

if [[ "$CTRL_OK" -eq 0 ]]; then
    FAIL=1
    NOTES+=("control topic drifted from baseline")
    say ""
    say "  A change here is NOT automatically a #359 regression. The F5-C"
    say "  scheduler may legally re-summarize this topic on its own counter or"
    say "  age trigger. Before concluding anything, check both:"
    say "    (a) scheduler activity — f5c_resummarize lines in tg_parser;"
    say "    (b) an unexplained fsm_confirm_execute in the list above."
    say "  Only an unexplained execute with no scheduler activity points at #359."
    say ""
    say "  (a) f5c_resummarize in tg_parser since ${SINCE}:"
    F5C_HITS="$(docker logs --since "$SINCE" tg_parser 2>&1 \
                | jq -Rr 'fromjson? | objects | select((.event // "") | test("f5c_resummarize"))
                          | "      \(.timestamp // "?")  \(.event)  \(.channel_id // "-")  resummarized=\(.resummarized // "-")"' \
                | tail -20 || true)"
    if [[ -n "$F5C_HITS" ]]; then
        printf '%s\n' "$F5C_HITS"
    else
        say "      (none — scheduler did not re-summarize in this window)"
    fi
fi

# -------------------------------------------------------------------- verdict
head_ "verdict"
verdict_line() { say "  $(printf '[%-4s] %s' "$1" "$2")"; }

# With a relative --since only StartedAt equality is asserted, so the claim is
# scoped to that: the run measured an ad-hoc slice, not continuous 24h coverage.
if [[ "$C_STARTED" != "$EXPECT_STARTED" ]]; then
    verdict_line "FAIL" "container re-created — window reset, 24 h not yet accumulated"
elif [[ "$COVERED_H" == "n/a" ]]; then
    verdict_line "PASS" "container not re-created — StartedAt still the #359 re-create (ad-hoc window: coverage NOT asserted)"
else
    verdict_line "PASS" "window continuous since the #359 re-create (${COVERED_H} h of 24 h)"
fi

[[ "$RF" -eq 0 && "$REF" -eq 0 ]] \
    && verdict_line "PASS" "router-failure counters both 0" \
    || verdict_line "FAIL" "router failures: failed=${RF} execute_failed=${REF}"

if [[ "$EXECS" -eq 0 ]]; then
    verdict_line "PASS" "no fsm_confirm_execute to account for"
else
    verdict_line "----" "${EXECS} fsm_confirm_execute listed above — needs operator sign-off (script cannot judge intent)"
fi

if [[ "$TOTAL_LINES" -eq 0 ]]; then
    # 0 errors out of 0 lines is the same empty-tally trap as a zero denominator.
    verdict_line "----" "no log lines in window — the 0 error count is absence of data, not health"
elif [[ "$ERRS" -eq 0 ]]; then
    verdict_line "PASS" "0 error/warn lines across ${TOTAL_LINES} log lines"
else
    verdict_line "FAIL" "${ERRS} error/warn line(s)"
fi

if [[ "$DENOM" -eq 0 ]]; then
    verdict_line "FAIL" "denominator 0 — result INCONCLUSIVE, the zeros mean nothing"
elif [[ "$DENOM" -lt 20 ]]; then
    verdict_line "WARN" "denominator ${DENOM} (${UM} user_message / ${ATC} agent_tool_call) — real but THIN"
else
    verdict_line "PASS" "denominator ${DENOM} (${UM} user_message / ${ATC} agent_tool_call)"
fi

[[ "$CTRL_OK" -eq 1 ]] \
    && verdict_line "PASS" "control topic bit-for-bit at baseline" \
    || verdict_line "FAIL" "control topic CHANGED — triage per the note above"

say ""
if [[ "$FAIL" -eq 0 ]]; then
    if [[ "$EXECS" -gt 0 ]]; then
        say "watch_359[${NOW}]: GREEN — pending your sign-off on ${EXECS} fsm_confirm_execute."
    else
        say "watch_359[${NOW}]: GREEN — all closing criteria met for the window covered so far."
    fi
    say "  Not the same as watch closed: it closes at ${DEADLINE}."
    # A thin sample and a non-zero fsm_confirm_execute both leave FAIL=0, so
    # without this their NOTES entries were written and never shown.
    if [[ "${#NOTES[@]}" -gt 0 ]]; then
        say "  notes carried by this GREEN — ${#NOTES[@]} item(s):"
        for n in "${NOTES[@]}"; do say "  - ${n}"; done
    fi
    exit 0
fi

say "watch_359[${NOW}]: ATTENTION — ${#NOTES[@]} item(s):"
for n in "${NOTES[@]}"; do say "  - ${n}"; done
exit 1
REMOTE_EOF
)

PRELUDE="$(printf 'CTR=%q\nPG_CTR=%q\nSINCE=%q\nSINCE_DEFAULT=%q\nEXPECT_STARTED=%q\nDEADLINE=%q\nTOPIC=%q\nBASE_VER=%q\nBASE_MD5=%q\nBASE_TS=%q\nBASE_ROWS=%q\nQUIET=%q\nSSH_DESC=%q\n' \
    "$CONTAINER" "$PG_CONTAINER" "$SINCE" "$SINCE_DEFAULT" "$EXPECT_STARTED" "$WATCH_DEADLINE" \
    "$TOPIC" "$BASE_VER" "$BASE_MD5" "$BASE_TS" "$BASE_ROWS" "$QUIET" \
    "-p ${SSH_PORT} ${SSH_TARGET}")"

RC=0
printf '%s\n%s\n' "$PRELUDE" "$REMOTE_BODY" \
    | ssh -T -p "$SSH_PORT" -o ConnectTimeout=20 "$SSH_TARGET" bash -s || RC=$?

# ssh's own 255 is not a watch verdict — say so instead of letting it read as
# an exit-1 "attention" result.
if [[ "$RC" -eq 255 ]]; then
    echo "watch_359: VOID — ssh to ${SSH_TARGET}:${SSH_PORT} failed; nothing was measured." >&2
    exit 2
fi
exit "$RC"
