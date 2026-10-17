"""Regenerate THIRD_PARTY.md from the real manifests and the *installed* package metadata.

    uv run --project contracts python .github/scripts/third_party.py          # write THIRD_PARTY.md
    uv run --project contracts python .github/scripts/third_party.py --check  # exit 1 on unknown/blocked licence

Licences are read from each package's own metadata (Python: `*.dist-info/METADATA` in that package's
.venv; web: `web/node_modules/<name>/package.json`), never typed from memory. A dependency that is not
installed yet is listed as "not installed — run `make install`". Data sources and documents are listed
from DATA below; their licences are what the owning agent recorded, with the URL to check.
"""

from __future__ import annotations

import argparse
import email.parser
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "THIRD_PARTY.md"
PY_PACKAGES = ["contracts", "engine", "api", "validation", "science"]
FIRST_PARTY = re.compile(r"^trialpilot[-_]")

# Licences compatible with shipping an MIT repo (permissive or weak-copyleft used unmodified as a library).
ALLOWED = re.compile(
    r"\b(MIT|BSD|ISC|Apache|PSF|Python Software Foundation|0BSD|Unlicense|CC0|MPL|OFL|Zlib|BlueOak|HPND)",
    re.IGNORECASE,
)
BLOCKED = re.compile(r"\b(AGPL|GPL(?!.*(with|exception))|SSPL|BUSL|Commons Clause|CC BY-NC|proprietary)", re.IGNORECASE)

USED_FOR: dict[str, str] = {
    "pydantic": "data models / validation (contracts)",
    "pydantic-settings": "settings from env / .env",
    "pyyaml": "parameter library YAML",
    "numpy": "Monte Carlo sampling",
    "fastapi": "HTTP API",
    "uvicorn": "ASGI server",
    "sqlmodel": "SQLite ORM",
    "sqlalchemy": "SQLite ORM",
    "sse-starlette": "server-sent events (command center feed)",
    "python-multipart": "PDF upload",
    "httpx": "HTTP client (ClinicalTrials.gov) / test client",
    "argon2-cffi": "PIN hashing for e-signatures",
    "reportlab": "PDF generation",
    "pdfplumber": "protocol PDF text/table extraction",
    "anthropic": "protocol extraction LLM client",
    "mcp": "read-only MCP server (official Python SDK)",
    "pytest": "tests",
    "jsonschema": "contract tests",
    "ruff": "lint",
    "mypy": "type checking",
    "types-pyyaml": "type stubs",
    "react": "UI",
    "react-dom": "UI",
    "react-router-dom": "routing",
    "recharts": "charts",
    "tailwindcss": "styling",
    "vite": "build / dev server",
    "@vitejs/plugin-react": "build",
    "typescript": "types",
    "vitest": "unit tests",
    "@playwright/test": "end-to-end tests",
    "@testing-library/react": "component tests",
    "@testing-library/jest-dom": "component tests",
    "@testing-library/user-event": "component tests",
    "jsdom": "test DOM",
    "d3-geo": "site map projection",
    "topojson-client": "site map geometry",
    "world-atlas": "site map country shapes",
    "@fontsource-variable/inter": "UI font (self-hosted)",
    "autoprefixer": "CSS build",
    "postcss": "CSS build",
    "cross-env": "scripts",
}

