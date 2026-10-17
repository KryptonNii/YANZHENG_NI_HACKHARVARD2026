#!/usr/bin/env bash
# Build and (re)start TrialPilot on a Linux server, then check health. Idempotent.
#   bash deploy/deploy.sh                 # from the repo root
# Needs: Docker Engine + compose plugin. Caddy (host) terminates HTTPS — see deploy/README.md.
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] || { cp .env.example .env; echo "created .env from .env.example (edit secrets there)"; }

docker compose build api
docker compose up -d api

echo -n "waiting for /api/health "
for _ in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:${API_PORT:-8000}/api/health >/dev/null 2>&1; then
    echo "ok"
    curl -fsS http://127.0.0.1:${API_PORT:-8000}/api/health | head -c 600; echo
    exit 0
  fi
  echo -n "."; sleep 2
done
echo " FAILED"; docker compose logs --tail 80 api; exit 1
