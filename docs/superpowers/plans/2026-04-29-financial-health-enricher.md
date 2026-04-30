# Financial Health Enricher — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add financial health assessment (score 1–5 + rationale) to `CompanyProfile`, driven by a third parallel search query and a dedicated LLM assessment pass.

**Architecture:** The parallel search in `searcher.py` gains a third `"financial"` query; the top result URL is fetched in parallel with the website URL inside `enricher.py`; the fetched HTML and snippets feed a new `assess_financial_health` function in `extractor.py`; the `FinancialHealth` result is stored as a nested field on `CompanyProfile`.

**Tech Stack:** Python 3.13, Pydantic v2, Groq SDK (`llama-3.3-70b-versatile`), ddgs, requests, BeautifulSoup4, pytest + unittest.mock

---

## File Map

| File | Change |
|------|--------|
| `enricher/models.py` | Add `FinancialHealth` model; add `financial_health: FinancialHealth \| None` to `CompanyProfile` |
| `enricher/searcher.py` | Add third parallel `"financial"` query; extend return signature to 3-tuple |
| `enricher/extractor.py` | Add `_strip_markdown_json` helper; add `assess_financial_health` function + prompt |
| `enricher/enricher.py` | Fetch website + financial URLs in parallel; call `assess_financial_health`; add timings |
| `tests/enricher/test_models.py` | Fix `company_type` → `is_consulting`; add `FinancialHealth` tests |
| `tests/enricher/test_extractor.py` | Fix dict → attribute access; fix markdown stripping tests; add financial health tests |
| `tests/enricher/test_searcher.py` | Fix tuple return; switch to `_search`-level mocking; add financial query test |
| `tests/enricher/test_enricher.py` | Fix tuple unpack + mock types; add financial health wire-up tests |

---

### Task 0: Commit pending working tree changes

**Files:**
- Modify: `enricher/enricher.py`, `enricher/fetcher.py`, `enricher/searcher.py`

- [ ] **Step 1: Review pending changes**

```bash
git diff HEAD enricher/
```

- [ ] **Step 2: Commit**

```bash
git add enricher/enricher.py enricher/fetcher.py enricher/searcher.py
git commit -m "feat: Serper fallback, probe paths, find-links timing"
```

---

### Task 1: Fix test_models.py — is_consulting field

**Files:**
- Modify: `tests/enricher/test_models.py`

- [ ] **Step 1: Run failing tests to confirm**

```bash
python -m pytest tests/enricher/test_models.py -v
```
Expected: 2 FAILED (`test_company_profile_all_fields_default_to_none`, `test_company_profile_accepts_all_fields`) — tests reference `company_type` which no longer exists.

- [ ] **Step 2: Replace test_models.py**

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
    assert p.is_consulting is None
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
        is_consulting=False,
        review_score=4.2,
        review_count=312,
        description="Acme makes things.",
    )
    assert p.name == "Acme"
    assert p.website == "https://acme.com"
    assert p.country == "DE"
    assert p.founded_year == 2010
    assert p.employee_count == "51-200"
    assert p.industry == "Software"
    assert p.is_consulting is False
    assert p.review_score == 4.2
    assert p.review_count == 312
    assert p.description == "Acme makes things."
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/enricher/test_models.py -v
```
Expected: 3 PASSED

- [ ] **Step 4: Commit**

```bash
git add tests/enricher/test_models.py
git commit -m "test: fix test_models — company_type → is_consulting"
```

---

### Task 2: Fix test_extractor.py + add markdown stripping

The tests access `extract_with_llm` results as dicts (`result["country"]`) but the function now returns a `CompanyExtraction` pydantic model. The markdown-stripping tests also fail because `model_validate_json` chokes on backtick-wrapped content.

**Files:**
- Modify: `tests/enricher/test_extractor.py`
- Modify: `enricher/extractor.py`

- [ ] **Step 1: Run failing tests**

```bash
python -m pytest tests/enricher/test_extractor.py -v
```
Expected: 4 FAILED

- [ ] **Step 2: Replace test_extractor.py**

```python
import json
from unittest.mock import MagicMock

