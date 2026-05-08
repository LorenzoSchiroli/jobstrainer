from datetime import date
from pydantic import BaseModel


class OfferExtraction(BaseModel):
    employment_type: str | None = None
    location_type: str | None = None
    office: str | None = None
    seniority: str | None = None
    salary_range: str | None = None
    languages_required: list[str] | None = None
    text_language: str | None = None


class EnrichedOffer(BaseModel):
    title: str
    company: str
    location: str
    url: str
    source: str
    posted_at: date | None
    employment_type: str | None = None
    location_type: str | None = None
    office: str | None = None
    seniority: str | None = None
    salary_range: str | None = None
    languages_required: list[str] | None = None
    text_language: str | None = None
