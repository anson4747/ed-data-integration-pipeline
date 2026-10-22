"""Pipeline run and step logging into etl.pipeline_run / etl.step_run / etl.alert.

Every pipeline entry point wraps its work like this:

    with PipelineRun(conn, "replicate_emr", settings.environment) as run:
        with run.step("ed.edstays") as step:
            ...
            step.counts(rows_read=10, rows_inserted=4)

A step that raises is recorded as Failed with the error text, a Critical alert is raised,
the run is marked Failed and the exception propagates, so the scheduler sees a non-zero
exit code. Nothing fails silently.
"""

from __future__ import annotations

import getpass
import socket
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field


def _truncate(text: str, limit: int = 3900) -> str:
    return text if len(text) <= limit else text[: limit - 20] + " ...[truncated]"


@dataclass
class StepHandle:
    name: str
    metrics: dict[str, int | None] = field(default_factory=dict)
    detail: str | None = None
    warning: bool = False

    def counts(self, **metrics: int | None) -> None:
        self.metrics.update(metrics)

    def note(self, detail: str, warning: bool = False) -> None:
        self.detail = detail
        self.warning = self.warning or warning


class PipelineRun:
    def __init__(self, conn, pipeline_name: str, environment: str, triggered_by: str | None = None):
        self.conn = conn  # warehouse connection with autocommit=True
        self.pipeline_name = pipeline_name
        self.environment = environment
        self.triggered_by = triggered_by or getpass.getuser()
        self.run_id: int | None = None
        self.warnings = 0

    def __enter__(self) -> PipelineRun:
        row = self.conn.execute(
            "INSERT INTO etl.pipeline_run (pipeline_name, environment, triggered_by, host_name) "
            "OUTPUT inserted.run_id VALUES (?, ?, ?, ?)",
            self.pipeline_name, self.environment, self.triggered_by, socket.gethostname(),
        ).fetchone()
        self.run_id = int(row[0])
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc is None:
            status = "SucceededWithWarnings" if self.warnings else "Succeeded"
            self.conn.execute(
                "UPDATE etl.pipeline_run SET status = ?, ended_at_utc = SYSUTCDATETIME() WHERE run_id = ?",
                status, self.run_id,
            )
        else:
            message = _truncate("".join(traceback.format_exception_only(exc_type, exc)).strip())
            self.conn.execute(
                "UPDATE etl.pipeline_run SET status = 'Failed', ended_at_utc = SYSUTCDATETIME(), "
                "error_message = ? WHERE run_id = ?",
                message, self.run_id,
            )
            self.alert("Critical", "PipelineFailed", f"{self.pipeline_name} failed: {message}")
        return False  # never swallow the exception

    def alert(self, severity: str, alert_type: str, message: str) -> None:
        self.conn.execute(
            "INSERT INTO etl.alert (run_id, severity, alert_type, message) VALUES (?, ?, ?, ?)",
            self.run_id, severity, alert_type, _truncate(message, 1990),
        )

    @contextmanager
    def step(self, name: str) -> Iterator[StepHandle]:
        step_id = int(self.conn.execute(
            "INSERT INTO etl.step_run (run_id, step_name) OUTPUT inserted.step_run_id VALUES (?, ?)",
            self.run_id, name,
        ).fetchone()[0])
        handle = StepHandle(name)
        try:
            yield handle
        except Exception as exc:
            self.conn.execute(
                "UPDATE etl.step_run SET status = 'Failed', ended_at_utc = SYSUTCDATETIME(), detail = ? "
                "WHERE step_run_id = ?",
                _truncate(f"{type(exc).__name__}: {exc}"), step_id,
            )
            raise
        if handle.warning:
            self.warnings += 1
        m = handle.metrics
        self.conn.execute(
            "UPDATE etl.step_run SET status = ?, ended_at_utc = SYSUTCDATETIME(), rows_read = ?, "
            "rows_inserted = ?, rows_updated = ?, rows_deleted = ?, rows_rejected = ?, detail = ? "
            "WHERE step_run_id = ?",
            "SucceededWithWarnings" if handle.warning else "Succeeded",
            m.get("rows_read"), m.get("rows_inserted"), m.get("rows_updated"), m.get("rows_deleted"),
            m.get("rows_rejected"), handle.detail, step_id,
        )
