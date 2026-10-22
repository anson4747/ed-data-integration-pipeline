"""Typed bulk loading of CSV rows into SQL Server tables.

Values arrive as text. Each column is converted using the target column's SQL type, read
from the catalog, so a bad value fails loudly with the file, line and column named, instead
of being silently coerced. Empty strings become NULL.
"""

from __future__ import annotations

import csv
import gzip
from collections.abc import Callable, Iterable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path


class LoadError(ValueError):
    pass


def _to_int(v: str) -> int:
    # MIMIC writes some integer columns as "3.0"
    d = Decimal(v)
    if d != d.to_integral_value():
        raise ValueError(f"not a whole number: {v!r}")
    return int(d)


def _to_datetime(v: str) -> datetime:
    return datetime.fromisoformat(v)


def _to_date(v: str) -> date:
    return date.fromisoformat(v[:10])


def _to_decimal(v: str) -> Decimal:
    try:
        return Decimal(v)
    except InvalidOperation as exc:
        raise ValueError(f"not a number: {v!r}") from exc


CONVERTERS: dict[str, Callable[[str], object]] = {
    "int": _to_int, "bigint": _to_int, "smallint": _to_int, "tinyint": _to_int, "bit": _to_int,
    "decimal": _to_decimal, "numeric": _to_decimal, "float": float, "real": float,
    "datetime2": _to_datetime, "datetime": _to_datetime, "date": _to_date,
}


def column_types(conn, table: str) -> dict[str, tuple[str, int | None]]:
    """{column: (sql type name, max length for strings)} for an existing table."""
    rows = conn.execute(
        "SELECT c.name, t.name, CASE WHEN t.name IN ('varchar', 'char') THEN c.max_length "
        "WHEN t.name IN ('nvarchar', 'nchar') THEN c.max_length / 2 END "
        "FROM sys.columns AS c JOIN sys.types AS t ON t.user_type_id = c.user_type_id "
        "WHERE c.object_id = OBJECT_ID(?) AND c.is_identity = 0 ORDER BY c.column_id",
        table,
    ).fetchall()
    if not rows:
        raise LoadError(f"Table {table} does not exist or has no columns")
    return {r[0]: (r[1], r[2]) for r in rows}


def convert_rows(rows: Iterable[dict[str, str]], columns: list[str], types: dict[str, tuple[str, int | None]],
                 source: str) -> list[tuple]:
    out = []
    for line_no, row in enumerate(rows, start=2):
        values = []
        for column in columns:
            raw = row.get(column)
            if raw is None or raw == "":
                values.append(None)
                continue
            sql_type, max_len = types[column]
            try:
                if sql_type in CONVERTERS:
                    values.append(CONVERTERS[sql_type](raw))
                else:
                    if max_len not in (None, -1) and len(raw) > max_len:
                        raise ValueError(f"{len(raw)} characters exceeds {max_len}")
                    values.append(raw)
            except ValueError as exc:
                raise LoadError(f"{source} line {line_no}, column {column}: {exc}") from exc
        out.append(tuple(values))
    return out


def read_gz_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        return list(reader.fieldnames or []), rows


def bulk_insert(conn, table: str, columns: list[str], rows: list[tuple], batch_size: int = 5000) -> int:
    if not rows:
        return 0
    sql = f"INSERT INTO {table} ({', '.join('[' + c + ']' for c in columns)}) VALUES ({', '.join('?' * len(columns))})"
    cursor = conn.cursor()
    cursor.fast_executemany = True
    for start in range(0, len(rows), batch_size):
        cursor.executemany(sql, rows[start:start + batch_size])
    return len(rows)
