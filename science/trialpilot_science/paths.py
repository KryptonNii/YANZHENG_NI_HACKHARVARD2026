"""Repository paths used by the science check (the only module that knows the folder layout)."""

from __future__ import annotations

from pathlib import Path

SCIENCE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SCIENCE_DIR.parent
DATA_DIR = SCIENCE_DIR / "data"
OUT_DIR = SCIENCE_DIR / "out"
PARAMS_DIR = REPO_ROOT / "data" / "params"
DEMO_TRIALS_DIR = REPO_ROOT / "data" / "fixtures" / "trials"

LEDGERS = {
    "casps": DATA_DIR / "casps_ledger.yaml",
    "primetime": DATA_DIR / "primetime_ledger.yaml",
}
DESIGNS = {
    "casps": DATA_DIR / "casps_design.yaml",
    "primetime": DATA_DIR / "primetime_design.yaml",
}
FACTOR_MAP = DATA_DIR / "factor_map.yaml"
PAPER_FACTOR_OVERRIDES = DATA_DIR / "paper_factor_overrides.yaml"
RESULTS_JSON = OUT_DIR / "results.json"
RESULTS_SCHEMA = OUT_DIR / "results.schema.json"
