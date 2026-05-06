import argparse
import logging
import os
from datetime import date

from dotenv import load_dotenv
from tabulate import tabulate

from offer.scraping.scraping import scrape
from offer.scraping.sources.adzuna_source import AdzunaSource
from offer.scraping.sources.arbeitnow_source import ArbeitnowSource
from offer.scraping.sources.jobspy_source import JobspySource
from offer.scraping.sources.remotive_source import RemotiveSource

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

_ALL_SOURCES = {
    "jobspy": JobspySource,
    "adzuna": AdzunaSource,
    "arbeitnow": ArbeitnowSource,
    "remotive": RemotiveSource,
}


def _truncate(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Fetch recent job offers matching a query.")
    parser.add_argument("query", help="Search query, e.g. 'machine learning engineer'")
    parser.add_argument("--hours", type=int, default=72, help="How many hours back to search (default: 72)")
    parser.add_argument(
        "--sources",
        default=",".join(_ALL_SOURCES),
        help=f"Comma-separated sources to use. Available: {', '.join(_ALL_SOURCES)} (default: all)",
    )
    args = parser.parse_args()

    source_names = [s.strip() for s in args.sources.split(",")]
    unknown = [s for s in source_names if s not in _ALL_SOURCES]
    if unknown:
        parser.error(f"Unknown sources: {', '.join(unknown)}. Available: {', '.join(_ALL_SOURCES)}")

    sources = [_ALL_SOURCES[name]() for name in source_names]

    print(f"Searching for '{args.query}' (last {args.hours}h) across: {', '.join(source_names)}...\n")

    deduped = scrape(args.query, args.hours, sources=sources)

    if not deduped:
        print("No offers found.")
        return

    rows = [
        [
            i + 1,
            _truncate(o.title, 45),
            _truncate(o.company, 25),
            _truncate(o.location, 25),
            o.source,
            str(o.posted_at) if o.posted_at else "—",
            _truncate(o.url, 60),
        ]
        for i, o in enumerate(deduped)
    ]

    headers = ["#", "Title", "Company", "Location", "Source", "Posted", "URL"]
    print(tabulate(rows, headers=headers, tablefmt="simple"))
    print(f"\n{len(deduped)} offers found.")
