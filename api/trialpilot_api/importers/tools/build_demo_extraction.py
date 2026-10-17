"""Turn a stored SoA transcription (data/fixtures/protocols/<NCT>_soa_transcription.yaml) into the
cached ExtractionResult the offline demo serves (data/fixtures/protocols/extractions/<sha256>.json).

The transcription is expanded into exactly the JSON shape the LLM returns and validated by the
same rules (`candidates_from_transcription` -> `build_candidates`).

    uv run --project api python -m trialpilot_api.importers.tools.build_demo_extraction NCT03930732
"""

from __future__ import annotations

import sys
from typing import Any

import yaml

from trialpilot_api.importers.paths import protocols_dir
from trialpilot_api.importers.protocol_extract import candidates_from_transcription, save_cached


def transcription_to_llm_shape(t: dict[str, Any]) -> dict[str, Any]:
    conf = float(t.get("default_confidence", 0.9))
    numbers = [v["n"] for v in t["visits"]]
    first_page = min(r["page"] for r in t["rows"])
    visits: list[dict[str, Any]] = []
    for v in t["visits"]:
        procs = []
        for r in t["rows"]:
            at = numbers if r["at"] == "all" else r["at"]
            if v["n"] in at:
                procs.append({"label": r["label"], "code_hint": None, "source_page": r["page"],
                              "quote": r["label"], "confidence": float(r.get("confidence", conf))})
        window = v.get("window") or [v["week"], v["week"]]
        visits.append({
            "visit_number": v["n"], "label": v["label"], "week": float(v["week"]),
            "week_window_start": float(window[0]), "week_window_end": float(window[1]),
            "is_site_visit": True, "source_page": first_page, "quote": v["header"],
            "confidence": conf, "procedures": procs,
        })
    doc = t["document"]
    return {
        "pdf_sha256": doc["sha256"],
        "page_count": doc["page_count"],
        "soa_pages": t["soa_pages"],
        "model": t["model"],
        "extracted_at": t["extracted_at"],
        "visits": visits,
        "excluded_columns": t.get("excluded_columns", []),
        "warnings": t.get("warnings", []),
        "quote_kind": "image_transcription",
        "provenance": {
            "pipeline": "page images -> transcription (build time) -> validation",
            "transcription_file": f"data/fixtures/protocols/{t['nct_id']}_soa_transcription.yaml",
            "document_url": doc["url"],
            "table": t.get("table"),
            "footnote_quotes": t.get("footnote_quotes", {}),
            "human_verified": False,
        },
    }


def main(nct: str) -> None:
    src = protocols_dir() / f"{nct}_soa_transcription.yaml"
    t = yaml.safe_load(src.read_text(encoding="utf-8"))
    res = candidates_from_transcription(transcription_to_llm_shape(t))
    out = save_cached(res, protocols_dir() / "extractions")  # committed demo cache
    n_proc = sum(len(c.visit.procedures) for c in res.candidates)
    print(f"{nct}: {len(res.candidates)} visits, {n_proc} visit-procedures, {len(res.warnings)} warnings -> {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "NCT03930732")
