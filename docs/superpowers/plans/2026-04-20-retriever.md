# Retriever — Job Offer Search CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a CLI tool (`python -m retriever "<query>"`) that fetches recent job offers from jobspy, Adzuna, Arbeitnow, and Remotive, deduplicates them, filters for English-language titles, and prints a sorted terminal table.

**Architecture:** Each source implements a common `Source` interface with a single `fetch(query, days) -> list[JobOffer]` method. The CLI runs all enabled sources concurrently via `ThreadPoolExecutor`, merges results through the deduplicator, sorts by date, and renders a table with `tabulate`.

**Tech Stack:** Python 3.13+, `python-jobspy`, `requests`, `tabulate`, `pytest`, `python-dotenv` (already present)

---

## File Map

| File | Responsibility |
|---|---|
| `retriever/__init__.py` | Empty package marker |
| `retriever/__main__.py` | `python -m retriever` entry point |
| `retriever/models.py` | `JobOffer` dataclass |
| `retriever/filters.py` | `is_english(text)` heuristic |
| `retriever/deduplicator.py` | Merge + deduplicate `list[JobOffer]` |
| `retriever/cli.py` | Arg parsing, orchestration, table printing |
| `retriever/sources/__init__.py` | Empty package marker |
| `retriever/sources/base.py` | Abstract `Source` base class |
| `retriever/sources/arbeitnow_source.py` | Arbeitnow public REST API (no key) |
| `retriever/sources/remotive_source.py` | Remotive public REST API (no key) |
| `retriever/sources/adzuna_source.py` | Adzuna REST API (key from `.env`) |
| `retriever/sources/jobspy_source.py` | Wraps `python-jobspy` scraper |
| `tests/__init__.py` | Empty |
| `tests/retriever/__init__.py` | Empty |
| `tests/retriever/test_filters.py` | Tests for `is_english` |
| `tests/retriever/test_deduplicator.py` | Tests for deduplication logic |
| `tests/retriever/test_arbeitnow_source.py` | Tests for Arbeitnow source |
| `tests/retriever/test_remotive_source.py` | Tests for Remotive source |
| `tests/retriever/test_adzuna_source.py` | Tests for Adzuna source |
| `tests/retriever/test_jobspy_source.py` | Tests for jobspy source |

---

### Task 1: Add dependencies and scaffold directories

**Files:**
- Modify: `pyproject.toml` (via uv add)
- Create: `retriever/__init__.py`
- Create: `retriever/__main__.py`
- Create: `retriever/sources/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/retriever/__init__.py`

- [ ] **Step 1: Add dependencies**

```bash
uv add python-jobspy requests tabulate pytest
```

Expected: packages installed, `uv.lock` updated.

- [ ] **Step 2: Create directories and empty init files**

```bash
mkdir -p retriever/sources tests/retriever
touch retriever/__init__.py retriever/sources/__init__.py tests/__init__.py tests/retriever/__init__.py
```

- [ ] **Step 3: Create `retriever/__main__.py`**

```python
from retriever.cli import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Verify importable**

```bash
uv run python -c "import retriever; print('ok')"
```

Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add retriever/ tests/ pyproject.toml uv.lock
git commit -m "chore: scaffold retriever module and add dependencies"
```

---

### Task 2: JobOffer dataclass and English filter

**Files:**
- Create: `retriever/models.py`
- Create: `retriever/filters.py`
- Create: `tests/retriever/test_filters.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/retriever/test_filters.py`:

```python
from retriever.filters import is_english


def test_english_title_passes():
    assert is_english("Machine Learning Engineer") is True


def test_german_title_fails():
    assert is_english("Softwareentwickler für maschinelles Lernen") is False


def test_french_title_fails():
    assert is_english("Ingénieur en apprentissage automatique") is False


def test_empty_string_passes():
    assert is_english("") is True


def test_mixed_mostly_ascii_passes():
    assert is_english("Senior Engineer — Berlin") is True
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/retriever/test_filters.py -v
```

