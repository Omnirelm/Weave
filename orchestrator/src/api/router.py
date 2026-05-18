from fastapi import APIRouter

from src.api.routes import health, integrations, skills, tasks, tenants, tools

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(skills.router)
api_router.include_router(tasks.router)
api_router.include_router(tenants.router)
api_router.include_router(integrations.router)
api_router.include_router(tools.router)
