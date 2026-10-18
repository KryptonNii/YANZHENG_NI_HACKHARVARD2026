"""Start the prepared local API and web servers without extra console windows.

Run through sysup.cmd. Startup forcibly stops listeners on the configured ports
and starts fresh services. --check only probes existing listeners; it changes no
files and starts or stops no process. PID metadata is informational.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "var" / "services"
METADATA = STATE_DIR / "services.json"
API_PORT = 8008
WEB_PORT = 5181
APP_URL = f"http://127.0.0.1:{WEB_PORT}/"
OPENER = build_opener(ProxyHandler({}))
SERVICES = {
    "api": (API_PORT, f"http://127.0.0.1:{API_PORT}/api/health"),
    "web": (WEB_PORT, APP_URL),
}


def fetch(url: str) -> bytes:
    with OPENER.open(url, timeout=1.5) as response:
        return response.read(512_000)


def trialpilot_health(value: object) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("version"), str)
        and isinstance(value.get("offline"), bool)
        and all(isinstance(value.get(key), dict) for key in ("database", "engine", "params", "modules"))
    )


def probe(name: str) -> tuple[str, str]:
    port, url = SERVICES[name]
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            pass
    except OSError:
        return "missing", f"port {port} is available"
    try:
        if name == "web":
            page = fetch(url).decode("utf-8", errors="replace")
            if not re.search(r"<title>\s*TrialPilot\s*</title>", page, re.IGNORECASE):
                return "conflict", f"port {port} is occupied by an unrecognized web server"
            health = json.loads(fetch(f"{url}api/health"))
        else:
            health = json.loads(fetch(url))
        if not trialpilot_health(health):
            return "conflict", f"port {port} does not return recognizable TrialPilot health"
        if health["offline"]:
            return "conflict", f"TrialPilot on port {port} is in offline mode; restart its owning service in live mode"
        if health.get("status") != "ok":
            return "unready", f"TrialPilot on port {port} reports degraded health"
        return "ready", f"live TrialPilot is ready on port {port}"
    except (OSError, URLError, ValueError) as exc:
        # Do not print response bodies or exception details from another process.
        return "unready", f"port {port} is occupied but TrialPilot is not ready ({type(exc).__name__})"


def listener_pids(port: int) -> set[int]:
    """Read current Windows TCP listeners, never stale saved PID metadata."""
    if os.name != "nt":
        raise RuntimeError("Automatic port release is supported by the Windows launcher only.")
    result = subprocess.run(
        ["netstat", "-ano"], capture_output=True, text=True, errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW, timeout=10,
    )
    if result.returncode:
        raise RuntimeError(f"Could not inspect the process listening on port {port}.")
    owners = set()
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) != 5 or fields[0].upper() != "TCP":
            continue
        # Listening rows have a wildcard peer with port zero. This also works
        # when Windows localizes the LISTENING state label.
        if fields[2] not in ("0.0.0.0:0", "[::]:0"):
            continue
        if fields[1].rsplit(":", 1)[-1] == str(port) and fields[4].isdigit():
            owners.add(int(fields[4]))
    return owners


def release_port(port: int) -> None:
    """Force-stop only current owners of this port and wait for its release."""
    owners = listener_pids(port)
    for owner in sorted(owners):
        if owner <= 4 or owner == os.getpid():
            raise RuntimeError(f"Cannot stop protected PID {owner} on port {port}.")
    for owner in sorted(owners):
        if owner not in listener_pids(port):
            continue  # The original listener may have exited on its own.
        print(f"Port {port} is occupied by PID {owner}; force-stopping its process tree...", flush=True)
        result = subprocess.run(
            ["taskkill", "/PID", str(owner), "/T", "/F"],
            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=10,
        )
        if result.returncode and owner in listener_pids(port):
            raise RuntimeError(
                f"Could not stop PID {owner} on port {port}. "
                "If access was denied, run the launcher as administrator."
            )
    deadline = time.monotonic() + 5
    while remaining := listener_pids(port):
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Port {port} is still occupied by PID(s) {sorted(remaining)} after stopping.")
        time.sleep(0.2)
    if owners:
        print(f"Port {port} is available; starting a fresh service.", flush=True)


@contextmanager
def startup_lock():
    """A kernel lock is released even if the launcher is interrupted."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with (STATE_DIR / "startup.lock").open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("Another TrialPilot startup is in progress. Wait for it to finish.") from exc
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def child_environment() -> dict[str, str]:
    env_file = ROOT / ".env"
    if not env_file.is_file():
        raise RuntimeError("Create the root .env from .env.example and configure the API key first.")
    try:
        from dotenv import dotenv_values
    except ImportError as exc:
        raise RuntimeError("API dependencies are incomplete: python-dotenv is missing from api/.venv.") from exc
    environment = os.environ.copy()
    # Saved project configuration wins over settings from an old demo terminal.
    # Neither its values nor credentials are logged or put in argv.
    environment.update({key: value for key, value in dotenv_values(env_file).items() if value is not None})
    environment.update({
        "DEMO_OFFLINE": "0",
        "VITE_MOCK_API": "0",
        "TP_SEED_FIXTURE_DESIGNS": "0",
        "API_TARGET": f"http://127.0.0.1:{API_PORT}",
        "WEB_PORT": str(WEB_PORT),
        "PYTHONUNBUFFERED": "1",
    })
    return environment


