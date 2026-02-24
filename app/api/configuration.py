import sys
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import apikey_or_jwt_required
from app.db.session import get_async_session
from app.db import cruise_crud as crud_cruise
from app.db import config_crud as crud_configs
from app.db import logger_crud as crud_loggers
from app.db import mode_crud as crud_modes
from app.deps import get_async_server_api

from os.path import dirname, realpath, basename
sys.path.append(dirname(dirname(dirname(dirname(realpath(__file__))))))
# Read in JSON with comments
from logger.utils.read_config import parse, read_config, expand_cruise_definition  # noqa: E402
from web_backend.async_fastapi_server_api import AsyncFastAPIServerAPI

router = APIRouter(prefix="/api/v1/configuration", tags=["Configuration"])


@router.get(
    "/",
    # response_model=CruiseRead,
    dependencies=[Depends(apikey_or_jwt_required())],
)
async def extract_configuration(
    session: AsyncSession = Depends(get_async_session),
    server_api: AsyncFastAPIServerAPI = Depends(get_async_server_api)
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
    # response_model=CruiseRead,
    dependencies=[Depends(apikey_or_jwt_required())],
)
async def load_configuration(
    config_filepath: str,
    session: AsyncSession = Depends(get_async_session),
    server_api: AsyncFastAPIServerAPI = Depends(get_async_server_api)
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
        # Load the file to memory and parse to a dict. Add the name of
        # the file we've just loaded to the dict.
        cfg = read_config(config_filepath)
        cfg = expand_cruise_definition(cfg)
        cfg['cruise']['config_filename'] = config_filepath

        await server_api.load_configuration(cfg)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # except Exception as e:
        # raise HTTPException(status_code=500, detail=f"Ingest failed: {e}")

    return str(cfg)
    # return CruiseRead(
    #     cruise_id=cruise.id,
    #     start=cruise.start,
    #     end=cruise.end,
    #     config_filename=cruise.config_filename,
    #     config_text=cruise.config_text,
    # )
