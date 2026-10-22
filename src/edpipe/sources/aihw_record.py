"""Record a small, real sample of the AIHW API for tests and offline use.

Calls the live API through the same client the pipeline uses, for a handful of reporting units,
and writes everything the pipeline needs (release, flag codes, reporting units, ED extracts) to one
gzipped JSON file. The reporting unit list is trimmed to the recorded units plus a few extra units that
exist only to prove scope selection leaves them out (another state, closed, private).

    python -m edpipe.sources.aihw_record --out tests/fixtures/aihw/myhospitals-sample.json.gz

AIHW MyHospitals data is published by the Australian Institute of Health and Welfare under CC BY 4.0.
"""

from __future__ import annotations

import argparse
import gzip
import json
from datetime import UTC, datetime
from pathlib import Path

from edpipe.aihw_ingest import CATEGORIES
from edpipe.sources.aihw import AihwClient

# Bayside Health from 1 Jan 2026 = Alfred Health + Peninsula Health + Bass Coast Health + Gippsland Southern
# Health Service + Kooweerup Regional Health Service. Every hospital of those five networks, the five networks,
# plus the Women's at Sandringham and its network (public, no ED), Victoria and national.
RECORD_UNITS = [
    "H0358", "H0344", "H0345", "H0350", "H0343", "H0356", "H0357", "H1056",  # Alfred Health, Peninsula Health
    "H0320", "H0324", "H0325", "H0346",                                      # Bass Coast, Gippsland Southern, Kooweerup
    "H0749", "LHN268", "LHN270", "LHN253", "LHN254", "LHN271", "LHN224", "Vic", "NAT",
]
# Present in the unit list only, to prove the scope filter drops them: NSW public, Vic closed, Vic private.
KEEP_ONLY_UNITS = ["H0021", "H0355", "H5203"]


def record(out: Path, units: list[str], keep_only: list[str]) -> None:
    client = AihwClient()
    release = client.release()
    all_units, _ = client.reporting_units()
    wanted = set(units) | set(keep_only)
    missing = wanted - {u["reporting_unit_code"] for u in all_units}
    if missing:
        raise SystemExit(f"reporting units not found in the API: {sorted(missing)}")
    extracts: dict[str, dict[str, dict]] = {}
    availability: dict[str, dict] = {}
    for category in CATEGORIES:
        measures = client.category_measures(category)
        availability[category] = {
            "measures": measures,
            # Only the recorded units are kept: the live answer covers about 400 units per measure.
            "units": {m: sorted(client.units_reporting(m) & set(units)) for m in measures},
        }
        extracts[category] = {}
        for code in units:
            extract = client.flat_extract(category, code)
            print(f"{category:<13} {code:<8} {len(extract.rows):>5} rows")
            if extract.rows:
                extracts[category][code] = {"rows": extract.rows}
    sample = {
        "recorded_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": "https://myhospitalsapi.aihw.gov.au/api/v1 (AIHW, CC BY 4.0)",
        "release": {"data_version": release.data_version, "date_uploaded": release.date_uploaded,
                    "api_version": release.api_version},
        "suppressions": client.suppressions(),
        "caveats": client.caveats(),
        "reporting_units": [u for u in all_units if u["reporting_unit_code"] in wanted],
        "availability": availability,
        "extracts": extracts,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out, "wt", encoding="utf-8", compresslevel=9) as handle:
        json.dump(sample, handle, ensure_ascii=False, separators=(",", ":"))
    print(f"wrote {out} ({out.stat().st_size:,} bytes), {client.requests_made} requests, "
          f"{client.retries_made} retries")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record an AIHW API sample.")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--unit", action="append", help="reporting unit to record (repeatable)")
    parser.add_argument("--keep-only", action="append", help="unit kept in the list but not extracted")
    args = parser.parse_args(argv)
    record(args.out, args.unit or RECORD_UNITS, args.keep_only or KEEP_ONLY_UNITS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
