from pydantic import BaseModel


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
    semantic_query: str


def build_filters(filters: SearchFilters) -> list[dict]:
    clauses: list[dict] = []
    for field, value in {
        "is_consulting": filters.is_consulting,
        "is_startup": filters.is_startup,
        "employment_type": filters.employment_type,
        "location_type": filters.location_type,
        "seniority": filters.seniority,
    }.items():
        if value is not None and (not isinstance(value, str) or "|" not in value):
            clauses.append({"term": {field: value}})
    if filters.min_review_score is not None:
        clauses.append({"range": {"review_score": {"gte": filters.min_review_score}}})
    if filters.min_financial_health_score is not None:
        clauses.append({"range": {"financial_health_score": {"gte": filters.min_financial_health_score}}})
    if filters.languages_required:
        clauses.append({"terms": {"languages_required": [lang.lower() for lang in filters.languages_required]}})
    return clauses
