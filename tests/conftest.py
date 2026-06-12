"""
Конфигурация pytest для TG_parser.

Общие фикстуры и helpers для тестов.
"""

import os

# IMPORTANT: Disable metrics BEFORE any other imports to prevent
# Prometheus registry conflicts when creating multiple test apps
os.environ["METRICS_ENABLED"] = "false"

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from alembic import command
from alembic.config import Config

# Load .env file into os.environ for SDKs that don't use pydantic-settings
# (e.g., OpenAI SDK, openai-agents)
from dotenv import load_dotenv
from sqlalchemy import text

load_dotenv()

# CRITICAL: Force test database name to prevent tests from touching production.
# load_dotenv() imports DB_NAME from .env (pointing at production), which would
# override the "tg_parser_test" defaults in test fixtures.  We always want tests
# to target the dedicated test database unless explicitly overridden via
# TEST_DB_NAME (e.g. in CI).
_TEST_DB_NAME = os.environ.get("TEST_DB_NAME", "tg_parser_test")
os.environ["DB_NAME"] = _TEST_DB_NAME

from tg_parser.config.settings import Settings  # noqa: E402  # must follow os.environ override
from tg_parser.domain.models import MessageType, RawTelegramMessage  # noqa: E402
from tg_parser.storage.sqlalchemy import Database  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ALEMBIC_BRANCHES = ("ingestion", "raw", "processing")

# Tables to truncate between tests, per logical branch.  Mirrors
# ``EXPECTED_TABLES`` in ``tests/test_migrations_runtime_upgrade.py`` MINUS
# the per-branch ``alembic_version_<branch>`` bookkeeping table — wiping
# that would force the session-scoped alembic fixture to re-upgrade on the
# next access, defeating the cache.
_TRUNCATE_TABLES_BY_BRANCH: dict[str, tuple[str, ...]] = {
    "ingestion": (
        "idempotency_keys",
        "watch_matches",
        "watch_interests",
        "workspace_sources",
        "workspaces",
        "source_attempts",
        "comment_cursors",
        "sources",
        "user_auth_mappings",
        "users",
        "digest_subscriptions",
    ),
    "raw": (
        "raw_conflicts",
        "raw_messages",
    ),
    "processing": (
        "topic_links",
        "handoff_history",
        "task_history",
        "agent_stats",
        "agent_states",
        "topic_card_versions",
        "topic_bundles",
        "topic_cards",
        "processing_failures",
        "processed_documents",
        "document_embeddings",
        "api_jobs",
    ),
}

# ============================================================================
# Database Fixtures
# ============================================================================


def _test_pg_settings() -> Settings:
    """Build Settings pointing at the local PostgreSQL test database."""
    return Settings(
        db_host=os.environ.get("DB_HOST", "localhost"),
        db_port=int(os.environ.get("DB_PORT", "5432")),
        db_name=_TEST_DB_NAME,
        db_user=os.environ.get("DB_USER", "tg_parser_user"),
        db_password=os.environ.get("DB_PASSWORD", ""),
        db_pool_size=2,
        db_max_overflow=3,
        telegram_api_id=12345,
        telegram_api_hash="test_hash",
        telegram_phone="+1234567890",
        openai_api_key="sk-test-key",
    )


def _alembic_upgrade_against_settings(s: Settings, branch: str) -> None:
    """Run ``alembic upgrade head`` for one branch against the ``Settings``-pointed PG.

    Uses the per-DB ``alembic_<branch>.ini`` files landed in DI-7 (Sprint A.5).
    Idempotent: when the DB is already at head this is a no-op (~50 ms).
    First-time invocation on a freshly-created ``tg_parser_test`` DB takes
    ~5–8 s for all three branches combined.

    DI-19 (Sprint A.7): replaces the prior ``init_*_schema(engine)`` calls
    that each test made individually.  Alembic is now the single source of
    truth for the schema in tests, mirroring production.
    """
    cfg = Config(str(_REPO_ROOT / "migrations" / f"alembic_{branch}.ini"))
    cfg.set_main_option(
        "sqlalchemy.url",
        f"postgresql+asyncpg://{s.db_user}:{s.db_password}@{s.db_host}:{s.db_port}/{s.db_name}",
    )
    cfg.set_main_option("db_name", branch)
    command.upgrade(cfg, "head")


