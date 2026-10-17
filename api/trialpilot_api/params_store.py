"""Parameter library: load `data/params/*.yaml`, keep immutable copies in the DB.

- Loading and the version hash use A1's `trialpilot_contracts.params` (same rules everywhere).
- The snapshot reloads automatically when a YAML file changes (A10 edits live during dev).
- Every (id, version) is stored once in `params`; a value that changes without a version bump
  is reported as a conflict (never silently overwritten). Every parameter_set_version is stored
  in `param_sets` so an old scenario can always list the exact parameters it used.
- An invalid library is reported, not used: compute answers 503 `params_invalid` with the problems.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.engine import Engine
from sqlmodel import Session, select
from trialpilot_contracts.params import ParamValidationError, load_params, param_set_version

from ._contracts import Parameter
from .db import ParamRow, ParamSetRow, utcnow_iso
from .hashing import canonical_json, sha256_hex

log = logging.getLogger("trialpilot.params")

_RELOAD_CHECK_SECONDS = 1.0


# ---------------------------------------------------------------------------------------
# Loader (A1's trialpilot_contracts.params is the reference implementation)
# ---------------------------------------------------------------------------------------
class ParamLibraryError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__(f"{len(problems)} problem(s) in parameter library")


def _yaml_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(
        f
        for f in directory.rglob("*")
        if f.is_file() and f.suffix in (".yaml", ".yml") and not f.name.startswith("_")
    )


def load_library(directory: Path) -> dict[str, Parameter]:
    """Load + validate (data/params/SCHEMA.md rules). Raises ParamLibraryError listing every
    problem. A missing directory is an empty library."""
    if not directory.is_dir():
        return {}
    try:
        return load_params(directory)
    except ParamValidationError as exc:
        raise ParamLibraryError(list(exc.problems)) from exc


# ---------------------------------------------------------------------------------------
# Snapshot store
# ---------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ParamSnapshot:
    params: dict[str, Parameter]
    version: str
    ok: bool
    problems: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    loaded_at: str = ""
    source_dir: str = ""

    @property
    def assumption_count(self) -> int:
        return sum(1 for p in self.params.values() if p.assumption)


class ParamStore:
    def __init__(self, directory: Path, engine: Engine) -> None:
        self.directory = directory
        self.engine = engine
        self._lock = threading.Lock()
        self._signature: tuple[Any, ...] | None = None
        self._checked_at = 0.0
        self._snapshot = ParamSnapshot(params={}, version="", ok=False, problems=["not loaded"])

    # -- public -----------------------------------------------------------------------
    def current(self) -> ParamSnapshot:
        now = time.monotonic()
        if now - self._checked_at < _RELOAD_CHECK_SECONDS and self._signature is not None:
            return self._snapshot
        with self._lock:
            self._checked_at = now
            sig = self._files_signature()
            if sig != self._signature:
                self._snapshot = self._load()
                self._signature = sig
            return self._snapshot

    def history(self, param_id: str) -> list[Parameter]:
        with Session(self.engine) as s:
            rows = s.exec(
                select(ParamRow)
                .where(ParamRow.id == param_id)
                .order_by(ParamRow.version, ParamRow.loaded_at)
            ).all()
        return [Parameter.model_validate_json(r.data) for r in rows]

    def params_for_set(self, set_version: str) -> list[Parameter] | None:
        """Exact parameters behind a parameter_set_version (None if never seen by this API)."""
        with Session(self.engine) as s:
            ps = s.get(ParamSetRow, set_version)
            if ps is None:
                return None
            out: list[Parameter] = []
            for pid, content_hash in json.loads(ps.members):
                row = s.get(ParamRow, (pid, content_hash))
                if row is not None:
                    out.append(Parameter.model_validate_json(row.data))
            return out

    # -- internals --------------------------------------------------------------------
    def _files_signature(self) -> tuple[Any, ...]:
        files = _yaml_files(self.directory)
        sig: list[Any] = [str(self.directory)]
        for f in files:
            try:
                st = f.stat()
                sig.append((str(f), st.st_mtime_ns, st.st_size))
            except OSError:
                sig.append((str(f), None, None))
        return tuple(sig)

    def _load(self) -> ParamSnapshot:
        loaded_at = utcnow_iso()
        try:
            params = load_library(self.directory)
        except ParamLibraryError as exc:
            log.warning("parameter library invalid", extra={"problems": exc.problems[:20]})
            return ParamSnapshot(
                params={}, version="", ok=False, problems=exc.problems, loaded_at=loaded_at,
                source_dir=str(self.directory),
            )
        except Exception as exc:  # unreadable directory, etc.
            log.exception("parameter library failed to load")
            return ParamSnapshot(
                params={}, version="", ok=False, problems=[f"load failed: {exc}"],
                loaded_at=loaded_at, source_dir=str(self.directory),
            )
        version = param_set_version(params)
        conflicts = self._persist(params, version, loaded_at)
        log.info(
            "parameter library loaded",
            extra={"count": len(params), "param_set_version": version, "conflicts": len(conflicts)},
        )
        return ParamSnapshot(
            params=params, version=version, ok=True, conflicts=conflicts, loaded_at=loaded_at,
            source_dir=str(self.directory),
        )

    def _persist(self, params: dict[str, Parameter], version: str, now: str) -> list[str]:
        conflicts: list[str] = []
        members: list[list[str]] = []
        with Session(self.engine) as s:
            for p in params.values():
                data = canonical_json(p)
                h = sha256_hex(data)
                members.append([p.id, h])
                same_version = s.exec(
                    select(ParamRow).where(ParamRow.id == p.id, ParamRow.version == p.version)
                ).all()
                if any(r.content_hash == h for r in same_version):
                    continue
                if same_version:
                    conflicts.append(
                        f"{p.id} v{p.version} changed without a version bump (bump `version` in "
                        "the YAML); both values are kept for provenance"
                    )
                s.add(ParamRow(id=p.id, content_hash=h, version=p.version, data=data,
                               loaded_at=now))
            if s.get(ParamSetRow, version) is None:
                members.sort()
                s.add(ParamSetRow(version=version, members=json.dumps(members),
                                  count=len(params), created_at=now))
            s.commit()
        return conflicts
