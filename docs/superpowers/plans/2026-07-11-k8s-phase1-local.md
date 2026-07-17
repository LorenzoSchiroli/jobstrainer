# k8s Phase 1 (Local/kind) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the full jobstrainer stack (API, worker, ingestion, frontend, Postgres, OpenSearch) end-to-end on a local **kind** cluster using plain Kubernetes manifests — no Helm yet (that's Phase 3 of `docs/superpowers/specs/2026-07-07-k8s-scaling-design.md`).

**Architecture:** Two parts. (1) A backend code split, required before any manifest work: extract the reconcile/retention loops into a standalone `backend/worker.py` entrypoint and the one-time migration/backfill bootstrap into `backend/bootstrap.py`, so the API `Deployment` can safely run N replicas without racing on background work or migrations (see spec §4/§5). (2) Plain manifests under `deploy/k8s/`, applied by hand in dependency order (Postgres/OpenSearch → Secret → bootstrap Job → API/worker/frontend/CronJob) — Phase 1 deliberately has no Helm hooks, so ordering is manual and that's the point: it's what motivates Helm hooks in Phase 3.

**Tech Stack:** Kubernetes (kind), kubectl, Docker, existing `uv` workspace (`backend/`, `ingestion/`) and Dockerfiles — no new dependencies.

## Global Constraints

- No Helm in this plan — plain manifests only (`kubectl apply -f`). Helm chart is Phase 3.
- No Ingress controller — the frontend/API are reached via `kubectl port-forward` to the same `localhost:3000`/`localhost:8000` ports the app already uses in `docker-compose.yml`, so the existing hardcoded CORS origin (`http://localhost:3000` in `backend/backend/main.py`) and `VITE_API_URL` build-arg pattern both work unchanged. Ingress/dual-host routing is deferred — it isn't one of Phase 1's stated concepts (Pod, Deployment, Service, CronJob).
- No ConfigMap — one Secret carries all config (secret and non-secret alike). Splitting Secret/ConfigMap isn't a Phase 1 concept either; it's introduced with templating value in Phase 3.
- Match existing local dev values where they exist: Postgres user/password/db (`postgres`/`postgres`/`jobstrainer`), OpenSearch `DISABLE_SECURITY_PLUGIN=true` + `discovery.type=single-node`, ingestion schedule every 2 hours (`0 */2 * * *`, matching the current `sleep 7200` loop).
- All new async tests rely on `asyncio_mode = "auto"` (`backend/pyproject.toml`) — no `@pytest.mark.asyncio` decorator needed, just `async def test_...`.
- `kind` is not installed in this environment yet — Task 4 installs it via Homebrew (macOS).

---

## Part A — Backend code split

### Task 1: Extract `backend/worker.py` entrypoint

**Files:**
- Create: `backend/backend/worker.py`
- Test: `backend/tests/test_worker_entrypoint.py`

**Interfaces:**
- Consumes: `backend.opensearch_client.init_opensearch() -> None` (async, idempotent — already exists, `backend/backend/opensearch_client.py:70`); `backend.outbox.worker.reconcile_worker() -> None` and `retention_worker() -> None` (async, infinite loops — already exist, `backend/backend/outbox/worker.py:169` and `:180`).
- Produces: `backend.worker.main() -> None` (async), run via `python -m backend.worker`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_worker_entrypoint.py`:

```python
from unittest.mock import patch, AsyncMock

from backend import worker


async def test_worker_main_inits_opensearch_then_runs_both_loops():
    with patch("backend.worker.init_opensearch", new_callable=AsyncMock) as mock_init, \
         patch("backend.worker.reconcile_worker", new_callable=AsyncMock) as mock_reconcile, \
         patch("backend.worker.retention_worker", new_callable=AsyncMock) as mock_retention:
        await worker.main()

    mock_init.assert_awaited_once()
    mock_reconcile.assert_awaited_once()
    mock_retention.assert_awaited_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_worker_entrypoint.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.worker'`

- [ ] **Step 3: Write minimal implementation**

Create `backend/backend/worker.py`:

```python
import asyncio
import logging

from backend.opensearch_client import init_opensearch
from backend.outbox.worker import reconcile_worker, retention_worker

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

logger = logging.getLogger(__name__)


async def main() -> None:
    await init_opensearch()
    await asyncio.gather(reconcile_worker(), retention_worker())


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_worker_entrypoint.py -v`
Expected: PASS — `test_worker_main_inits_opensearch_then_runs_both_loops` passes

- [ ] **Step 5: Commit**

```bash
git add backend/backend/worker.py backend/tests/test_worker_entrypoint.py
git commit -m "feat(backend): add standalone worker entrypoint for reconcile/retention loops"
```

---

