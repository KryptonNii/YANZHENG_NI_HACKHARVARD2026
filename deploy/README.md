# Deploying TrialPilot (one Linux server, Docker + Caddy)

One container serves the API under `/api` and the built web app at `/` (`api/Dockerfile`).
The container is published on **127.0.0.1:8000 only**; Caddy on the host terminates HTTPS and is the only
public listener. SQLite lives in the `tp-data` Docker volume. The demo runs offline (`DEMO_OFFLINE=1`).

## 1. Server prerequisites (Ubuntu/Debian, once)

```bash
# Docker Engine + compose plugin: https://docs.docker.com/engine/install/
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"   # log out and in again
# Caddy: https://caddyserver.com/docs/install#debian-ubuntu-raspbian
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy
```

Firewall: allow 22, 80, 443 only (`sudo ufw allow OpenSSH && sudo ufw allow 80,443/tcp && sudo ufw enable`).
Port 8000 stays private because Docker binds it to 127.0.0.1.

## 2. App

```bash
git clone <repo-url> trialpilot && cd trialpilot
cp .env.example .env          # keep DEMO_OFFLINE=1 for the demo; set TP_SECRET_PEPPER to a random string
bash deploy/deploy.sh         # docker compose build + up -d, then waits for /api/health
```

## 3. HTTPS

1. DNS: an `A` (and `AAAA`) record for your domain → the server's IP.
2. `echo 'TP_DOMAIN=trialpilot.example.org' | sudo tee -a /etc/default/caddy`
3. `sudo cp deploy/Caddyfile /etc/caddy/Caddyfile && sudo systemctl reload caddy`
4. `curl -fsS https://trialpilot.example.org/api/health`

Caddy obtains and renews the certificate automatically. The demo identity is a plain header
(`X-User` / `X-Role`), so for a public URL uncomment `basic_auth` in the Caddyfile (`caddy hash-password`).

## Operate

| Task | Command |
|---|---|
| Logs | `docker compose logs -f api` (JSON lines with request ids) |
| Update | `git pull && bash deploy/deploy.sh` |
| Re-seed (idempotent) | `docker compose exec api python -m trialpilot_api.seed` |
| Backup DB | `docker compose exec api python -c "import sqlite3; s=sqlite3.connect('/data/trialpilot.sqlite'); d=sqlite3.connect('/data/backup.sqlite'); s.backup(d)"` then `docker compose cp api:/data/backup.sqlite .` |
| Reset demo data | `docker compose down -v && bash deploy/deploy.sh` (deletes the volume) |
| Health | `curl -fsS http://127.0.0.1:8000/api/health` |

## Without Docker (fallback)

```bash
uv sync --project api
uv run --project api python -m trialpilot_api.seed
(cd web && pnpm install && pnpm exec vite build)      # API then serves web/dist at /
DEMO_OFFLINE=1 uv run --project api uvicorn trialpilot_api.main:app --host 127.0.0.1 --port 8000
```

Status: these files were written on a Windows dev machine **without Docker**; the image build and the
Caddy setup have not been run yet (see handoffs/A5.md).