from enricher.extractor import extract_jsonld, extract_with_llm
from enricher.models import CompanyExtraction

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
        "is_consulting": False,
        "review_score": 4.2,
        "review_count": 312,
        "description": "Acme makes things.",
    })

    result = extract_with_llm(_HTML_NO_JSONLD, "Acme", "Berlin", mock_client)

    assert result.country == "Germany"
    assert result.is_consulting is False
    assert result.founded_year == 2010


def test_extract_with_llm_handles_invalid_json():
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value.choices[0].message.content = "not json at all"

    result = extract_with_llm(_HTML_NO_JSONLD, "Acme", "Berlin", mock_client)

    assert result.country is None
    assert result.founded_year is None


def test_extract_with_llm_strips_markdown_code_block():
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value.choices[0].message.content = (
        '```json\n{"country": "Germany"}\n```'
    )
    result = extract_with_llm(_HTML_NO_JSONLD, "Acme", "Berlin", mock_client)
    assert result.country == "Germany"


def test_extract_with_llm_strips_markdown_code_block_uppercase():
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value.choices[0].message.content = (
        '```JSON\n{"country": "Germany"}\n```'
    )
    result = extract_with_llm(_HTML_NO_JSONLD, "Acme", "Berlin", mock_client)
    assert result.country == "Germany"
```

- [ ] **Step 3: Run — expect markdown stripping tests to still fail**

```bash
python -m pytest tests/enricher/test_extractor.py::test_extract_with_llm_strips_markdown_code_block -v
```
Expected: FAIL — `result.country` is `None` (no stripping yet)

- [ ] **Step 4: Add `_strip_markdown_json` to extractor.py**

Add the import at the top of `enricher/extractor.py`:

```python
import re
```

Add this helper function after the `_SNIPPETS_SECTION` constant:

```python
def _strip_markdown_json(text: str) -> str:
    stripped = re.sub(r"^```(?:json)?\s*\n?", "", text.strip(), flags=re.IGNORECASE)
    return re.sub(r"\n?```\s*$", "", stripped).strip()
```

In the `try` block of `extract_with_llm`, change:

```python
return CompanyExtraction.model_validate_json(response.choices[0].message.content)
```

to:

```python
content = _strip_markdown_json(response.choices[0].message.content)
return CompanyExtraction.model_validate_json(content)
```

- [ ] **Step 5: Run all extractor tests**

```bash
python -m pytest tests/enricher/test_extractor.py -v
```
Expected: 7 PASSED

- [ ] **Step 6: Commit**

```bash
git add enricher/extractor.py tests/enricher/test_extractor.py
git commit -m "fix: strip markdown wrapper before JSON validation; update extractor tests"
```

---

### Task 3: Fix test_searcher.py

`search_company_urls` now returns `tuple[dict[str, str], list[str]]` instead of `dict[str, str]`. The old tests also mock `DDGS` directly which is fragile with `ThreadPoolExecutor` ordering. Switch to mocking at the `_search` level for reliability.

**Files:**
- Modify: `tests/enricher/test_searcher.py`

- [ ] **Step 1: Run failing tests**

```bash
python -m pytest tests/enricher/test_searcher.py -v
```
Expected: 4 FAILED

- [ ] **Step 2: Replace test_searcher.py**

```python
from unittest.mock import patch

from enricher.searcher import search_company_urls


def test_search_returns_website_and_glassdoor_snippets():
    website_hits = [{"href": "https://acme.com", "title": "Acme Corp", "body": ""}]
    glassdoor_hits = [
        {"href": "https://www.glassdoor.com/Overview/acme", "title": "Acme", "body": "Great culture. 4.2 stars based on 35 reviews."},
    ]

    def mock_search(query, max_results):
        if "glassdoor" in query:
            return glassdoor_hits
        return website_hits

    with patch("enricher.searcher._search", side_effect=mock_search):
        urls, snippets = search_company_urls("Acme", "Berlin")

    assert urls["website"] == "https://acme.com"
    assert "glassdoor" not in urls
    assert any("4.2" in s for s in snippets)


def test_search_omits_missing_sources():
    with patch("enricher.searcher._search", return_value=[]):
        urls, snippets = search_company_urls("Unknown Corp", "Nowhere")

    assert urls == {}
    assert snippets == []


