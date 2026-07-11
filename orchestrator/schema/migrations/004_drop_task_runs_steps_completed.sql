-- Remove unused steps_completed column; workflow trace lives in step_execution_detail.
ALTER TABLE task_runs DROP COLUMN IF EXISTS steps_completed;
