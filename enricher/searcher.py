import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
from ddgs import DDGS

logger = logging.getLogger(__name__)

_REGION = "wt-wt"
_BACKEND = "duckduckgo,brave"

_BLOCKED_DOMAINS = {
    "linkedin.com", "crunchbase.com", "facebook.com", "twitter.com",
    "instagram.com", "bloomberg.com", "wikipedia.org", "indeed.com",
    "glassdoor.com", "pitchbook.com", "zoominfo.com",
}


def _search(query: str, max_results: int) -> list[dict]:
    try:
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results, region=_REGION, backend=_BACKEND))
    except Exception as e:
        logger.warning("DDG search failed for %r: %s", query, e)
        return []


def _is_blocked(url: str) -> bool:
    netloc = urlparse(url).netloc.lower()
    return any(domain in netloc for domain in _BLOCKED_DOMAINS)


def search_company_urls(name: str, location: str) -> tuple[dict[str, str], list[str]]:
    suffix = f" {location}" if location else ""
    queries = {
        "website": (f'"{name}"{suffix} company website', 3),
        "reviews": (f'"{name}"{suffix} glassdoor stars', 5),
    }

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(_search, q, n): source
            for source, (q, n) in queries.items()
        }
        results = {futures[f]: f.result() for f in as_completed(futures)}

    urls: dict[str, str] = {}
    for hit in results.get("website", []):
        if not _is_blocked(hit["href"]):
            urls["website"] = hit["href"]
            break

    review_hits = [h for h in results.get("reviews", []) if "glassdoor." in h.get("href", "")]
    snippets = [h.get("body", "") for h in review_hits if h.get("body")]

    all_website_hits = results.get("website", [])
    all_review_hits = results.get("reviews", [])
    print(f"DDG website:  {', '.join(h['href'] for h in all_website_hits) or '(none)'} → selected: {urls.get('website', '(none)')}")
    print(f"DDG reviews (raw):  {', '.join(h['href'] for h in all_review_hits) or '(none)'}")
    print(f"DDG reviews (glassdoor): {', '.join(h['href'] for h in review_hits) or '(none)'}")

    return urls, snippets
