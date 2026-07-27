# jobstrainer on Kubernetes (Helm)

The stack deploys as a single Helm chart: `deploy/helm/jobstrainer/`. The plain
manifests that previously lived here (Phase 1) were retired after the chart
took over; see git history and
`docs/superpowers/specs/2026-07-18-k8s-phase3-helm-design.md`. Only
`loadtest-job.yaml` (a demo/ops tool, not part of the app deploy) remains as a
plain manifest.

## 1. Prerequisites

### Cluster + images

    kind create cluster --name jobstrainer

    docker build -f backend/Dockerfile -t jobstrainer-backend:local .
    docker build -f ingestion/Dockerfile -t jobstrainer-ingestion:local .
    docker build -f frontend/Dockerfile \
      --build-arg VITE_API_URL=http://localhost:8000 \
      -t jobstrainer-frontend:local ./frontend
    kind load docker-image jobstrainer-backend:local jobstrainer-ingestion:local jobstrainer-frontend:local --name jobstrainer

### Secret

The chart does **not** create the secret — it references one by name
(`existingSecret`, default `jobstrainer-secrets`). Create it from the repo's
`.env` before installing.

> **Warning — no quotes in `.env` values.** `kubectl create secret
> --from-env-file` stores values **verbatim**: unlike docker-compose/dotenv it
> does NOT strip surrounding quotes. `GROQ_API_KEY="gsk_..."` becomes the
> literal value `"gsk_..."` (quotes included) and Groq rejects it with
> `401 invalid_api_key` — same for every other quoted value. Write
> `GROQ_API_KEY=gsk_...` unquoted, or strip quotes before creating the secret.

Due to kubectl version constraints, `--from-env-file` cannot be combined with
`--from-literal` in a single invocation. Create the secret in two steps:

    kubectl create secret generic jobstrainer-secrets \
      --from-env-file=.env

    kubectl patch secret jobstrainer-secrets \
      --type merge \
      -p '{"stringData":{"DATABASE_URL":"postgresql+asyncpg://postgres:postgres@postgres:5432/jobstrainer","OPENSEARCH_URL":"http://opensearch:9200","BACKEND_URL":"http://api:8000"}}'

To pick up `.env` changes: `kubectl delete secret jobstrainer-secrets`, re-run
both commands, then `kubectl rollout restart deployment api worker`.

### metrics-server (required by the API HPA)

    kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
    kubectl patch deployment metrics-server -n kube-system --type='json' \
      -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'
    kubectl rollout status deployment metrics-server -n kube-system --timeout=120s

`--kubelet-insecure-tls` is a **kind-only** workaround (kind's kubelet serving
cert isn't signed by the cluster CA). Real clusters — EKS/GKE/bare metal — must
NOT use it.

## 2. Deploy

    helm install jobstrainer deploy/helm/jobstrainer -f deploy/helm/jobstrainer/values-local.yaml

The `jobstrainer-bootstrap` post-install hook runs migrations, creates the
OpenSearch index, and sets up checkpointer tables automatically. On a fresh
cluster its first attempts may crash while Postgres/OpenSearch are still
starting — that is the `backoffLimit: 6` retry budget working, not a problem.

Upgrade after chart/values changes (the bootstrap hook re-runs pre-upgrade, so
migrations apply before new code rolls out):

    helm upgrade jobstrainer deploy/helm/jobstrainer -f deploy/helm/jobstrainer/values-local.yaml

Uninstall (PVCs — and therefore all Postgres/OpenSearch data — survive):

    helm uninstall jobstrainer

## 3. Access

    kubectl port-forward svc/api 8000:8000 &
    kubectl port-forward svc/frontend 3000:80 &

Open http://localhost:3000 — matches docker-compose's ports, so the frontend's
baked-in VITE_API_URL and the backend's CORS allow-list work unchanged.

## 4. Changing config

Edit `values.yaml` / `values-local.yaml` (or use `--set`) and `helm upgrade`.
Examples:

    # pause ingestion
    helm upgrade jobstrainer deploy/helm/jobstrainer \
      -f deploy/helm/jobstrainer/values-local.yaml --set ingestion.suspend=true

    # widen the HPA ceiling
    helm upgrade jobstrainer deploy/helm/jobstrainer \
      -f deploy/helm/jobstrainer/values-local.yaml --set hpa.maxReplicas=6

Notable values: `existingSecret`, `hpa.minReplicas/maxReplicas/targetCPUUtilization`,
`ingestion.schedule/suspend/activeDeadlineSeconds`, per-service `image.repository/tag`
and `resources`, `postgres.storage`, `opensearch.storage`.

## 5. HPA load demo

Watch in two panes:

    kubectl get hpa api -w
    kubectl get pods -l app=api -w

Fire the in-cluster k6 load Job (ramps 0→20→50 virtual users against
`POST /jobs/search`). Base search is LLM-free — regex query parsing, then
embedding + cross-encoder reranking supply the CPU load — so no Groq quota is
consumed. The script registers a throwaway `loadtest-*` user for the JWT the
endpoint requires:

    kubectl apply -f deploy/k8s/loadtest-job.yaml

Replicas climb 1 → up to 4 past 70% CPU, then settle back to 1 a few minutes
after the load ends (~5 min scale-down stabilization). Clean up:

    kubectl delete -f deploy/k8s/loadtest-job.yaml

## Hetzner ARM64 images

Build and push images from the repository root. Replace `OWNER`, `TAG`, and
`api.example.com` before running these commands:

    docker login ghcr.io

    docker buildx build --platform linux/arm64 \
      -f backend/Dockerfile \
      -t ghcr.io/OWNER/jobstrainer-backend:TAG --push .

    docker buildx build --platform linux/arm64 \
      -f ingestion/Dockerfile \
      -t ghcr.io/OWNER/jobstrainer-ingestion:TAG --push .

    docker buildx build --platform linux/arm64 \
      -f frontend/Dockerfile \
      --build-arg VITE_API_URL=https://api.example.com \
      -t ghcr.io/OWNER/jobstrainer-frontend:TAG --push ./frontend

    docker buildx build --platform linux/arm64 \
      -f deploy/images/postgres-backup/Dockerfile \
      -t ghcr.io/OWNER/jobstrainer-postgres-backup:TAG \
      --push deploy/images/postgres-backup

The frontend API URL is embedded at build time. Rebuild the frontend image when
the public API hostname changes.

If packages under `ghcr.io/OWNER/` are private, create a pull secret and attach
it through `values-hetzner-private.yaml` (or make the packages public for the
portfolio demo). Public packages need no `imagePullSecrets`.
