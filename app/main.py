import tomllib
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute

from app.api import apikeys, auth, configuration, configs, cruise, data_server, examples, loggers, modes, profile, updates, users
from app.config import settings
from app.deps import get_current_user
from async_fastapi_server_api import AsyncFastAPIServerAPI

# Load pyproject.toml
pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
with open(pyproject_path, "rb") as f:
    pyproject = tomllib.load(f)

project_name = pyproject["tool"]["poetry"]["name"]
project_version = pyproject["tool"]["poetry"]["version"]


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
app.include_router(configuration.router)
app.include_router(cruise.router)
app.include_router(modes.router)
app.include_router(loggers.router)
app.include_router(configs.router)
app.include_router(data_server.router)
app.include_router(updates.router)
