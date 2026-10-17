"""Load test for POST /api/scenarios/compute against a RUNNING API (asyncio + httpx).

    uv run --project api python api/scripts/loadtest.py --base http://127.0.0.1:8005 \
        --large --requests 200 --concurrency 8          # or --design-id <stored design>

Three phases:
  cold    every request has a new seed: A3 forecast + supply AND A2 engine run every time;
  slider  same seed, remote_monitoring_share changes every request (a slider drag): A2 runs,
          A3 results come from the cache (A3 does not read that lever);
  hits    the identical request repeated: full result cache hits.
Reports server-side X-Compute-Ms and client wall time percentiles. Numbers depend on the machine;
record them with the machine spec.
"""

from __future__ import annotations

import argparse
import asyncio
import platform
import random
import statistics
import time
import uuid
from typing import Any

import httpx


def pct(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    k = min(len(s) - 1, max(0, round(q / 100 * (len(s) - 1))))
    return s[k]


def large_design() -> dict[str, Any]:
    """SYNTHETIC load-test design (not a real trial): 120 sites, 900 patients, 12 visits —
    the size of the engine's < 300 ms performance target (MASTER §9 A2)."""
    countries = ["US", "GB", "DE", "FR", "ES", "IT", "CA", "PL", "JP", "AU"]
    procs = [{"code": "blood_draw", "label": "Blood draw", "ships_sample": True,
              "sample_temp": "frozen_-80"}, {"code": "ecg", "label": "ECG"},
             {"code": "vital_signs", "label": "Vital signs"}]
    return {
        "id": f"loadtest-large-{uuid.uuid4().hex[:6]}", "source": "manual",
        "title": "SYNTHETIC load-test design (120 sites, 900 patients, 12 visits)",
        "enrollment_target": 900, "duration_months": 30, "drug_type": "biologic",
        "sites": [{"id": f"s{i}", "name": f"Synthetic site {i}", "country": countries[i % 10],
                   "expected_enrollment": 7.5} for i in range(120)],
        "visits": [{"number": v, "label": f"Visit {v}", "week": 4 * (v - 1), "procedures": procs,
                    "can_be_remote": v not in (1, 12)} for v in range(1, 13)],
        "missing_fields": [],
    }


async def phase(base: str, design_id: str, n: int, conc: int, mode: str,
                draws: int) -> tuple[list[float], list[float], int]:
    server_ms: list[float] = []
    wall_ms: list[float] = []
    errors = 0
    sem = asyncio.Semaphore(conc)
    seed_base = random.randrange(10**6, 10**9)  # fresh seeds: "cold" really misses every cache
    slider_base = random.random()  # fresh lever values: "slider" misses the result cache
    async with httpx.AsyncClient(base_url=base, timeout=120) as c:
        async def one(i: int) -> None:
            nonlocal errors
            share = {"cold": 0.5, "slider": (slider_base + i / n) % 1.0, "hits": 0.5}[mode]
            body = {"design_id": design_id, "draws": draws,
                    "seed": (seed_base + i) if mode == "cold" else 7,
                    "levers": {"remote_monitoring_share": round(share, 6)}}
            async with sem:
                t = time.perf_counter()
                r = await c.post("/api/scenarios/compute", json=body)
                wall_ms.append((time.perf_counter() - t) * 1000)
            if r.status_code != 200:
                errors += 1
                return
            server_ms.append(float(r.headers["x-compute-ms"]))

        t0 = time.perf_counter()
        await asyncio.gather(*(one(i) for i in range(n)))
        elapsed = time.perf_counter() - t0
    print(f"    throughput {n / elapsed:.1f} req/s over {elapsed:.1f} s")
    return server_ms, wall_ms, errors


def report(name: str, server: list[float], wall: list[float], errors: int) -> None:
    print(f"  {name}: n={len(wall)} errors={errors}")
    print(f"    X-Compute-Ms  P50 {pct(server, 50):7.1f}  P95 {pct(server, 95):7.1f}  "
          f"max {max(server, default=float('nan')):7.1f}")
    print(f"    wall ms       P50 {pct(wall, 50):7.1f}  P95 {pct(wall, 95):7.1f}  "
          f"mean {statistics.fmean(wall) if wall else float('nan'):7.1f}")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--design-id", help="stored design to use")
    ap.add_argument("--large", action="store_true", help="store + use a synthetic 120-site design")
    ap.add_argument("--requests", type=int, default=100)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--draws", type=int, default=2000)
    args = ap.parse_args()
    if args.large:
        d = large_design()
        r = httpx.post(f"{args.base}/api/designs", json=d,
                       headers={"X-User": "alex.author", "X-Role": "author"}, timeout=60)
        r.raise_for_status()
        args.design_id = d["id"]
    if not args.design_id:
        ap.error("--design-id or --large is required")
    print(f"machine: {platform.platform()} / {platform.processor() or platform.machine()}")
    print(f"target {args.base}, design {args.design_id}, {args.requests} requests, "
          f"concurrency {args.concurrency}, {args.draws} draws")
    for mode in ("cold", "slider", "hits"):
        print(f"  phase {mode}:")
        report(mode, *await phase(args.base, args.design_id, args.requests, args.concurrency,
                                  mode, args.draws))


if __name__ == "__main__":
    asyncio.run(main())
