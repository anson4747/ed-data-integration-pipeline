"""Thin connection helpers around pyodbc."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager

from edpipe.config import Settings


def _pyodbc():
    # Imported lazily so unit tests run on machines without an ODBC driver.
    import pyodbc

    # ODBC connection pooling hands back physical connections with session state left over from
    # the previous user. A connection last used with autocommit off came back with implicit
    # transactions still on: later "autocommit" work ran inside an open transaction and was
    # rolled back when the connection closed. A batch pipeline opens few connections, so pooling
    # buys nothing here and is switched off.
    pyodbc.pooling = False
    return pyodbc


@contextmanager
def connect(settings: Settings, database: str = "master", autocommit: bool = False) -> Iterator:
    conn = _pyodbc().connect(settings.connection_string(database), autocommit=autocommit)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction(conn) -> Iterator:
    """Run a block as one transaction on an autocommit connection, then restore autocommit."""
    conn.autocommit = False
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.autocommit = True


def wait_for_server(settings: Settings, timeout_seconds: int = 120, interval_seconds: float = 3.0) -> None:
    """Block until SQL Server accepts connections. Used by CI while the container starts."""
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with connect(settings, "master", autocommit=True) as conn:
                conn.execute("SELECT 1").fetchone()
                return
        except Exception as exc:  # noqa: BLE001 - any failure means "not ready yet"
            last_error = exc
            time.sleep(interval_seconds)
    raise TimeoutError(f"SQL Server not reachable after {timeout_seconds}s: {last_error}")


if __name__ == "__main__":
    wait_for_server(Settings.load())
    print("SQL Server is accepting connections.")
