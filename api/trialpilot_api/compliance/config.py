"""GxP-relevant configuration of the compliance layer.

The control values are code constants, not environment variables: changing them is a
change-controlled code change (mapped to requirements in `validation/component_map.yaml`).

Runtime settings (DB path, pepper, output dir) come from the process environment first, then from
the repo's `.env` (same precedence as A5's settings), so the API and the `tpv` CLI agree.
"""

from __future__ import annotations

import os
from pathlib import Path

# E-signature re-authentication: lock the signer after this many consecutive wrong PINs ...
MAX_FAILED_ATTEMPTS = 3
# ... for this long.
LOCKOUT_SECONDS = 300

# Actors whose name starts with this prefix are machine/AI actors; they may never sign.
AI_ACTOR_PREFIX = "ai:"

# Used only when TP_SECRET_PEPPER is not set (local dev / tests). Not a secret, by design.
DEV_PEPPER = "trialpilot-dev-pepper-NOT-SECRET"


def repo_root() -> Path:
    # compliance/ -> trialpilot_api/ -> api/ -> <repo root>
    return Path(__file__).resolve().parents[3]


def _dotenv() -> dict[str, str]:
    path = repo_root() / ".env"
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip().removeprefix("export ").strip()] = value.strip().strip("'\"")
    return values


def env(name: str) -> str:
    """Environment variable, else the repo `.env` value, else ""."""
    value = os.environ.get(name)
    if value is not None:
        return value.strip()
    return _dotenv().get(name, "").strip()


def default_db_path() -> Path:
    for name in ("TP_COMPLIANCE_DB", "TP_DB_PATH"):
        value = env(name)
        if value:
            return Path(value)
    return repo_root() / "var" / "trialpilot.sqlite"


def validation_out_dir() -> Path:
    value = env("TP_VALIDATION_OUT")
    return Path(value) if value else repo_root() / "validation" / "out"


def pepper() -> tuple[str, bool]:
    """(pepper, is_configured). Falls back to the documented dev pepper when unset."""
    value = env("TP_SECRET_PEPPER")
    return (value, True) if value else (DEV_PEPPER, False)
