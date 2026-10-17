import subprocess
import sys
from pathlib import Path

import trialpilot_contracts
from trialpilot_contracts import CARBON_MODULES, models

REPO = Path(__file__).resolve().parents[2]


def test_every_model_is_reexported() -> None:
    model_names = [
        n for n, o in vars(models).items()
        if isinstance(o, type) and issubclass(o, models.BaseModel) and o.__module__ == models.__name__
    ]
    assert len(model_names) == 17
    assert set(model_names) <= set(trialpilot_contracts.__all__)


def test_carbon_modules_match_master_section_6() -> None:
    assert len(CARBON_MODULES) == 11 and CARBON_MODULES[-1] == "drug_supply"


def test_generated_files_are_up_to_date() -> None:
    proc = subprocess.run(
        [sys.executable, str(REPO / "contracts" / "gen.py"), "--check"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