### Task 2: Extract `backend/bootstrap.py` entrypoint

**Files:**
- Create: `backend/backend/bootstrap.py`
- Test: `backend/tests/test_bootstrap.py`

**Interfaces:**
- Consumes: `backend.opensearch_client.init_opensearch() -> None`, `backend.opensearch_client.get_opensearch() -> AsyncOpenSearch`, `backend.opensearch_client.INDEX_NAME: str` (all existing); `backend.database.get_session_factory() -> async_sessionmaker` (existing, `backend/backend/database.py:16`); `backend.models.Job` (existing); `langgraph.checkpoint.postgres.aio.AsyncPostgresSaver.from_conn_string(db_url) -> async context manager yielding an object with `.setup()`.
- Produces: `backend.bootstrap.backfill_created_at() -> None` (async — moved verbatim from `backend/backend/main.py`'s current `_backfill_created_at`), `backend.bootstrap.main() -> None` (async), run via `python -m backend.bootstrap`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_bootstrap.py`:

```python
from unittest.mock import patch, AsyncMock, MagicMock

from backend import bootstrap


async def test_bootstrap_main_runs_init_setup_backfill_in_order():
    call_order = []

    async def record_init():
        call_order.append("init_opensearch")

    async def record_setup():
        call_order.append("checkpointer.setup")

    async def record_backfill():
        call_order.append("backfill_created_at")

    mock_checkpointer = MagicMock()
    mock_checkpointer.setup = AsyncMock(side_effect=record_setup)
    mock_saver_cm = MagicMock()
    mock_saver_cm.__aenter__ = AsyncMock(return_value=mock_checkpointer)
    mock_saver_cm.__aexit__ = AsyncMock(return_value=None)

    with patch("backend.bootstrap.init_opensearch", new=AsyncMock(side_effect=record_init)), \
         patch("backend.bootstrap.AsyncPostgresSaver.from_conn_string", return_value=mock_saver_cm), \
         patch("backend.bootstrap.backfill_created_at", new=AsyncMock(side_effect=record_backfill)):
        await bootstrap.main()

    assert call_order == ["init_opensearch", "checkpointer.setup", "backfill_created_at"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_bootstrap.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.bootstrap'`

- [ ] **Step 3: Write minimal implementation**

Create `backend/backend/bootstrap.py` (the body of `backfill_created_at` is moved verbatim from `backend/backend/main.py`'s current `_backfill_created_at`, `main.py:37-49`):

```python
import asyncio
import logging
import os

from sqlalchemy import select
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from backend.database import get_session_factory
from backend.opensearch_client import init_opensearch, get_opensearch, INDEX_NAME
from backend.models import Job

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

logger = logging.getLogger(__name__)


async def backfill_created_at() -> None:
    factory = get_session_factory()
    os_client = get_opensearch()
    async with factory() as session:
        rows = (await session.execute(select(Job.id, Job.created_at))).all()
    if not rows:
        return
    body = []
    for job_id, created_at in rows:
        body.append({"update": {"_id": str(job_id)}})
        body.append({"doc": {"created_at": created_at.isoformat()}, "doc_as_upsert": False})
    await os_client.bulk(index=INDEX_NAME, body=body)
    logger.info("Backfilled created_at for %d jobs in OpenSearch", len(rows))


async def main() -> None:
    await init_opensearch()

    db_url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    async with AsyncPostgresSaver.from_conn_string(db_url) as checkpointer:
        await checkpointer.setup()

    await backfill_created_at()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_bootstrap.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/backend/bootstrap.py backend/tests/test_bootstrap.py
git commit -m "feat(backend): add one-time bootstrap entrypoint (migrations-adjacent setup, OpenSearch backfill)"
```

---

### Task 3: Simplify `main.py` lifespan and update all test fixtures

**Files:**
- Modify: `backend/backend/main.py:1-69`
- Modify: `backend/tests/conftest.py:52-63`
- Modify: `backend/tests/search/test_search_endpoint.py` (two occurrences, ~line 50 and ~line 121)
- Modify: `backend/tests/search/test_preferences_endpoint.py` (~line 32)
- Modify: `backend/tests/search/test_advanced_endpoint.py` (two occurrences, ~line 70 and ~line 130)
- Modify: `backend/tests/tailorer/test_ws.py` (~line 75)

**Interfaces:**
- Produces: simplified `lifespan(app)` — no longer starts `reconcile_worker`/`retention_worker` tasks, no longer calls `_backfill_created_at()` or `checkpointer.setup()`. `get_checkpointer()` behavior is unchanged (still returns the live connection opened in lifespan).
- This task has no code dependency on Task 1/2's new modules (`main.py` never imported `backend.worker`/`backend.bootstrap` and still doesn't) — it only removes code that moved there in Tasks 1–2. Do this task after Tasks 1–2 so the moved code isn't lost.

