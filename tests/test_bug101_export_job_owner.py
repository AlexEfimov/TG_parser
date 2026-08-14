"""
BUG-101 / F-10 — export job owner check on the three read paths.

A second identity asking for someone else's ``job_id`` must look like
the job does not exist: MCP ``status="unknown"`` / ``channel_id=None``,
HTTP status and download ``404``. Download checks the owner *before*
``COMPLETED``, so a foreign pending job is 404, not 400.

Source of truth is ``Job.client == user.name`` (both writers already
persist that). Admin (``allowed_channel_ids is None``) passes. Existing
lifecycle tests in ``test_f2_parse_only_export.py`` stay under one
identity and must keep working.
"""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from tg_parser.api.auth import resolve_current_user
from tg_parser.api.main import create_app
from tg_parser.auth.models import CurrentUser
from tg_parser.storage.ports import Job, JobStatus, JobType

NOW = datetime(2026, 8, 14, 12, 0, 0, tzinfo=UTC)
JOB_ID = "11111111-2222-4333-8444-555555555555"


def _admin() -> CurrentUser:
    return CurrentUser(
        id="admin-1", name="admin", role="admin", allowed_channel_ids=None, max_channels=100
    )


def _user(name: str = "alice") -> CurrentUser:
    return CurrentUser(
        id=f"user-{name}",
        name=name,
        role="user",
        allowed_channel_ids=["own_channel"],
        max_channels=5,
    )


def _job(*, client: str | None, status: JobStatus = JobStatus.COMPLETED, file_path: str | None = None) -> Job:
    return Job(
        job_id=JOB_ID,
        job_type=JobType.EXPORT,
        status=status,
        created_at=NOW,
        channel_id="own_channel",
        client=client,
        export_format="json",
        file_path=file_path,
        download_url=f"/api/v1/export/download/{JOB_ID}",
        progress={"level": "raw"},
        result={"file_size": 42, "level": "raw", "format": "json"},
    )


def _store(job: Job | None) -> AsyncMock:
    store = AsyncMock()
    store.get_job.return_value = job
    return store


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


class TestExportJobVisibleTo:
    def test_admin_sees_any_client(self):
        from tg_parser.api.routes.export import _export_job_visible_to

        assert _export_job_visible_to(_admin(), _job(client="bob")) is True

    def test_owner_name_matches(self):
        from tg_parser.api.routes.export import _export_job_visible_to

        assert _export_job_visible_to(_user("alice"), _job(client="alice")) is True

    def test_foreign_name_is_hidden(self):
        from tg_parser.api.routes.export import _export_job_visible_to

        assert _export_job_visible_to(_user("alice"), _job(client="bob")) is False

    def test_missing_client_is_hidden_from_non_admin(self):
        from tg_parser.api.routes.export import _export_job_visible_to

        assert _export_job_visible_to(_user("alice"), _job(client=None)) is False


# ---------------------------------------------------------------------------
# MCP get_export_status
# ---------------------------------------------------------------------------


class TestMcpGetExportStatusOwner:
    async def _call(self, user: CurrentUser, job: Job | None):
        store = _store(job)
        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=user)),
            patch(
                "tg_parser.api.job_store.ensure_job_store_initialized",
                AsyncMock(return_value=store),
            ),
        ):
            from tg_parser.mcp_server import get_export_status

            return await get_export_status(JOB_ID, ctx=None)

    async def test_foreign_job_looks_like_unknown(self):
        result = await self._call(_user("alice"), _job(client="bob"))
        assert result.status == "unknown"
        assert result.channel_id is None
        assert result.download_url is None
        assert result.file_size is None

    async def test_missing_job_is_unknown(self):
        result = await self._call(_user("alice"), None)
        assert result.status == "unknown"
        assert result.channel_id is None

    async def test_own_job_returns_status(self):
        result = await self._call(_user("alice"), _job(client="alice"))
        assert result.status == "completed"
        assert result.channel_id == "own_channel"
        assert result.file_size == 42

    async def test_admin_sees_foreign_job(self):
        result = await self._call(_admin(), _job(client="bob"))
        assert result.status == "completed"
        assert result.channel_id == "own_channel"


# ---------------------------------------------------------------------------
# HTTP status + download
# ---------------------------------------------------------------------------


class TestHttpExportOwner:
    @pytest.fixture
    def app(self):
        return create_app()

    async def _request(self, app, user: CurrentUser, method: str, path: str, job: Job | None):
        store = _store(job)
        app.dependency_overrides[resolve_current_user] = lambda: user
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                with patch(
                    "tg_parser.api.routes.export.ensure_job_store_initialized",
                    AsyncMock(return_value=store),
                ):
                    if method == "GET":
                        return await client.get(path)
        finally:
            app.dependency_overrides.clear()

    async def test_foreign_status_is_404_like_unknown(self, app):
        missing = await self._request(
            app, _user("alice"), "GET", f"/api/v1/export/status/{JOB_ID}", None
        )
        foreign = await self._request(
            app, _user("alice"), "GET", f"/api/v1/export/status/{JOB_ID}", _job(client="bob")
        )
        assert missing.status_code == 404
        assert foreign.status_code == 404
        assert foreign.json()["detail"] == missing.json()["detail"]

    async def test_own_status_is_200(self, app):
        resp = await self._request(
            app, _user("alice"), "GET", f"/api/v1/export/status/{JOB_ID}", _job(client="alice")
        )
        assert resp.status_code == 200
        assert resp.json()["job_id"] == JOB_ID

    async def test_admin_status_sees_foreign(self, app):
        resp = await self._request(
            app, _admin(), "GET", f"/api/v1/export/status/{JOB_ID}", _job(client="bob")
        )
        assert resp.status_code == 200

    async def test_foreign_pending_download_is_404_not_400(self, app):
        pending = _job(client="bob", status=JobStatus.PENDING)
        resp = await self._request(
            app, _user("alice"), "GET", f"/api/v1/export/download/{JOB_ID}", pending
        )
        assert resp.status_code == 404

    async def test_unknown_download_is_404(self, app):
        resp = await self._request(
            app, _user("alice"), "GET", f"/api/v1/export/download/{JOB_ID}", None
        )
        assert resp.status_code == 404

    async def test_own_completed_download_is_200(self, app, tmp_path: Path):
        path = tmp_path / "raw_messages.json"
        path.write_text("{}", encoding="utf-8")
        job = _job(client="alice", file_path=str(path))
        resp = await self._request(
            app, _user("alice"), "GET", f"/api/v1/export/download/{JOB_ID}", job
        )
        assert resp.status_code == 200
