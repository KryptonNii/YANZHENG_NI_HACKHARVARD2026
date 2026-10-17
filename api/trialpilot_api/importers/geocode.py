"""Offline geocoding of trial sites (city + country -> lat/lon).

Uses a compact index built from the GeoNames cities1000 dump (CC BY 4.0, see
data/fixtures/ctgov/geonames/README.md). No network calls: the index ships with the repo.

Matching order, per name variant (exact -> curated alias -> cleaned suffixes /
"A / B" splits): primary GeoNames names first, then Latin-script alternate
names. When the registry gives a state/province that maps to a GeoNames admin1
region, only places inside it are accepted. Ties go to the larger population.

If no city matches but the state is known we return the most populous place in
that state (precision "admin1"). We deliberately do NOT guess a point from the
country alone: `lookup` returns None and the caller reports the site as
unresolved. Callers must surface any non-"city" precision as an assumption.
"""

from __future__ import annotations

import gzip
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml

from .paths import geonames_dir

Precision = Literal["city", "admin1"]


def norm(s: str) -> str:
    """Lowercase ASCII fold, punctuation -> single spaces."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


@dataclass(frozen=True)
class GeoResult:
    lat: float
    lon: float
    precision: Precision
    matched: str  # the name key that matched, or the fallback rule used
    source: str = "geonames:cities1000"


@dataclass(frozen=True)
class _Place:
    iso2: str
    admin1: str
    lat: float
    lon: float
    population: int


# Suffixes registries append to place names ("Chuo-ku", "Himeji-shi", "Oaxaca City", "Odense C").
_SUFFIXES = re.compile(
    r"\s+(ku|shi|gun|machi|cho|city|municipality|district|town|village|c|nv|n|s|o|v|k|sv|ii|iii|iv|\d+)$"
)


def _variants(city: str) -> list[str]:
    out: list[str] = []

    def add(v: str) -> None:
        if v and v not in out:
            out.append(v)

    add(norm(city))
    for part in re.split(r"[/,;()]| - ", city):
        add(norm(part))
    for v in list(out):
        stripped = v
        while (nxt := _SUFFIXES.sub("", stripped).strip()) and nxt != stripped:
            stripped = nxt
            add(stripped)
        add(re.split(r"\s\d+\b", v)[0].strip())  # "praha 6 brevnov" -> "praha"
        words = v.split()
        if len(words) == 2 and words[0] == words[1]:  # "lima lima" -> "lima"
            add(words[0])
    return out


class Geocoder:
    def __init__(self, geo_dir: Path | None = None) -> None:
        self.geo_dir = geo_dir or geonames_dir()
        self._primary: dict[tuple[str, str], list[_Place]] = defaultdict(list)
        self._alternate: dict[tuple[str, str], list[_Place]] = defaultdict(list)
        self._largest_in_admin1: dict[tuple[str, str], _Place] = {}
        self._countries: dict[str, str] = {}
        self._admin1: dict[tuple[str, str], str] = {}
        self._city_aliases: dict[tuple[str, str], str] = {}
        self._load()

    def _load(self) -> None:
        for line in (self.geo_dir / "countries.tsv").read_text(encoding="utf-8").splitlines():
            iso, name = line.split("\t")
            self._countries[norm(name)] = iso
        for line in (self.geo_dir / "admin1.tsv").read_text(encoding="utf-8").splitlines():
            code, name, ascii_name = line.split("\t")
            iso, a1 = code.split(".", 1)
            self._admin1[(iso, norm(name))] = a1
            self._admin1[(iso, norm(ascii_name))] = a1
        aliases = yaml.safe_load((self.geo_dir / "aliases.yaml").read_text(encoding="utf-8")) or {}
        for name, iso in (aliases.get("countries") or {}).items():
            self._countries[norm(name)] = iso
        for iso, mapping in (aliases.get("cities") or {}).items():
            for src, dst in mapping.items():
                self._city_aliases[(iso, norm(src))] = norm(dst)
        for iso, mapping in (aliases.get("admin1") or {}).items():
            for state, a1 in mapping.items():
                self._admin1[(iso, norm(state))] = str(a1)
        with gzip.open(self.geo_dir / "cities.tsv.gz", "rt", encoding="utf-8") as f:
            for line in f:
                prim, alt, iso, a1, lat, lon, pop = line.rstrip("\n").split("\t")
                place = _Place(iso, a1, float(lat), float(lon), int(pop))
                for k in prim.split("|"):
                    self._primary[(k, iso)].append(place)
                for k in alt.split("|") if alt else ():
                    self._alternate[(k, iso)].append(place)
                ka = (iso, a1)
                best = self._largest_in_admin1.get(ka)
                if best is None or place.population > best.population:
                    self._largest_in_admin1[ka] = place

    def country_iso(self, country: str) -> str | None:
        return self._countries.get(norm(country))

    def admin1_code(self, iso: str, state: str | None) -> str | None:
        return self._admin1.get((iso, norm(state))) if state else None

    def lookup(self, city: str | None, country: str, state: str | None = None) -> GeoResult | None:
        iso = self.country_iso(country)
        if iso is None:
            return None
        a1 = self.admin1_code(iso, state)
        if city:
            keys = [self._city_aliases.get((iso, v), v) for v in _variants(city)]
            for table in (self._primary, self._alternate):
                for key in keys:
                    cands = table.get((key, iso), [])
                    if a1 is not None:
                        cands = [p for p in cands if p.admin1 == a1]
                    if cands:
                        best = max(cands, key=lambda p: p.population)
                        return GeoResult(best.lat, best.lon, "city", key)
        if a1 is not None and (iso, a1) in self._largest_in_admin1:
            p = self._largest_in_admin1[(iso, a1)]
            return GeoResult(p.lat, p.lon, "admin1", f"largest place in {iso}.{a1} ({state})")
        return None


@lru_cache(maxsize=1)
def default_geocoder() -> Geocoder:
    return Geocoder()