- [ ] **Step 1: Rewrite `backend/backend/main.py`'s imports and lifespan**

Replace the full top of the file (lines 1–69, ending right before `app = FastAPI(...)`) with:

```python
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

from backend.routers import companies, jobs
from backend.routers.search import router as search_router
from backend.routers.auth import router as auth_router
from backend.routers.cv import router as cv_router
from backend.tailorer.router import router as tailorer_router
from backend.routers.preferences import router as preferences_router
from backend.routers.search_advanced import router as search_advanced_router
from backend.search.models_lifecycle import init_models
from backend.opensearch_client import init_opensearch

logger = logging.getLogger(__name__)

_checkpointer: AsyncPostgresSaver | None = None


def get_checkpointer() -> AsyncPostgresSaver:
    if _checkpointer is None:
        raise RuntimeError("Checkpointer not initialized")
    return _checkpointer


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _checkpointer
    init_models()
    await init_opensearch()

    db_url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    async with AsyncPostgresSaver.from_conn_string(db_url) as checkpointer:
        _checkpointer = checkpointer
        yield
```

This drops: the `asyncio`, `sqlalchemy.select`, `backend.outbox.worker` (`reconcile_worker`/`retention_worker`), `backend.database.get_session_factory`, and `backend.models.Job` imports (all now unused — their only caller, `_backfill_created_at`, moved to `backend/backend/bootstrap.py` in Task 2), and the two `asyncio.create_task(...)` lines plus the `checkpointer.setup()` call (moved to the bootstrap Job, Task 8).

- [ ] **Step 2: Update `backend/tests/conftest.py`**

In the `client` fixture (around line 52), replace:

```python
    mock_checkpointer = MagicMock()
    mock_checkpointer.setup = AsyncMock()
    mock_saver_cm = MagicMock()
    mock_saver_cm.__aenter__ = AsyncMock(return_value=mock_checkpointer)
    mock_saver_cm.__aexit__ = AsyncMock(return_value=None)

    with patch("backend.main.init_models"), \
         patch("backend.main.init_opensearch", new_callable=AsyncMock), \
         patch("backend.main.reconcile_worker", new_callable=AsyncMock), \
         patch("backend.main.retention_worker", new_callable=AsyncMock), \
         patch("backend.main._backfill_created_at", new_callable=AsyncMock), \
         patch("backend.main.AsyncPostgresSaver.from_conn_string", return_value=mock_saver_cm):
```

with:

```python
    mock_checkpointer = MagicMock()
    mock_saver_cm = MagicMock()
    mock_saver_cm.__aenter__ = AsyncMock(return_value=mock_checkpointer)
    mock_saver_cm.__aexit__ = AsyncMock(return_value=None)

    with patch("backend.main.init_models"), \
         patch("backend.main.init_opensearch", new_callable=AsyncMock), \
         patch("backend.main.AsyncPostgresSaver.from_conn_string", return_value=mock_saver_cm):
```

- [ ] **Step 3: Update the four remaining test files**

In each of `backend/tests/search/test_search_endpoint.py` (both occurrences), `backend/tests/search/test_preferences_endpoint.py`, `backend/tests/search/test_advanced_endpoint.py` (both occurrences), and `backend/tests/tailorer/test_ws.py`: remove the `patch("backend.main.reconcile_worker", ...)`, `patch("backend.main.retention_worker", ...)`, and `patch("backend.main._backfill_created_at", ...)` lines from every `with patch(...)` block, keeping `patch("backend.main.init_models")` and `patch("backend.main.init_opensearch", new_callable=AsyncMock)` (and any other unrelated patches already in that block, e.g. `backend.search.advanced.nodes.rerank` in `test_advanced_endpoint.py` — leave those alone). Fix trailing commas/backslashes so the `with` statement stays valid Python.

- [ ] **Step 4: Run the full backend test suite**

Run: `cd backend && uv run pytest -v`
Expected: PASS, 0 errors. (Requires local Postgres at `postgresql+asyncpg://postgres:postgres@localhost:5432/jobstrainer_test` — see `CLAUDE.md`.) If any test still references `backend.main.reconcile_worker`/`retention_worker`/`_backfill_created_at`, it will fail with `AttributeError: <module 'backend.main'> does not have the attribute ...` — that means Step 3 missed an occurrence; grep for it: `grep -rn "backend.main.reconcile_worker\|backend.main.retention_worker\|backend.main._backfill_created_at" backend/tests/`.

- [ ] **Step 5: Commit**

