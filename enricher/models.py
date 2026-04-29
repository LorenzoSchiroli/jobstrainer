from pydantic import BaseModel


class FinancialHealth(BaseModel):
    score: int
    rationale: str


class CompanyExtraction(BaseModel):
    website: str | None = None
    country: str | None = None
    founded_year: int | None = None
    employee_count: str | None = None
    industry: str | None = None
    is_consulting: bool | None = None
    is_startup: bool | None = None
    review_score: float | None = None
    review_count: int | None = None
    description: str | None = None


class CompanyProfile(CompanyExtraction):
    name: str
    financial_health: FinancialHealth | None = None