def test_search_handles_search_exception_gracefully():
    glassdoor_hits = [
        {"href": "https://www.glassdoor.com/Overview/acme", "title": "Acme", "body": "Nice culture. 4.1 stars."},
    ]

    def mock_search(query, max_results):
        if "glassdoor" in query:
            return glassdoor_hits
        raise Exception("rate limited")

    with patch("enricher.searcher._search", side_effect=mock_search):
        urls, snippets = search_company_urls("Acme", "Berlin")

    assert "website" not in urls
    assert any("4.1" in s for s in snippets)


def test_search_returns_partial_when_glassdoor_empty():
    website_hits = [{"href": "https://acme.com", "title": "Acme", "body": ""}]

    def mock_search(query, max_results):
        if "glassdoor" in query:
            return []
        return website_hits

    with patch("enricher.searcher._search", side_effect=mock_search):
        urls, snippets = search_company_urls("Acme", "Berlin")

    assert urls == {"website": "https://acme.com"}
    assert snippets == []
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/enricher/test_searcher.py -v
```
Expected: 4 PASSED

- [ ] **Step 4: Commit**

```bash
git add tests/enricher/test_searcher.py
git commit -m "test: fix test_searcher — tuple return, _search-level mocking"
```

---

### Task 4: Fix test_enricher.py

`enrich` now returns `tuple[CompanyProfile, list]`, `search_company_urls` returns a 2-tuple, and `extract_with_llm` returns `CompanyExtraction`. Also need to patch `find_relevant_links` to prevent real network calls in tests.

**Files:**
- Modify: `tests/enricher/test_enricher.py`

- [ ] **Step 1: Run failing tests**

```bash
python -m pytest tests/enricher/test_enricher.py -v
```
Expected: 4 FAILED

- [ ] **Step 2: Replace test_enricher.py**

```python
from unittest.mock import MagicMock, patch

from enricher.enricher import enrich
from enricher.models import CompanyExtraction, CompanyProfile


def _make_client():
    return MagicMock()


def test_enrich_returns_company_profile():
    extraction = CompanyExtraction(industry="Software", is_consulting=False)

    with patch("enricher.enricher.search_company_urls", return_value=({"website": "https://acme.com"}, [])):
        with patch("enricher.enricher.fetch_html", return_value="<html></html>"):
            with patch("enricher.enricher.extract_jsonld", return_value={"country": "DE", "founded_year": 2010}):
                with patch("enricher.enricher.find_relevant_links", return_value=[]):
                    with patch("enricher.enricher.extract_with_llm", return_value=extraction):
                        result, _ = enrich("Acme", "Berlin", _make_client())

    assert isinstance(result, CompanyProfile)
    assert result.name == "Acme"
    assert result.country == "DE"
    assert result.founded_year == 2010
    assert result.industry == "Software"
    assert result.is_consulting is False


def test_enrich_jsonld_fields_not_overwritten_by_llm():
    extraction = CompanyExtraction(country="France")

    with patch("enricher.enricher.search_company_urls", return_value=({"website": "https://acme.com"}, [])):
        with patch("enricher.enricher.fetch_html", return_value="<html></html>"):
            with patch("enricher.enricher.extract_jsonld", return_value={"country": "DE"}):
                with patch("enricher.enricher.find_relevant_links", return_value=[]):
                    with patch("enricher.enricher.extract_with_llm", return_value=extraction):
                        result, _ = enrich("Acme", "Berlin", _make_client())

    assert result.country == "DE"


def test_enrich_handles_fetch_failure_gracefully():
    with patch("enricher.enricher.search_company_urls", return_value=({"website": "https://acme.com"}, [])):
        with patch("enricher.enricher.fetch_html", return_value=None):
            result, _ = enrich("Acme", "Berlin", _make_client())

    assert isinstance(result, CompanyProfile)
    assert result.name == "Acme"
    assert result.country is None


