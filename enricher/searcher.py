import logging
import os
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
from ddgs import DDGS

logger = logging.getLogger(__name__)

_REGION = "wt-wt"
_BACKEND = "duckduckgo,brave"
_SERPER_URL = "https://google.serper.dev/search"

_BLOCKED_DOMAINS = {
    # Social
    "linkedin.com", "facebook.com", "twitter.com", "instagram.com", "xing.com",
    # Job / review
    "glassdoor.com", "indeed.com", "kununu.com",
    # News / finance
    "bloomberg.com", "wikipedia.org", "wikidata.org",
    # Business directories
    "crunchbase.com", "pitchbook.com", "zoominfo.com",
    "dnb.com", "dun.com", "kompass.com", "northdata.com",
    "opencorporates.com", "companieshouse.gov.uk", "handelsregister.de",
    "yellowpages.com", "yelp.com", "manta.com", "hoovers.com",
}

_FINANCIAL_SKIP_DOMAINS = {
    "linkedin.com", "facebook.com", "twitter.com", "instagram.com",
    "crunchbase.com", "pitchbook.com", "zoominfo.com",
}


def _is_blocked(url: str) -> bool:
    netloc = urlparse(url).netloc.lower()
    return any(domain in netloc for domain in _BLOCKED_DOMAINS)


def _name_score(url: str, name: str) -> int:
    """Prefer URLs whose domain contains the company name slug."""
    slug = name.lower().replace(" ", "").replace("-", "").replace(".", "")
    domain = urlparse(url).netloc.lower().replace("www.", "").replace("-", "").replace(".", "")
    return 1 if slug in domain else 0


def _search_serper(query: str, max_results: int, api_key: str) -> list[dict]:
    try:
        resp = requests.post(
            _SERPER_URL,
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "num": max_results},
            timeout=10,
        )
        resp.raise_for_status()
        return [
            {"href": r["link"], "title": r.get("title", ""), "body": r.get("snippet", "")}
            for r in resp.json().get("organic", [])
        ]
    except Exception as e:
        logger.warning("Serper search failed for %r: %s", query, e)
        return []


def _search_ddgs(query: str, max_results: int) -> list[dict]:
    try:
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results, region=_REGION, backend=_BACKEND))
    except Exception as e:
        logger.warning("DDG search failed for %r: %s", query, e)
        return []


def _search(query: str, max_results: int) -> list[dict]:
    api_key = os.environ.get("SERPERDEV_API_KEY")
    if api_key:
        results = _search_serper(query, max_results, api_key)
        if results:
            return results
    return _search_ddgs(query, max_results)


def search_company_urls(name: str, location: str) -> tuple[dict[str, str], list[str], list[str]]:
    suffix = f" {location}" if location else ""
    queries = {
        "website": (f'"{name}"{suffix} company', 5),
        "reviews": (f'"{name}"{suffix} glassdoor stars', 5),
        "financial": (f'"{name}"{suffix} company financial health', 3),
    }

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_search, q, n): source
            for source, (q, n) in queries.items()
        }
        results = {}
        for f in as_completed(futures):
            source = futures[f]
            try:
                results[source] = f.result()
            except Exception as e:
                logger.warning("Search failed for %r: %s", source, e)
                results[source] = []

    urls: dict[str, str] = {}
    candidates = [h for h in results.get("website", []) if not _is_blocked(h["href"])]
    candidates.sort(key=lambda h: _name_score(h["href"], name), reverse=True)
    if candidates:
        urls["website"] = candidates[0]["href"]

    review_hits = [h for h in results.get("reviews", []) if "glassdoor." in h.get("href", "")]
    snippets = [h.get("body", "") for h in review_hits if h.get("body")]

    financial_hits = [
        h for h in results.get("financial", [])
        if not any(d in urlparse(h.get("href", "")).netloc.lower() for d in _FINANCIAL_SKIP_DOMAINS)
    ]
    financial_snippets = [h.get("body", "") for h in financial_hits if h.get("body")]
    if financial_hits:
        urls["financial"] = financial_hits[0]["href"]

    engine = "Serper" if os.environ.get("SERPERDEV_API_KEY") else "DDG"
    logger.debug("%s website: %s → selected: %s", engine,
                 ", ".join(h["href"] for h in results.get("website", [])) or "(none)",
                 urls.get("website", "(none)"))
    logger.debug("%s reviews (glassdoor): %s", engine,
                 ", ".join(h["href"] for h in review_hits) or "(none)")
    logger.debug("%s financial: %s → selected: %s", engine,
                 ", ".join(h["href"] for h in financial_hits) or "(none)",
                 urls.get("financial", "(none)"))

    return urls, snippets, financial_snippets
