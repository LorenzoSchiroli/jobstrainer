import argparse
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

from dotenv import load_dotenv
from tabulate import tabulate

from retriever.deduplicator import deduplicate
from retriever.models import JobOffer
from retriever.sources.adzuna_source import AdzunaSource
from retriever.sources.arbeitnow_source import ArbeitnowSource
from retriever.sources.jobspy_source import JobspySource
from retriever.sources.remotive_source import RemotiveSource

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
    parser.add_argument("--days", type=int, default=3, help="How many days back to search (default: 3)")
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

    print(f"Searching for '{args.query}' (last {args.days} days) across: {', '.join(source_names)}...\n")

    all_offers: list[JobOffer] = []
    with ThreadPoolExecutor(max_workers=len(sources)) as pool:
        futures = {pool.submit(src.fetch, args.query, args.days): src.__class__.__name__ for src in sources}
        for future in as_completed(futures):
            all_offers.extend(future.result())

    deduped = deduplicate(all_offers)
    deduped.sort(key=lambda o: o.posted_at or date.min, reverse=True)

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
    print(f"\n{len(deduped)} offers found ({len(all_offers)} before deduplication).")
