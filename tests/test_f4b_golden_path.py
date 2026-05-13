"""F4-B Core — Phase 5 end-to-end golden path test.

Mirror the scenario from the start prompt § "Golden-path test":

1. Create one user.
2. Create two workspaces ("AI", "Product").
3. Add three channels into "AI" (one of them also into "Product").
4. ``list_workspace_sources(workspace_id=AI)`` returns the AI channels.
5. ``list_workspace_sources(workspace_id=Product)`` returns just the shared channel.
6. ``effective_channel_ids(user, AI)`` ⊆ ``user.allowed_channel_ids``.
7. ``effective_channel_ids(user, Product)`` ⊆ ``user.allowed_channel_ids``.
8. ``effective_channel_ids(user, None)`` is bit-for-bit ``user.allowed_channel_ids``.
9. ``delete_workspace(AI)`` removes the AI workspace; the shared channel
   remains visible through ``Product``; ``sources`` rows are untouched.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from tg_parser.auth.models import CurrentUser
from tg_parser.services.workspace_service import WorkspaceService
from tg_parser.storage.ports import Source
from tg_parser.storage.sqlalchemy.ingestion_state_repo import SAIngestionStateRepo
from tg_parser.storage.sqlalchemy.user_repo import SAUserRepo
from tg_parser.storage.sqlalchemy.workspace_repo import SAWorkspaceRepo

pg_only = pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES"),
    reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)",
)


@pg_only
async def test_golden_path_workspace_lifecycle(test_db):
    session = test_db.ingestion_state_session()
    try:
        user_repo = SAUserRepo(session)
        source_repo = SAIngestionStateRepo(session)
        ws_repo = SAWorkspaceRepo(session)
        svc = WorkspaceService(ws_repo)

        owner = await user_repo.create_user("golden_alice")
        user = CurrentUser(
            id=owner.id,
            name="golden_alice",
            role="user",
            allowed_channel_ids=["ch_g1", "ch_g2", "ch_g3"],
            max_channels=10,
        )

        for src_id, channel_id in [
            ("tg:src_g1", "ch_g1"),
            ("tg:src_g2", "ch_g2"),
            ("tg:src_g3", "ch_g3"),
        ]:
            await source_repo.upsert_source(
                Source(
                    source_id=src_id,
                    channel_id=channel_id,
                    status="active",
                    include_comments=False,
                    fail_count=0,
                    comments_unavailable=False,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                    owner_id=owner.id,
                )
            )

        ai = await svc.create_workspace(user, name="AI", description="AI thinking")
        product = await svc.create_workspace(user, name="Product", description="Product ops")

        await svc.add_source(user, ai.id, "ch_g1")
        await svc.add_source(user, ai.id, "ch_g2")
        await svc.add_source(user, ai.id, "ch_g3")
        await svc.add_source(user, product.id, "ch_g3")

        ai_channels = sorted(await svc.list_workspace_sources(user, ai.id))
        product_channels = sorted(await svc.list_workspace_sources(user, product.id))
        assert ai_channels == ["ch_g1", "ch_g2", "ch_g3"]
        assert product_channels == ["ch_g3"]

        ai_effective = sorted(await svc.effective_channel_ids(user, ai.id))
        product_effective = sorted(await svc.effective_channel_ids(user, product.id))
        null_effective = await svc.effective_channel_ids(user, None)
        assert ai_effective == ["ch_g1", "ch_g2", "ch_g3"]
        assert product_effective == ["ch_g3"]
        assert null_effective == ["ch_g1", "ch_g2", "ch_g3"]

        deleted = await svc.delete_workspace(user, ai.id)
        assert deleted is True

        remaining_workspaces = await svc.list_workspaces(user)
        assert [ws.name for ws in remaining_workspaces] == ["Product"]

        product_after_delete = sorted(await svc.list_workspace_sources(user, product.id))
        assert product_after_delete == ["ch_g3"]

        sources_check = await source_repo.get_source("tg:src_g1")
        assert sources_check is not None
        assert sources_check.channel_id == "ch_g1"
    finally:
        await session.close()
