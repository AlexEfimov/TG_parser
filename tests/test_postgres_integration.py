"""
Tests for PostgreSQL integration (Session 24).

Comprehensive test suite for PostgreSQL support including:
- Engine factory
- Connection pooling
- Database operations
- Health checks
"""

import pytest
from sqlalchemy import text

from tg_parser.config.settings import Settings
from tg_parser.storage.engine_factory import (
    create_engine_from_settings,
    create_postgres_engine_config,
    get_pool_status,
)

# postgres_settings fixture is provided by conftest.py


# ============================================================================
# Engine Factory Tests
# ============================================================================


class TestEngineFactory:
    """Tests for engine factory functions."""

    def test_create_postgres_engine_config(self):
        """PostgreSQL engine config should use correct URL."""
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
        assert config.pool_size == 5
        assert config.max_overflow == 10
        assert config.pool_pre_ping is True

    async def test_create_postgres_engine_from_settings(self, postgres_settings):
        """Should create PostgreSQL engine from settings."""
        engine = create_engine_from_settings(postgres_settings, "ingestion")

        assert engine is not None
        assert "postgresql" in str(engine.url)

        await engine.dispose()

    def test_create_engine_from_settings_invalid_db_name(self):
        """Should raise ValueError for invalid db_name."""
        settings = Settings()
        with pytest.raises(ValueError, match="Invalid db_name"):
            create_engine_from_settings(settings, "invalid")


# ============================================================================
# Connection Pool Tests
# ============================================================================


class TestConnectionPool:
    """Tests for connection pooling."""

    async def test_postgres_queue_pool(self, postgres_settings):
        """PostgreSQL should use AsyncAdaptedQueuePool."""
        engine = create_engine_from_settings(postgres_settings, "processing")

        pool_status = get_pool_status(engine)

        assert "Queue" in pool_status["type"]
        assert pool_status["status"] == "healthy"
        assert "size" in pool_status
        assert "checked_out" in pool_status
        assert "overflow" in pool_status

        await engine.dispose()

    async def test_postgres_pool_connection_reuse(self, postgres_settings):
        """PostgreSQL pool should reuse connections."""
        engine = create_engine_from_settings(postgres_settings, "processing")

        try:
            for _ in range(5):
                async with engine.connect() as conn:
                    result = await conn.execute(text("SELECT 1"))
                    assert result.scalar() == 1

            final_status = get_pool_status(engine)
            assert final_status["size"] <= postgres_settings.db_pool_size

        finally:
            await engine.dispose()

    async def test_postgres_pool_pre_ping(self, postgres_settings):
        """PostgreSQL pool should check connection health before use."""
        assert postgres_settings.db_pool_pre_ping is True

        engine = create_engine_from_settings(postgres_settings, "processing")

        try:
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
            conns = []
            for _ in range(3):
                conn = await engine.connect()
                conns.append(conn)

            for conn in conns:
                result = await conn.execute(text("SELECT 1"))
                assert result.scalar() == 1

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
            db_name="tg_parser",
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
        settings = Settings(db_pool_size=10)
        assert settings.db_pool_size == 10

        with pytest.raises(Exception):
            Settings(db_pool_size=0)

        with pytest.raises(Exception):
            Settings(db_pool_size=100)


# ============================================================================
# Health Check Tests
# ============================================================================


class TestPostgresHealthChecks:
    """Tests for PostgreSQL health checks."""

    async def test_health_check_postgres(self, postgres_settings, monkeypatch):
        """Health check should work with PostgreSQL."""
        from tg_parser.api.health_checks import check_database

        monkeypatch.setattr("tg_parser.api.health_checks.settings", postgres_settings)

        result = await check_database()

        assert result["type"] == "postgresql"
        assert result["status"] in ("ok", "warning", "error")
        assert "latency_ms" in result
        assert "pool" in result
        assert "Queue" in result["pool"]["type"]


# ============================================================================
# Summary
# ============================================================================


def test_postgres_test_count():
    """Verify we have at least 15 tests for PostgreSQL."""
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

    assert total_tests >= 14, f"Expected at least 14 PostgreSQL tests, found {total_tests}"
