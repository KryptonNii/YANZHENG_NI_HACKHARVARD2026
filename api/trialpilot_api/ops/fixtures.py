"""The 40-site demo trial used by the command center (a FIXTURE, not a real trial).

38 active sites + 2 backup sites (S39, S40; expected_enrollment = 0, i.e. not in the enrollment plan)
in 13 countries. City coordinates are approximate centroids. Procedure minutes and expected enrollment
are assumptions (listed in `missing_fields`). Regenerate the JSON with
`python -m trialpilot_api.ops.fixtures` (it is also checked by the tests).
"""

from __future__ import annotations

import json
from pathlib import Path

from ._contracts import TrialDesign
from .params import ops_data_dir

DEMO_TRIAL_ID = "demo-40"
DESIGN_FILE = "demo_trial_40_sites.json"

# id, city, ISO2, lat, lon, expected_enrollment (assumption; 0 = backup site)
_SITES: list[tuple[str, str, str, float, float, float]] = [
    ("S01", "Boston", "US", 42.36, -71.06, 18),
    ("S02", "New York", "US", 40.71, -74.01, 20),
    ("S03", "Philadelphia", "US", 39.95, -75.17, 16),
    ("S04", "Chicago", "US", 41.88, -87.63, 18),
    ("S05", "Houston", "US", 29.76, -95.37, 16),
    ("S06", "Denver", "US", 39.74, -104.99, 14),
    ("S07", "Seattle", "US", 47.61, -122.33, 14),
    ("S08", "Atlanta", "US", 33.75, -84.39, 16),
    ("S09", "Toronto", "CA", 43.65, -79.38, 16),
    ("S10", "Montreal", "CA", 45.50, -73.57, 14),
    ("S11", "London", "GB", 51.51, -0.13, 18),
    ("S12", "Manchester", "GB", 53.48, -2.24, 15),
    ("S13", "Glasgow", "GB", 55.86, -4.25, 13),
    ("S14", "Paris", "FR", 48.86, 2.35, 18),
    ("S15", "Lyon", "FR", 45.76, 4.84, 15),
    ("S16", "Marseille", "FR", 43.30, 5.37, 14),
    ("S17", "Berlin", "DE", 52.52, 13.40, 17),
    ("S18", "Munich", "DE", 48.14, 11.58, 16),
    ("S19", "Hamburg", "DE", 53.55, 9.99, 15),
    ("S20", "Cologne", "DE", 50.94, 6.96, 15),
    ("S21", "Madrid", "ES", 40.42, -3.70, 16),
    ("S22", "Madrid", "ES", 40.45, -3.69, 15),
    ("S23", "Barcelona", "ES", 41.39, 2.17, 16),
    ("S24", "Barcelona", "ES", 41.40, 2.15, 14),
    ("S25", "Milan", "IT", 45.46, 9.19, 16),
    ("S26", "Rome", "IT", 41.90, 12.50, 16),
    ("S27", "Amsterdam", "NL", 52.37, 4.90, 16),
    ("S28", "Brussels", "BE", 50.85, 4.35, 15),
    ("S29", "Warsaw", "PL", 52.23, 21.01, 17),
    ("S30", "Krakow", "PL", 50.06, 19.94, 15),
    ("S31", "São Paulo", "BR", -23.55, -46.63, 18),
    ("S32", "Rio de Janeiro", "BR", -22.91, -43.17, 15),
    ("S33", "Porto Alegre", "BR", -30.03, -51.23, 14),
    ("S34", "Sydney", "AU", -33.87, 151.21, 16),
    ("S35", "Melbourne", "AU", -37.81, 144.96, 15),
    ("S36", "Tokyo", "JP", 35.68, 139.69, 15),
    ("S37", "Osaka", "JP", 34.69, 135.50, 14),
    ("S38", "Seoul", "KR", 37.57, 126.98, 15),
    ("S39", "Curitiba", "BR", -25.43, -49.27, 0),
    ("S40", "Belo Horizonte", "BR", -19.92, -43.94, 0),
]

