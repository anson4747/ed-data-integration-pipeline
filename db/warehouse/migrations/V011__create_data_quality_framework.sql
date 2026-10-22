/*
    Data quality framework.

    dq.quality_rule        the catalogue. Each rule is a SELECT that returns the rows that BREAK it as
                   (stay_id, entity_key, detail). Rules are data, added by migration, so the history of what
                   was checked and when is in version control.
    dq.exception   one row per (rule, entity) with a lifecycle: Open when first found, Resolved when a later
                   run no longer finds it, Open again if it comes back. Reruns never duplicate.
    Quarantine     is not a table: a stay is quarantined while it has an Open exception from an Error rule
                   (view dq.v_quarantined_stay, next migration). Nothing to keep in sync, nothing to forget.

    Error rules protect reporting: the stay is held back from dw.fact_ed_stay.
    Warning rules flag but do not block: the stay loads with open_warning_count above zero.

    Reference maps (ref.pain_value_map, ref.rhythm_map) hold the agreed standard values, so the same
    knowledge drives both the rules and the standardised reporting view.

    Every rule_code, check_sql and reference text below comes from this repository, never from user input:
    the runner executes check_sql with sp_executesql.
*/

CREATE TABLE dq.quality_rule (
    rule_code    varchar(40)    NOT NULL CONSTRAINT PK_dq_rule PRIMARY KEY,
    severity     varchar(10)    NOT NULL,
    target_table varchar(60)    NOT NULL,
    description  nvarchar(500)  NOT NULL,
    reference    nvarchar(300)  NOT NULL,
    check_sql    nvarchar(max)  NOT NULL,
    is_active    bit            NOT NULL CONSTRAINT DF_dq_rule_active DEFAULT 1,
    CONSTRAINT CK_dq_rule_severity CHECK (severity IN ('Error', 'Warning'))
);
GO

CREATE TABLE dq.exception (
    exception_id      bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_dq_exception PRIMARY KEY,
    rule_code         varchar(40)   NOT NULL CONSTRAINT FK_dq_exception_rule REFERENCES dq.quality_rule (rule_code),
    entity_key        nvarchar(100) NOT NULL,
    stay_id           int           NULL,
    detail            nvarchar(500) NULL,
    status            varchar(10)   NOT NULL,
    first_seen_run_id bigint        NOT NULL,
    first_seen_utc    datetime2(3)  NOT NULL CONSTRAINT DF_dq_exception_first DEFAULT SYSUTCDATETIME(),
    last_seen_run_id  bigint        NOT NULL,
    resolved_run_id   bigint        NULL,
    resolved_utc      datetime2(3)  NULL,
    CONSTRAINT UQ_dq_exception_entity UNIQUE (rule_code, entity_key),
    CONSTRAINT CK_dq_exception_status CHECK (status IN ('Open', 'Resolved'))
);
GO

CREATE INDEX IX_dq_exception_stay ON dq.exception (stay_id) WHERE stay_id IS NOT NULL;
GO

/* Agreed treatment of free text pain values. Numbers 0 to 10 need no entry. */
CREATE TABLE ref.pain_value_map (
    raw_value  varchar(50) NOT NULL CONSTRAINT PK_pain_value_map PRIMARY KEY,
    treatment  varchar(20) NOT NULL,
    CONSTRAINT CK_pain_value_map_treatment CHECK (treatment IN ('UnableToAssess', 'Asleep', 'SedatedOrIntubated', 'Denies'))
);
GO
/* Seeded from the values the demo data really contains. Genuinely ambiguous strings (for example 'u') and one-off
   observations ('sitting', 'NAD') are left out on purpose, so PAIN_UNPARSEABLE keeps flagging them for a person. */
