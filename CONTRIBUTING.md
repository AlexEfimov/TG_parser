# Contributing to TG_parser

Thank you for your interest in TG_parser. This project is in **Wave 1.5 operational dogfooding** — external contributions are welcome but expect evolving docs and APIs.

## Development setup

1. Clone the repository.
2. Follow [README.md](README.md) Quick Start or [docs/guides/SELF_HOST.md](docs/guides/SELF_HOST.md).
3. Run tests: `pytest` (requires PostgreSQL + pgvector — see CI in `.github/workflows/ci.yml`).

## Code style

- Python 3.12+
- `ruff` for lint and format (CI enforced)
- Match existing patterns in `tg_parser/` — minimal scope per change

## Pull requests

1. Branch from `main`.
2. Include tests for behavior changes when practical.
3. Update user-facing docs if you change CLI, MCP tools, or env vars.
4. Do not commit secrets (`.env`, sessions, tokens).

## Documentation

- **End users:** [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md)
- **Agents / MCP:** [docs/MCP_AGENT_GUIDE.md](docs/MCP_AGENT_GUIDE.md)
- **Architecture decisions:** [docs/adr/](docs/adr/) (normative)
- **Contracts:** [docs/contracts/](docs/contracts/) (do not break JSON schemas)
- **Internal dev notes:** `docs/notes/` — maintainer workspace, not required reading

## Methodology docs

Project documentation standards live in a separate methodology worktree (`methodology` branch) — not on `main` by design. See [AGENTS.md](AGENTS.md).

## Questions

Open a GitHub issue for bugs and feature discussions. For security issues, see [SECURITY.md](SECURITY.md).
