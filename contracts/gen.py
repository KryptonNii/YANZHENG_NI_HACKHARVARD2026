"""Generate contracts/schema/*.json (JSON Schema per model) and web/src/contracts.ts (TypeScript).

    python contracts/gen.py          # write files
    python contracts/gen.py --check  # exit 1 if the committed files are stale (CI)

Deterministic: same models -> byte-identical output on every OS (LF line endings).
Models and Literal aliases are discovered from trialpilot_contracts.models in source order,
so new models need no change here.
"""

from __future__ import annotations

import argparse
import inspect
import json
import re
import sys
import types
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "contracts"))

from trialpilot_contracts import constants, models  # noqa: E402

SCHEMA_DIR = ROOT / "contracts" / "schema"
TS_FILE = ROOT / "web" / "src" / "contracts.ts"
JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"


def discover() -> tuple[list[type[BaseModel]], dict[str, Any]]:
    """Models and module-level Literal aliases (EventType, Role) in definition order."""
    found: list[type[BaseModel]] = []
    aliases: dict[str, Any] = {}
    for name, obj in vars(models).items():
        if inspect.isclass(obj) and issubclass(obj, BaseModel) and obj.__module__ == models.__name__:
            found.append(obj)
        elif get_origin(obj) is Literal:
            aliases[name] = obj
    return found, aliases


# ---------------------------------------------------------------- JSON Schema
def json_schemas(found: list[type[BaseModel]]) -> dict[Path, str]:
    out: dict[Path, str] = {}
    for model in found:
        schema = {"$schema": JSON_SCHEMA_DIALECT, **model.model_json_schema()}
        out[SCHEMA_DIR / f"{model.__name__}.json"] = json.dumps(schema, indent=2) + "\n"
    return out


# ---------------------------------------------------------------- TypeScript
def field_comments(model: type[BaseModel]) -> dict[str, str]:
    """Trailing `# comments` on single-field lines of the class body -> JSDoc."""
    comments: dict[str, str] = {}
    for line in inspect.getsource(model).splitlines():
        m = re.match(r"^\s+(\w+)\s*:[^;#]*#\s*(.+?)\s*$", line)
        if m:
            comments[m.group(1)] = m.group(2)
    return comments


def pascal(name: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in name.split("_"))


class TsWriter:
    def __init__(self, aliases: dict[str, Any]) -> None:
        self.aliases: dict[str, Any] = dict(aliases)  # name -> Literal[...]
        self.generated: list[str] = []  # alias names created from fields, in order

    def literal_name(self, lit: Any, suggested: str) -> str:
        for name, existing in self.aliases.items():
            if existing == lit:
                return name
        self.aliases[suggested] = lit
        self.generated.append(suggested)
        return suggested

    def ts(self, ann: Any, hint: str) -> str:
        origin, args = get_origin(ann), get_args(ann)
        if ann is Any:
            return "unknown"
        if ann is type(None):
            return "null"
        if ann is str or ann in (datetime, date):
            return "string"
        if ann is bool:
            return "boolean"
        if ann in (int, float):
            return "number"
        if ann is dict or (origin is dict and not args):
            return "Record<string, unknown>"
        if origin is dict:
            return f"Record<string, {self.ts(args[1], hint)}>"
        if ann is list or origin is list:
            inner = self.ts(args[0], hint) if args else "unknown"
            return f"({inner})[]" if " | " in inner else f"{inner}[]"
        if origin is Literal:
            return self.literal_name(ann, hint)
        if origin in (Union, types.UnionType):
            return " | ".join(self.ts(a, hint) for a in args)
        if inspect.isclass(ann) and issubclass(ann, BaseModel):
            return ann.__name__
        raise TypeError(f"gen.py: no TypeScript mapping for {ann!r} ({hint})")

    def interface(self, model: type[BaseModel]) -> str:
        comments = field_comments(model)
        lines = [f"export interface {model.__name__} {{"]
        for name, field in model.model_fields.items():
            ts_type = self.ts(field.annotation, model.__name__ + pascal(name))
            if name in comments:
                lines.append(f"  /** {comments[name]} */")
            lines.append(f"  {name}: {ts_type};")
        lines.append("}")
        return "\n".join(lines)


