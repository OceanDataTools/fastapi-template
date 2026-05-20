from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import logger_crud as crud_loggers
from app.deps import get_async_session
from app.schemas_openrvdas import LoggerOut

router = APIRouter(prefix="/api/v1/loggers", tags=["Loggers"])


@router.get("/", response_model=List[LoggerOut])
async def list_loggers(
    session: AsyncSession = Depends(get_async_session),
):
    return await crud_loggers.list_loggers(session)


@router.get("/{logger_id}", response_model=LoggerOut)
async def get_logger(
    logger_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    try:
        logger = await crud_loggers.get_logger(session, logger_id)
    except NoResultFound:
        raise HTTPException(status_code=404, detail="Logger not found")
    return logger
