from datetime import datetime, timezone, timedelta
from pydantic import BaseModel

_BOOST = 2.0


class SearchFilters(BaseModel):
    is_consulting: bool | None = None
    is_startup: bool | None = None
    industry: str | None = None
    country: str | None = None
    employee_count: str | None = None
    min_review_score: float | None = None
    min_financial_health_score: int | None = None
    employment_type: str | None = None
    location_type: str | None = None
    seniority: str | None = None
    languages_required: list[str] | None = None
    max_age_hours: int | None = 720
    semantic_query: str
    strict: bool = False


def build_clauses(filters: SearchFilters) -> list[dict]:
    strict = filters.strict

    def term(field: str, value: object) -> dict:
        return {"term": {field: value if strict else {"value": value, "boost": _BOOST}}}

    def rng(field: str, gte: object) -> dict:
        return {"range": {field: {"gte": gte} if strict else {"gte": gte, "boost": _BOOST}}}

    clauses: list[dict] = []
    for field, value in {
        "is_consulting": filters.is_consulting,
        "is_startup": filters.is_startup,
        "employment_type": filters.employment_type,
        "location_type": filters.location_type,
        "seniority": filters.seniority,
    }.items():
        if value is not None and (not isinstance(value, str) or "|" not in value):
            clauses.append(term(field, value))
    if filters.min_review_score is not None:
        clauses.append(rng("review_score", filters.min_review_score))
    if filters.min_financial_health_score is not None:
        clauses.append(rng("financial_health_score", filters.min_financial_health_score))
    if filters.languages_required:
        langs = [lang.lower() for lang in filters.languages_required]
        clauses.append(
            {"terms": {"languages_required": langs}}
            if strict
            else {"terms": {"languages_required": langs, "boost": _BOOST}}
        )
    if filters.max_age_hours is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=filters.max_age_hours)).isoformat()
        clauses.append(rng("created_at", cutoff))
    return clauses
