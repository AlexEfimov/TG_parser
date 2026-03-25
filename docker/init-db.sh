#!/bin/bash
# Auto-create test database and enable pgvector on first docker-compose up.
# Mounted at /docker-entrypoint-initdb.d/init-db.sh (runs once on fresh volume).

set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Enable pgvector in the main database
    CREATE EXTENSION IF NOT EXISTS vector;

    -- Create test database (for pytest)
    SELECT 'CREATE DATABASE tg_parser_test OWNER $POSTGRES_USER'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'tg_parser_test')\gexec
EOSQL

# Enable pgvector in the test database
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "tg_parser_test" <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS vector;
EOSQL
