"""add workspaces and workspace_sources tables (F4-B Core)

Revision ID: e9f0a1b2c3d5
Revises: d7e8f9a0b1c4
Create Date: 2026-05-13

F4-B Core: тематические коллекции каналов внутри одного пользователя.
Schema only (additive) — никакого изменения существующих таблиц.

- `workspaces` — owner_id FK на users.id (ON DELETE CASCADE); UNIQUE
  (owner_id, name) гарантирует per-owner namespace (gotcha § 6);
  CheckConstraints на name (non-empty trimmed, max 200 chars).
- `workspace_sources` — M2M между workspaces и sources с композитным PK
  (workspace_id, source_id). Один source_id может быть в N workspaces
  одного user'а (Q5 = A); ON DELETE CASCADE сохраняет referential
  integrity при удалении workspace или soft-delete sources.

Q1 = B (opt-in, no default) — миграция НЕ создаёт workspace для
существующих users; их workspace-count остаётся = 0 до явного
`create_workspace`.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e9f0a1b2c3d5"
down_revision: str | None = "d7e8f9a0b1c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workspaces (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name VARCHAR(200) NOT NULL,
            description TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_workspaces_owner_name UNIQUE (owner_id, name),
            CONSTRAINT ck_workspaces_name_nonempty CHECK (length(trim(name)) > 0),
            CONSTRAINT ck_workspaces_name_length CHECK (length(name) <= 200)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_workspaces_owner_id ON workspaces(owner_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workspace_sources (
            workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            source_id VARCHAR NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
            added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT pk_workspace_sources PRIMARY KEY (workspace_id, source_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workspace_sources_source_id ON workspace_sources(source_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_workspace_sources_source_id")
    op.execute("DROP TABLE IF EXISTS workspace_sources")
    op.execute("DROP INDEX IF EXISTS idx_workspaces_owner_id")
    op.execute("DROP TABLE IF EXISTS workspaces")
