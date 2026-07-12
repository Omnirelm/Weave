-- Rename request_input to request_context.
ALTER TABLE task_runs RENAME COLUMN request_input TO request_context;
