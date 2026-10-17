"""Build the compact offline geocoding index from a GeoNames dump.

Source: https://download.geonames.org/export/dump/ (CC BY 4.0, see data/fixtures/ctgov/geonames/README.md).

Usage (download first, then build; nothing here touches the network):
    curl -O https://download.geonames.org/export/dump/cities1000.zip
    curl -O https://download.geonames.org/export/dump/countryInfo.txt
    curl -O https://download.geonames.org/export/dump/admin1CodesASCII.txt
    unzip cities1000.zip
    python -m trialpilot_api.importers.tools.build_geonames_index <download_dir> data/fixtures/ctgov/geonames

Output (committed):
    cities.tsv.gz   primary_keys | alternate_keys | country_iso2 | admin1_code | lat | lon | population
    countries.tsv   iso2 | name
    admin1.tsv      iso2.code | name | ascii_name
Only Latin-script alternate names are kept, to keep the file small.
"""

from __future__ import annotations

import gzip
import sys
from pathlib import Path

from trialpilot_api.importers.geocode import norm


def _is_latin(s: str) -> bool:
    return all(ord(ch) < 0x250 or not ch.isalpha() for ch in s)


def build(src: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    rows = 0
    with (
        open(src / "cities1000.txt", encoding="utf-8") as f,
        gzip.open(out / "cities.tsv.gz", "wt", encoding="utf-8", compresslevel=9) as g,
    ):
        for line in f:
            c = line.rstrip("\n").split("\t")
            primary = {norm(c[1]), norm(c[2])} - {""}
            alternates = {norm(a) for a in c[3].split(",") if a and _is_latin(a)} - primary - {""}
            if not primary:
                continue
            lat, lon = round(float(c[4]), 4), round(float(c[5]), 4)
            g.write(
                f"{'|'.join(sorted(primary))}\t{'|'.join(sorted(alternates))}\t"
                f"{c[8]}\t{c[10]}\t{lat}\t{lon}\t{c[14] or 0}\n"
            )
            rows += 1
    with open(src / "countryInfo.txt", encoding="utf-8") as f, open(out / "countries.tsv", "w", encoding="utf-8") as g:
        for line in f:
            if line.startswith("#"):
                continue
            c = line.rstrip("\n").split("\t")
            g.write(f"{c[0]}\t{c[4]}\n")
    with open(src / "admin1CodesASCII.txt", encoding="utf-8") as f, open(out / "admin1.tsv", "w", encoding="utf-8") as g:
        for line in f:
            c = line.rstrip("\n").split("\t")
            g.write(f"{c[0]}\t{c[1]}\t{c[2]}\n")
    print(f"wrote {rows} cities to {out / 'cities.tsv.gz'}")


if __name__ == "__main__":
    build(Path(sys.argv[1]), Path(sys.argv[2]))