def test_enrich_skips_llm_when_all_fields_present():
    full_data = {
        "website": "https://acme.com", "country": "DE", "founded_year": 2010,
        "employee_count": "51-200", "industry": "Software", "is_consulting": False,
        "review_score": 4.2, "review_count": 312, "description": "Acme makes things.",
    }

    with patch("enricher.enricher.search_company_urls", return_value=({"website": "https://acme.com"}, [])):
        with patch("enricher.enricher.fetch_html", return_value="<html></html>"):
            with patch("enricher.enricher.extract_jsonld", return_value=full_data):
                with patch("enricher.enricher.extract_with_llm") as mock_llm:
                    enrich("Acme", "Berlin", _make_client())

    mock_llm.assert_not_called()
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/enricher/test_enricher.py -v
```
Expected: 4 PASSED

- [ ] **Step 4: Run full enricher test suite**

```bash
python -m pytest tests/enricher/ -v
```
Expected: all PASSED (no failures)

- [ ] **Step 5: Commit**

```bash
git add tests/enricher/test_enricher.py
git commit -m "test: fix test_enricher — tuple return, CompanyExtraction mocks, find_relevant_links patch"
```

---

### Task 5: Add FinancialHealth model

**Files:**
- Modify: `tests/enricher/test_models.py`
- Modify: `enricher/models.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/enricher/test_models.py`:

```python
from enricher.models import FinancialHealth


def test_financial_health_requires_score_and_rationale():
    fh = FinancialHealth(score=3, rationale="Stable company, no major signals.")
    assert fh.score == 3
    assert fh.rationale == "Stable company, no major signals."


def test_company_profile_accepts_financial_health():
    fh = FinancialHealth(score=4, rationale="Growing revenue.")
    p = CompanyProfile(name="Acme", financial_health=fh)
    assert p.financial_health.score == 4
    assert p.financial_health.rationale == "Growing revenue."


def test_company_profile_financial_health_defaults_to_none():
    p = CompanyProfile(name="Acme")
    assert p.financial_health is None
```

- [ ] **Step 2: Run to verify fail**

```bash
python -m pytest tests/enricher/test_models.py::test_financial_health_requires_score_and_rationale -v
```
Expected: FAIL — `cannot import name 'FinancialHealth'`

- [ ] **Step 3: Update enricher/models.py**

Replace the entire file:

```python
from pydantic import BaseModel


class FinancialHealth(BaseModel):
    score: int
    rationale: str


class CompanyExtraction(BaseModel):
    website: str | None = None
    country: str | None = None
    founded_year: int | None = None
    employee_count: str | None = None
    industry: str | None = None
    is_consulting: bool | None = None
    review_score: float | None = None
    review_count: int | None = None
    description: str | None = None


class CompanyProfile(CompanyExtraction):
    name: str
    financial_health: FinancialHealth | None = None
```

- [ ] **Step 4: Run all model tests**

```bash
python -m pytest tests/enricher/test_models.py -v
```
Expected: 6 PASSED

- [ ] **Step 5: Commit**

```bash
git add enricher/models.py tests/enricher/test_models.py
git commit -m "feat: add FinancialHealth model and financial_health field to CompanyProfile"
```

---

### Task 6: Add financial health search query

**Files:**
- Modify: `tests/enricher/test_searcher.py`
- Modify: `enricher/searcher.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/enricher/test_searcher.py`:

```python
def test_search_returns_financial_url_and_snippets():
    website_hits = [{"href": "https://acme.com", "title": "Acme", "body": ""}]
    financial_hits = [
        {"href": "https://stockanalysis.com/stocks/acme", "title": "Acme Financials", "body": "Revenue grew 12% YoY. Strong cash position."},
    ]

    def mock_search(query, max_results):
        if "financial health" in query:
            return financial_hits
        if "glassdoor" in query:
            return []
        return website_hits

    with patch("enricher.searcher._search", side_effect=mock_search):
        urls, glassdoor_snippets, financial_snippets = search_company_urls("Acme", "Berlin")

    assert urls["website"] == "https://acme.com"
    assert urls["financial"] == "https://stockanalysis.com/stocks/acme"
    assert any("12%" in s for s in financial_snippets)
    assert glassdoor_snippets == []


def test_search_omits_financial_key_when_no_results():
    def mock_search(query, max_results):
        return []

    with patch("enricher.searcher._search", side_effect=mock_search):
        urls, _, financial_snippets = search_company_urls("Acme", "Berlin")

    assert "financial" not in urls
    assert financial_snippets == []
