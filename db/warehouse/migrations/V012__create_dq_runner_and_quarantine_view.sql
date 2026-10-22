/*
    dq.usp_run_rule

    Runs one rule and reconciles its findings with dq.exception in one transaction:
      new        found now, never seen before            -> inserted as Open
      persisting found now, already Open                  -> last_seen_run_id moves
      reopened   found now, was Resolved                  -> back to Open, resolution cleared
      resolved   Open before, not found now               -> Resolved with the run and time

    Safe to rerun: a second run on unchanged data inserts and resolves nothing.
    The rule's SELECT runs before the transaction starts, so a rule with a syntax error or a missing table fails
    loudly (the pipeline runner turns that into a Critical alert) and leaves the exception log as it was.

      50040  unknown or inactive rule
*/
CREATE OR ALTER PROCEDURE dq.usp_run_rule
    @rule_code varchar(40),
    @run_id    bigint
AS
BEGIN
    SET NOCOUNT, XACT_ABORT ON;

    DECLARE @sql nvarchar(max) = (SELECT check_sql FROM dq.rule WHERE rule_code = @rule_code AND is_active = 1);
    IF @sql IS NULL
        THROW 50040, 'Unknown or inactive data quality rule.', 1;

    CREATE TABLE #raw (stay_id int NULL, entity_key nvarchar(100) NOT NULL, detail nvarchar(500) NULL);
    INSERT INTO #raw EXEC sys.sp_executesql @sql;

    /* One finding per entity, whatever the rule returned. */
    SELECT entity_key, MIN(stay_id) AS stay_id, MIN(detail) AS detail
    INTO #found FROM #raw GROUP BY entity_key;

    DECLARE @new int, @reopened int, @resolved int, @persisting int;

    BEGIN TRANSACTION;

    SELECT @reopened = COUNT(*) FROM dq.exception AS x JOIN #found AS f ON f.entity_key = x.entity_key
    WHERE x.rule_code = @rule_code AND x.status = 'Resolved';

    SELECT @persisting = COUNT(*) FROM dq.exception AS x JOIN #found AS f ON f.entity_key = x.entity_key
    WHERE x.rule_code = @rule_code AND x.status = 'Open';

    UPDATE x SET status = 'Open', last_seen_run_id = @run_id, resolved_run_id = NULL, resolved_utc = NULL,
                 stay_id = f.stay_id, detail = f.detail
    FROM dq.exception AS x JOIN #found AS f ON f.entity_key = x.entity_key
    WHERE x.rule_code = @rule_code;

    INSERT INTO dq.exception (rule_code, entity_key, stay_id, detail, status, first_seen_run_id, last_seen_run_id)
    SELECT @rule_code, f.entity_key, f.stay_id, f.detail, 'Open', @run_id, @run_id
    FROM #found AS f
    WHERE NOT EXISTS (SELECT 1 FROM dq.exception AS x WHERE x.rule_code = @rule_code AND x.entity_key = f.entity_key);
    SET @new = @@ROWCOUNT;

    UPDATE x SET status = 'Resolved', resolved_run_id = @run_id, resolved_utc = SYSUTCDATETIME()
    FROM dq.exception AS x
    WHERE x.rule_code = @rule_code AND x.status = 'Open'
      AND NOT EXISTS (SELECT 1 FROM #found AS f WHERE f.entity_key = x.entity_key);
    SET @resolved = @@ROWCOUNT;

    COMMIT TRANSACTION;

    SELECT (SELECT COUNT(*) FROM #found) AS found, @new AS new_exceptions, @reopened AS reopened,
           @resolved AS resolved, @persisting AS persisting;
END;
GO

/* A stay is quarantined while any Error rule has an Open exception against it. */
CREATE OR ALTER VIEW dq.v_quarantined_stay AS
SELECT x.stay_id, STRING_AGG(x.rule_code, ', ') WITHIN GROUP (ORDER BY x.rule_code) AS reasons, COUNT(*) AS open_errors
FROM dq.exception AS x JOIN dq.rule AS r ON r.rule_code = x.rule_code
WHERE x.status = 'Open' AND r.severity = 'Error' AND x.stay_id IS NOT NULL
GROUP BY x.stay_id;
GO
