/*
    Replication targets for the EMR source.

      stg.emr_<schema>_<table>_ct   one batch of changes as read from CHANGETABLE: the
                                    operation (I, U, D), the change version and the row.
                                    Truncated and refilled on every run.
      ods.emr_<schema>_<table>      current-state mirror of the source table (operational
                                    data store). Same key as the source, plus replication
                                    metadata columns prefixed with an underscore.

    Generated from one column specification so the source, stage and replica stay aligned.
*/

IF SCHEMA_ID(N'ods') IS NULL EXEC (N'CREATE SCHEMA ods AUTHORIZATION dbo;');
GO

CREATE TABLE stg.emr_hosp_patients_ct (
    sys_change_operation char(1) NOT NULL,
    sys_change_version   bigint  NULL,
    subject_id         int NULL,
    gender             varchar(10) NULL,
    anchor_age         smallint NULL,
    anchor_year        smallint NULL,
    anchor_year_group  varchar(20) NULL,
    dod                date NULL,
    load_run_id          bigint  NOT NULL
);

CREATE TABLE ods.emr_hosp_patients (
    subject_id         int NOT NULL,
    gender             varchar(10) NULL,
    anchor_age         smallint NULL,
    anchor_year        smallint NULL,
    anchor_year_group  varchar(20) NULL,
    dod                date NULL,
    _ct_version        bigint NULL,
    _replicated_at_utc datetime2(3) NOT NULL CONSTRAINT DF_ods_emr_hosp_patients_repl DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_ods_emr_hosp_patients PRIMARY KEY (subject_id)
);
GO

CREATE TABLE stg.emr_hosp_admissions_ct (
    sys_change_operation char(1) NOT NULL,
    sys_change_version   bigint  NULL,
    hadm_id               int NULL,
    subject_id            int NULL,
    admittime             datetime2(0) NULL,
    dischtime             datetime2(0) NULL,
    deathtime             datetime2(0) NULL,
    admission_type        varchar(50) NULL,
    admit_provider_id     varchar(20) NULL,
    admission_location    varchar(100) NULL,
    discharge_location    varchar(100) NULL,
    insurance             varchar(50) NULL,
    language              varchar(50) NULL,
    marital_status        varchar(50) NULL,
    race                  varchar(100) NULL,
    edregtime             datetime2(0) NULL,
    edouttime             datetime2(0) NULL,
    hospital_expire_flag  tinyint NULL,
    load_run_id          bigint  NOT NULL
);

CREATE TABLE ods.emr_hosp_admissions (
    hadm_id               int NOT NULL,
    subject_id            int NULL,
    admittime             datetime2(0) NULL,
    dischtime             datetime2(0) NULL,
    deathtime             datetime2(0) NULL,
    admission_type        varchar(50) NULL,
    admit_provider_id     varchar(20) NULL,
    admission_location    varchar(100) NULL,
    discharge_location    varchar(100) NULL,
    insurance             varchar(50) NULL,
    language              varchar(50) NULL,
    marital_status        varchar(50) NULL,
    race                  varchar(100) NULL,
    edregtime             datetime2(0) NULL,
    edouttime             datetime2(0) NULL,
    hospital_expire_flag  tinyint NULL,
    _ct_version           bigint NULL,
    _replicated_at_utc    datetime2(3) NOT NULL CONSTRAINT DF_ods_emr_hosp_admissions_repl DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_ods_emr_hosp_admissions PRIMARY KEY (hadm_id)
);
GO

CREATE TABLE stg.emr_hosp_transfers_ct (
    sys_change_operation char(1) NOT NULL,
    sys_change_version   bigint  NULL,
    transfer_id  bigint NULL,
    subject_id   int NULL,
    hadm_id      int NULL,
    eventtype    varchar(20) NULL,
    careunit     varchar(100) NULL,
    intime       datetime2(0) NULL,
    outtime      datetime2(0) NULL,
    load_run_id          bigint  NOT NULL
);

