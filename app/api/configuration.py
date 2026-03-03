import sys
from os.path import dirname, realpath

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import apikey_or_jwt_required
from app.deps import get_async_server_api, get_async_session

sys.path.append(dirname(dirname(dirname(dirname(realpath(__file__))))))
# Read in JSON with comments
from logger.utils.read_config import expand_cruise_definition, read_config  # noqa: E402

from async_fastapi_server_api import AsyncFastAPIServerAPI  # noqa: E402

router = APIRouter(prefix="/api/v1/configuration", tags=["Configuration"])


@router.get(
    "/",
    dependencies=[Depends(apikey_or_jwt_required())],
)
async def extract_configuration(
    session: AsyncSession = Depends(get_async_session),
    server_api: AsyncFastAPIServerAPI = Depends(get_async_server_api),
):
    try:
        cfg = await server_api.get_configuration()
        return cfg
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ingest failed: {e}")


@router.post(
    "/",
    dependencies=[Depends(apikey_or_jwt_required())],
)
async def load_configuration(
    config_filepath: str,
    session: AsyncSession = Depends(get_async_session),
    server_api: AsyncFastAPIServerAPI = Depends(get_async_server_api),
):
    """
    Ingest an OpenRVDAS configuration file and create/update:

    * Cruise (singleton)
    * Modes
    * Loggers
    * Configs

    The operation is performed transactionally.
    """

    try:
        cfg = read_config(config_filepath)
        cfg = expand_cruise_definition(cfg)
        cfg["cruise"]["config_filename"] = config_filepath

        await server_api.load_configuration(cfg)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return str(cfg)
