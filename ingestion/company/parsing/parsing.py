import logging
from groq import Groq

from ingestion.company.models import CompanyExtraction
from ingestion.company.parsing.extractor import extract_jsonld, extract_with_llm

logger = logging.getLogger(__name__)

_ALL_FIELDS = [
    "website", "country", "founded_year", "employee_count",
    "industry", "is_consulting", "is_startup", "review_score", "review_count", "description",
]


def _missing(data: dict) -> list[str]:
    return [f for f in _ALL_FIELDS if data.get(f) is None]


def parse(name: str, location: str, text_dict: dict, client: Groq) -> CompanyExtraction:
    merged: dict = {}

    if website_html := text_dict.get("website_html"):
        for k, v in extract_jsonld(website_html).items():
            if v is not None:
                merged[k] = v

    if _missing(merged):
        website_html = text_dict.get("website_html") or ""
        has_content = (
            website_html
            or text_dict.get("review_snippets")
            or text_dict.get("linkedin_html")
            or text_dict.get("financial_html")
            or text_dict.get("financial_snippets")
        )
        if has_content:
            extraction = extract_with_llm(
                website_html,
                name, location, client,
                snippets=text_dict.get("review_snippets") or None,
                extra_htmls=text_dict.get("extra_htmls") or None,
                source_url=text_dict.get("website_url"),
                linkedin_html=text_dict.get("linkedin_html"),
                linkedin_url=text_dict.get("linkedin_url"),
                financial_html=text_dict.get("financial_html"),
                financial_url=text_dict.get("financial_url"),
                financial_snippets=text_dict.get("financial_snippets") or None,
            )
            for k, v in extraction.model_dump(exclude_none=True).items():
                if k not in merged:
                    merged[k] = v

    return CompanyExtraction.model_validate(merged)


def parse_financial(name: str, location: str, info: CompanyExtraction, text_dict: dict, client: Groq) -> CompanyExtraction:
    targeted = extract_with_llm(
        "", name, location, client,
        financial_snippets=text_dict.get("financial_snippets") or None,
        financial_html=text_dict.get("financial_html"),
        financial_url=text_dict.get("financial_url"),
    )
    data = info.model_dump()
    for field in ("financial_health_score", "financial_health_rationale"):
        if (val := getattr(targeted, field)) is not None:
            data[field] = val
    return CompanyExtraction.model_validate(data)
