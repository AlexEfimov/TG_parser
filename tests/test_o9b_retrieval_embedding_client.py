"""
O-9b lifecycle tests: reusable per-event-loop embedding client in the RAG path.

Closes review finding F-11 (retrieval half): ``retrieval_service.search()`` used
to build and close a fresh ``httpx``-backed embedding client on *every* semantic /
hybrid query. S7 replaces that with one client cached per running event loop,
closed once on application shutdown.

Design constraints exercised here:

- **Reuse within a loop** — repeated ``search()`` calls in one loop share a single
  client (no per-request TLS handshake / socket churn).
- **Per-loop safety** — the cache is keyed by the running loop (``httpx.AsyncClient``
  is loop-bound), so distinct ``asyncio.run(...)`` loops never touch a client that
  belongs to a closed loop (no ``RuntimeError: Event loop is closed``).
- **Idempotent shutdown close** — the shutdown hook closes the cached client exactly
  once; a second call is a no-op.
- **No per-request leak** — ``search()`` no longer closes the client per call.
- **Test isolation** — ``reset_embedding_client_cache()`` drops cached clients.

All cases run in *default* mode: mocked ``embed`` + injected mock repos, no Postgres.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_client() -> AsyncMock:
    """A stand-in embedding client: ``embed`` returns a fixed 3-dim vector."""
    client = AsyncMock()
    client.embed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
    client.close = AsyncMock()
    return client


def _mock_repos() -> tuple[AsyncMock, AsyncMock]:
    """Injected repos so ``search()`` never opens a real DB context."""
    emb_repo = AsyncMock()
    emb_repo.similarity_search = AsyncMock(return_value=[])
    emb_repo.keyword_search = AsyncMock(return_value=[])
    proc_repo = AsyncMock()
    proc_repo.get_by_source_refs = AsyncMock(return_value={})
    return emb_repo, proc_repo


@pytest.fixture(autouse=True)
def _clean_cache():
    """Isolate every test from cached clients created by others."""
    from tg_parser.services.embedding_service import reset_embedding_client_cache

    reset_embedding_client_cache()
    yield
    reset_embedding_client_cache()


class TestReuseWithinLoop:
    async def test_client_created_once_across_two_searches(self):
        """Two sequential semantic searches in one loop → factory called once."""
        from tg_parser.services.retrieval_service import search

        client = _make_client()
        factory = MagicMock(return_value=client)
        emb_repo, proc_repo = _mock_repos()

        with patch(
            "tg_parser.services.retrieval_service.create_embedding_client",
            factory,
        ):
            for _ in range(2):
                await search(
                    query="q",
                    mode="semantic",
                    include_topics=False,
                    emb_repo=emb_repo,
                    proc_repo=proc_repo,
                )

        assert factory.call_count == 1, "embedding client must be reused within a loop"
        assert client.embed.await_count == 2, "each search still embeds the query"

    async def test_no_per_request_close(self):
        """The reused client stays alive between requests (no per-request close)."""
        from tg_parser.services.retrieval_service import search

        client = _make_client()
        factory = MagicMock(return_value=client)
        emb_repo, proc_repo = _mock_repos()

        with patch(
            "tg_parser.services.retrieval_service.create_embedding_client",
            factory,
        ):
            await search(
                query="q",
                mode="semantic",
                include_topics=False,
                emb_repo=emb_repo,
                proc_repo=proc_repo,
            )
            await search(
                query="q2",
                mode="semantic",
                include_topics=False,
                emb_repo=emb_repo,
                proc_repo=proc_repo,
            )

        client.close.assert_not_awaited()


class TestPerLoopSafety:
    def test_distinct_loops_get_distinct_clients(self):
        """Two independent ``asyncio.run`` loops must each build their own client.

        Each loop runs two searches, so the single expected count per loop also
        pins down within-loop reuse. The final ``call_count == 2`` therefore
        discriminates against *both* wrong implementations:

        - a process-global singleton would reuse a client bound to the first
          (now-closed) loop (count 1, and in real code ``RuntimeError: Event
          loop is closed``);
        - the old per-request create/close would build a client per query
          (count 4).

        Only the per-loop cache yields exactly one client per loop (count 2).
        """
        from tg_parser.services.embedding_service import reset_embedding_client_cache
        from tg_parser.services.retrieval_service import search

        reset_embedding_client_cache()
        factory = MagicMock(side_effect=lambda: _make_client())
        emb_repo, proc_repo = _mock_repos()

        async def _one() -> None:
            for _ in range(2):
                await search(
                    query="q",
                    mode="semantic",
                    include_topics=False,
                    emb_repo=emb_repo,
                    proc_repo=proc_repo,
                )

        with patch(
            "tg_parser.services.retrieval_service.create_embedding_client",
            factory,
        ):
            asyncio.run(_one())
            asyncio.run(_one())  # must NOT raise "Event loop is closed"

        assert factory.call_count == 2, "one client per loop, reused within it"


class TestShutdownClose:
    async def test_close_is_idempotent(self):
        """Shutdown hook closes the cached client once; second call is a no-op."""
        from tg_parser.services.embedding_service import (
            close_embedding_client,
            get_embedding_client,
        )

        client = _make_client()
        factory = MagicMock(return_value=client)

        got = get_embedding_client(factory=factory)
        assert got is client

        await close_embedding_client()
        client.close.assert_awaited_once()

        # Cache is now empty → second close closes nothing.
        await close_embedding_client()
        client.close.assert_awaited_once()

    async def test_shutdown_closes_client_created_by_search(self):
        """End-to-end seam: the client ``search()`` caches is the one shutdown closes.

        Guards against the cache key drifting between the request path
        (``search`` → ``get_embedding_client``) and the shutdown path
        (``close_embedding_client``): both must resolve the same running loop's
        entry, so the reused socket is released exactly once.
        """
        from tg_parser.services.embedding_service import close_embedding_client
        from tg_parser.services.retrieval_service import search

        client = _make_client()
        factory = MagicMock(return_value=client)
        emb_repo, proc_repo = _mock_repos()

        with patch(
            "tg_parser.services.retrieval_service.create_embedding_client",
            factory,
        ):
            await search(
                query="q",
                mode="semantic",
                include_topics=False,
                emb_repo=emb_repo,
                proc_repo=proc_repo,
            )
            client.close.assert_not_awaited()  # search must not close it
            await close_embedding_client()

        client.close.assert_awaited_once()

    async def test_get_after_close_rebuilds(self):
        """After close, the next accessor call rebuilds a fresh client."""
        from tg_parser.services.embedding_service import (
            close_embedding_client,
            get_embedding_client,
        )

        factory = MagicMock(side_effect=lambda: _make_client())

        first = get_embedding_client(factory=factory)
        await close_embedding_client()
        second = get_embedding_client(factory=factory)

        assert factory.call_count == 2
        assert first is not second


class TestDiIsolation:
    async def test_reset_forces_new_client(self):
        """``reset_embedding_client_cache`` drops the cached client (test isolation)."""
        from tg_parser.services.embedding_service import (
            get_embedding_client,
            reset_embedding_client_cache,
        )

        factory = MagicMock(side_effect=lambda: _make_client())

        first = get_embedding_client(factory=factory)
        assert get_embedding_client(factory=factory) is first  # reuse

        reset_embedding_client_cache()

        second = get_embedding_client(factory=factory)
        assert first is not second
        assert factory.call_count == 2
