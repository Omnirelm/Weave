-- Tenant-defined workflows (full WorkflowDef in JSONB).
-- Apply after init.sql / 001_skills_to_agents.sql.

BEGIN;

CREATE TABLE IF NOT EXISTS tenant_workflows (
    tenant_slug    VARCHAR(64)   NOT NULL REFERENCES tenants (slug) ON DELETE CASCADE,
    workflow_id    VARCHAR(128)  NOT NULL,
    name           VARCHAR(255)  NOT NULL,
    definition     JSONB         NOT NULL,
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_slug, workflow_id)
);

CREATE INDEX IF NOT EXISTS ix_tenant_workflows_tenant_slug
    ON tenant_workflows (tenant_slug);

INSERT INTO plan_quotas (plan_slug, operation, limit_value, period) VALUES
    ('starter', 'workflow_max', 5, 'none'),
    ('essential', 'workflow_max', 50, 'none'),
    ('pro', 'workflow_max', 200, 'none')
ON CONFLICT (plan_slug, operation) DO NOTHING;

COMMIT;