```bash
git add backend/backend/main.py backend/tests/conftest.py backend/tests/search/test_search_endpoint.py backend/tests/search/test_preferences_endpoint.py backend/tests/search/test_advanced_endpoint.py backend/tests/tailorer/test_ws.py
git commit -m "refactor(backend): simplify API lifespan now that worker/bootstrap are separate entrypoints"
```

---

## Part B — Kubernetes manifests (kind)

### Task 4: kind cluster + image build/load, `deploy/k8s/README.md`

**Files:**
- Create: `deploy/k8s/README.md`

**Interfaces:**
- Produces: a running kind cluster named `jobstrainer`, and three images loaded into it: `jobstrainer-backend:local`, `jobstrainer-ingestion:local`, `jobstrainer-frontend:local`. Every later task's manifests reference these exact image names/tags.

- [ ] **Step 1: Install kind**

Run: `brew install kind`
Expected: `kind version 0.2x.0` — verify with `kind version`

- [ ] **Step 2: Create the cluster**

Run: `kind create cluster --name jobstrainer`
Expected: ends with `Set kubectl context to "kind-jobstrainer"` — verify with `kubectl get nodes` showing one `Ready` node.

- [ ] **Step 3: Build the three images**

From the repo root:

```bash
docker build -f backend/Dockerfile -t jobstrainer-backend:local .
docker build -f ingestion/Dockerfile -t jobstrainer-ingestion:local .
docker build -f frontend/Dockerfile --build-arg VITE_API_URL=http://localhost:8000 -t jobstrainer-frontend:local ./frontend
```

Expected: all three `docker build` commands exit 0. Verify with `docker images | grep jobstrainer` showing all three tags.

- [ ] **Step 4: Load the images into kind**

Run: `kind load docker-image jobstrainer-backend:local jobstrainer-ingestion:local jobstrainer-frontend:local --name jobstrainer`
Expected: no errors. There is no `kind` command to verify the load directly; it's confirmed implicitly in Task 9/11/12 when pods using these images reach `Running` with `imagePullPolicy: IfNotPresent` (no attempted registry pull).

- [ ] **Step 5: Write `deploy/k8s/README.md`**

Create `deploy/k8s/README.md`:

```markdown
# jobstrainer on kind (Phase 1)

Plain manifests, no Helm. Apply order matters — Kubernetes has no
dependency graph between plain `kubectl apply` resources, so each step below
must complete (not just be applied) before the next.

## 1. Cluster + images

    brew install kind
    kind create cluster --name jobstrainer

    docker build -f backend/Dockerfile -t jobstrainer-backend:local .
    docker build -f ingestion/Dockerfile -t jobstrainer-ingestion:local .
    docker build -f frontend/Dockerfile --build-arg VITE_API_URL=http://localhost:8000 -t jobstrainer-frontend:local ./frontend

    kind load docker-image jobstrainer-backend:local jobstrainer-ingestion:local jobstrainer-frontend:local --name jobstrainer

Re-run the `docker build` + `kind load` pair after any code change — kind
doesn't watch for image changes.
```

- [ ] **Step 6: Commit**

```bash
git add deploy/k8s/README.md
git commit -m "docs(k8s): add kind cluster setup and image build instructions"
```

---

### Task 5: Postgres StatefulSet + Service

**Files:**
- Create: `deploy/k8s/postgres.yaml`
- Modify: `deploy/k8s/README.md`

**Interfaces:**
- Produces: a `Service` named `postgres` on port `5432`, backing a single Postgres 16 instance with database `jobstrainer`, user `postgres`, password `postgres` (matches `docker-compose.yml`). Later tasks' `DATABASE_URL` is `postgresql+asyncpg://postgres:postgres@postgres:5432/jobstrainer`.

- [ ] **Step 1: Write `deploy/k8s/postgres.yaml`**

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
spec:
  serviceName: postgres
  replicas: 1
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      containers:
      - name: postgres
        image: postgres:16
        env:
        - name: POSTGRES_USER
          value: postgres
        - name: POSTGRES_PASSWORD
          value: postgres
        - name: POSTGRES_DB
          value: jobstrainer
        ports:
        - containerPort: 5432
        volumeMounts:
        - name: data
          mountPath: /var/lib/postgresql/data
        readinessProbe:
          exec:
            command: ["pg_isready", "-U", "postgres"]
          initialDelaySeconds: 5
          periodSeconds: 5
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: 500m
            memory: 512Mi
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 1Gi
---
apiVersion: v1
kind: Service
metadata:
  name: postgres
spec:
  selector:
    app: postgres
  ports:
  - port: 5432
    targetPort: 5432
```

- [ ] **Step 2: Apply and verify**

Run: `kubectl apply -f deploy/k8s/postgres.yaml`
Then: `kubectl wait --for=condition=ready pod -l app=postgres --timeout=120s`
Expected: `pod/postgres-0 condition met`

- [ ] **Step 3: Append to `deploy/k8s/README.md`**

```markdown
## 2. Postgres

    kubectl apply -f deploy/k8s/postgres.yaml
    kubectl wait --for=condition=ready pod -l app=postgres --timeout=120s
