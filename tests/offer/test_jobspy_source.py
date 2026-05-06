from datetime import date
from unittest.mock import patch
import pandas as pd
from offer.scraping.sources.jobspy_source import JobspySource


def _linkedin_df():
    return pd.DataFrame([
        {
            "title": "Python Engineer",
            "company": "SpyCorp",
            "location": "London, UK",
            "job_url": "https://linkedin.com/jobs/view/123",
            "date_posted": pd.Timestamp("2026-04-19"),
            "site": "linkedin",
            "description": None,
        },
        {
            "title": "Ingénieur Python",  # French — should be discarded
            "company": "FrenchCo",
            "location": "Paris",
            "job_url": "https://linkedin.com/jobs/view/456",
            "date_posted": pd.Timestamp("2026-04-19"),
            "site": "linkedin",
            "description": None,
        },
    ])


def _indeed_df():
    return pd.DataFrame([
        {
            "title": None,  # missing title — should be discarded
            "company": "NullCo",
            "location": "Berlin",
            "job_url": "https://indeed.com/jobs/789",
            "date_posted": None,
            "site": "indeed",
            "description": None,
        },
    ])


def test_returns_english_offers_from_all_calls():
    def side_effect(**kwargs):
        if "linkedin" in kwargs.get("site_name", []):
            return _linkedin_df()
        return _indeed_df()

    with patch("offer.scraping.sources.jobspy_source.scrape_jobs", side_effect=side_effect):
        results = JobspySource().fetch("python", hours=72)

    titles = [r.title for r in results]
    assert "Python Engineer" in titles
    assert "Ingénieur Python" not in titles
    assert all(r.source.startswith("jobspy:") for r in results)


def test_linkedin_failure_does_not_block_indeed():
    call_count = 0

    def side_effect(**kwargs):
        nonlocal call_count
        call_count += 1
        if "linkedin" in kwargs.get("site_name", []):
            raise Exception("blocked")
        return _indeed_df()

    with patch("offer.scraping.sources.jobspy_source.scrape_jobs", side_effect=side_effect):
        results = JobspySource().fetch("python", hours=72)

    assert results == []  # indeed df has no valid titles


def test_returns_empty_when_all_fail():
    with patch("offer.scraping.sources.jobspy_source.scrape_jobs", side_effect=Exception("blocked")):
        assert JobspySource().fetch("python", hours=72) == []


def test_description_is_stripped_of_html():
    mock_df = pd.DataFrame([{
        "title": "Python Engineer",
        "company": "SpyCorp",
        "location": "London, UK",
        "job_url": "https://linkedin.com/jobs/view/123",
        "date_posted": pd.Timestamp("2026-04-19"),
        "site": "linkedin",
        "description": "<p>Build <b>microservices</b> in Python.</p>",
    }])

    with patch("offer.scraping.sources.jobspy_source.scrape_jobs", return_value=mock_df):
        results = JobspySource().fetch("python", hours=72)

    assert len(results) >= 1
    matching = [r for r in results if r.title == "Python Engineer"]
    assert len(matching) >= 1
    assert "microservices" in matching[0].description
    assert "<" not in matching[0].description
