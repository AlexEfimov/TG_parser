# AGENTS.md — TG_parser project workspace

**Scope:** этот workspace — основная разработка проекта TG_parser. Code, tests, docs (кроме методологии), runbooks, ADR, contracts.

**Методология стандарта живёт в отдельном worktree** — `/Users/alexanderefimov/TG_parser-methodology` (ветка `methodology`). Не редактировать `docs/methodology/` отсюда — папка отсутствует на `main` намеренно.

**Branch:** `main`.

**Если задача касается методологии (структура документации, шаблоны, конвенции, agent-contracts):** переключиться в methodology workspace в отдельном Cursor-окне. Не предлагать правки `docs/methodology/**` из этого workspace.

**Project conventions (нормативно):**
- [`docs/adr/`](docs/adr/) — accepted ADR обязательны.
- [`docs/contracts/`](docs/contracts/) — JSON Schema нарушать нельзя.
- [`docs/quality/AGENT_PLAYBOOK.md`](docs/quality/AGENT_PLAYBOOK.md) — quality lifecycle.
- [`docs/notes/agents-roles.md`](docs/notes/agents-roles.md) — базовые роли.
- [`docs/notes/BUG_LOG.md`](docs/notes/BUG_LOG.md) — backbone fix-сессий.
- [`tests/README.md`](tests/README.md) — режимы pytest (default / PR / max local).

**Forbidden actions:**
- `git commit` без явного запроса пользователя.
- Создание `docs/methodology/**` в этом workspace.
- Прямые правки `pyproject.toml`, `requirements.txt` без явного запроса.

**Living document:** растёт по реальной нужде, не наугад.

### Cursor Cloud specific instructions

- Runtime Secret required: `PROD_SSH_PRIVATE_KEY` (OpenSSH private key for prod).
- Before any `ssh prod` / Prometheus scrape: run `bash scripts/cursor_cloud_setup_prod_ssh.sh` (also wired via `.cursor/environment.json` install/start).
- Details: [`docs/runbooks/CURSOR_CLOUD_PROD_SSH.md`](docs/runbooks/CURSOR_CLOUD_PROD_SSH.md).
