"""
Webhook notifications for job completion.

Sends HTTP callbacks when processing or export jobs complete.
Supports optional HMAC signature for security.
"""

import asyncio
import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from tg_parser.config import settings

logger = logging.getLogger(__name__)


async def send_webhook(
    url: str,
    payload: dict[str, Any],
    secret: str | None = None,
    max_retries: int | None = None,
    timeout: float | None = None,
) -> bool:
    """
    Send webhook notification with optional HMAC signature.
    
    Args:
        url: Webhook URL to call
        payload: JSON payload to send
        secret: Optional HMAC secret for signature (X-Webhook-Signature)
        max_retries: Max retry attempts (default from settings)
        timeout: HTTP timeout in seconds (default from settings)
        
    Returns:
        True if webhook was delivered successfully, False otherwise
    """
    if max_retries is None:
        max_retries = settings.webhook_max_retries
    if timeout is None:
        timeout = settings.webhook_timeout
    
    # Prepare headers
    headers = {"Content-Type": "application/json"}
    
    # Serialize payload
    body = json.dumps(payload, default=str)
    
    # Add HMAC signature if secret provided
    if secret:
        signature = hmac.new(
            secret.encode("utf-8"),
            body.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        headers["X-Webhook-Signature"] = f"sha256={signature}"
    
    # Add timestamp
    headers["X-Webhook-Timestamp"] = datetime.now(UTC).isoformat()
    
    # Retry loop
    last_error: Exception | None = None
    
    for attempt in range(max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    url,
                    content=body,
                    headers=headers,
                )
                
                if response.status_code < 400:
                    logger.info(
                        f"Webhook delivered successfully to {url}",
                        extra={
                            "webhook_url": url,
                            "status_code": response.status_code,
                            "attempt": attempt + 1,
                        },
                    )
                    return True
                
                # Log non-2xx response
                logger.warning(
                    f"Webhook received non-success response: {response.status_code}",
                    extra={
                        "webhook_url": url,
                        "status_code": response.status_code,
                        "response_body": response.text[:500],
                        "attempt": attempt + 1,
                    },
                )
                
                # Don't retry on 4xx client errors (except 429)
                if 400 <= response.status_code < 500 and response.status_code != 429:
                    return False
                    
        except httpx.TimeoutException as e:
            last_error = e
            logger.warning(
                f"Webhook timeout to {url}",
                extra={
                    "webhook_url": url,
                    "attempt": attempt + 1,
                    "error": str(e),
                },
            )
        except httpx.RequestError as e:
            last_error = e
            logger.warning(
                f"Webhook request error to {url}",
                extra={
                    "webhook_url": url,
                    "attempt": attempt + 1,
                    "error": str(e),
                },
            )
        
        # Exponential backoff before retry
        if attempt < max_retries:
            backoff = 2 ** attempt  # 1s, 2s, 4s, ...
            await asyncio.sleep(backoff)
    
    logger.error(
        f"Webhook delivery failed after {max_retries + 1} attempts to {url}",
        extra={
            "webhook_url": url,
            "last_error": str(last_error) if last_error else None,
        },
    )
    return False


def create_job_completion_payload(
    job_id: str,
    job_type: str,
    status: str,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """
    Create standard webhook payload for job completion.
    
    Args:
        job_id: Unique job identifier
        job_type: "processing" or "export"
        status: Final job status ("completed" or "failed")
        result: Optional result data
        error: Optional error message
        
    Returns:
        Standardized webhook payload
    """
    payload = {
        "event": "job.completed",
        "timestamp": datetime.now(UTC).isoformat(),
        "job": {
            "id": job_id,
            "type": job_type,
            "status": status,
        },
    }
    
    if result is not None:
        payload["job"]["result"] = result
    
    if error is not None:
        payload["job"]["error"] = error
    
    return payload


def verify_webhook_signature(
    body: bytes,
    signature: str,
    secret: str,
) -> bool:
    """
    Verify incoming webhook signature.
    
    Useful for webhook receivers to validate authenticity.
    
    Args:
        body: Raw request body
        signature: X-Webhook-Signature header value
        secret: HMAC secret
        
    Returns:
        True if signature is valid
    """
    if not signature.startswith("sha256="):
        return False
    
    expected_signature = signature[7:]  # Remove "sha256=" prefix
    
    computed_signature = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    
    return hmac.compare_digest(expected_signature, computed_signature)

