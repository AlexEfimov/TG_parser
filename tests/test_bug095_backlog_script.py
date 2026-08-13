"""BUG-095 — the backlog script's boundary handling.

The script owns half of a partition: it closes matches older than the
instant-flush watermark, the flush delivers everything newer. If the two halves
disagree about where the boundary is, the script sweeps matches the flush was
about to deliver and reports a live alert as "missed". These tests pin the
boundary rules; the delivery half is covered in
``test_bug095_watchlist_instant_delivery.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from scripts.watchlist_backlog_summary import _parse_before


class TestBoundaryResolution:
    def test_explicit_before_wins(self, monkeypatch):
        from tg_parser.config import settings

        monkeypatch.setattr(settings, "watchlist_instant_flush_cutoff", "2020-01-01T00:00:00Z")
        assert _parse_before("2026-08-13T12:00:00Z") == datetime(2026, 8, 13, 12, 0, tzinfo=UTC)

    def test_naive_before_is_read_as_utc(self):
        assert _parse_before("2026-08-13T12:00:00") == datetime(2026, 8, 13, 12, 0, tzinfo=UTC)

    def test_pinned_cutoff_is_used_when_before_is_omitted(self, monkeypatch):
        from tg_parser.config import settings

        monkeypatch.setattr(settings, "watchlist_instant_flush_cutoff", "2026-08-13T12:00:00Z")
        assert _parse_before(None) == datetime(2026, 8, 13, 12, 0, tzinfo=UTC)

    def test_without_any_boundary_the_script_refuses_rather_than_guessing(self, monkeypatch):
        """ "Now" would be the tempting default and it is the wrong one: the
        bot's watermark is process-local and invisible here, so "now" would
        swallow matches the flush has not delivered yet.
        """
        from tg_parser.config import settings
        from tg_parser.services import watchlist_service as ws

        monkeypatch.setattr(settings, "watchlist_instant_flush_cutoff", None)
        monkeypatch.setattr(ws, "_INSTANT_FLUSH_WATERMARK", None)

        with pytest.raises(SystemExit) as excinfo:
            _parse_before(None)
        # The operator is told where to read the value, not just that it is missing.
        assert "watchlist_instant_flush_registered" in str(excinfo.value)

    def test_malformed_before_fails_loudly(self):
        with pytest.raises(SystemExit, match="ISO-8601"):
            _parse_before("yesterday")
