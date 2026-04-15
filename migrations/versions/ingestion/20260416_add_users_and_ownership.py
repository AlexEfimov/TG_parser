"""add users, user_auth_mappings and sources.owner_id

Revision ID: b2c3d4e5f6a7
Revises: 89f91e768b9b
Create Date: 2026-04-16

F4 Multi-Tenancy Phase 1: User model + ownership.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "89f91e768b9b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # -- users table --------------------------------------------------------
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS users (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
            max_channels INTEGER DEFAULT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """))

    # -- user_auth_mappings table ------------------------------------------
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS user_auth_mappings (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            auth_type TEXT NOT NULL CHECK (auth_type IN ('api_key', 'telegram', 'mcp_token')),
            auth_identifier TEXT NOT NULL,
            client_name TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(auth_type, auth_identifier)
        )
    """))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_uam_lookup "
        "ON user_auth_mappings(auth_type, auth_identifier)"
    ))

    # -- owner_id on sources -----------------------------------------------
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("sources")]
    if "owner_id" not in columns:
        conn.execute(sa.text(
            "ALTER TABLE sources ADD COLUMN owner_id UUID REFERENCES users(id)"
        ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_sources_owner ON sources(owner_id)"
    ))

    # -- seed default admin user -------------------------------------------
    conn.execute(sa.text("""
        INSERT INTO users (name, role)
        SELECT 'admin', 'admin'
        WHERE NOT EXISTS (SELECT 1 FROM users WHERE role = 'admin')
    """))


def downgrade() -> None:
    op.drop_index("idx_sources_owner", table_name="sources")
    op.drop_column("sources", "owner_id")
    op.drop_table("user_auth_mappings")
    op.drop_table("users")
