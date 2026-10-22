"""Runtime settings, read from environment variables or a config/<env>.env file.

Nothing secret is ever committed: config/*.env files other than ci.env are git-ignored,
and on a workstation the default is Windows authentication (no password at all).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"


def _load_env_file(environment: str) -> None:
    """Load KEY=VALUE pairs from config/<environment>.env without overriding real env vars."""
    path = CONFIG_DIR / f"{environment}.env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class Settings:
    environment: str
    server: str
    driver: str
    trusted_connection: bool
    user: str | None
    password: str | None
    trust_server_certificate: bool
    source_db: str
    warehouse_db: str

    @classmethod
    def load(cls, environment: str | None = None) -> Settings:
        env = environment or os.environ.get("EDP_ENV", "dev")
        _load_env_file(env)
        trusted = _as_bool(os.environ.get("EDP_SQL_TRUSTED"), default=True)
        return cls(
            environment=env,
            server=os.environ.get("EDP_SQL_SERVER", "localhost"),
            driver=os.environ.get("EDP_SQL_DRIVER", "ODBC Driver 18 for SQL Server"),
            trusted_connection=trusted,
            user=None if trusted else os.environ.get("EDP_SQL_USER"),
            password=None if trusted else os.environ.get("EDP_SQL_PASSWORD"),
            trust_server_certificate=_as_bool(
                os.environ.get("EDP_SQL_TRUST_CERT"), default=True
            ),
            source_db=os.environ.get("EDP_SOURCE_DB", "SourceEMR"),
            warehouse_db=os.environ.get("EDP_WAREHOUSE_DB", "EDW"),
        )

    def connection_string(self, database: str = "master") -> str:
        parts = [
            f"DRIVER={{{self.driver}}}",
            f"SERVER={self.server}",
            f"DATABASE={database}",
            "Encrypt=yes",
            f"TrustServerCertificate={'yes' if self.trust_server_certificate else 'no'}",
            "APP=ed-data-integration-pipeline",
        ]
        if self.trusted_connection:
            parts.append("Trusted_Connection=yes")
        else:
            if not self.user or not self.password:
                raise ValueError("EDP_SQL_USER and EDP_SQL_PASSWORD are required when EDP_SQL_TRUSTED=false")
            parts.append(f"UID={self.user}")
            parts.append(f"PWD={self.password}")
        return ";".join(parts) + ";"

    @property
    def tokens(self) -> dict[str, str]:
        """Values substituted into SQL scripts, in the style of sqlcmd variables: $(SourceDb)."""
        return {"SourceDb": self.source_db, "WarehouseDb": self.warehouse_db}
