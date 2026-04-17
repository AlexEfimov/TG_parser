"""
Ownership and permission helpers for F4 Multi-Tenancy (Phase 3).

Centralizes ownership checks used by API, Bot, and MCP layers.
"""

from tg_parser.auth.models import CurrentUser


class PermissionDenied(Exception):
    """Raised when user lacks required permission."""

    def __init__(self, message: str = "Permission denied"):
        self.message = message
        super().__init__(message)


async def assert_channel_access(user: CurrentUser, channel_id: str) -> None:
    """Raise PermissionDenied if user cannot access this channel.

    Admin (allowed_channel_ids=None) always passes.
    """
    if user.allowed_channel_ids is None:
        return
    if channel_id not in user.allowed_channel_ids:
        raise PermissionDenied(f"No access to channel {channel_id}")


def assert_admin(user: CurrentUser) -> None:
    """Raise PermissionDenied if user is not admin."""
    if not user.is_admin:
        raise PermissionDenied("Admin access required")


def check_channel_limit(user: CurrentUser, current_count: int) -> None:
    """Raise PermissionDenied if user reached max_channels.

    Admin (is_admin=True) has no limit.
    """
    if user.is_admin:
        return
    if current_count >= user.max_channels:
        raise PermissionDenied(f"Channel limit reached ({current_count}/{user.max_channels})")