Expected: `ModuleNotFoundError: No module named 'retriever.filters'`

- [ ] **Step 3: Create `retriever/models.py`**

```python
from dataclasses import dataclass
from datetime import date


@dataclass
class JobOffer:
    title: str
    company: str
    location: str
    url: str
    source: str
    posted_at: date | None
```

- [ ] **Step 4: Create `retriever/filters.py`**

```python
def is_english(text: str) -> bool:
    if not text:
        return True
    ascii_count = sum(1 for c in text if ord(c) < 128)
    return ascii_count / len(text) >= 0.8
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/retriever/test_filters.py -v
```

Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add retriever/models.py retriever/filters.py tests/retriever/test_filters.py
git commit -m "feat: add JobOffer dataclass and English language filter"
```

---

### Task 3: Deduplicator

**Files:**
- Create: `retriever/deduplicator.py`
- Create: `tests/retriever/test_deduplicator.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/retriever/test_deduplicator.py`:

```python
from retriever.models import JobOffer
from retriever.deduplicator import deduplicate


def _offer(title="Engineer", company="Acme", url="https://example.com/1", source="adzuna"):
    return JobOffer(title=title, company=company, location="London", url=url, source=source, posted_at=None)


def test_no_duplicates_returns_all():
    offers = [_offer(url="https://example.com/1"), _offer(url="https://example.com/2", title="Designer")]
    assert len(deduplicate(offers)) == 2


def test_same_url_deduped():
    offers = [_offer(url="https://example.com/1", source="adzuna"), _offer(url="https://example.com/1", source="remotive")]
    assert len(deduplicate(offers)) == 1


def test_url_trailing_slash_deduped():
    offers = [_offer(url="https://example.com/1/", source="adzuna"), _offer(url="https://example.com/1", source="remotive")]
    assert len(deduplicate(offers)) == 1


def test_same_title_company_deduped():
    offers = [
        _offer(url="https://site1.com/1", title="ML Engineer", company="Acme", source="jobspy:linkedin"),
        _offer(url="https://site2.com/9", title="ML Engineer", company="Acme", source="remotive"),
    ]
    assert len(deduplicate(offers)) == 1


def test_jobspy_preferred_over_remotive():
    offers = [
        _offer(url="https://example.com/1", source="remotive"),
        _offer(url="https://example.com/1", source="jobspy:linkedin"),
    ]
    result = deduplicate(offers)
    assert result[0].source == "jobspy:linkedin"


def test_adzuna_preferred_over_arbeitnow():
    offers = [
        _offer(url="https://example.com/1", source="arbeitnow"),
        _offer(url="https://example.com/1", source="adzuna"),
    ]
    result = deduplicate(offers)
    assert result[0].source == "adzuna"
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/retriever/test_deduplicator.py -v
```

Expected: `ModuleNotFoundError: No module named 'retriever.deduplicator'`

- [ ] **Step 3: Create `retriever/deduplicator.py`**

```python
import re
from retriever.models import JobOffer

_PRIORITY = {"jobspy": 0, "adzuna": 1, "arbeitnow": 2, "remotive": 3}


def _url_key(url: str) -> str:
    return url.rstrip("/").split("?")[0].lower()


def _tc_key(title: str, company: str) -> tuple[str, str]:
    clean = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    return clean(title), clean(company)


def deduplicate(offers: list[JobOffer]) -> list[JobOffer]:
    sorted_offers = sorted(offers, key=lambda o: _PRIORITY.get(o.source.split(":")[0], 99))
    seen_urls: set[str] = set()
    seen_tc: set[tuple[str, str]] = set()
    result: list[JobOffer] = []

    for offer in sorted_offers:
        uk = _url_key(offer.url) if offer.url else None
        tk = _tc_key(offer.title, offer.company)

        if uk and uk in seen_urls:
            continue
        if tk in seen_tc:
            continue

        if uk:
            seen_urls.add(uk)
        seen_tc.add(tk)
        result.append(offer)

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/retriever/test_deduplicator.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add retriever/deduplicator.py tests/retriever/test_deduplicator.py
git commit -m "feat: add deduplicator with URL and title/company matching"
```

---

### Task 4: Abstract Source base class

**Files:**
- Create: `retriever/sources/base.py`

- [ ] **Step 1: Create `retriever/sources/base.py`**

```python
from abc import ABC, abstractmethod
from retriever.models import JobOffer


