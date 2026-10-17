# Effort baseline — write and execute one manual OQ for 5 requirements

Purpose: an honest comparison for the "Software Speedrun" effort claim. A **human** times the
traditional way; tpv's own time comes from its execution manifest. Until someone does this, the
package and slides say **"not measured"**.

## Scope (fixed, so the comparison is fair)
URS-015 (audit trail records every change) · URS-018 (PIN re-authentication + lockout) ·
URS-021 (no self-approval) · URS-028 (audit export complete) · URS-029 (offline mode).

## Steps
1. `uv run --project validation tpv effort start manual --who "<your name>"`
2. **Write** a manual test script in a document (Word/Markdown) for the 5 requirements: for each,
   test steps, expected result, a pass/fail box, and a place for evidence (screenshot name).
3. **Execute** it by hand against the running app (`make dev`, http://localhost:5173 and
   http://localhost:8000/docs): perform each step, take a screenshot per step, record pass/fail,
   sign and date the script.
4. **Trace**: fill a small table requirement → test step → result → screenshot file name.
5. `uv run --project validation tpv effort stop manual --note "5 requirements, manual"`
6. `uv run --project validation tpv effort show` prints both numbers; the latest is copied into the
   validation package (`effort` block in `package_index.json`).

## What to report (A11 slide)
- Manual: minutes from step 1 to step 5 (one person, one attempt — say so).
- tpv: wall-clock of `tpv execute` for **all** requirements (machine time) — plus, separately, the
  human time spent reviewing/approving the protocol and report, which tpv does not remove.
- If not measured, write "not measured". Do not estimate.
