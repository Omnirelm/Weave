-- Migrate from tenant_skills to tenant_agents.
-- Prerequisite: clear or drop tenant_skills data before applying.
--
-- Apply:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f orchestrator/schema/migrations/001_skills_to_agents.sql

BEGIN;

DROP TABLE IF EXISTS tenant_skills;

CREATE TABLE IF NOT EXISTS tenant_agents (
    tenant_slug  VARCHAR(64)   NOT NULL REFERENCES tenants (slug) ON DELETE CASCADE,
    agent_id     VARCHAR(128)  NOT NULL,
    name         VARCHAR(255)  NOT NULL,
    model        VARCHAR(128)  NOT NULL DEFAULT 'gemini/gemini-3.5-flash',
    definition   JSONB         NOT NULL,
    created_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_slug, agent_id)
);

CREATE INDEX IF NOT EXISTS ix_tenant_agents_tenant_slug ON tenant_agents (tenant_slug);

ALTER TABLE task_runs RENAME COLUMN skill_id TO agent_id;

UPDATE plan_quotas SET operation = 'agent_max' WHERE operation = 'skill_max';

COMMIT;
