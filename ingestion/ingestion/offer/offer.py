import logging
import time
from groq import Groq
from tqdm import tqdm

from ingestion.offer.models import EnrichedOffer
from ingestion.offer.parsing.parsing import parse
from ingestion.offer.scraping.filters import _fetch_description_from_url
from ingestion.offer.scraping.models import JobOffer
from ingestion.offer.scraping.scraping import scrape
from ingestion.utils.text import truncate_description

logger = logging.getLogger(__name__)

def _enrich_one(offer: JobOffer, client: Groq) -> EnrichedOffer:
    if offer.url and not offer.description:
        logger.info("fetch  [%s] %s", offer.source, offer.title[:60])
        full_desc = _fetch_description_from_url(offer.url)
        if full_desc:
            offer.description = truncate_description(full_desc)

    if offer.description:
        offer.description = truncate_description(offer.description)

    logger.info("parse  [%s] %s", offer.source, offer.title[:60])
    extraction = parse(offer, client)
    return EnrichedOffer(
        title=offer.title,
        company=offer.company,
        location=offer.location,
        url=offer.url,
        source=offer.source,
        posted_at=offer.posted_at,
        description=offer.description,
        **extraction.model_dump(),
    )


def enrich_all(query: str, hours: int, client: Groq, sources=None) -> list[EnrichedOffer]:
    t0 = time.monotonic()
    offers = scrape(query, hours, sources)
    if not offers:
        return []
    logger.info("Enriching %d offers...", len(offers))
    results = []
    for offer in tqdm(offers, desc="Enriching offers", unit="offer"):
        try:
            results.append(_enrich_one(offer, client))
        except Exception as e:
            logger.warning("Failed to enrich offer: %s", e)
    elapsed = time.monotonic() - t0
    logger.info("Enrichment completed in %.1fs — %d offers enriched.", elapsed, len(results))
    return results
