"""BUG-096: export path is keyed by job_id; old flat paths still download.

Covers the writer-side collision (two HTTP exports of the same level) and
the legacy ``file_path = output/raw_messages.json`` layout left by session #1.
MCP must not import ``tg_parser.api.routes.export``. Bot writes to a unique
subdirectory and does not create a Job.
"""

from __future__ import annotations

import ast
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from tg_parser.api.auth import resolve_current_user
from tg_parser.api.main import create_app
from tg_parser.api.schemas import ExportFormat, ExportLevel, ExportRequest
from tg_parser.auth.models import CurrentUser
from tg_parser.storage.ports import Job, JobStatus, JobType

NOW = datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)


def _admin() -> CurrentUser:
    return CurrentUser(
        id="admin-1", name="admin", role="admin", allowed_channel_ids=None, max_channels=100
    )


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    app.dependency_overrides[resolve_current_user] = _admin
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _fake_run_export(*, output_dir, **_kwargs):
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    artefact = path / "raw_messages.json"
    artefact.write_text(
        json.dumps({"messages": [{"id": path.name, "text": "seed"}]}),
        encoding="utf-8",
    )
    return {
        "raw_posts_count": 1,
        "raw_comments_count": 0,
        "raw_orphan_comments_count": 0,
        "channels_count": 1,
    }


class TestTwoHttpExportsWriteDistinctFiles:
    async def test_two_raw_exports_do_not_share_file_path(self, client, tmp_path, monkeypatch):
        from tg_parser.api.job_store import ensure_job_store_initialized
        from tg_parser.api.routes.export import _run_export_job
        from tg_parser.config import settings

        monkeypatch.setattr(settings, "output_dir", str(tmp_path))
        monkeypatch.setattr("tg_parser.api.routes.export.run_export", _fake_run_export)

        first = await client.post(
            "/api/v1/export",
            json={"channel_id": "ch1", "level": "raw", "format": "json"},
        )
        second = await client.post(
            "/api/v1/export",
            json={"channel_id": "ch1", "level": "raw", "format": "json"},
        )
        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        job_id_1 = first.json()["job_id"]
        job_id_2 = second.json()["job_id"]
        assert job_id_1 != job_id_2

        request = ExportRequest(channel_id="ch1", level=ExportLevel.RAW, format=ExportFormat.JSON)
        store = await ensure_job_store_initialized()
        for job_id in (job_id_1, job_id_2):
            job = await store.get_job(job_id)
            assert job is not None
            if job.status != JobStatus.COMPLETED:
                await _run_export_job(job_id, request)

        job_1 = await store.get_job(job_id_1)
        job_2 = await store.get_job(job_id_2)
        assert job_1 is not None and job_2 is not None
        assert job_1.file_path
        assert job_2.file_path
        assert job_1.file_path != job_2.file_path
        assert job_id_1 in job_1.file_path
        assert job_id_2 in job_2.file_path
        assert Path(job_1.file_path).is_file()
        assert Path(job_2.file_path).is_file()
        assert Path(job_1.file_path).read_text(encoding="utf-8") != Path(job_2.file_path).read_text(
            encoding="utf-8"
        )

        dl_1 = await client.get(f"/api/v1/export/download/{job_id_1}")
        dl_2 = await client.get(f"/api/v1/export/download/{job_id_2}")
        assert dl_1.status_code == 200, dl_1.text
        assert dl_2.status_code == 200, dl_2.text
        assert "raw_payload" not in dl_1.text
        assert "raw_payload" not in dl_2.text


class TestLegacyFlatFilePathDownloads:
    async def test_completed_job_with_flat_relative_path_is_200(self, client, tmp_path, monkeypatch):
        from tg_parser.api.job_store import ensure_job_store_initialized

        monkeypatch.chdir(tmp_path)
        (tmp_path / "output").mkdir()
        flat = tmp_path / "output" / "raw_messages.json"
        flat.write_text(json.dumps({"messages": [{"id": "legacy"}]}), encoding="utf-8")

        job_id = str(uuid.uuid4())
        store = await ensure_job_store_initialized()
        await store.create_job(
            Job(
                job_id=job_id,
                job_type=JobType.EXPORT,
                status=JobStatus.COMPLETED,
                created_at=NOW,
                completed_at=NOW,
                channel_id="ch1",
                client="admin",
                export_format="json",
                file_path="output/raw_messages.json",
                download_url=f"/api/v1/export/download/{job_id}",
                progress={"level": "raw"},
                result={"format": "json", "level": "raw", "file_size": flat.stat().st_size},
            )
        )

        resp = await client.get(f"/api/v1/export/download/{job_id}")
        assert resp.status_code == 200
        assert "legacy" in resp.text
        assert "raw_payload" not in resp.text


class TestMcpDoesNotImportApiRoutesExport:
    def test_mcp_server_has_no_api_routes_export_import(self):
        source = Path("tg_parser/mcp_server.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "tg_parser.api.routes.export"
            ):
                raise AssertionError(
                    f"mcp_server.py must not import api.routes.export (line {node.lineno})"
                )
        assert "tg_parser.api.routes.export" not in source


class TestBotExportUsesUniqueDirectory:
    async def test_two_bot_exports_do_not_share_output_dir(self, monkeypatch, tmp_path):
        from tg_parser.bot.tools import _exec_export_channel
        from tg_parser.config import settings

        seen: list[str] = []

        async def fake_assert(_user, _channel_id):
            return None

        async def fake_run_export(*, output_dir, **_kwargs):
            seen.append(output_dir)
            file_path = Path(output_dir) / "raw_messages.json"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(json.dumps({"messages": []}), encoding="utf-8")
            return {
                "raw_posts_count": 0,
                "raw_comments_count": 0,
                "raw_orphan_comments_count": 0,
                "channels_count": 1,
            }

        user = CurrentUser(
            id="u1", name="tester", role="user", allowed_channel_ids=None, max_channels=20
        )
        monkeypatch.setattr("tg_parser.auth.ownership.assert_channel_access", fake_assert)
        monkeypatch.setattr("tg_parser.services.export_service.run_export", fake_run_export)
        monkeypatch.setattr(settings, "output_dir", str(tmp_path))

        first = await _exec_export_channel(
            {"channel_id": "ch1", "level": "raw", "format": "json"},
            current_user=user,
        )
        second = await _exec_export_channel(
            {"channel_id": "ch1", "level": "raw", "format": "json"},
            current_user=user,
        )

        assert first.get("sent") is False
        assert second.get("sent") is False
        assert len(seen) == 2
        assert seen[0] != seen[1]
        assert Path(seen[0]).parent == tmp_path
        assert Path(seen[1]).parent == tmp_path
        assert (Path(seen[0]) / "raw_messages.json").is_file()
        assert (Path(seen[1]) / "raw_messages.json").is_file()
