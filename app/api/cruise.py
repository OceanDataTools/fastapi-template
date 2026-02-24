from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import NoResultFound

from app.auth import apikey_or_jwt_required
from app.db.session import get_async_session
from app.db import cruise_crud as crud_cruise
from app.schemas_openrvdas import CruiseRead, CruiseCreate, CruiseUpdate

router = APIRouter(prefix="/api/v1/cruise", tags=["Cruise"])

@router.get("/", response_model=CruiseRead)
async def get_cruise(session: AsyncSession = Depends(get_async_session)):
    """
    Retrieve the singleton Cruise record.
    """
    cruise = await crud_cruise.get_cruise(session)
    if cruise is None:
        raise HTTPException(status_code=404, detail="No Cruise record found")
    return CruiseRead(
        cruise_id=cruise.id,
        start=cruise.start,
        end=cruise.end,
        config_filename=cruise.config_filename,
    )


# @router.post("/", response_model=CruiseRead, dependencies=[Depends(apikey_or_jwt_required())])
# async def upsert_cruise(
#     cruise_in: CruiseCreate,
#     session: AsyncSession = Depends(get_async_session),
# ):
#     """
#     Create or update the singleton Cruise record.
#     """
#     try:
#         cruise = await crud_cruise.create_or_update_cruise(
#             session,
#             cruise_id=cruise_in.cruise_id,
#             start=cruise_in.start,
#             end=cruise_in.end,
#             config_filename=cruise_in.config_filename,
#         )
#     except ValueError as e:
#         raise HTTPException(status_code=400, detail=str(e))

#     return CruiseRead(
#         cruise_id=cruise.id,
#         start=cruise.start,
#         end=cruise.end,
#         config_filename=cruise.config_filename,
#     )


# @router.patch("/", response_model=CruiseRead, dependencies=[Depends(apikey_or_jwt_required())])
# async def update_cruise(
#     cruise_in: CruiseUpdate,
#     session: AsyncSession = Depends(get_async_session),
# ):
#     """
#     Partially update the singleton Cruise record.
#     Only provided fields are updated.
#     """
#     cruise = await crud_cruise.get_cruise(session)
#     if cruise is None:
#         raise HTTPException(status_code=404, detail="No Cruise record found")

#     # Merge updates
#     cruise_id = cruise.id  # Keep the existing singleton ID
#     start = cruise_in.start if cruise_in.start is not None else cruise.start
#     end = cruise_in.end if cruise_in.end is not None else cruise.end
#     config_filename = cruise_in.config_filename if cruise_in.config_filename is not None else cruise.config_filename

#     try:
#         cruise = await crud_cruise.create_or_update_cruise(
#             session,
#             cruise_id=cruise_id,
#             start=start,
#             end=end,
#             config_filename=config_filename,
#         )
#     except ValueError as e:
#         raise HTTPException(status_code=400, detail=str(e))

#     return CruiseRead(
#         cruise_id=cruise.id,
#         start=cruise.start,
#         end=cruise.end,
#         config_filename=cruise.config_filename,
#         config_text=cruise.config_text,
#     )


# @router.delete("/", response_model=dict, dependencies=[Depends(apikey_or_jwt_required())])
# async def delete_cruise(session: AsyncSession = Depends(get_async_session)):
#     """
#     Delete the singleton Cruise record.
#     """
#     try:
#         await crud_cruise.delete_cruise(session)
#     except NoResultFound as e:
#         raise HTTPException(status_code=404, detail=str(e))

#     return {"detail": "Cruise record deleted successfully"}
