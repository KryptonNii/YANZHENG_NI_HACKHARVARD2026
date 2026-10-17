"""A4 importers: ClinicalTrials.gov (API v2), offline geocoding, protocol PDF -> schedule of activities.

A5 mounts `router` at `/api/import`:  `from trialpilot_api.importers import router`.
"""

from __future__ import annotations

from typing import Any

__all__ = ["router"]


def __getattr__(name: str) -> Any:  # lazy, so data tools can import submodules without FastAPI
    if name == "router":
        from .router import router

        return router
    raise AttributeError(name)
