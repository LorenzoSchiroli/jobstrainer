import logging
from concurrent.futures import ThreadPoolExecutor

from company.scraping.fetcher import fetch_html, find_relevant_links
from company.scraping.searcher import search_company_urls, search_financial

logger = logging.getLogger(__name__)


def scrape(name: str, location: str) -> dict:
    urls, review_snippets, financial_snippets = search_company_urls(name, location)

    with ThreadPoolExecutor(max_workers=3) as ex:
        fut_website   = ex.submit(fetch_html, urls["website"])   if "website"   in urls else None
        fut_financial = ex.submit(fetch_html, urls["financial"]) if "financial" in urls else None
        fut_linkedin  = ex.submit(fetch_html, urls["linkedin"])  if "linkedin"  in urls else None
        website_html   = fut_website.result()   if fut_website   else None
        financial_html = fut_financial.result() if fut_financial else None
        linkedin_html  = fut_linkedin.result()  if fut_linkedin  else None

    extra_htmls: list[str] = []
    if website_html:
        extra_urls = find_relevant_links(website_html, urls.get("website", ""))
        if extra_urls:
            with ThreadPoolExecutor(max_workers=3) as ex:
                extra_htmls = [h for h in ex.map(fetch_html, extra_urls) if h]

    return {
        "website_url": urls.get("website"),
        "website_html": website_html,
        "extra_htmls": extra_htmls,
        "linkedin_url": urls.get("linkedin"),
        "linkedin_html": linkedin_html,
        "financial_url": urls.get("financial"),
        "financial_html": financial_html,
        "review_snippets": review_snippets,
        "financial_snippets": financial_snippets,
    }


def scrape_financial(name: str, location: str, registration_numbers: dict) -> dict:
    url, snippets = search_financial(name, location, registration_numbers)
    html = fetch_html(url) if url else None
    return {
        "financial_url": url,
        "financial_html": html,
        "financial_snippets": snippets,
    }
