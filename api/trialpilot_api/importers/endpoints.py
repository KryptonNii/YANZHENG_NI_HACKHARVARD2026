"""Conservative registry text links; these annotations never decide procedure removal."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from ._contracts import Procedure, Visit


def _words(text: str) -> str:
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold()))


def _key(visit: Visit, procedure: Procedure) -> tuple[int, str, str]:
    # Codes can group unrelated assessments, and roles can differ between visits.
    return visit.number, procedure.code, _words(procedure.label)


def link_visits(
    visits: list[Visit], outcomes: dict[str, Any], previous: list[Visit] | None = None,
) -> list[Visit]:
    """Match a complete label as a token phrase in measure + timeFrame (never description).

    At least part of the label must occur in the measure: a time point alone is not an
    outcome link. Primary takes precedence if both roles match. No synonyms, code-based
    guesses, clinical inference or inferred visit timing. Human choices survive reimport
    for the same visit number, code and normalized label (including a corrected visit
    week); fresh human edits win.
    """
    human = {
        _key(v, p): p
        for v in previous or [] for p in v.procedures if p.link_basis == "human"
    }
    result = []
    for visit in visits:
        procedures = []
        for procedure in visit.procedures:
            p = procedure.model_copy(deep=True)
            saved = human.get(_key(visit, p))
            if p.link_basis == "human":
                procedures.append(p)
                continue
            if saved is not None:
                p.endpoint_role = saved.endpoint_role
                p.endpoint_note = saved.endpoint_note
                p.link_basis = "human"
                procedures.append(p)
                continue
            p.endpoint_role, p.endpoint_note, p.link_basis = "unknown", "", "unmatched"
            label = _words(p.label)
            for field, role in (("primaryOutcomes", "supports_primary"),
                                ("secondaryOutcomes", "supports_secondary")):
                for outcome in outcomes.get(field) or []:
                    title = str(outcome.get("measure") or "").strip()
                    timing = str(outcome.get("timeFrame") or "").strip()
                    title_words = _words(title)
                    # A label must match in full in the title, optionally followed by
                    # its timeFrame. Do not match labels found only in the timeFrame.
                    if not label or not title_words:
                        continue
                    match = re.search(r"(?<!\w)" + re.escape(label) + r"(?!\w)",
                                      title_words + " " + _words(timing))
                    if match is None or match.start() >= len(title_words):
                        continue
                    p.endpoint_role = role
                    p.endpoint_note = f"{field}: {title}" + (f" — {timing}" if timing else "")
                    p.link_basis = "outcome_title"
                    break
                if p.link_basis == "outcome_title":
                    break
            procedures.append(p)
        result.append(visit.model_copy(update={"procedures": procedures}))
    return result
