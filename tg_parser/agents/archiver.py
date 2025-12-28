"""
Agent History Archiver.

Phase 3C: Archives expired task history and handoff records to NDJSON.gz files.
"""

import gzip
import json
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tg_parser.storage.ports import HandoffRecord, TaskRecord

logger = logging.getLogger(__name__)


def _serialize_datetime(obj: Any) -> Any:
    """Serialize datetime objects to ISO format."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _record_to_dict(record: TaskRecord | HandoffRecord) -> dict[str, Any]:
    """Convert a record to a JSON-serializable dictionary."""
    data = asdict(record)
    # Convert datetime objects
    for key, value in data.items():
        if isinstance(value, datetime):
            data[key] = value.isoformat()
    return data


class AgentHistoryArchiver:
    """
    Archives expired agent history to compressed NDJSON files.
    
    Features:
    - Archives task history records
    - Optionally archives handoff history
    - Compresses output with gzip
    - Generates timestamped filenames
    """
    
    def __init__(self, archive_path: Path):
        """
        Initialize archiver.
        
        Args:
            archive_path: Base directory for archives
        """
        self._archive_path = archive_path
        self._archive_path.mkdir(parents=True, exist_ok=True)
    
    def _generate_filename(self, prefix: str) -> str:
        """Generate timestamped filename."""
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        return f"{prefix}_{timestamp}.ndjson.gz"
    
    async def archive_task_history(
        self,
        records: list[TaskRecord],
    ) -> Path | None:
        """
        Archive task history records to NDJSON.gz file.
        
        Args:
            records: List of TaskRecord to archive
            
        Returns:
            Path to created archive file, or None if no records
        """
        if not records:
            logger.info("No task history records to archive")
            return None
        
        filename = self._generate_filename("task_history")
        filepath = self._archive_path / filename
        
        # Write compressed NDJSON
        with gzip.open(filepath, "wt", encoding="utf-8") as f:
            for record in records:
                line = json.dumps(_record_to_dict(record), ensure_ascii=False)
                f.write(line + "\n")
        
        logger.info(f"Archived {len(records)} task history records to {filepath}")
        return filepath
    
    async def archive_handoff_history(
        self,
        records: list[HandoffRecord],
    ) -> Path | None:
        """
        Archive handoff history records to NDJSON.gz file.
        
        Args:
            records: List of HandoffRecord to archive
            
        Returns:
            Path to created archive file, or None if no records
        """
        if not records:
            logger.info("No handoff history records to archive")
            return None
        
        filename = self._generate_filename("handoff_history")
        filepath = self._archive_path / filename
        
        # Write compressed NDJSON
        with gzip.open(filepath, "wt", encoding="utf-8") as f:
            for record in records:
                line = json.dumps(_record_to_dict(record), ensure_ascii=False)
                f.write(line + "\n")
        
        logger.info(f"Archived {len(records)} handoff history records to {filepath}")
        return filepath
    
    async def archive_all(
        self,
        task_records: list[TaskRecord],
        handoff_records: list[HandoffRecord] | None = None,
    ) -> dict[str, Path | None]:
        """
        Archive both task and handoff history.
        
        Args:
            task_records: List of TaskRecord to archive
            handoff_records: Optional list of HandoffRecord to archive
            
        Returns:
            Dictionary with paths to created files
        """
        result = {
            "task_history": await self.archive_task_history(task_records),
            "handoff_history": None,
        }
        
        if handoff_records:
            result["handoff_history"] = await self.archive_handoff_history(handoff_records)
        
        return result
    
    def list_archives(self) -> list[dict[str, Any]]:
        """
        List all archive files.
        
        Returns:
            List of archive info dictionaries
        """
        archives = []
        
        for filepath in sorted(self._archive_path.glob("*.ndjson.gz"), reverse=True):
            stat = filepath.stat()
            archives.append({
                "filename": filepath.name,
                "path": str(filepath),
                "size_bytes": stat.st_size,
                "created_at": datetime.fromtimestamp(stat.st_ctime, tz=UTC).isoformat(),
            })
        
        return archives

