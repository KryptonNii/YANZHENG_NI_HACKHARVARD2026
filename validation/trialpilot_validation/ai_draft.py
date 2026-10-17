"""Optional AI drafting of prose (never results, counts, evidence or signatures).

Off unless `--ai-draft` is passed. Skipped (returns None) when DEMO_OFFLINE=1 or no
ANTHROPIC_API_KEY is set. Callers stamp the returned text "DRAFT — requires human review".
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_MODEL = "claude-sonnet-5-5"


def draft(prompt: str, *, max_tokens: int = 300) -> str | None:
    if os.environ.get("DEMO_OFFLINE", "0").strip().lower() in ("1", "true", "yes"):
        print("tpv: AI drafting skipped (DEMO_OFFLINE=1); using template text only.",
              file=sys.stderr)
        return None
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        print("tpv: AI drafting skipped (no ANTHROPIC_API_KEY); using template text only.",
              file=sys.stderr)
        return None
    body = json.dumps({
        "model": os.environ.get("TPV_DRAFT_MODEL", DEFAULT_MODEL),
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body, method="POST",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        print(f"tpv: AI drafting failed ({exc}); using template text only.", file=sys.stderr)
        return None
    parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    text = "\n".join(p for p in parts if p).strip()
    return text or None
