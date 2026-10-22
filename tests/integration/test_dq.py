"""Data quality rules against a real SQL Server, using crafted ED stays with known defects.

Crafted stays use ids from 9,000,000 so they cannot collide with replicated MIMIC data, and are removed afterwards.
Order matters: first run, lifecycle (resolve, reopen), then failure behaviour.
"""

from datetime import datetime, timedelta

import pytest

from edpipe import dq

pytestmark = pytest.mark.integration

BASE = 9_000_000
T0 = datetime(2100, 1, 1, 10, 0, 0)


def sid(n: int) -> int:
    return BASE + n


def _clean(wh):
    wh.execute("DELETE FROM dq.exception WHERE stay_id >= ? OR entity_key LIKE '%:9000%'", BASE)
    for table in ("emr_ed_vitalsign", "emr_ed_triage", "emr_ed_edstays"):
        wh.execute(f"DELETE FROM ods.{table} WHERE stay_id >= ?", BASE)
    wh.execute("DELETE FROM ods.emr_hosp_admissions WHERE hadm_id >= ?", BASE)
    wh.execute("DELETE FROM dw.fact_ed_stay WHERE stay_id >= ?", BASE)
    wh.execute("DELETE FROM dq.quality_rule WHERE rule_code = 'ZZ_BAD_RULE'")


def add_stay(wh, n, intime=T0, outtime=T0 + timedelta(hours=2), disposition="HOME", hadm=None, subject=None,
             acuity=3, triage=True, vitals=()):
    wh.execute("INSERT INTO ods.emr_ed_edstays (stay_id, subject_id, hadm_id, intime, outtime, disposition) "
               "VALUES (?, ?, ?, ?, ?, ?)", sid(n), subject or sid(n), hadm, intime, outtime, disposition)
    if triage:
        wh.execute("INSERT INTO ods.emr_ed_triage (stay_id, subject_id, acuity, pain) VALUES (?, ?, ?, '5')",
                   sid(n), subject or sid(n), acuity)
    for i, v in enumerate(vitals):
        wh.execute("INSERT INTO ods.emr_ed_vitalsign "
                   "(vitalsign_id, stay_id, subject_id, charttime, o2sat, pain, rhythm) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?)", sid(n * 10 + i), sid(n), subject or sid(n), *v)


@pytest.fixture(scope="module", autouse=True)
def crafted_stays(settings):
    from edpipe.db import connect

    with connect(settings, settings.warehouse_db, autocommit=True) as wh:
        _clean(wh)
        add_stay(wh, 1, vitals=[(T0 + timedelta(minutes=30), 98, "5", "sr"),
                                (T0 + timedelta(minutes=40), 96, "asleep", "afib")])  # clean
        add_stay(wh, 2, outtime=T0 - timedelta(hours=1))  # departs before arriving
        add_stay(wh, 3, subject=sid(34))  # duplicate pair: first
        add_stay(wh, 4, subject=sid(34))  # duplicate pair: second
        add_stay(wh, 5, vitals=[(T0 - timedelta(hours=1), 97, "3", "sr")])  # vitals before arrival
        add_stay(wh, 6, acuity=6)  # not an ESI level
        add_stay(wh, 7, disposition="ADMITTED", hadm=sid(7))  # admitted, no admission
        add_stay(wh, 8, outtime=T0 + timedelta(days=8))  # 8 day stay
        add_stay(wh, 9, acuity=None, vitals=[(T0 + timedelta(minutes=20), 10, "banana", "weird")])  # warnings only
        add_stay(wh, 10, outtime=None)  # still in ED: valid
        wh.execute("INSERT INTO ods.emr_ed_triage (stay_id, subject_id, acuity) VALUES (?, ?, 3)", sid(11), sid(11))
    yield
    with connect(settings, settings.warehouse_db, autocommit=True) as wh:
        _clean(wh)


def _open(wh, severity):
    rows = wh.execute("SELECT x.rule_code, x.stay_id FROM dq.exception AS x "
                      "JOIN dq.quality_rule AS r ON r.rule_code = x.rule_code "
                      "WHERE x.status = 'Open' AND r.severity = ? AND x.stay_id >= ?", severity, BASE).fetchall()
    found: dict[str, set[int]] = {}
    for code, stay in rows:
        found.setdefault(code, set()).add(stay - BASE)
    return found


def _fact_ids(wh):
    return {r[0] - BASE for r in wh.execute("SELECT stay_id FROM dw.fact_ed_stay WHERE stay_id >= ?", BASE).fetchall()}


def test_every_error_rule_finds_its_defect_and_nothing_else(settings, warehouse):
    result = dq.run(settings, triggered_by="pytest")
    assert _open(warehouse, "Error") == {
        "E340_DEPARTURE_NOT_AFTER_ARRIVAL": {2}, "E025_DUPLICATE_PRESENTATION": {4}, "E167_VITALS_BEFORE_ARRIVAL": {5},
        "ACUITY_NOT_ESI_LEVEL": {6}, "ADMITTED_WITHOUT_ADMISSION": {7}, "E219_LENGTH_OF_STAY_OVER_7_DAYS": {8},
        "ORPHAN_TRIAGE": {11}}
    assert result.new_errors >= 7


def test_warnings_are_recorded_but_do_not_block(warehouse):
    warnings = _open(warehouse, "Warning")
    for rule in ("O2SAT_IMPLAUSIBLE", "TRIAGE_ACUITY_MISSING", "PAIN_UNPARSEABLE", "RHYTHM_NOT_IN_VOCABULARY"):
        assert warnings.get(rule) == {9}, rule
    row = warehouse.execute("SELECT open_warning_count, esi_level FROM dw.fact_ed_stay WHERE stay_id = ?",
                            sid(9)).fetchone()
    assert row.open_warning_count >= 4 and row.esi_level is None


