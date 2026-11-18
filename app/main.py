import tomllib
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute

from app.api import apikeys, auth, examples, profile, users
from app.config import settings
from app.deps import get_current_user

# Load pyproject.toml
pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
with open(pyproject_path, "rb") as f:
    pyproject = tomllib.load(f)

project_name = pyproject["tool"]["poetry"]["name"]
project_version = pyproject["tool"]["poetry"]["version"]


@asynccontextmanager
async def lifespan(_: FastAPI):
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

# Routers registered on the app. list_routes() walks these rather than
# app.routes: from FastAPI 0.137 on, include_router() adds a single
# _IncludedRouter object to app.routes instead of the individual APIRoutes.
# Each router sets its full prefix in APIRouter(prefix=...) and includes no
# sub-routers, so router.routes already carries the complete paths.
INCLUDED_ROUTERS = [
    apikeys.router,
    auth.router,
    examples.router,
    profile.router,
    users.router,
]

for _router in INCLUDED_ROUTERS:
    app.include_router(_router)


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
    for route in (r for router in INCLUDED_ROUTERS for r in router.routes):
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
