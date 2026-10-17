"""Offline geocoder: specific cases + accuracy measured against real registry geoPoints."""

from __future__ import annotations

import json
import math
import statistics

from trialpilot_api.importers.geocode import default_geocoder

from .conftest import ALL_NCT, REAL_FIXTURES


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def test_specific_cases() -> None:
    g = default_geocoder()
    caba = g.lookup("CABA", "Argentina", "Buenos Aires")
    assert caba is not None and _km(caba.lat, caba.lon, -34.61, -58.38) < 30
    chuo = g.lookup("Chuo-ku", "Japan", "Tokyo")
    assert chuo is not None and _km(chuo.lat, chuo.lon, 35.68, 139.77) < 30
    praha = g.lookup("Praha 6 - Brevnov", "Czechia")
    assert praha is not None and _km(praha.lat, praha.lon, 50.08, 14.42) < 20
    assert g.lookup("Nowhere-ville", "Atlantis") is None  # unknown country: no guess
    assert g.lookup(None, "France") is None  # never a country-centroid guess


def test_accuracy_against_registry_geopoints() -> None:
    """For every site that HAS a registry geoPoint, geocode its city and compare (recorded in HANDOFF)."""
    g = default_geocoder()
    errors: list[float] = []
    misses = 0
    total = 0
    for nct in ALL_NCT:
        raw = json.loads((REAL_FIXTURES / "ctgov" / f"{nct}.json").read_text(encoding="utf-8"))
        for loc in raw["protocolSection"]["contactsLocationsModule"]["locations"]:
            gp = loc.get("geoPoint")
            if not gp:
                continue
            total += 1
            hit = g.lookup(loc.get("city"), loc.get("country") or "", loc.get("state"))
            if hit is None:
                misses += 1
                continue
            errors.append(_km(hit.lat, hit.lon, gp["lat"], gp["lon"]))
    match_rate = len(errors) / total
    median = statistics.median(errors)
    within_25 = sum(e <= 25 for e in errors) / len(errors)
    print(f"\ngeocoder: {total} sites with geoPoints, match rate {match_rate:.1%}, "
          f"median error {median:.1f} km, {within_25:.1%} within 25 km, p95 {sorted(errors)[int(0.95 * len(errors))]:.1f} km")
    assert match_rate >= 0.95
    assert median < 5.0
    assert within_25 >= 0.90