# code, label, site_minutes (assumption), ships_sample, sample_temp
_PROC = {
    "consent": ("Informed consent", 45, False, None),
    "physical_exam": ("Physical examination", 20, False, None),
    "vitals": ("Vital signs", 10, False, None),
    "blood_draw": ("Safety labs (blood draw)", 15, True, "refrigerated"),
    "pk_sample": ("PK / biomarker sample", 15, True, "frozen_-80"),
    "ecg": ("12-lead ECG", 15, False, None),
    "questionnaire": ("Patient-reported outcome questionnaires", 20, False, None),
    "ip_dispense": ("IMP dispensing and administration", 30, False, None),
}

# number, label, week, procedures, can_be_remote
_VISITS = [
    (1, "Screening", -2, ["consent", "physical_exam", "vitals", "blood_draw", "ecg"], False),
    (2, "Baseline / randomisation", 0,
     ["physical_exam", "vitals", "blood_draw", "pk_sample", "questionnaire", "ip_dispense"], False),
    (3, "Week 2", 2, ["vitals", "questionnaire", "ip_dispense"], False),
    (4, "Week 4", 4, ["vitals", "blood_draw", "pk_sample", "ip_dispense"], False),
    (5, "Week 8", 8, ["vitals", "questionnaire", "ip_dispense"], False),
    (6, "Week 12", 12, ["vitals", "blood_draw", "pk_sample", "ecg", "ip_dispense"], False),
    (7, "Week 16", 16, ["vitals", "ip_dispense"], False),
    (8, "Week 20", 20, ["vitals", "questionnaire", "ip_dispense"], False),
    (9, "Week 24", 24,
     ["physical_exam", "vitals", "blood_draw", "pk_sample", "questionnaire", "ip_dispense"], False),
    (10, "Week 32", 32, ["vitals", "ip_dispense"], False),
    (11, "Week 40", 40, ["vitals", "blood_draw", "ip_dispense"], False),
    (12, "Week 48", 48, ["vitals", "questionnaire", "ip_dispense"], False),
    (13, "Week 52 / end of treatment", 52,
     ["physical_exam", "vitals", "blood_draw", "pk_sample", "ecg", "questionnaire"], False),
    (14, "Week 60 follow-up", 60, ["vitals", "questionnaire"], True),
]


def build_demo_design() -> TrialDesign:
    sites = [
        {
            "id": sid,
            "name": f"Site {sid[1:]} — {city}" + (" (backup)" if exp == 0 else ""),
            "city": city,
            "country": cc,
            "lat": lat,
            "lon": lon,
            "expected_enrollment": exp,
        }
        for sid, city, cc, lat, lon, exp in _SITES
    ]
    visits = [
        {
            "number": n,
            "label": label,
            "week": week,
            "can_be_remote": remote,
            "procedures": [
                {
                    "code": c,
                    "label": _PROC[c][0],
                    "site_minutes": _PROC[c][1],
                    "ships_sample": _PROC[c][2],
                    "sample_temp": _PROC[c][3],
                }
                for c in procs
            ],
        }
        for n, label, week, procs, remote in _VISITS
    ]
    return TrialDesign.model_validate(
        {
            "id": DEMO_TRIAL_ID,
            "source": "fixture",
            "registry_id": None,
            "title": "TrialPilot ops demo — 40-site Phase 3 biologic trial (SIMULATED, not a real study)",
            "phase": "PHASE3",
            "conditions": ["Atopic dermatitis (simulated demo trial)"],
            "enrollment_target": 900,
            "duration_months": 38,
            "sites": sites,
            "visits": visits,
            "drug_type": "biologic",
            "missing_fields": [
                "sites[].expected_enrollment",
                "sites[].lat/lon (approximate city centroids)",
                "visits[].procedures[].site_minutes",
            ],
        }
    )


def load_demo_design() -> TrialDesign:
    path = ops_data_dir() / DESIGN_FILE
    if path.is_file():
        return TrialDesign.model_validate_json(path.read_text(encoding="utf-8"))
    return build_demo_design()


def write_fixture(path: Path | None = None) -> Path:
    path = path or ops_data_dir() / DESIGN_FILE
    data = build_demo_design().model_dump(mode="json")
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    print(write_fixture())
