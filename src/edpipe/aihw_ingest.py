"""Load AIHW MyHospitals emergency department measures into the warehouse.

Run order:
  1. check release   ask the API for its current data_version; if it equals the version already
                     loaded (etl.watermark, source aihw.myhospitals) there is nothing to do
  2. reference data  suppression and caveat codes, and the full reporting unit list
  3. extract         for each in-scope reporting unit and ED measure category, fetch every row,
                     reconcile the count with the API's own total and land the rows as JSON
  4. apply           etl.usp_apply_aihw_release validates the landing and replaces the stored
                     slices in one transaction, then moves the release marker

Nothing reaches ods until every slice has been extracted and reconciled, and the marker moves in
the same transaction as the data, so a failed run leaves the previous release intact and can
simply be rerun.

Scope is one state (Victoria by default): its public, open hospitals, the networks they belong to,
the state, and the national figure. Each unit is requested on its own because unfiltered deep paging
returns duplicate rows (docs/aihw-api-notes.md).

    python -m edpipe.aihw_ingest                    # live API, skips if no new release
    python -m edpipe.aihw_ingest --force            # reload even if the release is unchanged
    python -m edpipe.aihw_ingest --from-fixture tests/fixtures/aihw/myhospitals-sample.json.gz
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from typing import Any, Protocol

from edpipe.config import Settings
from edpipe.db import connect, transaction
from edpipe.runlog import PipelineRun
from edpipe.sources.aihw import AihwApiError, AihwClient, ApiRelease, Extract
from edpipe.sqlload import bulk_insert

SOURCE_NAME = "aihw.myhospitals"
PIPELINE_NAME = "ingest_aihw"
CATEGORIES = ("MYH-ED-TIME", "MYH-ED", "MYH-ED-WAITS")
DEFAULT_STATE = "Vic"
NATIONAL = "NAT"


class Client(Protocol):
    """What the ingest needs from a client: the live AihwClient or a recorded replay."""

    def release(self) -> ApiRelease: ...
    def reporting_units(self) -> tuple[list[dict[str, Any]], ApiRelease]: ...
    def suppressions(self) -> list[dict[str, Any]]: ...
    def caveats(self) -> list[dict[str, Any]]: ...
    def category_measures(self, category: str) -> list[str]: ...
    def units_reporting(self, measure_code: str) -> set[str]: ...
    def flat_extract(self, category: str, reporting_unit_code: str | None = None, page_size: int = ...) -> Extract: ...


@dataclass
class IngestResult:
    skipped: bool
    data_version: int
    units: int = 0
    slices: int = 0
    rows_landed: int = 0
    rows_inserted: int = 0
    rows_updated: int = 0
    rows_deleted: int = 0


# ---- pure functions (unit tested) ---------------------------------------------------------------

def _mapped(unit: dict[str, Any], map_code: str) -> dict[str, Any] | None:
    for link in unit.get("mapped_reporting_units") or []:
        if link["map_type"]["mapped_reporting_unit_code"] == map_code:
            return link["mapped_reporting_unit"]
    return None


def state_of(unit: dict[str, Any]) -> str | None:
    if unit["reporting_unit_type"]["reporting_unit_type_code"] == "S":
        return unit["reporting_unit_code"]
    mapped = _mapped(unit, "STATE_MAPPING")
    return mapped["reporting_unit_code"] if mapped else None


def select_scope(units: list[dict[str, Any]], state: str = DEFAULT_STATE) -> list[str]:
    """Reporting unit codes to extract: the state's public open hospitals, their networks, the state, national."""
    hospitals = [u for u in units
                 if u["reporting_unit_type"]["reporting_unit_type_code"] == "H"
                 and state_of(u) == state and not u.get("closed") and not u.get("private")]
    networks = {m["reporting_unit_code"] for h in hospitals if (m := _mapped(h, "H_LHN"))}
    by_code = {u["reporting_unit_code"] for u in units}
    wanted = [h["reporting_unit_code"] for h in hospitals] + sorted(networks) + [state, NATIONAL]
    return [code for code in dict.fromkeys(wanted) if code in by_code]


def plan_slices(scope: list[str], available: dict[str, set[str]]) -> dict[str, list[str]]:
    """Per category, the in-scope units that the API says have data for it (order of scope kept)."""
    return {category: [code for code in scope if code in units] for category, units in available.items()}


