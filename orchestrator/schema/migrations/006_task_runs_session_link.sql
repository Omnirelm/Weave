-- Migration to add session_id link column to task_runs table
BEGIN;

ALTER TABLE task_runs
ADD COLUMN IF NOT EXISTS session_id VARCHAR(255) NULL;

COMMIT;
