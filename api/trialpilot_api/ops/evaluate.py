"""Reproducible evaluation against withheld simulator truth (never used for detection)."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from . import audit
from .fixtures import load_demo_design
from .params import ops_data_dir
from .store import TrialState


def evaluate_state(st):
    detection = []
    for problem in st.sim.ground_truth["problems"]:
        days = [meta["first_day"] for aid, meta in st.alert_meta.items()
                if st.alerts[aid].kind == problem["kind"] and meta["scope"] == problem["scope"]
                and meta["first_day"] >= problem["onset_day"]]
        first = min(days) if days else None
        deadline = problem["onset_day"] + problem["detect_within_days"]
        detection.append({"problem": problem["id"], "kind": problem["kind"],
                          "first_alert_day": first, "deadline_day": deadline,
                          "detected_in_time": first is not None and first <= deadline})
    effects = []
    for truth in st.sim.ground_truth["interventions"]:
        ids = [iv_id for iv_id, meta in st.iv_meta.items() if meta.label == truth["id"]]
        actual = st.effect(ids[0]).estimate.verdict if ids else "not_started"
        effects.append({"intervention": truth["id"], "expected": truth["expected_verdict"],
                        "actual": actual, "correct": actual == truth["expected_verdict"]})
    return {"seed": st.seed, "clock_day": st.clock_day, "simulated": True,
            "detection": detection, "effects": effects}


def evaluate(seeds=(42, 7, 19), day=599):
    reports, matrix = [], defaultdict(Counter)
    with audit.bound(lambda **kwargs: None):
        for seed in seeds:
            st = TrialState("demo-40", load_demo_design(), None, seed, 0, "demo", day, 600,
                            audit_sink=lambda **kwargs: None)
            report = evaluate_state(st)
            reports.append(report)
            for row in report["effects"]:
                matrix[row["expected"]][row["actual"]] += 1
    detections = [r for report in reports for r in report["detection"]]
    effects = [r for report in reports for r in report["effects"]]
    return {"simulated": True, "evaluation_day": day, "seeds": list(seeds),
            "detection_passed": sum(r["detected_in_time"] for r in detections),
            "detection_total": len(detections), "verdicts_correct": sum(r["correct"] for r in effects),
            "verdicts_total": len(effects),
            "confusion_matrix": {k: dict(v) for k, v in matrix.items()}, "runs": reports}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", nargs="+", type=int, default=[42, 7, 19])
    parser.add_argument("--day", type=int, default=599)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--write-ground-truth", action="store_true")
    args = parser.parse_args()
    report = evaluate(args.seeds, args.day)
    if args.write_ground_truth:
        st = TrialState("demo-40", load_demo_design(), None, 42, 0, "demo", 0, 600,
                        audit_sink=lambda **kwargs: None)
        (ops_data_dir() / "ground_truth.json").write_text(
            json.dumps(st.sim.ground_truth, indent=2) + "\n", encoding="utf-8")
    data = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(data, encoding="utf-8")
    print(data)


if __name__ == "__main__":
    main()
