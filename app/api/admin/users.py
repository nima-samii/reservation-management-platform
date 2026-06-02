import uuid
from math import ceil
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin.deps import get_current_admin
from app.api.admin.schemas.users import (
    CountryItem,
    PaginatedTransactions,
    PaginatedUsers,
    ScoreAdjustRequest,
    ScoreAdjustResponse,
    ScoreTransactionItem,
    SendMessageRequest,
    SendMessageResponse,
    UserDetail,
    UserListItem,
    UserPatch,
)
from app.core.logging import get_logger
from app.db.session import get_db_session
from app.repositories.admin_audit_log import AdminAuditLogRepository
from app.repositories.country import CountryRepository
from app.repositories.score import ScoreTransactionRepository
from app.repositories.user import UserRepository
from app.services.score import ParticipationScoreService

router = APIRouter(tags=["admin-users"])
logger = get_logger(__name__)

_VALID_SORT = {"score", "name", "created_at"}
_VALID_ORDER = {"asc", "desc"}


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")


def _to_list_item(user) -> UserListItem:
    return UserListItem(
        id=user.id,
        telegram_id=user.telegram_id,
        public_user_code=user.public_user_code,
        full_name=user.full_name,
        username=user.username,
        gender=user.gender,
        country=(
            CountryItem(
                id=user.country_rel.id,
                name=user.country_rel.name,
                flag_emoji=user.country_rel.flag_emoji,
                code=user.country_rel.code,
            )
            if user.country_rel
            else None
        ),
        participation_score=user.participation_score,
        is_active=user.is_active,
        is_banned=user.is_banned,
        created_at=user.created_at,
    )


@router.get("", response_model=PaginatedUsers)
async def list_users(
    search: Optional[str] = Query(None),
    country_id: Optional[uuid.UUID] = Query(None),
    gender: Optional[str] = Query(None),
    is_banned: Optional[bool] = Query(None),
    is_active: Optional[bool] = Query(None),
    sort_by: str = Query("created_at"),
    order: str = Query("desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
    _admin: str = Depends(get_current_admin),
) -> PaginatedUsers:
    if sort_by not in _VALID_SORT:
        sort_by = "created_at"
    if order not in _VALID_ORDER:
        order = "desc"

    repo = UserRepository(session)
    users, total = await repo.admin_list(
        search=search,
        country_id=country_id,
        gender=gender,
        is_banned=is_banned,
        is_active=is_active,
        sort_by=sort_by,
        order=order,
        page=page,
        page_size=page_size,
    )
    return PaginatedUsers(
        items=[_to_list_item(u) for u in users],
        total=total,
        page=page,
        pages=max(1, ceil(total / page_size)),
    )


@router.get("/{user_id}", response_model=UserDetail)
async def get_user(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    _admin: str = Depends(get_current_admin),
) -> UserDetail:
    user_repo = UserRepository(session)
    score_repo = ScoreTransactionRepository(session)

    user = await user_repo.get_by_uuid_with_country(user_id)
    if not user:
        raise _not_found()

    recent_txs = await score_repo.get_user_history(user_id, limit=20)
    base = _to_list_item(user)

    return UserDetail(
        **base.model_dump(),
        recent_transactions=[
            ScoreTransactionItem(
                id=tx.id,
                delta=tx.score_delta,
                transaction_type=tx.transaction_type,
                reason=tx.reason,
                created_at=tx.created_at,
            )
            for tx in recent_txs
        ],
    )


@router.patch("/{user_id}", response_model=UserListItem)
async def patch_user(
    user_id: uuid.UUID,
    body: UserPatch,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    admin: str = Depends(get_current_admin),
) -> UserListItem:
    user_repo = UserRepository(session)
    audit_repo = AdminAuditLogRepository(session)

    user = await user_repo.get_by_uuid_with_country(user_id)
    if not user:
        raise _not_found()

    if body.country_id is not None:
        country = await CountryRepository(session).get_by_id(body.country_id)
        if not country:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Country not found",
            )

    if body.full_name is not None:
        if not body.full_name.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="full_name must not be empty",
            )
        user.full_name = body.full_name.strip()

    if body.gender is not None:
        user.gender = body.gender
    if body.country_id is not None:
        user.country_id = body.country_id  # type: ignore[assignment]
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.is_banned is not None:
        user.is_banned = body.is_banned

    await user_repo.save(user)
    user = await user_repo.get_by_uuid_with_country(user_id)

    ip = request.client.host if request.client else None
    await audit_repo.log(
        action="user_patched",
        admin_username=admin,
        entity_type="user",
        entity_id=str(user_id),
        details=body.model_dump_json(exclude_none=True),
        ip_address=ip,
    )
    logger.info("admin_user_patched", user_id=str(user_id), admin=admin)

    return _to_list_item(user)


