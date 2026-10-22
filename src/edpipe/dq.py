"""Run the data quality rules over the replicated EMR and publish the clean ED stays.

    python -m edpipe.dq                  # run every active rule, then rebuild dw.fact_ed_stay
    python -m edpipe.dq --rule E340_DEPARTURE_NOT_AFTER_ARRIVAL

Each rule is its own logged step (etl.step_run), so a slow or broken rule is named in the run history.
A rule that cannot run fails the whole run loudly: a quality check that silently did not run is worse than
none. Error findings do not fail the run; they quarantine the stay and raise a Warning alert so someone looks.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field

from edpipe.config import Settings
from edpipe.db import connect
from edpipe.runlog import PipelineRun

PIPELINE_NAME = "run_dq"


@dataclass
class RuleResult:
    rule_code: str
    severity: str
    found: int
    new: int
    reopened: int
    resolved: int


@dataclass
class DqResult:
    rules: list[RuleResult] = field(default_factory=list)
    stays_loaded: int = 0
    stays_quarantined: int = 0

    @property
    def new_errors(self) -> int:
        return sum(r.new + r.reopened for r in self.rules if r.severity == "Error")


def run(settings: Settings, only_rule: str | None = None, triggered_by: str | None = None) -> DqResult:
    result = DqResult()
    with connect(settings, settings.warehouse_db, autocommit=True) as warehouse, \
            PipelineRun(warehouse, PIPELINE_NAME, settings.environment, triggered_by) as pipeline:
        rules = [(r[0], r[1]) for r in warehouse.execute(
            "SELECT rule_code, severity FROM dq.rule WHERE is_active = 1 AND (? IS NULL OR rule_code = ?) "
            "ORDER BY CASE severity WHEN 'Error' THEN 0 ELSE 1 END, rule_code", only_rule, only_rule).fetchall()]
        if not rules:
            raise RuntimeError(f"no active rule matches {only_rule!r}" if only_rule else "no active rules")
        for code, severity in rules:
            with pipeline.step(f"rule {code}") as step:
                found, new, reopened, resolved, persisting = (int(v) for v in warehouse.execute(
                    "EXEC dq.usp_run_rule @rule_code = ?, @run_id = ?", code, pipeline.run_id).fetchone())
                step.counts(rows_read=found, rows_rejected=found, rows_inserted=new, rows_updated=reopened,
                            rows_deleted=resolved)
                step.note(f"{severity}: {found} open ({new} new, {reopened} reopened, {persisting} persisting, "
                          f"{resolved} resolved)")
                result.rules.append(RuleResult(code, severity, found, new, reopened, resolved))
                if found:
                    print(f"[dq] {severity:<7} {code:<36} open {found:>5}  new {new:>4}  resolved {resolved:>4}")
        with pipeline.step("publish clean ED stays") as step:
            result.stays_loaded, result.stays_quarantined = (int(v) for v in warehouse.execute(
                "EXEC etl.usp_load_ed_stay @run_id = ?", pipeline.run_id).fetchone())
            step.counts(rows_inserted=result.stays_loaded, rows_rejected=result.stays_quarantined)
            step.note(f"{result.stays_loaded} stays published, {result.stays_quarantined} held in quarantine")
        if result.new_errors:
            pipeline.alert("Warning", "DqErrorsFound",
                           f"{result.new_errors} new or reopened Error finding(s); "
                           f"{result.stays_quarantined} stay(s) are in quarantine (rpt.dq_quarantine)")
        print(f"[dq] {len(rules)} rules run; {result.stays_loaded} stays published, "
              f"{result.stays_quarantined} quarantined")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run data quality rules.")
    parser.add_argument("--env", default=None)
    parser.add_argument("--rule", default=None, help="run a single rule by code")
    parser.add_argument("--triggered-by", default=None)
    args = parser.parse_args(argv)
    run(Settings.load(args.env), args.rule, args.triggered_by)
    return 0


if __name__ == "__main__":
    sys.exit(main())
