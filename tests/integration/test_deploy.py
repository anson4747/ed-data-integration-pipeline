import pytest

from edpipe.migrate import DB_DIR, discover

pytestmark = pytest.mark.integration


def _scalar(conn, sql, *params):
    return conn.execute(sql, *params).fetchone()[0]


@pytest.mark.parametrize("target,fixture", [("source_emr", "source"), ("warehouse", "warehouse")])
def test_every_migration_is_recorded_with_matching_checksum(target, fixture, request):
    conn = request.getfixturevalue(fixture)
    rows = dict(conn.execute("SELECT version, checksum_sha256 FROM meta.schema_version").fetchall())
    for migration in discover(DB_DIR / target / "migrations"):
        assert rows.get(migration.version) == migration.checksum


def test_change_tracking_is_enabled_on_source(source):
    assert _scalar(source, "SELECT COUNT(*) FROM sys.change_tracking_databases WHERE database_id = DB_ID()") == 1


def test_source_allows_snapshot_isolation(source):
    assert _scalar(source, "SELECT snapshot_isolation_state FROM sys.databases WHERE database_id = DB_ID()") == 1


@pytest.mark.parametrize("schema", ["stg", "dq", "dw", "rpt", "ref", "etl", "meta"])
def test_warehouse_layers_exist(warehouse, schema):
    assert _scalar(warehouse, "SELECT COUNT(*) FROM sys.schemas WHERE name = ?", schema) == 1


@pytest.mark.parametrize("table", ["pipeline_run", "step_run", "watermark", "alert"])
def test_control_tables_exist(warehouse, table):
    assert _scalar(warehouse, "SELECT COUNT(*) FROM sys.tables WHERE schema_id = SCHEMA_ID('etl') AND name = ?",
                   table) == 1
