/*
    Source system (mock EMR). Schemas mirror the two MIMIC-IV modules loaded in Stage 1:
      hosp  patient administration and hospital records
      ed    emergency department tracking
    admin holds the replay bookkeeping that simulates records arriving over time.
*/

IF SCHEMA_ID(N'hosp') IS NULL EXEC (N'CREATE SCHEMA hosp AUTHORIZATION dbo;');
IF SCHEMA_ID(N'ed') IS NULL EXEC (N'CREATE SCHEMA ed AUTHORIZATION dbo;');
IF SCHEMA_ID(N'admin') IS NULL EXEC (N'CREATE SCHEMA admin AUTHORIZATION dbo;');
GO
