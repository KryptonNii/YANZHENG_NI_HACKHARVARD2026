"""Drug supply simulation: upfront vs on-demand site supply (owner: A3). Pure functions, no I/O.

Model (full write-up: docs/model_forecast.md)
---------------------------------------------
For each forecast draw we sample patients (site + randomisation week) from the recruitment draws of
`forecast.forecast`, give each the protocol's dispensing schedule (dropouts stop early) and simulate
every site's inventory week by week:

* arrivals (initial stock at activation, resupplies after the lead time) → FIFO expiry → dispensing →
  reorder decision. A shipment expires `shelf life` after it reaches the site; with a constant shelf
  life FIFO-by-arrival = FIFO-by-expiry, so the kits expiring at week t are
  max(0, cumulative arrivals up to t − shelf − cumulative removals) (scheduled forward, no lot lists);
* demand a site cannot meet from stock is a STOCKOUT and is served by an emergency shipment;
* the strategies differ ONLY in the initial allocation at site activation:
  `upfront` = the site's planned patients' full course × (1 + overage);
  `on_demand` = projected need for the next k weeks + safety stock;
* both then share one IRT resupply rule: when usable stock + in-transit < projected need for the next
  k weeks + safety stock, ship up to (order-up-to factor × projected need + safety stock).
  Projection = scheduled dispensings of randomised patients (the IRT does not know who will drop out)
  + planned recruitment rate × new-patient kits (the planner does not know the realised site rate);
* usable stock excludes kits that expire before a resupply could arrive (lead time);
* kits left at sites or in transit when the trial ends are destroyed: waste = expired + destroyed.

Conservation per draw: produced = dispensed + expired + destroyed at close (tested).
Supply runs on the first `draws` forecast draws (default 500 = SUPPLY_DRAWS) to stay fast; very large
trials use fewer draws (budget on simulated dispensings) and say so in the result.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

from ._contracts import Levers, MetricRange, Parameter, ProvenanceItem, TrialDesign
from .forecast import (
    WEEKS_PER_MONTH,
    FloatArray,
    ForecastDraws,
    ForecastResult,
    IntArray,
    ParameterResolver,
    _assumed,
    _fmt,
    _stream,
    draw_parameter,
    metric_range,
)
from .levers import DISPENSING_MARKERS

__all__ = [
    "SUPPLY_DEFAULTS",
    "SUPPLY_DRAWS",
    "SupplyDraws",
    "SupplyResult",
    "compare_strategies",
    "dispensing_offsets_weeks",
    "simulate_supply",
]

SUPPLY_DRAWS = 500  # supply runs on the first 500 forecast draws (performance budget, documented)
_MIN_DRAWS = 100  # never fewer, even for very large trials
# Compute budget per call, in simulated (site × week) cells + ½ × dispensing events. Keeps one call at
# roughly 0.1–0.3 s on a laptop; larger trials run on fewer draws (never < _MIN_DRAWS) and say so.
_WORK_BUDGET = 6_000_000
_CHUNK_SITE_DRAWS = 16_384  # (draw, site) pairs simulated together; bounds memory to ~100 MB
Strategy = Literal["upfront", "on_demand"]
BoolArray = np.ndarray[Any, np.dtype[np.bool_]]

SUPPLY_DEFAULTS: dict[str, Parameter] = {
    p.id: p
    for p in (
        _assumed(
            "supply.kits_per_dispensing_visit", "Kits dispensed per dispensing visit",
            1.0, 1.0, 1.0, "kits/visit",
            "One kit per dispensing visit; replace with the protocol's kit configuration.",
        ),
        _assumed(
            "supply.dispensing_interval_weeks", "Weeks between dispensings (no visit schedule)",
            4.0, 4.0, 4.0, "weeks",
            "Only used when the design has no visit schedule.",
        ),
        _assumed(
            "supply.overage_share.upfront", "Upfront strategy: kits shipped above planned need",
            0.5, 0.75, 1.0, "share",
            "Calibration assumption. ZS (2025) reports teams 'routinely plan for 150% to 200% "
            "overage'; read conservatively as shipping 1.5–2× planned need. With this range the "
            "simulated upfront waste lands near the industry-reported median of 50% of IMP kits "
            "(IQVIA 2024) — see docs/model_forecast.md, Calibration.",
        ),
        _assumed(
            "supply.site_safety_stock_kits", "Safety stock kept at each active site",
            4.0, 4.0, 4.0, "kits/site",
            "Policy setting (a decision, so only the mid value is used). Placeholder.",
        ),
        _assumed(
            "supply.resupply_lead_time_weeks", "Depot-to-site resupply lead time",
            1.0, 1.0, 2.0, "weeks",
            "Placeholder for an international courier lead time; replace with depot data.",
        ),
        _assumed(
            "supply.on_demand.cover_weeks", "On-demand: weeks of projected need that trigger resupply",
            6.0, 6.0, 6.0, "weeks",
            "Policy setting (only the mid value is used). Placeholder IRT trigger window.",
        ),
        _assumed(
            "supply.order_up_to_factor", "Resupply quantity: multiple of the k-week projected need",
            2.0, 2.0, 2.0, "ratio",
            "Policy setting (only the mid value is used): a resupply covers 2 trigger windows so "
            "sites are not shipped to every week.",
        ),
        _assumed(
            "supply.shelf_life_months", "Remaining shelf life of a kit when it reaches the site",
            12.0, 18.0, 24.0, "months",
            "Placeholder; product-specific ids supply.shelf_life_months.<drug_type> take precedence.",
        ),
        _assumed(
            "supply.stockout_warning_threshold", "Warn when stockout probability exceeds",
            0.05, 0.05, 0.05, "share",
            "Policy setting: share of simulated trials with any site stockout that triggers a warning.",
        ),
    )
}


@dataclass(frozen=True)
class SupplyDraws:
    """Per-draw totals over all sites (length = draws used); for A2's per-draw carbon/cost."""

    kits_needed: IntArray  # dispensed to patients (= demand; stockouts are served by emergency kits)
    kits_produced: IntArray  # shipped to sites, incl. emergency shipments
    kits_expired: IntArray
    kits_destroyed_at_close: IntArray  # left at sites / in transit when the trial ends
    shipments: IntArray  # depot → site shipments, incl. emergency ones
    emergency_shipments: IntArray
    stockout: BoolArray  # any site short at any time

    @property
    def kits_wasted(self) -> IntArray:
        return self.kits_expired + self.kits_destroyed_at_close


