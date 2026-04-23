import logging
from groq import Groq

from enricher.extractor import extract_jsonld, extract_with_llm
from enricher.fetcher import fetch_html
from enricher.models import CompanyProfile
from enricher.searcher import search_company_urls

logger = logging.getLogger(__name__)

_ALL_FIELDS = [
    "website", "country", "founded_year", "employee_count",
    "industry", "company_type", "review_score", "review_count", "description",
]


def _missing(data: dict) -> list[str]:
    return [f for f in _ALL_FIELDS if not data.get(f)]


def enrich(name: str, location: str, client: Groq) -> CompanyProfile:
    urls = search_company_urls(name, location)
    merged: dict = {}
    website_html: str | None = None

    for source, url in urls.items():
        html = fetch_html(url)
        if not html:
            continue
        if source == "website":
            website_html = html
        for k, v in extract_jsonld(html).items():
            if k not in merged and v is not None:
                merged[k] = v

    if _missing(merged) and website_html:
        for k, v in extract_with_llm(website_html, name, location, client).items():
            if k not in merged and v is not None:
                merged[k] = v

    profile = CompanyProfile(name=name)
    for field, value in merged.items():
        if hasattr(profile, field):
            setattr(profile, field, value)
    return profile
