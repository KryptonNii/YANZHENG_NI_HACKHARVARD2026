"""Static small-multiples chart of complexity_trend.json for the README and the deck (SVG).

One panel per measure, shared log y-axis, 1x = as expected for phase and disease area. Regeneron-led
and large-sponsor peers are highlighted; all other industry trials are the gray context line.
`python -m trialpilot_api.benchmark.trend_chart` rewrites docs/complexity/complexity_trend.svg.
"""

from __future__ import annotations

import json
import math
from html import escape
from pathlib import Path
from typing import Any

from .trend import OUT_JSON

OUT_SVG = OUT_JSON.with_suffix(".svg")
W, H = 1600, 900
LEFT, RIGHT, TOP, BOTTOM, GAP = 84, 196, 236, 772, 40
Y_MIN, Y_MAX, Y_TICKS = 0.7, 5.0, (1, 2, 3, 5)
PANELS = (("composite", "Composite (outcomes, countries, sites)"),
          ("outcomes", "Registered outcome measures"),
          ("countries", "Countries"), ("sites", "Sites"))
SERIES = (  # drawn back to front
    ("industry", "All other industry", "#898781"),
    ("large_sponsor_peers", "Large-sponsor peers", "#eb6834"),
    ("sponsor_led", "Regeneron-led", "#2a78d6"),
)
INK, INK_2, MUTED, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", \
    "#fcfcfb"
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'


def _y(v: float) -> float:
    t = (math.log(v) - math.log(Y_MIN)) / (math.log(Y_MAX) - math.log(Y_MIN))
    return BOTTOM - t * (BOTTOM - TOP)


def _text(x: float, y: float, s: str, size: int = 15, fill: str = INK_2, anchor: str = "start",
          weight: int = 400) -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" '
            f'text-anchor="{anchor}" font-weight="{weight}">{escape(s)}</text>')


def render(report: dict[str, Any]) -> str:
    res = report["results"]
    blocks = res["blocks"]
    rows = {(s["group"], s["period"], s["metric"]): s for s in res["series"]}
    pw = (W - LEFT - RIGHT - GAP * (len(PANELS) - 1)) / len(PANELS)
    n_all = {g: rows[g, "all", "composite"]["n"] for g, _, _ in SERIES}
    peers = len(res["large_sponsor_peers"])
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
        f'font-family=\'{FONT}\' role="img" aria-labelledby="t d">',
        '<title id="t">Registered trial complexity versus expectation, 2010 to 2024</title>',
        '<desc id="d">Median observed-to-expected ratios by three-year start block for '
        'Regeneron-led trials, large-sponsor peers and all other industry trials. Values are in '
        'docs/complexity/complexity_trend.json and the table in docs/COMPLEXITY_TREND.md.</desc>',
        f'<rect width="{W}" height="{H}" fill="{SURFACE}"/>',
        _text(LEFT - 20, 64, "Registered trial complexity vs. expectation, 2010–2024", 34, INK,
              weight=600),
        _text(LEFT - 20, 100, "Median observed ÷ expected for industry-led Phase 2, 2/3 and 3 "
              "trials. Expected = industry median for the same phase and MeSH disease category.",
              17),
        _text(LEFT - 20, 124, "Shaded band = 95% bootstrap interval. Log scale; 1× = as "
              "expected.", 17),
    ]
    lx = LEFT - 20
    for group, label, color in reversed(SERIES):
        extra = f", {peers} sponsors" if group == "large_sponsor_peers" else ""
        item = f"{label} (n={n_all[group]:,}{extra})"
        out.append(f'<rect x="{lx}" y="152" width="14" height="14" rx="3" fill="{color}"/>')
        out.append(_text(lx + 22, 164, item, 16, INK))
        lx += 22 + len(item) * 8.6 + 36
    for i, (metric, title) in enumerate(PANELS):
        x0 = LEFT + i * (pw + GAP)
        xs = [x0 + 16 + k * (pw - 32) / (len(blocks) - 1) for k in range(len(blocks))]
        out.append(_text(x0, TOP - 22, title, 17, INK, weight=600))
        for v in Y_TICKS:
            stroke = AXIS if v == 1 else GRID
            out.append(f'<line x1="{x0}" x2="{x0 + pw}" y1="{_y(v):.1f}" y2="{_y(v):.1f}" '
                       f'stroke="{stroke}" stroke-width="1"/>')
            if i == 0:
                out.append(_text(x0 - 10, _y(v) + 5, f"{v:g}×", 14, MUTED, "end"))
        for x, b in zip(xs, blocks, strict=True):
            lo, hi = b.split("-")
            out.append(_text(x, BOTTOM + 26, f"{lo}–{hi[2:]}", 13, MUTED, "middle"))
        for group, _, color in SERIES:
            pts = [rows.get((group, b, metric)) for b in blocks]
            if any(p is None for p in pts):
                continue
            band = [(x, _y(p["ci95"][1])) for x, p in zip(xs, pts, strict=True)] + \
                [(x, _y(p["ci95"][0])) for x, p in reversed(list(zip(xs, pts, strict=True)))]
            out.append(f'<polygon points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in band)}" '
                       f'fill="{color}" fill-opacity="0.14"/>')
            line = " ".join(f"{x:.1f},{_y(p['median_ratio']):.1f}"
                            for x, p in zip(xs, pts, strict=True))
            out.append(f'<polyline points="{line}" fill="none" stroke="{color}" '
                       f'stroke-width="2" stroke-linejoin="round"/>')
            for x, p in zip(xs, pts, strict=True):
                out.append(f'<circle cx="{x:.1f}" cy="{_y(p["median_ratio"]):.1f}" r="4.5" '
                           f'fill="{color}" stroke="{SURFACE}" stroke-width="2"/>')
        if i == len(PANELS) - 1:  # direct labels at line ends, nudged apart
            ends = sorted(((_y(rows[g, blocks[-1], metric]["median_ratio"]), lab)
                           for g, lab, _ in SERIES), key=lambda e: e[0])
            last = -1e9
            for y, lab in ends:
                y = max(y, last + 20)
                out.append(_text(xs[-1] + 14, y + 5, lab, 14, INK))
                last = y
    src = report["source"]
    out += [
        _text(LEFT - 20, H - 66, f"Source: ClinicalTrials.gov API v{src['api_version']}, data "
              f"timestamp {src['data_timestamp'][:10]}; {res['trials_in_window']:,} industry-led "
              "trials started 2010–2024. Registry fields are sponsor-reported proxies.", 14),
        _text(LEFT - 20, H - 44, "Ratios are questions for a design team, not quality "
              "judgments. Eligibility is omitted: most Regeneron postings list key criteria "
              "only. Method: docs/COMPLEXITY_TREND.md", 14),
        "</svg>",
    ]
    return "\n".join(out) + "\n"


def main() -> None:
    report = json.loads(Path(OUT_JSON).read_text(encoding="utf-8"))
    OUT_SVG.write_text(render(report), encoding="utf-8")
    print(f"wrote {OUT_SVG}")


if __name__ == "__main__":
    main()
