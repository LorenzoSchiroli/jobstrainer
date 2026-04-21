from datetime import date
from unittest.mock import patch
import pandas as pd
from retriever.sources.jobspy_source import JobspySource


def _mock_df():
    return pd.DataFrame([
        {
            "title": "Python Engineer",
            "company": "SpyCorp",
            "location": "London, UK",
            "job_url": "https://linkedin.com/jobs/view/123",
            "date_posted": pd.Timestamp("2026-04-19"),
            "site": "linkedin",
        },
        {
            "title": "Ingénieur Python",  # French — should be discarded
            "company": "FrenchCo",
            "location": "Paris",
            "job_url": "https://linkedin.com/jobs/view/456",
            "date_posted": pd.Timestamp("2026-04-19"),
            "site": "linkedin",
        },
        {
            "title": None,  # missing title — should be discarded
            "company": "NullCo",
            "location": "Berlin",
            "job_url": "https://linkedin.com/jobs/view/789",
            "date_posted": None,
            "site": "indeed",
        },
    ])


def test_returns_english_offers():
    with patch("retriever.sources.jobspy_source.scrape_jobs", return_value=_mock_df()):
        results = JobspySource().fetch("python", days=3)

    assert len(results) == 1
    assert results[0].title == "Python Engineer"
    assert results[0].source == "jobspy:linkedin"


def test_returns_empty_on_scrape_error():
    with patch("retriever.sources.jobspy_source.scrape_jobs", side_effect=Exception("blocked")):
        assert JobspySource().fetch("python", days=3) == []
