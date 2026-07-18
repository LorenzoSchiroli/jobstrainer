# K8s Phase 3 — Helm Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert `deploy/k8s/*.yaml` into a Helm chart (`deploy/helm/jobstrainer/`), then cut the running kind cluster over to it without losing the Postgres data.

**Architecture:** Pure repackaging — templates are the existing manifests with minimal `{{ }}` substitutions, identical resource names/selectors so the Postgres StatefulSet reattaches its existing PVC (`data-postgres-0`). Bootstrap Job becomes a pre-install/pre-upgrade hook. Secret is referenced by name, never created by the chart.

**Tech Stack:** Helm 3, Kubernetes (kind), kubectl.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-18-k8s-phase3-helm-design.md`.
- Resource **names, labels, and selectors must match the live kubectl-managed resources exactly** (`postgres`, `opensearch`, `api`, `worker`, `frontend`, `ingestion`, `app:` labels) — PVC reattachment and port-forward/README continuity depend on it.
- The chart must NOT create a Secret. All workloads `envFrom` the secret named by `.Values.existingSecret` (default `jobstrainer-secrets`).
- API Deployment has **no `replicas` field** (HPA owns it). Worker keeps hardcoded `replicas: 1` + `strategy: Recreate`.
- HPA values: min 1 / max 4 / 70% CPU.
- Ingestion values: schedule `0 */2 * * *`, suspend false, activeDeadlineSeconds 1800, `concurrencyPolicy: Forbid`, `backoffLimit: 1`, command uses `$(OFFER_QUERY)`.
- `loadtest-job.yaml` stays a plain manifest in `deploy/k8s/`; metrics-server stays manual.
- No Ingress. No values-baremetal/eks.
- Commits: no Co-Authored-By trailer.

## File Structure

```
deploy/helm/jobstrainer/
  Chart.yaml
  values.yaml           # defaults (generic tags)
  values-local.yaml     # kind: :local tags + IfNotPresent
  templates/
    postgres.yaml  opensearch.yaml  bootstrap-job.yaml
    api-deployment.yaml  api-hpa.yaml  worker-deployment.yaml
    ingestion-cronjob.yaml  frontend-deployment.yaml
```

---

### Task 1: Helm install + chart scaffold

**Files:**
- Create: `deploy/helm/jobstrainer/Chart.yaml`
- Create: `deploy/helm/jobstrainer/values.yaml`
- Create: `deploy/helm/jobstrainer/values-local.yaml`

**Interfaces:**
- Produces: the values keys every template in Tasks 2–3 consumes (exact names below).

- [ ] **Step 1: Install helm**

```bash
brew install helm
helm version --short
```
Expected: `v3.x.y+...`

- [ ] **Step 2: Chart.yaml**

```yaml
apiVersion: v2
name: jobstrainer
description: Job search ranking system - API, worker, ingestion, frontend, Postgres, OpenSearch
type: application
version: 0.1.0
appVersion: "0.1.0"
```

- [ ] **Step 3: values.yaml**

```yaml
# Name of a pre-created Secret consumed via envFrom by api, worker, bootstrap,
# and ingestion. The chart never creates or manages it (see design §4).
existingSecret: jobstrainer-secrets

imagePullPolicy: IfNotPresent

postgres:
  image: postgres:16
  storage: 1Gi
  user: postgres
  password: postgres
  db: jobstrainer
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 500m
      memory: 512Mi

opensearch:
  image: opensearchproject/opensearch:2
  storage: 2Gi
  javaOpts: "-Xms512m -Xmx512m"
  resources:
    requests:
      cpu: 250m
      memory: 512Mi
    limits:
      cpu: 1000m
      memory: 1Gi

bootstrap:
  image:
    repository: jobstrainer-backend
    tag: latest
  resources:
    requests:
      cpu: 100m
      memory: 256Mi
    limits:
      cpu: 500m
      memory: 512Mi

api:
  image:
    repository: jobstrainer-backend
    tag: latest
  resources:
    requests:
      cpu: 250m
      memory: 512Mi
    limits:
      cpu: 1000m
      memory: 1536Mi

hpa:
  minReplicas: 1
  maxReplicas: 4
  targetCPUUtilization: 70

