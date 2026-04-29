from unittest.mock import MagicMock, patch

from enricher.enricher import enrich
from enricher.models import CompanyExtraction, CompanyProfile, FinancialHealth


def _make_client():
    return MagicMock()


def test_enrich_returns_company_profile():
    extraction = CompanyExtraction(industry="Software", is_consulting=False)

    with patch("enricher.enricher.search_company_urls", return_value=({"website": "https://acme.com"}, [], [])):
        with patch("enricher.enricher.fetch_html", return_value="<html></html>"):
            with patch("enricher.enricher.extract_jsonld", return_value={"country": "DE", "founded_year": 2010}):
                with patch("enricher.enricher.find_relevant_links", return_value=[]):
                    with patch("enricher.enricher.extract_with_llm", return_value=extraction):
                        result, _ = enrich("Acme", "Berlin", _make_client())

    assert isinstance(result, CompanyProfile)
    assert result.name == "Acme"
    assert result.country == "DE"
    assert result.founded_year == 2010
    assert result.industry == "Software"
    assert result.is_consulting is False


def test_enrich_jsonld_fields_not_overwritten_by_llm():
    extraction = CompanyExtraction(country="France")

    with patch("enricher.enricher.search_company_urls", return_value=({"website": "https://acme.com"}, [], [])):
        with patch("enricher.enricher.fetch_html", return_value="<html></html>"):
            with patch("enricher.enricher.extract_jsonld", return_value={"country": "DE"}):
                with patch("enricher.enricher.find_relevant_links", return_value=[]):
                    with patch("enricher.enricher.extract_with_llm", return_value=extraction):
                        result, _ = enrich("Acme", "Berlin", _make_client())

    assert result.country == "DE"


def test_enrich_handles_fetch_failure_gracefully():
    with patch("enricher.enricher.search_company_urls", return_value=({"website": "https://acme.com"}, [], [])):
        with patch("enricher.enricher.fetch_html", return_value=None):
            result, _ = enrich("Acme", "Berlin", _make_client())

    assert isinstance(result, CompanyProfile)
    assert result.name == "Acme"
    assert result.country is None


def test_enrich_skips_llm_when_all_fields_present():
    full_data = {
        "website": "https://acme.com", "country": "DE", "founded_year": 2010,
        "employee_count": "51-200", "industry": "Software", "is_consulting": False,
        "review_score": 4.2, "review_count": 312, "description": "Acme makes things.",
    }

    with patch("enricher.enricher.search_company_urls", return_value=({"website": "https://acme.com"}, [], [])):
        with patch("enricher.enricher.fetch_html", return_value="<html></html>"):
            with patch("enricher.enricher.extract_jsonld", return_value=full_data):
                with patch("enricher.enricher.extract_with_llm") as mock_llm:
                    enrich("Acme", "Berlin", _make_client())

    mock_llm.assert_not_called()


def test_enrich_attaches_financial_health():
    financial_health = FinancialHealth(score=4, rationale="Strong revenue growth.")

    with patch("enricher.enricher.search_company_urls", return_value=(
        {"website": "https://acme.com", "financial": "https://stockanalysis.com/acme"},
        [],
        ["Revenue grew 12% YoY."],
    )):
        with patch("enricher.enricher.fetch_html", return_value="<html></html>"):
            with patch("enricher.enricher.extract_jsonld", return_value={}):
                with patch("enricher.enricher.find_relevant_links", return_value=[]):
                    with patch("enricher.enricher.extract_with_llm", return_value=CompanyExtraction()):
                        with patch("enricher.enricher.assess_financial_health", return_value=financial_health):
                            result, _ = enrich("Acme", "Berlin", _make_client())

    assert result.financial_health is not None
    assert result.financial_health.score == 4
    assert result.financial_health.rationale == "Strong revenue growth."


def test_enrich_financial_health_is_none_when_no_financial_data():
    with patch("enricher.enricher.search_company_urls", return_value=(
        {"website": "https://acme.com"},
        [],
        [],
    )):
        with patch("enricher.enricher.fetch_html", return_value="<html></html>"):
            with patch("enricher.enricher.extract_jsonld", return_value={}):
                with patch("enricher.enricher.find_relevant_links", return_value=[]):
                    with patch("enricher.enricher.extract_with_llm", return_value=CompanyExtraction()):
                        with patch("enricher.enricher.assess_financial_health", return_value=None) as mock_assess:
                            result, _ = enrich("Acme", "Berlin", _make_client())

    assert result.financial_health is None
    mock_assess.assert_called_once()
