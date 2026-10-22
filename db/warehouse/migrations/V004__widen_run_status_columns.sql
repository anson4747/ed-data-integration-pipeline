/*
    Widen etl.pipeline_run.status and etl.step_run.status from varchar(20) to varchar(30).
    'SucceededWithWarnings' is 21 characters and was rejected on the first warning.

    Shipped as a new migration rather than an edit to V001, because V001 has already been
    applied. The check and default constraints depend on the column, so they are dropped and
    recreated around the ALTER.
*/

ALTER TABLE etl.pipeline_run DROP CONSTRAINT CK_pipeline_run_status;
ALTER TABLE etl.pipeline_run DROP CONSTRAINT DF_pipeline_run_status;
ALTER TABLE etl.pipeline_run ALTER COLUMN status varchar(30) NOT NULL;
ALTER TABLE etl.pipeline_run ADD CONSTRAINT DF_pipeline_run_status DEFAULT 'Running' FOR status;
ALTER TABLE etl.pipeline_run ADD CONSTRAINT CK_pipeline_run_status
    CHECK (status IN ('Running', 'Succeeded', 'Failed', 'SucceededWithWarnings'));

ALTER TABLE etl.step_run DROP CONSTRAINT CK_step_run_status;
ALTER TABLE etl.step_run DROP CONSTRAINT DF_step_run_status;
ALTER TABLE etl.step_run ALTER COLUMN status varchar(30) NOT NULL;
ALTER TABLE etl.step_run ADD CONSTRAINT DF_step_run_status DEFAULT 'Running' FOR status;
ALTER TABLE etl.step_run ADD CONSTRAINT CK_step_run_status
    CHECK (status IN ('Running', 'Succeeded', 'Failed', 'Skipped', 'SucceededWithWarnings'));
GO
