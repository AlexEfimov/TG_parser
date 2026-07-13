"""
BUG-084 — embedding ``429`` classify-by-``error.code`` + RAG keyword-fallback + metric.

The embedding client (:class:`OpenAIEmbeddingClient.embed`) historically had NO
retry/backoff — ``raise_for_status()`` surfaced a raw ``429`` and both consumers
(background topic/incremental embedding + the live semantic/hybrid RAG query path)
hard-failed. BUG-084 makes ``429`` a classified, two-class outcome:

- transient ``rate_limit_exceeded`` (+ ``{500,502,503,529}``) → jittered backoff
  honoring ``Retry-After`` → ``x-ratelimit-reset-*``; on exhaustion a typed
  :class:`EmbeddingRateLimitError` is raised;
- terminal ``insufficient_quota`` → an IMMEDIATE typed :class:`EmbeddingQuotaError`
  with NO retry (a billing/tier state — retrying only burns latency/attempts).

The user-facing RAG query path uses a SMALL retry budget (differentiated design,
Q1) and, on EITHER error class, degrades semantic/hybrid → keyword and exposes
``degraded=True`` (Q2). A distinct metric ``tg_embedding_requests_total{outcome,
stage}`` is classified at the two consumer call sites (background_scheduler +
retrieval_service), never conflated with DB-pool/LLM errors.

All cases run in *default* mode (mocked ``httpx`` client / injected mock repos,
no Postgres).
"""

import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from tg_parser.api.metrics import EMBEDDING_REQUESTS_TOTAL
from tg_parser.config.settings import Settings
from tg_parser.domain.ids import make_source_ref
from tg_parser.domain.models import ProcessedDocument
from tg_parser.services.embedding_service import (
    EmbeddingQuotaError,
    EmbeddingRateLimitError,
    OpenAIEmbeddingClient,
    reset_embedding_client_cache,
)

# ── Fakes ──────────────────────────────────────────────────────────────────

