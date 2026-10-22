"""Dimension and fact build against a real SQL Server, from the recorded AIHW sample.

Runs in file order. The story: first build (the Bayside Health merger is already in force), a quiet rerun,
a later period that must land on the merged network, a rename seen in the source, a future dated
reorganisation that must wait for its date, and a fact that cannot find its unit.
"""

import copy
from datetime import date
from decimal import Decimal

import pytest

from edpipe import aihw_ingest, dw_build
from edpipe.aihw_ingest import UNIT_COLUMNS, flatten_unit
from edpipe.sources.aihw_replay import ReplayClient

pytestmark = pytest.mark.integration

SAMPLE = "tests/fixtures/aihw/myhospitals-sample.json.gz"
BAYSIDE_LHNS = {"LHN253", "LHN254", "LHN268", "LHN270", "LHN271"}
BAYSIDE_HOSPITALS = ["H0320", "H0324", "H0325", "H0343", "H0344", "H0345", "H0346", "H0350", "H0356", "H0357",
                     "H0358", "H1056"]
AS_OF = date(2026, 10, 22)


@pytest.fixture(scope="module")
def sample() -> ReplayClient:
    return ReplayClient.load(SAMPLE)


@pytest.fixture(scope="module", autouse=True)
def clean_slate(settings, sample):
    from edpipe.db import connect

    with connect(settings, settings.warehouse_db, autocommit=True) as wh:
        for table in ("dw.fact_ed_measure", "dw.dim_measure", "dw.dim_reporting_unit"):
            wh.execute(f"DELETE FROM {table}")
    aihw_ingest.run(settings, sample, force=True, triggered_by="pytest")
    yield
    with connect(settings, settings.warehouse_db, autocommit=True) as wh:
        wh.execute("DELETE FROM ref.lhn_reorganisation WHERE to_network_code = 'FUTURE'")
        wh.execute("DELETE FROM ods.aihw_measurement WHERE reporting_unit_code = 'ZZZ9'")


def _one(wh, sql, *params):
    return wh.execute(sql, *params).fetchone()[0]


def _versions(wh, code):
    return [tuple(r) for r in wh.execute(
        "SELECT valid_from, valid_to, network_code, unit_name, is_current FROM dw.dim_reporting_unit "
        "WHERE reporting_unit_code = ? ORDER BY valid_from", code).fetchall()]


def _expected_bayside_four_hour(sample: ReplayClient, period_end: str):
    units, _ = sample.reporting_units()
    hospitals = {u["reporting_unit_code"] for u in units
                 if u["reporting_unit_type"]["reporting_unit_type_code"] == "H"
                 and dict(zip(UNIT_COLUMNS, flatten_unit(u, 0, 0), strict=True))["lhn_code"] in BAYSIDE_LHNS}
    num = den = n = 0.0
    for code in hospitals:
        rows = sample.sample["extracts"]["MYH-ED-TIME"].get(code, {"rows": []})["rows"]
        pick = {r["measure_code"]: r["value"] for r in rows
                if r["reporting_end_date"] == period_end and r["reported_measure_name"] == "All patients"
                and r["measure_code"] in ("MYH0005", "MYH0012")}
        if pick.get("MYH0005") is not None and pick.get("MYH0012") is not None:
            num += pick["MYH0005"] * pick["MYH0012"]
            den += pick["MYH0012"]
            n += 1
    return n, den, num / den


def test_first_build_gives_every_bayside_hospital_a_before_and_an_after(settings, warehouse):
    result = dw_build.run(settings, AS_OF, triggered_by="pytest")
    assert result.facts == _one(warehouse, "SELECT COUNT(*) FROM ods.aihw_measurement")
    assert _versions(warehouse, "H0358") == [
        (date(1900, 1, 1), date(2025, 12, 31), "LHN268", "The Alfred", False),
        (date(2026, 1, 1), date(9999, 12, 31), "BAYSIDE", "The Alfred", True)]
    for code in BAYSIDE_HOSPITALS:
        versions = _versions(warehouse, code)
        assert len(versions) == 2, code
        assert versions[0][2] in BAYSIDE_LHNS and versions[1][2] == "BAYSIDE", code
    assert len(_versions(warehouse, "H0749")) == 1          # Women's at Sandringham: another network
    assert len(_versions(warehouse, "LHN268")) == 1          # the legacy network keeps its own series
    assert _versions(warehouse, "LHN268")[0][2] == "LHN268"
    assert _one(warehouse, "SELECT network_code FROM dw.dim_reporting_unit WHERE reporting_unit_code = 'Vic'") is None


