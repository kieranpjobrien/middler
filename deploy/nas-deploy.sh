#!/usr/bin/env bash
# Deploy or refresh middler on the Synology NAS.
#
# Docker requires root on Synology (the daemon socket is root-only), so run this
# with sudo from the project directory:
#
#     cd /volume1/docker/middler && sudo ./deploy/nas-deploy.sh
#
# It is idempotent: safe to re-run to rebuild and restart after a code update.
set -euo pipefail

# Synology's sudo secure_path can omit /usr/local/bin, where the docker and
# docker-compose symlinks live — put it on PATH so this works under sudo.
export PATH="/usr/local/bin:/usr/bin:/bin:${PATH:-}"

cd "$(dirname "$0")/.."
PROJECT_DIR="$(pwd)"

# Pick whichever compose is available (Synology ships the standalone binary).
if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
else
  COMPOSE="docker-compose"
fi

# First run: seed .env from the template so the stack can start (it will warn
# about missing API keys and record nothing until you fill them in).
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from template — add your API keys, then re-run or 'restart middler'."
fi

echo "Building and starting (project: ${PROJECT_DIR})..."
$COMPOSE up -d --build
echo
$COMPOSE ps
echo
echo "Follow logs:  cd ${PROJECT_DIR} && sudo ${COMPOSE} logs -f middler"
echo "Healthcheck:  cd ${PROJECT_DIR} && sudo ${COMPOSE} exec middler uv run middler-healthcheck"
echo "After adding keys to .env:  cd ${PROJECT_DIR} && sudo ${COMPOSE} restart middler"