_SUCCESS_BODY = {"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]}
_RATE_LIMIT_BODY = {"error": {"code": "rate_limit_exceeded", "type": "requests"}}
_QUOTA_BODY = {
    "error": {
        "code": "insufficient_quota",
        "type": "insufficient_quota",
        "message": "You exceeded your current quota",
    }
}


class _FakeResponse:
    """Minimal stand-in for ``httpx.Response`` (status/headers/json/raise)."""

    def __init__(
        self,
        status_code: int,
        *,
        body: dict | None = None,
        headers: dict | None = None,
        raise_on_json: bool = False,
    ):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.headers = headers or {}
        self._raise_on_json = raise_on_json

    def json(self) -> dict:
        if self._raise_on_json:
            raise ValueError("not JSON")
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", "http://test/embeddings")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("error", request=request, response=response)


class _FakeHTTPClient:
    """Async client returning a scripted sequence of responses; counts calls."""

    def __init__(self, responses: list):
        self._responses = list(responses)
        self.post_calls = 0

    async def post(self, url, json=None):
        self.post_calls += 1
        idx = min(self.post_calls - 1, len(self._responses) - 1)
        resp = self._responses[idx]
        if isinstance(resp, Exception):
            raise resp
        return resp

    async def aclose(self) -> None:  # pragma: no cover - close is a no-op here
        pass


def _client_with(responses: list, **kwargs) -> OpenAIEmbeddingClient:
    """Build an embedding client whose HTTP layer is the scripted fake."""
    c = OpenAIEmbeddingClient(api_key="sk-test", **kwargs)
    c._client = _FakeHTTPClient(responses)  # noqa: SLF001 — inject fake transport
    return c


def _mock_repos() -> tuple[AsyncMock, AsyncMock]:
    emb_repo = AsyncMock()
    emb_repo.similarity_search = AsyncMock(return_value=[])
    emb_repo.keyword_search = AsyncMock(return_value=[])
    proc_repo = AsyncMock()
    proc_repo.get_by_source_refs = AsyncMock(return_value={})
    return emb_repo, proc_repo


def _metric(outcome: str, stage: str) -> float:
    return EMBEDDING_REQUESTS_TOTAL.labels(outcome=outcome, stage=stage)._value.get()  # noqa: SLF001


@pytest.fixture(autouse=True)
def _clean_cache():
    reset_embedding_client_cache()
    yield
    reset_embedding_client_cache()


# ── embed() retry + classification ───────────────────────────────────────────


class TestEmbedRetryClassification:
    async def test_transient_rate_limit_then_success_returns_vector(self):
        """Transient ``rate_limit_exceeded`` then ``200`` → vector; Retry-After honored."""
        client = _client_with(
            [
                _FakeResponse(429, body=_RATE_LIMIT_BODY, headers={"retry-after": "3"}),
                _FakeResponse(200, body=_SUCCESS_BODY),
            ],
            max_retries=5,
        )

        with patch("asyncio.sleep", new=AsyncMock()) as sleep:
            result = await client.embed(["q"])

        assert result == [[0.1, 0.2, 0.3]]
        assert client._client.post_calls == 2  # noqa: SLF001
        # Retry-After (3s) was honored for the single backoff.
        sleep.assert_awaited_once()
        assert sleep.await_args.args[0] == pytest.approx(3.0)

    async def test_5xx_retryable_then_success(self):
        """A retryable ``503`` then ``200`` → vector (5xx is in the transient set)."""
        client = _client_with(
            [_FakeResponse(503), _FakeResponse(200, body=_SUCCESS_BODY)],
            max_retries=5,
        )
        with patch("asyncio.sleep", new=AsyncMock()):
            result = await client.embed(["q"])
        assert result == [[0.1, 0.2, 0.3]]
        assert client._client.post_calls == 2  # noqa: SLF001

    async def test_transient_exhausted_raises_rate_limit_error(self):
        """Persistent transient ``429`` → EmbeddingRateLimitError after full budget."""
        client = _client_with(
            [_FakeResponse(429, body=_RATE_LIMIT_BODY)] * 6,
            max_retries=3,
        )
        with patch("asyncio.sleep", new=AsyncMock()):
            with pytest.raises(EmbeddingRateLimitError):
                await client.embed(["q"])
        assert client._client.post_calls == 3  # noqa: SLF001 — exactly max_retries attempts

    async def test_terminal_quota_no_retry_single_http_call(self):
        """``insufficient_quota`` → IMMEDIATE EmbeddingQuotaError, EXACTLY 1 HTTP call."""
        client = _client_with(
            [_FakeResponse(429, body=_QUOTA_BODY)] * 6,
            max_retries=5,
        )
        with patch("asyncio.sleep", new=AsyncMock()) as sleep:
            with pytest.raises(EmbeddingQuotaError):
                await client.embed(["q"])
        assert client._client.post_calls == 1  # noqa: SLF001 — NO retry on terminal quota
        sleep.assert_not_awaited()

    async def test_differentiated_small_budget_limits_attempts(self):
        """A small ``max_retries`` budget bounds the transient attempts (Q1)."""
        client = _client_with(
            [_FakeResponse(429, body=_RATE_LIMIT_BODY)] * 6,
            max_retries=5,
        )
        with patch("asyncio.sleep", new=AsyncMock()):
            with pytest.raises(EmbeddingRateLimitError):
                await client.embed(["q"], max_retries=2)
        assert client._client.post_calls == 2  # noqa: SLF001 — small budget wins over the default 5

    async def test_429_without_error_code_treated_as_transient(self):
        """A 429 with NO error.code (empty body) is treated as transient (retryable)."""
        client = _client_with(
            [_FakeResponse(429, body={}), _FakeResponse(200, body=_SUCCESS_BODY)],
            max_retries=5,
        )
        with patch("asyncio.sleep", new=AsyncMock()):
            result = await client.embed(["q"])
        assert result == [[0.1, 0.2, 0.3]]
        assert client._client.post_calls == 2  # noqa: SLF001 — retried, not raised immediately

    async def test_429_malformed_body_treated_as_transient(self):
        """A 429 whose body is not JSON (json() raises) is treated as transient."""
        client = _client_with(
            [_FakeResponse(429, raise_on_json=True), _FakeResponse(200, body=_SUCCESS_BODY)],
            max_retries=5,
        )
        with patch("asyncio.sleep", new=AsyncMock()):
            result = await client.embed(["q"])
        assert result == [[0.1, 0.2, 0.3]]
        assert client._client.post_calls == 2  # noqa: SLF001

    async def test_rate_limit_then_quota_stops_immediately(self):
        """Mixed 429s: transient rate_limit (retry) then insufficient_quota → terminal."""
        client = _client_with(
            [
                _FakeResponse(429, body=_RATE_LIMIT_BODY),
                _FakeResponse(429, body=_QUOTA_BODY),
                _FakeResponse(200, body=_SUCCESS_BODY),
            ],
            max_retries=5,
        )
        with patch("asyncio.sleep", new=AsyncMock()) as sleep:
            with pytest.raises(EmbeddingQuotaError):
                await client.embed(["q"])
        assert client._client.post_calls == 2  # noqa: SLF001 — stopped at the quota response
        sleep.assert_awaited_once()  # only the first (rate-limit) attempt backed off

    async def test_retry_after_absent_falls_back_to_x_ratelimit_reset(self):
        """No Retry-After → honor x-ratelimit-reset-requests (parsed to seconds)."""
        client = _client_with(
            [
                _FakeResponse(
                    429,
                    body=_RATE_LIMIT_BODY,
                    headers={"x-ratelimit-reset-requests": "2s"},
                ),
                _FakeResponse(200, body=_SUCCESS_BODY),
            ],
            max_retries=5,
        )
        with patch("asyncio.sleep", new=AsyncMock()) as sleep:
            await client.embed(["q"])
        sleep.assert_awaited_once()
        assert sleep.await_args.args[0] == pytest.approx(2.0)

    async def test_no_headers_uses_jittered_backoff_within_cap(self):
        """Neither Retry-After nor reset header → jittered exp backoff, > 0 and <= cap."""
        client = _client_with(
            [_FakeResponse(429, body=_RATE_LIMIT_BODY), _FakeResponse(200, body=_SUCCESS_BODY)],
            max_retries=5,
            retry_max_wait_s=60.0,
        )
        with patch("asyncio.sleep", new=AsyncMock()) as sleep:
            await client.embed(["q"])
        sleep.assert_awaited_once()
        waited = sleep.await_args.args[0]
        # attempt=1 → 2**1 + uniform(0,1) ∈ [2, 3)
        assert 2.0 <= waited < 3.0

    async def test_retry_after_capped_by_retry_max_wait_s(self):
        """A huge Retry-After is bounded by retry_max_wait_s."""
        client = _client_with(
            [
                _FakeResponse(429, body=_RATE_LIMIT_BODY, headers={"retry-after": "9999"}),
                _FakeResponse(200, body=_SUCCESS_BODY),
            ],
            max_retries=5,
            retry_max_wait_s=5.0,
        )
        with patch("asyncio.sleep", new=AsyncMock()) as sleep:
            await client.embed(["q"])
        sleep.assert_awaited_once()
        assert sleep.await_args.args[0] == pytest.approx(5.0)

    async def test_jittered_backoff_capped_by_retry_max_wait_s(self):
        """Exponential backoff that exceeds the cap is clamped to retry_max_wait_s."""
        client = _client_with(
            [
                _FakeResponse(429, body=_RATE_LIMIT_BODY),
                _FakeResponse(429, body=_RATE_LIMIT_BODY),
                _FakeResponse(429, body=_RATE_LIMIT_BODY),
                _FakeResponse(200, body=_SUCCESS_BODY),
            ],
            max_retries=5,
            retry_max_wait_s=5.0,
        )
        with patch("asyncio.sleep", new=AsyncMock()) as sleep:
            await client.embed(["q"])
        waits = [c.args[0] for c in sleep.await_args_list]
        assert len(waits) == 3
        assert all(w <= 5.0 for w in waits)
        # attempt=3 → 2**3 + jitter = 8+ > 5 → clamped to the cap.
        assert waits[2] == pytest.approx(5.0)

    @pytest.mark.parametrize("status", [400, 401, 403, 404])
    async def test_non_retryable_4xx_not_retried_and_surfaced(self, status):
        """Non-429/5xx 4xx statuses are NOT retried and surface raw (not EmbeddingError)."""
        client = _client_with(
            [_FakeResponse(status, body={"error": {"code": "invalid_request_error"}})] * 3,
            max_retries=5,
        )
        with patch("asyncio.sleep", new=AsyncMock()) as sleep:
            with pytest.raises(httpx.HTTPStatusError):
                await client.embed(["q"])
        assert client._client.post_calls == 1  # noqa: SLF001 — single attempt, no retry
        sleep.assert_not_awaited()


class TestParseResetDuration:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("2", 2.0),
            ("2.5", 2.5),
            ("2s", 2.0),
            ("500ms", 0.5),
            ("6m0s", 360.0),
            ("1h2m3s", 3723.0),
            ("", None),
            (None, None),
            ("garbage", None),
        ],
    )
    def test_parse_reset_duration(self, value, expected):
        from tg_parser.services.embedding_service import _parse_reset_duration

        result = _parse_reset_duration(value)
        if expected is None:
            assert result is None
        else:
            assert result == pytest.approx(expected)