def test_dimension_has_no_gaps_overlaps_or_missing_current_version(warehouse):
    assert _one(warehouse, "SELECT COUNT(*) FROM (SELECT reporting_unit_code FROM dw.dim_reporting_unit "
                           "WHERE is_current = 1 GROUP BY reporting_unit_code HAVING COUNT(*) <> 1) AS x") == 0
    assert _one(warehouse, "SELECT COUNT(DISTINCT reporting_unit_code) FROM dw.dim_reporting_unit") == _one(
        warehouse, "SELECT COUNT(DISTINCT reporting_unit_code) FROM dw.dim_reporting_unit WHERE is_current = 1")
    # Each version starts the day after the previous one ends.
    assert _one(warehouse, "SELECT COUNT(*) FROM dw.dim_reporting_unit AS a JOIN dw.dim_reporting_unit AS b "
                           "ON b.reporting_unit_code = a.reporting_unit_code AND b.valid_from > a.valid_from "
                           "AND b.valid_from = (SELECT MIN(c.valid_from) FROM dw.dim_reporting_unit AS c "
                           "WHERE c.reporting_unit_code = a.reporting_unit_code AND c.valid_from > a.valid_from) "
                           "WHERE a.valid_to <> DATEADD(day, -1, b.valid_from)") == 0


def test_every_fact_points_at_the_unit_version_valid_in_its_period(warehouse):
    assert _one(warehouse, "SELECT COUNT(*) FROM dw.fact_ed_measure AS f JOIN dw.dim_reporting_unit AS d "
                           "ON d.unit_key = f.unit_key WHERE f.reporting_unit_code <> d.reporting_unit_code "
                           "OR f.reporting_end_date NOT BETWEEN d.valid_from AND d.valid_to") == 0
    row = warehouse.execute(
        "SELECT network_name_at_period, current_network_name, financial_year FROM rpt.ed_measure "
        "WHERE reporting_unit_code = 'H0358' AND measure_code = 'MYH0005' AND reported_measure_name = 'All patients' "
        "AND reporting_end_date = '2025-06-30'").fetchone()
    assert tuple(row) == ("Alfred Health (Vic)", "Bayside Health", "2024-25")


def test_bayside_four_hour_rollup_matches_an_independent_calculation(warehouse, sample):
    n, presentations, expected = _expected_bayside_four_hour(sample, "2025-06-30")
    row = warehouse.execute("SELECT hospitals, presentations, four_hour_percent FROM "
                            "rpt.network_ed_four_hour_current_definition WHERE network_code = 'BAYSIDE' "
                            "AND financial_year = '2024-25'").fetchone()
    assert row.hospitals == n >= 4
    assert float(row.presentations) == presentations
    assert abs(float(row.four_hour_percent) - expected) <= 0.01


def test_as_at_period_view_keeps_pre_merger_figures_under_the_old_networks(warehouse):
    networks = {r[0] for r in warehouse.execute(
        "SELECT network_code FROM rpt.network_ed_four_hour_as_at_period WHERE financial_year = '2024-25'")}
    assert "LHN268" in networks and "BAYSIDE" not in networks


def test_rerun_with_unchanged_inputs_changes_nothing(settings, warehouse):
    before = _one(warehouse, "SELECT COUNT(*) FROM dw.dim_reporting_unit")
    result = dw_build.run(settings, AS_OF, triggered_by="pytest")
    assert (result.new_units, result.versions_added, result.versions_closed, result.versions_corrected) == (0, 0, 0, 0)
    assert _one(warehouse, "SELECT COUNT(*) FROM dw.dim_reporting_unit") == before


def test_a_period_after_the_merger_lands_on_bayside_health(settings, warehouse, sample):
    revised = copy.deepcopy(sample.sample)
    revised["release"]["data_version"] += 1
    for rec in revised["extracts"]["MYH-ED-TIME"].values():
        extra = []
        for r in rec["rows"]:
            if (r["reporting_end_date"] == "2025-06-30" and r["measure_code"] in ("MYH0005", "MYH0012")
                    and r["reported_measure_name"] == "All patients"):
                nxt = copy.deepcopy(r)
                nxt["reporting_start_date"], nxt["reporting_end_date"] = "2025-07-01", "2026-06-30"
                extra.append(nxt)
        rec["rows"].extend(extra)
    aihw_ingest.run(settings, ReplayClient(revised), triggered_by="pytest")
    dw_build.run(settings, AS_OF, triggered_by="pytest")
    row = warehouse.execute(
        "SELECT network_name_at_period, financial_year FROM rpt.ed_measure WHERE reporting_unit_code = 'H0358' "
        "AND measure_code = 'MYH0005' AND reported_measure_name = 'All patients' AND reporting_end_date = '2026-06-30'"
    ).fetchone()
    assert tuple(row) == ("Bayside Health", "2025-26")
    after = warehouse.execute("SELECT hospitals FROM rpt.network_ed_four_hour_as_at_period "
                              "WHERE network_code = 'BAYSIDE' AND financial_year = '2025-26'").fetchone()
    assert after.hospitals >= 4
    # And the older figure still belongs to the old network.
    assert _one(warehouse, "SELECT network_name_at_period FROM rpt.ed_measure WHERE reporting_unit_code = 'H0358' "
                           "AND measure_code = 'MYH0005' AND reported_measure_name = 'All patients' "
                           "AND reporting_end_date = '2025-06-30'") == "Alfred Health (Vic)"


