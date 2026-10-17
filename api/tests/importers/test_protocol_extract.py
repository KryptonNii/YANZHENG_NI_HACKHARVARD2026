"""Protocol PDF -> candidate schedule. Synthetic PDFs with a known schedule; the LLM is always mocked."""

from __future__ import annotations

import io
from typing import Any

import pytest

from trialpilot_api.importers.llm import LLMUnavailable
from trialpilot_api.importers.protocol_extract import (
    DRAFT_NOTICE,
    MAX_QUOTE_WORDS,
    ExtractionFailed,
    extract_schedule,
    load_cached,
    parse_week_cell,
)
from trialpilot_api.importers.tools.make_synthetic_protocol import (
    OFFSITE_WEEK,
    ground_truth,
    make_pdf,
)

pytestmark = pytest.mark.req("URS-002")
BOREAS_SHA ="76ead4e1be07e49f55ed405820c1a2fec18490505d88f6280e8a811f71f22b23"


def field_accuracy(result: Any) -> dict[str, float]:
    """Field-level accuracy of a result against the synthetic ground truth."""
    truth = {v["number"]: v for v in ground_truth()["visits"]}
    got = {c.visit.number: c for c in result.candidates}
    matched = [n for n in got if n in truth]
    weeks_ok = sum(got[n].visit.week == truth[n]["week"] for n in matched)
    windows_ok = sum((got[n].week_window or None) == truth[n]["window"] for n in matched)
    tp = fp = fn = 0
    for n in matched:
        g = {p.code for p in got[n].visit.procedures}
        t = set(truth[n]["codes"])
        tp, fp, fn = tp + len(g & t), fp + len(g - t), fn + len(t - g)
    return {
        "visit_recall": len(matched) / len(truth),
        "visit_precision": len(matched) / max(len(got), 1),
        "week_accuracy": weeks_ok / max(len(matched), 1),
        "window_accuracy": windows_ok / max(len(matched), 1),
        "procedure_precision": tp / max(tp + fp, 1),
        "procedure_recall": tp / max(tp + fn, 1),
    }


@pytest.fixture(scope="module")
def text_pdf() -> bytes:
    return make_pdf("text")


@pytest.fixture(scope="module")
def image_pdf() -> bytes:
    return make_pdf("image")


# ------------------------------------------------------------- deterministic table path
def test_table_parser_reads_synthetic_schedule(text_pdf: bytes) -> None:
    r = extract_schedule(text_pdf)
    assert r.method == "table_parser" and r.model is None
    assert r.soa_pages == [3, 4]
    assert r.notice == DRAFT_NOTICE
    acc = field_accuracy(r)
    print("\nsynthetic text PDF, table parser:", {k: round(v, 3) for k, v in acc.items()})
    assert acc == {k: 1.0 for k in acc}
    assert all(c.visit.week != OFFSITE_WEEK for c in r.candidates)  # home-dosing column excluded
    assert any(str(OFFSITE_WEEK) in x for x in r.excluded_columns)
    assert any("other:<label>" in w and "Smoking status" in w for w in r.warnings)


def test_every_item_carries_page_quote_and_confidence(text_pdf: bytes) -> None:
    r = extract_schedule(text_pdf)
    for c in r.candidates:
        assert c.source_page in r.soa_pages and c.quote and 0 <= c.confidence <= 1
        assert len(c.quote.split()) <= MAX_QUOTE_WORDS
        for e in c.procedures:
            assert e.source_page in r.soa_pages and e.quote and len(e.quote.split()) <= MAX_QUOTE_WORDS + 1
    weeks = [c.visit.week for c in r.candidates]
    assert weeks == sorted(weeks)


@pytest.mark.req("URS-029")
def test_result_is_cached_by_pdf_hash(text_pdf: bytes) -> None:
    first = extract_schedule(text_pdf)
    assert not first.from_cache
    again = extract_schedule(text_pdf, offline=True)
    assert again.from_cache and again.extraction_id == first.extraction_id


