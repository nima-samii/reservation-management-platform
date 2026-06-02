import sqlalchemy

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.admin.deps import get_current_admin
from app.cache.client import redis_client
from app.db.session import engine

router = APIRouter(tags=["admin"])


@router.get("/health")
async def admin_health(_: str = Depends(get_current_admin)) -> JSONResponse:
    db_ok = False
    redis_ok = False

    try:
        async with engine.connect() as conn:
            await conn.execute(sqlalchemy.text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    try:
        await redis_client.client.ping()
        redis_ok = True
    except Exception:
        pass

    ok = db_ok and redis_ok
    return JSONResponse(
        content={"status": "ok" if ok else "degraded", "db": db_ok, "redis": redis_ok},
        status_code=200 if ok else 503,
    )
