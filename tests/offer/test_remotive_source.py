from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from offer.scraping.sources.remotive_source import RemotiveSource

_recent = (datetime.now() - timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%S")
_old = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")

MOCK_RESPONSE = {
    "jobs": [
        {
            "title": "Senior Python Developer",
            "company_name": "Remote Inc",
            "url": "https://remotive.com/remote-jobs/python-dev-123",
            "candidate_required_location": "Europe",
            "publication_date": _recent,
        },
        {
            "title": "Développeur Python",  # French — should be discarded
            "company_name": "FrenchCo",
            "url": "https://remotive.com/remote-jobs/dev-456",
            "candidate_required_location": "France",
            "publication_date": _recent,
        },
        {
            "title": "Python Engineer",
            "company_name": "OldRemote",
            "url": "https://remotive.com/remote-jobs/py-789",
            "candidate_required_location": "Worldwide",
            "publication_date": _old,  # too old — should be filtered out
        },
    ]
}


def _mock_get(response):
    mock = MagicMock()
    mock.json.return_value = response
    mock.raise_for_status = MagicMock()
    return mock


def test_returns_matching_english_offers_within_hours():
    with patch("offer.scraping.sources.remotive_source.requests.get", return_value=_mock_get(MOCK_RESPONSE)):
        results = RemotiveSource().fetch("python", hours=72)

    assert len(results) == 1
    assert results[0].title == "Senior Python Developer"
    assert results[0].source == "remotive"


def test_returns_empty_on_error():
    with patch("offer.scraping.sources.remotive_source.requests.get", side_effect=Exception("timeout")):
        assert RemotiveSource().fetch("python", hours=72) == []
