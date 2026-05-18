# orchestrator

Python package for the **Weave** orchestrator: a FastAPI service that runs **tasks** (planner + steps) and **skills** against PostgreSQL, using the OpenAI Agents SDK.

**Setup, Docker Compose, uv, and the tenant → skill → integration → task walkthrough:** see the repository root **[README.md](../README.md#run-weave)**.

---

## Package layout

| Path | Purpose |
|------|---------|
| [`src/`](src/) | Application code: `api/` (routes, middleware, OpenAPI models), `core/` (skills runner, tools, MCP), `storage/` (ORM, repositories), `integrations/`, `config/`, … |
| [`skills/`](skills/) | JSON **templates** aligned with `POST /tenants/{slug}/skills`. Runtime execution reads skills from the **`tenant_skills`** table. |
| [`schema/init.sql`](schema/init.sql) | Canonical Postgres schema (applied manually or via Compose init). |
| [`schema/migrate_*.sql`](schema/) | Optional forward SQL for existing databases. |
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

SQLAlchemy 2.x (async) + PostgreSQL. The app does not migrate schema by itself — apply [`schema/init.sql`](schema/init.sql) (or your forward scripts). ORM models in [`src/storage/models/`](src/storage/models/) must stay in sync with that SQL; change patterns and checklist: **[CLAUD.md](CLAUD.md)**.

---

## API surface (summary)

| Area | Routes |
|------|--------|
| Health | `GET /health` |
| Tenants | `POST /tenants`, `GET /tenants/{slug}` |
| Skills | `GET`/`POST` `/tenants/{slug}/skills`, `GET`/`DELETE` `/tenants/{slug}/skills/{id}` |
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

## Production checklist

- [ ] Set **`auth.disabled`** / **`auth.quota_disabled`** and **`ORCHESTRATOR_AUTH__API_KEY_PEPPER`** as required; mint and distribute API keys.
- [ ] Apply schema (or migrations) **before** deploys that depend on new tables/columns.
- [ ] Prefer additive DB changes; backups before destructive SQL.