def test_quarantined_stays_are_held_back_and_explained(warehouse):
    assert _fact_ids(warehouse) == {1, 3, 9, 10}
    reasons = dict(warehouse.execute("SELECT stay_id, reasons FROM rpt.dq_quarantine WHERE stay_id >= ?",
                                     BASE).fetchall())
    assert "E340_DEPARTURE_NOT_AFTER_ARRIVAL" in reasons[sid(2)]
    assert set(reasons) == {sid(n) for n in (2, 4, 5, 6, 7, 8, 11)}  # 11: orphan triage, listed so nobody publishes it


def test_published_stays_carry_the_measures(warehouse):
    one = warehouse.execute("SELECT length_of_stay_min, within_four_hours, esi_level, is_open FROM dw.fact_ed_stay "
                            "WHERE stay_id = ?", sid(1)).fetchone()
    assert tuple(one) == (120, True, 3, False)
    still_in_ed = warehouse.execute("SELECT is_open, within_four_hours, length_of_stay_min FROM dw.fact_ed_stay "
                                    "WHERE stay_id = ?", sid(10)).fetchone()
    assert tuple(still_in_ed) == (True, None, None)


def test_reporting_view_standardises_pain_and_rhythm(warehouse):
    clean = warehouse.execute("SELECT rhythm, pain_score, pain_status FROM rpt.ed_vitalsign WHERE stay_id = ? "
                              "ORDER BY charttime", sid(1)).fetchall()
    assert [tuple(r) for r in clean] == [("Sinus Rhythm", 5, "Score"), ("Atrial Fibrillation", None, "Asleep")]
    messy = warehouse.execute("SELECT rhythm, pain_score, pain_status FROM rpt.ed_vitalsign WHERE stay_id = ?",
                              sid(9)).fetchone()
    assert tuple(messy) == (None, None, "Unmapped")


def test_rerun_on_unchanged_data_creates_and_resolves_nothing(settings):
    result = dq.run(settings, triggered_by="pytest")
    assert sum(r.new + r.reopened + r.resolved for r in result.rules) == 0


def test_fixing_the_data_resolves_the_exception_and_releases_the_stay(settings, warehouse):
    before = warehouse.execute("SELECT exception_id FROM dq.exception "
                               "WHERE rule_code = 'E340_DEPARTURE_NOT_AFTER_ARRIVAL' "
                               "AND stay_id = ?", sid(2)).fetchone()[0]
    warehouse.execute("UPDATE ods.emr_ed_edstays SET outtime = ? WHERE stay_id = ?", T0 + timedelta(hours=3), sid(2))
    result = dq.run(settings, triggered_by="pytest")
    row = warehouse.execute("SELECT status, resolved_run_id FROM dq.exception WHERE exception_id = ?",
                            before).fetchone()
    assert row.status == "Resolved" and row.resolved_run_id is not None
    assert sum(r.resolved for r in result.rules) == 1
    assert 2 in _fact_ids(warehouse)


def test_a_defect_that_returns_reopens_the_same_exception(settings, warehouse):
    before = warehouse.execute("SELECT exception_id FROM dq.exception "
                               "WHERE rule_code = 'E340_DEPARTURE_NOT_AFTER_ARRIVAL' "
                               "AND stay_id = ?", sid(2)).fetchone()[0]
    warehouse.execute("UPDATE ods.emr_ed_edstays SET outtime = ? WHERE stay_id = ?", T0 - timedelta(hours=1), sid(2))
    result = dq.run(settings, triggered_by="pytest")
    row = warehouse.execute("SELECT exception_id, status, resolved_run_id FROM dq.exception "
                            "WHERE rule_code = 'E340_DEPARTURE_NOT_AFTER_ARRIVAL' AND stay_id = ?", sid(2)).fetchone()
    assert (row.exception_id, row.status, row.resolved_run_id) == (before, "Open", None)
    assert sum(r.reopened for r in result.rules) == 1
    assert 2 not in _fact_ids(warehouse)


def test_a_single_rule_can_be_run_on_its_own(settings):
    result = dq.run(settings, only_rule="E340_DEPARTURE_NOT_AFTER_ARRIVAL", triggered_by="pytest")
    assert [r.rule_code for r in result.rules] == ["E340_DEPARTURE_NOT_AFTER_ARRIVAL"]


def test_a_rule_that_cannot_run_fails_the_run_loudly(settings, warehouse):
    warehouse.execute("INSERT INTO dq.quality_rule "
                      "(rule_code, severity, target_table, description, reference, check_sql) "
                      "VALUES ('ZZ_BAD_RULE', 'Warning', 'none', N'broken on purpose', N'test', "
                      "N'SELECT 1/0, N''x'', N''y''')")
    with pytest.raises(Exception, match="Divide by zero"):
        dq.run(settings, triggered_by="pytest")
    status = warehouse.execute("SELECT TOP (1) status FROM etl.pipeline_run WHERE pipeline_name = 'run_dq' "
                               "ORDER BY run_id DESC").fetchone()[0]
    alert = warehouse.execute("SELECT TOP (1) severity, alert_type FROM etl.alert ORDER BY alert_id DESC").fetchone()
    assert status == "Failed" and tuple(alert) == ("Critical", "PipelineFailed")