# ------------------------------------------------------------- LLM (vision) path, mocked
def _fake_llm_from_truth(defects: bool = False) -> tuple[Any, dict[str, Any]]:
    seen: dict[str, Any] = {}

    def call(blocks: list[dict[str, Any]], schema: dict[str, Any], system: str) -> dict[str, Any]:
        seen["blocks"], seen["schema"], seen["system"] = blocks, schema, system
        visits = []
        for v in ground_truth()["visits"]:
            win = v["window"] or [v["week"], v["week"]]
            visits.append({
                "visit_number": v["number"], "label": v["label"], "week": v["week"],
                "week_window_start": win[0], "week_window_end": win[1], "is_site_visit": True,
                "source_page": 3, "quote": f"Visit {v['number']} Week {v['week']:g}", "confidence": 0.9,
                "procedures": [{"label": c.removeprefix("other:").replace("_", " "),
                                "code_hint": "other" if c.startswith("other:") else c,
                                "source_page": 3, "quote": c, "confidence": 0.8} for c in v["codes"]],
            })
        visits.append({"visit_number": 0, "label": "Home dosing", "week": OFFSITE_WEEK, "week_window_start": OFFSITE_WEEK,
                       "week_window_end": OFFSITE_WEEK, "is_site_visit": False, "source_page": 3, "quote": "Home",
                       "confidence": 0.8, "procedures": []})
        if defects:
            visits[0]["quote"] = "word " * 40                    # too long -> clipped + warning
            visits[1]["source_page"] = 99                       # outside the SoA -> confidence <= 0.3
            visits[2]["procedures"].append({"label": "Retinal laser foo", "code_hint": "other",
                                            "source_page": 3, "quote": "foo", "confidence": 0.5})
        return {"visits": visits, "warnings": ["Footnote b applies to ECG."], "_model": "fake-model"}

    return call, seen


def test_image_pdf_uses_vision_llm_and_validates(image_pdf: bytes) -> None:
    call, seen = _fake_llm_from_truth()
    r = extract_schedule(image_pdf, llm=call)
    assert r.method == "llm_vision" and r.model == "fake-model"
    assert any(b["type"] == "image" and b["source"]["media_type"] == "image/png" for b in seen["blocks"])
    assert seen["schema"]["additionalProperties"] is False and "visits" in seen["schema"]["required"]
    assert all(c.quote_kind == "image_transcription" and c.quote_verified is None for c in r.candidates)
    acc = field_accuracy(r)
    print("\nsynthetic image PDF, mocked vision LLM:", {k: round(v, 3) for k, v in acc.items()})
    assert acc["visit_recall"] == 1.0 and acc["procedure_recall"] == 1.0
    assert r.excluded_columns and "Home dosing" in r.excluded_columns[0]
    assert "Model note: Footnote b applies to ECG." in r.warnings


def test_llm_output_defects_are_caught(image_pdf: bytes) -> None:
    call, _ = _fake_llm_from_truth(defects=True)
    r = extract_schedule(image_pdf, llm=call, use_cache=False, write_cache=False)
    v1 = next(c for c in r.candidates if c.visit.number == 1)
    v2 = next(c for c in r.candidates if c.visit.number == 2)
    assert v1.quote.endswith("...") and len(v1.quote.split()) == MAX_QUOTE_WORDS + 1
    assert v2.confidence <= 0.3
    assert any("outside the SoA pages" in w for w in r.warnings)
    assert any("Retinal laser foo" in w for w in r.warnings)
    assert any(p.code == "other:retinal_laser_foo" for c in r.candidates for p in c.visit.procedures)


def test_quotes_are_checked_against_page_text(text_pdf: bytes) -> None:
    def call(blocks: list[dict[str, Any]], schema: dict[str, Any], system: str) -> dict[str, Any]:
        return {"visits": [
            {"visit_number": 1, "label": "Screening", "week": -4, "week_window_start": -4, "week_window_end": -1,
             "is_site_visit": True, "source_page": 3, "quote": "Schedule of Activities", "confidence": 0.9,
             "procedures": []},
            {"visit_number": 2, "label": "Baseline", "week": 0, "week_window_start": 0, "week_window_end": 0,
             "is_site_visit": True, "source_page": 3, "quote": "this sentence is not in the protocol", "confidence": 0.9,
             "procedures": []},
        ], "warnings": []}

    from trialpilot_api.importers import protocol_extract as pe

    r = pe.build_candidates(call([], {}, "")["visits"], pe.read_pdf(text_pdf), [3, 4], pe.default_vocabulary(),
                            {3: "text", 4: "text"})[0]
    assert r[0].quote_verified is True and r[0].confidence == 0.9
    assert r[1].quote_verified is False and r[1].confidence == 0.45


