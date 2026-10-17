"""The transcribed CASPS / PRIMETIME calculations reproduce the paper, except where we documented why not."""

from __future__ import annotations

import pytest

from trialpilot_science import paths
from trialpilot_science.ledger import load_ledger

LEDGERS = {tid: load_ledger(p) for tid, p in paths.LEDGERS.items()}


@pytest.mark.parametrize("tid", list(LEDGERS))
def test_summary_table_adds_up(tid: str) -> None:
    led = LEDGERS[tid]
    assert sum(led.published_modules.values()) == pytest.approx(led.published_total_kg, abs=0.5)
    assert led.published_total_kg == pytest.approx(led.published_total_main_text_kg, abs=1.0)


@pytest.mark.parametrize("tid", list(LEDGERS))
def test_figure_labels_match_summary_table(tid: str) -> None:
    led = LEDGERS[tid]
    for m, v in led.figure_modules.items():
        assert v == pytest.approx(led.published_modules[m], abs=1.0), m


@pytest.mark.parametrize("tid", list(LEDGERS))
def test_every_line_reproduces_unless_a_finding_explains_it(tid: str) -> None:
    led = LEDGERS[tid]
    explained = {lid for f in led.findings for lid in f.lines}
    off = [ln.id for ln in led.lines
           if abs(ln.recomputed_kg - ln.reported_kg) > max(0.06, 0.01 * ln.reported_kg) and ln.id not in explained]
    assert off == []


@pytest.mark.parametrize("tid", list(LEDGERS))
def test_modules_reproduce_within_rounding_except_documented(tid: str) -> None:
    led = LEDGERS[tid]
    rec = led.recomputed_by_module()
    explained_modules = {ln.module for f in led.findings if f.severity != "info" for ln in led.lines if ln.id in f.lines}
    for m, pub in led.published_modules.items():
        if m in explained_modules:
            continue
        assert rec[m] == pytest.approx(pub, rel=0.005, abs=0.5), m


def test_casps_corrections_are_the_documented_ones() -> None:
    led = LEDGERS["casps"]
    delta = sum(led.corrected_by_module().values()) - sum(led.recomputed_by_module().values())
    # centrifuge W -> kWh (-811.7) and the double-counted tissue storage (-636)
    assert delta == pytest.approx(-811.7 - 636.0, abs=1.0)


def test_primetime_hotel_slip() -> None:
    hotel = next(ln for ln in LEDGERS["primetime"].lines if ln.id == "mt-hotels")
    assert hotel.recomputed_kg == pytest.approx(111.2)
    assert hotel.reported_kg == pytest.approx(250.2)


def test_lcct_travel_factors_are_desnz_2022_plus_wtt() -> None:
    """The paper's travel factors = DESNZ 2022 direct (with RF) + WTT, to 5 decimals (docs/sources.md)."""
    pairs = {  # paper factor: (DESNZ 2022 direct, DESNZ 2022 WTT)
        0.04441: (0.03549, 0.00892),   # national rail
        0.27278: (0.24587, 0.02691),   # domestic flight
        0.17034: (0.15353, 0.01681),   # short-haul flight
        0.21423: (0.19309, 0.02114),   # long-haul flight
        0.20373: (0.18362, 0.02011),   # international flight
        2.55439: (2.30229, 0.2521),    # short-haul freight flight
        1.13047: (1.0189, 0.11157),    # long-haul freight flight
        4.98549: (4.49363, 0.49186),   # domestic freight flight
    }
    used = {ln.factor for led in LEDGERS.values() for ln in led.lines}
    for paper, (direct, wtt) in pairs.items():
        assert paper == pytest.approx(direct + wtt, abs=1e-5)
    assert {0.04441, 0.17034, 0.21423, 0.20373, 2.55439, 1.13047} <= used
