"""
Regression tests for `tg_parser.processing.mock_llm`.

Anchored on BUG-002 mitigation M1 (`docs/notes/BUG_LOG.md` § BUG-002 §
«Mitigation backlog»): `TopicizationMockLLM.__init__` must require
`channel_id` explicitly so no production code path can silently fall
back to the `test_channel` placeholder, which becomes an attractor for
LLM hallucination in the bot's confirm-flow.
"""

from __future__ import annotations

import inspect
import json

import pytest

from tg_parser.processing.mock_llm import (
    DeterministicMockLLM,
    MockLLMClient,
    ProcessingMockLLM,
    TopicizationMockLLM,
)


class TestTopicizationMockLLMRequiresChannelId:
    """M1: `TopicizationMockLLM` must not default `channel_id` to any literal."""

    def test_missing_channel_id_raises(self) -> None:
        """Calling without channel_id raises a TypeError (no silent default)."""
        with pytest.raises(TypeError):
            TopicizationMockLLM()  # type: ignore[call-arg]

    def test_signature_has_no_default_for_channel_id(self) -> None:
        """Signature inspection: parameter is positional, no default value."""
        sig = inspect.signature(TopicizationMockLLM.__init__)
        param = sig.parameters["channel_id"]
        assert param.default is inspect.Parameter.empty, (
            f"TopicizationMockLLM.__init__ must not provide a default for channel_id; "
            f"found default={param.default!r}. See BUG-002 mitigation M1."
        )
        assert param.annotation is str

    def test_no_test_channel_literal_in_source(self) -> None:
        """The `test_channel` literal must not appear in the mock_llm source.

        Anchors against future regressions where someone re-introduces
        the placeholder as a fixture default. Comments are allowed iff
        they reference BUG-002 explicitly.
        """
        src = inspect.getsource(TopicizationMockLLM)
        assert '"test_channel"' not in src, (
            "TopicizationMockLLM still embeds `test_channel` as a literal; "
            "see BUG-002 mitigation M1."
        )

    async def test_explicit_channel_id_propagates_into_source_ref(self) -> None:
        """Explicit channel_id flows through to anchor source_refs."""
        mock = TopicizationMockLLM(channel_id="my_dev_channel")

        out = await mock.generate(prompt="extract topics from messages...")
        payload = json.loads(out)

        assert payload["topics"], "mock should return at least one topic"
        anchors = payload["topics"][0]["anchors"]
        assert anchors, "topic should have anchors"
        for anchor in anchors:
            assert "my_dev_channel" in anchor["source_ref"]
            assert "test_channel" not in anchor["source_ref"]


class TestOtherMocksAreUnchangedByM1:
    """Sanity: M1 only constrains TopicizationMockLLM, not the other mocks."""

    async def test_mock_llm_client_default_response(self) -> None:
        client = MockLLMClient()
        out = await client.generate(prompt="hello")
        assert out == "Mock LLM response"

    async def test_deterministic_mock_returns_value(self) -> None:
        client = DeterministicMockLLM()
        out_a = await client.generate(prompt="x")
        out_b = await client.generate(prompt="x")
        assert out_a == out_b

    async def test_processing_mock_returns_json(self) -> None:
        client = ProcessingMockLLM()
        out = await client.generate(prompt="some message text")
        payload = json.loads(out)
        assert "text_clean" in payload
        assert "summary" in payload
