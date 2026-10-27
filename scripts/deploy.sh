#!/usr/bin/env bash
# First-time deployment of aware-server.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
_env_get() { sed -n "s/^$1=//p" "$REPO_DIR/.env" 2>/dev/null | tail -1 | tr -d "\"'"; }

APP_DIR="$REPO_DIR"
VENV="$APP_DIR/venv"
SERVICES="aware-gunicorn"
DEPLOY_USER="$(id -un)"
RUN_USER="${RUN_USER:-aware}"
DOMAIN="${DOMAIN:-$(_env_get DOMAIN)}"
SSL_CERT="${SSL_CERT:-$(_env_get SSL_CERT)}"
SSL_KEY="${SSL_KEY:-$(_env_get SSL_KEY)}"
SSL_CHAIN="${SSL_CHAIN:-$(_env_get SSL_CHAIN)}"INSTALL_CONFIGS="${INSTALL_CONFIGS:-yes}"  # first-time setup always installs the rendered configs

# shellcheck source=lib.sh
source "$(dirname "$(readlink -f "$0")")/lib.sh"

install_packages

cd "$APP_DIR"

echo "==> Setting up Python virtual environment"
if [ ! -d "$VENV" ]; then
    python3 -m venv venv
fi
# Editable install: the app reads static/ and .env relative to the checkout.
"$VENV/bin/pip" install -e .

ensure_run_user

if [ ! -f .env ]; then
    echo "==> Creating .env from .env.example"
    cp .env.example .env
    cat <<'MSG'
Created .env from .env.example. Fill in the per-deployment values before continuing:
  - DOMAIN
  - DEBUG=False
Then rerun this script.
MSG
    exit 1
fi
DOMAIN="${DOMAIN:-$(_env_get DOMAIN)}"

install_permissions

render_services
echo "==> Enabling and starting services"
sudo systemctl enable --now $SERVICES
verify_services_active

install_nginx

echo "==> Deployment complete."