worker:
  image:
    repository: jobstrainer-backend
    tag: latest
  resources:
    requests:
      cpu: 50m
      memory: 128Mi
    limits:
      cpu: 300m
      memory: 256Mi

ingestion:
  image:
    repository: jobstrainer-ingestion
    tag: latest
  schedule: "0 */2 * * *"
  suspend: false
  activeDeadlineSeconds: 1800
  resources:
    requests:
      cpu: 500m
      memory: 1Gi
    limits:
      cpu: 1500m
      memory: 2Gi

frontend:
  image:
    repository: jobstrainer-frontend
    tag: latest
  resources:
    requests:
      cpu: 25m
      memory: 32Mi
    limits:
      cpu: 200m
      memory: 128Mi
```

- [ ] **Step 4: values-local.yaml** (kind overrides only)

```yaml
# kind: images are side-loaded (`kind load docker-image`), tagged :local
bootstrap:
  image:
    tag: local
api:
  image:
    tag: local
worker:
  image:
    tag: local
ingestion:
  image:
    tag: local
frontend:
  image:
    tag: local
```

- [ ] **Step 5: Lint the scaffold (no templates yet — must pass)**

```bash
helm lint deploy/helm/jobstrainer -f deploy/helm/jobstrainer/values-local.yaml
```
Expected: `1 chart(s) linted, 0 chart(s) failed` (info about missing templates dir is fine at this stage; if lint errors on the empty chart, create `templates/` with `mkdir -p deploy/helm/jobstrainer/templates` and rerun).

- [ ] **Step 6: Commit**

```bash
git add deploy/helm/jobstrainer
git commit -m "feat(helm): chart scaffold with values and local overrides"
```

---

### Task 2: Stateful templates + bootstrap hook

**Files:**
- Create: `deploy/helm/jobstrainer/templates/postgres.yaml`
- Create: `deploy/helm/jobstrainer/templates/opensearch.yaml`
- Create: `deploy/helm/jobstrainer/templates/bootstrap-job.yaml`

**Interfaces:**
- Consumes: `.Values.postgres.*`, `.Values.opensearch.*`, `.Values.bootstrap.*`, `.Values.existingSecret`, `.Values.imagePullPolicy` from Task 1.
- Produces: Services `postgres:5432`, `opensearch:9200` (DNS names other workloads use).

- [ ] **Step 1: templates/postgres.yaml** — StatefulSet name `postgres`, volumeClaimTemplate `data` (⇒ PVC `data-postgres-0`, matching the live one):

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
        image: {{ .Values.postgres.image }}
        env:
        - name: POSTGRES_USER
          value: {{ .Values.postgres.user }}
        - name: POSTGRES_PASSWORD
          value: {{ .Values.postgres.password }}
        - name: POSTGRES_DB
          value: {{ .Values.postgres.db }}
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
          {{- toYaml .Values.postgres.resources | nindent 10 }}
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: {{ .Values.postgres.storage }}
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

- [ ] **Step 2: templates/opensearch.yaml** — same pattern:

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
        image: {{ .Values.opensearch.image }}
        env:
        - name: discovery.type
          value: single-node
        - name: DISABLE_SECURITY_PLUGIN
          value: "true"
        - name: OPENSEARCH_JAVA_OPTS
          value: {{ .Values.opensearch.javaOpts | quote }}
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
          {{- toYaml .Values.opensearch.resources | nindent 10 }}
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: {{ .Values.opensearch.storage }}
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

- [ ] **Step 3: templates/bootstrap-job.yaml** — now a Helm hook (design §3):

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: jobstrainer-bootstrap
  annotations:
    helm.sh/hook: pre-install,pre-upgrade
    helm.sh/hook-delete-policy: before-hook-creation
spec:
  backoffLimit: 3
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: bootstrap
        image: {{ .Values.bootstrap.image.repository }}:{{ .Values.bootstrap.image.tag }}
        imagePullPolicy: {{ .Values.imagePullPolicy }}
        command: ["sh", "-c", "uv run alembic upgrade head && uv run python -m backend.bootstrap"]
        envFrom:
        - secretRef:
            name: {{ .Values.existingSecret }}
        resources:
          {{- toYaml .Values.bootstrap.resources | nindent 10 }}
```