```

- [ ] **Step 2: Run to verify fail**

```bash
python -m pytest tests/enricher/test_searcher.py::test_search_returns_financial_url_and_snippets -v
```
Expected: FAIL — `not enough values to unpack` (still returns 2-tuple)

- [ ] **Step 3: Update search_company_urls in enricher/searcher.py**

Change the `queries` dict (adding the financial query):

```python
queries = {
    "website":   (f'"{name}"{suffix} company', 5),
    "reviews":   (f'"{name}"{suffix} glassdoor stars', 5),
    "financial": (f'"{name}"{suffix} company financial health', 3),
}
```

Change `ThreadPoolExecutor(max_workers=2)` to `ThreadPoolExecutor(max_workers=3)`.

After the `snippets` line, add the financial block:

```python
financial_hits = results.get("financial", [])
financial_snippets = [h.get("body", "") for h in financial_hits if h.get("body")]
if financial_hits:
    urls["financial"] = financial_hits[0]["href"]
```

Add a debug print for financial (alongside the existing prints):

```python
print(f"{engine} financial:  {', '.join(h['href'] for h in financial_hits) or '(none)'} → selected: {urls.get('financial', '(none)')}")
```

Update the return statement:

```python
return urls, snippets, financial_snippets
```

Note: `_BLOCKED_DOMAINS` is intentionally **not applied** to `financial_hits` — financial pages on bloomberg, stockanalysis, macrotrends, etc. are desirable sources.

- [ ] **Step 4: Run searcher tests**

```bash
python -m pytest tests/enricher/test_searcher.py -v
```
Expected: 6 PASSED

- [ ] **Step 5: Commit**

```bash
git add enricher/searcher.py tests/enricher/test_searcher.py
git commit -m "feat: add third parallel financial health search query"
```

---

### Task 7: Add assess_financial_health to extractor

**Files:**
- Modify: `tests/enricher/test_extractor.py`
- Modify: `enricher/extractor.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/enricher/test_extractor.py`:

```python
from enricher.extractor import assess_financial_health
from enricher.models import FinancialHealth


def test_assess_financial_health_returns_score_and_rationale():
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value.choices[0].message.content = json.dumps({
        "score": 4,
        "rationale": "Revenue grew 12% YoY with a strong cash position and no debt concerns.",
    })

    result = assess_financial_health(
        html="<html><body>Revenue grew 12% YoY.</body></html>",
        snippets=["Strong cash position, no debt."],
        name="Acme",
        client=mock_client,
    )

    assert isinstance(result, FinancialHealth)
    assert result.score == 4
    assert "Revenue" in result.rationale


def test_assess_financial_health_returns_none_when_no_input():
    mock_client = MagicMock()

    result = assess_financial_health(html=None, snippets=[], name="Acme", client=mock_client)

    assert result is None
    mock_client.chat.completions.create.assert_not_called()


def test_assess_financial_health_returns_none_on_llm_failure():
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = Exception("API error")

    result = assess_financial_health(
        html="<html><body>Some financial data.</body></html>",
        snippets=[],
        name="Acme",
        client=mock_client,
    )

    assert result is None


def test_assess_financial_health_uses_snippets_when_no_html():
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value.choices[0].message.content = json.dumps({
        "score": 2,
        "rationale": "Snippets indicate significant debt and declining revenue.",
    })

    result = assess_financial_health(
        html=None,
        snippets=["Significant debt load. Revenue down 20%."],
        name="Acme",
        client=mock_client,
    )

    assert isinstance(result, FinancialHealth)
    assert result.score == 2
```

- [ ] **Step 2: Run to verify fail**

```bash
python -m pytest tests/enricher/test_extractor.py::test_assess_financial_health_returns_score_and_rationale -v
```
Expected: FAIL — `cannot import name 'assess_financial_health'`

- [ ] **Step 3: Add constants and function to enricher/extractor.py**

Add these constants after `_SNIPPETS_SECTION`:

```python
_FINANCIAL_PROMPT = (
    "You are a financial analyst. Assess the financial health of the company below "
    "based on the provided sources.\n\n"
    "Return ONLY valid JSON with exactly these fields:\n"
    '{{"score": int, "rationale": str}}\n\n'
    "Score the company 1–5 using these anchors:\n"
    "1 = critical risk (bankruptcy, insolvency, severe losses)\n"
    "2 = financially stressed (significant debt, declining revenue)\n"
    "3 = neutral (stable but no strong signals either way)\n"
    "4 = financially healthy (profitable, growing, solid balance sheet)\n"
    "5 = very healthy (strong profitability, cash-rich, market leader)\n\n"
    "IMPORTANT: Write the rationale in English, 1–3 sentences, citing specific signals "
    "from the sources (e.g. revenue trend, debt level, profitability). "
    "If signals are too weak to assess confidently, use score 3 and explain the lack of data.\n\n"
    "Company name: {name}\n\n"
    "{snippets_section}"
    "Financial page text:\n{text}"
)

