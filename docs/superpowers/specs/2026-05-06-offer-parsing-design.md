# Offer Parsing Design

**Date:** 2026-05-06

## Overview

Add `offer/parsing/` to extract structured fields from job offer descriptions via LLM, and `offer/offer.py` to orchestrate 1 scraping call → n parsing calls. Also adds `description` to `JobOffer` so the parser has text to work with.

## Architecture

```
offer/
├── models.py                  # NEW: OfferExtraction, EnrichedOffer
├── offer.py                   # NEW: enrich_all(query, hours, client)
├── scraping/
│   ├── models.py              # MODIFY: add description field to JobOffer
│   ├── filters.py             # MODIFY: add _strip_html helper
│   ├── scraping.py            # NEW: extract scrape() from cli.py
│   ├── cli.py                 # MODIFY: delegate to scraping.py
│   └── sources/
│       ├── jobspy_source.py   # MODIFY: populate description
│       ├── remotive_source.py # MODIFY: populate description
│       ├── adzuna_source.py   # MODIFY: populate description (short snippet)
│       └── arbeitnow_source.py # MODIFY: populate description
└── parsing/
    ├── __init__.py            # already exists (empty)
    ├── extractor.py           # NEW: LLM call
    └── parsing.py             # NEW: per-offer orchestration
```

## Components

### Scraping changes

`JobOffer` (in `offer/scraping/models.py`) gains:
```python
description: str | None = None
```

A `_strip_html(html: str) -> str` helper is added to `offer/scraping/filters.py` using BeautifulSoup, stripping script/style/nav/footer tags and returning plain text. Each source calls it when populating `description`.

Note: Adzuna's API returns a short text snippet rather than the full description — this is a known limitation of that source.

The scraping orchestration is extracted from `cli.py` into `offer/scraping/scraping.py`:
```python
def scrape(query: str, hours: int) -> list[JobOffer]: ...
```
`cli.py` is updated to call `scrape()` instead of inlining the logic.

### Models (`offer/models.py`)

```python
class OfferExtraction(BaseModel):
    employment_type: str | None = None   # full-time, part-time, contract, internship, stage, etc.
    location_type: str | None = None     # on-site, remote, hybrid
    office: str | None = None            # city/address if on-site or hybrid
    seniority: str | None = None         # junior, mid, senior, lead, etc.
    salary_range: str | None = None      # as stated in the offer, e.g. "€50k–€70k"

class EnrichedOffer(BaseModel):
    # identity (from JobOffer)
    title: str
    company: str
    location: str
    url: str
    source: str
    posted_at: date | None
    # parsed fields (from OfferExtraction)
    employment_type: str | None = None
    location_type: str | None = None
    office: str | None = None
    seniority: str | None = None
    salary_range: str | None = None
```

`EnrichedOffer` is a flat merge — no inheritance, keeps construction explicit.

### `offer/parsing/extractor.py`

Single function:
```python
def extract_with_llm(offer: JobOffer, client: Groq) -> OfferExtraction
```

Builds prompt from `offer.title` + `offer.description`. Calls Groq with `response_format={"type": "json_object"}` and model `llama-3.3-70b-versatile` (same as company parser). Returns validated `OfferExtraction`. On failure, logs warning and returns `OfferExtraction()`.

Prompt instructs the LLM to return null for any field not explicitly stated in the offer. All text fields must be in English.

### `offer/parsing/parsing.py`

Single function:
```python
def parse(offer: JobOffer, client: Groq) -> OfferExtraction
```

Guards: if `offer.description` is empty/None, returns `OfferExtraction()` immediately. Otherwise delegates to `extract_with_llm`. No multi-step logic needed — all fields come from the same text.

### `offer/offer.py`

```python
def enrich_all(query: str, hours: int, client: Groq) -> list[EnrichedOffer]
```

1. Calls `scrape(query, hours)` → `list[JobOffer]`
2. For each offer, calls `parse(offer, client)` → `OfferExtraction`
3. Merges into `EnrichedOffer` and collects results
4. Returns `list[EnrichedOffer]`

Parsing is sequential (one offer at a time) to keep it simple. Parallelism can be added later if needed.

## Data Flow

```
query, hours
    │
    ▼
scrape(query, hours)
    │  list[JobOffer]  (each with title, company, location, url, source, posted_at, description)
    ▼
for each offer:
    parse(offer, client)
        │  OfferExtraction
        ▼
    EnrichedOffer
    │
    ▼
list[EnrichedOffer]
```

## Error Handling

- Sources never raise (existing contract from `base.py`); missing description yields `None`
- Parser returns empty `OfferExtraction()` for offers with no description
- LLM failures are caught, logged as warnings, and return empty `OfferExtraction()`

## Out of Scope

- CLI for `offer/offer.py` (not requested)
- Parallel LLM calls
- Caching parsed results
- Fetching full offer text by scraping offer URLs (Adzuna limitation accepted)
