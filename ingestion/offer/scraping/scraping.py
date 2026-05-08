import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

from ingestion.offer.scraping.deduplicator import deduplicate
from ingestion.offer.scraping.models import JobOffer
from ingestion.offer.scraping.sources.adzuna_source import AdzunaSource
from ingestion.offer.scraping.sources.arbeitnow_source import ArbeitnowSource
from ingestion.offer.scraping.sources.base import Source
from ingestion.offer.scraping.sources.jobspy_source import JobspySource
from ingestion.offer.scraping.sources.remotive_source import RemotiveSource

logger = logging.getLogger(__name__)

_ALL_SOURCE_CLASSES = [AdzunaSource, ArbeitnowSource, JobspySource, RemotiveSource]


def scrape(query: str, hours: int, sources: list[Source] | None = None) -> list[JobOffer]:
    if sources is None:
        sources = [cls() for cls in _ALL_SOURCE_CLASSES]
    logger.info("Scraping %d source(s)...", len(sources))
    all_offers: list[JobOffer] = []
    with ThreadPoolExecutor(max_workers=len(sources)) as pool:
        futures = {pool.submit(src.fetch, query, hours): src.__class__.__name__ for src in sources}
        for future in as_completed(futures):
            src_name = futures[future]
            offers = future.result()
            logger.info("  %-20s %d offers", src_name, len(offers))
            all_offers.extend(offers)
    deduped = deduplicate(all_offers)
    deduped.sort(key=lambda o: o.posted_at or date.min, reverse=True)
    logger.info("Scraped %d offers total (after dedup)", len(deduped))
    return deduped
