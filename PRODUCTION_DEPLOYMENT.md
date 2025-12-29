# Production Deployment Guide

**TG_parser v3.1.1 Production Deployment**

Session 24: Complete guide for deploying TG_parser with PostgreSQL in production.

> ✅ **Tested**: Full pipeline successfully tested on real channel @BiocodebySechenov with PostgreSQL backend

---

## 📋 Table of Contents

- [Prerequisites](#prerequisites)
- [Server Setup](#server-setup)
- [Database Setup](#database-setup)
- [Application Deployment](#application-deployment)
- [SSL/TLS Configuration](#ssltls-configuration)
- [Monitoring](#monitoring)
- [Backup Strategy](#backup-strategy)
- [Troubleshooting](#troubleshooting)
- [Rollback Procedures](#rollback-procedures)

---

## Prerequisites

### Hardware Requirements

**Minimum:**
- CPU: 2 cores
- RAM: 4 GB
- Disk: 20 GB SSD
- Network: 100 Mbps

**Recommended:**
- CPU: 4+ cores
- RAM: 8+ GB
- Disk: 50+ GB SSD
- Network: 1 Gbps

### Software Requirements

- **OS**: Ubuntu 22.04 LTS (recommended) or any Docker-compatible Linux
- **Docker**: 24.0+ 
- **Docker Compose**: v2.0+
- **Domain**: Optional, for HTTPS setup
- **SSL Certificate**: Let's Encrypt or commercial certificate

---

## Server Setup

### 1. Install Docker

```bash
# Update package index
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Add user to docker group
sudo usermod -aG docker $USER

# Install Docker Compose (v2)
sudo apt install docker-compose-plugin

# Verify installation
docker --version
docker compose version
```

### 2. Configure Firewall

```bash
# Allow SSH
sudo ufw allow 22/tcp

# Allow HTTP/HTTPS (if using reverse proxy)
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Or allow custom API port (e.g., 8000)
sudo ufw allow 8000/tcp

# Enable firewall
sudo ufw enable
```

### 3. Create Application Directory

```bash
# Create app directory
sudo mkdir -p /opt/tg_parser
cd /opt/tg_parser

# Set permissions
sudo chown $USER:$USER /opt/tg_parser

# Create data directories
mkdir -p data/output data/archive
```

---

## Database Setup

### Option 1: Docker Compose (Recommended)

PostgreSQL is automatically set up via `docker-compose.yml`.

### Option 2: External PostgreSQL

If you want to use an external PostgreSQL server:

```bash
# On PostgreSQL server
sudo -u postgres psql

-- Create database and user
CREATE DATABASE tg_parser;
CREATE USER tg_parser_user WITH ENCRYPTED PASSWORD 'YOUR_SECURE_PASSWORD';
GRANT ALL PRIVILEGES ON DATABASE tg_parser TO tg_parser_user;

-- Exit
\q
```

Configure connection in `.env`:

```env
DB_TYPE=postgresql
DB_HOST=your-postgres-host.com
DB_PORT=5432
DB_NAME=tg_parser
DB_USER=tg_parser_user
DB_PASSWORD=YOUR_SECURE_PASSWORD
```

---

## Application Deployment

### Step 1: Clone Repository

```bash
cd /opt/tg_parser

# Clone from Git
git clone https://github.com/your-org/tg_parser.git .

# Or upload files via SCP/SFTP
```

### Step 2: Configure Environment

```bash
# Copy production environment template
cp env.production.example .env

# Edit configuration
nano .env
```

**Critical settings to configure:**

```env
# Database (PostgreSQL)
DB_TYPE=postgresql
DB_HOST=postgres  # Docker service name
DB_PORT=5432
DB_NAME=tg_parser
DB_USER=tg_parser_user
DB_PASSWORD=CHANGE_THIS_TO_SECURE_PASSWORD_32_CHARS_MIN

# Connection Pool
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=10

# LLM Provider
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-proj-YOUR_KEY_HERE

# Telegram
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_PHONE=+1234567890

# Logging (Production)
LOG_FORMAT=json
LOG_LEVEL=INFO

# Security
API_KEY_REQUIRED=true
API_KEYS={"YOUR_KEY":"production"}
```

### Step 3: Deploy with Docker Compose

```bash
# Build and start services
docker compose up -d

# Check logs
docker compose logs -f

# Verify services are running
docker compose ps
```

### Step 4: Run Database Migrations

```bash
# Run migrations for all databases
docker compose exec tg_parser tg-parser db upgrade --db all

# Verify migrations
docker compose exec tg_parser tg-parser db current --db all
```

### Step 5: Verify Deployment

```bash
# Check health endpoint
curl http://localhost:8000/health

# Expected response:
# {
#   "status": "ok",
#   "version": "processing:v1.0.0",
#   "timestamp": "2025-12-29T12:00:00Z"
# }

# Check detailed status
curl http://localhost:8000/status/detailed

# Should show database type: postgresql
```

---

## SSL/TLS Configuration

### Option 1: Nginx Reverse Proxy

```bash
# Install Nginx
sudo apt install nginx certbot python3-certbot-nginx

# Create Nginx config
sudo nano /etc/nginx/sites-available/tg_parser
```

**Nginx configuration:**

```nginx
server {
    listen 80;
    server_name your-domain.com;
    
    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;
    
    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
    
    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    
    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
# Enable site
sudo ln -s /etc/nginx/sites-available/tg_parser /etc/nginx/sites-enabled/

# Get SSL certificate
sudo certbot --nginx -d your-domain.com

# Test Nginx config
sudo nginx -t

# Reload Nginx
sudo systemctl reload nginx
```

### Option 2: Traefik (Docker)

See Traefik documentation for Docker-based reverse proxy setup.

---

## Monitoring

### Health Check Monitoring

Use UptimeRobot, Pingdom, or similar service:

- **Endpoint**: `https://your-domain.com/health`
- **Interval**: 5 minutes
- **Alert on**: Status != "ok"

### Log Aggregation

**CloudWatch (AWS):**

```bash
# Install CloudWatch agent
# Configure to forward Docker logs
```

**Datadog:**

```yaml
# Add to docker-compose.yml
services:
  datadog:
    image: datadog/agent:latest
    environment:
      - DD_API_KEY=${DD_API_KEY}
      - DD_SITE=datadoghq.com
      - DD_LOGS_ENABLED=true
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - /proc/:/host/proc/:ro
      - /sys/fs/cgroup/:/host/sys/fs/cgroup:ro
```

### Prometheus Metrics

TG_parser exposes Prometheus metrics at `/metrics`:

```bash
# Check metrics
curl http://localhost:8000/metrics
```

**Prometheus configuration:**

```yaml
scrape_configs:
  - job_name: 'tg_parser'
    static_configs:
      - targets: ['your-domain.com:8000']
```

---

## Backup Strategy

### Database Backups

```bash
# Automated daily backup script
cat > /opt/tg_parser/backup.sh << 'EOF'
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/opt/tg_parser/backups"
mkdir -p $BACKUP_DIR

# Backup PostgreSQL
docker compose exec -T postgres pg_dump -U tg_parser_user tg_parser | gzip > $BACKUP_DIR/postgres_$DATE.sql.gz

# Keep only last 7 days
find $BACKUP_DIR -name "postgres_*.sql.gz" -mtime +7 -delete

echo "Backup completed: postgres_$DATE.sql.gz"
EOF

chmod +x /opt/tg_parser/backup.sh

# Add to crontab (daily at 2 AM)
crontab -e
# Add line:
# 0 2 * * * /opt/tg_parser/backup.sh >> /var/log/tg_parser_backup.log 2>&1
```

### Restore from Backup

```bash
# Stop application
docker compose down tg_parser

# Restore database
gunzip < backups/postgres_20251229_020000.sql.gz | \
  docker compose exec -T postgres psql -U tg_parser_user tg_parser

# Start application
docker compose up -d
```

---

## Troubleshooting

### Database Connection Errors

```bash
# Check PostgreSQL is running
docker compose ps postgres

# Check logs
docker compose logs postgres

# Test connection manually
docker compose exec postgres psql -U tg_parser_user -d tg_parser

# Check pool status
curl http://localhost:8000/status/detailed | jq '.components.database.pool'
```

### Application Won't Start

```bash
# Check logs
docker compose logs tg_parser

# Check health endpoint
curl http://localhost:8000/health

# Restart services
docker compose restart

# Full rebuild if needed
docker compose down
docker compose build --no-cache
docker compose up -d
```

### High Memory Usage

```bash
# Check container stats
docker stats

# Reduce pool size in .env
DB_POOL_SIZE=3
DB_MAX_OVERFLOW=5

# Restart
docker compose restart tg_parser
```

### Slow Queries

```bash
# Check PostgreSQL slow query log
docker compose exec postgres psql -U tg_parser_user -d tg_parser

-- Enable slow query logging
ALTER DATABASE tg_parser SET log_min_duration_statement = 1000;

-- Check indexes
SELECT * FROM pg_indexes WHERE schemaname = 'public';
```

---

## Rollback Procedures

### Rollback to Previous Version

```bash
# Stop services
docker compose down

# Checkout previous version
git checkout v3.0.0  # or previous tag

# Restore database backup (if schema changed)
gunzip < backups/postgres_backup.sql.gz | \
  docker compose exec -T postgres psql -U tg_parser_user tg_parser

# Rebuild and restart
docker compose build
docker compose up -d

# Verify
curl http://localhost:8000/health
```

### Emergency Shutdown

```bash
# Graceful shutdown
docker compose down

# Force stop if hanging
docker compose kill

# Check all containers stopped
docker ps -a
```

---

## Maintenance

### Regular Maintenance Tasks

**Weekly:**
- Check disk space: `df -h`
- Review logs for errors
- Verify backups are running

**Monthly:**
- Update Docker images: `docker compose pull`
- Review database size and performance
- Test backup restoration
- Update SSL certificates (if manual)

### Updates

```bash
# Pull latest code
git pull origin main

# Rebuild containers
docker compose build

# Run migrations if needed
docker compose exec tg_parser tg-parser db upgrade --db all

# Restart services
docker compose restart
```

---

## Security Checklist

- [ ] Strong database password (32+ characters)
- [ ] API keys secured and rotated regularly
- [ ] Firewall configured (only necessary ports open)
- [ ] SSL/TLS enabled for public access
- [ ] Docker images from trusted sources
- [ ] Regular security updates
- [ ] Backups encrypted and stored securely
- [ ] Access logs monitored
- [ ] Rate limiting enabled
- [ ] CORS properly configured

---

## Support

For issues and questions:
- GitHub Issues: https://github.com/your-org/tg_parser/issues
- Documentation: https://github.com/your-org/tg_parser/tree/main/docs

---

**Document Version**: 1.0  
**Last Updated**: December 29, 2025  
**TG_parser Version**: v3.1.0

