#!/usr/bin/env bash
# Install the graphify toolchain and build/refresh the repository's code graph.
#
# Idempotent: safe to re-run. Runs identically on a developer Mac and on a
# Cursor Cloud VM, so the same command serves both modes.
#
# Code-only extraction (tree-sitter AST) — no LLM call, no API key, no network
# beyond installing the tool itself. Corpus boundaries live in .graphifyignore.
#
# Output goes to graphify-out/ (git-ignored, derived). Point GRAPHIFY_OUT at an
# absolute path to keep the repository untouched, e.g. for experiments:
#   GRAPHIFY_OUT=/tmp/gf_out bash scripts/graphify_bootstrap.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$HOME/.local/bin:$PATH"

log() { printf 'graphify_bootstrap: %s\n' "$1"; }

if ! command -v uv >/dev/null 2>&1; then
  log "installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
fi

if ! command -v graphify >/dev/null 2>&1; then
  log "installing graphifyy[mcp]"
  uv tool install "graphifyy[mcp]" >/dev/null
fi

log "$(graphify --version 2>/dev/null | head -1)"

cd "$ROOT"
# Incremental: unchanged files come from graphify-out/cache, keyed by content
# hash. Only the graph assembly is redone, which is the bulk of the runtime.
graphify update . >/dev/null
log "graph ready at ${GRAPHIFY_OUT:-graphify-out}/graph.json"
