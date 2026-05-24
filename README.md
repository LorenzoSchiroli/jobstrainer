# jobstrainer

## Commands

### Offer

Fetch recent job offers matching a search query.

```bash
uv run python -m offer "machine learning engineer"
uv run python -m offer "machine learning engineer" --hours 48
uv run python -m offer "machine learning engineer" --sources jobspy,adzuna
```

Available sources: `jobspy`, `adzuna`, `arbeitnow`, `remotive` (default: all).

### Company

Enrich a company profile with metadata (size, funding, financial health, etc.).

```bash
uv run python -m company "Stripe"
uv run python -m company "Stripe" "San Francisco"
uv run python -m company "Stripe" --debug
```

Requires `GROQ_API_KEY` in `.env`.

### Tailor

Generate tailored CV versions (LLM-focused and Computer Vision-focused) from the base CV.

```bash
uv run python tailor_cv.py
```

Outputs to `tailor/lorenzo_schiroli_cv_llm.docx` and `tailor/lorenzo_schiroli_cv_cv.docx`.

## Design

search
input: cv + query (what i'm looking for)
output: rank of offers

Architecture:
- scraper + parsing (jobs and companies, actively interrogate the backend);
    - clean text before saving
- backend (holding the database and data, holding the ranker operation, fully passive); tools: postgresql + opensearch (bm25 on full text + embedding on summary + crossencoder, no chunking because llm summary seems to be better)
- frontend (just ui, react)

Next:
- fix scraper? add llanggraph (or temporal) as a crawler orchestrator?
- llanggraph:
    - advanced query search with miltistep refinement (very fiew steps) + fit evaluation for final result (using also memory of user preferences or past session)
    - tailor for cv, cl, custom message, "autofill" job offer page
    - advanced crawling / discovery / orchestration around scraping (find links, retries, fallbacks): only on edge cases / unknown websites, like hidden job discovery or company discover
- trining (do at the end): use llm to generate 1-5k examples for the training + 500 test (hard negatives are important)
- company discover



