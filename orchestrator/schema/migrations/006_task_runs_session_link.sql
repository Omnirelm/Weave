-- Migration to add session_id link column to task_runs table
BEGIN;

ALTER TABLE task_runs
ADD COLUMN IF NOT EXISTS session_id VARCHAR(255) NULL;
CREATE INDEX IF NOT EXISTS ix_task_runs_session_id ON task_runs (session_id);

COMMIT;
