import pytest
from unittest.mock import AsyncMock, patch
import backend.opensearch_client as m


async def test_init_creates_index_when_missing(monkeypatch):
    monkeypatch.setenv("OPENSEARCH_URL", "http://localhost:9200")
    mock_client = AsyncMock()
    mock_client.indices.exists.return_value = False
    with patch("backend.opensearch_client.AsyncOpenSearch", return_value=mock_client):
        m._client = None
        await m.init_opensearch()
    mock_client.indices.create.assert_called_once()
    mock_client.transport.perform_request.assert_called_once()


async def test_init_skips_index_creation_when_exists(monkeypatch):
    monkeypatch.setenv("OPENSEARCH_URL", "http://localhost:9200")
    mock_client = AsyncMock()
    mock_client.indices.exists.return_value = True
    with patch("backend.opensearch_client.AsyncOpenSearch", return_value=mock_client):
        m._client = None
        await m.init_opensearch()
    mock_client.indices.create.assert_not_called()


def test_get_opensearch_raises_before_init():
    m._client = None
    with pytest.raises(AssertionError):
        m.get_opensearch()
