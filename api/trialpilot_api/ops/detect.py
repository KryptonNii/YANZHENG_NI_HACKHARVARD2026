"""Alert detection: transparent rules + simple statistics over the feed (no black boxes).

Each rule returns `Finding`s for problems *present* as of a day. `trigger=True` means the (stricter) raise
condition holds; a finding with `trigger=False` only keeps an existing alert open (hysteresis). The store
de-duplicates on (kind, scope): one open alert per kind and site/country/milestone.

Impact ranges are Monte Carlo over the ops parameters (triangular, seeded) and observed-rate
uncertainty (Gamma posteriors). Provenance is returned per impact key.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass, field
from typing import get_args

import numpy as np

from . import actions
from ._contracts import MetricRange, ProvenanceItem
from .metrics import Feed
from .milestones import MilestoneForecast, forecast_milestones
from .plan import DAYS_PER_MONTH, OpsPlan

N = 2000  # Monte Carlo draws for impact ranges

# ----------------------------------------------------------------------------- thresholds (documented)
ENR_MIN_EXPECTED = 5.0  # planned patients to date before a site can be judged
ENR_CONSEC_WEEKS = 4
ENR_RATIO_MAX = 0.7
ENR_ALPHA = 0.05  # plus four consecutive weeks below the P10 band; not a single-week test
ENR_NULL_SHARE = 0.9
ENR_NEVER_EXPECTED = 4.5  # zero enrolled while >= 4.5 expected (P(0) ~ 1%)
MS_MIN_WEEKS = 8
MS_TOLERANCE_DAYS = 14  # DB-lock P50 may exceed target by this much before alerting
OVER_MIN_HISTORY_DAYS = 56
QB_WINDOW_WEEKS = 8
QB_SLOPE_MIN = 0.5  # open queries per week
QB_OPEN_MIN = 8
QB_AGE_MIN = 21.0  # days, median age of open queries
OVER_RATE_WEEKS = 8
OVER_WASTE_MIN = 10.0  # kits (P50)
OVER_WASTE_SHARE = 0.25
OVER_PERSIST = 5.0
SHORT_RATE_WEEKS = 6
SHIP_WINDOW_WEEKS = 8
SHIP_MIN_AIR = 2
MON_WINDOW_WEEKS = 12
MON_AVOIDABLE_MIN = 2
VENDOR_SLIP_MIN = 14
VENDOR_SLIP_CRITICAL = 30

_UNITS = set(get_args(MetricRange.model_fields["unit"].annotation))
DELAY_UNIT = "days" if "days" in _UNITS else "months"  # contract has no "days" yet -> months


@dataclass
class Finding:
    kind: str
    scope: str  # site id, country code, milestone id, or "study"
    site_id: str | None
    severity: str
    trigger: bool
    summary: str
    est_impact: dict[str, MetricRange]
    provenance: dict[str, ProvenanceItem]
    recommended_actions: list[str]
    evidence: dict = field(default_factory=dict)


def mr(draws: np.ndarray | float, unit: str) -> MetricRange:
    a = np.atleast_1d(np.asarray(draws, dtype=float))
    p10, p50, p90 = (float(x) for x in np.quantile(a, [0.1, 0.5, 0.9]))
    return MetricRange(p10=round(p10, 2), p50=round(p50, 2), p90=round(p90, 2), unit=unit)  # type: ignore[arg-type]


def poisson_cdf(k: int, lam: float) -> float:
    """P(X <= k) for X ~ Poisson(lam)."""
    if lam <= 0:
        return 1.0
    term = total = float(np.exp(-lam))
    for i in range(1, int(k) + 1):
        term *= lam / i
        total += term
    return min(1.0, total)


def delay_range(days: np.ndarray) -> MetricRange:
    d = np.clip(days, 0, None)
    return mr(d if DELAY_UNIT == "days" else d / DAYS_PER_MONTH, DELAY_UNIT)


class Detector:
    def __init__(self, plan: OpsPlan, feed: Feed, seed: int = 0):
        self.plan, self.feed, self.p = plan, feed, feed.params
        self.seed = seed

    def d(self, pid: str, key: str) -> np.ndarray:
        """Parameter draws; seeded per (parameter, finding) so ranges are reproducible."""
        return self.p.draws(pid, N, seed=self.seed + (zlib.crc32(key.encode()) & 0xFFFF))

    def run(self, upto: float) -> list[Finding]:
        out: list[Finding] = []
        self._mf: MilestoneForecast | None = None
        for rule in (self.enrollment, self.query_backlog, self.overstock, self.shortfall, self.shipping,
                     self.monitoring, self.vendor, self.milestone):
            out.extend(rule(upto))
        return out

    def mf(self, upto: float) -> MilestoneForecast:
        if self._mf is None or self._mf.upto != upto:
            self._mf = forecast_milestones(self.plan, self.feed, upto, self.seed)
        return self._mf

    # ------------------------------------------------------------------------- enrollment
    def enrollment(self, upto: float) -> list[Finding]:
        plan, feed = self.plan, self.feed
        W = int(upto // 7)
        if W < 1:
            return []
        weekly = feed.weekly("enrolled", upto)
        cum = np.cumsum(weekly, axis=1)
        band = plan.site_band[:, 1: W + 1, :] if W < plan.site_band.shape[1] else plan.site_band[:, 1:, :]
        out: list[Finding] = []
        study_rate_day = sum(s.planned_rate_month for s in plan.sites) / DAYS_PER_MONTH
        for s in plan.sites:
            if s.backup or s.activation_day is None:
                continue
            active_weeks = (upto - s.activation_day) / 7
            n_now = int(cum[s.idx, -1])
            exposure_m = max(0.0, (upto - s.activation_day) / DAYS_PER_MONTH)
            planned_now = s.planned_rate_month * exposure_m
            if planned_now < ENR_NEVER_EXPECTED:
                continue
            ratio = n_now / planned_now if planned_now > 0 else 1.0
            k = min(ENR_CONSEC_WEEKS, W)
            below = bool(np.all(cum[s.idx, W - k: W] < band[s.idx, W - k: W, 0]))
            never = n_now == 0
            p_value = poisson_cdf(n_now, ENR_NULL_SHARE * planned_now)
            judged = planned_now >= ENR_MIN_EXPECTED
            present = never or (judged and ratio < ENR_RATIO_MAX and p_value < 5 * ENR_ALPHA)
            trigger = never or (judged and below and ratio < ENR_RATIO_MAX and p_value < ENR_ALPHA)
            if not present:
                continue
            p10, p50, p90 = band[s.idx, W - 1]
            key = f"enr:{s.id}"
            # posterior site rate (Gamma) -> patients the site will not deliver by the planned end
            rng = np.random.default_rng([self.seed, 11, s.idx])
            rate_draws = rng.gamma(0.5 + n_now, 1.0 / max(exposure_m, 1e-6), N)  # per month (Jeffreys)
            months_left = max(0.0, (plan.enrollment_end_day - upto) / DAYS_PER_MONTH)
            shortfall = np.clip(s.planned_rate_month - rate_draws, 0, None) * months_left
            delay_days = shortfall / max(study_rate_day, 1e-6)
            run_rate = self.d("ops.cost.trial_run_rate", key)
            impact = {"delay_days": delay_range(delay_days),
                      "cost_usd": mr(delay_days / DAYS_PER_MONTH * run_rate, "usd")}
            prov = {
                "delay_days": self.p.provenance(
                    "ops.impact.enrollment_lag.delay.v1",
                    "patients the site will not deliver by the planned enrollment end ÷ planned study "
                    "enrollment rate (if no other site compensates)",
                    {"enrolled": n_now, "planned_to_date": round(planned_now, 1),
                     "planned_rate_month": round(s.planned_rate_month, 2), "months_left": round(months_left, 1),
                     "study_rate_per_day": round(study_rate_day, 3)}, [],
                    ["site rate ~ Gamma(0.5 + n, exposure) (Jeffreys prior)",
                     "no compensation by other sites assumed"]),
                "cost_usd": self.p.provenance(
                    "ops.impact.enrollment_lag.cost.v1", "delay (months) × trial run-rate per month",
                    {"delay_days_p50": round(float(np.median(delay_days)), 1)}, ["ops.cost.trial_run_rate"]),
            }
            name = s.name
            if never:
                summary = (f"{name}: no patient enrolled after {active_weeks:.0f} weeks active "
                           f"(plan P50 {p50:.0f}).")
                recs = actions.recommended_texts("enrollment_lag_never")
            else:
                summary = (f"{name}: {n_now} enrolled vs plan P50 {p50:.0f} (P10 {p10:.0f}) — "
                           f"{ratio:.0%} of the planned rate.")
                recs = actions.recommended_texts("enrollment_lag")
            sev = "critical" if never or ratio < 0.25 else "warning"
            out.append(Finding("enrollment_lag", s.id, s.id, sev, trigger, summary, impact, prov, recs,
                               {"enrolled": n_now, "plan_p10": float(p10), "plan_p50": float(p50),
                                "plan_p90": float(p90), "ratio_to_plan": round(ratio, 3),
                                "p_value_vs_90pct_plan": round(p_value, 4)}))
        # study level
        sc = cum.sum(axis=0)
        sb = plan.study_band[1: W + 1]
        k = min(ENR_CONSEC_WEEKS, W)
        if W >= MS_MIN_WEEKS and np.all(sc[W - k: W] < sb[W - k: W, 0]):
            mf = self.mf(upto)
            delay = mf.lpi - plan.lpi_target_day
            run_rate = self.d("ops.cost.trial_run_rate", "enr:study")
            out.append(Finding(
                "enrollment_lag", "study", None, "critical", True,
                f"Study enrollment {int(sc[-1])} is below the plan P10 band ({sb[W - 1, 0]:.0f}) for "
                f"{k} weeks; last-patient-in forecast P50 day {np.median(mf.lpi):.0f} vs target "
                f"{plan.lpi_target_day}.",
                {"delay_days": delay_range(delay),
                 "cost_usd": mr(np.clip(delay, 0, None) / DAYS_PER_MONTH * run_rate, "usd")},
                {"delay_days": self.p.provenance("ops.impact.lpi_delay.v1",
                                                 "LPI forecast (Poisson–gamma from actuals) − LPI target",
                                                 {"enrolled": int(sc[-1])}, []),
                 "cost_usd": self.p.provenance("ops.impact.lpi_delay.cost.v1",
                                                "positive LPI delay months × trial run-rate", {},
                                                ["ops.cost.trial_run_rate"])},
                actions.recommended_texts("enrollment_lag"),
            ))
        return out

    # ------------------------------------------------------------------------- queries
    def query_backlog(self, upto: float) -> list[Finding]:
        feed = self.feed
        W = int(upto // 7)
        if W < QB_WINDOW_WEEKS:
            return []
        open_w = feed.open_queries_weekly(upto)[:, W - QB_WINDOW_WEEKS: W]
        counts, ages, age_site = feed.open_queries(upto)
        x = np.arange(QB_WINDOW_WEEKS) - (QB_WINDOW_WEEKS - 1) / 2
        out: list[Finding] = []
        for s in self.plan.sites:
            n_open = int(counts[s.idx])
            if n_open < QB_OPEN_MIN:
                continue
            a = ages[age_site == s.idx]
            med_age = float(np.median(a)) if len(a) else 0.0
            if med_age < QB_AGE_MIN:
                continue
            slope = float(np.dot(x, open_w[s.idx]) / np.dot(x, x))
            trigger = slope >= QB_SLOPE_MIN
            key = f"qb:{s.id}"
            minutes = self.d("ops.time.query_resolution", key)
            hourly = self.d("ops.cost.site_staff_hour", key)
            projected = n_open + max(slope, 0.0) * 12  # backlog in 12 weeks if the trend continues
            hours = projected * minutes / 60.0
            impact = {"site_staff_hours": mr(hours, "hours"), "cost_usd": mr(hours * hourly, "usd")}
            prov = {
                "site_staff_hours": self.p.provenance(
                    "ops.impact.query_backlog.hours.v1",
                    "(open queries + 12 weeks × backlog slope) × minutes per query ÷ 60",
                    {"open_queries": n_open, "slope_per_week": round(slope, 2), "median_age_days": round(med_age, 1)},
                    ["ops.time.query_resolution"], ["trend assumed to continue for 12 weeks"]),
                "cost_usd": self.p.provenance("ops.impact.query_backlog.cost.v1", "staff hours × loaded hourly cost",
                                              {}, ["ops.time.query_resolution", "ops.cost.site_staff_hour"]),
            }
            sev = "critical" if n_open >= 30 or med_age >= 60 else "warning"
            out.append(Finding(
                "query_backlog", s.id, s.id, sev, trigger,
                f"{s.name}: {n_open} open queries (median age {med_age:.0f} days), growing "
                f"{slope:+.1f}/week over {QB_WINDOW_WEEKS} weeks.",
                impact, prov, actions.recommended_texts("query_backlog"),
                {"open_queries": n_open, "median_age_days": round(med_age, 1), "slope_per_week": round(slope, 2)}))
        return out

    # ------------------------------------------------------------------------- drug supply
    def _dispense_rate(self, s_idx: int, upto: float, weeks: int) -> tuple[float, float]:
        key = (upto, weeks)
        cache = self.__dict__.setdefault("_disp_cache", {})
        if key not in cache:
            cache[key] = self.feed.per_site("dispensed", upto, upto - weeks * 7, field="kits")
        return float(cache[key][s_idx]), float(weeks)

    def overstock(self, upto: float) -> list[Finding]:
        feed = self.feed
        lots = feed.lots_on_hand(upto)
        first_rx = feed.per_site("received", upto, upto - OVER_MIN_HISTORY_DAYS, field="kits")
        all_rx = feed.per_site("received", upto, field="kits")
        out: list[Finding] = []
        for s in self.plan.sites:
            if all_rx[s.idx] - first_rx[s.idx] <= 0:  # no stock older than 8 weeks: rate not yet known
                continue
            site_lots = sorted(lots.get(s.idx, []), key=lambda x: x[2])
            on_hand = sum(q for _, q, _ in site_lots)
            if on_hand < OVER_PERSIST:
                continue
            kits, weeks = self._dispense_rate(s.idx, upto, OVER_RATE_WEEKS)
            rng = np.random.default_rng([self.seed, 13, s.idx])
            rate = rng.gamma(0.5 + kits, 1.0 / weeks, N) / 7.0  # kits per day
            used = np.zeros(N)
            waste = np.zeros(N)
            for _, q, exp in site_lots:
                cap = np.clip(rate * max(exp - upto, 0.0) - used, 0, None)
                use = np.minimum(q, cap)
                waste += q - use
                used += use
            w50 = float(np.median(waste))
            if w50 < OVER_PERSIST:
                continue
            trigger = w50 >= OVER_WASTE_MIN and w50 >= OVER_WASTE_SHARE * on_hand
            key = f"over:{s.id}"
            kit_cost = self.d("ops.cost.drug_kit", key)
            ef_kit = self.d("ops.ef.drug_kit_production", key)
            kit_kg = self.d("ops.ship.kit_kg", key)
            ef_road = self.d("ops.ef.freight_road_tkm", key)
            co2 = waste * (ef_kit + kit_kg / 1000.0 * s.road_km_to_hub * ef_road)
            impact = {"cost_usd": mr(waste * kit_cost, "usd"), "co2e_kg": mr(co2, "kg_co2e")}
            first_exp = self.plan.date(site_lots[0][2]).date().isoformat() if site_lots else "?"
            prov = {
                "cost_usd": self.p.provenance(
                    "ops.impact.drug_overstock.cost.v1",
                    "kits projected to expire (FEFO at the observed dispensing rate) × cost per kit",
                    {"kits_on_hand": on_hand, "kits_dispensed_last_8_weeks": kits, "waste_kits_p50": w50,
                     "first_expiry": first_exp}, ["ops.cost.drug_kit"],
                    ["dispensing rate ~ Gamma(0.5 + kits, weeks) (Jeffreys)",
                     "rate assumed constant until expiry (overstates waste if enrollment accelerates)"]),
                "co2e_kg": self.p.provenance(
                    "ops.impact.drug_overstock.co2e.v1",
                    "wasted kits × (production footprint + kg per kit × road km from depot × road freight EF)",
                    {"road_km_from_depot": round(s.road_km_to_hub, 0)},
                    ["ops.ef.drug_kit_production", "ops.ship.kit_kg", "ops.ef.freight_road_tkm"]),
            }
            sev = "critical" if w50 >= 25 or w50 >= 0.5 * on_hand else "warning"
            out.append(Finding(
                "drug_overstock", s.id, s.id, sev, trigger,
                f"{s.name}: {on_hand:.0f} kits on hand, {kits:.0f} dispensed in the last {OVER_RATE_WEEKS} weeks; "
                f"~{w50:.0f} kits projected to expire (first expiry {first_exp}).",
                impact, prov, actions.recommended_texts("drug_overstock"),
                {"kits_on_hand": on_hand, "waste_kits_p50": w50, "kits_dispensed_8w": kits}))
        return out

    def _lead_days(self, s_idx: int, upto: float) -> float:
        f = self.feed
        t = f.col("dispatched", "t")
        m = (f.col("dispatched", "s") == s_idx) & (t < upto)
        eta = f.col("dispatched", "eta")[m]
        tt = t[m]
        if not len(tt):
            return 8.0
        leads = np.ceil(eta - np.floor(tt))[-5:]
        return float(np.median(leads)) if len(leads) else 8.0

    def shortfall(self, upto: float) -> list[Finding]:
        feed = self.feed
        W = int(upto // 7)
        if W < SHORT_RATE_WEEKS + 2:
            return []
        out: list[Finding] = []
        short8 = feed.per_site("dispensed", upto, upto - 56, field="short")
        lots_now = feed.lots_on_hand(upto)
        transit = {t: feed.in_transit(t) for t in (upto - 14, upto - 7, upto)}
        for s in self.plan.sites:
            kits, weeks = self._dispense_rate(s.idx, upto, SHORT_RATE_WEEKS)
            if kits < 3:
                continue
            lead_w = self._lead_days(s.idx, upto) / 7.0
            low = 0
            wos_now = 0.0
            for back in (14, 7, 0):
                t = upto - back
                k2, _ = self._dispense_rate(s.idx, t, SHORT_RATE_WEEKS)
                stock = sum(q for _, q, _ in feed.lots_on_hand(t).get(s.idx, [])) + transit[t][s.idx]
                wos = stock / max(k2 / weeks, 1e-6)
                low += wos < lead_w + 0.5
                wos_now = wos
            stockouts = int(short8[s.idx])
            present = stockouts > 0 or wos_now < lead_w + 0.5
            if not present:
                continue
            trigger = stockouts > 0 or low >= 2
            key = f"short:{s.id}"
            cost = self.d("ops.cost.emergency_resupply", key)
            kit_kg = self.d("ops.ship.kit_kg", key)
            ef_air = self.d("ops.ef.freight_air_tkm", key)
            kits4 = kits / weeks * 4
            impact = {"cost_usd": mr(cost, "usd"),
                      "co2e_kg": mr(kits4 * kit_kg / 1000.0 * s.gc_km_to_hub * ef_air, "kg_co2e")}
            prov = {
                "cost_usd": self.p.provenance("ops.impact.drug_shortfall.cost.v1",
                                              "one emergency resupply shipment", {"stockouts_8w": stockouts},
                                              ["ops.cost.emergency_resupply"]),
                "co2e_kg": self.p.provenance(
                    "ops.impact.drug_shortfall.co2e.v1", "4 weeks of kits × kg per kit × air km × air freight EF",
                    {"kits_4_weeks": round(kits4, 1), "air_km": round(s.gc_km_to_hub, 0)},
                    ["ops.ship.kit_kg", "ops.ef.freight_air_tkm"]),
            }
            on_hand = sum(q for _, q, _ in lots_now.get(s.idx, []))
            out.append(Finding(
                "drug_shortfall", s.id, s.id, "critical" if stockouts else "warning", trigger,
                f"{s.name}: {wos_now:.1f} weeks of supply (on hand + in transit) vs observed resupply lead time "
                f"{lead_w * 7:.0f} days; {stockouts} kit(s) short at dispensing in the last 8 weeks.",
                impact, prov, actions.recommended_texts("drug_shortfall"),
                {"weeks_of_supply": round(wos_now, 2), "lead_time_days": round(lead_w * 7, 1),
                 "kits_short_8w": stockouts, "kits_on_hand": on_hand}))
        return out

    # ------------------------------------------------------------------------- shipping
    def shipping(self, upto: float) -> list[Finding]:
        feed = self.feed
        gmax = self.p.mid("ops.ship.ground_max_km")
        air = feed.col("sample", "air") > 0
        n_air8 = feed.per_site("sample", upto, upto - SHIP_WINDOW_WEEKS * 7, where=air)
        n_air4 = feed.per_site("sample", upto, upto - 28, where=air)
        n_all8 = feed.per_site("sample", upto, upto - SHIP_WINDOW_WEEKS * 7)
        out: list[Finding] = []
        for s in self.plan.sites:
            if s.road_km_to_hub > gmax or n_air4[s.idx] < 1:
                continue
            trigger = n_air8[s.idx] >= SHIP_MIN_AIR
            key = f"ship:{s.id}"
            per_week = n_air8[s.idx] / SHIP_WINDOW_WEEKS
            weeks_left = max(0.0, (self.plan.lplv_target_day - upto) / 7)
            n_future = per_week * weeks_left
            c_air, c_gr = self.d("ops.cost.courier_air", key), self.d("ops.cost.courier_ground", key)
            kg = self.d("ops.ship.specimen_package_kg", key)
            ef_air, ef_road = self.d("ops.ef.freight_air_tkm", key), self.d("ops.ef.freight_road_tkm", key)
            dco2 = n_future * kg / 1000.0 * (s.gc_km_to_hub * ef_air - s.road_km_to_hub * ef_road)
            impact = {"cost_usd": mr(n_future * (c_air - c_gr), "usd"), "co2e_kg": mr(dco2, "kg_co2e")}
            prov = {
                "cost_usd": self.p.provenance(
                    "ops.impact.shipping_mode.cost.v1",
                    "air shipments/week × weeks to planned last visit × (air − ground courier price)",
                    {"air_shipments_8w": float(n_air8[s.idx]), "weeks_left": round(weeks_left, 1),
                     "road_km": round(s.road_km_to_hub, 0), "ground_max_km": gmax},
                    ["ops.cost.courier_air", "ops.cost.courier_ground", "ops.ship.ground_max_km"]),
                "co2e_kg": self.p.provenance(
                    "ops.impact.shipping_mode.co2e.v1",
                    "future shipments × package kg × (air km × air EF − road km × road EF)",
                    {"air_km": round(s.gc_km_to_hub, 0), "road_km": round(s.road_km_to_hub, 0)},
                    ["ops.ship.specimen_package_kg", "ops.ef.freight_air_tkm", "ops.ef.freight_road_tkm",
                     "ops.dist.road_factor"]),
            }
            out.append(Finding(
                "costly_shipping_mode", s.id, s.id, "warning", trigger,
                f"{s.name}: {int(n_air8[s.idx])} of {int(n_all8[s.idx])} specimen shipments flown in "
                f"{SHIP_WINDOW_WEEKS} weeks although the central lab is ~{s.road_km_to_hub:.0f} km by road "
                f"(ground courier with dry ice is feasible up to {gmax:.0f} km).",
                impact, prov, actions.recommended_texts("costly_shipping_mode"),
                {"air_shipments_8w": int(n_air8[s.idx]), "road_km": round(s.road_km_to_hub, 0)}))
        return out

    # ------------------------------------------------------------------------- monitoring
    def monitoring(self, upto: float) -> list[Finding]:
        start = upto - MON_WINDOW_WEEKS * 7
        trips = [t for t in self.feed.trips if start <= t["t"] < upto and not t["remote"]]
        sites_by_cluster: dict[tuple[str, str], set[str]] = {}
        for s in self.plan.sites:
            sites_by_cluster.setdefault((s.country, s.city), set()).add(s.id)
        out: list[Finding] = []
        for cc in sorted({t["country"] for t in trips}):
            avoidable, km, modes, cities = 0, [], [], []
            for (c, city), ids in sites_by_cluster.items():
                if c != cc or len(ids) < 2:
                    continue
                ct = [t for t in trips if t["country"] == cc and t["city"] == city]
                if not ct:
                    continue
                visits: dict[str, int] = {}
                for t in ct:
                    for sid in t["site_ids"]:
                        visits[sid] = visits.get(sid, 0) + 1
                extra = len(ct) - max(visits.values())
                if extra > 0:
                    avoidable += extra
                    cities.append(city)
                    km += [t["km"] for t in ct]
                    modes += [t["mode"] for t in ct]
            if avoidable < 1:
                continue
            trigger = avoidable >= MON_AVOIDABLE_MIN
            key = f"mon:{cc}"
            months_left = max(0.0, (self.plan.lplv_target_day - upto) / DAYS_PER_MONTH)
            per_month = avoidable / (MON_WINDOW_WEEKS * 7 / DAYS_PER_MONTH)
            n_future = per_month * months_left
            avg_km = float(np.mean(km)) if km else 0.0
            mode = max(set(modes), key=modes.count) if modes else "car"
            from .metrics import TRIP_EF

            ef = self.d(TRIP_EF.get(mode, "ops.ef.car_km"), key)
            travel = self.d("ops.cost.monitoring_trip_travel", key)
            impact = {"cost_usd": mr(n_future * travel, "usd"), "co2e_kg": mr(n_future * avg_km * ef, "kg_co2e")}
            prov = {
                "cost_usd": self.p.provenance(
                    "ops.impact.monitoring.cost.v1",
                    "avoidable trips per month × months to planned last visit × travel cost per trip",
                    {"avoidable_trips_12w": avoidable, "months_left": round(months_left, 1)},
                    ["ops.cost.monitoring_trip_travel"],
                    ["avoidable = trips to a multi-site city − visits per site in that city (same 12 weeks)"]),
                "co2e_kg": self.p.provenance(
                    "ops.impact.monitoring.co2e.v1", "avoidable trips × average round-trip km × EF(mode)",
                    {"avg_round_trip_km": round(avg_km, 0), "mode": mode},
                    [TRIP_EF.get(mode, "ops.ef.car_km")]),
            }
            out.append(Finding(
                "monitoring_inefficiency", cc, None, "warning", trigger,
                f"{cc}: {avoidable} avoidable monitoring trip(s) in {MON_WINDOW_WEEKS} weeks — sites in "
                f"{', '.join(sorted(set(cities)))} visited on separate trips instead of one trip per city.",
                impact, prov, actions.recommended_texts("monitoring_inefficiency"),
                {"avoidable_trips_12w": avoidable, "cities": sorted(set(cities)), "country": cc}))
        return out

    # ------------------------------------------------------------------------- vendor + milestones
    def vendor(self, upto: float) -> list[Finding]:
        latest: dict[str, dict] = {}
        for r in self.feed.vendor:
            if r["t"] < upto:
                latest[r["milestone_id"]] = r
        out: list[Finding] = []
        for mid, r in sorted(latest.items()):
            slip = r["forecast_day"] - r["planned_day"]
            if r["status"] == "complete" or slip <= 7:
                continue
            trigger = slip > VENDOR_SLIP_MIN
            key = f"ven:{mid}"
            mf = self.mf(upto)
            delta = mf.dblock - mf.dblock_without_vendor if r.get("critical_path") else np.zeros(N)
            run_rate = self.d("ops.cost.trial_run_rate", key)
            impact = {"delay_days": delay_range(delta),
                      "cost_usd": mr(np.clip(delta, 0, None) / DAYS_PER_MONTH * run_rate[: len(delta)], "usd")}
            prov = {"delay_days": self.p.provenance(
                "ops.impact.vendor_delay.v1",
                "DB-lock forecast with the vendor's latest date − DB-lock forecast from enrollment alone",
                {"vendor": r["vendor"], "planned": r["planned_date"], "forecast": r["forecast_date"],
                 "slip_days": slip}, ["ops.time.db_lock_cleaning"]),
                    "cost_usd": self.p.provenance("ops.impact.vendor_delay.cost.v1",
                        "positive additional vendor delay months × trial run-rate", {},
                        ["ops.cost.trial_run_rate"])}
            sev = "critical" if r.get("critical_path") and slip > VENDOR_SLIP_CRITICAL else "warning"
            out.append(Finding(
                "vendor_delay", mid, None, sev, trigger,
                f"{r['vendor']}: '{r['milestone']}' now forecast {r['forecast_date']} vs planned "
                f"{r['planned_date']} (+{slip:.0f} days){' — on the database-lock critical path' if r.get('critical_path') else ''}.",
                impact, prov, actions.recommended_texts("vendor_delay"),
                {"slip_days": slip, "critical_path": bool(r.get("critical_path")), "vendor": r["vendor"]}))
        return out

    def milestone(self, upto: float) -> list[Finding]:
        plan = self.plan
        if upto < MS_MIN_WEEKS * 7:
            return []
        mf = self.mf(upto)
        p10, p50, p90 = mf.q("dblock")
        target = plan.dblock_target_day
        if p50 <= target + MS_TOLERANCE_DAYS:
            return []
        delay = mf.dblock - target
        run_rate = self.d("ops.cost.trial_run_rate", "ms:db_lock")
        vend = mf.vendor_path is not None and np.median(mf.dblock_without_vendor) < p50 - 1
        driver = (f"vendor '{mf.vendor_milestone['milestone']}' ({mf.vendor_milestone['vendor']})"
                  if vend and mf.vendor_milestone else "enrollment pace")
        impact = {"delay_days": delay_range(delay),
                  "cost_usd": mr(np.clip(delay, 0, None) / DAYS_PER_MONTH * run_rate, "usd")}
        prov = {
            "delay_days": self.p.provenance(
                "ops.impact.milestone.dblock.v1",
                "max(LPI forecast + treatment/follow-up + cleaning, vendor critical-path forecast + planned lag) "
                "− DB-lock target",
                {"target_day": target, "p50_day": round(p50, 0), "enrolled": mf.enrolled},
                ["ops.time.db_lock_cleaning"],
                ["LPI from A3 update_with_actuals with labelled operational plan parameters"]),
            "cost_usd": self.p.provenance("ops.impact.milestone.cost.v1", "delay months × trial run-rate",
                                          {}, ["ops.cost.trial_run_rate"]),
        }
        sev = "critical" if p10 > target else "warning"
        return [Finding(
            "milestone_at_risk", "db_lock", None, sev, True,
            f"Database lock forecast P50 {plan.date(p50).date()} (P10 {plan.date(p10).date()}, P90 "
            f"{plan.date(p90).date()}) vs target {plan.date(target).date()}: +{p50 - target:.0f} days. "
            f"Main driver: {driver}.",
            impact, prov, actions.recommended_texts("milestone_at_risk"),
            {"dblock_p10": p10, "dblock_p50": p50, "dblock_p90": p90, "target_day": target, "driver": driver})]