# ── RAG keyword fallback + degraded + metric ─────────────────────────────────


class TestRagFallback:
    async def test_semantic_fallback_on_quota_sets_degraded(self):
        """semantic + EmbeddingQuotaError → keyword fallback, degraded=True, metric."""
        from tg_parser.services.retrieval_service import search

        mock_client = AsyncMock()
        mock_client.embed = AsyncMock(side_effect=EmbeddingQuotaError("quota"))
        mock_client.close = AsyncMock()
        emb_repo, proc_repo = _mock_repos()

        before = _metric("quota_exhausted", "rag_query")
        with patch(
            "tg_parser.services.retrieval_service.create_embedding_client",
            MagicMock(return_value=mock_client),
        ):
            results = await search(
                query="q",
                mode="semantic",
                include_topics=False,
                emb_repo=emb_repo,
                proc_repo=proc_repo,
            )

        assert isinstance(results, list)
        assert getattr(results, "degraded", False) is True
        emb_repo.keyword_search.assert_awaited()  # fell back to keyword branch
        emb_repo.similarity_search.assert_not_awaited()  # never ran semantic (no vector)
        assert _metric("quota_exhausted", "rag_query") == before + 1

    async def test_hybrid_fallback_on_rate_limit_before_parallel(self):
        """hybrid + EmbeddingRateLimitError → keyword branch (fallback BEFORE parallel)."""
        from tg_parser.services.retrieval_service import search

        mock_client = AsyncMock()
        mock_client.embed = AsyncMock(side_effect=EmbeddingRateLimitError("rl"))
        mock_client.close = AsyncMock()
        emb_repo, proc_repo = _mock_repos()

        before = _metric("rate_limited", "rag_query")
        with patch(
            "tg_parser.services.retrieval_service.create_embedding_client",
            MagicMock(return_value=mock_client),
        ):
            results = await search(
                query="q",
                mode="hybrid",
                include_topics=False,
                emb_repo=emb_repo,
                proc_repo=proc_repo,
            )

        assert isinstance(results, list)
        assert getattr(results, "degraded", False) is True
        # effective_mode became keyword BEFORE the run_hybrid_parallel decision:
        # only the keyword branch ran, the semantic branch never did.
        emb_repo.keyword_search.assert_awaited()
        emb_repo.similarity_search.assert_not_awaited()
        assert _metric("rate_limited", "rag_query") == before + 1

    @pytest.mark.parametrize("mode", ["semantic", "hybrid"])
    @pytest.mark.parametrize(
        ("exc", "outcome"),
        [
            (EmbeddingQuotaError("quota"), "quota_exhausted"),
            (EmbeddingRateLimitError("rl"), "rate_limited"),
        ],
    )
    async def test_fallback_matrix_both_classes_both_modes(self, mode, exc, outcome):
        """BOTH error classes degrade BOTH semantic and hybrid → keyword + degraded."""
        from tg_parser.services.retrieval_service import search

        mock_client = AsyncMock()
        mock_client.embed = AsyncMock(side_effect=exc)
        mock_client.close = AsyncMock()
        emb_repo, proc_repo = _mock_repos()

        before = _metric(outcome, "rag_query")
        with patch(
            "tg_parser.services.retrieval_service.create_embedding_client",
            MagicMock(return_value=mock_client),
        ):
            results = await search(
                query="q",
                mode=mode,
                include_topics=False,
                emb_repo=emb_repo,
                proc_repo=proc_repo,
            )

        assert getattr(results, "degraded", False) is True
        emb_repo.keyword_search.assert_awaited()
        emb_repo.similarity_search.assert_not_awaited()
        assert _metric(outcome, "rag_query") == before + 1

    async def test_tenant_scoping_preserved_under_fallback(self):
        """The tenant scope (allowed_channel_ids) is passed to the keyword branch on fallback."""
        from tg_parser.services.retrieval_service import search

        mock_client = AsyncMock()
        mock_client.embed = AsyncMock(side_effect=EmbeddingQuotaError("quota"))
        mock_client.close = AsyncMock()
        emb_repo, proc_repo = _mock_repos()

        with patch(
            "tg_parser.services.retrieval_service.create_embedding_client",
            MagicMock(return_value=mock_client),
        ):
            await search(
                query="q",
                mode="semantic",
                include_topics=False,
                allowed_channel_ids=["ch1", "ch2"],
                emb_repo=emb_repo,
                proc_repo=proc_repo,
            )

        emb_repo.keyword_search.assert_awaited()
        assert emb_repo.keyword_search.await_args.kwargs["channel_ids"] == ["ch1", "ch2"]

    async def test_rag_uses_small_retry_budget(self):
        """RAG path passes a SMALL retry budget (< full background budget)."""
        from tg_parser.services.retrieval_service import (
            RAG_QUERY_EMBED_MAX_RETRIES,
            search,
        )

        captured: dict = {}
        mock_client = AsyncMock()

        async def _embed(texts, *, max_retries=None):
            captured["max_retries"] = max_retries
            return [[0.1, 0.2, 0.3]]

        mock_client.embed = _embed
        mock_client.close = AsyncMock()
        emb_repo, proc_repo = _mock_repos()

        with patch(
            "tg_parser.services.retrieval_service.create_embedding_client",
            MagicMock(return_value=mock_client),
        ):
            await search(
                query="q",
                mode="semantic",
                include_topics=False,
                emb_repo=emb_repo,
                proc_repo=proc_repo,
            )

        assert captured["max_retries"] == RAG_QUERY_EMBED_MAX_RETRIES
        assert RAG_QUERY_EMBED_MAX_RETRIES < Settings().embedding_max_retries

    async def test_ok_records_outcome_and_not_degraded(self):
        """A healthy embed records outcome=ok and does not degrade."""
        from tg_parser.services.retrieval_service import search

        mock_client = AsyncMock()
        mock_client.embed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
        mock_client.close = AsyncMock()
        emb_repo, proc_repo = _mock_repos()

        before = _metric("ok", "rag_query")
        with patch(
            "tg_parser.services.retrieval_service.create_embedding_client",
            MagicMock(return_value=mock_client),
        ):
            results = await search(
                query="q",
                mode="semantic",
                include_topics=False,
                emb_repo=emb_repo,
                proc_repo=proc_repo,
            )

        assert getattr(results, "degraded", False) is False
        assert _metric("ok", "rag_query") == before + 1

    async def test_no_regression_per_loop_client_reuse(self):
        """S7 per-loop reuse intact: one client across two searches (no leak)."""
        from tg_parser.services.retrieval_service import search

        mock_client = AsyncMock()
        mock_client.embed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
        mock_client.close = AsyncMock()
        factory = MagicMock(return_value=mock_client)
        emb_repo, proc_repo = _mock_repos()

        with patch("tg_parser.services.retrieval_service.create_embedding_client", factory):
            for _ in range(2):
                await search(
                    query="q",
                    mode="semantic",
                    include_topics=False,
                    emb_repo=emb_repo,
                    proc_repo=proc_repo,
                )

        assert factory.call_count == 1
        mock_client.close.assert_not_awaited()


