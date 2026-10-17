"""Parameter resolution with provenance.

`ParamStore` hands out per-draw parameter values and records, for the formula being evaluated, which
parameter ids it used, which fallbacks it took (country → `.global`, code → `.default`) and which ids
were missing. A missing parameter yields NaN draws: the term becomes *unknown*, is excluded from totals
and is reported in warnings — it is never counted as zero.

`Term` is one formula's result (one metric, one module); it turns itself into a `ProvenanceItem`.
Formula ids are prefixed by metric family: `cost.*` (usd), `carbon.*` (kg CO2e),
`workload.*` (site staff hours), `burden.*` (patient hours).
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from ._contracts import Parameter, ProvenanceItem
from .uncertainty import FloatArray, Unit, parameter_draws, to_range

Metric = Literal["cost_usd", "co2e_kg", "site_staff_hours", "patient_travel_hours"]
Inputs = dict[str, float | str]

METRIC_UNIT: dict[Metric, Unit] = {
    "cost_usd": "usd",
    "co2e_kg": "kg_co2e",
    "site_staff_hours": "hours",
    "patient_travel_hours": "hours",
}

_NON_SLUG = re.compile(r"[^a-z0-9_]+")


def slug(text: str) -> str:
    """Parameter-id-safe slug: 'Blood draw' → 'blood_draw', 'other:Holter' → 'other_holter'."""
    return _NON_SLUG.sub("_", text.strip().lower()).strip("_") or "unknown"


@dataclass
class Trace:
    """What one formula touched, in first-use order."""

    parameter_ids: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    @staticmethod
    def _add(bucket: list[str], item: str) -> None:
        if item not in bucket:
            bucket.append(item)


class ParamStore:
    """Per-draw parameter values for one computation (seeded; cached; read-only arrays)."""

    def __init__(self, params: Mapping[str, Parameter], seed: int, n: int) -> None:
        self._params = params
        self.seed = seed
        self.n = n
        self._draws: dict[str, FloatArray] = {}
        self._trace: Trace | None = None
        self.missing: list[str] = []

    def has(self, pid: str) -> bool:
        return pid in self._params

    def parameter(self, pid: str) -> Parameter | None:
        return self._params.get(pid)

    @contextmanager
    def track(self) -> Iterator[Trace]:
        """Record every parameter used inside the `with` block into a fresh Trace."""
        previous, self._trace = self._trace, Trace()
        try:
            yield self._trace
        finally:
            self._trace = previous

    def note(self, text: str) -> None:
        if self._trace is not None:
            Trace._add(self._trace.notes, text)

    def get(self, pid: str) -> FloatArray:
        """Draws of parameter `pid`; NaN draws (unknown) if the library does not have it."""
        if self._trace is not None:
            Trace._add(self._trace.parameter_ids, pid)
        if pid not in self._params:
            Trace._add(self.missing, pid)
            if self._trace is not None:
                Trace._add(self._trace.missing, pid)
        cached = self._draws.get(pid)
        if cached is not None:
            return cached
        p = self._params.get(pid)
        draws = np.full(self.n, np.nan) if p is None else parameter_draws(p, self.seed, self.n)
        draws.flags.writeable = False
        self._draws[pid] = draws
        return draws

    def regional(self, base: str, country: str) -> FloatArray:
        """`<base>.<country>` if the library has it, else `<base>.global` (noted in provenance)."""
        specific = f"{base}.{country}"
        if country != "global" and specific in self._params:
            return self.get(specific)
        general = f"{base}.global"
        if country != "global":
            self.note(f"No country-specific `{specific}` in the library; used `{general}`.")
        return self.get(general)

    def with_default(self, base: str, key: str) -> FloatArray:
        """`<base>.<key>` if the library has it, else `<base>.default` (noted in provenance)."""
        specific = f"{base}.{key}"
        if specific in self._params:
            return self.get(specific)
        fallback = f"{base}.default"
        self.note(f"No `{specific}` in the library; used `{fallback}`.")
        return self.get(fallback)

    def used_draws(self) -> dict[str, FloatArray]:
        """Draws of every library parameter used so far (for the variance-drivers panel)."""
        return {pid: d for pid, d in self._draws.items() if pid in self._params}


@dataclass(frozen=True)
class Term:
    """One formula's per-draw result for one metric in one §6 module."""

    module: str
    metric: Metric
    formula_id: str
    description: str
    values: FloatArray
    inputs: Inputs
    trace: Trace
    assumptions: tuple[str, ...] = ()

    @property
    def known(self) -> bool:
        return bool(np.all(np.isfinite(self.values)))

    def provenance(self, extra_assumptions: tuple[str, ...] = ()) -> ProvenanceItem:
        inputs: Inputs = dict(self.inputs)
        if self.known:
            r = to_range(self.values, METRIC_UNIT[self.metric])
            inputs.update(result_p10=r.p10, result_p50=r.p50, result_p90=r.p90, result_unit=r.unit)
        else:
            inputs["result"] = "unknown (missing or invalid input) - excluded from totals"
        missing_text = (
            "is not in the library; not needed for this scenario's values"
            if self.known
            else "is MISSING from the library; this term is unknown and excluded from totals "
            "(not counted as zero)"
        )
        return ProvenanceItem(
            formula_id=self.formula_id,
            description=self.description,
            inputs=inputs,
            parameter_ids=list(self.trace.parameter_ids),
            assumptions=list(dict.fromkeys([
                *self.assumptions,
                *self.trace.notes,
                *(f"Parameter `{m}` {missing_text}." for m in self.trace.missing),
                *extra_assumptions,
            ])),
        )


