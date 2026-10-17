# A2 — contract change proposals (for A1)

## 1. MetricRange can be unknown (proposal, non-breaking option available)
**Problem.** §2 rule 2: unknown ≠ zero. When a parameter is missing, the engine cannot compute a term.
`MetricRange.p10/p50/p90` are `float`, so the engine currently returns NaN, which pydantic serialises
as JSON `null`, while `web/src/contracts.ts` types them as `number`.

**Options.**
- (a) Keep the contract; document "NaN ⇒ null ⇒ unknown" and have A8 treat `null` as unknown. *(current behaviour)*
- (b) Change `p10/p50/p90` to `Optional[float]` (`number | null` in TS) so the type says it.

A2 recommends (b) at integration if cheap; (a) works today. No other contract changes needed.

**Status: accepted as (b) in contract v2** (A1, commit 325c3cb): percentiles are `Optional[float]`, all three
numbers or all three `None`, NaN → `None`. Engine adopted it on Fri 2026-10-16 23:10 ET: `to_range` returns
`None` percentiles, `draws_from_range` turns an unknown range into NaN draws (unknown terms, warned) instead
of failing on `None` comparisons.

## 2. Well-to-tank terms (no contract change)
New `ProvenanceItem.formula_id`s `carbon.<name>_wtt.v1` (8, listed in docs/model.md §5). Same model, same
`carbon.*` prefix; consumers filtering by prefix need no change.

Caller rule, not a schema change: `ef.travel.*` and `ef.freight.*` are the direct factor only. The twin
reads `ef.wtt.*`. A value that already includes well-to-tank (the paper's rail 0.04441, the flight factors,
long-haul air freight 1.13047) must be split across the two ids. Leaving it in the direct id and also
supplying `ef.wtt.*` counts upstream fuel twice.
