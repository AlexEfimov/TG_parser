"""
Tests for topicization prompt builders.

Validates prompt structure, content inclusion, and edge cases
to protect against prompt regressions.
"""

import pytest

from tg_parser.processing.topicization_prompts import (
    INCREMENTAL_DISCOVER_SYSTEM_PROMPT,
    TOPICIZATION_SYSTEM_PROMPT,
    build_incremental_discover_prompt,
    build_supporting_items_prompt,
    build_topicization_prompt,
    get_incremental_discover_prompt_name,
    get_supporting_items_prompt_name,
    get_topicization_prompt_name,
)


class TestBuildTopicizationPrompt:
    def test_basic_prompt_structure(self):
        messages = [
            {
                "source_ref": "tg:ch1:post:1",
                "text_clean": "Python async programming guide",
                "summary": "Guide to asyncio",
                "topics": ["python", "async"],
            }
        ]
        prompt = build_topicization_prompt(messages)

        assert "tg:ch1:post:1" in prompt
        assert "Python async programming guide" in prompt
        assert "Guide to asyncio" in prompt
        assert "python, async" in prompt

    def test_multiple_messages(self):
        messages = [
            {
                "source_ref": f"tg:ch1:post:{i}",
                "text_clean": f"Message {i} text",
                "summary": f"Summary {i}",
                "topics": [f"topic_{i}"],
            }
            for i in range(5)
        ]
        prompt = build_topicization_prompt(messages)

        for i in range(5):
            assert f"tg:ch1:post:{i}" in prompt
            assert f"Message {i} text" in prompt

    def test_long_text_truncation(self):
        messages = [
            {
                "source_ref": "tg:ch1:post:1",
                "text_clean": "x" * 1000,
                "summary": "Long text",
                "topics": [],
            }
        ]
        prompt = build_topicization_prompt(messages)
        assert "..." in prompt
        assert len(prompt) < 1500

    def test_empty_topics_and_summary(self):
        messages = [
            {
                "source_ref": "tg:ch1:post:1",
                "text_clean": "Some text",
                "summary": "",
                "topics": [],
            }
        ]
        prompt = build_topicization_prompt(messages)
        assert "N/A" in prompt

    def test_empty_messages_list(self):
        prompt = build_topicization_prompt([])
        assert isinstance(prompt, str)


class TestBuildSupportingItemsPrompt:
    def test_basic_prompt_structure(self):
        prompt = build_supporting_items_prompt(
            topic_title="Python Async",
            topic_summary="Guide to async programming in Python",
            scope_in=["asyncio", "coroutines"],
            scope_out=["JavaScript promises"],
            anchor_refs=["tg:ch1:post:1"],
            messages=[
                {
                    "source_ref": "tg:ch1:post:2",
                    "text_clean": "Candidate message",
                    "summary": "About coroutines",
                },
                {
                    "source_ref": "tg:ch1:post:1",
                    "text_clean": "This is an anchor — should be skipped",
                    "summary": "Anchor message",
                },
            ],
        )

        assert "Python Async" in prompt
        assert "asyncio" in prompt
        assert "JavaScript promises" in prompt
        assert "tg:ch1:post:2" in prompt

    def test_anchor_messages_excluded(self):
        prompt = build_supporting_items_prompt(
            topic_title="Test",
            topic_summary="Test topic",
            scope_in=["test"],
            scope_out=[],
            anchor_refs=["tg:ch1:post:1"],
            messages=[
                {
                    "source_ref": "tg:ch1:post:1",
                    "text_clean": "Anchor text that should not appear in candidates",
                    "summary": "Anchor",
                },
            ],
        )
        assert "Anchor text that should not appear" not in prompt


class TestBuildIncrementalDiscoverPrompt:
    def test_basic_structure_with_existing_topics(self):
        existing = [
            {"id": "topic:ch1:post:1", "title": "Python", "scope_in": ["asyncio", "typing"]},
            {"id": "topic:ch1:post:2", "title": "ML", "scope_in": ["pytorch"]},
        ]
        docs = [
            {
                "source_ref": "tg:ch1:post:10",
                "summary": "New doc about NLP",
                "topics": ["nlp"],
                "text_clean": "Natural language processing tutorial",
            }
        ]

        prompt = build_incremental_discover_prompt(existing, docs)

        assert "topic:ch1:post:1" in prompt
        assert "Python" in prompt
        assert "asyncio" in prompt
        assert "tg:ch1:post:10" in prompt
        assert "NLP" in prompt or "nlp" in prompt

    def test_cross_channel_topics_section(self):
        existing = [{"id": "t1", "title": "Local Topic", "scope_in": ["local"]}]
        docs = [{"source_ref": "ref:1", "summary": "Doc", "topics": [], "text_clean": "Text"}]
        cross = [
            {"id": "t_other", "title": "Foreign Topic", "scope_in": ["foreign"], "channel_id": "other_ch"},
        ]

        prompt = build_incremental_discover_prompt(existing, docs, cross_channel_topics=cross)

        assert "Foreign Topic" in prompt
        assert "other_ch" in prompt
        assert "do not assign documents to these" in prompt.lower()

    def test_no_cross_channel_topics(self):
        existing = [{"id": "t1", "title": "Topic", "scope_in": []}]
        docs = [{"source_ref": "ref:1", "summary": "Doc", "topics": [], "text_clean": "Text"}]

        prompt = build_incremental_discover_prompt(existing, docs, cross_channel_topics=None)

        assert "other channels" not in prompt.lower() or "OTHER channels" not in prompt

    def test_long_text_truncated_in_docs(self):
        existing = []
        docs = [
            {
                "source_ref": "ref:1",
                "summary": "Summary",
                "topics": [],
                "text_clean": "w" * 1000,
            }
        ]
        prompt = build_incremental_discover_prompt(existing, docs)
        assert "..." in prompt


class TestPromptNameFunctions:
    def test_topicization_prompt_name(self):
        name = get_topicization_prompt_name()
        assert isinstance(name, str)
        assert len(name) > 0

    def test_supporting_items_prompt_name(self):
        name = get_supporting_items_prompt_name()
        assert isinstance(name, str)
        assert len(name) > 0

    def test_incremental_discover_prompt_name(self):
        name = get_incremental_discover_prompt_name()
        assert isinstance(name, str)
        assert len(name) > 0


class TestSystemPrompts:
    def test_topicization_system_prompt_has_json_structure(self):
        assert "topics" in TOPICIZATION_SYSTEM_PROMPT
        assert "JSON" in TOPICIZATION_SYSTEM_PROMPT
        assert "singleton" in TOPICIZATION_SYSTEM_PROMPT
        assert "cluster" in TOPICIZATION_SYSTEM_PROMPT

    def test_incremental_discover_system_prompt_has_structure(self):
        assert "assignments" in INCREMENTAL_DISCOVER_SYSTEM_PROMPT
        assert "new_topics" in INCREMENTAL_DISCOVER_SYSTEM_PROMPT
        assert "unassignable" in INCREMENTAL_DISCOVER_SYSTEM_PROMPT
