from pathlib import Path

import pytest

from edpipe.migrate import (
    AppliedMigration,
    MigrationDriftError,
    MigrationError,
    check_drift,
    checksum,
    discover,
    pending,
    render,
    split_batches,
)

REPO = Path(__file__).resolve().parents[2]


def _write(directory: Path, name: str, body: str = "SELECT 1;") -> Path:
    path = directory / name
    path.write_text(body, encoding="utf-8")
    return path


def test_discover_orders_by_version(tmp_path):
    _write(tmp_path, "V010__later.sql")
    _write(tmp_path, "V002__earlier.sql")
    assert [m.version for m in discover(tmp_path)] == [2, 10]


def test_discover_rejects_bad_names(tmp_path):
    _write(tmp_path, "create_tables.sql")
    with pytest.raises(MigrationError, match="Badly named"):
        discover(tmp_path)


def test_discover_rejects_duplicate_versions(tmp_path):
    _write(tmp_path, "V001__a.sql")
    _write(tmp_path, "V0001__b.sql")
    with pytest.raises(MigrationError, match="Duplicate"):
        discover(tmp_path)


def test_checksum_ignores_line_endings():
    assert checksum("SELECT 1;\r\nGO\r\n") == checksum("SELECT 1;\nGO\n")


def test_edited_script_is_drift(tmp_path):
    script = discover(Path(_write(tmp_path, "V001__a.sql", "SELECT 2;").parent))[0]
    applied = [AppliedMigration(1, "V001__a.sql", checksum("SELECT 1;"))]
    with pytest.raises(MigrationDriftError, match="edited after it was applied"):
        check_drift(applied, [script])


def test_missing_script_is_drift():
    applied = [AppliedMigration(1, "V001__gone.sql", "0" * 64)]
    with pytest.raises(MigrationDriftError, match="missing from disk"):
        check_drift(applied, [])


def test_pending_rejects_out_of_order_script(tmp_path):
    _write(tmp_path, "V001__a.sql")
    _write(tmp_path, "V002__b.sql")
    _write(tmp_path, "V003__c.sql")
    migrations = discover(tmp_path)
    applied = [AppliedMigration(1, "V001__a.sql", migrations[0].checksum),
               AppliedMigration(3, "V003__c.sql", migrations[2].checksum)]
    with pytest.raises(MigrationError, match="older than the latest"):
        pending(applied, migrations)


def test_pending_returns_new_scripts_only(tmp_path):
    _write(tmp_path, "V001__a.sql")
    _write(tmp_path, "V002__b.sql")
    migrations = discover(tmp_path)
    applied = [AppliedMigration(1, "V001__a.sql", migrations[0].checksum)]
    assert [m.version for m in pending(applied, migrations)] == [2]


def test_split_batches_on_go_lines_only():
    sql = "SELECT 'GO';\nGO\nSELECT 2;\n  go  \nSELECT 3; -- GOAL\nGO -- end\n"
    assert split_batches(sql) == ["SELECT 'GO';", "SELECT 2;", "SELECT 3; -- GOAL"]


def test_render_substitutes_tokens_and_rejects_unknown():
    assert render("USE [$(WarehouseDb)];", {"WarehouseDb": "EDW"}) == "USE [EDW];"
    with pytest.raises(MigrationError, match="Unknown token"):
        render("$(Nope)", {})


@pytest.mark.parametrize("target", ["source_emr", "warehouse"])
def test_repository_migrations_are_well_formed(target):
    migrations = discover(REPO / "db" / target / "migrations")
    assert migrations, f"no migrations for {target}"
    assert [m.version for m in migrations] == list(range(1, len(migrations) + 1)), "gap in version numbers"