INSERT INTO ref.pain_value_map (raw_value, treatment) VALUES
 ('uta', 'UnableToAssess'), ('ua', 'UnableToAssess'), ('unable', 'UnableToAssess'),
 ('asleep', 'Asleep'), ('sleeping', 'Asleep'), ('sleep', 'Asleep'), ('sleepin', 'Asleep'),
 ('sedated', 'SedatedOrIntubated'), ('intubated', 'SedatedOrIntubated'), ('ett', 'SedatedOrIntubated'),
 ('denies', 'Denies');
GO

/* Agreed standard names for heart rhythm. Variants map to one standard value. */
CREATE TABLE ref.rhythm_map (
    raw_value       varchar(100) NOT NULL CONSTRAINT PK_rhythm_map PRIMARY KEY,
    standard_value  varchar(100) NOT NULL
);
GO
INSERT INTO ref.rhythm_map (raw_value, standard_value) VALUES
 ('Sinus Rhythm', 'Sinus Rhythm'), ('sr', 'Sinus Rhythm'),
 ('Sinus Tachycardia', 'Sinus Tachycardia'), ('Sinus Bradycardia', 'Sinus Bradycardia'),
 ('Atrial Fibrillation', 'Atrial Fibrillation'), ('afib', 'Atrial Fibrillation'),
 ('Atrial Flutter', 'Atrial Flutter'), ('Normal Sinus Rhythm', 'Sinus Rhythm'), ('Paced Rhythm', 'Paced Rhythm');
GO

