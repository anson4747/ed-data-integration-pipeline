"""Client for the AIHW MyHospitals API (https://myhospitalsapi.aihw.gov.au).

What the API is like, from probing it (see docs/aihw-api-notes.md):

* The data endpoint is /flat-data-extract/{measure-category}. ``skip`` and ``top`` are both
  required and ``top`` is capped at 1000.
* Deep offset paging over a whole category is unreliable: the same rows can be returned on
  more than one page and large unfiltered requests time out. Filtering to one reporting unit
  (a hospital, a network, a state) returns small, consistent result sets. This client is
  built for that use, and it checks every extract against the total the API reports.
* Past-the-end offsets and unknown categories return an empty 200, not an error, so an empty
  result is never taken as proof that the request was valid.
* Every response carries ``version_information.data_version``. That is the release marker
  the pipeline uses to decide whether there is anything new to load.

Failure handling: transient failures (timeouts, connection errors, 408/429/5xx, a body that is
not the JSON shape the API documents) are retried with exponential backoff and jitter, and
Retry-After is honoured. Client errors (400, 404) are not retried because repeating them
cannot succeed. After the last attempt the client raises AihwApiError with the URL and cause.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://myhospitalsapi.aihw.gov.au/api/v1"
MAX_PAGE_SIZE = 1000
RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})
USER_AGENT = "ed-data-integration-pipeline/0.1 (portfolio project; polite client)"


class AihwApiError(RuntimeError):
    """The API could not give us a valid answer, after retries where retrying makes sense."""


@dataclass(frozen=True)
class ApiRelease:
    """The data release a response came from."""

    data_version: int
    date_uploaded: str
    api_version: str


@dataclass(frozen=True)
class Extract:
    """All rows for one (category, reporting unit) request, with the release they came from."""

    category: str
    reporting_unit_code: str | None
    rows: list[dict[str, Any]]
    total_available: int
    release: ApiRelease
    pages: int


class AihwClient:
    def __init__(
        self,
        base_url: str = BASE_URL,
        session: requests.Session | None = None,
        timeout: tuple[float, float] = (10.0, 90.0),
        max_attempts: int = 5,
        backoff_seconds: float = 2.0,
        max_backoff_seconds: float = 60.0,
        min_interval_seconds: float = 0.2,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = lambda: random.uniform(0.5, 1.0),
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        # Assigned, not setdefault: a Session already carries a "python-requests/x" User-Agent, and the
        # API's gateway answers that one with 403 Forbidden. An identifying agent is accepted.
        self.session.headers["Accept"] = "application/json"
        self.session.headers["User-Agent"] = USER_AGENT
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self.min_interval_seconds = min_interval_seconds
        self._sleep = sleep
        self._jitter = jitter
        self._last_request_at: float | None = None
        self.requests_made = 0
        self.retries_made = 0

    # ---- transport -------------------------------------------------------------------------

    def _pause_between_requests(self) -> None:
        if self._last_request_at is not None and self.min_interval_seconds > 0:
            wait = self.min_interval_seconds - (time.monotonic() - self._last_request_at)
            if wait > 0:
                self._sleep(wait)

    def _delay_for(self, attempt: int, retry_after: str | None) -> float:
        backoff = min(self.max_backoff_seconds, self.backoff_seconds * (2 ** (attempt - 1))) * self._jitter()
        if retry_after and retry_after.strip().isdigit():
            return min(self.max_backoff_seconds, max(backoff, float(retry_after)))
        return backoff

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET a path and return the parsed JSON body (which always has a ``result`` key)."""
        url = f"{self.base_url}/{path.lstrip('/')}"
        last_problem = "no attempt made"
        for attempt in range(1, self.max_attempts + 1):
            self._pause_between_requests()
            retry_after = None
            try:
                self.requests_made += 1
                response = self.session.get(url, params=params, timeout=self.timeout)
                self._last_request_at = time.monotonic()
            except (requests.ConnectionError, requests.Timeout) as exc:
                self._last_request_at = time.monotonic()
                last_problem = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code in RETRYABLE_STATUS:
                    last_problem = f"HTTP {response.status_code}"
                    retry_after = response.headers.get("Retry-After")
                elif response.status_code != 200:
                    # 400 and 404 are answers, not accidents: retrying repeats the same answer.
                    raise AihwApiError(f"GET {url} params={params} failed: HTTP {response.status_code}: "
                                       f"{response.text[:300]}")
                else:
                    try:
                        body = response.json()
                    except ValueError:
                        body = None
                    if isinstance(body, dict) and "result" in body:
                        return body
                    last_problem = "HTTP 200 but the body is not the documented JSON shape"
            if attempt == self.max_attempts:
                break
            delay = self._delay_for(attempt, retry_after)
            self.retries_made += 1
            log.warning("AIHW API attempt %d/%d failed (%s); retrying in %.1fs: %s",
                        attempt, self.max_attempts, last_problem, delay, url)
            self._sleep(delay)
        raise AihwApiError(f"GET {url} params={params} gave up after {self.max_attempts} attempts: {last_problem}")

    # ---- endpoints -------------------------------------------------------------------------

    @staticmethod
    def _release_from(body: dict[str, Any]) -> ApiRelease:
        info = body.get("version_information") or {}
        if "data_version" not in info:
            raise AihwApiError("response has no version_information.data_version")
        return ApiRelease(int(info["data_version"]), str(info.get("date_uploaded", "")),
                          str(info.get("api_version", "")))

    def release(self) -> ApiRelease:
        """The current data release. Uses the smallest endpoint, so it is cheap to call every run."""
        return self._release_from(self.get("measure-categories"))

    def reporting_units(self) -> tuple[list[dict[str, Any]], ApiRelease]:
        body = self.get("reporting-units")
        return body["result"], self._release_from(body)

    def suppressions(self) -> list[dict[str, Any]]:
        return self.get("suppressions")["result"]

    def caveats(self) -> list[dict[str, Any]]:
        return self.get("caveats")["result"]

    def flat_extract(self, category: str, reporting_unit_code: str | None = None,
                     page_size: int = MAX_PAGE_SIZE) -> Extract:
        """Every row of a measure category, optionally for one reporting unit, as an exact extract.

        Pages until the API's own total is reached and then verifies the count. A release that
        changes between pages, a short read, or more rows than the API promised all raise,
        because the result would not be a consistent snapshot.
        """
        if not 1 <= page_size <= MAX_PAGE_SIZE:
            raise ValueError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")
        rows: list[dict[str, Any]] = []
        release: ApiRelease | None = None
        total: int | None = None
        pages = 0
        while True:
            params: dict[str, Any] = {"skip": len(rows), "top": page_size}
            if reporting_unit_code:
                params["reporting_unit_code"] = reporting_unit_code
            body = self.get(f"flat-data-extract/{category}", params)
            page_release = self._release_from(body)
            if release is not None and page_release.data_version != release.data_version:
                raise AihwApiError(f"{category}/{reporting_unit_code}: data release changed from "
                                   f"{release.data_version} to {page_release.data_version} while paging")
            release = page_release
            result = body["result"]
            page_rows = result.get("data", [])
            reported_total = int(result["pagination"]["total_results_available"])
            if total is not None and reported_total != total:
                raise AihwApiError(f"{category}/{reporting_unit_code}: reported total changed from "
                                   f"{total} to {reported_total} while paging")
            total = reported_total
            pages += 1
            rows.extend(page_rows)
            if not page_rows or len(rows) >= total:
                break
        if len(rows) != total:
            raise AihwApiError(f"{category}/{reporting_unit_code}: expected {total} rows, received {len(rows)}")
        assert release is not None
        return Extract(category, reporting_unit_code, rows, total, release, pages)
