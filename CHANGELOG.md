# Changelog

All notable changes are recorded here. Database changes always ship as a new numbered
migration; an applied migration is never edited.

## [Unreleased]

### Added
- Repository foundation: versioned migration runner with checksum drift detection,
  idempotent database bootstrap, PowerShell deployment script, GitHub Actions CI that
  deploys to SQL Server 2022 and runs unit and integration tests.
- Warehouse V001: layered schemas (stg, dq, dw, rpt, ref, etl) and pipeline control
  tables (runs, steps, watermarks, alerts).
- Source V001: mock EMR schemas (hosp, ed, admin) with Change Tracking enabled at
  database level.
