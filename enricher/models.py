from pydantic import BaseModel

class CompanyExtraction(BaseModel):
    website: str | None = None
    country: str | None = None
    founded_year: int | None = None
    employee_count: str | None = None
    industry: str | None = None
    is_consulting: bool | None = None
    review_score: float | None = None
    review_count: int | None = None
    description: str | None = None


class CompanyProfile(CompanyExtraction):
    name: str
