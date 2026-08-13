"""Optional-dependency probes for pytest UX (DF-1 / Wave 1.5 dogfood).

Watchlist tests import ``tg_parser.services.watchlist_service`` (module-level
``structlog``) and exercise ``watchlist_tokenizer`` (lazy ``pymorphy3``).
Running under a system Python that lacks those packages historically produced
a cascade of hard failures that look like product regressions.

Two skip sets (do not conflate):

- **Import set** — modules that import ``watchlist_service`` /
  ``test_watchlist_service`` at collect time (or on first test import).
  Skipped / ignore-collected when ``structlog`` is missing.
- **Morph set** — modules that assert lemmatization / keyword morphology.
  Skipped when ``pymorphy3`` is missing. Subset of the import set; bot/F11
  suites that only wire fakes are **not** here (avoids over-skip).

Production code is unchanged: missing ``pymorphy3`` on prod remains a real
bug. This module only steers **pytest** toward a clear skip → use ``.venv``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

# Both failure modes called out in DF-1 / ε1 START_PROMPT.
WATCHLIST_OPTIONAL_DEPS: tuple[str, ...] = ("structlog", "pymorphy3")

WATCHLIST_DEPS_SKIP_REASON = (
    "watchlist tests need project venv deps (structlog, pymorphy3); "
    "use `.venv/bin/python -m pytest` (see tests/README.md)"
)

# Module-level (or first-import) consumers of watchlist_service / its test fakes.
# Keep in sync when adding ``from tg_parser.services.watchlist_service`` or
# ``from test_watchlist_service import …`` at module top (or equivalent).
_WATCHLIST_IMPORT_TEST_FILES: frozenset[str] = frozenset(
    {
        "test_watchlist_score.py",
        "test_watchlist_service.py",
        "test_watchlist_batch.py",
        "test_watchlist_metrics.py",
        "test_bug095_watchlist_instant_delivery.py",
        "test_bug095_instant_flush_wiring.py",
        "test_bug095_backlog_script.py",
        # BUG-095 added a service-level end-to-end that imports the fakes.
        "test_f11_watchlist_repo.py",
        "test_watchlist_workspace_id.py",
        "test_subscribe_idempotency.py",
        "test_digest_subscribe_race.py",
        "test_incremental_topicization.py",
        "test_f11_bot_tools.py",
        "test_f11_cli_watchlist.py",
        "test_f11_mcp_tools.py",
        "test_bot_confirm_flow.py",
        "test_bot_intent_break_bug048.py",
        "test_bot_chat_target_resolution.py",
        "test_bot_delete_routing_bug047.py",
        "test_bot_channel_name_parser.py",
        "test_bot_subscribe_channel_resume_bug050.py",
        "test_bot_unsubscribe_confirm_gate_g1.py",
        "test_scheduler_invalidation_on_unsubscribe.py",
        "test_enh001_last_checked_telemetry.py",
    }
)

# Suites that hard-fail without pymorphy3 (lemma / alias assertions).
_WATCHLIST_MORPH_TEST_FILES: frozenset[str] = frozenset(
    {
        "test_watchlist_score.py",
        "test_watchlist_service.py",
        "test_watchlist_batch.py",
        # BUG-095 red/green drives real scoring through check_interests.
        "test_bug095_watchlist_instant_delivery.py",
    }
)

# Union — useful for docs / "is this a watchlist-dep module at all?"
_WATCHLIST_DEP_TEST_FILES: frozenset[str] = (
    _WATCHLIST_IMPORT_TEST_FILES | _WATCHLIST_MORPH_TEST_FILES
)


def missing_watchlist_deps() -> list[str]:
    """Return names of watchlist optional deps not importable in this interpreter."""
    missing: list[str] = []
    for name in WATCHLIST_OPTIONAL_DEPS:
        try:
            if importlib.util.find_spec(name) is None:
                missing.append(name)
        except ModuleNotFoundError:
            # Some meta-path finders raise instead of returning None.
            missing.append(name)
    return missing


def watchlist_deps_available() -> bool:
    return not missing_watchlist_deps()


def files_to_skip_for_missing_deps(missing: list[str] | None = None) -> frozenset[str]:
    """Filenames that should skip given the missing-dep list.

    - ``structlog`` missing → entire import set (avoid ImportError / bad collect).
    - ``pymorphy3`` missing → morph set only (bot/F11 wiring tests still run).
    """
    if missing is None:
        missing = missing_watchlist_deps()
    files: set[str] = set()
    if "structlog" in missing:
        files |= _WATCHLIST_IMPORT_TEST_FILES
    if "pymorphy3" in missing:
        files |= _WATCHLIST_MORPH_TEST_FILES
    return frozenset(files)


def is_watchlist_dep_test_path(path: Path | str) -> bool:
    """True if *path* is in the import or morph watchlist-dep sets."""
    return Path(path).name in _WATCHLIST_DEP_TEST_FILES


def is_watchlist_import_test_path(path: Path | str) -> bool:
    """True if *path* imports watchlist_service (needs structlog at collect)."""
    return Path(path).name in _WATCHLIST_IMPORT_TEST_FILES


def is_watchlist_morph_test_path(path: Path | str) -> bool:
    """True if *path* asserts morphology (needs pymorphy3)."""
    return Path(path).name in _WATCHLIST_MORPH_TEST_FILES


def should_skip_watchlist_test_path(path: Path | str, missing: list[str] | None = None) -> bool:
    """True if this test module should skip for the current missing deps."""
    return Path(path).name in files_to_skip_for_missing_deps(missing)


def is_watchlist_dep_nodeid(nodeid: str, missing: list[str] | None = None) -> bool:
    """True if a collected item should skip for the current missing deps.

    When *missing* is omitted, uses :func:`missing_watchlist_deps` (live probe).
    Pass an explicit list from tests to assert skip-set membership without
    depending on the host interpreter's site-packages.
    """
    file_part = nodeid.split("::", 1)[0]
    return should_skip_watchlist_test_path(file_part, missing=missing)


def require_watchlist_deps() -> None:
    """Module-level skip when structlog / pymorphy3 are missing.

    Call **before** importing ``watchlist_service`` so a missing ``structlog``
    becomes a clear skip instead of ``ImportError`` during collection.
    """
    missing = missing_watchlist_deps()
    if missing:
        pytest.skip(
            f"missing {', '.join(missing)}; {WATCHLIST_DEPS_SKIP_REASON}",
            allow_module_level=True,
        )
