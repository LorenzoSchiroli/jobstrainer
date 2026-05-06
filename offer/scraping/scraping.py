from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

from offer.scraping.deduplicator import deduplicate
from offer.scraping.models import JobOffer
from offer.scraping.sources.adzuna_source import AdzunaSource
from offer.scraping.sources.arbeitnow_source import ArbeitnowSource
from offer.scraping.sources.base import Source
from offer.scraping.sources.jobspy_source import JobspySource
from offer.scraping.sources.remotive_source import RemotiveSource

_ALL_SOURCE_CLASSES = [AdzunaSource, ArbeitnowSource, JobspySource, RemotiveSource]


def scrape(query: str, hours: int, sources: list[Source] | None = None) -> list[JobOffer]:
    if sources is None:
        sources = [cls() for cls in _ALL_SOURCE_CLASSES]
    all_offers: list[JobOffer] = []
    with ThreadPoolExecutor(max_workers=len(sources)) as pool:
        futures = {pool.submit(src.fetch, query, hours): src.__class__.__name__ for src in sources}
        for future in as_completed(futures):
            all_offers.extend(future.result())
    deduped = deduplicate(all_offers)
    deduped.sort(key=lambda o: o.posted_at or date.min, reverse=True)
    return deduped
