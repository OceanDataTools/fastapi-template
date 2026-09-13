import importlib.metadata
import sys
import tomllib
from contextlib import asynccontextmanager
from os.path import dirname, realpath
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute

from app.api import (
    apikeys,
    auth,
    configs,
    configuration,
    connection,
    cruise,
    data_server,
    loggers,
    modes,
    profile,
    test_connection,
    updates,
    users,
)
from app.config import settings
from app.deps import get_current_user
from async_fastapi_server_api import AsyncFastAPIServerAPI

# Load pyproject.toml
pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
with open(pyproject_path, "rb") as f:
    pyproject = tomllib.load(f)

project_name = pyproject["tool"]["poetry"]["name"]

# The displayed version tracks the parent OpenRVDAS project's release, not
# this submodule's own (poetry) version. 3 levels up from this file
# (app/main.py -> app -> web_backend -> OpenRVDAS root) is where an
# OpenRVDAS installation's own `logger` package lives.
sys.path.append(dirname(dirname(dirname(realpath(__file__)))))

try:
    # Available only when running inside an OpenRVDAS installation. Reads
    # the version live from the current git tree where possible, rather
    # than trusting only what was frozen into this venv's dist-info
    # metadata at install time - see that function's docstring in the
    # parent OpenRVDAS repo (logger/utils/read_version.py).
    from logger.utils.read_version import (  # noqa: E402
        get_version as get_openrvdas_version,
    )
except ImportError:

    def get_openrvdas_version() -> str:
        try:
            return importlib.metadata.version("openrvdas")
        except importlib.metadata.PackageNotFoundError:
            return "unknown"


project_version = get_openrvdas_version()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.async_server_api = AsyncFastAPIServerAPI()
    yield


app = FastAPI(
    title=project_name,
    version=project_version,
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(apikeys.router)


@app.get("/api/v1/version", tags=["Version"])
async def get_version():
    return {"version": project_version}


@app.get("/api/v1/apikeys/routes", tags=["API Keys"])
async def list_routes(current_user=Depends(get_current_user)):

    EXCLUDED_TAGS = ["API Keys", "Users", "Auth", "Profile"]

    def has_apikey_dependency(route: APIRoute) -> bool:
        for dep in route.dependant.dependencies:
            call_obj = dep.call
            if callable(call_obj) and call_obj.__name__ in (
                "apikey_checker",
                "apikey_or_jwt_checker",
            ):
                return True
        return False

    routes = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue

        # Skip routes with excluded tags
        route_tags = set(getattr(route, "tags", []) or [])
        if route_tags.intersection(EXCLUDED_TAGS):
            continue

        # Skip routes that don't require API key auth
        if not has_apikey_dependency(route):
            continue

        routes.append(
            {
                "route": route.path,
                "methods": list(route.methods),
                "name": route.name,
                "summary": route.summary,
            }
        )

    return routes


app.include_router(auth.router)
# app.include_router(examples.router)
app.include_router(profile.router)
app.include_router(users.router)

# OpenRVDAS routes
app.include_router(data_server.router)
app.include_router(configuration.router)
app.include_router(connection.router)
app.include_router(cruise.router)
app.include_router(modes.router)
app.include_router(loggers.router)
app.include_router(configs.router)
app.include_router(updates.router)
app.include_router(test_connection.router)