class Source(ABC):
    @abstractmethod
    def fetch(self, query: str, days: int) -> list[JobOffer]:
        """Return offers matching query posted within the last `days` days. Never raises — return [] on failure."""
```

- [ ] **Step 2: Verify import**

```bash
uv run python -c "from retriever.sources.base import Source; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add retriever/sources/base.py
git commit -m "feat: add abstract Source base class"
```

---

### Task 5: Arbeitnow source

**Files:**
- Create: `retriever/sources/arbeitnow_source.py`
- Create: `tests/retriever/test_arbeitnow_source.py`

API: `GET https://arbeitnow.com/api/job-board-api`
No auth. Returns all jobs paginated — filter by query and date client-side.
Response shape: `{"data": [{"title", "company_name", "location", "url", "created_at" (Unix int)}]}`

- [ ] **Step 1: Write the failing tests**

Create `tests/retriever/test_arbeitnow_source.py`:

```python
import time
from unittest.mock import MagicMock, patch
from retriever.sources.arbeitnow_source import ArbeitnowSource

_NOW = time.time()

MOCK_RESPONSE = {
    "data": [
        {
            "title": "Python Developer",
            "company_name": "TechCorp",
            "location": "Berlin, Germany",
            "url": "https://arbeitnow.com/jobs/python-dev-123",
            "created_at": int(_NOW - 3600),  # 1 hour ago — within 3 days
        },
        {
            "title": "Softwareentwickler",  # German title — should be discarded
            "company_name": "GmbH AG",
            "location": "Munich",
            "url": "https://arbeitnow.com/jobs/sw-456",
            "created_at": int(_NOW - 3600),
        },
        {
            "title": "Data Engineer",
            "company_name": "OldCorp",
            "location": "Amsterdam",
            "url": "https://arbeitnow.com/jobs/de-789",
            "created_at": int(_NOW - 7 * 24 * 3600),  # 7 days ago — too old
        },
    ]
}


def _mock_get(response):
    mock = MagicMock()
    mock.json.return_value = response
    mock.raise_for_status = MagicMock()
    return mock


def test_returns_matching_english_offers_within_days():
    with patch("retriever.sources.arbeitnow_source.requests.get", return_value=_mock_get(MOCK_RESPONSE)):
        results = ArbeitnowSource().fetch("python", days=3)

    assert len(results) == 1
    assert results[0].title == "Python Developer"
    assert results[0].source == "arbeitnow"
    assert results[0].company == "TechCorp"


def test_returns_empty_on_network_error():
    with patch("retriever.sources.arbeitnow_source.requests.get", side_effect=Exception("timeout")):
        assert ArbeitnowSource().fetch("python", days=3) == []
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/retriever/test_arbeitnow_source.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create `retriever/sources/arbeitnow_source.py`**

```python
import logging
import time
import requests
from datetime import date
from retriever.models import JobOffer
from retriever.sources.base import Source
from retriever.filters import is_english

logger = logging.getLogger(__name__)

_API_URL = "https://arbeitnow.com/api/job-board-api"


