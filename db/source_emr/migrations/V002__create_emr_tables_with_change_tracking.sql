/*
    Live EMR tables, shaped like the MIMIC-IV hosp and ed modules.

    Each table has a primary key (Change Tracking needs one) and Change Tracking switched on,
    so the warehouse can ask "what changed since version N?" instead of re-reading everything.

    No foreign keys: the source system does not enforce them (MIMIC does not guarantee
    referential integrity either), and pretending otherwise would hide exactly the kind of
    orphan records the warehouse validation layer is there to catch.

    ed.vitalsign has no natural key in MIMIC (a stay can have two readings at the same
    minute), so the EMR assigns a surrogate row id, as a real charting system would.
*/

CREATE TABLE hosp.patients (
    subject_id          int          NOT NULL CONSTRAINT PK_patients PRIMARY KEY,
    gender              varchar(10)  NULL,
    anchor_age          smallint     NULL,
    anchor_year         smallint     NULL,
    anchor_year_group   varchar(20)  NULL,
    dod                 date         NULL
);

CREATE TABLE hosp.admissions (
    hadm_id              int           NOT NULL CONSTRAINT PK_admissions PRIMARY KEY,
    subject_id           int           NOT NULL,
    admittime            datetime2(0)  NOT NULL,
    dischtime            datetime2(0)  NULL,
    deathtime            datetime2(0)  NULL,
    admission_type       varchar(50)   NULL,
    admit_provider_id    varchar(20)   NULL,
    admission_location   varchar(100)  NULL,
    discharge_location   varchar(100)  NULL,
    insurance            varchar(50)   NULL,
    language             varchar(50)   NULL,
    marital_status       varchar(50)   NULL,
    race                 varchar(100)  NULL,
    edregtime            datetime2(0)  NULL,
    edouttime            datetime2(0)  NULL,
    hospital_expire_flag tinyint       NULL
);

CREATE TABLE hosp.transfers (
    transfer_id  bigint        NOT NULL CONSTRAINT PK_transfers PRIMARY KEY,
    subject_id   int           NOT NULL,
    hadm_id      int           NULL,
    eventtype    varchar(20)   NULL,
    careunit     varchar(100)  NULL,
    intime       datetime2(0)  NULL,
    outtime      datetime2(0)  NULL
);

CREATE TABLE hosp.diagnoses_icd (
    subject_id   int          NOT NULL,
    hadm_id      int          NOT NULL,
    seq_num      smallint     NOT NULL,
    icd_code     varchar(10)  NOT NULL,
    icd_version  tinyint      NOT NULL,
    CONSTRAINT PK_diagnoses_icd PRIMARY KEY (hadm_id, seq_num, icd_code, icd_version)
);

CREATE TABLE hosp.d_icd_diagnoses (
    icd_code     varchar(10)   NOT NULL,
    icd_version  tinyint       NOT NULL,
    long_title   varchar(500)  NULL,
    CONSTRAINT PK_d_icd_diagnoses PRIMARY KEY (icd_code, icd_version)
);

CREATE TABLE ed.edstays (
    stay_id            int           NOT NULL CONSTRAINT PK_edstays PRIMARY KEY,
    subject_id         int           NOT NULL,
    hadm_id            int           NULL,
    intime             datetime2(0)  NOT NULL,
    outtime            datetime2(0)  NULL,
    gender             varchar(10)   NULL,
    race               varchar(100)  NULL,
    arrival_transport  varchar(50)   NULL,
    disposition        varchar(50)   NULL
);

CREATE TABLE ed.triage (
    stay_id         int            NOT NULL CONSTRAINT PK_triage PRIMARY KEY,
    subject_id      int            NOT NULL,
    temperature     decimal(6, 2)  NULL,
    heartrate       decimal(6, 1)  NULL,
    resprate        decimal(6, 1)  NULL,
    o2sat           decimal(6, 1)  NULL,
    sbp             decimal(6, 1)  NULL,
    dbp             decimal(6, 1)  NULL,
    pain            varchar(50)    NULL,
    acuity          decimal(3, 1)  NULL,
    chiefcomplaint  varchar(1000)  NULL
);

CREATE TABLE ed.vitalsign (
    vitalsign_id  bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_vitalsign PRIMARY KEY,
    stay_id       int            NOT NULL,
    subject_id    int            NOT NULL,
    charttime     datetime2(0)   NOT NULL,
    temperature   decimal(6, 2)  NULL,
    heartrate     decimal(6, 1)  NULL,
    resprate      decimal(6, 1)  NULL,
    o2sat         decimal(6, 1)  NULL,
    sbp           decimal(6, 1)  NULL,
    dbp           decimal(6, 1)  NULL,
    rhythm        varchar(100)   NULL,
    pain          varchar(50)    NULL
);

CREATE INDEX IX_vitalsign_stay ON ed.vitalsign (stay_id, charttime);

CREATE TABLE ed.diagnosis (
    stay_id      int           NOT NULL,
    subject_id   int           NOT NULL,
    seq_num      smallint      NOT NULL,
    icd_code     varchar(10)   NOT NULL,
    icd_version  tinyint       NOT NULL,
    icd_title    varchar(500)  NULL,
    CONSTRAINT PK_ed_diagnosis PRIMARY KEY (stay_id, seq_num)
);
GO

ALTER TABLE hosp.patients        ENABLE CHANGE_TRACKING WITH (TRACK_COLUMNS_UPDATED = ON);
ALTER TABLE hosp.admissions      ENABLE CHANGE_TRACKING WITH (TRACK_COLUMNS_UPDATED = ON);
ALTER TABLE hosp.transfers       ENABLE CHANGE_TRACKING WITH (TRACK_COLUMNS_UPDATED = ON);
ALTER TABLE hosp.diagnoses_icd   ENABLE CHANGE_TRACKING WITH (TRACK_COLUMNS_UPDATED = ON);
ALTER TABLE hosp.d_icd_diagnoses ENABLE CHANGE_TRACKING WITH (TRACK_COLUMNS_UPDATED = ON);
ALTER TABLE ed.edstays           ENABLE CHANGE_TRACKING WITH (TRACK_COLUMNS_UPDATED = ON);
ALTER TABLE ed.triage            ENABLE CHANGE_TRACKING WITH (TRACK_COLUMNS_UPDATED = ON);
ALTER TABLE ed.vitalsign         ENABLE CHANGE_TRACKING WITH (TRACK_COLUMNS_UPDATED = ON);
ALTER TABLE ed.diagnosis         ENABLE CHANGE_TRACKING WITH (TRACK_COLUMNS_UPDATED = ON);
GO