Note the hook caveat: pre-install hooks run **before** postgres/opensearch exist on a *fresh* cluster; `backoffLimit: 3` + our cutover order (PVC/stores already up) make this a non-issue for the cutover. On a fresh cluster the Job retries while stores start. Document in README (Task 5).

- [ ] **Step 4: Render-check just these templates**

```bash
helm template jobstrainer deploy/helm/jobstrainer -f deploy/helm/jobstrainer/values-local.yaml --show-only templates/postgres.yaml
helm template jobstrainer deploy/helm/jobstrainer -f deploy/helm/jobstrainer/values-local.yaml --show-only templates/bootstrap-job.yaml
```
Expected: valid YAML; postgres image `postgres:16`, storage `1Gi`; bootstrap image `jobstrainer-backend:local`, hook annotations present.

- [ ] **Step 5: Commit**

```bash
git add deploy/helm/jobstrainer/templates
git commit -m "feat(helm): postgres/opensearch statefulsets and bootstrap hook job"
```

---

### Task 3: Workload templates

**Files:**
- Create: `deploy/helm/jobstrainer/templates/api-deployment.yaml`
- Create: `deploy/helm/jobstrainer/templates/api-hpa.yaml`
- Create: `deploy/helm/jobstrainer/templates/worker-deployment.yaml`
- Create: `deploy/helm/jobstrainer/templates/ingestion-cronjob.yaml`
- Create: `deploy/helm/jobstrainer/templates/frontend-deployment.yaml`

**Interfaces:**
- Consumes: `.Values.api/worker/ingestion/frontend/hpa`, `.Values.existingSecret`, `.Values.imagePullPolicy`.
- Produces: Services `api:8000`, `frontend:80` (port-forward targets in README).