_FINANCIAL_SNIPPETS_SECTION = "Search result snippets:\n{snippets}\n\n"
```

Add the function at the end of `enricher/extractor.py`:

```python
def assess_financial_health(
    html: str | None,
    snippets: list[str],
    name: str,
    client: Groq,
) -> "FinancialHealth | None":
    from enricher.models import FinancialHealth

    if not html and not snippets:
        return None

    text = _html_to_text(html)[:6000] if html else ""
    snippets_section = (
        _FINANCIAL_SNIPPETS_SECTION.format(snippets="\n".join(f"- {s}" for s in snippets))
        if snippets
        else ""
    )
    prompt = _FINANCIAL_PROMPT.format(name=name, snippets_section=snippets_section, text=text)

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        content = _strip_markdown_json(response.choices[0].message.content)
        return FinancialHealth.model_validate_json(content)
    except Exception as e:
        logger.warning("Financial health assessment failed: %s", e)
        return None
```

(`FinancialHealth` is imported inside the function to avoid a circular import since `models.py` has no dependencies on `extractor.py`.)

- [ ] **Step 4: Run all extractor tests**

```bash
python -m pytest tests/enricher/test_extractor.py -v
```
Expected: 11 PASSED

- [ ] **Step 5: Commit**

```bash
git add enricher/extractor.py tests/enricher/test_extractor.py
git commit -m "feat: add assess_financial_health to extractor"
```

---

### Task 8: Wire financial health into enricher

**Files:**
- Modify: `tests/enricher/test_enricher.py`
- Modify: `enricher/enricher.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/enricher/test_enricher.py`:

```python
from enricher.models import FinancialHealth


def test_enrich_attaches_financial_health():
    financial_health = FinancialHealth(score=4, rationale="Strong revenue growth.")

    with patch("enricher.enricher.search_company_urls", return_value=(
        {"website": "https://acme.com", "financial": "https://stockanalysis.com/acme"},
        [],
        ["Revenue grew 12% YoY."],
    )):
        with patch("enricher.enricher.fetch_html", return_value="<html></html>"):
            with patch("enricher.enricher.extract_jsonld", return_value={}):
                with patch("enricher.enricher.find_relevant_links", return_value=[]):
                    with patch("enricher.enricher.extract_with_llm", return_value=CompanyExtraction()):
                        with patch("enricher.enricher.assess_financial_health", return_value=financial_health):
                            result, _ = enrich("Acme", "Berlin", _make_client())

    assert result.financial_health is not None
    assert result.financial_health.score == 4
    assert result.financial_health.rationale == "Strong revenue growth."


def test_enrich_financial_health_is_none_when_no_financial_data():
    with patch("enricher.enricher.search_company_urls", return_value=(
        {"website": "https://acme.com"},
        [],
        [],
    )):
        with patch("enricher.enricher.fetch_html", return_value="<html></html>"):
            with patch("enricher.enricher.extract_jsonld", return_value={}):
                with patch("enricher.enricher.find_relevant_links", return_value=[]):
                    with patch("enricher.enricher.extract_with_llm", return_value=CompanyExtraction()):
                        with patch("enricher.enricher.assess_financial_health", return_value=None) as mock_assess:
                            result, _ = enrich("Acme", "Berlin", _make_client())

    assert result.financial_health is None
    mock_assess.assert_called_once()
