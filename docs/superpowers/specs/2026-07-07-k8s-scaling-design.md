# jobstrainer on Kubernetes — Scaling Design

**Date:** 2026-07-07
**Status:** Design (pre-implementation)
**Author:** lschiroli

## 1. Goal

Package and run the full jobstrainer stack on Kubernetes as **one portable Helm
chart** that runs unchanged on three targets:

- **local** — a laptop cluster (kind / k3d / minikube) for development and learning
- **baremetal** — a self-managed cluster on your own VMs
- **eks** — a managed cloud cluster (EKS/GKE/AKS)

The design must support horizontal scaling under load *and* collapsing to near
nothing when idle, and it is explicitly structured as a **layered learning path**
so each phase introduces one new Kubernetes concept rather than all at once.

This is primarily a personal/portfolio project; the design favours clarity and
"exercise the real toolbox" over squeezing maximum production throughput.

## 2. Key principles

1. **One chart, per-environment values.** A single Helm chart with
   `values-local.yaml` / `values-baremetal.yaml` / `values-eks.yaml`. Every
   environment-specific or optional component is a toggle in values, not a fork
   of the manifests.

2. **Postgres is the only precious store.** It is the source of truth. It needs
   durable storage and, in production, backups. It is **not** horizontally
   scaled for writes (single-writer RDBMS); scaling is vertical + optional read
   replicas.

3. **OpenSearch is a rebuildable derived index, not precious.** Its contents are
   a copy of Postgres data. The reconcile worker repopulates any missing docs
   from Postgres (within the 30-day window), and `_backfill_created_at` tops it
   up on startup. Therefore:
   - It uses a normal disk (PVC) so *restarts* are fast and skip a full
     re-index, but losing that disk is **recoverable, not catastrophic** — it
     re-warms from Postgres (takes time, no data loss).
   - No backup machinery and no mandatory managed-OpenSearch requirement. It can
     run in-cluster on every target.
   - Its only real scaling knob is data-node/shard replica count for search
     throughput.

4. **Cluster-wide singletons live outside the request-serving pods.** Anything
   that must run "once for the whole cluster" is pulled out of the replicated
   API:
   - continuous loops (reconcile/retention sync) → a singleton **worker**
     Deployment (`replicas: 1`)
   - scheduled one-shots (ingestion) → a **CronJob**

5. **App code is environment-agnostic.** The application only reads
   `DATABASE_URL` / `OPENSEARCH_URL` / secrets from config. It never knows
   whether a store is in-cluster or external.

## 3. Per-service scaling model

| Service | K8s object | Scaling mechanism | Notes |
|---|---|---|---|
| **backend API** | Deployment | **HPA** on CPU | Stateless. CPU-bound (loads bi-encoder + cross-encoder per pod; rerank is the hot path). Behind a Service (load balancer) that spreads requests across replicas. `min 1`, `max N` — cost-optimized: no standing redundancy, but no config needed for zero-downtime deploys either (see below). Readiness probe gates traffic until models load. |
| **backend worker** | Deployment, **`replicas: 1`** | Not horizontally scaled (singleton by design) | Runs `reconcile_worker` + `retention_worker`. `strategy: Recreate` so there is never briefly a 2nd copy. No Service (nothing calls it). |
| **ingestion** | **CronJob** | Schedule-driven; 0 pods when idle | Replaces the current in-container `while true: run --hours 2; sleep 7200` loop with `schedule: "0 */2 * * *"` (same 2h cadence). `OFFER_QUERY` comes from values (one query for now, matching current behavior — multiple queries would mean multiple CronJob entries later). `concurrencyPolicy: Forbid`, `restartPolicy: OnFailure`. Heavy pod (chromium + embedding model) alive only during a run. |
| **frontend** | Deployment + Ingress | HPA or fixed 1 replica | Static nginx; trivially scalable. Real caching answer is the Ingress/CDN. Same `min 1` cost tradeoff as the API. |
| **Postgres** | StatefulSet/operator *or* external | Vertical + optional read replicas | `inCluster=true`: StatefulSet (optionally via CloudNativePG operator) with PVC + backups. `inCluster=false`: chart emits only a Secret pointing at RDS/Cloud SQL. Single-writer. |
| **OpenSearch** | StatefulSet *or* external | **Horizontal** via data-node count + shard replicas | Runs in-cluster on all targets by default (rebuildable, see §2.3). PVC for fast restart, treated as disposable. `external` toggle exists but is optional. |

