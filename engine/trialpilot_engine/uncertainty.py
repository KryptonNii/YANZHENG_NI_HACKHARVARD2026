"""Monte Carlo machinery: triangular draws with common random numbers, P10/P50/P90, variance drivers.

Every parameter is sampled from triangular(value_low, value_mid, value_high). The uniform numbers behind
a parameter depend only on (seed, parameter id), so two scenarios computed with the same seed see the
*same* draw of every shared parameter ("common random numbers"): per-draw differences between them
isolate the effect of the levers instead of sampling noise.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from functools import lru_cache
from typing import Literal

import numpy as np
import numpy.typing as npt

from ._contracts import MetricRange, Parameter

FloatArray = npt.NDArray[np.float64]
Unit = Literal["usd", "hours", "kg_co2e", "months", "patients", "percent", "kits"]

DEFAULT_SEED = 7
DEFAULT_DRAWS = 2000
PERCENTILES = (10.0, 50.0, 90.0)


@lru_cache(maxsize=8192)
def _key_entropy(key: str) -> int:
    return int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big")


def uniform_draws(seed: int, key: str, n: int) -> FloatArray:
    """`n` uniforms in [0, 1) that depend only on (seed, key): the first k of n draws equal the k draws."""
    rng = np.random.default_rng([seed % 2**63, _key_entropy(key)])
    return rng.random(n)


def triangular(u: FloatArray, low: float, mid: float, high: float) -> FloatArray:
    """Inverse CDF of triangular(low, mid, high) applied to uniforms `u`; constant when low == high."""
    if high <= low:
        return np.full(u.shape, float(low))
    span = high - low
    mode_cdf = (mid - low) / span
    left = low + np.sqrt(u * span * (mid - low))
    right = high - np.sqrt((1.0 - u) * span * (high - mid))
    return np.where(u < mode_cdf, left, right)


def parameter_draws(p: Parameter, seed: int, n: int) -> FloatArray:
    """Draws of one library parameter (common random numbers keyed by its id)."""
    return triangular(uniform_draws(seed, p.id, n), p.value_low, p.value_mid, p.value_high)


def to_range(x: FloatArray, unit: Unit) -> MetricRange:
    """P10/P50/P90 of per-draw values. NaN anywhere (unknown input) gives an unknown range (all None)."""
    if x.size == 0 or not np.all(np.isfinite(x)):
        return MetricRange(p10=None, p50=None, p90=None, unit=unit)
    p10, p50, p90 = np.percentile(x, PERCENTILES)
    return MetricRange(p10=float(p10), p50=float(p50), p90=float(p90), unit=unit)


def range_known(r: MetricRange) -> bool:
    """True when all three percentiles are numbers (contract v2: unknown = None; NaN counts as unknown)."""
    return all(q is not None and math.isfinite(q) for q in (r.p10, r.p50, r.p90))


def draws_from_range(r: MetricRange, seed: int, key: str, n: int, floor: float = 0.0) -> FloatArray:
    """Approximate per-draw values from a P10/P50/P90 range produced elsewhere (A3 forecast/supply).

    Piecewise-linear quantile function through (0.1, P10), (0.5, P50), (0.9, P90); the outer
    segments are extended linearly to quantiles 0 and 1, then clipped at `floor`. An unknown range
    (any percentile None or NaN) gives NaN draws: whatever uses them is unknown, never zero.
    """
    p10, p50, p90 = r.p10, r.p50, r.p90
    if p10 is None or p50 is None or p90 is None or not range_known(r):
        return np.full(n, np.nan)
    if not (p10 <= p50 <= p90):
        raise ValueError(f"range for {key!r} is not ordered: {p10}, {p50}, {p90}")
    lower_tail = p10 - (p50 - p10) * 0.25  # slope of the P10–P50 segment over 0.1 quantile
    upper_tail = p90 + (p90 - p50) * 0.25
    u = uniform_draws(seed, key, n)
    x = np.interp(u, [0.0, 0.1, 0.5, 0.9, 1.0], [lower_tail, p10, p50, p90, upper_tail])
    return np.maximum(x, floor)


def variance_shares(y: FloatArray, inputs: Mapping[str, FloatArray]) -> list[tuple[str, float]]:
    """Share of the variance of `y` explained by each input alone (squared Pearson correlation).

    Inputs are sampled independently, so for a near-additive model the shares add up to about 1;
    multiplicative interactions make the sum smaller. Constant inputs are skipped. Sorted, largest first.
    """
    if y.size < 2 or not np.all(np.isfinite(y)):
        return []
    yc = y - y.mean()
    sy = float(np.sqrt(yc @ yc))
    if sy == 0.0:
        return []
    shares: list[tuple[str, float]] = []
    for name, x in inputs.items():
        if x.shape != y.shape or not np.all(np.isfinite(x)):
            continue
        xc = x - x.mean()
        sx = float(np.sqrt(xc @ xc))
        if sx == 0.0:
            continue
        r = float(xc @ yc) / (sx * sy)
        shares.append((name, r * r))
    shares.sort(key=lambda item: (-item[1], item[0]))
    return shares
