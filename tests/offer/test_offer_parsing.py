from datetime import date
from unittest.mock import MagicMock, patch

from offer.models import OfferExtraction
from offer.parsing.parsing import parse
from offer.scraping.models import JobOffer


def _make_offer(description: str | None) -> JobOffer:
    return JobOffer(
        title="Python Engineer",
        company="Acme",
        location="Berlin",
        url="https://example.com/job/1",
        source="test",
        posted_at=date(2024, 1, 15),
        description=description,
    )


def test_parse_returns_extraction_for_offer_with_description():
    expected = OfferExtraction(employment_type="full-time", seniority="senior")

    with patch("offer.parsing.parsing.extract_with_llm", return_value=expected) as mock_extract:
        result = parse(_make_offer("We need a senior engineer."), MagicMock())

    mock_extract.assert_called_once()
    assert result.employment_type == "full-time"
    assert result.seniority == "senior"


def test_parse_returns_empty_extraction_when_description_is_none():
    result = parse(_make_offer(None), MagicMock())

    assert isinstance(result, OfferExtraction)
    assert result.employment_type is None
    assert result.seniority is None


def test_parse_returns_empty_extraction_when_description_is_empty_string():
    result = parse(_make_offer(""), MagicMock())

    assert isinstance(result, OfferExtraction)
    assert result.employment_type is None


def test_parse_does_not_call_llm_when_description_is_missing():
    with patch("offer.parsing.parsing.extract_with_llm") as mock_extract:
        parse(_make_offer(None), MagicMock())

    mock_extract.assert_not_called()
