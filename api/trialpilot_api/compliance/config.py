"""GxP-relevant configuration of the compliance layer.

The control values are code constants, not environment variables: changing them is a
change-controlled code change (mapped to requirements in `validation/component_map.yaml`).
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


def default_db_path() -> Path:
    for name in ("TP_COMPLIANCE_DB", "TP_DB_PATH"):
        value = os.environ.get(name, "").strip()
        if value:
            return Path(value)
    return repo_root() / "var" / "trialpilot.sqlite"


def validation_out_dir() -> Path:
    value = os.environ.get("TP_VALIDATION_OUT", "").strip()
    return Path(value) if value else repo_root() / "validation" / "out"


def pepper() -> tuple[str, bool]:
    """(pepper, is_configured). Falls back to the documented dev pepper when unset."""
    value = os.environ.get("TP_SECRET_PEPPER", "")
    return (value, True) if value else (DEV_PEPPER, False)
