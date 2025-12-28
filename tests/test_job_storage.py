"""
Tests for Persistent Job Storage (Phase 2F).

Tests the Job model, SQLiteJobRepo, and JobStore singleton.
"""

import uuid
from datetime import UTC, datetime

import pytest

from tg_parser.storage.ports import Job, JobType, JobStatus


@pytest.fixture
async def job_store():
    """Initialize and return job store for tests, cleanup after."""
    from tg_parser.api.job_store import get_job_store, JobStore
    
    store = get_job_store()
    await store.init()
    yield store
    # Cleanup: close connection and reset singleton
    await store.close()
    JobStore.reset()


class TestJobModel:
    """Tests for the Job dataclass model."""

    def test_create_processing_job(self):
        """Job can be created with processing type."""
        job = Job(
            job_id="job-123",
            job_type=JobType.PROCESSING,
            status=JobStatus.PENDING,
            created_at=datetime.now(UTC),
            channel_id="test_channel",
        )
        
        assert job.job_id == "job-123"
        assert job.job_type == JobType.PROCESSING
        assert job.status == JobStatus.PENDING
        assert job.channel_id == "test_channel"
        assert job.result is None
        assert job.error is None

    def test_create_export_job(self):
        """Job can be created with export type."""
        job = Job(
            job_id="export-456",
            job_type=JobType.EXPORT,
            status=JobStatus.PENDING,
            created_at=datetime.now(UTC),
            export_format="ndjson",
        )
        
        assert job.job_id == "export-456"
        assert job.job_type == JobType.EXPORT
        assert job.export_format == "ndjson"

    def test_job_progress_default_empty(self):
        """Job progress defaults to empty dict."""
        job = Job(
            job_id="job-789",
            job_type=JobType.PROCESSING,
            status=JobStatus.PENDING,
            created_at=datetime.now(UTC),
        )
        
        assert job.progress == {}

    def test_job_with_client(self):
        """Job tracks authenticated client."""
        job = Job(
            job_id="job-auth",
            job_type=JobType.PROCESSING,
            status=JobStatus.PENDING,
            created_at=datetime.now(UTC),
            client="admin_user",
        )
        
        assert job.client == "admin_user"

    def test_job_with_webhook(self):
        """Job stores webhook configuration."""
        job = Job(
            job_id="job-webhook",
            job_type=JobType.PROCESSING,
            status=JobStatus.PENDING,
            created_at=datetime.now(UTC),
            webhook_url="https://example.com/hook",
            webhook_secret="my-secret",
        )
        
        assert job.webhook_url == "https://example.com/hook"
        assert job.webhook_secret == "my-secret"


class TestJobStatus:
    """Tests for JobStatus enum."""

    def test_job_status_values(self):
        """JobStatus has expected values."""
        assert JobStatus.PENDING.value == "pending"
        assert JobStatus.RUNNING.value == "running"
        assert JobStatus.COMPLETED.value == "completed"
        assert JobStatus.FAILED.value == "failed"

    def test_job_status_is_string_enum(self):
        """JobStatus values are strings."""
        assert JobStatus.PENDING.value == "pending"
        assert JobStatus.RUNNING.value == "running"


class TestJobType:
    """Tests for JobType enum."""

    def test_job_type_values(self):
        """JobType has expected values."""
        assert JobType.PROCESSING.value == "processing"
        assert JobType.EXPORT.value == "export"