# Data and documents: (name, licence as recorded by the owner, used for, owner, where to check).
DATA: list[tuple[str, str, str, str, str]] = [
    ("ClinicalTrials.gov API v2 (trial registry data)",
     "No charge; redistribution terms below (confirmed in handoffs/A4.md, 2026-10-16)",
     "trial import (cached fixtures)",
     "A4", "https://clinicaltrials.gov/about-site/terms-conditions"),
    ("GeoNames", "CC BY 4.0 (confirmed in handoffs/A4.md, 2026-10-16)",
     "offline geocoding of trial sites", "A4",
     "https://www.geonames.org/about.html"),
    ("UK Government GHG Conversion Factors (DESNZ 2022/2025/2026)",
     "Open Government Licence v3.0 (recorded in docs/sources.md §11, 2026-10-16)",
     "emission factors; cell-cited values, workbooks not committed", "A10",
     "https://www.gov.uk/government/collections/government-conversion-factors-for-company-reporting"),
    ("DfT National Travel Survey",
     "Open Government Licence v3.0 (recorded in docs/sources.md §11, 2026-10-16)",
     "patient-travel distance and mode shares", "A10",
     "https://www.gov.uk/government/statistical-data-sets/nts04-purpose-of-trips"),
    ("Ember yearly electricity data",
     "CC BY 4.0 (recorded in docs/sources.md §11, 2026-10-16)",
     "grid emission intensity outside the UK", "A10",
     "https://ember-energy.org/data/yearly-electricity-data/"),
    ("Australian National Greenhouse Accounts Factors 2026",
     "CC BY 4.0 (recorded in docs/sources.md §11, 2026-10-16)",
     "Australian grid factors", "A10",
     "https://www.dcceew.gov.au/climate-change/publications/national-greenhouse-accounts-factors-2026"),
    ("Griffiths, Fox, Williamson et al., BMJ Open 2024 (Low Carbon Clinical Trials Group method)",
     "CC BY 4.0 (recorded in docs/sources.md §11, 2026-10-16)",
     "carbon module framework; CASPS/PRIMETIME published values (cited, not copied)",
     "A10", "https://bmjopen.bmj.com/content/14/1/e075755"),
    ("ISPE GAMP 5 Guide", "copyrighted — linked only, never committed", "validation approach reference",
     "A7", "https://ispe.org/publications/guidance-documents/gamp-5-guide-2nd-edition"),
]


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def req_name(req: str) -> str:
    m = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", req)
    return norm(m.group(1)) if m else norm(req)


def site_packages(pkg: str) -> list[Path]:
    venv = ROOT / pkg / ".venv"
    return [*venv.glob("Lib/site-packages"), *venv.glob("lib/python3*/site-packages")]


def py_licence(pkg: str, dist: str) -> tuple[str, str]:
    for sp in site_packages(pkg):
        for info in sp.glob("*.dist-info"):
            if norm(info.name.removesuffix(".dist-info").rsplit("-", 1)[0]) != dist:
                continue
            meta = email.parser.Parser().parsestr((info / "METADATA").read_text(encoding="utf-8"))
            lic = meta.get("License-Expression") or ""
            if not lic:
                raw = (meta.get("License") or "").strip()
                if raw and "\n" not in raw and len(raw) < 60:
                    lic = raw
            if not lic:
                classifiers = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or []
                               if c.startswith("License ::")]
                lic = ", ".join(classifiers)
            return (lic or "see package metadata", f"{info.name}")
    return ("not installed — run `make install`", "")


def python_rows() -> dict[str, dict[str, object]]:
    rows: dict[str, dict[str, object]] = {}
    for pkg in PY_PACKAGES:
        manifest = ROOT / pkg / "pyproject.toml"
        if not manifest.exists():
            continue
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
        reqs = list(data.get("project", {}).get("dependencies", []))
        for group in data.get("dependency-groups", {}).values():
            reqs += [r for r in group if isinstance(r, str)]
        for req in reqs:
            name = req_name(req)
            if FIRST_PARTY.match(name):
                continue
            row = rows.setdefault(name, {"by": set(), "lic": None, "src": ""})
            row["by"].add(pkg)  # type: ignore[union-attr]
            if not row["lic"] or str(row["lic"]).startswith("not installed"):
                row["lic"], row["src"] = py_licence(pkg, name)
    return rows


def web_rows() -> dict[str, dict[str, object]]:
    manifest = ROOT / "web" / "package.json"
    if not manifest.exists():
        return {}
    pkg = json.loads(manifest.read_text(encoding="utf-8"))
    rows: dict[str, dict[str, object]] = {}
    for section in ("dependencies", "devDependencies"):
        for name in pkg.get(section, {}):
            installed = ROOT / "web" / "node_modules" / name / "package.json"
            if installed.exists():
                meta = json.loads(installed.read_text(encoding="utf-8"))
                lic = meta.get("license") or meta.get("licenses") or "see package"
                if isinstance(lic, dict):
                    lic = lic.get("type", "see package")
                elif isinstance(lic, list):
                    lic = " OR ".join(x.get("type", "?") if isinstance(x, dict) else str(x) for x in lic)
                src = f"node_modules/{name}@{meta.get('version', '?')}"
            else:
                lic, src = "not installed — run `make install`", ""
            rows[name] = {"by": {"web" + (" (dev)" if section == "devDependencies" else "")},
                          "lic": lic, "src": src}
    return rows


