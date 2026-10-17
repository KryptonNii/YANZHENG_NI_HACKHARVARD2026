"""Cold HTTP benchmark with isolated state, distinct seeds and optional profiling.

Run with an interpreter containing the API dependencies. No warmup or discarded
samples; caches start empty and each seed has its own forecast/supply cache key.
"""
from __future__ import annotations

import argparse
import cProfile
import json
import os
import statistics
import subprocess
import tempfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", action="store_true")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    args.output.mkdir(parents=True, exist_ok=False)
    from fastapi.testclient import TestClient
    from trialpilot_api.engine_adapter import EngineFns, load_engine
    from trialpilot_api.main import create_app
    from trialpilot_api.settings import Settings

    with tempfile.TemporaryDirectory(prefix="tp-backend-") as tmp:
        root = Path(tmp)
        os.environ.update(TP_COMPLIANCE_DB=str(root / "compliance.sqlite"),
                          TP_VALIDATION_OUT=str(root / "validation"),
                          TP_SECRET_PEPPER="isolated-benchmark-demo", DEMO_OFFLINE="1")
        fns = load_engine()
        producer_counts: dict[str, int] = {}
        for name in ("forecast", "simulate_supply"):
            fn = getattr(fns, name)

            def measured(*a, _fn=fn, _name=name, **kw):
                result = _fn(*a, **kw)
                view = result.to_dict()
                for field in ("draws_requested", "draws_used", "curve_draws_used"):
                    value = view.get(field)
                    if value is not None:
                        producer_counts[f"{_name}.{field}"] = value
                return result

            setattr(fns, name, measured)
        # Profile the worker thread that executes the real sync route.
        profiler = cProfile.Profile()
        assert isinstance(fns, EngineFns)
        app = create_app(Settings(
            db_path=root / "api.sqlite", params_dir=repo / "data/params",
            fixtures_dir=repo / "data/fixtures", science_results_path=root / "results.json",
            web_dist_dir=root / "dist", seed_fixture_designs=False,
            demo_offline=True, log_json=False, log_level="WARNING",
        ), engine_fns=fns)
        if args.profile:
            compute = app.state.services.engine.compute

            def profiled(*a, **kw):
                return profiler.runcall(compute, *a, **kw)

            app.state.services.engine.compute = profiled
        rows = []
        with TestClient(app) as client:
            author = {"X-User": "alex.author", "X-Role": "author"}
            imported = client.post("/api/import/ctgov/NCT03930732", headers=author)
            imported.raise_for_status()
            design = imported.json()["design"]
            saved = client.post("/api/designs", json=design, headers=author)
            saved.raise_for_status()
            for seed in range(200, 207):
                response = client.post("/api/scenarios/compute", json={
                    "design_id": design["id"], "design_version": 1,
                    "levers": {}, "seed": seed, "draws": 2000,
                })
                response.raise_for_status()
                assert response.headers["X-Cache"] == "miss"
                rows.append({"seed": seed, "draws_requested": 2000, "cache": "miss",
                             "compute_ms": float(response.headers["X-Compute-Ms"]),
                             "queue_ms": float(response.headers["X-Queue-Ms"]),
                             **producer_counts})
                print(json.dumps(rows[-1]), flush=True)
        app.state.db_engine.dispose()
        from trialpilot_api.compliance import store
        store.get_store().close()
    if args.profile:
        profiler.dump_stats(str(args.output / "engine.prof"))
    result = {"head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo,
                                               text=True).strip(),
              "profiled": args.profile, "samples": rows,
              "dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=repo)),
              "median_ms": statistics.median(row["compute_ms"] for row in rows),
              "threshold_ms": 300, "all_samples_kept": True}
    (args.output / "benchmark.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
