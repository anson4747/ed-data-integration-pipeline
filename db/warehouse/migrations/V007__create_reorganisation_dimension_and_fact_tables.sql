/*
    Stage 3 tables.

    ref.lhn_reorganisation     dated network mergers that the source data does not carry. AIHW still lists
                               The Alfred under "Alfred Health (Vic)" months after the Bayside Health merger
                               of 1 January 2026, so the merger is curated here, with its source.
    dw.dim_reporting_unit      Type 2 slowly changing dimension for hospitals, networks, states and national.
                               A row is one version of a unit, valid from valid_from to valid_to inclusive.
                               valid_to is 9999-12-31 for the current version. valid_from 1900-01-01 means
                               "start of recorded history", not a real founding date.
    dw.dim_measure             Type 1: measures are described by AIHW, the latest description wins.
    dw.fact_ed_measure         One row per unit, measure, reported measure and period. unit_key is the version
                               of the unit that was valid at the end of the reporting period.
*/

CREATE TABLE ref.lhn_reorganisation (
    from_lhn_code    varchar(20)    NOT NULL CONSTRAINT PK_lhn_reorganisation PRIMARY KEY,
    from_lhn_name    nvarchar(300)  NOT NULL,
    to_network_code  varchar(20)    NOT NULL,
    to_network_name  nvarchar(300)  NOT NULL,
    effective_date   date           NOT NULL,
    source_url       nvarchar(500)  NOT NULL,
    source_note      nvarchar(500)  NULL
);
GO

/* One row per merging service. The Victorian Government announced on 29 August 2025 that Alfred Health,
   Bass Coast Health, Gippsland Southern Health Service, Kooweerup Regional Health Service and Peninsula
   Health would merge voluntarily as Bayside Health from 1 January 2026. Hospitals keep their names. */
INSERT INTO ref.lhn_reorganisation (from_lhn_code, from_lhn_name, to_network_code, to_network_name, effective_date, source_url, source_note)
VALUES
 ('LHN268', N'Alfred Health (Vic)',                  'BAYSIDE', N'Bayside Health', '2026-01-01',
  N'https://www.premier.vic.gov.au/bayside-health-voluntary-merger-strengthen-care', N'Voluntary merger announced 29 August 2025'),
 ('LHN270', N'Peninsula Health (Vic)',               'BAYSIDE', N'Bayside Health', '2026-01-01',
  N'https://www.premier.vic.gov.au/bayside-health-voluntary-merger-strengthen-care', N'Voluntary merger announced 29 August 2025'),
 ('LHN253', N'Bass Coast Regional Health',           'BAYSIDE', N'Bayside Health', '2026-01-01',
  N'https://www.premier.vic.gov.au/bayside-health-voluntary-merger-strengthen-care', N'Voluntary merger announced 29 August 2025'),
 ('LHN254', N'Gippsland Southern Health Service',    'BAYSIDE', N'Bayside Health', '2026-01-01',
  N'https://www.premier.vic.gov.au/bayside-health-voluntary-merger-strengthen-care', N'Voluntary merger announced 29 August 2025'),
 ('LHN271', N'Kooweerup Regional Health Service',    'BAYSIDE', N'Bayside Health', '2026-01-01',
  N'https://www.premier.vic.gov.au/bayside-health-voluntary-merger-strengthen-care', N'Voluntary merger announced 29 August 2025');
GO

CREATE TABLE dw.dim_reporting_unit (
    unit_key             int IDENTITY(1,1) NOT NULL CONSTRAINT PK_dim_reporting_unit PRIMARY KEY,
    reporting_unit_code  varchar(20)   NOT NULL,
    unit_type_code       varchar(10)   NOT NULL,
    unit_name            nvarchar(300) NOT NULL,
    state_code           varchar(10)   NULL,
    sector               varchar(10)   NOT NULL,
    network_code         varchar(20)   NULL,
    network_name         nvarchar(300) NULL,
    network_basis        varchar(30)   NULL,
    phn_code             varchar(20)   NULL,
    phn_name             nvarchar(300) NULL,
    is_closed            bit           NOT NULL,
    latitude             decimal(9, 6) NULL,
    longitude            decimal(9, 6) NULL,
    valid_from           date          NOT NULL,
    valid_to             date          NOT NULL,
    is_current           bit           NOT NULL,
    _loaded_run_id       bigint        NOT NULL,
    _loaded_at_utc       datetime2(3)  NOT NULL CONSTRAINT DF_dim_reporting_unit_loaded DEFAULT SYSUTCDATETIME(),
    CONSTRAINT UQ_dim_reporting_unit_version UNIQUE (reporting_unit_code, valid_from),
    CONSTRAINT CK_dim_reporting_unit_range CHECK (valid_to >= valid_from),
    CONSTRAINT CK_dim_reporting_unit_current CHECK ((is_current = 1 AND valid_to = '9999-12-31') OR (is_current = 0 AND valid_to < '9999-12-31')),
    CONSTRAINT CK_dim_reporting_unit_basis CHECK (network_basis IN ('AIHW MyHospitals', 'ref.lhn_reorganisation'))
);
GO

/* Exactly one current version per unit. */
CREATE UNIQUE INDEX UX_dim_reporting_unit_current ON dw.dim_reporting_unit (reporting_unit_code) WHERE is_current = 1;
GO

CREATE TABLE dw.dim_measure (
    measure_code          varchar(20)   NOT NULL CONSTRAINT PK_dim_measure PRIMARY KEY,
    measure_name          nvarchar(500) NOT NULL,
    measure_category_code varchar(30)   NOT NULL,
    units_name            nvarchar(100) NULL,
    units_display         nvarchar(50)  NULL,
    decimal_places        tinyint       NULL,
    _loaded_run_id        bigint        NOT NULL
);
GO

CREATE TABLE dw.fact_ed_measure (
    measure_code          varchar(20)    NOT NULL CONSTRAINT FK_fact_ed_measure_measure REFERENCES dw.dim_measure (measure_code),
    reported_measure_code varchar(30)    NOT NULL,
    reported_measure_name nvarchar(300)  NOT NULL,
    reporting_unit_code   varchar(20)    NOT NULL,
    unit_key              int            NOT NULL CONSTRAINT FK_fact_ed_measure_unit REFERENCES dw.dim_reporting_unit (unit_key),
    reporting_start_date  date           NOT NULL,
    reporting_end_date    date           NOT NULL,
    financial_year        char(7)        NULL,
    value                 decimal(18, 4) NULL,
    lower_value           decimal(18, 4) NULL,
    upper_value           decimal(18, 4) NULL,
    result_status         varchar(20)    NOT NULL,
    suppression_codes     varchar(100)   NULL,
    caveat_codes          varchar(100)   NULL,
    peer_group_name       nvarchar(300)  NULL,
    peer_value            decimal(18, 4) NULL,
    data_version          bigint         NOT NULL,
    _loaded_run_id        bigint         NOT NULL,
    CONSTRAINT PK_fact_ed_measure PRIMARY KEY
        (measure_code, reported_measure_code, reporting_unit_code, reporting_start_date, reporting_end_date)
);
GO

CREATE INDEX IX_fact_ed_measure_unit ON dw.fact_ed_measure (unit_key);
GO
