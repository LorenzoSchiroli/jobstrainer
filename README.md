# jobstrainer

A job search ranking system. It scrapes job offers from multiple sources, enriches
them with LLM-parsed metadata and dense embeddings, stores them in Postgres +
OpenSearch, and serves a hybrid BM25 + k-NN search endpoint with cross-encoder
reranking.

On top of search it adds two LangGraph agents: an **advanced search** mode that asks
clarifying questions and fit-scores results against your CV, and a **tailorer** that
drafts a tailored CV / cover letter and fills application forms from a Chrome side
panel.

```mermaid
flowchart LR
    subgraph sources["Job sources"]
        S["jobspy · adzuna<br/>arbeitnow · remotive"]
    end

    subgraph ing["ingestion"]
        I["scrape → LLM parse<br/>→ embed (384-dim)"]
    end

    subgraph clients["Clients"]
        FE["frontend<br/>React SPA"]
        EXT["extension<br/>Chrome side panel"]
    end

    subgraph be["backend (FastAPI)"]
        API["REST API<br/>JWT auth"]
        SEARCH["hybrid search<br/>BM25 + k-NN → rerank"]
        WORKER["outbox worker<br/>reconcile · retention · backup"]
    end

    PG[("Postgres<br/>source of truth")]
    OS[("OpenSearch<br/>derived index")]

    S --> I
    I -->|"POST /jobs, /companies"| API
    FE --> API
    EXT --> API
    API --> PG
    PG -->|"outbox rows"| WORKER
    WORKER -->|"bulk re-index<br/>every 5 min"| OS
    API --> SEARCH
    SEARCH -->|"retrieve"| OS
    SEARCH -->|"hydrate by ID"| PG
```

## Repository layout

| Path | What it is |
|------|------------|
| `backend/` | FastAPI service — REST API, Postgres (SQLAlchemy async), OpenSearch hybrid search, outbox reconcile worker, LangGraph agents |
| `ingestion/` | Pipeline — job scraping, LLM offer parsing, company enrichment, embedding, POST to the backend |
| `frontend/` | React (Vite) SPA, served by nginx in Docker/k8s |
| `extension/` | Chrome extension (Tailorer side panel; talks to the backend directly) |
| `deploy/` | Helm chart, k8s runbook, OpenTofu stacks for Hetzner and AWS, demo scripts |

`backend/` and `ingestion/` are the two members of a `uv` workspace (Python 3.13).

## Quick start

### 1. Configuration

Secrets live in a gitignored `.env`; non-secrets are committed in `.env.public`.

```bash
cp .env.example .env      # then fill in the keys below
```

| Variable | Where | Purpose |
|----------|-------|---------|
| `GROQ_API_KEY` | `.env` | LLM parsing, agents |
| `SECRET_KEY` | `.env` | JWT signing |
| `SERPERDEV_API_KEY` | `.env` | Company enrichment web search |
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | `.env` | Optional job source |
| `DDGS_PROXY` | `.env` | Optional proxy for DuckDuckGo scraping |
| `BACKUP_SBOX_HOST` / `_USER` / `_RCLONE_PASS` | `.env` | Optional nightly Postgres backup |
| `GROQ_MODEL_LARGE` / `GROQ_MODEL_BASE` | `.env.public` | Model IDs for agents / parsing |
| `OFFER_QUERY` | `.env.public` | Query used by the ingestion container / CronJob |
| `CORS_ORIGINS` | `.env.public` | Extra browser origins for the API |
| `VITE_API_URL` | `.env.public` | API base URL baked into the frontend image |

> **Keep values unquoted.** `kubectl create secret --from-env-file` stores quotes
> verbatim (unlike dotenv), so a quoted `GROQ_API_KEY` yields a Groq
> `401 invalid_api_key` in Kubernetes.

### 2. Run the stack

```bash
docker compose up -d postgres opensearch   # dependencies only
docker compose up --build                  # full stack incl. frontend + ingestion
```

The frontend is on `:3000`, the API on `:8000` (`/docs` for OpenAPI).

### 3. Run the backend from source

```bash
cd backend
uv run alembic upgrade head                # apply DB migrations
uv run uvicorn backend.main:app --reload   # dev server on :8000
```

## Commands

### Backend

```bash
cd backend
uv run pytest                              # all tests
uv run pytest tests/test_jobs.py           # one file
uv run pytest tests/search/test_filters.py::test_build_clauses_empty_when_all_none
```

Tests need a live Postgres at
`postgresql+asyncpg://postgres:postgres@localhost:5432/jobstrainer_test`
(override with `TEST_DATABASE_URL`). OpenSearch and the ML models are mocked.

Three entrypoints, split so they can scale independently:

| Command | Role |
|---------|------|
| `backend.main:app` | API only — loads ML models, ensures the OpenSearch index/pipeline, opens the LangGraph checkpointer |
| `python -m backend.worker` | Outbox reconcile + retention + nightly backup loops (singleton) |
| `python -m backend.bootstrap` | One-time setup — checkpointer tables, `created_at` backfill |

### Ingestion

```bash
cd ingestion
uv run python -m ingestion.pipeline "machine learning engineer" --hours 48
uv run pytest
```

Ad-hoc CLIs for debugging a single stage:

```bash
uv run python -m ingestion.offer "machine learning engineer" --hours 48 --sources jobspy,adzuna
uv run python -m ingestion.company "Stripe" "San Francisco" --debug
```

Offer sources: `jobspy`, `adzuna`, `arbeitnow`, `remotive` (default: all).

## How search works

`POST /jobs/search` (JWT-protected, body `{query}`) runs four sequential steps and
uses **no LLM**:

1. **Query parsing** — deterministic regex extraction of `SearchFilters`
   (seniority, location type, languages, …) plus a `semantic_query`
   (`search/query_parsing.py`).
