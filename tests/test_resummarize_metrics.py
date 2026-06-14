"""F5-C P2 / #15 item #10 + Wave 2 — re-summarize metric label tests.

The ``channel_id`` label on ``tg_resummarize_total`` (F5-C P2) and the Wave 2
additions — ``channel_id`` on ``tg_resummarize_tokens_total`` and the
``trigger`` (counter / age / "-") label on ``tg_resummarize_total`` — are all
threaded through :func:`tg_parser.api.metrics.record_resummarize_outcome`.
These pure-unit tests assert each label moves the right series without needing
Postgres.
"""

from __future__ import annotations

import pytest

from tg_parser.api.metrics import (
    RESUMMARIZE_TOKENS_TOTAL,
    RESUMMARIZE_TOTAL,
    record_resummarize_outcome,
)


def _counter_value(counter, **labels: str) -> float:
    return counter.labels(**labels)._value.get()


def test_outcome_uses_real_channel_label() -> None:
    before = _counter_value(
        RESUMMARIZE_TOTAL, channel_id="ch-42", outcome="ok", trigger="counter"
    )
    record_resummarize_outcome(
        topic_id="topic:x", status="ok", channel_id="ch-42", trigger="counter"
    )
    after = _counter_value(
        RESUMMARIZE_TOTAL, channel_id="ch-42", outcome="ok", trigger="counter"
    )
    assert after == pytest.approx(before + 1.0)


def test_outcome_defaults_to_dash_when_channel_unknown() -> None:
    before = _counter_value(
        RESUMMARIZE_TOTAL, channel_id="-", outcome="locked", trigger="-"
    )
    record_resummarize_outcome(topic_id="topic:y", status="locked")
    after = _counter_value(
        RESUMMARIZE_TOTAL, channel_id="-", outcome="locked", trigger="-"
    )
    assert after == pytest.approx(before + 1.0)


def test_empty_channel_normalises_to_dash() -> None:
    before = _counter_value(
        RESUMMARIZE_TOTAL, channel_id="-", outcome="no_card", trigger="-"
    )
    record_resummarize_outcome(topic_id="topic:z", status="no_card", channel_id="")
    after = _counter_value(
        RESUMMARIZE_TOTAL, channel_id="-", outcome="no_card", trigger="-"
    )
    assert after == pytest.approx(before + 1.0)


def test_trigger_counter_label_recorded() -> None:
    before = _counter_value(
        RESUMMARIZE_TOTAL, channel_id="ch-7", outcome="ok", trigger="counter"
    )
    record_resummarize_outcome(
        topic_id="topic:c", status="ok", channel_id="ch-7", trigger="counter"
    )
    after = _counter_value(
        RESUMMARIZE_TOTAL, channel_id="ch-7", outcome="ok", trigger="counter"
    )
    assert after == pytest.approx(before + 1.0)


def test_trigger_age_label_recorded() -> None:
    before = _counter_value(
        RESUMMARIZE_TOTAL, channel_id="ch-7", outcome="ok", trigger="age"
    )
    record_resummarize_outcome(
        topic_id="topic:a", status="ok", channel_id="ch-7", trigger="age"
    )
    after = _counter_value(
        RESUMMARIZE_TOTAL, channel_id="ch-7", outcome="ok", trigger="age"
    )
    assert after == pytest.approx(before + 1.0)


def test_trigger_defaults_to_dash_fallback() -> None:
    before = _counter_value(
        RESUMMARIZE_TOTAL, channel_id="ch-7", outcome="empty_scope", trigger="-"
    )
    # Omitting ``trigger`` (e.g. a direct force_resummarize that matched neither
    # predicate) falls back to "-" so unknown paths stay bounded.
    record_resummarize_outcome(
        topic_id="topic:f", status="empty_scope", channel_id="ch-7"
    )
    after = _counter_value(
        RESUMMARIZE_TOTAL, channel_id="ch-7", outcome="empty_scope", trigger="-"
    )
    assert after == pytest.approx(before + 1.0)


