"""A3 — enrollment forecast tests (Poisson–gamma recruitment, milestones, posterior update).

Parameter values below are TEST values chosen so expected results can be computed by hand; they are
not real-world numbers.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest
from trialpilot_contracts import Levers, Parameter, Procedure, Site, TrialDesign, Visit

from trialpilot_engine.forecast import (
    MILESTONES,
    ForecastError,
    estimate_rate_hyperparameters,
    forecast,
    update_with_actuals,
)


def p(pid: str, low: float, mid: float | None = None, high: float | None = None) -> Parameter:
    mid = low if mid is None else mid
    high = mid if high is None else high
    return Parameter(
        id=pid, label=pid, value_low=low, value_mid=mid, value_high=high, unit="test",
        assumption=True, rationale="TEST value",
    )


def params(**overrides: Parameter) -> dict[str, Parameter]:
    """Point-valued TEST parameters: activation at month 0, 0.5 patients/site/month, near-constant
    site rates, no dropout, 3-month closeout."""
    base = {
        "site.activation_months": p("site.activation_months", 0.0),
        "site.enrollment_rate_per_month": p("site.enrollment_rate_per_month", 0.5),
        "site.enrollment_rate_shape": p("site.enrollment_rate_shape", 1e4),
        "patient.dropout_rate": p("patient.dropout_rate", 0.0),
        "trial.closeout_months": p("trial.closeout_months", 3.0),
    }
    base.update({k.replace("__", "."): v for k, v in overrides.items()})
    return base


def design(
    n_sites: int = 50, target: int = 500, duration: float = 36.0, last_week: float = 52.0,
    **kw: object,
) -> TrialDesign:
    sites = [Site(id=f"site-{i:03d}", name=f"Site {i}", country="US") for i in range(n_sites)]
    visits = [Visit(number=1, label="Screening", week=-2)] + [
        Visit(
            number=i + 2, label=f"Week {w}", week=w,
            procedures=[Procedure(code="drug_dispensing", label="Study drug dispensing")],
        )
        for i, w in enumerate(range(0, int(last_week), 4))
    ] + [Visit(number=99, label="End of study", week=last_week)]
    return TrialDesign(
        id="test-design", source="fixture", title="TEST", enrollment_target=target,
        duration_months=duration, sites=sites, visits=visits, drug_type="biologic", **kw,
    )


def ordered(m: object) -> bool:
    return bool(m.p10 <= m.p50 <= m.p90)  # type: ignore[attr-defined]


# ---------------------------------------------------------------- Poisson–gamma core


def test_rate_hyperparameters_recovered_on_synthetic_data() -> None:
    rng = np.random.default_rng(1)
    alpha, mean = 2.0, 0.8
    tau = rng.uniform(6, 18, 4000)
    lam = rng.gamma(alpha, mean / alpha, tau.size)
    k = rng.poisson(lam * tau)
    mu_hat, cv_hat = estimate_rate_hyperparameters(k, tau)
    assert mu_hat == pytest.approx(mean, rel=0.03)
    assert cv_hat == pytest.approx(1 / math.sqrt(alpha), rel=0.10)


def test_forecast_recovers_mean_rate() -> None:
    # 50 sites × 0.5 patients/month = 25/month from month 0 → 500 patients in ~20 months.
    fc = forecast(design(), Levers(), params(), draws=2000)
    assert fc.months_to_full_enrollment.p50 == pytest.approx(20.0, rel=0.02)
    month10 = next(row for row in fc.enrollment_curve if row[0] == 10.0)
    assert month10[2] == pytest.approx(250, rel=0.03)  # p50 cumulative patients at month 10


def test_between_site_heterogeneity_widens_the_range() -> None:
    narrow = forecast(design(), Levers(), params(), draws=2000).months_to_full_enrollment
    wide = forecast(
        design(), Levers(),
        params(site__enrollment_rate_shape=p("site.enrollment_rate_shape", 0.5)), draws=2000,
    ).months_to_full_enrollment
    assert (wide.p90 - wide.p10) > 3 * (narrow.p90 - narrow.p10)


def test_milestones_and_duration() -> None:
    fc = forecast(design(), Levers(), params(), draws=2000)
    assert set(fc.milestone_dates) == set(MILESTONES)
    m = {k: v.p50 for k, v in fc.milestone_dates.items()}
    assert m["first_patient_in"] < m["last_patient_in"] <= m["last_patient_last_visit"] <= m["database_lock"]
    # LPLV = LPI + 52 weeks of follow-up; DB lock = LPLV + 3-month closeout (TEST params).
    assert m["last_patient_last_visit"] - m["last_patient_in"] == pytest.approx(52 * 12 / 52)
    assert m["database_lock"] - m["last_patient_last_visit"] == pytest.approx(3.0)
    assert fc.duration_months == fc.milestone_dates["database_lock"]
    assert fc.months_to_full_enrollment == fc.milestone_dates["last_patient_in"]


def test_quantiles_ordered_and_curve_monotone() -> None:
    fc = forecast(design(), Levers(), params(site__enrollment_rate_shape=p("x.y", 1.0)), draws=1000)
    assert ordered(fc.months_to_full_enrollment) and ordered(fc.duration_months)
    assert all(ordered(v) for v in fc.milestone_dates.values())
    assert all(r[1] <= r[2] <= r[3] for r in fc.enrollment_curve)
    p50 = [r[2] for r in fc.enrollment_curve]
    assert p50 == sorted(p50) and p50[0] == 0 and p50[-1] == 500


def test_dropout_inflates_patients_to_randomise() -> None:
    fc = forecast(design(), Levers(), params(patient__dropout_rate=p("patient.dropout_rate", 0.2)))
    assert fc.patients_to_randomise is not None
    assert fc.patients_to_randomise.p50 == 625  # ⌈500 / (1 − 0.2)⌉
    base = forecast(design(), Levers(), params())
    assert fc.months_to_full_enrollment.p50 > base.months_to_full_enrollment.p50


def test_determinism_by_seed() -> None:
    a = forecast(design(), Levers(), {}, seed=11, draws=500)
    b = forecast(design(), Levers(), {}, seed=11, draws=500)
    c = forecast(design(), Levers(), {}, seed=12, draws=500)
    assert a.to_dict() == b.to_dict()
    assert a.duration_months != c.duration_months


# ---------------------------------------------------------------- levers


def test_excluding_sites_lengthens_enrollment() -> None:
    d = design()
    base = forecast(d, Levers(), params())
    fewer = forecast(d, Levers(excluded_site_ids=[s.id for s in d.sites[:25]]), params())
    assert fewer.months_to_full_enrollment.p50 == pytest.approx(40.0, rel=0.03)  # half the sites
    assert fewer.duration_months.p50 > base.duration_months.p50


def test_excluding_a_site_keeps_other_sites_draws() -> None:
    d = design(n_sites=10)
    full = forecast(d, Levers(), {}, draws=200).draws
    less = forecast(d, Levers(excluded_site_ids=["site-003"]), {}, draws=200).draws
    assert full is not None and less is not None
    keep = [i for i, sid in enumerate(full.site_ids) if sid != "site-003"]
    assert np.array_equal(full.activation[:, keep], less.activation)


def test_zero_sites_is_an_explicit_error() -> None:
    with pytest.raises(ForecastError, match="no sites"):
        forecast(design(n_sites=0), Levers(), params())
    d = design(n_sites=3)
    with pytest.raises(ForecastError, match="excluded"):
        forecast(d, Levers(excluded_site_ids=[s.id for s in d.sites]), params())


def test_zero_target_is_an_explicit_error() -> None:
    with pytest.raises(ForecastError, match="enrollment_target"):
        forecast(design(target=0), Levers(), params())


def test_decentralised_visits_have_no_effect_unless_assumed() -> None:
    d = design()
    moved = [v.number for v in d.visits if v.week > 0][:6]
    base = forecast(d, Levers(), params())
    home = forecast(d, Levers(home_visit_numbers=moved), params())
    assert home.months_to_full_enrollment == base.months_to_full_enrollment
    assert any("no recruitment or retention benefit" in a for pi in home.provenance for a in pi.assumptions)
    boosted = forecast(
        d, Levers(home_visit_numbers=moved),
        params(lever__decentralised__recruitment_uplift=p("lever.decentralised.recruitment_uplift", 0.5)),
    )
    assert boosted.months_to_full_enrollment.p50 < base.months_to_full_enrollment.p50


# ---------------------------------------------------------------- honesty: fallbacks, plan rate


def test_missing_parameters_are_reported_not_silent() -> None:
    fc = forecast(design(), Levers(), {}, draws=300)
    text = " ".join(fc.warnings)
    for pid in ("site.activation_months", "patient.dropout_rate", "trial.closeout_months"):
        assert pid in text
    assert any("built-in assumption" in a for pi in fc.provenance for a in pi.assumptions)


def test_rate_derived_from_registered_plan_reproduces_planned_duration() -> None:
    d = design(duration=36.0)
    fc = forecast(d, Levers(), {}, draws=2000)  # no rate in the library → plan-implied rate
    assert fc.duration_months.p50 == pytest.approx(36.0, rel=0.05)
    assert fc.provenance[0].inputs["recruitment_rate_source"] == "plan"
    explicit = forecast(d, Levers(), params(), draws=500)
    assert explicit.provenance[0].inputs["recruitment_rate_source"] == "library"


def test_no_visit_schedule_uses_followup_parameter_and_says_so() -> None:
    d = design().model_copy(update={"visits": []})
    fc = forecast(d, Levers(), params(trial__followup_months=p("trial.followup_months", 6.0)))
    m = fc.milestone_dates
    assert m["last_patient_last_visit"].p50 - m["last_patient_in"].p50 == pytest.approx(6.0)
    assert any("no visit schedule" in w for w in fc.warnings)


# ---------------------------------------------------------------- posterior update


def _actuals(rate: float, months: float, d: TrialDesign) -> dict[str, list[tuple[float, int]]]:
    return {s.id: [(months / 2, int(rate * months / 2)), (months, int(rate * months))] for s in d.sites}


def test_posterior_update_moves_toward_fast_actuals() -> None:
    d = design()
    prior = forecast(d, Levers(), params(site__enrollment_rate_shape=p("x.y", 2.0)), draws=1000)
    fast = update_with_actuals(prior, d, _actuals(1.0, 6.0, d), params(site__enrollment_rate_shape=p("x.y", 2.0)))
    slow = update_with_actuals(prior, d, _actuals(0.2, 6.0, d), params(site__enrollment_rate_shape=p("x.y", 2.0)))
    assert fast.months_to_full_enrollment.p50 < prior.months_to_full_enrollment.p50
    assert slow.months_to_full_enrollment.p50 > prior.months_to_full_enrollment.p50
    # Fast sites: 300 enrolled by month 6, 200 to go. Posterior site rate = (α + k)/(α/m + τ) =
    # (2 + 6)/(2/0.5 + 6) = 0.8/month → 50 sites × 0.8 = 40/month → ≈ 5 more months.
    assert fast.months_to_full_enrollment.p50 == pytest.approx(6.0 + 200 / 40, rel=0.05)
    assert fast.milestone_dates["first_patient_in"].p50 <= 3.0
    assert any("Updated with actual enrolment" in w for w in fast.warnings)


def test_posterior_update_sites_without_data_are_not_zero() -> None:
    d = design()
    prior = forecast(d, Levers(), params(), draws=500)
    half = {k: v for i, (k, v) in enumerate(_actuals(0.5, 6.0, d).items()) if i < 25}
    upd = update_with_actuals(prior, d, half, params())
    # 25 reporting sites × 3 + 25 silent sites × ~3 (prior predictive) ≈ 150 by month 6.
    month6 = next(r for r in upd.enrollment_curve if r[0] == 6.0)
    assert month6[2] == pytest.approx(150, rel=0.1)
    assert any("prior predictive" in w for w in upd.warnings)


def test_actuals_must_be_cumulative() -> None:
    d = design(n_sites=2)
    prior = forecast(d, Levers(), params(), draws=100)
    with pytest.raises(ForecastError, match="cumulative"):
        update_with_actuals(prior, d, {"site-000": [(1.0, 5), (2.0, 3)]}, params())


def test_actuals_for_unknown_sites_are_ignored_with_warning() -> None:
    d = design(n_sites=2)
    prior = forecast(d, Levers(), params(), draws=100)
    upd = update_with_actuals(prior, d, {"nope": [(1.0, 5)]}, params())
    assert any("unknown site 'nope'" in w for w in upd.warnings)


# ---------------------------------------------------------------- integration


def test_result_is_json_ready_and_exposes_duration_draws() -> None:
    fc = forecast(design(), Levers(), {}, draws=400)
    json.dumps(fc.to_dict())
    assert fc.duration_draws is not None and fc.duration_draws.shape == (400,)
    assert np.percentile(fc.duration_draws, 50) == pytest.approx(fc.duration_months.p50)


def test_a2_engine_uses_the_forecast_duration(ranged_params: dict[str, Parameter]) -> None:
    from trialpilot_engine import compute_scenario

    d = design(n_sites=20, target=200)
    fc = forecast(d, Levers(), ranged_params, draws=2000)
    result = compute_scenario(d, Levers(), ranged_params, seed=7, draws=2000, forecast=fc)
    assert result.duration_months.p50 == pytest.approx(fc.duration_months.p50)
    assert result.duration_months.p90 > result.duration_months.p10
