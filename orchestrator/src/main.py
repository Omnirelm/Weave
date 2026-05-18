import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.middleware.auth_quota import (
    AuthQuotaMiddleware,
    compile_public_route_pairs,
    compile_quota_route_table,
)

from src.api.router import api_router
from src.bootstrap import wire_application
from src.config.settings import get_config


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await wire_application(app)
    try:
        yield
    finally:
        if hasattr(app.state, "storage"):
            await app.state.storage.db.dispose()


def create_app() -> FastAPI:
    config = get_config()
    app = FastAPI(title=config.app_name, lifespan=lifespan)
    app.add_middleware(
        AuthQuotaMiddleware,
        quota_route_table=compile_quota_route_table(config.auth),
        public_route_pairs=compile_public_route_pairs(config.auth),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors.allow_origins,
        allow_methods=config.cors.allow_methods,
        allow_headers=config.cors.allow_headers,
        allow_credentials=config.cors.allow_credentials,
        max_age=config.cors.max_age,
    )
    app.include_router(api_router)
    return app


app = create_app()


def run() -> None:
    import uvicorn

    config = get_config()
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=int(os.environ.get("REST_PORT", "9999")),
        reload=config.debug,
    )


if __name__ == "__main__":
    run()