class ArbeitnowSource(Source):
    def fetch(self, query: str, days: int) -> list[JobOffer]:
        try:
            resp = requests.get(_API_URL, timeout=10)
            resp.raise_for_status()
            data = resp.json().get("data", [])
        except Exception as e:
            logger.warning("Arbeitnow fetch failed: %s", e)
            return []

        cutoff = time.time() - days * 24 * 3600
        query_lower = query.lower()
        results = []

        for item in data:
            if item.get("created_at", 0) < cutoff:
                continue
            title = item.get("title", "")
            if query_lower not in title.lower():
                continue
            if not is_english(title):
                continue
            results.append(JobOffer(
                title=title,
                company=item.get("company_name", ""),
                location=item.get("location", ""),
                url=item.get("url", ""),
                source="arbeitnow",
                posted_at=date.fromtimestamp(item["created_at"]) if item.get("created_at") else None,
            ))

        return results
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/retriever/test_arbeitnow_source.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add retriever/sources/arbeitnow_source.py tests/retriever/test_arbeitnow_source.py
git commit -m "feat: add Arbeitnow source"
```

---

### Task 6: Remotive source

**Files:**
- Create: `retriever/sources/remotive_source.py`
- Create: `tests/retriever/test_remotive_source.py`

API: `GET https://remotive.com/api/remote-jobs?search=<query>&limit=100`
No auth. Response: `{"jobs": [{"title", "company_name", "url", "candidate_required_location", "publication_date" (ISO string without tz)}]}`

- [ ] **Step 1: Write the failing tests**

Create `tests/retriever/test_remotive_source.py`:

```python
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from retriever.sources.remotive_source import RemotiveSource

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
        },
        {
            "title": "Développeur Python",  # French — should be discarded
            "company_name": "FrenchCo",
            "url": "https://remotive.com/remote-jobs/dev-456",
            "candidate_required_location": "France",
            "publication_date": _recent,
        },
        {
            "title": "Python Engineer",
            "company_name": "OldRemote",
            "url": "https://remotive.com/remote-jobs/py-789",
            "candidate_required_location": "Worldwide",
            "publication_date": _old,  # too old
        },
    ]
}


def _mock_get(response):
    mock = MagicMock()
    mock.json.return_value = response
    mock.raise_for_status = MagicMock()
    return mock


def test_returns_matching_english_offers_within_days():
    with patch("retriever.sources.remotive_source.requests.get", return_value=_mock_get(MOCK_RESPONSE)):
        results = RemotiveSource().fetch("python", days=3)

    assert len(results) == 1
    assert results[0].title == "Senior Python Developer"
    assert results[0].source == "remotive"


def test_returns_empty_on_error():
    with patch("retriever.sources.remotive_source.requests.get", side_effect=Exception("timeout")):
        assert RemotiveSource().fetch("python", days=3) == []
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/retriever/test_remotive_source.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create `retriever/sources/remotive_source.py`**

```python
import logging
import requests
from datetime import date, datetime, timedelta
from retriever.models import JobOffer
from retriever.sources.base import Source
from retriever.filters import is_english

logger = logging.getLogger(__name__)

_API_URL = "https://remotive.com/api/remote-jobs"


class RemotiveSource(Source):
    def fetch(self, query: str, days: int) -> list[JobOffer]:
        try:
            resp = requests.get(_API_URL, params={"search": query, "limit": 100}, timeout=10)
            resp.raise_for_status()
            jobs = resp.json().get("jobs", [])
        except Exception as e:
            logger.warning("Remotive fetch failed: %s", e)
            return []

        cutoff = datetime.now() - timedelta(days=days)
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
            results.append(JobOffer(
                title=title,
                company=item.get("company_name", ""),
                location=item.get("candidate_required_location", "Remote"),
                url=item.get("url", ""),
                source="remotive",
                posted_at=posted.date(),
            ))

        return results
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/retriever/test_remotive_source.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add retriever/sources/remotive_source.py tests/retriever/test_remotive_source.py
git commit -m "feat: add Remotive source"
```

---

### Task 7: Adzuna source

**Files:**
- Create: `retriever/sources/adzuna_source.py`
- Create: `tests/retriever/test_adzuna_source.py`

API: `GET https://api.adzuna.com/v1/api/jobs/{country}/search/1`
Params: `app_id`, `app_key`, `results_per_page=50`, `what=<query>`, `max_days_old=<days>`
Iterates over countries: `["gb", "de", "fr", "nl", "es", "it", "at", "be"]`
Response: `{"results": [{"title", "company": {"display_name"}, "location": {"display_name"}, "redirect_url", "created"}]}`
Keys loaded from `.env` as `ADZUNA_APP_ID` and `ADZUNA_APP_KEY`. If either is missing, return `[]` with a warning.

