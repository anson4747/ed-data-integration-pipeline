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
- Replication: Change Tracking based incremental copy from the mock EMR to the warehouse, with
  full reload and an alert when the warehouse falls behind the retention window (warehouse V002, V003).
- AIHW MyHospitals ingest: per reporting unit extraction reconciled to the API total, release
  marker (`data_version`) so unchanged releases are a no-op, raw JSON landing and an atomic
  apply procedure (warehouse V005, V006).
- Dimensional model: Type 2 `dw.dim_reporting_unit`, dated reorganisations including the Bayside
  Health merger of 1 January 2026, `dw.fact_ed_measure`, reporting views and a Bayside rollup
  (warehouse V007 to V009).
- V010: a reorganisation row that matches no hospital now raises a Warning alert instead of
  passing silently.
- Data quality framework: 18 rules stored as data (`dq.quality_rule`), exception lifecycle with
  reopen, quarantine view, `dw.fact_ed_stay` built from clean stays only, standardised pain and
  rhythm via reference maps, and a CI step that prints the quality report (warehouse V011 to V013).
- Design decisions and known limits in `docs/design-decisions.md`; API behaviour notes in
  `docs/aihw-api-notes.md`.
- Operations: `scripts/run-pipeline.ps1` runs every step in order, stops at the first failure and exits
  non-zero; `rpt.pipeline_health` (warehouse V014) gives one row per pipeline with a Healthy, Attention,
  Failing or Running status; `docs/runbook.md` covers alerts, common failures and acknowledging alerts.
  CI runs the runner end to end and checks that it fails fast.
