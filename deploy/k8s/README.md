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

    docker build -t jobstrainer-backend:local backend/
    docker build -t jobstrainer-ingestion:local ingestion/
    docker build -t jobstrainer-frontend:local frontend/
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
`POST /jobs/search`; needs a valid `GROQ_API_KEY` in the secret — requests fail
at query-understanding without it and produce no CPU load):

    kubectl apply -f deploy/k8s/loadtest-job.yaml

Replicas climb 1 → up to 4 past 70% CPU, then settle back to 1 a few minutes
after the load ends (~5 min scale-down stabilization). Clean up:

    kubectl delete -f deploy/k8s/loadtest-job.yaml
