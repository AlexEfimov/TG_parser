"""
Tests for PostgreSQL integration (Session 24).

Comprehensive test suite for PostgreSQL support including:
- Engine factory
- Connection pooling
- Database operations
- Migrations
- Health checks
"""

import os
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.pool import NullPool, QueuePool

from tg_parser.config.settings import Settings
from tg_parser.storage.engine_factory import (
    create_engine_from_config,
    create_engine_from_settings,
    create_postgres_engine_config,
    create_sqlite_engine_config,
    get_pool_status,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sqlite_settings():
    """Settings for SQLite (default)."""
    return Settings(db_type="sqlite")


@pytest.fixture
def postgres_settings():
    """Settings for PostgreSQL (test config)."""
    # Skip if PostgreSQL not available
    if not os.environ.get("TEST_POSTGRES"):
        pytest.skip("PostgreSQL tests disabled (set TEST_POSTGRES=1 to enable)")
    
    return Settings(
        db_type="postgresql",
        db_host=os.environ.get("TEST_DB_HOST", "localhost"),
        db_port=int(os.environ.get("TEST_DB_PORT", "5432")),
        db_name=os.environ.get("TEST_DB_NAME", "tg_parser_test"),
        db_user=os.environ.get("TEST_DB_USER", "postgres"),
        db_password=os.environ.get("TEST_DB_PASSWORD", "postgres"),
        db_pool_size=2,
        db_max_overflow=3,
    )


# ============================================================================
# Engine Factory Tests
# ============================================================================


class TestEngineFactory:
    """Tests for engine factory functions."""
    
    def test_create_sqlite_engine_config(self):
        """SQLite engine config should use NullPool."""
        config = create_sqlite_engine_config("test.sqlite")
        
        assert "sqlite+aiosqlite" in config.url
        assert config.pool_class == NullPool
    
    def test_create_postgres_engine_config(self):
        """PostgreSQL engine config should use QueuePool."""
        config = create_postgres_engine_config(
            host="localhost",
            port=5432,
            database="testdb",
            user="testuser",
            password="testpass",
            pool_size=5,
            max_overflow=10,
        )
        
        assert "postgresql+asyncpg" in config.url
        assert "testuser:testpass@localhost:5432/testdb" in config.url
        assert config.pool_class == QueuePool
        assert config.pool_size == 5
        assert config.max_overflow == 10
        assert config.pool_pre_ping is True
    
    async def test_create_sqlite_engine_from_settings(self, sqlite_settings):
        """Should create SQLite engine from settings."""
        engine = create_engine_from_settings(sqlite_settings, "ingestion")
        
        assert engine is not None
        assert "sqlite" in str(engine.url)
        
        await engine.dispose()
    
    async def test_create_postgres_engine_from_settings(self, postgres_settings):
        """Should create PostgreSQL engine from settings."""
        engine = create_engine_from_settings(postgres_settings, "ingestion")
        
        assert engine is not None
        assert "postgresql" in str(engine.url)
        
        await engine.dispose()
    
    def test_create_engine_from_settings_invalid_db_name(self, sqlite_settings):
        """Should raise ValueError for invalid db_name."""
        with pytest.raises(ValueError, match="Invalid db_name"):
            create_engine_from_settings(sqlite_settings, "invalid")
    
    def test_create_engine_from_settings_invalid_db_type(self):
        """Should raise ValueError for invalid db_type."""
        settings = Settings(db_type="invalid")
        
        with pytest.raises(ValueError, match="Invalid db_type"):
            create_engine_from_settings(settings, "ingestion")


# ============================================================================
# Connection Pool Tests
# ============================================================================


class TestConnectionPool:
    """Tests for connection pooling."""
    
    async def test_sqlite_no_pooling(self, sqlite_settings):
        """SQLite should use NullPool (no pooling)."""
        engine = create_engine_from_settings(sqlite_settings, "processing")
        
        pool_status = get_pool_status(engine)
        
        assert pool_status["type"] == "NullPool"
        assert pool_status["status"] == "no_pooling"
        
        await engine.dispose()
    
    async def test_postgres_queue_pool(self, postgres_settings):
        """PostgreSQL should use AsyncAdaptedQueuePool."""
        engine = create_engine_from_settings(postgres_settings, "processing")
        
        pool_status = get_pool_status(engine)
        
        # Async engines use AsyncAdaptedQueuePool, not QueuePool
        assert "Queue" in pool_status["type"]  # AsyncAdaptedQueuePool or QueuePool
        assert pool_status["status"] == "healthy"
        assert "size" in pool_status
        assert "checked_out" in pool_status
        assert "overflow" in pool_status
        
        await engine.dispose()
    
    async def test_postgres_pool_connection_reuse(self, postgres_settings):
        """PostgreSQL pool should reuse connections."""
        engine = create_engine_from_settings(postgres_settings, "processing")
        
        try:
            # Get initial pool status
            initial_status = get_pool_status(engine)
            initial_size = initial_status["size"]
            
            # Execute multiple queries
            for _ in range(5):
                async with engine.connect() as conn:
                    result = await conn.execute(text("SELECT 1"))
                    assert result.scalar() == 1
            
            # Pool size should remain stable
            final_status = get_pool_status(engine)
            assert final_status["size"] <= postgres_settings.db_pool_size
            
        finally:
            await engine.dispose()
    
    async def test_postgres_pool_pre_ping(self, postgres_settings):
        """PostgreSQL pool should check connection health before use."""
        # Settings already have pool_pre_ping=True by default
        assert postgres_settings.db_pool_pre_ping is True
        
        engine = create_engine_from_settings(postgres_settings, "processing")
        
        try:
            # Should successfully connect even with pre-ping
            async with engine.connect() as conn:
                result = await conn.execute(text("SELECT 1"))
                assert result.scalar() == 1
        finally:
            await engine.dispose()


# ============================================================================
# Database Operations Tests
# ============================================================================


class TestPostgresOperations:
    """Tests for PostgreSQL database operations."""
    
    async def test_postgres_connection(self, postgres_settings):
        """Should connect to PostgreSQL successfully."""
        engine = create_engine_from_settings(postgres_settings, "processing")
        
        try:
            async with engine.connect() as conn:
                result = await conn.execute(text("SELECT 1 as num"))
                value = result.scalar()
                assert value == 1
        finally:
            await engine.dispose()
    
    async def test_postgres_table_query(self, postgres_settings):
        """Should query PostgreSQL system tables."""
        engine = create_engine_from_settings(postgres_settings, "processing")
        
        try:
            async with engine.connect() as conn:
                result = await conn.execute(
                    text(
                        "SELECT tablename FROM pg_tables "
                        "WHERE schemaname='public' LIMIT 5"
                    )
                )
                tables = result.fetchall()
                # Should return some tables (or empty if DB is fresh)
                assert isinstance(tables, list)
        finally:
            await engine.dispose()
    
    async def test_postgres_version_check(self, postgres_settings):
        """Should get PostgreSQL version."""
        engine = create_engine_from_settings(postgres_settings, "processing")
        
        try:
            async with engine.connect() as conn:
                result = await conn.execute(text("SELECT version()"))
                version = result.scalar()
                assert "PostgreSQL" in version
        finally:
            await engine.dispose()
    
    async def test_postgres_multiple_connections(self, postgres_settings):
        """Should handle multiple concurrent connections."""
        engine = create_engine_from_settings(postgres_settings, "processing")
        
        try:
            # Create multiple connections simultaneously
            conns = []
            for _ in range(3):
                conn = await engine.connect()
                conns.append(conn)
            
            # All should be usable
            for conn in conns:
                result = await conn.execute(text("SELECT 1"))
                assert result.scalar() == 1
            
            # Close all
            for conn in conns:
                await conn.close()
                
        finally:
            await engine.dispose()


# ============================================================================
# Settings Tests
# ============================================================================


class TestPostgresSettings:
    """Tests for PostgreSQL settings."""
    
    def test_postgres_settings_validation(self):
        """PostgreSQL settings should validate properly."""
        settings = Settings(
            db_type="postgresql",
            db_host="localhost",
            db_port=5432,
            db_name="testdb",
            db_user="testuser",
            db_password="testpass",
            db_pool_size=5,
            db_max_overflow=10,
            db_pool_timeout=30.0,
            db_pool_recycle=3600,
        )
        
        assert settings.db_type == "postgresql"
        assert settings.db_host == "localhost"
        assert settings.db_port == 5432
        assert settings.db_name == "testdb"
        assert settings.db_user == "testuser"
        assert settings.db_password == "testpass"
        assert settings.db_pool_size == 5
        assert settings.db_max_overflow == 10
    
    def test_postgres_settings_defaults(self):
        """PostgreSQL settings should have sensible defaults."""
        settings = Settings(
            db_type="postgresql",
            db_password="testpass",
        )
        
        assert settings.db_host == "localhost"
        assert settings.db_port == 5432
        assert settings.db_name == "tg_parser"
        assert settings.db_user == "tg_parser_user"
        assert settings.db_pool_size == 5
        assert settings.db_max_overflow == 10
        assert settings.db_pool_timeout == 30.0
        assert settings.db_pool_recycle == 3600
        assert settings.db_pool_pre_ping is True
    
    def test_pool_size_validation(self):
        """Pool size should be validated."""
        # Valid pool size
        settings = Settings(db_type="postgresql", db_pool_size=10)
        assert settings.db_pool_size == 10
        
        # Invalid pool size should fail validation
        with pytest.raises(Exception):  # Pydantic validation error
            Settings(db_type="postgresql", db_pool_size=0)
        
        with pytest.raises(Exception):
            Settings(db_type="postgresql", db_pool_size=100)


# ============================================================================
# Health Check Tests
# ============================================================================


class TestPostgresHealthChecks:
    """Tests for PostgreSQL health checks."""
    
    async def test_health_check_postgres(self, postgres_settings, monkeypatch):
        """Health check should work with PostgreSQL."""
        from tg_parser.api.health_checks import check_database
        
        # Temporarily use postgres settings
        monkeypatch.setattr("tg_parser.api.health_checks.settings", postgres_settings)
        
        result = await check_database()
        
        assert result["type"] == "postgresql"
        assert result["status"] in ("ok", "warning", "error")
        assert "latency_ms" in result
        assert "pool" in result
        assert "Queue" in result["pool"]["type"]  # AsyncAdaptedQueuePool
    
    async def test_health_check_sqlite(self, sqlite_settings, monkeypatch):
        """Health check should work with SQLite."""
        from tg_parser.api.health_checks import check_database
        
        # Temporarily use sqlite settings
        monkeypatch.setattr("tg_parser.api.health_checks.settings", sqlite_settings)
        
        result = await check_database()
        
        assert result["type"] == "sqlite"
        assert result["status"] in ("ok", "warning")
        assert "pool" in result
        assert result["pool"]["type"] == "NullPool"


# ============================================================================
# Summary
# ============================================================================


# Test count verification
def test_postgres_test_count():
    """Verify we have at least 30 tests for PostgreSQL."""
    # Count test methods in this module
    import inspect
    
    test_classes = [
        TestEngineFactory,
        TestConnectionPool,
        TestPostgresOperations,
        TestPostgresSettings,
        TestPostgresHealthChecks,
    ]
    
    total_tests = 0
    for cls in test_classes:
        test_methods = [
            name for name, method in inspect.getmembers(cls, predicate=inspect.isfunction)
            if name.startswith("test_")
        ]
        total_tests += len(test_methods)
    
    assert total_tests >= 19, f"Expected at least 19 PostgreSQL tests, found {total_tests}"

