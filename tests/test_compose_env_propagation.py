"""
Regression tests for DI-16: docker-compose env propagation.

Background
----------
`tg-parser migrate-users` runs inside the `tg_parser` service. To map
credentials from `.env` into the user model, it needs visibility of:

  - API_KEYS               (always required)
  - API_KEY_REQUIRED       (always required)
  - MCP_AUTH_ENABLED       (always required)
  - MCP_AUTH_TOKENS        (mcp client credentials)
  - BOT_ALLOWED_USERS      (telegram user allowlist)

Historically `MCP_AUTH_TOKENS` was only declared in the `mcp` service block
and `BOT_ALLOWED_USERS` only in the `tg_bot` service block.  As a result,
`migrate-users` silently mapped 0 mcp tokens and 0 telegram users on a clean
deployment, even though `.env` was correctly populated and Settings parsed
the JSON without errors (DI-12 covered the parsing/observability side, not
this propagation side).

These tests assert the env-variable surface area each service exposes, so
that future edits to `docker-compose.yml` cannot silently re-introduce the
gap.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

COMPOSE_PATH = Path(__file__).resolve().parent.parent / "docker-compose.yml"


@pytest.fixture(scope="module")
def compose_config() -> dict:
    with COMPOSE_PATH.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _service_env_keys(compose_config: dict, service: str) -> set[str]:
    """Return the set of env variable names declared for `service`."""
    services = compose_config.get("services") or {}
    spec = services.get(service)
    assert spec is not None, f"service '{service}' missing from docker-compose.yml"
    raw_env = spec.get("environment") or []
    keys: set[str] = set()
    if isinstance(raw_env, list):
        for item in raw_env:
            assert isinstance(item, str), f"unexpected env item type: {item!r}"
            name = item.split("=", 1)[0].strip()
            if name:
                keys.add(name)
    elif isinstance(raw_env, dict):
        keys.update(raw_env.keys())
    else:  # pragma: no cover — defensive
        raise AssertionError(f"unexpected env block type: {type(raw_env)!r}")
    return keys


# ---------------------------------------------------------------------------
# DI-16: tg_parser must see EVERY auth source migrate-users needs to map.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "var",
    [
        "API_KEY_REQUIRED",
        "API_KEYS",
        "MCP_AUTH_ENABLED",
        "MCP_AUTH_TOKENS",
        "BOT_ALLOWED_USERS",
    ],
)
def test_tg_parser_service_exposes_auth_env(compose_config: dict, var: str) -> None:
    """tg_parser hosts the migrate-users CLI and must see every auth source."""
    keys = _service_env_keys(compose_config, "tg_parser")
    assert var in keys, (
        f"{var!r} missing from `tg_parser` env block in docker-compose.yml. "
        "Without it, `tg-parser migrate-users` cannot map credentials from .env "
        "(see DI-16 in docs/notes/FUTURE_FEATURES.md)."
    )


# ---------------------------------------------------------------------------
# Per-service guarantees that already held before DI-16 — pinned for safety.
# ---------------------------------------------------------------------------


def test_mcp_service_exposes_mcp_auth(compose_config: dict) -> None:
    """The MCP server itself authenticates clients via MCP_AUTH_*."""
    keys = _service_env_keys(compose_config, "mcp")
    assert {"MCP_AUTH_ENABLED", "MCP_AUTH_TOKENS"}.issubset(keys), (
        f"mcp service missing MCP_AUTH_* env: {keys}"
    )


@pytest.mark.parametrize(
    "var",
    [
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "EMBEDDING_PROVIDER",
        "EMBEDDING_MODEL",
        "RAG_LLM_PROVIDER",
        "RAG_LLM_MODEL",
    ],
)
def test_mcp_service_exposes_full_llm_surface(compose_config: dict, var: str) -> None:
    """DI-17: the MCP server hosts ask_question / search_knowledge_base, which
    can route to any of the three LLM providers depending on .env. Without
    the full key trio + RAG/EMBEDDING settings, ask_question silently fails
    with provider-specific 'API key required' errors at runtime even though
    .env is correctly populated.
    """
    keys = _service_env_keys(compose_config, "mcp")
    assert var in keys, (
        f"{var!r} missing from `mcp` env block in docker-compose.yml. "
        "Without it, MCP tools that need this provider/setting fail at "
        "runtime even when .env is correct (see DI-17 in docs/notes/FUTURE_FEATURES.md)."
    )


def test_tg_bot_service_exposes_bot_allowlist(compose_config: dict) -> None:
    """The bot enforces BOT_ALLOWED_USERS on every incoming Telegram update."""
    keys = _service_env_keys(compose_config, "tg_bot")
    assert "BOT_ALLOWED_USERS" in keys, f"tg_bot service missing BOT_ALLOWED_USERS env: {keys}"
    assert "TELEGRAM_BOT_TOKEN" in keys, f"tg_bot service missing TELEGRAM_BOT_TOKEN env: {keys}"
