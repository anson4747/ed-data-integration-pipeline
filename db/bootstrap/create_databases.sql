/*
    Bootstrap: create the two databases and set the options that cannot change inside a
    migration transaction. Safe to run any number of times.

    $(SourceDb)     mock hospital source system (EMR / ED tracking). Change Tracking is on,
                    because the warehouse syncs from it incrementally.
    $(WarehouseDb)  the analytics warehouse.

    Snapshot isolation is enabled on the source so the extract reads a consistent version
    of the data while the source keeps changing (the pattern Microsoft documents for
    Change Tracking consumers).
*/

IF DB_ID(N'$(SourceDb)') IS NULL
    EXEC (N'CREATE DATABASE [$(SourceDb)];');
GO

IF DB_ID(N'$(WarehouseDb)') IS NULL
    EXEC (N'CREATE DATABASE [$(WarehouseDb)];');
GO

IF (SELECT snapshot_isolation_state FROM sys.databases WHERE name = N'$(SourceDb)') = 0
    EXEC (N'ALTER DATABASE [$(SourceDb)] SET ALLOW_SNAPSHOT_ISOLATION ON;');
GO

IF NOT EXISTS (SELECT 1 FROM sys.change_tracking_databases WHERE database_id = DB_ID(N'$(SourceDb)'))
    EXEC (N'ALTER DATABASE [$(SourceDb)] SET CHANGE_TRACKING = ON (CHANGE_RETENTION = 7 DAYS, AUTO_CLEANUP = ON);');
GO

/* Warehouse reads use row versioning so reports never block loads. */
IF (SELECT is_read_committed_snapshot_on FROM sys.databases WHERE name = N'$(WarehouseDb)') = 0
    EXEC (N'ALTER DATABASE [$(WarehouseDb)] SET READ_COMMITTED_SNAPSHOT ON WITH ROLLBACK IMMEDIATE;');
GO
