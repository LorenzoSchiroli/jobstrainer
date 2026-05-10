# Ingestion Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a pipeline orchestrator that scrapes offers, posts them to the backend, and enriches company profiles for any company where half or more of its fields are null.

**Architecture:** A new `client.py` wraps the backend REST API (`POST /jobs`, `POST /companies`). A new `pipeline/__main__.py` orchestrates the full flow: scrape offers via the existing `enrich_all`, post each to the backend (using 201/200 as the dedup signal), then for each unique company check completeness with a simple null-count threshold and run `company.enrich()` if needed. The docker-compose ingestion service is updated to use the new pipeline entrypoint and receive `BACKEND_URL`.

**Tech Stack:** Python 3.13, requests, existing `ingestion.offer.offer.enrich_all`, existing `ingestion.company.company.enrich`, FastAPI backend at `http://backend:8000`

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `ingestion/ingestion/client.py` | Create | HTTP client: `post_job`, `post_company`, reads `BACKEND_URL` from env |
| `ingestion/ingestion/pipeline/__init__.py` | Create | Empty — makes `pipeline` a package |
| `ingestion/ingestion/pipeline/__main__.py` | Create | Pipeline CLI: orchestrates offer scrape → job POST → company POST → company enrich |
| `ingestion/tests/pipeline/__init__.py` | Create | Empty |
| `ingestion/tests/pipeline/test_client.py` | Create | Unit tests for client.py (mock requests) |
| `ingestion/tests/pipeline/test_pipeline.py` | Create | Unit tests for `is_enrichment_needed` |
| `ingestion/Dockerfile` | Modify | Line 19: `ingestion.offer` → `ingestion.pipeline`, remove `--json` |
| `docker-compose.yml` | Modify | Add `BACKEND_URL`, `depends_on: backend` to ingestion service |

---

## Task 1: Backend HTTP client

**Files:**
- Create: `ingestion/ingestion/client.py`
- Create: `ingestion/tests/pipeline/__init__.py`
- Create: `ingestion/tests/pipeline/test_client.py`

- [ ] **Step 1: Create test directory**

```bash
mkdir -p /Users/loryschi/projects/jobstrainer/ingestion/tests/pipeline
touch /Users/loryschi/projects/jobstrainer/ingestion/tests/pipeline/__init__.py
```

- [ ] **Step 2: Write failing tests**

Create `/Users/loryschi/projects/jobstrainer/ingestion/tests/pipeline/test_client.py`:

```python
from unittest.mock import MagicMock, patch
import pytest
from ingestion.offer.models import EnrichedOffer
from ingestion.client import post_job, post_company


@pytest.fixture(autouse=True)
def backend_url(monkeypatch):
    monkeypatch.setenv("BACKEND_URL", "http://localhost:8000")


def _resp(status: int, body: dict) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body
    return r


def _offer(**kwargs) -> EnrichedOffer:
    defaults = dict(
        title="ML Engineer",
        company="Acme Corp",
        location="Berlin",
        url="https://example.com/job/1",
        source="jobspy",
        posted_at=None,
    )
    return EnrichedOffer(**{**defaults, **kwargs})


def test_post_job_renames_company_to_company_name():
    with patch("ingestion.client.requests.post") as mock_post:
        mock_post.return_value = _resp(201, {"id": "abc"})
        post_job(_offer())

    payload = mock_post.call_args.kwargs["json"]
    assert payload["company_name"] == "Acme Corp"
    assert "company" not in payload


def test_post_job_returns_status_and_body():
    with patch("ingestion.client.requests.post") as mock_post:
        mock_post.return_value = _resp(200, {"id": "abc", "title": "ML Engineer"})
        status, body = post_job(_offer())

    assert status == 200
    assert body["id"] == "abc"


def test_post_job_hits_correct_url():
    with patch("ingestion.client.requests.post") as mock_post:
        mock_post.return_value = _resp(201, {})
        post_job(_offer())

    assert mock_post.call_args.args[0] == "http://localhost:8000/jobs"


def test_post_company_sends_dict_and_returns_status():
    with patch("ingestion.client.requests.post") as mock_post:
        mock_post.return_value = _resp(201, {"id": "xyz", "name": "Acme"})
        status, body = post_company({"name": "Acme"})

    assert status == 201
    assert mock_post.call_args.kwargs["json"] == {"name": "Acme"}


def test_post_company_hits_correct_url():
    with patch("ingestion.client.requests.post") as mock_post:
        mock_post.return_value = _resp(200, {})
        post_company({"name": "Acme"})

    assert mock_post.call_args.args[0] == "http://localhost:8000/companies"
```

