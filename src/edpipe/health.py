"""Operational health check: the first command to run when a pipeline alert fires.

Prints source and warehouse row counts side by side, replay queue progress, watermarks, the
last pipeline runs, failed steps and open alerts.

    python -m edpipe.health
"""

from __future__ import annotations

import argparse

from edpipe.config import Settings
from edpipe.db import connect
from edpipe.replicate import TRACKED_TABLES


def _safe(conn, sql: str, *params):
    try:
        return conn.execute(sql, *params).fetchall()
    except Exception as exc:  # noqa: BLE001 - a health check reports, it does not stop
        return [(f"ERROR: {exc}",)]


def report(settings: Settings) -> str:
    lines: list[str] = []
    with connect(settings, settings.source_db, autocommit=True) as src, \
            connect(settings, settings.warehouse_db, autocommit=True) as wh:
        lines.append("== Source EMR ==")
        for row in _safe(src, "SELECT target_table, rows_loaded, loaded_at_utc "
                              "FROM admin.raw_load_log ORDER BY load_id"):
            lines.append("raw load  " + " | ".join(str(v) for v in row))
        for row in _safe(src, "SELECT COUNT(*), SUM(CASE WHEN applied_at_utc IS NULL THEN 1 ELSE 0 END) "
                              "FROM admin.replay_event"):
            lines.append(f"replay queue  events={row[0]}  pending={row[1] if len(row) > 1 else '?'}")
        lines.append(f"change tracking version  {_safe(src, 'SELECT CHANGE_TRACKING_CURRENT_VERSION()')[0][0]}")

        lines.append("== Source vs replica row counts ==")
        for table in TRACKED_TABLES:
            schema, name = table.split(".")
            s = _safe(src, f"SELECT COUNT(*) FROM {table}")[0][0]
            r = _safe(wh, f"SELECT COUNT(*) FROM ods.emr_{schema}_{name}")[0][0]
            flag = "" if s == r else "   <-- differs"
            lines.append(f"{table:<22} source={s}  replica={r}{flag}")

        lines.append("== Watermarks ==")
        for row in _safe(wh, "SELECT source_name, watermark_value, updated_at_utc "
                             "FROM etl.watermark ORDER BY source_name"):
            lines.append(" | ".join(str(v) for v in row))

        lines.append("== Last 5 runs ==")
        for row in _safe(wh, "SELECT TOP (5) run_id, pipeline_name, status, started_at_utc, ended_at_utc, "
                             "LEFT(error_message, 300) FROM etl.pipeline_run ORDER BY run_id DESC"):
            lines.append(" | ".join(str(v) for v in row))

        lines.append("== Failed or warning steps (last 10) ==")
        for row in _safe(wh, "SELECT TOP (10) run_id, step_name, status, LEFT(detail, 300) FROM etl.step_run "
                             "WHERE status <> 'Succeeded' ORDER BY step_run_id DESC"):
            lines.append(" | ".join(str(v) for v in row))

        lines.append("== Open alerts ==")
        for row in _safe(wh, "SELECT TOP (10) alert_id, severity, alert_type, LEFT(message, 300) FROM etl.alert "
                             "WHERE acknowledged_at_utc IS NULL ORDER BY alert_id DESC"):
            lines.append(" | ".join(str(v) for v in row))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pipeline health check.")
    parser.add_argument("--env", default=None)
    args = parser.parse_args(argv)
    print(report(Settings.load(args.env)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