# ── Background scheduler classification ───────────────────────────────────────


def _patch_sources(sources: list):
    @contextlib.asynccontextmanager
    async def _cm():
        state_repo = AsyncMock()
        state_repo.list_sources = AsyncMock(return_value=sources)
        yield (state_repo, None)

    return patch(
        "tg_parser.services.db_context.ingestion_state_repo",
        MagicMock(return_value=_cm()),
    )


class TestBackgroundClassification:
    async def test_background_quota_records_quota_exhausted(self):
        from tg_parser.services import background_scheduler

        before = _metric("quota_exhausted", "background_message")
        with _patch_sources([SimpleNamespace(channel_id="ch")]):
            with patch(
                "tg_parser.services.embedding_service.run_embedding",
                AsyncMock(side_effect=EmbeddingQuotaError("quota")),
            ):
                with patch(
                    "tg_parser.services.embedding_service.run_topic_embedding",
                    AsyncMock(return_value={"embedded_count": 0}),
                ):
                    await background_scheduler._incremental_embedding_task()

        assert _metric("quota_exhausted", "background_message") == before + 1

    async def test_background_rate_limit_records_rate_limited(self):
        from tg_parser.services import background_scheduler

        before = _metric("rate_limited", "background_message")
        with _patch_sources([SimpleNamespace(channel_id="ch")]):
            with patch(
                "tg_parser.services.embedding_service.run_embedding",
                AsyncMock(side_effect=EmbeddingRateLimitError("rl")),
            ):
                with patch(
                    "tg_parser.services.embedding_service.run_topic_embedding",
                    AsyncMock(return_value={"embedded_count": 0}),
                ):
                    await background_scheduler._incremental_embedding_task()

        assert _metric("rate_limited", "background_message") == before + 1

    async def test_background_generic_error_records_error(self):
        from tg_parser.services import background_scheduler

        before = _metric("error", "background_message")
        with _patch_sources([SimpleNamespace(channel_id="ch")]):
            with patch(
                "tg_parser.services.embedding_service.run_embedding",
                AsyncMock(side_effect=RuntimeError("boom")),
            ):
                with patch(
                    "tg_parser.services.embedding_service.run_topic_embedding",
                    AsyncMock(return_value={"embedded_count": 0}),
                ):
                    await background_scheduler._incremental_embedding_task()

        assert _metric("error", "background_message") == before + 1

    async def test_background_topic_quota_records_at_topic_stage(self):
        """A quota failure in the TOPIC embedding step is classified at stage=background_topic."""
        from tg_parser.services import background_scheduler

        before = _metric("quota_exhausted", "background_topic")
        with _patch_sources([SimpleNamespace(channel_id="ch")]):
            with patch(
                "tg_parser.services.embedding_service.run_embedding",
                AsyncMock(return_value={"embedded_count": 0}),
            ):
                with patch(
                    "tg_parser.services.embedding_service.run_topic_embedding",
                    AsyncMock(side_effect=EmbeddingQuotaError("quota")),
                ):
                    await background_scheduler._incremental_embedding_task()

        assert _metric("quota_exhausted", "background_topic") == before + 1

    async def test_background_success_records_ok_both_stages(self):
        """A healthy tick records outcome=ok at both background stages."""
        from tg_parser.services import background_scheduler

        before_msg = _metric("ok", "background_message")
        before_topic = _metric("ok", "background_topic")
        with _patch_sources([SimpleNamespace(channel_id="ch")]):
            with patch(
                "tg_parser.services.embedding_service.run_embedding",
                AsyncMock(return_value={"embedded_count": 3}),
            ):
                with patch(
                    "tg_parser.services.embedding_service.run_topic_embedding",
                    AsyncMock(return_value={"embedded_count": 2}),
                ):
                    await background_scheduler._incremental_embedding_task()

        assert _metric("ok", "background_message") == before_msg + 1
        assert _metric("ok", "background_topic") == before_topic + 1


