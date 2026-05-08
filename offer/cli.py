import argparse
import logging
import os
import sys

from dotenv import load_dotenv
from groq import Groq
from tabulate import tabulate

from offer.offer import enrich_all
from offer.scraping.sources.adzuna_source import AdzunaSource
from offer.scraping.sources.arbeitnow_source import ArbeitnowSource
from offer.scraping.sources.jobspy_source import JobspySource
from offer.scraping.sources.remotive_source import RemotiveSource

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logging.getLogger("offer").setLevel(logging.INFO)

_ALL_SOURCES = {
    "jobspy": JobspySource,
    "adzuna": AdzunaSource,
    "arbeitnow": ArbeitnowSource,
    "remotive": RemotiveSource,
}


def _t(value: str | None, n: int) -> str:
    if not value:
        return "—"
    return value if len(value) <= n else value[: n - 1] + "…"


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Fetch and parse job offers.")
    parser.add_argument("query", help="Search query, e.g. 'machine learning engineer'")
    parser.add_argument("--hours", type=int, default=72, help="How many hours back to search (default: 72)")
    parser.add_argument(
        "--sources",
        default=",".join(_ALL_SOURCES),
        help=f"Comma-separated sources. Available: {', '.join(_ALL_SOURCES)} (default: all)",
    )
    args = parser.parse_args()

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        print("Error: GROQ_API_KEY is not set. Add it to your .env file.", file=sys.stderr)
        sys.exit(1)

    source_names = [s.strip() for s in args.sources.split(",")]
    unknown = [s for s in source_names if s not in _ALL_SOURCES]
    if unknown:
        parser.error(f"Unknown sources: {', '.join(unknown)}. Available: {', '.join(_ALL_SOURCES)}")

    client = Groq(api_key=api_key)

    print(f"Searching and parsing '{args.query}' (last {args.hours}h)...\n")

    results = enrich_all(args.query, args.hours, client)

    if not results:
        print("No offers found.")
        return

    rows = [
        [
            i + 1,
            _t(o.title, 40),
            _t(o.company, 20),
            _t(o.employment_type, 12),
            _t(o.location_type, 8),
            _t(o.office, 15),
            _t(o.seniority, 10),
            _t(o.salary_range, 20),
            str(o.posted_at) if o.posted_at else "—",
        ]
        for i, o in enumerate(results)
    ]

    headers = ["#", "Title", "Company", "Type", "Location", "Office", "Seniority", "Salary", "Posted"]
    print(tabulate(rows, headers=headers, tablefmt="simple"))
    print(f"\n{len(results)} offers found.")
