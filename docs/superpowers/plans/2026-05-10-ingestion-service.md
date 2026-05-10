# Ingestion Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the existing ingestion code into a proper uv workspace member and add a scheduled Docker container that scrapes job offers every 2 hours.

**Architecture:** Root `pyproject.toml` becomes a pure workspace declaration. The Python package at `ingestion/` moves to `ingestion/ingestion/` (workspace member pattern, same as `backend/`). Tests move from root `tests/` to `ingestion/tests/`. A Dockerfile and docker-compose entry run the offer scraper on a 2-hour loop.

**Tech Stack:** Python 3.13, uv workspaces, Playwright, Docker Compose

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `pyproject.toml` | Modify | Strip to workspace-only, add `ingestion` to members |
| `ingestion/pyproject.toml` | Create | Ingestion package deps |
| `ingestion/ingestion/` | Move (git mv) | Python package, moved from root `ingestion/` |
| `ingestion/tests/` | Move (git mv) | Tests, moved from root `tests/` |
| `ingestion/Dockerfile` | Create | Scheduled scraper container |
| `docker-compose.yml` | Modify | Add ingestion service |

---

## Task 1: Workspace restructure

This task moves all the pieces in one atomic step to avoid a broken intermediate state.

**Files:**
- Modify: `pyproject.toml`
- Create: `ingestion/pyproject.toml`
- Move: `ingestion/` → `ingestion/ingestion/` (git mv)
- Move: `tests/` → `ingestion/tests/` (git mv)

- [ ] **Step 1: Establish baseline — run existing tests**

```bash
cd /Users/loryschi/projects/jobstrainer
uv run pytest tests/ -v --ignore=tests/company 2>&1 | tail -20
```

Note how many pass. Some tests may require external API keys (GROQ_API_KEY, ADZUNA_APP_ID etc.) and will be skipped or fail — that is expected and acceptable. We just need to know the baseline so we can confirm nothing regresses after the move.

- [ ] **Step 2: Move the Python package using git mv**

```bash
cd /Users/loryschi/projects/jobstrainer

# Temporarily rename the package dir
git mv ingestion ingestion_pkg

# Create the workspace member directory (untracked, just a container)
mkdir ingestion

# Move the package one level deeper — ingestion/ingestion doesn't exist yet so git creates it
git mv ingestion_pkg ingestion/ingestion

# Move tests into the workspace member
git mv tests ingestion/tests
```

Verify the structure:
```bash
ls ingestion/
# Expected: ingestion/  tests/
ls ingestion/ingestion/
# Expected: __init__.py  company/  offer/
ls ingestion/tests/
# Expected: __init__.py  company/  offer/
```

- [ ] **Step 3: Strip root pyproject.toml to workspace-only**

Replace the entire content of `/Users/loryschi/projects/jobstrainer/pyproject.toml` with:

```toml
[tool.uv.workspace]
members = ["backend", "ingestion"]
```

- [ ] **Step 4: Create ingestion/pyproject.toml**

Create `/Users/loryschi/projects/jobstrainer/ingestion/pyproject.toml`:

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

Note: `python-docx` is intentionally excluded — it belongs to `tailor/` which is out of scope.

- [ ] **Step 5: Sync the workspace**

```bash
cd /Users/loryschi/projects/jobstrainer
uv sync
```

Expected: resolves all workspace members (backend + ingestion), updates `uv.lock`. No errors.

- [ ] **Step 6: Run tests from new location to confirm nothing regressed**

```bash
cd /Users/loryschi/projects/jobstrainer/ingestion
uv run pytest tests/ -v 2>&1 | tail -30
```

Expected: same pass/fail pattern as the baseline from Step 1. No new failures. If a test fails that previously passed, investigate and fix before committing.

- [ ] **Step 7: Commit everything**

```bash
cd /Users/loryschi/projects/jobstrainer
git add pyproject.toml uv.lock ingestion/pyproject.toml
git commit -m "chore(ingestion): restructure as uv workspace member"
```

---

## Task 2: Ingestion Dockerfile

**Files:**
- Create: `ingestion/Dockerfile`

- [ ] **Step 1: Create ingestion/Dockerfile**

Create `/Users/loryschi/projects/jobstrainer/ingestion/Dockerfile`:

