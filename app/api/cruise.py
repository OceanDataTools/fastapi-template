from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import cruise_crud as crud_cruise
from app.deps import get_async_session
from app.schemas_openrvdas import CruiseRead

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
        cruise_id=cruise["id"],
        start=cruise["start"],
        end=cruise["end"],
        config_filename=cruise["config_filename"],
    )
