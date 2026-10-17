"""Controlled procedure vocabulary (`data/fixtures/procedure_codes.yaml`) and label -> code mapping."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from ._contracts import Procedure
from .paths import fixtures_dir

OTHER_PREFIX = "other:"


@dataclass(frozen=True)
class CodeSpec:
    code: str
    label: str
    patterns: tuple[re.Pattern[str], ...]
    ships_sample: bool = False
    in_param_library: bool = False


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def clean_label(label: str) -> str:
    """Drop footnote markers and squeeze whitespace: 'Chest X-ray e' -> 'Chest X-ray'."""
    s = " ".join(label.replace("\n", " ").split())
    # footnote letters must be separated ("X-ray e", "Spirometry n,o") or carets ("X-ray^e")
    s = re.sub(r"(\s|\^)[a-z](,[a-z])*$", "", s) if len(s) > 3 else s
    s = re.sub(r"\s*\((footnote|note)\s*[a-z0-9,]+\)$", "", s, flags=re.I)
    return s.strip(" *:,;")


def slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _ascii(label).lower()).strip("_")[:48] or "unnamed"


class Vocabulary:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or fixtures_dir() / "procedure_codes.yaml"
        doc = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        self.version: int = int(doc.get("version", 1))
        self.specs: list[CodeSpec] = [
            CodeSpec(
                code=c["code"],
                label=c["label"],
                patterns=tuple(re.compile(p, re.I) for p in c.get("match", [])),
                ships_sample=bool(c.get("ships_sample", False)),
                in_param_library=bool(c.get("param", False)),
            )
            for c in doc["codes"]
        ]
        self.by_code = {s.code: s for s in self.specs}

    def match(self, label: str) -> CodeSpec | None:
        text = _ascii(clean_label(label)).lower()
        for spec in self.specs:
            if any(p.search(text) for p in spec.patterns):
                return spec
        return None

    def to_procedure(self, label: str, code_hint: str | None = None) -> tuple[Procedure, bool]:
        """Map a protocol label to a `Procedure`. Returns (procedure, mapped_to_vocabulary).

        `code_hint` (e.g. from the LLM) is accepted only if it is a known code; otherwise the
        label decides. Unknown labels become `other:<slug>` with ships_sample=False.
        """
        label_c = clean_label(label) or label
        spec = self.by_code.get(code_hint or "") or self.match(label_c)
        if spec is None:
            return Procedure(code=OTHER_PREFIX + slug(label_c), label=label_c), False
        return Procedure(code=spec.code, label=label_c, ships_sample=spec.ships_sample), True

    def procedure_for_code(self, code: str) -> Procedure:
        spec = self.by_code[code]
        return Procedure(code=spec.code, label=spec.label, ships_sample=spec.ships_sample)


@lru_cache(maxsize=1)
def default_vocabulary() -> Vocabulary:
    return Vocabulary()
