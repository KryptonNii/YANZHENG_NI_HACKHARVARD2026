"""Columnar view of the ops feed + weekly per-unit series.

Built only from feed events (the same information a real command center receives); every query takes an
``upto`` day so detection and effect estimation never look past the simulated clock.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

import numpy as np

from .params import OpsParams
from .plan import WEEKS_PER_MONTH, OpsPlan


def _arr(x: list, dtype=float) -> np.ndarray:
    return np.asarray(x, dtype=dtype)


@dataclass
class MetricDef:
    id: str
    label: str
    unit: str  # MetricRange unit literal
    level: str  # site | country
    better: str  # up | down
    kind: str  # rate (num/den*scale) | count (mean per unit-week * scale) | level (mean of levels)
    scale: float
    abs_floor: float  # smallest change we call meaningful (for "no_effect")
    description: str


METRICS: dict[str, MetricDef] = {
    m.id: m
    for m in [
        MetricDef("enrollment_rate_per_month", "Enrollment rate per site", "patients", "site", "up", "count",
                  WEEKS_PER_MONTH, 0.3, "patients enrolled per active site-month"),
        MetricDef("regional_enrollment_rate_per_month", "Enrollment rate per country", "patients", "country",
                  "up", "count", WEEKS_PER_MONTH, 1.0, "patients enrolled per country-month"),
        MetricDef("query_rate_percent", "Query rate", "percent", "site", "down", "rate", 100.0, 5.0,
                  "data queries opened per 100 completed visits"),
        MetricDef("missed_visit_rate_percent", "Missed-visit rate", "percent", "site", "down", "rate", 100.0,
                  3.0, "missed visits per 100 scheduled post-baseline visits"),
        MetricDef("kits_on_hand", "Drug kits on hand", "kits", "site", "down", "level", 1.0, 3.0,
                  "kits at the site at the end of each week"),
        MetricDef("air_shipment_share_percent", "Specimen shipments by air", "percent", "site", "down", "rate",
                  100.0, 10.0, "air shipments per 100 specimen shipments"),
        MetricDef("monitoring_co2e_kg_per_month", "Monitoring travel CO2e", "kg_co2e", "country", "down",
                  "count", WEEKS_PER_MONTH, 50.0, "monitoring-trip kg CO2e per country-month (EF mid values)"),
    ]
}

TRIP_EF = {"car": "ops.ef.car_km", "rail": "ops.ef.rail_pkm", "flight": "ops.ef.flight_pkm"}


class Feed:
    def __init__(self, plan: OpsPlan, events: Iterable, params: OpsParams):
        self.plan = plan
        self.params = params
        self.sidx = plan.site_index()
        self.S = len(plan.sites)
        self.countries = sorted({s.country for s in plan.sites})
        self.cidx = {c: i for i, c in enumerate(self.countries)}
        self.site_country = np.array([self.cidx[s.country] for s in plan.sites])
        ef = {m: params.mid(p) for m, p in TRIP_EF.items()}
        cols: dict[str, dict[str, list]] = {}

        def add(name: str, **kw) -> None:
            c = cols.setdefault(name, {k: [] for k in kw})
            for k, v in kw.items():
                c[k].append(v)

        q_open: dict[str, tuple[float, int]] = {}
        q_close: dict[str, float] = {}
        self.lot_events: list[tuple[float, int, str, float, float]] = []  # (t, site, lot, delta, expiry_day)
        self.trips: list[dict] = []
        self.vendor: list[dict] = []
        self.spend: list[tuple[float, int, int, str, float]] = []  # (t, site|-1, country|-1, category, usd)
        for e in events:
            t = e.t
            s = self.sidx.get(e.site_id, -1) if e.site_id else -1
            p = e.payload
            typ = e.type
            if typ == "patient_enrolled":
                add("enrolled", t=t, s=s)
            elif typ == "patient_withdrawn":
                add("withdrawn", t=t, s=s)
            elif typ == "visit_completed":
                add("visit", t=t, s=s, minutes=p.get("site_minutes", 0.0), onsite=p.get("mode") == "on_site",
                    followup=float(p.get("week", 1.0)) > 0)
            elif typ == "visit_missed":
                add("missed", t=t, s=s)
            elif typ == "query_opened":
                q_open[p["query_id"]] = (t, s)
            elif typ == "query_closed":
                q_close[p["query_id"]] = t
            elif typ == "drug_dispensed":
                add("dispensed", t=t, s=s, kits=p["kits"], short=p.get("kits_short", 0))
                for lot in p.get("lots", []):
                    self.lot_events.append((t, s, lot["lot_id"], -lot["kits"], np.nan))
            elif typ == "drug_shipment":
                if p["direction"] == "inbound" and p["status"] == "received":
                    exp = _day(plan, p["expiry_date"])
                    add("received", t=t, s=s, kits=p["kits"])
                    self.lot_events.append((t, s, p["lot_id"], p["kits"], exp))
                elif p["direction"] == "inbound":
                    add("dispatched", t=t, s=s, kits=p["kits"], eta=_day(plan, p["eta"]),
                        emergency=p.get("reason") == "emergency", air=p["mode"] == "air",
                        km=p["distance_km"], kg=p["weight_kg"])
                else:
                    add("outbound", t=t, s=s, kits=p["kits"], km=p["distance_km"], kg=p["weight_kg"])
                    for lot in p.get("lots", []):
                        self.lot_events.append((t, s, lot["lot_id"], -lot["kits"], np.nan))
            elif typ == "drug_expired":
                add("expired", t=t, s=s, kits=p["kits"])
                self.lot_events.append((t, s, p["lot_id"], -p["kits"], np.nan))
            elif typ == "sample_shipment":
                add("sample", t=t, s=s, air=p["mode"] == "air", km=p["distance_km"], kg=p["weight_kg"],
                    frozen=str(p["temp"]).startswith("frozen"))
            elif typ == "monitoring_trip":
                km = float(p["round_trip_km"])
                co2 = 0.0 if p.get("remote") else km * ef.get(p["mode"], ef["car"])
                trip = {"t": t, "country": p["country"], "city": p["city"], "site_ids": p["site_ids"],
                        "mode": p["mode"], "km": km, "site_days": p["site_days"], "remote": p.get("remote")}
                self.trips.append(trip)
                add("trip", t=t, c=self.cidx.get(p["country"], 0), co2=co2, km=km,
                    remote=bool(p.get("remote")), site_days=p["site_days"])
            elif typ == "vendor_milestone":
                self.vendor.append({"t": t, **p, "planned_day": _day(plan, p["planned_date"]),
                                    "forecast_day": _day(plan, p["forecast_date"])})
            elif typ == "budget_spend":
                c = self.cidx.get(p.get("country", ""), -1)
                self.spend.append((t, s, c, p["category"], float(p["amount_usd"])))
        self.c: dict[str, dict[str, np.ndarray]] = {
            name: {k: _arr(v) for k, v in col.items()} for name, col in cols.items()
        }
        qid = sorted(q_open)
        self.q_open_t = _arr([q_open[q][0] for q in qid])
        self.q_site = _arr([q_open[q][1] for q in qid], int)
        self.q_close_t = _arr([q_close.get(q, np.inf) for q in qid])

    # ------------------------------------------------------------------ basic accessors
    def col(self, name: str, field: str) -> np.ndarray:
        return self.c.get(name, {}).get(field, np.zeros(0))

    def mask(self, name: str, upto: float, start: float = -np.inf) -> np.ndarray:
        t = self.col(name, "t")
        return (t < upto) & (t >= start)

    def per_site(self, name: str, upto: float, start: float = -np.inf, field: str | None = None,
                 where: np.ndarray | None = None) -> np.ndarray:
        m = self.mask(name, upto, start)
        if where is not None:
            m = m & where
        s = self.col(name, "s").astype(int)[m]
        w = None if field is None else self.col(name, field)[m]
        ok = s >= 0
        return np.bincount(s[ok], weights=None if w is None else w[ok], minlength=self.S)[: self.S]

    def weekly(self, name: str, upto: float, field: str | None = None,
               where: np.ndarray | None = None) -> np.ndarray:
        """[S, W] weekly sums for complete weeks before `upto`."""
        W = int(upto // 7)
        out = np.zeros((self.S, max(W, 0)))
        if W <= 0:
            return out
        m = self.mask(name, W * 7.0)
        if where is not None:
            m = m & where
        s = self.col(name, "s").astype(int)[m]
        wk = (self.col(name, "t")[m] // 7).astype(int)
        w = np.ones(len(s)) if field is None else self.col(name, field)[m]
        ok = s >= 0
        np.add.at(out, (s[ok], wk[ok]), w[ok])
        return out

    # ------------------------------------------------------------------ derived quantities
    def open_queries(self, upto: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Open queries per site, plus the age (days) and site of every open query, as of `upto`."""
        m = (self.q_open_t < upto) & (self.q_close_t >= upto)
        counts = np.bincount(self.q_site[m], minlength=self.S)[: self.S]
        return counts, upto - self.q_open_t[m], self.q_site[m]

    def open_queries_weekly(self, upto: float) -> np.ndarray:
        W = int(upto // 7)
        ends = (np.arange(W) + 1) * 7.0
        out = np.zeros((self.S, W))
        for s in range(self.S):
            m = self.q_site == s
            if not m.any():
                continue
            o, c = np.sort(self.q_open_t[m]), np.sort(self.q_close_t[m])
            out[s] = np.searchsorted(o, ends) - np.searchsorted(c, ends)
        return out

    def _lot_arrays(self) -> None:
        if hasattr(self, "_lot_t"):
            return
        keys: dict[tuple[int, str], int] = {}
        t, k, dlt = [], [], []
        self._lot_exp: list[float] = []
        self._lot_site: list[int] = []
        self._lot_id: list[str] = []
        for ti, s, lot, delta, e in self.lot_events:
            key = (s, lot)
            if key not in keys:
                keys[key] = len(keys)
                self._lot_exp.append(np.nan)
                self._lot_site.append(s)
                self._lot_id.append(lot)
            if not np.isnan(e):
                self._lot_exp[keys[key]] = e
            t.append(ti)
            k.append(keys[key])
            dlt.append(delta)
        self._lot_t, self._lot_k, self._lot_d = _arr(t), _arr(k, int), _arr(dlt)
        self._lot_cache: dict[float, dict[int, list[tuple[str, float, float]]]] = {}

    def lots_on_hand(self, upto: float) -> dict[int, list[tuple[str, float, float]]]:
        """Per site: [(lot_id, kits, expiry_day)] on hand as of `upto` (received - used - moved - expired)."""
        self._lot_arrays()
        if upto in self._lot_cache:
            return self._lot_cache[upto]
        m = self._lot_t < upto
        qty = np.bincount(self._lot_k[m], weights=self._lot_d[m], minlength=len(self._lot_exp))
        out: dict[int, list[tuple[str, float, float]]] = {}
        for i in np.nonzero(qty > 0.5)[0]:
            e = self._lot_exp[i]
            if not np.isnan(e):
                out.setdefault(self._lot_site[i], []).append((self._lot_id[i], float(qty[i]), e))
        if len(self._lot_cache) > 64:
            self._lot_cache.clear()
        self._lot_cache[upto] = out
        return out

    def kits_on_hand_weekly(self, upto: float) -> np.ndarray:
        W = int(upto // 7)
        rec = self.weekly("received", upto, "kits")
        disp = self.weekly("dispensed", upto, "kits")
        out_ = self.weekly("outbound", upto, "kits")
        exp_ = self.weekly("expired", upto, "kits")
        return np.cumsum(rec - disp - out_ - exp_, axis=1)[:, :W]

    def in_transit(self, upto: float) -> np.ndarray:
        """Inbound kits dispatched but not yet received, per site."""
        sent = self.per_site("dispatched", upto, field="kits")
        return np.clip(sent - self.per_site("received", upto, field="kits"), 0, None)

    def country_weekly(self, site_weekly: np.ndarray) -> np.ndarray:
        out = np.zeros((len(self.countries), site_weekly.shape[1]))
        np.add.at(out, self.site_country, site_weekly)
        return out

    def trips_weekly(self, upto: float, field: str = "co2") -> np.ndarray:
        W = int(upto // 7)
        out = np.zeros((len(self.countries), W))
        m = self.mask("trip", W * 7.0)
        c = self.col("trip", "c").astype(int)[m]
        wk = (self.col("trip", "t")[m] // 7).astype(int)
        np.add.at(out, (c, wk), self.col("trip", field)[m])
        return out

    def site_active_weeks(self, upto: float) -> np.ndarray:
        """[S, W] 1 where the site was open for enrollment for the whole week (plan activation or first
        enrollment for backup sites)."""
        W = int(upto // 7)
        starts = np.full(self.S, np.inf)
        first = {}
        t, s = self.col("enrolled", "t"), self.col("enrolled", "s").astype(int)
        for ti, si in zip(t[t < upto], s[t < upto], strict=True):
            first.setdefault(si, ti)
        for site in self.plan.sites:
            if site.activation_day is not None:
                starts[site.idx] = site.activation_day
            elif site.idx in first:
                starts[site.idx] = first[site.idx]
        wk_start = np.arange(W) * 7.0
        return (wk_start[None, :] >= starts[:, None]).astype(float)

    # ------------------------------------------------------------------ DiD series
    def series(self, metric: str, upto: float) -> tuple[np.ndarray, np.ndarray, list[str]]:
        """Weekly (numerator, denominator) per unit for a metric, plus unit ids."""
        md = METRICS[metric]
        active = self.site_active_weeks(upto)
        if metric == "enrollment_rate_per_month":
            return self.weekly("enrolled", upto) * active, active, [s.id for s in self.plan.sites]
        if metric == "regional_enrollment_rate_per_month":
            num = self.country_weekly(self.weekly("enrolled", upto))
            den = (self.country_weekly(active) > 0).astype(float)
            return num * den, den, list(self.countries)
        if metric == "query_rate_percent":
            return self.weekly_opened(upto), self.weekly("visit", upto), [s.id for s in self.plan.sites]
        if metric == "missed_visit_rate_percent":  # post-baseline visits (screening/baseline cannot be missed)
            miss = self.weekly("missed", upto)
            done = self.weekly("visit", upto, where=self.col("visit", "followup") > 0)
            return miss, miss + done, [s.id for s in self.plan.sites]
        if metric == "kits_on_hand":
            lvl = self.kits_on_hand_weekly(upto)
            has = (np.cumsum(self.weekly("received", upto, "kits"), axis=1) > 0).astype(float)
            return lvl * has, has, [s.id for s in self.plan.sites]
        if metric == "air_shipment_share_percent":
            air = self.weekly("sample", upto, where=self.col("sample", "air") > 0)
            return air, self.weekly("sample", upto), [s.id for s in self.plan.sites]
        if metric == "monitoring_co2e_kg_per_month":
            num = self.trips_weekly(upto, "co2")
            den = (self.country_weekly(active) > 0).astype(float)
            return num * den, den, list(self.countries)
        raise KeyError(md.id)

    def weekly_opened(self, upto: float) -> np.ndarray:
        W = int(upto // 7)
        out = np.zeros((self.S, W))
        m = self.q_open_t < W * 7.0
        np.add.at(out, (self.q_site[m], (self.q_open_t[m] // 7).astype(int)), 1.0)
        return out


def _day(plan: OpsPlan, iso: str) -> float:
    d = date.fromisoformat(iso[:10])
    return float((d - plan.epoch.date()).days)
