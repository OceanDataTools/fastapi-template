from typing import List, Union

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel

from app.auth import apikey_or_jwt_required, apikey_required, jwt_required


class ExampleSchema(BaseModel):
    status: str


class ExamplePostSchema(BaseModel):
    data_1: str
    data_2: str


router = APIRouter(prefix="/api/v1/examples", tags=["Example Auth Routes"])


@router.get("", response_model=ExampleSchema)
async def no_auth_route():
    return {"status": "ok"}


@router.get(
    "/any_auth",
    response_model=ExampleSchema,
    dependencies=[Depends(apikey_or_jwt_required())],
)
async def any_auth_route():
    return {"status": "ok"}


@router.get(
    "/jwt_auth", response_model=ExampleSchema, dependencies=[Depends(jwt_required())]
)
async def jwt_auth_route():
    return {"status": "ok"}


@router.get(
    "/admin_auth",
    response_model=ExampleSchema,
    dependencies=[Depends(jwt_required(required_roles=tuple(["admin"])))],
)
async def admin_auth_route():
    return {"status": "ok"}


@router.get(
    "/apikey_auth",
    response_model=ExampleSchema,
    dependencies=[Depends(apikey_required())],
)
async def apikey_auth_route():
    return {"status": "ok"}


@router.post(
    "/post_auth",
    response_model=ExampleSchema,
    dependencies=[Depends(apikey_or_jwt_required())],
)
async def post_with_auth(
    post_data: Union[ExamplePostSchema, List[ExamplePostSchema]] = Body(...),
):
    if isinstance(post_data, ExamplePostSchema):
        post_data = [post_data]

    return {"status": "ok"}
