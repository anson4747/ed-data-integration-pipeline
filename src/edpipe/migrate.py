"""Versioned schema migrations (a small Flyway-style runner).

Rules:
* Scripts live in db/<target>/migrations and are named V<version>__<description>.sql.
* Each script runs once, inside one transaction, and is recorded in meta.schema_version
  with a SHA-256 checksum.
* If a script that has already been applied is edited later, the runner refuses to continue
  (drift). Fixes go in a new script, never in an old one. This is what makes a deployment to
  test or prod reproducible.

Usage:
    python -m edpipe.migrate --bootstrap            # create databases (idempotent)
    python -m edpipe.migrate --target all           # apply pending migrations
    python -m edpipe.migrate --target warehouse --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from edpipe.config import REPO_ROOT, Settings

DB_DIR = REPO_ROOT / "db"
FILENAME_PATTERN = re.compile(r"^V(?P<version>\d{3,})__(?P<description>[A-Za-z0-9_]+)\.sql$")
GO_PATTERN = re.compile(r"^\s*GO\s*(?:--.*)?$", re.IGNORECASE | re.MULTILINE)
TOKEN_PATTERN = re.compile(r"\$\((?P<name>[A-Za-z_][A-Za-z0-9_]*)\)")

TARGETS = {"source_emr": "source_db", "warehouse": "warehouse_db"}

VERSION_TABLE_DDL = """
IF SCHEMA_ID(N'meta') IS NULL EXEC (N'CREATE SCHEMA meta AUTHORIZATION dbo;');
IF OBJECT_ID(N'meta.schema_version', N'U') IS NULL
BEGIN
    CREATE TABLE meta.schema_version (
        version         int            NOT NULL CONSTRAINT PK_schema_version PRIMARY KEY,
        description     nvarchar(200)  NOT NULL,
        script_name     nvarchar(260)  NOT NULL,
        checksum_sha256 char(64)       NOT NULL,
        environment     varchar(20)    NOT NULL,
        applied_by      sysname        NOT NULL CONSTRAINT DF_schema_version_applied_by DEFAULT SUSER_SNAME(),
        applied_at_utc  datetime2(3)   NOT NULL CONSTRAINT DF_schema_version_applied_at DEFAULT SYSUTCDATETIME(),
        execution_ms    int            NOT NULL
    );