def _reset_test_db_schema(s: Settings) -> None:
    """Drop and recreate the ``public`` schema in ``tg_parser_test``.

    Forces a clean slate before alembic runs.  Required because the
    legacy ``init_*_schema(engine)`` helpers (used by the prior
    test_db fixture and by ``init_databases_fallback`` before DI-19)
    leave behind tables WITHOUT any ``alembic_version_<branch>``
    bookkeeping — alembic would then try to apply the initial
    migration on top of pre-existing tables and fail with
    ``DuplicateTableError``.  Mirrors what the CI ``test`` job and the
    testcontainers fixtures already do (fresh DB on each session).

    Safe by construction: ``conftest`` forces ``DB_NAME=tg_parser_test``
    at the top of the file before any imports, so this can never
    target a developer's real DB.
    """
    import psycopg2

    assert s.db_name == _TEST_DB_NAME, (
        f"refusing to drop schema on db_name={s.db_name!r} (expected {_TEST_DB_NAME!r})"
    )
    conn = psycopg2.connect(
        host=s.db_host,
        port=s.db_port,
        dbname=s.db_name,
        user=s.db_user,
        password=s.db_password,
    )
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS public CASCADE")
            cur.execute("CREATE SCHEMA public")
            cur.execute(f'GRANT ALL ON SCHEMA public TO "{s.db_user}"')
            cur.execute("GRANT ALL ON SCHEMA public TO public")
    finally:
        conn.close()


# BUG-056: fixed app-specific advisory-lock key used to serialize the
# session-scoped schema reset across concurrent xdist workers that share the
# single ``tg_parser_test`` database. The exact value is arbitrary but must be
# stable so every worker contends on the same lock.
_SCHEMA_INIT_LOCK_KEY = 0x7C9A0056


def _branch_head_revision(s: Settings, branch: str) -> str | None:
    """Return the head revision id for ``branch`` from its migration scripts."""
    from alembic.script import ScriptDirectory

    cfg = Config(str(_REPO_ROOT / "migrations" / f"alembic_{branch}.ini"))
    cfg.set_main_option(
        "sqlalchemy.url",
        f"postgresql+asyncpg://{s.db_user}:{s.db_password}@{s.db_host}:{s.db_port}/{s.db_name}",
    )
    cfg.set_main_option("db_name", branch)
    return ScriptDirectory.from_config(cfg).get_current_head()


def _db_branch_revision(conn, branch: str) -> str | None:
    """Return the applied revision recorded in ``alembic_version_<branch>``.

    ``None`` when the bookkeeping table is absent (schema never initialized)
    or empty.
    """
    table = f"alembic_version_{branch}"
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (f"public.{table}",))
        if cur.fetchone()[0] is None:
            return None
        cur.execute(f'SELECT version_num FROM "{table}" LIMIT 1')  # noqa: S608 (table is internal)
        row = cur.fetchone()
        return row[0] if row else None


def _test_schema_initialized(conn, s: Settings) -> bool:
    """True when every branch is already at its head revision.

    Lets a late worker (BUG-056) that acquired the advisory lock AFTER a peer
    finished initialization skip the destructive reset entirely instead of
    racing/clobbering a schema other workers may be mid-test against.
    """
    return all(
        _db_branch_revision(conn, branch) == _branch_head_revision(s, branch)
        for branch in _ALEMBIC_BRANCHES
    )


@pytest.fixture(scope="session")
def _alembic_initialized_test_db() -> Settings:
    """Drop+recreate ``public`` schema, then ``alembic upgrade head`` × 3 branches.

    Yields ``Settings`` (NOT a ``Database`` instance) so the per-test
    ``test_db`` fixture can construct a fresh ``Database`` via the
    singleton without colliding with the ``cleanup_job_store`` autouse
    fixture, which calls ``Database.reset_instance()`` after every test.

    BUG-056: the destructive ``DROP SCHEMA``/``CREATE SCHEMA`` + alembic
    upgrades run under a Postgres session-level advisory lock so concurrent
    xdist workers sharing ``tg_parser_test`` serialize. Whichever worker wins
    the lock first does the reset; subsequent workers find the schema already
    at head (``_test_schema_initialized``) and skip the reset rather than
    racing. The lock is always released in ``finally`` (even on error).
    """
    import psycopg2

    s = _test_pg_settings()
    lock_conn = psycopg2.connect(
        host=s.db_host,
        port=s.db_port,
        dbname=s.db_name,
        user=s.db_user,
        password=s.db_password,
    )
    try:
        lock_conn.autocommit = True
        with lock_conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(%s)", (_SCHEMA_INIT_LOCK_KEY,))
        try:
            if not _test_schema_initialized(lock_conn, s):
                _reset_test_db_schema(s)
                for branch in _ALEMBIC_BRANCHES:
                    _alembic_upgrade_against_settings(s, branch)
        finally:
            with lock_conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", (_SCHEMA_INIT_LOCK_KEY,))
    finally:
        lock_conn.close()
    return s


