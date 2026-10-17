"""Parameter library: load + validate `data/params/*.yaml` (format: data/params/SCHEMA.md).

    load_params("data/params")            -> dict[str, Parameter]  (sorted by id)
    param_set_version(params)             -> "3f9a1c0b2d4e"         (first 12 hex of sha256)
    python -m trialpilot_contracts.params data/params   # validate from the command line
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .models import Parameter

ID_PATTERN = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")
YAML_SUFFIXES = (".yaml", ".yml")
_FIELDS = frozenset(Parameter.model_fields)


class ParamValidationError(ValueError):
    """Raised when the parameter library is invalid. `.problems` lists every problem found."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        lines = "\n".join(f"  - {p}" for p in problems)
        super().__init__(f"{len(problems)} problem(s) in parameter library:\n{lines}")


def validate_parameter(p: Parameter) -> list[str]:
    """Rules beyond the pydantic types. Returns human-readable problems (empty = valid)."""
    problems: list[str] = []
    if not ID_PATTERN.match(p.id):
        problems.append(f"{p.id!r}: id must be a lowercase dotted slug, e.g. 'ef.travel.car.average_km'")
    values = (p.value_low, p.value_mid, p.value_high)
    if not all(math.isfinite(v) for v in values):
        problems.append(f"{p.id}: values must be finite numbers")
    elif not p.value_low <= p.value_mid <= p.value_high:
        problems.append(
            f"{p.id}: need value_low <= value_mid <= value_high, got {p.value_low}, {p.value_mid}, "
            f"{p.value_high}"
        )
    if not p.label.strip():
        problems.append(f"{p.id}: label must not be empty")
    if not p.unit.strip():
        problems.append(f"{p.id}: unit must not be empty")
    if p.assumption and not (p.rationale and p.rationale.strip()):
        problems.append(f"{p.id}: assumption=true requires a rationale")
    if p.source_url and p.source_year is None:
        problems.append(f"{p.id}: source_url requires source_year")
    if not p.assumption:
        if not (p.source_url or p.source_title):
            problems.append(
                f"{p.id}: not an assumption, so it needs source_title or source_url "
                "(or set assumption: true with a rationale)"
            )
        elif p.source_year is None:
            problems.append(f"{p.id}: sourced parameter requires source_year")
    if p.version < 1:
        problems.append(f"{p.id}: version must be >= 1")
    return problems


def _yaml_files(path: Path, include_examples: bool) -> list[Path]:
    if path.is_file():
        return [path]
    if not path.is_dir():
        raise FileNotFoundError(f"parameter library not found: {path}")
    return sorted(
        f
        for f in path.rglob("*")
        if f.is_file()
        and f.suffix in YAML_SUFFIXES
        and (include_examples or not f.name.startswith("_"))
    )


def _entries(file: Path, problems: list[str]) -> list[tuple[str, dict[str, Any]]]:
    """Parse one YAML file into (location, raw entry) pairs, recording structural problems."""
    try:
        doc = yaml.safe_load(file.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        problems.append(f"{file}: invalid YAML: {exc}")
        return []
    if doc is None:
        return []
    if not isinstance(doc, dict) or not isinstance(doc.get("parameters"), list):
        problems.append(f"{file}: top level must be a mapping with a 'parameters:' list")
        return []
    unknown_top = set(doc) - {"parameters", "defaults"}
    if unknown_top:
        problems.append(f"{file}: unknown top-level keys {sorted(unknown_top)}")
    defaults = doc.get("defaults") or {}
    if not isinstance(defaults, dict):
        problems.append(f"{file}: 'defaults' must be a mapping")
        defaults = {}
    out: list[tuple[str, dict[str, Any]]] = []
    for i, raw in enumerate(doc["parameters"]):
        where = f"{file}[{i}]"
        if not isinstance(raw, dict):
            problems.append(f"{where}: each parameter must be a mapping")
            continue
        out.append((where, {**defaults, **raw}))
    return out


def load_params(directory: str | Path, *, include_examples: bool = False) -> dict[str, Parameter]:
    """Load and validate every parameter under `directory` (recursive), or a single YAML file.

    Files whose name starts with `_` (e.g. `_example.yaml`) are skipped unless
    `include_examples=True` or the file is passed directly. Raises ParamValidationError
    listing *all* problems; returns parameters sorted by id.
    """
    problems: list[str] = []
    params: dict[str, Parameter] = {}
    seen_at: dict[str, str] = {}
    for file in _yaml_files(Path(directory), include_examples):
        for where, raw in _entries(file, problems):
            label = f"{where} ({raw.get('id', '?')})"
            unknown = set(raw) - _FIELDS
            if unknown:
                problems.append(f"{label}: unknown keys {sorted(unknown)} (typo?)")
                continue
            try:
                p = Parameter.model_validate(raw)
            except ValidationError as exc:
                errs = "; ".join(
                    f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()
                )
                problems.append(f"{label}: {errs}")
                continue
            if p.id in seen_at:
                problems.append(f"{p.id}: duplicate id ({seen_at[p.id]} and {where})")
                continue
            seen_at[p.id] = where
            problems.extend(validate_parameter(p))
            params[p.id] = p
    if problems:
        raise ParamValidationError(problems)
    return dict(sorted(params.items()))


def param_set_version(params: Mapping[str, Parameter] | Iterable[Parameter]) -> str:
    """Content hash of a parameter set: first 12 hex of sha256 over the id-sorted, canonical JSON.

    Order-independent; changes whenever any field of any parameter changes.
    Use it for ScenarioResult.parameter_set_version.
    """
    items = params.values() if isinstance(params, Mapping) else params
    payload = sorted((p.model_dump(mode="json") for p in items), key=lambda d: str(d["id"]))
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Validate the TrialPilot parameter library.")
    ap.add_argument("path", nargs="?", default="data/params", help="directory or YAML file")
    ap.add_argument("--include-examples", action="store_true", help="also load _*.yaml files")
    args = ap.parse_args(argv)
    try:
        params = load_params(args.path, include_examples=args.include_examples)
    except (ParamValidationError, FileNotFoundError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    n_assumed = sum(p.assumption for p in params.values())
    print(
        f"OK: {len(params)} parameters ({n_assumed} assumptions) in {args.path}, "
        f"parameter_set_version={param_set_version(params)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