def test_llm_failure_is_a_clean_error(image_pdf: bytes) -> None:
    def broken(*_: Any) -> dict[str, Any]:
        raise LLMUnavailable("llm_unavailable", "The LLM provider did not answer after one retry.")

    with pytest.raises(ExtractionFailed) as e:
        extract_schedule(image_pdf, llm=broken, use_cache=False, write_cache=False)
    assert e.value.status == 503 and e.value.code == "llm_unavailable"


@pytest.mark.req("URS-029")
def test_image_pdf_offline_without_cache_explains(image_pdf: bytes) -> None:
    with pytest.raises(ExtractionFailed) as e:
        extract_schedule(image_pdf, offline=True, use_cache=False, write_cache=False)
    assert e.value.code == "extraction_unavailable" and "offline" in e.value.message


@pytest.mark.req("URS-029", "URS-030")
def test_no_api_key_means_no_llm_call(image_pdf: bytes) -> None:
    with pytest.raises(ExtractionFailed) as e:  # ANTHROPIC_API_KEY removed by the autouse fixture
        extract_schedule(image_pdf, use_cache=False, write_cache=False)
    assert e.value.code == "extraction_unavailable" and "no LLM API key" in e.value.message


# ------------------------------------------------------------- bad inputs
def test_not_a_pdf() -> None:
    with pytest.raises(ExtractionFailed) as e:
        extract_schedule(b"hello, I am a text file")
    assert e.value.status == 415


def test_broken_pdf() -> None:
    with pytest.raises(ExtractionFailed) as e:
        extract_schedule(b"%PDF-1.7\n garbage garbage")
    assert e.value.code == "unreadable_pdf"


def test_scanned_pdf_without_text_layer() -> None:
    from PIL import Image as PILImage
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    png = io.BytesIO()
    PILImage.new("RGB", (200, 100), "white").save(png, format="PNG")
    buf = io.BytesIO()
    c = canvas.Canvas(buf, invariant=1)
    for _ in range(5):
        c.drawImage(ImageReader(io.BytesIO(png.getvalue())), 50, 500, 200, 100)
        c.showPage()
    c.save()
    with pytest.raises(ExtractionFailed) as e:
        extract_schedule(buf.getvalue())
    assert e.value.code == "scanned_pdf" and e.value.status == 422


def test_pdf_without_schedule() -> None:
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, invariant=1)
    c.drawString(72, 720, "Minutes of the steering committee meeting. Nothing about visits here at all, " * 2)
    c.showPage()
    c.save()
    with pytest.raises(ExtractionFailed) as e:
        extract_schedule(buf.getvalue())
    assert e.value.code == "soa_not_found"


@pytest.mark.parametrize(("cell", "unit", "expected"), [
    ("W-4 to W-1", "week", (-4.0, [-4.0, -1.0])),
    ("0", "week", (0.0, None)),
    ("52 (EOT)", "week", (52.0, None)),
    ("-21 to -1", "day", (-3.0, [-3.0, -0.14])),
    ("1", "day", (0.0, None)),
    ("85", "day", (12.0, None)),
    ("", "week", None),
])
def test_parse_week_cell(cell: str, unit: str, expected: Any) -> None:
    assert parse_week_cell(cell, unit) == expected


# ------------------------------------------------------------- demo protocol (cached transcription)
@pytest.mark.req("URS-029")
def test_boreas_cached_extraction_is_valid() -> None:
    r = load_cached(BOREAS_SHA)
    assert r is not None and r.from_cache and r.method == "llm_vision"
    assert "not the runtime EXTRACT_MODEL" in (r.model or "")
    assert r.provenance["human_verified"] is False
    assert [c.visit.number for c in r.candidates] == list(range(1, 20))
    assert [c.visit.week for c in r.candidates][:3] == [-4.0, 0.0, 2.0] and r.candidates[-1].visit.week == 64.0
    assert r.candidates[0].week_window == [-4.0, -1.0]
    assert sum(len(c.visit.procedures) for c in r.candidates) == 293
    assert any("weeks 6, 10, 14" in x for x in r.excluded_columns)  # home dosing is not a site visit
    v2 = {p.code for p in r.candidates[1].visit.procedures}
    assert {"randomization", "imp_administration", "pk_sample", "ada_sample", "spirometry"} <= v2
