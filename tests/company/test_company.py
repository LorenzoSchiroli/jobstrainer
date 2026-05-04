from unittest.mock import MagicMock, patch

from company.company import enrich
from company.models import CompanyExtraction, CompanyProfile


def _make_client():
    return MagicMock()


def test_enrich_returns_company_profile():
    extraction = CompanyExtraction(industry="Software", is_consulting=False, is_startup=True)

    with patch("company.company.search_company_urls", return_value=({"website": "https://acme.com"}, [], [])):
        with patch("company.company.fetch_html", return_value="<html></html>"):
            with patch("company.company.extract_jsonld", return_value={"country": "DE", "founded_year": 2010}):
                with patch("company.company.find_relevant_links", return_value=[]):
                    with patch("company.company.extract_with_llm", return_value=extraction):
                        result, _ = enrich("Acme", "Berlin", _make_client())

    assert isinstance(result, CompanyProfile)
    assert result.name == "Acme"
    assert result.country == "DE"
    assert result.founded_year == 2010
    assert result.industry == "Software"
    assert result.is_consulting is False
    assert result.is_startup is True


def test_enrich_jsonld_fields_not_overwritten_by_llm():
    extraction = CompanyExtraction(country="France")

    with patch("company.company.search_company_urls", return_value=({"website": "https://acme.com"}, [], [])):
        with patch("company.company.fetch_html", return_value="<html></html>"):
            with patch("company.company.extract_jsonld", return_value={"country": "DE"}):
                with patch("company.company.find_relevant_links", return_value=[]):
                    with patch("company.company.extract_with_llm", return_value=extraction):
                        result, _ = enrich("Acme", "Berlin", _make_client())

    assert result.country == "DE"


def test_enrich_handles_fetch_failure_gracefully():
    with patch("company.company.search_company_urls", return_value=({"website": "https://acme.com"}, [], [])):
        with patch("company.company.fetch_html", return_value=None):
            result, _ = enrich("Acme", "Berlin", _make_client())

    assert isinstance(result, CompanyProfile)
    assert result.name == "Acme"
    assert result.country is None


def test_enrich_skips_llm_when_all_fields_present():
    full_data = {
        "website": "https://acme.com", "country": "DE", "founded_year": 2010,
        "employee_count": "51-200", "industry": "Software", "is_consulting": False, "is_startup": False,
        "review_score": 4.2, "review_count": 312, "description": "Acme makes things.",
    }

    with patch("company.company.search_company_urls", return_value=({"website": "https://acme.com"}, [], [])):
        with patch("company.company.fetch_html", return_value="<html></html>"):
            with patch("company.company.extract_jsonld", return_value=full_data):
                with patch("company.company.extract_with_llm") as mock_llm:
                    enrich("Acme", "Berlin", _make_client())

    mock_llm.assert_not_called()


def test_enrich_attaches_financial_health_from_llm():
    extraction = CompanyExtraction(
        financial_health_score=4,
        financial_health_rationale="Strong revenue growth.",
    )

    with patch("company.company.search_company_urls", return_value=(
        {"website": "https://acme.com"},
        [],
        ["Revenue grew 12% YoY."],
    )):
        with patch("company.company.fetch_html", return_value="<html></html>"):
            with patch("company.company.extract_jsonld", return_value={}):
                with patch("company.company.find_relevant_links", return_value=[]):
                    with patch("company.company.extract_with_llm", return_value=extraction):
                        result, _ = enrich("Acme", "Berlin", _make_client())

    assert result.financial_health_score == 4
    assert result.financial_health_rationale == "Strong revenue growth."


def test_enrich_triggers_targeted_financial_search_when_registration_numbers_found():
    first_extraction = CompanyExtraction(
        registration_numbers={"VAT": "DE123456789"},
        financial_health_score=3,
        financial_health_rationale="Insufficient data.",
    )
    second_extraction = CompanyExtraction(
        financial_health_score=4,
        financial_health_rationale="Strong balance sheet per annual report.",
    )

    with patch("company.company.search_company_urls", return_value=({"website": "https://acme.com"}, [], [])):
        with patch("company.company.fetch_html", return_value="<html></html>"):
            with patch("company.company.extract_jsonld", return_value={}):
                with patch("company.company.find_relevant_links", return_value=[]):
                    with patch("company.company.extract_with_llm", side_effect=[first_extraction, second_extraction]):
                        with patch("company.company.search_financial", return_value=("https://bundesanzeiger.de/acme", ["Revenue €50M."])):
                            result, _ = enrich("Acme", "Berlin", _make_client())

    assert result.financial_health_score == 4
    assert result.financial_health_rationale == "Strong balance sheet per annual report."


def test_enrich_skips_targeted_financial_search_when_score_is_confident():
    extraction = CompanyExtraction(
        registration_numbers={"VAT": "DE123456789"},
        financial_health_score=4,
        financial_health_rationale="Profitable.",
    )

    with patch("company.company.search_company_urls", return_value=({"website": "https://acme.com"}, [], [])):
        with patch("company.company.fetch_html", return_value="<html></html>"):
            with patch("company.company.extract_jsonld", return_value={}):
                with patch("company.company.find_relevant_links", return_value=[]):
                    with patch("company.company.extract_with_llm", return_value=extraction):
                        with patch("company.company.search_financial") as mock_sf:
                            enrich("Acme", "Berlin", _make_client())

    mock_sf.assert_not_called()


def test_enrich_financial_snippets_passed_to_llm():
    with patch("company.company.search_company_urls", return_value=(
        {"website": "https://acme.com"},
        [],
        ["Revenue grew 12% YoY."],
    )):
        with patch("company.company.fetch_html", return_value="<html></html>"):
            with patch("company.company.extract_jsonld", return_value={}):
                with patch("company.company.find_relevant_links", return_value=[]):
                    with patch("company.company.extract_with_llm", return_value=CompanyExtraction()) as mock_llm:
                        enrich("Acme", "Berlin", _make_client())

    _, kwargs = mock_llm.call_args
    assert kwargs.get("financial_snippets") == ["Revenue grew 12% YoY."]
