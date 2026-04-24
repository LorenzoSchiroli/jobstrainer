import logging
from ddgs import DDGS

logger = logging.getLogger(__name__)

_QUERIES = {
    "website": '"{name}" {location} official website',
    "glassdoor": '"{name}" {location} glassdoor',
}


def search_company_urls(name: str, location: str) -> dict[str, str]:
    results = {}
    with DDGS() as ddgs:
        for source, template in _QUERIES.items():
            query = template.format(name=name, location=location)
            try:
                hits = list(ddgs.text(query, max_results=1))
                if hits:
                    results[source] = hits[0]["href"]
            except Exception as e:
                logger.warning("DDG search failed for %s: %s", source, e)
    return results
