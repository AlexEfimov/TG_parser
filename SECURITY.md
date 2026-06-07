# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 4.4.x   | Yes       |
| < 4.4   | Best effort |

## Reporting a vulnerability

**Do not** open public GitHub issues for security vulnerabilities.

Send a private report to the repository maintainer with:

- Description of the issue
- Steps to reproduce
- Impact assessment
- Suggested fix (if any)

Allow reasonable time for remediation before public disclosure.

## Sensitive data

Never commit or share in issues:

- `.env` files and API keys
- MCP bearer tokens or API keys
- Telegram session files (`.session`)
- Production host credentials

TG_parser stores credential hashes (SHA-256) for API/MCP tokens in the database; raw tokens are only shown once at creation.

## Deployment hardening

For production deployments, see [PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md):

- Enable `MCP_AUTH_ENABLED` and `API_KEY_REQUIRED`
- Run `migrate-users` for multi-tenant auth mappings
- Bind service ports to `127.0.0.1`; terminate TLS at reverse proxy
- Rotate tokens when validators complete Wave 1.5 testing

## Known deferred items

Bot UX validation (BUG-025/026/027) and some LLM retry paths are documented in Wave 2 backlog — not security-critical blockers for Wave 1.5 dogfooding.
