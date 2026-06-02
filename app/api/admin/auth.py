import uuid
from datetime import datetime, timedelta, timezone

import bcrypt as _bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.client import redis_client
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import get_db_session
from app.repositories.admin_audit_log import AdminAuditLogRepository

logger = get_logger(__name__)
router = APIRouter(tags=["admin-auth"])

ALGORITHM = "HS256"
_REFRESH_TTL_DAYS = 7
_RT_PREFIX = "admin:rt:"


class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


def _create_access_token() -> str:
    payload = {
        "sub": settings.ADMIN_USERNAME,
        "type": "access",
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.ADMIN_JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.ADMIN_JWT_SECRET, algorithm=ALGORITHM)


def _create_refresh_token() -> tuple[str, str]:
    """Returns (jti, signed_jwt). Store jti in Redis; send signed_jwt to client."""
    jti = str(uuid.uuid4())
    payload = {
        "sub": settings.ADMIN_USERNAME,
        "type": "refresh",
        "jti": jti,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(days=_REFRESH_TTL_DAYS),
    }
    return jti, jwt.encode(payload, settings.ADMIN_JWT_SECRET, algorithm=ALGORITHM)


async def _store_rt(jti: str) -> None:
    await redis_client.set(f"{_RT_PREFIX}{jti}", "valid", ttl=_REFRESH_TTL_DAYS * 86400)


async def _revoke_rt(jti: str) -> None:
    await redis_client.delete(f"{_RT_PREFIX}{jti}")


async def _rt_valid(jti: str) -> bool:
    return await redis_client.exists(f"{_RT_PREFIX}{jti}")


def _require_admin_configured() -> None:
    if not settings.ADMIN_JWT_SECRET or not settings.ADMIN_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin panel is not configured — set ADMIN_PASSWORD and ADMIN_JWT_SECRET in .env",
        )


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> TokenResponse:
    _require_admin_configured()

    ip = request.client.host if request.client else None
    invalid = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if body.username != settings.ADMIN_USERNAME:
        raise invalid

    try:
        password_ok = _bcrypt.checkpw(
            body.password.encode("utf-8"),
            settings.ADMIN_PASSWORD.encode("utf-8"),
        )
    except Exception:
        raise invalid

    if not password_ok:
        raise invalid

    access_token = _create_access_token()
    jti, refresh_token = _create_refresh_token()
    await _store_rt(jti)

    repo = AdminAuditLogRepository(session)
    await repo.log(action="admin_login", admin_username=body.username, ip_address=ip)

    logger.info("admin_login", username=body.username, ip=ip)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest) -> TokenResponse:
    _require_admin_configured()

    invalid = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    try:
        payload = jwt.decode(body.refresh_token, settings.ADMIN_JWT_SECRET, algorithms=[ALGORITHM])
    except JWTError:
        raise invalid

    if payload.get("type") != "refresh":
        raise invalid

    jti = payload.get("jti")
    if not jti or not await _rt_valid(jti):
        raise invalid

    # Rotate: revoke old, issue new pair
    await _revoke_rt(jti)

    access_token = _create_access_token()
    new_jti, new_refresh_token = _create_refresh_token()
    await _store_rt(new_jti)

    return TokenResponse(access_token=access_token, refresh_token=new_refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: RefreshRequest) -> None:
    try:
        payload = jwt.decode(body.refresh_token, settings.ADMIN_JWT_SECRET, algorithms=[ALGORITHM])
        jti = payload.get("jti")
        if jti:
            await _revoke_rt(jti)
    except JWTError:
        pass
