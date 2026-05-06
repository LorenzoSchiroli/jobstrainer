# Offer Parsing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `offer/parsing/` to extract structured fields (employment type, location type, office, seniority, salary range) from job offer descriptions via LLM, and `offer/offer.py` to orchestrate 1 scraping call → n parsing calls.

**Architecture:** `JobOffer` gains a `description` field populated by all 4 sources at scrape time (HTML stripped to plain text). `offer/parsing/extractor.py` makes the LLM call; `offer/parsing/parsing.py` orchestrates per offer; `offer/offer.py` ties scraping + parsing together. Follows the `company/` module pattern exactly.

**Tech Stack:** Python 3.13, Pydantic v2, Groq (`llama-3.3-70b-versatile`), BeautifulSoup4, pytest + unittest.mock

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `offer/scraping/filters.py` | Add `_strip_html` helper |
| Modify | `offer/scraping/models.py` | Add `description` field to `JobOffer` |
| Modify | `offer/scraping/sources/remotive_source.py` | Populate `description` |
| Modify | `offer/scraping/sources/adzuna_source.py` | Populate `description` |
| Modify | `offer/scraping/sources/arbeitnow_source.py` | Populate `description` |
| Modify | `offer/scraping/sources/jobspy_source.py` | Populate `description` |
| Create | `offer/scraping/scraping.py` | `scrape(query, hours, sources)` extracted from cli |
| Modify | `offer/scraping/cli.py` | Delegate to `scrape()` |
| Create | `offer/models.py` | `OfferExtraction`, `EnrichedOffer` |
| Create | `offer/parsing/extractor.py` | `extract_with_llm(offer, client)` |
| Create | `offer/parsing/parsing.py` | `parse(offer, client)` |
| Create | `offer/offer.py` | `enrich_all(query, hours, client)` |
| Modify | `tests/offer/test_filters.py` | Tests for `_strip_html` |
| Modify | `tests/offer/test_remotive_source.py` | Assert `description` populated |
| Modify | `tests/offer/test_adzuna_source.py` | Assert `description` populated |
| Modify | `tests/offer/test_arbeitnow_source.py` | Assert `description` populated |
| Modify | `tests/offer/test_jobspy_source.py` | Assert `description` populated |
| Create | `tests/offer/test_offer_extractor.py` | Tests for `extract_with_llm` |
| Create | `tests/offer/test_offer_parsing.py` | Tests for `parse` |
| Create | `tests/offer/test_offer.py` | Tests for `enrich_all` |

---

## Task 1: Add `_strip_html` to filters and `description` to `JobOffer`

**Files:**
- Modify: `offer/scraping/filters.py`
- Modify: `offer/scraping/models.py`
- Test: `tests/offer/test_filters.py`

- [ ] **Step 1: Write failing tests for `_strip_html`**

Append to `tests/offer/test_filters.py`:

```python
from offer.scraping.filters import is_english, _strip_html


def test_strip_html_removes_tags():
    assert _strip_html("<p>Hello <b>world</b></p>") == "Hello world"


def test_strip_html_removes_script_content():
    result = _strip_html("<script>console.log('x')</script><p>visible</p>")
    assert "console.log" not in result
    assert "visible" in result


def test_strip_html_removes_style_content():
    result = _strip_html("<style>.foo { color: red }</style><p>text</p>")
    assert "color" not in result
    assert "text" in result


def test_strip_html_returns_plain_text_without_angle_brackets():
    html = "<div><h1>Job Title</h1><p>We need a developer.</p></div>"
    result = _strip_html(html)
    assert "Job Title" in result
    assert "developer" in result
    assert "<" not in result


def test_strip_html_handles_empty_string():
    assert _strip_html("") == ""


def test_strip_html_handles_plain_text_passthrough():
    assert _strip_html("plain text") == "plain text"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/offer/test_filters.py -v -k "strip_html"
```

Expected: `ImportError` — `_strip_html` not yet defined.

- [ ] **Step 3: Implement `_strip_html` in `offer/scraping/filters.py`**

Replace the entire file:

```python
def is_english(text: str) -> bool:
    if not text:
        return True
    import unicodedata
    for c in text:
        if ord(c) >= 128:
            if unicodedata.category(c) in ('Ll', 'Lu', 'Lt') and ord(c) < 0x250:
                if any(accent in unicodedata.name(c, '') for accent in ['WITH', 'ACUTE', 'GRAVE', 'DIAERESIS', 'CIRCUMFLEX']):
                    return False
    return True


def _strip_html(html: str) -> str:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    return soup.get_text(separator=" ", strip=True)
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/offer/test_filters.py -v
```

