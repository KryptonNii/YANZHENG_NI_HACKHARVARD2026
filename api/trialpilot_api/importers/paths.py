"""Filesystem locations used by the importers.

Read-only, committed data lives under the fixtures dir (`TP_FIXTURES_DIR`, same variable A5 uses;
default `<repo>/data/fixtures`). Anything written at runtime (newly fetched studies, downloaded
protocol PDFs, new extractions, the review log) goes to a writable dir:
`TP_RUNTIME_CACHE_DIR`, else `$TP_DATA_DIR/importers` (A5's writable Docker volume), else - in a
dev checkout - next to the committed fixtures, so new real fixtures can be committed deliberately.
Reads look in the writable dir first, then in the committed fixtures.
"""

from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]


def fixtures_dir() -> Path:
    return Path(os.environ.get("TP_FIXTURES_DIR") or _REPO_ROOT / "data" / "fixtures")


def ctgov_cache_dir() -> Path:
    """Committed raw ClinicalTrials.gov responses (`TP_CTGOV_CACHE_DIR` overrides)."""
    return Path(os.environ.get("TP_CTGOV_CACHE_DIR") or fixtures_dir() / "ctgov")


def geonames_dir() -> Path:
    return Path(os.environ.get("TP_GEONAMES_DIR") or fixtures_dir() / "ctgov" / "geonames")


def protocols_dir() -> Path:
    """Committed protocol transcriptions + cached extractions (never the third-party PDFs themselves)."""
    return Path(os.environ.get("TP_PROTOCOLS_DIR") or fixtures_dir() / "protocols")


def _writable_root() -> Path | None:
    if os.environ.get("TP_RUNTIME_CACHE_DIR"):
        return Path(os.environ["TP_RUNTIME_CACHE_DIR"])
    if os.environ.get("TP_DATA_DIR"):
        return Path(os.environ["TP_DATA_DIR"]) / "importers"
    return None


def runtime_cache_dir() -> Path:
    """Writable, never committed: downloaded protocol PDFs and the review log."""
    root = _writable_root()
    return root if root is not None else protocols_dir() / ".cache"  # .cache/ is gitignored


def ctgov_write_dir() -> Path:
    root = _writable_root()
    return root / "ctgov" if root is not None else ctgov_cache_dir()


def ctgov_read_dirs() -> list[Path]:
    return list(dict.fromkeys([ctgov_write_dir(), ctgov_cache_dir()]))


def extractions_write_dir() -> Path:
    root = _writable_root()
    return root / "extractions" if root is not None else protocols_dir() / "extractions"


def extractions_read_dirs() -> list[Path]:
    return list(dict.fromkeys([extractions_write_dir(), protocols_dir() / "extractions"]))


def demo_offline() -> bool:
    return os.environ.get("DEMO_OFFLINE", "0").strip().lower() in {"1", "true", "yes", "on"}
