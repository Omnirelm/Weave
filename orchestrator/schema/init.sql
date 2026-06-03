-- Manual schema for the orchestrator service.
--
-- This file is the canonical SQL view of the schema. The application reads/writes
-- through SQLAlchemy ORM models in src/storage/models/, but the database itself
-- is managed manually: apply this file (and any follow-up *.sql) by hand.
--
-- Apply (idempotent: uses IF NOT EXISTS where possible):
--   psql "postgresql://orchestrator:orchestrator@localhost:5432/orchestrator" \
--        -v ON_ERROR_STOP=1 -f orchestrator/schema/init.sql
--
-- Keep this file in sync with src/storage/models/*.py whenever you edit a model.

BEGIN;

-- Plans (subscription tiers; quotas reference these).
CREATE TABLE IF NOT EXISTS plans (
    slug           VARCHAR(64)   PRIMARY KEY,
    display_name   VARCHAR(255)  NOT NULL,
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ   NOT NULL DEFAULT now()
);

INSERT INTO plans (slug, display_name) VALUES
    ('starter', 'Starter'),
    ('essential', 'Essential'),
    ('pro', 'Pro')
ON CONFLICT (slug) DO NOTHING;

-- Per-plan limits per logical operation (task_run, skill_max, ...).
CREATE TABLE IF NOT EXISTS plan_quotas (
    plan_slug    VARCHAR(64)   NOT NULL REFERENCES plans (slug) ON DELETE CASCADE,
    operation    VARCHAR(64)   NOT NULL,
    limit_value  INTEGER       NOT NULL CHECK (limit_value >= 0),
    period       VARCHAR(32)   NOT NULL,
    created_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT uq_plan_quotas_plan_operation UNIQUE (plan_slug, operation)
);

CREATE INDEX IF NOT EXISTS ix_plan_quotas_plan_slug ON plan_quotas (plan_slug);

INSERT INTO plan_quotas (plan_slug, operation, limit_value, period) VALUES
    ('starter', 'task_run', 20, 'monthly'),
    ('starter', 'skill_max', 20, 'none'),
    ('essential', 'task_run', 500, 'monthly'),
    ('essential', 'skill_max', 100, 'none'),
    ('pro', 'task_run', 10000, 'monthly'),
    ('pro', 'skill_max', 500, 'none')
ON CONFLICT (plan_slug, operation) DO NOTHING;

-- Tenants
-- Primary key is the slug (human-readable, URL-safe identifier).
CREATE TABLE IF NOT EXISTS tenants (
    slug          VARCHAR(64)  PRIMARY KEY,
    display_name  VARCHAR(255) NOT NULL,
    plan_slug     VARCHAR(64)  NOT NULL DEFAULT 'starter' REFERENCES plans (slug),
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- Tenant API keys (hash-only storage; multiple per tenant).
CREATE TABLE IF NOT EXISTS tenant_api_keys (
    id            UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_slug   VARCHAR(64)   NOT NULL REFERENCES tenants (slug) ON DELETE CASCADE,
    key_prefix    VARCHAR(16)   NOT NULL,
    key_hash      VARCHAR(128)  NOT NULL,
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    revoked_at    TIMESTAMPTZ,
    CONSTRAINT uq_tenant_api_keys_hash UNIQUE (key_hash)
);

CREATE INDEX IF NOT EXISTS ix_tenant_api_keys_tenant_slug ON tenant_api_keys (tenant_slug);

-- Consumption counters for time-bucketed quotas (e.g. monthly task_run).
CREATE TABLE IF NOT EXISTS tenant_quota_usage (
    tenant_slug   VARCHAR(64)   NOT NULL REFERENCES tenants (slug) ON DELETE CASCADE,
    operation     VARCHAR(64)   NOT NULL,
    period_key    VARCHAR(16)   NOT NULL,
    used          INTEGER       NOT NULL DEFAULT 0 CHECK (used >= 0),
    updated_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_slug, operation, period_key)
);

-- Tenant integrations: one row per (tenant, type, flavour) combination.
CREATE TABLE IF NOT EXISTS tenant_integrations (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_slug  VARCHAR(64) NOT NULL REFERENCES tenants (slug) ON DELETE CASCADE,
    type         VARCHAR(64) NOT NULL,
    flavour      VARCHAR(64) NOT NULL,
    active       BOOLEAN     NOT NULL DEFAULT TRUE,
    config       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_tenant_integrations_type_flavour
        UNIQUE (tenant_slug, type, flavour)
);

CREATE INDEX IF NOT EXISTS ix_tenant_integrations_tenant_slug
    ON tenant_integrations (tenant_slug);

-- Tenant-defined skills (full SkillDef in JSONB; indexed columns for listing/filtering).
CREATE TABLE IF NOT EXISTS tenant_skills (
    tenant_slug  VARCHAR(64)   NOT NULL REFERENCES tenants (slug) ON DELETE CASCADE,
    skill_id     VARCHAR(128)  NOT NULL,
    kind         VARCHAR(32)   NOT NULL CHECK (kind IN ('simple', 'composed')),
    name         VARCHAR(255)  NOT NULL,
    model        VARCHAR(128)  NOT NULL DEFAULT 'gemini/gemini-2.0-flash',
    definition   JSONB         NOT NULL,
    created_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_slug, skill_id)
);

CREATE INDEX IF NOT EXISTS ix_tenant_skills_tenant_slug ON tenant_skills (tenant_slug);
CREATE INDEX IF NOT EXISTS ix_tenant_skills_kind ON tenant_skills (tenant_slug, kind);

-- Orchestrated task runs (POST /tasks/run): full response snapshot per execution.
CREATE TABLE IF NOT EXISTS task_runs (
    id                      UUID          PRIMARY KEY,
    tenant_slug             VARCHAR(64)   NOT NULL REFERENCES tenants (slug) ON DELETE CASCADE,
    success                 BOOLEAN       NOT NULL,
    objective               TEXT          NOT NULL,
    skill_id                VARCHAR(255),
    request_input           JSONB,
    output                  JSONB,
    summary                 TEXT,
    reasoning               TEXT,
    error                   TEXT,
    steps_completed         JSONB         NOT NULL DEFAULT '[]'::jsonb,
    -- step_execution_detail: v1 object {"schemaVersion":1,"events":[...]} or NULL (see README).
    step_execution_detail   JSONB,
    cost                    JSONB,
    started_at              TIMESTAMPTZ   NOT NULL,
    finished_at             TIMESTAMPTZ   NOT NULL,
    created_at              TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_task_runs_tenant_slug ON task_runs (tenant_slug);
CREATE INDEX IF NOT EXISTS ix_task_runs_tenant_finished ON task_runs (tenant_slug, finished_at DESC);

COMMIT;
