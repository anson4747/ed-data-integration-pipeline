"""AIHW client behaviour, with HTTP mocked. These tests never touch the real API."""

import pytest
import requests
import responses

from edpipe.sources.aihw import BASE_URL, AihwApiError, AihwClient

FLAT = f"{BASE_URL}/flat-data-extract/MYH-ED-TIME"


def make_client(**kw) -> tuple[AihwClient, list[float]]:
    sleeps: list[float] = []
    client = AihwClient(sleep=sleeps.append, jitter=lambda: 1.0, min_interval_seconds=0, **kw)
    return client, sleeps


def page(rows: list[dict], total: int, version: int = 2026081901) -> dict:
    return {
        "result": {"data": rows, "pagination": {"results_returned": len(rows), "starting_result_index": 1,
                                                 "total_results_available": total}},
        "version_information": {"api_version": "1.6.4.0", "data_version": version,
                                "date_uploaded": "2026-08-19T00:00:00"},
    }


def rows(n: int, start: int = 0) -> list[dict]:
    return [{"measure_code": "MYH0005", "value": float(i)} for i in range(start, start + n)]


@responses.activate
def test_release_reads_the_data_version():
    responses.get(f"{BASE_URL}/measure-categories", json=page([], 0) | {"result": []})
    release = make_client()[0].release()
    assert release.data_version == 2026081901
    assert release.date_uploaded == "2026-08-19T00:00:00"


@responses.activate
def test_transient_server_errors_are_retried_with_exponential_backoff():
    responses.get(FLAT, status=503)
    responses.get(FLAT, status=502, headers={"Retry-After": "7"})
    responses.get(FLAT, json=page(rows(3), 3))
    client, sleeps = make_client()
    extract = client.flat_extract("MYH-ED-TIME", "H0358")
    assert len(extract.rows) == 3
    assert sleeps == [2.0, 7.0]  # 2s backoff, then Retry-After beats the 4s backoff
    assert client.retries_made == 2


@responses.activate
def test_timeouts_and_connection_errors_are_retried():
    responses.get(FLAT, body=requests.Timeout("read timed out"))
    responses.get(FLAT, body=requests.ConnectionError("reset by peer"))
    responses.get(FLAT, json=page(rows(1), 1))
    assert len(make_client()[0].flat_extract("MYH-ED-TIME").rows) == 1


@responses.activate
def test_a_200_with_the_wrong_shape_is_treated_as_transient():
    responses.get(FLAT, body="<html>maintenance</html>")
    responses.get(FLAT, json={"unexpected": True})
    responses.get(FLAT, json=page(rows(1), 1))
    assert len(make_client()[0].flat_extract("MYH-ED-TIME").rows) == 1


@responses.activate
def test_client_errors_are_not_retried():
    responses.get(FLAT, status=400, json={"errors": {"skip": ["The skip field is required."]}})
    client, sleeps = make_client()
    with pytest.raises(AihwApiError, match="HTTP 400"):
        client.flat_extract("MYH-ED-TIME")
    assert sleeps == [] and client.requests_made == 1


@responses.activate
def test_gives_up_after_max_attempts_and_says_why():
    for _ in range(3):
        responses.get(FLAT, status=500)
    client, sleeps = make_client(max_attempts=3)
    with pytest.raises(AihwApiError, match="gave up after 3 attempts: HTTP 500"):
        client.flat_extract("MYH-ED-TIME")
    assert len(sleeps) == 2  # no pointless sleep after the final attempt


@responses.activate
def test_backoff_is_capped():
    for _ in range(6):
        responses.get(FLAT, status=503)
    client, sleeps = make_client(max_attempts=6, backoff_seconds=10, max_backoff_seconds=25)
    with pytest.raises(AihwApiError):
        client.flat_extract("MYH-ED-TIME")
    assert sleeps == [10, 20, 25, 25, 25]


@responses.activate
def test_pages_until_the_reported_total_and_sends_required_parameters():
    responses.get(FLAT, json=page(rows(2), 5))
    responses.get(FLAT, json=page(rows(2, 2), 5))
    responses.get(FLAT, json=page(rows(1, 4), 5))
    extract = make_client()[0].flat_extract("MYH-ED-TIME", "H0358", page_size=2)
    assert [r["value"] for r in extract.rows] == [0.0, 1.0, 2.0, 3.0, 4.0]
    assert extract.pages == 3 and extract.total_available == 5
    queries = [c.request.params for c in responses.calls]
    assert [(q["skip"], q["top"], q["reporting_unit_code"]) for q in queries] == [
        ("0", "2", "H0358"), ("2", "2", "H0358"), ("4", "2", "H0358")]


@responses.activate
def test_empty_extract_is_valid_when_the_api_says_total_zero():
    responses.get(FLAT, json=page([], 0))
    extract = make_client()[0].flat_extract("MYH-ED-TIME", "H9999")
    assert extract.rows == [] and extract.total_available == 0


@responses.activate
def test_short_read_is_an_error_not_a_silent_partial_load():
    responses.get(FLAT, json=page(rows(2), 5))
    responses.get(FLAT, json=page([], 5))  # API stops serving rows before the total it promised
    with pytest.raises(AihwApiError, match="expected 5 rows, received 2"):
        make_client()[0].flat_extract("MYH-ED-TIME", page_size=2)


@responses.activate
def test_release_changing_mid_extract_is_an_error():
    responses.get(FLAT, json=page(rows(2), 4, version=2026081901))
    responses.get(FLAT, json=page(rows(2, 2), 4, version=2026111001))
    with pytest.raises(AihwApiError, match="release changed from 2026081901 to 2026111001"):
        make_client()[0].flat_extract("MYH-ED-TIME", page_size=2)


@responses.activate
def test_total_changing_mid_extract_is_an_error():
    responses.get(FLAT, json=page(rows(2), 4))
    responses.get(FLAT, json=page(rows(2, 2), 6))
    with pytest.raises(AihwApiError, match="reported total changed"):
        make_client()[0].flat_extract("MYH-ED-TIME", page_size=2)


def test_page_size_is_validated_before_any_request():
    with pytest.raises(ValueError):
        make_client()[0].flat_extract("MYH-ED-TIME", page_size=1001)


@responses.activate
def test_lookup_endpoints_return_the_result_list():
    responses.get(f"{BASE_URL}/suppressions", json={"result": [{"suppression_code": "X01"}]})
    responses.get(f"{BASE_URL}/caveats", json={"result": [{"caveat_code": "X01"}]})
    client = make_client()[0]
    assert client.suppressions()[0]["suppression_code"] == "X01"
    assert client.caveats()[0]["caveat_code"] == "X01"