# ── Batch/ingestion embedding path unchanged ──────────────────────────────────


class TestBatchPathsStillWork:
    async def test_incremental_embedding_uses_full_default_budget(self):
        """Batch/ingestion path still embeds and does NOT pass the small RAG budget."""
        from datetime import datetime

        from tg_parser.services.embedding_service import run_incremental_embedding

        ref = make_source_ref("batch_ch", "post", "1")
        doc = ProcessedDocument(
            id=f"doc:{ref}",
            source_ref=ref,
            source_message_id="1",
            channel_id="batch_ch",
            processed_at=datetime(2026, 1, 1, 0, 0, 0),
            text_clean="hello world",
            summary="hi",
        )

        captured: dict = {}
        mock_client = AsyncMock()

        async def _embed(texts, *, max_retries=None):
            captured["max_retries"] = max_retries
            return [[0.1, 0.2, 0.3] for _ in texts]

        mock_client.embed = _embed
        mock_client.close = AsyncMock()

        emb_repo = AsyncMock()
        emb_repo.save_batch = AsyncMock(return_value=1)
        proc_repo = AsyncMock()
        proc_repo.get_by_source_refs = AsyncMock(return_value={ref: doc})

        with patch(
            "tg_parser.services.embedding_service.create_embedding_client",
            MagicMock(return_value=mock_client),
        ):
            stats = await run_incremental_embedding([ref], emb_repo=emb_repo, proc_repo=proc_repo)

        assert stats["embedded_count"] == 1
        # Batch path uses the client's own (full) default budget — not the small RAG one.
        assert captured["max_retries"] is None

    async def test_empty_incremental_embedding_is_noop(self):
        from tg_parser.services.embedding_service import run_incremental_embedding

        with patch(
            "tg_parser.services.embedding_service.create_embedding_client"
        ) as mock_factory:
            stats = await run_incremental_embedding([])
        assert stats == {"embedded_count": 0, "total_count": 0}
        mock_factory.assert_not_called()