```

- [ ] **Step 4: Commit**

```bash
git add deploy/k8s/postgres.yaml deploy/k8s/README.md
git commit -m "feat(k8s): add Postgres StatefulSet for local kind deployment"
```

---

### Task 6: OpenSearch StatefulSet + Service

**Files:**
- Create: `deploy/k8s/opensearch.yaml`
- Modify: `deploy/k8s/README.md`

**Interfaces:**
- Produces: a `Service` named `opensearch` on port `9200`, security plugin disabled (matches `docker-compose.yml`, see spec's OpenSearch security note in §3). Later tasks' `OPENSEARCH_URL` is `http://opensearch:9200`.

- [ ] **Step 1: Write `deploy/k8s/opensearch.yaml`**

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: opensearch
spec:
  serviceName: opensearch
  replicas: 1
  selector:
    matchLabels:
      app: opensearch
  template:
    metadata:
      labels:
        app: opensearch
    spec:
      containers:
      - name: opensearch
        image: opensearchproject/opensearch:2
        env:
        - name: discovery.type
          value: single-node
        - name: DISABLE_SECURITY_PLUGIN
          value: "true"
        - name: OPENSEARCH_JAVA_OPTS
          value: "-Xms512m -Xmx512m"
        ports:
        - containerPort: 9200
        volumeMounts:
        - name: data
          mountPath: /usr/share/opensearch/data
        readinessProbe:
          httpGet:
            path: /_cluster/health
            port: 9200
          initialDelaySeconds: 20
          periodSeconds: 10
          failureThreshold: 12
        resources:
          requests:
            cpu: 250m
            memory: 512Mi
          limits:
            cpu: 1000m
            memory: 1Gi
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 2Gi
---
apiVersion: v1
kind: Service
metadata:
  name: opensearch
spec:
  selector:
    app: opensearch
  ports:
  - port: 9200
    targetPort: 9200
```

- [ ] **Step 2: Apply and verify**

Run: `kubectl apply -f deploy/k8s/opensearch.yaml`
Then: `kubectl wait --for=condition=ready pod -l app=opensearch --timeout=180s`
Expected: `pod/opensearch-0 condition met`

- [ ] **Step 3: Append to `deploy/k8s/README.md`**

```markdown
## 3. OpenSearch

    kubectl apply -f deploy/k8s/opensearch.yaml
    kubectl wait --for=condition=ready pod -l app=opensearch --timeout=180s
```

- [ ] **Step 4: Commit**

```bash
git add deploy/k8s/opensearch.yaml deploy/k8s/README.md
git commit -m "feat(k8s): add OpenSearch StatefulSet for local kind deployment"
```

---

### Task 7: Secret

**Files:**
- Modify: `deploy/k8s/README.md`

No manifest is committed for this task — the Secret is created imperatively from the repo's existing `.env` (per `CLAUDE.md`'s required env vars) plus the two cluster-internal URLs, so no real credentials ever land in a tracked file.

**Interfaces:**
- Produces: a `Secret` named `jobstrainer-secrets` containing every key from `.env` (`GROQ_API_KEY`, `GROQ_MODEL_LARGE`, `GROQ_MODEL_BASE`, `SECRET_KEY`, `ACCESS_TOKEN_EXPIRE_DAYS`, `OFFER_QUERY`, `SERPERDEV_API_KEY`, `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `DDGS_PROXY`) plus `DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/jobstrainer`, `OPENSEARCH_URL=http://opensearch:9200`, `BACKEND_URL=http://api:8000`. Every later Deployment/Job/CronJob consumes it via `envFrom: - secretRef: {name: jobstrainer-secrets}`.

- [ ] **Step 1: Create the Secret**

From the repo root (requires the existing `.env` file, per `CLAUDE.md`):

```bash
kubectl create secret generic jobstrainer-secrets \
  --from-env-file=.env \
  --from-literal=DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/jobstrainer \
  --from-literal=OPENSEARCH_URL=http://opensearch:9200 \
  --from-literal=BACKEND_URL=http://api:8000
```

Expected: `secret/jobstrainer-secrets created`

- [ ] **Step 2: Verify the keys landed**

Run: `kubectl get secret jobstrainer-secrets -o jsonpath='{.data}' | tr ',' '\n'`
Expected: a line per key listed above (base64-encoded values, not printed in plaintext by this command).

- [ ] **Step 3: Append to `deploy/k8s/README.md`**

