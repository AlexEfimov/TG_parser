"""
API Key authentication for TG_parser HTTP API.

Implements:
- API key verification via X-API-Key header
- Optional authentication (configurable via settings)
- Client identification for logging
"""

import logging

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from tg_parser.config import settings

logger = logging.getLogger(__name__)

# API key header definition
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str | None = Security(api_key_header)) -> str | None:
    """
    Verify API key and return client identifier.
    
    If API_KEY_REQUIRED is False and no key provided, returns None.
    If API_KEY_REQUIRED is True, key is required.
    
    Args:
        api_key: API key from X-API-Key header
        
    Returns:
        Client name if authenticated, None if auth not required
        
    Raises:
        HTTPException: 401 if key required but missing, 403 if key invalid
    """
    # Check if authentication is required
    if not settings.api_key_required:
        # Auth not required - if key provided, validate it anyway
        if api_key is None:
            return None
    else:
        # Auth required - must have key
        if api_key is None:
            logger.warning("API key required but not provided")
            raise HTTPException(
                status_code=401,
                detail="API key required. Provide X-API-Key header.",
            )
    
    # Validate the provided key
    valid_keys = settings.api_keys
    
    if api_key not in valid_keys:
        logger.warning(f"Invalid API key attempt: {api_key[:8]}...")
        raise HTTPException(
            status_code=403,
            detail="Invalid API key",
        )
    
    client_name = valid_keys[api_key]
    logger.debug(f"Authenticated client: {client_name}")
    return client_name


async def get_optional_client(
    api_key: str | None = Security(api_key_header),
) -> str | None:
    """
    Get client name if authenticated, None otherwise.
    
    For endpoints that work with or without authentication.
    Never raises HTTPException.
    """
    if api_key is None:
        return None
    
    valid_keys = settings.api_keys
    return valid_keys.get(api_key)

