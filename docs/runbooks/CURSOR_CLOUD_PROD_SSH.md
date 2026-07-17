# Cursor Cloud — prod SSH for Automations / Cloud Agents

Phase-1 watch automation and other Cloud Agents need `ssh prod`. Local runners already use host `~/.ssh`; Cloud VMs do not — provision a **Runtime Secret** and keep `.cursor/environment.json` on `main`.

## Required secret (Dashboard)

**Cursor Settings / Dashboard → Cloud Agents → Secrets**

| Name | Type | Value |
|------|------|--------|
| `PROD_SSH_PRIVATE_KEY` | **Runtime Secret** (redacted) | Full OpenSSH private key that authenticates as `user@212.72.189.15:2296` (same as local `~/.ssh/id_ed25519`) |

Paste the entire key, including `-----BEGIN …-----` / `-----END …-----` lines and a trailing newline.

Optional (Environment Variable, not secret):

| Name | Default |
|------|---------|
| `PROD_SSH_HOST` | `212.72.189.15` |
| `PROD_SSH_PORT` | `2296` |
| `PROD_SSH_USER` | `user` |
| `PROD_SSH_KNOWN_HOSTS` | (omit → `ssh-keyscan` on start) |

Scope the secret to the TG_parser / Cloud Agents environment used by the Phase-1 automation if the UI offers environment scoping.

## How it is applied

On Cloud Agent boot, `.cursor/environment.json` runs:

```bash
bash scripts/cursor_cloud_setup_prod_ssh.sh
```

That writes `~/.ssh/id_ed25519_prod` + `Host prod` in `~/.ssh/config`. The private key never appears in agent transcripts (Runtime Secret → `[REDACTED]`).

## Verify

1. Secret saved in Dashboard (`PROD_SSH_PRIVATE_KEY`, Runtime Secret).
2. `.cursor/environment.json` + `scripts/cursor_cloud_setup_prod_ssh.sh` present on the branch the agent checks out (`main`). Note: `.cursor/*` is gitignored except `environment.json` (see `.gitignore`).
3. Automation prompt step 0 must call the bootstrap script — canonical text: `docs/notes/PHASE1_WATCH_AUTOMATION_PROMPT.md`.
4. Manual run of automation [Phase-1 watch re-snapshot](https://cursor.com/automations/c4dada76-8107-11f1-ba66-0e7d0216e441) — agent log should show `cursor_cloud_setup_prod_ssh: ssh prod OK`, then live Prometheus reads (not Gap #5).
5. Close failed Gap #5 docs-PRs ([#322](https://github.com/AlexEfimov/TG_parser/pull/322), [#324](https://github.com/AlexEfimov/TG_parser/pull/324)) without merge once a successful run exists.

## Do not

- Commit private keys, `known_hosts` with secrets, or paste keys into PR bodies / chat.
- Disable the Phase-1 automation until W2 FINAL in the 48–72h billing-clean window.
