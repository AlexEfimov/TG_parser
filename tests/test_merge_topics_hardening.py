"""S6 regression tests for deterministic merge-LLM post-processing."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from tg_parser.processing.topicization import TopicizationPipelineImpl


def _topic(index: int, anchor_count: int = 1) -> dict:
    return {
        "title": f"Topic {index}",
        "summary": f"Summary {index}",
        "type": "singleton",
        "scope_in": [f"in-{index}"],
        "scope_out": [f"out-{index}"],
        "anchors": [
            {"source_ref": f"tg:test:post:{index}-{anchor}", "score": 0.9}
            for anchor in range(anchor_count)
        ],
    }


def _pipeline(groups: list) -> TopicizationPipelineImpl:
    response = MagicMock()
    response.text = __import__("json").dumps({"groups": groups})
    response.input_tokens = 5
    response.output_tokens = 3
    response.stop_reason = "stop"

    llm = AsyncMock()
    llm.model = "test-model"
    llm.compute_prompt_id = MagicMock(return_value="test-prompt-id")
    llm.generate_with_usage = AsyncMock(return_value=response)
    return TopicizationPipelineImpl(
        llm_client=llm,
        processed_doc_repo=AsyncMock(),
        topic_card_repo=AsyncMock(),
        topic_bundle_repo=AsyncMock(),
    )


async def _merge(groups: list, topics: list[dict]) -> list[dict]:
    return await _pipeline(groups)._merge_topics(topics, candidates=[])


@pytest.mark.asyncio
async def test_primary_is_member_with_most_anchors_and_anchors_stay_deduped():
    topics = [_topic(0, 1), _topic(1, 1), _topic(2, 3)]
    duplicate_anchor = topics[0]["anchors"][0]
    topics[2]["anchors"].append(duplicate_anchor)

    merged = await _merge([[0, 2], [1]], topics)

    assert merged[0]["title"] == "Topic 2"
    assert merged[0]["summary"] == "Summary 2"
    assert merged[0]["scope_in"] == ["in-2"]
    assert [anchor["source_ref"] for anchor in merged[0]["anchors"]] == [
        "tg:test:post:0-0",
        "tg:test:post:2-0",
        "tg:test:post:2-1",
        "tg:test:post:2-2",
    ]


@pytest.mark.asyncio
async def test_primary_anchor_count_tie_uses_first_group_member():
    merged = await _merge([[2, 0], [1]], [_topic(index) for index in range(3)])

    assert merged[0]["title"] == "Topic 2"


@pytest.mark.asyncio
async def test_unmentioned_topics_are_emitted_as_singletons():
    merged = await _merge([[0, 1]], [_topic(index) for index in range(4)])

    assert len(merged) == 3
    assert [topic["title"] for topic in merged] == ["Topic 0", "Topic 2", "Topic 3"]


@pytest.mark.asyncio
async def test_numeric_string_ids_are_coerced():
    merged = await _merge([["0", "1"]], [_topic(0), _topic(1)])

    assert len(merged) == 1
    assert {anchor["source_ref"] for anchor in merged[0]["anchors"]} == {
        "tg:test:post:0-0",
        "tg:test:post:1-0",
    }


@pytest.mark.asyncio
async def test_non_numeric_string_ids_are_skipped_and_all_topics_preserved():
    merged = await _merge([["a", "b"]], [_topic(0), _topic(1)])

    assert [topic["title"] for topic in merged] == ["Topic 0", "Topic 1"]


@pytest.mark.asyncio
async def test_invalid_member_is_skipped_without_discarding_valid_group_members():
    merged = await _merge([[0, "bad", 1]], [_topic(0), _topic(1), _topic(2)])

    assert len(merged) == 2
    assert [anchor["source_ref"] for anchor in merged[0]["anchors"]] == [
        "tg:test:post:0-0",
        "tg:test:post:1-0",
    ]
    assert merged[1]["title"] == "Topic 2"


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_id", [True, 1.9])
async def test_non_integer_json_values_do_not_claim_topic_ids(invalid_id):
    merged = await _merge([[invalid_id]], [_topic(0), _topic(1)])

    assert [topic["title"] for topic in merged] == ["Topic 0", "Topic 1"]


@pytest.mark.asyncio
async def test_duplicate_id_across_groups_is_owned_by_first_group():
    merged = await _merge([[0, 1], [1, 2]], [_topic(index) for index in range(3)])

    assert len(merged) == 2
    assert [anchor["source_ref"] for anchor in merged[0]["anchors"]] == [
        "tg:test:post:0-0",
        "tg:test:post:1-0",
    ]
    assert [anchor["source_ref"] for anchor in merged[1]["anchors"]] == ["tg:test:post:2-0"]


@pytest.mark.asyncio
async def test_out_of_range_id_is_skipped_without_losing_orphans():
    merged = await _merge([[0, 99]], [_topic(0), _topic(1)])

    assert [topic["title"] for topic in merged] == ["Topic 0", "Topic 1"]


@pytest.mark.asyncio
async def test_all_invalid_group_is_skipped_and_orphans_are_preserved():
    merged = await _merge([[99, 100]], [_topic(0), _topic(1)])

    assert [topic["title"] for topic in merged] == ["Topic 0", "Topic 1"]


@pytest.mark.asyncio
async def test_dict_shaped_group_uses_member_ids():
    merged = await _merge(
        [{"member_ids": [0, 1]}],
        [_topic(0), _topic(1)],
    )

    assert len(merged) == 1
    assert len(merged[0]["anchors"]) == 2


@pytest.mark.asyncio
async def test_dict_shaped_group_rejects_non_list_member_container():
    with pytest.raises(TypeError, match="member_ids must be a list"):
        await _merge([{"member_ids": "01"}], [_topic(0), _topic(1)])
