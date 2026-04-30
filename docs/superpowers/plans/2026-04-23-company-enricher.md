# Company Enricher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a `enricher/` module that takes a company name + location and returns a `CompanyProfile` with website, country, founded year, employee count, industry, type, and Glassdoor review score.

**Architecture:** DuckDuckGo search discovers relevant URLs (company website + Glassdoor page), `requests` fetches them with Playwright as a fallback for bot-blocked pages, JSON-LD structured data is parsed first, and a Groq LLM call fills any remaining gaps from the raw page text — same pipeline for every field.

**Tech Stack:** `duckduckgo-search`, `beautifulsoup4`, `playwright`, `groq` (already installed), `requests` (already installed), `llama-3.3-70b-versatile` model (same as `cover_letter.py`).

---

## File Map

| File | Responsibility |
|---|---|
| `enricher/__init__.py` | Empty package marker |
| `enricher/models.py` | `CompanyProfile` dataclass |
| `enricher/searcher.py` | DuckDuckGo → `dict[str, str]` of source→URL |
| `enricher/fetcher.py` | `requests` fetch + Playwright fallback → HTML string |
| `enricher/extractor.py` | JSON-LD parser + Groq LLM extraction → `dict` |
| `enricher/enricher.py` | Orchestrator: search → fetch → extract → merge → `CompanyProfile` |
| `enricher/__main__.py` | CLI smoke test: `python -m enricher "Acme" "Berlin"` |
| `tests/enricher/__init__.py` | Empty package marker |
| `tests/enricher/test_models.py` | Tests for `CompanyProfile` |
| `tests/enricher/test_searcher.py` | Tests for `search_company_urls` |
| `tests/enricher/test_fetcher.py` | Tests for `fetch_html` |
| `tests/enricher/test_extractor.py` | Tests for `extract_jsonld` and `extract_with_llm` |

---

## Task 1: CompanyProfile model

**Files:**
- Create: `enricher/__init__.py`
- Create: `enricher/models.py`
- Create: `tests/enricher/__init__.py`
- Create: `tests/enricher/test_models.py`

- [ ] **Step 1: Create package markers**

```bash
touch enricher/__init__.py tests/enricher/__init__.py
```

- [ ] **Step 2: Write the failing test**

`tests/enricher/test_models.py`:
```python
from enricher.models import CompanyProfile


def test_company_profile_requires_name():
    p = CompanyProfile(name="Acme")
    assert p.name == "Acme"


def test_company_profile_all_fields_default_to_none():
    p = CompanyProfile(name="Acme")
    assert p.website is None
    assert p.country is None
    assert p.founded_year is None
    assert p.employee_count is None
    assert p.industry is None
    assert p.company_type is None
    assert p.review_score is None
    assert p.review_count is None
    assert p.description is None


def test_company_profile_accepts_all_fields():
    p = CompanyProfile(
        name="Acme",
        website="https://acme.com",
        country="DE",
        founded_year=2010,
        employee_count="51-200",
        industry="Software",
        company_type="saas",
        review_score=4.2,
        review_count=312,
        description="Acme makes things.",
    )
    assert p.review_score == 4.2
    assert p.founded_year == 2010
```

- [ ] **Step 3: Run test to verify it fails**

```bash
python -m pytest tests/enricher/test_models.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'enricher.models'`

- [ ] **Step 4: Write the model**

`enricher/models.py`:
```python
from dataclasses import dataclass


@dataclass
class CompanyProfile:
    name: str
    website: str | None = None
    country: str | None = None
    founded_year: int | None = None
    employee_count: str | None = None
    industry: str | None = None
    company_type: str | None = None
    review_score: float | None = None
    review_count: int | None = None
    description: str | None = None
```

- [ ] **Step 5: Run test to verify it passes**

```bash
python -m pytest tests/enricher/test_models.py -v
```
Expected: 3 PASSED

- [ ] **Step 6: Commit**

```bash
git add enricher/__init__.py enricher/models.py tests/enricher/__init__.py tests/enricher/test_models.py
git commit -m "feat: add CompanyProfile model for company enricher"
```

---

## Task 2: Add dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Install new dependencies**

```bash
uv add duckduckgo-search beautifulsoup4 playwright
python -m playwright install chromium
```

- [ ] **Step 2: Verify they're importable**