def literal_alias(name: str, lit: Any) -> str:
    values = [json.dumps(v) for v in get_args(lit)]
    one_line = f"export type {name} = {' | '.join(values)};"
    if len(one_line) <= 100:
        return one_line
    return f"export type {name} =\n" + "\n".join(f"  | {v}" for v in values) + ";"


def const_tuple(name: str, values: tuple[str, ...]) -> str:
    body = "\n".join(f"  {json.dumps(v)}," for v in values)
    return f"export const {name} = [\n{body}\n] as const;"


def typescript(found: list[type[BaseModel]], aliases: dict[str, Any]) -> str:
    w = TsWriter(aliases)
    interfaces = [w.interface(m) for m in found]  # discovers field-level Literal aliases
    named = [literal_alias(n, aliases[n]) for n in aliases]
    generated = [literal_alias(n, w.aliases[n]) for n in w.generated]
    consts = [
        const_tuple("CARBON_MODULES", constants.CARBON_MODULES),
        "export type CarbonModuleId = (typeof CARBON_MODULES)[number];",
        const_tuple("EXTENSION_MODULES", constants.EXTENSION_MODULES),
        const_tuple("EXCLUDED_BY_DEFAULT_MODULES", constants.EXCLUDED_BY_DEFAULT_MODULES),
        const_tuple("ALERT_IMPACT_KEYS", constants.ALERT_IMPACT_KEYS),
        "export type AlertImpactKey = (typeof ALERT_IMPACT_KEYS)[number];",
    ]
    header = (
        "/* eslint-disable */\n"
        "// AUTO-GENERATED by contracts/gen.py from contracts/trialpilot_contracts — DO NOT EDIT.\n"
        "// Regenerate: `python contracts/gen.py` (CI fails if this file is stale).\n"
        "//\n"
        "// Shapes are JSON as *emitted by the API*: every field is present (fields with a default\n"
        "// in pydantic are always serialised). When *sending* JSON you may omit defaulted fields;\n"
        "// see contracts/schema/*.json for the exact input schema. Datetimes are ISO 8601 UTC strings.\n"
    )
    sections = [
        header,
        "// ---------- Named literal types (from models.py) ----------\n\n" + "\n\n".join(named),
        "// ---------- Field literal types ----------\n\n" + "\n\n".join(generated),
        "// ---------- Constants (constants.py, MASTER §6) ----------\n\n" + "\n\n".join(consts),
        "// ---------- Models (MASTER §5) ----------\n\n" + "\n\n".join(interfaces),
    ]
    return "\n".join(s.rstrip("\n") + "\n" for s in sections)


# ---------------------------------------------------------------- main
def render() -> dict[Path, str]:
    found, aliases = discover()
    files = json_schemas(found)
    files[TS_FILE] = typescript(found, aliases)
    return files


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--check", action="store_true", help="fail if generated files are stale")
    args = ap.parse_args(argv)
    files = render()
    expected = set(files)
    stray = {p for p in SCHEMA_DIR.glob("*.json")} - expected
    stale = [p for p, text in files.items() if not p.exists() or p.read_bytes() != text.encode()]
    if args.check:
        for p in sorted(stale):
            print(f"stale: {p.relative_to(ROOT).as_posix()}", file=sys.stderr)
        for p in sorted(stray):
            print(f"stray: {p.relative_to(ROOT).as_posix()}", file=sys.stderr)
        if stale or stray:
            print("Run `python contracts/gen.py` and commit the result.", file=sys.stderr)
            return 1
        print(f"OK: {len(files)} generated files are up to date")
        return 0
    SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    TS_FILE.parent.mkdir(parents=True, exist_ok=True)
    for p in stray:
        p.unlink()
    for p, text in files.items():
        p.write_bytes(text.encode())
    print(f"wrote {len(files)} files ({len(stale)} changed, {len(stray)} removed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
