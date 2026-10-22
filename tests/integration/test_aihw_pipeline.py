"""AIHW ingest against a real SQL Server, replaying a recorded sample of the live API.

Runs in file order, like a short operating history: first load, quiet rerun, a revised release,
a forced reload, then two kinds of failure. The warehouse must stay on the last good release
after each failure.
"""

import copy

import pytest

from edpipe import aihw_ingest
from edpipe.sources.aihw import AihwApiError
from edpipe.sources.aihw_replay import ReplayClient

pytestmark = pytest.mark.integration

SAMPLE = "tests/fixtures/aihw/myhospitals-sample.json.gz"
SCOPE_UNITS = 21  # 13 hospitals, 6 networks, Victoria, national (unit tests prove the selection)


@pytest.fixture(scope="module")
def sample() -> ReplayClient:
    return ReplayClient.load(SAMPLE)


@pytest.fixture(scope="module", autouse=True)
def clean_slate(settings):
    from edpipe.db import connect

    with connect(settings, settings.warehouse_db, autocommit=True) as wh:
        for table in ("ods.aihw_measurement", "ods.aihw_reporting_unit", "ref.aihw_flag_code",
                      "stg.aihw_flat_raw", "stg.aihw_slice_manifest"):
            wh.execute(f"DELETE FROM {table}")
        wh.execute("DELETE FROM etl.watermark WHERE source_name = 'aihw.myhospitals'")
    yield


def _recorded_rows(sample: ReplayClient, in_scope_units: list[str]) -> int:
    return sum(len(v["rows"]) for by_unit in sample.sample["extracts"].values()
               for unit, v in by_unit.items() if unit in in_scope_units)


def _count(wh, sql, *params):
    return wh.execute(sql, *params).fetchone()[0]


def _stored_version(wh) -> str:
    return _count(wh, "SELECT watermark_value FROM etl.watermark WHERE source_name = 'aihw.myhospitals'")


def _last_run(wh):
    return wh.execute("SELECT TOP (1) run_id, status FROM etl.pipeline_run WHERE pipeline_name = 'ingest_aihw' "
                      "ORDER BY run_id DESC").fetchone()


def test_first_load_lands_every_recorded_row_and_sets_the_release(settings, warehouse, sample):
    result = aihw_ingest.run(settings, sample, triggered_by="pytest")
    in_scope = aihw_ingest.select_scope(sample.reporting_units()[0])
    expected = _recorded_rows(sample, in_scope)
    assert not result.skipped and result.units == len(in_scope) == SCOPE_UNITS
    assert result.rows_inserted == expected and result.rows_updated == 0 and result.rows_deleted == 0
    assert _count(warehouse, "SELECT COUNT(*) FROM ods.aihw_measurement") == expected
    assert _count(warehouse, "SELECT COUNT(*) FROM ods.aihw_reporting_unit") == len(sample.reporting_units()[0])
    assert _count(warehouse, "SELECT COUNT(*) FROM ref.aihw_flag_code") == 56
    stored = warehouse.execute("SELECT watermark_value, watermark_type FROM etl.watermark "
                               "WHERE source_name = 'aihw.myhospitals'").fetchone()
    assert (int(stored[0]), stored[1]) == (sample.release().data_version, "ApiDataVersion")
    # Slice reconciliation: what landed equals what the API said it had, for every slice.
    assert _count(warehouse, "SELECT COUNT(*) FROM stg.aihw_slice_manifest AS m WHERE m.rows_expected <> ("
                             "SELECT COUNT(*) FROM stg.aihw_flat_raw AS r WHERE r.load_run_id = m.load_run_id "
                             "AND r.category_code = m.category_code AND r.reporting_unit_code = m.reporting_unit_code)"
                  ) == 0


def test_measures_are_typed_and_suppression_is_decoded(warehouse):
    statuses = dict(warehouse.execute("SELECT result_status, COUNT(*) FROM ods.aihw_measurement "
                                      "GROUP BY result_status").fetchall())
    assert statuses.get("Reported", 0) > 0
    # A withheld figure has no value, and a value is never withheld.
    assert _count(warehouse, "SELECT COUNT(*) FROM ods.aihw_measurement WHERE result_status = 'Withheld' "
                             "AND value IS NOT NULL") == 0
    assert _count(warehouse, "SELECT COUNT(*) FROM ods.aihw_measurement WHERE result_status <> 'Withheld' "
                             "AND value IS NULL") == 0
    # Every flag code on a measurement is a code AIHW published.
    codes = [r[0] for r in warehouse.execute(
        "SELECT DISTINCT caveat_codes FROM ods.aihw_measurement WHERE caveat_codes IS NOT NULL").fetchall()]
    known = {r[0] for r in warehouse.execute("SELECT flag_code FROM ref.aihw_flag_code").fetchall()}
    for combined in codes:
        for code in combined.replace(";", ",").replace("|", ",").split(","):
            assert code.strip() in known, f"unknown flag code {code!r}"


def test_the_alfred_has_a_four_hour_target_figure(warehouse):
    row = warehouse.execute(
        "SELECT TOP (1) m.value, m.units_name, u.reporting_unit_name FROM ods.aihw_measurement AS m "
        "JOIN ods.aihw_reporting_unit AS u ON u.reporting_unit_code = m.reporting_unit_code "
        "WHERE m.reporting_unit_code = 'H0358' AND m.measure_code = 'MYH0005' AND m.value IS NOT NULL "
        "ORDER BY m.reporting_end_date DESC").fetchone()
    assert row.reporting_unit_name == "The Alfred" and row.units_name == "percent" and 0 <= row.value <= 100