def test_tokens_counter_carries_channel_label() -> None:
    before_prompt = _counter_value(
        RESUMMARIZE_TOKENS_TOTAL,
        channel_id="ch-9",
        provider="anthropic",
        model="claude-x",
        token_type="prompt",
    )
    before_completion = _counter_value(
        RESUMMARIZE_TOKENS_TOTAL,
        channel_id="ch-9",
        provider="anthropic",
        model="claude-x",
        token_type="completion",
    )
    record_resummarize_outcome(
        topic_id="topic:tok",
        status="ok",
        channel_id="ch-9",
        trigger="counter",
        input_tokens=11,
        output_tokens=7,
        model="anthropic/claude-x",
    )
    after_prompt = _counter_value(
        RESUMMARIZE_TOKENS_TOTAL,
        channel_id="ch-9",
        provider="anthropic",
        model="claude-x",
        token_type="prompt",
    )
    after_completion = _counter_value(
        RESUMMARIZE_TOKENS_TOTAL,
        channel_id="ch-9",
        provider="anthropic",
        model="claude-x",
        token_type="completion",
    )
    assert after_prompt == pytest.approx(before_prompt + 11.0)
    assert after_completion == pytest.approx(before_completion + 7.0)


def test_tokens_counter_dash_fallback_when_channel_unknown() -> None:
    before = _counter_value(
        RESUMMARIZE_TOKENS_TOTAL,
        channel_id="-",
        provider="openai",
        model="gpt-z",
        token_type="prompt",
    )
    record_resummarize_outcome(
        topic_id="topic:tok2",
        status="ok",
        channel_id="",
        trigger="age",
        input_tokens=5,
        model="openai/gpt-z",
    )
    after = _counter_value(
        RESUMMARIZE_TOKENS_TOTAL,
        channel_id="-",
        provider="openai",
        model="gpt-z",
        token_type="prompt",
    )
    assert after == pytest.approx(before + 5.0)


# ----------------------------------------------------------------------------
# Service-level trigger classification (_classify_trigger) — pure-unit, no PG.
# ----------------------------------------------------------------------------


class _FakeCard:
    def __init__(self, *, new_items: int, last_summarized_at):
        self.new_items_since_last_summary = new_items
        self.last_summarized_at = last_summarized_at


def test_classify_trigger_counter(monkeypatch) -> None:
    from tg_parser.config import settings
    from tg_parser.services.resummarization_service import _classify_trigger

    monkeypatch.setattr(settings, "resummarize_trigger_n", 5, raising=False)
    monkeypatch.setattr(settings, "resummarize_max_age_days", 14, raising=False)
    card = _FakeCard(new_items=8, last_summarized_at=None)
    assert _classify_trigger(card) == "counter"


def test_classify_trigger_age(monkeypatch) -> None:
    from datetime import UTC, datetime, timedelta

    from tg_parser.config import settings
    from tg_parser.services.resummarization_service import _classify_trigger

    monkeypatch.setattr(settings, "resummarize_trigger_n", 5, raising=False)
    monkeypatch.setattr(settings, "resummarize_max_age_days", 14, raising=False)
    old = datetime.now(UTC) - timedelta(days=30)
    card = _FakeCard(new_items=2, last_summarized_at=old)
    assert _classify_trigger(card) == "age"


def test_classify_trigger_fallback_dash(monkeypatch) -> None:
    from datetime import UTC, datetime, timedelta

    from tg_parser.config import settings
    from tg_parser.services.resummarization_service import _classify_trigger

    monkeypatch.setattr(settings, "resummarize_trigger_n", 5, raising=False)
    monkeypatch.setattr(settings, "resummarize_max_age_days", 14, raising=False)
    # Below counter threshold and last summary is recent → neither predicate.
    recent = datetime.now(UTC) - timedelta(days=1)
    card = _FakeCard(new_items=2, last_summarized_at=recent)
    assert _classify_trigger(card) == "-"


def test_classify_trigger_age_disabled_falls_back(monkeypatch) -> None:
    from datetime import UTC, datetime, timedelta

    from tg_parser.config import settings
    from tg_parser.services.resummarization_service import _classify_trigger

    monkeypatch.setattr(settings, "resummarize_trigger_n", 5, raising=False)
    monkeypatch.setattr(settings, "resummarize_max_age_days", 0, raising=False)
    old = datetime.now(UTC) - timedelta(days=30)
    card = _FakeCard(new_items=2, last_summarized_at=old)
    assert _classify_trigger(card) == "-"
