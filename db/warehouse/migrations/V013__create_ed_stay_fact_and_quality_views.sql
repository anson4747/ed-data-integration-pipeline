/*
    dw.fact_ed_stay: one row per ED stay that passed every Error rule, built from the replicated EMR.
    Stays held in quarantine are not in this table; they are listed, with reasons, in rpt.dq_quarantine.
    Warnings do not block a stay: open_warning_count says how many remain open against it.

    Dates in the MIMIC demo are shifted into the 2100s to de-identify them, and acuity is the US ESI scale.
*/
CREATE TABLE dw.fact_ed_stay (
    stay_id            int          NOT NULL CONSTRAINT PK_fact_ed_stay PRIMARY KEY,
    subject_id         int          NOT NULL,
    hadm_id            int          NULL,
    arrival_dt         datetime2(0) NOT NULL,
    departure_dt       datetime2(0) NULL,
    is_open            bit          NOT NULL,
    length_of_stay_min int          NULL,
    within_four_hours  bit          NULL,
    esi_level          tinyint      NULL,
    arrival_transport  varchar(50)  NULL,
    disposition        varchar(50)  NULL,
    was_admitted       bit          NOT NULL,
    open_warning_count int          NOT NULL,
    _loaded_run_id     bigint       NOT NULL,
    _loaded_at_utc     datetime2(3) NOT NULL CONSTRAINT DF_fact_ed_stay_loaded DEFAULT SYSUTCDATETIME()
);
GO

/* Rebuilds the stay fact from the replica, leaving out quarantined stays. One transaction. */
CREATE OR ALTER PROCEDURE etl.usp_load_ed_stay
    @run_id bigint
AS
BEGIN
    SET NOCOUNT, XACT_ABORT ON;
    DECLARE @total int = (SELECT COUNT(*) FROM ods.emr_ed_edstays), @loaded int;

    BEGIN TRANSACTION;
    DELETE FROM dw.fact_ed_stay;
    INSERT INTO dw.fact_ed_stay (stay_id, subject_id, hadm_id, arrival_dt, departure_dt, is_open, length_of_stay_min,
        within_four_hours, esi_level, arrival_transport, disposition, was_admitted, open_warning_count, _loaded_run_id)
    SELECT e.stay_id, e.subject_id, e.hadm_id, e.intime, e.outtime,
           CASE WHEN e.outtime IS NULL THEN 1 ELSE 0 END,
           DATEDIFF(MINUTE, e.intime, e.outtime),
           CASE WHEN e.outtime IS NULL THEN NULL WHEN DATEDIFF(MINUTE, e.intime, e.outtime) <= 240 THEN 1 ELSE 0 END,
           CASE WHEN t.acuity IN (1, 2, 3, 4, 5) THEN CAST(t.acuity AS tinyint) END,
           e.arrival_transport, e.disposition,
           CASE WHEN e.disposition = 'ADMITTED' THEN 1 ELSE 0 END,
           (SELECT COUNT(*) FROM dq.exception AS x JOIN dq.quality_rule AS r ON r.rule_code = x.rule_code
            WHERE x.stay_id = e.stay_id AND x.status = 'Open' AND r.severity = 'Warning'),
           @run_id
    FROM ods.emr_ed_edstays AS e
    LEFT JOIN ods.emr_ed_triage AS t ON t.stay_id = e.stay_id
    WHERE NOT EXISTS (SELECT 1 FROM dq.v_quarantined_stay AS q WHERE q.stay_id = e.stay_id);
    SET @loaded = @@ROWCOUNT;
    COMMIT TRANSACTION;

    SELECT @loaded AS loaded, @total - @loaded AS quarantined;
END;
GO

CREATE OR ALTER VIEW rpt.dq_rule_summary AS
SELECT r.rule_code, r.severity, r.target_table, r.description, r.reference, r.is_active,
       COUNT(CASE WHEN x.status = 'Open' THEN 1 END) AS open_exceptions,
       COUNT(CASE WHEN x.status = 'Resolved' THEN 1 END) AS resolved_exceptions
