"""
Tests for topicization prompt builders.

Validates prompt structure, content inclusion, and edge cases
to protect against prompt regressions.
"""

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
    def test_returns_non_empty_string(self):
        messages = [
            {
                "source_ref": "tg:x:post:1",
                "text_clean": "Hello",
                "summary": "",
                "topics": [],
            }
        ]
        prompt = build_topicization_prompt(messages)
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_includes_user_template_markers(self):
        messages = [
            {
                "source_ref": "tg:ch1:post:1",
                "text_clean": "Body",
                "summary": "S",
                "topics": ["t"],
            }
        ]
        prompt = build_topicization_prompt(messages)
        assert "Analyze these messages" in prompt
        assert "Return structured JSON" in prompt

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

        assert len(prompt) > 0
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
        assert len(prompt) > 0
        assert "Analyze these messages" in prompt


class TestBuildSupportingItemsPrompt:
    def test_returns_non_empty_string(self):
        prompt = build_supporting_items_prompt(
            topic_title="T",
            topic_summary="S",
            scope_in=["a"],
            scope_out=["b"],
            anchor_refs=[],
            messages=[
                {"source_ref": "tg:1:post:1", "text_clean": "x", "summary": ""},
            ],
        )
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_includes_template_placeholders_content(self):
        prompt = build_supporting_items_prompt(
            topic_title="My Topic",
            topic_summary="My summary line",
            scope_in=["in1"],
            scope_out=["out1"],
            anchor_refs=["tg:anchor:post:1"],
            messages=[{"source_ref": "tg:c:post:9", "text_clean": "Hi", "summary": "Sum"}],
        )
        assert "Topic: My Topic" in prompt
        assert "Summary: My summary line" in prompt
        assert "Scope (what's included):" in prompt
        assert "Scope (what's excluded):" in prompt
        assert "Anchor messages (already included):" in prompt
        assert "Return supporting items" in prompt
        assert "tg:anchor:post:1" in prompt

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
        assert len(prompt) > 0

    def test_empty_scope_and_anchor_lists(self):
        prompt = build_supporting_items_prompt(
            topic_title="T",
            topic_summary="S",
            scope_in=[],
            scope_out=[],
            anchor_refs=[],
            messages=[{"source_ref": "tg:1:post:1", "text_clean": "body", "summary": ""}],
        )
        assert len(prompt) > 0
        assert "Topic: T" in prompt
        assert "tg:1:post:1" in prompt

    def test_empty_messages_list(self):
        prompt = build_supporting_items_prompt(
            topic_title="T",
            topic_summary="S",
            scope_in=["x"],
            scope_out=["y"],
            anchor_refs=[],
            messages=[],
        )
        assert len(prompt) > 0
        assert "Evaluate these messages" in prompt

    def test_long_text_truncation(self):
        prompt = build_supporting_items_prompt(
            topic_title="T",
            topic_summary="S",
            scope_in=[],
            scope_out=[],
            anchor_refs=[],
            messages=[
                {"source_ref": "tg:1:post:1", "text_clean": "z" * 400, "summary": ""},
            ],
        )
        assert "..." in prompt
        assert len(prompt) < 800

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
    def test_returns_non_empty_string(self):
        prompt = build_incremental_discover_prompt([], [])
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_includes_expected_instruction_markers(self):
        existing = [{"id": "id1", "title": "T", "scope_in": ["s"]}]
        docs = [{"source_ref": "r1", "summary": "S", "topics": [], "text_clean": "x"}]
        prompt = build_incremental_discover_prompt(existing, docs)
        assert "existing topics in this channel" in prompt
        assert "assignments, new_topics, and unassignable" in prompt
        assert "NOT matched to any topic by keyword" in prompt

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
        assert len(prompt) > 0

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
        assert len(prompt) > 0

    def test_no_cross_channel_topics(self):
        existing = [{"id": "t1", "title": "Topic", "scope_in": []}]
        docs = [{"source_ref": "ref:1", "summary": "Doc", "topics": [], "text_clean": "Text"}]

        prompt = build_incremental_discover_prompt(existing, docs, cross_channel_topics=None)

        assert "Topics from OTHER channels" not in prompt

    def test_doc_missing_text_clean_uses_empty_preview(self):
        existing = []
        docs = [{"source_ref": "ref:minimal", "summary": "Only summary", "topics": ["a"]}]
        prompt = build_incremental_discover_prompt(existing, docs)
        assert "ref:minimal" in prompt
        assert "Only summary" in prompt
        assert len(prompt) > 0

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
        assert name == "topicization_v1"

    def test_supporting_items_prompt_name(self):
        name = get_supporting_items_prompt_name()
        assert isinstance(name, str)
        assert len(name) > 0
        assert name == "supporting_items_v1"

    def test_incremental_discover_prompt_name(self):
        name = get_incremental_discover_prompt_name()
        assert isinstance(name, str)
        assert len(name) > 0
        assert name == "incremental_discover_v1"


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
