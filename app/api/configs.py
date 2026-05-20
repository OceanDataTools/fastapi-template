import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import apikey_or_jwt_required
from app.db import config_crud as crud_configs
from app.deps import get_async_server_api, get_async_session
from app.schemas_openrvdas import ConfigOut
from async_fastapi_server_api import AsyncFastAPIServerAPI

router = APIRouter(
    prefix="/api/v1/configs",
    tags=["Configs"],
)


@router.get("/", response_model=List[ConfigOut])
async def list_configs(
    session: AsyncSession = Depends(get_async_session),
):
    return await crud_configs.list_configs(session)


@router.get("/{config_id}", response_model=ConfigOut)
async def get_config(
    config_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    config = await crud_configs.get_config(session, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="Config not found")
    return config


@router.post("/{config_id}/activate", dependencies=[Depends(apikey_or_jwt_required())])
async def activate_config(
    config_id: str,
    session: AsyncSession = Depends(get_async_session),
    server_api: AsyncFastAPIServerAPI = Depends(get_async_server_api),
):
    try:
        config = await crud_configs.get_config(session, config_id)
        state = await server_api.set_active_logger_config(
            config["logger_id"], config_id
        )
        logging.debug(f"state {state}")
    except NoResultFound as e:
        raise HTTPException(status_code=422, detail=str(e))


# @router.post("/", response_model=ConfigOut, status_code=201, dependencies=[Depends(apikey_or_jwt_required())])
# async def create_logger_config(
#     payload: ConfigCreate,
#     session: AsyncSession = Depends(get_async_session),
# ):
#     return await crud_configs.create_config(
#         session,
#         name=payload.name,
#         config_json=payload.config_json,
#         logger_id=payload.logger_id,
#         enabled=payload.enabled,
#     )

# @router.patch("/{config_id}", response_model=ConfigOut, dependencies=[Depends(apikey_or_jwt_required())])
# async def patch_logger_config(
#     config_id: str,
#     payload: ConfigUpdate,
#     session: AsyncSession = Depends(get_async_session),
# ):
#     try:
#         return await crud_configs.update_config(
#             session,
#             config_id,
#             name=payload.name,
#             config_json=payload.config_json,
#             logger_id=payload.logger_id,
#             enabled=payload.enabled,
#         )
#     except NoResultFound:
#         raise HTTPException(status_code=404, detail="Config not found")

# @router.delete("/{config_id}", response_model=dict, dependencies=[Depends(apikey_or_jwt_required())])
# async def delete_logger_config(
#     config_id: str,
#     session: AsyncSession = Depends(get_async_session),
# ):
#     try:
#         await crud_configs.delete_config(session, config_id)
#     except NoResultFound:
#         raise HTTPException(status_code=404, detail="Config not found")

#     return {"detail": "Config deleted successfully"}
