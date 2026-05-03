# jobstrainer

## Commands

### Retriever

Fetch recent job offers matching a search query.

```bash
uv run python -m retriever "machine learning engineer"
uv run python -m retriever "machine learning engineer" --hours 48
uv run python -m retriever "machine learning engineer" --sources jobspy,adzuna
```

Available sources: `jobspy`, `adzuna`, `arbeitnow`, `remotive` (default: all).

### Enricher

Enrich a company profile with metadata (size, funding, tech stack, etc.).

```bash
uv run python -m enricher "Stripe"
uv run python -m enricher "Stripe" "San Francisco"
uv run python -m enricher "Stripe" --debug
```

Requires `GROQ_API_KEY` in `.env`.

### Tailor

Generate tailored CV versions (LLM-focused and Computer Vision-focused) from the base CV.

```bash
uv run python tailor_cv.py
```

Outputs to `tailor/lorenzo_schiroli_cv_llm.docx` and `tailor/lorenzo_schiroli_cv_cv.docx`.
