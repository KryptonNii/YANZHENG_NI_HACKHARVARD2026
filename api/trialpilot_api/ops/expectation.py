"""What a recommended action should achieve, saved when it is planned, and how the observed effect compares.

Prediction uses only the observed feed up to the clock and the labelled assumptions `ops.effect.*` and
`ops.cost.action.*` (plus the cost parameters the alerts already use). It never reads the simulator or its
withheld ground truth, and a test enforces that. A prediction that misses the observed effect therefore says
something about the assumptions, not about a model tuned to the answer.

Four actions are quantified: `enrollment_retraining` and `activate_backup` for a site's enrollment lag,
`supply_on_demand` and `transfer_excess` for a site's drug overstock. Every other recommended action is listed
as "not quantified" and is not ranked. The baseline arithmetic mirrors `Detector.enrollment` and
`Detector.overstock` with the same seeds, so "do nothing" equals the alert's own impact estimate.

The follow-up compares the observed difference-in-differences interval with the predicted range for the
weeks actually observed (the effect is diluted by the assumed start-up lag). The comparison is between two
model-based numbers on simulated data; it does not establish a clinical or real-world result.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from . import actions, geo
from ._contracts import Alert
from .detect import OVER_RATE_WEEKS, N
from .metrics import METRICS
from .params import OpsParams
from .plan import DAYS_PER_MONTH, OpsPlan

if TYPE_CHECKING:
    from ._contracts import Intervention
    from .effects import EffectDetails

MIN_REPLAN_WEEKS = 6  # observed post-start weeks before a shortfall against the prediction triggers a re-plan
MODEL_LABEL = "Planning model with assumed parameters. A prediction, not an observed result."
QUANTIFIED: dict[str, tuple[str, ...]] = {
    "enrollment_lag": ("enrollment_retraining", "activate_backup"),
    "drug_overstock": ("supply_on_demand", "transfer_excess"),
}
VERDICTS = ("insufficient_data", "inconclusive", "met", "exceeded", "partial", "not_met")


# ------------------------------------------------------------------------------------------ helpers
def _d(params: OpsParams, seed: int, pid: str, key: str) -> np.ndarray:
    """Parameter draws, seeded per (parameter, key) like `Detector.d`."""
    return params.draws(pid, N, seed=seed + (zlib.crc32(key.encode()) & 0xFFFF))


def _q(draws: np.ndarray, unit: str, nd: int = 3) -> dict:
    p10, p50, p90 = (float(x) for x in np.quantile(np.asarray(draws, dtype=float), [0.1, 0.5, 0.9]))
    return {"p10": round(p10, nd), "p50": round(p50, nd), "p90": round(p90, nd), "unit": unit}


def _mid(params: OpsParams, pid: str) -> float:
    return params.mid(pid)


@dataclass
class OptionSet:
    payload: dict
    draws: dict[str, dict[str, np.ndarray]] = field(default_factory=dict)  # code -> frozen sampling, never serialised


# ------------------------------------------------------------------------------------------ baselines
def _enrollment_baseline(plan: OpsPlan, feed, params: OpsParams, seed: int, upto: float, site_id: str) -> dict | None:
    s = plan.site(site_id)
    if s.backup or s.activation_day is None or int(upto // 7) < 1:
        return None
    cum = np.cumsum(feed.weekly("enrolled", upto), axis=1)
    n_now = int(cum[s.idx, -1])
    exposure_m = max(0.0, (upto - s.activation_day) / DAYS_PER_MONTH)
    rng = np.random.default_rng([seed, 11, s.idx])
    rate = rng.gamma(0.5 + n_now, 1.0 / max(exposure_m, 1e-6), N)  # posterior site rate, patients/month
    months_left = max(0.0, (plan.enrollment_end_day - upto) / DAYS_PER_MONTH)
    gap = np.clip(s.planned_rate_month - rate, 0, None)
    study_rate_day = max(sum(x.planned_rate_month for x in plan.sites) / DAYS_PER_MONTH, 1e-6)
    run_rate = _d(params, seed, "ops.cost.trial_run_rate", f"enr:{s.id}")
    delay_days = gap * months_left / study_rate_day
    return {"site": s, "n_now": n_now, "rate": rate, "gap": gap, "months_left": months_left,
            "study_rate_day": study_rate_day, "run_rate": run_rate, "delay_days": delay_days,
            "cost": delay_days / DAYS_PER_MONTH * run_rate}


def _overstock_baseline(plan: OpsPlan, feed, params: OpsParams, seed: int, upto: float, site_id: str) -> dict | None:
    s = plan.site(site_id)
    lots = feed.lots_on_hand(upto)
    site_lots = sorted(lots.get(s.idx, []), key=lambda x: x[2])
    kits = float(feed.per_site("dispensed", upto, upto - OVER_RATE_WEEKS * 7, field="kits")[s.idx])
    rng = np.random.default_rng([seed, 13, s.idx])
    rate = rng.gamma(0.5 + kits, 1.0 / OVER_RATE_WEEKS, N) / 7.0  # kits per day
    used = np.zeros(N)
    waste = np.zeros(N)
    for _, q, exp in site_lots:
        cap = np.clip(rate * max(exp - upto, 0.0) - used, 0, None)
        use = np.minimum(q, cap)
        waste += q - use
        used += use
    kit_cost = _d(params, seed, "ops.cost.drug_kit", f"over:{s.id}")
    return {"site": s, "on_hand": sum(q for _, q, _ in site_lots), "kits_8w": kits, "waste": waste,
            "kit_cost": kit_cost, "cost": waste * kit_cost}


# ------------------------------------------------------------------------------------------ options
def _prov(params: OpsParams, formula_id: str, description: str, inputs: dict, pids: list[str],
          extra: list[str]) -> dict:
    return params.provenance(formula_id, description, inputs, pids, extra).model_dump(mode="json")


def _quantified(*, code: str, text: str, label: str, md_id: str, targets: list[str], effect: np.ndarray,
                lag: np.ndarray, delay_saved_days: np.ndarray | None, avoided: np.ndarray, cost: np.ndarray,
                reasoning: list[str], provenance: dict, extra_warnings: list[str] | None = None) -> tuple[dict, dict]:
    md = METRICS[md_id]
    net = avoided - cost
    warnings = list(extra_warnings or [])
    if abs(float(np.median(effect))) < md.abs_floor:
        warnings.append(
            f"The predicted change is smaller than the smallest change the follow-up check can resolve "
            f"({md.abs_floor:g} {md.unit}); expect an inconclusive follow-up even if the action works.")
    public = {
        "action": text, "code": code, "label": label, "quantified": True, "reason": None,
        "metric": md.id, "metric_label": md.label, "metric_unit": md.unit, "better": md.better, "level": md.level,
        "target_site_ids": targets,
        "effect": _q(effect, md.unit, 4),
        "delay_saved_days": _q(delay_saved_days, "days", 2) if delay_saved_days is not None else None,
        "cost_avoided_usd": _q(avoided, "usd", 0), "action_cost_usd": _q(cost, "usd", 0),
        "net_usd": _q(net, "usd", 0), "lag_days": _q(lag, "days", 1),
        "warnings": warnings, "reasoning": reasoning, "assumptions": provenance["assumptions"],
        "provenance": provenance, "model_label": MODEL_LABEL,
    }
    return public, {"effect": np.asarray(effect, dtype=float), "lag": np.asarray(lag, dtype=float),
                    "net": np.asarray(net, dtype=float)}


def _unquantified(code: str, text: str, reason: str) -> dict:
    return {"action": text, "code": code, "label": text, "quantified": False, "reason": reason}


def _enrollment_options(plan, feed, params, seed, upto, alert: Alert, wanted: list[tuple[str, str]]):
    out: list[tuple[dict, dict | None]] = []
    base = _enrollment_baseline(plan, feed, params, seed, upto, alert.site_id)
    if base is None:
        reason = "The site has no complete week of enrollment data yet, so no prediction is possible."
        return [(_unquantified(c, t, reason), None) for c, t in wanted], None
    s = base["site"]
    gap, rate, ml = base["gap"], base["rate"], base["months_left"]
    lag = _d(params, seed, "ops.effect.action_lag_days", f"exp:lag:{s.id}")
    after = np.clip(ml - lag / DAYS_PER_MONTH, 0, None)  # months in which the action is assumed to work
    srd, run_rate = base["study_rate_day"], base["run_rate"]
    shortfall = gap * ml
    for code, text in wanted:
        if code == "enrollment_retraining":
            rec = _d(params, seed, "ops.effect.enrollment_retraining.gap_recovery", f"exp:retrain:{s.id}")
            saved = gap * rec * after
            cost = _d(params, seed, "ops.cost.action.enrollment_retraining", f"exp:cost:retrain:{s.id}")
            saved_days = saved / srd
            reasoning = [
                f"{s.name} has enrolled {base['n_now']} patients; its posterior median rate is "
                f"{float(np.median(rate)):.2f}/month against a planned {s.planned_rate_month:.2f}/month.",
                f"Retraining is assumed to close {_mid(params, 'ops.effect.enrollment_retraining.gap_recovery'):.0%} "
                f"of that gap (range {params.get('ops.effect.enrollment_retraining.gap_recovery').value_low:.0%} to "
                f"{params.get('ops.effect.enrollment_retraining.gap_recovery').value_high:.0%}) after "
                f"about {_mid(params, 'ops.effect.action_lag_days'):.0f} days.",
                "Time saved = patients recovered / the study's planned enrollment rate; value = days saved x "
                "trial run-rate, minus the action's cost.",
            ]
            prov = _prov(params, "ops.expectation.enrollment_retraining.v1",
                         "gap to planned rate x assumed recovery share x months after start-up lag",
                         {"site": s.id, "enrolled": base["n_now"], "planned_rate_month": round(s.planned_rate_month, 2),
                          "months_left": round(ml, 1)},
                         ["ops.effect.enrollment_retraining.gap_recovery", "ops.effect.action_lag_days",
                          "ops.cost.action.enrollment_retraining", "ops.cost.trial_run_rate"],
                         ["site rate ~ Gamma(0.5 + n, exposure) (Jeffreys prior)",
                          "no other site compensates, as in the alert's own impact estimate"])
            out.append(_quantified(
                code=code, text=text, label=text, md_id="enrollment_rate_per_month", targets=[s.id],
                effect=gap * rec, lag=lag, delay_saved_days=saved_days,
                avoided=saved_days / DAYS_PER_MONTH * run_rate, cost=cost, reasoning=reasoning, provenance=prov))
        elif code == "activate_backup":
            counts = feed.per_site("enrolled", upto)
            cands = sorted((b for b in plan.sites if b.backup and counts[b.idx] == 0), key=lambda b: b.id)
            same = [b for b in cands if b.country == s.country]
            pick = same[0] if same else (min(cands, key=lambda b: (geo.haversine_km(s.lat, s.lon, b.lat, b.lon), b.id))
                                         if cands else None)
            if pick is None:
                out.append((_unquantified(code, text, "The design has no unactivated backup site."), None))
                continue
            active = [x.planned_rate_month for x in plan.sites if not x.backup]
            mean_plan = float(np.mean(active)) if active else 0.0
            share = _d(params, seed, "ops.effect.backup_site.rate_share_of_plan", f"exp:backup:{s.id}")
            rate_b = share * mean_plan
            saved = np.minimum(shortfall, rate_b * after)
            saved_days = saved / srd
            cost = _d(params, seed, "ops.cost.action.backup_site_activation", f"exp:cost:backup:{s.id}")
            where = "in the same country" if pick.country == s.country else f"in {pick.country}, the nearest available"
            reasoning = [
                f"Backup site {pick.id} ({pick.city}, {pick.country}) is {where}.",
                f"It is assumed to enroll {_mid(params, 'ops.effect.backup_site.rate_share_of_plan'):.0%} of the mean "
                f"planned site rate ({mean_plan:.2f}/month) after about {_mid(params, 'ops.effect.action_lag_days'):.0f} "
                "days, and its patients offset the lagging site's shortfall.",
                "Days saved cannot exceed the shortfall: the study is not assumed to finish before plan.",
            ]
            prov = _prov(params, "ops.expectation.activate_backup.v1",
                         "backup site rate x months after start-up lag, capped at the site's shortfall",
                         {"lagging_site": s.id, "backup_site": pick.id, "mean_planned_rate_month": round(mean_plan, 2),
                          "months_left": round(ml, 1)},
                         ["ops.effect.backup_site.rate_share_of_plan", "ops.effect.action_lag_days",
                          "ops.cost.action.backup_site_activation", "ops.cost.trial_run_rate"],
                         ["no other site compensates, as in the alert's own impact estimate"])
            out.append(_quantified(
                code=code, text=text, label=f"Activate backup site {pick.id} ({pick.country})",
                md_id="regional_enrollment_rate_per_month", targets=[pick.id], effect=rate_b, lag=lag,
                delay_saved_days=saved_days, avoided=saved_days / DAYS_PER_MONTH * run_rate, cost=cost,
                reasoning=reasoning, provenance=prov))
    baseline = {"delay_days": _q(base["delay_days"], "days", 2), "cost_usd": _q(base["cost"], "usd", 0),
                "description": "Doing nothing, as in the alert's own impact estimate."}
    return out, baseline


def _overstock_options(plan, feed, params, seed, upto, alert: Alert, wanted: list[tuple[str, str]]):
    out: list[tuple[dict, dict | None]] = []
    base = _overstock_baseline(plan, feed, params, seed, upto, alert.site_id)
    s, waste, kit_cost = base["site"], base["waste"], base["kit_cost"]
    lag = _d(params, seed, "ops.effect.supply_action_lag_days", f"exp:lag:{s.id}")
    specs = {
        "transfer_excess": ("ops.effect.excess_kit_return_share", "ops.cost.action.kit_transfer",
                            "one-off transfer of excess kits to the regional depot"),
        "supply_on_demand": ("ops.effect.on_demand_waste_avoided_share", "ops.cost.action.on_demand_switch",
                             "switch to on-demand resupply and return excess kits"),
    }
    for code, text in wanted:
        share_id, cost_id, what = specs[code]
        share = _d(params, seed, share_id, f"exp:{code}:{s.id}")
        kits = share * waste
        cost = _d(params, seed, cost_id, f"exp:cost:{code}:{s.id}")
        reasoning = [
            f"{s.name} holds {base['on_hand']:.0f} kits and dispensed {base['kits_8w']:.0f} in the last "
            f"{OVER_RATE_WEEKS} weeks; the median projection is {float(np.median(waste)):.1f} kits expiring unused.",
            f"A {what} is assumed to avoid {_mid(params, share_id):.0%} of them (range "
            f"{params.get(share_id).value_low:.0%} to {params.get(share_id).value_high:.0%}).",
            "Value = kits avoided x cost per kit, minus the action's cost. Carbon and any dosing risk are not included.",
        ]
        prov = _prov(params, f"ops.expectation.{code}.v1", "projected expiring kits x assumed avoided share x kit cost",
                     {"site": s.id, "kits_on_hand": round(base["on_hand"], 1),
                      "waste_kits_p50": round(float(np.median(waste)), 1)},
                     [share_id, cost_id, "ops.cost.drug_kit", "ops.effect.supply_action_lag_days"],
                     ["dispensing rate ~ Gamma(0.5 + kits, weeks) (Jeffreys prior), constant until expiry"])
        warn = ["Little projected waste: the expected value is small."] if float(np.median(waste)) < 1 else None
        out.append(_quantified(
            code=code, text=text, label=text, md_id="kits_on_hand", targets=[s.id], effect=-kits, lag=lag,
            delay_saved_days=None, avoided=kits * kit_cost, cost=cost, reasoning=reasoning, provenance=prov,
            extra_warnings=warn))
    baseline = {"delay_days": None, "cost_usd": _q(base["cost"], "usd", 0),
                "description": "Doing nothing, as in the alert's own impact estimate."}
    return out, baseline


def options_for_alert(plan: OpsPlan, feed, params: OpsParams, seed: int, upto: float, alert: Alert) -> OptionSet:
    """Predict each recommended action for one alert and rank the quantified ones by net value (P50)."""
    payload: dict = {"alert_id": alert.id, "alert_kind": alert.kind, "computed_at_day": round(upto, 3),
                     "ranked_by": "net_usd P50 (cost avoided minus action cost)", "model_label": MODEL_LABEL,
                     "baseline": None, "items": [], "simulated": True}
    texts = list(alert.recommended_actions)
    codes = [actions.action_code(t) for t in texts]
    supported = QUANTIFIED.get(alert.kind, ())
    wanted = [(c, t) for c, t in zip(codes, texts, strict=True) if c in supported]
    quantified: list[tuple[dict, dict | None]] = []
    if wanted and alert.site_id:
        builder = _enrollment_options if alert.kind == "enrollment_lag" else _overstock_options
        quantified, payload["baseline"] = builder(plan, feed, params, seed, upto, alert, wanted)
    done = {pub["code"] for pub, _ in quantified}
    ranked = sorted((q for q in quantified if q[0]["quantified"]), key=lambda q: -q[0]["net_usd"]["p50"])
    items = [pub for pub, _ in ranked]
    draws: dict[str, dict] = {}
    for i, (pub, drw) in enumerate(ranked, start=1):
        pub["rank"] = i
        draws[pub["code"]] = drw or {}
    items += [pub for pub, _ in quantified if not pub["quantified"]]
    for c, t in zip(codes, texts, strict=True):
        if c in done:
            continue
        if not alert.site_id:
            reason = "A study-level alert has no target site; choose sites before the model can predict."
        elif c in supported:
            continue
        else:
            reason = "No quantitative model for this action; it is listed but not ranked."
        items.append(_unquantified(c, t, reason))
    payload["items"] = items
    top = next((i for i in items if i.get("rank") == 1), None)
    payload["best_net_positive"] = bool(top and top["net_usd"]["p50"] > 0)
    if top is not None and not payload["best_net_positive"]:
        payload["note"] = "No quantified option has a positive expected net value under the assumed parameters."
    return OptionSet(payload, draws)


def freeze(option: dict, alert_id: str, upto: float, plan: OpsPlan) -> dict:
    """The prediction as it stood when the action was planned. Stored once and never recomputed."""
    return {**{k: v for k, v in option.items() if k != "rank"}, "alert_id": alert_id,
            "computed_at_day": round(upto, 3), "computed_at": plan.date(upto).date().isoformat(), "frozen": True,
            "rank_when_planned": option.get("rank")}


# ------------------------------------------------------------------------------------------ follow-up
def window_factor(lag_days: np.ndarray, start_day: float, weeks: tuple[int, int]) -> np.ndarray:
    """Share of the full predicted effect present on average over the observed post-start weeks."""
    a, b = weeks
    if b <= a:
        return np.zeros_like(lag_days, dtype=float)
    ends = (np.arange(a, b) + 1) * 7.0
    live = np.clip((ends[None, :] - (start_day + lag_days[:, None])) / 7.0, 0.0, 1.0)
    return live.mean(axis=1)


def _fmt(x: float) -> str:
    return f"{x:+.2f}"


def reconcile(plan: OpsPlan, iv: Intervention, exp: dict, draws: dict, details: EffectDetails) -> dict:
    """Compare the observed effect interval with the frozen prediction, over the weeks observed so far."""
    md = METRICS[exp["metric"]]
    est = details.estimate
    base = {"metric": md.id, "metric_label": md.label, "unit": md.unit, "better": md.better,
            "alert_id": exp["alert_id"], "model_label": MODEL_LABEL, "needs_replan": False,
            "replan_min_weeks": MIN_REPLAN_WEEKS, "predicted": None, "observed": None, "post_weeks": 0,
            "share_of_effect_in_window": None,
            "basis": f"Compared on {md.label.lower()}. The predicted days and dollars follow from the same model "
                     "and are not observed separately."}
    a, b = details.post_weeks
    if iv.started_at is None:
        return {**base, "verdict": "insufficient_data",
                "explanation": "Not started yet. The prediction is saved; it is compared with data after the start."}
    eff = est.effect
    if eff.p50 is None or details.ci95 is None or b - a < 1:
        return {**base, "verdict": "insufficient_data", "post_weeks": max(0, b - a), "explanation": est.explanation}
    factor = window_factor(draws["lag"], plan.day_of(iv.started_at), (a, b))
    pred = draws["effect"] * factor
    pred_q = _q(pred, md.unit, 3)
    lo_c, hi_c = details.ci95
    observed = {"p10": eff.p10, "p50": eff.p50, "p90": eff.p90, "unit": md.unit,
                "ci95": [round(float(lo_c), 3), round(float(hi_c), 3)]}
    s = 1.0 if md.better == "up" else -1.0
    o_lo, o_hi = sorted((s * float(lo_c), s * float(hi_c)))
    p_lo, _, p_hi = (float(x) for x in np.quantile(s * pred, [0.1, 0.5, 0.9]))
    weeks = b - a
    shown = (f"predicted {_fmt(pred_q['p10'])} to {_fmt(pred_q['p90'])} {md.unit} (median {_fmt(pred_q['p50'])}) "
             f"over the {weeks} observed weeks; observed {_fmt(eff.p50)} (95% interval {_fmt(float(lo_c))} to "
             f"{_fmt(float(hi_c))})")
    if o_lo > p_hi:
        verdict, why = "exceeded", "The observed effect is larger than the predicted range."
    elif o_lo > 0 and o_hi >= p_lo:
        verdict, why = "met", "The observed effect is real and consistent with the predicted range."
    elif o_lo > 0:
        verdict, why = "partial", "The action had a real effect, but smaller than predicted."
    elif o_hi < p_lo:
        verdict, why = "not_met", ("The observed interval rules out the predicted effect and cannot be told apart "
                                   "from no effect." if o_lo <= 0 else "The observed effect is below the predicted range.")
    else:
        verdict, why = "inconclusive", "The observed interval is too wide to tell whether the prediction held."
    replan = verdict in ("partial", "not_met") and weeks >= MIN_REPLAN_WEEKS
    note = " Re-plan: this action is below its predicted effect." if replan else ""
    return {**base, "verdict": verdict, "predicted": pred_q, "observed": observed, "post_weeks": weeks,
            "share_of_effect_in_window": round(float(np.mean(factor)), 3), "needs_replan": replan,
            "explanation": f"{why} {shown[0].upper() + shown[1:]}.{note}"}
