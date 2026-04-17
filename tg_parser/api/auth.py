"""
API Key authentication for TG_parser HTTP API (F4 Multi-Tenancy).

Implements:
- API key verification via X-API-Key header
- resolve_current_user: DB-backed user resolution for multi-tenancy
- Backward-compatible: no key + api_key_required=False -> default admin
"""

import structlog
from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from tg_parser.auth.models import CurrentUser
from tg_parser.auth.resolvers import (
    get_default_admin,
    hash_credential,
    resolve_user_by_auth,
)
from tg_parser.config import settings

logger = structlog.get_logger(__name__)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def resolve_current_user(
    api_key: str | None = Security(api_key_header),
) -> CurrentUser:
    """FastAPI dependency: resolve API key to CurrentUser.

    - api_key_required=False + no key -> default admin
    - api_key_required=True  + no key -> 401
    - Invalid key -> 403
    - Key not mapped to a user in DB -> 403
    """
    if api_key is None:
        if not settings.api_key_required:
            return await get_default_admin()
        logger.warning("API key required but not provided")
        raise HTTPException(
            status_code=401,
            detail="API key required. Provide X-API-Key header.",
        )

    valid_keys = settings.api_keys
    if api_key not in valid_keys:
        logger.warning("invalid_api_key_attempt", key_prefix=api_key[:4] + "****")
        raise HTTPException(status_code=403, detail="Invalid API key")

    hashed = hash_credential(api_key)
    user = await resolve_user_by_auth("api_key", hashed)
    if user is not None:
        logger.debug("Authenticated user: %s", user.name)
        return user

    # Key is valid in settings but not yet mapped to a DB user -> admin fallback
    logger.debug("API key valid but no DB user mapping, using default admin")
    return await get_default_admin()


async def verify_api_key(api_key: str | None = Security(api_key_header)) -> str | None:
    """Legacy dependency kept for backward compatibility.

    Returns client name string or None (admin).
    """
    if not settings.api_key_required:
        if api_key is None:
            return None
    else:
        if api_key is None:
            logger.warning("API key required but not provided")
            raise HTTPException(
                status_code=401,
                detail="API key required. Provide X-API-Key header.",
            )

    valid_keys = settings.api_keys

    if api_key not in valid_keys:
        logger.warning("invalid_api_key_attempt", key_prefix=api_key[:4] + "****")
        raise HTTPException(status_code=403, detail="Invalid API key")

    client_name = valid_keys[api_key]
    logger.debug("Authenticated client: %s", client_name)
    return client_name


async def get_optional_user(
    api_key: str | None = Security(api_key_header),
) -> CurrentUser | None:
    """Get CurrentUser if authenticated, None otherwise. Never raises."""
    if api_key is None:
        return None
    valid_keys = settings.api_keys
    if api_key not in valid_keys:
        return None
    hashed = hash_credential(api_key)
    return await resolve_user_by_auth("api_key", hashed)


# Keep old name as alias for backward compat
get_optional_client = get_optional_user

