"""
Users API routes (F4 Phase 5): user management and current user profile.
"""

from datetime import datetime

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from tg_parser.api.auth import resolve_current_user
from tg_parser.auth.models import CurrentUser
from tg_parser.auth.ownership import assert_admin

router = APIRouter(prefix="/api/v1/users", tags=["Users"])
logger = structlog.get_logger(__name__)


# ── Schemas ──────────────────────────────────────────────────────────────────


class CreateUserRequest(BaseModel):
    name: str
    role: str = "user"
    max_channels: int | None = None


class UpdateUserRequest(BaseModel):
    name: str | None = None
    role: str | None = None
    max_channels: int | None = None
    reset_max_channels: bool = False


class UserResponse(BaseModel):
    id: str
    name: str
    role: str
    max_channels: int | None
    owned_channels_count: int
    created_at: datetime


class UserMeResponse(BaseModel):
    id: str
    name: str
    role: str
    max_channels: int
    owned_channels: list[str]
    owned_channels_count: int


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/me", response_model=UserMeResponse)
async def get_me(user: CurrentUser = Depends(resolve_current_user)):
    """Current user profile with owned channels."""
    from tg_parser.config import settings as app_settings
    from tg_parser.services.db_context import user_repo

    async with user_repo() as (repo, _db):
        channel_ids = await repo.get_owned_channel_ids(user.id)
        db_user = await repo.get_by_id(user.id)

    effective_max = user.max_channels
    if db_user and db_user.max_channels is not None:
        effective_max = db_user.max_channels
    elif db_user:
        effective_max = app_settings.default_max_channels

    return UserMeResponse(
        id=user.id,
        name=user.name,
        role=user.role,
        max_channels=effective_max,
        owned_channels=channel_ids,
        owned_channels_count=len(channel_ids),
    )


@router.get("", response_model=list[UserResponse])
async def list_users(user: CurrentUser = Depends(resolve_current_user)):
    """List all users with owned channel counts. Admin only."""
    from tg_parser.services.db_context import user_repo

    assert_admin(user)

    async with user_repo() as (repo, _db):
        all_users = await repo.list_users()
        results = []
        for u in all_users:
            channel_ids = await repo.get_owned_channel_ids(u.id)
            results.append(UserResponse(
                id=u.id,
                name=u.name,
                role=u.role,
                max_channels=u.max_channels,
                owned_channels_count=len(channel_ids),
                created_at=u.created_at,
            ))
    return results


@router.post("", response_model=UserResponse, status_code=201)
async def create_user(
    body: CreateUserRequest,
    user: CurrentUser = Depends(resolve_current_user),
):
    """Create a new user. Admin only."""
    from tg_parser.services.db_context import user_repo

    assert_admin(user)

    async with user_repo() as (repo, _db):
        new_user = await repo.create_user(body.name, body.role, body.max_channels)
        channel_ids = await repo.get_owned_channel_ids(new_user.id)

    return UserResponse(
        id=new_user.id,
        name=new_user.name,
        role=new_user.role,
        max_channels=new_user.max_channels,
        owned_channels_count=len(channel_ids),
        created_at=new_user.created_at,
    )


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    body: UpdateUserRequest,
    user: CurrentUser = Depends(resolve_current_user),
):
    """Update user properties. Admin only."""
    from typing import Any

    from fastapi import HTTPException

    from tg_parser.services.db_context import user_repo

    assert_admin(user)

    mc_val: Any = ...
    if body.reset_max_channels:
        mc_val = None
    elif body.max_channels is not None:
        mc_val = body.max_channels

    async with user_repo() as (repo, _db):
        updated = await repo.update_user(user_id, name=body.name, role=body.role, max_channels=mc_val)
        if updated is None:
            raise HTTPException(status_code=404, detail=f"User '{user_id}' not found")
        channel_ids = await repo.get_owned_channel_ids(updated.id)

    return UserResponse(
        id=updated.id,
        name=updated.name,
        role=updated.role,
        max_channels=updated.max_channels,
        owned_channels_count=len(channel_ids),
        created_at=updated.created_at,
    )


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: str,
    user: CurrentUser = Depends(resolve_current_user),
):
    """Delete a user and cascade auth mappings. Admin only."""
    from fastapi import HTTPException

    from tg_parser.services.db_context import user_repo

    assert_admin(user)

    async with user_repo() as (repo, _db):
        deleted = await repo.delete_user(user_id)

    if not deleted:
        raise HTTPException(status_code=404, detail=f"User '{user_id}' not found")