```markdown
## 4. Secret

Requires the repo's `.env` file (see `CLAUDE.md` for required vars).

    kubectl create secret generic jobstrainer-secrets \
      --from-env-file=.env \
      --from-literal=DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/jobstrainer \
      --from-literal=OPENSEARCH_URL=http://opensearch:9200 \
      --from-literal=BACKEND_URL=http://api:8000

To pick up `.env` changes: `kubectl delete secret jobstrainer-secrets` then re-run the command above, then restart any running pods (`kubectl rollout restart deployment api worker`).
```

- [ ] **Step 4: Commit**

```bash
git add deploy/k8s/README.md
git commit -m "docs(k8s): document Secret creation from .env"
```

---

### Task 8: Bootstrap Job

**Files:**
- Create: `deploy/k8s/bootstrap-job.yaml`
- Modify: `deploy/k8s/README.md`

**Interfaces:**
- Consumes: `jobstrainer-secrets` (Task 7), `postgres`/`opensearch` Services (Tasks 5–6), `backend.bootstrap` entrypoint (Task 2).
- Produces: migrated Postgres schema, the `jobs` OpenSearch index + `hybrid-pipeline`, and LangGraph checkpointer tables — all preconditions for Tasks 9–10.

- [ ] **Step 1: Write `deploy/k8s/bootstrap-job.yaml`**

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: jobstrainer-bootstrap
spec:
  backoffLimit: 3
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: bootstrap
        image: jobstrainer-backend:local
        imagePullPolicy: IfNotPresent
        command: ["sh", "-c", "uv run alembic upgrade head && uv run python -m backend.bootstrap"]
        envFrom:
        - secretRef:
            name: jobstrainer-secrets
        resources:
          requests:
            cpu: 100m
            memory: 256Mi
          limits:
            cpu: 500m
            memory: 512Mi
```

- [ ] **Step 2: Apply and verify**

Run: `kubectl apply -f deploy/k8s/bootstrap-job.yaml`
Then: `kubectl wait --for=condition=complete job/jobstrainer-bootstrap --timeout=180s`
Expected: `job.batch/jobstrainer-bootstrap condition met`. If it fails, check `kubectl logs job/jobstrainer-bootstrap` — a common cause is the Secret/Postgres/OpenSearch from Tasks 5–7 not being ready yet.

- [ ] **Step 3: Append to `deploy/k8s/README.md`**

```markdown
## 5. Bootstrap (migrations + OpenSearch index + checkpointer tables)

    kubectl apply -f deploy/k8s/bootstrap-job.yaml
    kubectl wait --for=condition=complete job/jobstrainer-bootstrap --timeout=180s

Job specs are immutable, so re-running bootstrap (e.g. after a new
migration) requires deleting the old Job first:

    kubectl delete job jobstrainer-bootstrap --ignore-not-found
    kubectl apply -f deploy/k8s/bootstrap-job.yaml
```

- [ ] **Step 4: Commit**

```bash
git add deploy/k8s/bootstrap-job.yaml deploy/k8s/README.md
git commit -m "feat(k8s): add one-time bootstrap Job (migrations, OpenSearch index, checkpointer setup)"
```

---

### Task 9: API Deployment + Service

**Files:**
- Create: `deploy/k8s/api-deployment.yaml`
- Modify: `deploy/k8s/README.md`

**Interfaces:**
- Consumes: `jobstrainer-secrets`, `postgres`/`opensearch` Services, completed `jobstrainer-bootstrap` Job.
- Produces: a `Service` named `api` on port `8000`. Later tasks (frontend, `BACKEND_URL` in the Secret) depend on this exact name/port.

- [ ] **Step 1: Write `deploy/k8s/api-deployment.yaml`**

The container `command` overrides the image's default `CMD` (`alembic upgrade head && uvicorn ...`) to skip migrations — those are now the bootstrap Job's job (spec §4):

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
spec:
  replicas: 1
  selector:
    matchLabels:
      app: api
  template:
    metadata:
      labels:
        app: api
    spec:
      containers:
      - name: api
        image: jobstrainer-backend:local
        imagePullPolicy: IfNotPresent
        command: ["uv", "run", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
        envFrom:
        - secretRef:
            name: jobstrainer-secrets
        ports:
        - containerPort: 8000
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 5
          failureThreshold: 12
        resources:
          requests:
            cpu: 250m
            memory: 512Mi
          limits:
            cpu: 1000m
            memory: 1536Mi
---
apiVersion: v1
kind: Service
metadata:
  name: api
spec:
  selector:
    app: api
  ports:
  - port: 8000
    targetPort: 8000
```