```bash
python -c "from duckduckgo_search import DDGS; from bs4 import BeautifulSoup; from playwright.sync_api import sync_playwright; print('ok')"
```
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add duckduckgo-search, beautifulsoup4, playwright for company enricher"
```

---

## Task 3: Searcher

**Files:**
- Create: `enricher/searcher.py`
- Create: `tests/enricher/test_searcher.py`

- [ ] **Step 1: Write the failing tests**

`tests/enricher/test_searcher.py`:
```python
from unittest.mock import MagicMock, patch

from enricher.searcher import search_company_urls


def test_search_returns_website_and_glassdoor():
    website_hit = [{"href": "https://acme.com", "title": "Acme Corp"}]
    glassdoor_hit = [{"href": "https://www.glassdoor.com/Overview/acme", "title": "Acme Glassdoor"}]

    with patch("enricher.searcher.DDGS") as mock_ddgs:
        instance = MagicMock()
        mock_ddgs.return_value.__enter__.return_value = instance
        instance.text.side_effect = [website_hit, glassdoor_hit]

        result = search_company_urls("Acme", "Berlin")

    assert result["website"] == "https://acme.com"
    assert result["glassdoor"] == "https://www.glassdoor.com/Overview/acme"


def test_search_omits_missing_sources():
    with patch("enricher.searcher.DDGS") as mock_ddgs:
        instance = MagicMock()
        mock_ddgs.return_value.__enter__.return_value = instance
        instance.text.return_value = []

        result = search_company_urls("Unknown Corp", "Nowhere")

    assert result == {}


def test_search_returns_partial_when_one_source_missing():
    website_hit = [{"href": "https://acme.com", "title": "Acme"}]

    with patch("enricher.searcher.DDGS") as mock_ddgs:
        instance = MagicMock()
        mock_ddgs.return_value.__enter__.return_value = instance
        instance.text.side_effect = [website_hit, []]

        result = search_company_urls("Acme", "Berlin")

    assert result == {"website": "https://acme.com"}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/enricher/test_searcher.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'enricher.searcher'`

- [ ] **Step 3: Write the searcher**

`enricher/searcher.py`:
```python
import logging
from duckduckgo_search import DDGS

logger = logging.getLogger(__name__)

_QUERIES = {
    "website": '"{name}" {location} official website',
    "glassdoor": '"{name}" {location} glassdoor',
}


def search_company_urls(name: str, location: str) -> dict[str, str]:
    results = {}
    with DDGS() as ddgs:
        for source, template in _QUERIES.items():
            query = template.format(name=name, location=location)
            try:
                hits = list(ddgs.text(query, max_results=1))
                if hits:
                    results[source] = hits[0]["href"]
            except Exception as e:
                logger.warning("DDG search failed for %s: %s", source, e)
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/enricher/test_searcher.py -v
```
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add enricher/searcher.py tests/enricher/test_searcher.py
git commit -m "feat: add DDG-based URL searcher for company enricher"
```

---

## Task 4: Fetcher

**Files:**
- Create: `enricher/fetcher.py`
- Create: `tests/enricher/test_fetcher.py`

- [ ] **Step 1: Write the failing tests**

`tests/enricher/test_fetcher.py`:
```python
from unittest.mock import MagicMock, patch

from enricher.fetcher import fetch_html


def test_fetch_returns_html_on_200():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><body>Hello</body></html>"

    with patch("enricher.fetcher.requests.get", return_value=mock_resp):
        result = fetch_html("https://example.com")

    assert result == "<html><body>Hello</body></html>"


def test_fetch_falls_back_to_playwright_on_403():
    mock_resp = MagicMock()
    mock_resp.status_code = 403

    with patch("enricher.fetcher.requests.get", return_value=mock_resp):
        with patch("enricher.fetcher._fetch_with_playwright", return_value="<html>pw</html>"):
            result = fetch_html("https://example.com")

    assert result == "<html>pw</html>"


def test_fetch_falls_back_to_playwright_on_exception():
    with patch("enricher.fetcher.requests.get", side_effect=Exception("timeout")):
        with patch("enricher.fetcher._fetch_with_playwright", return_value="<html>pw</html>"):
            result = fetch_html("https://example.com")

    assert result == "<html>pw</html>"


def test_fetch_returns_none_when_both_fail():
    with patch("enricher.fetcher.requests.get", side_effect=Exception("timeout")):
        with patch("enricher.fetcher._fetch_with_playwright", return_value=None):
            result = fetch_html("https://example.com")

    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/enricher/test_fetcher.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'enricher.fetcher'`