class TestJobStore:
    """Tests for JobStore singleton."""

    async def test_job_store_singleton(self, job_store):
        """JobStore returns same instance."""
        from tg_parser.api.job_store import get_job_store
        
        store1 = get_job_store()
        store2 = get_job_store()
        
        assert store1 is store2

    async def test_create_and_get_job(self, job_store):
        """JobStore can create and retrieve jobs."""
        job_id = f"test-{uuid.uuid4()}"
        job = Job(
            job_id=job_id,
            job_type=JobType.PROCESSING,
            status=JobStatus.PENDING,
            created_at=datetime.now(UTC),
            channel_id="test_channel",
        )
        
        await job_store.create_job(job)
        
        retrieved = await job_store.get_job(job_id)
        assert retrieved is not None
        assert retrieved.job_id == job_id
        assert retrieved.status == JobStatus.PENDING
        assert retrieved.channel_id == "test_channel"

    async def test_update_job_status(self, job_store):
        """JobStore can update job status."""
        job_id = f"test-update-{uuid.uuid4()}"
        job = Job(
            job_id=job_id,
            job_type=JobType.PROCESSING,
            status=JobStatus.PENDING,
            created_at=datetime.now(UTC),
        )
        
        await job_store.create_job(job)
        
        # Update to running
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(UTC)
        await job_store.update_job(job)
        
        retrieved = await job_store.get_job(job_id)
        assert retrieved.status == JobStatus.RUNNING
        assert retrieved.started_at is not None

    async def test_update_job_completed(self, job_store):
        """JobStore tracks completed jobs with result."""
        job_id = f"test-complete-{uuid.uuid4()}"
        job = Job(
            job_id=job_id,
            job_type=JobType.EXPORT,
            status=JobStatus.PENDING,
            created_at=datetime.now(UTC),
            export_format="ndjson",
        )
        
        await job_store.create_job(job)
        
        # Complete the job
        job.status = JobStatus.COMPLETED
        job.completed_at = datetime.now(UTC)
        job.result = {"file_count": 10, "record_count": 100}
        job.file_path = "/tmp/export.ndjson"
        await job_store.update_job(job)
        
        retrieved = await job_store.get_job(job_id)
        assert retrieved.status == JobStatus.COMPLETED
        assert retrieved.result == {"file_count": 10, "record_count": 100}
        assert retrieved.file_path == "/tmp/export.ndjson"

    async def test_update_job_failed(self, job_store):
        """JobStore tracks failed jobs with error."""
        job_id = f"test-fail-{uuid.uuid4()}"
        job = Job(
            job_id=job_id,
            job_type=JobType.PROCESSING,
            status=JobStatus.PENDING,
            created_at=datetime.now(UTC),
        )
        
        await job_store.create_job(job)
        
        # Fail the job
        job.status = JobStatus.FAILED
        job.completed_at = datetime.now(UTC)
        job.error = "LLM rate limit exceeded"
        await job_store.update_job(job)
        
        retrieved = await job_store.get_job(job_id)
        assert retrieved.status == JobStatus.FAILED
        assert retrieved.error == "LLM rate limit exceeded"

    async def test_list_jobs(self, job_store):
        """JobStore lists jobs."""
        # Create some jobs
        for i in range(3):
            job = Job(
                job_id=f"test-list-{uuid.uuid4()}",
                job_type=JobType.PROCESSING,
                status=JobStatus.PENDING,
                created_at=datetime.now(UTC),
            )
            await job_store.create_job(job)
        
        jobs = await job_store.list_jobs()
        
        assert isinstance(jobs, list)
        assert len(jobs) >= 3

    async def test_list_jobs_with_status_filter(self, job_store):
        """JobStore filters jobs by status."""
        # Create a completed job
        job_id = f"test-completed-{uuid.uuid4()}"
        job = Job(
            job_id=job_id,
            job_type=JobType.PROCESSING,
            status=JobStatus.COMPLETED,
            created_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        await job_store.create_job(job)
        
        # List only completed
        completed_jobs = await job_store.list_jobs(status=JobStatus.COMPLETED)
        
        assert all(j.status == JobStatus.COMPLETED for j in completed_jobs)

    async def test_get_nonexistent_job_returns_none(self, job_store):
        """JobStore returns None for nonexistent job."""
        result = await job_store.get_job("nonexistent-job-id")
        
        assert result is None

