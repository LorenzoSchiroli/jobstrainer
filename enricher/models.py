from dataclasses import dataclass


@dataclass
class CompanyProfile:
    name: str
    website: str | None = None
    country: str | None = None
    founded_year: int | None = None
    employee_count: str | None = None
    industry: str | None = None
    company_type: str | None = None
    review_score: float | None = None
    review_count: int | None = None
    description: str | None = None
