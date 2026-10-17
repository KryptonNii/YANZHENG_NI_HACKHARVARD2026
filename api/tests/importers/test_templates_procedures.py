"""Visit templates (all assumptions) and the procedure vocabulary."""

from __future__ import annotations

import pytest
import yaml

from trialpilot_api.importers.procedures import OTHER_PREFIX, clean_label, default_vocabulary
from trialpilot_api.importers.templates import _parse_timeframe_weeks, default_templates

from .conftest import REAL_FIXTURES

pytestmark = pytest.mark.req("URS-001")


@pytest.mark.parametrize(("text", "weeks"), [
    ("Baseline (Day 1) to Week 52", 52.0),
    ("Baseline (Day 1) to Weeks 2, 4, 8, 12, 24, 36, 44 and 52", 52.0),
    ("Through Week 156", 156.0),
    ("12 months", 52.2),
    ("Day 1 to Day 28", 4.0),
    ("Baseline, Week 48", 48.0),
    ("Weeks 6, 12 and 24", 24.0),
])
def test_timeframe_parsing(text: str, weeks: float) -> None:
    assert _parse_timeframe_weeks(text) == pytest.approx(weeks, abs=0.05)


def test_timeframe_without_number() -> None:
    assert _parse_timeframe_weeks("End of study") is None


def test_every_template_is_a_labelled_assumption() -> None:
    doc = yaml.safe_load((REAL_FIXTURES / "visit_templates.yaml").read_text(encoding="utf-8"))
    for t in doc["templates"]:
        assert t["assumption"] is True and t["rationale"].strip()
        for k, v in t.items():
            if isinstance(v, dict) and "mid" in v:
                assert v["low"] <= v["mid"] <= v["high"], (t["id"], k)


@pytest.mark.parametrize("phase", ["Phase 1", "Phase 2", "Phase 3", "Phase 2/3", None, "Not Applicable"])
def test_template_schedules_are_valid(phase: str | None) -> None:
    lib = default_templates()
    s = lib.build(phase, None)
    weeks = [v.week for v in s.visits]
    assert weeks == sorted(weeks) and len(set(weeks)) == len(weeks)
    assert s.visits[0].label == "Screening" and s.visits[-1].label.startswith("Follow-up")
    assert s.treatment_weeks_basis.startswith("assumption")
    vocab = default_vocabulary()
    assert all(p.code in vocab.by_code for v in s.visits for p in v.procedures)


def test_template_uses_registry_length_when_given() -> None:
    s = default_templates().build("Phase 3", 24.0, "primary outcome time frame 'Week 24'")
    assert s.visits[-2].week == 24.0 and s.treatment_weeks_basis.startswith("registry")


@pytest.mark.parametrize(("label", "code"), [
    ("Informed consent", "informed_consent"),
    ("Dense PK substudy ICF2", "informed_consent"),
    ("Chest X-ray e", "x_ray"),
    ("Electrocardiogram (12 lead)", "ecg"),
    ("Hematology, biochemistry, urinalysis including cotinine", "blood_draw"),
    ("Urine pregnancy test", "urine_sample"),
    ("Pregnancy (β-HCG blood) test", "blood_draw"),
    ("Serum PK samples for dupilumab concentration", "pk_sample"),
    ("Anti-dupilumab antibody", "ada_sample"),
    ("FeNO post-bronchodilator", "feno"),
    ("At-home spirometry (FEV1)", "home_spirometry"),
    ("Spirometry (pre-BD) n,o", "spirometry"),
    ("SD-OCT10", "retinal_imaging"),
    ("IOP8", "ophthalmic_exam"),
    ("BCVA (ETDRS) and Refraction", "visual_acuity"),
    ("NEI-VFQ-25", "questionnaire"),
    ("Study Drug (active or sham)", "imp_administration"),
    ("Study drug dispensing", "drug_dispensing"),
    ("Vital signs12", "vital_signs"),
])
@pytest.mark.req("URS-002")
def test_label_mapping(label: str, code: str) -> None:
    proc, mapped = default_vocabulary().to_procedure(label)
    assert mapped and proc.code == code


@pytest.mark.req("URS-002")
def test_unknown_label_kept_as_other() -> None:
    proc, mapped = default_vocabulary().to_procedure("Smoking status")
    assert not mapped and proc.code == OTHER_PREFIX + "smoking_status" and proc.label == "Smoking status"


@pytest.mark.req("URS-002")
def test_code_hint_only_if_known() -> None:
    v = default_vocabulary()
    assert v.to_procedure("Weird thing", "ecg")[0].code == "ecg"
    assert v.to_procedure("Weird thing", "made_up_code")[0].code == "other:weird_thing"


@pytest.mark.req("URS-002")
def test_clean_label() -> None:
    assert clean_label("Chest X-ray e") == "Chest X-ray"
    assert clean_label("Vital signs") == "Vital signs"  # no letter eaten
    assert clean_label("Eotaxin-3") == "Eotaxin-3"
    assert clean_label("NEI VFQ-25") == "NEI VFQ-25"
    assert clean_label("Immunogenicity sample16, 17") == "Immunogenicity sample"


def test_vocabulary_shares_codes_with_parameter_library() -> None:
    """Codes A10 lists for time.site.procedure.<code> (data/params/NEEDED.md) exist in the vocabulary."""
    v = default_vocabulary()
    for code in ["blood_draw", "pk_sample", "ecg", "vital_signs", "physical_exam", "questionnaire",
                 "informed_consent", "drug_dispensing", "urine_sample", "mri", "ct_scan", "x_ray",
                 "mammogram", "echocardiogram", "biopsy"]:
        assert code in v.by_code and v.by_code[code].in_param_library