CREATE TABLE ods.emr_hosp_transfers (
    transfer_id  bigint NOT NULL,
    subject_id   int NULL,
    hadm_id      int NULL,
    eventtype    varchar(20) NULL,
    careunit     varchar(100) NULL,
    intime       datetime2(0) NULL,
    outtime      datetime2(0) NULL,
    _ct_version  bigint NULL,
    _replicated_at_utc datetime2(3) NOT NULL CONSTRAINT DF_ods_emr_hosp_transfers_repl DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_ods_emr_hosp_transfers PRIMARY KEY (transfer_id)
);
GO

CREATE TABLE stg.emr_hosp_diagnoses_icd_ct (
    sys_change_operation char(1) NOT NULL,
    sys_change_version   bigint  NULL,
    hadm_id      int NULL,
    seq_num      smallint NULL,
    icd_code     varchar(10) NULL,
    icd_version  tinyint NULL,
    subject_id   int NULL,
    load_run_id          bigint  NOT NULL
);

CREATE TABLE ods.emr_hosp_diagnoses_icd (
    hadm_id      int NOT NULL,
    seq_num      smallint NOT NULL,
    icd_code     varchar(10) NOT NULL,
    icd_version  tinyint NOT NULL,
    subject_id   int NULL,
    _ct_version  bigint NULL,
    _replicated_at_utc datetime2(3) NOT NULL CONSTRAINT DF_ods_emr_hosp_diagnoses_icd_repl DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_ods_emr_hosp_diagnoses_icd PRIMARY KEY (hadm_id, seq_num, icd_code, icd_version)
);
GO

CREATE TABLE stg.emr_hosp_d_icd_diagnoses_ct (
    sys_change_operation char(1) NOT NULL,
    sys_change_version   bigint  NULL,
    icd_code     varchar(10) NULL,
    icd_version  tinyint NULL,
    long_title   varchar(500) NULL,
    load_run_id          bigint  NOT NULL
);

CREATE TABLE ods.emr_hosp_d_icd_diagnoses (
    icd_code     varchar(10) NOT NULL,
    icd_version  tinyint NOT NULL,
    long_title   varchar(500) NULL,
    _ct_version  bigint NULL,
    _replicated_at_utc datetime2(3) NOT NULL CONSTRAINT DF_ods_emr_hosp_d_icd_diagnoses_repl DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_ods_emr_hosp_d_icd_diagnoses PRIMARY KEY (icd_code, icd_version)
);
GO

CREATE TABLE stg.emr_ed_edstays_ct (
    sys_change_operation char(1) NOT NULL,
    sys_change_version   bigint  NULL,
    stay_id            int NULL,
    subject_id         int NULL,
    hadm_id            int NULL,
    intime             datetime2(0) NULL,
    outtime            datetime2(0) NULL,
    gender             varchar(10) NULL,
    race               varchar(100) NULL,
    arrival_transport  varchar(50) NULL,
    disposition        varchar(50) NULL,
    load_run_id          bigint  NOT NULL
);

CREATE TABLE ods.emr_ed_edstays (
    stay_id            int NOT NULL,
    subject_id         int NULL,
    hadm_id            int NULL,
    intime             datetime2(0) NULL,
    outtime            datetime2(0) NULL,
    gender             varchar(10) NULL,
    race               varchar(100) NULL,
    arrival_transport  varchar(50) NULL,
    disposition        varchar(50) NULL,
    _ct_version        bigint NULL,
    _replicated_at_utc datetime2(3) NOT NULL CONSTRAINT DF_ods_emr_ed_edstays_repl DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_ods_emr_ed_edstays PRIMARY KEY (stay_id)
);
GO