```dockerfile
FROM python:3.13-slim

WORKDIR /app

RUN pip install uv --quiet

COPY pyproject.toml uv.lock ./
COPY ingestion/pyproject.toml ./ingestion/pyproject.toml

RUN uv sync --package ingestion --no-dev

RUN uv run playwright install --with-deps chromium

COPY ingestion/ ./ingestion/

WORKDIR /app/ingestion

CMD ["sh", "-c", "while true; do uv run python -m ingestion.offer \"$OFFER_QUERY\" --hours 2 --json; sleep 7200; done"]
```

Key points:
- `uv sync --package ingestion --no-dev` installs only ingestion deps — no backend deps, no tailor deps
- `playwright install --with-deps chromium` installs Chromium + OS-level dependencies. This makes the image ~1GB — expected for a scraping service
- `--hours 2` fetches only offers from the last 2 hours, matching the loop interval
- `--json` saves results to `data/offers.json` relative to WORKDIR (`/app/ingestion/data/offers.json`), which maps to the host `./data/` volume

- [ ] **Step 2: Verify the Dockerfile builds (optional but recommended)**

```bash
cd /Users/loryschi/projects/jobstrainer
docker build -f ingestion/Dockerfile -t ingestion-test .
```

Expected: build completes. Playwright install takes 2-3 minutes on first run.

If the build fails on `playwright install --with-deps`, the slim image may be missing a package. Switch to `python:3.13` (non-slim) base image:

```dockerfile
FROM python:3.13
```

- [ ] **Step 3: Commit**

```bash
cd /Users/loryschi/projects/jobstrainer
git add ingestion/Dockerfile
git commit -m "feat(ingestion): add Dockerfile with scheduled offer scraper"
```

---

## Task 3: docker-compose.yml — add ingestion service

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add ingestion service to docker-compose.yml**

Open `/Users/loryschi/projects/jobstrainer/docker-compose.yml` and add the `ingestion` service. The final file must look exactly like this:

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: jobstrainer
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 5s
      retries: 5

  backend:
    build:
      context: .
      dockerfile: backend/Dockerfile
    environment:
      DATABASE_URL: postgresql+asyncpg://postgres:postgres@postgres:5432/jobstrainer
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy

  ingestion:
    build:
      context: .
      dockerfile: ingestion/Dockerfile
    environment:
      OFFER_QUERY: "machine learning engineer"
      GROQ_API_KEY: ${GROQ_API_KEY}
    volumes:
      - ./data:/app/ingestion/data

volumes:
  postgres_data:
```

Note:
- `GROQ_API_KEY: ${GROQ_API_KEY}` reads from the host environment or a `.env` file at the repo root. Make sure `GROQ_API_KEY` is set in `.env`.
- The ingestion service has no `depends_on` — it is independent of the backend for now (output goes to `data/offers.json`, not the backend API).
- The `./data` volume mount persists scraped offers across container restarts.

- [ ] **Step 2: Verify .env has GROQ_API_KEY**

```bash
grep GROQ_API_KEY /Users/loryschi/projects/jobstrainer/.env
```

Expected: a non-empty value. If missing, add `GROQ_API_KEY=your_key_here` to `.env`.

- [ ] **Step 3: Validate docker-compose config parses correctly**

```bash
cd /Users/loryschi/projects/jobstrainer
docker-compose config --quiet
```

Expected: no errors. If there are YAML errors, fix them before committing.

- [ ] **Step 4: Commit**

```bash
cd /Users/loryschi/projects/jobstrainer
git add docker-compose.yml
git commit -m "feat(ingestion): add ingestion service to docker-compose with 2-hour scrape schedule"
```

---

## Notes

**tailor/ is temporarily broken.** The root `pyproject.toml` no longer declares `python-docx` or any other tailor deps. Running tailor scripts will fail. This is expected and out of scope — tailor will be restructured as its own workspace member in a future task.

**Adzuna and other source API keys.** If the ingestion uses `AdzunaSource`, additional env vars (`ADZUNA_APP_ID`, `ADZUNA_APP_KEY`) may be required. Add them to `.env` and to the ingestion service's `environment:` block in `docker-compose.yml` as needed.
