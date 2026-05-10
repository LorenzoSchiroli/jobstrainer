# Ingestion Service Design

**Date:** 2026-05-10
**Status:** Approved

## Overview

Restructure the existing ingestion code into a proper uv workspace member with its own dependencies, Dockerfile, and a scheduled Docker container that runs offer scraping every 2 hours. Only the offer pipeline is in scope; company enrichment and tailor are out of scope for this restructure.

## Repo Structure

```
jobstrainer/
├── pyproject.toml        ← workspace-only (no [project] section, no deps)
├── uv.lock
├── backend/              ← unchanged
│   └── pyproject.toml
├── ingestion/            ← new workspace member
│   ├── pyproject.toml   ← owns all ingestion deps
│   ├── Dockerfile
│   ├── ingestion/       ← existing code moved here
│   │   ├── __init__.py
│   │   ├── offer/
│   │   └── company/
│   └── tests/           ← moved from root tests/
│       ├── offer/
│       └── company/
└── tailor/              ← untouched, temporarily out of scope
```

The root `pyproject.toml` becomes a pure workspace declaration:

```toml
[tool.uv.workspace]
members = ["backend", "ingestion"]
```

`tailor/` has no `pyproject.toml` and will be broken until tackled as a separate service.

## ingestion/pyproject.toml

Owns all deps currently in the root:

```toml
[project]
name = "ingestion"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
    "beautifulsoup4>=4.14.3",
    "ddgs>=9.14.1",
    "groq>=1.2.0",
    "playwright>=1.58.0",
    "pydantic>=2.13.2",
    "pyperclip>=1.11.0",
    "python-docx>=1.2.0",
    "python-dotenv>=1.2.2",
    "python-jobspy>=1.1.82",
    "requests>=2.33.1",
    "tabulate>=0.10.0",
    "tqdm>=4.67.3",
]

[dependency-groups]
dev = [
    "pytest>=9.0.3",
]
```

## Scheduling

The ingestion container runs a shell loop — no extra scheduler dependency:

```
while true; do
  uv run python -m ingestion.offer "$OFFER_QUERY" --hours 2
  sleep 7200
done
```

- `OFFER_QUERY` is set via env var in docker-compose (e.g. `"machine learning engineer"`)
- `--hours 2` fetches only offers from the last 2 hours, matching the scrape interval
- Output goes to stdout and `data/offers.json` via a mounted volume

## Dockerfile

```dockerfile
FROM python:3.13-slim

WORKDIR /app

RUN pip install uv --quiet

COPY pyproject.toml uv.lock ./
COPY ingestion/pyproject.toml ./ingestion/pyproject.toml

RUN uv sync --package ingestion --no-dev

# Install Playwright + Chromium (required for browser-based scraping sources)
RUN uv run --package ingestion playwright install --with-deps chromium

COPY ingestion/ ./ingestion/

WORKDIR /app/ingestion

CMD ["sh", "-c", "while true; do uv run python -m ingestion.offer \"$OFFER_QUERY\" --hours 2; sleep 7200; done"]
```

Note: Playwright + Chromium makes this image large (~1GB). This is expected for a scraping service.

## docker-compose.yml addition

```yaml
ingestion:
  build:
    context: .
    dockerfile: ingestion/Dockerfile
  environment:
    OFFER_QUERY: "machine learning engineer"
    GROQ_API_KEY: ${GROQ_API_KEY}
  volumes:
    - ./data:/app/ingestion/data
```

No `depends_on` — the ingestion service is independent of the backend for now. Wiring ingestion to POST results to the backend API is a separate follow-up.

## Import Path Changes

Current entry point: `python -m ingestion.offer` (already correct given the package is at `ingestion/`).

All internal imports (`from ingestion.offer import ...`, `from ingestion.company import ...`) remain unchanged since the Python package name stays `ingestion`.

Tests move from `tests/offer/` and `tests/company/` to `ingestion/tests/offer/` and `ingestion/tests/company/` with no changes to test code.

## Out of Scope

- Company enrichment scheduling
- `tailor/` restructure
- Ingestion → backend API integration (separate feature)