`replicas: 1` here, not the spec's eventual `min 2` — HPA and multi-replica behavior are Phase 2's concept, not Phase 1's. `/health` is a thin liveness-style check today (spec §6 flags deeper Postgres/OpenSearch reachability probing as a later refinement); it's still meaningful here because FastAPI's `lifespan` blocks serving until `init_models()` + `init_opensearch()` + the checkpointer connection all succeed, so a pod can't become ready with models unloaded.

- [ ] **Step 2: Apply and verify**

Run: `kubectl apply -f deploy/k8s/api-deployment.yaml`
Then: `kubectl wait --for=condition=available deployment/api --timeout=120s`
Expected: `deployment.apps/api condition met`

Then: `kubectl port-forward svc/api 8000:8000 &` and `curl http://localhost:8000/health`
Expected: `{"status":"ok"}`

- [ ] **Step 3: Append to `deploy/k8s/README.md`**

```markdown
## 6. API

    kubectl apply -f deploy/k8s/api-deployment.yaml
    kubectl wait --for=condition=available deployment/api --timeout=120s
    kubectl port-forward svc/api 8000:8000 &
    curl http://localhost:8000/health   # {"status":"ok"}
```

- [ ] **Step 4: Commit**

```bash
git add deploy/k8s/api-deployment.yaml deploy/k8s/README.md
git commit -m "feat(k8s): add API Deployment (migration-free command) and Service"
```

---

### Task 10: Worker Deployment

**Files:**
- Create: `deploy/k8s/worker-deployment.yaml`
- Modify: `deploy/k8s/README.md`

**Interfaces:**
- Consumes: `jobstrainer-secrets`, `postgres`/`opensearch` Services, completed `jobstrainer-bootstrap` Job, `backend.worker` entrypoint (Task 1).
- Produces: nothing consumed by later tasks — this is the terminal singleton (spec §2.4: "no Service, nothing calls it").

- [ ] **Step 1: Write `deploy/k8s/worker-deployment.yaml`**

`replicas: 1` with `strategy: Recreate` so there's never a moment with two copies running the reconcile/retention loops against the same `outbox` table (spec §3):

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: worker
spec:
  replicas: 1
  strategy:
    type: Recreate
  selector:
    matchLabels:
      app: worker
  template:
    metadata:
      labels:
        app: worker
    spec:
      containers:
      - name: worker
        image: jobstrainer-backend:local
        imagePullPolicy: IfNotPresent
        command: ["uv", "run", "python", "-m", "backend.worker"]
        envFrom:
        - secretRef:
            name: jobstrainer-secrets
        resources:
          requests:
            cpu: 50m
            memory: 128Mi
          limits:
            cpu: 300m
            memory: 256Mi
```

- [ ] **Step 2: Apply and verify**

Run: `kubectl apply -f deploy/k8s/worker-deployment.yaml`
Then: `kubectl wait --for=condition=available deployment/worker --timeout=60s`
Expected: `deployment.apps/worker condition met`

Then: `kubectl logs deployment/worker --tail=20`
Expected: no traceback; the process starts and (per `RECONCILE_INTERVAL_SECONDS = 300` in `backend/backend/outbox/worker.py`) ticks silently unless there's outbox work — absence of `Reconcile worker error` / `Retention worker error` log lines is the pass condition.

- [ ] **Step 3: Append to `deploy/k8s/README.md`**

```markdown
## 7. Worker

    kubectl apply -f deploy/k8s/worker-deployment.yaml
    kubectl wait --for=condition=available deployment/worker --timeout=60s
    kubectl logs deployment/worker --tail=20   # no errors
```

- [ ] **Step 4: Commit**

```bash
git add deploy/k8s/worker-deployment.yaml deploy/k8s/README.md
git commit -m "feat(k8s): add singleton worker Deployment for reconcile/retention loops"
```

---

### Task 11: Ingestion CronJob

**Files:**
- Create: `deploy/k8s/ingestion-cronjob.yaml`
- Modify: `deploy/k8s/README.md`

**Interfaces:**
- Consumes: `jobstrainer-secrets` (specifically `OFFER_QUERY` and `BACKEND_URL`), the `api` Service (Task 9) — `ingestion/ingestion/client.py:7-9` hard-fails if `BACKEND_URL` isn't set.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Write `deploy/k8s/ingestion-cronjob.yaml`**

`$(OFFER_QUERY)` is Kubernetes' native `command`/`args` env-var substitution (resolved by the kubelet from the container's own env, populated here via `envFrom`) — no shell needed:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: ingestion
spec:
  schedule: "0 */2 * * *"
  concurrencyPolicy: Forbid
  jobTemplate:
    spec:
      backoffLimit: 1
      template:
        spec:
          restartPolicy: OnFailure
          containers:
          - name: ingestion
            image: jobstrainer-ingestion:local
            imagePullPolicy: IfNotPresent
            command: ["uv", "run", "python", "-m", "ingestion.pipeline", "$(OFFER_QUERY)", "--hours", "2"]
            envFrom:
            - secretRef:
                name: jobstrainer-secrets
            resources:
              requests:
                cpu: 500m
                memory: 1Gi
              limits:
                cpu: 1500m
                memory: 2Gi
```

