from datetime import date
from unittest.mock import MagicMock, patch

from offer.models import EnrichedOffer, OfferExtraction
from offer.offer import enrich_all
from offer.scraping.models import JobOffer


def _make_offer(title: str, description: str | None = "Some job description.") -> JobOffer:
    return JobOffer(
        title=title,
        company="Acme",
        location="Berlin",
        url=f"https://example.com/{title}",
        source="test",
        posted_at=date(2024, 1, 15),
        description=description,
    )


def test_enrich_all_returns_enriched_offers():
    offers = [_make_offer("Python Engineer"), _make_offer("Data Scientist")]
    extraction = OfferExtraction(employment_type="full-time", seniority="senior")

    with patch("offer.offer.scrape", return_value=offers):
        with patch("offer.offer.parse", return_value=extraction):
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
            results = enrich_all("ml", hours=72, client=MagicMock())

    assert results[0].company == "DeepMind"
    assert results[0].location == "London"
    assert results[0].source == "remotive"
    assert results[0].posted_at == date(2024, 3, 10)


def test_enrich_all_handles_offers_with_no_description():
    offer = _make_offer("Python Dev", description=None)
    extraction = OfferExtraction()

    with patch("offer.offer.scrape", return_value=[offer]):
        with patch("offer.offer.parse", return_value=extraction):
            results = enrich_all("python", hours=72, client=MagicMock())

    assert len(results) == 1
    assert results[0].employment_type is None
    assert results[0].seniority is None
