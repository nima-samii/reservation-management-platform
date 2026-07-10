import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.admin.deps import get_current_admin
from app.core.logging import get_logger

router = APIRouter(tags=["admin-jobs"])
logger = get_logger(__name__)

_ALLOWED_JOBS = {
    "slot_generation",
    "reservation_lifecycle",
    "same_day_reminders",
    "pre_session_reminders",
    "daily_broadcast",
    "recurring_broadcast_dispatch",
    "inactivity_reminders",
}


async def _import_and_run(job_id: str) -> None:
    if job_id == "slot_generation":
        from app.schedulers.jobs.slot_generation import generate_upcoming_slots
        await generate_upcoming_slots()
    elif job_id == "reservation_lifecycle":
        from app.schedulers.jobs.reservation_lifecycle import complete_past_reservations_job
        await complete_past_reservations_job()
    elif job_id == "same_day_reminders":
        from app.schedulers.jobs.reminders import send_same_day_reminders_job
        await send_same_day_reminders_job()
    elif job_id == "pre_session_reminders":
        from app.schedulers.jobs.reminders import send_pre_session_reminders_job
        await send_pre_session_reminders_job()
    elif job_id == "daily_broadcast":
        from app.schedulers.jobs.broadcast import send_daily_schedule_job
        await send_daily_schedule_job()
    elif job_id == "recurring_broadcast_dispatch":
        from app.schedulers.jobs.recurring_broadcast import dispatch_recurring_broadcasts_job
        await dispatch_recurring_broadcasts_job()
    elif job_id == "inactivity_reminders":
        from app.schedulers.jobs.inactivity_reminder import send_inactivity_reminders_job
        await send_inactivity_reminders_job()


@router.get("")
async def list_jobs(
    request: Request,
    _admin: str = Depends(get_current_admin),
) -> list[dict]:
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        return []

    jobs = scheduler.get_jobs()
    return [
        {
            "id": job.id,
            "name": job.name or job.id,
            "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
            "last_run_status": None,
        }
        for job in jobs
    ]


@router.post("/{job_id}/trigger")
async def trigger_job(
    job_id: str,
    _admin: str = Depends(get_current_admin),
) -> dict:
    if job_id not in _ALLOWED_JOBS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown job: {job_id}. Allowed: {sorted(_ALLOWED_JOBS)}",
        )

    asyncio.create_task(_import_and_run(job_id), name=f"admin_trigger_{job_id}")
    logger.info("admin_job_triggered", job_id=job_id)

    return {"job_id": job_id, "status": "triggered", "message": "Job started in background"}