@router.post(
    "/{user_id}/score",
    response_model=ScoreAdjustResponse,
    status_code=status.HTTP_201_CREATED,
)
async def adjust_score(
    user_id: uuid.UUID,
    body: ScoreAdjustRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    admin: str = Depends(get_current_admin),
) -> ScoreAdjustResponse:
    user_repo = UserRepository(session)
    audit_repo = AdminAuditLogRepository(session)

    user = await user_repo.get_by_id(user_id)
    if not user:
        raise _not_found()

    score_service = ParticipationScoreService(session)
    tx = await score_service.apply_admin_adjustment(
        user_id=user_id,
        delta=body.delta,
        reason=body.reason,
        meta={"admin": admin},
    )

    await session.refresh(user)

    ip = request.client.host if request.client else None
    await audit_repo.log(
        action="score_adjusted",
        admin_username=admin,
        entity_type="user",
        entity_id=str(user_id),
        details=f"delta={body.delta:+d} reason={body.reason}",
        ip_address=ip,
    )
    logger.info("admin_score_adjusted", user_id=str(user_id), delta=body.delta, admin=admin)

    return ScoreAdjustResponse(new_score=user.participation_score, transaction_id=tx.id)


@router.get("/{user_id}/score-history", response_model=PaginatedTransactions)
async def get_score_history(
    user_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
    _admin: str = Depends(get_current_admin),
) -> PaginatedTransactions:
    user_repo = UserRepository(session)
    score_repo = ScoreTransactionRepository(session)

    user = await user_repo.get_by_id(user_id)
    if not user:
        raise _not_found()

    txs, total = await score_repo.get_user_history_paginated(
        user_id, page=page, page_size=page_size
    )

    return PaginatedTransactions(
        items=[
            ScoreTransactionItem(
                id=tx.id,
                delta=tx.score_delta,
                transaction_type=tx.transaction_type,
                reason=tx.reason,
                created_at=tx.created_at,
            )
            for tx in txs
        ],
        total=total,
        page=page,
        pages=max(1, ceil(total / page_size)),
    )


@router.post("/{user_id}/send-message", response_model=SendMessageResponse)
async def send_message_to_user(
    user_id: uuid.UUID,
    body: SendMessageRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    admin: str = Depends(get_current_admin),
) -> SendMessageResponse:
    user_repo = UserRepository(session)
    audit_repo = AdminAuditLogRepository(session)

    user = await user_repo.get_by_id(user_id)
    if not user:
        raise _not_found()

    bot: Bot = request.app.state.bot
    ip = request.client.host if request.client else None
    preview = body.message[:120]

    try:
        tg_msg = await bot.send_message(chat_id=user.telegram_id, text=body.message)
        await audit_repo.log(
            action="message_sent",
            admin_username=admin,
            entity_type="user",
            entity_id=str(user_id),
            details=f"ok=true msg_id={tg_msg.message_id} preview={preview!r}",
            ip_address=ip,
        )
        logger.info("admin_message_sent", user_id=str(user_id), admin=admin)
        return SendMessageResponse(ok=True, telegram_message_id=tg_msg.message_id)
    except TelegramAPIError as exc:
        await audit_repo.log(
            action="message_sent",
            admin_username=admin,
            entity_type="user",
            entity_id=str(user_id),
            details=f"ok=false error={exc}",
            ip_address=ip,
        )
        logger.warning("admin_message_failed", user_id=str(user_id), error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