def command(name: str) -> tuple[list[str], Path]:
    if name == "api":
        python = ROOT / "api" / ".venv" / "Scripts" / "python.exe"
        if not python.is_file():
            raise RuntimeError("Prepared API environment is missing: api/.venv/Scripts/python.exe.")
        return [
            str(python), "-m", "uvicorn", "trialpilot_api.main:create_app", "--factory",
            "--env-file", str(ROOT / ".env"), "--host", "127.0.0.1", "--port", str(API_PORT),
        ], ROOT
    node = shutil.which("node.exe") or shutil.which("node")
    vite = ROOT / "web" / "node_modules" / "vite" / "bin" / "vite.js"
    if not node or not vite.is_file():
        raise RuntimeError("Prepared web dependencies are missing: install Node.js and web/node_modules first.")
    return [node, str(vite), "--host", "127.0.0.1", "--port", str(WEB_PORT), "--strictPort"], ROOT / "web"


def write_metadata(records: dict[str, dict]) -> None:
    payload = {
        "updated_at": datetime.now(UTC).isoformat(),
        "app_url": APP_URL,
        "services": records,
    }
    temporary = STATE_DIR / "services.json.tmp"
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(METADATA)


def log_tail(path: Path, environment: dict[str, str]) -> str:
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        handle.seek(max(0, handle.tell() - 16_000))
        lines = handle.read().decode("utf-8", errors="replace").splitlines()[-20:]
    tail = "\n".join(lines)
    for key, value in environment.items():
        if len(value) >= 8 and any(term in key.upper() for term in ("KEY", "TOKEN", "SECRET", "PASSWORD", "PEPPER")):
            tail = tail.replace(value, "[redacted]")
    return tail


def start_services() -> None:
    with startup_lock():
        # Validate dependencies before interrupting any existing service.
        environment = child_environment()
        commands = {name: command(name) for name in SERVICES}
        for port, _ in SERVICES.values():
            release_port(port)
        started: dict[str, subprocess.Popen] = {}
        records: dict[str, dict] = {}
        logs: dict[str, Path] = {}
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        for name, (port, url) in SERVICES.items():
            argv, cwd = commands[name]
            log_path = STATE_DIR / f"{name}-{stamp}.log"
            logs[name] = log_path
            options: dict = {}
            if os.name == "nt":
                # Independent of the launching console; no extra window.
                options["creationflags"] = (
                    subprocess.CREATE_NO_WINDOW
                    | subprocess.DETACHED_PROCESS
                    | subprocess.CREATE_NEW_PROCESS_GROUP
                )
            else:
                options["start_new_session"] = True
            with log_path.open("ab", buffering=0) as output:
                process = subprocess.Popen(
                    argv, cwd=cwd, env=environment, stdin=subprocess.DEVNULL,
                    stdout=output, stderr=subprocess.STDOUT, close_fds=True, **options,
                )
            started[name] = process
            records[name] = {
                "port": port, "url": url, "state": "starting", "action": "started",
                "pid": process.pid, "log": str(log_path),
                "started_at": datetime.now(UTC).isoformat(),
            }
            write_metadata(records)
            print(f"Started {name} (PID {process.pid}); waiting for readiness...", flush=True)
        deadline = time.monotonic() + 20
        try:
            while True:
                for name, process in started.items():
                    if process.poll() is not None:
                        raise RuntimeError(f"{name} exited with code {process.returncode} during startup.")
                statuses = {name: probe(name) for name in SERVICES}
                if all(state == "ready" for state, _ in statuses.values()):
                    break
                if time.monotonic() >= deadline:
                    descriptions = "; ".join(f"{name}: {description}" for name, (_, description) in statuses.items())
                    raise RuntimeError(f"Readiness timed out after 20 seconds. {descriptions}")
                time.sleep(0.4)
        except RuntimeError:
            for name, path in logs.items():
                records[name]["state"] = "ready" if probe(name)[0] == "ready" else "needs_attention"
                print(f"\n{name} log: {path}\n{log_tail(path, environment)}", file=sys.stderr)
            write_metadata(records)
            raise
        for record in records.values():
            record["state"] = "ready"
        write_metadata(records)
        print(f"\nTrialPilot is ready in live mode: {APP_URL}", flush=True)
        print(f"Logs and PID metadata: {STATE_DIR}", flush=True)
        print("Both services keep running after this window closes.", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="read-only readiness check; start or stop nothing")
    mode.add_argument("--release-port", type=int, metavar="PORT", help="force-stop listeners on PORT, then exit")
    args = parser.parse_args()
    if args.release_port is not None and not 1 <= args.release_port <= 65535:
        parser.error("--release-port must be between 1 and 65535")
    if args.check:
        statuses = {name: probe(name) for name in SERVICES}
        for name, (state, description) in statuses.items():
            print(f"{name}: {state} - {description}")
        return 0 if all(state == "ready" for state, _ in statuses.values()) else 1
    try:
        if args.release_port is not None:
            with startup_lock():
                release_port(args.release_port)
        else:
            start_services()
        return 0
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"Startup failed: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Startup check interrupted. Any services already started were left running.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
