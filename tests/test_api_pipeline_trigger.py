"""
HTTP API tests for POST /api/v1/pipeline/trigger (Wave 1 step 3.1 / ADR 0007).
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from tg_parser.api.auth import resolve_current_user
from tg_parser.api.main import create_app
from tg_parser.api.metrics import PIPELINE_TRIGGER_TOTAL, record_pipeline_trigger
from tg_parser.auth.models import CurrentUser
from tg_parser.services.pipeline_dispatch_service import (
    PipelineDispatchError,
    PipelineTriggerAccepted,
    _running_channel_jobs,
)

pg_only = pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES"),
    reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)",
)


def _user(user_id: str, *, role: str = "user", channels: list[str] | None = None) -> CurrentUser:
    return CurrentUser(
        id=user_id,
        name="alice",
        role=role,
        allowed_channel_ids=None if role == "admin" else (channels or []),
        max_channels=100,
    )


def _override_user(app, user: CurrentUser) -> None:
    app.dependency_overrides[resolve_current_user] = lambda: user


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def _idem_db(test_db):
    session = test_db.ingestion_state_session()
    try:
        await session.execute(text("DELETE FROM idempotency_keys"))
        await session.commit()
    finally:
        await session.close()
    return test_db


class TestPipelineTriggerAuthGate:
    async def test_requires_auth_when_api_key_required(self, client, monkeypatch):
        monkeypatch.setattr(
            "tg_parser.config.settings.api_key_required",
            True,
        )
        resp = await client.post(
            "/api/v1/pipeline/trigger",
            json={"channel_id": "ch1", "job": "full_pipeline"},
        )
        assert resp.status_code == 401

    async def test_missing_api_key_returns_401(self, app):
        transport = ASGITransport(app=app)
        with patch("tg_parser.api.auth.settings") as mock:
            mock.api_key_required = True
            mock.api_keys = {"valid-key": "tester"}
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/pipeline/trigger",
                    json={"channel_id": "ch1", "job": "full_pipeline"},
                )
        assert resp.status_code == 401

    async def test_invalid_api_key_returns_403(self, app):
        transport = ASGITransport(app=app)
        with patch("tg_parser.api.auth.settings") as mock:
            mock.api_key_required = True
            mock.api_keys = {"valid-key": "tester"}
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/pipeline/trigger",
                    headers={"X-API-Key": "totally-wrong-key"},
                    json={"channel_id": "ch1", "job": "full_pipeline"},
                )
        assert resp.status_code == 403


class TestPipelineTriggerFunctional:
    def setup_method(self):
        _running_channel_jobs.clear()

    async def test_trigger_success(self, client, app):
        admin = _user("admin-1", role="admin")
        _override_user(app, admin)

        accepted = PipelineTriggerAccepted(job_id="job-abc", created=True)
        with patch(
            "tg_parser.api.routes.pipeline.trigger_pipeline_job",
            new_callable=AsyncMock,
            return_value=accepted,
        ) as mock_trigger:
            resp = await client.post(
                "/api/v1/pipeline/trigger",
                headers={"X-API-Key": "test-key"},
                json={"channel_id": "ch1", "job": "topicization", "force": True},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["job_id"] == "job-abc"
        assert body["created"] is True
        assert body["status"] == "queued"
        assert body["job"] == "topicization"
        mock_trigger.assert_awaited_once()
        call_kwargs = mock_trigger.await_args.kwargs
        assert call_kwargs["channel_id"] == "ch1"
        assert call_kwargs["job"] == "topicization"
        assert call_kwargs["force"] is True

        app.dependency_overrides.clear()

    async def test_force_defaults_false(self, client, app):
        admin = _user("admin-force-default", role="admin")
        _override_user(app, admin)

        accepted = PipelineTriggerAccepted(job_id="job-def", created=True)
        with patch(
            "tg_parser.api.routes.pipeline.trigger_pipeline_job",
            new_callable=AsyncMock,
            return_value=accepted,
        ) as mock_trigger:
            resp = await client.post(
                "/api/v1/pipeline/trigger",
                json={"channel_id": "ch1", "job": "full_pipeline"},
            )

        assert resp.status_code == 200
        assert mock_trigger.await_args.kwargs["force"] is False
        app.dependency_overrides.clear()

    async def test_link_topics_job_accepted(self, client, app):
        admin = _user("admin-link", role="admin")
        _override_user(app, admin)

        accepted = PipelineTriggerAccepted(job_id="job-link", created=True)
        with patch(
            "tg_parser.api.routes.pipeline.trigger_pipeline_job",
            new_callable=AsyncMock,
            return_value=accepted,
        ) as mock_trigger:
            resp = await client.post(
                "/api/v1/pipeline/trigger",
                json={"channel_id": "ch1", "job": "link_topics"},
            )

        assert resp.status_code == 200
        assert resp.json()["job"] == "link_topics"
        assert mock_trigger.await_args.kwargs["job"] == "link_topics"
        app.dependency_overrides.clear()

    async def test_cross_tenant_forbidden(self, client, app):
        user = _user("u1", channels=["owned-ch"])
        _override_user(app, user)

        resp = await client.post(
            "/api/v1/pipeline/trigger",
            json={"channel_id": "foreign-ch", "job": "full_pipeline"},
        )
        assert resp.status_code == 403
        app.dependency_overrides.clear()

    async def test_missing_channel_id_returns_422(self, client, app):
        admin = _user("admin-422", role="admin")
        _override_user(app, admin)

        resp = await client.post(
            "/api/v1/pipeline/trigger",
            json={"job": "full_pipeline"},
        )
        assert resp.status_code == 422
        app.dependency_overrides.clear()

    async def test_invalid_job_enum(self, client, app):
        admin = _user("admin-1", role="admin")
        _override_user(app, admin)

        resp = await client.post(
            "/api/v1/pipeline/trigger",
            json={"channel_id": "ch1", "job": "not_a_job"},
        )
        assert resp.status_code == 422
        app.dependency_overrides.clear()

    async def test_dispatch_error_maps_to_http(self, client, app):
        admin = _user("admin-1", role="admin")
        _override_user(app, admin)

        with patch(
            "tg_parser.api.routes.pipeline.trigger_pipeline_job",
            new_callable=AsyncMock,
            side_effect=PipelineDispatchError(
                error_class="JobAlreadyRunning",
                message="already running",
                status_code=409,
            ),
        ):
            resp = await client.post(
                "/api/v1/pipeline/trigger",
                json={"channel_id": "ch1", "job": "full_pipeline"},
            )

        assert resp.status_code == 409
        body = resp.json()
        assert body["error_class"] == "JobAlreadyRunning"
        app.dependency_overrides.clear()

    async def test_rate_limit_returns_429(self, client, app):
        from tg_parser.api.middleware.rate_limit import limiter

        was_enabled = limiter.enabled
        limiter.enabled = True
        admin = _user("admin-rate", role="admin")
        _override_user(app, admin)

        accepted = PipelineTriggerAccepted(job_id="job-rate", created=True)
        api_key = f"rate-{uuid.uuid4().hex}"
        payload = {"channel_id": "ch1", "job": "full_pipeline"}
        headers = {"X-API-Key": api_key}

        try:
            with patch(
                "tg_parser.api.routes.pipeline.trigger_pipeline_job",
                new_callable=AsyncMock,
                return_value=accepted,
            ):
                for _ in range(30):
                    ok = await client.post(
                        "/api/v1/pipeline/trigger",
                        json=payload,
                        headers=headers,
                    )
                    assert ok.status_code == 200, ok.text

                limited = await client.post(
                    "/api/v1/pipeline/trigger",
                    json=payload,
                    headers=headers,
                )

            assert limited.status_code == 429
            assert "rate" in limited.json().get("error", "").lower()
        finally:
            limiter.enabled = was_enabled
            app.dependency_overrides.clear()


@pytest.fixture
async def user_repo(_idem_db):
    from tg_parser.storage.sqlalchemy.user_repo import SAUserRepo

    session = _idem_db.ingestion_state_session()
    try:
        yield SAUserRepo(session)
    finally:
        await session.close()


@pg_only
class TestPipelineTriggerIdempotency:
    async def test_idempotency_replay_same_job_id_created_false(
        self, client, app, _idem_db, user_repo
    ):
        owner = await user_repo.create_user("pipeline_idem_owner")
        _override_user(app, _user(owner.id, role="admin"))

        accepted = PipelineTriggerAccepted(job_id="job-idem-1", created=True)
        payload = {"channel_id": "ch1", "job": "full_pipeline", "force": False}
        headers = {"Idempotency-Key": "pipeline-k-replay"}

        with patch(
            "tg_parser.api.routes.pipeline.trigger_pipeline_job",
            new_callable=AsyncMock,
            return_value=accepted,
        ) as mock_trigger:
            first = await client.post(
                "/api/v1/pipeline/trigger",
                json=payload,
                headers=headers,
            )
            second = await client.post(
                "/api/v1/pipeline/trigger",
                json=payload,
                headers=headers,
            )

        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        first_body = first.json()
        second_body = second.json()
        assert first_body["created"] is True
        assert second_body["created"] is False
        assert first_body["job_id"] == second_body["job_id"] == "job-idem-1"
        assert mock_trigger.await_count == 1

        session = _idem_db.ingestion_state_session()
        try:
            count = (
                await session.execute(text("SELECT COUNT(*) FROM idempotency_keys"))
            ).fetchone()[0]
            assert count == 1
        finally:
            await session.close()

        app.dependency_overrides.clear()


class TestPipelineTriggerMetrics:
    def test_record_pipeline_trigger_increments_counter(self):
        before = PIPELINE_TRIGGER_TOTAL.labels(
            job="full_pipeline", result="queued", surface="api"
        )._value.get()
        record_pipeline_trigger(job="full_pipeline", result="queued", surface="api")
        after = PIPELINE_TRIGGER_TOTAL.labels(
            job="full_pipeline", result="queued", surface="api"
        )._value.get()
        assert after == pytest.approx(before + 1.0)
