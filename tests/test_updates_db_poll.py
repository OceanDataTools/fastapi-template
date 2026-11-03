"""
_db_poll_loop must push "update" once on connect and then only when the
LastUpdate timestamp changes - including on a fresh install, where there is
no LastUpdate row at all and the timestamp reads as None on every poll.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api import updates


class _FakeSession:
    def __init__(self, timestamps):
        self._timestamps = timestamps

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, _stmt):
        ts = self._timestamps.pop(0) if len(self._timestamps) > 1 else self._timestamps[0]
        row = None if ts is None else MagicMock(timestamp=ts)
        result = MagicMock()
        result.scalar_one_or_none.return_value = row
        return result


async def _run_loop(timestamps, polls):
    """Run _db_poll_loop for `polls` iterations; return messages sent."""
    websocket = MagicMock()
    websocket.send_json = AsyncMock()
    calls = 0

    async def fake_sleep(_seconds):
        nonlocal calls
        calls += 1
        if calls >= polls:
            raise asyncio.CancelledError

    session = _FakeSession(list(timestamps))
    with patch.object(updates, "AsyncSessionLocal", lambda: session), patch.object(
        updates.asyncio, "sleep", fake_sleep
    ):
        with pytest.raises(asyncio.CancelledError):
            await updates._db_poll_loop(websocket)
    return [c.args[0] for c in websocket.send_json.await_args_list]


@pytest.mark.asyncio
async def test_no_last_update_row_sends_update_only_once():
    sent = await _run_loop([None], polls=10)
    assert sent == [{"type": "update"}]


@pytest.mark.asyncio
async def test_sends_update_when_timestamp_changes():
    sent = await _run_loop([None, None, 1, 1, 2, 2], polls=6)
    assert sent == [{"type": "update"}] * 3
