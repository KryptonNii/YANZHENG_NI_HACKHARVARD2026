"""Regenerate the planted-defect patch files from the committed (HEAD) versions of their targets.

    uv run --project validation python validation/defects/make_patches.py

Each defect is one exact text replacement (`old` must occur exactly once in the HEAD file). This
writes patch files only; it never modifies the working tree. `tpv defects-run` applies them in a
throwaway git worktree outside the repository.
"""

from __future__ import annotations

import difflib
import subprocess
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def head_text(path: str) -> str:
    out = subprocess.run(["git", "show", f"HEAD:{path}"], cwd=REPO, capture_output=True,
                         check=True)
    return out.stdout.decode("utf-8")


def main() -> int:
    spec = yaml.safe_load((HERE / "defects.yaml").read_text(encoding="utf-8"))
    failures = 0
    for d in spec["defects"]:
        path = d["target"]
        try:
            before = head_text(path)
        except subprocess.CalledProcessError:
            print(f"{d['id']}: {path} is not committed at HEAD — skipped", file=sys.stderr)
            failures += 1
            continue
        if d.get("append"):
            after = before + d["append"]
        else:
            n = before.count(d["old"])
            if n != 1:
                print(f"{d['id']}: expected exactly one match in {path}, found {n} — skipped",
                      file=sys.stderr)
                failures += 1
                continue
            after = before.replace(d["old"], d["new"])
        diff = difflib.unified_diff(before.splitlines(keepends=True),
                                    after.splitlines(keepends=True),
                                    fromfile=f"a/{path}", tofile=f"b/{path}", n=3)
        text = f"diff --git a/{path} b/{path}\n" + "".join(diff)
        (HERE / d["patch"]).write_text(text, encoding="utf-8", newline="\n")
        print(f"{d['id']}: wrote {d['patch']}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
