from pydantic import BaseModel, Field


class CompanyExtraction(BaseModel):
    website: str | None = None
    linkedin_url: str | None = None
    topic: str | None = None
    country: str | None = None
    founded_year: int | None = None
    employee_count: str | None = None
    industry: str | None = None
    is_consulting: bool | None = None
    is_startup: bool | None = None
    review_score: float | None = None
    review_count: int | None = None
    description: str | None = None
    financial_health_score: int | None = Field(None, ge=1, le=5)
    financial_health_rationale: str | None = None
    registration_numbers: dict[str, str] | None = None


class CompanyProfile(CompanyExtraction):
    name: str