- [ ] **Step 3: Write the fetcher**

`enricher/fetcher.py`:
```python
import logging
import requests

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def fetch_html(url: str) -> str | None:
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        if resp.status_code == 200:
            return resp.text
    except Exception as e:
        logger.debug("requests failed for %s: %s", url, e)
    return _fetch_with_playwright(url)


def _fetch_with_playwright(url: str) -> str | None:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=15000)
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        logger.warning("Playwright failed for %s: %s", url, e)
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/enricher/test_fetcher.py -v
```
Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add enricher/fetcher.py tests/enricher/test_fetcher.py
git commit -m "feat: add HTML fetcher with Playwright fallback for company enricher"
```

---

## Task 5: Extractor

**Files:**
- Create: `enricher/extractor.py`
- Create: `tests/enricher/test_extractor.py`

- [ ] **Step 1: Write the failing tests**

`tests/enricher/test_extractor.py`:
```python
import json
from unittest.mock import MagicMock

from enricher.extractor import extract_jsonld, extract_with_llm

_HTML_WITH_JSONLD = """<html><head>
<script type="application/ld+json">
{
  "@type": "Organization",
  "url": "https://acme.com",
  "description": "Acme makes things.",
  "foundingDate": "2010",
  "numberOfEmployees": {"value": "51-200"},
  "aggregateRating": {"ratingValue": "4.2", "reviewCount": "312"},
  "address": {"addressCountry": "DE"}
}
</script>
</head><body></body></html>"""

_HTML_NO_JSONLD = "<html><body>We are Acme, founded in 2010 in Berlin.</body></html>"


def test_extract_jsonld_parses_all_fields():
    result = extract_jsonld(_HTML_WITH_JSONLD)
    assert result["website"] == "https://acme.com"
    assert result["review_score"] == 4.2
    assert result["review_count"] == 312
    assert result["country"] == "DE"
    assert result["founded_year"] == 2010
    assert result["employee_count"] == "51-200"
    assert result["description"] == "Acme makes things."


def test_extract_jsonld_returns_empty_on_no_jsonld():
    result = extract_jsonld(_HTML_NO_JSONLD)
    assert result == {}


def test_extract_jsonld_returns_empty_on_wrong_type():
    html = """<html><head><script type="application/ld+json">
    {"@type": "WebPage", "name": "Home"}
    </script></head></html>"""
    result = extract_jsonld(html)
    assert result == {}


def test_extract_with_llm_returns_parsed_fields():
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value.choices[0].message.content = json.dumps({
        "website": "https://acme.com",
        "country": "Germany",
        "founded_year": 2010,
        "employee_count": "51-200",
        "industry": "Software",
        "company_type": "saas",
        "review_score": 4.2,
        "review_count": 312,
        "description": "Acme makes things.",
    })

    result = extract_with_llm(_HTML_NO_JSONLD, "Acme", "Berlin", mock_client)

    assert result["country"] == "Germany"
    assert result["company_type"] == "saas"
    assert result["founded_year"] == 2010


def test_extract_with_llm_handles_invalid_json():
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value.choices[0].message.content = "not json at all"

    result = extract_with_llm(_HTML_NO_JSONLD, "Acme", "Berlin", mock_client)

    assert result == {}


def test_extract_with_llm_strips_markdown_code_block():
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value.choices[0].message.content = (
        "```json\n{\"country\": \"Germany\"}\n```"
    )

    result = extract_with_llm(_HTML_NO_JSONLD, "Acme", "Berlin", mock_client)

    assert result["country"] == "Germany"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/enricher/test_extractor.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'enricher.extractor'`

- [ ] **Step 3: Write the extractor**

`enricher/extractor.py`:
```python
import json
import logging
from bs4 import BeautifulSoup
from groq import Groq

logger = logging.getLogger(__name__)

_ORG_TYPES = ("Organization", "LocalBusiness", "Corporation")

