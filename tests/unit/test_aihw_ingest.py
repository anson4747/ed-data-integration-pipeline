"""Scope selection and flattening, checked against a real recorded API sample."""

from pathlib import Path

import pytest

from edpipe.aihw_ingest import (
    UNIT_COLUMNS,
    flag_rows,
    flatten_unit,
    plan_slices,
    rows_to_json,
    select_scope,
    state_of,
)
from edpipe.sources.aihw_replay import ReplayClient

SAMPLE = Path(__file__).parent.parent / "fixtures" / "aihw" / "myhospitals-sample.json.gz"


@pytest.fixture(scope="module")
def sample() -> ReplayClient:
    return ReplayClient.load(SAMPLE)


def test_scope_is_public_open_hospitals_of_the_state_their_networks_state_and_national(sample):
    units, _ = sample.reporting_units()
    scope = select_scope(units, "Vic")
    assert set(scope) == {
        "H0320", "H0324", "H0325", "H0343", "H0344", "H0345", "H0346", "H0350", "H0356", "H0357", "H0358",
        "H0749", "H1056", "LHN224", "LHN253", "LHN254", "LHN268", "LHN270", "LHN271", "Vic", "NAT"}


def test_scope_leaves_out_other_states_closed_and_private_units(sample):
    units, _ = sample.reporting_units()
    scope = select_scope(units, "Vic")
    assert "H0021" not in scope  # NSW public hospital
    assert "H0355" not in scope  # Victorian but closed
    assert "H5203" not in scope  # Victorian but private


def test_scope_has_no_duplicates_and_lists_hospitals_before_networks(sample):
    units, _ = sample.reporting_units()
    scope = select_scope(units, "Vic")
    assert len(scope) == len(set(scope))
    assert scope.index("H0358") < scope.index("LHN268") < scope.index("Vic")


def test_scope_for_a_state_with_no_units_is_just_national(sample):
    units, _ = sample.reporting_units()
    assert select_scope(units, "Tas") == ["NAT"]


def test_state_of_reads_the_mapping_and_treats_a_state_as_itself(sample):
    units = {u["reporting_unit_code"]: u for u in sample.reporting_units()[0]}
    assert state_of(units["H0358"]) == "Vic"
    assert state_of(units["H0021"]) == "NSW"
    assert state_of(units["Vic"]) == "Vic"


def test_flatten_unit_pulls_network_and_state_out_of_the_mappings(sample):
    unit = next(u for u in sample.reporting_units()[0] if u["reporting_unit_code"] == "H0358")
    row = dict(zip(UNIT_COLUMNS, flatten_unit(unit, 2026081901, 7), strict=True))
    assert row["reporting_unit_name"] == "The Alfred"
    assert (row["state_code"], row["lhn_code"], row["lhn_name"]) == ("Vic", "LHN268", "Alfred Health (Vic)")
    assert row["phn_code"] == "PHN201"
    assert row["is_closed"] is False and row["is_private"] is False
    assert row["data_version"] == 2026081901 and row["_loaded_run_id"] == 7


def test_flag_rows_keep_suppression_and_caveat_codes_apart(sample):
    rows = flag_rows(sample.suppressions(), sample.caveats(), 1)
    kinds = {(code, kind) for code, kind, *_ in rows}
    assert ("X01", "Suppression") in kinds and ("X01", "Caveat") in kinds
    assert len(kinds) == len(rows)  # (code, kind) is a usable primary key


def test_every_recorded_slice_is_clean_and_matches_its_request(sample):
    for category, by_unit in sample.sample["extracts"].items():
        for unit, recorded in by_unit.items():
            rows = recorded["rows"]
            keys = [(r["measure_code"], r["reported_measure_code"], r["reporting_unit_code"],
                     r["reporting_start_date"], r["reporting_end_date"]) for r in rows]
            assert len(keys) == len(set(keys)), f"{category}/{unit} has duplicate natural keys"
            assert {r["reporting_unit_code"] for r in rows} <= {unit}
            assert {r["measure_category_code"] for r in rows} <= {category}


def test_replay_of_an_unrecorded_unit_is_empty_like_the_real_api(sample):
    extract = sample.flat_extract("MYH-ED", "H9999")
    assert extract.rows == [] and extract.total_available == 0


def test_rows_to_json_is_compact_and_round_trips():
    text = rows_to_json([{"a": 1, "b": "é"}])
    assert text == '[{"a":1,"b":"é"}]'


def test_plan_slices_keeps_only_units_the_api_lists_and_keeps_scope_order():
    plan = plan_slices(["H1", "H2", "LHN1", "Vic"], {"A": {"Vic", "H2"}, "B": set(), "C": {"H1", "LHN1", "X"}})
    assert plan == {"A": ["H2", "Vic"], "B": [], "C": ["H1", "LHN1"]}


def test_availability_in_the_sample_predicts_exactly_which_units_have_rows(sample):
    for category, availability in sample.sample["availability"].items():
        listed = set().union(*(set(units) for units in availability["units"].values()))
        assert listed == set(sample.sample["extracts"][category])