2. **Hybrid retrieval** — OpenSearch BM25 on `description` + k-NN on `embedding`
   (384-dim, `BAAI/bge-small-en-v1.5`), combined by min-max normalization with
   50/50 weights (`search/retrieval.py`). Filters are *soft* by default (scored
   `should`, boost 2) so near-misses still surface; words like "strictly" /
   "exactly" / "no exceptions" flip `SearchFilters.strict`, applying them as a hard
   `post_filter` with a larger prefetch.
3. **Cross-encoder reranking** — `cross-encoder/ms-marco-MiniLM-L-6-v2` reranks on
   `summary_text` and returns the top 20 (`search/reranker.py`).
4. **Postgres round-trip** — full `Job` + `Company` records fetched by ID.

**Advanced search (WIP)** — `POST /jobs/search/advanced` is a Postgres-checkpointed
LangGraph agent with per-user preference memory. It interrupts with up to two
clarifying questions (answered via `POST /jobs/search/advanced/resume`), can
critique and refine its own retrieval, and returns fit-scored results. Requires an
uploaded CV.

### Durability: the outbox pattern

Jobs and companies are written atomically to Postgres together with an `outbox`
row — Postgres is the source of truth, OpenSearch is a derived index. Every 5
minutes the reconcile worker bulk re-indexes jobs with unprocessed outbox rows plus
live jobs (≤30 days) missing from the index; `company_upserted` events patch
company-derived fields on that company's job docs via `update_by_query`. Every 6
hours retention deletes OpenSearch docs older than 30 days. With `BACKUP_SBOX_*`
set, a daily `pg_dump` + rclone upload goes to a Hetzner Storage Box (7-day rolling
retention).

## API surface

| Endpoint | Notes |
|----------|-------|
| `POST /auth/register`, `POST /auth/login`, `GET /auth/me` | JWT bearer tokens |
| `POST /jobs/`, `GET /jobs/{id}` | Ingestion writes here |
| `POST /companies/`, `GET /companies/{id}` | |
| `POST /jobs/search` | Basic hybrid search |
| `POST /jobs/search/advanced`, `.../resume` | Agent search (WIP) |
| `POST /cv`, `GET /cv` | CV upload for fit scoring / tailoring |
| `GET/PUT /preference-memory` | Per-user search preferences |
| `GET/PUT /tailorer/profile`, `WS /tailorer/ws/{job_id}`, `GET /tailorer/files/...` | Tailorer agent + generated documents |

Most endpoints depend on `get_current_user`.

## Data model

- **`Company`** — unique by `name`; enriched with employee count, founded year,
  review score, financial health score (0–10), consulting/startup flags, industry,
  country.
- **`Job`** — unique by `url`; parsed fields (employment type, location type,
  seniority, required languages) plus a `summary` JSONB.
- **`Outbox`** — transient sync table; `processed_at` is NULL until the worker
  drains it.
- **`User`**, **`ApplicantProfile`**, **`Application`** — accounts and per-user CV
  data.

Schema changes go through Alembic in `backend/alembic/`. Compose runs
`alembic upgrade head` at container start; in Kubernetes the bootstrap hook Job runs
it before rollout.

## Deployment

Kubernetes via Helm is the canonical path; docker-compose still works but is being
phased out.

```bash
helm install jobstrainer deploy/helm/jobstrainer \
  -f deploy/helm/jobstrainer/values-local.yaml
```

The chart deploys the whole stack — postgres, opensearch, api (+ HPA), worker,
ingestion CronJob, frontend, and a bootstrap hook Job (migrations, OpenSearch index,
checkpointer). It references a pre-created `jobstrainer-secrets` Secret rather than
creating one; build it from `.env.public` **then** `.env`.

| Target | Path | Notes |
|--------|------|-------|
| Local kind cluster | `values-local.yaml` | Full runbook in [`deploy/k8s/README.md`](deploy/k8s/README.md) |
| Hetzner (Helm + OpenTofu) | `values-hetzner.yaml`, [`deploy/infra/hetzner/`](deploy/infra/hetzner/) | CX33 x86 nodes — images **must** be `linux/amd64` |
| AWS showcase (ECS, not Helm) | [`deploy/infra/aws/`](deploy/infra/aws/) | Fargate + RDS + OpenSearch Service + ALB, via OpenTofu |

Images are published to GHCR by the **Build and push images** GitHub Actions
workflow; set `VITE_API_URL` in `.env.public` before building the frontend image,
since Vite bakes it in. `deploy/k8s/loadtest-job.yaml` is an in-cluster k6 job for
the HPA demo, and `deploy/scripts/run <local|hetzner|aws>` brings the stack up on a
chosen target (the cloud targets restore from a seeded Postgres dump).

## Key dependencies

| Component | Library |
|-----------|---------|
| API framework | FastAPI + uvicorn |
| ORM / async DB | SQLAlchemy async + asyncpg |
| Vector search | opensearch-py[async] |
| Bi-encoder (embed) | sentence-transformers (`BAAI/bge-small-en-v1.5`) |
| Cross-encoder (rerank) | sentence-transformers (`cross-encoder/ms-marco-MiniLM-L-6-v2`) |
| LLM | Groq SDK; agents use `langchain-openai` against Groq's OpenAI-compatible API |
| Agents / checkpointing | LangGraph + `langgraph-checkpoint-postgres` |
| Auth | python-jose (JWT) + passlib[bcrypt] |
| Scraping | python-jobspy, Playwright, trafilatura, ddgs |
| Package manager | uv workspace |

## Contributing / agents

[`AGENTS.md`](AGENTS.md) is the working guide for AI coding agents (and a decent
orientation for humans).
