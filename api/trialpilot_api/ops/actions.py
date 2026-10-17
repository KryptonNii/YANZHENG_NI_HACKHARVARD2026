"""Recommended actions per alert kind, the default metric to track, and how the SIMULATOR responds.

The response (`sim_effect`) is part of the simulation's ground truth — it is what "really" happens in
the simulated world when someone takes that action. The effect estimator never reads it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Action:
    code: str
    text: str
    sim_effect: str  # plain-English description of the simulated response (ground truth)


ACTIONS: dict[str, Action] = {
    a.code: a
    for a in [
        Action("feasibility_call", "Hold a feasibility call with the site to review its pre-screening log",
               "none"),
        Action("enrollment_retraining",
               "Retrain the site on inclusion/exclusion criteria and referral pathways",
               "site enrollment rate x1.6 from 14 days after the start"),
        Action("activate_backup", "Activate a backup site in the same country",
               "backup sites in the country start enrolling 1.5 patients/month 14 days after the start"),
        Action("close_site", "Close the site and reallocate its enrollment target",
               "site stops enrolling and returns all kits"),
        Action("crf_retraining", "Retrain site staff on eCRF completion guidelines",
               "query rate x0.35 and faster query closure from the start"),
        Action("query_session", "Run a remote query-resolution session with the CRA",
               "queries open at the start are closed within 1-7 days; query rate unchanged"),
        Action("query_reminder_email", "Send weekly open-query reminder e-mails to site coordinators", "none"),
        Action("supply_on_demand",
               "Switch the site to on-demand (IRT-triggered) resupply and return excess kits to the depot",
               "excess kits returned 2 days after the start; predictive resupply from then on"),
        Action("transfer_excess", "Transfer excess kits to the regional depot before they expire",
               "one-off return of excess kits; the bulk push schedule continues"),
        Action("raise_trigger", "Raise the site's IRT resupply trigger and maximum stock levels",
               "IRT levels use the observed enrollment rate and the actual lead time"),
        Action("emergency_resupply", "Send an emergency resupply shipment by air",
               "one expedited shipment arriving 2 days after dispatch"),
        Action("ground_shipping", "Switch specimen shipments to ground courier with dry ice (<= 48 h transit)",
               "shipments follow the ground SOP from the start"),
        Action("batch_monitoring", "Batch monitoring visits by city: one trip per cluster per cycle",
               "one trip per city cluster per cycle from the start"),
        Action("remote_monitoring", "Move alternate monitoring visits to remote source-data review",
               "every second monitoring cycle is remote (no travel)"),
        Action("vendor_escalation", "Escalate to the vendor's account lead and agree a recovery plan", "none"),
        Action("vendor_resourcing", "Ask the vendor to add a second programming team for the delivery",
               "vendor recovers 60% of the slip over two months"),
        Action("dblock_rebaseline", "Re-baseline the database-lock timeline with the steering committee",
               "none (planning action)"),
        Action("prioritise_cleaning", "Prioritise data cleaning at sites with the largest query backlogs",
               "none"),
        Action("visit_reminder_sms", "Visit-reminder SMS programme for patients", "none"),
    ]
}

RECOMMENDED: dict[str, list[str]] = {
    "enrollment_lag": ["enrollment_retraining", "feasibility_call", "activate_backup"],
    "enrollment_lag_never": ["close_site", "activate_backup", "feasibility_call"],
    "query_backlog": ["crf_retraining", "query_session"],
    "drug_overstock": ["supply_on_demand", "transfer_excess"],
    "drug_shortfall": ["raise_trigger", "emergency_resupply"],
    "costly_shipping_mode": ["ground_shipping"],
    "monitoring_inefficiency": ["batch_monitoring", "remote_monitoring"],
    "vendor_delay": ["vendor_resourcing", "vendor_escalation"],
    "milestone_at_risk": ["dblock_rebaseline", "prioritise_cleaning"],
}

DEFAULT_METRIC: dict[str, str] = {
    "enrollment_lag": "enrollment_rate_per_month",
    "query_backlog": "query_rate_percent",
    "drug_overstock": "kits_on_hand",
    "drug_shortfall": "kits_on_hand",
    "costly_shipping_mode": "air_shipment_share_percent",
    "monitoring_inefficiency": "monitoring_co2e_kg_per_month",
    "vendor_delay": "milestone_slip_days",
    "milestone_at_risk": "milestone_slip_days",
}

# Intended direction of change per alert kind (overrides the metric default, e.g. shortfall wants more kits).
DIRECTION: dict[str, str] = {"drug_shortfall": "up"}

_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("backup site", "activate"), "activate_backup"),
    (("on-demand",), "supply_on_demand"),
    (("on demand",), "supply_on_demand"),
    (("transfer", "kit"), "transfer_excess"),
    (("return", "kit"), "transfer_excess"),
    (("trigger",), "raise_trigger"),
    (("emergency",), "emergency_resupply"),
    (("ground",), "ground_shipping"),
    (("batch",), "batch_monitoring"),
    (("remote", "monitor"), "remote_monitoring"),
    (("ecrf",), "crf_retraining"),
    (("retrain", "query"), "crf_retraining"),
    (("query-resolution",), "query_session"),
    (("query resolution",), "query_session"),
    (("inclusion",), "enrollment_retraining"),
    (("retrain", "referral"), "enrollment_retraining"),
    (("close the site",), "close_site"),
    (("second programming team",), "vendor_resourcing"),
]


def recommended_texts(kind: str) -> list[str]:
    return [ACTIONS[c].text for c in RECOMMENDED.get(kind, [])]


def action_code(text: str) -> str:
    """Map free-text intervention actions to a catalog code ('unrecognised' -> no simulated effect)."""
    t = (text or "").strip().lower()
    for a in ACTIONS.values():
        if a.text.lower() == t or a.code == t:
            return a.code
    for words, code in _KEYWORDS:
        if all(w in t for w in words):
            return code
    return "unrecognised"


def catalog() -> list[dict[str, object]]:
    return [
        {"kind": kind, "default_metric": DEFAULT_METRIC.get(kind.replace("_never", "")),
         "actions": [{"code": c, "text": ACTIONS[c].text} for c in codes]}
        for kind, codes in RECOMMENDED.items()
    ]
