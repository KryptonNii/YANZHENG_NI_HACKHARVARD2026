"""Protocol PDF -> candidate schedule of activities (visits + procedures), for a human to confirm.

Pipeline: pdfplumber text/tables per page -> locate the Schedule of Activities (headings, table of
contents, continuation pages) -> deterministic grid parser for text tables -> LLM (text, or page
images when the SoA is scanned/flattened) if the parser cannot read it -> validation (weeks
increasing, procedure codes from the controlled vocabulary, unknown labels kept as `other:<label>`,
quotes <= 25 words and checked against the page text).

Results are cached by the PDF's sha256 in `data/fixtures/protocols/extractions/`; offline mode
(`DEMO_OFFLINE=1`) serves only cached results. Nothing here applies candidates to a design.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from ._contracts import Procedure, Visit
from .llm import LLMCall, LLMUnavailable, anthropic_call, extract_model, llm_configured
from .paths import demo_offline, protocols_dir
from .procedures import Vocabulary, default_vocabulary

MAX_QUOTE_WORDS = 25
MAX_SOA_PAGES = 12
MAX_IMAGE_PAGES = 8
FIRST_PASS_PAGES = 40
_NS = uuid.UUID("0b8f5d0e-5a3c-4c55-9f7e-2c1d7a9e4b21")
DRAFT_NOTICE = "DRAFT - machine-extracted candidates. A human must accept, edit or reject each item before use."


# ---------------------------------------------------------------- result models
class ProcedureEvidence(BaseModel):
    code: str
    label: str
    mapped: bool                      # False -> kept as other:<label>
    source_page: int
    quote: str
    confidence: float = Field(ge=0, le=1)


class VisitCandidate(BaseModel):
    visit: Visit
    source_page: int
    quote: str                         # <= 25 words
    quote_kind: Literal["text", "table_cells", "image_transcription"]
    quote_verified: bool | None        # found verbatim in the page text (None: image page, cannot check)
    confidence: float = Field(ge=0, le=1)
    week_window: list[float] | None = None   # [start, end] when the protocol gives a window
    procedures: list[ProcedureEvidence] = []


class ExtractionResult(BaseModel):
    extraction_id: str
    pdf_sha256: str
    page_count: int
    soa_pages: list[int]
    method: Literal["table_parser", "llm_text", "llm_vision"]
    model: str | None = None
    from_cache: bool = False
    extracted_at: str
    candidates: list[VisitCandidate]
    excluded_columns: list[str] = []   # schedule columns that are not site visits (home dosing, diary...)
    warnings: list[str] = []
    notice: str = DRAFT_NOTICE
    vocabulary_version: int = 1
    provenance: dict[str, Any] = {}

    @property
    def visits(self) -> list[Visit]:
        return [c.visit for c in self.candidates]


class ExtractionFailed(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details or {}


# ---------------------------------------------------------------- PDF reading
@dataclass
class PageInfo:
    number: int                  # 1-based
    text: str
    n_images: int
    tables: list[list[list[str | None]]] = field(default_factory=list)
    landscape: bool = False
    image_share: float = 0.0     # largest image's share of the page area

    @property
    def image_only(self) -> bool:
        """No usable text grid: either no text at all, or a large picture and no X-mark table."""
        if self.n_images == 0:
            return False
        if len(self.text.strip()) < 80:
            return True
        return self.image_share >= 0.25 and _marks_in_tables(self.tables) < 3


def _largest_image_share(page: Any) -> float:
    area = float(page.width * page.height) or 1.0
    best = 0.0
    for im in page.images:
        try:
            best = max(best, abs(float(im["x1"]) - float(im["x0"])) * abs(float(im["bottom"]) - float(im["top"])) / area)
        except (KeyError, TypeError, ValueError):
            continue
    return round(min(best, 1.0), 3)


def pdf_page_count(pdf_bytes: bytes) -> int:
    import pdfplumber

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            return len(pdf.pages)
    except Exception as exc:
        raise ExtractionFailed(422, "unreadable_pdf", "The file could not be read as a PDF.",
                               {"cause": type(exc).__name__}) from exc


def read_pdf(pdf_bytes: bytes, max_pages: int = 600) -> list[PageInfo]:
    """Text of the first `max_pages` pages (text extraction dominates the cost: ~0.25 s/page)."""
    import pdfplumber

    pages: list[PageInfo] = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for i, page in enumerate(pdf.pages[:max_pages], start=1):
                pages.append(PageInfo(i, page.extract_text() or "", len(page.images),
                                      landscape=page.width > page.height, image_share=_largest_image_share(page)))
    except Exception as exc:  # pdfminer raises many types for broken files
        raise ExtractionFailed(422, "unreadable_pdf", "The file could not be read as a PDF.",
                               {"cause": type(exc).__name__}) from exc
    if not pages:
        raise ExtractionFailed(422, "unreadable_pdf", "The PDF has no pages.")
    return pages


def _load_tables(pdf_bytes: bytes, page_numbers: list[int], pages: list[PageInfo]) -> None:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for n in page_numbers:
            pages[n - 1].tables = pdf.pages[n - 1].extract_tables() or []


def render_pages_png(pdf_bytes: bytes, page_numbers: list[int], resolution: int = 150) -> dict[int, bytes]:
    import pdfplumber

    out: dict[int, bytes] = {}
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for n in page_numbers:
            buf = io.BytesIO()
            pdf.pages[n - 1].to_image(resolution=resolution).original.save(buf, format="PNG")
            out[n] = buf.getvalue()
    return out


# ---------------------------------------------------------------- locating the SoA
_SOA_TITLE = (r"(schedule\s+of\s+(activities|assessments|events|study\s+(procedures|assessments))"
              r"|study\s+flow\s*-?\s*chart|flow\s*-?\s*chart|time\s+and\s+events\s+(schedule|table))")
# a heading line: optional section number, the title, optional "(SoA)" - nothing else on the line
_HEADING_RE = re.compile(rf"^\s*(\d+(\.\d+)*\.?\s+)?{_SOA_TITLE}\s*(\(soa\))?\s*$", re.I)
_TOC_RE = re.compile(rf"{_SOA_TITLE}.*?\.{{3,}}\s*(\d+)\s*$", re.I)
# a marked cell: "X", "x", "(X)", check marks/bullets, optionally followed by footnote refs ("X^f", "X13", "X 2,3")
_MARK_RE = re.compile(r"^\s*\(?[xX✓✔●•]\)?(\s*\^?[a-z0-9]{1,3}(,\s*[a-z0-9]{1,3})*)?\s*\*?\s*$")


def _marks_in_tables(tables: list[list[list[str | None]]]) -> int:
    return sum(1 for t in tables for row in t for c in row if c and _MARK_RE.match(c))


def _footer_page(p: PageInfo) -> int | None:
    tail = " ".join(p.text.strip().splitlines()[-3:])
    m = re.search(r"\bpage\s+(\d+)\b", tail, re.I)
    return int(m.group(1)) if m else None


def locate_soa(pages: list[PageInfo], pdf_bytes: bytes | None = None) -> tuple[list[int], list[str]]:
    """Return (1-based page numbers of the SoA, notes on how they were found).

    Order of trust: the table-of-contents entry (mapped to a PDF page via "Page N" footers), a
    short SoA heading near it or anywhere, then the page with the densest X-mark table.
    """
    notes: list[str] = []
    toc_hint: int | None = None
    headings: list[int] = []
    for p in pages:
        for line in p.text.splitlines():
            m = _TOC_RE.search(line)
            if m:
                toc_hint = toc_hint or int(m.group(_TOC_RE.groups))
                continue
            if len(line) < 100 and _HEADING_RE.match(line) and not re.search(r"\bsee\b|refer|section\s*\d", line, re.I):
                headings.append(p.number)
    start: int | None = None
    if toc_hint is not None and toc_hint > len(pages) and not headings:
        return [], [f"The table of contents puts the SoA on printed page {toc_hint}, beyond the pages read."]
    if toc_hint is not None:
        by_footer = {fp: p.number for p in pages if (fp := _footer_page(p)) is not None}
        mapped = by_footer.get(toc_hint, min(toc_hint, len(pages)))
        near = [h for h in headings if abs(h - mapped) <= 1]
        start = near[0] if near else mapped
        notes.append(f"SoA located from the table of contents (printed page {toc_hint} -> PDF page {start}).")
    elif headings:
        start = headings[0]
        notes.append(f"SoA located from its heading on page {start}.")
    else:
        if pdf_bytes is not None:
            _load_tables(pdf_bytes, [p.number for p in pages], pages)
        best = max(pages, key=lambda p: _marks_in_tables(p.tables))
        if _marks_in_tables(best.tables) < 10:
            return [], ["No Schedule of Activities heading, TOC entry or X-grid table was found."]
        start = best.number
        notes.append("No SoA heading found; used the page with the densest X-mark table.")
    found = [start]
    if pdf_bytes is not None:
        _load_tables(pdf_bytes, list(range(start, min(start + MAX_SOA_PAGES, len(pages)) + 1)), pages)
    for p in pages[start: start + MAX_SOA_PAGES - 1]:
        continues = p.image_only or _marks_in_tables(p.tables) >= 3 or bool(re.search(_SOA_TITLE, p.text[:400], re.I))
        # SoA footnote pages: no table, several lines like "a Randomization visit is Day 1 ..."
        footnote_lines = sum(1 for ln in p.text.splitlines() if re.match(r"^[a-z]{1,2}\s+[A-Z(]", ln))
        footnotes_only = not p.tables and footnote_lines >= 3
        if continues or footnotes_only:
            found.append(p.number)
        else:
            break
    return found, notes


# ---------------------------------------------------------------- week parsing
def parse_week_cell(text: str, unit: str = "week") -> tuple[float, list[float] | None] | None:
    """'W-4 to W-1' -> (-4, [-4, -1]); '12' -> (12, None); 'Day 15' -> (2, None); '52 (EOT)' -> (52, None)."""
    t = (text or "").replace("\n", " ").replace("−", "-").replace("–", "-").strip()
    if not t:
        return None
    lower = t.lower()
    if "day" in lower or lower.startswith("d"):
        unit = "day"
    elif "month" in lower:
        unit = "month"
    nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", re.sub(r"(?<=[a-z])-(?=\d)", " -", lower))]
    if not nums:
        return None

    def to_week(v: float) -> float:
        if unit == "day":
            return round((v - 1) / 7 if v >= 1 else v / 7, 2)  # Day 1 = week 0
        if unit == "month":
            return round(v * 52.1775 / 12, 1)
        return v

    weeks = [to_week(v) for v in nums]
    if len(weeks) >= 2 and re.search(r"\bto\b|-|–|through", lower) and weeks[0] < weeks[1]:
        return weeks[0], [weeks[0], weeks[1]]
    return weeks[0], None


# ---------------------------------------------------------------- quotes
def _norm_ws(s: str) -> str:
    return " ".join(s.split()).lower()


def clip_quote(q: str) -> tuple[str, bool]:
    words = (q or "").split()
    if len(words) <= MAX_QUOTE_WORDS:
        return " ".join(words), False
    return " ".join(words[:MAX_QUOTE_WORDS]) + " ...", True


# ---------------------------------------------------------------- deterministic grid parser
@dataclass
class _Column:
    visit_label: str
    visit_number: int | None
    week: float
    window: list[float] | None
    page: int
    header_text: str
    site: bool = True
    exclude_reason: str | None = None
    marks: list[tuple[str, str, int]] = field(default_factory=list)  # (row label, cell text, page)


def _cell(s: str | None) -> str:
    """Squeeze whitespace and re-join words hyphenated across lines ('Screen- ing' -> 'Screening')."""
    t = " ".join((s or "").split())
    return re.sub(r"([a-z])- ([a-z])", r"\1\2", t)


_VISIT_WORD = re.compile(r"\bvisit\b|screen|baseline|\beos\b|\beot\b|end of (study|treatment)|follow.?up|\bday\s*1\b", re.I)
_TIME_ROW = re.compile(r"^(study\s+)?(week|day|month)s?\b", re.I)
_SKIP_ROW = re.compile(r"^(window|visit|week|day|month|study procedure|procedure|assessment)s?\b", re.I)
_OFFSITE = re.compile(r"option\s?al|phone|telephone|home|unscheduled|remote|call\b|e-?mail", re.I)


def _visit_label(s: str) -> str:
    """'Option al Visit 4.11' -> 'Optional Visit 4'; 'EOS Visit18' -> 'EOS Visit' (glued digits are footnotes)."""
    s = re.sub(r"\b(Option)\s(al)\b", r"\1\2", s, flags=re.I)
    s = re.sub(r"(?<=[A-Za-z])\d{1,2}\b", "", s)
    s = re.sub(r"(\d+)\.\d{1,2}\b", r"\1", s)
    return " ".join(s.split())


def parse_grid_tables(pages: list[PageInfo], soa_pages: list[int]) -> tuple[list[_Column], list[str]]:
    """Parse X-mark grids: header rows (visit labels + Week and/or Day rows), then one row per procedure.

    Handles merged header cells (a visit spanning several sub-columns), tables continued over
    several pages (merged by visit and week), and footnote digits glued to marks ("X13").
    """
    warnings: list[str] = []
    merged: dict[str, _Column] = {}
    order: list[str] = []
    for n in soa_pages:
        for table in pages[n - 1].tables:
            rows = [[_cell(c) for c in r] for r in table if r]
            if len(rows) < 3:
                continue
            ncols = max(len(r) for r in rows)
            rows = [r + [""] * (ncols - len(r)) for r in rows]
            head = rows[:6]
            time_rows = [i for i, r in enumerate(head) if _TIME_ROW.match(r[0])]
            if not time_rows:
                continue
            visit_rows = [i for i, r in enumerate(head) if i not in time_rows
                          and sum(1 for c in r[1:] if _VISIT_WORD.search(c) or re.fullmatch(r"\d{1,3}", c)) >= 2]

            def number_score(r: list[str]) -> int:  # prefer the row that carries visit numbers
                return (2 if re.match(r"^visits?\b", r[0], re.I) else 0) + sum(
                    1 for c in r[1:] if re.search(r"\bvisit\s+\d|^\d{1,3}\b", c, re.I))

            visit_i = max(visit_rows, key=lambda i: number_score(head[i])) if visit_rows else None
            header_end = max(time_rows + visit_rows)
            label_rows = [i for i in range(header_end + 1) if i not in time_rows and not re.match(r"^window", rows[i][0], re.I)]
            units = {i: _TIME_ROW.match(rows[i][0]).group(2).lower() for i in time_rows}  # type: ignore[union-attr]
            week_first = sorted(time_rows, key=lambda i: {"week": 0, "month": 1, "day": 2}[units[i]])
            anchors = [ci for ci in range(1, ncols)
                       if (visit_i is not None and rows[visit_i][ci]) or any(rows[i][ci] for i in time_rows)]
            for k, ci in enumerate(anchors):
                span = range(ci, anchors[k + 1] if k + 1 < len(anchors) else ncols)
                vcell = next((rows[visit_i][c] for c in span if rows[visit_i][c]), "") if visit_i is not None else ""
                vlabel = _visit_label(" ".join(x for x in (next((rows[i][c] for c in span if rows[i][c]), "") for i in label_rows) if x))
                parsed = None
                tcell = ""
                for i in week_first:
                    tcell = next((rows[i][c] for c in span if rows[i][c]), "")
                    parsed = parse_week_cell(tcell, units[i]) if tcell else None
                    if parsed is not None:
                        break
                if parsed is None:
                    continue
                # "Visit 3" or a bare "3"; digits glued to a word ("EOS Visit18") are footnotes, not numbers
                m = re.search(r"\bvisit\s+(\d{1,3})\b", vcell, re.I) or re.fullmatch(r"(\d{1,3})(\s?[a-z](,[a-z])*)?", vcell)
                number = int(m.group(1)) if m else None
                if re.fullmatch(r"\d{1,3}(\s?[a-z](,[a-z])*)?", vlabel or "x") and number is not None:
                    vlabel = f"Visit {number}"
                key = f"{number}|{parsed[0]}|{vlabel.lower() if number is None else ''}"
                if key not in merged:
                    col = _Column(vlabel or f"Week {parsed[0]:g}", number, parsed[0], parsed[1], n,
                                  " | ".join(x for x in (vlabel, rows[week_first[0]][0], tcell) if x))
                    if number is None and visit_i is not None and not vcell:
                        col.site, col.exclude_reason = False, "column has no visit label"
                    elif number is None and _OFFSITE.search(vlabel):
                        col.site, col.exclude_reason = False, f"labelled '{vlabel}'"
                    merged[key] = col
                    order.append(key)
                col = merged[key]
                for r in rows[header_end + 1:]:
                    label = r[0]
                    if not label or _SKIP_ROW.match(label):
                        continue
                    cell = next((r[c] for c in span if r[c] and _MARK_RE.match(r[c])), "")
                    if cell:
                        col.marks.append((label, cell, n))
    cols = [merged[k] for k in order]
    off = [c for c in cols if not c.site]
    if off:
        warnings.append(
            f"{len(off)} schedule column(s) are not site visits and were not made visits: "
            + "; ".join(f"week {c.week:g} ({c.exclude_reason})" for c in off) + "."
        )
    return cols, warnings


# ---------------------------------------------------------------- LLM path
def _schema(vocab: Vocabulary) -> dict[str, Any]:
    codes = [s.code for s in vocab.specs] + ["other"]
    proc = {
        "type": "object",
        "properties": {
            "label": {"type": "string", "description": "procedure name exactly as written in the protocol"},
            "code_hint": {"type": "string", "enum": codes},
            "source_page": {"type": "integer"},
            "quote": {"type": "string", "description": "verbatim text from the page, at most 25 words"},
            "confidence": {"type": "number"},
        },
        "required": ["label", "code_hint", "source_page", "quote", "confidence"],
        "additionalProperties": False,
    }
    visit = {
        "type": "object",
        "properties": {
            "visit_number": {"type": "integer"},
            "label": {"type": "string"},
            "week": {"type": "number", "description": "weeks relative to Day 1 / randomization (= week 0)"},
            "week_window_start": {"type": "number"},
            "week_window_end": {"type": "number"},
            "is_site_visit": {"type": "boolean"},
            "source_page": {"type": "integer"},
            "quote": {"type": "string"},
            "confidence": {"type": "number"},
            "procedures": {"type": "array", "items": proc},
        },
        "required": ["visit_number", "label", "week", "week_window_start", "week_window_end", "is_site_visit",
                     "source_page", "quote", "confidence", "procedures"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"visits": {"type": "array", "items": visit}, "warnings": {"type": "array", "items": {"type": "string"}}},
        "required": ["visits", "warnings"],
        "additionalProperties": False,
    }


SYSTEM_PROMPT = """You extract the Schedule of Activities (SoA) from a clinical trial protocol.
Report only what the provided pages show; never add visits or procedures from general knowledge.
For every visit column give its visit number, label, nominal week relative to Day 1 / randomization (week 0;
convert days with week = (day - 1) / 7), and the window if one is printed (otherwise start = end = week).
Columns that are not on-site visits (home dosing, phone calls, daily diary periods) must have is_site_visit = false.
For every procedure marked at a visit, give its label as printed, the closest code_hint (or "other"),
the page number, and a verbatim quote of at most 25 words from that page (for page images: transcribe the
visible text exactly). Confidence is your probability (0 to 1) that the item is correct.
Use the main schedule for participants who complete treatment; ignore separate tables for early
discontinuation / early termination, but mention them in warnings.
Put anything ambiguous (footnotes that change a visit, unreadable cells) in warnings."""


def _llm_blocks(pages: list[PageInfo], soa_pages: list[int], pngs: dict[int, bytes]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for n in soa_pages:
        p = pages[n - 1]
        if n in pngs:
            blocks.append({"type": "text", "text": f"--- Page {n} (image of the page follows) ---"})
            blocks.append({"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                       "data": base64.standard_b64encode(pngs[n]).decode()}})
        else:
            tables = "\n\n".join("\n".join("\t".join((c or "").replace("\n", " ") for c in r) for r in t)
                                 for t in p.tables)
            blocks.append({"type": "text", "text": f"--- Page {n} text ---\n{p.text}\n--- Page {n} tables (TSV) ---\n{tables}"})
    blocks.append({"type": "text", "text": "Extract the schedule of activities from the pages above."})
    return blocks


# ---------------------------------------------------------------- validation / assembly
def build_candidates(
    raw_visits: list[dict[str, Any]],
    pages: list[PageInfo] | None,
    soa_pages: list[int],
    vocab: Vocabulary,
    quote_kind_for_page: dict[int, str],
) -> tuple[list[VisitCandidate], list[str], list[str]]:
    """Validate visit dicts (LLM output shape) -> (candidates, warnings, excluded column notes)."""
    warnings: list[str] = []
    excluded: list[str] = []
    page_text = {p.number: _norm_ws(p.text) for p in pages} if pages else {}
    allowed = set(soa_pages)

    def check_quote(q: str, page: int, conf: float) -> tuple[str, bool | None, float]:
        q2, clipped = clip_quote(q)
        if clipped:
            warnings.append(f"A quote on page {page} was longer than {MAX_QUOTE_WORDS} words and was shortened.")
        kind = quote_kind_for_page.get(page, "text")
        if kind != "text" or not page_text:
            return q2, None, conf
        ok = _norm_ws(q2.removesuffix(" ...")) in page_text.get(page, "")
        return q2, ok, conf if ok else round(conf * 0.5, 2)

    site = [v for v in raw_visits if v.get("is_site_visit", True)]
    for v in raw_visits:
        if not v.get("is_site_visit", True):
            excluded.append(f"{v.get('label') or 'column'} (week {v.get('week')}, page {v.get('source_page')})")
    out: list[VisitCandidate] = []
    prev_week: float | None = None
    for v in site:
        page = int(v.get("source_page") or 0)
        conf = float(min(max(v.get("confidence", 0.5), 0.0), 1.0))
        if page not in allowed:
            warnings.append(f"Visit '{v.get('label')}' cites page {page}, outside the SoA pages {soa_pages}; confidence lowered.")
            conf = min(conf, 0.3)
        week = float(v["week"])
        if prev_week is not None and week < prev_week:
            warnings.append(f"Weeks are not increasing at visit '{v.get('label')}' (week {week:g} after {prev_week:g}); check the order.")
        prev_week = week if prev_week is None else max(prev_week, week)
        quote, verified, conf = check_quote(str(v.get("quote") or ""), page, conf)
        procs: list[Procedure] = []
        evidence: list[ProcedureEvidence] = []
        seen: set[tuple[str, str]] = set()
        for pr in v.get("procedures", []):
            label = str(pr.get("label") or "").strip()
            if not label:
                continue
            hint = pr.get("code_hint")
            proc, mapped = vocab.to_procedure(label, None if hint in (None, "other") else hint)
            if (proc.code, proc.label.lower()) in seen:
                continue
            seen.add((proc.code, proc.label.lower()))
            ppage = int(pr.get("source_page") or page)
            pconf = float(min(max(pr.get("confidence", 0.5), 0.0), 1.0))
            pquote, _, pconf = check_quote(str(pr.get("quote") or label), ppage, pconf)
            procs.append(proc)
            evidence.append(ProcedureEvidence(code=proc.code, label=proc.label, mapped=mapped,
                                              source_page=ppage, quote=pquote, confidence=pconf))
        ws, we = v.get("week_window_start"), v.get("week_window_end")
        window = [float(ws), float(we)] if ws is not None and we is not None and float(ws) != float(we) else None
        out.append(VisitCandidate(
            visit=Visit(number=int(v.get("visit_number") or 0), label=str(v.get("label") or f"Week {week:g}"),
                        week=week, procedures=procs, can_be_remote=False),
            source_page=page, quote=quote, quote_kind=quote_kind_for_page.get(page, "text"),  # type: ignore[arg-type]
            quote_verified=verified, confidence=conf, week_window=window, procedures=evidence,
        ))
    out.sort(key=lambda c: (c.visit.week, c.visit.number))
    numbers = [c.visit.number for c in out]
    if 0 in numbers or len(set(numbers)) != len(numbers) or numbers != sorted(numbers):
        missing = sum(1 for x in numbers if x == 0)
        warnings.append(
            ("Some visits had no printed visit number" if missing else "Visit numbers were duplicated or out of order")
            + "; all visits were renumbered 1..N in week order."
        )
        for i, c in enumerate(out, start=1):
            c.visit.number = i
    unmapped = sorted({e.label for c in out for e in c.procedures if not e.mapped})
    if unmapped:
        warnings.append(f"{len(unmapped)} procedure label(s) are not in the controlled vocabulary and were kept as "
                        f"other:<label>: {', '.join(unmapped)}.")
    return out, warnings, excluded


def _grid_to_raw(cols: list[_Column]) -> list[dict[str, Any]]:
    raw = []
    for c in cols:
        raw.append({
            "visit_number": c.visit_number, "label": c.visit_label, "week": c.week,
            "week_window_start": c.window[0] if c.window else c.week,
            "week_window_end": c.window[1] if c.window else c.week,
            "is_site_visit": c.site,
            "source_page": c.page, "quote": c.header_text,
            "confidence": 0.9 if c.visit_number is not None else 0.75,
            "procedures": [{"label": lbl, "code_hint": None, "source_page": pg, "quote": f"{lbl} | {cell}",
                            "confidence": 0.9} for lbl, cell, pg in c.marks],
        })
    return raw


# ---------------------------------------------------------------- cache
def pdf_sha256(pdf_bytes: bytes) -> str:
    return hashlib.sha256(pdf_bytes).hexdigest()


def extraction_cache_dir() -> Path:
    return protocols_dir() / "extractions"


def load_cached(sha: str) -> ExtractionResult | None:
    p = extraction_cache_dir() / f"{sha}.json"
    if not p.exists():
        return None
    res = ExtractionResult.model_validate_json(p.read_text(encoding="utf-8"))
    res.from_cache = True
    return res


def save_cached(res: ExtractionResult) -> Path:
    d = extraction_cache_dir()
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{res.pdf_sha256}.json"
    p.write_text(res.model_dump_json(indent=1, exclude={"from_cache"}), encoding="utf-8", newline="\n")
    return p


# ---------------------------------------------------------------- entry point
def extract_schedule(
    pdf_bytes: bytes,
    *,
    llm: LLMCall | None = None,
    use_cache: bool = True,
    write_cache: bool = True,
    offline: bool | None = None,
    vocab: Vocabulary | None = None,
) -> ExtractionResult:
    """Extract candidate visits from a protocol PDF. Raises `ExtractionFailed` with a clear code."""
    if not pdf_bytes.startswith(b"%PDF"):
        raise ExtractionFailed(415, "not_a_pdf", "The uploaded file is not a PDF.")
    vocab = vocab or default_vocabulary()
    offline = demo_offline() if offline is None else offline
    sha = pdf_sha256(pdf_bytes)
    if use_cache and (cached := load_cached(sha)) is not None:
        return cached

    total = pdf_page_count(pdf_bytes)
    pages = read_pdf(pdf_bytes, max_pages=FIRST_PASS_PAGES)  # the SoA is normally in section 1
    no_text = sum(1 for p in pages if len(p.text.strip()) < 30)
    if no_text >= 0.8 * len(pages):
        raise ExtractionFailed(
            422, "scanned_pdf",
            f"This PDF has no text layer ({no_text} of the first {len(pages)} pages are scanned images), so the "
            "Schedule of Activities cannot be located automatically. Enter the visits manually or upload a text PDF.",
            {"pdf_sha256": sha, "pages_checked": len(pages)},
        )
    soa_pages, locate_notes = locate_soa(pages, pdf_bytes)
    if not soa_pages and total > len(pages):
        hint = next((int(m.group(_TOC_RE.groups)) for p in pages for ln in p.text.splitlines()
                     if (m := _TOC_RE.search(ln))), None)
        # read up to the page the table of contents points at (plus slack for front matter), else everything
        pages = read_pdf(pdf_bytes, max_pages=hint + 2 * MAX_SOA_PAGES if hint else 600)
        soa_pages, locate_notes = locate_soa(pages, pdf_bytes)
    if not soa_pages:
        raise ExtractionFailed(422, "soa_not_found",
                               "No Schedule of Activities was found in this PDF. Add the visits manually.",
                               {"pages": len(pages)})
    warnings = list(locate_notes)
    image_pages = [n for n in soa_pages if pages[n - 1].image_only]
    method: Literal["table_parser", "llm_text", "llm_vision"]
    model: str | None = None

    cols, grid_warn = parse_grid_tables(pages, soa_pages)
    grid_ok = sum(1 for c in cols if c.marks) >= 2
    quote_kind: dict[int, str] = {n: ("image_transcription" if n in image_pages else "text") for n in soa_pages}
    if grid_ok and not image_pages:
        raw = _grid_to_raw(cols)
        warnings += grid_warn
        quote_kind = {n: "table_cells" for n in soa_pages}
        method = "table_parser"
    else:
        call = llm or (anthropic_call if (llm_configured() and not offline) else None)
        if call is None:
            if grid_ok:
                raw = _grid_to_raw(cols)
                warnings += grid_warn
                warnings.append(f"SoA pages {image_pages} are images and were not read (no LLM configured).")
                quote_kind = {n: "table_cells" for n in soa_pages}
                method = "table_parser"
            else:
                why = ("offline demo mode" if offline else "no LLM API key configured")
                raise ExtractionFailed(
                    503, "extraction_unavailable",
                    f"This protocol's schedule needs the LLM extractor ({'scanned pages ' + str(image_pages) if image_pages else 'table not machine-readable'}), "
                    f"which is unavailable: {why}. No cached extraction exists for this file.",
                    {"pdf_sha256": sha, "soa_pages": soa_pages},
                )
        else:
            pngs = render_pages_png(pdf_bytes, image_pages[:MAX_IMAGE_PAGES]) if image_pages else {}
            if len(image_pages) > MAX_IMAGE_PAGES:
                warnings.append(f"Only the first {MAX_IMAGE_PAGES} image pages of the SoA were sent to the model.")
            try:
                out = call(_llm_blocks(pages, soa_pages, pngs), _schema(vocab), SYSTEM_PROMPT)
            except LLMUnavailable as exc:
                raise ExtractionFailed(503, exc.code, exc.message, exc.details) from exc
            raw = list(out.get("visits") or [])
            warnings += [f"Model note: {w}" for w in out.get("warnings") or []]
            model = str(out.get("_model") or extract_model())
            method = "llm_vision" if image_pages else "llm_text"

    candidates, v_warn, excluded = build_candidates(raw, pages, soa_pages, vocab, quote_kind)
    if not candidates:
        raise ExtractionFailed(422, "no_visits_extracted", "The Schedule of Activities was found but no visits could be read.",
                               {"soa_pages": soa_pages})
    res = ExtractionResult(
        extraction_id=str(uuid.uuid5(_NS, f"{sha}:{method}:{model}")),
        pdf_sha256=sha,
        page_count=total,
        soa_pages=soa_pages,
        method=method,
        model=model,
        extracted_at=datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        candidates=candidates,
        excluded_columns=excluded,
        warnings=warnings + v_warn,
        vocabulary_version=vocab.version,
        provenance={"pipeline": "pdfplumber text/tables -> SoA locator -> " + method + " -> validation"},
    )
    if write_cache:
        save_cached(res)
    return res


def candidates_from_transcription(doc: dict[str, Any], *, vocab: Vocabulary | None = None) -> ExtractionResult:
    """Build an ExtractionResult from a stored transcription (same JSON shape the LLM returns).

    Used for the demo protocol, whose SoA pages are images: the transcription was produced once at
    build time and is validated by exactly the same rules as live LLM output.
    """
    vocab = vocab or default_vocabulary()
    soa_pages = list(doc["soa_pages"])
    kinds = {n: doc.get("quote_kind", "image_transcription") for n in soa_pages}
    candidates, warnings, excluded = build_candidates(doc["visits"], None, soa_pages, vocab, kinds)
    return ExtractionResult(
        extraction_id=str(uuid.uuid5(_NS, f"{doc['pdf_sha256']}:transcription:{doc.get('model')}")),
        pdf_sha256=doc["pdf_sha256"],
        page_count=int(doc["page_count"]),
        soa_pages=soa_pages,
        method="llm_vision",
        model=doc.get("model"),
        extracted_at=doc["extracted_at"],
        candidates=candidates,
        excluded_columns=excluded + list(doc.get("excluded_columns", [])),
        warnings=list(doc.get("warnings", [])) + warnings,
        vocabulary_version=vocab.version,
        provenance=dict(doc.get("provenance", {})),
    )


def result_to_json(res: ExtractionResult) -> dict[str, Any]:
    return json.loads(res.model_dump_json())
