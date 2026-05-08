from datetime import date
from unittest.mock import MagicMock, patch

from offer.models import EnrichedOffer, OfferExtraction
from offer.offer import enrich_all, _linkedin_job_id
from offer.scraping.models import JobOffer


def _make_offer(title: str, description: str | None = "Short snippet.", source: str = "test") -> JobOffer:
    return JobOffer(
        title=title,
        company="Acme",
        location="Berlin",
        url=f"https://example.com/{title}",
        source=source,
        posted_at=date(2024, 1, 15),
        description=description,
    )


def _make_linkedin_offer(title: str, job_id: str = "1234567890") -> JobOffer:
    return JobOffer(
        title=title,
        company="Acme",
        location="Berlin",
        url=f"https://www.linkedin.com/jobs/view/some-engineer-{job_id}",
        source="jobspy:linkedin",
        posted_at=date(2024, 1, 15),
        description=None,
    )


def _patch_fetch(return_value=None):
    return patch("offer.offer._fetch_description_from_url", return_value=return_value)


def _patch_linkedin_scraper(scraper=None):
    return patch("offer.offer.make_linkedin_scraper", return_value=scraper or MagicMock())


# --- _linkedin_job_id ---

def test_linkedin_job_id_extracts_numeric_id():
    url = "https://www.linkedin.com/jobs/view/senior-python-engineer-1234567890"
    assert _linkedin_job_id(url) == "1234567890"


def test_linkedin_job_id_works_without_slug():
    assert _linkedin_job_id("https://www.linkedin.com/jobs/view/1234567890") == "1234567890"


def test_linkedin_job_id_returns_none_for_non_numeric():
    assert _linkedin_job_id("https://example.com/jobs/some-role") is None


# --- enrich_all ---

def test_enrich_all_returns_enriched_offers():
    offers = [_make_offer("Python Engineer"), _make_offer("Data Scientist")]
    extraction = OfferExtraction(employment_type="full-time", seniority="senior")

    with patch("offer.offer.scrape", return_value=offers):
        with patch("offer.offer.parse", return_value=extraction):
            with _patch_fetch():
                with _patch_linkedin_scraper():
                    results = enrich_all("python", hours=72, client=MagicMock())

    assert len(results) == 2
    assert all(isinstance(r, EnrichedOffer) for r in results)
    assert results[0].title == "Python Engineer"
    assert results[0].employment_type == "full-time"
    assert results[0].seniority == "senior"
    assert results[1].title == "Data Scientist"


def test_enrich_all_returns_empty_list_when_no_offers():
    with patch("offer.offer.scrape", return_value=[]):
        results = enrich_all("python", hours=72, client=MagicMock())

    assert results == []


def test_enrich_all_calls_parse_once_per_offer():
    offers = [_make_offer("Job A"), _make_offer("Job B"), _make_offer("Job C")]

    with patch("offer.offer.scrape", return_value=offers):
        with patch("offer.offer.parse", return_value=OfferExtraction()) as mock_parse:
            with _patch_fetch():
                with _patch_linkedin_scraper():
                    enrich_all("python", hours=72, client=MagicMock())

    assert mock_parse.call_count == 3


def test_enrich_all_preserves_offer_identity_fields():
    offer = _make_offer("ML Engineer")
    offer.company = "DeepMind"
    offer.location = "London"
    offer.source = "remotive"
    offer.posted_at = date(2024, 3, 10)

    with patch("offer.offer.scrape", return_value=[offer]):
        with patch("offer.offer.parse", return_value=OfferExtraction()):
            with _patch_fetch():
                with _patch_linkedin_scraper():
                    results = enrich_all("ml", hours=72, client=MagicMock())

    assert results[0].company == "DeepMind"
    assert results[0].location == "London"
    assert results[0].source == "remotive"
    assert results[0].posted_at == date(2024, 3, 10)


def test_enrich_all_handles_offers_with_no_description():
    offer = _make_offer("Python Dev", description=None)

    with patch("offer.offer.scrape", return_value=[offer]):
        with patch("offer.offer.parse", return_value=OfferExtraction()):
            with _patch_fetch():
                with _patch_linkedin_scraper():
                    results = enrich_all("python", hours=72, client=MagicMock())

    assert len(results) == 1
    assert results[0].employment_type is None


def test_enrich_all_fetches_description_when_missing():
    offer = _make_offer("Python Dev", description=None)

    with patch("offer.offer.scrape", return_value=[offer]):
        with patch("offer.offer.parse", return_value=OfferExtraction()):
            with _patch_fetch("Fetched full description.") as mock_fetch:
                with _patch_linkedin_scraper():
                    enrich_all("python", hours=72, client=MagicMock())

    mock_fetch.assert_called_once_with(offer.url)


def test_enrich_all_fetches_description_when_short():
    offer = _make_offer("Python Dev", description="Short snippet…")

    with patch("offer.offer.scrape", return_value=[offer]):
        with patch("offer.offer.parse", return_value=OfferExtraction()):
            with _patch_fetch("Full description text.") as mock_fetch:
                with _patch_linkedin_scraper():
                    enrich_all("python", hours=72, client=MagicMock())

    mock_fetch.assert_called_once_with(offer.url)


def test_enrich_all_skips_fetch_when_description_is_long():
    long_desc = "x" * 600
    offer = _make_offer("Python Dev", description=long_desc)

    with patch("offer.offer.scrape", return_value=[offer]):
        with patch("offer.offer.parse", return_value=OfferExtraction()):
            with _patch_fetch() as mock_fetch:
                with _patch_linkedin_scraper():
                    enrich_all("python", hours=72, client=MagicMock())

    mock_fetch.assert_not_called()


def test_enrich_all_uses_linkedin_scraper_for_linkedin_offers():
    offer = _make_linkedin_offer("Python Engineer", job_id="9876543210")
    mock_scraper = MagicMock()
    mock_scraper._get_job_details.return_value = {"description": "<p>Full LinkedIn description.</p>"}

    with patch("offer.offer.scrape", return_value=[offer]):
        with patch("offer.offer.parse", return_value=OfferExtraction()):
            with _patch_fetch() as mock_fetch:
                with _patch_linkedin_scraper(mock_scraper):
                    enrich_all("python", hours=72, client=MagicMock())

    mock_scraper._get_job_details.assert_called_once_with("9876543210")
    mock_fetch.assert_not_called()


def test_enrich_all_does_not_use_linkedin_scraper_for_other_sources():
    offer = _make_offer("Python Dev", description=None, source="adzuna")

    with patch("offer.offer.scrape", return_value=[offer]):
        with patch("offer.offer.parse", return_value=OfferExtraction()):
            with _patch_fetch("Full description."):
                with _patch_linkedin_scraper() as mock_make:
                    enrich_all("python", hours=72, client=MagicMock())

    mock_scraper = mock_make.return_value
    mock_scraper._get_job_details.assert_not_called()