_LLM_PROMPT = (
    "Extract company information from the following web page text. "
    "Return ONLY valid JSON with exactly these fields (use null if unknown):\n"
    '{"website": str, "country": str, "founded_year": int, "employee_count": str, '
    '"industry": str, "company_type": "consulting"|"saas"|"product"|"agency"|"startup"|"enterprise"|"ngo"|"other", '
    '"review_score": float, "review_count": int, "description": str}\n\n'
    "Company name: {name}\n"
    "Location hint: {location}\n\n"
    "Page text:\n{text}"
)


def extract_jsonld(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    result = {}

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, list):
                data = next((d for d in data if d.get("@type") in _ORG_TYPES), {})
            if data.get("@type") not in _ORG_TYPES:
                continue

            if url := data.get("url"):
                result["website"] = url
            if desc := data.get("description"):
                result["description"] = desc
            if rating := data.get("aggregateRating"):
                try:
                    result["review_score"] = float(rating["ratingValue"])
                    result["review_count"] = int(rating["reviewCount"])
                except (KeyError, ValueError):
                    pass
            if address := data.get("address"):
                result["country"] = address.get("addressCountry")
            if employees := data.get("numberOfEmployees"):
                val = employees.get("value", employees) if isinstance(employees, dict) else employees
                result["employee_count"] = str(val)
            if founded := data.get("foundingDate"):
                try:
                    result["founded_year"] = int(str(founded)[:4])
                except ValueError:
                    pass
        except (json.JSONDecodeError, AttributeError):
            continue

    return result


def extract_with_llm(html: str, name: str, location: str, client: Groq) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)[:3000]

    prompt = _LLM_PROMPT.format(name=name, location=location, text=text)

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.choices[0].message.content.strip()

        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1].lstrip("json").strip() if len(parts) > 1 else raw

        return json.loads(raw)
    except Exception as e:
        logger.warning("LLM extraction failed: %s", e)
        return {}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/enricher/test_extractor.py -v
```
Expected: 6 PASSED

- [ ] **Step 5: Commit**

```bash
git add enricher/extractor.py tests/enricher/test_extractor.py
git commit -m "feat: add JSON-LD and Groq LLM extractor for company enricher"
```

---

## Task 6: Enricher Orchestrator

**Files:**
- Create: `enricher/enricher.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/enricher/test_enricher.py`:
```python
from unittest.mock import MagicMock, patch

from enricher.enricher import enrich
from enricher.models import CompanyProfile


def _make_client():
    return MagicMock()


def test_enrich_returns_company_profile():
    with patch("enricher.enricher.search_company_urls", return_value={"website": "https://acme.com"}):
        with patch("enricher.enricher.fetch_html", return_value="<html></html>"):
            with patch("enricher.enricher.extract_jsonld", return_value={"country": "DE", "founded_year": 2010}):
                with patch("enricher.enricher.extract_with_llm", return_value={"industry": "Software", "company_type": "saas"}):
                    result = enrich("Acme", "Berlin", _make_client())

    assert isinstance(result, CompanyProfile)
    assert result.name == "Acme"
    assert result.country == "DE"
    assert result.founded_year == 2010
    assert result.industry == "Software"
    assert result.company_type == "saas"


def test_enrich_jsonld_fields_not_overwritten_by_llm():
    with patch("enricher.enricher.search_company_urls", return_value={"website": "https://acme.com"}):
        with patch("enricher.enricher.fetch_html", return_value="<html></html>"):
            with patch("enricher.enricher.extract_jsonld", return_value={"country": "DE"}):
                with patch("enricher.enricher.extract_with_llm", return_value={"country": "France"}):
                    result = enrich("Acme", "Berlin", _make_client())

    assert result.country == "DE"


def test_enrich_handles_fetch_failure_gracefully():
    with patch("enricher.enricher.search_company_urls", return_value={"website": "https://acme.com"}):
        with patch("enricher.enricher.fetch_html", return_value=None):
            result = enrich("Acme", "Berlin", _make_client())

    assert isinstance(result, CompanyProfile)
    assert result.name == "Acme"
    assert result.country is None


