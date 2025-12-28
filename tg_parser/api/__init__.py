"""
TG_parser HTTP API (v2.0).

FastAPI-based HTTP API for message processing and export.

Phase 2F additions:
- API key authentication (auth.py)
- Rate limiting middleware (middleware/rate_limit.py)
- Request logging middleware (middleware/logging.py)
- Webhook notifications (webhooks.py)
"""

from tg_parser.api.auth import verify_api_key
from tg_parser.api.main import create_app
from tg_parser.api.webhooks import send_webhook, verify_webhook_signature

__all__ = [
    "create_app",
    "verify_api_key",
    "send_webhook",
    "verify_webhook_signature",
]

