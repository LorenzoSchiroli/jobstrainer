from ingestion.pipeline.__main__ import is_enrichment_needed


def test_all_none_needs_enrichment():
    company = {
        "id": "1", "name": "Acme", "website": None,
        "country": None, "founded_year": None, "employee_count": None,
    }
    assert is_enrichment_needed(company) is True


def test_exactly_half_none_needs_enrichment():
    # 3 None out of 6 = 50% — threshold is >=, so True
    company = {
        "id": "1", "name": "Acme", "website": "acme.com",
        "country": None, "founded_year": None, "employee_count": None,
    }
    assert is_enrichment_needed(company) is True


def test_majority_populated_no_enrichment():
    company = {
        "id": "1", "name": "Acme", "website": "acme.com",
        "country": "US", "founded_year": 2010, "employee_count": "100-500",
    }
    assert is_enrichment_needed(company) is False


def test_one_null_no_enrichment():
    # 1 out of 6 = 17% → False
    company = {
        "id": "1", "name": "Acme", "website": "acme.com",
        "country": "US", "founded_year": None, "employee_count": "100-500",
    }
    assert is_enrichment_needed(company) is False


def test_bool_false_is_not_null():
    company = {
        "id": "1", "name": "Acme", "is_consulting": False,
        "is_startup": False, "website": "acme.com", "country": "US",
    }
    assert is_enrichment_needed(company) is False
