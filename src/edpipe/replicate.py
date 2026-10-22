"""Incremental replication from the source EMR to the warehouse using SQL Server Change Tracking.

For each tracked table:
  1. Read the table's watermark (last Change Tracking version applied) from etl.watermark.
  2. In a SNAPSHOT transaction on the source, read the current version and the table's minimum
     valid version. If there is no watermark, or it is older than the minimum valid version
     (changes were cleaned up by retention before we read them), fall back to a FULL reload.
     Otherwise read only the net changes since the watermark from CHANGETABLE(CHANGES ...).
  3. Land the batch in stg.emr_<schema>_<table>_ct.
  4. etl.usp_apply_ct_batch applies it to ods.emr_<schema>_<table> and moves the watermark
     in the same transaction.

Rerunning after a failure is safe: the watermark only moves when the apply commits.

    python -m edpipe.replicate                 # all tables
    python -m edpipe.replicate --table ed.edstays
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from edpipe.config import Settings
from edpipe.db import connect
from edpipe.runlog import PipelineRun
from edpipe.sqlload import bulk_insert

# Reference data first, then parents before children (not required for correctness, since
# there are no foreign keys, but it keeps a half-finished run easier to reason about).
TRACKED_TABLES = (
    "hosp.d_icd_diagnoses",
    "hosp.patients",
    "hosp.admissions",
    "hosp.transfers",
    "hosp.diagnoses_icd",
    "ed.edstays",
    "ed.triage",
    "ed.vitalsign",
    "ed.diagnosis",
)


@dataclass
class TableResult:
    table: str
    mode: str
    rows_read: int
    rows_inserted: int
    rows_updated: int
    rows_deleted: int
    from_version: int | None
    to_version: int


def _columns(conn, table: str) -> tuple[list[str], list[str]]:
    """(all columns in order, primary key columns in key order) for a source table."""
    cols = [r[0] for r in conn.execute(
        "SELECT name FROM sys.columns WHERE object_id = OBJECT_ID(?) ORDER BY column_id", table).fetchall()]
    keys = [r[0] for r in conn.execute(
        "SELECT c.name FROM sys.indexes AS i "
        "JOIN sys.index_columns AS ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id "
        "JOIN sys.columns AS c ON c.object_id = ic.object_id AND c.column_id = ic.column_id "
        "WHERE i.object_id = OBJECT_ID(?) AND i.is_primary_key = 1 ORDER BY ic.key_ordinal", table).fetchall()]
    if not cols or not keys:
        raise RuntimeError(f"{table}: table missing or has no primary key (Change Tracking needs one)")
    return cols, keys


def read_watermark(warehouse, table: str) -> int | None:
    row = warehouse.execute(
        "SELECT watermark_value FROM etl.watermark WHERE source_name = ?", f"emr.{table}").fetchone()
    return int(row[0]) if row and row[0] is not None else None


def extract(source, table: str, watermark: int | None) -> tuple[str, int, list[str], list[tuple]]:
    """Return (mode, to_version, columns, rows) where each row is (operation, version, *columns)."""
    cols, keys = _columns(source, table)
    source.autocommit = False
    try:
        cursor = source.cursor()
        cursor.execute("SET TRANSACTION ISOLATION LEVEL SNAPSHOT;")
        current, min_valid = cursor.execute(
            "SELECT CHANGE_TRACKING_CURRENT_VERSION(), CHANGE_TRACKING_MIN_VALID_VERSION(OBJECT_ID(?))",
            table).fetchone()
        if min_valid is None:
            raise RuntimeError(f"{table}: Change Tracking is not enabled")
        current = int(current or 0)
        if watermark is None or watermark < int(min_valid):
            mode = "FULL"
            select_cols = ", ".join(f"t.[{c}]" for c in cols)
            rows = cursor.execute(f"SELECT 'I', CAST(NULL AS bigint), {select_cols} FROM {table} AS t").fetchall()
        else:
            mode = "INCR"
            # Key values come from CHANGETABLE so deleted rows (absent from the table) still carry their key.
            select_cols = ", ".join(f"ct.[{c}]" if c in keys else f"t.[{c}]" for c in cols)
            join = " AND ".join(f"t.[{k}] = ct.[{k}]" for k in keys)
            rows = cursor.execute(
                f"SELECT ct.SYS_CHANGE_OPERATION, ct.SYS_CHANGE_VERSION, {select_cols} "
                f"FROM CHANGETABLE(CHANGES {table}, ?) AS ct LEFT JOIN {table} AS t ON {join}",
                watermark).fetchall()
        source.commit()
    except Exception:
        source.rollback()
        raise
    finally:
        source.autocommit = True
    return mode, current, cols, [tuple(r) for r in rows]


def replicate_table(source, warehouse, table: str, run_id: int) -> TableResult:
    schema, name = table.split(".")
    stage = f"stg.emr_{schema}_{name}_ct"
    watermark = read_watermark(warehouse, table)
    mode, to_version, cols, rows = extract(source, table, watermark)

    warehouse.execute(f"TRUNCATE TABLE {stage}")
    stage_cols = ["sys_change_operation", "sys_change_version", *cols, "load_run_id"]
    bulk_insert(warehouse, stage, stage_cols, [(*r, run_id) for r in rows])
    result = warehouse.execute(
        "EXEC etl.usp_apply_ct_batch @source_table = ?, @load_mode = ?, @to_version = ?, @run_id = ?",
        table, mode, to_version, run_id).fetchone()
    return TableResult(table, result[0], result[1], result[2], result[3], result[4], watermark, to_version)


def run(settings: Settings, tables: tuple[str, ...] = TRACKED_TABLES, triggered_by: str | None = None
        ) -> list[TableResult]:
    results = []
    with connect(settings, settings.warehouse_db, autocommit=True) as warehouse, \
            connect(settings, settings.source_db, autocommit=True) as source, \
            PipelineRun(warehouse, "replicate_emr", settings.environment, triggered_by) as pipeline:
        for table in tables:
            with pipeline.step(f"replicate {table}") as step:
                r = replicate_table(source, warehouse, table, pipeline.run_id)
                step.counts(rows_read=r.rows_read, rows_inserted=r.rows_inserted,
                            rows_updated=r.rows_updated, rows_deleted=r.rows_deleted)
                note = f"{r.mode} load, CT version {r.from_version} -> {r.to_version}"
                if r.mode == "FULL" and r.from_version is not None:
                    note += " (watermark older than retention: full reload)"
                    pipeline.alert("Warning", "ReplicationFullReload",
                                   f"{table}: watermark {r.from_version} fell behind Change Tracking retention")
                    step.note(note, warning=True)
                else:
                    step.note(note)
                results.append(r)
                print(f"[replicate] {table:<22} {r.mode}  read {r.rows_read:>6,}  ins {r.rows_inserted:>6,}  "
                      f"upd {r.rows_updated:>5,}  del {r.rows_deleted:>5,}  v{r.from_version} -> v{r.to_version}")
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replicate source EMR changes into the warehouse.")
    parser.add_argument("--env", default=None)
    parser.add_argument("--table", action="append", choices=TRACKED_TABLES)
    parser.add_argument("--triggered-by", default=None)
    args = parser.parse_args(argv)
    run(Settings.load(args.env), tuple(args.table or TRACKED_TABLES), args.triggered_by)
    return 0


if __name__ == "__main__":
    sys.exit(main())
