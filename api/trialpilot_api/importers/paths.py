"""Filesystem locations used by the importers (env overrides for tests and deploys)."""

from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]


def data_dir() -> Path:
    """`data/` at the repo root, or `TP_DATA_DIR`."""
    return Path(os.environ.get("TP_DATA_DIR") or _REPO_ROOT / "data")


def fixtures_dir() -> Path:
    return data_dir() / "fixtures"


def ctgov_cache_dir() -> Path:
    """Raw ClinicalTrials.gov responses: committed fixtures + runtime cache (`TP_CTGOV_CACHE_DIR`)."""
    return Path(os.environ.get("TP_CTGOV_CACHE_DIR") or fixtures_dir() / "ctgov")


def geonames_dir() -> Path:
    return Path(os.environ.get("TP_GEONAMES_DIR") or fixtures_dir() / "ctgov" / "geonames")


def protocols_dir() -> Path:
    """Committed protocol metadata + cached extractions (never the third-party PDFs themselves)."""
    return Path(os.environ.get("TP_PROTOCOLS_DIR") or fixtures_dir() / "protocols")


def runtime_cache_dir() -> Path:
    """Gitignored cache for documents we must not commit (downloaded protocol PDFs)."""
    return Path(os.environ.get("TP_RUNTIME_CACHE_DIR") or protocols_dir() / ".cache")


def demo_offline() -> bool:
    return os.environ.get("DEMO_OFFLINE", "0").strip().lower() in {"1", "true", "yes", "on"}
