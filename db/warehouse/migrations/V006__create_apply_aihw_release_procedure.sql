/*
    etl.usp_apply_aihw_release

    Applies the slices landed by one run (stg.aihw_flat_raw plus stg.aihw_slice_manifest) to
    ods.aihw_measurement and moves the release marker, in one transaction.

    Checks that run before anything in ods is touched. Any failure raises and leaves ods as it was:
      50020  the run landed no slices
      50021  a slice landed a different number of rows than the API said it had
      50022  the same natural key appears twice (the API can return duplicate rows; a clean
             slice never does, so a duplicate means the extract is not trustworthy)
      50023  a row belongs to a different category or reporting unit than the request asked for

    Then, per slice, the stored rows are replaced by the new ones. A release is a snapshot, so
    replace is the correct semantics, and it also removes rows AIHW has withdrawn. The counts
    returned describe the difference between the old and new release:
      rows_inserted  keys not seen before
      rows_updated   keys whose value, bounds, flags or peer figure changed
      rows_deleted   keys that were in the old release and are gone from the new one

    result_status decodes what the figure means:
      Reported            a value with no caveat
      ReportedWithCaveat  a value with an interpret-with-caution caveat (for example X42)
      Withheld            no value: suppressed or not published (for example X01 "<5", X40 "NP")
*/
CREATE OR ALTER PROCEDURE etl.usp_apply_aihw_release
    @run_id       bigint,
    @data_version bigint
