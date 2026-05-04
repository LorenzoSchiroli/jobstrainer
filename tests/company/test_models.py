from company.models import CompanyProfile


def test_company_profile_requires_name():
    p = CompanyProfile(name="Acme")
    assert p.name == "Acme"


def test_company_profile_all_fields_default_to_none():
    p = CompanyProfile(name="Acme")
    assert p.website is None
    assert p.country is None
    assert p.founded_year is None
    assert p.employee_count is None
    assert p.industry is None
    assert p.is_consulting is None
    assert p.is_startup is None
    assert p.review_score is None
    assert p.review_count is None
    assert p.description is None
    assert p.financial_health_score is None
    assert p.financial_health_rationale is None
    assert p.registration_numbers is None


def test_company_profile_accepts_all_fields():
    p = CompanyProfile(
        name="Acme",
        website="https://acme.com",
        country="DE",
        founded_year=2010,
        employee_count="51-200",
        industry="Software",
        is_consulting=False,
        is_startup=True,
        review_score=4.2,
        review_count=312,
        description="Acme makes things.",
        financial_health_score=4,
        financial_health_rationale="Revenue grew 12% YoY.",
        registration_numbers={"VAT": "DE123456789", "DUNS": "12-345-6789"},
    )
    assert p.name == "Acme"
    assert p.website == "https://acme.com"
    assert p.country == "DE"
    assert p.founded_year == 2010
    assert p.employee_count == "51-200"
    assert p.industry == "Software"
    assert p.is_consulting is False
    assert p.is_startup is True
    assert p.review_score == 4.2
    assert p.review_count == 312
    assert p.description == "Acme makes things."
    assert p.financial_health_score == 4
    assert p.financial_health_rationale == "Revenue grew 12% YoY."
    assert p.registration_numbers == {"VAT": "DE123456789", "DUNS": "12-345-6789"}


def test_financial_health_score_validates_range():
    import pytest
    with pytest.raises(Exception):
        CompanyProfile(name="Acme", financial_health_score=0)
    with pytest.raises(Exception):
        CompanyProfile(name="Acme", financial_health_score=6)