- [ ] **Step 1: Write the failing tests**

Create `tests/retriever/test_adzuna_source.py`:

```python
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from retriever.sources.adzuna_source import AdzunaSource

_recent = (datetime.now() - timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ")

MOCK_RESPONSE = {
    "results": [
        {
            "title": "Machine Learning Engineer",
            "company": {"display_name": "DataCo"},
            "location": {"display_name": "London, UK"},
            "redirect_url": "https://adzuna.co.uk/jobs/details/123",
            "created": _recent,
        }
    ]
}


def _mock_get(response):
    mock = MagicMock()
    mock.json.return_value = response
    mock.raise_for_status = MagicMock()
    return mock


def test_returns_offers_with_valid_keys():
    with patch.dict("os.environ", {"ADZUNA_APP_ID": "fake_id", "ADZUNA_APP_KEY": "fake_key"}):
        with patch("retriever.sources.adzuna_source.requests.get", return_value=_mock_get(MOCK_RESPONSE)):
            results = AdzunaSource().fetch("machine learning", days=3)

    assert len(results) > 0
    assert results[0].title == "Machine Learning Engineer"
    assert results[0].source == "adzuna"


def test_returns_empty_when_keys_missing():
    with patch.dict("os.environ", {}, clear=True):
        results = AdzunaSource().fetch("machine learning", days=3)
    assert results == []


def test_returns_empty_on_http_error():
    with patch.dict("os.environ", {"ADZUNA_APP_ID": "id", "ADZUNA_APP_KEY": "key"}):
        with patch("retriever.sources.adzuna_source.requests.get", side_effect=Exception("403")):
            results = AdzunaSource().fetch("python", days=3)
    assert results == []
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/retriever/test_adzuna_source.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create `retriever/sources/adzuna_source.py`**

```python
import logging
import os
import requests
from datetime import date, datetime
from retriever.models import JobOffer
from retriever.sources.base import Source
from retriever.filters import is_english

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/1"
_COUNTRIES = ["gb", "de", "fr", "nl", "es", "it", "at", "be"]


class AdzunaSource(Source):
    def fetch(self, query: str, days: int) -> list[JobOffer]:
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
                        "max_days_old": days,
                        "content-type": "application/json",
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
                    ))
            except Exception as e:
                logger.warning("Adzuna fetch failed for %s: %s", country, e)

        return results
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/retriever/test_adzuna_source.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add retriever/sources/adzuna_source.py tests/retriever/test_adzuna_source.py
git commit -m "feat: add Adzuna source with European country iteration"
```

---

### Task 8: jobspy source

**Files:**
- Create: `retriever/sources/jobspy_source.py`
- Create: `tests/retriever/test_jobspy_source.py`

`scrape_jobs` returns a pandas DataFrame with columns: `title`, `company`, `location`, `job_url`, `date_posted` (pandas Timestamp or None), `site` (e.g. `"linkedin"`, `"indeed"`).
Uses `hours_old=days*24`. LinkedIn searches globally; Indeed uses `country_indeed="UK"` for UK results.

- [ ] **Step 1: Write the failing tests**

Create `tests/retriever/test_jobspy_source.py`:

```python
from datetime import date
from unittest.mock import patch
import pandas as pd
from retriever.sources.jobspy_source import JobspySource


