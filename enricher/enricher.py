import logging
import time
from concurrent.futures import ThreadPoolExecutor
from groq import Groq

from enricher.extractor import assess_financial_health, extract_jsonld, extract_with_llm
from enricher.fetcher import fetch_html, find_relevant_links
from enricher.models import CompanyProfile
from enricher.searcher import search_company_urls

logger = logging.getLogger(__name__)

_ALL_FIELDS = [
    "website", "country", "founded_year", "employee_count",
    "industry", "is_consulting", "is_startup", "review_score", "review_count", "description",
]


def _missing(data: dict) -> list[str]:
    return [f for f in _ALL_FIELDS if data.get(f) is None]


def enrich(name: str, location: str, client: Groq) -> tuple[CompanyProfile, list[tuple[str, float]]]:
    timings: list[tuple[str, float]] = []

    def tick(label: str, t0: float) -> float:
        timings.append((label, time.perf_counter() - t0))
        return time.perf_counter()

    t = time.perf_counter()
    urls, snippets, financial_snippets = search_company_urls(name, location)
    t = tick("search", t)

    merged: dict = {}
    website_html: str | None = None
    financial_html: str | None = None

    with ThreadPoolExecutor(max_workers=2) as ex:
        fut_website   = ex.submit(fetch_html, urls["website"])   if "website"   in urls else None
        fut_financial = ex.submit(fetch_html, urls["financial"]) if "financial" in urls else None
        website_html   = fut_website.result()   if fut_website   else None
        financial_html = fut_financial.result() if fut_financial else None
    t = tick("fetch website+financial", t)

    if website_html:
        for k, v in extract_jsonld(website_html).items():
            if k not in merged and v is not None:
                merged[k] = v
        t = tick("jsonld website", t)

    if _missing(merged) and website_html:
        extra_urls = find_relevant_links(website_html, urls.get("website", ""))
        t = tick("find links", t)

        if extra_urls:
            with ThreadPoolExecutor(max_workers=3) as ex:
                extra_htmls = [h for h in ex.map(fetch_html, extra_urls) if h]
            t = tick("fetch extra pages", t)
        else:
            extra_htmls = []

        extraction = extract_with_llm(
            website_html, name, location, client,
            snippets or None, extra_htmls or None, urls.get("website"),
        )
        for k, v in extraction.model_dump(exclude_none=True).items():
            if k not in merged:
                merged[k] = v
        t = tick("llm", t)

    profile = CompanyProfile.model_validate({"name": name, **merged})
    profile.financial_health = assess_financial_health(financial_html, financial_snippets, name, client)
    tick("financial health", t)

    return profile, timings
