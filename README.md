# Weave

Weave is an agentic platform that takes boring, repetitive engineering work off your team, so humans can keep building what they love.

It can investigate incidents by analyzing logs and metrics, execute runbooks, and handle ad-hoc engineering requests such as:
- "Can you check if we already have a bug on our board for login failures?"
- "Can you inspect this repo and tell me whether feature flags gate payments?"

## Table of Contents
- [Why Weave](#why-weave)
- [What Weave Can Do](#what-weave-can-do)
- [Core Concepts](#core-concepts)
- [Run Weave](#run-weave)
- [Configuration](#configuration)
- [Project Layout](#project-layout)
- [Developing Locally](#developing-locally)
- [Contributing](#contributing)
- [License](#license)

## Why Weave

Engineering teams lose time on repetitive operational work:
- Triaging noisy alerts
- Correlating logs and metrics across systems
- Running the same investigation workflows repeatedly
- Handling "quick checks" across tools like issue trackers and code repos

Weave turns these tasks into agent workflows with reusable skills and tools, so investigations are faster, more consistent, and easier to scale.

## What Weave Can Do

- Incident triage using logs, metrics, and structured investigation steps
- Automated runbook execution for repeatable ops workflows
- Ad-hoc engineering requests across integrated systems
- Multi-step orchestration with planning, execution, and synthesis
- Local tools plus per-tenant MCP and log integrations in one skill run

## Core Concepts

- **Orchestrator** — HTTP API (`orchestrator/`) backed by PostgreSQL: tenants, agents, integrations, and `POST /tasks/run`.
- **Agents** — Instructions + model + optional JSON schemas; may declare **`tools`** (tool names) and **`mcp_servers`** (MCP integration flavours). Stored per tenant in the DB; JSON files under `orchestrator/agents/` are templates you register via the API.
- **Tools** — Resolved at runtime (e.g. static HTTP tool, or Loki/OpenSearch/ClickHouse tools when a matching **integration** exists).
- **Integrations** — Per-tenant configuration (Loki, OpenSearch, ClickHouse, Git, traces, MCP servers). MCP **`flavour`** must match what agents list under **`mcp_servers`**.

---

## Run Weave

### 1. Minimal environment

| Variable | When |
|----------|------|
| **`OPENAI_API_KEY`** | Required for model calls. Set in **`orchestrator/.env`** (used by Docker Compose and local **uv**). |
| **`ORCHESTRATOR_DATABASE__URL`** | Only if you run **uv** against a database other than the default in `orchestrator/config.yaml`. Compose injects the correct URL for the orchestrator container. |

Optional variables (Redis, OTel, auth, …): **`orchestrator/.env.example`**.

Default **`orchestrator/config.yaml`** keeps **`auth.disabled`** and **`auth.quota_disabled`** as **`true`** so you can use the API locally without API keys or plan quotas.

**Postgres URLs:** `psql` uses `postgresql://…`; the app uses `postgresql+asyncpg://…` (same host, user, database; different driver prefix).

### 2. Option A — Docker Compose (Postgres + API)

From the **repository root** (where `docker-compose.yml` lives):

```bash
cp orchestrator/.env.example orchestrator/.env
# set OPENAI_API_KEY in orchestrator/.env

docker compose up --build
```

- **API:** `http://localhost:9999` — OpenAPI UI at `/docs`, health at `GET /health`.
- **Postgres:** `localhost:5432` — on **first** creation of the compose volume, `orchestrator/schema/init.sql` runs automatically. If you keep an old volume after schema changes, re-apply SQL or remove the volume.
- **Observability (optional):** `docker compose --profile observability up --build` — see comments in [`docker-compose.yml`](docker-compose.yml).

### 3. Option B — Local **uv** + your Postgres

```bash
cd orchestrator
cp .env.example .env
# OPENAI_API_KEY=...
# ORCHESTRATOR_DATABASE__URL=postgresql+asyncpg://...   # if not using config default

psql "postgresql://USER:PASS@HOST:5432/DB" -v ON_ERROR_STOP=1 -f schema/init.sql

uv sync
uv run uvicorn src.main:app --reload --host 0.0.0.0 --port 9999
# or: uv run orchestrator   (port from REST_PORT, default 9999)
```

### 4. First flow: tenant → agent → integration → task

Agents the runner uses are stored in **`tenant_agents`**. Copy definitions from **`orchestrator/agents/*.json`** into the API with **`POST /tenants/{slug}/agents`**. After editing template files, re-POST affected agents so the database picks up changes (see **`orchestrator/README.md`** for the `ppl_log_analysis` workflow agents).

From the **repository root**, paths below use **`orchestrator/agents/`**. If you already **`cd orchestrator`**, use **`agents/`** instead.

```bash
export BASE=http://localhost:9999
```

**1 — Create a tenant** (`plan_slug`: `starter` | `essential` | `pro`)

```bash
curl -s -X POST "$BASE/tenants" \
  -H "Content-Type: application/json" \
  -d '{"slug":"dev","display_name":"Dev","plan_slug":"starter"}'
```

**2 — Register an agent** (example: HTTP check; no integration required)

```bash
curl -s -X POST "$BASE/tenants/dev/agents" \
  -H "Content-Type: application/json" \
  -d @orchestrator/agents/http_check.json
```

**3 — Add an integration** (example: Loki — needed for agents whose **`tools`** include `loki_*` tool names; point **`url`** at a real Loki when you have one)

```bash
curl -s -X POST "$BASE/tenants/dev/integrations" \
  -H "Content-Type: application/json" \
  -d '{"type":"LOG_SOURCE","flavour":"LOKI","url":"http://localhost:3100","active":true}'
```

**4 — Run a task**

```bash
curl -s -X POST "$BASE/tasks/run" \
  -H "Content-Type: application/json" \
  -d '{"objective":"Health check","slug":"dev","agent_id":"http_check","input":{"url":"https://example.com"}}'
```

Request body: **`objective`**, **`slug`**, and **`agent_id`** required; **`input`** optional (validated against the agent's `input_schema` when present).

With Loki registered, you can **`POST`** e.g. `orchestrator/agents/logql_generation.json` and run a task with **`"agent_id": "logql_generation"`** and a body that matches that agent's schema.

---

## Configuration

- **Runtime tuning** — `orchestrator/config.yaml` (CORS, database pool, auth defaults, public routes, quota route patterns). Overrides: **`ORCHESTRATOR_*`** env vars with **`__`** for nesting (e.g. `ORCHESTRATOR_DATABASE__URL`).
- **Secrets and integrations** — not in `config.yaml` for MCP/log stacks: create **integrations** per tenant via the API (see walkthrough and [`orchestrator/README.md`](orchestrator/README.md)).
- **Orchestrator package details** — layout, OpenAPI, DB maintenance, scripts: **[orchestrator/README.md](orchestrator/README.md)**.

---

## Project Layout

```text
weave/
  docker-compose.yml
  README.md
  orchestrator/
    README.md           # package / dev details
    CLAUD.md            # coding conventions
    config.yaml
    pyproject.toml
    spec/openapi.yaml
    schema/init.sql
    agents/             # JSON templates → POST …/tenants/{slug}/agents
    scripts/
    src/
      api/
      core/
      storage/
      integrations/
      config/
      …
    tests/
```

---

## Developing Locally

```bash
cd orchestrator
uv run pytest
```

---

## Contributing

Contributions are welcome. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for setup, coding standards, testing expectations, and the PR checklist.

## License

This repository is licensed under the terms in [`LICENSE`](LICENSE).
