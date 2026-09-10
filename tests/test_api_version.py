import tomllib
from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_get_version_matches_openrvdas_pyproject(client):
    response = await client.get("/api/v1/version")
    assert response.status_code == 200

    openrvdas_pyproject_path = (
        Path(__file__).parent.parent.parent / "pyproject.toml"
    )
    with open(openrvdas_pyproject_path, "rb") as f:
        expected_version = tomllib.load(f)["project"]["version"]

    assert response.json() == {"version": expected_version}
