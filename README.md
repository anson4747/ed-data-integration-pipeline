# ED Data Integration Pipeline

Moves emergency department and hospital data from source systems into a SQL Server
warehouse: incremental replication with Change Tracking, REST API ingestion, Victorian ED
style validation, and REDCap exports. Work in progress; full documentation lands with each
stage.

![CI](https://github.com/anson4747/ed-data-integration-pipeline/actions/workflows/ci.yml/badge.svg)

## Quick start (Windows, SQL Server Express)

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item config\dev.env.example config\dev.env   # Windows authentication by default
.\scripts\deploy.ps1 -Environment dev
pytest -m "not integration"
```
