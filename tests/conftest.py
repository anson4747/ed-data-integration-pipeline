import os

import pytest


@pytest.fixture(scope="session")
def settings():
    if not os.environ.get("EDP_ENV"):
        pytest.skip("integration tests need EDP_ENV and a reachable SQL Server")
    from edpipe.config import Settings

    return Settings.load()


@pytest.fixture()
def warehouse(settings):
    from edpipe.db import connect

    with connect(settings, settings.warehouse_db, autocommit=True) as conn:
        yield conn


@pytest.fixture()
def source(settings):
    from edpipe.db import connect

    with connect(settings, settings.source_db, autocommit=True) as conn:
        yield conn
