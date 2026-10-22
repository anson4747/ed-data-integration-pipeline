"""Mock EMR: load the MIMIC-IV demo extracts and replay them as live activity.

    python -m edpipe.sources.emr_sim load            # fetch, verify, load admin.raw_*
    python -m edpipe.sources.emr_sim reset           # empty live tables, rebuild event queue
    python -m edpipe.sources.emr_sim replay --events 500
    python -m edpipe.sources.emr_sim replay --all
    python -m edpipe.sources.emr_sim status
"""

from __future__ import annotations

import argparse
import sys

from edpipe.config import Settings
from edpipe.db import connect
from edpipe.sources.fetch import MIMIC_ED_DEMO, MIMIC_HOSP_DEMO, fetch, sha256_of
from edpipe.sqlload import bulk_insert, column_types, convert_rows, read_gz_csv

# file inside the dataset -> raw holding table in the source database
RAW_TABLES = {
    (MIMIC_HOSP_DEMO, "hosp/patients.csv.gz"): "admin.raw_patients",
    (MIMIC_HOSP_DEMO, "hosp/admissions.csv.gz"): "admin.raw_admissions",
    (MIMIC_HOSP_DEMO, "hosp/transfers.csv.gz"): "admin.raw_transfers",
    (MIMIC_HOSP_DEMO, "hosp/diagnoses_icd.csv.gz"): "admin.raw_diagnoses_icd",
    (MIMIC_HOSP_DEMO, "hosp/d_icd_diagnoses.csv.gz"): "admin.raw_d_icd_diagnoses",
    (MIMIC_ED_DEMO, "ed/edstays.csv.gz"): "admin.raw_edstays",
    (MIMIC_ED_DEMO, "ed/triage.csv.gz"): "admin.raw_triage",
    (MIMIC_ED_DEMO, "ed/vitalsign.csv.gz"): "admin.raw_vitalsign",
    (MIMIC_ED_DEMO, "ed/diagnosis.csv.gz"): "admin.raw_ed_diagnosis",
}


def load_raw(settings: Settings, force: bool = False) -> dict[str, int]:
    """Load every extract into its raw table. Skips a table whose last load had the same checksum."""
    for dataset in (MIMIC_ED_DEMO, MIMIC_HOSP_DEMO):
        fetch(dataset)
    loaded: dict[str, int] = {}
    with connect(settings, settings.source_db) as conn:
        for (dataset, relative), table in RAW_TABLES.items():
            path = dataset.local_dir / relative
            digest = sha256_of(path)
            last = conn.execute(
                "SELECT TOP (1) sha256, rows_loaded FROM admin.raw_load_log WHERE target_table = ? "
                "ORDER BY load_id DESC", table,
            ).fetchone()
            current_rows = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if not force and last and last[0] == digest and last[1] == current_rows:
                print(f"[load] {table}: unchanged ({current_rows:,} rows), skipped")
                loaded[table] = 0
                continue
            header, rows = read_gz_csv(path)
            types = column_types(conn, table)
            missing = [c for c in types if c not in header]
            unexpected = [c for c in header if c not in types]
            if missing or unexpected:
                raise RuntimeError(f"{relative}: schema mismatch, missing {missing}, unexpected {unexpected}")
            values = convert_rows(rows, header, types, f"{dataset.slug}/{relative}")
            conn.execute(f"DELETE FROM {table}")
            count = bulk_insert(conn, table, header, values)
            conn.execute(
                "INSERT INTO admin.raw_load_log (source_file, sha256, target_table, rows_loaded) VALUES (?, ?, ?, ?)",
                f"{dataset.slug}/{dataset.version}/{relative}", digest, table, count,
            )
            conn.commit()
            loaded[table] = count
            print(f"[load] {table}: {count:,} rows")
    return loaded


def reset(settings: Settings) -> tuple:
    with connect(settings, settings.source_db, autocommit=True) as conn:
        conn.execute("EXEC admin.usp_reset_live")
        row = conn.execute("EXEC admin.usp_build_replay_queue").fetchone()
    print(f"[reset] live tables emptied, {row[0]:,} events queued ({row[1]} to {row[2]})")
    return tuple(row)


def replay(settings: Settings, events: int | None) -> tuple[int, int]:
    """Apply the next `events` events, or everything when events is None. Returns (applied, remaining)."""
    applied_total = 0
    remaining = -1
    with connect(settings, settings.source_db, autocommit=True) as conn:
        while True:
            batch = 500 if events is None else min(500, events - applied_total)
            if batch <= 0:
                break
            applied, remaining, clock = conn.execute("EXEC admin.usp_replay_next @max_events = ?", batch).fetchone()
            applied_total += applied
            if applied:
                print(f"[replay] applied {applied:,} events, clock now {clock}, {remaining:,} remaining")
            if applied == 0 or remaining == 0:
                break
    return applied_total, remaining


def status(settings: Settings) -> None:
    with connect(settings, settings.source_db, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT 'events applied', COUNT(*) FROM admin.replay_event WHERE applied_at_utc IS NOT NULL "
            "UNION ALL SELECT 'events pending', COUNT(*) FROM admin.replay_event WHERE applied_at_utc IS NULL "
            "UNION ALL SELECT 'ed.edstays', COUNT(*) FROM ed.edstays "
            "UNION ALL SELECT 'ed.edstays still in ED', COUNT(*) FROM ed.edstays WHERE outtime IS NULL "
            "UNION ALL SELECT 'hosp.admissions', COUNT(*) FROM hosp.admissions "
            "UNION ALL SELECT 'change tracking version', CHANGE_TRACKING_CURRENT_VERSION()"
        ).fetchall()
    for label, value in rows:
        print(f"{label:>26}: {value:,}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mock EMR built from the MIMIC-IV demo datasets.")
    parser.add_argument("--env", default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    load_cmd = sub.add_parser("load", help="fetch, verify and load the raw extracts")
    load_cmd.add_argument("--force", action="store_true")
    sub.add_parser("reset", help="empty live tables and rebuild the event queue")
    replay_cmd = sub.add_parser("replay", help="release queued events into the live tables")
    group = replay_cmd.add_mutually_exclusive_group(required=True)
    group.add_argument("--events", type=int)
    group.add_argument("--all", action="store_true")
    sub.add_parser("status")
    args = parser.parse_args(argv)

    settings = Settings.load(args.env)
    if args.command == "load":
        load_raw(settings, force=args.force)
    elif args.command == "reset":
        reset(settings)
    elif args.command == "replay":
        replay(settings, None if args.all else args.events)
    else:
        status(settings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
