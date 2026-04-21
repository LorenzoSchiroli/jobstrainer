# Retriever — Job Offer Search CLI

**Date:** 2026-04-20
**Status:** Approved

## Overview

A CLI tool inside `retriever/` that fetches recent job offers (default: last 3 days) from multiple sources given a single query string. Results from all sources are merged, deduplicated, and printed as a sorted table in the terminal.

## Goals

- Single query string input: `python -m retriever "machine learning engineer"`
- Cover European + UK job markets, English-language offers only (non-English discarded)
- Aggregate 4 sources: jobspy, Adzuna, Arbeitnow, Remotive
- Deduplicate across sources
- Zero crash on missing API keys — skip that source with a warning instead

## Non-goals

- Saving results to file (future work)
- Interactive prompt or multi-query mode (future work)
- Authentication or user accounts

## File Structure

```
retriever/
├── __init__.py
├── cli.py                  # entry point: arg parsing, orchestration, printing
├── models.py               # JobOffer dataclass
├── deduplicator.py         # merges + deduplicates list[JobOffer]
└── sources/
    ├── __init__.py
    ├── base.py             # abstract Source base class
    ├── jobspy_source.py    # wraps python-jobspy
    ├── adzuna_source.py    # wraps Adzuna REST API
    ├── arbeitnow_source.py # wraps Arbeitnow public API (no key)
    └── remotive_source.py  # wraps Remotive public API (no key)
```

## Data Model

```python
@dataclass
class JobOffer:
    title: str
    company: str
    location: str
    url: str
    source: str           # e.g. "jobspy:linkedin", "adzuna", "arbeitnow", "remotive"
    posted_at: date | None
```

## Sources

| Source | Auth | European coverage | Notes |
|---|---|---|---|
| jobspy | None | LinkedIn, Indeed, Glassdoor, Google Jobs | Multi-board scraper; `hours_old` filter |
| Adzuna | `ADZUNA_APP_ID` + `ADZUNA_APP_KEY` in `.env` | Strong UK + EU | Free tier 250 req/day; iterate over `gb`, `de`, `fr`, `nl`, `es`, `it` |
| Arbeitnow | None | European-focused | Public REST API, no key, remote+EU |
| Remotive | None | Remote only | Public REST API, no key |

For Adzuna, the CLI iterates over a fixed list of European country codes and merges results.

## CLI Interface

```bash
python -m retriever "machine learning engineer"
python -m retriever "machine learning engineer" --days 3
python -m retriever "machine learning engineer" --days 3 --sources jobspy,adzuna
```

**Arguments:**
- Positional `query` — required
- `--days` — integer, default `3`
- `--sources` — comma-separated list, default `jobspy,adzuna,arbeitnow,remotive`

**Behaviour:**
- All enabled sources are fetched concurrently (ThreadPoolExecutor)
- If a source raises an exception or its key is missing, it logs a warning and returns `[]`
- Results are filtered: keep only offers where `title` or `description` (if available) contains at least one English word heuristic (or where `language` field is `"en"` if the source provides it)
- Deduplicated, then sorted by `posted_at` descending (nulls last)
- Printed as a terminal table with columns: `#`, `Title`, `Company`, `Location`, `Source`, `Posted`, `URL`

## Deduplication

Two offers are considered duplicates if either:
1. Their `url` is identical (after stripping trailing slashes and query params), **or**
2. Their `(title, company)` pair matches after lowercasing and stripping punctuation/whitespace

When a duplicate is detected, keep the entry with the more informative `source` label (prefer jobspy > adzuna > arbeitnow > remotive as tiebreaker).

## English-language Filtering

Since sources don't always expose a language field, filtering is done heuristically:
- If the source provides a `language` field and it is not `"en"`, discard.
- Otherwise, check whether the `title` is composed predominantly of ASCII characters. Non-ASCII-heavy titles (e.g. German, French) are discarded.

This is intentionally simple — false negatives (discarding a valid English offer) are acceptable.

## Dependencies to Add

```
jobspy          # python-jobspy
requests        # for Adzuna, Arbeitnow, Remotive HTTP calls
python-dotenv   # already in project
tabulate        # terminal table formatting
langdetect      # optional, stronger language detection if heuristic proves too weak
```

## Environment Variables

Add to `.env` (optional — if absent, Adzuna is skipped):
```
ADZUNA_APP_ID=your_id
ADZUNA_APP_KEY=your_key
```

## Error Handling

- Network errors per source are caught, logged as warnings, source skipped
- Missing `.env` keys for Adzuna: skip with warning
- Empty results from a source: acceptable, no error
- All sources fail: print a clear message and exit 0

## Testing

Manual testing approach (no automated tests for now):
- Run with a known query and verify results appear from multiple sources
- Run with `ADZUNA_APP_KEY` unset and verify Adzuna is skipped cleanly
- Run with `--sources remotive` alone and verify only Remotive results appear
