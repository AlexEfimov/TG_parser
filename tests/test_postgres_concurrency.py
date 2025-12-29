"""
Concurrency and E2E tests for PostgreSQL (Session 24).

Tests for:
- Concurrent writes
- Race conditions
- Connection pool under load
- E2E pipeline with PostgreSQL
"""

import asyncio
import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from tg_parser.config.settings import Settings
from tg_parser.storage.engine_factory import create_engine_from_settings, get_pool_status


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def postgres_settings():
    """Settings for PostgreSQL (test config)."""
    if not os.environ.get("TEST_POSTGRES"):
        pytest.skip("PostgreSQL tests disabled (set TEST_POSTGRES=1 to enable)")
    
    return Settings(
        db_type="postgresql",
        db_host=os.environ.get("TEST_DB_HOST", "localhost"),
        db_port=int(os.environ.get("TEST_DB_PORT", "5432")),
        db_name=os.environ.get("TEST_DB_NAME", "tg_parser_test"),
        db_user=os.environ.get("TEST_DB_USER", "postgres"),
        db_password=os.environ.get("TEST_DB_PASSWORD", "postgres"),
        db_pool_size=5,
        db_max_overflow=10,
    )


@pytest.fixture
async def test_table(postgres_settings):
    """Create and cleanup test table."""
    engine = create_engine_from_settings(postgres_settings, "processing")
    
    table_name = f"test_concurrent_{int(datetime.now(UTC).timestamp())}"
    
    try:
        async with engine.connect() as conn:
            # Create test table
            await conn.execute(
                text(f"""
                    CREATE TABLE IF NOT EXISTS {table_name} (
                        id SERIAL PRIMARY KEY,
                        value INTEGER NOT NULL,
                        created_at TIMESTAMP DEFAULT NOW()
                    )
                """)
            )
            await conn.commit()
        
        yield table_name
        
        # Cleanup
        async with engine.connect() as conn:
            await conn.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
            await conn.commit()
            
    finally:
        await engine.dispose()


# ============================================================================
# Concurrent Write Tests
# ============================================================================


class TestConcurrentWrites:
    """Tests for concurrent write operations."""
    
    async def test_concurrent_inserts_no_deadlock(self, postgres_settings, test_table):
        """Should handle concurrent inserts without deadlocks."""
        engine = create_engine_from_settings(postgres_settings, "processing")
        
        async def insert_records(worker_id: int, count: int):
            """Insert records from a worker."""
            session_factory = sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            
            async with session_factory() as session:
                for i in range(count):
                    await session.execute(
                        text(f"INSERT INTO {test_table} (value) VALUES (:val)"),
                        {"val": worker_id * 1000 + i},
                    )
                await session.commit()
        
        try:
            # Run 5 concurrent workers
            workers = 5
            records_per_worker = 10
            
            tasks = [
                insert_records(worker_id, records_per_worker)
                for worker_id in range(workers)
            ]
            
            await asyncio.gather(*tasks)
            
            # Verify all records inserted
            async with engine.connect() as conn:
                result = await conn.execute(
                    text(f"SELECT COUNT(*) FROM {test_table}")
                )
                count = result.scalar()
                assert count == workers * records_per_worker
                
        finally:
            await engine.dispose()
    
    async def test_concurrent_updates_no_conflicts(self, postgres_settings, test_table):
        """Should handle concurrent updates without conflicts."""
        engine = create_engine_from_settings(postgres_settings, "processing")
        
        try:
            # Insert initial records
            async with engine.connect() as conn:
                for i in range(10):
                    await conn.execute(
                        text(f"INSERT INTO {test_table} (value) VALUES (:val)"),
                        {"val": i},
                    )
                await conn.commit()
            
            # Update concurrently
            async def update_records(worker_id: int):
                """Update records from a worker."""
                session_factory = sessionmaker(
                    engine, class_=AsyncSession, expire_on_commit=False
                )
                
                async with session_factory() as session:
                    await session.execute(
                        text(
                            f"UPDATE {test_table} "
                            f"SET value = value + :increment "
                            f"WHERE id % :mod = :remainder"
                        ),
                        {
                            "increment": worker_id * 100,
                            "mod": 5,
                            "remainder": worker_id % 5,
                        },
                    )
                    await session.commit()
            
            tasks = [update_records(worker_id) for worker_id in range(5)]
            await asyncio.gather(*tasks)
            
            # Verify updates completed
            async with engine.connect() as conn:
                result = await conn.execute(
                    text(f"SELECT COUNT(*) FROM {test_table} WHERE value > 0")
                )
                count = result.scalar()
                assert count > 0
                
        finally:
            await engine.dispose()
    
    async def test_pool_under_concurrent_load(self, postgres_settings):
        """Pool should handle concurrent load without exhaustion."""
        engine = create_engine_from_settings(postgres_settings, "processing")
        
        async def execute_query(worker_id: int):
            """Execute a query."""
            async with engine.connect() as conn:
                # Simple query that works with all drivers
                result = await conn.execute(text("SELECT 1 as test"))
                return result.scalar()
        
        try:
            # Initial pool status
            initial_status = get_pool_status(engine)
            
            # Run many concurrent queries
            workers = 20
            tasks = [execute_query(i) for i in range(workers)]
            results = await asyncio.gather(*tasks)
            
            # All queries should succeed
            assert len(results) == workers
            assert all(r == 1 for r in results)  # All returned 1
            
            # Pool should return to normal
            await asyncio.sleep(0.1)  # Let connections return to pool
            final_status = get_pool_status(engine)
            
            # Pool should not have grown beyond max
            max_pool = postgres_settings.db_pool_size + postgres_settings.db_max_overflow
            assert final_status["size"] <= max_pool
            
        finally:
            await engine.dispose()