def status(lic: str) -> str:
    if lic.startswith("not installed"):
        return "pending"
    if BLOCKED.search(lic):
        return "**BLOCKED**"
    return "ok" if ALLOWED.search(lic) else "**review**"


def render() -> tuple[str, list[str]]:
    problems: list[str] = []
    lines = [
        "# Third-party components",
        "",
        "TrialPilot is MIT-licensed (see [LICENSE](LICENSE)). This file is generated by",
        "`.github/scripts/third_party.py` from the manifests and the licence metadata of the installed",
        "packages — regenerate with `make licenses` after adding a dependency.",
        "",
        "## Software dependencies (direct)",
        "",
        "| Name | Licence | Used by | Used for | Status | Read from |",
        "|---|---|---|---|---|---|",
    ]
    rows = {**python_rows(), **web_rows()}
    for name in sorted(rows, key=str.lower):
        r = rows[name]
        lic = str(r["lic"])
        st = status(lic)
        if st in ("**BLOCKED**", "**review**"):
            problems.append(f"{name}: {lic} ({st.strip('*')})")
        by = ", ".join(sorted(r["by"]))  # type: ignore[arg-type]
        use = USED_FOR.get(name, "type definitions" if name.startswith("@types/") else "")
        lines.append(f"| {name} | {lic} | {by} | {use} | {st} | {r['src']} |")
    lines += [
        "",
        "## Data and documents",
        "",
        "Real data is labelled as real with its source in the app; simulated data is labelled simulated.",
        "Copyrighted documents (e.g. GAMP 5) are linked, never committed.",
        "",
        "| Source | Licence / terms | Used for | Owner | Check at |",
        "|---|---|---|---|---|",
    ]
    lines += [f"| {n} | {lic} | {use} | {own} | {url} |" for n, lic, use, own, url in DATA]
    lines += [
        "",
        "ClinicalTrials.gov: [A4's source review](handoffs/A4.md) records the",
        "[terms](https://clinicaltrials.gov/about-site/terms-conditions) last updated January 31, 2023.",
        "Redistribution should credit ClinicalTrials.gov, keep the data current, include the date",
        "ClinicalTrials.gov processed it, and describe modifications. Some content may carry",
        "third-party copyright. Import attribution records the source, processing timestamp, fetch",
        "time and modifications; sponsor protocol PDFs are linked rather than committed.",
        "",
        "Contains data from [GeoNames](https://www.geonames.org/about.html), licensed under",
        "[Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/).",
        "Modifications (name normalization, alternate-name filtering, coordinate rounding and",
        "column selection) are listed in the [offline index notes](data/fixtures/ctgov/geonames/README.md).",
        "",
        "UK Government GHG Conversion Factors and the DfT National Travel Survey: [A10's source index](docs/sources.md)",
        "§11 records the gov.uk footer, \"All content is available under the Open Government Licence v3.0,",
        "except where otherwise stated.\" Factor values are copied with workbook cell references. The",
        "workbooks themselves are not committed.",
        "",
        "Griffiths et al., BMJ Open 2024, Ember yearly electricity data, and the Australian National",
        "Greenhouse Accounts Factors 2026 are CC BY 4.0 in that same index. Published numbers are transcribed",
        "and cited. The paper PDFs are not committed.",
    ]
    return "\n".join(lines) + "\n", problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    text, problems = render()
    if args.check:
        for p in problems:
            print(f"licence: {p}", file=sys.stderr)
        return 1 if problems else 0
    OUT.write_bytes(text.encode("utf-8"))
    print(f"wrote {OUT.relative_to(ROOT)} ({len(problems)} to review)")
    for p in problems:
        print(f"  review: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
