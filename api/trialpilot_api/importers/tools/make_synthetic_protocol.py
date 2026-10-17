"""Synthetic protocol PDFs with a KNOWN schedule of activities (for tests and the live demo).

Fictional content written for TrialPilot (no third-party text). Two variants:
  * text  - SoA as a real PDF table split over two pages (read by the deterministic grid parser)
  * image - the same SoA rendered as a picture (needs the vision LLM path; mocked in tests)

    uv run --project api python -m trialpilot_api.importers.tools.make_synthetic_protocol data/fixtures/protocols/synthetic_protocol.pdf
"""

from __future__ import annotations

import io
import sys
from typing import Any

# Ground truth: visit number -> (label, week, window or None); plus procedure rows -> visits marked.
VISITS: list[tuple[int, str, float, tuple[float, float] | None]] = [
    (1, "Screening", -4, (-4, -1)),
    (2, "Baseline", 0, None),
    (3, "Visit 3", 4, None),
    (4, "Visit 4", 12, None),
    (5, "Visit 5", 24, None),
    (6, "End of treatment", 36, None),
    (7, "Follow-up", 40, None),
]
# label as printed (footnote markers included on purpose), expected code, visits marked, page part (1 or 2)
ROWS: list[tuple[str, str, list[int], int]] = [
    ("Informed consent", "informed_consent", [1], 1),
    ("Inclusion/exclusion criteria a", "eligibility_check", [1, 2], 1),
    ("Medical history", "medical_history", [1], 1),
    ("Randomization", "randomization", [2], 1),
    ("Physical examination", "physical_exam", [1, 2, 5, 6], 1),
    ("Vital signs", "vital_signs", [1, 2, 3, 4, 5, 6, 7], 1),
    ("12-lead ECG b", "ecg", [1, 2, 4, 6], 1),
    ("Hematology and chemistry", "blood_draw", [1, 2, 3, 4, 5, 6], 1),
    ("Study drug administration", "imp_administration", [2, 3, 4, 5], 1),
    ("PK sample", "pk_sample", [2, 3, 4, 6], 2),
    ("Anti-drug antibodies", "ada_sample", [2, 4, 6], 2),
    ("Quality of life questionnaire", "questionnaire", [2, 4, 6], 2),
    ("Chest X-ray", "x_ray", [1], 2),
    ("Smoking status", "other:smoking_status", [1, 2, 6], 2),
    ("Adverse events", "adverse_events", [2, 3, 4, 5, 6, 7], 2),
]
OFFSITE_WEEK = 30  # an unnumbered column (home dosing) that must NOT become a visit


def _grid(part: int) -> list[list[str]]:
    header_visit = ["Visit"] + [str(n) for n, *_ in VISITS[:5]] + [""] + [str(n) for n, *_ in VISITS[5:]]
    header_name = ["Period", "Screening", "Baseline", "", "", "", "Home", "EOT", "Follow-up"]
    weeks = ["Week", "-4 to -1", "0", "4", "12", "24", str(OFFSITE_WEEK), "36", "40"]
    rows = [header_name, header_visit, weeks]
    for label, _code, marked, p in ROWS:
        if p != part:
            continue
        cells = [label]
        for n, *_ in VISITS[:5]:
            cells.append("X" if n in marked else "")
        cells.append("X" if label == "Study drug administration" else "")  # home dosing column
        for n, *_ in VISITS[5:]:
            cells.append("X" if n in marked else "")
        rows.append(cells)
    return rows


def ground_truth() -> dict[str, Any]:
    return {
        "visits": [
            {"number": n, "label": label, "week": week, "window": list(win) if win else None,
             "codes": sorted({code for _l, code, marked, _p in ROWS if n in marked})}
            for n, label, week, win in VISITS
        ],
        "offsite_weeks": [OFFSITE_WEEK],
    }


def _table_image_png(rows: list[list[str]]) -> bytes:
    from PIL import Image, ImageDraw

    cw, rh, first = 90, 26, 240
    w, h = first + cw * (len(rows[0]) - 1) + 2, rh * len(rows) + 2
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    for r, row in enumerate(rows):
        for c, text in enumerate(row):
            x0 = 0 if c == 0 else first + cw * (c - 1)
            x1 = first if c == 0 else x0 + cw
            d.rectangle([x0, r * rh, x1, (r + 1) * rh], outline="black")
            d.text((x0 + 4, r * rh + 7), text, fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_pdf(variant: str = "text") -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import (
        Image,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    styles = getSampleStyleSheet()
    buf = io.BytesIO()

    def footer(canvas: Any, doc: Any) -> None:
        canvas.setFont("Helvetica", 8)
        canvas.drawString(40, 20, f"TrialPilot synthetic protocol TP-SYN-001 - fictional - Page {doc.page}")

    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), title="TP-SYN-001 synthetic protocol", invariant=1)
    story: list[Any] = [
        Paragraph("CLINICAL TRIAL PROTOCOL TP-SYN-001 (fictional, generated for software tests)", styles["Title"]),
        Paragraph("TABLE OF CONTENTS", styles["Heading2"]),
        Paragraph("1.1 Synopsis ........................................ 2", styles["Normal"]),
        Paragraph("1.2 Schedule of Activities ........................ 3", styles["Normal"]),
        PageBreak(),
        Paragraph("1.1 Synopsis", styles["Heading2"]),
        Paragraph("A fictional 36-week randomized study used to test schedule-of-activities extraction. "
                  "Study drug is given at the site at visits 2 to 5 and at home at week 30.", styles["Normal"]),
        PageBreak(),
        Paragraph("1.2 Schedule of Activities", styles["Heading2"]),
        Spacer(1, 8),
    ]
    style = TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black), ("FONTSIZE", (0, 0), (-1, -1), 8)])
    for part in (1, 2):
        grid = _grid(part)
        if variant == "text":
            t = Table(grid, colWidths=[180] + [62] * (len(grid[0]) - 1))
            t.setStyle(style)
            story.append(t)
        else:
            png = _table_image_png(grid)
            iw, ih = ImageReader(io.BytesIO(png)).getSize()
            story.append(Image(io.BytesIO(png), width=iw * 0.9, height=ih * 0.9))
        story.append(Paragraph("a Footnote: eligibility is re-confirmed at baseline. b Footnote: ECG read centrally.",
                               styles["Normal"]))
        story.append(PageBreak())
    story.append(Paragraph("2 Introduction", styles["Heading2"]))
    story.append(Paragraph("Fictional background text. " * 40, styles["Normal"]))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "synthetic_protocol.pdf"
    variant = sys.argv[2] if len(sys.argv) > 2 else "text"
    with open(out, "wb") as f:
        f.write(make_pdf(variant))
    print(f"wrote {out} ({variant})")
