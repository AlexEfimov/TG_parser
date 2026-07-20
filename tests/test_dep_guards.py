"""Unit tests for DF-1 watchlist optional-dep pytest guard."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import patch

import pytest
from _dep_guards import (
    WATCHLIST_DEPS_SKIP_REASON,
    WATCHLIST_OPTIONAL_DEPS,
    files_to_skip_for_missing_deps,
    is_watchlist_dep_nodeid,
    is_watchlist_dep_test_path,
    is_watchlist_import_test_path,
    is_watchlist_morph_test_path,
    missing_watchlist_deps,
    require_watchlist_deps,
    should_skip_watchlist_test_path,
    watchlist_deps_available,
)


class TestWatchlistDepPathMatchers:
    def test_import_set_covers_bot_and_f11(self) -> None:
        assert is_watchlist_import_test_path("tests/test_bot_confirm_flow.py")
        assert is_watchlist_import_test_path(Path("test_f11_mcp_tools.py"))
        assert is_watchlist_import_test_path("test_digest_subscribe_race.py")
        assert is_watchlist_dep_test_path("tests/test_watchlist_score.py")

    def test_morph_set_is_narrow(self) -> None:
        assert is_watchlist_morph_test_path("test_watchlist_score.py")
        assert is_watchlist_morph_test_path("test_watchlist_service.py")
        assert is_watchlist_morph_test_path("test_watchlist_batch.py")
        assert not is_watchlist_morph_test_path("test_bot_confirm_flow.py")
        assert not is_watchlist_morph_test_path("test_f11_mcp_tools.py")

    def test_unrelated_files_not_matched(self) -> None:
        assert not is_watchlist_dep_test_path("tests/test_mcp_server.py")
        assert not is_watchlist_import_test_path("tests/test_logging.py")


class TestSkipSetsByMissingDep:
    def test_pymorphy3_only_skips_morph_not_bot(self) -> None:
        missing = ["pymorphy3"]
        skip = files_to_skip_for_missing_deps(missing)
        assert "test_watchlist_score.py" in skip
        assert "test_watchlist_service.py" in skip
        assert "test_watchlist_batch.py" in skip
        assert "test_bot_confirm_flow.py" not in skip
        assert "test_f11_mcp_tools.py" not in skip
        assert should_skip_watchlist_test_path("test_watchlist_score.py", missing)
        assert not should_skip_watchlist_test_path("test_bot_confirm_flow.py", missing)
        assert is_watchlist_dep_nodeid(
            "tests/test_watchlist_score.py::TestX::test_y", missing=missing
        )
        assert not is_watchlist_dep_nodeid(
            "tests/test_bot_confirm_flow.py::TestX::test_y", missing=missing
        )

    def test_structlog_skips_full_import_set(self) -> None:
        missing = ["structlog"]
        skip = files_to_skip_for_missing_deps(missing)
        assert "test_bot_confirm_flow.py" in skip
        assert "test_f11_cli_watchlist.py" in skip
        assert "test_digest_subscribe_race.py" in skip
        assert "test_watchlist_score.py" in skip

    def test_both_missing_is_union(self) -> None:
        missing = ["structlog", "pymorphy3"]
        skip = files_to_skip_for_missing_deps(missing)
        assert "test_bot_confirm_flow.py" in skip
        assert "test_watchlist_score.py" in skip

    def test_nothing_missing_skips_nothing(self) -> None:
        assert files_to_skip_for_missing_deps([]) == frozenset()


class TestMissingWatchlistDeps:
    def test_reports_absent_module(self) -> None:
        real_find_spec = __import__("importlib.util", fromlist=["find_spec"]).find_spec

        def _fake_find_spec(name: str, package: str | None = None):
            if name == "pymorphy3":
                return None
            return real_find_spec(name, package)

        with patch("importlib.util.find_spec", side_effect=_fake_find_spec):
            missing = missing_watchlist_deps()
        assert missing == ["pymorphy3"]

    def test_probe_consistent_with_availability(self) -> None:
        missing = missing_watchlist_deps()
        assert set(missing) <= set(WATCHLIST_OPTIONAL_DEPS)
        assert watchlist_deps_available() is (not missing)


class TestRequireWatchlistDeps:
    def test_skips_when_dep_missing(self) -> None:
        with patch(
            "_dep_guards.missing_watchlist_deps",
            return_value=["pymorphy3"],
        ):
            with pytest.raises(pytest.skip.Exception) as excinfo:
                require_watchlist_deps()
        assert "pymorphy3" in str(excinfo.value)
        assert "venv" in str(excinfo.value).lower() or WATCHLIST_DEPS_SKIP_REASON[:20] in str(
            excinfo.value
        )

    def test_noop_when_deps_present(self) -> None:
        with patch("_dep_guards.missing_watchlist_deps", return_value=[]):
            require_watchlist_deps()  # must not raise


class TestConftestStructlogReachability:
    """Bugbot: ignore_collect must register even when structlog is absent."""

    def test_conftest_has_no_eager_settings_or_database_import(self) -> None:
        conftest_path = Path(__file__).resolve().parent / "conftest.py"
        tree = ast.parse(conftest_path.read_text(encoding="utf-8"))
        eager: list[str] = []
        for node in tree.body:
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if node.module in {
                "tg_parser.config.settings",
                "tg_parser.storage.sqlalchemy",
            }:
                eager.append(node.module)
            if node.module == "tg_parser.storage.sqlalchemy.database":
                eager.append(node.module)
        assert eager == [], (
            "conftest must lazy-import Settings/Database so DF-1 hooks register "
            f"without structlog; found eager imports: {eager}"
        )
