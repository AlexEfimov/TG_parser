"""
Request logging middleware.

Provides:
- Automatic request ID generation/propagation (X-Request-ID)
- Structured logging for all requests with structlog (Session 23)
- Request timing metrics
- JSON logging support in production
"""

import time
import uuid
from contextvars import ContextVar

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger(__name__)

# Context variable for request ID (accessible across async context)
request_id_var: ContextVar[str] = ContextVar("request_id", default="")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware for request logging and X-Request-ID propagation.
    
    Features:
    - Generates X-Request-ID if not provided
    - Logs request start/completion with timing
    - Sets request_id in context var for use in other code
    - Returns X-Request-ID in response headers
    """
    
    async def dispatch(self, request: Request, call_next) -> Response:
        """Process request with logging and request ID."""
        # Get or generate request ID
        request_id = request.headers.get("X-Request-ID")
        if not request_id:
            request_id = str(uuid.uuid4())
        
        # Set in context var for access elsewhere
        request_id_var.set(request_id)
        
        # Bind request_id to structlog context for all subsequent logs
        structlog.contextvars.bind_contextvars(request_id=request_id)
        
        # Log request start
        start_time = time.time()
        client_host = request.client.host if request.client else "unknown"
        api_key = request.headers.get("X-API-Key", "")
        api_key_prefix = f"{api_key[:8]}..." if api_key else "none"
        
        logger.info(
            "request_started",
            method=request.method,
            path=request.url.path,
            query=str(request.query_params) if request.query_params else None,
            client_ip=client_host,
            api_key=api_key_prefix,
        )
        
        # Process request
        try:
            response = await call_next(request)
        except Exception as e:
            # Log exception
            duration = time.time() - start_time
            logger.error(
                "request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=round(duration * 1000, 2),
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True,
            )
            # Clear context vars
            structlog.contextvars.clear_contextvars()
            raise
        
        # Calculate duration
        duration = time.time() - start_time
        
        # Log request completion
        logger.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(duration * 1000, 2),
        )
        
        # Add request ID to response headers
        response.headers["X-Request-ID"] = request_id
        
        # Clear context vars after request
        structlog.contextvars.clear_contextvars()
        
        return response


def get_request_id() -> str:
    """
    Get current request ID from context.
    
    Returns empty string if called outside of request context.
    """
    return request_id_var.get()

