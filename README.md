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
- scraper + parsing (jobs and companies, actively interrogate the backend); tools: langchain?
- backend (holding the database and data, holding the ranker operation, fully passive); tools: postgresql + pgvector + pg_bm25 + llamaindex + langchain (+ crossencoder)
- frontend (just ui, react)

ranker
approaches: bm25 + embedding -> cross-encoder reranker

Other things:
- tailorer
- company discover
