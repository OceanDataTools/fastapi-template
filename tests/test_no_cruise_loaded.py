"""
Behavior when no cruise definition has been loaded yet (e.g. right after a
fresh install). This is a normal state, not an error: LoggerManager polls
the API in a loop and must be able to tell "nothing loaded" apart from a
failure, the way it can with the Django and SQLite ServerAPIs.
"""

import pytest
from unittest.mock import AsyncMock, patch

from app.db import mode_crud as crud_modes


@pytest.fixture(autouse=True)
def _no_modes():
    """Simulate an empty database: no modes, no cruise, nothing cached."""
    with patch.object(crud_modes, "_get", AsyncMock(return_value=None)), \
         patch.object(crud_modes, "list_modes", AsyncMock(return_value=[])):
        yield


@pytest.mark.asyncio
async def test_crud_active_and_default_mode_return_none(db_session):
    assert await crud_modes.get_active_mode(db_session) is None
    assert await crud_modes.get_default_mode(db_session) is None


@pytest.mark.asyncio
async def test_server_api_returns_none_without_cruise():
    from async_fastapi_server_api import AsyncFastAPIServerAPI

    api = AsyncFastAPIServerAPI()
    with patch(
        "async_fastapi_server_api.crud_cruise.get_cruise",
        AsyncMock(return_value=None),
    ):
        assert await api.get_configuration() is None
    assert await api.get_active_mode() is None
    assert await api.get_default_mode() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("which", ["active", "default"])
async def test_mode_endpoints_return_404_not_500(client, which):
    resp = await client.get(f"/api/v1/modes/{which}")
    assert resp.status_code == 404
