# Runbook

For whoever is looking at the pipeline when something is wrong. The first five minutes: find out what failed,
decide whether it is safe to re-run, and know what each alert means.

## Run it

```powershell
.\scripts\run-pipeline.ps1 -Environment prod
```

Order: replicate EMR changes, ingest AIHW, build dimension and facts, run data quality rules, print the health
report. It stops at the first failing step and exits with code 1. A copy of the output is in `logs\run-<time>.log`.

| Option | Use when |
|---|---|
| `-ForceAihw` | Reload AIHW even though the published release is unchanged |
| `-SkipAihw` | The API is unreachable but the rest must still run |
| `-AihwFixture <file>` | Offline run against a recorded API sample |

SQL Server Express has no SQL Agent. To schedule, use Windows Task Scheduler with this action:

```
powershell.exe -NoProfile -ExecutionPolicy Bypass -File <repo>\scripts\run-pipeline.ps1 -Environment prod
```

Task Scheduler marks a run failed when the script exits non-zero.

**Re-running is safe.** Each step is idempotent: replication resumes from its watermark, AIHW does nothing when the
release is unchanged, the dimension adds only new versions, the facts are rebuilt in one transaction, and quality rules resolve or reopen
exceptions rather than duplicating them. Re-run the whole script after a fix.

## Step 1: is it healthy?

```powershell
python -m edpipe.health --env prod
```

or, in SQL:

```sql
SELECT * FROM rpt.pipeline_health ORDER BY health_status;
```

| health_status | Meaning | Action |
|---|---|---|
| Healthy | Latest run succeeded, no open Warning or Critical alerts | None |
| Running | The latest run has not finished | Wait. If it has been running for hours, see "Run stuck in Running" below |
| Attention | Latest run had warnings, or an alert is unacknowledged | Read the open alerts (below), act, then acknowledge them |
| Failing | The latest run failed | Read `last_error`, see the table below |

A pipeline that recovered after a failure shows Attention, not Healthy, until its old Critical alert is
acknowledged. That is deliberate: someone should read why it failed.

`minutes_since_last_success` shows how stale the data is. The view does not judge it, because acceptable staleness
depends on the schedule.

## Step 2: read the failure

```sql
-- What failed, in which step
SELECT r.run_id, r.pipeline_name, r.status, r.error_message, s.step_name, s.status AS step_status, s.detail
FROM etl.pipeline_run r
LEFT JOIN etl.step_run s ON s.run_id = r.run_id AND s.status = 'Failed'
WHERE r.run_id = (SELECT MAX(run_id) FROM etl.pipeline_run WHERE status = 'Failed');

-- Open alerts
SELECT alert_id, severity, alert_type, message, raised_at_utc
FROM etl.alert WHERE acknowledged_at_utc IS NULL ORDER BY alert_id DESC;
```

## What each alert means

| Alert type | Severity | Meaning | What to do |
|---|---|---|---|
| `PipelineFailed` | Critical | A step raised an error. The message holds the error text | Fix the cause (see the next table), re-run |
| `ReplicationFullReload` | Warning | The warehouse fell behind Change Tracking retention, so a table was reloaded in full | Data is correct. Find out why replication was not running often enough |
| `ReorganisationUnmatched` | Warning | A row in `ref.lhn_reorganisation` matches no hospital | Check the code against the AIHW reporting unit codes. A typo means the merger is not applied |
| `DqErrorsFound` | Warning | New or reopened Error findings. Affected stays are quarantined, not published | `SELECT * FROM rpt.dq_quarantine`. Correct the source record, replicate, re-run. The next run resolves the exception |
| `AvailableButEmpty` | Warning | AIHW lists reporting units that returned no ED data | Compare the count with the previous release. Many missing units suggests an API problem |
| `ApiRetries` | Info | Some API requests needed a retry | Ignore unless it appears on every run |

## Common failures

| Symptom | Likely cause | Action |
|---|---|---|
| AIHW step fails with HTTP 403 | The gateway rejects default client identities | The client sets its own User-Agent. If it still returns 403, run the `probe-aihw` workflow to see what changed |
| AIHW step fails: duplicate keys in an extract | The source returned duplicate rows. Duplicates fail the run on purpose | Do not remove them silently. Check `docs/aihw-api-notes.md`, re-run with `-ForceAihw` once resolved |
| AIHW step shows Skipped | The published `data_version` has not changed | Normal. No action |
| Whole AIHW category empty | API fault or outage | The run fails rather than accept it. Retry later |
| Deploy fails with checksum drift | An applied migration file was edited | Revert the edit and ship the change as a new numbered migration. Never edit an applied one |
| Replicate fails to connect | Source database down, or credentials changed | Check `config\<env>.env` and that both databases are online |
| Source and replica row counts differ | Replication has not caught up | `python -m edpipe.health` shows the counts side by side. Re-run replicate |

## Run stuck in Running

A run records `Running` when it starts and its final status when it ends. If the process is killed (reboot, closed
window), the final update never happens and the run stays `Running`.

1. Confirm nothing is executing: check the host and Task Scheduler.
2. Mark the run as failed so health reflects reality:

```sql
UPDATE etl.pipeline_run
SET status = 'Failed', ended_at_utc = SYSUTCDATETIME(), error_message = N'Process killed; marked failed by operator'
WHERE run_id = <run_id> AND status = 'Running';
```

3. Re-run the pipeline.

There is no automatic timeout today. That is a known gap.

## Acknowledge an alert

After reading and acting on an alert:

```sql
UPDATE etl.alert
SET acknowledged_at_utc = SYSUTCDATETIME(), acknowledged_by = SUSER_SNAME()
WHERE alert_id = <alert_id>;
```

Acknowledged alerts stay in the table for audit. They are never deleted.
