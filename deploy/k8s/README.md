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

## 2. Postgres

    kubectl apply -f deploy/k8s/postgres.yaml
    kubectl wait --for=condition=ready pod -l app=postgres --timeout=120s

## 3. OpenSearch

    kubectl apply -f deploy/k8s/opensearch.yaml
    kubectl wait --for=condition=ready pod -l app=opensearch --timeout=180s

## 4. Secret

Requires the repo's `.env` file (see `CLAUDE.md` for required vars).

Due to kubectl version constraints, `--from-env-file` cannot be combined with
`--from-literal` in a single invocation. Create the secret in two steps:

    kubectl create secret generic jobstrainer-secrets \
      --from-env-file=.env

    kubectl patch secret jobstrainer-secrets \
      --type merge \
      -p '{"stringData":{"DATABASE_URL":"postgresql+asyncpg://postgres:postgres@postgres:5432/jobstrainer","OPENSEARCH_URL":"http://opensearch:9200","BACKEND_URL":"http://api:8000"}}'

To pick up `.env` changes: `kubectl delete secret jobstrainer-secrets` then re-run both commands above, then restart any running pods (`kubectl rollout restart deployment api worker`).

## 5. Bootstrap (migrations + OpenSearch index + checkpointer tables)

    kubectl apply -f deploy/k8s/bootstrap-job.yaml
    kubectl wait --for=condition=complete job/jobstrainer-bootstrap --timeout=180s

Job specs are immutable, so re-running bootstrap (e.g. after a new
migration) requires deleting the old Job first:

    kubectl delete job jobstrainer-bootstrap --ignore-not-found
    kubectl apply -f deploy/k8s/bootstrap-job.yaml

## 6. API

    kubectl apply -f deploy/k8s/api-deployment.yaml
    kubectl wait --for=condition=available deployment/api --timeout=120s
    kubectl port-forward svc/api 8000:8000 &
    curl http://localhost:8000/health   # {"status":"ok"}

## 7. Worker

    kubectl apply -f deploy/k8s/worker-deployment.yaml
    kubectl wait --for=condition=available deployment/worker --timeout=60s
    kubectl logs deployment/worker --tail=20   # no errors

## 8. Ingestion CronJob

    kubectl apply -f deploy/k8s/ingestion-cronjob.yaml

Scheduled to run every 2 hours, but **currently suspended** (`suspend: true` in
the manifest) because the scraper's external sources are unreliable. Re-enable
with:

    kubectl patch cronjob ingestion -p '{"spec":{"suspend":false}}'

(also flip `suspend: false` in the manifest to keep them in sync). A slow run
self-terminates after `activeDeadlineSeconds: 1800` so it can't wedge the
`concurrencyPolicy: Forbid` lock. To trigger one run immediately (e.g. to
verify the pod spec without waiting):

    kubectl create job --from=cronjob/ingestion ingestion-manual-test
    kubectl wait --for=condition=complete job/ingestion-manual-test --timeout=600s
    kubectl logs job/ingestion-manual-test
    kubectl delete job ingestion-manual-test

## 9. Frontend

    kubectl apply -f deploy/k8s/frontend-deployment.yaml
    kubectl wait --for=condition=available deployment/frontend --timeout=60s

## Full stack access

    kubectl port-forward svc/api 8000:8000 &
    kubectl port-forward svc/frontend 3000:80 &

Open http://localhost:3000 — this matches docker-compose's ports exactly, so
the frontend's baked-in VITE_API_URL and the backend's CORS allow-list both
work unchanged.

# Phase 2 — API autoscaling (HPA)

Adds a CPU-based HorizontalPodAutoscaler to the **API only** (min 1 / max 4 @
70% CPU). Other services are excluded on purpose: the frontend is near-idle, the
worker is a singleton, Postgres/OpenSearch are stateful, and ingestion is a batch
CronJob — none are HPA-shaped. See
`docs/superpowers/specs/2026-07-18-k8s-phase2-hpa-autoscaling-design.md`.

## 10. metrics-server

HPA reads pod CPU from metrics-server, which kind does not ship by default:

    kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
    kubectl patch deployment metrics-server -n kube-system --type='json' \
      -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'
    kubectl rollout status deployment metrics-server -n kube-system --timeout=120s

`--kubelet-insecure-tls` is a **kind-only** workaround (kind's kubelet serving
cert isn't signed by the cluster CA). Real clusters — EKS/GKE/bare metal — must
NOT use it. Verify metrics flow:

    kubectl top pods -l app=api

## 11. HPA

    kubectl apply -f deploy/k8s/api-hpa.yaml
    kubectl get hpa api

`TARGETS` should read `<N>%/70%` with a real number (not `<unknown>`). Note:
`replicas` was removed from `api-deployment.yaml` because the HPA owns the
replica count — never set both.

## 12. Watch it scale (load demo)

**Prerequisite:** a valid `GROQ_API_KEY` must be in `jobstrainer-secrets`.
`POST /jobs/search` calls Groq for query-understanding *first*; with a dead key
every request fails before the CPU-heavy reranking stage, so no load is produced
and nothing scales.

In two panes:

    kubectl get hpa api -w
    kubectl get pods -l app=api -w

Then start the in-cluster k6 load Job (ramps 0→20→50 virtual users against
`http://api:8000/jobs/search`):

    kubectl apply -f deploy/k8s/loadtest-job.yaml

Watch replicas climb 1 → up to 4 as CPU crosses 70%, then settle back to 1 a few
minutes after the Job finishes (HPA scale-down stabilization ~5 min). Inspect and
clean up:

    kubectl logs -l job-name=api-loadtest -f
    kubectl delete -f deploy/k8s/loadtest-job.yaml
