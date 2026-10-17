from __future__ import annotations

import numpy as np
import pytest
from trialpilot_contracts import MetricRange

from trialpilot_engine.uncertainty import (
    draws_from_range,
    to_range,
    triangular,
    uniform_draws,
    variance_shares,
)


def test_uniform_draws_depend_only_on_seed_and_key() -> None:
    a = uniform_draws(7, "ef.travel.car.average_km", 2000)
    assert np.array_equal(a, uniform_draws(7, "ef.travel.car.average_km", 2000))
    assert not np.array_equal(a, uniform_draws(8, "ef.travel.car.average_km", 2000))
    assert not np.array_equal(a, uniform_draws(7, "ef.travel.bus.passenger_km", 2000))
    # prefix-stable: fewer draws are the first draws of more draws
    assert np.array_equal(a[:500], uniform_draws(7, "ef.travel.car.average_km", 500))


def test_triangular_matches_its_moments() -> None:
    u = uniform_draws(1, "x", 200_000)
    x = triangular(u, 2.0, 3.0, 7.0)
    assert x.min() >= 2.0 and x.max() <= 7.0
    assert x.mean() == pytest.approx((2 + 3 + 7) / 3, rel=0.01)  # mean of triangular = (a + b + c) / 3
    # mode at 3: P(x < 3) = (c - a) / (b - a) = 1 / 5
    assert (x < 3.0).mean() == pytest.approx(0.2, abs=0.01)


def test_triangular_point_value_is_constant() -> None:
    x = triangular(uniform_draws(1, "x", 10), 4.0, 4.0, 4.0)
    assert np.all(x == 4.0)


def test_to_range_is_ordered_and_nan_for_unknown() -> None:
    r = to_range(uniform_draws(3, "y", 1000), "usd")
    assert r.p10 <= r.p50 <= r.p90
    unknown = to_range(np.array([1.0, np.nan]), "usd")
    assert np.isnan(unknown.p50)


def test_draws_from_range_reproduces_the_quantiles() -> None:
    r = MetricRange(p10=20.0, p50=24.0, p90=31.0, unit="months")
    x = draws_from_range(r, 7, "a3.forecast", 100_000)
    p10, p50, p90 = np.percentile(x, [10, 50, 90])
    assert (p10, p50, p90) == pytest.approx((20.0, 24.0, 31.0), rel=0.01)


def test_draws_from_range_rejects_unordered_ranges() -> None:
    with pytest.raises(ValueError):
        draws_from_range(MetricRange(p10=3, p50=2, p90=4, unit="kits"), 7, "k", 10)


def test_variance_shares_ranks_the_dominant_input_first() -> None:
    big = uniform_draws(1, "big", 5000) * 10
    small = uniform_draws(1, "small", 5000)
    const = np.full(5000, 3.0)
    y = big + small
    shares = variance_shares(y, {"small": small, "big": big, "const": const})
    assert [name for name, _ in shares] == ["big", "small"]  # constant inputs are skipped
    # independent additive inputs: shares ≈ variance fractions 100 / 101 and 1 / 101
    assert shares[0][1] == pytest.approx(100 / 101, abs=0.01)
    assert sum(s for _, s in shares) == pytest.approx(1.0, abs=0.02)
