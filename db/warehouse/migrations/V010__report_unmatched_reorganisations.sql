/*
    Review fix: report reorganisation rows that match no hospital.

    A reorganisation whose from_lhn_code matches no hospital in the source (a typo, or AIHW retiring the code)
    used to be ignored without a word, leaving hospitals in their old network with nobody told. The load now
    returns unmatched_reorganisations and the runner raises a Warning alert when it is not zero.

    A new migration rather than an edit to V008, which has already been applied: same procedure, one more
    output column. The full text of etl.usp_load_dim_reporting_unit follows.
*/
CREATE OR ALTER PROCEDURE etl.usp_load_dim_reporting_unit
    @run_id bigint,
    @as_of  date
AS
BEGIN
    SET NOCOUNT, XACT_ABORT ON;
    DECLARE @beginning date = '1900-01-01', @eternity date = '9999-12-31';

    SELECT u.reporting_unit_code, u.unit_type_code, u.reporting_unit_name AS unit_name, u.state_code,
           CASE WHEN u.is_private = 1 THEN 'Private' ELSE 'Public' END AS sector,
           CASE WHEN u.unit_type_code = 'H' THEN COALESCE(r.to_network_code, u.lhn_code)
                WHEN u.unit_type_code = 'LHN' THEN u.reporting_unit_code END AS network_code,
           CASE WHEN u.unit_type_code = 'H' THEN COALESCE(r.to_network_name, u.lhn_name)
                WHEN u.unit_type_code = 'LHN' THEN u.reporting_unit_name END AS network_name,
           CASE WHEN u.unit_type_code = 'H' AND r.from_lhn_code IS NOT NULL THEN 'ref.lhn_reorganisation'
                WHEN u.unit_type_code IN ('H', 'LHN') THEN 'AIHW MyHospitals' END AS network_basis,
           r.effective_date AS reorg_date,
           u.lhn_code AS original_network_code, u.lhn_name AS original_network_name,
           u.phn_code, u.phn_name, u.is_closed, u.latitude, u.longitude
    INTO #src
    FROM ods.aihw_reporting_unit AS u
    LEFT JOIN ref.lhn_reorganisation AS r
           ON u.unit_type_code = 'H' AND r.from_lhn_code = u.lhn_code AND r.effective_date <= @as_of
    WHERE u.unit_type_code IN ('H', 'LHN', 'S', 'NAT');

    IF NOT EXISTS (SELECT 1 FROM #src)
        THROW 50030, 'No hospitals, networks, states or national unit in ods.aihw_reporting_unit.', 1;

    DECLARE @new_units int, @versions_added int, @versions_closed int, @corrected int, @type1 int;

    BEGIN TRANSACTION;

    /* Units seen for the first time. */
    SELECT @new_units = COUNT(*) FROM #src AS s
    WHERE NOT EXISTS (SELECT 1 FROM dw.dim_reporting_unit AS d WHERE d.reporting_unit_code = s.reporting_unit_code);

    INSERT INTO dw.dim_reporting_unit (reporting_unit_code, unit_type_code, unit_name, state_code, sector,
        network_code, network_name, network_basis, phn_code, phn_name, is_closed, latitude, longitude,
        valid_from, valid_to, is_current, _loaded_run_id)
    SELECT s.reporting_unit_code, s.unit_type_code, s.unit_name, s.state_code, s.sector,
           s.original_network_code, s.original_network_name, 'AIHW MyHospitals', s.phn_code, s.phn_name,
           s.is_closed, s.latitude, s.longitude, @beginning, DATEADD(day, -1, s.reorg_date), 0, @run_id
    FROM #src AS s
    WHERE s.reorg_date IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM dw.dim_reporting_unit AS d WHERE d.reporting_unit_code = s.reporting_unit_code)
    UNION ALL
    SELECT s.reporting_unit_code, s.unit_type_code, s.unit_name, s.state_code, s.sector,
           s.network_code, s.network_name, s.network_basis, s.phn_code, s.phn_name,
           s.is_closed, s.latitude, s.longitude, COALESCE(s.reorg_date, @beginning), @eternity, 1, @run_id
    FROM #src AS s
    WHERE NOT EXISTS (SELECT 1 FROM dw.dim_reporting_unit AS d WHERE d.reporting_unit_code = s.reporting_unit_code);
    SET @versions_added = @@ROWCOUNT;

    /* Existing units whose tracked attributes changed. */
    SELECT d.unit_key, s.reporting_unit_code,
           CASE WHEN s.network_code <> d.network_code AND s.reorg_date IS NOT NULL AND s.reorg_date > d.valid_from
                THEN s.reorg_date ELSE @as_of END AS change_date,
           d.valid_from AS old_valid_from,
           s.unit_type_code, s.unit_name, s.state_code, s.sector, s.network_code, s.network_name, s.network_basis,
           s.phn_code, s.phn_name, s.is_closed, s.latitude, s.longitude
    INTO #changed
    FROM #src AS s
    JOIN dw.dim_reporting_unit AS d ON d.reporting_unit_code = s.reporting_unit_code AND d.is_current = 1
    WHERE NOT EXISTS (SELECT s.unit_name, s.sector, s.network_code, s.network_name, s.phn_code, s.phn_name, s.is_closed
                      INTERSECT
                      SELECT d.unit_name, d.sector, d.network_code, d.network_name, d.phn_code, d.phn_name, d.is_closed);

    /* A change dated on or before the current version's start corrects that version in place. */
    UPDATE d SET unit_name = c.unit_name, sector = c.sector, network_code = c.network_code,
                 network_name = c.network_name, network_basis = c.network_basis, phn_code = c.phn_code,
                 phn_name = c.phn_name, is_closed = c.is_closed, _loaded_run_id = @run_id
    FROM dw.dim_reporting_unit AS d JOIN #changed AS c ON c.unit_key = d.unit_key
    WHERE c.change_date <= c.old_valid_from;
    SET @corrected = @@ROWCOUNT;

    /* Otherwise close the current version the day before and start a new one. */
    UPDATE d SET valid_to = DATEADD(day, -1, c.change_date), is_current = 0
    FROM dw.dim_reporting_unit AS d JOIN #changed AS c ON c.unit_key = d.unit_key
    WHERE c.change_date > c.old_valid_from;
    SET @versions_closed = @@ROWCOUNT;

    INSERT INTO dw.dim_reporting_unit (reporting_unit_code, unit_type_code, unit_name, state_code, sector,
        network_code, network_name, network_basis, phn_code, phn_name, is_closed, latitude, longitude,
        valid_from, valid_to, is_current, _loaded_run_id)
    SELECT c.reporting_unit_code, c.unit_type_code, c.unit_name, c.state_code, c.sector, c.network_code,
           c.network_name, c.network_basis, c.phn_code, c.phn_name, c.is_closed, c.latitude, c.longitude,
           c.change_date, @eternity, 1, @run_id
    FROM #changed AS c WHERE c.change_date > c.old_valid_from;
    SET @versions_added = @versions_added + @@ROWCOUNT;

    /* Type 1 attributes, on every version of the unit. */
    UPDATE d SET latitude = s.latitude, longitude = s.longitude
    FROM dw.dim_reporting_unit AS d JOIN #src AS s ON s.reporting_unit_code = d.reporting_unit_code
    WHERE NOT EXISTS (SELECT d.latitude, d.longitude INTERSECT SELECT s.latitude, s.longitude);
    SET @type1 = @@ROWCOUNT;

    COMMIT TRANSACTION;

    SELECT @new_units AS new_units, @versions_added AS versions_added, @versions_closed AS versions_closed,
           @corrected AS versions_corrected, @type1 AS type1_updates,
           (SELECT COUNT(*) FROM ref.lhn_reorganisation AS r
            WHERE NOT EXISTS (SELECT 1 FROM #src AS s WHERE s.unit_type_code = 'H'
                                AND s.original_network_code = r.from_lhn_code)) AS unmatched_reorganisations;
END;
GO
