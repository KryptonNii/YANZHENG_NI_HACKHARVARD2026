"""/api/params — the parameter library with sources (read-only; A10 edits the YAML files)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ._contracts import Parameter
from .deps import services
from .errors import ApiError

router = APIRouter(prefix="/api/params", tags=["params"])


class ParamLibraryOut(BaseModel):
    ok: bool
    parameter_set_version: str
    count: int
    assumption_count: int
    loaded_at: str
    problems: list[str]
    conflicts: list[str]
    parameters: list[Parameter]


@router.get("", response_model=ParamLibraryOut)
def list_params(
    prefix: str | None = Query(default=None, description="Only ids starting with this, e.g. 'ef.'"),
    ids: str | None = Query(default=None, description="Comma-separated ids (provenance drawer)"),
    assumption: bool | None = Query(default=None, description="Only assumptions / only sourced"),
    svc: Any = Depends(services),
) -> ParamLibraryOut:
    snap = svc.params.current()
    params = list(snap.params.values())
    if prefix:
        params = [p for p in params if p.id.startswith(prefix)]
    if ids:
        wanted = {i.strip() for i in ids.split(",") if i.strip()}
        params = [p for p in params if p.id in wanted]
    if assumption is not None:
        params = [p for p in params if p.assumption is assumption]
    return ParamLibraryOut(
        ok=snap.ok, parameter_set_version=snap.version, count=len(snap.params),
        assumption_count=snap.assumption_count, loaded_at=snap.loaded_at,
        problems=snap.problems[:100], conflicts=snap.conflicts, parameters=params,
    )


@router.get("/{param_id}", response_model=Parameter)
def get_param(param_id: str, svc: Any = Depends(services)) -> Parameter:
    snap = svc.params.current()
    p = snap.params.get(param_id)
    if p is None:
        history = svc.params.history(param_id)
        if history:
            raise ApiError(404, "param_not_in_current_set",
                           f"Parameter {param_id!r} is not in the current library (it was in an "
                           "older parameter set; see /history).", {"param_id": param_id})
        raise ApiError(404, "param_not_found", f"No parameter with id {param_id!r}.",
                       {"param_id": param_id})
    return p


@router.get("/{param_id}/history", response_model=list[Parameter])
def param_history(param_id: str, svc: Any = Depends(services)) -> list[Parameter]:
    """Every stored value of this parameter (oldest first), including superseded versions."""
    history = svc.params.history(param_id)
    if not history:
        raise ApiError(404, "param_not_found", f"No parameter with id {param_id!r}.",
                       {"param_id": param_id})
    return history
