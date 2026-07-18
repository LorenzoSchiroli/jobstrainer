# jobstrainer on Kubernetes — Phase 2: API Autoscaling (HPA)

## 1. Goal

Add horizontal autoscaling to the API so it scales out under load and back down
when idle, while every other service keeps its Phase 1 behaviour. This is Phase 2
of the layered build plan in `2026-07-07-k8s-scaling-design.md` §8 — it teaches
one concept (the Horizontal Pod Autoscaler) and leaves behind a sensible,
carry-forward autoscaling config rather than a throwaway demo.

Runs on the local **kind** cluster (`kind-jobstrainer`), same as Phase 1.

## 2. Why the API is the only HPA target

HPA fits a service only when it is **stateless** (any pod handles any request),
**horizontally scalable** (N identical copies add throughput with no
coordination), and **load-varies**. Only the API meets all three:

| Service | HPA? | Reason |
|---|---|---|
| **API** | ✅ | Stateless, CPU-bound (embedding + cross-encoder reranking), request-driven. |
| frontend | ❌ (skipped) | Stateless but near-idle nginx serving static files; an HPA would sit at 1 replica indefinitely. |
| worker | ❌ | Singleton by design (reconcile/retention loops mutate shared state); scaling needs leader election, not HPA. |
| Postgres | ❌ | Stateful; scales via read-replicas + an operator (CloudNativePG), not by bouncing pods. |
| OpenSearch | ❌ | Stateful/sharded; scaled by deliberate shard/node sizing. |
| ingestion | ❌ | Batch CronJob (currently suspended); event/queue-driven scaling is KEDA's job (Phase 5), not HPA. |

## 3. Components

### 3.1 metrics-server (the data source)

HPA reads pod CPU from metrics-server, which is not installed by default on kind.
Install the upstream manifest **with the kind-specific fix**: add
`--kubelet-insecure-tls` to the metrics-server container args. On kind, kubelet's
serving certificate is not signed by the cluster CA, so without this flag
metrics-server cannot scrape kubelets and reports CPU as `<unknown>` — the HPA
then never scales.

**Carry-forward note:** `--kubelet-insecure-tls` is a **kind-only** workaround.
Real clusters (EKS/GKE/bare metal with proper kubelet certs) must not use it; it
becomes a values toggle in the Helm phase.

### 3.2 HorizontalPodAutoscaler (`deploy/k8s/api-hpa.yaml`)

`autoscaling/v2` HPA targeting the `api` Deployment:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: api
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: api
  minReplicas: 1
  maxReplicas: 4
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

Bounds: **min 1 / max 4 @ 70% CPU utilization**, chosen to match the project's
`min 1` cost decision (`2026-07-07` §3/§6) while giving headroom to demonstrate
and absorb bursts. The API requests `250m` CPU, so 70% ≈ **175m average** is the
scale-up threshold; the pod limit is `1000m`, so a single pod can burst well past
its request under load — that burst is what pushes utilization over target and
triggers scale-up.

### 3.3 API Deployment change (`deploy/k8s/api-deployment.yaml`)

Remove the hardcoded `replicas: 1` field. When an HPA owns the replica count, a
Deployment must not also set `replicas` — otherwise each `kubectl apply` resets
it to 1 and fights the HPA. The API's `resources.requests.cpu: 250m` already
exists and is unchanged (it is the denominator for the utilization target).

### 3.4 Load harness — in-cluster k6 Job (`deploy/k8s/loadtest-job.yaml`)

A one-shot Kubernetes Job running a `k6` script that hits
`http://api:8000/jobs/search` via in-cluster Service DNS (no port-forward, no
local install). The script ramps virtual users in stages (e.g. 0→20→50 over a
couple of minutes, then down) so the step-ups (1→2→3 pods) and the scale-back to
1 are both visible. It POSTs a realistic `{cv_text, query}` body.

Chosen over a local `k6`/`hey` run because it is portable (identical on kind,
bare metal, cloud), needs nothing installed on the developer machine, and is a
reusable artifact that lives with the manifests.

**Prerequisite for the run (not the build):** `POST /jobs/search` step 1
(query-understanding) calls Groq. A **valid `GROQ_API_KEY`** must be present in
`jobstrainer-secrets` before running the load Job — otherwise every request fails
at step 1, generates no CPU load, and nothing scales. Building and applying all
Phase 2 manifests does **not** require the key; only the load run does. The key
rotation is deferred to run time.

### 3.5 Docs (`deploy/k8s/README.md`)

A new Phase 2 section: install metrics-server (with the kind flag), apply the
HPA, run the load Job, and watch scaling with `kubectl get hpa -w` /
`kubectl get pods -w`. Include the two carry-forward notes: `--kubelet-insecure-tls`
is kind-only, and `replicas` was removed from the API Deployment because the HPA
owns it.

## 4. How to run / observe (end state)

1. Ensure a valid `GROQ_API_KEY` is in `jobstrainer-secrets`.
2. `kubectl get hpa api -w` in one pane; `kubectl get pods -l app=api -w` in another.
3. `kubectl apply -f deploy/k8s/loadtest-job.yaml`.
4. Watch the API scale 1 → up to 4 as CPU crosses 70%, then back to 1 after the
   Job finishes and load drains (default HPA scale-down stabilization ~5 min).

## 5. Out of scope (Phase 2)

- Frontend HPA (near-idle; skipped deliberately).
- Custom/RPS metrics via prometheus-adapter (CPU utilization is sufficient here).
- Cluster/node autoscaling and scale-to-zero (Phases 5).
- Helm packaging of these manifests (Phase 3).
- Worker/Postgres/OpenSearch/ingestion scaling (wrong mechanism for each; see §2).
- Rotating the Groq key (a run-time prerequisite the operator handles, not a
  build task).

## 6. Files touched

| File | Change |
|---|---|
| `deploy/k8s/api-deployment.yaml` | Remove `replicas: 1` (HPA owns replica count). |
| `deploy/k8s/api-hpa.yaml` | New — the HorizontalPodAutoscaler. |
| `deploy/k8s/loadtest-job.yaml` | New — in-cluster k6 load Job. |
| `deploy/k8s/README.md` | New Phase 2 section + carry-forward notes. |
| metrics-server | Installed in-cluster by applying the upstream manifest, then patching `--kubelet-insecure-tls` onto the Deployment. Not vendored into the repo — the install/patch commands live in the README. (Revisit vendoring/pinning in the Helm phase.) |
