"""Did the intervention work? Difference-in-differences with matched controls and a two-stage bootstrap.

effect = (treated post − treated pre) − (control post − control pre)

* Windows: up to 12 complete weeks before the start week vs up to 26 complete weeks after it (the start
  week itself is excluded as a transition week), never past the clock.
* Controls (up to 6 sites / 4 countries): untreated units at the same level, not touched by another
  intervention on the same metric in the window, with data in both windows. Ranked by tier (same country →
  same region → same hemisphere → all), then by how close their whole pre-start history is to the treated
  units' (not the short pre-window, to avoid regression-to-the-mean bias).
* Uncertainty: cluster bootstrap over units when a group has >= 5 units, otherwise bootstrap over weeks
  within each (fixed) unit; B = 1000, seeded.
  `effect` reports bootstrap P10/P50/P90; verdicts use the 95% interval.
* Verdicts:
  - likely_worked: 95% CI of the DiD excludes 0 in the intended direction;
  - likely_coincidence: CI includes 0, but the treated units clearly improved (95% CI of their own change
    excludes 0) and the controls moved the same way by at least half as much;
  - no_effect: the 90% interval lies within ± max(50% of the treated baseline, metric floor) (equivalence,
    TOST at 5%) — or the treated units got significantly worse than controls;
  - inconclusive: anything else (too little data, no controls, wide interval).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import actions
from ._contracts import EffectEstimate, Intervention, MetricRange
from .metrics import METRICS, Feed
from .plan import OpsPlan

PRE_MAX_WEEKS = 12
PRE_MIN_WEEKS = 4
POST_MAX_WEEKS = 26
POST_MIN_WEEKS = 3
MIN_CONTROLS = 3
K_SITE, K_COUNTRY = 6, 4
B = 1000
UNIT_RESAMPLE_MIN = 5  # >= 5 units: cluster bootstrap over units; fewer: bootstrap weeks within units


@dataclass
class EffectDetails:
    estimate: EffectEstimate
    metric: str
    unit: str
    level: str
    better: str
    treated_units: list[str] = field(default_factory=list)
    control_units: list[str] = field(default_factory=list)
    control_tier: str = ""
    pre_weeks: tuple[int, int] = (0, 0)
    post_weeks: tuple[int, int] = (0, 0)
    values: dict[str, float] = field(default_factory=dict)
    ci95: tuple[float, float] | None = None
    treated_change_ci95: tuple[float, float] | None = None
    control_change_ci95: tuple[float, float] | None = None

    def to_dict(self, plan: OpsPlan) -> dict:
        return {
            "estimate": self.estimate.model_dump(mode="json"),
            "metric": self.metric, "metric_label": METRICS[self.metric].label if self.metric in METRICS else
            self.metric, "unit": self.unit, "level": self.level, "better": self.better,
            "treated_units": self.treated_units, "control_units": self.control_units,
            "control_tier": self.control_tier,
            "pre_window": _window(plan, self.pre_weeks), "post_window": _window(plan, self.post_weeks),
            "values": self.values, "ci95": self.ci95, "treated_change_ci95": self.treated_change_ci95,
            "control_change_ci95": self.control_change_ci95, "bootstrap_draws": B,
            "method_note": "difference-in-differences, matched controls, two-stage bootstrap (units, weeks)",
        }


def _window(plan: OpsPlan, wk: tuple[int, int]) -> dict:
    a, b = wk
    return {"start": plan.date(a * 7).date().isoformat(), "end": plan.date(b * 7).date().isoformat(),
            "weeks": max(0, b - a)}


def _inconclusive(iv: Intervention, metric: str, why: str, unit: str = "percent") -> EffectDetails:
    md = METRICS.get(metric)
    zero = MetricRange(p10=None, p50=None, p90=None, unit=(md.unit if md else unit))  # type: ignore[arg-type]
    est = EffectEstimate(intervention_id=iv.id, method="diff_in_diff", effect=zero, treated_change=0.0,
                         control_change=0.0, verdict="inconclusive", explanation=why)
    return EffectDetails(est, metric, zero.unit, md.level if md else "study", md.better if md else "down")


def _group_draws(num_pre, den_pre, num_post, den_post, scale, rng) -> tuple[np.ndarray, np.ndarray]:
    """Bootstrap draws of a group's pre and post values.

    >= 5 units: cluster bootstrap (resample whole units; captures within- and between-unit noise once).
    < 5 units: keep the units and resample weeks within each unit (block-free week bootstrap).
    """
    n, lp = num_pre.shape
    lq = num_post.shape[1]
    rows = np.arange(B)[:, None]
    if n >= UNIT_RESAMPLE_MIN:
        ui = rng.integers(0, n, (B, n))
        sums = [a.sum(1)[ui].sum(1) for a in (num_pre, den_pre, num_post, den_post)]
    else:
        u = np.arange(n)[None, :, None]
        ip = rng.integers(0, lp, (B, n, lp))
        iq = rng.integers(0, lq, (B, n, lq))
        sums = [num_pre[u, ip].sum((1, 2)), den_pre[u, ip].sum((1, 2)),
                num_post[u, iq].sum((1, 2)), den_post[u, iq].sum((1, 2))]
    del rows
    pre = sums[0] / np.maximum(sums[1], 1e-9) * scale
    post = sums[2] / np.maximum(sums[3], 1e-9) * scale
    return pre, post


def _val(num: np.ndarray, den: np.ndarray, scale: float) -> float:
    d = den.sum()
    return float(num.sum() / d * scale) if d > 0 else float("nan")


def estimate_effect(
    plan: OpsPlan,
    feed: Feed,
    iv: Intervention,
    upto: float,
    others: list[Intervention] | None = None,
    direction: str | None = None,
    seed: int = 0,
) -> EffectDetails:
    metric = iv.metric
    md = METRICS.get(metric)
    if md is None:
        return _inconclusive(iv, metric, f"'{metric}' is a study-level or unsupported metric: there is no "
                                         "comparable control group, so the effect cannot be separated from "
                                         "coincidence. Track the forecast instead.", "months")
    if iv.started_at is None:
        return _inconclusive(iv, metric, "Not started yet: the effect is estimated once the intervention has a "
                                         "start date and enough weeks of data after it.")
    start = plan.day_of(iv.started_at)
    sw = int(start // 7)
    end_w = int(upto // 7)
    post = (sw + 1, min(end_w, sw + 1 + POST_MAX_WEEKS))
    pre = (max(0, sw - PRE_MAX_WEEKS), sw)
    if post[1] - post[0] < POST_MIN_WEEKS:
        return _inconclusive(iv, metric, f"Too early: {max(0, post[1] - post[0])} complete week(s) of data "
                                         f"after the start; at least {POST_MIN_WEEKS} are needed.")
    if pre[1] - pre[0] < PRE_MIN_WEEKS:
        return _inconclusive(iv, metric, "Not enough history before the start for a baseline.")

    num, den, units = feed.series(metric, upto)
    uidx = {u: i for i, u in enumerate(units)}
    site_country = {s.id: s.country for s in plan.sites}
    if md.level == "site":
        treated = [u for u in iv.target_site_ids if u in uidx]
        unit_country = site_country
    else:
        treated = sorted({site_country[s] for s in iv.target_site_ids if s in site_country})
        unit_country = {c: c for c in units}
    region = {s.country: s.region for s in plan.sites}
    hemi = {s.country: s.hemisphere for s in plan.sites}

    def has_data(u: str) -> bool:
        i = uidx[u]
        return den[i, pre[0]: pre[1]].sum() > 0 and den[i, post[0]: post[1]].sum() > 0

    treated = [u for u in treated if has_data(u)]
    if not treated:
        return _inconclusive(iv, metric, "The targeted units have no data in both the before and after windows "
                                         f"for '{md.label}' (e.g. a site that did not exist before). Use a "
                                         "country-level metric such as regional_enrollment_rate_per_month.")
    # contamination: units touched by another intervention on the same metric during the windows
    busy: set[str] = set()
    for o in others or []:
        if o.id == iv.id or o.metric != metric or o.started_at is None:
            continue
        od = plan.day_of(o.started_at)
        if pre[0] * 7 - 28 <= od <= post[1] * 7:
            busy |= set(o.target_site_ids) if md.level == "site" else {
                site_country[s] for s in o.target_site_ids if s in site_country}
    cands = [u for u in units if u not in treated and u not in busy and has_data(u)]
    t_rows = [uidx[u] for u in treated]
    t_countries = {unit_country[u] for u in treated}
    tiers = [
        ("same country", lambda u: unit_country[u] in t_countries and md.level == "site"),
        ("same region", lambda u: region.get(unit_country[u]) in {region.get(c) for c in t_countries}),
        ("same hemisphere", lambda u: hemi.get(unit_country[u]) in {hemi.get(c) for c in t_countries}),
        ("all units", lambda u: True),
    ]
    k = K_SITE if md.level == "site" else K_COUNTRY

    # Similarity is judged on ALL history before the start (not just the analysis pre-window): matching on
    # a short noisy window selects units that were high by chance and then regress to the mean.
    def baseline(u: str) -> float:
        i = uidx[u]
        return _val(num[i, :sw], den[i, :sw], md.scale)

    base_hist = _val(num[t_rows, :sw], den[t_rows, :sw], md.scale)
    # closest tier first (same country, region, hemisphere, all), then nearest baseline; fill up to k units
    ranked = sorted(
        (next(i for i, (_, ok) in enumerate(tiers) if ok(u)), abs(baseline(u) - base_hist), u) for u in cands
    )[:k]
    if not ranked:
        return _inconclusive(iv, metric, "No untreated comparison units with data in both windows.")
    controls = [u for _, _, u in ranked]
    tier = tiers[max(r for r, _, _ in ranked)][0]
    if len(controls) < MIN_CONTROLS:
        tier += f" (only {len(controls)} available)"
    c_rows = [uidx[u] for u in controls]

    def windows(rows: list[int]) -> tuple[np.ndarray, ...]:
        return (num[rows, pre[0]: pre[1]], den[rows, pre[0]: pre[1]], num[rows, post[0]: post[1]],
                den[rows, post[0]: post[1]])

    tw, cw = windows(t_rows), windows(c_rows)
    t_pre, t_post = _val(tw[0], tw[1], md.scale), _val(tw[2], tw[3], md.scale)
    c_pre, c_post = _val(cw[0], cw[1], md.scale), _val(cw[2], cw[3], md.scale)
    tc, cc = t_post - t_pre, c_post - c_pre
    did = tc - cc
    rng = np.random.default_rng([seed, 4242, sum(ord(ch) * (i + 1) for i, ch in enumerate(iv.id))])
    tp, tq = _group_draws(*tw, md.scale, rng)
    cp, cq = _group_draws(*cw, md.scale, rng)
    d_tc, d_cc = tq - tp, cq - cp
    d_did = d_tc - d_cc
    lo, hi = (float(x) for x in np.quantile(d_did, [0.025, 0.975]))
    lo90, hi90 = (float(x) for x in np.quantile(d_did, [0.05, 0.95]))
    tlo, thi = (float(x) for x in np.quantile(d_tc, [0.025, 0.975]))
    clo, chi = (float(x) for x in np.quantile(d_cc, [0.025, 0.975]))
    p10, p50, p90 = (float(x) for x in np.quantile(d_did, [0.1, 0.5, 0.9]))

    better = direction or md.better
    sgn = 1.0 if better == "up" else -1.0
    excl0 = lo > 0 or hi < 0
    improve = sgn * did > 0
    tc_sig = tlo > 0 or thi < 0
    margin = max(0.5 * abs(t_pre), md.abs_floor)
    if excl0 and improve:
        verdict = "likely_worked"
    elif excl0:
        verdict = "no_effect"
    elif tc_sig and sgn * tc > 0 and sgn * cc > 0 and abs(cc) >= 0.5 * abs(tc):
        verdict = "likely_coincidence"
    elif max(abs(lo90), abs(hi90)) <= margin:  # equivalence (TOST at 5%: 90% interval inside ±margin)
        verdict = "no_effect"
    else:
        verdict = "inconclusive"

    u = _unit_word(md.unit, metric)
    t_label = ", ".join(treated)
    start_s = iv.started_at.date().isoformat()
    lines = [
        f"{md.label} ({md.description}) at the treated {md.level}(s) {t_label} went from {t_pre:.1f} to "
        f"{t_post:.1f}{u} ({tc:+.1f}); at {len(controls)} matched control {md.level}(s) ({tier}, nearest "
        f"baseline: {', '.join(controls)}) it went from {c_pre:.1f} to {c_post:.1f} ({cc:+.1f}).",
        f"Difference-in-differences: {did:+.1f}{u} (95% interval {lo:+.1f} to {hi:+.1f}; "
        f"{pre[1] - pre[0]} weeks before vs {post[1] - post[0]} weeks after the start on {start_s}).",
    ]
    reason = {
        "likely_worked": "The interval excludes zero in the intended direction: the change at the treated units "
                         "is larger than what the controls show, so it is unlikely to be coincidence.",
        "likely_coincidence": "The treated units did improve, but the controls improved by a similar amount over "
                              "the same weeks, so the improvement is most likely a shared trend (e.g. seasonal), "
                              "not the intervention.",
        "no_effect": ("The treated units got worse relative to the controls." if excl0 else
                      f"The interval includes zero and its 90% version ({lo90:+.1f} to {hi90:+.1f}) rules out an "
                      f"effect larger than ±{margin:.1f}{u} (equivalence test)."),
        "inconclusive": "The interval includes zero but is too wide to rule out a meaningful effect; more weeks "
                        "of data (or more treated units) are needed.",
    }[verdict]
    lines.append(reason)
    lines.append("Interpretation assumes parallel trends and no unmeasured concurrent changes; "
                 "this simulated observational estimate does not prove causation.")
    if base_hist and controls and abs(baseline(controls[0]) - base_hist) > 0.5 * abs(base_hist):
        lines.append("Note: no control had a similar baseline; the estimate relies on parallel trends.")
    est = EffectEstimate(
        intervention_id=iv.id, method="diff_in_diff",
        effect=MetricRange(p10=round(p10, 3), p50=round(p50, 3), p90=round(p90, 3), unit=md.unit),  # type: ignore[arg-type]
        treated_change=round(tc, 3), control_change=round(cc, 3), verdict=verdict,  # type: ignore[arg-type]
        explanation=" ".join(lines))
    return EffectDetails(
        est, metric, md.unit, md.level, better, treated, controls, tier, pre, post,
        {"treated_pre": t_pre, "treated_post": t_post, "control_pre": c_pre, "control_post": c_post,
         "did": did, "margin": margin},
        (lo, hi), (tlo, thi), (clo, chi))


def _unit_word(unit: str, metric: str) -> str:
    if metric.endswith("_percent"):
        return " per 100"
    return {"patients": " patients/month", "kits": " kits", "kg_co2e": " kg CO2e/month"}.get(unit, "")


def direction_for(alert_kind: str | None) -> str | None:
    return actions.DIRECTION.get(alert_kind or "")
