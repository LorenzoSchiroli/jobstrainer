import json
import pytest
from datetime import date
from unittest.mock import MagicMock, patch

from groq import RateLimitError

from offer.models import OfferExtraction
from offer.parsing.extractor import extract_with_llm
from offer.scraping.models import JobOffer


def _make_offer(description: str) -> JobOffer:
    return JobOffer(
        title="Senior Python Engineer",
        company="Acme",
        location="Berlin, Germany",
        url="https://example.com/job/1",
        source="test",
        posted_at=date(2024, 1, 15),
        description=description,
    )


def _mock_client(response_json: dict) -> MagicMock:
    mock = MagicMock()
    mock.chat.completions.create.return_value.choices[0].message.content = json.dumps(response_json)
    return mock


def test_extract_with_llm_returns_all_fields():
    client = _mock_client({
        "employment_type": "full-time",
        "location_type": "hybrid",
        "office": "Berlin",
        "seniority": "senior",
        "salary_range": "€70,000–€90,000/year",
        "languages_required": ["french", "german"],
        "text_language": "english",
    })

    result = extract_with_llm(_make_offer("We are hiring a senior engineer."), client)

    assert result.employment_type == "full-time"
    assert result.location_type == "hybrid"
    assert result.office == "Berlin"
    assert result.seniority == "senior"
    assert result.salary_range == "€70,000–€90,000/year"
    assert result.languages_required == ["french", "german"]
    assert result.text_language == "english"


def test_extract_with_llm_returns_null_languages_when_none_required():
    client = _mock_client({
        "employment_type": "full-time",
        "location_type": None,
        "office": None,
        "seniority": None,
        "salary_range": None,
        "languages_required": None,
        "text_language": "english",
    })

    result = extract_with_llm(_make_offer("No language requirement."), client)

    assert result.languages_required is None
    assert result.text_language == "english"


def test_extract_with_llm_returns_nulls_for_missing_fields():
    client = _mock_client({
        "employment_type": "full-time",
        "location_type": None,
        "office": None,
        "seniority": None,
        "salary_range": None,
    })

    result = extract_with_llm(_make_offer("Full-time position."), client)

    assert result.employment_type == "full-time"
    assert result.location_type is None
    assert result.office is None
    assert result.seniority is None
    assert result.salary_range is None


def test_extract_with_llm_returns_empty_extraction_on_invalid_json():
    mock = MagicMock()
    mock.chat.completions.create.return_value.choices[0].message.content = "not json at all"

    result = extract_with_llm(_make_offer("Some job description."), mock)

    assert isinstance(result, OfferExtraction)
    assert result.employment_type is None
    assert result.seniority is None


def test_extract_with_llm_returns_empty_extraction_on_llm_error():
    mock = MagicMock()
    mock.chat.completions.create.side_effect = Exception("API timeout")

    result = extract_with_llm(_make_offer("Some job description."), mock)

    assert isinstance(result, OfferExtraction)
    assert result.employment_type is None


def test_extract_with_llm_includes_title_in_prompt():
    client = _mock_client({"employment_type": None, "location_type": None, "office": None, "seniority": None, "salary_range": None})

    extract_with_llm(_make_offer("Some description."), client)

    prompt_sent = client.chat.completions.create.call_args[1]["messages"][0]["content"]
    assert "Senior Python Engineer" in prompt_sent


def test_extract_with_llm_retries_on_rate_limit_then_succeeds():
    mock = MagicMock()
    rate_limit_error = RateLimitError(
        message="Rate limit reached. Please try again in 2.0s.",
        response=MagicMock(status_code=429, headers={}),
        body={"error": {"message": "Rate limit reached. Please try again in 2.0s."}},
    )
    mock.chat.completions.create.side_effect = [
        rate_limit_error,
        MagicMock(choices=[MagicMock(message=MagicMock(content='{"employment_type": "full-time", "location_type": null, "office": null, "seniority": null, "salary_range": null}'))]),
    ]

    with patch("offer.parsing.extractor.time.sleep") as mock_sleep:
        result = extract_with_llm(_make_offer("Some job."), mock)

    assert result.employment_type == "full-time"
    mock_sleep.assert_called_once()
    assert mock_sleep.call_args[0][0] == pytest.approx(2.5, abs=0.1)


def test_extract_with_llm_returns_empty_after_max_retries():
    mock = MagicMock()
    rate_limit_error = RateLimitError(
        message="Rate limit reached. Please try again in 1.0s.",
        response=MagicMock(status_code=429, headers={}),
        body={"error": {"message": "Rate limit reached. Please try again in 1.0s."}},
    )
    mock.chat.completions.create.side_effect = rate_limit_error

    with patch("offer.parsing.extractor.time.sleep"):
        result = extract_with_llm(_make_offer("Some job."), mock)

    assert isinstance(result, OfferExtraction)
    assert result.employment_type is None


def test_extract_with_llm_strips_markdown_code_fence():
    mock = MagicMock()
    mock.chat.completions.create.return_value.choices[0].message.content = (
        '```json\n{"employment_type": "contract", "location_type": null, "office": null, "seniority": null, "salary_range": null}\n```'
    )

    result = extract_with_llm(_make_offer("Contract role."), mock)

    assert result.employment_type == "contract"
