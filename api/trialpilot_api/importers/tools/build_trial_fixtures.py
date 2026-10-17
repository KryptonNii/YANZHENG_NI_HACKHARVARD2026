"""Regenerate the golden mapped designs `data/fixtures/trials/<NCT>.json` from the cached raw studies.

Each file is the TrialDesign the importer produces offline, plus a sibling `<NCT>.report.json` with
the import notes (assumptions, sources, attribution). Run after an intentional mapping change:

    uv run --project api python -m trialpilot_api.importers.tools.build_trial_fixtures
"""

from __future__ import annotations

import json
from dataclasses import asdict

from trialpilot_api.importers.ctgov import cached_study_ids, fetch_study_result, map_study_report
from trialpilot_api.importers.paths import fixtures_dir


def main() -> None:
    out = fixtures_dir() / "trials"
    out.mkdir(parents=True, exist_ok=True)
    for nct in cached_study_ids():
        res = fetch_study_result(nct, offline=True)
        rep = map_study_report(res.raw, meta=res.meta)
        (out / f"{nct}.json").write_text(rep.design.model_dump_json(indent=1), encoding="utf-8", newline="\n")
        report = {k: v for k, v in asdict(rep).items() if k != "design"}
        (out / "reports").mkdir(exist_ok=True)  # subfolder: A5 seeds every trials/*.json as a design
        (out / "reports" / f"{nct}.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8",
                                                 newline="\n")
        d = rep.design
        print(f"{nct}: {d.title[:60]} | {len(d.sites)} sites | {len(d.visits)} visits | missing {d.missing_fields}")


if __name__ == "__main__":
    main()