@dataclass
class SupplyResult:
    kits_needed: MetricRange
    kits_produced: MetricRange
    kits_wasted: MetricRange
    waste_share: MetricRange  # percent
    shipments: MetricRange  # count → A2 uses for shipping carbon/cost (unit "count", see HANDOFF)
    stockout_probability: float  # share of draws with any stockout at any site
    # --- A3 extensions (additive) ---
    strategy: Strategy = "upfront"
    kits_expired: MetricRange | None = None
    kits_destroyed_at_close: MetricRange | None = None
    emergency_shipments: MetricRange | None = None
    draws_used: int = 0
    warnings: list[str] = field(default_factory=list)
    provenance: list[ProvenanceItem] = field(default_factory=list)
    per_draw: SupplyDraws | None = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        def dump(m: MetricRange | None) -> dict[str, Any] | None:
            return m.model_dump() if m is not None else None

        return {
            "strategy": self.strategy,
            "kits_needed": dump(self.kits_needed),
            "kits_produced": dump(self.kits_produced),
            "kits_wasted": dump(self.kits_wasted),
            "kits_expired": dump(self.kits_expired),
            "kits_destroyed_at_close": dump(self.kits_destroyed_at_close),
            "waste_share": dump(self.waste_share),
            "shipments": dump(self.shipments),
            "emergency_shipments": dump(self.emergency_shipments),
            "stockout_probability": self.stockout_probability,
            "draws_used": self.draws_used,
            "warnings": list(self.warnings),
            "provenance": [p.model_dump() for p in self.provenance],
        }


def _count_range(x: IntArray) -> MetricRange:
    """MetricRange for a count of shipments. The contract's unit literal has no 'count' (proposal in
    handoffs/A3_CONTRACT_CHANGES.md), so this is built without validation and labelled honestly."""
    p10, p50, p90 = np.percentile(x.astype(np.float64), [10.0, 50.0, 90.0])
    return MetricRange.model_construct(p10=float(p10), p50=float(p50), p90=float(p90), unit="count")


