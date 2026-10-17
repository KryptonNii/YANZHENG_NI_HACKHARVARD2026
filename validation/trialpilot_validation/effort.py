"""`tpv effort start|stop|show`: a stopwatch for the human-timed manual OQ baseline.

The human follows `validation/effort/manual_oq_checklist.md` (write + execute a manual OQ for five
requirements) and runs `tpv effort start manual` / `tpv effort stop manual`. tpv's own durations
come from the execution manifest. Nothing here is estimated: unmeasured means "not measured".
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .context import Ctx, TpvError, read_json, utc_now, write_json

FMT = "%Y-%m-%dT%H:%M:%SZ"


def _path(ctx: Ctx) -> Any:
    return ctx.vdir / "effort" / "effort_log.json"


def load(ctx: Ctx) -> dict[str, Any]:
    p = _path(ctx)
    return read_json(p) if p.exists() else {"sessions": []}


def start(ctx: Ctx, label: str, who: str | None) -> dict[str, Any]:
    data = load(ctx)
    if any(s["label"] == label and s.get("stopped_at") is None for s in data["sessions"]):
        raise TpvError(f"'{label}' is already running; stop it first.")
    s = {"label": label, "who": who, "started_at": utc_now(), "stopped_at": None,
         "minutes": None}
    data["sessions"].append(s)
    write_json(_path(ctx), data)
    return s


def stop(ctx: Ctx, label: str, note: str | None) -> dict[str, Any]:
    data = load(ctx)
    for s in reversed(data["sessions"]):
        if s["label"] == label and s.get("stopped_at") is None:
            s["stopped_at"] = utc_now()
            t0 = datetime.strptime(s["started_at"], FMT).replace(tzinfo=UTC)
            t1 = datetime.strptime(s["stopped_at"], FMT).replace(tzinfo=UTC)
            s["minutes"] = round((t1 - t0).total_seconds() / 60, 1)
            s["note"] = note
            write_json(_path(ctx), data)
            return s
    raise TpvError(f"No running session '{label}'.")


def summary(ctx: Ctx, run: dict[str, Any] | None) -> dict[str, Any]:
    data = load(ctx)
    manual = [s for s in data["sessions"] if s["label"] == "manual" and s.get("minutes")]
    tpv_minutes = None
    if run:
        m = run["manifest"]
        t0 = datetime.strptime(m["started_at"], FMT)
        t1 = datetime.strptime(m["finished_at"], FMT)
        tpv_minutes = round((t1 - t0).total_seconds() / 60, 1)
    return {
        "manual_oq_5_requirements_minutes": manual[-1]["minutes"] if manual else "not measured",
        "manual_sessions": manual,
        "tpv_execute_minutes_all_requirements": tpv_minutes if tpv_minutes is not None
        else "not measured",
        "note": "Manual baseline timed by a human with `tpv effort`; tpv time is wall-clock of "
                "the latest signed execution (machine time, excludes human review/approval).",
    }
