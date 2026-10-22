"""Replay a recorded AIHW API sample, so the pipeline runs without the network.

Used by the integration tests (CI never depends on AIHW being up), and by anyone who wants to try
the pipeline offline. A sample is recorded from the live API with ``python -m edpipe.sources.aihw_record``.

Like the real API, a unit with no recorded rows answers with an empty extract rather than an error.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

from edpipe.sources.aihw import ApiRelease as Release
from edpipe.sources.aihw import Extract


class ReplayClient:
    retries_made = 0

    def __init__(self, sample: dict[str, Any]) -> None:
        self.sample = sample
        self._release = Release(**sample["release"])

    @classmethod
    def load(cls, path: str | Path) -> ReplayClient:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return cls(json.load(handle))

    def with_release(self, data_version: int) -> ReplayClient:
        """The same sample presented as a different release, to exercise 'new release' behaviour."""
        changed = json.loads(json.dumps(self.sample))
        changed["release"]["data_version"] = data_version
        return ReplayClient(changed)

    def release(self) -> Release:
        return self._release

    def reporting_units(self) -> tuple[list[dict[str, Any]], Release]:
        return self.sample["reporting_units"], self._release

    def suppressions(self) -> list[dict[str, Any]]:
        return self.sample["suppressions"]

    def caveats(self) -> list[dict[str, Any]]:
        return self.sample["caveats"]

    def flat_extract(self, category: str, reporting_unit_code: str | None = None, page_size: int = 1000) -> Extract:
        recorded = self.sample["extracts"].get(category, {}).get(reporting_unit_code or "", {"rows": []})
        rows = recorded["rows"]
        pages = max(1, -(-len(rows) // page_size))
        return Extract(category, reporting_unit_code, rows, len(rows), self._release, pages)
