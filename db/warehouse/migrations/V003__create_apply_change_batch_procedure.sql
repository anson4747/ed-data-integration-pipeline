/*
    etl.usp_apply_ct_batch

    Applies one batch of Change Tracking changes (already landed in stg) to the matching
    ods replica table, and advances the watermark, in a single transaction. Either the
    replica and the watermark both move, or neither does, so a failed run can simply be
    rerun: it re-reads the same changes and applies them again with the same result.

    Metadata driven: key and data columns are read from the replica's primary key and
    column list, so one procedure serves every replicated table.

    Deliberately UPDATE + INSERT rather than MERGE: MERGE has a long list of documented
    edge-case bugs in SQL Server, and separate statements give exact row counts per action.

    @load_mode  INCR  apply inserts, updates and deletes from the batch
                FULL  replace the replica with the batch (first load, or the watermark fell
                      behind Change Tracking retention and changes were lost)
*/
CREATE OR ALTER PROCEDURE etl.usp_apply_ct_batch
    @source_table  sysname,
    @load_mode     varchar(4),
    @to_version    bigint,
    @run_id        bigint
AS
BEGIN
    SET NOCOUNT, XACT_ABORT ON;

    IF @load_mode NOT IN ('INCR', 'FULL')
        THROW 50010, 'load_mode must be INCR or FULL.', 1;

    DECLARE @schema  sysname = PARSENAME(@source_table, 2),
            @table   sysname = PARSENAME(@source_table, 1);
    DECLARE @ods     nvarchar(300) = N'ods.' + QUOTENAME(N'emr_' + @schema + N'_' + @table),
            @stg     nvarchar(300) = N'stg.' + QUOTENAME(N'emr_' + @schema + N'_' + @table + N'_ct'),
            @source_name varchar(100) = 'emr.' + @schema + '.' + @table;
    DECLARE @ods_id int = OBJECT_ID(@ods), @stg_id int = OBJECT_ID(@stg);

    IF @schema IS NULL OR @ods_id IS NULL OR @stg_id IS NULL
    BEGIN
        DECLARE @msg nvarchar(400) = CONCAT(N'No replica or stage table for ', @source_table, N'.');
        THROW 50011, @msg, 1;
    END;

    DECLARE @key  TABLE (name sysname NOT NULL, ord int NOT NULL);
    DECLARE @col  TABLE (name sysname NOT NULL, ord int NOT NULL, is_key bit NOT NULL);

    INSERT INTO @key (name, ord)
    SELECT c.name, ic.key_ordinal
    FROM sys.indexes AS i
    JOIN sys.index_columns AS ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
    JOIN sys.columns AS c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
    WHERE i.object_id = @ods_id AND i.is_primary_key = 1;

    INSERT INTO @col (name, ord, is_key)
    SELECT c.name, c.column_id, CASE WHEN k.name IS NULL THEN 0 ELSE 1 END
    FROM sys.columns AS c
    LEFT JOIN @key AS k ON k.name = c.name
    WHERE c.object_id = @ods_id AND c.name NOT LIKE N'[_]%';

    DECLARE @join     nvarchar(max) = (SELECT STRING_AGG(CAST(N't.' + QUOTENAME(name) + N' = s.' + QUOTENAME(name) AS nvarchar(max)), N' AND ') WITHIN GROUP (ORDER BY ord) FROM @key),
            @cols     nvarchar(max) = (SELECT STRING_AGG(CAST(QUOTENAME(name) AS nvarchar(max)), N', ') WITHIN GROUP (ORDER BY ord) FROM @col),
            @s_cols   nvarchar(max) = (SELECT STRING_AGG(CAST(N's.' + QUOTENAME(name) AS nvarchar(max)), N', ') WITHIN GROUP (ORDER BY ord) FROM @col),
            @t_cols   nvarchar(max) = (SELECT STRING_AGG(CAST(N't.' + QUOTENAME(name) AS nvarchar(max)), N', ') WITHIN GROUP (ORDER BY ord) FROM @col),
            @set_list nvarchar(max) = (SELECT STRING_AGG(CAST(N't.' + QUOTENAME(name) + N' = s.' + QUOTENAME(name) AS nvarchar(max)), N', ') WITHIN GROUP (ORDER BY ord) FROM @col WHERE is_key = 0);

    DECLARE @deleted int = 0, @updated int = 0, @inserted int = 0, @batch_rows int = 0, @sql nvarchar(max);

    BEGIN TRANSACTION;

        SET @sql = N'SELECT @n = COUNT(*) FROM ' + @stg + N';';
        EXEC sys.sp_executesql @sql, N'@n int OUTPUT', @n = @batch_rows OUTPUT;

        IF @load_mode = 'FULL'
        BEGIN
            SET @sql = N'DELETE FROM ' + @ods + N'; SET @n = @@ROWCOUNT;';
            EXEC sys.sp_executesql @sql, N'@n int OUTPUT', @n = @deleted OUTPUT;

            SET @sql = N'INSERT INTO ' + @ods + N' (' + @cols + N', _ct_version) '
                     + N'SELECT ' + @s_cols + N', @v FROM ' + @stg + N' AS s WHERE s.sys_change_operation <> ''D''; '
                     + N'SET @n = @@ROWCOUNT;';
            EXEC sys.sp_executesql @sql, N'@v bigint, @n int OUTPUT', @v = @to_version, @n = @inserted OUTPUT;
        END
        ELSE
        BEGIN
            SET @sql = N'DELETE t FROM ' + @ods + N' AS t JOIN ' + @stg + N' AS s ON ' + @join
                     + N' WHERE s.sys_change_operation = ''D''; SET @n = @@ROWCOUNT;';
            EXEC sys.sp_executesql @sql, N'@n int OUTPUT', @n = @deleted OUTPUT;

            /* Update only rows whose values actually differ. INTERSECT compares NULLs as equal,
               which a column-by-column <> would not. */
            IF @set_list IS NOT NULL
            BEGIN
                SET @sql = N'UPDATE t SET ' + @set_list
                         + N', t._ct_version = s.sys_change_version, t._replicated_at_utc = SYSUTCDATETIME() '
                         + N'FROM ' + @ods + N' AS t JOIN ' + @stg + N' AS s ON ' + @join
                         + N' WHERE s.sys_change_operation IN (''I'', ''U'') '
                         + N'AND NOT EXISTS (SELECT ' + @t_cols + N' INTERSECT SELECT ' + @s_cols + N'); '
                         + N'SET @n = @@ROWCOUNT;';
                EXEC sys.sp_executesql @sql, N'@n int OUTPUT', @n = @updated OUTPUT;
            END;

            SET @sql = N'INSERT INTO ' + @ods + N' (' + @cols + N', _ct_version) '
                     + N'SELECT ' + @s_cols + N', s.sys_change_version FROM ' + @stg + N' AS s '
                     + N'WHERE s.sys_change_operation IN (''I'', ''U'') '
                     + N'AND NOT EXISTS (SELECT 1 FROM ' + @ods + N' AS t WHERE ' + @join + N'); '
                     + N'SET @n = @@ROWCOUNT;';
            EXEC sys.sp_executesql @sql, N'@n int OUTPUT', @n = @inserted OUTPUT;
        END;

        UPDATE etl.watermark
        SET watermark_value = CAST(@to_version AS nvarchar(200)),
            updated_at_utc = SYSUTCDATETIME(),
            updated_by_run_id = @run_id
        WHERE source_name = @source_name;

        IF @@ROWCOUNT = 0
            INSERT INTO etl.watermark (source_name, watermark_type, watermark_value, updated_by_run_id)
            VALUES (@source_name, 'ChangeTrackingVersion', CAST(@to_version AS nvarchar(200)), @run_id);

    COMMIT;

    SELECT @load_mode AS load_mode, @batch_rows AS rows_read, @inserted AS rows_inserted,
           @updated AS rows_updated, @deleted AS rows_deleted, @to_version AS watermark;
END;
GO
