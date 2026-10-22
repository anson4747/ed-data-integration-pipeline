"""End to end replication tests against a real SQL Server.

The tests share one source database and run in file order, like a short operating day:
first load, partial replay, catch-up, quiet period, a deletion, and a lost watermark.
"""

import pytest

from edpipe import replicate
from edpipe.sources import emr_sim

pytestmark = pytest.mark.integration


def _diff(settings, warehouse, table: str) -> tuple[int, int]:
    """Rows in source not in replica, and rows in replica not in source (full column comparison)."""
    schema, name = table.split(".")
    cols = [r[0] for r in warehouse.execute(
        "SELECT name FROM sys.columns WHERE object_id = OBJECT_ID(?) AND name NOT LIKE '[_]%' ORDER BY column_id",
        f"ods.emr_{schema}_{name}").fetchall()]
    col_list = ", ".join(f"[{c}]" for c in cols)
    src = f"[{settings.source_db}].{schema}.{name}"
    ods = f"ods.emr_{schema}_{name}"
    missing = warehouse.execute(f"SELECT COUNT(*) FROM (SELECT {col_list} FROM {src} EXCEPT "
                                f"SELECT {col_list} FROM {ods}) AS x").fetchone()[0]
    extra = warehouse.execute(f"SELECT COUNT(*) FROM (SELECT {col_list} FROM {ods} EXCEPT "
                              f"SELECT {col_list} FROM {src}) AS x").fetchone()[0]
    return missing, extra


def _assert_reconciled(settings, warehouse):
    for table in replicate.TRACKED_TABLES:
        assert _diff(settings, warehouse, table) == (0, 0), f"{table} does not reconcile"


@pytest.fixture(scope="module", autouse=True)
def fresh_source(settings):
    emr_sim.load_raw(settings)
    emr_sim.reset(settings)
    yield


def test_first_run_is_a_full_load(settings, warehouse):
    emr_sim.replay(settings, 300)
    results = {r.table: r for r in replicate.run(settings, triggered_by="pytest")}
    if all(r.from_version is None for r in results.values()):
        assert {r.mode for r in results.values()} == {"FULL"}
    _assert_reconciled(settings, warehouse)


def test_incremental_catch_up_applies_inserts_and_updates(settings, warehouse):
    emr_sim.replay(settings, None)
    results = {r.table: r for r in replicate.run(settings, triggered_by="pytest")}
    assert results["ed.edstays"].mode == "INCR"
    # Stays that arrived in the first replay window departed later: those are updates.
    assert results["ed.edstays"].rows_updated > 0
    _assert_reconciled(settings, warehouse)
    still_in_ed = warehouse.execute("SELECT COUNT(*) FROM ods.emr_ed_edstays WHERE outtime IS NULL").fetchone()[0]
    assert still_in_ed == 0


def test_rerun_with_no_source_changes_changes_nothing(settings, warehouse):
    results = replicate.run(settings, triggered_by="pytest")
    for r in results:
        assert (r.rows_read, r.rows_inserted, r.rows_updated, r.rows_deleted) == (0, 0, 0, 0), r.table


def test_source_delete_is_replicated(settings, warehouse, source):
    stay_id = source.execute("SELECT TOP (1) stay_id FROM ed.triage ORDER BY stay_id").fetchone()[0]
    source.execute("DELETE FROM ed.triage WHERE stay_id = ?", stay_id)
    results = {r.table: r for r in replicate.run(settings, tables=("ed.triage",), triggered_by="pytest")}
    assert results["ed.triage"].rows_deleted == 1
    assert warehouse.execute("SELECT COUNT(*) FROM ods.emr_ed_triage WHERE stay_id = ?", stay_id).fetchone()[0] == 0
    _assert_reconciled(settings, warehouse)


def test_watermark_behind_retention_forces_full_reload_and_warns(settings, warehouse):
    warehouse.execute("UPDATE etl.watermark SET watermark_value = '-1' WHERE source_name = 'emr.ed.edstays'")
    results = {r.table: r for r in replicate.run(settings, tables=("ed.edstays",), triggered_by="pytest")}
    assert results["ed.edstays"].mode == "FULL"
    _assert_reconciled(settings, warehouse)
    warning = warehouse.execute(
        "SELECT TOP (1) alert_type FROM etl.alert ORDER BY alert_id DESC").fetchone()[0]
    assert warning == "ReplicationFullReload"


def test_every_run_is_logged(warehouse):
    failed = warehouse.execute(
        "SELECT COUNT(*) FROM etl.pipeline_run WHERE pipeline_name = 'replicate_emr' AND status = 'Failed'"
    ).fetchone()[0]
    steps = warehouse.execute(
        "SELECT COUNT(*) FROM etl.step_run AS s JOIN etl.pipeline_run AS r ON r.run_id = s.run_id "
        "WHERE r.pipeline_name = 'replicate_emr' AND s.status IN ('Succeeded', 'SucceededWithWarnings')"
    ).fetchone()[0]
    assert failed == 0
    assert steps >= len(replicate.TRACKED_TABLES) * 3
