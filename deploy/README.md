# Deploying TrialPilot (one Linux server, Docker + Caddy)

One container serves the API under `/api` and the built web app at `/` (`api/Dockerfile`).
The container is published on **127.0.0.1:8000 only**; Caddy on the host terminates HTTPS and is the only
public listener. SQLite lives in the `tp-data` Docker volume. The image runs live by default
(`DEMO_OFFLINE=0`); set `DEMO_OFFLINE=1` to serve cached fixtures only.

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
cp .env.example .env          # DEMO_OFFLINE=1 for a cached-only demo; set TP_SECRET_PEPPER to a random string
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

## Public demo on Hugging Face Spaces

The public demo, https://surround1ngkni-trialpilot.hf.space, is the same image on a Docker Space
(`Surround1ngkni/trialpilot`, CPU basic: 2 vCPU, 16 GB). The Space repo is a snapshot of a commit, not a mirror:

1. `git archive <commit>` into an empty folder; copy `api/Dockerfile` to `Dockerfile` and
   `api/Dockerfile.dockerignore` to `.dockerignore`; drop `.github/`, `handoffs/`, `reviews/`, `docs/agents/`.
2. Prepend a README header with `sdk: docker` and `app_port: 8000`.
3. Copy a generated validation package (`validation/out/clean-clone/<run>/package`) to
   `validation/published/package` so the Validation page has a package to show.
4. `hf upload Surround1ngkni/trialpilot <folder> . --repo-type space`.

Space variables: `DEMO_OFFLINE=0`, `TP_DATA_DIR=/app/var` (writable by uid 1000) and
`TP_VALIDATION_OUT=/app/validation/published`. Storage is not persistent: a restart or rebuild resets
saved designs, scenarios and approvals to the seeded state. CPU basic sleeps after 48 hours without
visits; an external cron pings `/api/health` every 10 minutes.

The earlier Render free instance (512 MB) restarted when a live import of a 47,000-patient trial
ran the drug-supply simulation; the supply simulation now caps patients per chunk.

## Without Docker (fallback)

```bash
uv sync --project api
uv run --project api python -m trialpilot_api.seed
(cd web && pnpm install && pnpm exec vite build)      # API then serves web/dist at /
DEMO_OFFLINE=1 uv run --project api uvicorn trialpilot_api.main:app --host 127.0.0.1 --port 8000
```

Status: the image builds and runs on Hugging Face Spaces (above). The single-server Docker + Caddy
setup in sections 1–3 has not been run (see handoffs/A5.md).