async def _truncate_branch_tables(engine, branch: str) -> None:
    """TRUNCATE all user tables for ``branch`` in dependency-safe order.

    ``CASCADE`` removes inbound-FK rows; ``RESTART IDENTITY`` is included
    for forward-compat with any future SERIAL/IDENTITY columns (current
    schema uses TEXT/UUID PKs, so this is a no-op today but harmless).
    Skips tables that don't exist (defensive against migrations that
    drop a table after this list was last updated).
    """
    tables = _TRUNCATE_TABLES_BY_BRANCH[branch]
    if not tables:
        return
    async with engine.begin() as conn:
        existing = await conn.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename = ANY(:names)"
            ),
            {"names": list(tables)},
        )
        present = {row[0] for row in existing.fetchall()}
        wipe = [t for t in tables if t in present]
        if wipe:
            joined = ", ".join(wipe)
            await conn.execute(text(f"TRUNCATE {joined} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def test_db(_alembic_initialized_test_db):
    """Per-test ``Database`` against ``tg_parser_test``; schema via alembic.

    Schema is up-to-head once per session via ``_alembic_initialized_test_db``;
    this fixture wipes user data with ``TRUNCATE ... CASCADE`` between
    tests so each test sees a deterministic empty state.
    """
    Database.reset_instance()
    s = _alembic_initialized_test_db
    db = Database.get_instance(s)
    await db.init()
    await _truncate_branch_tables(db.ingestion_state_engine, "ingestion")
    await _truncate_branch_tables(db.raw_storage_engine, "raw")
    await _truncate_branch_tables(db.processing_storage_engine, "processing")
    try:
        yield db
    finally:
        await db.close()
        Database.reset_instance()


@pytest.fixture
def test_settings():
    """
    Создать тестовые настройки для приложения.

    Использует PostgreSQL test database и mock Telegram credentials.
    """
    return _test_pg_settings()


@pytest.fixture
def postgres_settings():
    """Settings for PostgreSQL integration tests (requires TEST_POSTGRES=1)."""
    if not os.environ.get("TEST_POSTGRES"):
        pytest.skip("PostgreSQL tests disabled (set TEST_POSTGRES=1 to enable)")
    return _test_pg_settings()


# ============================================================================
# Telethon Mock Helpers
# ============================================================================


def create_mock_telethon_message(
    message_id: int,
    text: str,
    date: datetime | None = None,
    reply_to_msg_id: int | None = None,
    views: int | None = None,
    forwards: int | None = None,
    media: Mock | None = None,
) -> Mock:
    """
    Создать mock Telethon Message.

    Args:
        message_id: ID сообщения
        text: Текст сообщения
        date: Дата сообщения (по умолчанию UTC now)
        reply_to_msg_id: ID сообщения на которое отвечает (для комментариев)
        views: Количество просмотров
        forwards: Количество пересылок
        media: Mock медиа объект

    Returns:
        Mock объект имитирующий Telethon Message
    """
    mock_message = Mock()
    mock_message.id = message_id
    mock_message.text = text
    mock_message.message = text  # Telethon использует оба атрибута
    mock_message.date = date or datetime.now(UTC)
    mock_message.views = views
    mock_message.forwards = forwards
    mock_message.edit_date = None
    mock_message.post_author = None
    mock_message.grouped_id = None
    mock_message.media = media

    # Reply_to для комментариев
    if reply_to_msg_id is not None:
        mock_reply_to = Mock()
        mock_reply_to.reply_to_msg_id = reply_to_msg_id
        mock_message.reply_to = mock_reply_to
    else:
        mock_message.reply_to = None

    # Replies для постов с комментариями
    mock_message.replies = None

    return mock_message


@pytest.fixture
def mock_telethon_client():
    """
    Создать mock TelethonClient для E2E тестов.

    Mock автоматически подключается и возвращает предопределённые сообщения.
    """
    mock_client = AsyncMock()

    # Mock методы подключения
    mock_client.connect = AsyncMock()
    mock_client.disconnect = AsyncMock()

    # Mock get_messages возвращает async generator
    async def mock_get_messages(*args, **kwargs):
        # По умолчанию возвращаем пустой список
        # Тесты могут переопределить это через mock_client.get_messages.side_effect
        for msg in []:
            yield msg

    mock_client.get_messages = mock_get_messages

    # Mock get_comments возвращает async generator
    async def mock_get_comments(*args, **kwargs):
        for msg in []:
            yield msg

    mock_client.get_comments = mock_get_comments

    return mock_client


# Logger names that ``tg_parser.config.logging.configure_logging``,
# ``tg_parser.mcp_server._configure_mcp_logging`` and
# ``tg_parser.bot.main._configure_logging`` mutate beyond the root
# logger. Must be restored alongside root, otherwise named-logger
# levels (e.g. ``aiogram`` clamped to WARNING by the bot config
# function) leak into subsequent tests.
_LOGGER_NAMES_TOUCHED_BY_APP_CONFIG = (
    "httpx",
    "httpcore",
    "urllib3",
    "asyncio",
    "aiogram",
)


def _apply_structlog_baseline() -> None:
    """Force structlog into a deterministic stdlib-routed configuration.

    Idempotent: safe to call any number of times. Used by both the
    session-scoped baseline fixture and the per-test fixture (latter
    re-applies on setup to defeat module-level imports performed
    between tests).
    """
    import structlog

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )


@pytest.fixture(scope="session", autouse=True)
def _baseline_structlog_for_caplog():
    """Configure structlog → stdlib logging baseline for the whole session.

    structlog's out-of-the-box ``logger_factory`` is
    :class:`structlog.PrintLoggerFactory`, which writes directly to
    ``stdout`` / ``stderr`` and **bypasses stdlib logging entirely**.
    Pytest's ``caplog`` fixture only captures records that flow through
    stdlib propagation — without an explicit
    ``LoggerFactory()``/``BoundLogger`` configuration, ``caplog.records``
    is empty for any structlog log call, even at WARN/ERROR level.

    Historically a few tests in this repo were working "by accident":
    upstream tests (e.g. ``test_logging.py``) called ``configure_logging``
    which switched the global factory to ``stdlib.LoggerFactory``, and
    that state leaked downstream into tests like
    ``TestMigrateUsersDI12::test_warns_when_settings_collections_empty``
    which depend on ``caplog`` seeing structlog WARN logs. Once those
    upstream tests acquired proper teardown (see the per-test fixture
    below), the latent brittleness in the downstream tests surfaced.

    This session-scoped fixture installs a deterministic
    structlog-→-stdlib baseline once at the start of the suite. The
    per-test fixture below snapshots and restores around each test so
    mid-session reconfigurations (e.g. ``_configure_mcp_logging``)
    don't bleed between tests, but the *baseline* the per-test fixture
    snapshots is always the stdlib-routed one — so ``caplog`` works
    deterministically everywhere.
    """
    _apply_structlog_baseline()
    yield


@pytest.fixture(autouse=True)
def _isolate_global_logging_config():
    """Snapshot + restore process-global logging state around every test.

    Several tests (and several module-import side effects) call
    ``configure_logging`` / ``_configure_mcp_logging`` / similar
    helpers that mutate process-global state: the structlog config
    (including ``logger_factory`` — switching to ``PrintLoggerFactory``
    bypasses stdlib propagation entirely, so ``caplog`` no longer sees
    structlog records), the root stdlib logger's handlers and level,
    and the named-logger levels for ``httpx`` / ``httpcore`` /
    ``urllib3`` / ``asyncio`` / ``aiogram``. Without isolation, a
    single test that sets ``log_level=ERROR`` (or installs
    ``PrintLoggerFactory``) silently swallows WARN-level assertions in
    any later test that runs in the same pytest session.

    Pairs with :func:`_baseline_structlog_for_caplog` (session-scoped):
    the baseline ensures structlog → stdlib routing is the snapshot
    target, so each test sees a deterministic config regardless of
    what previous tests did.
    """
    import logging  # local imports keep conftest startup time low

    import structlog

    root_logger = logging.getLogger()
    saved_root_handlers = root_logger.handlers[:]
    saved_root_level = root_logger.level
    saved_named_levels = {
        name: logging.getLogger(name).level for name in _LOGGER_NAMES_TOUCHED_BY_APP_CONFIG
    }
    saved_structlog_config = structlog.get_config()

    # Re-apply baseline at setup so each test starts with a known-good
    # structlog → stdlib routing, defeating any module-level pollution
    # that may have occurred between tests (e.g. side-effects of
    # importing ``tg_parser.bot.main`` at collection time of another
    # test file that happens to be collected just before this one).
    _apply_structlog_baseline()

    try:
        yield
    finally:
        root_logger.handlers.clear()
        for handler in saved_root_handlers:
            root_logger.addHandler(handler)
        root_logger.setLevel(saved_root_level)
        for name, level in saved_named_levels.items():
            logging.getLogger(name).setLevel(level)
        structlog.configure(**saved_structlog_config)
        structlog.contextvars.clear_contextvars()


@pytest.fixture(autouse=True)
async def cleanup_job_store():
    """
    Автоматически очищает JobStore и Database singleton после каждого теста.

    Предотвращает зависание из-за незакрытых SQLite соединений
    и утечку состояния Database singleton между тестами.
    """
    yield
    # Cleanup after test
    try:
        from tg_parser.api.job_store import JobStore, get_job_store

        store = get_job_store()
        if store.is_initialized:
            await store.close()
        JobStore.reset()
    except Exception:
        pass
    # Reset Database singleton so each test starts fresh
    Database.reset_instance()


@pytest.fixture(autouse=True, scope="session")
def disable_metrics_for_tests():
    """
    Disable Prometheus metrics for tests to prevent registry conflicts.

    Prometheus registry is global, and multiple app creations cause
    'Duplicated timeseries' errors.
    """
    import os

    # Set environment variable BEFORE any imports
    os.environ["METRICS_ENABLED"] = "false"

    # Also directly patch the settings singleton
    try:
        from tg_parser.config import settings

        settings.metrics_enabled = False
    except Exception:
        pass

    yield

    # Cleanup
    os.environ.pop("METRICS_ENABLED", None)


@pytest.fixture
def sample_raw_messages():
    """
    Создать набор тестовых RawTelegramMessage для E2E тестов.

    Возвращает список из 5 сообщений с разными характеристиками.
    """
    return [
        RawTelegramMessage(
            id="1",
            message_type=MessageType.POST,
            source_ref="tg:test_channel:post:1",
            channel_id="test_channel",
            date=datetime(2025, 12, 14, 10, 0, 0, tzinfo=UTC),
            text="Первое тестовое сообщение о Python разработке.",
        ),
        RawTelegramMessage(
            id="2",
            message_type=MessageType.POST,
            source_ref="tg:test_channel:post:2",
            channel_id="test_channel",
            date=datetime(2025, 12, 14, 11, 0, 0, tzinfo=UTC),
            text="Второе сообщение про Machine Learning и AI.",
        ),
        RawTelegramMessage(
            id="3",
            message_type=MessageType.POST,
            source_ref="tg:test_channel:post:3",
            channel_id="test_channel",
            date=datetime(2025, 12, 14, 12, 0, 0, tzinfo=UTC),
            text="Третье сообщение о DevOps и облачных технологиях.",
        ),
        RawTelegramMessage(
            id="4",
            message_type=MessageType.COMMENT,
            source_ref="tg:test_channel:comment:4",
            channel_id="test_channel",
            thread_id="1",
            parent_message_id="1",
            date=datetime(2025, 12, 14, 13, 0, 0, tzinfo=UTC),
            text="Комментарий к первому посту.",
        ),
        RawTelegramMessage(
            id="5",
            message_type=MessageType.POST,
            source_ref="tg:test_channel:post:5",
            channel_id="test_channel",
            date=datetime(2025, 12, 14, 14, 0, 0, tzinfo=UTC),
            text="Пятое сообщение про frontend разработку и React.",
        ),
    ]
