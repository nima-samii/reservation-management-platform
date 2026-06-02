from fastapi import APIRouter

from app.api.admin.auth import router as auth_router
from app.api.admin.broadcast import router as broadcast_router
from app.api.admin.channels import router as channels_router
from app.api.admin.countries import router as countries_router
from app.api.admin.dashboard import router as dashboard_router
from app.api.admin.health import router as health_router
from app.api.admin.jobs import router as jobs_router
from app.api.admin.reservations import router as reservations_router
from app.api.admin.schedule_events import router as schedule_events_router
from app.api.admin.settings import router as settings_router
from app.api.admin.users import router as users_router

admin_router = APIRouter(prefix="/api/admin")
admin_router.include_router(auth_router, prefix="/auth")
admin_router.include_router(health_router)
admin_router.include_router(users_router, prefix="/users")
admin_router.include_router(countries_router)
admin_router.include_router(reservations_router, prefix="/reservations")
admin_router.include_router(channels_router, prefix="/channels")
admin_router.include_router(dashboard_router, prefix="/dashboard")
admin_router.include_router(settings_router, prefix="/settings")
admin_router.include_router(broadcast_router, prefix="/broadcast")
admin_router.include_router(jobs_router, prefix="/jobs")
admin_router.include_router(schedule_events_router, prefix="/schedule-events")