- [ ] **Step 2: Apply and manually trigger a run**

Run: `kubectl apply -f deploy/k8s/ingestion-cronjob.yaml`
Expected: `cronjob.batch/ingestion created`

CronJobs don't run on `apply` — trigger one manually to verify the pod spec works, rather than waiting up to 2 hours:

Run: `kubectl create job --from=cronjob/ingestion ingestion-manual-test`
Then: `kubectl wait --for=condition=complete job/ingestion-manual-test --timeout=600s`
Expected: `job.batch/ingestion-manual-test condition met`. Check `kubectl logs job/ingestion-manual-test` for the pipeline's normal scrape/parse/embed/POST log lines and no `BACKEND_URL environment variable is not set` error.

- [ ] **Step 3: Clean up the manual test job**

Run: `kubectl delete job ingestion-manual-test`

- [ ] **Step 4: Append to `deploy/k8s/README.md`**

```markdown
## 8. Ingestion CronJob

    kubectl apply -f deploy/k8s/ingestion-cronjob.yaml

Runs every 2 hours automatically. To trigger one run immediately (e.g. to
verify the pod spec without waiting):

    kubectl create job --from=cronjob/ingestion ingestion-manual-test
    kubectl wait --for=condition=complete job/ingestion-manual-test --timeout=600s
    kubectl logs job/ingestion-manual-test
    kubectl delete job ingestion-manual-test
```

- [ ] **Step 5: Commit**

```bash
git add deploy/k8s/ingestion-cronjob.yaml deploy/k8s/README.md
git commit -m "feat(k8s): add ingestion CronJob (replaces in-container while-true loop)"
```

---

### Task 12: Frontend Deployment + Service, end-to-end verification

**Files:**
- Create: `deploy/k8s/frontend-deployment.yaml`
- Modify: `deploy/k8s/README.md`

**Interfaces:**
- Consumes: the `jobstrainer-frontend:local` image (Task 4, already built with `VITE_API_URL=http://localhost:8000` baked in — see Global Constraints).
- Produces: a `Service` named `frontend` on port `80`. Terminal task — this is the full-stack verification.

- [ ] **Step 1: Write `deploy/k8s/frontend-deployment.yaml`**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: frontend
spec:
  replicas: 1
  selector:
    matchLabels:
      app: frontend
  template:
    metadata:
      labels:
        app: frontend
    spec:
      containers:
      - name: frontend
        image: jobstrainer-frontend:local
        imagePullPolicy: IfNotPresent
        ports:
        - containerPort: 80
        resources:
          requests:
            cpu: 25m
            memory: 32Mi
          limits:
            cpu: 200m
            memory: 128Mi
---
apiVersion: v1
kind: Service
metadata:
  name: frontend
spec:
  selector:
    app: frontend
  ports:
  - port: 80
    targetPort: 80
```

- [ ] **Step 2: Apply and verify**

Run: `kubectl apply -f deploy/k8s/frontend-deployment.yaml`
Then: `kubectl wait --for=condition=available deployment/frontend --timeout=60s`
Expected: `deployment.apps/frontend condition met`

- [ ] **Step 3: End-to-end browser check**

```bash
kubectl port-forward svc/api 8000:8000 &
kubectl port-forward svc/frontend 3000:80 &
```

Open `http://localhost:3000` in a browser. Expected: the app loads, and a search request (or whatever the frontend's landing action is) round-trips to the API without a CORS error in the browser console — the existing hardcoded `allow_origins=["http://localhost:3000"]` in `backend/backend/main.py` already permits this origin because the port-forward reuses the same port the app already assumes.

This is the Phase 1 completion condition from the spec: "full stack works end-to-end on kind."

- [ ] **Step 4: Append to `deploy/k8s/README.md`**

```markdown
## 9. Frontend

    kubectl apply -f deploy/k8s/frontend-deployment.yaml
    kubectl wait --for=condition=available deployment/frontend --timeout=60s

## Full stack access

    kubectl port-forward svc/api 8000:8000 &
    kubectl port-forward svc/frontend 3000:80 &

Open http://localhost:3000 — this matches docker-compose's ports exactly, so
the frontend's baked-in VITE_API_URL and the backend's CORS allow-list both
work unchanged.
```

- [ ] **Step 5: Commit**

```bash
git add deploy/k8s/frontend-deployment.yaml deploy/k8s/README.md
git commit -m "feat(k8s): add frontend Deployment and Service, complete Phase 1 local stack"
```