FROM dq.quality_rule AS r LEFT JOIN dq.exception AS x ON x.rule_code = r.rule_code
GROUP BY r.rule_code, r.severity, r.target_table, r.description, r.reference, r.is_active;
GO

CREATE OR ALTER VIEW rpt.dq_open_exception AS
SELECT x.exception_id, x.rule_code, r.severity, r.target_table, x.entity_key, x.stay_id, x.detail,
       x.first_seen_utc, x.first_seen_run_id, x.last_seen_run_id
FROM dq.exception AS x JOIN dq.quality_rule AS r ON r.rule_code = x.rule_code
WHERE x.status = 'Open';
GO

CREATE OR ALTER VIEW rpt.dq_quarantine AS
SELECT q.stay_id, q.reasons, q.open_errors, e.subject_id, e.intime AS arrival_dt, e.outtime AS departure_dt
FROM dq.v_quarantined_stay AS q LEFT JOIN ods.emr_ed_edstays AS e ON e.stay_id = q.stay_id;
GO

CREATE OR ALTER VIEW rpt.ed_stay AS
SELECT stay_id, subject_id, hadm_id, arrival_dt, departure_dt, is_open, length_of_stay_min, within_four_hours,
       esi_level, arrival_transport, disposition, was_admitted, open_warning_count
FROM dw.fact_ed_stay;
GO

/* Monthly view of the clean stays. Open stays are counted as stays but not in the four hour measure. */
CREATE OR ALTER VIEW rpt.ed_stay_monthly AS
SELECT DATEFROMPARTS(YEAR(arrival_dt), MONTH(arrival_dt), 1) AS arrival_month,
       COUNT(*) AS stays,
       COUNT(CASE WHEN is_open = 0 THEN 1 END) AS completed_stays,
       CAST(100.0 * SUM(CASE WHEN within_four_hours = 1 THEN 1 ELSE 0 END)
            / NULLIF(COUNT(CASE WHEN is_open = 0 THEN 1 END), 0) AS decimal(5, 1)) AS four_hour_percent,
       AVG(length_of_stay_min) AS average_length_of_stay_min,
       CAST(100.0 * SUM(CAST(was_admitted AS int)) / COUNT(*) AS decimal(5, 1)) AS admitted_percent
FROM dw.fact_ed_stay
GROUP BY DATEFROMPARTS(YEAR(arrival_dt), MONTH(arrival_dt), 1);
GO

/* Vital signs with pain and rhythm in the agreed standard form, for clean stays only. */
CREATE OR ALTER VIEW rpt.ed_vitalsign AS
SELECT v.vitalsign_id, v.stay_id, v.charttime, v.temperature AS temperature_f, v.heartrate, v.resprate, v.o2sat,
       v.sbp, v.dbp, v.rhythm AS rhythm_raw, rm.standard_value AS rhythm,
       CASE WHEN pm.treatment IS NOT NULL THEN NULL
            WHEN TRY_CAST(v.pain AS decimal(5, 2)) BETWEEN 0 AND 10 THEN CAST(TRY_CAST(v.pain AS decimal(5, 2)) AS tinyint)
       END AS pain_score,
       CASE WHEN v.pain IS NULL THEN NULL
            WHEN pm.treatment IS NOT NULL THEN pm.treatment
            WHEN TRY_CAST(v.pain AS decimal(5, 2)) BETWEEN 0 AND 10 THEN 'Score'
            ELSE 'Unmapped' END AS pain_status
FROM ods.emr_ed_vitalsign AS v
JOIN dw.fact_ed_stay AS s ON s.stay_id = v.stay_id
LEFT JOIN ref.rhythm_map AS rm ON rm.raw_value = v.rhythm
LEFT JOIN ref.pain_value_map AS pm ON pm.raw_value = v.pain;
GO
