from groq import Groq

from offer.models import EnrichedOffer
from offer.parsing.parsing import parse
from offer.scraping.scraping import scrape


def enrich_all(query: str, hours: int, client: Groq) -> list[EnrichedOffer]:
    offers = scrape(query, hours)
    results = []
    for offer in offers:
        extraction = parse(offer, client)
        results.append(EnrichedOffer(
            title=offer.title,
            company=offer.company,
            location=offer.location,
            url=offer.url,
            source=offer.source,
            posted_at=offer.posted_at,
            **extraction.model_dump(),
        ))
    return results
