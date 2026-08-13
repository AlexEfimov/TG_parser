#!/usr/bin/env bash
# Report what this machine can and cannot do for agent work, in either mode.
#
# The same script runs on a developer Mac and on a Cursor Cloud VM: it detects
# the mode, then checks every dependency that differs between the two. The point
# is that a mode switch fails loudly here instead of silently mid-task — which is
# how the PR-standard test mode quietly went unrun in cloud sessions.
#
# Read-only. Exits 0 even with MISS lines: this is a report, not a gate.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$HOME/.local/bin:$PATH"

PROD_MCP_URL="${PROD_MCP_URL:-https://mcp.tgp.efimov.mobi/mcp}"
LOCAL_MCP_URL="${LOCAL_MCP_URL:-http://localhost:8080/mcp}"

if [ -d /opt/cursor ] || [ -d /tmp/cursor ]; then
  MODE="cloud"
else
  MODE="local"
fi

if [ -t 1 ]; then G=$'\033[32m'; R=$'\033[31m'; Y=$'\033[33m'; Z=$'\033[0m'; else G=""; R=""; Y=""; Z=""; fi
ok()   { printf '  %sOK%s    %-24s %s\n' "$G" "$Z" "$1" "${2-}"; }
miss() { printf '  %sMISS%s  %-24s %s\n' "$R" "$Z" "$1" "${2-}"; }
note() { printf '  %s--%s    %-24s %s\n' "$Y" "$Z" "$1" "${2-}"; }

port_open() { (exec 3<>"/dev/tcp/$1/$2") >/dev/null 2>&1; }

printf '\nmode: %s   repo: %s\n\n' "$MODE" "$ROOT"

printf 'git\n'
cd "$ROOT"
if git rev-parse --git-dir >/dev/null 2>&1; then
  ok "branch" "$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '(no commits)')"
  DIRTY="$(git status --porcelain | wc -l | tr -d ' ')"
  [ "$DIRTY" = "0" ] && ok "worktree" "clean" \
    || note "worktree" "$DIRTY uncommitted path(s) — commit or stash before switching mode"
  if git rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1; then
    read -r BEHIND AHEAD < <(git rev-list --left-right --count '@{u}...HEAD' 2>/dev/null)
    [ "${BEHIND:-0}${AHEAD:-0}" = "00" ] && ok "vs upstream" "in sync" \
      || note "vs upstream" "behind ${BEHIND:-?}, ahead ${AHEAD:-?} — fetch / push"
  else
    note "vs upstream" "no tracking branch"
  fi
else
  miss "git" "not a repository"
fi

printf '\ntest prerequisites (tests/README.md)\n'
[ -d "$ROOT/.venv" ] && ok ".venv" "present" || miss ".venv" "uv sync --frozen --extra dev"
DB_HOST_EFF="${DB_HOST:-localhost}"; DB_PORT_EFF="${DB_PORT:-5432}"
DBN="${DB_NAME:-tg_parser_test}"
if port_open "$DB_HOST_EFF" "$DB_PORT_EFF"; then
  ok "postgres" "$DB_HOST_EFF:$DB_PORT_EFF reachable"
  # psql is often absent on a developer Mac while the server runs in Docker,
  # so fall back to the container rather than reporting "cannot verify".
  EXT=""
  if command -v psql >/dev/null 2>&1; then
    EXT="$(PGPASSWORD="${DB_PASSWORD:-}" psql -h "$DB_HOST_EFF" -p "$DB_PORT_EFF" \
            -U "${DB_USER:-tg_parser_test}" -d "$DBN" -tAc \
            "select extversion from pg_extension where extname='vector';" 2>/dev/null | tr -d ' ')"
  elif command -v docker >/dev/null 2>&1; then
    EXT="$(docker exec tg_parser_postgres psql -U "${DB_USER:-tg_parser_user}" -d "$DBN" -tAc \
            "select extversion from pg_extension where extname='vector';" 2>/dev/null | tr -d ' ')"
  fi
  if [ -n "$EXT" ]; then
    ok "pgvector" "$EXT in $DBN"
  elif command -v psql >/dev/null 2>&1 || command -v docker >/dev/null 2>&1; then
    miss "pgvector" "CREATE EXTENSION IF NOT EXISTS vector; in $DBN (db must exist)"
  else
    note "pgvector" "neither psql nor docker available — cannot verify"
  fi
else
  miss "postgres" "docker compose up -d postgres  (container tg_parser_postgres, :5432)"
  note "consequence" "PR standard (TEST_POSTGRES=1) cannot run — ~500 tests stay unverified"
fi
# Keys reach the test suite through .env as well as the shell, and locally .env
# is the usual carrier — checking only the environment reports a false MISS.
for v in OPENAI_API_KEY ANTHROPIC_API_KEY GEMINI_API_KEY; do
  if [ -n "${!v:-}" ]; then
    ok "$v" "set in environment"
  elif [ -f "$ROOT/.env" ] && grep -qE "^${v}=.+" "$ROOT/.env"; then
    ok "$v" "set in .env"
  else
    miss "$v" "any non-empty value works for tests (CI uses sk-test-key)"
  fi
done

printf '\nknowledge graph (graphify)\n'
command -v graphify >/dev/null 2>&1 \
  && ok "graphify" "$(graphify --version 2>/dev/null | head -1)" \
  || miss "graphify" "bash scripts/graphify_bootstrap.sh"
GOUT="${GRAPHIFY_OUT:-graphify-out}"
[ -f "$ROOT/$GOUT/graph.json" ] \
  && ok "graph.json" "$(du -h "$ROOT/$GOUT/graph.json" 2>/dev/null | cut -f1)" \
  || miss "graph.json" "bash scripts/graphify_bootstrap.sh"
[ -f "$ROOT/.graphifyignore" ] && ok ".graphifyignore" "committed" || note ".graphifyignore" "absent — whole repo would be scanned"

printf '\nprod access\n'
if ssh -o BatchMode=yes -o ConnectTimeout=5 prod true 2>/dev/null; then
  ok "ssh prod" "reachable"
elif [ "$MODE" = "cloud" ]; then
  miss "ssh prod" "PROD_SSH_PRIVATE_KEY secret + bash scripts/cursor_cloud_setup_prod_ssh.sh"
else
  miss "ssh prod" "check host 'prod' in ~/.ssh/config"
fi

printf '\nMCP endpoints\n'
CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 -X POST "$PROD_MCP_URL" \
        -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
        -d '{}' 2>/dev/null)"
case "$CODE" in
  200|400|401) ok "tg-parser (prod)" "HTTP $CODE — endpoint alive" ;;
  404) miss "tg-parser (prod)" "HTTP 404 — URL must keep the /mcp suffix" ;;
  *)   miss "tg-parser (prod)" "HTTP ${CODE:-timeout}" ;;
esac
if [ "$MODE" = "local" ]; then
  curl -s -o /dev/null --max-time 3 "$LOCAL_MCP_URL" 2>/dev/null \
    && ok "tg-parser-local" "$LOCAL_MCP_URL up" \
    || note "tg-parser-local" "not running — start the local stack if you need it"
else
  note "tg-parser-local" "n/a in cloud — use the prod endpoint"
fi

printf '\nmode-specific, by design\n'
if [ "$MODE" = "cloud" ]; then
  note "methodology worktree" "unavailable — local-only task"
  note "Sourcegraph MCP" "interactive OAuth — local-only"
  note "TEST_TESTCONTAINERS" "needs Docker; covered by the CI alembic job"
else
  note "cron automations" "cloud-only — cannot run here"
fi
printf '\n'