def test_enrich_skips_llm_when_all_fields_present():
    full_data = {
        "website": "https://acme.com", "country": "DE", "founded_year": 2010,
        "employee_count": "51-200", "industry": "Software", "company_type": "saas",
        "review_score": 4.2, "review_count": 312, "description": "Acme makes things.",
    }
    mock_client = _make_client()

    with patch("enricher.enricher.search_company_urls", return_value={"website": "https://acme.com"}):
        with patch("enricher.enricher.fetch_html", return_value="<html></html>"):
            with patch("enricher.enricher.extract_jsonld", return_value=full_data):
                enrich("Acme", "Berlin", mock_client)

    mock_client.chat.completions.create.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/enricher/test_enricher.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'enricher.enricher'`

- [ ] **Step 3: Write the orchestrator**

`enricher/enricher.py`:
```python
import logging
from groq import Groq

from enricher.extractor import extract_jsonld, extract_with_llm
from enricher.fetcher import fetch_html
from enricher.models import CompanyProfile
from enricher.searcher import search_company_urls

logger = logging.getLogger(__name__)

_ALL_FIELDS = [
    "website", "country", "founded_year", "employee_count",
    "industry", "company_type", "review_score", "review_count", "description",
]


def _missing(data: dict) -> list[str]:
    return [f for f in _ALL_FIELDS if not data.get(f)]


def enrich(name: str, location: str, client: Groq) -> CompanyProfile:
    urls = search_company_urls(name, location)
    merged: dict = {}
    website_html: str | None = None

    for source, url in urls.items():
        html = fetch_html(url)
        if not html:
            continue
        if source == "website":
            website_html = html
        for k, v in extract_jsonld(html).items():
            if k not in merged and v is not None:
                merged[k] = v

    if _missing(merged) and website_html:
        for k, v in extract_with_llm(website_html, name, location, client).items():
            if k not in merged and v is not None:
                merged[k] = v

    profile = CompanyProfile(name=name)
    for field, value in merged.items():
        if hasattr(profile, field):
            setattr(profile, field, value)
    return profile
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/enricher/test_enricher.py -v
```
Expected: 4 PASSED

- [ ] **Step 5: Run the full test suite**

```bash
python -m pytest tests/enricher/ -v
```
Expected: all PASSED

- [ ] **Step 6: Commit**

```bash
git add enricher/enricher.py tests/enricher/test_enricher.py
git commit -m "feat: add enricher orchestrator — search, fetch, extract, merge into CompanyProfile"
```

---

## Task 7: CLI smoke test

**Files:**
- Create: `enricher/__main__.py`

- [ ] **Step 1: Write the CLI entry point**

`enricher/__main__.py`:
```python
import os
import sys
from dotenv import load_dotenv
from groq import Groq

from enricher.enricher import enrich

load_dotenv()


def main():
    if len(sys.argv) < 3:
        print("Usage: python -m enricher \"<company name>\" \"<location>\"")
        sys.exit(1)
    name = sys.argv[1]
    location = sys.argv[2]
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    profile = enrich(name, location, client)
    for field in vars(profile):
        value = getattr(profile, field)
        print(f"{field}: {value}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run a live smoke test against a well-known company**

```bash
python -m enricher "Stripe" "San Francisco"
```
Expected: output with at least `name`, `website`, and some non-None fields. Exact values will vary.

- [ ] **Step 3: Run against a smaller European company to test coverage**

```bash
python -m enricher "Personio" "Munich"
```
Expected: some fields populated, `review_score` may be None if Glassdoor snippet unavailable.

- [ ] **Step 4: Commit**

```bash
git add enricher/__main__.py
git commit -m "feat: add CLI entry point for company enricher smoke testing"
```

---

## Self-Review

**Spec coverage:**
- Website URL → `searcher.py` finds it, `extractor.py` parses it ✓
- Employee count → JSON-LD + LLM ✓
- Revenue/financials → not included (no free source for private companies — accepted tradeoff from design discussion) ✓
- Review score → Glassdoor URL found via DDG, JSON-LD or LLM extracts rating ✓
- Company type → LLM classification ✓
- Founded year / stage → JSON-LD `foundingDate` + LLM ✓
- HQ country → JSON-LD `address.addressCountry` + LLM ✓

**Placeholder scan:** None found.

**Type consistency:**
- `search_company_urls` returns `dict[str, str]` — used correctly in `enricher.py` ✓
- `fetch_html` returns `str | None` — None-checked before use ✓
- `extract_jsonld` and `extract_with_llm` both return `dict` — merged identically ✓
- `CompanyProfile` fields match keys used in `_ALL_FIELDS` and `merged` dict ✓
