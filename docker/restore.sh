#!/bin/bash
# PostgreSQL restore script for TG_parser.
# Usage:
#   ./docker/restore.sh data/backups/postgres_20260331_020000.sql.gz
#
# Stops tg_parser and mcp services, restores the database, restarts services,
# and verifies table counts.

set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: $0 <backup_file.sql.gz>"
    echo "Example: $0 data/backups/postgres_20260331_020000.sql.gz"
    exit 1
fi

BACKUP_FILE="$1"
COMPOSE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DB_USER="${DB_USER:-tg_parser_user}"
DB_NAME="${DB_NAME:-tg_parser}"

if [ ! -f "$BACKUP_FILE" ]; then
    echo "❌ File not found: $BACKUP_FILE"
    exit 1
fi

SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "🔄 Restoring from: $BACKUP_FILE ($SIZE)"
echo "   Target: $DB_NAME"
echo ""

read -p "⚠️  This will overwrite current data. Continue? [y/N] " -r
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

echo ""
echo "[$(date)] Stopping application services..."
docker compose -f "${COMPOSE_DIR}/docker-compose.yml" stop tg_parser mcp 2>/dev/null || true

echo "[$(date)] Restoring database..."
gunzip -c "$BACKUP_FILE" \
    | docker compose -f "${COMPOSE_DIR}/docker-compose.yml" exec -T postgres \
        psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 --quiet

echo "[$(date)] Verifying restore..."
docker compose -f "${COMPOSE_DIR}/docker-compose.yml" exec -T postgres \
    psql -U "$DB_USER" -d "$DB_NAME" -c "
        SELECT 'sources' AS table_name, count(*) FROM sources
        UNION ALL SELECT 'raw_messages', count(*) FROM raw_messages
        UNION ALL SELECT 'processed_documents', count(*) FROM processed_documents
        UNION ALL SELECT 'topic_cards', count(*) FROM topic_cards;
    "

echo ""
echo "[$(date)] Restarting application services..."
docker compose -f "${COMPOSE_DIR}/docker-compose.yml" start tg_parser mcp 2>/dev/null || true

echo ""
echo "✅ Restore completed successfully!"
