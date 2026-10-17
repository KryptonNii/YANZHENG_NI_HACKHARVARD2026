# Offline geocoding index (GeoNames)

Used by `api/trialpilot_api/importers/geocode.py` to place trial sites whose ClinicalTrials.gov
record has no `geoPoint`. No geocoding request ever leaves the machine.

- **Source:** GeoNames export dump, https://download.geonames.org/export/dump/
  (`cities1000.zip`, `countryInfo.txt`, `admin1CodesASCII.txt`), downloaded 2026-10-16.
- **Licence:** Creative Commons Attribution 4.0 (https://creativecommons.org/licenses/by/4.0/),
  as stated in the dump's `readme.txt`. Attribution: "Contains data from GeoNames (geonames.org)".
- **Modifications:** names lower-cased and ASCII-folded; only Latin-script alternate names kept;
  coordinates rounded to 4 decimals; columns reduced to
  `primary_keys, alternate_keys, country_iso2, admin1_code, lat, lon, population`.
- **Rebuild:** see the docstring of `api/trialpilot_api/importers/tools/build_geonames_index.py`.

`aliases.yaml` holds hand-curated name mappings (e.g. "CABA" -> "Buenos Aires"). It contains no coordinates.
