"""F5-C P2 / #15 item #10 — per-channel re-summarize metric tests.

The previously-reserved ``channel_id`` label on ``tg_resummarize_total`` is now
threaded through :func:`tg_parser.api.metrics.record_resummarize_outcome`. These
pure-unit tests assert the label moves the right series (real channel on
card-bearing paths, ``"-"`` fallback otherwise) without needing Postgres.
"""

from __future__ import annotations

import pytest

from tg_parser.api.metrics import RESUMMARIZE_TOTAL, record_resummarize_outcome


def _counter_value(counter, **labels: str) -> float:
    return counter.labels(**labels)._value.get()


def test_outcome_uses_real_channel_label() -> None:
    before = _counter_value(RESUMMARIZE_TOTAL, channel_id="ch-42", outcome="ok")
    record_resummarize_outcome(topic_id="topic:x", status="ok", channel_id="ch-42")
    after = _counter_value(RESUMMARIZE_TOTAL, channel_id="ch-42", outcome="ok")
    assert after == pytest.approx(before + 1.0)


def test_outcome_defaults_to_dash_when_channel_unknown() -> None:
    before = _counter_value(RESUMMARIZE_TOTAL, channel_id="-", outcome="locked")
    record_resummarize_outcome(topic_id="topic:y", status="locked")
    after = _counter_value(RESUMMARIZE_TOTAL, channel_id="-", outcome="locked")
    assert after == pytest.approx(before + 1.0)


def test_empty_channel_normalises_to_dash() -> None:
    before = _counter_value(RESUMMARIZE_TOTAL, channel_id="-", outcome="no_card")
    record_resummarize_outcome(topic_id="topic:z", status="no_card", channel_id="")
    after = _counter_value(RESUMMARIZE_TOTAL, channel_id="-", outcome="no_card")
    assert after == pytest.approx(before + 1.0)
