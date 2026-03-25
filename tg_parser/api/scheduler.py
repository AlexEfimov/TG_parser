"""
Backward-compatibility shim — real code lives in services/background_scheduler.py.

All symbols are re-exported so existing imports continue to work.
This file can be removed once all callers migrate their imports.
"""

from tg_parser.services.background_scheduler import (  # noqa: F401
    BackgroundScheduler,
    cleanup_expired_records,
    get_scheduler,
    health_check_task,
    setup_default_tasks,
)
from tg_parser.services.scheduler_service import (  # noqa: F401
    incremental_pipeline_task,
)
