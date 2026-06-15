import argparse
import logging
import os
from groq import Groq
from tqdm import tqdm
from ingestion.offer.offer import enrich_all
from ingestion.company.company import enrich as enrich_company
from ingestion.client import post_job, post_company
from ingestion.embedder import embed

logger = logging.getLogger(__name__)

_IDENTITY_FIELDS = {"id", "name", "created_at", "updated_at"}


def is_enrichment_needed(company: dict) -> bool:
    enrichable = {k: v for k, v in company.items() if k not in _IDENTITY_FIELDS}
    values = list(enrichable.values())
    if not values:
        return False
    return sum(1 for v in values if v is None) >= len(values) / 2


def run(query: str, hours: int) -> None:
    groq = Groq(api_key=os.environ["GROQ_API_KEY"])

    logger.info("[1/3] Scraping & enriching offers: %r, last %dh", query, hours)
    offers = enrich_all(query, hours, groq)
    logger.info("Scraped %d offers", len(offers))

    logger.info("[2/3] Embedding & posting %d jobs...", len(offers))
    new_jobs = 0
    errors = 0
    company_locations: dict[str, str] = {}
    for offer in tqdm(offers, desc="Posting jobs", unit="job"):
        try:
            embedding = embed(offer.title, offer.summary)
            status, _ = post_job(offer, embedding=embedding)
            if status == 201:
                new_jobs += 1
        except Exception as e:
            logger.warning("Failed to post job %r: %s", offer.url, e)
            errors += 1
            continue
        if offer.company not in company_locations or (
            company_locations[offer.company] == "" and offer.location
        ):
            company_locations[offer.company] = offer.location or ""
    logger.info("Jobs: %d new, %d existing, %d errors", new_jobs, len(offers) - new_jobs - errors, errors)

    logger.info("[3/3] Upserting & enriching %d companies...", len(company_locations))
    enriched = 0
    new_companies = 0
    for name, location in tqdm(company_locations.items(), desc="Companies", unit="company"):
        try:
            status, record = post_company({"name": name})
        except Exception as e:
            logger.warning("Failed to upsert company %r: %s", name, e)
            continue
        if status == 201:
            new_companies += 1
        if is_enrichment_needed(record):
            try:
                logger.info("Enriching company %r...", name)
                profile, _ = enrich_company(name, location, groq)
                post_company(profile.model_dump(mode="json"))
                enriched += 1
            except Exception as e:
                logger.warning("Failed to enrich company %r: %s", name, e)
    logger.info("Companies: %d new, %d enriched out of %d unique", new_companies, enriched, len(company_locations))


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    parser = argparse.ArgumentParser(description="Ingest offers and companies into backend")
    parser.add_argument("query", help="Job search query")
    parser.add_argument("--hours", type=int, default=72, help="How many hours back to search")
    args = parser.parse_args()
    run(args.query, args.hours)


if __name__ == "__main__":
    main()
