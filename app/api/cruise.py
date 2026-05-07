from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import cruise_crud as crud_cruise
from app.deps import get_async_session
from app.schemas_openrvdas import CruiseRead

router = APIRouter(prefix="/api/v1/cruise", tags=["Cruise"])

_OPENRVDAS_DIR = Path(__file__).resolve().parents[3]


def _compute_config_file_changed(cruise: dict) -> bool:
    """Compare current file mtime against the stored baseline."""
    filename = cruise.get("config_filename")
    baseline = cruise.get("config_mtime_baseline")
    if not filename or baseline is None:
        return False
    try:
        return (_OPENRVDAS_DIR / filename).stat().st_mtime != baseline
    except OSError:
        return False


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
        config_file_changed=_compute_config_file_changed(cruise),
    )


@router.get("/config-mtime")
async def get_config_mtime(session: AsyncSession = Depends(get_async_session)):
    """Return whether the loaded config file has changed on disk since it was loaded."""
    cruise = await crud_cruise.get_cruise(session)
    if cruise is None or not cruise.get("config_filename"):
        return {"changed": False, "mtime": None}
    config_path = _OPENRVDAS_DIR / cruise["config_filename"]
    try:
        mtime = config_path.stat().st_mtime
    except OSError:
        return {"changed": False, "mtime": None}
    baseline = cruise.get("config_mtime_baseline")
    if baseline is None:
        # First poll after feature rollout — establish baseline silently
        await crud_cruise.set_config_mtime_baseline(session, mtime)
        await session.commit()
        return {"changed": False, "mtime": mtime}
    changed = mtime != baseline
    return {"changed": changed, "mtime": mtime}