def _mock_df():
    return pd.DataFrame([
        {
            "title": "Python Engineer",
            "company": "SpyCorp",
            "location": "London, UK",
            "job_url": "https://linkedin.com/jobs/view/123",
            "date_posted": pd.Timestamp("2026-04-19"),
            "site": "linkedin",
        },
        {
            "title": "Ingenieur Python",  # French — should be discarded
            "company": "FrenchCo",
            "location": "Paris",
            "job_url": "https://linkedin.com/jobs/view/456",
            "date_posted": pd.Timestamp("2026-04-19"),
            "site": "linkedin",
        },
        {
            "title": None,  # missing title — should be discarded
            "company": "NullCo",
            "location": "Berlin",
            "job_url": "https://linkedin.com/jobs/view/789",
            "date_posted": None,
            "site": "indeed",
        },
    ])


def test_returns_english_offers():
    with patch("retriever.sources.jobspy_source.scrape_jobs", return_value=_mock_df()):
        results = JobspySource().fetch("python", days=3)

    assert len(results) == 1
    assert results[0].title == "Python Engineer"
    assert results[0].source == "jobspy:linkedin"


def test_returns_empty_on_scrape_error():
    with patch("retriever.sources.jobspy_source.scrape_jobs", side_effect=Exception("blocked")):
        assert JobspySource().fetch("python", days=3) == []
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/retriever/test_jobspy_source.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create `retriever/sources/jobspy_source.py`**

```python
import logging
from datetime import date
import pandas as pd
from jobspy import scrape_jobs
from retriever.models import JobOffer
from retriever.sources.base import Source
from retriever.filters import is_english

logger = logging.getLogger(__name__)


class JobspySource(Source):
    def fetch(self, query: str, days: int) -> list[JobOffer]:
        try:
            df = scrape_jobs(
                site_name=["linkedin", "indeed"],
                search_term=query,
                hours_old=days * 24,
                results_wanted=50,
                country_indeed="UK",
            )
        except Exception as e:
            logger.warning("jobspy fetch failed: %s", e)
            return []

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
            results.append(JobOffer(
                title=title,
                company=str(row.get("company") or ""),
                location=str(row.get("location") or ""),
                url=str(row.get("job_url") or ""),
                source=f"jobspy:{site}",
                posted_at=posted_at,
            ))

        return results
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/retriever/test_jobspy_source.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add retriever/sources/jobspy_source.py tests/retriever/test_jobspy_source.py
git commit -m "feat: add jobspy source for LinkedIn and Indeed"
```

---

### Task 9: CLI entry point

**Files:**
- Create: `retriever/cli.py`

The CLI loads `.env`, instantiates enabled sources, fetches concurrently, deduplicates, sorts, and prints a table.

- [ ] **Step 1: Create `retriever/cli.py`**

```python
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
```

- [ ] **Step 2: Run a smoke test with a real query**

```bash
uv run python -m retriever "python developer" --sources remotive --days 3
```

Expected: table printed with results, or "No offers found." — no crash or traceback.

- [ ] **Step 3: Test with all sources (Adzuna skipped if no key)**

```bash
uv run python -m retriever "machine learning engineer" --days 3
```

Expected: results from available sources, warning if Adzuna key missing.

- [ ] **Step 4: Test `--sources` flag**

```bash
uv run python -m retriever "data engineer" --sources arbeitnow,remotive --days 3
```

Expected: only Arbeitnow and Remotive results in table.

- [ ] **Step 5: Run full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add retriever/cli.py
git commit -m "feat: add CLI entry point with concurrent fetching and tabulate output"
```

---

### Task 10: Add Adzuna keys to .env and final smoke test

**Files:**
- Create: `.env.example`

- [ ] **Step 1: Create `.env.example`**

```bash
cat > .env.example << 'EOF'
# Adzuna API credentials — free tier at https://developer.adzuna.com/
ADZUNA_APP_ID=your_app_id_here
ADZUNA_APP_KEY=your_app_key_here
EOF
```

- [ ] **Step 2: Add `.env` to .gitignore**

Open `.gitignore` and verify `.env` is listed. If not, add it:

```bash
echo ".env" >> .gitignore
```

- [ ] **Step 3: Run final full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add .env.example .gitignore
git commit -m "chore: add .env.example and verify .gitignore covers .env"
```
