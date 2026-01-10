from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import NoResultFound

from app.auth import apikey_or_jwt_required
from app.db.session import get_async_session
from app.db import logger_configs as crud_logger_configs
from app.schemas_openrvdas import (
    LoggerConfigCreate,
    LoggerConfigUpdate,
    LoggerConfigOut,
)

router = APIRouter(
    prefix="/api/v1/logger-configs",
    tags=["LoggerConfigs"],
)

@router.get("/", response_model=List[LoggerConfigOut])
async def list_logger_configs(
    session: AsyncSession = Depends(get_async_session),
):
    return await crud_logger_configs.get_logger_configs(session)

@router.get("/{config_id}", response_model=LoggerConfigOut)
async def get_logger_config(
    config_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    config = await crud_logger_configs.get_logger_config(session, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="LoggerConfig not found")
    return config

@router.post("/", response_model=LoggerConfigOut, status_code=201, dependencies=[Depends(apikey_or_jwt_required())])
async def create_logger_config(
    payload: LoggerConfigCreate,
    session: AsyncSession = Depends(get_async_session),
):
    return await crud_logger_configs.create_logger_config(
        session,
        name=payload.name,
        config_json=payload.config_json,
        logger_id=payload.logger_id,
        enabled=payload.enabled,
    )

@router.patch("/{config_id}", response_model=LoggerConfigOut, dependencies=[Depends(apikey_or_jwt_required())])
async def patch_logger_config(
    config_id: str,
    payload: LoggerConfigUpdate,
    session: AsyncSession = Depends(get_async_session),
):
    try:
        return await crud_logger_configs.update_logger_config(
            session,
            config_id,
            name=payload.name,
            config_json=payload.config_json,
            logger_id=payload.logger_id,
            enabled=payload.enabled,
        )
    except NoResultFound:
        raise HTTPException(status_code=404, detail="LoggerConfig not found")

@router.delete("/{config_id}", response_model=dict, dependencies=[Depends(apikey_or_jwt_required())])
async def delete_logger_config(
    config_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    try:
        await crud_logger_configs.delete_logger_config(session, config_id)
    except NoResultFound:
        raise HTTPException(status_code=404, detail="LoggerConfig not found")

    return {"detail": "LoggerConfig deleted successfully"}
