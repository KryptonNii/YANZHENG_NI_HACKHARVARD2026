"""End-to-end smoke test of demo steps 2–3 against a RUNNING API (local, Docker or deployed).

    uv run --project api python api/scripts/smoke_demo.py --base http://127.0.0.1:8000

Stores a small design (or uses --design-id), computes with levers, saves + submits scenario B, shows
that the author cannot approve their own scenario, signs as reviewer and QA, checks the audit chain,
checks immutability, and downloads the CSV/PDF export. Exit code 0 = every step behaved as expected.
Demo PINs are A7's fictional demo values (override with --pins alex=1111,riley=2222,sam=3333).
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from typing import Any

import httpx

AUTHOR = {"X-User": "alex.author", "X-Role": "author"}
REVIEWER = {"X-User": "riley.reviewer", "X-Role": "reviewer"}
QA = {"X-User": "sam.qa", "X-Role": "qa"}

DESIGN: dict[str, Any] = {
    "source": "manual", "title": "Smoke-test trial (manual, not a real study)",
    "enrollment_target": 300, "duration_months": 24, "drug_type": "biologic",
    "sites": [{"id": "s1", "name": "Site 1", "country": "US"},
              {"id": "s2", "name": "Site 2", "country": "GB"}],
    "visits": [
        {"number": 1, "label": "Screening", "week": 0,
         "procedures": [{"code": "blood_draw", "label": "Blood draw", "ships_sample": True}]},
        {"number": 2, "label": "Week 12", "week": 12, "can_be_remote": True},
        {"number": 3, "label": "Week 24", "week": 24},
    ],
    "missing_fields": [],
}


class Smoke:
    def __init__(self, base: str) -> None:
        self.c = httpx.Client(base_url=base, timeout=60)
        self.failures = 0

    def check(self, label: str, ok: bool, detail: Any = "") -> bool:
        print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
        self.failures += 0 if ok else 1
        return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--design-id", help="use an existing design instead of storing the smoke design")
    ap.add_argument("--pins", default="alex.author=1111,riley.reviewer=2222,sam.qa=3333")
    args = ap.parse_args()
    pins = dict(kv.split("=", 1) for kv in args.pins.split(","))
    s = Smoke(args.base)
    c = s.c

    h = c.get("/api/health").json()
    s.check("health", h.get("status") == "ok",
            f"offline={h.get('offline')} engine={h['engine'].get('ready')} "
            f"params={h['params'].get('count')} compliance={h['compliance'].get('audit')}")

    design_id = args.design_id
    if not design_id:
        design_id = f"smoke-{uuid.uuid4().hex[:8]}"
        r = c.post("/api/designs", headers=AUTHOR, json={**DESIGN, "id": design_id})
        s.check("store design", r.status_code == 201, r.status_code)

    levers = {"remote_monitoring_share": 0.5, "drug_supply_strategy": "on_demand"}
    t = time.perf_counter()
    r = c.post("/api/scenarios/compute", json={"design_id": design_id, "levers": levers})
    wall = (time.perf_counter() - t) * 1000
    if not s.check("compute", r.status_code == 200, f"{r.status_code} {r.text[:200]}"
                   if r.status_code != 200 else
                   f"X-Compute-Ms={r.headers.get('x-compute-ms')} wall={wall:.0f} ms "
                   f"cache={r.headers.get('x-cache')}"):
        return 1
    res = r.json()
    unknown = [m for m in ("cost_usd", "site_staff_hours", "patient_travel_hours", "co2e_kg")
               if res[m]["p50"] is None]
    print(f"       cost P50={res['cost_usd']['p50']}  co2e P50={res['co2e_kg']['p50']}  "
          f"unknown={unknown}  warnings={len(res['warnings'])}")
    r2 = c.post("/api/scenarios/compute", json={"design_id": design_id, "levers": levers})
    s.check("cache hit on identical request", r2.headers.get("x-cache") == "hit")

    r = c.post("/api/scenarios", headers=AUTHOR,
               json={"name": "Scenario B (smoke)", "design_id": design_id, "levers": levers})
    s.check("save scenario", r.status_code == 201, r.status_code)
    sid = r.json()["id"]
    r = c.post(f"/api/scenarios/{sid}/submit", headers=AUTHOR)
    s.check("submit", r.status_code == 200 and r.json()["status"] == "submitted", r.status_code)
    aid = r.json().get("approval_id")

    def sign(who: dict[str, str], meaning: str) -> httpx.Response:
        return c.post(f"/api/approvals/{aid}/sign", headers=who,
                      json={"meaning": meaning, "pin": pins[who["X-User"]]})

    r = sign(AUTHOR, "reviewed")
    s.check("author cannot approve own scenario", r.status_code == 403,
            r.json().get("error"))
    s.check("reviewer signs 'reviewed'", sign(REVIEWER, "reviewed").status_code == 200)
    s.check("QA signs 'approved'", sign(QA, "approved").status_code == 200)
    final = c.get(f"/api/scenarios/{sid}").json()
    s.check("scenario approved", final["status"] == "approved",
            [(x["signer"], x["meaning"]) for x in (final.get("approval") or {}).get("signatures", [])])
    v = c.get("/api/audit/verify").json()
    s.check("audit chain verifies", v.get("ok") is True, v)
    r = c.patch(f"/api/scenarios/{sid}", headers=AUTHOR, json={"name": "changed"})
    s.check("approved scenario immutable", r.status_code == 409, r.json().get("error"))
    r = c.post(f"/api/scenarios/{sid}/versions", headers=AUTHOR, json={"levers": {}})
    s.check("new version instead", r.status_code == 201 and r.json()["version"] == 2)
    r = c.get(f"/api/export/scenario/{sid}.pdf")
    s.check("PDF export", r.status_code == 200 and r.content[:5] == b"%PDF-", len(r.content))
    r = c.get(f"/api/export/scenario/{sid}.csv")
    s.check("CSV export", r.status_code == 200 and "signature," in r.text,
            f"{len(r.text.splitlines())} rows")
    print(f"\n{'OK' if s.failures == 0 else f'{s.failures} FAILURE(S)'}")
    return 0 if s.failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
