import logging
import sys
from os.path import dirname, normpath, realpath
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import apikey_or_jwt_required
from app.db import cruise_crud as crud_cruise
from app.db import mode_crud as crud_modes
from app.deps import get_async_server_api, get_async_session

sys.path.append(dirname(dirname(dirname(dirname(realpath(__file__))))))

from async_fastapi_server_api import AsyncFastAPIServerAPI  # noqa: E402

try:
    # Available only when running inside an OpenRVDAS installation.
    from logger.utils.check_parse_format import check_parse_format  # noqa: E402
    from logger.utils.read_config import (  # noqa: E402
        expand_cruise_definition,
        expand_templates,
        read_config,
    )

    _OPENRVDAS_AVAILABLE = True
except ImportError:
    _OPENRVDAS_AVAILABLE = False


def _require_openrvdas() -> None:
    if not _OPENRVDAS_AVAILABLE:
        raise HTTPException(
            status_code=503, detail="OpenRVDAS is not installed on this host"
        )


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

    # Collapse any '..' components without following symlinks, then verify
    # the result is still within the openrvdas root.  This blocks traversal
    # attacks like local/../../etc/passwd while still allowing local/ itself
    # to be a symlink pointing outside _OPENRVDAS_DIR.
    normalized = Path(normpath(openrvdas / path))
    try:
        normalized.relative_to(openrvdas)
    except ValueError:
        raise HTTPException(status_code=400, detail="Path traversal not allowed")

    # Resolve now to follow symlinks for filesystem operations.
    target = normalized.resolve()

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

    # Use the logical (pre-resolve) path for rel_path so it stays within the
    # allowed root even when the physical path resolves outside _OPENRVDAS_DIR.
    logical_dir = normalized.relative_to(openrvdas)
    for item in sorted(dirs, key=lambda p: p.name):
        entries.append(
            {
                "name": item.name,
                "type": "dir",
                "rel_path": str(logical_dir / item.name),
                "abs_path": None,
            }
        )
    for item in sorted(files, key=lambda p: p.name):
        entries.append(
            {
                "name": item.name,
                "type": "file",
                "rel_path": str(logical_dir / item.name),
                "abs_path": str(item),
            }
        )

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


def _resolve_config_path(config_filepath: str) -> Path:
    """Validate and resolve a config file path, raising HTTPException on bad input.

    Accepts both absolute paths (must be inside the OpenRVDAS root) and relative
    paths (must start with an allowed root such as 'local/' or 'test/').
    """
    openrvdas = _OPENRVDAS_DIR.resolve()
    p = Path(config_filepath)

    if p.is_absolute():
        try:
            p = p.relative_to(openrvdas)
        except ValueError:
            raise HTTPException(status_code=400, detail="Path traversal not allowed")

    parts = p.parts
    if not parts or parts[0] not in _ALLOWED_ROOTS:
        raise HTTPException(
            status_code=400,
            detail=f"Path must start with one of: {', '.join(sorted(_ALLOWED_ROOTS))}",
        )
    target = (openrvdas / p).resolve()
    try:
        target.relative_to(openrvdas)
    except ValueError:
        raise HTTPException(status_code=400, detail="Path traversal not allowed")
    if not target.exists():
        raise HTTPException(status_code=404, detail="Config file not found")
    return target


@router.post(
    "/preview",
    dependencies=[Depends(apikey_or_jwt_required())],
)
async def preview_configuration(config_filepath: str) -> dict[str, Any]:
    """Parse and expand a config file without writing to the database.

    Returns the processed config dict plus any errors and warnings captured
    from the read_config / expand_cruise_definition pipeline so the UI can
    show the user what would be applied and gate the Apply button on zero errors.
    """
    target = _resolve_config_path(config_filepath)
    _require_openrvdas()

    errors: list[str] = []
    warnings: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            msg = record.getMessage()
            if record.levelno >= logging.ERROR:
                errors.append(msg)
            elif record.levelno >= logging.WARNING:
                warnings.append(msg)

    handler = _Capture()
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    cfg: dict[str, Any] = {}
    try:
        cfg = read_config(str(target))
        if cfg:
            cfg = expand_cruise_definition(cfg, errors=errors)
    except Exception as e:
        errors.append(str(e))
    finally:
        root_logger.removeHandler(handler)

    return {"config": cfg, "errors": errors, "warnings": warnings}


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
        target = _resolve_config_path(config_filepath)
        _require_openrvdas()
        cfg = read_config(str(target))
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
        mtime = target.stat().st_mtime
    except OSError:
        mtime = None
    await crud_cruise.set_config_mtime_baseline(session, mtime)
    await session.commit()

    return str(cfg)


class _RenderTemplateRequest(BaseModel):
    template_yaml: str
    config_yaml: str


@router.post(
    "/render-template",
    dependencies=[Depends(apikey_or_jwt_required())],
)
async def render_template(body: _RenderTemplateRequest) -> dict[str, Any]:
    """Merge two YAML snippets and expand any template references.

    ``template_yaml`` should contain ``logger_templates``, ``config_templates``,
    and/or ``variables`` keys.  ``config_yaml`` should contain a ``loggers``
    key whose entries reference those templates.  The two dicts are merged and
    passed through ``expand_templates()``.
    """
    _require_openrvdas()
    errors: list[str] = []
    warnings: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            msg = record.getMessage()
            if record.levelno >= logging.ERROR:
                errors.append(msg)
            elif record.levelno >= logging.WARNING:
                warnings.append(msg)

    handler = _Capture()
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    result: dict[str, Any] = {}
    try:
        template_dict = yaml.safe_load(body.template_yaml) or {}
        config_dict = yaml.safe_load(body.config_yaml) or {}
        if not isinstance(template_dict, dict):
            raise ValueError("Template YAML must be a mapping")
        if not isinstance(config_dict, dict):
            raise ValueError("Config YAML must be a mapping")
        merged = {**template_dict, **config_dict}
        result = expand_templates(merged, errors=errors)
    except Exception as e:
        errors.append(str(e))
    finally:
        root_logger.removeHandler(handler)

    return {"result": result, "errors": errors, "warnings": warnings}


@router.post(
    "/verify-parser",
    dependencies=[Depends(apikey_or_jwt_required())],
)
async def verify_parser_format(
    format_string: str,
    raw_string: str,
) -> dict[str, Any]:
    """Check whether a PyPi parse format string matches a raw data string.

    Returns:
      - full_match: True if the entire string matched
      - parsed: dict of field name -> value for matched fields
      - max_span: character index in raw_string where the partial match ends (None on full match or no match)
      - partial_format: the portion of format_string that produced a partial match (None otherwise)
    """
    _require_openrvdas()
    try:
        parsed, max_span, partial_format = check_parse_format(format_string, raw_string)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    if parsed is None:
        return {
            "full_match": False,
            "parsed": {},
            "max_span": None,
            "partial_format": None,
        }

    return {
        "full_match": max_span is None,
        "parsed": parsed,
        "max_span": max_span,
        "partial_format": partial_format,
    }
