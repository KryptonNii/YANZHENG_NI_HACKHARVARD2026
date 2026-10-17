"""Deterministic incremental changes to the user's current lever selection."""

from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite

from .._contracts import Levers, TrialDesign
from .schemas import BlockedProcedure, CandidateKind, EndpointRole, LeverValue, ProcedureRef

NON_DRUG_TYPES = frozenset({"none", "device"})
BLOCKING_ROLES: dict[EndpointRole, str] = {
    "supports_primary": "Supports a primary endpoint; removal is excluded from advice and "
                        "requires manual protocol review.",
    "supports_secondary": "Supports a secondary endpoint; removal is excluded from advice and "
                          "requires manual protocol review.",
    "unknown": "Endpoint linkage is unknown; removal is excluded from advice and requires "
               "manual protocol review.",
}
MIXED_NOT_LINKED = "Its not_linked occurrences do not override the linked or unknown ones."
REMOVAL_REASON = (
    "Not linked to an endpoint in the reviewed schedule, so removing it is screened as one cost "
    "lever. This is not clinical approval: endpoint linkage does not show the procedure is "
    "unnecessary for safety, eligibility or treatment decisions, and removal still requires "
    "manual protocol review."
)
STRESS_ENROLLMENT_FACTOR = 0.7
MIN_ENROLLMENT_MULTIPLIER = 0.5  # Levers lower bound
STRESS_REASON = (
    "Pressure scenario under an assumed slower enrollment rate. It is an assumption, not a "
    "recommendation, and any cost change is not a saving; it shows how the current plan behaves "
    "if recruitment is slower than expected."
)


@dataclass(frozen=True)
class Candidate:
    id: str
    label: str
    levers: Levers
    patch: dict[str, LeverValue]
    reason: str
    kind: CandidateKind = "lever"
    procedure: ProcedureRef | None = None


def propose(
    current: Levers, identifier: str, label: str, patch: dict[str, LeverValue], reason: str,
    kind: CandidateKind = "lever", procedure: ProcedureRef | None = None,
) -> Candidate | None:
    """Merge a patch into the current levers; lists only gain entries. No-ops return None."""
    merged = current.model_dump()
    changes: dict[str, LeverValue] = {}
    for name, value in patch.items():
        if isinstance(value, list):
            additions = [item for item in dict.fromkeys(value) if item not in merged[name]]
            if additions:
                merged[name] = changes[name] = [*merged[name], *additions]
        elif value != merged[name]:
            merged[name] = changes[name] = value
    if not changes:
        return None
    return Candidate(identifier, label, Levers.model_validate(merged), changes, reason,
                     kind, procedure)


def remote_monitoring(design: TrialDesign, current: Levers) -> Candidate | None:
    if current.remote_monitoring_share < 0.5:
        return propose(current, "remote_monitoring", "50% remote monitoring",
                       {"remote_monitoring_share": 0.5},
                       "Remote monitoring can reduce monitor travel and on-site review work.")
    return None


def local_labs(design: TrialDesign, current: Levers) -> Candidate | None:
    if current.local_lab_share < 0.5:
        return propose(current, "local_labs", "50% local laboratory testing",
                       {"local_lab_share": 0.5},
                       "Local laboratory testing can reduce central sample shipping costs.")
    return None


def on_demand_supply(design: TrialDesign, current: Levers) -> Candidate | None:
    if design.drug_type in NON_DRUG_TYPES:
        return None
    return propose(current, "on_demand_supply", "On-demand drug supply",
                   {"drug_supply_strategy": "on_demand"},
                   "On-demand supply can reduce unused drug kits while changing shipment costs.")


def added_countries(design: TrialDesign, current: Levers) -> Candidate | None:
    extra = min(2, 5 - current.added_country_count)
    if extra <= 0:
        return None
    return propose(current, "added_countries",
                   f"Add {extra} assumed {'country' if extra == 1 else 'countries'}",
                   {"added_country_count": current.added_country_count + extra},
                   "Adding assumed countries can change recruitment time and site costs; these "
                   "are assumed sites, not registry sites.")


def home_visits(design: TrialDesign, current: Levers) -> Candidate | None:
    numbers = sorted({visit.number for visit in design.visits if visit.can_be_remote}
                     - set(current.home_visit_numbers) - set(current.remote_visit_numbers))[:3]
    if not numbers:
        return None
    return propose(current, "home_visits", "Move eligible visits home",
                   {"home_visit_numbers": numbers},
                   "Moving eligible visits home can reduce site work while adding home nursing "
                   "costs.")


