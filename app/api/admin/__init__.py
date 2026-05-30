from fastapi import APIRouter

from app.api.admin.auth import router as auth_router
from app.api.admin.health import router as health_router

admin_router = APIRouter(prefix="/api/admin")
admin_router.include_router(auth_router, prefix="/auth")
admin_router.include_router(health_router)
