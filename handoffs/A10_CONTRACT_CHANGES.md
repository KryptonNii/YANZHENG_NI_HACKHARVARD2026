# A10 — contract change proposals (for A1)

The model is unchanged. This file only records the request.

## 1. `Visit.patient_share` (default 1.0)

**Problem.** `Visit` applies every visit to every enrolled patient. PRIMETIME's five extra mammogram visits
apply to 1,623 of 1,962 patients (the no-radiotherapy cohort; BMJ Open 2024 appendix D). The rebuilt design
therefore has `enrollment_target` 1962 and 5 visits, and the engine counts 1962 × 5 = 9,810 patient-visits.
The paper counts 1,623 × 5 = 8,115 (+20.9%). `Activity.visits_in` (`engine/trialpilot_engine/levers.py`)
counts each scheduled visit once per enrolled patient, so travel, procedures, samples and dispensing all
scale with the full cohort.

**Proposal.** Add an optional share on `Visit`, default `1.0`, so every current design stays valid.

```python
class Visit(BaseModel):
    number: int
    label: str
    week: float
    procedures: list[Procedure] = []
    can_be_remote: bool = False      # decided by humans, default False
    patient_share: float = Field(default=1.0, ge=0, le=1)
```

`patient_share` is the fraction of `enrollment_target` who attend that visit. Activity for the visit
(patient travel, procedure counts, samples, dispensing, site-staff minutes) is
`enrollment_target * patient_share`, with the default `1.0` meaning every enrolled patient attends.
PRIMETIME would set `patient_share` to 1623/1962 on each of the five mammogram visits.

No parameter values change. The published engine gaps (CASPS about +5%, PRIMETIME about +7%) stay as they are.