- [ ] **Step 1: templates/api-deployment.yaml** (no `replicas` — HPA owns it):

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
spec:
  # replicas intentionally omitted: the HPA owns the replica count.
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
        image: {{ .Values.api.image.repository }}:{{ .Values.api.image.tag }}
        imagePullPolicy: {{ .Values.imagePullPolicy }}
        command: ["uv", "run", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
        envFrom:
        - secretRef:
            name: {{ .Values.existingSecret }}
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
          {{- toYaml .Values.api.resources | nindent 10 }}
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

- [ ] **Step 2: templates/api-hpa.yaml**:

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
  minReplicas: {{ .Values.hpa.minReplicas }}
  maxReplicas: {{ .Values.hpa.maxReplicas }}
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: {{ .Values.hpa.targetCPUUtilization }}
```

- [ ] **Step 3: templates/worker-deployment.yaml** (singleton stays hardcoded):

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
        image: {{ .Values.worker.image.repository }}:{{ .Values.worker.image.tag }}
        imagePullPolicy: {{ .Values.imagePullPolicy }}
        command: ["uv", "run", "python", "-m", "backend.worker"]
        envFrom:
        - secretRef:
            name: {{ .Values.existingSecret }}
        resources:
          {{- toYaml .Values.worker.resources | nindent 10 }}
```

- [ ] **Step 4: templates/ingestion-cronjob.yaml**:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: ingestion
spec:
  schedule: {{ .Values.ingestion.schedule | quote }}
  concurrencyPolicy: Forbid
  suspend: {{ .Values.ingestion.suspend }}
  jobTemplate:
    spec:
      backoffLimit: 1
      activeDeadlineSeconds: {{ .Values.ingestion.activeDeadlineSeconds }}
      template:
        spec:
          restartPolicy: OnFailure
          containers:
          - name: ingestion
            image: {{ .Values.ingestion.image.repository }}:{{ .Values.ingestion.image.tag }}
            imagePullPolicy: {{ .Values.imagePullPolicy }}
            command: ["uv", "run", "python", "-m", "ingestion.pipeline", "$(OFFER_QUERY)", "--hours", "2"]
            envFrom:
            - secretRef:
                name: {{ .Values.existingSecret }}
            resources:
              {{- toYaml .Values.ingestion.resources | nindent 14 }}
```

- [ ] **Step 5: templates/frontend-deployment.yaml**:

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
        image: {{ .Values.frontend.image.repository }}:{{ .Values.frontend.image.tag }}
        imagePullPolicy: {{ .Values.imagePullPolicy }}
        ports:
        - containerPort: 80
        resources:
          {{- toYaml .Values.frontend.resources | nindent 10 }}
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

- [ ] **Step 6: Full lint + server dry-run**

```bash
helm lint deploy/helm/jobstrainer -f deploy/helm/jobstrainer/values-local.yaml
helm template jobstrainer deploy/helm/jobstrainer -f deploy/helm/jobstrainer/values-local.yaml | kubectl apply --dry-run=server -f -
```
Expected: lint 0 failed; dry-run lists every resource as created/configured (server dry run), no schema errors. (Hook Job appears in template output too — dry-run "created" for it is fine; existing live resources show "configured".)

- [ ] **Step 7: Commit**

```bash
git add deploy/helm/jobstrainer/templates
git commit -m "feat(helm): api+hpa, worker, ingestion, frontend templates"
```

---

### Task 4: Render diff gate (pre-cutover)

**Files:** none (verification gate).

- [ ] **Step 1: Diff rendered chart vs live cluster state**

For each of: statefulset/postgres, statefulset/opensearch, deployment/api, deployment/worker, deployment/frontend, cronjob/ingestion, hpa/api, service/postgres, service/opensearch, service/api, service/frontend:

```bash
helm template jobstrainer deploy/helm/jobstrainer -f deploy/helm/jobstrainer/values-local.yaml > /tmp/rendered.yaml  # scratchpad ok
kubectl diff -f /tmp/rendered.yaml; echo "kubectl diff exit: $?"
```
Expected: exit 0 (no differences) or exit 1 with **only** cosmetic/intended diffs (e.g. comment lines, the bootstrap Job hook annotations, missing server-defaulted fields). Any *behavioral* diff (image, command, env, ports, probes, resources, schedule, storage) is a template bug — fix the template, not the manifest, and rerun.

- [ ] **Step 2: Record the diff summary in the commit message**

```bash
git commit --allow-empty -m "chore(helm): render diff gate passed against live cluster"
```

---

### Task 5: Cutover + cleanup + README

**Files:**
- Delete: `deploy/k8s/postgres.yaml`, `opensearch.yaml`, `bootstrap-job.yaml`, `api-deployment.yaml`, `api-hpa.yaml`, `worker-deployment.yaml`, `ingestion-cronjob.yaml`, `frontend-deployment.yaml`
- Keep: `deploy/k8s/loadtest-job.yaml`
- Rewrite: `deploy/k8s/README.md`

- [ ] **Step 1: Safety dump**

```bash
kubectl exec postgres-0 -- pg_dump -U postgres -Fc jobstrainer > ~/jobstrainer-data/dumps/pre-helm-$(date +%Y%m%d).dump
ls -lh ~/jobstrainer-data/dumps/
```
Expected: new dump file, size ~25M+.

- [ ] **Step 2: Record pre-cutover counts**

```bash
kubectl exec postgres-0 -- psql -U postgres -d jobstrainer -t -c \
  "SELECT (SELECT count(*) FROM jobs), (SELECT count(*) FROM companies), (SELECT count(*) FROM users), (SELECT count(*) FROM applications);"
```
Save the four numbers for Step 7.

- [ ] **Step 3: Suspend ingestion + wait out any active run**

```bash
kubectl patch cronjob ingestion -p '{"spec":{"suspend":true}}'
kubectl get jobs | grep -i ingestion   # if a run is Active, wait or delete it
```

- [ ] **Step 4: Delete workloads, KEEP PVCs**

```bash
kubectl delete deployment api worker frontend
kubectl delete statefulset postgres opensearch
kubectl delete service api frontend postgres opensearch
kubectl delete cronjob ingestion
kubectl delete hpa api
kubectl delete job --all   # completed bootstrap/ingestion jobs
kubectl get pvc            # MUST still list data-postgres-0 and data-opensearch-0
```
Expected: final line shows both PVCs `Bound`.

- [ ] **Step 5: Helm install**

```bash
helm install jobstrainer deploy/helm/jobstrainer -f deploy/helm/jobstrainer/values-local.yaml
kubectl rollout status statefulset/postgres --timeout=180s
kubectl rollout status statefulset/opensearch --timeout=300s
kubectl rollout status deployment/api --timeout=300s
kubectl rollout status deployment/worker --timeout=120s
kubectl rollout status deployment/frontend --timeout=120s
```
Expected: hook Job `jobstrainer-bootstrap` completes (it may retry while postgres starts — that's the backoffLimit working), then all rollouts succeed.

- [ ] **Step 6: Verify Helm owns the stack**

```bash
helm list
kubectl get all
kubectl get hpa api
```
Expected: release `jobstrainer` deployed; pods running; HPA shows a real percentage (not `<unknown>`).

- [ ] **Step 7: Verify data survived (counts match Step 2)**

```bash
kubectl exec postgres-0 -- psql -U postgres -d jobstrainer -t -c \
  "SELECT (SELECT count(*) FROM jobs), (SELECT count(*) FROM companies), (SELECT count(*) FROM users), (SELECT count(*) FROM applications);"
```
Expected: identical four numbers. Then restart port-forwards and check endpoints:

```bash
pkill -f "port-forward svc/api"; pkill -f "port-forward svc/frontend"; sleep 1
nohup kubectl port-forward svc/api 8000:8000 >/dev/null 2>&1 &
nohup kubectl port-forward svc/frontend 3000:80 >/dev/null 2>&1 &
sleep 2
curl -s -o /dev/null -w "api %{http_code}\n" http://localhost:8000/health
curl -s -o /dev/null -w "frontend %{http_code}\n" http://localhost:3000
```
Expected: `api 200`, `frontend 200`.

- [ ] **Step 8: Delete plain manifests (keep loadtest), rewrite README**

```bash
git rm deploy/k8s/postgres.yaml deploy/k8s/opensearch.yaml deploy/k8s/bootstrap-job.yaml \
       deploy/k8s/api-deployment.yaml deploy/k8s/api-hpa.yaml deploy/k8s/worker-deployment.yaml \
       deploy/k8s/ingestion-cronjob.yaml deploy/k8s/frontend-deployment.yaml
```

Rewrite `deploy/k8s/README.md` with sections: (1) Prerequisites — kind cluster, `docker build` + `kind load docker-image` for the three `:local` images, secret creation (two-step create+patch, **quotes warning kept verbatim**), metrics-server install (kind-only TLS flag note); (2) Deploy — `helm install jobstrainer deploy/helm/jobstrainer -f deploy/helm/jobstrainer/values-local.yaml`; upgrade — `helm upgrade` same args; uninstall — `helm uninstall jobstrainer` (note: PVCs survive uninstall); fresh-cluster note — bootstrap hook retries while stores start; (3) Access — the two port-forwards + localhost:3000; (4) Changing config — edit values / `--set` (example: `--set ingestion.suspend=true`) + `helm upgrade`; (5) HPA load demo — unchanged instructions pointing at `deploy/k8s/loadtest-job.yaml`.

- [ ] **Step 9: Final commit**

```bash
git add deploy/k8s deploy/helm
git commit -m "feat(helm): cut cluster over to Helm chart; retire plain manifests"
```

---

## Self-Review

**Spec coverage:** chart shape+params (§3→T1–T3), hook (§3→T2), existingSecret (§4→T1–T3), cutover dump/replace/reattach (§5→T5), manifest deletion + README (§6→T5), verification incl. render diff (§7→T3 S6, T4, T5 S6–7), out-of-scope respected (no ingress/extra values files/secret templating). ✅

**Placeholders:** none — every template/command is literal. ✅

**Name consistency:** values keys in T1 match every `{{ .Values.* }}` reference in T2–T3 (`postgres.user/password/db/storage/image/resources`, `opensearch.javaOpts/...`, `*.image.repository/tag`, `hpa.minReplicas/maxReplicas/targetCPUUtilization`, `ingestion.schedule/suspend/activeDeadlineSeconds`, `existingSecret`, `imagePullPolicy`). Resource names match live cluster (`postgres`, `opensearch`, `api`, `worker`, `frontend`, `ingestion`, `jobstrainer-bootstrap`). ✅
