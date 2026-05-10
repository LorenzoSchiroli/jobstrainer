import argparse
import os
from groq import Groq
from ingestion.offer.offer import enrich_all
from ingestion.company.company import enrich as enrich_company
from ingestion.client import post_job, post_company


def is_enrichment_needed(company: dict) -> bool:
    values = list(company.values())
    return sum(1 for v in values if v is None) >= len(values) / 2


def run(query: str, hours: int) -> None:
    groq = Groq(api_key=os.environ["GROQ_API_KEY"])

    print(f"Scraping offers: {query!r}, last {hours}h")
    offers = enrich_all(query, hours, groq)
    print(f"Scraped {len(offers)} offers")

    new_jobs = 0
    company_locations: dict[str, str] = {}
    for offer in offers:
        status, _ = post_job(offer)
        if status == 201:
            new_jobs += 1
        if offer.company not in company_locations:
            company_locations[offer.company] = offer.location or ""
    print(f"Jobs: {new_jobs} new, {len(offers) - new_jobs} existing")

    enriched = 0
    for name, location in company_locations.items():
        _, record = post_company({"name": name})
        if is_enrichment_needed(record):
            profile, _ = enrich_company(name, location, groq)
            post_company(profile.model_dump(mode="json"))
            enriched += 1
    print(f"Companies: {enriched} enriched out of {len(company_locations)} unique")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest offers and companies into backend")
    parser.add_argument("query", help="Job search query")
    parser.add_argument("--hours", type=int, default=72, help="How many hours back to search")
    args = parser.parse_args()
    run(args.query, args.hours)


if __name__ == "__main__":
    main()