def _kits(x: IntArray) -> MetricRange:
    return metric_range(x.astype(np.float64), "kits")


# ---------------------------------------------------------------------------------------------
# Dispensing schedule
# ---------------------------------------------------------------------------------------------


def _is_dispensing(code: str) -> bool:
    c = code.lower()
    return any(h in c for h in DISPENSING_MARKERS)  # same detection as A2's engine


def dispensing_offsets_weeks(
    design: TrialDesign, res: ParameterResolver, followup_weeks: float, notes: list[str]
) -> IntArray:
    """Weeks after randomisation at which kits are dispensed (sorted, unique, first = 0 or later)."""
    on_study = sorted((v for v in design.visits if v.week >= 0), key=lambda v: v.week)
    if on_study:
        base = on_study[0].week
        disp = [v for v in on_study if any(_is_dispensing(p.code) for p in v.procedures)]
        if not disp:
            disp = on_study[:-1] if len(on_study) > 1 else on_study
            notes.append(
                "No dispensing procedure found in the visit schedule; assumed kits are dispensed at "
                f"every on-study visit except the last ({len(disp)} visits)."
            )
        weeks = sorted({int(round(v.week - base)) for v in disp})
        return np.asarray(weeks, dtype=np.int64)
    p = res.get("supply.dispensing_interval_weeks")
    step = max(1, int(round(p.value_mid)))
    notes.append(
        f"No visit schedule; assumed a dispensing every {step} weeks over "
        f"{followup_weeks:.0f} weeks of follow-up ('{p.id}')."
    )
    return np.arange(0, max(int(followup_weeks), 1), step, dtype=np.int64)


# ---------------------------------------------------------------------------------------------
# Patients
# ---------------------------------------------------------------------------------------------


