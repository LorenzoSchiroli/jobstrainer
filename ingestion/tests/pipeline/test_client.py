from unittest.mock import MagicMock, patch
import pytest
from ingestion.offer.models import EnrichedOffer
from ingestion.client import post_job, post_company


@pytest.fixture(autouse=True)
def backend_url(monkeypatch):
    monkeypatch.setenv("BACKEND_URL", "http://localhost:8000")


def _resp(status: int, body: dict) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body
    return r


def _offer(**kwargs) -> EnrichedOffer:
    defaults = dict(
        title="ML Engineer",
        company="Acme Corp",
        location="Berlin",
        url="https://example.com/job/1",
        source="jobspy",
        posted_at=None,
    )
    return EnrichedOffer(**{**defaults, **kwargs})


def test_post_job_renames_company_to_company_name():
    with patch("ingestion.client.requests.post") as mock_post:
        mock_post.return_value = _resp(201, {"id": "abc"})
        post_job(_offer())

    payload = mock_post.call_args.kwargs["json"]
    assert payload["company_name"] == "Acme Corp"
    assert "company" not in payload


def test_post_job_returns_status_and_body():
    with patch("ingestion.client.requests.post") as mock_post:
        mock_post.return_value = _resp(200, {"id": "abc", "title": "ML Engineer"})
        status, body = post_job(_offer())

    assert status == 200
    assert body["id"] == "abc"


def test_post_job_hits_correct_url():
    with patch("ingestion.client.requests.post") as mock_post:
        mock_post.return_value = _resp(201, {})
        post_job(_offer())

    assert mock_post.call_args.args[0] == "http://localhost:8000/jobs"


def test_post_company_sends_dict_and_returns_status():
    with patch("ingestion.client.requests.post") as mock_post:
        mock_post.return_value = _resp(201, {"id": "xyz", "name": "Acme"})
        status, body = post_company({"name": "Acme"})

    assert status == 201
    assert mock_post.call_args.kwargs["json"] == {"name": "Acme"}


def test_post_company_hits_correct_url():
    with patch("ingestion.client.requests.post") as mock_post:
        mock_post.return_value = _resp(200, {})
        post_company({"name": "Acme"})

    assert mock_post.call_args.args[0] == "http://localhost:8000/companies"