def test_rerun_of_an_unchanged_release_does_nothing(settings, warehouse, sample):
    before = _count(warehouse, "SELECT MAX(_loaded_run_id) FROM ods.aihw_measurement")
    result = aihw_ingest.run(settings, sample, triggered_by="pytest")
    assert result.skipped
    assert _count(warehouse, "SELECT MAX(_loaded_run_id) FROM ods.aihw_measurement") == before
    assert warehouse.execute("SELECT TOP (1) s.status FROM etl.step_run AS s JOIN etl.pipeline_run AS r "
                             "ON r.run_id = s.run_id WHERE r.pipeline_name = 'ingest_aihw' AND "
                             "s.step_name = 'check release' ORDER BY s.step_run_id DESC").fetchone()[0] == "Skipped"
    assert _last_run(warehouse).status == "Succeeded"


def test_forced_reload_of_the_same_release_changes_nothing(settings, sample):
    result = aihw_ingest.run(settings, sample, force=True, triggered_by="pytest")
    assert (result.rows_inserted, result.rows_updated, result.rows_deleted) == (0, 0, 0)
    assert result.rows_landed > 0


def test_a_revised_release_reports_what_changed(settings, warehouse, sample):
    revised = copy.deepcopy(sample.sample)
    revised["release"]["data_version"] = sample.release().data_version + 1
    rows = revised["extracts"]["MYH-ED-WAITS"]["H0358"]["rows"]
    changed_value = next(r for r in rows if r["value"] is not None)
    old_value = changed_value["value"]
    changed_value["value"] = old_value + 1.0            # one figure revised
    withdrawn = rows.pop()                              # one row withdrawn
    added = copy.deepcopy(rows[0])                      # one new period
    added["reporting_start_date"], added["reporting_end_date"] = "2099-07-01", "2100-06-30"
    rows.append(added)
    result = aihw_ingest.run(settings, ReplayClient(revised), triggered_by="pytest")
    assert (result.rows_inserted, result.rows_updated, result.rows_deleted) == (1, 1, 1)
    assert _count(warehouse, "SELECT COUNT(*) FROM ods.aihw_measurement WHERE reporting_unit_code = 'H0358' "
                             "AND reporting_start_date = '2099-07-01'") == 1
    assert _count(warehouse, "SELECT COUNT(*) FROM ods.aihw_measurement WHERE measure_code = ? AND "
                             "reported_measure_code = ? AND reporting_unit_code = 'H0358' AND "
                             "reporting_start_date = ?", withdrawn["measure_code"], withdrawn["reported_measure_code"],
                  withdrawn["reporting_start_date"]) == 0
    assert int(_stored_version(warehouse)) == sample.release().data_version + 1


def test_duplicate_rows_in_an_extract_fail_the_run_and_leave_the_release_untouched(settings, warehouse, sample):
    snapshot = _count(warehouse, "SELECT CHECKSUM_AGG(CHECKSUM(*)) FROM ods.aihw_measurement")
    version_before = _stored_version(warehouse)
    broken = copy.deepcopy(sample.sample)
    broken["release"]["data_version"] = int(version_before) + 1
    rows = broken["extracts"]["MYH-ED"]["H0358"]["rows"]
    rows.append(copy.deepcopy(rows[0]))  # what unfiltered deep paging does to a real extract
    with pytest.raises(Exception, match="Duplicate natural keys"):
        aihw_ingest.run(settings, ReplayClient(broken), triggered_by="pytest")
    assert _count(warehouse, "SELECT CHECKSUM_AGG(CHECKSUM(*)) FROM ods.aihw_measurement") == snapshot
    assert _stored_version(warehouse) == version_before
    assert _last_run(warehouse).status == "Failed"
    alert = warehouse.execute("SELECT TOP (1) severity, alert_type FROM etl.alert ORDER BY alert_id DESC").fetchone()
    assert tuple(alert) == ("Critical", "PipelineFailed")


class _FlakyClient(ReplayClient):
    """Fails after a few extracts, as the live API does when it gives up mid-run."""

    calls = 0

    def flat_extract(self, category, reporting_unit_code=None, page_size=1000):
        type(self).calls += 1
        if type(self).calls > 4:
            raise AihwApiError("GET .../flat-data-extract gave up after 5 attempts: HTTP 503")
        return super().flat_extract(category, reporting_unit_code, page_size)


def test_api_failure_midway_leaves_the_last_good_release_in_place(settings, warehouse, sample):
    rows_before = _count(warehouse, "SELECT COUNT(*) FROM ods.aihw_measurement")
    version_before = _stored_version(warehouse)
    flaky = _FlakyClient(sample.sample)
    flaky._release = type(flaky._release)(int(version_before) + 5, "2099-01-01T00:00:00", "1.6.4.0")
    with pytest.raises(AihwApiError, match="HTTP 503"):
        aihw_ingest.run(settings, flaky, triggered_by="pytest")
    assert _count(warehouse, "SELECT COUNT(*) FROM ods.aihw_measurement") == rows_before
    assert _stored_version(warehouse) == version_before
    assert _last_run(warehouse).status == "Failed"
