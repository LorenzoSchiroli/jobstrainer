from unittest.mock import MagicMock, patch

from company.company import enrich
from company.models import CompanyExtraction, CompanyProfile


def _make_client():
    return MagicMock()


def test_enrich_returns_company_profile():
    info = CompanyExtraction(industry="Software", is_consulting=False, is_startup=True, country="DE", founded_year=2010)

    with patch("company.company.scrape", return_value={}):
        with patch("company.company.parse", return_value=info):
            result, _ = enrich("Acme", "Berlin", _make_client())

    assert isinstance(result, CompanyProfile)
    assert result.name == "Acme"
    assert result.country == "DE"
    assert result.founded_year == 2010
    assert result.industry == "Software"
    assert result.is_consulting is False
    assert result.is_startup is True


def test_enrich_handles_no_data_gracefully():
    with patch("company.company.scrape", return_value={}):
        with patch("company.company.parse", return_value=CompanyExtraction()):
            result, _ = enrich("Acme", "Berlin", _make_client())

    assert isinstance(result, CompanyProfile)
    assert result.name == "Acme"
    assert result.country is None


def test_enrich_triggers_targeted_financial_search_when_registration_numbers_found():
    first_info = CompanyExtraction(
        registration_numbers={"VAT": "DE123456789"},
        financial_health_score=3,
        financial_health_rationale="Insufficient data.",
    )
    second_info = CompanyExtraction(
        registration_numbers={"VAT": "DE123456789"},
        financial_health_score=4,
        financial_health_rationale="Strong balance sheet per annual report.",
    )

    with patch("company.company.scrape", return_value={}):
        with patch("company.company.parse", return_value=first_info):
            with patch("company.company.scrape_financial", return_value={}) as mock_sf:
                with patch("company.company.parse_financial", return_value=second_info):
                    result, _ = enrich("Acme", "Berlin", _make_client())

    mock_sf.assert_called_once_with("Acme", "Berlin", {"VAT": "DE123456789"})
    assert result.financial_health_score == 4
    assert result.financial_health_rationale == "Strong balance sheet per annual report."


def test_enrich_skips_targeted_financial_search_when_score_is_confident():
    info = CompanyExtraction(
        registration_numbers={"VAT": "DE123456789"},
        financial_health_score=4,
        financial_health_rationale="Profitable.",
    )

    with patch("company.company.scrape", return_value={}):
        with patch("company.company.parse", return_value=info):
            with patch("company.company.scrape_financial") as mock_sf:
                enrich("Acme", "Berlin", _make_client())

    mock_sf.assert_not_called()


def test_enrich_skips_targeted_financial_search_when_no_registration_numbers():
    info = CompanyExtraction(financial_health_score=3)

    with patch("company.company.scrape", return_value={}):
        with patch("company.company.parse", return_value=info):
            with patch("company.company.scrape_financial") as mock_sf:
                enrich("Acme", "Berlin", _make_client())

    mock_sf.assert_not_called()
