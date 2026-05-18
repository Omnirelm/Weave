# Orchestrator — coding standards

This document sets **foundational** conventions for this Python service. Extend it as the codebase grows; avoid ceremony before there is a second use case.

## Stack

- Python 3.11+
- Dependency and env management: **uv** (`pyproject.toml`, `uv.lock`)
- Web: **FastAPI**, **Pydantic**, **`pydantic-settings`** for configuration
- Run locally: `uv run uvicorn src.main:app --reload` or `uv run orchestrator-api` (see `pyproject.toml` `[project.scripts]`)

## Layered layout

| Layer | Purpose |
| --- | --- |
| **`domain/`** | Entities, value objects, domain errors, **`typing.Protocol`** interfaces. **No** FastAPI, Starlette, or I/O imports. |
| **`application/`** | Use cases / application services: orchestrate domain rules and ports. No HTTP types. |
| **`infrastructure/`** | Adapters: databases, caches, external HTTP clients—implementations of `domain` protocols. |
| **`api/`** | HTTP surface: routers, request/response models, dependency wiring via `Depends`. Keep handlers thin; delegate to `application`. |
| **`config/`** | Centralized settings (env-backed). |

**Dependency direction:** `api` → `application` → `domain`; `infrastructure` implements `domain` protocols and is wired at the edge (e.g. FastAPI `Depends` or app factory).

## Design principles

- **SOLID (pragmatic):** Prefer small modules (**single responsibility**). Depend on **protocols** in `domain` or `application`, inject implementations from `infrastructure` (**dependency inversion**). Extend behavior by adding routes/use cases rather than growing god-objects (**open/closed**).
- **DRY:** One place for env/config (`config/settings.py`). Reuse Pydantic models under `api/schemas/` when the same shape appears in multiple routes—do not duplicate large model blobs.
- **YAGNI:** No generic repository layer until persistence is real. No abstract base classes until a **second** implementation exists.

## Python practices

- Type hints on public functions and route handlers.
- **`create_app()`** in `main.py` is the single factory for the FastAPI app; tests should prefer `create_app()` over importing the global `app` when isolation matters.
- Routers return clear Pydantic models or typed dicts; avoid leaking infrastructure exceptions—map to HTTP errors at the API boundary when you add error handling.

## Handler conventions

**Execution order inside a route handler:**

1. **Request validation first** — call `body.validate()` before any I/O. A bad request should never cost a DB round-trip.
2. **Existence checks second** — tenant guard, resource lookup. These are the cheapest necessary DB calls before mutating state.
3. **Business rule checks third** — immutability guards, conflict detection that requires the fetched row (e.g. flavour cannot change on update).
4. **Mutation last** — write to the DB only after all checks pass.

```python
# correct order
body.validate()                          # 1. pure — no I/O
await _require_tenant(storage, slug)     # 2. cheapest existence check
existing = await repo.get(id)            # 3. fetch only when needed for a check
if body.immutable_field != existing.x:   # 3. business rule against fetched row
    raise HTTPException(400, ...)
await repo.update(id, payload)           # 4. mutate
```

**Error mapping:**

| Exception | HTTP status |
|---|---|
| `ValueError` from `body.validate()` | 400 Bad Request |
| Resource not found | 404 Not Found |
| `sqlalchemy.exc.IntegrityError` | 409 Conflict |
| Unexpected exception | 500 Internal Server Error |

## Testing

- **`tests/`** mirrors features; use **`fastapi.testclient.TestClient`** (or `httpx` against ASGI) for API tests.
- Run: `uv run pytest` from the `orchestrator/` directory.

## Environment

- Settings use the prefix **`ORCHESTRATOR_`** (see `Settings` in `config/settings.py`). Example: `ORCHESTRATOR_DEBUG=true`.
