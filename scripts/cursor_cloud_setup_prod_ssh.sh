#!/usr/bin/env bash
# Materialize `ssh prod` for Cursor Cloud Agents / Automations from Runtime Secrets.
#
# Required (Cursor Dashboard → Cloud Agents → Secrets, type: Runtime Secret):
#   PROD_SSH_PRIVATE_KEY  — full OpenSSH private key (same as local ~/.ssh/id_ed25519)
#
# Optional Environment Variables (non-secret defaults match local Host prod):
#   PROD_SSH_HOST=212.72.189.15
#   PROD_SSH_PORT=2296
#   PROD_SSH_USER=user
#   PROD_SSH_KNOWN_HOSTS  — if set, written to known_hosts as-is; else ssh-keyscan
#
# Idempotent. Safe to run from .cursor/environment.json install + start.
# Never prints the private key.

set -euo pipefail

# Prefer explicit Runtime Secret; accept common aliases if the dashboard name differs.
if [[ -z "${PROD_SSH_PRIVATE_KEY:-}" && -n "${SSH_PRIVATE_KEY:-}" ]]; then
  PROD_SSH_PRIVATE_KEY="${SSH_PRIVATE_KEY}"
fi
if [[ -z "${PROD_SSH_PRIVATE_KEY:-}" && -n "${CURSOR_SSH_PRIVATE_KEY:-}" ]]; then
  PROD_SSH_PRIVATE_KEY="${CURSOR_SSH_PRIVATE_KEY}"
fi

if [[ -z "${PROD_SSH_PRIVATE_KEY:-}" ]]; then
  echo "cursor_cloud_setup_prod_ssh: PROD_SSH_PRIVATE_KEY unset — skip (local runners use host ~/.ssh)"
  exit 0
fi

HOST="${PROD_SSH_HOST:-212.72.189.15}"
PORT="${PROD_SSH_PORT:-2296}"
USER_NAME="${PROD_SSH_USER:-user}"
SSH_DIR="${HOME}/.ssh"
KEY_PATH="${SSH_DIR}/id_ed25519_prod"
CONFIG_PATH="${SSH_DIR}/config"
KNOWN_HOSTS_PATH="${SSH_DIR}/known_hosts"

umask 077
mkdir -p "${SSH_DIR}"
chmod 700 "${SSH_DIR}"

# Normalize newlines (secrets UIs sometimes flatten or use CRLF).
printf '%s\n' "${PROD_SSH_PRIVATE_KEY}" | tr -d '\r' > "${KEY_PATH}"
# Ensure trailing newline (OpenSSH rejects keys without one).
[[ -n "$(tail -c1 "${KEY_PATH}" 2>/dev/null || true)" ]] || printf '\n' >> "${KEY_PATH}"
chmod 600 "${KEY_PATH}"

# Host alias used by runbooks / Phase-1 watch automation.
{
  echo "Host prod tg-parser-prod"
  echo "  HostName ${HOST}"
  echo "  Port ${PORT}"
  echo "  User ${USER_NAME}"
  echo "  IdentityFile ${KEY_PATH}"
  echo "  IdentitiesOnly yes"
  echo "  ServerAliveInterval 30"
  echo "  ServerAliveCountMax 4"
  echo "  StrictHostKeyChecking accept-new"
} > "${CONFIG_PATH}"
chmod 600 "${CONFIG_PATH}"

if [[ -n "${PROD_SSH_KNOWN_HOSTS:-}" ]]; then
  printf '%s\n' "${PROD_SSH_KNOWN_HOSTS}" | tr -d '\r' > "${KNOWN_HOSTS_PATH}"
  chmod 600 "${KNOWN_HOSTS_PATH}"
elif command -v ssh-keyscan >/dev/null 2>&1; then
  # Best-effort pin; failures must not block agent start (network allowlist etc.).
  ssh-keyscan -p "${PORT}" -T 5 "${HOST}" >> "${KNOWN_HOSTS_PATH}" 2>/dev/null || true
  chmod 600 "${KNOWN_HOSTS_PATH}" 2>/dev/null || true
fi

if ssh -o BatchMode=yes -o ConnectTimeout=8 prod 'echo ok' >/dev/null 2>&1; then
  echo "cursor_cloud_setup_prod_ssh: ssh prod OK"
else
  echo "cursor_cloud_setup_prod_ssh: key installed but ssh prod smoke failed (check secret / firewall / allowlist)" >&2
  # Non-zero would break every Cloud Agent boot; leave soft so non-prod tasks still run.
  exit 0
fi
