# jobstrainer on Kubernetes — Phase 3: Helm Packaging

## 1. Goal

Convert the plain `deploy/k8s/*.yaml` manifests into a Helm chart so the whole
stack deploys with one command (`helm install`), parameterized per environment
by values files. Phase 3 of the build plan in `2026-07-07-k8s-scaling-design.md`
§8: "*Same deploy, one command*" — a pure repackaging with deploy-time
parameterization, no behavior changes.

Runs on the local **kind** cluster (`kind-jobstrainer`), taking over the
currently-running kubectl-managed stack without losing the merged Postgres data.

## 2. Scope decisions

- **Values files: `values.yaml` + `values-local.yaml` only.** Sensible defaults
  plus the kind overrides. `values-baremetal.yaml` / `values-eks.yaml` come in
  the phases that actually deploy there, written against real infrastructure
  (YAGNI).
- **Ingress: deferred.** Access stays exactly today's port-forwards
  (`svc/api 8000:8000`, `svc/frontend 3000:80`). The §7 two-host Ingress drags
  in an ingress controller, `/etc/hosts` entries, a frontend image rebuild
  (`VITE_API_URL`), and a CORS code change — none of which belong in a pure
  repackaging. It becomes its own later step.
- **Cutover: dump → replace → reattach** (see §5). Helm cannot adopt
  kubectl-created resources by default; we delete workloads but keep PVCs and
  reinstall under identical names.

## 3. Chart shape

```
deploy/helm/jobstrainer/
  Chart.yaml
  values.yaml                # defaults
  values-local.yaml          # kind: :local tags, IfNotPresent, small PVCs
  templates/
    postgres.yaml            # StatefulSet + Service
    opensearch.yaml          # StatefulSet + Service
    bootstrap-job.yaml       # Helm hook: pre-install,pre-upgrade
    api-deployment.yaml      # Deployment + Service (no replicas field)
    api-hpa.yaml
    worker-deployment.yaml
    ingestion-cronjob.yaml
    frontend-deployment.yaml # Deployment + Service
```

Per-template parameterization:

| Template | Values |
|---|---|
| postgres / opensearch | image tag, PVC storage size, resources |
| bootstrap-job | image; annotated `helm.sh/hook: pre-install,pre-upgrade`, `helm.sh/hook-delete-policy: before-hook-creation` — migrations/index/checkpointer run automatically on every install/upgrade (idempotent) |
| api | `image.repository`/`image.tag`, resources. **No `replicas`** — the HPA owns it |
| api-hpa | `hpa.minReplicas` (1), `hpa.maxReplicas` (4), `hpa.targetCPUUtilization` (70) |
| worker | image, resources. `replicas: 1` + `strategy: Recreate` stay **hardcoded** — the singleton is an invariant, not a knob |
| ingestion-cronjob | `ingestion.schedule` (`0 */2 * * *`), `ingestion.suspend` (false), `ingestion.activeDeadlineSeconds` (1800) — pausing becomes `--set ingestion.suspend=true` |
| frontend | image, resources |

Out of the chart, on purpose:

- **`loadtest-job.yaml`** stays a plain manifest in `deploy/k8s/` — it is a
  demo/ops tool, not part of the app deploy.
- **metrics-server** stays a documented manual bootstrap step — cluster
  infrastructure, not application.

## 4. Config & secrets — reference, don't recreate

The chart does **not** create or manage the secret. Every workload consumes
`envFrom` a secret whose name is a value (`existingSecret`, default
`jobstrainer-secrets`) — the "bring your own secret" pattern used by mainstream
charts.

Rationale (deliberate deviation from §7's templated Secret + ConfigMap):

- The in-cluster secret is the known-good, quote-fixed one. Re-templating it
  from `.env`-sourced values reintroduces the quoting landmine that broke 7 of
  12 values (Groq 401s, Serper 403s) for zero functional gain.
- Helm-managed secrets leak into release metadata (stored values).

The README keeps the two-step `kubectl create secret` prerequisite with the
quotes warning. The §7 Secret/ConfigMap *split* (non-secret config like
`OPENSEARCH_URL`, model names) is deferred until per-environment values
actually diverge.

## 5. Cutover procedure (dump, replace, reattach)

1. **Safety dump**: fresh `pg_dump` of k8s Postgres to
   `~/jobstrainer-data/dumps/` (joins the merge-era dumps).
2. **Suspend ingestion** so no CronJob fires mid-switch.
3. **Delete workloads, keep data**: `kubectl delete` the kubectl-managed
   Deployments, Services, StatefulSets, CronJob, and completed Jobs —
   **explicitly not the PVCs**. PVCs outlive their StatefulSets by design.
4. **`helm install jobstrainer deploy/helm/jobstrainer -f
   deploy/helm/jobstrainer/values-local.yaml`**: resource names are identical
   to today's, so `postgres-0` reattaches its existing PVC (same
   StatefulSet name + volumeClaimTemplate name ⇒ same PVC name). The bootstrap
   hook runs idempotently. Ingestion resumes via the chart (suspend=false
   default).
5. **Verify** (see §7).

Rollback: the step-1 dump + the Phase 1 manifests in git history.

## 6. Plain manifests & README

- After the chart is verified live, **delete `deploy/k8s/*.yaml` except
  `loadtest-job.yaml`**. Two sources of truth would drift; git history
  preserves Phase 1. Historical plans/specs referencing them stay untouched.
- **Rewrite `deploy/k8s/README.md`** around the Helm workflow: prerequisites
  (kind cluster + loaded images, secret creation with quotes warning,
  metrics-server), `helm install/upgrade/uninstall`, port-forward access, the
  HPA demo, and a "changing config" section (`--set`/values edit + `helm
  upgrade`).

## 7. Verification

- `helm lint` passes; `helm template ... | kubectl apply --dry-run=server -f -`
  is schema-clean.
- **Pre-cutover render diff**: `helm template` output diffed against the live
  kubectl manifests; differences must be only the intended parameterizations
  (names, labels, values plumbing) — a gate that catches accidental behavior
  changes while the old stack still runs.
- Post-install: Postgres counts (jobs, companies, users, applications) match
  pre-cutover; admin login works via the frontend; `kubectl get hpa api` shows
  a real percentage; the bootstrap hook Job completed; ingestion CronJob
  scheduled and unsuspended; port-forwards serve :8000/:3000.

## 8. Out of scope

- Ingress / hostname routing (own later step, likely with baremetal/cloud).
- `values-baremetal.yaml` / `values-eks.yaml`.
- Secret/ConfigMap split and templated secrets.
- Frontend image rebuild or CORS code changes.
- CloudNativePG or any operator adoption; KEDA; cluster autoscaling.
- Helm repository publishing / chart versioning discipline beyond `0.1.0`.
