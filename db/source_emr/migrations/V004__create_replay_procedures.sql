/*
    Replay procedures for the mock EMR.

    admin.usp_reset_live         empty the live tables and the event queue
    admin.usp_build_replay_queue build the ordered event queue from admin.raw_*
    admin.usp_replay_next        release the next N events into the live tables

    Ordering rule: an event is never queued before its parent. If the source says a stay
    departed before it arrived (a real defect in clinical extracts), the departure is queued
    at the arrival time but the recorded outtime is kept as delivered, so the warehouse
    validation rules still see and flag it.
*/

CREATE OR ALTER PROCEDURE admin.usp_reset_live
AS
BEGIN
    SET NOCOUNT, XACT_ABORT ON;
    BEGIN TRANSACTION;
        /* DELETE rather than TRUNCATE: TRUNCATE on a change-tracked table is not tracked and
           invalidates every consumer's watermark. DELETE is tracked like any other change. */
        DELETE FROM ed.diagnosis;
        DELETE FROM ed.vitalsign;
        DELETE FROM ed.triage;
        DELETE FROM ed.edstays;
        DELETE FROM hosp.diagnoses_icd;
        DELETE FROM hosp.transfers;
        DELETE FROM hosp.admissions;
        DELETE FROM hosp.patients;
        DELETE FROM admin.replay_event;
    COMMIT;
END;
GO

CREATE OR ALTER PROCEDURE admin.usp_build_replay_queue
AS
BEGIN
    SET NOCOUNT, XACT_ABORT ON;

    IF EXISTS (SELECT 1 FROM admin.replay_event WHERE applied_at_utc IS NOT NULL)
        THROW 50001, 'Replay already in progress. Run admin.usp_reset_live first.', 1;

    BEGIN TRANSACTION;
        DELETE FROM admin.replay_event;

        /* Reference data is static in a real EMR, so it is published in full up front. */
        INSERT INTO hosp.d_icd_diagnoses (icd_code, icd_version, long_title)
        SELECT r.icd_code, r.icd_version, MAX(r.long_title)
        FROM admin.raw_d_icd_diagnoses AS r
        WHERE r.icd_code IS NOT NULL AND r.icd_version IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM hosp.d_icd_diagnoses AS d
                          WHERE d.icd_code = r.icd_code AND d.icd_version = r.icd_version)
        GROUP BY r.icd_code, r.icd_version;

        WITH first_seen AS (
            SELECT subject_id, MIN(t) AS first_time
            FROM (
                SELECT subject_id, admittime AS t FROM admin.raw_admissions
                UNION ALL SELECT subject_id, intime FROM admin.raw_edstays
                UNION ALL SELECT subject_id, intime FROM admin.raw_transfers
            ) AS x
            GROUP BY subject_id
        ),
        events AS (
            SELECT DISTINCT p.subject_id AS key_1, CAST(NULL AS bigint) AS key_2,
                   'PATIENT_REGISTER' AS event_type, 1 AS priority,
                   COALESCE(f.first_time, CAST('2000-01-01' AS datetime2(0))) AS event_time
            FROM admin.raw_patients AS p
            LEFT JOIN first_seen AS f ON f.subject_id = p.subject_id
            WHERE p.subject_id IS NOT NULL

            UNION ALL
            SELECT hadm_id, NULL, 'ADMIT', 2, admittime
            FROM admin.raw_admissions WHERE hadm_id IS NOT NULL AND admittime IS NOT NULL

            UNION ALL
            SELECT stay_id, NULL, 'ED_ARRIVE', 3, intime
            FROM admin.raw_edstays WHERE stay_id IS NOT NULL AND intime IS NOT NULL

            UNION ALL
            SELECT t.transfer_id, NULL, 'TRANSFER_IN', 4, COALESCE(t.intime, a.admittime)
            FROM admin.raw_transfers AS t
            LEFT JOIN admin.raw_admissions AS a ON a.hadm_id = t.hadm_id
            WHERE t.transfer_id IS NOT NULL AND COALESCE(t.intime, a.admittime) IS NOT NULL

            UNION ALL
            SELECT v.raw_row_id, v.stay_id, 'ED_VITALS', 5,
                   CASE WHEN v.charttime < s.intime THEN s.intime ELSE v.charttime END
            FROM admin.raw_vitalsign AS v
            JOIN admin.raw_edstays AS s ON s.stay_id = v.stay_id
            WHERE v.charttime IS NOT NULL

            UNION ALL
            SELECT transfer_id, NULL, 'TRANSFER_OUT', 6,
                   CASE WHEN outtime < intime THEN intime ELSE outtime END
            FROM admin.raw_transfers WHERE transfer_id IS NOT NULL AND outtime IS NOT NULL AND intime IS NOT NULL

            UNION ALL
            SELECT stay_id, NULL, 'ED_DEPART', 7, CASE WHEN outtime < intime THEN intime ELSE outtime END
            FROM admin.raw_edstays WHERE stay_id IS NOT NULL AND intime IS NOT NULL AND outtime IS NOT NULL

            UNION ALL
            SELECT hadm_id, NULL, 'DISCHARGE', 8, CASE WHEN dischtime < admittime THEN admittime ELSE dischtime END
            FROM admin.raw_admissions WHERE hadm_id IS NOT NULL AND admittime IS NOT NULL AND dischtime IS NOT NULL
        )
        INSERT INTO admin.replay_event (event_seq, event_time, event_type, key_1, key_2)
        SELECT ROW_NUMBER() OVER (ORDER BY event_time, priority, key_1, key_2),
               event_time, event_type, key_1, key_2
        FROM events;
    COMMIT;

    SELECT COUNT(*) AS events_queued, MIN(event_time) AS first_event, MAX(event_time) AS last_event
    FROM admin.replay_event;
