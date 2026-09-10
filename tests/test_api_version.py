import importlib.metadata
from unittest.mock import patch

import pytest

from app.main import get_openrvdas_version


@pytest.mark.asyncio
async def test_get_version_endpoint_returns_project_version(client):
    response = await client.get("/api/v1/version")
    assert response.status_code == 200

    import app.main

    assert response.json() == {"version": app.main.project_version}


def test_get_openrvdas_version_reads_installed_package_metadata():
    with patch("importlib.metadata.version", return_value="2.6.1") as mock_version:
        assert get_openrvdas_version() == "2.6.1"
        mock_version.assert_called_once_with("openrvdas")


def test_get_openrvdas_version_falls_back_to_unknown():
    with patch("importlib.metadata.version", side_effect=importlib.metadata.PackageNotFoundError):
        assert get_openrvdas_version() == "unknown"