### Load-balancing note
A **Service** sits in front of each replicated Deployment and distributes
*different* requests across the replicas. Each individual request is still served
by exactly one pod; N replicas means N requests handled in parallel. This is why
horizontal scaling works — and why self-firing background timers must NOT live in
a replicated pod (they would fire once per replica and collide).

### Cost vs redundancy note (API/frontend `min 1`)
`min 2` exists purely for *redundancy*, not load — it guarantees one replica
can be down (deploy, crash, node drain) while another keeps serving, at the
cost of paying for double the steady-state compute. `min 1` drops that
standing redundancy to cut cost, but doesn't give up zero-downtime deploys:
a Deployment's default `RollingUpdate` strategy (`maxSurge: 25%`,
`maxUnavailable: 25%`, unset in the manifest) rounds to `maxSurge: 1`,
`maxUnavailable: 0` at `replicas: 1` — every update spins up a 2nd pod,
waits for it to be ready, *then* kills the old one. Briefly 2, back down to
1, no explicit config needed. This is exactly why the worker Deployment
needs `strategy: Recreate` to *opt out* of this default — the API has no
such constraint, so it gets deploy-time safety for free. What `min 1` does
give up: an *unplanned* single-pod failure (crash, node loss) has a gap
while Kubernetes reschedules, since there's no live standby to fail over to.
Accepted tradeoff for this project.

### OpenSearch security note
The compose stack runs OpenSearch with `DISABLE_SECURITY_PLUGIN=true` and
`discovery.type=single-node`, and the backend client
(`backend/opensearch_client.py`) connects plain-HTTP with no credentials. The
in-cluster StatefulSet must carry those same env vars on the local target or
nothing can connect — the stock image defaults to security **on** (TLS + a
required admin password). Turning security/TLS on is a later values toggle
paired with client credentials; note also that scaling past one data node means
replacing `single-node` discovery with real cluster discovery config.

## 4. The backend split (the linchpin — required code change)

Today `backend/main.py`'s `lifespan` starts `reconcile_worker` and
`retention_worker` as `asyncio` tasks *inside the API process*. Running N API
replicas would run N copies of those loops against the same `outbox` table and
OpenSearch index — a race. Fix:

- **New worker entrypoint** — `python -m backend.worker` (new `backend/worker.py`)
  that runs only the reconcile + retention loops. Same functions, lifted out of
  the API lifespan. It must call `init_opensearch()` on startup before the loops:
  both workers fetch the client via `get_opensearch()`, which asserts it was
  initialized (the call is idempotent — it only creates the index/pipeline if
  missing).
- **API lifespan keeps** `init_models()`, `init_opensearch()`, and opening a
  live `AsyncPostgresSaver` connection — and **drops** the two
  `asyncio.create_task(...)` lines. Opening the connection is not one-time
  setup: `get_checkpointer()` is used at **request time** by the tailorer
  websocket agent, so every API replica needs its own open connection for as
  long as it runs — same as its regular Postgres connection pool.
- **One-time bootstrap moves to a Helm init Job** (see §5): `alembic upgrade
  head`, `_backfill_created_at()`, and `checkpointer.setup()` (the one-time
  table creation, distinct from opening a connection above) must run exactly
  once per deploy, not once per API replica on boot.
- **API image `CMD` changes for k8s.** `backend/Dockerfile`'s current `CMD` is
  `alembic upgrade head && uvicorn ...`, run fresh on every container start.
  With N replicas starting together during a rollout, they'd race to apply the
  same pending migration and crash-loop (one `ALTER TABLE` succeeds, the
  others fail on the now-already-applied change). The k8s Deployment overrides
  the command to run `uvicorn` only — migrations are the init Job's
  responsibility now.

Result: API pods are pure, fast-starting, safely replicable; exactly one worker
performs all OpenSearch mutation.

## 5. One-time bootstrap: Helm init Job

A Helm `post-install`/`pre-upgrade` hook **Job** runs once per release:

1. `alembic upgrade head` (DB migrations)
2. `checkpointer.setup()` (LangGraph Postgres checkpointer tables)
3. `_backfill_created_at()` (OpenSearch top-up)