END;
"""


class MigrationError(RuntimeError):
    """A migration script failed to apply."""


class MigrationDriftError(MigrationError):
    """An applied migration no longer matches the script on disk, or is missing from disk."""


@dataclass(frozen=True)
class Migration:
    version: int
    description: str
    path: Path
    checksum: str

    @property
    def script_name(self) -> str:
        return self.path.name


@dataclass(frozen=True)
class AppliedMigration:
    version: int
    script_name: str
    checksum: str


def checksum(text: str) -> str:
    # Normalise line endings so a Windows checkout (CRLF) and Linux CI (LF) agree.
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def discover(directory: Path) -> list[Migration]:
    migrations: list[Migration] = []
    seen: dict[int, Path] = {}
    for path in sorted(directory.glob("*.sql")):
        match = FILENAME_PATTERN.match(path.name)
        if not match:
            raise MigrationError(f"Badly named migration file: {path.name} (expected V001__description.sql)")
        version = int(match["version"])
        if version in seen:
            raise MigrationError(f"Duplicate migration version {version}: {seen[version].name} and {path.name}")
        seen[version] = path
        migrations.append(
            Migration(
                version=version,
                description=match["description"].replace("_", " "),
                path=path,
                checksum=checksum(path.read_text(encoding="utf-8")),
            )
        )
    return sorted(migrations, key=lambda m: m.version)


def check_drift(applied: list[AppliedMigration], discovered: list[Migration]) -> None:
    on_disk = {m.version: m for m in discovered}
    problems = []
    for row in applied:
        script = on_disk.get(row.version)
        if script is None:
            problems.append(f"V{row.version:03d} ({row.script_name}) is applied but missing from disk")
        elif script.checksum != row.checksum:
            problems.append(
                f"V{row.version:03d} ({row.script_name}) was edited after it was applied "
                f"(db {row.checksum[:12]}, disk {script.checksum[:12]}). Add a new migration instead."
            )
    if problems:
        raise MigrationDriftError("Schema drift detected:\n  " + "\n  ".join(problems))


def pending(applied: list[AppliedMigration], discovered: list[Migration]) -> list[Migration]:
    done = {row.version for row in applied}
    todo = [m for m in discovered if m.version not in done]
    if applied and todo and min(m.version for m in todo) < max(done):
        raise MigrationError(
            "A migration older than the latest applied one is pending "
            f"(V{min(m.version for m in todo):03d}). Renumber it after V{max(done):03d}."
        )
    return todo


def split_batches(sql: str) -> list[str]:
    """Split a script on GO separators, as SSMS and sqlcmd do."""
    return [batch.strip() for batch in GO_PATTERN.split(sql) if batch.strip()]


def render(sql: str, tokens: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match["name"]
        if name not in tokens:
            raise MigrationError(f"Unknown token $({name}) in SQL script")
        return tokens[name]

    return TOKEN_PATTERN.sub(replace, sql)


# Database side ---------------------------------------------------------------------------


def _applied(conn) -> list[AppliedMigration]:
    rows = conn.execute(
        "SELECT version, script_name, checksum_sha256 FROM meta.schema_version ORDER BY version"
    ).fetchall()
    return [AppliedMigration(int(r[0]), r[1], r[2]) for r in rows]


def bootstrap(settings: Settings) -> None:
    from edpipe.db import connect

    script = DB_DIR / "bootstrap" / "create_databases.sql"
    sql = render(script.read_text(encoding="utf-8"), settings.tokens)
    with connect(settings, "master", autocommit=True) as conn:
        for batch in split_batches(sql):
            conn.execute(batch)
    print(f"[bootstrap] databases ready: {settings.source_db}, {settings.warehouse_db}")


def migrate_target(settings: Settings, target: str, dry_run: bool = False) -> int:
    from edpipe.db import connect

    database = getattr(settings, TARGETS[target])
    migrations = discover(DB_DIR / target / "migrations")
    with connect(settings, database, autocommit=True) as conn:
        for batch in split_batches(VERSION_TABLE_DDL):
            conn.execute(batch)
        applied = _applied(conn)
        check_drift(applied, migrations)
        todo = pending(applied, migrations)
        if not todo:
            print(f"[{target}] up to date at V{max((a.version for a in applied), default=0):03d}")
            return 0
        if dry_run:
            for m in todo:
                print(f"[{target}] would apply {m.script_name}")
            return len(todo)

        conn.autocommit = False
        for m in todo:
            started = time.perf_counter()
            batches = split_batches(render(m.path.read_text(encoding="utf-8"), settings.tokens))
            cursor = conn.cursor()
            try:
                for index, batch in enumerate(batches, start=1):
                    try:
                        cursor.execute(batch)
                        while cursor.nextset():
                            pass
                    except Exception as exc:
                        raise MigrationError(f"{m.script_name}, batch {index}: {exc}") from exc
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                cursor.execute(
                    "INSERT INTO meta.schema_version "
                    "(version, description, script_name, checksum_sha256, environment, execution_ms) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    m.version, m.description, m.script_name, m.checksum, settings.environment, elapsed_ms,
                )
                conn.commit()
                print(f"[{target}] applied {m.script_name} in {elapsed_ms} ms")
            except Exception:
                conn.rollback()
                raise
        return len(todo)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply versioned SQL Server migrations.")
    parser.add_argument("--env", default=None, help="config environment (dev, ci, test, prod)")
    parser.add_argument("--bootstrap", action="store_true", help="create databases first")
    parser.add_argument("--target", choices=[*TARGETS, "all"], default="all")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    settings = Settings.load(args.env)
    try:
        if args.bootstrap:
            bootstrap(settings)
        targets = list(TARGETS) if args.target == "all" else [args.target]
        for target in targets:
            migrate_target(settings, target, dry_run=args.dry_run)
    except MigrationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
