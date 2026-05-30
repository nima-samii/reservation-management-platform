from fastapi import APIRouter

from app.api.admin.auth import router as auth_router
from app.api.admin.channels import router as channels_router
from app.api.admin.countries import router as countries_router
from app.api.admin.health import router as health_router
from app.api.admin.reservations import router as reservations_router
from app.api.admin.users import router as users_router

admin_router = APIRouter(prefix="/api/admin")
admin_router.include_router(auth_router, prefix="/auth")
admin_router.include_router(health_router)
admin_router.include_router(users_router, prefix="/users")
admin_router.include_router(countries_router)
admin_router.include_router(reservations_router, prefix="/reservations")
admin_router.include_router(channels_router, prefix="/channels")
