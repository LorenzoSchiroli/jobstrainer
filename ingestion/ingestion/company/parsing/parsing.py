import json
import logging
from groq import Groq

from ingestion.company.models import CompanyExtraction
from ingestion.company.parsing.extractor import extract_jsonld, extract_with_llm
from ingestion.utils.text import clean_html, MAX_COMPANY_DESCRIPTION_CHARS

logger = logging.getLogger(__name__)

_ALL_FIELDS = [
    "country", "founded_year", "employee_count",
    "industry", "is_consulting", "is_startup", "review_score", "review_count",
]


def _missing(data: dict) -> list[str]:
    return [f for f in _ALL_FIELDS if data.get(f) is None]


def _build_sources(text_dict: dict) -> dict:
    sources: dict = {}

    pages = []
    for html in filter(None, [text_dict.get("website_html")] + (text_dict.get("extra_htmls") or [])):
        if text := clean_html(html, aggressive=False):
            pages.append(text)
    if pages:
        sources["company_pages"] = pages

    if html := text_dict.get("linkedin_html"):
        if text := clean_html(html, aggressive=False):
            sources["linkedin"] = text

    if snippets := text_dict.get("review_snippets"):
        sources["glassdoor_reviews"] = snippets

    if html := text_dict.get("financial_html"):
        if text := clean_html(html, aggressive=False):
            sources["financial_page"] = text

    if snippets := text_dict.get("financial_snippets"):
        sources["financial_snippets"] = snippets

    return sources


def parse(name: str, location: str, text_dict: dict, client: Groq) -> CompanyExtraction:
    merged: dict = {}

    if website_html := text_dict.get("website_html"):
        for k, v in extract_jsonld(website_html).items():
            if v is not None:
                merged[k] = v

    if url := text_dict.get("website_url"):
        merged["website"] = url
    if url := text_dict.get("linkedin_url"):
        merged["linkedin_url"] = url

    sources = _build_sources(text_dict)

    if _missing(merged):
        has_content = sources or text_dict.get("review_snippets") or text_dict.get("financial_snippets")
        if has_content:
            extraction = extract_with_llm(name, location, client, sources)
            for k, v in extraction.model_dump(exclude_none=True).items():
                if k not in merged:
                    merged[k] = v

    if sources:
        merged["description"] = json.dumps(sources, ensure_ascii=False)[:MAX_COMPANY_DESCRIPTION_CHARS]

    return CompanyExtraction.model_validate(merged)


def parse_financial(name: str, location: str, info: CompanyExtraction, text_dict: dict, client: Groq) -> CompanyExtraction:
    sources = _build_sources(text_dict)
    targeted = extract_with_llm(name, location, client, sources)
    data = info.model_dump()
    for field in ("financial_health_score", "financial_health_rationale"):
        if (val := getattr(targeted, field)) is not None:
            data[field] = val
    return CompanyExtraction.model_validate(data)