AS
BEGIN
    SET NOCOUNT, XACT_ABORT ON;

    IF NOT EXISTS (SELECT 1 FROM stg.aihw_slice_manifest WHERE load_run_id = @run_id)
        THROW 50020, 'Run landed no AIHW slices.', 1;

    IF EXISTS (
        SELECT 1
        FROM stg.aihw_slice_manifest AS m
        CROSS APPLY (SELECT COUNT_BIG(*) AS landed FROM stg.aihw_flat_raw AS r
                     WHERE r.load_run_id = m.load_run_id AND r.category_code = m.category_code
                       AND r.reporting_unit_code = m.reporting_unit_code) AS l
        WHERE m.load_run_id = @run_id AND l.landed <> m.rows_expected)
        THROW 50021, 'A slice landed a different number of rows than the API reported.', 1;

    CREATE TABLE #shred (
        slice_category varchar(30) NOT NULL, slice_unit varchar(20) NOT NULL,
        measure_category_code varchar(30) NOT NULL, measure_code varchar(20) NOT NULL,
        measure_name nvarchar(500) NOT NULL, reported_measure_code varchar(30) NOT NULL,
        reported_measure_name nvarchar(300) NOT NULL, reported_measure_category_code varchar(60) NOT NULL,
        reported_measure_category_name nvarchar(300) NOT NULL, reporting_unit_code varchar(20) NOT NULL,
        reporting_start_date date NOT NULL, reporting_end_date date NOT NULL,
        value decimal(18, 4) NULL, lower_value decimal(18, 4) NULL, upper_value decimal(18, 4) NULL,
        units_name nvarchar(100) NULL, units_display nvarchar(50) NULL, decimal_places tinyint NULL,
        suppression_codes varchar(100) NULL, caveat_codes varchar(100) NULL, caveat_footnotes nvarchar(2000) NULL,
        peer_group_name nvarchar(300) NULL, peer_value decimal(18, 4) NULL, peer_caveat_codes varchar(100) NULL
    );

    INSERT INTO #shred
    SELECT r.category_code, r.reporting_unit_code,
           j.measure_category_code, j.measure_code, j.measure_name, j.reported_measure_code, j.reported_measure_name,
           j.reported_measure_category_code, j.reported_measure_category_name, j.reporting_unit_code,
           j.reporting_start_date, j.reporting_end_date, j.value, j.lower_value, j.upper_value,
           j.units_name, j.units_display, j.decimal_places, j.suppression_codes, j.caveat_codes, j.caveat_footnotes,
           j.peer_group_name, j.peer_value, j.peer_caveat_codes
    FROM stg.aihw_flat_raw AS r
    CROSS APPLY OPENJSON(r.row_json) WITH (
        measure_category_code          varchar(30)    '$.measure_category_code',
        measure_code                   varchar(20)    '$.measure_code',
        measure_name                   nvarchar(500)  '$.measure_name',
        reported_measure_code          varchar(30)    '$.reported_measure_code',
        reported_measure_name          nvarchar(300)  '$.reported_measure_name',
        reported_measure_category_code varchar(60)    '$.reported_measure_category_code',
        reported_measure_category_name nvarchar(300)  '$.reported_measure_category_name',
        reporting_unit_code            varchar(20)    '$.reporting_unit_code',
        reporting_start_date           date           '$.reporting_start_date',
        reporting_end_date             date           '$.reporting_end_date',
        value                          decimal(18, 4) '$.value',
        lower_value                    decimal(18, 4) '$.lower_value',
        upper_value                    decimal(18, 4) '$.upper_value',
        units_name                     nvarchar(100)  '$.units_name',
        units_display                  nvarchar(50)   '$.units_display',
        decimal_places                 tinyint        '$.decimal_places',
        suppression_codes              varchar(100)   '$.suppression_codes',
        caveat_codes                   varchar(100)   '$.caveat_codes',
        caveat_footnotes               nvarchar(2000) '$.caveat_footnotes',
        peer_group_name                nvarchar(300)  '$.peer_group_name',
        peer_value                     decimal(18, 4) '$.peer_value',
        peer_caveat_codes              varchar(100)   '$.peer_caveat_codes'
    ) AS j
    WHERE r.load_run_id = @run_id;

    IF EXISTS (SELECT 1 FROM #shred WHERE measure_category_code <> slice_category OR reporting_unit_code <> slice_unit)
        THROW 50023, 'A row belongs to a different category or reporting unit than the request asked for.', 1;

    IF EXISTS (SELECT 1 FROM #shred
               GROUP BY measure_code, reported_measure_code, reporting_unit_code, reporting_start_date, reporting_end_date
               HAVING COUNT(*) > 1)
        THROW 50022, 'Duplicate natural keys in the landed AIHW rows.', 1;

    DECLARE @inserted int, @updated int, @deleted int;

    BEGIN TRANSACTION;

    SELECT @inserted = COUNT(*) FROM #shred AS s
    WHERE NOT EXISTS (SELECT 1 FROM ods.aihw_measurement AS o
                      WHERE o.measure_code = s.measure_code AND o.reported_measure_code = s.reported_measure_code
                        AND o.reporting_unit_code = s.reporting_unit_code
                        AND o.reporting_start_date = s.reporting_start_date AND o.reporting_end_date = s.reporting_end_date);

    SELECT @updated = COUNT(*) FROM #shred AS s
    JOIN ods.aihw_measurement AS o
      ON o.measure_code = s.measure_code AND o.reported_measure_code = s.reported_measure_code
     AND o.reporting_unit_code = s.reporting_unit_code
     AND o.reporting_start_date = s.reporting_start_date AND o.reporting_end_date = s.reporting_end_date
    WHERE NOT EXISTS (SELECT s.value, s.lower_value, s.upper_value, s.suppression_codes, s.caveat_codes, s.peer_value
                      INTERSECT
                      SELECT o.value, o.lower_value, o.upper_value, o.suppression_codes, o.caveat_codes, o.peer_value);

    SELECT @deleted = COUNT(*) FROM ods.aihw_measurement AS o
    JOIN stg.aihw_slice_manifest AS m
      ON m.load_run_id = @run_id AND m.category_code = o.measure_category_code AND m.reporting_unit_code = o.reporting_unit_code
    WHERE NOT EXISTS (SELECT 1 FROM #shred AS s
                      WHERE s.measure_code = o.measure_code AND s.reported_measure_code = o.reported_measure_code
                        AND s.reporting_unit_code = o.reporting_unit_code
                        AND s.reporting_start_date = o.reporting_start_date AND s.reporting_end_date = o.reporting_end_date);

    DELETE o FROM ods.aihw_measurement AS o
    JOIN stg.aihw_slice_manifest AS m
      ON m.load_run_id = @run_id AND m.category_code = o.measure_category_code AND m.reporting_unit_code = o.reporting_unit_code;

    INSERT INTO ods.aihw_measurement (
        measure_category_code, measure_code, measure_name, reported_measure_code, reported_measure_name,
        reported_measure_category_code, reported_measure_category_name, reporting_unit_code,
        reporting_start_date, reporting_end_date, value, lower_value, upper_value, units_name, units_display,
        decimal_places, suppression_codes, caveat_codes, caveat_footnotes, peer_group_name, peer_value,
        peer_caveat_codes, result_status, data_version, _loaded_run_id)
    SELECT measure_category_code, measure_code, measure_name, reported_measure_code, reported_measure_name,
           reported_measure_category_code, reported_measure_category_name, reporting_unit_code,
           reporting_start_date, reporting_end_date, value, lower_value, upper_value, units_name, units_display,
           decimal_places, suppression_codes, caveat_codes, caveat_footnotes, peer_group_name, peer_value,
           peer_caveat_codes,
           CASE WHEN value IS NULL THEN 'Withheld'
                WHEN caveat_codes IS NOT NULL THEN 'ReportedWithCaveat'
                ELSE 'Reported' END,
           @data_version, @run_id
    FROM #shred;

    UPDATE etl.watermark
       SET watermark_value = CAST(@data_version AS nvarchar(200)), updated_at_utc = SYSUTCDATETIME(),
           updated_by_run_id = @run_id
     WHERE source_name = 'aihw.myhospitals';
    IF @@ROWCOUNT = 0
        INSERT INTO etl.watermark (source_name, watermark_type, watermark_value, updated_by_run_id)
        VALUES ('aihw.myhospitals', 'ApiDataVersion', CAST(@data_version AS nvarchar(200)), @run_id);

    COMMIT TRANSACTION;

    -- Keep the latest landing for troubleshooting; older landings are no longer needed.
    DELETE FROM stg.aihw_flat_raw WHERE load_run_id < @run_id;
    DELETE FROM stg.aihw_slice_manifest WHERE load_run_id < @run_id;

    SELECT (SELECT COUNT(*) FROM #shred) AS rows_landed, @inserted AS rows_inserted,
           @updated AS rows_updated, @deleted AS rows_deleted;
END;
GO
