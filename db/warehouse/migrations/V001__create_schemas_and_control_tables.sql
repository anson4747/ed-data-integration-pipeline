/*
    Warehouse layers
      stg   raw landing, one table per source object, loaded as delivered (never edited)
      dq    data quality: rule catalogue, exception log, quarantine
      dw    conformed dimensions and facts
      rpt   reporting views for Power BI
      ref   reference and mapping tables
      etl   pipeline control: runs, steps, watermarks, alerts

    Control tables are created first so every later stage can log against them.
*/

IF SCHEMA_ID(N'stg') IS NULL EXEC (N'CREATE SCHEMA stg AUTHORIZATION dbo;');
IF SCHEMA_ID(N'dq')  IS NULL EXEC (N'CREATE SCHEMA dq  AUTHORIZATION dbo;');
IF SCHEMA_ID(N'dw')  IS NULL EXEC (N'CREATE SCHEMA dw  AUTHORIZATION dbo;');
IF SCHEMA_ID(N'rpt') IS NULL EXEC (N'CREATE SCHEMA rpt AUTHORIZATION dbo;');
IF SCHEMA_ID(N'ref') IS NULL EXEC (N'CREATE SCHEMA ref AUTHORIZATION dbo;');
IF SCHEMA_ID(N'etl') IS NULL EXEC (N'CREATE SCHEMA etl AUTHORIZATION dbo;');
GO

CREATE TABLE etl.pipeline_run (
    run_id          bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_pipeline_run PRIMARY KEY,
    pipeline_name   varchar(100)   NOT NULL,
    environment     varchar(20)    NOT NULL,
    triggered_by    varchar(100)   NOT NULL,
    host_name       nvarchar(128)  NULL,
    started_at_utc  datetime2(3)   NOT NULL CONSTRAINT DF_pipeline_run_started DEFAULT SYSUTCDATETIME(),
    ended_at_utc    datetime2(3)   NULL,
    status          varchar(20)    NOT NULL CONSTRAINT DF_pipeline_run_status DEFAULT 'Running',
    error_message   nvarchar(4000) NULL,
    CONSTRAINT CK_pipeline_run_status CHECK (status IN ('Running', 'Succeeded', 'Failed', 'SucceededWithWarnings'))
);
GO

CREATE TABLE etl.step_run (
    step_run_id     bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_step_run PRIMARY KEY,
    run_id          bigint         NOT NULL CONSTRAINT FK_step_run_run REFERENCES etl.pipeline_run (run_id),
    step_name       varchar(100)   NOT NULL,
    started_at_utc  datetime2(3)   NOT NULL CONSTRAINT DF_step_run_started DEFAULT SYSUTCDATETIME(),
    ended_at_utc    datetime2(3)   NULL,
    status          varchar(20)    NOT NULL CONSTRAINT DF_step_run_status DEFAULT 'Running',
    rows_read       int            NULL,
    rows_inserted   int            NULL,
    rows_updated    int            NULL,
    rows_deleted    int            NULL,
    rows_rejected   int            NULL,
    detail          nvarchar(4000) NULL,
    CONSTRAINT CK_step_run_status CHECK (status IN ('Running', 'Succeeded', 'Failed', 'Skipped', 'SucceededWithWarnings'))
);
GO

CREATE INDEX IX_step_run_run ON etl.step_run (run_id);
GO

/* One row per source. The value is text because each source has its own kind of marker:
   a Change Tracking version (bigint), an API data version (string) or a timestamp. */
CREATE TABLE etl.watermark (
    source_name       varchar(100)  NOT NULL CONSTRAINT PK_watermark PRIMARY KEY,
    watermark_type    varchar(30)   NOT NULL,
    watermark_value   nvarchar(200) NULL,
    updated_at_utc    datetime2(3)  NOT NULL CONSTRAINT DF_watermark_updated DEFAULT SYSUTCDATETIME(),
    updated_by_run_id bigint        NULL CONSTRAINT FK_watermark_run REFERENCES etl.pipeline_run (run_id),
    CONSTRAINT CK_watermark_type CHECK (watermark_type IN ('ChangeTrackingVersion', 'ApiDataVersion', 'Timestamp', 'FileChecksum'))
);
GO

CREATE TABLE etl.alert (
    alert_id            bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_alert PRIMARY KEY,
    run_id              bigint         NULL CONSTRAINT FK_alert_run REFERENCES etl.pipeline_run (run_id),
    severity            varchar(10)    NOT NULL,
    alert_type          varchar(50)    NOT NULL,
    message             nvarchar(2000) NOT NULL,
    raised_at_utc       datetime2(3)   NOT NULL CONSTRAINT DF_alert_raised DEFAULT SYSUTCDATETIME(),
    acknowledged_at_utc datetime2(3)   NULL,
    acknowledged_by     nvarchar(128)  NULL,
    CONSTRAINT CK_alert_severity CHECK (severity IN ('Info', 'Warning', 'Critical'))
);
GO