This removes one-time work from the API startup path so replicas don't duplicate
it.

Hook timing matters: a `pre-install` hook runs **before any chart resources are
created**, so on a fresh install the in-cluster Postgres/OpenSearch StatefulSets
wouldn't exist yet and the Job would wait forever. Hence `post-install` for the
first install (the Job retries until the stores accept connections; API pods sit
not-ready behind the §6 readiness probe until migrations land) and `pre-upgrade`
thereafter (the previous release's stores are already running, so migrations
correctly precede the new pods).

The Job also needs a real entrypoint — today `_backfill_created_at()` lives in
`backend/main.py` and assumes `init_opensearch()` has already run (which is also
what creates the `jobs` index on a fresh cluster). Ship a small
`python -m backend.bootstrap` alongside the §4 worker entrypoint that calls
`init_opensearch()` first, then runs steps 1–3.

Helm doesn't delete hook Jobs after they complete, so the second
`helm upgrade` would try to create a Job with the same name and fail (Job
specs are immutable). The Job needs
`helm.sh/hook-delete-policy: before-hook-creation` so each release deletes the
previous hook Job right before creating its own.

## 6. Cross-cutting scaling toolbox

Introduced progressively (see phases in §8):

- **HPA** on the API (CPU-based). Requires **metrics-server** (bundled as a
  prereq toggle; needed on kind).
- **Resource `requests`/`limits`** on every pod — required for HPA math and
  scheduling. The API is memory-heavy because of the ML models; values set
  honestly.
