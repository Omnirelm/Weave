# orchestrator

Python package for the **Weave** orchestrator: a FastAPI service that runs **tasks** (single agent execution) against PostgreSQL, using Google ADK.

**Setup, Docker Compose, uv, and the tenant → agent → integration → task walkthrough:** see the repository root **[README.md](../README.md#run-weave)**.

---

## Package layout

| Path | Purpose |
|------|---------|
| [`src/`](src/) | Application code: `api/` (routes, middleware, OpenAPI models), `core/` (agents runner, tools, MCP), `storage/` (ORM, repositories), `integrations/`, `config/`, … |
| [`agents/`](agents/) | JSON **templates** aligned with `POST /tenants/{slug}/agents`. Runtime execution reads agents from the **`tenant_agents`** table. |
| [`workflows/`](workflows/) | JSON **templates** for multi-agent chains (`POST /tenants/{slug}/workflows`). |

**Updating agents after template changes:** the API does not auto-sync files under `agents/`. Re-register each changed agent so `tenant_agents` picks up the new definition:

```bash
export BASE=http://localhost:9999
for agent in ppl_generation fetch_and_analyze git_inference; do
  curl -s -X POST "$BASE/tenants/{slug}/agents" \
    -H "Content-Type: application/json" \
    -d @"agents/${agent}.json"
done
```

Replace `{slug}` with your tenant (e.g. `xcorp`). Workflow agents use natural-language handoffs end-to-end.

| [`schema/init.sql`](schema/init.sql) | Canonical Postgres schema (applied manually or via Compose init). |
| [`schema/migrations/`](schema/migrations/) | Forward SQL for existing databases. |
| [`spec/openapi.yaml`](spec/openapi.yaml) | API contract; generated Pydantic models live under `src/api/models/`. |
| [`scripts/mint_api_key.py`](scripts/mint_api_key.py) | Mint tenant API keys when **`auth.disabled`** is `false`. |

Coding conventions: **[CLAUD.md](CLAUD.md)**.

---

## Configuration (`config.yaml`)

- **CORS**, **database** pool / URL default
- **`auth`**: `disabled`, `quota_disabled`, `api_key_pepper`, `public_routes`, `quota_routes`

Dynaconf loads this file from the package root; override with **`ORCHESTRATOR_`** env vars and **`__`** nesting (see [`.env.example`](.env.example)).

---

## Database

SQLAlchemy 2.x (async) + PostgreSQL. The app does not migrate schema by itself — apply [`schema/init.sql`](schema/init.sql) (or migration scripts). ORM models in [`src/storage/models/`](src/storage/models/) must stay in sync with that SQL.

---

## API surface (summary)

| Area | Routes |
|------|--------|
| Health | `GET /health` |
| Tenants | `POST /tenants`, `GET /tenants/{slug}` |
| Agents | `GET`/`POST` `/tenants/{slug}/agents`, `GET`/`DELETE` `/tenants/{slug}/agents/{id}` |
| Integrations | `GET`/`POST` `/tenants/{slug}/integrations`, `GET`/`PUT` `/tenants/{slug}/integrations/{id}` |
| Tasks | `POST /tasks/run` |
| Tools | `GET /tools` |

Full request/response shapes: **`/docs`** or [`spec/openapi.yaml`](spec/openapi.yaml).

---

## Auth (when enabled)

Set **`ORCHESTRATOR_AUTH__API_KEY_PEPPER`**. Mint keys: `uv run python scripts/mint_api_key.py <tenant_slug>` (`-p` / `--print-only` emits SQL, no DB). Client: `Authorization: Bearer <key>` or `X-API-Key`.

Public routes without a key (from default config): `GET /health`, `GET /docs`, `GET /redoc`, `GET /openapi.json`, `POST /tenants`.

---

## Tests

```bash
uv run pytest
```

Run from **`orchestrator/`** (next to `pyproject.toml`).

---

## Observability

**Application logs:** Workflow runs emit structured `workflow.run.*` and `workflow.step.done` lines correlated by `task_id`. Override verbosity with `ORCHESTRATOR_LOG_LEVEL` (`DEBUG` adds per-ADK-event `workflow.event` lines).

**OpenTelemetry (ADK-native):** Set `OTEL_ENABLED=true` and `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` in [`.env.example`](.env.example). With `docker compose --profile observability up`, traces appear in Jaeger at `http://localhost:16686` (`invoke_workflow` → `invoke_agent` waterfalls). Spans include `weave.task_id`, `weave.tenant_id`, and `weave.workflow_id` when a task run is in progress.

---

## Production checklist

- [ ] Set **`auth.disabled`** / **`auth.quota_disabled`** and **`ORCHESTRATOR_AUTH__API_KEY_PEPPER`** as required; mint and distribute API keys.
- [ ] Apply schema (or migrations) **before** deploys that depend on new tables/columns.
- [ ] Prefer additive DB changes; backups before destructive SQL.