# Every parameter id the engine can ask for. `<cc>` = lowercase ISO 3166 alpha-2 or `global`
# (always needed as fallback); `<code>` = procedure code or `default`; `<temp>` = ambient |
# refrigerated | frozen; `<drug_type>` = biologic | small_molecule | default; `<strategy>` =
# upfront | on_demand. Values live in data/params/*.yaml (A10); docs/model.md explains each use.
PARAMETER_CATALOG: dict[str, tuple[str, str]] = {
    # patient_assessments: patient travel and visit time
    "dist.patient.roundtrip_km.<cc>": ("km/visit", "patient home to site round trip per on-site visit"),
    "rate.patient.mode_share.car.<cc>": ("share", "share of patient km travelled by car"),
    "rate.patient.mode_share.rail.<cc>": ("share", "share of the non-car km by rail (rest by bus)"),
    "time.patient.travel_speed_kmh.<cc>": ("km/hour", "door-to-door average patient travel speed"),
    "time.patient.visit_at_site": ("hours/visit", "patient time at site per visit"),
    "time.patient.home_visit": ("hours/visit", "patient time per home-nursing visit"),
    "time.patient.remote_visit": ("hours/visit", "patient time per telehealth visit"),
    "ef.travel.car.average_km": ("kg_co2e/km", "average car per vehicle-km"),
    "ef.travel.bus.passenger_km": ("kg_co2e/passenger_km", "average local bus"),
    "ef.travel.rail.passenger_km": ("kg_co2e/passenger_km", "national rail"),
    "cost.patient.reimbursement_visit": ("usd/visit", "patient travel reimbursement per on-site visit"),
    "cost.home_nurse.visit": ("usd/visit", "one home-nursing visit"),
    "dist.home_nurse.roundtrip_km": ("km/visit", "home nurse round trip by car per home visit"),
    "cost.telehealth.visit": ("usd/visit", "one telehealth visit"),
    # site staff time
    "time.site.visit_admin": ("minutes/visit", "scheduling + documentation per patient visit"),
    "time.site.procedure.<code>": ("minutes/procedure", "site staff minutes per procedure"),
    "rate.site.minutes_factor.home_visit": (
        "share",
        "share of a visit's procedure minutes still borne by site staff when done at home",
    ),
    "rate.site.minutes_factor.remote_visit": (
        "share",
        "share of a visit's procedure minutes still borne by site staff when done by telehealth",
    ),
    "time.site.monitoring_visit_support": ("hours/visit", "site staff hours per on-site monitoring visit"),
    "time.site.remote_monitoring_review": ("hours/visit", "site staff hours per remote monitoring visit"),
    "rate.queries.per_patient": ("queries/patient", "data queries raised per patient"),
    "time.site.query_resolution": ("minutes/query", "site time to resolve one query"),
    "cost.site_staff.hour": ("usd/hour", "loaded cost of one site research staff hour"),
    # meetings_travel: monitoring + investigator meeting
    "rate.monitoring.onsite_visits_per_site_month": (
        "visits/site/month",
        "monitoring visit frequency (all on-site at remote share 0)",
    ),
    "dist.monitoring.roundtrip_km.<cc>": ("km/trip", "CRA base to site round trip, same country"),
    "dist.monitoring.flight_threshold_km": ("km", "one-way distance above which a trip is flown"),
    "ef.travel.flight.domestic.passenger_km": ("kg_co2e/passenger_km", "domestic flight, with RF"),
    "ef.travel.flight.short_haul.passenger_km": ("kg_co2e/passenger_km", "short-haul flight, with RF"),
    "ef.travel.flight.long_haul.passenger_km": ("kg_co2e/passenger_km", "long-haul flight, with RF"),
    "dist.flight.short_haul_max_km": ("km", "one-way distance up to which a flight is short-haul"),
    "cost.monitoring.cra_day_rate": ("usd/day", "fully loaded CRA day"),
    "time.monitoring.onsite_visit_days": ("days/visit", "CRA days per on-site visit incl. travel"),
    "time.monitoring.remote_visit_days": ("days/visit", "CRA days per remote monitoring visit"),
    "cost.monitoring.travel_expenses_per_trip": ("usd/trip", "travel + subsistence per on-site trip"),
    "rate.investigator_meeting.attendees_per_site": ("people/site", "kickoff meeting attendees per site"),
    "dist.investigator_meeting.roundtrip_km": ("km/attendee", "kickoff meeting round trip"),
    "cost.investigator_meeting.per_attendee": ("usd/attendee", "travel + venue per attendee"),
    # setup, closeout, trial management, data collection, supplies
    "ef.setup.per_site": ("kg_co2e/site", "site set-up excluding initiation-visit travel"),
    "cost.setup.per_site": ("usd/site", "site start-up (contracts, ethics, initiation)"),
    "cost.closeout.per_site": ("usd/site", "site close-out"),
    "rate.closeout.archive_boxes_per_site": ("boxes/site", "archive boxes per site"),
    "time.closeout.archive_years": ("years", "archive retention period"),
    "ef.closeout.archiving_per_box_year": ("kg_co2e/box_year", "archive storage"),
    "rate.trial_management.fte": ("fte", "coordinating-unit / sponsor staff on the trial"),
    "ef.trial_management.per_fte_year": ("kg_co2e/fte_year", "office energy + commuting per FTE-year"),
    "cost.trial_management.per_fte_year": ("usd/fte_year", "loaded cost per FTE-year"),
    "ef.data_collection.per_patient_year": ("kg_co2e/patient_year", "EDC hosting / data exchange"),
    "cost.data_collection.per_patient": ("usd/patient", "EDC + data management per patient"),
    "ef.supplies_equipment.per_patient": ("kg_co2e/patient", "trial-specific supplies"),
    "cost.supplies_equipment.per_patient": ("usd/patient", "trial-specific supplies"),
    # samples + laboratory
    "supply.sample.samples_per_shipment": ("samples/shipment", "samples batched per shipment"),
    "supply.sample.shipment_weight_kg.<temp>": ("kg/shipment", "shipped weight incl. packaging"),
    "dist.sample.to_central_lab_km.<cc>": ("km/shipment", "site to central lab, one way"),
    "ef.freight.van.tonne_km": ("kg_co2e/tonne_km", "road courier (van)"),
    "ef.freight.air.tonne_km": ("kg_co2e/tonne_km", "air freight, with RF"),
    "supply.sample.dry_ice_kg_per_shipment": ("kg/shipment", "dry ice per frozen shipment"),
    "ef.dry_ice.kg": ("kg_co2e/kg", "dry ice"),
    "cost.courier.shipment.<temp>": ("usd/shipment", "one sample shipment"),
    "energy.freezer.minus80.kwh_per_day": ("kwh/day", "one -80 C upright freezer"),
    "energy.freezer.minus80.trial_share": ("share", "share of one freezer used by the trial, per site"),
    "ef.electricity.grid.<cc>": ("kg_co2e/kwh", "grid electricity"),
    "cost.lab.local_harmonisation_per_site": ("usd/site", "harmonising a local lab with the central lab"),
    "ef.laboratory.per_sample": ("kg_co2e/sample", "analysis of one sample"),
    "cost.lab.central_per_sample": ("usd/sample", "central lab analysis per sample"),
    "cost.lab.local_per_sample": ("usd/sample", "local lab analysis per sample"),
    # drug_supply (extension beyond the published method)
    "supply.kits_per_dispensing_visit": ("kits/visit", "kits dispensed per dispensing visit"),
    "supply.waste_share.<strategy>": ("share", "share of manufactured kits never dispensed"),
    "supply.shipments_per_site.<strategy>": ("shipments/site", "depot to site shipments per site"),
    "cost.drug.kit.<drug_type>": ("usd/kit", "one patient kit"),
    "ef.drug_kit.unit": ("kg_co2e/kit", "manufacture + packaging (+ cold storage) per kit, excl. transport"),
    "supply.kit_shipping_weight_kg": ("kg/kit", "shipped weight per kit incl. packaging"),
    "dist.drug.depot_to_site_km": ("km", "depot to site, one way"),
    "cost.drug.shipment": ("usd/shipment", "one depot to site shipment"),
    # fall-backs for incomplete designs (labelled assumptions)
    "assume.design.visits_per_patient": ("visits", "visits assumed when the design has no schedule"),
    "assume.design.patients_per_site": ("patients/site", "used to assume sites when none are listed"),
}

_PLACEHOLDER = re.compile(r"<[a-z_]+>")


def catalog_patterns() -> list[re.Pattern[str]]:
    """Regexes matching every concrete id the catalog allows (placeholders → one slug segment)."""
    return [
        re.compile("^" + _PLACEHOLDER.sub("[a-z0-9_]+", re.escape(key)) + "$")
        for key in PARAMETER_CATALOG
    ]
