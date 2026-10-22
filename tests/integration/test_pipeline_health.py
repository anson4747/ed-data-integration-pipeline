"""rpt.pipeline_health against a real SQL Server, using crafted pipelines named zz_health_*.

Each test creates its own pipeline name, so tests do not depend on each other or on real runs.
"""

import pytest

pytestmark = pytest.mark.integration

PREFIX = "zz_health_"


def _clean(wh):
    wh.execute("DELETE a FROM etl.alert a JOIN etl.pipeline_run r ON r.run_id = a.run_id "
               "WHERE r.pipeline_name LIKE ?", PREFIX + "%")
    wh.execute("DELETE s FROM etl.step_run s JOIN etl.pipeline_run r ON r.run_id = s.run_id "
               "WHERE r.pipeline_name LIKE ?", PREFIX + "%")
    wh.execute("DELETE FROM etl.pipeline_run WHERE pipeline_name LIKE ?", PREFIX + "%")


@pytest.fixture()
def wh(warehouse):
    _clean(warehouse)
    yield warehouse
    _clean(warehouse)


def run(wh, name, status, error=None):
    ended = "NULL" if status == "Running" else "SYSUTCDATETIME()"
    return int(wh.execute(
        "INSERT INTO etl.pipeline_run (pipeline_name, environment, triggered_by, status, ended_at_utc, error_message) "
        f"OUTPUT inserted.run_id VALUES (?, 'test', 'pytest', ?, {ended}, ?)",
        PREFIX + name, status, error).fetchone()[0])


def alert(wh, run_id, severity, acknowledged=False):
    wh.execute("INSERT INTO etl.alert (run_id, severity, alert_type, message, acknowledged_at_utc) "
               f"VALUES (?, ?, 'Test', 'crafted', {'SYSUTCDATETIME()' if acknowledged else 'NULL'})", run_id, severity)


def health(wh, name):
    return wh.execute("SELECT health_status, last_run_status, open_critical_alerts, open_warning_alerts, "
                      "failed_steps_in_last_run, last_error, last_success_utc "
                      "FROM rpt.pipeline_health WHERE pipeline_name = ?", PREFIX + name).fetchone()


def test_clean_success_is_healthy(wh):
    run(wh, "ok", "Succeeded")
    row = health(wh, "ok")
    assert row.health_status == "Healthy"
    assert row.last_success_utc is not None


def test_failed_latest_run_is_failing_and_shows_the_error(wh):
    run(wh, "bad", "Succeeded")
    failed = run(wh, "bad", "Failed", error="ValueError: boom")
    wh.execute("INSERT INTO etl.step_run (run_id, step_name, status) VALUES (?, 'load', 'Failed')", failed)
    row = health(wh, "bad")
    assert row.health_status == "Failing"
    assert row.failed_steps_in_last_run == 1
    assert "boom" in row.last_error
    assert row.last_success_utc is not None  # the earlier success is still reported


def test_unacknowledged_warning_means_attention_until_acknowledged(wh):
    r = run(wh, "warn", "Succeeded")
    alert(wh, r, "Warning")
    row = health(wh, "warn")
    assert (row.health_status, row.open_warning_alerts) == ("Attention", 1)
    wh.execute("UPDATE etl.alert SET acknowledged_at_utc = SYSUTCDATETIME() WHERE run_id = ?", r)
    assert health(wh, "warn").health_status == "Healthy"


def test_run_with_warnings_is_attention(wh):
    run(wh, "ww", "SucceededWithWarnings")
    assert health(wh, "ww").health_status == "Attention"


def test_recovered_pipeline_stays_attention_until_the_critical_alert_is_acknowledged(wh):
    failed = run(wh, "rec", "Failed", error="down")
    alert(wh, failed, "Critical")
    run(wh, "rec", "Succeeded")
    row = health(wh, "rec")
    assert (row.health_status, row.last_run_status, row.open_critical_alerts) == ("Attention", "Succeeded", 1)


def test_info_alerts_are_ignored(wh):
    r = run(wh, "info", "Succeeded")
    alert(wh, r, "Info")
    assert health(wh, "info").health_status == "Healthy"


def test_unfinished_run_is_running(wh):
    run(wh, "busy", "Running")
    assert health(wh, "busy").health_status == "Running"


def test_only_the_latest_run_per_pipeline_is_reported(wh):
    run(wh, "once", "Failed", error="old")
    run(wh, "once", "Succeeded")
    rows = wh.execute("SELECT COUNT(*) FROM rpt.pipeline_health WHERE pipeline_name = ?", PREFIX + "once").fetchone()
    assert rows[0] == 1
    assert health(wh, "once").last_run_status == "Succeeded"
