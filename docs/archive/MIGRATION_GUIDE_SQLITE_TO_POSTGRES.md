# Migration Guide: SQLite → PostgreSQL

**TG_parser v3.1.0 Database Migration**

Complete guide for migrating existing TG_parser installation from SQLite to PostgreSQL.

---

## 📋 Table of Contents

- [When to Migrate](#when-to-migrate)
- [Pre-Migration Checklist](#pre-migration-checklist)
- [Migration Steps](#migration-steps)
- [Verification](#verification)
- [Rollback](#rollback)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)

---

## When to Migrate

### Migrate to PostgreSQL if you:

✅ **Need production deployment** - PostgreSQL is recommended for production  
✅ **Have multiple users/processes** - Better concurrency support  
✅ **Need better performance** - Better query optimization and indexing  
✅ **Want connection pooling** - Efficient connection management  
✅ **Need advanced features** - Full-text search, JSON operations, etc.  
✅ **Have large datasets** - Better handling of millions of records

### Stay with SQLite if you:

⚠️ **Development/testing only** - SQLite is simpler for development  
⚠️ **Single-user usage** - No concurrent access needed  
⚠️ **Small datasets** - Less than 10,000 messages  
⚠️ **File-based portability needed** - Easy to copy database files  
⚠️ **Zero-configuration preferred** - No separate database server

---

## Pre-Migration Checklist

### 1. Backup Your Data

```bash
# Create backup directory
mkdir -p backups/$(date +%Y%m%d)

# Backup SQLite files
cp *.sqlite backups/$(date +%Y%m%d)/

# Backup configuration
cp .env backups/$(date +%Y%m%d)/

# Verify backups
ls -lh backups/$(date +%Y%m%d)/
```

### 2. Check Data Size

```bash
# Check size of SQLite databases
du -h *.sqlite

# Estimate migration time:
# - < 100 MB: < 1 minute
# - 100 MB - 1 GB: 1-5 minutes
# - > 1 GB: 5+ minutes
```

### 3. Setup PostgreSQL

**Option A: Docker Compose (Recommended)**

```bash
# PostgreSQL is already in docker-compose.yml
# Just configure .env
```

**Option B: Existing PostgreSQL Server**

```bash
# Create database and user
sudo -u postgres psql
CREATE DATABASE tg_parser;
CREATE USER tg_parser_user WITH ENCRYPTED PASSWORD 'YOUR_PASSWORD';
GRANT ALL PRIVILEGES ON DATABASE tg_parser TO tg_parser_user;
\q
```

### 4. Configure Environment

```bash
# Edit .env file
nano .env
```

Add PostgreSQL configuration:

```env
# Database type
DB_TYPE=postgresql

# PostgreSQL connection
DB_HOST=localhost  # or postgres for Docker
DB_PORT=5432
DB_NAME=tg_parser
DB_USER=tg_parser_user
DB_PASSWORD=YOUR_SECURE_PASSWORD

# Connection pool settings
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=10
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=3600
DB_POOL_PRE_PING=true
```

---

## Migration Steps

### 🚀 Quick Start (New Installations)

If you have **no existing data** in SQLite, use the direct initialization script:

```bash
# 1. Start PostgreSQL
docker compose up -d postgres

# 2. Wait for PostgreSQL to be ready
sleep 10

# 3. Initialize schema directly (faster than Alembic)
DB_HOST=localhost DB_PASSWORD=your_password python scripts/init_postgres.py

# Done! PostgreSQL is ready to use.
```

This is the **recommended approach** for new deployments.

---

### Step 1: Verify Current Data (For Existing SQLite Users)

```bash
# Check current SQLite data
python -c "
import sqlite3
for db in ['ingestion_state.sqlite', 'raw_storage.sqlite', 'processing_storage.sqlite']:
    conn = sqlite3.connect(db)
    cursor = conn.cursor()
    cursor.execute('SELECT name FROM sqlite_master WHERE type=\"table\"')
    tables = cursor.fetchall()
    print(f'{db}: {len(tables)} tables')
    for table in tables:
        cursor.execute(f'SELECT COUNT(*) FROM {table[0]}')
        count = cursor.fetchone()[0]
        print(f'  - {table[0]}: {count} records')
    conn.close()
"
```

### Step 2: Start PostgreSQL

```bash
# If using Docker Compose
docker compose up -d postgres

# Wait for PostgreSQL to be ready
docker compose exec postgres pg_isready -U tg_parser_user

# Verify connection
docker compose exec postgres psql -U tg_parser_user -d tg_parser -c "SELECT version();"
```

### Step 3: Run Migrations on PostgreSQL

```bash
# Update DB_TYPE in .env temporarily to run migrations
echo "DB_TYPE=postgresql" >> .env

# Run Alembic migrations for all databases
# For each database: ingestion, raw, processing
tg-parser db upgrade --db ingestion
tg-parser db upgrade --db raw
tg-parser db upgrade --db processing

# Or upgrade all at once
tg-parser db upgrade --db all

# Verify migrations applied
tg-parser db current --db all
```

### Step 4: Dry Run Migration (Recommended)

```bash
# Test migration without committing changes
python scripts/migrate_sqlite_to_postgres.py --dry-run

# Output should show:
# - Source record counts
# - Tables to migrate
# - No errors

# Review output carefully before proceeding
```

### Step 5: Perform Migration

```bash
# Run migration with verification
python scripts/migrate_sqlite_to_postgres.py --verify

# Migration will:
# 1. Connect to both databases
# 2. Copy all records table by table
# 3. Verify record counts match
# 4. Display detailed summary

# Expected output:
# ======================================================================
# MIGRATION SUMMARY
# ======================================================================
# ✅ OK ingestion_state              X → X
# ✅ OK raw_messages                  Y → Y
# ✅ OK processed_documents           Z → Z
# ...
# ----------------------------------------------------------------------
# Total records migrated: N
# Duration: X.XX seconds
# Status: SUCCESS
# ======================================================================
```

### Step 6: Verify Migration

```bash
# Check PostgreSQL data
docker compose exec postgres psql -U tg_parser_user -d tg_parser -c "
SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size,
    (SELECT COUNT(*) FROM information_schema.columns WHERE table_name = t.tablename) AS columns
FROM pg_tables t
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
"

# Compare with SQLite counts from Step 1
```

### Step 7: Test Application

```bash
# Update .env to use PostgreSQL permanently
sed -i 's/DB_TYPE=sqlite/DB_TYPE=postgresql/' .env

# Restart application (if running)
docker compose restart tg_parser

# Test health endpoint
curl http://localhost:8000/health

# Check database status
curl http://localhost:8000/status/detailed | jq '.components.database'

# Expected output:
# {
#   "status": "ok",
#   "type": "postgresql",
#   "pool": {
#     "type": "QueuePool",
#     "status": "healthy",
#     ...
#   }
# }
```

### Step 8: Run Smoke Tests

```bash
# Test basic operations
tg-parser list-sources

# Test processing (if you have data)
# tg-parser process --channel your_channel --limit 5

# Check logs for errors
docker compose logs tg_parser --tail 100
```

---

## Verification

### Automated Verification

```bash
# Compare record counts between SQLite and PostgreSQL
python scripts/verify_migration.py

# Or manually:
python -c "
import sqlite3
import psycopg2

# SQLite counts
sqlite_counts = {}
for db in ['ingestion_state.sqlite', 'raw_storage.sqlite', 'processing_storage.sqlite']:
    conn = sqlite3.connect(db)
    cursor = conn.cursor()
    cursor.execute('SELECT name FROM sqlite_master WHERE type=\"table\"')
    tables = cursor.fetchall()
    for table in tables:
        cursor.execute(f'SELECT COUNT(*) FROM {table[0]}')
        sqlite_counts[table[0]] = cursor.fetchone()[0]
    conn.close()

# PostgreSQL counts
pg_conn = psycopg2.connect(
    host='localhost',
    port=5432,
    database='tg_parser',
    user='tg_parser_user',
    password='YOUR_PASSWORD'
)
pg_cursor = pg_conn.cursor()

for table, sqlite_count in sqlite_counts.items():
    pg_cursor.execute(f'SELECT COUNT(*) FROM {table}')
    pg_count = pg_cursor.fetchone()[0]
    status = '✅' if sqlite_count == pg_count else '❌'
    print(f'{status} {table}: SQLite={sqlite_count}, PostgreSQL={pg_count}')

pg_conn.close()
"
```

### Manual Verification

```bash
# Check specific records exist
docker compose exec postgres psql -U tg_parser_user -d tg_parser -c "
SELECT COUNT(*) FROM raw_messages;
SELECT COUNT(*) FROM processed_documents;
SELECT COUNT(*) FROM topics;
"

# Verify indexes created
docker compose exec postgres psql -U tg_parser_user -d tg_parser -c "
SELECT indexname, tablename FROM pg_indexes 
WHERE schemaname = 'public' 
ORDER BY tablename, indexname;
"
```

---

## Rollback

### If Migration Fails

```bash
# 1. Stop application
docker compose down tg_parser

# 2. Revert .env to SQLite
sed -i 's/DB_TYPE=postgresql/DB_TYPE=sqlite/' .env

# 3. Restore SQLite backups (if needed)
cp backups/$(date +%Y%m%d)/*.sqlite .

# 4. Restart application
docker compose up -d tg_parser

# 5. Verify working
curl http://localhost:8000/health
```

### If PostgreSQL Has Issues

```bash
# Keep PostgreSQL but clear and retry
docker compose exec postgres psql -U tg_parser_user -d tg_parser -c "
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
GRANT ALL ON SCHEMA public TO tg_parser_user;
"

# Re-run migrations
tg-parser db upgrade --db all

# Re-run migration script
python scripts/migrate_sqlite_to_postgres.py --verify
```

---

## Troubleshooting

### Connection Refused

```bash
# Check PostgreSQL is running
docker compose ps postgres

# Check PostgreSQL logs
docker compose logs postgres

# Test connection
docker compose exec postgres pg_isready -U tg_parser_user
```

### Migration Script Errors

```bash
# Enable debug logging
export LOG_LEVEL=DEBUG
python scripts/migrate_sqlite_to_postgres.py --verify

# Check for conflicting data
# Migration script continues even if individual records fail
# Review summary for failed tables
```

### Performance Issues

```bash
# Reduce pool size if memory constrained
DB_POOL_SIZE=3
DB_MAX_OVERFLOW=5

# Check indexes created
docker compose exec postgres psql -U tg_parser_user -d tg_parser -c "
SELECT schemaname, tablename, indexname 
FROM pg_indexes 
WHERE schemaname = 'public';
"
```

### Data Mismatch

```bash
# Find missing records
# Example for raw_messages table
docker compose exec postgres psql -U tg_parser_user -d tg_parser -c "
SELECT COUNT(*) FROM raw_messages;
"

# Compare with SQLite
sqlite3 raw_storage.sqlite "SELECT COUNT(*) FROM raw_messages;"

# Re-run migration for specific database
python scripts/migrate_sqlite_to_postgres.py --db raw --verify
```

---

## FAQ

### Q: How long does migration take?

**A:** Depends on data size:
- Small (<100MB): < 1 minute
- Medium (100MB-1GB): 1-5 minutes  
- Large (>1GB): 5-30 minutes

### Q: Can I migrate while application is running?

**A:** Not recommended. Stop the application first to avoid data inconsistency.

### Q: Will I lose data?

**A:** No, if you follow backup steps. Migration copies data, doesn't move it. Original SQLite files remain intact.

### Q: Can I switch back to SQLite?

**A:** Yes, just change `DB_TYPE=sqlite` in `.env` and restart.

### Q: Do I need to keep SQLite files after migration?

**A:** Keep them as backup for at least 2 weeks after successful migration.

### Q: What if migration fails halfway?

**A:** Migration script continues even if individual records fail. Check summary for failed tables and re-run if needed.

### Q: Can I migrate incrementally?

**A:** Yes, migration script can be run per-database:
```bash
python scripts/migrate_sqlite_to_postgres.py --db ingestion
python scripts/migrate_sqlite_to_postgres.py --db raw
python scripts/migrate_sqlite_to_postgres.py --db processing
```

### Q: Does PostgreSQL use more resources?

**A:** Yes, PostgreSQL uses more memory (~50-100MB base + pool) but provides better performance for concurrent access.

### Q: Are there any breaking changes?

**A:** No, API and functionality remain identical. Only database backend changes.

---

## Post-Migration

### Optimize PostgreSQL

```sql
-- Run ANALYZE to update statistics
ANALYZE;

-- Optional: VACUUM to reclaim space
VACUUM ANALYZE;
```

### Monitor Performance

```bash
# Check query performance
docker compose exec postgres psql -U tg_parser_user -d tg_parser -c "
SELECT query, calls, mean_exec_time, max_exec_time 
FROM pg_stat_statements 
ORDER BY mean_exec_time DESC 
LIMIT 10;
"

# Check connection pool status
curl http://localhost:8000/status/detailed | jq '.components.database.pool'
```

### Setup Backups

See [PRODUCTION_DEPLOYMENT.md](./PRODUCTION_DEPLOYMENT.md) for backup configuration.

---

## Support

For issues during migration:
- GitHub Issues: https://github.com/your-org/tg_parser/issues
- Documentation: https://github.com/your-org/tg_parser/tree/main/docs

---

**Document Version**: 1.0  
**Last Updated**: December 29, 2025  
**TG_parser Version**: v3.1.0

