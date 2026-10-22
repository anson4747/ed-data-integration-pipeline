/*
    rpt.pipeline_health: one row per pipeline, answering "is it healthy?" without reading the control tables.

    health_status, evaluated in this order:
      Running    the latest run has not finished
      Failing    the latest run failed
      Attention  the latest run finished with warnings, or any Warning or Critical alert is still unacknowledged
      Healthy    none of the above

    Alerts stay open until someone acknowledges them (etl.alert.acknowledged_at_utc), so a pipeline that
    recovered after a failure shows Attention, not Healthy, until the old Critical alert is acknowledged.
    Info alerts are ignored. Freshness is reported as minutes_since_last_success and is not judged here,
    because what counts as stale depends on how often each pipeline is scheduled.
*/
CREATE OR ALTER VIEW rpt.pipeline_health AS
WITH latest AS (
    SELECT run_id, pipeline_name, status, started_at_utc, ended_at_utc, error_message,
           ROW_NUMBER() OVER (PARTITION BY pipeline_name ORDER BY run_id DESC) AS rn
    FROM etl.pipeline_run
),
last_success AS (
    SELECT pipeline_name, MAX(ended_at_utc) AS last_success_utc
    FROM etl.pipeline_run
    WHERE status IN ('Succeeded', 'SucceededWithWarnings')
    GROUP BY pipeline_name
),
open_alert AS (
    SELECT r.pipeline_name,
           SUM(CASE WHEN a.severity = 'Critical' THEN 1 ELSE 0 END) AS open_critical,
           SUM(CASE WHEN a.severity = 'Warning'  THEN 1 ELSE 0 END) AS open_warning
    FROM etl.alert AS a
    JOIN etl.pipeline_run AS r ON r.run_id = a.run_id
    WHERE a.acknowledged_at_utc IS NULL
    GROUP BY r.pipeline_name
)
SELECT
    l.pipeline_name,
    CASE
        WHEN l.status = 'Running' THEN 'Running'
        WHEN l.status = 'Failed' THEN 'Failing'
        WHEN l.status = 'SucceededWithWarnings'
             OR COALESCE(o.open_critical, 0) + COALESCE(o.open_warning, 0) > 0 THEN 'Attention'
        ELSE 'Healthy'
    END                                                              AS health_status,
    l.run_id                                                         AS last_run_id,
    l.status                                                         AS last_run_status,
    l.started_at_utc                                                 AS last_run_started_utc,
    DATEDIFF(SECOND, l.started_at_utc, l.ended_at_utc)               AS last_run_seconds,
    s.last_success_utc,
    DATEDIFF(MINUTE, s.last_success_utc, SYSUTCDATETIME())           AS minutes_since_last_success,
    (SELECT COUNT(*) FROM etl.step_run AS x
      WHERE x.run_id = l.run_id AND x.status = 'Failed')             AS failed_steps_in_last_run,
    COALESCE(o.open_critical, 0)                                     AS open_critical_alerts,
    COALESCE(o.open_warning, 0)                                      AS open_warning_alerts,
    CASE WHEN l.status = 'Failed' THEN LEFT(l.error_message, 300) END AS last_error
FROM latest AS l
LEFT JOIN last_success AS s ON s.pipeline_name = l.pipeline_name
LEFT JOIN open_alert  AS o ON o.pipeline_name = l.pipeline_name
WHERE l.rn = 1;
GO
