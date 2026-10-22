"""Build the warehouse layer (dimension and fact) from the ODS layer.

    python -m edpipe.dw_build                    # as of today
    python -m edpipe.dw_build --as-of 2026-03-01 # as the reorganisation table should be read on that date

Steps: dim_reporting_unit (Type 2, applies dated network reorganisations), then dim_measure and
fact_ed_measure (rebuilt from the ODS layer). Each step is one stored procedure in one transaction.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime

from edpipe.config import Settings
from edpipe.db import connect
from edpipe.runlog import PipelineRun

PIPELINE_NAME = "build_dw"


@dataclass
class BuildResult:
    new_units: int
    versions_added: int
    versions_closed: int
    versions_corrected: int
    unmatched_reorganisations: int
    measures: int
    facts: int


def run(settings: Settings, as_of: date | None = None, triggered_by: str | None = None) -> BuildResult:
    as_of = as_of or datetime.now(UTC).date()
    with connect(settings, settings.warehouse_db, autocommit=True) as warehouse, \
            PipelineRun(warehouse, PIPELINE_NAME, settings.environment, triggered_by) as pipeline:
        with pipeline.step("dim_reporting_unit") as step:
            r = warehouse.execute("EXEC etl.usp_load_dim_reporting_unit @run_id = ?, @as_of = ?",
                                  pipeline.run_id, as_of).fetchone()
            new_units, added, closed, corrected, type1, unmatched = (int(v) for v in r)
            step.counts(rows_inserted=added, rows_updated=closed + corrected + type1)
            note = (f"as of {as_of}: {new_units} new units, {added} versions added, {closed} closed, "
                    f"{corrected} corrected in place, {type1} type 1 updates")
            if unmatched:
                # A reorganisation that matches no hospital does nothing, which looks exactly like success.
                note += f"; {unmatched} reorganisation row(s) matched no hospital"
                pipeline.alert("Warning", "ReorganisationUnmatched",
                               f"{unmatched} row(s) in ref.lhn_reorganisation match no hospital's network code")
            step.note(note, warning=bool(unmatched))
        with pipeline.step("fact_ed_measure") as step:
            measures, facts = (int(v) for v in warehouse.execute(
                "EXEC etl.usp_load_ed_fact @run_id = ?", pipeline.run_id).fetchone())
            step.counts(rows_inserted=facts)
            step.note(f"{measures} measures, {facts:,} fact rows")
        print(f"[dw] dimension: {new_units} new units, {added} versions added, {closed} closed; "
              f"fact: {facts:,} rows, {measures} measures")
    return BuildResult(new_units, added, closed, corrected, unmatched, measures, facts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the warehouse dimension and fact.")
    parser.add_argument("--env", default=None)
    parser.add_argument("--as-of", type=date.fromisoformat, default=None)
    parser.add_argument("--triggered-by", default=None)
    args = parser.parse_args(argv)
    run(Settings.load(args.env), args.as_of, args.triggered_by)
    return 0


if __name__ == "__main__":
    sys.exit(main())
