/*
    AIHW MyHospitals: landing, reference and ODS tables.

    stg.aihw_flat_raw         every API row exactly as delivered (JSON text), one table for all
                              measure categories, keyed by the run that landed it
    stg.aihw_slice_manifest   one row per (category, reporting unit) request: how many rows the
                              API said it had, so the apply step can prove nothing was lost
    ref.aihw_flag_code        suppression and caveat codes (X01 "<5", X40 "NP", ...) from the API
    ods.aihw_reporting_unit   hospitals, networks, states and national, with their mappings
    ods.aihw_measurement      current release of the measure values, typed and decoded

    The release marker is kept in etl.watermark (type ApiDataVersion), not a new table.
*/

CREATE TABLE stg.aihw_flat_raw (
    raw_id              bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_aihw_flat_raw PRIMARY KEY,
    load_run_id         bigint        NOT NULL,
    category_code       varchar(30)   NOT NULL,
    reporting_unit_code varchar(20)   NOT NULL,
    row_json            nvarchar(max) NOT NULL,
    CONSTRAINT CK_aihw_flat_raw_json CHECK (ISJSON(row_json) = 1)
);
GO

CREATE INDEX IX_aihw_flat_raw_slice ON stg.aihw_flat_raw (load_run_id, category_code, reporting_unit_code);
GO

CREATE TABLE stg.aihw_slice_manifest (
    load_run_id         bigint      NOT NULL,
    category_code       varchar(30) NOT NULL,
    reporting_unit_code varchar(20) NOT NULL,
    rows_expected       int         NOT NULL,
    pages               int         NOT NULL,
    data_version        bigint      NOT NULL,
    CONSTRAINT PK_aihw_slice_manifest PRIMARY KEY (load_run_id, category_code, reporting_unit_code)
);
GO

CREATE TABLE ref.aihw_flag_code (
    flag_code     varchar(10)    NOT NULL,
    flag_kind     varchar(12)    NOT NULL,
    display_value nvarchar(50)   NULL,
    flag_name     nvarchar(200)  NULL,
    footnote      nvarchar(1000) NULL,
    data_version  bigint         NOT NULL,
    CONSTRAINT PK_aihw_flag_code PRIMARY KEY (flag_code, flag_kind),
    CONSTRAINT CK_aihw_flag_code_kind CHECK (flag_kind IN ('Suppression', 'Caveat'))
);
GO

CREATE TABLE ods.aihw_reporting_unit (
    reporting_unit_code varchar(20)    NOT NULL CONSTRAINT PK_aihw_reporting_unit PRIMARY KEY,
    reporting_unit_name nvarchar(300)  NOT NULL,
    unit_type_code      varchar(10)    NOT NULL,
    unit_type_name      nvarchar(100)  NOT NULL,
    state_code          varchar(10)    NULL,
    lhn_code            varchar(20)    NULL,
    lhn_name            nvarchar(300)  NULL,
    phn_code            varchar(20)    NULL,
    phn_name            nvarchar(300)  NULL,
    latitude            decimal(9, 6)  NULL,
    longitude           decimal(9, 6)  NULL,
    is_closed           bit            NOT NULL,
    is_private          bit            NOT NULL,
    alternative_names   nvarchar(1000) NULL,
    data_version        bigint         NOT NULL,
    _loaded_run_id      bigint         NOT NULL,
    _loaded_at_utc      datetime2(3)   NOT NULL CONSTRAINT DF_aihw_reporting_unit_loaded DEFAULT SYSUTCDATETIME()
);
GO

CREATE TABLE ods.aihw_measurement (
    measure_category_code           varchar(30)    NOT NULL,
    measure_code                    varchar(20)    NOT NULL,
    measure_name                    nvarchar(500)  NOT NULL,
    reported_measure_code           varchar(30)    NOT NULL,
    reported_measure_name           nvarchar(300)  NOT NULL,
    reported_measure_category_code  varchar(60)    NOT NULL,
    reported_measure_category_name  nvarchar(300)  NOT NULL,
    reporting_unit_code             varchar(20)    NOT NULL,
    reporting_start_date            date           NOT NULL,
    reporting_end_date              date           NOT NULL,
    value                           decimal(18, 4) NULL,
    lower_value                     decimal(18, 4) NULL,
    upper_value                     decimal(18, 4) NULL,
    units_name                      nvarchar(100)  NULL,
    units_display                   nvarchar(50)   NULL,
    decimal_places                  tinyint        NULL,
    suppression_codes               varchar(100)   NULL,
    caveat_codes                    varchar(100)   NULL,
    caveat_footnotes                nvarchar(2000) NULL,
    peer_group_name                 nvarchar(300)  NULL,
    peer_value                      decimal(18, 4) NULL,
    peer_caveat_codes               varchar(100)   NULL,
    result_status                   varchar(20)    NOT NULL,
    data_version                    bigint         NOT NULL,
    _loaded_run_id                  bigint         NOT NULL,
    _loaded_at_utc                  datetime2(3)   NOT NULL CONSTRAINT DF_aihw_measurement_loaded DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_aihw_measurement PRIMARY KEY
        (measure_code, reported_measure_code, reporting_unit_code, reporting_start_date, reporting_end_date),
    CONSTRAINT CK_aihw_measurement_status CHECK (result_status IN ('Reported', 'ReportedWithCaveat', 'Withheld')),
    CONSTRAINT CK_aihw_measurement_period CHECK (reporting_end_date >= reporting_start_date)
);
GO

CREATE INDEX IX_aihw_measurement_unit ON ods.aihw_measurement (reporting_unit_code, measure_category_code);
GO
