/*
    Replay holding area.

    The MIMIC extracts are complete histories. To behave like a live EMR, the full extract is
    loaded here first (admin.raw_*), then admin.usp_replay_next releases it into the live
    tables in event order: an ED stay is inserted at arrival with no departure, then updated
    at departure, the way an ED tracking system records it. That produces genuine insert and
    update traffic for the warehouse to replicate.

    Raw tables are deliberately constraint free and nullable: they hold the extract exactly as
    delivered, including its defects.
*/

CREATE TABLE admin.raw_patients (
    subject_id int NULL, gender varchar(10) NULL, anchor_age smallint NULL, anchor_year smallint NULL,
    anchor_year_group varchar(20) NULL, dod date NULL
);

CREATE TABLE admin.raw_admissions (
    subject_id int NULL, hadm_id int NULL, admittime datetime2(0) NULL, dischtime datetime2(0) NULL,
    deathtime datetime2(0) NULL, admission_type varchar(50) NULL, admit_provider_id varchar(20) NULL,
    admission_location varchar(100) NULL, discharge_location varchar(100) NULL, insurance varchar(50) NULL,
    language varchar(50) NULL, marital_status varchar(50) NULL, race varchar(100) NULL,
    edregtime datetime2(0) NULL, edouttime datetime2(0) NULL, hospital_expire_flag tinyint NULL
);

CREATE TABLE admin.raw_transfers (
    subject_id int NULL, hadm_id int NULL, transfer_id bigint NULL, eventtype varchar(20) NULL,
    careunit varchar(100) NULL, intime datetime2(0) NULL, outtime datetime2(0) NULL
);

CREATE TABLE admin.raw_diagnoses_icd (
    subject_id int NULL, hadm_id int NULL, seq_num smallint NULL, icd_code varchar(10) NULL, icd_version tinyint NULL
);

CREATE TABLE admin.raw_d_icd_diagnoses (
    icd_code varchar(10) NULL, icd_version tinyint NULL, long_title varchar(500) NULL
);

CREATE TABLE admin.raw_edstays (
    subject_id int NULL, hadm_id int NULL, stay_id int NULL, intime datetime2(0) NULL, outtime datetime2(0) NULL,
    gender varchar(10) NULL, race varchar(100) NULL, arrival_transport varchar(50) NULL, disposition varchar(50) NULL
);

CREATE TABLE admin.raw_triage (
    subject_id int NULL, stay_id int NULL, temperature decimal(6, 2) NULL, heartrate decimal(6, 1) NULL,
    resprate decimal(6, 1) NULL, o2sat decimal(6, 1) NULL, sbp decimal(6, 1) NULL, dbp decimal(6, 1) NULL,
    pain varchar(50) NULL, acuity decimal(3, 1) NULL, chiefcomplaint varchar(1000) NULL
);

CREATE TABLE admin.raw_vitalsign (
    raw_row_id int IDENTITY(1,1) NOT NULL CONSTRAINT PK_raw_vitalsign PRIMARY KEY,
    subject_id int NULL, stay_id int NULL, charttime datetime2(0) NULL, temperature decimal(6, 2) NULL,
    heartrate decimal(6, 1) NULL, resprate decimal(6, 1) NULL, o2sat decimal(6, 1) NULL, sbp decimal(6, 1) NULL,
    dbp decimal(6, 1) NULL, rhythm varchar(100) NULL, pain varchar(50) NULL
);

CREATE TABLE admin.raw_ed_diagnosis (
    subject_id int NULL, stay_id int NULL, seq_num smallint NULL, icd_code varchar(10) NULL,
    icd_version tinyint NULL, icd_title varchar(500) NULL
);

/* Load audit: which file, which checksum, how many rows, when. */
CREATE TABLE admin.raw_load_log (
    load_id         int IDENTITY(1,1) NOT NULL CONSTRAINT PK_raw_load_log PRIMARY KEY,
    source_file     nvarchar(260) NOT NULL,
    sha256          char(64)      NOT NULL,
    target_table    sysname       NOT NULL,
    rows_loaded     int           NOT NULL,
    loaded_at_utc   datetime2(3)  NOT NULL CONSTRAINT DF_raw_load_log DEFAULT SYSUTCDATETIME()
);

/* The ordered event queue, built once from the raw tables. */
CREATE TABLE admin.replay_event (
    event_seq     int           NOT NULL CONSTRAINT PK_replay_event PRIMARY KEY,
    event_time    datetime2(0)  NOT NULL,
    event_type    varchar(20)   NOT NULL,
    key_1         bigint        NOT NULL,
    key_2         bigint        NULL,
    applied_at_utc datetime2(3) NULL,
    CONSTRAINT CK_replay_event_type CHECK (event_type IN
        ('PATIENT_REGISTER', 'ADMIT', 'ED_ARRIVE', 'TRANSFER_IN', 'ED_VITALS', 'TRANSFER_OUT', 'ED_DEPART', 'DISCHARGE'))
);

CREATE INDEX IX_replay_event_pending ON admin.replay_event (applied_at_utc, event_seq);
GO