- [ ] **Step 3: Run tests — expect failure**

```bash
cd /Users/loryschi/projects/jobstrainer/ingestion
uv run pytest tests/pipeline/test_client.py -v 2>&1 | tail -10
```

Expected: `ModuleNotFoundError: No module named 'ingestion.client'`

- [ ] **Step 4: Create the client**

Create `/Users/loryschi/projects/jobstrainer/ingestion/ingestion/client.py`:

```python
import os
import requests
from ingestion.offer.models import EnrichedOffer


def _base() -> str:
    return os.environ["BACKEND_URL"].rstrip("/")


def post_job(offer: EnrichedOffer) -> tuple[int, dict]:
    payload = offer.model_dump(mode="json")
    payload["company_name"] = payload.pop("company")
    resp = requests.post(f"{_base()}/jobs", json=payload)
    resp.raise_for_status()
    return resp.status_code, resp.json()


def post_company(data: dict) -> tuple[int, dict]:
    resp = requests.post(f"{_base()}/companies", json=data)
    resp.raise_for_status()
    return resp.status_code, resp.json()
```

- [ ] **Step 5: Run tests — expect pass**

```bash
cd /Users/loryschi/projects/jobstrainer/ingestion
uv run pytest tests/pipeline/test_client.py -v 2>&1 | tail -10
```

Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
cd /Users/loryschi/projects/jobstrainer
git add ingestion/ingestion/client.py ingestion/tests/pipeline/
git commit -m "feat(ingestion): add backend HTTP client"
```

---

## Task 2: Pipeline orchestrator

**Files:**
- Create: `ingestion/ingestion/pipeline/__init__.py`
- Create: `ingestion/ingestion/pipeline/__main__.py`
- Create: `ingestion/tests/pipeline/test_pipeline.py`

- [ ] **Step 1: Create pipeline package**

```bash
mkdir -p /Users/loryschi/projects/jobstrainer/ingestion/ingestion/pipeline
touch /Users/loryschi/projects/jobstrainer/ingestion/ingestion/pipeline/__init__.py
```

- [ ] **Step 2: Write failing tests for is_enrichment_needed**

Create `/Users/loryschi/projects/jobstrainer/ingestion/tests/pipeline/test_pipeline.py`:

```python
from ingestion.pipeline.__main__ import is_enrichment_needed


def test_all_none_needs_enrichment():
    company = {
        "id": "1", "name": "Acme", "website": None,
        "country": None, "founded_year": None, "employee_count": None,
    }
    assert is_enrichment_needed(company) is True


def test_exactly_half_none_needs_enrichment():
    # 3 None out of 6 = 50% — threshold is >=, so True
    company = {
        "id": "1", "name": "Acme", "website": "acme.com",
        "country": None, "founded_year": None, "employee_count": None,
    }
    assert is_enrichment_needed(company) is True


def test_majority_populated_no_enrichment():
    company = {
        "id": "1", "name": "Acme", "website": "acme.com",
        "country": "US", "founded_year": 2010, "employee_count": "100-500",
    }
    assert is_enrichment_needed(company) is False