Expected: all PASS (including the 5 pre-existing `is_english` tests).

- [ ] **Step 5: Add `description` to `JobOffer`**

Replace `offer/scraping/models.py`:

```python
from dataclasses import dataclass, field
from datetime import date


@dataclass
class JobOffer:
    title: str
    company: str
    location: str
    url: str
    source: str
    posted_at: date | None
    description: str | None = None
```

- [ ] **Step 6: Run the full test suite to confirm nothing broke**

```bash
pytest tests/ -v
```

Expected: all PASS (existing tests don't touch `description`).

- [ ] **Step 7: Commit**

```bash
git add offer/scraping/filters.py offer/scraping/models.py tests/offer/test_filters.py
git commit -m "feat(offer/scraping): add _strip_html helper and description field to JobOffer"
```

---

## Task 2: Update sources to populate `description`

**Files:**
- Modify: `offer/scraping/sources/remotive_source.py`
- Modify: `offer/scraping/sources/adzuna_source.py`
- Modify: `offer/scraping/sources/arbeitnow_source.py`
- Modify: `offer/scraping/sources/jobspy_source.py`
- Test: `tests/offer/test_remotive_source.py`
- Test: `tests/offer/test_adzuna_source.py`
- Test: `tests/offer/test_arbeitnow_source.py`
- Test: `tests/offer/test_jobspy_source.py`

- [ ] **Step 1: Add description assertion to `test_remotive_source.py`**

The existing `MOCK_RESPONSE` must include a `description` key on the matching job. Update the file to:

```python
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from offer.scraping.sources.remotive_source import RemotiveSource

_recent = (datetime.now() - timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%S")
_old = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")

MOCK_RESPONSE = {
    "jobs": [
        {
            "title": "Senior Python Developer",
            "company_name": "Remote Inc",
            "url": "https://remotive.com/remote-jobs/python-dev-123",
            "candidate_required_location": "Europe",
            "publication_date": _recent,
            "description": "<p>We need a <b>senior developer</b> with Python skills.</p>",
        },
        {
            "title": "Développeur Python",
            "company_name": "FrenchCo",
            "url": "https://remotive.com/remote-jobs/dev-456",
            "candidate_required_location": "France",
            "publication_date": _recent,
            "description": "<p>Description en français.</p>",
        },
        {
            "title": "Python Engineer",
            "company_name": "OldRemote",
            "url": "https://remotive.com/remote-jobs/py-789",
            "candidate_required_location": "Worldwide",
            "publication_date": _old,
            "description": "<p>Old job.</p>",
        },
    ]
}


def _mock_get(response):
    mock = MagicMock()
    mock.json.return_value = response
    mock.raise_for_status = MagicMock()
    return mock


def test_returns_matching_english_offers_within_hours():
    with patch("offer.scraping.sources.remotive_source.requests.get", return_value=_mock_get(MOCK_RESPONSE)):
        results = RemotiveSource().fetch("python", hours=72)

    assert len(results) == 1
    assert results[0].title == "Senior Python Developer"
    assert results[0].source == "remotive"


def test_description_is_stripped_of_html():
    with patch("offer.scraping.sources.remotive_source.requests.get", return_value=_mock_get(MOCK_RESPONSE)):
        results = RemotiveSource().fetch("python", hours=72)

    assert results[0].description is not None
    assert "senior developer" in results[0].description
    assert "<" not in results[0].description


def test_returns_empty_on_error():
    with patch("offer.scraping.sources.remotive_source.requests.get", side_effect=Exception("timeout")):
        assert RemotiveSource().fetch("python", hours=72) == []
```

- [ ] **Step 2: Run new test to confirm it fails**

```bash
pytest tests/offer/test_remotive_source.py::test_description_is_stripped_of_html -v
```

Expected: FAIL — `description` is `None`.

- [ ] **Step 3: Update `offer/scraping/sources/remotive_source.py`**

```python
import logging
import requests
from datetime import date, datetime, timedelta
from offer.scraping.filters import is_english, _strip_html
from offer.scraping.models import JobOffer
from offer.scraping.sources.base import Source

logger = logging.getLogger(__name__)

_API_URL = "https://remotive.com/api/remote-jobs"


class RemotiveSource(Source):
    def fetch(self, query: str, hours: int) -> list[JobOffer]:
        try:
            resp = requests.get(_API_URL, params={"search": query, "limit": 100}, timeout=10)
            resp.raise_for_status()
            jobs = resp.json().get("jobs", [])
        except Exception as e:
            logger.warning("Remotive fetch failed: %s", e)
            return []

        cutoff = datetime.now() - timedelta(hours=hours)
        results = []

        for item in jobs:
            pub = item.get("publication_date", "")
            try:
                posted = datetime.fromisoformat(pub)
            except (ValueError, AttributeError):
                continue
            if posted < cutoff:
                continue
            title = item.get("title", "")
            if not is_english(title):
                continue
            raw_desc = item.get("description", "")
            results.append(JobOffer(
                title=title,
                company=item.get("company_name", ""),
                location=item.get("candidate_required_location", "Remote"),
                url=item.get("url", ""),
                source="remotive",
                posted_at=posted.date(),
                description=_strip_html(raw_desc) or None,
            ))

        return results
```

- [ ] **Step 4: Run remotive tests**

```bash
pytest tests/offer/test_remotive_source.py -v
```

Expected: all PASS.

- [ ] **Step 5: Add description assertion to `test_adzuna_source.py`**

Read `tests/offer/test_adzuna_source.py` first, then add `description` to the mock item and add:

```python
def test_description_is_populated():
    # Assumes the mock item includes: "description": "Develop Python services."
    with patch(...):
        results = AdzunaSource().fetch("python", hours=72)
    matching = [r for r in results if r.title == "<the English title in your mock>"]
    assert len(matching) == 1
    assert matching[0].description == "Develop Python services."
```

Replace the placeholder above with the actual title from the existing mock. Add `"description": "Develop Python services."` to the matching mock item.

- [ ] **Step 6: Run new adzuna test to confirm it fails**

```bash
pytest tests/offer/test_adzuna_source.py -v -k "description"
```

Expected: FAIL.

- [ ] **Step 7: Update `offer/scraping/sources/adzuna_source.py`**

```python
import logging
import os
import requests
from datetime import date, datetime
from offer.scraping.filters import is_english
from offer.scraping.models import JobOffer
from offer.scraping.sources.base import Source

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/1"
_COUNTRIES = ["gb", "de", "fr", "nl", "es", "it", "at", "be"]


class AdzunaSource(Source):
    def fetch(self, query: str, hours: int) -> list[JobOffer]:
        app_id = os.getenv("ADZUNA_APP_ID")
        app_key = os.getenv("ADZUNA_APP_KEY")
        if not app_id or not app_key:
            logger.warning("Adzuna skipped: ADZUNA_APP_ID or ADZUNA_APP_KEY not set")
            return []

        results = []
        for country in _COUNTRIES:
            try:
                resp = requests.get(
                    _BASE_URL.format(country=country),
                    params={
                        "app_id": app_id,
                        "app_key": app_key,
                        "results_per_page": 50,
                        "what": query,
                        "max_days_old": max(1, hours // 24),
                    },
                    timeout=10,
                )
                resp.raise_for_status()
                for item in resp.json().get("results", []):
                    title = item.get("title", "")
                    if not is_english(title):
                        continue
                    posted_at = None
                    created = item.get("created", "")
                    try:
                        posted_at = datetime.fromisoformat(created.replace("Z", "+00:00")).date()
                    except (ValueError, AttributeError):
                        pass
                    results.append(JobOffer(
                        title=title,
                        company=item.get("company", {}).get("display_name", ""),
                        location=item.get("location", {}).get("display_name", ""),
                        url=item.get("redirect_url", ""),
                        source="adzuna",
                        posted_at=posted_at,
                        description=item.get("description") or None,
                    ))
            except Exception as e:
                logger.warning("Adzuna fetch failed for %s: %s", country, e)

        return results
```

- [ ] **Step 8: Run adzuna tests**

```bash
pytest tests/offer/test_adzuna_source.py -v
```

Expected: all PASS.

- [ ] **Step 9: Add description assertion to `test_arbeitnow_source.py`**

Read `tests/offer/test_arbeitnow_source.py` first, then add `"description": "<p>Build backend systems.</p>"` to the matching mock item, and add:

```python
def test_description_is_stripped_of_html():
    with patch(...):
        results = ArbeitnowSource().fetch("<query in your mock>", hours=72)
    matching = [r for r in results if r.title == "<the matching title>"]
    assert len(matching) == 1
    assert "Build backend systems" in matching[0].description
    assert "<" not in matching[0].description
```

Replace placeholders with actual values from the existing mock.

- [ ] **Step 10: Run new arbeitnow test to confirm it fails**

```bash
pytest tests/offer/test_arbeitnow_source.py -v -k "description"
```

Expected: FAIL.

- [ ] **Step 11: Update `offer/scraping/sources/arbeitnow_source.py`**

```python
import logging
import time
import requests
from datetime import date
from offer.scraping.filters import is_english, _strip_html
from offer.scraping.models import JobOffer
from offer.scraping.sources.base import Source

logger = logging.getLogger(__name__)

_API_URL = "https://arbeitnow.com/api/job-board-api"


class ArbeitnowSource(Source):
    def fetch(self, query: str, hours: int) -> list[JobOffer]:
        try:
            resp = requests.get(_API_URL, timeout=10)
            resp.raise_for_status()
            data = resp.json().get("data", [])
        except Exception as e:
            logger.warning("Arbeitnow fetch failed: %s", e)
            return []

        cutoff = time.time() - hours * 3600
        query_lower = query.lower()
        results = []

        for item in data:
            if item.get("created_at", 0) < cutoff:
                continue
            title = item.get("title", "")
            tags = " ".join(item.get("tags", []))
            if query_lower not in title.lower() and query_lower not in tags.lower():
                continue
            if not is_english(title):
                continue
            raw_desc = item.get("description", "")
            results.append(JobOffer(
                title=title,
                company=item.get("company_name", ""),
                location=item.get("location", ""),
                url=item.get("url", ""),
                source="arbeitnow",
                posted_at=date.fromtimestamp(item["created_at"]) if item.get("created_at") else None,
                description=_strip_html(raw_desc) or None,
            ))

        return results
```

- [ ] **Step 12: Run arbeitnow tests**

```bash
pytest tests/offer/test_arbeitnow_source.py -v
```

Expected: all PASS.

- [ ] **Step 13: Add description assertion to `test_jobspy_source.py`**

Read `tests/offer/test_jobspy_source.py` first, then add a `description` column to the mock DataFrame used in the existing tests and add:

```python
def test_description_is_populated():
    import pandas as pd
    from unittest.mock import patch
    from offer.scraping.sources.jobspy_source import JobspySource

    mock_df = pd.DataFrame([{
        "title": "Python Engineer",
        "company": "Acme",
        "location": "Berlin",
        "job_url": "https://linkedin.com/jobs/1",
        "site": "linkedin",
        "date_posted": "2024-01-15",
        "description": "<p>Build <b>microservices</b> in Python.</p>",
    }])

    with patch("offer.scraping.sources.jobspy_source.scrape_jobs", return_value=mock_df):
        with patch("offer.scraping.sources.jobspy_source._scrape_glassdoor", return_value=[]):
            with patch("offer.scraping.sources.jobspy_source._scrape_google", return_value=[]):
                results = JobspySource().fetch("python", hours=72)

    assert len(results) == 1
    assert results[0].description is not None
    assert "microservices" in results[0].description
    assert "<" not in results[0].description
```

> **Note:** Read the existing jobspy test first — it may already mock `scrape_jobs` at a different path. Match the mock path exactly.

- [ ] **Step 14: Run new jobspy test to confirm it fails**

```bash
pytest tests/offer/test_jobspy_source.py -v -k "description"
```

Expected: FAIL.

- [ ] **Step 15: Update `offer/scraping/sources/jobspy_source.py`**

In `_df_to_offers`, add description extraction (strip HTML since jobspy may return HTML):

```python
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
import pandas as pd
from jobspy import scrape_jobs
from offer.scraping.filters import is_english, _strip_html
from offer.scraping.models import JobOffer
from offer.scraping.sources.base import Source

logger = logging.getLogger(__name__)

_INDEED_COUNTRIES = ["UK", "Germany", "France", "Netherlands", "Spain", "Italy", "Belgium", "Austria"]


def _df_to_offers(df: pd.DataFrame) -> list[JobOffer]:
    results = []
    for _, row in df.iterrows():
        title = row.get("title")
        if not title or not isinstance(title, str):
            continue
        if not is_english(title):
            continue
        posted_at: date | None = None
        raw_date = row.get("date_posted")
        if pd.notna(raw_date) and raw_date is not None:
            try:
                posted_at = pd.Timestamp(raw_date).date()
            except Exception:
                pass
        site = row.get("site", "unknown")
        raw_desc = row.get("description") or ""
        results.append(JobOffer(
            title=title,
            company=str(row.get("company") or ""),
            location=str(row.get("location") or ""),
            url=str(row.get("job_url") or ""),
            source=f"jobspy:{site}",
            posted_at=posted_at,
            description=_strip_html(str(raw_desc)) or None if raw_desc else None,
        ))
    return results


def _scrape_linkedin(query: str, hours: int) -> list[JobOffer]:
    try:
        df = scrape_jobs(
            site_name=["linkedin"],
            search_term=query,
            location="Europe",
            hours_old=hours,
            results_wanted=50,
        )
        return _df_to_offers(df)
    except Exception as e:
        logger.warning("jobspy LinkedIn fetch failed: %s", e)
        return []


def _scrape_glassdoor(query: str, hours: int) -> list[JobOffer]:
    try:
        df = scrape_jobs(
            site_name=["glassdoor"],
            search_term=query,
            location="Europe",
            hours_old=hours,
            results_wanted=50,
        )
        return _df_to_offers(df)
    except Exception as e:
        logger.warning("jobspy Glassdoor fetch failed: %s", e)
        return []


def _scrape_google(query: str, hours: int) -> list[JobOffer]:
    try:
        df = scrape_jobs(
            site_name=["google"],
            search_term=query,
            location="Europe",
            hours_old=hours,
            results_wanted=50,
        )
        return _df_to_offers(df)
    except Exception as e:
        logger.warning("jobspy Google Jobs fetch failed: %s", e)
        return []


def _scrape_indeed(query: str, hours: int, country: str) -> list[JobOffer]:
    try:
        df = scrape_jobs(
            site_name=["indeed"],
            search_term=query,
            hours_old=hours,
            results_wanted=20,
            country_indeed=country,
        )
        return _df_to_offers(df)
    except Exception as e:
        logger.warning("jobspy Indeed/%s fetch failed: %s", country, e)
        return []


class JobspySource(Source):
    def fetch(self, query: str, hours: int) -> list[JobOffer]:
        results: list[JobOffer] = []

        tasks = [
            (_scrape_linkedin, (query, hours)),
            (_scrape_glassdoor, (query, hours)),
            (_scrape_google, (query, hours)),
        ] + [
            (_scrape_indeed, (query, hours, country)) for country in _INDEED_COUNTRIES
        ]

        with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
            futures = [pool.submit(fn, *args) for fn, args in tasks]
            for future in as_completed(futures):
                results.extend(future.result())

        return results
```

- [ ] **Step 16: Run all offer source tests**

```bash
pytest tests/offer/ -v
```

Expected: all PASS.

- [ ] **Step 17: Commit**

```bash
git add offer/scraping/sources/ tests/offer/test_remotive_source.py tests/offer/test_adzuna_source.py tests/offer/test_arbeitnow_source.py tests/offer/test_jobspy_source.py
git commit -m "feat(offer/scraping): populate description field in all sources"
```

---

## Task 3: Extract `scrape()` into `offer/scraping/scraping.py`

**Files:**
- Create: `offer/scraping/scraping.py`
- Modify: `offer/scraping/cli.py`

No new tests needed — this is pure extraction of existing, already-tested logic.

- [ ] **Step 1: Create `offer/scraping/scraping.py`**

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

from offer.scraping.deduplicator import deduplicate
from offer.scraping.models import JobOffer
from offer.scraping.sources.adzuna_source import AdzunaSource
from offer.scraping.sources.arbeitnow_source import ArbeitnowSource
from offer.scraping.sources.base import Source
from offer.scraping.sources.jobspy_source import JobspySource
from offer.scraping.sources.remotive_source import RemotiveSource

_ALL_SOURCE_CLASSES = [AdzunaSource, ArbeitnowSource, JobspySource, RemotiveSource]


def scrape(query: str, hours: int, sources: list[Source] | None = None) -> list[JobOffer]:
    if sources is None:
        sources = [cls() for cls in _ALL_SOURCE_CLASSES]
    all_offers: list[JobOffer] = []
    with ThreadPoolExecutor(max_workers=len(sources)) as pool:
        futures = {pool.submit(src.fetch, query, hours): src.__class__.__name__ for src in sources}
        for future in as_completed(futures):
            all_offers.extend(future.result())
    deduped = deduplicate(all_offers)
    deduped.sort(key=lambda o: o.posted_at or date.min, reverse=True)
    return deduped
```

- [ ] **Step 2: Update `offer/scraping/cli.py` to delegate to `scrape()`**

```python
import argparse
import logging
import os
from datetime import date

from dotenv import load_dotenv
from tabulate import tabulate

from offer.scraping.models import JobOffer
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
```

- [ ] **Step 3: Run full test suite to confirm nothing broke**

```bash
pytest tests/ -v
```

Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add offer/scraping/scraping.py offer/scraping/cli.py
git commit -m "refactor(offer/scraping): extract scrape() from cli into scraping.py"
```

---

## Task 4: Create `offer/models.py`

**Files:**
- Create: `offer/models.py`
- Test: (inline validation — model tests are part of extractor tests in Task 5)

- [ ] **Step 1: Create `offer/models.py`**

```python
from datetime import date
from pydantic import BaseModel


class OfferExtraction(BaseModel):
    employment_type: str | None = None
    location_type: str | None = None
    office: str | None = None
    seniority: str | None = None
    salary_range: str | None = None


class EnrichedOffer(BaseModel):
    title: str
    company: str
    location: str
    url: str
    source: str
    posted_at: date | None
    employment_type: str | None = None
    location_type: str | None = None
    office: str | None = None
    seniority: str | None = None
    salary_range: str | None = None
```

- [ ] **Step 2: Verify import works**

```bash
python -c "from offer.models import OfferExtraction, EnrichedOffer; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add offer/models.py
git commit -m "feat(offer): add OfferExtraction and EnrichedOffer models"
```

---

## Task 5: Create `offer/parsing/extractor.py`

**Files:**
- Create: `offer/parsing/extractor.py`
- Test: `tests/offer/test_offer_extractor.py`

- [ ] **Step 1: Write failing tests**

Create `tests/offer/test_offer_extractor.py`:

```python
import json
from datetime import date
from unittest.mock import MagicMock

from offer.models import OfferExtraction
from offer.parsing.extractor import extract_with_llm
from offer.scraping.models import JobOffer


def _make_offer(description: str) -> JobOffer:
    return JobOffer(
        title="Senior Python Engineer",
        company="Acme",
        location="Berlin, Germany",
        url="https://example.com/job/1",
        source="test",
        posted_at=date(2024, 1, 15),
        description=description,
    )


def _mock_client(response_json: dict) -> MagicMock:
    mock = MagicMock()
    mock.chat.completions.create.return_value.choices[0].message.content = json.dumps(response_json)
    return mock


def test_extract_with_llm_returns_all_fields():
    client = _mock_client({
        "employment_type": "full-time",
        "location_type": "hybrid",
        "office": "Berlin",
        "seniority": "senior",
        "salary_range": "€70,000–€90,000/year",
    })

    result = extract_with_llm(_make_offer("We are hiring a senior engineer."), client)

    assert result.employment_type == "full-time"
    assert result.location_type == "hybrid"
    assert result.office == "Berlin"
    assert result.seniority == "senior"
    assert result.salary_range == "€70,000–€90,000/year"


def test_extract_with_llm_returns_nulls_for_missing_fields():
    client = _mock_client({
        "employment_type": "full-time",
        "location_type": None,
        "office": None,
        "seniority": None,
        "salary_range": None,
    })

    result = extract_with_llm(_make_offer("Full-time position."), client)

    assert result.employment_type == "full-time"
    assert result.location_type is None
    assert result.office is None
    assert result.seniority is None
    assert result.salary_range is None


def test_extract_with_llm_returns_empty_extraction_on_invalid_json():
    mock = MagicMock()
    mock.chat.completions.create.return_value.choices[0].message.content = "not json at all"

    result = extract_with_llm(_make_offer("Some job description."), mock)

    assert isinstance(result, OfferExtraction)
    assert result.employment_type is None
    assert result.seniority is None


def test_extract_with_llm_returns_empty_extraction_on_llm_error():
    mock = MagicMock()
    mock.chat.completions.create.side_effect = Exception("API timeout")

    result = extract_with_llm(_make_offer("Some job description."), mock)

    assert isinstance(result, OfferExtraction)
    assert result.employment_type is None


def test_extract_with_llm_includes_title_in_prompt():
    client = _mock_client({"employment_type": None, "location_type": None, "office": None, "seniority": None, "salary_range": None})

    extract_with_llm(_make_offer("Some description."), client)

    prompt_sent = client.chat.completions.create.call_args[1]["messages"][0]["content"]
    assert "Senior Python Engineer" in prompt_sent


def test_extract_with_llm_strips_markdown_code_fence():
    mock = MagicMock()
    mock.chat.completions.create.return_value.choices[0].message.content = (
        '```json\n{"employment_type": "contract", "location_type": null, "office": null, "seniority": null, "salary_range": null}\n```'
    )

    result = extract_with_llm(_make_offer("Contract role."), mock)

    assert result.employment_type == "contract"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/offer/test_offer_extractor.py -v
```

Expected: `ImportError` — `offer.parsing.extractor` not yet defined.

- [ ] **Step 3: Create `offer/parsing/extractor.py`**

```python
import logging
import re
from groq import Groq

from offer.models import OfferExtraction
from offer.scraping.models import JobOffer

logger = logging.getLogger(__name__)

_LLM_PROMPT = (
    "Extract job offer details from the text below. "
    "Return ONLY valid JSON with exactly these fields (use null if not stated):\n"
    '{{"employment_type": str, "location_type": str, "office": str, "seniority": str, "salary_range": str}}\n\n'
    "IMPORTANT: employment_type values: full-time, part-time, contract, internship, stage, freelance. "
    "Use null if not stated.\n"
    "IMPORTANT: location_type values: on-site, remote, hybrid. "
    "If only an office city is mentioned without specifying remote or hybrid, assume on-site.\n"
    "IMPORTANT: office is the city or address of the office, only when location_type is on-site or hybrid. "
    "Use null if location_type is remote or not stated.\n"
    "IMPORTANT: seniority values: junior, mid, senior, lead, principal, staff, director. "
    "Use null if not explicitly stated or clearly inferable.\n"
    "IMPORTANT: salary_range is the salary exactly as stated in the offer (e.g. '€50,000–€70,000/year'). "
    "Use null if not stated.\n"
    "IMPORTANT: Use null for any field not explicitly stated or clearly inferable from the text.\n"
    "IMPORTANT: All text fields must be in English.\n\n"
    "Job title: {title}\n"
    "Job description:\n{description}"
)


def _strip_markdown_json(text: str) -> str:
    stripped = re.sub(r"^```(?:json)?\s*\n?", "", text.strip(), flags=re.IGNORECASE)
    return re.sub(r"\n?```\s*$", "", stripped).strip()


def extract_with_llm(offer: JobOffer, client: Groq) -> OfferExtraction:
    prompt = _LLM_PROMPT.format(
        title=offer.title,
        description=(offer.description or "")[:8000],
    )
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        content = _strip_markdown_json(response.choices[0].message.content)
        return OfferExtraction.model_validate_json(content)
    except Exception as e:
        logger.warning("LLM extraction failed: %s", e)
        return OfferExtraction()
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/offer/test_offer_extractor.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add offer/parsing/extractor.py tests/offer/test_offer_extractor.py
git commit -m "feat(offer/parsing): add extractor with LLM-based field extraction"
```

---

## Task 6: Create `offer/parsing/parsing.py`

**Files:**
- Create: `offer/parsing/parsing.py`
- Test: `tests/offer/test_offer_parsing.py`

- [ ] **Step 1: Write failing tests**

Create `tests/offer/test_offer_parsing.py`:

```python
from datetime import date
from unittest.mock import MagicMock, patch

from offer.models import OfferExtraction
from offer.parsing.parsing import parse
from offer.scraping.models import JobOffer


def _make_offer(description: str | None) -> JobOffer:
    return JobOffer(
        title="Python Engineer",
        company="Acme",
        location="Berlin",
        url="https://example.com/job/1",
        source="test",
        posted_at=date(2024, 1, 15),
        description=description,
    )


def test_parse_returns_extraction_for_offer_with_description():
    expected = OfferExtraction(employment_type="full-time", seniority="senior")

    with patch("offer.parsing.parsing.extract_with_llm", return_value=expected) as mock_extract:
        result = parse(_make_offer("We need a senior engineer."), MagicMock())

    mock_extract.assert_called_once()
    assert result.employment_type == "full-time"
    assert result.seniority == "senior"


def test_parse_returns_empty_extraction_when_description_is_none():
    result = parse(_make_offer(None), MagicMock())

    assert isinstance(result, OfferExtraction)
    assert result.employment_type is None
    assert result.seniority is None


def test_parse_returns_empty_extraction_when_description_is_empty_string():
    result = parse(_make_offer(""), MagicMock())

    assert isinstance(result, OfferExtraction)
    assert result.employment_type is None


def test_parse_does_not_call_llm_when_description_is_missing():
    with patch("offer.parsing.parsing.extract_with_llm") as mock_extract:
        parse(_make_offer(None), MagicMock())

    mock_extract.assert_not_called()
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/offer/test_offer_parsing.py -v
```

Expected: `ImportError` — `offer.parsing.parsing` not yet defined.

- [ ] **Step 3: Create `offer/parsing/parsing.py`**

```python
from groq import Groq

from offer.models import OfferExtraction
from offer.parsing.extractor import extract_with_llm
from offer.scraping.models import JobOffer


def parse(offer: JobOffer, client: Groq) -> OfferExtraction:
    if not offer.description:
        return OfferExtraction()
    return extract_with_llm(offer, client)
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/offer/test_offer_parsing.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add offer/parsing/parsing.py tests/offer/test_offer_parsing.py
git commit -m "feat(offer/parsing): add parse() orchestration for per-offer extraction"
```

---

## Task 7: Create `offer/offer.py`

**Files:**
- Create: `offer/offer.py`
- Test: `tests/offer/test_offer.py`

- [ ] **Step 1: Write failing tests**

Create `tests/offer/test_offer.py`:

```python
from datetime import date
from unittest.mock import MagicMock, patch

from offer.models import EnrichedOffer, OfferExtraction
from offer.offer import enrich_all
from offer.scraping.models import JobOffer


def _make_offer(title: str, description: str | None = "Some job description.") -> JobOffer:
    return JobOffer(
        title=title,
        company="Acme",
        location="Berlin",
        url=f"https://example.com/{title}",
        source="test",
        posted_at=date(2024, 1, 15),
        description=description,
    )


def test_enrich_all_returns_enriched_offers():
    offers = [_make_offer("Python Engineer"), _make_offer("Data Scientist")]
    extraction = OfferExtraction(employment_type="full-time", seniority="senior")

    with patch("offer.offer.scrape", return_value=offers):
        with patch("offer.offer.parse", return_value=extraction):
            results = enrich_all("python", hours=72, client=MagicMock())

    assert len(results) == 2
    assert all(isinstance(r, EnrichedOffer) for r in results)
    assert results[0].title == "Python Engineer"
    assert results[0].employment_type == "full-time"
    assert results[0].seniority == "senior"
    assert results[1].title == "Data Scientist"


def test_enrich_all_returns_empty_list_when_no_offers():
    with patch("offer.offer.scrape", return_value=[]):
        results = enrich_all("python", hours=72, client=MagicMock())

    assert results == []


def test_enrich_all_calls_parse_once_per_offer():
    offers = [_make_offer("Job A"), _make_offer("Job B"), _make_offer("Job C")]

    with patch("offer.offer.scrape", return_value=offers):
        with patch("offer.offer.parse", return_value=OfferExtraction()) as mock_parse:
            enrich_all("python", hours=72, client=MagicMock())

    assert mock_parse.call_count == 3


def test_enrich_all_preserves_offer_identity_fields():
    offer = _make_offer("ML Engineer")
    offer.company = "DeepMind"
    offer.location = "London"
    offer.source = "remotive"
    offer.posted_at = date(2024, 3, 10)

    with patch("offer.offer.scrape", return_value=[offer]):
        with patch("offer.offer.parse", return_value=OfferExtraction()):
            results = enrich_all("ml", hours=72, client=MagicMock())

    assert results[0].company == "DeepMind"
    assert results[0].location == "London"
    assert results[0].source == "remotive"
    assert results[0].posted_at == date(2024, 3, 10)


def test_enrich_all_handles_offers_with_no_description():
    offer = _make_offer("Python Dev", description=None)
    extraction = OfferExtraction()  # all None — parse() returns this for no description

    with patch("offer.offer.scrape", return_value=[offer]):
        with patch("offer.offer.parse", return_value=extraction):
            results = enrich_all("python", hours=72, client=MagicMock())

    assert len(results) == 1
    assert results[0].employment_type is None
    assert results[0].seniority is None
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/offer/test_offer.py -v
```

Expected: `ImportError` — `offer.offer` not yet defined.

- [ ] **Step 3: Create `offer/offer.py`**

```python
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
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/offer/test_offer.py -v
```

Expected: all PASS.

- [ ] **Step 5: Run the full test suite**

```bash
pytest tests/ -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add offer/offer.py tests/offer/test_offer.py
git commit -m "feat(offer): add enrich_all() merging scraping and parsing"
```

---

## Self-Review

**Spec coverage:**
- [x] `_strip_html` helper → Task 1
- [x] `description` field on `JobOffer` → Task 1
- [x] All 4 sources populate `description` → Task 2
- [x] `offer/scraping/scraping.py` extracted → Task 3
- [x] `offer/models.py` with `OfferExtraction` + `EnrichedOffer` → Task 4
- [x] `offer/parsing/extractor.py` → Task 5
- [x] `offer/parsing/parsing.py` → Task 6
- [x] `offer/offer.py` → Task 7
- [x] Empty description guard → Task 6 (`parse` returns `OfferExtraction()`)
- [x] LLM failure returns empty extraction → Task 5
- [x] Sequential parsing → Task 7 (plain `for` loop)

**Type consistency check:**
- `extract_with_llm(offer: JobOffer, client: Groq) -> OfferExtraction` — defined Task 5, used Task 6 ✓
- `parse(offer: JobOffer, client: Groq) -> OfferExtraction` — defined Task 6, used Task 7 ✓
- `scrape(query, hours, sources=None) -> list[JobOffer]` — defined Task 3, used Task 7 ✓
- `enrich_all(query, hours, client) -> list[EnrichedOffer]` — defined Task 7 ✓
- `EnrichedOffer` fields match `JobOffer` + `OfferExtraction` fields — checked ✓