def test_a_rename_seen_in_the_source_starts_a_new_version_on_the_day_it_was_seen(settings, warehouse):
    warehouse.execute("UPDATE ods.aihw_reporting_unit SET reporting_unit_name = N'Sandringham Hospital (renamed)' "
                      "WHERE reporting_unit_code = 'H0344'")
    result = dw_build.run(settings, date(2026, 11, 1), triggered_by="pytest")
    assert result.versions_closed == 1 and result.versions_added == 1
    versions = _versions(warehouse, "H0344")
    assert [(v[0], v[1], v[3]) for v in versions] == [
        (date(1900, 1, 1), date(2025, 12, 31), "Sandringham Hospital"),
        (date(2026, 1, 1), date(2026, 10, 31), "Sandringham Hospital"),
        (date(2026, 11, 1), date(9999, 12, 31), "Sandringham Hospital (renamed)")]


def test_a_future_dated_reorganisation_waits_for_its_date_then_starts_on_it(settings, warehouse):
    warehouse.execute(
        "INSERT INTO ref.lhn_reorganisation (from_lhn_code, from_lhn_name, to_network_code, to_network_name, "
        "effective_date, source_url) VALUES ('LHN224', N'Royal Women''s Hospital (Melbourne)', 'FUTURE', "
        "N'Future Network', '2027-07-01', N'https://example.invalid/test')")
    dw_build.run(settings, date(2026, 11, 2), triggered_by="pytest")
    assert len(_versions(warehouse, "H0749")) == 1                      # not in force yet
    dw_build.run(settings, date(2027, 8, 15), triggered_by="pytest")    # learned about it six weeks late
    versions = _versions(warehouse, "H0749")
    assert [(v[0], v[1], v[2]) for v in versions] == [
        (date(1900, 1, 1), date(2027, 6, 30), "LHN224"), (date(2027, 7, 1), date(9999, 12, 31), "FUTURE")]


def test_a_reorganisation_that_matches_no_hospital_raises_a_warning(settings, warehouse):
    warehouse.execute(
        "INSERT INTO ref.lhn_reorganisation (from_lhn_code, from_lhn_name, to_network_code, to_network_name, "
        "effective_date, source_url) VALUES ('LHN999', N'Typo Network', 'FUTURE', N'Future Network', "
        "'2027-07-01', N'https://example.invalid/test')")
    try:
        result = dw_build.run(settings, date(2027, 8, 15), triggered_by="pytest")
    finally:
        warehouse.execute("DELETE FROM ref.lhn_reorganisation WHERE from_lhn_code = 'LHN999'")
    assert result.unmatched_reorganisations == 1
    alert = warehouse.execute("SELECT TOP (1) severity, alert_type FROM etl.alert ORDER BY alert_id DESC").fetchone()
    assert tuple(alert) == ("Warning", "ReorganisationUnmatched")


def test_a_measurement_for_an_unknown_unit_fails_the_fact_load_and_leaves_the_fact_alone(settings, warehouse):
    facts = _one(warehouse, "SELECT COUNT(*) FROM dw.fact_ed_measure")
    warehouse.execute(
        "INSERT INTO ods.aihw_measurement (measure_category_code, measure_code, measure_name, reported_measure_code, "
        "reported_measure_name, reported_measure_category_code, reported_measure_category_name, reporting_unit_code, "
        "reporting_start_date, reporting_end_date, value, result_status, data_version, _loaded_run_id) "
        "SELECT TOP (1) measure_category_code, measure_code, measure_name, reported_measure_code, "
        "reported_measure_name, reported_measure_category_code, reported_measure_category_name, 'ZZZ9', "
        "reporting_start_date, reporting_end_date, 50, 'Reported', data_version, _loaded_run_id "
        "FROM ods.aihw_measurement WHERE measure_code = 'MYH0005'")
    with pytest.raises(Exception, match="no dimension version"):
        dw_build.run(settings, date(2027, 8, 15), triggered_by="pytest")
    assert _one(warehouse, "SELECT COUNT(*) FROM dw.fact_ed_measure") == facts
    assert Decimal(_one(warehouse, "SELECT COUNT(*) FROM etl.pipeline_run WHERE pipeline_name = 'build_dw' "
                                   "AND status = 'Failed'")) >= 1
