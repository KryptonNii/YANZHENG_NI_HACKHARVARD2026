# A2 — contract change proposals (for A1)

## 1. MetricRange can be unknown (proposal, non-breaking option available)
**Problem.** §2 rule 2: unknown ≠ zero. When a parameter is missing, the engine cannot compute a term.
`MetricRange.p10/p50/p90` are `float`, so the engine currently returns NaN, which pydantic serialises
as JSON `null`, while `web/src/contracts.ts` types them as `number`.

**Options.**
- (a) Keep the contract; document "NaN ⇒ null ⇒ unknown" and have A8 treat `null` as unknown. *(current behaviour)*
- (b) Change `p10/p50/p90` to `Optional[float]` (`number | null` in TS) so the type says it.

A2 recommends (b) at integration if cheap; (a) works today. No other contract changes needed.
