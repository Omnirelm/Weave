-- Add workflow_id to task_runs for workflow execution tracking.
ALTER TABLE task_runs ADD COLUMN IF NOT EXISTS workflow_id VARCHAR(128);
CREATE INDEX IF NOT EXISTS ix_task_runs_workflow_id ON task_runs (tenant_slug, workflow_id);
