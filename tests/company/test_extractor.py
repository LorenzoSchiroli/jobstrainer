import json
from unittest.mock import MagicMock

from company.parsing.extractor import extract_jsonld, extract_with_llm
from company.models import CompanyExtraction

_HTML_WITH_JSONLD = """<html><head>
<script type="application/ld+json">
{
  "@type": "Organization",
  "url": "https://acme.com",
  "description": "Acme makes things.",
  "foundingDate": "2010",
  "numberOfEmployees": {"value": "51-200"},
  "aggregateRating": {"ratingValue": "4.2", "reviewCount": "312"},
  "address": {"addressCountry": "DE"}
}
</script>
</head><body></body></html>"""

_HTML_NO_JSONLD = "<html><body>We are Acme, founded in 2010 in Berlin.</body></html>"


def test_extract_jsonld_parses_all_fields():
    result = extract_jsonld(_HTML_WITH_JSONLD)
    assert result["website"] == "https://acme.com"
    assert result["review_score"] == 4.2
    assert result["review_count"] == 312
    assert result["country"] == "DE"
    assert result["founded_year"] == 2010
    assert result["employee_count"] == "51-200"
    assert result["description"] == "Acme makes things."


def test_extract_jsonld_returns_empty_on_no_jsonld():
    result = extract_jsonld(_HTML_NO_JSONLD)
    assert result == {}


def test_extract_jsonld_returns_empty_on_wrong_type():
    html = """<html><head><script type="application/ld+json">
    {"@type": "WebPage", "name": "Home"}
    </script></head></html>"""
    result = extract_jsonld(html)
    assert result == {}


def test_extract_with_llm_returns_parsed_fields():
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value.choices[0].message.content = json.dumps({
        "website": "https://acme.com",
        "country": "Germany",
        "founded_year": 2010,
        "employee_count": "51-200",
        "industry": "Software",
        "is_consulting": False,
        "is_startup": True,
        "review_score": 4.2,
        "review_count": 312,
        "description": "Acme makes things.",
        "financial_health_score": 4,
        "financial_health_rationale": "Revenue grew 12% YoY.",
        "registration_numbers": {"VAT": "DE123456789", "EIN": "12-3456789"},
    })

    result = extract_with_llm(_HTML_NO_JSONLD, "Acme", "Berlin", mock_client)

    assert result.country == "Germany"
    assert result.is_consulting is False
    assert result.is_startup is True
    assert result.founded_year == 2010
    assert result.financial_health_score == 4
    assert result.financial_health_rationale == "Revenue grew 12% YoY."
    assert result.registration_numbers == {"VAT": "DE123456789", "EIN": "12-3456789"}


def test_extract_with_llm_handles_invalid_json():
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value.choices[0].message.content = "not json at all"

    result = extract_with_llm(_HTML_NO_JSONLD, "Acme", "Berlin", mock_client)

    assert result.country is None
    assert result.founded_year is None
    assert result.financial_health_score is None


def test_extract_with_llm_strips_markdown_code_block():
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value.choices[0].message.content = (
        '```json\n{"country": "Germany"}\n```'
    )
    result = extract_with_llm(_HTML_NO_JSONLD, "Acme", "Berlin", mock_client)
    assert result.country == "Germany"


def test_extract_with_llm_strips_markdown_code_block_uppercase():
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value.choices[0].message.content = (
        '```JSON\n{"country": "Germany"}\n```'
    )
    result = extract_with_llm(_HTML_NO_JSONLD, "Acme", "Berlin", mock_client)
    assert result.country == "Germany"


def test_extract_with_llm_includes_financial_snippets_in_prompt():
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value.choices[0].message.content = json.dumps({})

    extract_with_llm(
        _HTML_NO_JSONLD, "Acme", "Berlin", mock_client,
        financial_snippets=["Revenue grew 12% YoY.", "Strong cash position."],
    )

    prompt_sent = mock_client.chat.completions.create.call_args[1]["messages"][0]["content"]
    assert "Revenue grew 12% YoY." in prompt_sent
    assert "Financial snippets" in prompt_sent
