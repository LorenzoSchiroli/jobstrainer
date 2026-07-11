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

    kubectl create secret generic jobstrainer-secrets \
      --from-env-file=.env \
      --from-literal=DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/jobstrainer \
      --from-literal=OPENSEARCH_URL=http://opensearch:9200 \
      --from-literal=BACKEND_URL=http://api:8000

To pick up `.env` changes: `kubectl delete secret jobstrainer-secrets` then re-run the command above, then restart any running pods (`kubectl rollout restart deployment api worker`).
