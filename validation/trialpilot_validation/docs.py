"""`tpv plan`, `tpv risk` and the URS document.

The GAMP software-category judgement is drafted for a human decision and stamped DRAFT. No GAMP
guide text is reproduced (copyrighted); the guide is referenced by title only.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from . import ai_draft
from .context import DRAFT_STAMP, Ctx, md_escape, sha256_file, write_text

DELIVERABLES = [
    ("D1", "Validation plan", "tpv plan", "plan.md"),
    ("D2", "User requirements (URS)", "validation/requirements.yaml", "urs.md"),
    ("D3", "Risk assessment", "tpv risk", "risk_assessment.md"),
    ("D4", "OQ test protocol (approved before execution)", "tpv protocol", "protocol.md"),
    ("D5", "Executed evidence + manifest (signed 'executed')", "tpv execute", "evidence.md"),
    ("D6", "Traceability matrix", "tpv trace", "trace_matrix.md"),
    ("D7", "Validation summary report (QA approval)", "tpv report", "report.md"),
    ("D8", "Change control (impact analysis, change record)", "tpv impact", "change_control.md"),
]


def plan_md(ctx: Ctx, *, ai: bool = False) -> str:
    reqs = ctx.requirements()
    areas = Counter(r.get("area", "other") for r in reqs)
    risk = Counter(r["risk"] for r in reqs)
    git = ctx.git_info()
    lines = ["# Validation Plan — TrialPilot", ""]
    intro = ai_draft.draft(
        "Write a 3-sentence introduction for a computerised system validation plan for "
        "TrialPilot, an open-source clinical-trial scenario simulator and command center with "
        "an audit trail and e-signatures. Neutral, factual tone. No numbers.",
    ) if ai else None
    if intro:
        lines += [DRAFT_STAMP + " (AI-drafted paragraph)", "", intro, ""]
    lines += [
        "## 1. Purpose and scope",
        "This plan defines how TrialPilot is validated for its intended use: planning clinical-trial "
        "designs (cost, site workload, patient burden, timeline risk, carbon) and monitoring "
        "simulated trial operations, with an append-only audit trail, electronic signatures and "
        "role-based approvals. It follows the fictional company procedure SOP CSV-001 "
        "(`validation/company_sop.md`).",
        "",
        f"- Version under validation: git commit `{git.get('commit') or 'unknown'}`"
        + (" (with uncommitted changes)" if git.get("dirty") else ""),
        f"- Requirements in scope: **{len(reqs)}** "
        f"(H {risk.get('H', 0)}, M {risk.get('M', 0)}, L {risk.get('L', 0)}; "
        f"GxP-relevant {sum(1 for r in reqs if r['gxp'])})",
        "- Areas: " + ", ".join(f"{a} ({n})" for a, n in sorted(areas.items())),
        "- Out of scope: infrastructure qualification (IQ) of a production host, real patient "
        "data, integrations with real EDC/CTMS/IRT systems (TrialPilot ingests simulated feeds).",
        "",
        "## 2. System category (judgement for a human decision)",
        "",
        DRAFT_STAMP,
        "",
        "Suggested: **GAMP 5 software category 5 (custom application)** — TrialPilot is "
        "bespoke code written for this purpose (engine, API, UI), not configured off-the-shelf "
        "software. Libraries it builds on (FastAPI, React, NumPy, SQLite) would be treated as "
        "category 1 infrastructure software. Reference: ISPE GAMP® 5 Guide, 2nd edition (2022) — "
        "consult the guide; it is not reproduced here. *This category must be confirmed or "
        "changed by the validation lead and QA; tpv does not decide it.*",
        "",
        "## 3. Approach (risk-based)",
        "- Each URS item carries a risk (H/M/L) and a GxP flag with written rationale "
        "(`tpv risk`). Test depth follows SOP CSV-001 §4.",
        "- Tests are automated (pytest per package, Playwright end-to-end) and tagged with the "
        "requirement ids they verify. `tpv protocol` lists them per requirement.",
        "- The protocol is approved (reviewer → QA) **before** `tpv execute` runs it. Execution "
        "evidence is hashed in a manifest and signed `executed` by the executor.",
        "- `tpv trace` links requirement → risk → tests → result → evidence hash and flags gaps; "
        "`tpv report` states the real counts; QA approves the report in the app.",
        "- Planted defects (`validation/defects/`) check that this process actually catches "
        "problems; the detection count is reported as measured (`tpv defects-run`).",
        "",
        "## 4. Deliverables",
        "",
        "| # | Deliverable | Produced by | File in package |",
        "|---|---|---|---|",
    ]
    lines += [f"| {d} | {t} | `{cmd}` | {f} |" for d, t, cmd, f in DELIVERABLES]
    lines += [
        "",
        "## 5. Roles",
        "Author (writes and executes), Reviewer (independent review), QA (final approval), Admin "
        "(no signing), Viewer (read-only). Matrix: `validation/ROLES.md`. Nobody approves their "
        "own work; enforced in code (`workflow.py`).",
        "",
        "## 6. Acceptance criteria",
        "Every requirement passes (all its tests pass), no requirement is left without a test, "
        "and every deviation is resolved or justified in the summary report before QA approval.",
        "",
        "## 7. Use of AI",
        "AI may draft prose (e.g. a plan introduction with `tpv plan --ai-draft`); every such "
        f"paragraph is stamped \"{DRAFT_STAMP}\". Results, evidence, counts and signatures are "
        "produced by the test runners and humans only; AI actors cannot sign (enforced in code).",
        "",
    ]
    return "\n".join(lines)


def risk_md(ctx: Ctx) -> str:
    reqs = ctx.requirements()
    risk = Counter(r["risk"] for r in reqs)
    lines = ["# Risk Assessment — TrialPilot", "",
             "Scale (SOP CSV-001 §4): **H** — could corrupt a GxP record/signature, mislead a trial "
             "decision or hide a change (≥ 2 tests incl. a negative test); **M** — degrades "
             "decision quality, detectable (≥ 1 test); **L** — cosmetic/performance (test or "
             "justification).", "",
             f"Totals: H **{risk.get('H', 0)}** · M **{risk.get('M', 0)}** · L "
             f"**{risk.get('L', 0)}** · GxP-relevant **{sum(1 for r in reqs if r['gxp'])}** of "
             f"{len(reqs)}", "",
             "| Requirement | Area | Risk | Rationale | GxP | GxP rationale |",
             "|---|---|---|---|---|---|"]
    for r in reqs:
        lines.append(f"| **{r['id']}** {md_escape(' '.join(str(r['text']).split()))} | "
                     f"{r.get('area', '')} | **{r['risk']}** | {md_escape(r['risk_rationale'])} | "
                     f"{'yes' if r['gxp'] else 'no'} | {md_escape(r.get('gxp_rationale', ''))} |")
    lines.append("")
    return "\n".join(lines)


def urs_md(ctx: Ctx) -> str:
    doc = ctx.requirements_doc()
    reqs = ctx.requirements()
    lines = [f"# User Requirements Specification — {doc.get('system', 'TrialPilot')}", "",
             f"Document `{doc.get('id', 'URS')}` version {doc.get('version', 1)} · source "
             f"`validation/requirements.yaml` (sha256 "
             f"`{sha256_file(ctx.vdir / 'requirements.yaml')[:16]}…`)", "",
             "| ID | Area | Requirement | Risk | GxP |", "|---|---|---|---|---|"]
    for r in reqs:
        lines.append(f"| **{r['id']}** | {r.get('area', '')} | "
                     f"{md_escape(' '.join(str(r['text']).split()))} | {r['risk']} | "
                     f"{'yes' if r['gxp'] else 'no'} |")
    lines.append("")
    return "\n".join(lines)


def write_plan(ctx: Ctx, *, ai: bool = False) -> Any:
    return write_text(ctx.out / "plan" / "plan.md", plan_md(ctx, ai=ai))


def write_risk(ctx: Ctx) -> Any:
    return write_text(ctx.out / "risk" / "risk_assessment.md", risk_md(ctx))
