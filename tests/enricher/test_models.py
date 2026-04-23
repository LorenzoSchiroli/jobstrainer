from enricher.models import CompanyProfile


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
    assert p.company_type is None
    assert p.review_score is None
    assert p.review_count is None
    assert p.description is None


def test_company_profile_accepts_all_fields():
    p = CompanyProfile(
        name="Acme",
        website="https://acme.com",
        country="DE",
        founded_year=2010,
        employee_count="51-200",
        industry="Software",
        company_type="saas",
        review_score=4.2,
        review_count=312,
        description="Acme makes things.",
    )
    assert p.name == "Acme"
    assert p.website == "https://acme.com"
    assert p.country == "DE"
    assert p.founded_year == 2010
    assert p.employee_count == "51-200"
    assert p.industry == "Software"
    assert p.company_type == "saas"
    assert p.review_score == 4.2
    assert p.review_count == 312
    assert p.description == "Acme makes things."