CREATE TABLE stg.emr_ed_triage_ct (
    sys_change_operation char(1) NOT NULL,
    sys_change_version   bigint  NULL,
    stay_id         int NULL,
    subject_id      int NULL,
    temperature     decimal(6, 2) NULL,
    heartrate       decimal(6, 1) NULL,
    resprate        decimal(6, 1) NULL,
    o2sat           decimal(6, 1) NULL,
    sbp             decimal(6, 1) NULL,
    dbp             decimal(6, 1) NULL,
    pain            varchar(50) NULL,
    acuity          decimal(3, 1) NULL,
    chiefcomplaint  varchar(1000) NULL,
    load_run_id          bigint  NOT NULL
);

CREATE TABLE ods.emr_ed_triage (
    stay_id         int NOT NULL,
    subject_id      int NULL,
    temperature     decimal(6, 2) NULL,
    heartrate       decimal(6, 1) NULL,
    resprate        decimal(6, 1) NULL,
    o2sat           decimal(6, 1) NULL,
    sbp             decimal(6, 1) NULL,
    dbp             decimal(6, 1) NULL,
    pain            varchar(50) NULL,
    acuity          decimal(3, 1) NULL,
    chiefcomplaint  varchar(1000) NULL,
    _ct_version     bigint NULL,
    _replicated_at_utc datetime2(3) NOT NULL CONSTRAINT DF_ods_emr_ed_triage_repl DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_ods_emr_ed_triage PRIMARY KEY (stay_id)
);
GO

CREATE TABLE stg.emr_ed_vitalsign_ct (
    sys_change_operation char(1) NOT NULL,
    sys_change_version   bigint  NULL,
    vitalsign_id  bigint NULL,
    stay_id       int NULL,
    subject_id    int NULL,
    charttime     datetime2(0) NULL,
    temperature   decimal(6, 2) NULL,
    heartrate     decimal(6, 1) NULL,
    resprate      decimal(6, 1) NULL,
    o2sat         decimal(6, 1) NULL,
    sbp           decimal(6, 1) NULL,
    dbp           decimal(6, 1) NULL,
    rhythm        varchar(100) NULL,
    pain          varchar(50) NULL,
    load_run_id          bigint  NOT NULL
);

CREATE TABLE ods.emr_ed_vitalsign (
    vitalsign_id  bigint NOT NULL,
    stay_id       int NULL,
    subject_id    int NULL,
    charttime     datetime2(0) NULL,
    temperature   decimal(6, 2) NULL,
    heartrate     decimal(6, 1) NULL,
    resprate      decimal(6, 1) NULL,
    o2sat         decimal(6, 1) NULL,
    sbp           decimal(6, 1) NULL,
    dbp           decimal(6, 1) NULL,
    rhythm        varchar(100) NULL,
    pain          varchar(50) NULL,
    _ct_version   bigint NULL,
    _replicated_at_utc datetime2(3) NOT NULL CONSTRAINT DF_ods_emr_ed_vitalsign_repl DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_ods_emr_ed_vitalsign PRIMARY KEY (vitalsign_id)
);
GO

CREATE TABLE stg.emr_ed_diagnosis_ct (
    sys_change_operation char(1) NOT NULL,
    sys_change_version   bigint  NULL,
    stay_id      int NULL,
    seq_num      smallint NULL,
    subject_id   int NULL,
    icd_code     varchar(10) NULL,
    icd_version  tinyint NULL,
    icd_title    varchar(500) NULL,
    load_run_id          bigint  NOT NULL
);

CREATE TABLE ods.emr_ed_diagnosis (
    stay_id      int NOT NULL,
    seq_num      smallint NOT NULL,
    subject_id   int NULL,
    icd_code     varchar(10) NULL,
    icd_version  tinyint NULL,
    icd_title    varchar(500) NULL,
    _ct_version  bigint NULL,
    _replicated_at_utc datetime2(3) NOT NULL CONSTRAINT DF_ods_emr_ed_diagnosis_repl DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_ods_emr_ed_diagnosis PRIMARY KEY (stay_id, seq_num)
);
GO