def flatten_unit(unit: dict[str, Any], data_version: int, run_id: int) -> tuple:
    lhn = _mapped(unit, "H_LHN") or {}
    phn = _mapped(unit, "H_PHN") or {}
    unit_type = unit["reporting_unit_type"]
    return (
        unit["reporting_unit_code"], unit["reporting_unit_name"],
        unit_type["reporting_unit_type_code"], unit_type["reporting_unit_type_name"],
        state_of(unit), lhn.get("reporting_unit_code"), lhn.get("reporting_unit_name"),
        phn.get("reporting_unit_code"), phn.get("reporting_unit_name"),
        unit.get("latitude"), unit.get("longitude"), bool(unit.get("closed")), bool(unit.get("private")),
        "; ".join(unit.get("alternative_names") or []) or None, data_version, run_id,
    )


UNIT_COLUMNS = ["reporting_unit_code", "reporting_unit_name", "unit_type_code", "unit_type_name", "state_code",
                "lhn_code", "lhn_name", "phn_code", "phn_name", "latitude", "longitude", "is_closed", "is_private",
                "alternative_names", "data_version", "_loaded_run_id"]


def flag_rows(suppressions: list[dict[str, Any]], caveats: list[dict[str, Any]], data_version: int) -> list[tuple]:
    rows = [(s["suppression_code"], "Suppression", s.get("suppression_display_value"), s.get("suppression_name"),
             s.get("suppression_footnote"), data_version) for s in suppressions]
    rows += [(c["caveat_code"], "Caveat", c.get("caveat_display_value"), c.get("caveat_name"),
              c.get("caveat_footnote"), data_version) for c in caveats]
    return rows


def rows_to_json(rows: list[dict[str, Any]]) -> str:
    return json.dumps(rows, separators=(",", ":"), ensure_ascii=False)


# ---- pipeline ------------------------------------------------------------------------------------

def _stored_version(warehouse) -> int | None:
    row = warehouse.execute("SELECT watermark_value FROM etl.watermark WHERE source_name = ?", SOURCE_NAME).fetchone()
    return int(row[0]) if row and row[0] is not None else None


def _land_slice(warehouse, run_id: int, extract: Extract) -> int:
    unit = extract.reporting_unit_code
    with transaction(warehouse):
        warehouse.execute(
            "INSERT INTO stg.aihw_slice_manifest (load_run_id, category_code, reporting_unit_code, rows_expected, "
            "pages, data_version) VALUES (?, ?, ?, ?, ?, ?)",
            run_id, extract.category, unit, extract.total_available, extract.pages, extract.release.data_version)
        if extract.rows:
            # One round trip per slice: SQL Server splits the JSON array into one stage row per element.
            warehouse.execute(
                "INSERT INTO stg.aihw_flat_raw (load_run_id, category_code, reporting_unit_code, row_json) "
                "SELECT ?, ?, ?, [value] FROM OPENJSON(?)",
                run_id, extract.category, unit, rows_to_json(extract.rows))
    return len(extract.rows)