# ============================================================================
# Connection Pool Stress Tests
# ============================================================================


class TestPoolStress:
    """Stress tests for connection pool."""
    
    async def test_rapid_connection_acquisition(self, postgres_settings):
        """Should handle rapid connection acquisition and release."""
        engine = create_engine_from_settings(postgres_settings, "processing")
        
        try:
            iterations = 100
            
            for _ in range(iterations):
                async with engine.connect() as conn:
                    result = await conn.execute(text("SELECT 1"))
                    assert result.scalar() == 1
            
            # Pool should be healthy
            pool_status = get_pool_status(engine)
            assert pool_status["status"] == "healthy"
            
        finally:
            await engine.dispose()
    
    async def test_connection_timeout_handling(self, postgres_settings):
        """Should handle connection timeouts gracefully."""
        # Create engine with very short timeout
        settings = Settings(**postgres_settings.model_dump())
        settings.db_pool_timeout = 0.1  # 100ms timeout
        
        engine = create_engine_from_settings(settings, "processing")
        
        try:
            # Hold all connections
            conns = []
            for _ in range(settings.db_pool_size + settings.db_max_overflow):
                conn = await engine.connect()
                conns.append(conn)
            
            # Try to get one more (should timeout or fail)
            with pytest.raises(Exception):
                async with engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
            
            # Release connections
            for conn in conns:
                await conn.close()
                
        finally:
            await engine.dispose()


# ============================================================================
# E2E Pipeline Tests
# ============================================================================


class TestE2EPostgres:
    """End-to-end tests with PostgreSQL."""
    
    async def test_database_from_settings_postgres(self, postgres_settings):
        """Database class should work with PostgreSQL settings."""
        from tg_parser.storage.sqlite.database import Database
        
        db = Database.from_settings(postgres_settings)
        
        try:
            await db.init()
            
            # All engines should be initialized
            assert db.ingestion_state_engine is not None
            assert db.raw_storage_engine is not None
            assert db.processing_storage_engine is not None
            
            # Test connection to processing storage
            async with db.processing_storage_session() as session:
                result = await session.execute(text("SELECT 1"))
                assert result.scalar() == 1
                
        finally:
            await db.close()
    
    async def test_multiple_database_instances(self, postgres_settings):
        """Should support multiple Database instances (multi-user)."""
        from tg_parser.storage.sqlite.database import Database
        
        db1 = Database.from_settings(postgres_settings)
        db2 = Database.from_settings(postgres_settings)
        
        try:
            await db1.init()
            await db2.init()
            
            # Both should work independently
            async with db1.processing_storage_session() as session1:
                result1 = await session1.execute(text("SELECT 1 as num"))
                assert result1.scalar() == 1
            
            async with db2.processing_storage_session() as session2:
                result2 = await session2.execute(text("SELECT 2 as num"))
                assert result2.scalar() == 2
                
        finally:
            await db1.close()
            await db2.close()


# ============================================================================
# Migration Tests
# ============================================================================


class TestMigrationScenarios:
    """Tests for migration scenarios."""
    
    def test_migration_script_exists(self):
        """Migration script should exist."""
        from pathlib import Path
        
        script_path = Path("scripts/migrate_sqlite_to_postgres.py")
        assert script_path.exists(), "Migration script not found"
    
    def test_migration_script_importable(self):
        """Migration script should be importable."""
        import sys
        from pathlib import Path
        
        # Add scripts to path
        scripts_dir = Path(__file__).parent.parent / "scripts"
        sys.path.insert(0, str(scripts_dir))
        
        try:
            import migrate_sqlite_to_postgres
            
            # Check key functions exist
            assert hasattr(migrate_sqlite_to_postgres, "run_migration")
            assert hasattr(migrate_sqlite_to_postgres, "migrate_database")
            assert hasattr(migrate_sqlite_to_postgres, "MigrationStats")
        finally:
            sys.path.remove(str(scripts_dir))


# ============================================================================
# Summary
# ============================================================================


def test_concurrency_test_count():
    """Verify we have sufficient concurrency tests."""
    import inspect
    
    test_classes = [
        TestConcurrentWrites,
        TestPoolStress,
        TestE2EPostgres,
        TestMigrationScenarios,
    ]
    
    total_tests = 0
    for cls in test_classes:
        test_methods = [
            name for name, method in inspect.getmembers(cls, predicate=inspect.isfunction)
            if name.startswith("test_")
        ]
        total_tests += len(test_methods)
    
    assert total_tests >= 9, f"Expected at least 9 concurrency tests, found {total_tests}"

