"""Session F (2026-04-29) regression tests — read-tool hardening batch.

Covers:

* **BUG-003** — read-tool executors normalize ``@`` prefix, surrounding
  quotes, and whitespace through ``normalize_channel_id``.
* **BUG-007** — read-tools that returned ``total=0`` for a specific
  channel emit ``available_channel_ids`` and an optional
  ``suggestion`` (RBAC-aware, difflib-based).
* **BUG-005-B** — ``execute_tool`` preserves the exception class and
  truncated message instead of collapsing to a generic
  ``"internal error"``.
* **F-9 production scenarios** — the four input variants observed
  on 2026-04-29 (`@ch`, `ch`, `'ch'`, `"@ch"`) reach storage with
  identical normalised ``channel_id``.

See ``docs/notes/START_PROMPT_FIX_READ_HARDENING_BUG003_005B_007_2026-04-29.md``
§ 3.5 for the full scope.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tg_parser.auth.models import CurrentUser
from tg_parser.bot.tools import (
    _build_no_results_suggestion,
    _exec_add_channel,
    _exec_ask_question,
    _exec_get_cross_channel_stats,
    _exec_list_topics,
    _exec_pause_channel,
    _exec_remove_channel,
    _exec_search,
    execute_tool,
)
from tg_parser.services.retrieval_service import AnswerResult, SearchResult
from tg_parser.storage.ports import Source

NOW = datetime(2026, 4, 29, 16, 11, 0, tzinfo=UTC)

ADMIN_USER = CurrentUser(
    id="admin",
    name="admin",
    role="admin",
    allowed_channel_ids=None,
    max_channels=100,
)


def _make_source(channel_id: str) -> Source:
    return Source(
        source_id=channel_id,
        channel_id=channel_id,
        status="active",
        include_comments=False,
        channel_username=None,
        created_at=NOW,
    )


def _mock_ingestion_state_repo(*, sources: list[Source] | None = None):
    state_repo = AsyncMock()
    db = MagicMock()
    state_repo.list_sources.return_value = sources or []
    state_repo.get_source.return_value = None
    state_repo.delete_source.return_value = True

    @asynccontextmanager
    async def mock_ctx():
        yield (state_repo, db)

    return mock_ctx, state_repo


# ---------------------------------------------------------------------------
# BUG-003 — @ + quotes normalization across read-tools
# ---------------------------------------------------------------------------


class TestBug003ReadToolNormalization:
    @pytest.mark.parametrize(
        "raw_input",
        [
            "Lab4health",
            "@Lab4health",
            "'Lab4health'",
            '"Lab4health"',
            "  @Lab4health  ",
            "'@Lab4health'",
        ],
    )
    async def test_list_topics_normalizes_to_canonical(self, raw_input):
        """All channel-id variants must resolve to the canonical form before
        storage is consulted (BUG-003 root cause asymmetry)."""
        topic_card_repo = AsyncMock()
        topic_card_repo.list_by_channel.return_value = []
        topic_card_repo.list_by_channels.return_value = []
        topic_card_repo.list_all.return_value = []
        topic_bundle_repo = AsyncMock()
        topic_bundle_repo.list_by_channel.return_value = []
        topic_bundle_repo.list_all.return_value = []
        proc_repo = AsyncMock()
        db = MagicMock()

        @asynccontextmanager
        async def mock_proc_ctx():
            yield (proc_repo, topic_card_repo, topic_bundle_repo, db)

        # Suggestion lookup runs because total=0; mock empty sources to
        # keep the assertion focused on the normalised channel_id call.
        ingest_ctx, _ = _mock_ingestion_state_repo()

        with (
            patch("tg_parser.services.db_context.processing_repos", mock_proc_ctx),
            patch("tg_parser.services.db_context.ingestion_state_repo", ingest_ctx),
        ):
            await _exec_list_topics(
                {"channel_id": raw_input},
                current_user=ADMIN_USER,
            )

        topic_card_repo.list_by_channel.assert_awaited_once_with("Lab4health")
        topic_bundle_repo.list_by_channel.assert_awaited_once_with("Lab4health")

    async def test_search_normalizes_at_prefix(self):
        ingest_ctx, _ = _mock_ingestion_state_repo()

        called_with: dict = {}

        async def fake_search(*, query, channel_id, limit, allowed_channel_ids):
            called_with["channel_id"] = channel_id
            return []

        with (
            patch("tg_parser.services.retrieval_service.search", fake_search),
            patch("tg_parser.services.db_context.ingestion_state_repo", ingest_ctx),
        ):
            await _exec_search(
                {"query": "test", "channel_id": "@Lab4health"},
                current_user=ADMIN_USER,
            )

        assert called_with["channel_id"] == "Lab4health"

    async def test_get_cross_channel_stats_normalizes(self):
        called_with: dict = {}

        async def fake_analytics(*, channel_id, allowed_channel_ids):
            called_with["channel_id"] = channel_id
            return {"channel_id": channel_id, "processed_documents": 5}

        with patch(
            "tg_parser.services.analytics_service.get_cross_channel_analytics",
            fake_analytics,
        ):
            await _exec_get_cross_channel_stats(
                {"channel_id": "'@Lab4health'"},
                current_user=ADMIN_USER,
            )

        assert called_with["channel_id"] == "Lab4health"

    @pytest.mark.parametrize(
        "raw_input",
        [
            "@AgeManagement",
            "AgeManagement",
            "'AgeManagement'",
            '"@AgeManagement"',
            "  @AgeManagement  ",
        ],
    )
    async def test_ask_question_normalizes_to_canonical(self, raw_input):
        """The ORIGINAL BUG-003 production symptom: «Каковы основные темы канала
        @AgeManagement?» — Gemini agent passed the literal `@AgeManagement` to
        ``ask_question`` and storage replied with empty sources because the DB
        key is stored without ``@``. After normalize the call site receives the
        canonical form regardless of input variant.
        """
        called_with: dict = {}

        async def fake_answer(*, question, channel_id, allowed_channel_ids):
            called_with["channel_id"] = channel_id
            return AnswerResult(answer="…", sources=[], model=None)

        with patch("tg_parser.services.retrieval_service.answer", fake_answer):
            await _exec_ask_question(
                {"question": "топ темы?", "channel_id": raw_input},
                current_user=ADMIN_USER,
            )

        assert called_with["channel_id"] == "AgeManagement", (
            f"input {raw_input!r} reached storage as "
            f"{called_with.get('channel_id')!r}, expected 'AgeManagement'"
        )


# ---------------------------------------------------------------------------
# F-9 production regression — 4 input variants for `test_channel`
# ---------------------------------------------------------------------------


class TestF9ProductionScenarios:
    """All four input variants observed on the 2026-04-29 production smoke
    must reach storage with the same canonical ``channel_id="test_channel"``.

    Source: BUG_LOG.md § BUG-006 Update «Production deploy», Session F § 0.
    """

    @pytest.mark.parametrize(
        "raw_input",
        [
            "@test_channel",
            "test_channel",
            "'test_channel'",
            '"@test_channel"',
        ],
    )
    async def test_remove_channel_collapses_input_variants(self, raw_input):
        ingest_ctx, state_repo = _mock_ingestion_state_repo()
        # _exec_remove_channel needs ownership check + repo lookup + soft-delete.
        # We do not exercise the full removal repo machinery; the assertion
        # is on assert_channel_access receiving the *canonical* ID.

        captured: dict = {}

        async def fake_assert_access(user, normalized):
            captured["normalized"] = normalized
            return None

        with (
            patch("tg_parser.auth.ownership.assert_channel_access", fake_assert_access),
            patch("tg_parser.services.db_context.ingestion_state_repo", ingest_ctx),
        ):
            # `confirm=False` — preview path, no destructive call needed.
            await _exec_remove_channel(
                {"channel_id": raw_input, "confirm": False},
                current_user=ADMIN_USER,
            )

        assert captured["normalized"] == "test_channel", (
            f"input {raw_input!r} reached storage as "
            f"{captured.get('normalized')!r}, expected 'test_channel'"
        )

    @pytest.mark.parametrize(
        "raw_input",
        [
            "@test_channel",
            "test_channel",
            "'test_channel'",
            '"@test_channel"',
        ],
    )
    async def test_pause_channel_collapses_input_variants(self, raw_input):
        """F-9 defense-in-depth: pause_channel must echo the canonical ID in
        the preview payload across all four input variants — otherwise the
        confirm-step would persist whatever wrapping the LLM hallucinated."""
        ingest_ctx, _state_repo = _mock_ingestion_state_repo()  # get_source -> None

        with patch("tg_parser.services.db_context.ingestion_state_repo", ingest_ctx):
            payload = await _exec_pause_channel(
                {"channel_id": raw_input, "confirm": False},
                current_user=ADMIN_USER,
            )

        assert payload.get("channel_id") == "test_channel"

    @pytest.mark.parametrize(
        "raw_input",
        [
            "@new_channel",
            "new_channel",
            "'new_channel'",
            '"@new_channel"',
        ],
    )
    async def test_add_channel_preview_collapses_input_variants(self, raw_input):
        """F-9 + F-8: add_channel preview must echo a canonical channel_id
        regardless of input variant — otherwise the LLM may show the user a
        confirmation dialog with the literal `'new_channel'` (quoted) and
        the subsequent confirm=true path would store the same quoted form.
        Preview path does not mutate state, so we run it as-is."""
        ingest_ctx, state_repo = _mock_ingestion_state_repo()

        with patch("tg_parser.services.db_context.ingestion_state_repo", ingest_ctx):
            payload = await _exec_add_channel(
                {"channel_id": raw_input, "confirm": False},
                current_user=ADMIN_USER,
            )

        assert payload.get("channel_id") == "new_channel", (
            f"input {raw_input!r} reached preview as "
            f"{payload.get('channel_id')!r}, expected 'new_channel'"
        )


# ---------------------------------------------------------------------------
# BUG-007 — suggestion-emit on total=0
# ---------------------------------------------------------------------------


class TestBug007SuggestionPayload:
    async def test_suggestion_proposes_close_match(self):
        ingest_ctx, _ = _mock_ingestion_state_repo(
            sources=[_make_source("AgeManagment"), _make_source("Lab4health")]
        )
        with patch("tg_parser.services.db_context.ingestion_state_repo", ingest_ctx):
            payload = await _build_no_results_suggestion("AgeManagement", ADMIN_USER)

        assert payload["available_channel_ids"] == ["AgeManagment", "Lab4health"]
        assert payload["suggestion"] is not None
        assert "AgeManagment" in payload["suggestion"]
        assert "AgeManagement" in payload["suggestion"]

    async def test_suggestion_skips_far_input(self):
        ingest_ctx, _ = _mock_ingestion_state_repo(
            sources=[_make_source("Lab4health"), _make_source("AgeManagment")]
        )
        with patch("tg_parser.services.db_context.ingestion_state_repo", ingest_ctx):
            payload = await _build_no_results_suggestion("xyz_unknown", ADMIN_USER)

        assert payload["suggestion"] is None
        assert payload["available_channel_ids"] == ["Lab4health", "AgeManagment"]

    async def test_suggestion_filters_by_user_allowed_channel_ids(self):
        non_admin = CurrentUser(
            id="user-1",
            name="alice",
            role="user",
            allowed_channel_ids=["Lab4health"],
            max_channels=5,
        )
        ingest_ctx, _ = _mock_ingestion_state_repo(
            sources=[
                _make_source("Lab4health"),
                _make_source("AgeManagment"),
                _make_source("PrivateOps"),
            ]
        )
        with patch("tg_parser.services.db_context.ingestion_state_repo", ingest_ctx):
            payload = await _build_no_results_suggestion("Lab4health2", non_admin)

        # RBAC: only the user's allowed channel must surface in the
        # suggestion list, even though three sources exist.
        assert payload["available_channel_ids"] == ["Lab4health"]

    async def test_suggestion_caps_at_ten(self):
        ingest_ctx, _ = _mock_ingestion_state_repo(
            sources=[_make_source(f"ch_{i}") for i in range(25)]
        )
        with patch("tg_parser.services.db_context.ingestion_state_repo", ingest_ctx):
            payload = await _build_no_results_suggestion("zzz", ADMIN_USER)

        assert len(payload["available_channel_ids"]) == 10

    async def test_suggestion_no_match_when_input_is_exact(self):
        ingest_ctx, _ = _mock_ingestion_state_repo(sources=[_make_source("Lab4health")])
        with patch("tg_parser.services.db_context.ingestion_state_repo", ingest_ctx):
            payload = await _build_no_results_suggestion("Lab4health", ADMIN_USER)

        # `Lab4health` IS in the available list — but the user already
        # asked for it (total=0 came from a different filter, e.g.
        # topic_type), so we don't propose it as a "did you mean".
        assert payload["suggestion"] is None

    async def test_list_topics_appends_suggestion_on_empty(self):
        topic_card_repo = AsyncMock()
        topic_card_repo.list_by_channel.return_value = []
        topic_bundle_repo = AsyncMock()
        topic_bundle_repo.list_by_channel.return_value = []
        proc_repo = AsyncMock()
        db = MagicMock()

        @asynccontextmanager
        async def mock_proc_ctx():
            yield (proc_repo, topic_card_repo, topic_bundle_repo, db)

        ingest_ctx, _ = _mock_ingestion_state_repo(sources=[_make_source("AgeManagment")])

        with (
            patch("tg_parser.services.db_context.processing_repos", mock_proc_ctx),
            patch("tg_parser.services.db_context.ingestion_state_repo", ingest_ctx),
        ):
            payload = await _exec_list_topics(
                {"channel_id": "AgeManagement"},
                current_user=ADMIN_USER,
            )

        assert payload["total"] == 0
        assert payload["available_channel_ids"] == ["AgeManagment"]
        assert payload["suggestion"] is not None
        assert "AgeManagment" in payload["suggestion"]

    async def test_list_topics_no_suggestion_when_total_nonzero(self):
        from tg_parser.domain.models import (
            Anchor,
            MessageType,
            TopicCard,
            TopicType,
        )

        card = TopicCard(
            id="t1",
            title="T1",
            summary="s",
            scope_in=["i"],
            scope_out=["o"],
            type=TopicType.SINGLETON,
            anchors=[
                Anchor(
                    channel_id="ch",
                    message_id="1",
                    message_type=MessageType.POST,
                    anchor_ref="tg:ch:post:1",
                    score=1.0,
                )
            ],
            sources=["ch"],
            updated_at=NOW,
        )
        topic_card_repo = AsyncMock()
        topic_card_repo.list_by_channel.return_value = [card]
        topic_bundle_repo = AsyncMock()
        topic_bundle_repo.list_by_channel.return_value = []
        proc_repo = AsyncMock()
        db = MagicMock()

        @asynccontextmanager
        async def mock_proc_ctx():
            yield (proc_repo, topic_card_repo, topic_bundle_repo, db)

        with patch("tg_parser.services.db_context.processing_repos", mock_proc_ctx):
            payload = await _exec_list_topics(
                {"channel_id": "ch"},
                current_user=ADMIN_USER,
            )

        assert payload["total"] == 1
        # Optional fields must NOT leak into a successful response.
        assert "available_channel_ids" not in payload
        assert "suggestion" not in payload

    async def test_search_appends_suggestion_on_empty(self):
        async def fake_search(*, query, channel_id, limit, allowed_channel_ids):
            return []

        ingest_ctx, _ = _mock_ingestion_state_repo(sources=[_make_source("Lab4health")])

        with (
            patch("tg_parser.services.retrieval_service.search", fake_search),
            patch("tg_parser.services.db_context.ingestion_state_repo", ingest_ctx),
        ):
            payload = await _exec_search(
                {"query": "x", "channel_id": "Lab5health"},
                current_user=ADMIN_USER,
            )

        assert payload["count"] == 0
        assert payload["available_channel_ids"] == ["Lab4health"]
        assert payload["suggestion"] is not None

    async def test_suggestion_swallows_db_errors(self):
        """Contract: ``_build_no_results_suggestion`` is an advisory path —
        if storage is unavailable for the diagnostic lookup, the user-facing
        ``total=0`` answer must NOT be replaced by an error. The helper must
        return an empty dict so the caller's primary payload survives.
        Source: BUG-007 § Resolution «Errors swallowed (advisory path)»."""

        @asynccontextmanager
        async def failing_ctx():
            raise RuntimeError("simulated storage outage")
            yield  # unreachable, satisfies the type checker

        with patch("tg_parser.services.db_context.ingestion_state_repo", failing_ctx):
            payload = await _build_no_results_suggestion("anything", ADMIN_USER)

        assert payload == {}, (
            "advisory path leaked an exception or a non-empty payload "
            "instead of swallowing the storage error"
        )

    async def test_list_topics_survives_suggestion_helper_error(self):
        """End-to-end version of the swallowing contract: even if the
        suggestion helper itself blows up internally, ``_exec_list_topics``
        must still return the canonical empty-result payload (``total=0``),
        without leaking ``available_channel_ids`` / ``suggestion`` keys."""
        topic_card_repo = AsyncMock()
        topic_card_repo.list_by_channel.return_value = []
        topic_bundle_repo = AsyncMock()
        topic_bundle_repo.list_by_channel.return_value = []
        proc_repo = AsyncMock()
        db = MagicMock()

        @asynccontextmanager
        async def mock_proc_ctx():
            yield (proc_repo, topic_card_repo, topic_bundle_repo, db)

        @asynccontextmanager
        async def failing_ingest_ctx():
            raise RuntimeError("storage outage during suggestion lookup")
            yield  # unreachable

        with (
            patch("tg_parser.services.db_context.processing_repos", mock_proc_ctx),
            patch(
                "tg_parser.services.db_context.ingestion_state_repo",
                failing_ingest_ctx,
            ),
        ):
            payload = await _exec_list_topics(
                {"channel_id": "anything"},
                current_user=ADMIN_USER,
            )

        assert payload["total"] == 0
        assert payload.get("items") == []
        assert payload["has_more"] is False
        # Helper failed → no advisory keys leak into the response.
        assert "available_channel_ids" not in payload
        assert "suggestion" not in payload

    async def test_suggestion_with_empty_db(self):
        """No sources at all → ``available_channel_ids`` is empty list and
        ``suggestion`` is None. Distinct from "DB error" path — the helper
        succeeds but returns nothing usable."""
        ingest_ctx, _ = _mock_ingestion_state_repo(sources=[])
        with patch("tg_parser.services.db_context.ingestion_state_repo", ingest_ctx):
            payload = await _build_no_results_suggestion("anything", ADMIN_USER)

        assert payload["available_channel_ids"] == []
        assert payload["suggestion"] is None


# ---------------------------------------------------------------------------
# BUG-005-B — typed catches in execute_tool
# ---------------------------------------------------------------------------


class TestBug005BTypedCatch:
    async def test_value_error_preserved(self):
        async def fake_executor(args, **_):
            raise ValueError("invalid arg X")

        with patch.dict(
            "tg_parser.bot.tools._TOOL_EXECUTORS",
            {"fake_tool": fake_executor},
            clear=False,
        ):
            result = await execute_tool(
                "fake_tool",
                {},
                current_user=ADMIN_USER,
            )

        assert result["error_class"] == "ValueError"
        assert result["error"] == "invalid arg X"

    async def test_key_error_preserved(self):
        async def fake_executor(args, **_):
            raise KeyError("missing_key")

        with patch.dict(
            "tg_parser.bot.tools._TOOL_EXECUTORS",
            {"fake_tool_k": fake_executor},
            clear=False,
        ):
            result = await execute_tool(
                "fake_tool_k",
                {},
                current_user=ADMIN_USER,
            )

        assert result["error_class"] == "KeyError"
        assert "missing_key" in result["error"]

    async def test_permission_error_preserved(self):
        async def fake_executor(args, **_):
            raise PermissionError("admin only")

        with patch.dict(
            "tg_parser.bot.tools._TOOL_EXECUTORS",
            {"fake_tool_p": fake_executor},
            clear=False,
        ):
            result = await execute_tool(
                "fake_tool_p",
                {},
                current_user=ADMIN_USER,
            )

        assert result["error_class"] == "PermissionError"
        assert result["error"] == "admin only"

    async def test_billing_error_preserved_as_regression_for_bug_005_a(self):
        """The original BUG-005-A symptom: Anthropic gateway returned
        HTTP-402 ("Your credit balance is too low...") and the generic
        catch reduced it to "internal error". With typed catch the
        message is preserved verbatim so the LLM can recover with a
        meaningful user-facing answer."""

        anthropic_message = (
            "Your credit balance is too low to access the Anthropic API. "
            "Please go to Plans & Billing to upgrade or purchase credits."
        )

        async def fake_executor(args, **_):
            raise RuntimeError(anthropic_message)

        with patch.dict(
            "tg_parser.bot.tools._TOOL_EXECUTORS",
            {"fake_tool_b": fake_executor},
            clear=False,
        ):
            result = await execute_tool(
                "fake_tool_b",
                {},
                current_user=ADMIN_USER,
            )

        assert result["error_class"] == "RuntimeError"
        assert anthropic_message in result["error"]

    async def test_long_exception_message_truncated_to_500(self):
        async def fake_executor(args, **_):
            raise RuntimeError("a" * 1000)

        with patch.dict(
            "tg_parser.bot.tools._TOOL_EXECUTORS",
            {"fake_tool_long": fake_executor},
            clear=False,
        ):
            result = await execute_tool(
                "fake_tool_long",
                {},
                current_user=ADMIN_USER,
            )

        assert len(result["error"]) <= 500
        assert result["error_class"] == "RuntimeError"

    async def test_timeout_returns_typed_class(self):
        import asyncio

        async def fake_executor(args, **_):
            await asyncio.sleep(2.0)
            return {"ok": True}

        with patch.dict(
            "tg_parser.bot.tools._TOOL_EXECUTORS",
            {"fake_tool_t": fake_executor},
            clear=False,
        ):
            result = await execute_tool(
                "fake_tool_t",
                {},
                timeout=0.05,
                current_user=ADMIN_USER,
            )

        assert result["error_class"] == "TimeoutError"
        assert "timed out" in result["error"]

    async def test_unknown_tool_returns_typed_class(self):
        result = await execute_tool(
            "definitely_not_a_real_tool",
            {},
            current_user=ADMIN_USER,
        )

        assert result["error_class"] == "UnknownTool"
        assert "Unknown tool" in result["error"]

    async def test_happy_path_does_not_inject_error_class(self):
        """Critical contract: a successful executor's return value must reach
        the caller verbatim — no ``error`` / ``error_class`` keys may be
        injected. Otherwise downstream LLM logic could mistake a healthy
        response for an error-recovery branch."""

        async def fake_executor(args, **_):
            return {"ok": True, "result": [1, 2, 3]}

        with patch.dict(
            "tg_parser.bot.tools._TOOL_EXECUTORS",
            {"happy_tool": fake_executor},
            clear=False,
        ):
            result = await execute_tool(
                "happy_tool",
                {},
                current_user=ADMIN_USER,
            )

        assert result == {"ok": True, "result": [1, 2, 3]}
        assert "error_class" not in result
        assert "error" not in result

    async def test_value_error_with_empty_message_falls_back(self):
        """``ValueError()`` with no message — the typed catch must still
        surface a useful ``error`` string instead of an empty one, otherwise
        the LLM has no hint to act on."""

        async def fake_executor(args, **_):
            raise ValueError()

        with patch.dict(
            "tg_parser.bot.tools._TOOL_EXECUTORS",
            {"empty_value_tool": fake_executor},
            clear=False,
        ):
            result = await execute_tool(
                "empty_value_tool",
                {},
                current_user=ADMIN_USER,
            )

        assert result["error_class"] == "ValueError"
        # `error` must not be empty / None — implementation guarantees a
        # human-readable fallback message naming the tool.
        assert result.get("error")
        assert isinstance(result["error"], str)

    async def test_unrelated_runtime_error_uses_generic_catch(self):
        """``RuntimeError`` is not in the typed-catch allow-list, so it must
        fall through to the generic ``except Exception`` branch with
        ``error_class="RuntimeError"`` (not collapsed to a generic label)."""

        async def fake_executor(args, **_):
            raise RuntimeError("network timeout to upstream RAG")

        with patch.dict(
            "tg_parser.bot.tools._TOOL_EXECUTORS",
            {"runtime_tool": fake_executor},
            clear=False,
        ):
            result = await execute_tool(
                "runtime_tool",
                {},
                current_user=ADMIN_USER,
            )

        assert result["error_class"] == "RuntimeError"
        assert "network timeout" in result["error"]


# ---------------------------------------------------------------------------
# Test that _exec_search payload still matches the documented shape
# ---------------------------------------------------------------------------


class TestSearchPayloadShape:
    async def test_search_with_results_does_not_emit_suggestion(self):
        from tg_parser.domain.models import ProcessedDocument

        doc = ProcessedDocument(
            id="d1",
            source_ref="tg:ch:post:1",
            source_message_id="1",
            channel_id="ch",
            processed_at=NOW,
            text_clean="hello",
            summary=None,
            topics=[],
        )

        async def fake_search(*, query, channel_id, limit, allowed_channel_ids):
            return [SearchResult(source_ref=doc.source_ref, score=0.9, document=doc)]

        with patch("tg_parser.services.retrieval_service.search", fake_search):
            payload = await _exec_search(
                {"query": "x", "channel_id": "ch"},
                current_user=ADMIN_USER,
            )

        assert payload["count"] == 1
        assert "suggestion" not in payload
        assert "available_channel_ids" not in payload