def run(settings: Settings, client: Client | None = None, force: bool = False, state: str = DEFAULT_STATE,
        categories: tuple[str, ...] = CATEGORIES, triggered_by: str | None = None) -> IngestResult:
    client = client or AihwClient()
    result = IngestResult(skipped=False, data_version=0)
    with connect(settings, settings.warehouse_db, autocommit=True) as warehouse, \
            PipelineRun(warehouse, PIPELINE_NAME, settings.environment, triggered_by) as pipeline:
        run_id = pipeline.run_id

        with pipeline.step("check release") as step:
            release = client.release()
            result.data_version = release.data_version
            stored = _stored_version(warehouse)
            if not force and stored == release.data_version:
                step.skip(f"No new release: data_version {release.data_version} is already loaded")
                result.skipped = True
                print(f"[aihw] no new release (data_version {release.data_version}); nothing to do")
            else:
                step.note(f"API data_version {release.data_version} (uploaded {release.date_uploaded}); "
                          f"loaded version {stored}")
        if result.skipped:
            return result

        with pipeline.step("load reference data") as step:
            units, unit_release = client.reporting_units()
            if unit_release.data_version != release.data_version:
                raise AihwApiError(f"release changed from {release.data_version} to {unit_release.data_version} "
                                   "while loading reference data; rerun to pick up the new release")
            flags = flag_rows(client.suppressions(), client.caveats(), release.data_version)
            with transaction(warehouse):
                warehouse.execute("DELETE FROM ref.aihw_flag_code")
                warehouse.execute("DELETE FROM ods.aihw_reporting_unit")
                bulk_insert(warehouse, "ref.aihw_flag_code",
                            ["flag_code", "flag_kind", "display_value", "flag_name", "footnote", "data_version"], flags)
                bulk_insert(warehouse, "ods.aihw_reporting_unit", UNIT_COLUMNS,
                            [flatten_unit(u, release.data_version, run_id) for u in units])
            step.counts(rows_read=len(units) + len(flags), rows_inserted=len(units) + len(flags))
            scope = select_scope(units, state)
            result.units = len(scope)
            step.note(f"{len(units)} reporting units, {len(flags)} flag codes; {len(scope)} units in scope for {state}")

        with pipeline.step("plan extracts") as step:
            # One call per ED measure tells us every unit that has data for it. Asking per unit instead
            # (or asking everyone) would spend most requests on units with no emergency department.
            available = {c: set().union(*(client.units_reporting(m) for m in client.category_measures(c)))
                         for c in categories}
            plan = plan_slices(scope, available)
            planned = sum(len(units) for units in plan.values())
            step.note(f"{planned} of {len(scope) * len(categories)} unit-category requests needed "
                      f"({', '.join(f'{c}: {len(u)}' for c, u in plan.items())})")
            print(f"[aihw] plan: {planned} of {len(scope) * len(categories)} unit-category requests needed")

        for category in categories:
            with pipeline.step(f"extract {category}") as step:
                landed = empty = 0
                started = time.monotonic()
                for code in plan[category]:
                    extract = client.flat_extract(category, code)
                    if extract.release.data_version != release.data_version:
                        raise AihwApiError(f"release changed from {release.data_version} to "
                                           f"{extract.release.data_version} during extract; rerun")
                    landed += _land_slice(warehouse, run_id, extract)
                    empty += 0 if extract.rows else 1
                    result.slices += 1
                if landed == 0:
                    raise AihwApiError(f"{category}: no rows for any of {len(plan[category])} reporting units; "
                                       "an empty answer for everything is a failure, not a quiet period")
                result.rows_landed += landed
                step.counts(rows_read=landed, rows_inserted=landed)
                detail = f"{len(plan[category])} units, {landed:,} rows in {time.monotonic() - started:.0f}s"
                if empty:
                    # The API listed the unit as having data and then returned none: worth a human look.
                    detail += f"; {empty} unit(s) listed as available returned no rows"
                    pipeline.alert("Warning", "AvailableButEmpty", f"{category}: {empty} unit(s) listed as "
                                   "available by the API returned no rows")
                step.note(detail, warning=bool(empty))
                print(f"[aihw] {category:<13} {landed:>7,} rows from {len(plan[category]) - empty} of "
                      f"{len(plan[category])} planned units")

        with pipeline.step("apply release") as step:
            applied = warehouse.execute(
                "EXEC etl.usp_apply_aihw_release @run_id = ?, @data_version = ?", run_id, release.data_version
            ).fetchone()
            result.rows_inserted, result.rows_updated, result.rows_deleted = applied[1], applied[2], applied[3]
            step.counts(rows_read=applied[0], rows_inserted=applied[1], rows_updated=applied[2],
                        rows_deleted=applied[3])
            step.note(f"release {release.data_version}: {applied[1]} new, {applied[2]} changed, "
                      f"{applied[3]} withdrawn")
            print(f"[aihw] applied release {release.data_version}: new {applied[1]:,}  changed {applied[2]:,}  "
                  f"withdrawn {applied[3]:,}")

        retries = getattr(client, "retries_made", 0)
        if retries:
            pipeline.alert("Info", "ApiRetries", f"{retries} API request(s) needed a retry during this run")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load AIHW MyHospitals ED measures.")
    parser.add_argument("--env", default=None)
    parser.add_argument("--force", action="store_true", help="reload even if the release is unchanged")
    parser.add_argument("--state", default=DEFAULT_STATE)
    parser.add_argument("--from-fixture", default=None, help="replay a recorded API sample instead of calling the API")
    parser.add_argument("--triggered-by", default=None)
    args = parser.parse_args(argv)
    client: Client | None = None
    if args.from_fixture:
        from edpipe.sources.aihw_replay import ReplayClient

        client = ReplayClient.load(args.from_fixture)
    run(Settings.load(args.env), client, args.force, args.state, triggered_by=args.triggered_by)
    return 0


if __name__ == "__main__":
    sys.exit(main())
