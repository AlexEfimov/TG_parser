#!/bin/bash
# PostgreSQL backup script for TG_parser.
# Usage:
#   ./docker/backup.sh                  # default: see BACKUP_DIR resolution below
#   ./docker/backup.sh /custom/path 14  # custom dir, 14-day retention
#
# Designed for cron (always pass the target explicitly there):
#   0 2 * * * /home/user/TG_parser/docker/backup.sh /mnt/data/backups/tg_parser/nightly \
#     >> /var/log/tg_parser_backup.log 2>&1

set -euo pipefail

# Where dumps land, in order of precedence:
#   1. $1                     — explicit argument (what cron uses)
#   2. $TG_PARSER_BACKUP_DIR  — per-host override, for deployments where the
#                               project root sits on a small system partition
#                               and dumps must go to a separate disk
#   3. <project>/data/backups — dev default, fine on a workstation
BACKUP_DIR="${1:-${TG_PARSER_BACKUP_DIR:-$(dirname "$0")/../data/backups}}"
RETENTION_DAYS="${2:-7}"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="postgres_${DATE}.sql.gz"

BACKUP_DIR=$(cd "$(dirname "$0")/.." && mkdir -p "$BACKUP_DIR" && cd "$BACKUP_DIR" && pwd)

COMPOSE_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "[$(date)] Starting backup..."
echo "  Output: ${BACKUP_DIR}/${BACKUP_FILE}"

docker compose -f "${COMPOSE_DIR}/docker-compose.yml" exec -T postgres \
    pg_dump --clean --if-exists -U "${DB_USER:-tg_parser_user}" "${DB_NAME:-tg_parser}" \
    | gzip > "${BACKUP_DIR}/${BACKUP_FILE}"

SIZE=$(du -h "${BACKUP_DIR}/${BACKUP_FILE}" | cut -f1)
echo "  Size: ${SIZE}"

# Rotate old backups
DELETED=$(find "${BACKUP_DIR}" -name "postgres_*.sql.gz" -mtime +"${RETENTION_DAYS}" -print -delete | wc -l | tr -d ' ')
if [ "$DELETED" -gt 0 ]; then
    echo "  Rotated: ${DELETED} backup(s) older than ${RETENTION_DAYS} days"
fi

echo "[$(date)] Backup completed: ${BACKUP_FILE} (${SIZE})"
