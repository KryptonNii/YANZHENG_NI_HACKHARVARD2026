"""Plan vs actual: 14 KPIs at study / country / site level (definitions and rationale in KPIS.md).

Plan and actual go through the SAME activity -> cost / carbon / hours formulas (common random numbers), so a
gap between them comes from activity, not from different assumptions. Actual spend is the sum of FINANCE
invoices; carbon and hours are activity × parameters (ranges, because the factors are uncertain).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

import numpy as np

from ._contracts import Alert, MetricRange
from .detect import Detector, N, mr
from .metrics import TRIP_EF, Feed
from .milestones import forecast_milestones
from .params import OpsParams
from .plan import DAYS_PER_MONTH, MONITORING_CYCLE_WEEKS, WEEKS_PER_MONTH, OpsPlan

TRAIL_WEEKS = 8
KPI_DEFS: list[dict[str, str]] = [
    {"id": "enrollment", "label": "Enrollment vs plan band", "unit": "patients", "levels": "study,country,site"},
    {"id": "enrollment_rate", "label": "Enrollment rate (trailing 8 weeks)", "unit": "patients/month",
     "levels": "study,country,site"},
    {"id": "sites_status", "label": "Sites active / stalled / not activated", "unit": "sites",
     "levels": "study,country,site"},
    {"id": "missed_visit_rate", "label": "Missed visits (trailing 8 weeks)", "unit": "percent",
     "levels": "study,country,site"},
    {"id": "withdrawals", "label": "Withdrawals", "unit": "patients", "levels": "study,country,site"},
    {"id": "open_queries", "label": "Open queries and median age", "unit": "queries",
     "levels": "study,country,site"},
    {"id": "query_rate", "label": "Queries per 100 visits (trailing 8 weeks)", "unit": "percent",
     "levels": "study,site"},
    {"id": "drug_supply", "label": "Drug on hand vs projected need", "unit": "kits", "levels": "study,site"},
    {"id": "spend_to_date", "label": "Spend to date vs plan", "unit": "usd", "levels": "study"},
    {"id": "carbon_to_date", "label": "Carbon to date vs plan", "unit": "kg_co2e", "levels": "study"},
    {"id": "site_staff_hours", "label": "Site staff hours to date vs plan", "unit": "hours", "levels": "study,site"},
    {"id": "patient_burden_hours", "label": "Patient burden hours to date vs plan", "unit": "hours",
     "levels": "study"},
    {"id": "milestones", "label": "Milestone forecasts vs targets", "unit": "date", "levels": "study"},
    {"id": "open_alerts", "label": "Open alerts by severity", "unit": "alerts", "levels": "study,country,site"},
]


def _status_band(value: float, p10: float, p50: float) -> str:
    if value < p10:
        return "off_track"
    if value < p50:
        return "watch"
    return "on_track"


def _ratio_status(actual: float, plan: float, tol: float = 0.1, higher_is_bad: bool = True) -> str:
    if plan <= 0:
        return "unknown"
    r = actual / plan
    bad = r > 1 + tol if higher_is_bad else r < 1 - tol
    very = r > 1 + 2 * tol if higher_is_bad else r < 1 - 2 * tol
    return "off_track" if very else "watch" if bad else "on_track"


# ----------------------------------------------------------------------------- activity models
def actual_activity(feed: Feed, upto: float) -> dict[str, float]:
    road = feed.params.mid("ops.dist.road_factor")
    a: dict[str, float] = defaultdict(float)
    onsite = feed.col("visit", "onsite") > 0
    a["visits"] = float(feed.mask("visit", upto).sum())
    a["visits_onsite"] = float((feed.mask("visit", upto) & onsite).sum())
    a["site_minutes"] = float(feed.col("visit", "minutes")[feed.mask("visit", upto)].sum())
    a["queries"] = float((feed.q_open_t < upto).sum())
    for t in feed.trips:
        if t["t"] < upto and not t["remote"]:
            a["trips"] += 1
            a["site_days"] += t["site_days"]
            a[f"pkm_{t['mode']}"] += t["km"]
    m = feed.mask("sample", upto)
    air = feed.col("sample", "air")[m] > 0
    tkm = feed.col("sample", "kg")[m] * feed.col("sample", "km")[m] / 1000.0
    a["ship_air"], a["ship_ground"] = float(air.sum()), float((~air).sum())
    a["tkm_air"] += float(tkm[air].sum())
    a["tkm_road"] += float(tkm[~air].sum())
    m = feed.mask("dispatched", upto)
    dair = feed.col("dispatched", "air")[m] > 0
    dtkm = feed.col("dispatched", "kg")[m] * feed.col("dispatched", "km")[m] / 1000.0
    a["tkm_air"] += float(dtkm[dair].sum())
    a["tkm_road"] += float(dtkm[~dair].sum())
    a["kits_shipped"] = float(feed.col("dispatched", "kits")[m].sum())
    a["road_factor"] = road
    return dict(a)


def planned_activity(plan: OpsPlan, params: OpsParams, upto: float) -> dict[str, float]:
    """Expected activity to date under the plan (mid parameters, plan enrollment rates, batched monitoring)."""
    miss = params.mid("ops.rate.missed_visit_base")
    drop = params.mid("ops.rate.dropout_per_year") / 365.25
    qpv = params.mid("ops.rate.queries_per_visit")
    pkg = params.mid("ops.ship.specimen_package_kg")
    kit_kg = params.mid("ops.ship.kit_kg")
    gmax = params.mid("ops.ship.ground_max_km")
    a: dict[str, float] = defaultdict(float)
    days = np.arange(int(upto))
    cum_enrolled = 0.0
    clusters: dict[str, list] = defaultdict(list)
    for s in plan.sites:
        if s.backup or s.activation_day is None:
            continue
        clusters[s.cluster].append(s)
        rate = s.planned_rate_month / DAYS_PER_MONTH
        e = np.where((days >= s.activation_day) & (days < plan.enrollment_end_day), rate, 0.0)
        cum = np.cumsum(e)
        cum_enrolled += float(cum[-1]) if len(cum) else 0.0
        air = s.road_km_to_hub > gmax
        km = s.gc_km_to_hub if air else s.road_km_to_hub
        site_visits = 0.0
        for v in plan.visits:
            lag = int(round(v.week * 7))
            n = float(cum[int(upto) - 1 - lag]) if 0 <= int(upto) - 1 - lag < len(cum) else 0.0
            if v.week > 0:
                n *= (1 - miss) * np.exp(-drop * v.week * 7)
            site_visits += n
            a["site_minutes"] += n * v.site_minutes
            if v.mode == "on_site":
                a["visits_onsite"] += n
            if "refrigerated" in v.sample_temps and plan.local_lab_share < 1:
                a["ship_air" if air else "ship_ground"] += n * (1 - plan.local_lab_share)
                a["tkm_air" if air else "tkm_road"] += n * (1 - plan.local_lab_share) * pkg * km / 1000
            a["kits_dispensed"] += n * v.dispense_kits
        a["visits"] += site_visits
        weeks_with_patients = max(0.0, (upto - s.activation_day - 30) / 7)
        a["ship_air" if air else "ship_ground"] += weeks_with_patients
        a["tkm_air" if air else "tkm_road"] += weeks_with_patients * pkg * km / 1000
        a["kits_shipped"] += 10.0  # initial stock (IRT minimum level)
        a["tkm_air" if air else "tkm_road"] += 10.0 * kit_kg * km / 1000
    a["kits_shipped"] += a.get("kits_dispensed", 0.0)
    a["queries"] = a["visits"] * qpv
    road = params.mid("ops.dist.road_factor")
    cycle = MONITORING_CYCLE_WEEKS * 7
    from . import geo

    base: dict[str, object] = {}
    for s in plan.sites:
        base.setdefault(s.country, s)
    for _, sites in clusters.items():
        first = min(s.activation_day for s in sites) + 30  # type: ignore[type-var]
        n_cycles = max(0.0, (upto - first) / cycle)
        remote = plan.remote_monitoring_share
        a["trips"] += n_cycles * (1 - remote)
        a["site_days"] += n_cycles * (1 - remote) * len(sites)
        b = base[sites[0].country]
        gc = geo.haversine_km(b.lat, b.lon, sites[0].lat, sites[0].lon)  # type: ignore[attr-defined]
        one_way = gc * road
        mode, rt = ("car", 30.0) if gc < 30 else ("car", 2 * one_way) if one_way <= 250 else (
            ("rail" if sites[0].region in geo.RAIL_REGIONS else "car"), 2 * one_way) if one_way <= 700 else (
            "flight", 2 * gc)
        a[f"pkm_{mode}"] += n_cycles * (1 - remote) * rt
    a["road_factor"] = road
    a["enrolled"] = min(cum_enrolled, plan.enrollment_target)
    return dict(a)


def activity_metrics(act: dict[str, float], params: OpsParams, seed: int) -> dict[str, np.ndarray]:
    """Activity -> draws of cost (excl. drug), carbon, staff hours, patient hours (common random numbers)."""
    def d(pid: str) -> np.ndarray:
        return params.draws(pid, N, seed=seed)

    cost = (act.get("visits", 0) * d("ops.cost.site_visit_fee")
            + act.get("site_days", 0) * d("ops.cost.monitoring_site_day")
            + act.get("trips", 0) * d("ops.cost.monitoring_trip_travel")
            + act.get("ship_ground", 0) * d("ops.cost.courier_ground")
            + act.get("ship_air", 0) * d("ops.cost.courier_air")
            + act.get("kits_shipped", 0) * d("ops.cost.drug_kit"))
    co2 = (act.get("pkm_car", 0) * d("ops.ef.car_km") + act.get("pkm_rail", 0) * d("ops.ef.rail_pkm")
           + act.get("pkm_flight", 0) * d("ops.ef.flight_pkm")
           + act.get("tkm_road", 0) * d("ops.ef.freight_road_tkm")
           + act.get("tkm_air", 0) * d("ops.ef.freight_air_tkm")
           + act.get("visits_onsite", 0) * d("ops.dist.patient_round_trip") * d("ops.ef.car_km"))
    staff = act.get("site_minutes", 0) / 60.0 + act.get("queries", 0) * d("ops.time.query_resolution") / 60.0
    # patients spend at least the procedures' duration at the visit, plus travel for on-site visits
    patient = act.get("visits_onsite", 0) * d("ops.time.patient_travel_per_visit") + act.get("site_minutes", 0) / 60
    return {"cost": cost, "co2": co2, "staff": staff, "patient": patient}


# ----------------------------------------------------------------------------- health
def compute_health(plan: OpsPlan, feed: Feed, params: OpsParams, upto: float, alerts: list[Alert],
                   seed: int = 0) -> dict:
    W = int(upto // 7)
    det = Detector(plan, feed, seed)
    cum = feed.per_site("enrolled", upto)
    trail_start = upto - TRAIL_WEEKS * 7
    enr_trail = feed.per_site("enrolled", upto, trail_start)
    wd = feed.per_site("withdrawn", upto)
    miss_trail = feed.per_site("missed", upto, trail_start)
    fu = feed.col("visit", "followup") > 0
    done_fu_trail = feed.per_site("visit", upto, trail_start, where=fu)
    visits_trail = feed.per_site("visit", upto, trail_start)
    q_trail = np.bincount(feed.q_site[(feed.q_open_t < upto) & (feed.q_open_t >= trail_start)],
                          minlength=feed.S)[: feed.S]
    open_q, ages, age_site = feed.open_queries(upto)
    lots = feed.lots_on_hand(upto)
    disp6 = feed.per_site("dispensed", upto, upto - 42, field="kits")
    transit = feed.in_transit(upto)
    waste = {f.scope: f.evidence.get("waste_kits_p50", 0.0) for f in det.overstock(upto)}
    open_alerts = [a for a in alerts if a.status in ("open", "acknowledged", "action_planned")]
    band_idx = min(W, plan.site_band.shape[1] - 1)

    def alert_counts(pred) -> dict[str, int]:
        out = {"critical": 0, "warning": 0, "info": 0}
        for a in open_alerts:
            if pred(a):
                out[a.severity] += 1
        return out

    sites_out = []
    by_country: dict[str, list] = defaultdict(list)
    for s in plan.sites:
        i = s.idx
        b10, b50, b90 = (float(x) for x in plan.site_band[i, band_idx])
        active = (s.activation_day is not None and s.activation_day <= upto) or cum[i] > 0
        stalled = bool(active and s.activation_day is not None and
                       (upto - s.activation_day) >= 56 and enr_trail[i] == 0)
        status = ("backup (not activated)" if s.backup and not active else "not activated" if not active
                  else "stalled" if stalled else "active")
        on_hand = float(sum(q for _, q, _ in lots.get(i, [])))
        rate_wk = disp6[i] / 6.0
        site_ages = ages[age_site == i]
        planned_rate = s.planned_rate_month
        k = {
            "enrollment": {"value": int(cum[i]), "plan": {"p10": b10, "p50": b50, "p90": b90},
                           "status": _status_band(cum[i], b10, b50) if active and not s.backup else "unknown"},
            "enrollment_rate": {"value": round(enr_trail[i] / TRAIL_WEEKS * WEEKS_PER_MONTH, 2),
                                "plan": round(planned_rate, 2),
                                "status": _ratio_status(enr_trail[i] / TRAIL_WEEKS * WEEKS_PER_MONTH, planned_rate,
                                                        0.25, higher_is_bad=False) if active and planned_rate else
                                "unknown"},
            "sites_status": {"value": status},
            "missed_visit_rate": _pct(miss_trail[i], miss_trail[i] + done_fu_trail[i]),
            "withdrawals": {"value": int(wd[i]), "share_of_enrolled": round(wd[i] / cum[i], 3) if cum[i] else None},
            "open_queries": {"value": int(open_q[i]),
                             "median_age_days": round(float(np.median(site_ages)), 1) if len(site_ages) else None},
            "query_rate": _pct(q_trail[i], visits_trail[i]),
            "drug_supply": {"kits_on_hand": on_hand, "kits_in_transit": float(transit[i]),
                            "weeks_of_supply": round((on_hand + transit[i]) / rate_wk, 1) if rate_wk > 0 else None,
                            "projected_expiry_kits": round(waste.get(s.id, 0.0), 1)},
            "open_alerts": alert_counts(lambda a, sid=s.id: a.site_id == sid),
        }
        site_row = {"site_id": s.id, "name": s.name, "city": s.city, "country": s.country, "region": s.region,
                    "lat": s.lat if s.id not in {v.id for v in plan.design.sites if v.lat is None} else None,
                    "lon": s.lon if s.id not in {v.id for v in plan.design.sites if v.lon is None} else None,
                    "backup": s.backup, "status": status,
                    "activation_date": plan.date(s.activation_day).date().isoformat()
                    if s.activation_day is not None else None, "kpis": k}
        need = (np.random.default_rng([seed, 809, i]).gamma(.5 + disp6[i], 1 / 42, N) * 28
                if upto >= 42 else None)
        site_row.update(enrolled=int(cum[i]), planned_to_date={"p10": b10, "p50": b50,
                        "p90": b90, "unit": "patients"}, open_queries=int(open_q[i]),
                        median_query_age_days=k["open_queries"]["median_age_days"],
                        drug_on_hand_kits=on_hand,
                        drug_need_kits=mr(need, "kits").model_dump() if need is not None else None,
                        status=("never_enrolled" if stalled and cum[i] == 0 else "stalled" if stalled
                                else "active" if active else "not_started"))
        sites_out.append(site_row)
        by_country[s.country].append((s, site_row))

    countries_out = []
    for cc, rows in sorted(by_country.items()):
        idx = [s.idx for s, _ in rows]
        b = plan.site_band[idx, band_idx].sum(axis=0)
        c_cum = float(cum[idx].sum())
        c_rate = float(enr_trail[idx].sum()) / TRAIL_WEEKS * WEEKS_PER_MONTH
        c_plan_rate = sum(s.planned_rate_month for s, _ in rows)
        countries_out.append({
            "country": cc, "region": rows[0][0].region, "n_sites": len(rows),
            "sites": len(rows), "enrolled": int(c_cum), "open_queries": int(open_q[idx].sum()),
            "stalled_sites": sum(r["status"] in ("stalled", "never_enrolled") for _, r in rows),
            "planned_to_date": {"p10": float(b[0]), "p50": float(b[1]), "p90": float(b[2]),
                                "unit": "patients"},
            "kpis": {
                "enrollment": {"value": int(c_cum), "plan": {"p10": float(b[0]), "p50": float(b[1]),
                                                             "p90": float(b[2])},
                               "status": _status_band(c_cum, b[0], b[1])},
                "enrollment_rate": {"value": round(c_rate, 2), "plan": round(c_plan_rate, 2),
                                    "status": _ratio_status(c_rate, c_plan_rate, 0.25, higher_is_bad=False)},
                "sites_status": {"value": _site_counts([r["status"] for _, r in rows])},
                "missed_visit_rate": _pct(miss_trail[idx].sum(), miss_trail[idx].sum() + done_fu_trail[idx].sum()),
                "withdrawals": {"value": int(wd[idx].sum())},
                "open_queries": {"value": int(open_q[idx].sum())},
                "open_alerts": alert_counts(lambda a, ids=set(s.id for s, _ in rows), c=cc: a.site_id in ids or (
                    a.site_id is None and c in a.summary[:4])),
            }})

    # study level
    sb = plan.study_band[band_idx]
    s_cum = float(cum.sum())
    planned_rate_study = sum(s.planned_rate_month for s in plan.sites)
    act = actual_activity(feed, upto)
    pla = planned_activity(plan, params, upto)
    m_act, m_pla = activity_metrics(act, params, seed), activity_metrics(pla, params, seed)
    invoice_cut = _month_start(plan, upto)
    spend = [x for x in feed.spend if x[0] < upto]
    spend_total = float(sum(x[4] for x in spend))
    spend_by_cat: dict[str, float] = defaultdict(float)
    for x in spend:
        spend_by_cat[x[3]] += x[4]
    pla_cut = activity_metrics(planned_activity(plan, params, invoice_cut), params, seed)
    mf = forecast_milestones(plan, feed, upto, seed)

    def mdate(v: float) -> str | None:
        return plan.date(v).date().isoformat() if np.isfinite(v) else None

    def ms(name: str, target: int) -> dict:
        p10, p50, p90 = mf.q(name)
        return {"p10": mdate(p10), "p50": mdate(p50), "p90": mdate(p90), "target": mdate(target),
                "slip_days_p50": round(p50 - target, 0) if np.isfinite(p50) else None,
                "status": "off_track" if p10 > target else "watch" if p50 > target else "on_track"}

    staff_plan, staff_act = mr(m_pla["staff"], "hours"), mr(m_act["staff"], "hours")
    study = {
        "enrollment": {"value": int(s_cum), "target": plan.enrollment_target,
                       "plan": {"p10": float(sb[0]), "p50": float(sb[1]), "p90": float(sb[2])},
                       "status": _status_band(s_cum, sb[0], sb[1])},
        "enrollment_rate": {"value": round(float(enr_trail.sum()) / TRAIL_WEEKS * WEEKS_PER_MONTH, 2),
                            "plan": round(planned_rate_study, 2),
                            "status": _ratio_status(float(enr_trail.sum()) / TRAIL_WEEKS * WEEKS_PER_MONTH,
                                                    planned_rate_study, 0.15, higher_is_bad=False)},
        "sites_status": {"value": _site_counts([r["status"] for r in sites_out])},
        "missed_visit_rate": _pct(miss_trail.sum(), miss_trail.sum() + done_fu_trail.sum()),
        "withdrawals": {"value": int(wd.sum()), "share_of_enrolled": round(float(wd.sum()) / s_cum, 3)
                        if s_cum else None},
        "open_queries": {"value": int(open_q.sum()),
                         "median_age_days": round(float(np.median(ages)), 1) if len(ages) else None},
        "query_rate": _pct(q_trail.sum(), visits_trail.sum()),
        "drug_supply": {"kits_on_hand": float(sum(q for v in lots.values() for _, q, _ in v)),
                        "kits_in_transit": float(transit.sum()),
                        "kits_expired_to_date": float(feed.per_site("expired", upto, field="kits").sum()),
                        "projected_expiry_kits": round(sum(waste.values()), 1)},
        "spend_to_date": {
            "value": MetricRange(p10=spend_total, p50=spend_total, p90=spend_total, unit="usd").model_dump(),
            "plan": mr(pla_cut["cost"], "usd").model_dump(), "as_of_invoices": mdate(invoice_cut),
            "by_category": {k: round(v, 2) for k, v in sorted(spend_by_cat.items())},
            "status": _ratio_status(spend_total, float(np.median(pla_cut["cost"])), 0.1)},
        "carbon_to_date": {"value": mr(m_act["co2"], "kg_co2e").model_dump(),
                           "plan": mr(m_pla["co2"], "kg_co2e").model_dump(),
                           "status": _ratio_status(float(np.median(m_act["co2"])), float(np.median(m_pla["co2"])),
                                                   0.1)},
        "site_staff_hours": {"value": staff_act.model_dump(), "plan": staff_plan.model_dump(),
                             "status": _ratio_status(staff_act.p50, staff_plan.p50, 0.1)},
        "patient_burden_hours": {"value": mr(m_act["patient"], "hours").model_dump(),
                                 "plan": mr(m_pla["patient"], "hours").model_dump()},
        "milestones": {"lpi": ms("lpi", plan.lpi_target_day), "lplv": ms("lplv", plan.lplv_target_day),
                       "db_lock": ms("dblock", plan.dblock_target_day),
                       "first_patient_in": mdate(float(feed.col("enrolled", "t")[
                           feed.mask("enrolled", upto)].min()))
                       if feed.mask("enrolled", upto).any() else None},
        "open_alerts": alert_counts(lambda a: True),
    }
    prov = {
        "spend_to_date": params.provenance(
            "ops.kpi.spend.v1", "actual = sum of FINANCE invoices to date; plan = planned activity to the same "
            "invoice cut-off × unit costs (site visit fees, monitoring, courier, drug kits)",
            {"invoices": len(spend)}, ["ops.cost.site_visit_fee", "ops.cost.monitoring_site_day",
                                       "ops.cost.monitoring_trip_travel", "ops.cost.courier_ground",
                                       "ops.cost.courier_air", "ops.cost.drug_kit"]),
        "carbon_to_date": params.provenance(
            "ops.kpi.carbon.v1", "monitoring pkm × EF(mode) + specimen/drug tonne-km × EF(mode) + on-site visits × "
            "patient round-trip km × car EF", {k: round(v, 1) for k, v in act.items()},
            [*TRIP_EF.values(), "ops.ef.freight_road_tkm", "ops.ef.freight_air_tkm", "ops.dist.patient_round_trip"]),
        "site_staff_hours": params.provenance(
            "ops.kpi.staff_hours.v1", "visit procedure minutes ÷ 60 + queries × minutes per query ÷ 60",
            {"site_minutes": round(act.get("site_minutes", 0)), "queries": act.get("queries", 0)},
            ["ops.time.query_resolution"]),
        "patient_burden_hours": params.provenance(
            "ops.kpi.patient_hours.v1", "on-site visits × travel hours per visit + procedure time",
            {"visits_onsite": act.get("visits_onsite", 0)}, ["ops.time.patient_travel_per_visit"]),
        "milestones": params.provenance(
            "ops.kpi.milestones.v1", "Poisson–gamma update of site rates with actuals (A3 "
            "update_with_actuals); DB lock = max(LPLV + cleaning, vendor critical path)", {"enrolled": mf.enrolled},
            ["ops.time.db_lock_cleaning"]),
    }
    return {
        "trial_id": None,
        "trial_title": plan.design.title,
        "as_of": plan.date(upto).isoformat(),
        "clock_day": round(upto, 3),
        "simulated": True,
        "data_label": "Simulated feed",
        "study": study,
        "countries": countries_out,
        "sites": sites_out,
        "provenance": {k: v.model_dump() for k, v in prov.items()},
        "kpi_definitions": KPI_DEFS,
        "kpis": _ui_kpis(study),
        "plan_notes": plan.notes,
        "parameter_assumptions": sorted(pid for pid, p in params.params.items() if p.assumption),
        "parameter_sources": {pid: p.model_dump(mode="json") for pid, p in params.params.items()},
        "forecast_parameters": {pid: p.model_dump(mode="json")
                                for pid, p in plan.forecast_params.items()},
        "baseline_scenario": plan.scenario_meta,
    }


def _ui_kpis(study):
    """Flat, additive view accepted by A9's existing normalizeHealth adapter."""
    out = []
    for definition in KPI_DEFS:
        key = definition["id"]
        item = study[key]
        value = item.get("value")
        plan = item.get("plan")
        if isinstance(value, dict) and "p50" in value:
            value = value["p50"]
        text = None
        if key == "sites_status":
            counts = item["value"]
            text = f"{counts.get('active', 0)} active / {counts.get('stalled', 0)} stalled"
            value = counts.get("active", 0)
        elif key == "drug_supply":
            value = item["kits_on_hand"]
            text = f"{value:.0f} on hand / {item['projected_expiry_kits']:.0f} projected expiry"
        elif key == "milestones":
            text = item["db_lock"]["p50"] or "Unknown"
        elif key == "open_alerts":
            value = sum(item.values())
        out.append({"id": key, "label": definition["label"], "unit": definition["unit"],
                    "value": value if isinstance(value, int | float) else None,
                    "value_text": text, "plan": plan if isinstance(plan, dict) else None,
                    "status": "at_risk" if item.get("status") == "off_track" else
                              item.get("status", "unknown")})
    return out


def _pct(num: float, den: float) -> dict:
    return {"value": round(100.0 * num / den, 1) if den else None, "numerator": int(num), "denominator": int(den)}


def _site_counts(statuses: list[str]) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for s in statuses:
        out[s] += 1
    return dict(out)


def _month_start(plan: OpsPlan, upto: float) -> float:
    d = plan.date(upto)
    first = datetime(d.year, d.month, 1, tzinfo=d.tzinfo)
    # invoices for month M arrive on the 3rd of M+1: before the 3rd, the last complete invoiced month is M-2
    if d.day <= 3:
        prev = datetime(d.year - (d.month == 1), (d.month - 2) % 12 + 1, 1, tzinfo=d.tzinfo)
        first = prev
    return plan.day_of(first)
