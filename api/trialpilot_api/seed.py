"""`python -m trialpilot_api.seed` (what `make seed` runs): create/upgrade the database, load and
store the parameter library, and store A4's fixture designs. Idempotent; prints a summary."""

from __future__ import annotations

import sys

from .main import create_app


def main() -> int:
    app = create_app()
    svc = app.state.services
    snap = svc.params.current()
    from sqlmodel import Session, func, select

    from .db import DesignRow

    with Session(svc.db_engine) as s:
        designs = s.exec(select(func.count(func.distinct(DesignRow.design_id)))).one()
    print(f"database: {svc.settings.resolved_db_path}")
    if snap.ok:
        print(f"parameters: {len(snap.params)} ({snap.assumption_count} assumptions), "
              f"parameter_set_version={snap.version}")
    else:
        print(f"parameters: INVALID ({len(snap.problems)} problems)", file=sys.stderr)
        for problem in snap.problems[:20]:
            print(f"  - {problem}", file=sys.stderr)
    for c in snap.conflicts:
        print(f"  ! {c}", file=sys.stderr)
    print(f"designs stored: {designs}")
    print(f"engine ready: {svc.engine.ready}; compliance: {svc.compliance.status.get('audit')}")
    return 0 if snap.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
