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
_DISPENSING_BUDGET = 6_000_000  # max simulated (patient, dispensing) events per call
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


def _dense_counts(index: IntArray, weights: FloatArray | None, rows: int, cols: int) -> FloatArray:
    return np.bincount(index, weights=weights, minlength=rows * cols).reshape(rows, cols)


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
    rows = horizon + k + 2
    kits = pol.kits_per_visit[gdraw]

    # --- dispensing demand: one bincount over all (patient, visit) events ---------------------
    base = p_week * ds + p_ds
    off_ds = offs * ds
    full = p_visits >= n_vis
    j_drop = p_visits[~full]
    rep = np.repeat(base[~full], j_drop)
    vis = np.arange(rep.size) - np.repeat(np.cumsum(j_drop) - j_drop, j_drop)
    events = np.concatenate([(base[full, None] + off_ds[None, :]).ravel(), rep + off_ds[vis]])
    dem = np.bincount(events, minlength=rows * ds).reshape(rows, ds) * kits[None, :]
    total_dem = np.bincount(p_ds, weights=p_visits, minlength=ds).astype(np.int64) * kits

    # --- what the IRT cannot know, as a difference array over weeks --------------------------
    # known need(t) = dispensings in (t, t+k] of patients randomised by t
    #   = window sum of `dem`  − dispensings of patients randomised after t  (+ phantom visits of
    #     patients who will drop out but have not yet missed a visit).
    add_idx: list[IntArray] = []
    add_w: list[FloatArray] = []

    def _range(t0: IntArray, t1: IntArray, cols: IntArray, sign: float) -> None:
        keep = t0 < t1
        add_idx.extend([t0[keep] * ds + cols[keep], t1[keep] * ds + cols[keep]])
        add_w.extend([np.full(int(keep.sum()), sign), np.full(int(keep.sum()), -sign)])

    for v, off in enumerate(offs):
        if off >= k:
            break
        on = p_visits > v
        e = p_week[on]
        _range(np.maximum(e + off - k, 0), e, p_ds[on], -1.0)  # new patients, not yet known
    drop = ~full
    e_d, j_d, c_d = p_week[drop], p_visits[drop], p_ds[drop]
    b_miss = e_d + offs[np.minimum(j_d, n_vis - 1)]
    for m in range(n_vis):
        v = j_d + m
        valid = v < n_vis
        if not valid.any():
            break
        b_v = e_d + offs[np.minimum(v, n_vis - 1)]
        valid &= (b_v - b_miss) < k
        if not valid.any():
            break
        _range(
            np.maximum(e_d, b_v - k)[valid], b_miss[valid], c_d[valid], 1.0,
        )  # phantom: expected until the first missed visit
    if add_idx:
        adj_diff = _dense_counts(np.concatenate(add_idx), np.concatenate(add_w), rows, ds)
        adj = np.rint(np.cumsum(adj_diff, axis=0)).astype(np.int64) * kits[None, :]
    else:
        adj = np.zeros((rows, ds), dtype=np.int64)

    # --- policy constants ----------------------------------------------------------------------
    rate_week = fd.planned_rate[site] / WEEKS_PER_MONTH
    new_kits_k = rate_week * kits * float(sum(k - o for o in offs if o < k))
    if pol.strategy == "upfront":
        q0 = np.ceil(pol.planned_patients[site] * kits * n_vis * (1.0 + pol.overage[gdraw]))
    else:
        q0 = np.ceil(new_kits_k + pol.safety)
    q0 = q0.astype(np.int64)
    lead = pol.lead_weeks[gdraw]
    shelf = pol.shelf_weeks[gdraw]
    ring_len = int(lead.max()) + 1
    exp_len = int(shelf.max()) + 1
    look = int(lead.max())
    act_order, act_ptr = _event_groups(act_w, horizon)
    close_order, close_ptr = _event_groups(np.minimum(close_w, horizon), horizon)

    ring = np.zeros((ring_len, ds), dtype=np.int64)  # orders in transit, by arrival week
    exp_due = np.zeros((exp_len, ds), dtype=np.int64)  # expiry thresholds, by due week
    stock = np.zeros(ds, dtype=np.int64)
    pipeline = np.zeros(ds, dtype=np.int64)
    arrived = np.zeros(ds, dtype=np.int64)
    removed = np.zeros(ds, dtype=np.int64)
    remaining = total_dem.copy()
    expired = np.zeros(ds, dtype=np.int64)
    produced = np.zeros(ds, dtype=np.int64)
    shipments = np.zeros(ds, dtype=np.int64)
    emergency = np.zeros(ds, dtype=np.int64)
    active = np.zeros(ds, dtype=bool)
    enrolling = np.zeros(ds, dtype=bool)
    exp_new = np.zeros(ds, dtype=np.float64)
    soon = np.zeros(ds, dtype=np.int64)
    win = dem[1 : k + 1].sum(axis=0)
    safety_on = np.int64(pol.safety)

    def receive(idx: IntArray, qty: IntArray, t: int) -> None:
        stock[idx] += qty
        arrived[idx] += qty
        exp_due[(t + shelf[idx]) % exp_len, idx] = arrived[idx]

    for t in range(horizon):
        # 1. arrivals: resupplies in transit, then initial stock of sites opening this week
        slot = t % ring_len
        nz = np.flatnonzero(ring[slot])
        if nz.size:
            q = ring[slot, nz]
            ring[slot, nz] = 0
            pipeline[nz] -= q
            receive(nz, q, t)
        opening = act_order[act_ptr[t] : act_ptr[t + 1]]
        if opening.size:
            q = q0[opening]
            produced[opening] += q
            shipments[opening] += q > 0
            receive(opening, q, t)
            active[opening] = True
            enrolling[opening] = t < close_w[opening]
            exp_new[opening] = np.where(enrolling[opening], new_kits_k[opening], 0.0)
        closing = close_order[close_ptr[t] : close_ptr[t + 1]]
        if closing.size:
            enrolling[closing] = False
            exp_new[closing] = 0.0

        # 2. expiry of shipments that reached the site `shelf` weeks ago (FIFO)
        eslot = t % exp_len
        nz = np.flatnonzero(exp_due[eslot])
        if nz.size:
            x = np.maximum(exp_due[eslot, nz] - removed[nz], 0)
            exp_due[eslot, nz] = 0
            stock[nz] -= x
            removed[nz] += x
            expired[nz] += x

        # 3. dispensing; shortfalls are stockouts served by emergency shipments
        d_t = dem[t]
        take = np.minimum(d_t, stock)
        stock -= take
        removed += d_t
        remaining -= d_t
        short = np.flatnonzero(d_t - take)
        if short.size:
            u = d_t[short] - take[short]
            produced[short] += u
            arrived[short] += u  # arrive and are dispensed in the same week
            emergency[short] += 1
            shipments[short] += 1

        # 4. reorder on usable position vs projected need for weeks t+1 … t+k
        soon.fill(0)
        for j in range(1, look + 1):
            np.maximum(soon, exp_due[(t + j) % exp_len], out=soon)
        usable = stock + pipeline - np.maximum(soon - removed, 0)
        in_service = enrolling | (active & (remaining > 0))
        safety = np.where(in_service, safety_on, 0)
        projected = win + adj[t] + exp_new
        nz = np.flatnonzero(usable < projected + safety)
        if nz.size:
            q = np.maximum(
                np.ceil(pol.order_factor * projected[nz] + safety[nz] - usable[nz]), 1
            ).astype(np.int64)
            ring[(t + lead[nz]) % ring_len, nz] += q
            pipeline[nz] += q
            produced[nz] += q
            shipments[nz] += 1

        win += dem[t + k + 1]
        win -= dem[t + 1]

    leftover = stock + pipeline
    dispensed = total_dem - remaining

    def per_draw(x: IntArray) -> IntArray:
        return np.asarray(x.reshape(dc, s).sum(axis=1), dtype=np.int64)

    return {
        "needed": per_draw(dispensed),
        "produced": per_draw(produced),
        "expired": per_draw(expired),
        "leftover": per_draw(leftover),
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
    budget_draws = int(_DISPENSING_BUDGET // max(planned_total * n_vis, 1.0))
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
