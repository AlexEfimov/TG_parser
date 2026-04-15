"""
Authentication and authorization (F4 Multi-Tenancy).

Provides CurrentUser model and resolvers used across API, Bot, and MCP layers.
"""

from .models import CurrentUser
from .ownership import PermissionDenied, assert_admin, assert_channel_access, check_channel_limit
from .resolvers import get_default_admin, invalidate_user_cache, resolve_user_by_auth

__all__ = [
    "CurrentUser",
    "PermissionDenied",
    "assert_admin",
    "assert_channel_access",
    "check_channel_limit",
    "get_default_admin",
    "invalidate_user_cache",
    "resolve_user_by_auth",
]