- **PodDisruptionBudget** — API `maxUnavailable: 1` (not `minAvailable: 1`).
  With `min 1` (see §3's cost/redundancy note), the API sits at exactly 1
  replica whenever idle; a `minAvailable: 1` PDB would then refuse to ever
  evict that one pod, blocking node drains the same way it would for the
  singleton worker. `maxUnavailable: 1` has no effect at 1 replica (nothing
  to protect yet) but still limits disruption once HPA has scaled up under
  load. The singleton worker remains excluded entirely — even
  `maxUnavailable: 1` would let its one replica be evicted with no
  guaranteed replacement ordering.
- **Pod anti-affinity** — spread API replicas (and OpenSearch data nodes) across
  nodes.
- **Probes** — API readiness waits on model load + OpenSearch reachability +
  Postgres reachability (every request needs the DB, including the
  request-time checkpointer connection from §4); worker liveness on a
  heartbeat.
- **KEDA (later, optional overlay)** — scale-to-zero / scale-from-zero on the API
  for the cost goal. Off by default.
- **Cluster Autoscaler / Karpenter (later, EKS only)** — node-level scaling;
  no-op locally.

## 7. Chart layout

```
deploy/helm/jobstrainer/
  Chart.yaml
  values.yaml                # defaults: in-cluster, small
  values-local.yaml          # kind/k3d: 1-2 replicas, tiny PVCs
  values-baremetal.yaml      # in-cluster HA, anti-affinity
  values-eks.yaml            # optional external Postgres, HPA + cluster autoscaler
  templates/
    api-deployment.yaml, api-service.yaml, api-hpa.yaml, api-pdb.yaml
    worker-deployment.yaml
    ingestion-cronjob.yaml
    frontend-deployment.yaml, frontend-service.yaml, ingress.yaml
    init-job.yaml            # alembic + backfill + checkpointer setup (helm hook)
    postgres.yaml            # {{ if .Values.postgres.inCluster }}
    opensearch.yaml          # StatefulSet (in-cluster by default)
    secrets.yaml, configmap.yaml
docs/                        # bootstrap notes: install metrics-server, (later) operators
```

### Image strategy

Every image-producing service (api, worker, ingestion, frontend) takes
`image.repository` / `image.tag` as values, defaulted per environment file —
not hardcoded in templates. This is what actually makes "one chart, per-env
values" true for images specifically:

- **local (kind):** build with the existing Dockerfiles, `kind load
  docker-image` into the cluster, `values-local.yaml` points
  `image.repository` at the locally-loaded tag. No registry needed. This is
  the only target being built out right now.
- **baremetal / eks (later):** same Dockerfiles, pushed to a registry
  (private registry / ECR / etc.) instead of loaded into kind;
  `values-baremetal.yaml` / `values-eks.yaml` just point `image.repository` at
  that registry. No template changes required — swapping the values file is
  the whole migration.

### Config & secrets

`secrets.yaml`/`configmap.yaml` need an actual source for what docker-compose
currently pulls from `.env`:

- **One shared Secret**: `GROQ_API_KEY`, `SECRET_KEY` (hard requirement —
  `backend/auth/jwt.py` does `os.environ["SECRET_KEY"]`), `SERPERDEV_API_KEY`,
  `ADZUNA_APP_ID`/`ADZUNA_APP_KEY`, `DDGS_PROXY`, and the Postgres
  password / `DATABASE_URL`. Locally, populate it from the existing `.env` via
  a gitignored `values-secrets.yaml` passed with `-f`, or
  `kubectl create secret generic ... --from-env-file=.env` before install.
- **ConfigMap** for non-secret config: `OPENSEARCH_URL`,
  `GROQ_MODEL_LARGE`/`GROQ_MODEL_BASE`, `ACCESS_TOKEN_EXPIRE_DAYS`,
  `OFFER_QUERY`.
- API, worker, and init Job all consume the **same** Secret + ConfigMap via
  `envFrom`, so their DB/OpenSearch/Groq config can't drift. The ingestion
  CronJob additionally needs `BACKEND_URL` pointing at the api Service DNS
  name (`ingestion/client.py` hard-fails without it; compose sets
  `http://backend:8000` today).

### Frontend → API wiring (build-time URL)

`VITE_API_URL` is a Docker **build arg** baked into the JS bundle at
`npm run build` (`frontend/Dockerfile`), and the nginx image serves static
files only — no runtime proxy. So the API URL cannot come from Helm values at
deploy time: the chart must expose the API to the *browser* (not just
in-cluster), and the frontend image must be built already knowing that address.

- Ingress routes two hosts — e.g. `jobstrainer.local` → frontend Service,
  `api.jobstrainer.local` → api Service (backend routes live at `/`, so
  path-based routing would need rewrites) — and the local frontend image is
  built with `VITE_API_URL=http://api.jobstrainer.local` before `kind load`.
- `backend/main.py` hardcodes CORS `allow_origins=["http://localhost:3000"]`
  with `allow_credentials=True`; the frontend's new origin must be allowed, so
  the allowed origin becomes an env var (small code change, bundled with the
  §4 split).

## 8. Layered learning / build plan

Each phase runs on a local **kind** cluster first, and teaches one concept.

1. **Run it locally (concepts: Pod, Deployment, Service, CronJob).**
   Deployments for API + worker + frontend, a CronJob for ingestion, simple
   in-cluster Postgres + OpenSearch, plain manifests or a minimal chart. Includes
   the §4 backend split and the §5 bootstrap Job — applied as a plain
   `kubectl apply` Job here; the Helm hook annotations (and delete-policy) only
   arrive with the chart in phase 3. Goal: full stack works end-to-end on kind.
2. **Add autoscaling (concept: HPA).** metrics-server + HPA on the API; generate
   load; watch replicas scale up/down.
3. **Package with Helm (concept: Helm + portability).** Convert manifests into
   the chart in §7 with `values-local`. Same deploy, one command.
4. **Production toggles (concepts: StatefulSet durability, external stores).**
   Postgres durability/backup + optional external-endpoint mode; `values-eks`.
5. **Advanced/cost (concepts: KEDA, cluster autoscaler).** Scale-to-zero overlay
   and node autoscaling for the portfolio-grade story.

## 9. Decisions & assumptions

- **Packaging:** Helm (chosen for portability + parameterization). *Assumed* —
  confirm.
- **Postgres operator vs plain StatefulSet:** start with a plain StatefulSet for
  learning; adopt CloudNativePG in a later phase if desired. External (RDS) is a
  toggle.
- **OpenSearch:** in-cluster on all targets, treated as rebuildable; external
  toggle exists but is not required.
- **Backend split:** singleton worker Deployment (chosen over in-process leader
  election for simplicity). *Assumed* — confirm.

## 10. Out of scope (YAGNI for now)

- Service mesh, mTLS, network policies.
- Multi-region / cross-cluster.
- GPU inference (models run on CPU today; unchanged).
- Managed-OpenSearch integration work (toggle stubbed, not built out).
- CI/CD and GitOps (ArgoCD/Flux) — can follow later.