def test_one_null_no_enrichment():
    # 1 out of 6 = 17% → False
    company = {
        "id": "1", "name": "Acme", "website": "acme.com",
        "country": "US", "founded_year": None, "employee_count": "100-500",
    }
    assert is_enrichment_needed(company) is False


def test_bool_false_is_not_null():
    company = {
        "id": "1", "name": "Acme", "is_consulting": False,
        "is_startup": False, "website": "acme.com", "country": "US",
    }
    assert is_enrichment_needed(company) is False
```

- [ ] **Step 3: Run tests — expect failure**

```bash
cd /Users/loryschi/projects/jobstrainer/ingestion
uv run pytest tests/pipeline/test_pipeline.py -v 2>&1 | tail -10
```

Expected: `ModuleNotFoundError: No module named 'ingestion.pipeline'`

- [ ] **Step 4: Create the pipeline orchestrator**

Create `/Users/loryschi/projects/jobstrainer/ingestion/ingestion/pipeline/__main__.py`:

```python
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
```

- [ ] **Step 5: Run all pipeline tests — expect pass**

```bash
cd /Users/loryschi/projects/jobstrainer/ingestion
uv run pytest tests/pipeline/ -v 2>&1 | tail -15
```

Expected: 10 passed (5 client + 5 pipeline).

- [ ] **Step 6: Commit**

```bash
cd /Users/loryschi/projects/jobstrainer
git add ingestion/ingestion/pipeline/ ingestion/tests/pipeline/test_pipeline.py
git commit -m "feat(ingestion): add pipeline orchestrator with company enrichment"
```

---

## Task 3: Wire docker-compose and Dockerfile

**Files:**
- Modify: `ingestion/Dockerfile` (line 19)
- Modify: `docker-compose.yml` (ingestion service block)

- [ ] **Step 1: Update Dockerfile CMD**

In `/Users/loryschi/projects/jobstrainer/ingestion/Dockerfile`, line 19 currently reads:

```dockerfile
CMD ["sh", "-c", "if [ -z \"$OFFER_QUERY\" ]; then echo 'ERROR: OFFER_QUERY is not set' >&2; exit 1; fi; while true; do uv run python -m ingestion.offer \"$OFFER_QUERY\" --hours 2 --json; sleep 7200; done"]
```

Replace with:

```dockerfile
CMD ["sh", "-c", "if [ -z \"$OFFER_QUERY\" ]; then echo 'ERROR: OFFER_QUERY is not set' >&2; exit 1; fi; while true; do uv run python -m ingestion.pipeline \"$OFFER_QUERY\" --hours 2; sleep 7200; done"]
```

Two changes: `ingestion.offer` → `ingestion.pipeline`, and `--json` removed (data goes to backend now, not a file).

- [ ] **Step 2: Update docker-compose.yml ingestion service**

In `/Users/loryschi/projects/jobstrainer/docker-compose.yml`, the ingestion service block (lines 30–39) currently reads:

```yaml
  ingestion:
    build:
      context: .
      dockerfile: ingestion/Dockerfile
    restart: unless-stopped
    environment:
      OFFER_QUERY: "machine learning engineer"
      GROQ_API_KEY: ${GROQ_API_KEY}
    volumes:
      - ./data:/app/ingestion/data
```

Replace with:

```yaml
  ingestion:
    build:
      context: .
      dockerfile: ingestion/Dockerfile
    restart: unless-stopped
    environment:
      OFFER_QUERY: "machine learning engineer"
      GROQ_API_KEY: ${GROQ_API_KEY}
      BACKEND_URL: http://backend:8000
    volumes:
      - ./data:/app/ingestion/data
    depends_on:
      backend:
        condition: service_started
```

- [ ] **Step 3: Validate docker-compose config**

```bash
cd /Users/loryschi/projects/jobstrainer
docker compose config --quiet
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
cd /Users/loryschi/projects/jobstrainer
git add ingestion/Dockerfile docker-compose.yml
git commit -m "feat(ingestion): wire pipeline into docker-compose with BACKEND_URL"
```
