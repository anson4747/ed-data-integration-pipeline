"""Download PhysioNet open-access datasets and verify them against the published checksums.

Raw files are never committed (ODbL attribution and share-alike terms apply to the data,
see DATA_LICENCES.md). They are fetched on demand into data/raw/ and reused while the
SHA-256 still matches PhysioNet's SHA256SUMS.txt, so a rerun downloads nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from edpipe.config import REPO_ROOT

RAW_DIR = REPO_ROOT / "data" / "raw"
USER_AGENT = "ed-data-integration-pipeline/0.1 (portfolio project; +https://github.com/anson4747/ed-data-integration-pipeline)"


@dataclass(frozen=True)
class Dataset:
    slug: str
    version: str
    files: tuple[str, ...]

    @property
    def base_url(self) -> str:
        return f"https://physionet.org/files/{self.slug}/{self.version}"

    @property
    def local_dir(self) -> Path:
        return RAW_DIR / self.slug / self.version


MIMIC_ED_DEMO = Dataset(
    slug="mimic-iv-ed-demo",
    version="2.2",
    files=("ed/edstays.csv.gz", "ed/triage.csv.gz", "ed/vitalsign.csv.gz", "ed/diagnosis.csv.gz"),
)

MIMIC_HOSP_DEMO = Dataset(
    slug="mimic-iv-demo",
    version="2.2",
    files=(
        "hosp/patients.csv.gz",
        "hosp/admissions.csv.gz",
        "hosp/transfers.csv.gz",
        "hosp/diagnoses_icd.csv.gz",
        "hosp/d_icd_diagnoses.csv.gz",
    ),
)

DATASETS = (MIMIC_ED_DEMO, MIMIC_HOSP_DEMO)


class ChecksumError(RuntimeError):
    pass


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_sums(text: str) -> dict[str, str]:
    """PhysioNet format: '<sha256> <relative path>' per line (one or two spaces)."""
    sums: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) == 2 and len(parts[0]) == 64:
            sums[parts[1].lstrip("*")] = parts[0].lower()
    return sums


def _get(session: requests.Session, url: str, attempts: int = 4) -> requests.Response:
    for attempt in range(1, attempts + 1):
        try:
            response = session.get(url, timeout=60)
            if response.status_code < 500:
                response.raise_for_status()
                return response
        except requests.RequestException:
            if attempt == attempts:
                raise
        time.sleep(2**attempt)
    raise RuntimeError(f"Giving up on {url} after {attempts} attempts")


def fetch(dataset: Dataset, session: requests.Session | None = None) -> list[Path]:
    session = session or requests.Session()
    session.headers.setdefault("User-Agent", USER_AGENT)
    sums = parse_sums(_get(session, f"{dataset.base_url}/SHA256SUMS.txt").text)
    paths = []
    for relative in dataset.files:
        expected = sums.get(relative)
        if expected is None:
            raise ChecksumError(f"{dataset.slug}: {relative} is not listed in SHA256SUMS.txt")
        target = dataset.local_dir / relative
        if target.exists() and sha256_of(target) == expected:
            print(f"[fetch] {dataset.slug}/{relative} cached, checksum ok")
            paths.append(target)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".part")
        tmp.write_bytes(_get(session, f"{dataset.base_url}/{relative}").content)
        actual = sha256_of(tmp)
        if actual != expected:
            tmp.unlink(missing_ok=True)
            raise ChecksumError(f"{dataset.slug}/{relative}: checksum {actual[:12]} != published {expected[:12]}")
        tmp.replace(target)
        print(f"[fetch] {dataset.slug}/{relative} downloaded, checksum ok ({target.stat().st_size:,} bytes)")
        paths.append(target)
    return paths


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description="Fetch and verify the MIMIC-IV demo datasets.").parse_args(argv)
    try:
        for dataset in DATASETS:
            fetch(dataset)
    except (ChecksumError, requests.RequestException) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
