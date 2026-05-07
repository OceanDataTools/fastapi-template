import sys
from os.path import dirname, realpath
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import apikey_or_jwt_required
from app.db import cruise_crud as crud_cruise, mode_crud as crud_modes
from sqlalchemy.exc import NoResultFound
from app.deps import get_async_server_api, get_async_session

sys.path.append(dirname(dirname(dirname(dirname(realpath(__file__))))))
# Read in JSON with comments
from logger.utils.read_config import expand_cruise_definition, read_config  # noqa: E402

from async_fastapi_server_api import AsyncFastAPIServerAPI  # noqa: E402

router = APIRouter(prefix="/api/v1/configuration", tags=["Configuration"])

# Root of the OpenRVDAS installation (4 levels up from this file)
_OPENRVDAS_DIR = Path(__file__).resolve().parents[3]
_ALLOWED_ROOTS = {"local", "test"}
_CONFIG_SUFFIXES = {".yaml", ".json"}


@router.get(
    "/files",
    dependencies=[Depends(apikey_or_jwt_required())],
)
async def list_config_files(path: str = Query(default="")) -> dict[str, Any]:
    """List files and directories within allowed roots (local/, test/)."""
    openrvdas = _OPENRVDAS_DIR.resolve()

    if not path:
        entries = [
            {"name": root, "type": "dir", "rel_path": root, "abs_path": None}
            for root in sorted(_ALLOWED_ROOTS)
            if (openrvdas / root).is_dir()
        ]
        return {"path": "", "entries": entries}

    # Validate that the path starts with an allowed root
    parts = Path(path).parts
    if not parts or parts[0] not in _ALLOWED_ROOTS:
        raise HTTPException(
            status_code=400,
            detail=f"Path must start with one of: {', '.join(sorted(_ALLOWED_ROOTS))}",
        )

    target = (openrvdas / path).resolve()

    # Prevent path traversal
    try:
        target.relative_to(openrvdas)
    except ValueError:
        raise HTTPException(status_code=400, detail="Path traversal not allowed")

    if not target.exists():
        raise HTTPException(status_code=404, detail="Path not found")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")

    entries = []
    dirs, files = [], []
    for item in target.iterdir():
        if item.is_dir():
            dirs.append(item)
        elif item.is_file() and item.suffix in _CONFIG_SUFFIXES:
            files.append(item)

    for item in sorted(dirs, key=lambda p: p.name):
        entries.append({
            "name": item.name,
            "type": "dir",
            "rel_path": str(item.relative_to(openrvdas)),
            "abs_path": None,
        })
    for item in sorted(files, key=lambda p: p.name):
        entries.append({
            "name": item.name,
            "type": "file",
            "rel_path": str(item.relative_to(openrvdas)),
            "abs_path": str(item),
        })

    return {"path": path, "entries": entries}


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

    # If the same config file is being reloaded, try to retain the active mode.
    # Capture it now, before load_configuration wipes and recreates all modes.
    previous_mode_id: str | None = None
    try:
        current_cruise = await crud_cruise.get_cruise(session)
        if current_cruise and current_cruise.get("config_filename") == config_filepath:
            try:
                active_mode = await crud_modes.get_active_mode(session)
                previous_mode_id = active_mode["id"] if active_mode else None
            except (NoResultFound, Exception):
                previous_mode_id = None
    except Exception:
        previous_mode_id = None

    try:
        cfg = read_config(config_filepath)
        cfg = expand_cruise_definition(cfg)
        cfg["cruise"]["config_filename"] = config_filepath

        await server_api.load_configuration(cfg)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Restore the previous mode if it still exists in the reloaded config.
    # If it doesn't exist, the default mode (activated by load_configuration) stands.
    if previous_mode_id and previous_mode_id in (cfg.get("modes") or {}):
        await server_api.set_active_mode(previous_mode_id)

    # Record the file's mtime at load time as the change-detection baseline
    try:
        mtime = (_OPENRVDAS_DIR / config_filepath).stat().st_mtime
    except OSError:
        mtime = None
    await crud_cruise.set_config_mtime_baseline(session, mtime)
    await session.commit()

    return str(cfg)
