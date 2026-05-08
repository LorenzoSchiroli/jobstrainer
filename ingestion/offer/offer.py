import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Semaphore, Lock
from urllib.parse import urlparse
from groq import Groq

from ingestion.offer.models import EnrichedOffer
from ingestion.offer.parsing.parsing import parse
from ingestion.offer.scraping.filters import _fetch_description_from_url, _strip_html
from ingestion.offer.scraping.models import JobOffer
from ingestion.offer.scraping.scraping import scrape
from ingestion.offer.scraping.sources.jobspy_source import make_linkedin_scraper

logger = logging.getLogger(__name__)

_MIN_DESC_LENGTH = 500
_MAX_CONCURRENT_PER_DOMAIN = 2

_domain_semaphores: dict[str, Semaphore] = {}
_semaphores_lock = Lock()


def _domain_semaphore(url: str) -> Semaphore:
    domain = urlparse(url).netloc
    with _semaphores_lock:
        if domain not in _domain_semaphores:
            _domain_semaphores[domain] = Semaphore(_MAX_CONCURRENT_PER_DOMAIN)
        return _domain_semaphores[domain]


def _linkedin_job_id(url: str) -> str | None:
    """Extract numeric job ID from a LinkedIn job URL.

    e.g. https://www.linkedin.com/jobs/view/senior-python-engineer-1234567890 → "1234567890"
    """
    slug = url.rstrip("/").split("/")[-1]
    job_id = slug.split("-")[-1]
    return job_id if job_id.isdigit() else None


def _enrich_one(offer: JobOffer, client: Groq, linkedin_scraper) -> EnrichedOffer:
    if offer.url and (not offer.description or len(offer.description) < _MIN_DESC_LENGTH):
        logger.info("fetch  [%s] %s", offer.source, offer.title[:60])
        with _domain_semaphore(offer.url):
            if offer.source == "jobspy:linkedin" and linkedin_scraper:
                job_id = _linkedin_job_id(offer.url)
                if job_id:
                    details = linkedin_scraper._get_job_details(job_id) or {}
                    raw_desc = details.get("description") or ""
                    if raw_desc:
                        offer.description = _strip_html(raw_desc) or None
            else:
                full_desc = _fetch_description_from_url(offer.url)
                if full_desc:
                    offer.description = full_desc

    logger.info("parse  [%s] %s", offer.source, offer.title[:60])
    extraction = parse(offer, client)
    return EnrichedOffer(
        title=offer.title,
        company=offer.company,
        location=offer.location,
        url=offer.url,
        source=offer.source,
        posted_at=offer.posted_at,
        **extraction.model_dump(),
    )


def enrich_all(query: str, hours: int, client: Groq) -> list[EnrichedOffer]:
    offers = scrape(query, hours)
    if not offers:
        return []
    logger.info("Enriching %d offers...", len(offers))
    linkedin_scraper = make_linkedin_scraper()
    results = []
    with ThreadPoolExecutor(max_workers=min(20, len(offers))) as pool:
        futures = [pool.submit(_enrich_one, offer, client, linkedin_scraper) for offer in offers]
        for future in futures:
            try:
                results.append(future.result())
            except Exception as e:
                logger.warning("Failed to enrich offer: %s", e)
    logger.info("Done. %d offers enriched.", len(results))
    return results
