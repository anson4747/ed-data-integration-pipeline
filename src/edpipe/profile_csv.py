"""Quick column profile of gzipped CSV extracts: row count, nulls, distinct values, min and max.

Run before modelling a new source. It answers the analyst's first questions (how big, how
complete, what do the values look like) and the output goes into docs/data-profile.md.
"""

from __future__ import annotations

import argparse
import csv
import gzip
from collections import Counter
from pathlib import Path


def profile(path: Path, top: int = 5) -> dict:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = reader.fieldnames or []
        counts = {c: Counter() for c in columns}
        rows = 0
        for row in reader:
            rows += 1
            for column in columns:
                counts[column][row[column]] += 1
    summary = {"file": path.name, "rows": rows, "columns": []}
    for column in columns:
        values = counts[column]
        non_empty = [v for v in values if v != ""]
        summary["columns"].append(
            {
                "name": column,
                "nulls": values.get("", 0),
                "distinct": len(non_empty),
                "min": min(non_empty) if non_empty else None,
                "max": max(non_empty) if non_empty else None,
                "top": [v for v, _ in values.most_common(top) if v != ""][:top],
            }
        )
    return summary


def to_markdown(summary: dict) -> str:
    lines = [f"### {summary['file']} ({summary['rows']:,} rows)", "",
             "| column | nulls | distinct | min | max | most common |", "|---|---|---|---|---|---|"]
    for c in summary["columns"]:
        top = ", ".join(str(v)[:30] for v in c["top"][:3])
        lines.append(f"| {c['name']} | {c['nulls']} | {c['distinct']} | {str(c['min'])[:30]} | "
                     f"{str(c['max'])[:30]} | {top} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    text = "\n".join(to_markdown(profile(p)) for p in args.paths)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