END;
GO

CREATE OR ALTER PROCEDURE admin.usp_replay_next
    @max_events int = 500
AS
BEGIN
    SET NOCOUNT, XACT_ABORT ON;

    CREATE TABLE #batch (
        event_seq  int          NOT NULL PRIMARY KEY,
        event_type varchar(20)  NOT NULL,
        key_1      bigint       NOT NULL,
        key_2      bigint       NULL,
        event_time datetime2(0) NOT NULL
    );

    BEGIN TRANSACTION;
        INSERT INTO #batch (event_seq, event_type, key_1, key_2, event_time)
        SELECT TOP (@max_events) event_seq, event_type, key_1, key_2, event_time
        FROM admin.replay_event WITH (UPDLOCK, READPAST)
        WHERE applied_at_utc IS NULL
        ORDER BY event_seq;

        /* Applied in dependency order. Within one batch a parent always precedes its child
           because the queue never places a child before its parent. Duplicate rows in the raw
           extract are collapsed with ROW_NUMBER, as a live system cannot hold two rows with
           the same primary key. */

        INSERT INTO hosp.patients (subject_id, gender, anchor_age, anchor_year, anchor_year_group, dod)
        SELECT subject_id, gender, anchor_age, anchor_year, anchor_year_group, dod
        FROM (
            SELECT p.*, ROW_NUMBER() OVER (PARTITION BY p.subject_id ORDER BY (SELECT NULL)) AS rn
            FROM admin.raw_patients AS p
            JOIN #batch AS b ON b.event_type = 'PATIENT_REGISTER' AND b.key_1 = p.subject_id
        ) AS x
        WHERE rn = 1 AND NOT EXISTS (SELECT 1 FROM hosp.patients AS l WHERE l.subject_id = x.subject_id);

        INSERT INTO hosp.admissions (hadm_id, subject_id, admittime, admission_type, admit_provider_id,
                                     admission_location, insurance, language, marital_status, race,
                                     edregtime, edouttime)
        SELECT hadm_id, subject_id, admittime, admission_type, admit_provider_id,
               admission_location, insurance, language, marital_status, race, edregtime, edouttime
        FROM (
            SELECT a.*, ROW_NUMBER() OVER (PARTITION BY a.hadm_id ORDER BY (SELECT NULL)) AS rn
            FROM admin.raw_admissions AS a
            JOIN #batch AS b ON b.event_type = 'ADMIT' AND b.key_1 = a.hadm_id
        ) AS x
        WHERE rn = 1 AND NOT EXISTS (SELECT 1 FROM hosp.admissions AS l WHERE l.hadm_id = x.hadm_id);

        INSERT INTO ed.edstays (stay_id, subject_id, intime, gender, race, arrival_transport)
        SELECT stay_id, subject_id, intime, gender, race, arrival_transport
        FROM (
            SELECT s.*, ROW_NUMBER() OVER (PARTITION BY s.stay_id ORDER BY (SELECT NULL)) AS rn
            FROM admin.raw_edstays AS s
            JOIN #batch AS b ON b.event_type = 'ED_ARRIVE' AND b.key_1 = s.stay_id
        ) AS x
        WHERE rn = 1 AND NOT EXISTS (SELECT 1 FROM ed.edstays AS l WHERE l.stay_id = x.stay_id);

        INSERT INTO ed.triage (stay_id, subject_id, temperature, heartrate, resprate, o2sat, sbp, dbp,
                               pain, acuity, chiefcomplaint)
        SELECT stay_id, subject_id, temperature, heartrate, resprate, o2sat, sbp, dbp, pain, acuity, chiefcomplaint
        FROM (
            SELECT t.*, ROW_NUMBER() OVER (PARTITION BY t.stay_id ORDER BY (SELECT NULL)) AS rn
            FROM admin.raw_triage AS t
            JOIN #batch AS b ON b.event_type = 'ED_ARRIVE' AND b.key_1 = t.stay_id
        ) AS x
        WHERE rn = 1 AND NOT EXISTS (SELECT 1 FROM ed.triage AS l WHERE l.stay_id = x.stay_id);

        INSERT INTO hosp.transfers (transfer_id, subject_id, hadm_id, eventtype, careunit, intime)
        SELECT transfer_id, subject_id, hadm_id, eventtype, careunit, intime
        FROM (
            SELECT t.*, ROW_NUMBER() OVER (PARTITION BY t.transfer_id ORDER BY (SELECT NULL)) AS rn
            FROM admin.raw_transfers AS t
            JOIN #batch AS b ON b.event_type = 'TRANSFER_IN' AND b.key_1 = t.transfer_id
        ) AS x
        WHERE rn = 1 AND NOT EXISTS (SELECT 1 FROM hosp.transfers AS l WHERE l.transfer_id = x.transfer_id);

        INSERT INTO ed.vitalsign (stay_id, subject_id, charttime, temperature, heartrate, resprate, o2sat,
                                  sbp, dbp, rhythm, pain)
        SELECT v.stay_id, v.subject_id, v.charttime, v.temperature, v.heartrate, v.resprate, v.o2sat,
               v.sbp, v.dbp, v.rhythm, v.pain
        FROM admin.raw_vitalsign AS v
        JOIN #batch AS b ON b.event_type = 'ED_VITALS' AND b.key_1 = v.raw_row_id;

        UPDATE l SET l.outtime = r.outtime
        FROM hosp.transfers AS l
        JOIN admin.raw_transfers AS r ON r.transfer_id = l.transfer_id
        JOIN #batch AS b ON b.event_type = 'TRANSFER_OUT' AND b.key_1 = l.transfer_id;

        UPDATE l SET l.outtime = r.outtime, l.disposition = r.disposition, l.hadm_id = r.hadm_id
        FROM ed.edstays AS l
        JOIN admin.raw_edstays AS r ON r.stay_id = l.stay_id
        JOIN #batch AS b ON b.event_type = 'ED_DEPART' AND b.key_1 = l.stay_id;

        INSERT INTO ed.diagnosis (stay_id, subject_id, seq_num, icd_code, icd_version, icd_title)
        SELECT stay_id, subject_id, seq_num, icd_code, icd_version, icd_title
        FROM (
            SELECT d.*, ROW_NUMBER() OVER (PARTITION BY d.stay_id, d.seq_num ORDER BY (SELECT NULL)) AS rn
            FROM admin.raw_ed_diagnosis AS d
            JOIN #batch AS b ON b.event_type = 'ED_DEPART' AND b.key_1 = d.stay_id
        ) AS x
        WHERE rn = 1 AND x.seq_num IS NOT NULL AND x.icd_code IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM ed.diagnosis AS l WHERE l.stay_id = x.stay_id AND l.seq_num = x.seq_num);

        UPDATE l SET l.dischtime = r.dischtime, l.deathtime = r.deathtime,
                     l.discharge_location = r.discharge_location, l.hospital_expire_flag = r.hospital_expire_flag
        FROM hosp.admissions AS l
        JOIN admin.raw_admissions AS r ON r.hadm_id = l.hadm_id
        JOIN #batch AS b ON b.event_type = 'DISCHARGE' AND b.key_1 = l.hadm_id;

        INSERT INTO hosp.diagnoses_icd (subject_id, hadm_id, seq_num, icd_code, icd_version)
        SELECT subject_id, hadm_id, seq_num, icd_code, icd_version
        FROM (
            SELECT d.*, ROW_NUMBER() OVER (PARTITION BY d.hadm_id, d.seq_num, d.icd_code, d.icd_version
                                           ORDER BY (SELECT NULL)) AS rn
            FROM admin.raw_diagnoses_icd AS d
            JOIN #batch AS b ON b.event_type = 'DISCHARGE' AND b.key_1 = d.hadm_id
        ) AS x
        WHERE rn = 1 AND x.seq_num IS NOT NULL AND x.icd_code IS NOT NULL AND x.icd_version IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM hosp.diagnoses_icd AS l
                          WHERE l.hadm_id = x.hadm_id AND l.seq_num = x.seq_num
                            AND l.icd_code = x.icd_code AND l.icd_version = x.icd_version);

        UPDATE e SET e.applied_at_utc = SYSUTCDATETIME()
        FROM admin.replay_event AS e
        JOIN #batch AS b ON b.event_seq = e.event_seq;
    COMMIT;

    SELECT (SELECT COUNT(*) FROM #batch) AS events_applied,
           (SELECT COUNT(*) FROM admin.replay_event WHERE applied_at_utc IS NULL) AS events_remaining,
           (SELECT MAX(event_time) FROM #batch) AS simulated_clock;
END;
GO
