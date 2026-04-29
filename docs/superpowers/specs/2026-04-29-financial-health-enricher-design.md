# Financial Health Enricher — Design Spec

**Date:** 2026-04-29  
**Status:** Approved

## Overview

Add financial health assessment to the company enricher. A third parallel search query fetches financial health signals for a company; the results are fetched and assessed by the LLM, producing a score (1–5) and a rationale attached to `CompanyProfile`.

## Goals

- Quickly flag companies that are financially distressed before a job application.
- Score 1–5 with a 1–3 sentence rationale citing concrete signals.
- Add zero sequential latency: search + fetch run in parallel with existing pipeline.

## Non-Goals

- Deep financial analysis (revenue figures, P&L parsing).
- Fetching multiple financial pages.
- Caching or persisting financial data separately.

---

## 1. Models (`models.py`)

Add a new `FinancialHealth` model:

```python
class FinancialHealth(BaseModel):
    score: int      # 1–5
    rationale: str  # 1–3 sentences in English
```

Score anchors:

| Score | Meaning |
|-------|---------|
| 1 | Critical risk — bankruptcy, insolvency, severe losses |
| 2 | Financially stressed — significant debt, declining revenue |
| 3 | Neutral — stable but no strong signals either way |
| 4 | Financially healthy — profitable, growing, solid balance sheet |
| 5 | Very healthy — strong profitability, cash-rich, market leader |

Add to `CompanyProfile`:

```python
class CompanyProfile(CompanyExtraction):
    name: str
    financial_health: FinancialHealth | None = None
```

`FinancialHealth` is intentionally separate from `CompanyExtraction`: it is an LLM assessment, not scraped metadata, and is never subject to the "fill missing fields" logic in the enricher.

---

## 2. Search (`searcher.py`)

Add a third parallel query to `search_company_urls`:

```python
"financial": (f'"{name}"{suffix} company financial health', 3),
```

Runs in the same `ThreadPoolExecutor(max_workers=3)` as the existing website and reviews queries.

**Domain filtering:** `_BLOCKED_DOMAINS` is **not applied** to financial results. Financial health pages on bloomberg, crunchbase, stockanalysis, macrotrends, etc. are exactly the sources we want. Take the first result URL as-is.

**Return signature change:**

```python
# Before
tuple[dict[str, str], list[str]]

# After
tuple[dict[str, str], list[str], list[str]]
# (urls, glassdoor_snippets, financial_snippets)
```

The `urls` dict gains a `"financial"` key with the top result URL. Financial snippets are the `body` fields from the search results (same pattern as Glassdoor snippets).

---

## 3. Enricher orchestration (`enricher.py`)

After `search_company_urls`, fetch website and financial URLs **in parallel**:

```python
with ThreadPoolExecutor(max_workers=2) as ex:
    fut_website   = ex.submit(fetch_html, urls["website"])   if "website"   in urls else None
    fut_financial = ex.submit(fetch_html, urls["financial"]) if "financial" in urls else None
    website_html   = fut_website.result()   if fut_website   else None
    financial_html = fut_financial.result() if fut_financial else None
```

The main extraction pipeline (JSON-LD, link discovery, LLM extraction) continues unchanged on `website_html`.

Financial assessment is called after the main pipeline and its result attached to the profile:

```python
profile.financial_health = assess_financial_health(
    financial_html, financial_snippets, name, client
)
```

`financial_health` is **not** added to `_ALL_FIELDS` — it is never part of the "missing fields" check.

Timing entries added: `"fetch financial"` and `"financial health assessment"`.

---

## 4. Extractor (`extractor.py`)

New function:

```python
def assess_financial_health(
    html: str | None,
    snippets: list[str],
    name: str,
    client: Groq,
) -> FinancialHealth | None:
```

Returns `None` if both `html` and `snippets` are empty/None.

**LLM prompt** instructs the model to:
- Act as a financial analyst.
- Use the score anchors above.
- Write the rationale in English, 1–3 sentences, citing specific signals from the source.
- Default to score 3 with an explanatory rationale if signals are too weak to assess confidently.
- Return only valid JSON: `{"score": int, "rationale": str}`.

Response is validated into `FinancialHealth` via `model_validate_json`. On LLM failure, returns `None`.

---

## Data Flow

```
search_company_urls(name, location)
  ├── query: "{name}" company          → urls["website"]
  ├── query: "{name}" glassdoor stars  → glassdoor_snippets
  └── query: "{name}" financial health → urls["financial"] + financial_snippets

ThreadPoolExecutor
  ├── fetch_html(urls["website"])   → website_html
  └── fetch_html(urls["financial"]) → financial_html

website_html → extract_jsonld → merged
website_html → find_relevant_links → extra_htmls
website_html + extra_htmls + glassdoor_snippets → extract_with_llm → CompanyExtraction

financial_html + financial_snippets → assess_financial_health → FinancialHealth

CompanyProfile(name=name, **merged, financial_health=financial_health)
```

---

## Files Changed

| File | Change |
|------|--------|
| `enricher/models.py` | Add `FinancialHealth`; add `financial_health` field to `CompanyProfile` |
| `enricher/searcher.py` | Add `"financial"` query; update return signature to include financial snippets |
| `enricher/enricher.py` | Parallel fetch; wire financial assessment; update timings |
| `enricher/extractor.py` | Add `assess_financial_health` function + prompt |
