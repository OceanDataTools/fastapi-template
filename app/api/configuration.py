import sys

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import apikey_or_jwt_required
from app.db.session import get_async_session
# from app.db import ingest as crud_ingest
# from app.schemas_openrvdas import CruiseRead

from os.path import dirname, realpath
sys.path.append(dirname(dirname(dirname(dirname(realpath(__file__))))))
# Read in JSON with comments
from logger.utils.read_config import parse, read_config, expand_cruise_definition  # noqa: E402

router = APIRouter(prefix="/api/v1/configuration", tags=["Configuration"])


@router.get(
    "/",
    # response_model=CruiseRead,
    dependencies=[Depends(apikey_or_jwt_required())],
)
async def ingest_configuration(
    # config_file: UploadFile = File(...),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Ingest an OpenRVDAS configuration file and create/update:

    * Cruise (singleton)
    * Modes
    * Loggers
    * LoggerConfigs

    The operation is performed transactionally.
    """

    return {'status': 'ok'}
    # if config_file.content_type not in ("application/x-yaml", "text/yaml", "text/plain"):
    #     raise HTTPException(status_code=400, detail="Configuration file must be YAML")

    # try:
    #     # Load the file to memory and parse to a dict. Add the name of
    #     # the file we've just loaded to the dict.
    #     config = read_config(config_file)
    #     config = expand_cruise_definition(config)

    #     # cruise = await crud_ingest.ingest_configuration_file(
    #     #     session=session,
    #     #     filename=config_file.filename,
    #     #     text=contents.decode("utf-8"),
    #     # )
    # except ValueError as e:
    #     raise HTTPException(status_code=400, detail=str(e))
    # except Exception as e:
    #     raise HTTPException(status_code=500, detail=f"Ingest failed: {e}")

    # return config
    # return CruiseRead(
    #     cruise_id=cruise.id,
    #     start=cruise.start,
    #     end=cruise.end,
    #     config_filename=cruise.config_filename,
    #     config_text=cruise.config_text,
    # )
