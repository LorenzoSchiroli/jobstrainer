import argparse
import os
from groq import Groq
from ingestion.offer.offer import enrich_all
from ingestion.company.company import enrich as enrich_company
from ingestion.client import post_job, post_company


_IDENTITY_FIELDS = {"id", "name", "created_at", "updated_at"}


def is_enrichment_needed(company: dict) -> bool:
    enrichable = {k: v for k, v in company.items() if k not in _IDENTITY_FIELDS}
    values = list(enrichable.values())
    if not values:
        return False
    return sum(1 for v in values if v is None) >= len(values) / 2


def run(query: str, hours: int) -> None:
    groq = Groq(api_key=os.environ["GROQ_API_KEY"])

    print(f"Scraping offers: {query!r}, last {hours}h")
    offers = enrich_all(query, hours, groq)
    print(f"Scraped {len(offers)} offers")

    new_jobs = 0
    errors = 0
    company_locations: dict[str, str] = {}
    for offer in offers:
        try:
            status, _ = post_job(offer)
            if status == 201:
                new_jobs += 1
        except Exception as e:
            print(f"[warn] Failed to post job {offer.url!r}: {e}")
            errors += 1
            continue
        if offer.company not in company_locations or (
            company_locations[offer.company] == "" and offer.location
        ):
            company_locations[offer.company] = offer.location or ""
    print(f"Jobs: {new_jobs} new, {len(offers) - new_jobs - errors} existing, {errors} errors")

    enriched = 0
    new_companies = 0
    for name, location in company_locations.items():
        try:
            status, record = post_company({"name": name})
        except Exception as e:
            print(f"[warn] Failed to upsert company {name!r}: {e}")
            continue
        if status == 201:
            new_companies += 1
        if is_enrichment_needed(record):
            try:
                profile, _ = enrich_company(name, location, groq)
                post_company(profile.model_dump(mode="json"))
                enriched += 1
            except Exception as e:
                print(f"[warn] Failed to enrich company {name!r}: {e}")
    print(f"Companies: {new_companies} new, {enriched} enriched out of {len(company_locations)} unique")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest offers and companies into backend")
    parser.add_argument("query", help="Job search query")
    parser.add_argument("--hours", type=int, default=72, help="How many hours back to search")
    args = parser.parse_args()
    run(args.query, args.hours)


if __name__ == "__main__":
    main()
