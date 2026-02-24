from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import NoResultFound

from app.auth import apikey_or_jwt_required
from app.db.session import get_async_session
from app.db import logger_crud as crud_loggers
from app.schemas_openrvdas import (
    LoggerCreate,
    LoggerUpdate,
    LoggerOut,
)

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
    logger = await crud_loggers.get_logger(session, logger_id)

    for s in logger.config_states:
        print(s.config_id, s.running)

    if not logger:
        raise HTTPException(status_code=404, detail="Logger not found")
    return logger

# @router.post("/", response_model=LoggerOut, status_code=201, dependencies=[Depends(apikey_or_jwt_required())])
# async def create_logger(
#     payload: LoggerCreate,
#     session: AsyncSession = Depends(get_async_session),
# ):
#     return await crud_loggers.create_logger(
#         session,
#         name=payload.name,
#     )

# @router.patch("/{logger_id}", response_model=LoggerOut, dependencies=[Depends(apikey_or_jwt_required())])
# async def patch_logger(
#     logger_id: str,
#     payload: LoggerUpdate,
#     session: AsyncSession = Depends(get_async_session),
# ):
#     try:
#         return await crud_loggers.update_logger(
#             session,
#             logger_id,
#             name=payload.name,
#         )
#     except NoResultFound:
#         raise HTTPException(status_code=404, detail="Logger not found")

# @router.delete("/{logger_id}", response_model=dict, dependencies=[Depends(apikey_or_jwt_required())])
# async def delete_logger(
#     logger_id: str,
#     session: AsyncSession = Depends(get_async_session),
# ):
#     try:
#         await crud_loggers.delete_logger(session, logger_id)
#     except NoResultFound:
#         raise HTTPException(status_code=404, detail="Logger not found")

#     return {"detail": "Logger deleted successfully"}

# @router.post("/{logger_id}/logger-configs", response_model=LoggerOut, dependencies=[Depends(apikey_or_jwt_required())])
# async def add_configs_to_logger(
#     logger_id: str,
#     config_ids: List[str],
#     session: AsyncSession = Depends(get_async_session),
# ):
#     try:
#         return await crud_loggers.assign_configs_to_logger(session, logger_id, config_ids)
#     except NoResultFound as e:
#         raise HTTPException(status_code=404, detail=str(e))
#     except ValueError as e:
#         raise HTTPException(status_code=400, detail=str(e))