INSERT INTO dq.quality_rule (rule_code, severity, target_table, description, reference, check_sql)
VALUES ('E025_DUPLICATE_PRESENTATION', 'Error', N'ed.edstays',
 N'Two ED presentations for the same patient at the same arrival time.',
 N'Modelled on VEMD 2026-27 validation E025 (duplicate record)',
 N'SELECT e.stay_id, CAST(e.stay_id AS nvarchar(100)), CONCAT(N''Same patient and arrival time as stay '', f.stay_id)
FROM ods.emr_ed_edstays AS e
JOIN ods.emr_ed_edstays AS f ON f.subject_id = e.subject_id AND f.intime = e.intime AND f.stay_id < e.stay_id');
GO

INSERT INTO dq.quality_rule (rule_code, severity, target_table, description, reference, check_sql)
VALUES ('E340_DEPARTURE_NOT_AFTER_ARRIVAL', 'Error', N'ed.edstays',
 N'Departure time is not after arrival time.',
 N'Modelled on VEMD 2026-27 validation E340 (departure not after arrival)',
 N'SELECT stay_id, CAST(stay_id AS nvarchar(100)), N''Departure is not after arrival''
FROM ods.emr_ed_edstays WHERE outtime IS NOT NULL AND outtime <= intime');
GO

INSERT INTO dq.quality_rule (rule_code, severity, target_table, description, reference, check_sql)
VALUES ('E167_VITALS_BEFORE_ARRIVAL', 'Error', N'ed.vitalsign',
 N'Vital signs charted before the patient arrived.',
 N'Modelled on VEMD 2026-27 validation E167 (triage before arrival), applied to charting times',
 N'SELECT e.stay_id, CAST(e.stay_id AS nvarchar(100)), CONCAT(COUNT(*), N'' vital sign reading(s) charted before arrival'')
FROM ods.emr_ed_edstays AS e
JOIN ods.emr_ed_vitalsign AS v ON v.stay_id = e.stay_id AND v.charttime < e.intime
GROUP BY e.stay_id');
GO

INSERT INTO dq.quality_rule (rule_code, severity, target_table, description, reference, check_sql)
VALUES ('E219_LENGTH_OF_STAY_OVER_7_DAYS', 'Error', N'ed.edstays',
 N'ED stay longer than 7 days.',
 N'Modelled on VEMD 2026-27 validation E219/E350 (length of stay), upper bound',
 N'SELECT stay_id, CAST(stay_id AS nvarchar(100)), CONCAT(N''Stay of '', DATEDIFF(HOUR, intime, outtime), N'' hours'')
FROM ods.emr_ed_edstays WHERE outtime IS NOT NULL AND DATEDIFF(MINUTE, intime, outtime) > 10080');
GO

INSERT INTO dq.quality_rule (rule_code, severity, target_table, description, reference, check_sql)
VALUES ('LENGTH_OF_STAY_OVER_72H', 'Warning', N'ed.edstays',
 N'ED stay between 72 hours and 7 days: possible, but check.',
 N'Modelled on VEMD 2026-27 validation E219/E350 (length of stay), soft bound',
 N'SELECT stay_id, CAST(stay_id AS nvarchar(100)), CONCAT(N''Stay of '', DATEDIFF(HOUR, intime, outtime), N'' hours'')
FROM ods.emr_ed_edstays WHERE outtime IS NOT NULL
  AND DATEDIFF(MINUTE, intime, outtime) > 4320 AND DATEDIFF(MINUTE, intime, outtime) <= 10080');
GO

INSERT INTO dq.quality_rule (rule_code, severity, target_table, description, reference, check_sql)
VALUES ('ORPHAN_TRIAGE', 'Error', N'ed.triage',
 N'Triage record whose ED stay does not exist.',
 N'Referential integrity',
 N'SELECT t.stay_id, CAST(t.stay_id AS nvarchar(100)), N''No ED stay for this triage record''
FROM ods.emr_ed_triage AS t WHERE NOT EXISTS (SELECT 1 FROM ods.emr_ed_edstays AS e WHERE e.stay_id = t.stay_id)');
GO

INSERT INTO dq.quality_rule (rule_code, severity, target_table, description, reference, check_sql)
VALUES ('ORPHAN_VITALSIGN', 'Error', N'ed.vitalsign',
 N'Vital sign reading whose ED stay does not exist.',
 N'Referential integrity',
 N'SELECT v.stay_id, CONCAT(N''vitalsign:'', v.vitalsign_id), N''No ED stay for this vital sign reading''
FROM ods.emr_ed_vitalsign AS v WHERE NOT EXISTS (SELECT 1 FROM ods.emr_ed_edstays AS e WHERE e.stay_id = v.stay_id)');
GO

INSERT INTO dq.quality_rule (rule_code, severity, target_table, description, reference, check_sql)
VALUES ('ACUITY_NOT_ESI_LEVEL', 'Error', N'ed.triage',
 N'Triage acuity present but not an ESI level from 1 to 5.',
 N'MIMIC-IV-ED uses the US Emergency Severity Index, not the Australian ATS',
 N'SELECT stay_id, CAST(stay_id AS nvarchar(100)), CONCAT(N''Acuity '', acuity)
FROM ods.emr_ed_triage WHERE acuity IS NOT NULL AND acuity NOT IN (1, 2, 3, 4, 5)');
GO

INSERT INTO dq.quality_rule (rule_code, severity, target_table, description, reference, check_sql)
VALUES ('ADMITTED_WITHOUT_ADMISSION', 'Error', N'ed.edstays',
 N'Disposition is admitted but there is no hospital admission record for the stay.',
 N'Referential integrity',
 N'SELECT e.stay_id, CAST(e.stay_id AS nvarchar(100)),
       CASE WHEN e.hadm_id IS NULL THEN N''Admitted with no admission number'' ELSE CONCAT(N''Admission '', e.hadm_id, N'' not found'') END
FROM ods.emr_ed_edstays AS e
WHERE e.disposition = ''ADMITTED''
  AND (e.hadm_id IS NULL OR NOT EXISTS (SELECT 1 FROM ods.emr_hosp_admissions AS a WHERE a.hadm_id = e.hadm_id))');
GO

INSERT INTO dq.quality_rule (rule_code, severity, target_table, description, reference, check_sql)
VALUES ('ADMISSION_DISCHARGE_BEFORE_ADMIT', 'Error', N'hosp.admissions',
 N'Hospital discharge is before admission for an admission that began in ED.',
 N'Modelled on VEMD 2026-27 validation E340 logic applied to admissions',
 N'SELECT e.stay_id, CAST(e.stay_id AS nvarchar(100)), CONCAT(N''Admission '', a.hadm_id, N'' discharged before it began'')
FROM ods.emr_hosp_admissions AS a JOIN ods.emr_ed_edstays AS e ON e.hadm_id = a.hadm_id
WHERE a.dischtime IS NOT NULL AND a.dischtime < a.admittime');
GO

INSERT INTO dq.quality_rule (rule_code, severity, target_table, description, reference, check_sql)
VALUES ('TRIAGE_ACUITY_MISSING', 'Warning', N'ed.triage',
 N'Stay with no triage record, or triage without an acuity.',
 N'Acuity drives benchmarking; 15 of 222 stays in the demo data have none',
 N'SELECT e.stay_id, CAST(e.stay_id AS nvarchar(100)),
       CASE WHEN t.stay_id IS NULL THEN N''No triage record'' ELSE N''Triage has no acuity'' END
FROM ods.emr_ed_edstays AS e LEFT JOIN ods.emr_ed_triage AS t ON t.stay_id = e.stay_id
WHERE t.stay_id IS NULL OR t.acuity IS NULL');
GO

INSERT INTO dq.quality_rule (rule_code, severity, target_table, description, reference, check_sql)
VALUES ('O2SAT_IMPLAUSIBLE', 'Warning', N'ed.triage, ed.vitalsign',
 N'Oxygen saturation below 70% or above 100%.',
 N'Found in the demo data: a reading of 10%',
 N'WITH r AS (
  SELECT t.stay_id, CONCAT(N''triage:'', t.stay_id) AS k, t.temperature, t.heartrate, t.o2sat, t.sbp, t.dbp, t.pain
  FROM ods.emr_ed_triage AS t
  UNION ALL
  SELECT v.stay_id, CONCAT(N''vitalsign:'', v.vitalsign_id), v.temperature, v.heartrate, v.o2sat, v.sbp, v.dbp, v.pain
  FROM ods.emr_ed_vitalsign AS v)
SELECT stay_id, k, CONCAT(N''SpO2 '', o2sat) FROM r WHERE o2sat < 70 OR o2sat > 100');
GO

INSERT INTO dq.quality_rule (rule_code, severity, target_table, description, reference, check_sql)
VALUES ('HEARTRATE_IMPLAUSIBLE', 'Warning', N'ed.triage, ed.vitalsign',
 N'Heart rate below 20 or above 250.',
 N'Physiological range check',
 N'WITH r AS (
  SELECT t.stay_id, CONCAT(N''triage:'', t.stay_id) AS k, t.temperature, t.heartrate, t.o2sat, t.sbp, t.dbp, t.pain
  FROM ods.emr_ed_triage AS t
  UNION ALL
  SELECT v.stay_id, CONCAT(N''vitalsign:'', v.vitalsign_id), v.temperature, v.heartrate, v.o2sat, v.sbp, v.dbp, v.pain
  FROM ods.emr_ed_vitalsign AS v)
SELECT stay_id, k, CONCAT(N''Heart rate '', heartrate) FROM r WHERE heartrate < 20 OR heartrate > 250');
GO

INSERT INTO dq.quality_rule (rule_code, severity, target_table, description, reference, check_sql)
VALUES ('TEMPERATURE_IMPLAUSIBLE_F', 'Warning', N'ed.triage, ed.vitalsign',
 N'Temperature outside 85 to 108 degrees Fahrenheit (MIMIC records Fahrenheit).',
 N'Physiological range check, unit check',
 N'WITH r AS (
  SELECT t.stay_id, CONCAT(N''triage:'', t.stay_id) AS k, t.temperature, t.heartrate, t.o2sat, t.sbp, t.dbp, t.pain
  FROM ods.emr_ed_triage AS t
  UNION ALL
  SELECT v.stay_id, CONCAT(N''vitalsign:'', v.vitalsign_id), v.temperature, v.heartrate, v.o2sat, v.sbp, v.dbp, v.pain
  FROM ods.emr_ed_vitalsign AS v)
SELECT stay_id, k, CONCAT(N''Temperature '', temperature) FROM r WHERE temperature < 85 OR temperature > 108');
GO

INSERT INTO dq.quality_rule (rule_code, severity, target_table, description, reference, check_sql)
VALUES ('DIASTOLIC_ABOVE_SYSTOLIC', 'Warning', N'ed.triage, ed.vitalsign',
 N'Diastolic blood pressure above systolic.',
 N'Usually transposed values',
 N'WITH r AS (
  SELECT t.stay_id, CONCAT(N''triage:'', t.stay_id) AS k, t.temperature, t.heartrate, t.o2sat, t.sbp, t.dbp, t.pain
  FROM ods.emr_ed_triage AS t
  UNION ALL
  SELECT v.stay_id, CONCAT(N''vitalsign:'', v.vitalsign_id), v.temperature, v.heartrate, v.o2sat, v.sbp, v.dbp, v.pain
  FROM ods.emr_ed_vitalsign AS v)
SELECT stay_id, k, CONCAT(N''BP '', sbp, N''/'', dbp) FROM r WHERE dbp > sbp');
GO

INSERT INTO dq.quality_rule (rule_code, severity, target_table, description, reference, check_sql)
VALUES ('PAIN_UNPARSEABLE', 'Warning', N'ed.triage, ed.vitalsign',
 N'Pain is neither a 0 to 10 score nor a value in ref.pain_value_map.',
 N'Pain is free text in the source: scores, ''uta'' (unable to assess) and other strings',
 N'WITH r AS (
  SELECT t.stay_id, CONCAT(N''triage:'', t.stay_id) AS k, t.temperature, t.heartrate, t.o2sat, t.sbp, t.dbp, t.pain
  FROM ods.emr_ed_triage AS t
  UNION ALL
  SELECT v.stay_id, CONCAT(N''vitalsign:'', v.vitalsign_id), v.temperature, v.heartrate, v.o2sat, v.sbp, v.dbp, v.pain
  FROM ods.emr_ed_vitalsign AS v)
SELECT stay_id, k, CONCAT(N''Pain "'', pain, N''"'') FROM r
WHERE pain IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM ref.pain_value_map AS m WHERE m.raw_value = r.pain)
  AND (TRY_CAST(pain AS decimal(5, 2)) IS NULL OR TRY_CAST(pain AS decimal(5, 2)) NOT BETWEEN 0 AND 10)');
GO

INSERT INTO dq.quality_rule (rule_code, severity, target_table, description, reference, check_sql)
VALUES ('RHYTHM_NOT_IN_VOCABULARY', 'Warning', N'ed.vitalsign',
 N'Heart rhythm text not listed in ref.rhythm_map.',
 N'The source mixes codes and phrases for the same rhythm (''sr'', ''Sinus Rhythm'')',
 N'SELECT v.stay_id, CONCAT(N''vitalsign:'', v.vitalsign_id), CONCAT(N''Rhythm "'', v.rhythm, N''"'')
FROM ods.emr_ed_vitalsign AS v
WHERE v.rhythm IS NOT NULL AND NOT EXISTS (SELECT 1 FROM ref.rhythm_map AS m WHERE m.raw_value = v.rhythm)');
GO

INSERT INTO dq.quality_rule (rule_code, severity, target_table, description, reference, check_sql)
VALUES ('LANGUAGE_UNKNOWN', 'Warning', N'hosp.admissions',
 N'Preferred language recorded as ''?''.',
 N'Found in the demo data; placeholders must not reach reports as a language',
 N'SELECT CAST(NULL AS int), CONCAT(N''admission:'', hadm_id), N''Language is ?''
FROM ods.emr_hosp_admissions WHERE language = ''?''');
GO
