from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.cache.client import redis_client
from app.db.session import engine

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> JSONResponse:
    db_ok = False
    redis_ok = False

    try:
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    try:
        await redis_client.client.ping()
        redis_ok = True
    except Exception:
        pass

    status = "ok" if db_ok and redis_ok else "degraded"
    return JSONResponse(
        content={"status": status, "db": db_ok, "redis": redis_ok},
        status_code=200 if status == "ok" else 503,
    )
