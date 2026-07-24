"""F5-C CLI ``tg-parser topic {versions,resummarize}`` — pure-mock tests.

Uses Typer's ``CliRunner`` to invoke the registered subcommands. Database
singleton + ``resummarization_repos`` + ``ResummarizationService`` are
patched so the tests run without Postgres or live LLMs.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import patch

from typer.testing import CliRunner

from tg_parser.cli.topic_cmd import app as topic_app
from tg_parser.domain.models import (
    Anchor,
    MessageType,
    TopicCard,
    TopicCardVersion,
    TopicType,
)

runner = CliRunner()


def _make_card(
    *,
    summary_version: int = 2,
    new_items: int = 3,
) -> TopicCard:
    return TopicCard(
        id="topic:tg:c1:post:1",
        title="Test topic",
        summary="Original summary",
        scope_in=["alpha"],
        scope_out=["beta"],
        type=TopicType.SINGLETON,
        anchors=[
            Anchor(
                channel_id="c1",
                message_id="1",
                message_type=MessageType.POST,
                anchor_ref="tg:c1:post:1",
                score=0.9,
            )
        ],
        sources=["c1"],
        updated_at=datetime(2026, 4, 26, tzinfo=UTC),
        summary_version=summary_version,
        last_summarized_at=datetime(2026, 4, 25, 12, 0, tzinfo=UTC),
        new_items_since_last_summary=new_items,
    )


def _make_version(version_no: int) -> TopicCardVersion:
    return TopicCardVersion(
        id=version_no,
        topic_id="topic:tg:c1:post:1",
        version_no=version_no,
        summary=f"Snapshot v{version_no}",
        scope_in=["alpha"],
        scope_out=["beta"],
        supporting_items_count_at_time=10 + version_no,
        llm_provider="openai",
        llm_model="gpt-4o-mini",
        prompt_version="1.0.0",
        created_at=datetime(2026, 4, 26, 10, version_no, 0, tzinfo=UTC),
    )


class _FakeCardRepo:
    def __init__(self, card: TopicCard | None) -> None:
        self._card = card

    async def get_by_id(self, _topic_id: str) -> TopicCard | None:
        return self._card


class _FakeBundleRepo:
    def __init__(self, items_count: int = 5) -> None:
        self.items_count = items_count

    async def get_by_topic_id(self, _topic_id: str):
        from tg_parser.domain.models import (
            BundleItem,
            BundleItemRole,
            MessageType,
            TopicBundle,
        )

        return TopicBundle(
            topic_id="topic:tg:c1:post:1",
            items=[
                BundleItem(
                    channel_id="c1",
                    message_id=str(idx),
                    message_type=MessageType.POST,
                    source_ref=f"tg:c1:post:{idx}",
                    role=BundleItemRole.SUPPORTING,
                    score=0.5,
                )
                for idx in range(2, 2 + self.items_count)
            ],
            updated_at=datetime(2026, 4, 26, tzinfo=UTC),
        )


class _FakeVersionRepo:
    def __init__(self, versions: list[TopicCardVersion]) -> None:
        self._versions = versions
        self.calls: list[dict] = []

    async def list_by_topic(self, topic_id: str, limit: int = 50):
        self.calls.append({"topic_id": topic_id, "limit": limit})
        return list(self._versions[:limit])

    async def get_two_versions(self, topic_id: str, version_a: int, version_b: int):
        self.calls.append({"get_two_versions": (topic_id, version_a, version_b)})
        wanted = {version_a, version_b}
        return {v.version_no: v for v in self._versions if v.version_no in wanted}


class _FakeService:
    def __init__(self, outcome: dict) -> None:
        self.outcome = outcome
        self.calls: list[str] = []
        self.closed = False

    async def resummarize_topic(self, topic_id: str) -> dict:
        self.calls.append(topic_id)
        return self.outcome

    async def aclose(self) -> None:
        self.closed = True


@asynccontextmanager
async def _fake_repos(card_repo, bundle_repo, version_repo):
    yield (card_repo, bundle_repo, version_repo, "proc_repo", "db")


def _patch_close():
    async def _fake_close():
        return None

    return patch(
        "tg_parser.storage.sqlalchemy.database.Database.close_instance",
        classmethod(lambda cls: _fake_close()),
    )


# ---------------------------------------------------------------------------
# tg-parser topic versions
# ---------------------------------------------------------------------------


class TestVersionsCommand:
    def test_happy_path_prints_history(self):
        cr = _FakeCardRepo(_make_card(summary_version=3))
        br = _FakeBundleRepo()
        vr = _FakeVersionRepo([_make_version(3), _make_version(2), _make_version(1)])

        with (
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                lambda: _fake_repos(cr, br, vr),
            ),
            _patch_close(),
        ):
            result = runner.invoke(topic_app, ["versions", "topic:tg:c1:post:1"])

        assert result.exit_code == 0, result.output
        assert "current_version" in result.output
        assert "v3" in result.output
        assert "v2" in result.output
        assert "v1" in result.output

    def test_topic_not_found_exits_1(self):
        cr = _FakeCardRepo(None)
        br = _FakeBundleRepo()
        vr = _FakeVersionRepo([])

        with (
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                lambda: _fake_repos(cr, br, vr),
            ),
            _patch_close(),
        ):
            result = runner.invoke(topic_app, ["versions", "topic:tg:cX:post:1"])

        assert result.exit_code == 1
        assert "не найден" in result.output

    def test_empty_history_prints_warning_but_succeeds(self):
        cr = _FakeCardRepo(_make_card(summary_version=1))
        br = _FakeBundleRepo()
        vr = _FakeVersionRepo([])

        with (
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                lambda: _fake_repos(cr, br, vr),
            ),
            _patch_close(),
        ):
            result = runner.invoke(topic_app, ["versions", "topic:tg:c1:post:1"])

        assert result.exit_code == 0
        assert "пуста" in result.output

    def test_limit_option_is_forwarded_to_repo(self):
        """``--limit N`` must reach ``version_repo.list_by_topic`` so admins
        actually narrow the audit dump (otherwise the ``min=1, max=200``
        Typer constraint is decorative)."""
        cr = _FakeCardRepo(_make_card(summary_version=3))
        br = _FakeBundleRepo()
        vr = _FakeVersionRepo([_make_version(3), _make_version(2), _make_version(1)])

        with (
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                lambda: _fake_repos(cr, br, vr),
            ),
            _patch_close(),
        ):
            result = runner.invoke(
                topic_app,
                ["versions", "topic:tg:c1:post:1", "--limit", "5"],
            )

        assert result.exit_code == 0, result.output
        assert vr.calls == [{"topic_id": "topic:tg:c1:post:1", "limit": 5}]
        assert "limit=5" in result.output

    def test_invalid_limit_is_rejected_by_typer(self):
        """Typer's ``min=1, max=200`` must reject out-of-range values
        before any repo call (UX guardrail)."""
        cr = _FakeCardRepo(_make_card())
        br = _FakeBundleRepo()
        vr = _FakeVersionRepo([])

        with (
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                lambda: _fake_repos(cr, br, vr),
            ),
            _patch_close(),
        ):
            result = runner.invoke(
                topic_app,
                ["versions", "topic:tg:c1:post:1", "--limit", "0"],
            )

        assert result.exit_code != 0
        assert vr.calls == []


# ---------------------------------------------------------------------------
# tg-parser topic diff (F5-C #15 item #2 diff API)
# ---------------------------------------------------------------------------


class TestDiffCommand:
    def test_default_genesis_to_current_renders(self):
        cr = _FakeCardRepo(_make_card(summary_version=3))
        br = _FakeBundleRepo()
        vr = _FakeVersionRepo([_make_version(3), _make_version(2), _make_version(1)])

        with (
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                lambda: _fake_repos(cr, br, vr),
            ),
            _patch_close(),
        ):
            result = runner.invoke(topic_app, ["diff", "topic:tg:c1:post:1"])

        assert result.exit_code == 0, result.output
        assert "Diff summary" in result.output
        # genesis (v1) -> current label
        assert "v1" in result.output
        assert "current" in result.output
        assert "summary" in result.output
        # Only genesis fetched from the archival side.
        assert {"get_two_versions": ("topic:tg:c1:post:1", 1, 1)} in vr.calls

    def test_archival_pair_renders(self):
        cr = _FakeCardRepo(_make_card(summary_version=4))
        br = _FakeBundleRepo()
        vr = _FakeVersionRepo([_make_version(3), _make_version(2), _make_version(1)])

        with (
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                lambda: _fake_repos(cr, br, vr),
            ),
            _patch_close(),
        ):
            result = runner.invoke(
                topic_app,
                ["diff", "topic:tg:c1:post:1", "--version-a", "1", "--version-b", "3"],
            )

        assert result.exit_code == 0, result.output
        assert {"get_two_versions": ("topic:tg:c1:post:1", 1, 3)} in vr.calls

    def test_missing_version_prints_typed_not_found_and_exits_1(self):
        cr = _FakeCardRepo(_make_card(summary_version=6))
        br = _FakeBundleRepo()
        vr = _FakeVersionRepo([_make_version(1)])  # v99 missing

        with (
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                lambda: _fake_repos(cr, br, vr),
            ),
            _patch_close(),
        ):
            result = runner.invoke(
                topic_app,
                ["diff", "topic:tg:c1:post:1", "--version-a", "1", "--version-b", "99"],
            )

        assert result.exit_code == 1
        assert "retention policy" in result.output
        assert "v99" in result.output

    def test_topic_not_found_exits_1(self):
        cr = _FakeCardRepo(None)
        br = _FakeBundleRepo()
        vr = _FakeVersionRepo([])

        with (
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                lambda: _fake_repos(cr, br, vr),
            ),
            _patch_close(),
        ):
            result = runner.invoke(topic_app, ["diff", "topic:tg:cX:post:1"])

        assert result.exit_code == 1
        assert "не найден" in result.output

    def test_bad_version_b_token_rejected(self):
        cr = _FakeCardRepo(_make_card())
        br = _FakeBundleRepo()
        vr = _FakeVersionRepo([_make_version(1)])

        with (
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                lambda: _fake_repos(cr, br, vr),
            ),
            _patch_close(),
        ):
            result = runner.invoke(
                topic_app,
                ["diff", "topic:tg:c1:post:1", "--version-b", "bogus"],
            )

        assert result.exit_code == 1
        assert vr.calls == []


# ---------------------------------------------------------------------------
# tg-parser topic resummarize
# ---------------------------------------------------------------------------


class TestResummarizeCommand:
    def test_dry_run_prints_context_without_invoking_service(self):
        cr = _FakeCardRepo(_make_card(summary_version=4, new_items=7))
        br = _FakeBundleRepo(items_count=12)
        vr = _FakeVersionRepo([])

        with (
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                lambda: _fake_repos(cr, br, vr),
            ),
            _patch_close(),
        ):
            result = runner.invoke(topic_app, ["resummarize", "topic:tg:c1:post:1", "--dry-run"])

        assert result.exit_code == 0, result.output
        assert "Dry-run" in result.output
        assert "current_version:" in result.output
        assert "12" in result.output

    def test_dry_run_topic_not_found_exits_1(self):
        cr = _FakeCardRepo(None)
        br = _FakeBundleRepo()
        vr = _FakeVersionRepo([])

        with (
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                lambda: _fake_repos(cr, br, vr),
            ),
            _patch_close(),
        ):
            result = runner.invoke(topic_app, ["resummarize", "topic:tg:cX:post:1", "--dry-run"])

        assert result.exit_code == 1
        assert "не найден" in result.output

    def test_happy_path_invokes_service_and_closes(self):
        # NB: real ResummarizationService.resummarize_topic returns
        # ``version_no`` (NOT ``summary_version``) — this test pins the
        # actual contract so the CLI rendering keeps working.  The previous
        # version of this test mocked ``summary_version``, which masked a
        # real bug where the CLI silently dropped the new version on every
        # successful run.
        cr = _FakeCardRepo(_make_card())
        br = _FakeBundleRepo()
        vr = _FakeVersionRepo([])
        svc = _FakeService(
            outcome={
                "status": "ok",
                "version_no": 5,
                "tokens": 1234,
                "duration_s": 0.42,
            }
        )

        with (
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                lambda: _fake_repos(cr, br, vr),
            ),
            patch(
                "tg_parser.services.resummarization_service.ResummarizationService",
                lambda **_kw: svc,
            ),
            _patch_close(),
        ):
            result = runner.invoke(topic_app, ["resummarize", "topic:tg:c1:post:1"])

        assert result.exit_code == 0, result.output
        assert "ok" in result.output
        assert "Готово" in result.output
        # Version must be rendered — regression guard against the
        # version_no/summary_version mismatch bug.
        assert "new_version: 5" in result.output
        assert "tokens" in result.output
        assert svc.calls == ["topic:tg:c1:post:1"]
        assert svc.closed is True

    def test_locked_status_prints_warning_but_succeeds(self):
        cr = _FakeCardRepo(_make_card())
        br = _FakeBundleRepo()
        vr = _FakeVersionRepo([])
        svc = _FakeService(outcome={"status": "locked"})

        with (
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                lambda: _fake_repos(cr, br, vr),
            ),
            patch(
                "tg_parser.services.resummarization_service.ResummarizationService",
                lambda **_kw: svc,
            ),
            _patch_close(),
        ):
            result = runner.invoke(topic_app, ["resummarize", "topic:tg:c1:post:1"])

        # CLI's locked branch is a soft warning (exit 0) — operators retry.
        assert result.exit_code == 0
        assert "locked" in result.output
        assert "повторите позже" in result.output
        assert svc.closed is True

    def test_unknown_status_exits_1(self):
        cr = _FakeCardRepo(_make_card())
        br = _FakeBundleRepo()
        vr = _FakeVersionRepo([])
        svc = _FakeService(outcome={"status": "skipped_n_below_threshold"})

        with (
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                lambda: _fake_repos(cr, br, vr),
            ),
            patch(
                "tg_parser.services.resummarization_service.ResummarizationService",
                lambda **_kw: svc,
            ),
            _patch_close(),
        ):
            result = runner.invoke(topic_app, ["resummarize", "topic:tg:c1:post:1"])

        assert result.exit_code == 1
        assert "skipped_n_below_threshold" in result.output

    def test_service_exception_closes_service_and_exits_1(self):
        """If the underlying service blows up, the CLI must surface the
        error AND ``aclose`` must still run so we don't leak DB sessions
        / LLM clients on a manual invocation."""
        cr = _FakeCardRepo(_make_card())
        br = _FakeBundleRepo()
        vr = _FakeVersionRepo([])

        class _Boom(_FakeService):
            async def resummarize_topic(self, topic_id: str):
                raise RuntimeError("llm down")

        svc = _Boom(outcome={})

        with (
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                lambda: _fake_repos(cr, br, vr),
            ),
            patch(
                "tg_parser.services.resummarization_service.ResummarizationService",
                lambda **_kw: svc,
            ),
            _patch_close(),
        ):
            result = runner.invoke(topic_app, ["resummarize", "topic:tg:c1:post:1"])

        assert result.exit_code == 1
        assert "llm down" in result.output
        assert svc.closed is True, "aclose must run even on fatal exception"
