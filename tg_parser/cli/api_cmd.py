"""
CLI command to run the HTTP API server.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def run_api_server(
    host: str = "0.0.0.0",
    port: int = 8000,
    reload: bool = False,
    workers: int = 1,
    log_level: str = "info",
) -> None:
    """
    Run the HTTP API server.
    
    Args:
        host: Host to bind to
        port: Port to bind to
        reload: Enable auto-reload for development
        workers: Number of worker processes
        log_level: Logging level
    """
    try:
        import uvicorn
    except ImportError:
        logger.error("uvicorn not installed. Run: pip install uvicorn[standard]")
        raise SystemExit(1)
    
    logger.info(f"Starting TG_parser API server on {host}:{port}")
    
    uvicorn.run(
        "tg_parser.api.main:app",
        host=host,
        port=port,
        reload=reload,
        workers=workers if not reload else 1,  # reload incompatible with workers
        log_level=log_level,
    )

