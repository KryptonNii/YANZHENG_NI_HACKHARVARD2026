"""Repository paths, configuration, requirements loading and small shared helpers for `tpv`."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from trialpilot_api.compliance import config as compliance_config
from trialpilot_api.compliance.hashing import fs_path

REQ_ID = re.compile(r"^URS-\d{3}$")
RISKS = ("H", "M", "L")
DRAFT_STAMP = "DRAFT — requires human review"


class TpvError(Exception):
    """A user-facing problem (bad input, missing prerequisite). Exit code 2."""


class Refused(Exception):
    """A control refused the action (e.g. protocol not approved). Exit code 3."""


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(fs_path(path), "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_text(path: Path, text: str) -> Path:
    target = fs_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n": identical bytes (and hashes) on Windows and Linux
    with open(target, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return path


def write_json(path: Path, data: Any) -> Path:
    return write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def read_json(path: Path) -> Any:
    return json.loads(fs_path(path).read_text(encoding="utf-8"))


def find_repo(start: Path | None = None) -> Path:
    env = os.environ.get("TPV_REPO", "").strip()
    if env:
        return Path(env).resolve()
    here = Path(__file__).resolve().parents[2]  # validation/trialpilot_validation/x.py -> repo
    if (here / "validation" / "requirements.yaml").exists():
        return here
    cur = (start or Path.cwd()).resolve()
    for p in (cur, *cur.parents):
        if (p / "validation" / "requirements.yaml").exists():
            return p
    raise TpvError("Cannot find the repository root (no validation/requirements.yaml found).")


@dataclass
class Ctx:
    repo: Path
    config: dict[str, Any]

    @property
    def vdir(self) -> Path:
        return self.repo / "validation"

    @property
    def out(self) -> Path:
        # Process env, then the repo .env: the lookup the API and the compliance DB path use.
        value = compliance_config.env("TP_VALIDATION_OUT")
        return Path(value) if value else self.vdir / "out"

    def rel(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.repo.resolve()).as_posix()
        except ValueError:
            return path.as_posix()

    # ---- requirements -----------------------------------------------------------------------
    def requirements(self) -> list[dict[str, Any]]:
        return load_requirements(self.vdir / "requirements.yaml")

    def requirements_doc(self) -> dict[str, Any]:
        data = yaml.safe_load((self.vdir / "requirements.yaml").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}

    # ---- git ----------------------------------------------------------------------------------
    def git(self, *args: str, check: bool = True) -> str:
        proc = subprocess.run(["git", *args], cwd=self.repo, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        if check and proc.returncode != 0:
            raise TpvError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
        return proc.stdout.strip()

    def git_info(self) -> dict[str, Any]:
        try:
            sha = self.git("rev-parse", "HEAD")
            dirty_lines = self.git("status", "--porcelain", "--untracked-files=no").splitlines()
            branch = self.git("rev-parse", "--abbrev-ref", "HEAD", check=False)
            return {"commit": sha, "branch": branch, "dirty": bool(dirty_lines),
                    "dirty_files": len(dirty_lines)}
        except (TpvError, FileNotFoundError):
            return {"commit": None, "branch": None, "dirty": None, "dirty_files": None}


def load_ctx(repo: Path | None = None) -> Ctx:
    root = (repo or find_repo()).resolve()
    cfg_path = root / "validation" / "tpv_config.yaml"
    config = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
    config = config or {}
    config.setdefault("system", "TrialPilot")
    config.setdefault("protocol_id", "OQ-TP-001")
    config.setdefault("report_id", "VSR-TP-001")
    config.setdefault("change_record_prefix", "CR-TP")
    config.setdefault("suites", [])
    config.setdefault("env", {})
    return Ctx(root, config)


def load_requirements(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise TpvError(f"{path} not found.")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise TpvError(f"{path}: 'items' must be a non-empty list.")
    problems: list[str] = []
    seen: set[str] = set()
    for i, it in enumerate(items):
        where = f"item {i + 1}"
        if not isinstance(it, dict):
            problems.append(f"{where}: not a mapping")
            continue
        rid = str(it.get("id", ""))
        where = rid or where
        if not REQ_ID.match(rid):
            problems.append(f"{where}: id must look like URS-001")
        if rid in seen:
            problems.append(f"{where}: duplicate id")
        seen.add(rid)
        if not str(it.get("text", "")).strip():
            problems.append(f"{where}: text is empty")
        if it.get("risk") not in RISKS:
            problems.append(f"{where}: risk must be one of H/M/L")
        if not str(it.get("risk_rationale", "")).strip():
            problems.append(f"{where}: risk_rationale is required")
        if not isinstance(it.get("gxp"), bool):
            problems.append(f"{where}: gxp must be true or false")
    if problems:
        raise TpvError("Invalid requirements.yaml:\n  - " + "\n  - ".join(problems))
    return items


def short(text: str, n: int = 90) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def md_escape(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")