def _sample_patients(fd: ForecastDraws, rng: np.random.Generator) -> tuple[IntArray, FloatArray]:
    """Every patient of every draw as (flat draw·site index, randomisation month), sorted by index.

    Conditional on n arrivals before t_full, arrivals are iid: site ∝ λᵢ·(t_full − startᵢ)⁺
    (multinomial), time uniform on [startᵢ, t_full] — an exact sample of the capped process.
    """
    d, s = fd.rates.shape
    w = fd.rates * np.clip(fd.t_full[:, None] - fd.accrual_start, 0.0, None)
    tot = w.sum(axis=1, keepdims=True)
    pvals = np.where(tot > 0, w / np.where(tot > 0, tot, 1.0), 1.0 / s)
    n_new = np.where(tot[:, 0] > 0, fd.new_patients, 0)
    counts = rng.multinomial(n_new, pvals)
    flat_new = np.repeat(np.arange(d * s), counts.ravel())
    lo = fd.accrual_start.ravel()[flat_new]
    t_new = lo + rng.random(flat_new.size) * (fd.t_full[flat_new // s] - lo)

    flat_fix = np.repeat(np.arange(d * s), fd.fixed_counts.ravel())
    hi = fd.fixed_until[flat_fix // s]
    lo_f = np.minimum(fd.activation.ravel()[flat_fix], hi)
    t_fix = lo_f + rng.random(flat_fix.size) * (hi - lo_f)

    flat = np.concatenate([flat_new, flat_fix])
    order = np.argsort(flat, kind="stable")
    return flat[order].astype(np.int64), np.concatenate([t_new, t_fix])[order]


# ---------------------------------------------------------------------------------------------
# Inventory simulation (one chunk of draws, all sites, weekly steps)
# ---------------------------------------------------------------------------------------------


@dataclass
class _Policy:
    strategy: Strategy
    offsets: IntArray  # dispensing weeks after randomisation
    kits_per_visit: IntArray  # (D,)
    overage: FloatArray  # (D,)
    lead_weeks: IntArray  # (D,) ≥ 1
    shelf_weeks: IntArray  # (D,) ≥ 1
    safety: int
    cover_weeks: int
    order_factor: float
    planned_patients: FloatArray  # (S,) planner's expected patients per site over the trial


def _event_groups(weeks: IntArray, n_weeks: int) -> tuple[IntArray, IntArray]:
    """Indices sorted by week + pointer array: indices for week t are order[ptr[t]:ptr[t+1]]."""
    order = np.argsort(weeks, kind="stable")
    ptr = np.searchsorted(weeks[order], np.arange(n_weeks + 1))
    return order.astype(np.int64), ptr.astype(np.int64)


def _simulate_chunk(
    fd: ForecastDraws, pol: _Policy, draw_lo: int, draw_hi: int, p_ds: IntArray, p_week: IntArray,
    p_visits: IntArray,
) -> dict[str, IntArray]:
    """Weekly inventory for draws [draw_lo, draw_hi) × all sites. p_* are this chunk's patients:
    local (draw, site) column, randomisation week, dispensing visits received (dropouts < V)."""
    s = fd.rates.shape[1]
    dc = draw_hi - draw_lo
    ds = dc * s
    col = np.arange(ds)
    gdraw = draw_lo + col // s
    site = col % s
    offs = pol.offsets
    n_vis = len(offs)
    k = pol.cover_weeks

    act_w = np.floor(fd.activation[gdraw, site] * WEEKS_PER_MONTH).astype(np.int64)
    close_w = np.ceil(fd.enrollment_closed_at[gdraw] * WEEKS_PER_MONTH).astype(np.int64)
    last = int(p_week.max() + offs[-1]) if p_week.size else 0
    horizon = max(last, int(act_w.max())) + 1
    rows = horizon + k + 1
    kits = pol.kits_per_visit[gdraw]

    # --- dispensing events: patient (cell, randomisation week e) gets kits at b = e + offset -------
    # Flat bin index = week · ds + cell (int32: rows · ds stays far below 2³¹).
    base = (p_week * ds + p_ds).astype(np.int32)
    full = p_visits >= n_vis
    j_drop = p_visits[~full]
    vis_drop = np.arange(int(j_drop.sum())) - np.repeat(np.cumsum(j_drop) - j_drop, j_drop)
    base_drop = np.repeat(base[~full], j_drop)
    off_ds = (offs * ds).astype(np.int32)
    # The IRT knows a dispensing at week b from week max(e, b − k) — the patient is randomised and the
    # visit is inside the k-week window — until b: a +1/−1 range starting at b − min(offset, k).
    start_ds = (off_ds - np.minimum(offs, k) * ds).astype(np.int32)
    b_idx = np.concatenate([(base[full, None] + off_ds[None, :]).ravel(), base_drop + off_ds[vis_drop]])
    s_idx = np.concatenate(
        [(base[full, None] + start_ds[None, :]).ravel(), base_drop + start_ds[vis_drop]]
    )
    del base, base_drop, vis_drop

    # Phantom visits: a patient who will drop out is still expected (within the window) until the
    # first visit they miss — the IRT cannot know the future dropout.
    drop = ~full
    e_d, j_d, c_d = p_week[drop], p_visits[drop], p_ds[drop]
    b_miss = e_d + offs[np.minimum(j_d, n_vis - 1)]
    ph_lo: list[IntArray] = []
    ph_hi: list[IntArray] = []
    for m in range(n_vis):
        v = j_d + m
        b_v = e_d + offs[np.minimum(v, n_vis - 1)]
        valid = (v < n_vis) & ((b_v - b_miss) < k)
        if not valid.any():
            break
        ph_lo.append(np.maximum(e_d, b_v - k)[valid] * ds + c_d[valid])
        ph_hi.append(b_miss[valid] * ds + c_d[valid])

    size = rows * ds
    plus = [s_idx, *ph_lo]
    minus = [b_idx, *ph_hi]
    n_plus = sum(a.size for a in plus)
    weights = np.ones(n_plus + sum(a.size for a in minus))
    weights[n_plus:] = -1.0
    diff = np.bincount(np.concatenate(plus + minus), weights=weights, minlength=size)
    known = np.cumsum(diff.reshape(rows, ds)[:horizon], axis=0).astype(np.int32)  # exact: small ints
    dem = np.bincount(b_idx, minlength=size).reshape(rows, ds).astype(np.int32)
    del diff, weights, plus, minus, s_idx, b_idx
    if np.any(kits != 1):
        dem *= kits[None, :].astype(np.int32)
        known *= kits[None, :].astype(np.int32)
    total_dem = np.bincount(p_ds, weights=p_visits, minlength=ds).astype(np.int64) * kits
    last_dem_w = np.full(ds, -1, dtype=np.int64)
    np.maximum.at(last_dem_w, p_ds, p_week + offs[np.maximum(p_visits, 1) - 1])

    # --- policy -----------------------------------------------------------------------------------
    rate_week = fd.planned_rate[site] / WEEKS_PER_MONTH
    new_kits_k = rate_week * kits * float(sum(k - o for o in offs if o < k))
    exp_new = np.rint(new_kits_k).astype(np.int32)  # expected new-patient kits, whole kits
    if pol.strategy == "upfront":
        q0f = np.ceil(pol.planned_patients[site] * kits * n_vis * (1.0 + pol.overage[gdraw]))
    else:
        q0f = np.ceil(new_kits_k + pol.safety)
    q0 = q0f.astype(np.int32)
    end_w = np.maximum(close_w, last_dem_w)  # in service while act_w <= t < end_w
    lead = pol.lead_weeks[gdraw]
    shelf = pol.shelf_weeks[gdraw]
    lead_values = [int(v) for v in np.unique(lead)]
    exp_len = int(shelf.max()) + 1
    look = int(lead.max())
    open_order, open_ptr = _event_groups(act_w, horizon)
    closing_cells = np.flatnonzero(act_w < close_w)
    close_order, close_ptr = _event_groups(close_w[closing_cells], horizon)
    ending_cells = np.flatnonzero(act_w < end_w)
    end_order, end_ptr = _event_groups(end_w[ending_cells], horizon)

    in_transit: dict[int, list[tuple[IntArray, IntArray]]] = {}  # arrival week → (cells, kits)
    exp_due = np.zeros((exp_len, ds), dtype=np.int32)  # FIFO expiry thresholds, by due week
    soon_thr = np.zeros(ds, dtype=np.int32)  # latest threshold due within the lead time
    stock = np.zeros(ds, dtype=np.int32)
    position = np.zeros(ds, dtype=np.int32)  # stock + in transit
    arrived = np.zeros(ds, dtype=np.int32)  # cumulative arrivals (incl. emergency kits)
    exp_part = np.zeros(ds, dtype=np.int32)
    safety_part = np.zeros(ds, dtype=np.int32)
    trig_base = np.zeros(ds, dtype=np.int32)
    expired = np.zeros(ds, dtype=np.int64)
    produced = np.zeros(ds, dtype=np.int64)
    shipments = np.zeros(ds, dtype=np.int64)
    emergency = np.zeros(ds, dtype=np.int64)
    take = np.empty(ds, dtype=np.int32)
    unmet = np.empty(ds, dtype=np.int32)
    trig = np.empty(ds, dtype=np.int32)
    below = np.empty(ds, dtype=bool)
    has_soon = np.empty(ds, dtype=bool)
    safety = np.int32(pol.safety)

    def schedule_expiry(idx: IntArray, t: int) -> None:
        exp_due[(t + shelf[idx]) % exp_len, idx] = arrived[idx]

    for t in range(horizon):
        # 1. arrivals: resupplies in transit, then the initial stock of sites opening this week
        for nz, q in in_transit.pop(t, ()):
            stock[nz] += q
            arrived[nz] += q
            schedule_expiry(nz, t)
        idx = open_order[open_ptr[t] : open_ptr[t + 1]]
        if idx.size:
            q = q0[idx]
            stock[idx] += q
            position[idx] += q
            arrived[idx] += q
            produced[idx] += q
            shipments[idx] += q > 0
            schedule_expiry(idx, t)
            exp_part[idx] = np.where(t < close_w[idx], exp_new[idx], 0)
            safety_part[idx] = np.where(t < end_w[idx], safety, 0)
            trig_base[idx] = exp_part[idx] + safety_part[idx]
        idx = closing_cells[close_order[close_ptr[t] : close_ptr[t + 1]]]
        if idx.size:
            exp_part[idx] = 0
            trig_base[idx] = safety_part[idx]
        idx = ending_cells[end_order[end_ptr[t] : end_ptr[t + 1]]]
        if idx.size:
            safety_part[idx] = 0
            trig_base[idx] = exp_part[idx]

        # 2. FIFO expiry of shipments that reached the site `shelf` weeks ago
        eslot = t % exp_len
        nz = np.flatnonzero(exp_due[eslot])
        if nz.size:
            thr = exp_due[eslot, nz]
            exp_due[eslot, nz] = 0
            x = np.maximum(thr - (arrived[nz] - stock[nz]), 0)
            stock[nz] -= x
            position[nz] -= x
            expired[nz] += x
            soon_thr[nz] = np.where(soon_thr[nz] <= thr, 0, soon_thr[nz])
        lslot = (t + look) % exp_len
        nz = np.flatnonzero(exp_due[lslot])
        if nz.size:
            soon_thr[nz] = np.maximum(soon_thr[nz], exp_due[lslot, nz])

        # 3. dispensing; a shortfall is a stockout served by an emergency shipment
        d_t = dem[t]
        np.minimum(d_t, stock, out=take)
        stock -= take
        position -= take
        np.subtract(d_t, take, out=unmet)
        nz = np.flatnonzero(unmet)
        if nz.size:
            u = unmet[nz]
            produced[nz] += u
            arrived[nz] += u  # arrive and are dispensed in the same week
            emergency[nz] += 1
            shipments[nz] += 1

        # 4. resupply when usable stock + in transit < projected need (t, t+k] + safety stock
        np.add(known[t], trig_base, out=trig)
        np.less(position, trig, out=below)
        np.greater(soon_thr, 0, out=has_soon)
        below |= has_soon  # kits about to expire: check exactly below
        cand = np.flatnonzero(below)
        if cand.size:
            usable = position[cand] - np.maximum(soon_thr[cand] - (arrived[cand] - stock[cand]), 0)
            need = usable < trig[cand]
            o = cand[need]
            if o.size:
                projected = known[t][o] + exp_part[o]
                q = np.maximum(
                    np.ceil(pol.order_factor * projected + safety_part[o] - usable[need]), 1
                ).astype(np.int32)
                if len(lead_values) == 1:
                    in_transit.setdefault(t + lead_values[0], []).append((o, q))
                else:
                    lo_ = lead[o]
                    for lv in lead_values:
                        sel = lo_ == lv
                        if sel.any():
                            in_transit.setdefault(t + lv, []).append((o[sel], q[sel]))
                position[o] += q
                produced[o] += q
                shipments[o] += 1

    def per_draw(x: IntArray) -> IntArray:
        return np.asarray(x.reshape(dc, s).sum(axis=1), dtype=np.int64)

    return {
        "needed": per_draw(total_dem),
        "produced": per_draw(produced),
        "expired": per_draw(expired),
        "leftover": per_draw(position.astype(np.int64)),
        "shipments": per_draw(shipments),
        "emergency": per_draw(emergency),
    }


# ---------------------------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------------------------


def _no_drug_result(design: TrialDesign, strategy: Strategy) -> SupplyResult:
    zero = MetricRange(p10=0.0, p50=0.0, p90=0.0, unit="kits")
    none = MetricRange.model_construct(p10=0.0, p50=0.0, p90=0.0, unit="count")
    return SupplyResult(
        kits_needed=zero, kits_produced=zero, kits_wasted=zero,
        waste_share=MetricRange(p10=0.0, p50=0.0, p90=0.0, unit="percent"),
        shipments=none, stockout_probability=0.0, strategy=strategy, kits_expired=zero,
        kits_destroyed_at_close=zero, emergency_shipments=none,
        warnings=[f"drug_type is '{design.drug_type}': no investigational drug kits are simulated."],
    )


def simulate_supply(
    design: TrialDesign,
    levers: Levers,
    params: Mapping[str, Parameter],
    forecast_draws: ForecastResult | ForecastDraws,
    seed: int = 7,
    draws: int = SUPPLY_DRAWS,
) -> SupplyResult:
    """Simulate site drug supply for `levers.drug_supply_strategy` on the forecast's recruitment draws.

    Same `forecast_draws` + same seed ⇒ the same patients for both strategies (common random numbers).
    """
    strategy: Strategy = levers.drug_supply_strategy
    if design.drug_type in ("none", "device"):
        return _no_drug_result(design, strategy)
    fd_all = forecast_draws.draws if isinstance(forecast_draws, ForecastResult) else forecast_draws
    if fd_all is None:
        raise ValueError("forecast_draws has no per-draw data; pass the result of forecast().")
    notes: list[str] = []
    warnings: list[str] = []
    res = ParameterResolver(params, SUPPLY_DEFAULTS)

    follow_weeks = float(np.median(fd_all.followup_months)) * WEEKS_PER_MONTH
    offsets = dispensing_offsets_weeks(design, res, follow_weeks, notes)
    n_vis = len(offsets)
    patients_per_draw = fd_all.new_patients + fd_all.fixed_counts.sum(axis=1)
    planned_total = float(np.median(patients_per_draw))
    n_draws = min(max(1, draws), fd_all.n_draws)
    weeks = float(np.median(fd_all.t_full + fd_all.followup_months)) * WEEKS_PER_MONTH
    per_draw_work = fd_all.rates.shape[1] * weeks + 0.5 * planned_total * n_vis
    budget_draws = int(_WORK_BUDGET // max(per_draw_work, 1.0))
    if budget_draws < n_draws:
        n_draws = max(min(_MIN_DRAWS, n_draws), budget_draws)
        warnings.append(
            f"Large trial: drug supply simulated on {n_draws} draws (not {draws}) to stay within the "
            "compute budget; supply ranges are noisier than the other metrics."
        )
    fd = fd_all.take(n_draws)
    d, s = fd.rates.shape

    kpv = res.get("supply.kits_per_dispensing_visit")
    over = res.get("supply.overage_share.upfront")
    lead = res.get("supply.resupply_lead_time_weeks")
    shelf = res.get(f"supply.shelf_life_months.{design.drug_type}", "supply.shelf_life_months")
    safety = res.get("supply.site_safety_stock_kits")
    cover = res.get("supply.on_demand.cover_weeks")
    factor = res.get("supply.order_up_to_factor")
    threshold = res.get("supply.stockout_warning_threshold")

    rng = _stream(seed, "supply.patients")
    p_flat, p_t = _sample_patients(fd, rng)
    p_draw = p_flat // s
    dropped = rng.random(p_flat.size) < fd.dropout[p_draw]
    p_visits = np.where(dropped, 1 + np.floor(rng.random(p_flat.size) * n_vis), n_vis).astype(np.int64)
    p_week = np.floor(p_t * WEEKS_PER_MONTH).astype(np.int64)

    plan_sum = float(fd.planned_rate.sum())
    share = fd.planned_rate / plan_sum if plan_sum > 0 else np.full(s, 1.0 / s)
    pol = _Policy(
        strategy=strategy,
        offsets=offsets,
        kits_per_visit=np.maximum(1, np.rint(draw_parameter(kpv, seed, d))).astype(np.int64),
        overage=draw_parameter(over, seed, d),
        lead_weeks=np.maximum(1, np.rint(draw_parameter(lead, seed, d))).astype(np.int64),
        shelf_weeks=np.maximum(
            1, np.rint(draw_parameter(shelf, seed, d) * WEEKS_PER_MONTH)
        ).astype(np.int64),
        safety=int(round(safety.value_mid)),
        cover_weeks=max(1, int(round(cover.value_mid))),
        order_factor=max(1.0, factor.value_mid),
        planned_patients=planned_total * share,
    )

    chunk = max(1, _CHUNK_SITE_DRAWS // s)
    parts = []
    for lo in range(0, d, chunk):
        hi = min(lo + chunk, d)
        a, b = np.searchsorted(p_flat, [lo * s, hi * s])
        parts.append(
            _simulate_chunk(fd, pol, lo, hi, p_flat[a:b] - lo * s, p_week[a:b], p_visits[a:b])
        )
    out = {key: np.concatenate([p[key] for p in parts]) for key in parts[0]}
    per = SupplyDraws(
        kits_needed=out["needed"], kits_produced=out["produced"], kits_expired=out["expired"],
        kits_destroyed_at_close=out["leftover"], shipments=out["shipments"],
        emergency_shipments=out["emergency"], stockout=out["emergency"] > 0,
    )
    wasted = per.kits_wasted
    waste_pct = 100.0 * wasted / np.maximum(per.kits_produced, 1)
    p_stockout = float(per.stockout.mean())

    warnings += res.warnings()
    if p_stockout > threshold.value_mid:
        label = "On-demand" if strategy == "on_demand" else "Upfront"
        warnings.append(
            f"{label} supply: {p_stockout:.0%} of simulated trials have at least one site stockout "
            f"(threshold {threshold.value_mid:.0%}); emergency shipments were needed. Consider a "
            "larger safety stock or cover window."
        )
    if design.drug_type == "unknown":
        notes.append("drug_type unknown: generic kits simulated with the generic shelf life.")
    notes += [
        f"Policy settings use their mid values: safety stock {pol.safety} kits/site, cover window "
        f"{pol.cover_weeks} weeks, resupply up to {_fmt(pol.order_factor)}× the cover-window need.",
        "Kits left at sites or in transit at the end of the trial are destroyed and counted as "
        "waste; depot stock beyond site shipments is out of scope.",
        "Dropouts stop after a uniformly random number of dispensings; the IRT projection does not "
        "know future dropouts.",
        f"Supply simulated on {d} forecast draws in weekly steps.",
    ]
    desc = (
        "Upfront: each site receives planned patients × kits per patient × (1 + overage) at "
        "activation."
        if strategy == "upfront"
        else "On-demand: each site receives the projected need for the next k weeks + safety stock "
        "at activation."
    ) + (
        " Both strategies then resupply a site when usable stock + in-transit < projected need for "
        "the next k weeks + safety stock (projection = scheduled dispensings of randomised patients "
        "+ planned recruitment rate × new-patient kits)."
    )
    provenance = [
        ProvenanceItem(
            formula_id=f"supply.{strategy}.v1",
            description=desc
            + " Weekly per-site inventory with FIFO expiry; waste = expired + destroyed at close; "
            "stockouts are served by emergency shipments.",
            inputs={
                "strategy": strategy,
                "sites": float(s),
                "dispensing_visits_per_patient": float(n_vis),
                "kits_per_dispensing_visit_mid": kpv.value_mid,
                "upfront_overage_mid": over.value_mid,
                "shelf_life_months_mid": shelf.value_mid,
                "lead_time_weeks_mid": lead.value_mid,
                "safety_stock_kits": float(pol.safety),
                "cover_weeks": float(pol.cover_weeks),
                "planned_patients": round(planned_total, 1),
                "draws": float(d),
                "seed": float(seed),
            },
            parameter_ids=list(res.used),
            assumptions=[
                *notes, *(f"'{pid}' not in library — built-in assumption used." for pid in res.fallbacks)
            ],
        )
    ]
    return SupplyResult(
        kits_needed=_kits(per.kits_needed),
        kits_produced=_kits(per.kits_produced),
        kits_wasted=_kits(wasted),
        waste_share=metric_range(waste_pct, "percent"),
        shipments=_count_range(per.shipments),
        stockout_probability=p_stockout,
        strategy=strategy,
        kits_expired=_kits(per.kits_expired),
        kits_destroyed_at_close=_kits(per.kits_destroyed_at_close),
        emergency_shipments=_count_range(per.emergency_shipments),
        draws_used=d,
        warnings=warnings,
        provenance=provenance,
        per_draw=per,
    )


def compare_strategies(
    design: TrialDesign,
    levers: Levers,
    params: Mapping[str, Parameter],
    forecast_draws: ForecastResult | ForecastDraws,
    seed: int = 7,
    draws: int = SUPPLY_DRAWS,
) -> dict[str, SupplyResult]:
    """Both strategies on the same patients (for the 'on-demand vs upfront' comparison)."""
    return {
        strat: simulate_supply(
            design, levers.model_copy(update={"drug_supply_strategy": strat}), params,
            forecast_draws, seed=seed, draws=draws,
        )
        for strat in ("upfront", "on_demand")
    }
