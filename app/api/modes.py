from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import NoResultFound

from app.auth import apikey_or_jwt_required
from app.db.session import get_async_session
from app.db import mode_crud as crud_modes
from app.deps import get_async_server_api
from app.schemas_openrvdas import ModeCreate, ModeUpdate, ModeOut
from web_backend.async_fastapi_server_api import AsyncFastAPIServerAPI
# from web_backend.fastapi_server_api import FastAPIServerAPI

router = APIRouter(prefix="/api/v1/modes", tags=["Modes"])


@router.get("/", response_model=List[ModeOut])
async def list_modes(
    session: AsyncSession = Depends(get_async_session),
):
    return await crud_modes.list_modes(session)


@router.get("/active", response_model=ModeOut)
async def get_active_mode(session: AsyncSession = Depends(get_async_session)):
    mode = await crud_modes.get_active_mode(session)
    if not mode:
        raise HTTPException(status_code=404, detail="No active mode found")
    return mode


@router.get("/default", response_model=ModeOut)
async def get_default_mode(session: AsyncSession = Depends(get_async_session)):
    mode = await crud_modes.get_default_mode(session)
    if not mode:
        raise HTTPException(status_code=404, detail="No default mode found")
    return mode


@router.get("/{mode_id}", response_model=ModeOut)
async def get_mode(
    mode_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    mode = await crud_modes.get_mode(session, mode_id)
    if not mode:
        raise HTTPException(status_code=422, detail=f"Mode {mode_id} not found")
    return mode


# @router.post("/", response_model=ModeOut, dependencies=[Depends(apikey_or_jwt_required())])
# async def create_mode(
#     payload: ModeCreate,
#     session: AsyncSession = Depends(get_async_session),
# ):
#     # TODO Replace with ServerAPI call
#     try:
#         return await crud_modes.create_mode(
#             session,
#             name=payload.name,
#             config_ids=payload.config_ids,
#         )
#     except ValueError as e:
#         raise HTTPException(status_code=400, detail=str(e))


# @router.patch("/{mode_id}", response_model=ModeOut, dependencies=[Depends(apikey_or_jwt_required())])
# async def update_mode(
#     mode_id: str,
#     payload: ModeUpdate,
#     session: AsyncSession = Depends(get_async_session),
# ):
#     try:
#         return await crud_modes.update_mode(
#             session,
#             mode_id,
#             name=payload.name,
#             config_ids=payload.config_ids,
#             is_active=payload.is_active,
#             is_default=payload.is_default,
#         )
#     except NoResultFound as e:
#         raise HTTPException(status_code=404, detail=str(e))
#     except ValueError as e:
#         raise HTTPException(status_code=400, detail=str(e))


# @router.delete("/{mode_id}", response_model=dict, dependencies=[Depends(apikey_or_jwt_required())])
# async def delete_mode(
#     mode_id: str,
#     session: AsyncSession = Depends(get_async_session),
# ):
#     try:
#         await crud_modes.delete_mode(session, mode_id)
#     except NoResultFound as e:
#         raise HTTPException(status_code=404, detail=str(e))
#     except ValueError as e:
#         raise HTTPException(status_code=400, detail=str(e))

#     return {"detail": "Mode deleted successfully"}


@router.post("/{mode_id}/activate", dependencies=[Depends(apikey_or_jwt_required())])
async def activate_mode(
    mode_id: str,
    session: AsyncSession = Depends(get_async_session),
    server_api: AsyncFastAPIServerAPI = Depends(get_async_server_api)
):
    try:
        await crud_modes.get_mode(session, mode_id)
        await server_api.set_active_mode(mode_id)
    except NoResultFound as e:
        raise HTTPException(status_code=422, detail=str(e))


# @router.post("/{mode_id}/logger-configs", response_model=ModeOut, dependencies=[Depends(apikey_or_jwt_required())])
# async def add_configs_to_mode(
#     mode_id: str,
#     config_ids: List[str],
#     session: AsyncSession = Depends(get_async_session),
# ):
#     try:
#         return await crud_modes.assign_configs_to_mode(session, mode_id, config_ids)
#     except NoResultFound as e:
#         raise HTTPException(status_code=404, detail=str(e))
#     except ValueError as e:
#         raise HTTPException(status_code=400, detail=str(e))


# @router.delete("/{mode_id}/logger-configs/{config_id}", response_model=ModeOut, dependencies=[Depends(apikey_or_jwt_required())])
# async def remove_logger_config_from_mode(
#     mode_id: str,
#     config_id: str,
#     session: AsyncSession = Depends(get_async_session),
# ):
#     try:
#         return await crud_modes.remove_logger_config_from_mode(session, mode_id, config_id)
#     except NoResultFound as e:
#         raise HTTPException(status_code=404, detail=str(e))
