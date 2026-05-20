"""
Unit tests for AsyncFastAPIServerAPI.get_status — covering the Bug #4 fix.

When since_timestamp is None, get_latest_status_per_logger returns
{logger_id: single_dict} (not a list). The old code iterated dict values
as if they were lists, yielding dict keys instead of state objects.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone


@pytest.mark.asyncio
async def test_get_status_none_timestamp_returns_list_not_keys():
    """get_status(None) must flatten {id: dict} into [dict], not [key, key, ...]."""
    from async_fastapi_server_api import AsyncFastAPIServerAPI

    fake_state = {
        "logger_id": "test-logger",
        "config_id": "test-logger->on",
        "running": True,
        "timestamp": datetime.now(timezone.utc),
    }
    # get_latest_status_per_logger returns {logger_id: single_state_dict}
    fake_latest = {"test-logger": fake_state}

    reformatted_sentinel = {"reformatted": True}

    api = AsyncFastAPIServerAPI()

    with patch.object(
        type(api).__mro__[0],
        "_with_session",
        new_callable=AsyncMock,
    ) as mock_with_session:
        # Simulate what _inner would do: call the two CRUDs and return.
        # We patch at the CRUD level instead so _inner runs for real.
        with patch(
            "async_fastapi_server_api.crud_logger_config_state"
        ) as mock_crud:
            mock_crud.get_latest_status_per_logger = AsyncMock(return_value=fake_latest)
            mock_crud.get_status_since_per_logger = AsyncMock(return_value={})
            mock_crud.reformat_status_by_timestamp_with_names = AsyncMock(
                return_value=reformatted_sentinel
            )

            # Run the actual _inner function by letting _with_session call it.
            async def real_with_session(inner_fn, *args, **kwargs):
                from app.db.session import AsyncSessionLocal
                async with AsyncSessionLocal() as session:
                    return await inner_fn(session)

            mock_with_session.side_effect = real_with_session

            result = await api.get_status(since_timestamp=None)

    # reformat was called with a list containing the single dict — not its keys
    call_args = mock_crud.reformat_status_by_timestamp_with_names.call_args
    passed_list = call_args[0][0]

    assert isinstance(passed_list, list), "Expected a list passed to reformat"
    assert passed_list == [fake_state], (
        f"Expected [{fake_state!r}], got {passed_list!r}. "
        "If you see string keys here, the dict-vs-list bug is back."
    )


@pytest.mark.asyncio
async def test_get_status_with_timestamp_flattens_lists():
    """get_status(timestamp) must flatten {id: [list]} correctly."""
    from async_fastapi_server_api import AsyncFastAPIServerAPI

    s1 = {"logger_id": "l1", "config_id": "c1", "running": True}
    s2 = {"logger_id": "l2", "config_id": "c2", "running": False}
    fake_since = {"l1": [s1], "l2": [s2]}

    api = AsyncFastAPIServerAPI()

    with patch("async_fastapi_server_api.crud_logger_config_state") as mock_crud:
        mock_crud.get_status_since_per_logger = AsyncMock(return_value=fake_since)
        mock_crud.reformat_status_by_timestamp_with_names = AsyncMock(return_value={})

        async def real_with_session(inner_fn, *args, **kwargs):
            from app.db.session import AsyncSessionLocal
            async with AsyncSessionLocal() as session:
                return await inner_fn(session)

        api._with_session = real_with_session

        since = datetime(2020, 1, 1, tzinfo=timezone.utc)
        await api.get_status(since_timestamp=since)

    call_args = mock_crud.reformat_status_by_timestamp_with_names.call_args
    passed_list = call_args[0][0]
    assert set(id(x) for x in passed_list) == {id(s1), id(s2)}