LEVER_GENERATORS: tuple[Callable[[TrialDesign, Levers], Candidate | None], ...] = (
    remote_monitoring, local_labs, on_demand_supply, added_countries, home_visits,
)


def site_exclusion(design: TrialDesign, current: Levers) -> tuple[Candidate | None, list[str]]:
    remaining = [site for site in design.sites if site.id not in current.excluded_site_ids]
    if len(remaining) <= 1:
        return None, []
    known = [site for site in remaining
             if site.expected_enrollment is not None and isfinite(site.expected_enrollment)]
    warnings = [] if len(known) == len(remaining) else [
        "Some sites have no finite expected_enrollment; the smallest site is selected only among "
        "reported values, or site exclusion is skipped if none are reported."
    ]
    if not known:
        return None, warnings
    smallest = min(known, key=lambda site: (site.expected_enrollment, site.id))
    return propose(current, f"exclude_site:{smallest.id}", f"Exclude {smallest.name}",
                   {"excluded_site_ids": [smallest.id]},
                   "Excluding the remaining site with the lowest reported expected enrollment can "
                   "reduce site costs but may lengthen recruitment."), warnings


def endpoint_roles_by_code(design: TrialDesign) -> dict[str, set[EndpointRole]]:
    roles: dict[str, set[EndpointRole]] = {}
    for visit in design.visits:
        for procedure in visit.procedures:
            roles.setdefault(procedure.code, set()).add(procedure.endpoint_role)
    return roles


def blocked_procedures(roles_by_code: dict[str, set[EndpointRole]]) -> list[BlockedProcedure]:
    """Codes with any primary, secondary or unknown role; a not_linked visit never unblocks."""
    return [BlockedProcedure(
        code=code, endpoint_roles=sorted(roles),
        reason=" ".join([text for role, text in BLOCKING_ROLES.items() if role in roles]
                        + ([MIXED_NOT_LINKED] if "not_linked" in roles else [])),
    ) for code, roles in sorted(roles_by_code.items()) if roles & BLOCKING_ROLES.keys()]


def procedure_removal_candidates(
    design: TrialDesign, current: Levers, roles_by_code: dict[str, set[EndpointRole]],
) -> list[Candidate]:
    """One single-procedure removal per code whose every occurrence is not_linked."""
    labels: dict[str, str] = {}
    for visit in design.visits:
        for procedure in visit.procedures:
            labels.setdefault(procedure.code, procedure.label)
    proposals = [propose(
        current, f"remove_procedure:{code}", f"Remove {labels[code]}",
        {"removed_procedures": [code]}, REMOVAL_REASON, "procedure_removal",
        ProcedureRef(code=code, label=labels[code]),
    ) for code, roles in sorted(roles_by_code.items()) if roles == {"not_linked"}]
    return [candidate for candidate in proposals if candidate is not None]


def build_candidates(
    design: TrialDesign, current: Levers | None = None,
) -> tuple[list[Candidate], list[BlockedProcedure], list[str]]:
    current = current or Levers()
    candidates = [candidate for generate in LEVER_GENERATORS
                  if (candidate := generate(design, current)) is not None]
    site, warnings = site_exclusion(design, current)
    if site is not None:
        candidates.append(site)
    roles_by_code = endpoint_roles_by_code(design)
    blocked = blocked_procedures(roles_by_code)
    candidates += procedure_removal_candidates(design, current, roles_by_code)
    if current.removed_procedures:
        warnings.append("Existing procedure removals are retained as the comparison baseline; "
                        "this does not approve their clinical appropriateness.")
    removed_blocked = sorted({item.code for item in blocked} & set(current.removed_procedures))
    if removed_blocked:
        warnings.append(
            f"Your current selection already removes {', '.join(removed_blocked)}, which "
            "support an endpoint or have unknown linkage; advice keeps these removals only as the "
            "comparison baseline, and this is not approval of removing them."
        )
    return candidates, blocked, warnings


def slower_enrollment(current: Levers) -> Candidate | None:
    """The assumption-only pressure scenario; never a lever candidate."""
    multiplier = round(max(MIN_ENROLLMENT_MULTIPLIER,
                           current.enrollment_rate_multiplier * STRESS_ENROLLMENT_FACTOR), 4)
    if multiplier >= current.enrollment_rate_multiplier:
        return None
    slower = round(100 * (1 - multiplier / current.enrollment_rate_multiplier))
    return propose(current, "slower_enrollment",
                   f"Enrollment {slower}% slower than your current selection",
                   {"enrollment_rate_multiplier": multiplier}, STRESS_REASON)
