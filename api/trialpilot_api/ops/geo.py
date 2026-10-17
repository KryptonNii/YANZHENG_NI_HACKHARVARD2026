"""Geography helpers for the ops simulator: country normalisation, regions, distances, regional hubs.

Hub placements (central labs / drug depots) are SIMULATED facilities in real cities, used only to
derive distances for the simulated feed. City coordinates are approximate city centroids.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Common country names (ClinicalTrials.gov style) -> ISO 3166-1 alpha-2.
_NAME_TO_ISO2 = {
    "united states": "US", "usa": "US", "canada": "CA", "united kingdom": "GB", "uk": "GB",
    "france": "FR", "germany": "DE", "spain": "ES", "italy": "IT", "netherlands": "NL",
    "belgium": "BE", "switzerland": "CH", "austria": "AT", "ireland": "IE", "portugal": "PT",
    "denmark": "DK", "sweden": "SE", "norway": "NO", "finland": "FI", "poland": "PL",
    "czechia": "CZ", "czech republic": "CZ", "hungary": "HU", "romania": "RO", "bulgaria": "BG",
    "slovakia": "SK", "ukraine": "UA", "serbia": "RS", "greece": "GR", "brazil": "BR",
    "argentina": "AR", "mexico": "MX", "chile": "CL", "colombia": "CO", "peru": "PE",
    "australia": "AU", "new zealand": "NZ", "japan": "JP", "korea, republic of": "KR",
    "south korea": "KR", "republic of korea": "KR", "china": "CN", "taiwan": "TW",
    "singapore": "SG", "india": "IN", "thailand": "TH", "malaysia": "MY", "south africa": "ZA",
    "israel": "IL", "turkey": "TR", "türkiye": "TR", "russian federation": "RU", "russia": "RU",
}

_REGION = {
    **dict.fromkeys(["US", "CA"], "North America"),
    **dict.fromkeys(
        ["GB", "FR", "DE", "ES", "IT", "NL", "BE", "CH", "AT", "IE", "PT", "DK", "SE", "NO", "FI", "GR"],
        "Western Europe",
    ),
    **dict.fromkeys(["PL", "CZ", "HU", "RO", "BG", "SK", "UA", "RS", "RU"], "Eastern Europe"),
    **dict.fromkeys(["BR", "AR", "MX", "CL", "CO", "PE"], "Latin America"),
    **dict.fromkeys(["AU", "NZ"], "Oceania"),
    **dict.fromkeys(["JP", "KR", "CN", "TW", "SG", "IN", "TH", "MY"], "Asia"),
    **dict.fromkeys(["ZA"], "Africa"),
    **dict.fromkeys(["IL", "TR"], "Middle East"),
}

# Southern-hemisphere countries (used when a site has no latitude).
_SOUTH = {"BR", "AR", "CL", "PE", "AU", "NZ", "ZA"}

# Regions where rail is a normal choice for 250–700 km monitoring trips.
RAIL_REGIONS = {"Western Europe", "Eastern Europe", "Asia"}


@dataclass(frozen=True)
class Hub:
    id: str
    label: str
    lat: float
    lon: float


# SIMULATED regional hubs (central lab + drug depot share a location for simplicity).
HUBS = {
    "EU": Hub("EU", "EU central lab & depot (Frankfurt, DE) — simulated", 50.11, 8.68),
    "US": Hub("US", "US central lab & depot (Indianapolis, US) — simulated", 39.77, -86.16),
    "LATAM": Hub("LATAM", "LatAm central lab & depot (São Paulo, BR) — simulated", -23.55, -46.63),
    "APAC": Hub("APAC", "APAC central lab & depot (Singapore, SG) — simulated", 1.35, 103.82),
}

_REGION_HUB = {
    "North America": "US",
    "Western Europe": "EU",
    "Eastern Europe": "EU",
    "Africa": "EU",
    "Middle East": "EU",
    "Latin America": "LATAM",
    "Oceania": "APAC",
    "Asia": "APAC",
}


def iso2(country: str) -> str:
    c = (country or "").strip()
    if len(c) == 2 and c.isalpha():
        return c.upper()
    return _NAME_TO_ISO2.get(c.lower(), c.upper()[:2] or "XX")


def region_of(country: str) -> str:
    return _REGION.get(iso2(country), "Other")


def hemisphere_of(country: str, lat: float | None) -> str:
    if lat is not None:
        return "south" if lat < 0 else "north"
    return "south" if iso2(country) in _SOUTH else "north"


def hub_for_region(region: str) -> Hub:
    return HUBS[_REGION_HUB.get(region, "EU")]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))