```

Also update the 4 existing tests: change every `return_value=({"website": "https://acme.com"}, [])` to `return_value=({"website": "https://acme.com"}, [], [])`.

- [ ] **Step 2: Run to verify fail**

```bash
python -m pytest tests/enricher/test_enricher.py::test_enrich_attaches_financial_health -v
```
Expected: FAIL — `not enough values to unpack` (enricher still unpacks 2-tuple from `search_company_urls`)

- [ ] **Step 3: Update enricher/enricher.py**

Update the import:

```python
from enricher.extractor import assess_financial_health, extract_jsonld, extract_with_llm
```

Replace the entire `enrich` function body with:

```python
def enrich(name: str, location: str, client: Groq) -> tuple[CompanyProfile, list[tuple[str, float]]]:
    timings: list[tuple[str, float]] = []

    def tick(label: str, t0: float) -> float:
        timings.append((label, time.perf_counter() - t0))
        return time.perf_counter()

    t = time.perf_counter()
    urls, snippets, financial_snippets = search_company_urls(name, location)
    t = tick("search", t)

    merged: dict = {}
    website_html: str | None = None
    financial_html: str | None = None

    with ThreadPoolExecutor(max_workers=2) as ex:
        fut_website   = ex.submit(fetch_html, urls["website"])   if "website"   in urls else None
        fut_financial = ex.submit(fetch_html, urls["financial"]) if "financial" in urls else None
        website_html   = fut_website.result()   if fut_website   else None
        financial_html = fut_financial.result() if fut_financial else None
    t = tick("fetch website+financial", t)

    if website_html:
        for k, v in extract_jsonld(website_html).items():
            if k not in merged and v is not None:
                merged[k] = v
        t = tick("jsonld website", t)

    if _missing(merged) and website_html:
        extra_urls = find_relevant_links(website_html, urls.get("website", ""))
        t = tick("find links", t)

        if extra_urls:
            with ThreadPoolExecutor(max_workers=3) as ex:
                extra_htmls = [h for h in ex.map(fetch_html, extra_urls) if h]
            t = tick("fetch extra pages", t)
        else:
            extra_htmls = []

        extraction = extract_with_llm(
            website_html, name, location, client,
            snippets or None, extra_htmls or None, urls.get("website"),
        )
        for k, v in extraction.model_dump(exclude_none=True).items():
            if k not in merged:
                merged[k] = v
        t = tick("llm", t)

    profile = CompanyProfile.model_validate({"name": name, **merged})
    profile.financial_health = assess_financial_health(financial_html, financial_snippets, name, client)
    tick("financial health", t)

    return profile, timings
```

- [ ] **Step 4: Run all enricher tests**

```bash
python -m pytest tests/enricher/test_enricher.py -v
```
Expected: 6 PASSED

- [ ] **Step 5: Run the full test suite**

```bash
python -m pytest tests/enricher/ -v
```
Expected: all PASSED

- [ ] **Step 6: Commit**

```bash
git add enricher/enricher.py tests/enricher/test_enricher.py
git commit -m "feat: parallel fetch + financial health assessment in enricher"
```

---

## Self-Review

**Spec coverage:**
- ✅ `FinancialHealth(score, rationale)` model → Task 5
- ✅ Nested `financial_health: FinancialHealth | None` on `CompanyProfile` → Task 5
- ✅ Third parallel query `"{name}" company financial health` → Task 6
- ✅ `_BLOCKED_DOMAINS` not applied to financial results → Task 6 (raw `financial_hits[0]["href"]`)
- ✅ Return signature extended to 3-tuple → Task 6
- ✅ `assess_financial_health` in extractor → Task 7
- ✅ Score anchors 1–5 in prompt → Task 7
- ✅ English rationale, 1–3 sentences, cite specific signals → Task 7
- ✅ Default to score 3 if weak signals → Task 7 (in prompt instructions)
- ✅ Returns `None` if no html and no snippets → Task 7
- ✅ Parallel fetch website + financial → Task 8
- ✅ `financial_health` not in `_ALL_FIELDS` → Task 8 (not touched)
- ✅ Timing entries added → Task 8

**Placeholder scan:** No TBDs. All steps have complete code.

**Type consistency:**
- `FinancialHealth` defined in Task 5, imported in Tasks 7 and 8 ✅
- `assess_financial_health` defined in Task 7, imported in Task 8 ✅
- `search_company_urls` returns 3-tuple from Task 6 onward; Task 8 unpacks correctly ✅
- `_strip_markdown_json` defined in Task 2, reused in Task 7 ✅
