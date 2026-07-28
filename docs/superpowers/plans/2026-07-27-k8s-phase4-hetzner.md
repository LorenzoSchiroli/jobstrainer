# K8s Phase 4 — Affordable Hetzner Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy jobstrainer on a single permanent ARM64 Hetzner k3s node with HTTPS, durable Postgres storage, seven rolling daily backups, and zero-idle-cost worker-node autoscaling while retaining local kind support.

**Architecture:** OpenTofu provisions a `kube-hetzner` k3s cluster with one schedulable CAX21 control-plane node and a zero-to-two CAX21 autoscaler pool. The existing Helm chart gains a Hetzner values profile for CSI storage, permanent/burst workload placement, Traefik ingress, cert-manager issuers, and Postgres backups. The API accepts a configured hosted CORS origin; the frontend is rebuilt with a public API URL.

**Tech Stack:** OpenTofu (>= 1.10.1), `kube-hetzner` v3.0.1, Hetzner Cloud (`hcloud` provider >= 1.62.0), Packer, k3s, Kubernetes Cluster Autoscaler, Helm 3+, Traefik, cert-manager, Cloudflare DNS, GHCR OCI images, PostgreSQL 16, rclone, Hetzner Storage Box, kubeconform.

## Global Constraints

- The idle deployment target is below €20/month including VAT, excluding domain registration and temporary burst nodes. Verify current Hetzner pricing before `tofu apply`.
- The permanent node and all autoscaled nodes use ARM64 CAX21 instances. Abort deployment and choose x86 if the ARM64 compatibility gate fails.
- The permanent CAX21 is intentionally a single point of failure; restoration from the Storage Box is the accepted recovery mechanism.
- The existing kind workflow and `values-local.yaml` must continue to render and deploy without ingress, backups, affinity, or explicit storage class changes. Diff the full local Helm render before and after chart edits; StatefulSet `volumeClaimTemplates` are immutable on upgrade.
- The chart continues to reference, never create, `jobstrainer-secrets`. Keep all tokens, credentials, private keys, kubeconfigs, state files, and `*.tfvars` out of Git.
- Postgres, OpenSearch, and the singleton worker (reconcile + retention + backup) run only on the permanent node. Ingestion runs only on the autoscaled burst pool. The API deployment carries no node affinity: overflow reaches burst nodes as an emergent result of resource pressure.
- The Hetzner profile lowers the ingestion schedule to once daily (`0 3 * * *`) so the required burst affinity does not boot a worker twelve times a day.
- Burst nodes keep a public IPv4 for image pulls and scraping. Do not disable autoscaler IPv4 unless a permanent NAT router is also provisioned. Public IPv6 stays disabled.
- Build an ARM Leap Micro (or MicroOS) Packer snapshot in the Hetzner project before the first `tofu apply`.
- The API HPA remains initially `minReplicas: 1`, `maxReplicas: 4`, CPU target 70%; load testing determines final requests and limits.
- The initial autoscaled pool is `min_nodes = 0`, `max_nodes = 2`.
- Cloudflare DNS records are DNS-only at first (`proxied = false`). Let’s Encrypt HTTP-01 challenges route through Traefik.
- Each Ingress hostname owns its own TLS Secret. Do not share one Secret across hosts.
- The Storage Box keeps exactly the seven newest successfully uploaded custom-format `pg_dump` backups. Prune by sorting filenames locally; fail loudly if retention fails.
- Storage Box SFTP uses port 23 and relative (no leading `/`) paths. Convert `DATABASE_URL` from SQLAlchemy (`postgresql+asyncpg://`) to a libpq URI before `pg_dump`.
- Postgres and OpenSearch stay cluster-internal (no Ingress). Chart credentials remain the kind defaults; that is accepted for this portfolio phase.
- Validate rendered manifests with `kubeconform`. Do not treat `kubectl apply --dry-run=client` as an offline schema check.
- Do not add KEDA, multi-node k3s HA, CloudNativePG, OpenSearch backups, CI/CD automation, or production Chrome-extension configuration.

---

## File Structure

```
deploy/
  infra/
    hetzner/
      README.md
      versions.tf
      providers.tf
      variables.tf
      main.tf
      dns.tf
      outputs.tf
      terraform.tfvars.example
  helm/jobstrainer/
    values-hetzner.yaml
    templates/
      _helpers.tpl
      ingress.yaml
      cert-manager-clusterissuers.yaml
      worker-deployment.yaml
  k8s/
    README.md
    loadtest-job-hetzner.yaml

backend/
  backend/
    backup.py
    scripts/postgres_backup.sh
    worker.py
  Dockerfile
```

> **Amendment (2026-07-28):** Postgres backup runs inside `backend.worker` (same
> image/Deployment as reconcile/retention). There is no separate
> `postgres-backup` image or Helm CronJob.
Existing application and Helm files modified by this plan:

- `.gitignore`
- `.env.example`
- `backend/backend/main.py`
- `backend/tests/test_cors.py` (new)
- `deploy/helm/jobstrainer/values.yaml`
- `deploy/helm/jobstrainer/templates/{postgres,opensearch,worker-deployment,ingestion-cronjob}.yaml`
- `deploy/k8s/README.md`
- `AGENTS.md`

---

### Task 1: Protect IaC and deployment credentials

**Files:**
- Modify: `.gitignore`
- Modify: `.env.example`
- Test: Git ignored-file checks

**Interfaces:**
- Consumes: existing `.env` / `jobstrainer-secrets` convention.
- Produces: a repository that ignores OpenTofu state, variable files, local kubeconfigs, Helm release artifacts, and Storage Box/rclone credentials; an `.env.example` whose values are safe for `kubectl --from-env-file`.

- [ ] **Step 1: Add IaC and local deployment artifacts to `.gitignore`**

Append:

```gitignore

# OpenTofu/Terraform local state and secret variable files
.terraform/
*.tfstate
*.tfstate.*
*.tfvars
*.tfvars.json
crash.log
crash.*.log
override.tf
override.tf.json
*_override.tf
*_override.tf.json

# Local kubeconfig and deployment secrets
kubeconfig*
.kube/
rclone.conf
values-hetzner-private.yaml
```

- [ ] **Step 2: Unquote `.env.example` and document non-secret deployment variables**

Replace the entire `.env.example` with:

```dotenv
GROQ_API_KEY=
GROQ_MODEL_LARGE=openai/gpt-oss-120b
GROQ_MODEL_BASE=qwen/qwen3-32b

# Adzuna API credentials — free tier at https://developer.adzuna.com/
ADZUNA_APP_ID=
ADZUNA_APP_KEY=

# Serper.dev
SERPERDEV_API_KEY=

OFFER_QUERY=machine learning engineer

SECRET_KEY=change-me-generate-with-python-secrets
ACCESS_TOKEN_EXPIRE_DAYS=7

# Comma-separated browser origins allowed by the API. Localhost remains allowed
# even when this is unset. Production example:
# CORS_ORIGINS=https://app.example.com
CORS_ORIGINS=

# Used by the singleton backend worker for nightly Postgres dumps to a
# Hetzner Storage Box. Create these values in the Kubernetes Secret; do not
# commit real Storage Box credentials. When unset, the worker skips backups.
BACKUP_SBOX_HOST=
BACKUP_SBOX_USER=
BACKUP_SBOX_PATH=backups/jobstrainer
# BACKUP_SBOX_RCLONE_PASS is the output of `rclone obscure <password>`.
# Generate it outside Git and store only the obscured value in the Secret.
# BACKUP_SBOX_RCLONE_PASS=
```

Keep values unquoted: `kubectl create secret --from-env-file` stores quotes verbatim.

- [ ] **Step 3: Verify sensitive deployment files are ignored**

Run:

```bash
git check-ignore -v \
  deploy/infra/hetzner/terraform.tfvars \
  deploy/infra/hetzner/terraform.tfstate \
  deploy/infra/hetzner/.terraform/providers \
  kubeconfig-jobstrainer \
  rclone.conf \
  values-hetzner-private.yaml
```

Expected: each path is reported with the matching `.gitignore` rule.

- [ ] **Step 4: Verify examples do not contain real credentials or quoted values**

Run:

```bash
grep -E 'HCLOUD_TOKEN=|CLOUDFLARE_API_TOKEN=|BACKUP_SBOX_RCLONE_PASS=[^#[:space:]]|gsk_[A-Za-z0-9]+' \
  .env.example deploy/infra/hetzner/terraform.tfvars.example 2>/dev/null || true

grep -E '^(GROQ_MODEL_|OFFER_QUERY=).*["'\'']' .env.example && exit 1 || true
```

Expected: no real token values and no quoted assignment values in `.env.example`.

- [ ] **Step 5: Commit the guardrails**

```bash
git add .gitignore .env.example
git commit -m "chore(deploy): ignore infrastructure state and document deployment variables"
```

---

### Task 2: Make browser CORS origins environment-driven

**Files:**
- Modify: `backend/backend/main.py`
- Create: `backend/tests/test_cors.py`
- Test: `backend/tests/test_cors.py`

**Interfaces:**
- Consumes: optional `CORS_ORIGINS` environment variable, as a comma-separated list.
- Produces: `cors_origins() -> list[str]`; the list always includes `http://localhost:3000`, deduplicates configured origins, and remains compatible with the existing Chrome-extension regex.

- [ ] **Step 1: Write failing CORS unit tests**

Create `backend/tests/test_cors.py`:

```python
from backend.main import cors_origins


def test_cors_origins_defaults_to_local_frontend(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)

    assert cors_origins() == ["http://localhost:3000"]


def test_cors_origins_adds_trimmed_configured_values(monkeypatch):
    monkeypatch.setenv(
        "CORS_ORIGINS",
        " https://app.example.com,https://preview.example.com ,",
    )

    assert cors_origins() == [
        "http://localhost:3000",
        "https://app.example.com",
        "https://preview.example.com",
    ]


def test_cors_origins_deduplicates_local_frontend(monkeypatch):
    monkeypatch.setenv(
        "CORS_ORIGINS",
        "http://localhost:3000,https://app.example.com,http://localhost:3000",
    )

    assert cors_origins() == [
        "http://localhost:3000",
        "https://app.example.com",
    ]
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd backend && uv run pytest tests/test_cors.py -v
```

Expected: collection fails because `cors_origins` is not importable.

- [ ] **Step 3: Implement `cors_origins` and wire it into CORS middleware**

In `backend/backend/main.py`, `os` is already imported. Place the helper directly above the FastAPI construction:

```python
def cors_origins() -> list[str]:
    origins = ["http://localhost:3000"]
    for origin in os.environ.get("CORS_ORIGINS", "").split(","):
        origin = origin.strip()
        if origin and origin not in origins:
            origins.append(origin)
    return origins
```

Replace:

```python
allow_origins=["http://localhost:3000"],
```

with:

```python
allow_origins=cors_origins(),
```

Keep `allow_origin_regex=r"chrome-extension://.*"` unchanged.

- [ ] **Step 4: Run focused and full backend tests**

Run:

```bash
cd backend && uv run pytest tests/test_cors.py -v
cd backend && uv run pytest -q
```

Expected: the focused tests pass; the full suite has no CORS/lifespan regressions.

- [ ] **Step 5: Commit the backwards-compatible CORS configuration**

```bash
git add backend/backend/main.py backend/tests/test_cors.py
git commit -m "feat(api): configure CORS origins from environment"
```

---

### Task 3: Add reusable Helm storage and scheduling primitives

**Files:**
- Create: `deploy/helm/jobstrainer/templates/_helpers.tpl`
- Modify: `deploy/helm/jobstrainer/values.yaml`
- Modify: `deploy/helm/jobstrainer/templates/postgres.yaml`
- Modify: `deploy/helm/jobstrainer/templates/opensearch.yaml`
- Modify: `deploy/helm/jobstrainer/templates/worker-deployment.yaml`
- Modify: `deploy/helm/jobstrainer/templates/ingestion-cronjob.yaml`
- Test: Helm rendering with local and Hetzner-like values

**Interfaces:**
- Consumes:
  - `.Values.storageClass` (`""` means omit `storageClassName`);
  - `.Values.postgres.pgdataSubdir` (`""` means omit `PGDATA`);
  - `.Values.opensearch.fsGroup` (`null` means omit `securityContext`);
  - `.Values.nodePools.<name>.labelKey` and `.labelValue`;
  - `.Values.scheduling.{postgres,opensearch,worker,ingestion}`.
- Produces:
  - `jobstrainer.storageClass` and `jobstrainer.nodeAffinity` helpers;
  - local rendering with no affinity/storage-class/`PGDATA`/`fsGroup` fields;
  - Hetzner-ready hooks for CSI, permanent affinity, Postgres subdirectory, and OpenSearch `fsGroup`.

- [ ] **Step 1: Capture the local render baseline before chart edits**

Run:

```bash
helm template jobstrainer deploy/helm/jobstrainer \
  -f deploy/helm/jobstrainer/values-local.yaml \
  > /tmp/jobstrainer-local-before.yaml
```

Expected: the file is written and contains Postgres/OpenSearch StatefulSets.

- [ ] **Step 2: Add default values that preserve local behavior**

Append to `deploy/helm/jobstrainer/values.yaml`:

```yaml
# Empty keeps the cluster default StorageClass, as used by local kind.
storageClass: ""

nodePools: {}

scheduling:
  postgres: ""
  opensearch: ""
  worker: ""
  ingestion: ""
```

Also extend the existing `postgres:` and `opensearch:` blocks (do not replace them) with:

```yaml
postgres:
  # ...existing keys unchanged...
  # Empty keeps the image default PGDATA. Set only for CSI volumes that
  # ship a non-empty root (lost+found); never set this on an already
  # initialized kind volume.
  pgdataSubdir: ""

opensearch:
  # ...existing keys unchanged...
  # null omits securityContext. Set to 1000 on CSI so the non-root
  # OpenSearch process can write the volume.
  fsGroup: null
```

- [ ] **Step 3: Add shared Helm helpers**

Create `deploy/helm/jobstrainer/templates/_helpers.tpl`:

```gotemplate
{{- define "jobstrainer.storageClass" -}}
{{- if .Values.storageClass }}
storageClassName: {{ .Values.storageClass | quote }}
{{- end }}
{{- end }}

{{- define "jobstrainer.nodeAffinity" -}}
{{- $poolName := .pool -}}
{{- $pool := index .root.Values.nodePools $poolName -}}
{{- if and $poolName $pool }}
nodeAffinity:
  requiredDuringSchedulingIgnoredDuringExecution:
    nodeSelectorTerms:
    - matchExpressions:
      - key: {{ $pool.labelKey | quote }}
        operator: In
        values:
        - {{ $pool.labelValue | quote }}
{{- end }}
{{- end }}
```

- [ ] **Step 4: Wire storage class, affinity, PGDATA, and fsGroup into workloads**

In `postgres.yaml`:

1. Under the PVC `spec:` (after `accessModes`), add:

```gotemplate
      {{- include "jobstrainer.storageClass" . | nindent 6 }}
```

2. Under the StatefulSet pod-template `spec:`, before `containers:`, add:

```gotemplate
      {{- $nodeContext := dict "root" . "pool" .Values.scheduling.postgres }}
      {{- with include "jobstrainer.nodeAffinity" $nodeContext }}
      affinity:
        {{- . | nindent 8 }}
      {{- end }}
```

3. Inside the postgres container `env:` list, add:

```gotemplate
        {{- if .Values.postgres.pgdataSubdir }}
        - name: PGDATA
          value: {{ printf "/var/lib/postgresql/data/%s" .Values.postgres.pgdataSubdir | quote }}
        {{- end }}
```

In `opensearch.yaml`:

1. Add the same storage-class include under the PVC `spec:`.
2. Under the StatefulSet pod-template `spec:`, before `containers:`, add:

```gotemplate
      {{- $nodeContext := dict "root" . "pool" .Values.scheduling.opensearch }}
      {{- with include "jobstrainer.nodeAffinity" $nodeContext }}
      affinity:
        {{- . | nindent 8 }}
      {{- end }}
      {{- if .Values.opensearch.fsGroup }}
      securityContext:
        fsGroup: {{ .Values.opensearch.fsGroup }}
      {{- end }}
```

In `worker-deployment.yaml`, insert the affinity block under the pod-template `spec:` using `.Values.scheduling.worker`.

In `ingestion-cronjob.yaml`, insert the affinity block under `jobTemplate.spec.template.spec:` using `.Values.scheduling.ingestion`.

Do **not** add affinity to the API deployment.

- [ ] **Step 5: Diff the local profile against the baseline**

Run:

```bash
helm lint deploy/helm/jobstrainer \
  -f deploy/helm/jobstrainer/values-local.yaml

helm template jobstrainer deploy/helm/jobstrainer \
  -f deploy/helm/jobstrainer/values-local.yaml \
  > /tmp/jobstrainer-local-after.yaml

diff -u /tmp/jobstrainer-local-before.yaml /tmp/jobstrainer-local-after.yaml
```

Expected: lint reports zero failed charts; `diff` is empty (no affinity, storageClassName, PGDATA, or fsGroup leaked into the local render).

- [ ] **Step 6: Commit the chart primitives**

```bash
git add deploy/helm/jobstrainer
git commit -m "feat(helm): add optional storage and node-pool scheduling"
```

---

### Task 4: Add the Hetzner Helm profile and public ingress

**Files:**
- Create: `deploy/helm/jobstrainer/values-hetzner.yaml`
- Create: `deploy/helm/jobstrainer/templates/ingress.yaml`
- Create: `deploy/helm/jobstrainer/templates/cert-manager-clusterissuers.yaml`
- Modify: `deploy/helm/jobstrainer/values.yaml`
- Test: Helm lint/template rendering and kubeconform

**Interfaces:**
- Consumes the node placement helpers from Task 3, a pre-installed Traefik ingress class, and cert-manager CRDs installed by `kube-hetzner`.
- Produces:
  - DNS-only Cloudflare-compatible HTTPS routes for `frontendHost` and `apiHost`;
  - distinct TLS Secrets per hostname;
  - `letsencrypt-staging` and `letsencrypt-prod` `ClusterIssuer` resources;
  - initial CAX21 / `hcloud-volumes` settings with no credential values.

- [ ] **Step 1: Add disabled ingress, certificate, and backup defaults**

Append to `deploy/helm/jobstrainer/values.yaml`:

```yaml
ingress:
  enabled: false
  className: traefik
  frontendHost: ""
  apiHost: ""
  frontendTlsSecretName: jobstrainer-frontend-tls
  apiTlsSecretName: jobstrainer-api-tls

certManager:
  createIssuers: false
  email: ""
  issuerName: letsencrypt-prod

backup:
  enabled: false
```

- [ ] **Step 2: Add the Hetzner environment profile**

Create `deploy/helm/jobstrainer/values-hetzner.yaml`:

```yaml
imagePullPolicy: Always
storageClass: hcloud-volumes

nodePools:
  permanent:
    labelKey: jobstrainer.io/node-pool
    labelValue: permanent
  burst:
    labelKey: jobstrainer.io/node-pool
    labelValue: burst

scheduling:
  postgres: permanent
  opensearch: permanent
  worker: permanent
  ingestion: burst

postgres:
  storage: 10Gi
  pgdataSubdir: pgdata

opensearch:
  storage: 20Gi
  javaOpts: "-Xms512m -Xmx512m"
  fsGroup: 1000

bootstrap:
  image:
    repository: ghcr.io/jobstrainer-demo/jobstrainer-backend
    tag: phase4-example

api:
  image:
    repository: ghcr.io/jobstrainer-demo/jobstrainer-backend
    tag: phase4-example

worker:
  image:
    repository: ghcr.io/jobstrainer-demo/jobstrainer-backend
    tag: phase4-example

ingestion:
  image:
    repository: ghcr.io/jobstrainer-demo/jobstrainer-ingestion
    tag: phase4-example
  # Daily rather than every two hours: burst affinity boots a CAX21 per run.
  schedule: "0 3 * * *"

frontend:
  image:
    repository: ghcr.io/jobstrainer-demo/jobstrainer-frontend
    tag: phase4-example

ingress:
  enabled: true
  className: traefik
  frontendHost: app.example.com
  apiHost: api.example.com
  frontendTlsSecretName: jobstrainer-frontend-tls
  apiTlsSecretName: jobstrainer-api-tls

certManager:
  createIssuers: true
  email: ops@example.com
  issuerName: letsencrypt-staging
```

`values-hetzner.yaml` is a safe, syntactically valid example profile. The
operator supplies actual registry references, immutable image tags, hostnames,
and the Let's Encrypt email through an ignored `values-hetzner-private.yaml`
passed after this file to Helm. If GHCR packages are private, that private
values file (or the cluster) must also supply `imagePullSecrets`; public GHCR
packages need none.

- [ ] **Step 3: Add a ClusterIssuer template**

Create `deploy/helm/jobstrainer/templates/cert-manager-clusterissuers.yaml`:

```gotemplate
{{- if .Values.certManager.createIssuers }}
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-staging
spec:
  acme:
    email: {{ .Values.certManager.email | quote }}
    server: https://acme-staging-v02.api.letsencrypt.org/directory
    privateKeySecretRef:
      name: letsencrypt-staging-account-key
    solvers:
    - http01:
        ingress:
          ingressClassName: {{ .Values.ingress.className | quote }}
---
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    email: {{ .Values.certManager.email | quote }}
    server: https://acme-v02.api.letsencrypt.org/directory
    privateKeySecretRef:
      name: letsencrypt-prod-account-key
    solvers:
    - http01:
        ingress:
          ingressClassName: {{ .Values.ingress.className | quote }}
{{- end }}
```

- [ ] **Step 4: Add dual-host Ingress routing with separate TLS secrets**

Create `deploy/helm/jobstrainer/templates/ingress.yaml`:

```gotemplate
{{- if .Values.ingress.enabled }}
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: frontend
  annotations:
    cert-manager.io/cluster-issuer: {{ .Values.certManager.issuerName | quote }}
spec:
  ingressClassName: {{ .Values.ingress.className | quote }}
  tls:
  - hosts:
    - {{ .Values.ingress.frontendHost | quote }}
    secretName: {{ .Values.ingress.frontendTlsSecretName | quote }}
  rules:
  - host: {{ .Values.ingress.frontendHost | quote }}
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: frontend
            port:
              number: 80
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: api
  annotations:
    cert-manager.io/cluster-issuer: {{ .Values.certManager.issuerName | quote }}
spec:
  ingressClassName: {{ .Values.ingress.className | quote }}
  tls:
  - hosts:
    - {{ .Values.ingress.apiHost | quote }}
    secretName: {{ .Values.ingress.apiTlsSecretName | quote }}
  rules:
  - host: {{ .Values.ingress.apiHost | quote }}
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: api
            port:
              number: 8000
{{- end }}
```

- [ ] **Step 5: Verify local and Hetzner render contracts**

Install kubeconform if missing (`brew install kubeconform`), then run:

```bash
helm lint deploy/helm/jobstrainer \
  -f deploy/helm/jobstrainer/values-local.yaml

helm template jobstrainer deploy/helm/jobstrainer \
  -f deploy/helm/jobstrainer/values-local.yaml \
  > /tmp/jobstrainer-local.yaml

helm template jobstrainer deploy/helm/jobstrainer \
  -f deploy/helm/jobstrainer/values.yaml \
  -f deploy/helm/jobstrainer/values-hetzner.yaml \
  > /tmp/jobstrainer-hetzner.yaml

grep -E 'kind: Ingress|kind: ClusterIssuer|storageClassName:|PGDATA|fsGroup:|jobstrainer.io/node-pool|jobstrainer-frontend-tls|jobstrainer-api-tls|schedule:' \
  /tmp/jobstrainer-hetzner.yaml

grep -E 'kind: Ingress|kind: ClusterIssuer|storageClassName:|PGDATA|fsGroup:|nodeAffinity:' \
  /tmp/jobstrainer-local.yaml && exit 1 || true

helm template jobstrainer deploy/helm/jobstrainer \
  -f deploy/helm/jobstrainer/values.yaml \
  -f deploy/helm/jobstrainer/values-hetzner.yaml \
  | kubeconform -strict -ignore-missing-schemas -summary
```

Expected:

- local render has none of those production fields;
- Hetzner render has two Ingresses, two ClusterIssuers, CSI storage classes, permanent affinity for Postgres/OpenSearch/worker, burst affinity for ingestion, distinct TLS secret names, `PGDATA`, `fsGroup: 1000`, and the daily ingestion schedule;
- kubeconform reports zero errors (`-ignore-missing-schemas` covers ClusterIssuer until CRDs are available offline).

- [ ] **Step 6: Commit the hosting profile and ingress**

```bash
git add deploy/helm/jobstrainer
git commit -m "feat(helm): add Hetzner ingress and node-pool profile"
```

---

### Task 5: Fold Postgres backup into the backend worker

> **Amendment (2026-07-28):** Prefer a worker loop over a separate image/CronJob
> so Hetzner deploy only needs one backend image push.

**Files:**
- Create: `backend/backend/backup.py`
- Create: `backend/backend/scripts/postgres_backup.sh`
- Create: `backend/tests/test_backup_worker.py`
- Modify: `backend/backend/worker.py`
- Modify: `backend/Dockerfile` (install `postgresql-client` + `rclone`)
- Modify: `deploy/helm/jobstrainer/templates/worker-deployment.yaml`
- Modify: `deploy/helm/jobstrainer/values.yaml` (`backup.intervalSeconds` only)
- Delete: `deploy/images/postgres-backup/`
- Delete: `deploy/helm/jobstrainer/templates/postgres-backup-cronjob.yaml`
- Test: `backend/tests/test_backup_worker.py`, `backend/tests/test_worker_entrypoint.py`

**Interfaces:**
- Consumes secret keys `DATABASE_URL`, `BACKUP_SBOX_HOST`, `BACKUP_SBOX_USER`, `BACKUP_SBOX_PATH`, and an rclone-obscured `BACKUP_SBOX_RCLONE_PASS`.
- Produces `backup_worker()` gathered beside reconcile/retention; skips when `BACKUP_SBOX_*` unset; retains exactly seven successful dumps.

- [x] **Step 1: Implement `backup_worker` + script in the backend image**
- [x] **Step 2: Remove separate postgres-backup image and CronJob**
- [x] **Step 3: Wire `BACKUP_INTERVAL_SECONDS` on the worker Deployment**
- [x] **Step 4: Update design/runbook/AGENTS**

Verify:

```bash
cd backend && uv run pytest tests/test_backup_worker.py tests/test_worker_entrypoint.py -v
bash -n backend/backend/scripts/postgres_backup.sh
helm template jobstrainer deploy/helm/jobstrainer \
  -f deploy/helm/jobstrainer/values.yaml \
  -f deploy/helm/jobstrainer/values-hetzner.yaml \
  --show-only templates/worker-deployment.yaml \
  | grep -E 'BACKUP_INTERVAL_SECONDS|backend.worker'
```

Expected: tests pass; worker render has the interval env; no `postgres-backup` CronJob template exists.

---

### Task 6: Add the Hetzner OpenTofu environment

**Files:**
- Create: `deploy/infra/hetzner/versions.tf`
- Create: `deploy/infra/hetzner/providers.tf`
- Create: `deploy/infra/hetzner/variables.tf`
- Create: `deploy/infra/hetzner/main.tf`
- Create: `deploy/infra/hetzner/dns.tf`
- Create: `deploy/infra/hetzner/outputs.tf`
- Create: `deploy/infra/hetzner/terraform.tfvars.example`
- Create: `deploy/infra/hetzner/README.md`
- Test: `tofu fmt`, `tofu init`, `tofu validate`, reviewed `tofu plan`

**Interfaces:**
- Consumes environment-only `HCLOUD_TOKEN` and `CLOUDFLARE_API_TOKEN`, a Cloudflare zone ID, public hostnames, and an SSH public-key path.
- Produces a k3s cluster through `kube-hetzner` v3.0.1:
  - one schedulable `cax21` permanent control-plane node labeled `jobstrainer.io/node-pool=permanent`;
  - `vm.max_map_count=262144` on that node for OpenSearch;
  - a `cax21` ARM autoscaler pool labeled `jobstrainer.io/node-pool=burst`, minimum zero, maximum two, public IPv4 enabled, public IPv6 disabled;
  - Traefik, cert-manager, metrics-server, Hetzner CSI, Klipper/ServiceLB on ports 80/443;
  - DNS-only Cloudflare A records for the frontend and API hostnames, using the module's `ingress_public_ipv4` output.

- [ ] **Step 1: Install toolchain floors if missing**

Run:

```bash
command -v tofu || brew install opentofu
command -v packer || brew install hashicorp/tap/packer
command -v hcloud || brew install hcloud
tofu version
packer version
```

Expected: OpenTofu reports >= 1.10.1; Packer and hcloud are present.

- [ ] **Step 2: Pin OpenTofu providers**

Create `deploy/infra/hetzner/versions.tf`:

```hcl
terraform {
  required_version = ">= 1.10.1"

  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = ">= 1.62.0"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.0"
    }
  }
}
```

Create `deploy/infra/hetzner/providers.tf`:

```hcl
provider "hcloud" {
  token = var.hcloud_token
}

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}
```

- [ ] **Step 3: Define secret and non-secret infrastructure inputs**

Create `deploy/infra/hetzner/variables.tf`:

```hcl
variable "hcloud_token" {
  type      = string
  sensitive = true
}

variable "cloudflare_api_token" {
  type      = string
  sensitive = true
}

variable "cloudflare_zone_id" {
  type = string
}

variable "domain" {
  type = string
}

variable "letsencrypt_email" {
  type = string
}

variable "location" {
  type    = string
  default = "nbg1"
}

variable "cluster_name" {
  type    = string
  default = "jobstrainer"
}

variable "ssh_public_key_path" {
  type = string
}
```

Create `deploy/infra/hetzner/terraform.tfvars.example`:

```hcl
cloudflare_zone_id  = "00000000000000000000000000000000"
domain              = "example.com"
letsencrypt_email   = "ops@example.com"
location            = "nbg1"
cluster_name        = "jobstrainer"
ssh_public_key_path = "~/.ssh/id_ed25519.pub"
```

- [ ] **Step 4: Document and run the Packer ARM snapshot prerequisite**

Create `deploy/infra/hetzner/README.md` containing the full operator path below, then execute the Packer build **before** `tofu apply` when a real cluster is being created:

```markdown
# jobstrainer Hetzner infrastructure

## Prerequisites

- OpenTofu >= 1.10.1
- Packer (initial ARM Leap Micro snapshot only)
- Hetzner Cloud project token (`HCLOUD_TOKEN`)
- Cloudflare API token scoped to DNS Edit for the selected zone
- SSH public key
- hcloud CLI

## One-time ARM OS snapshot

kube-hetzner boots nodes from an OS snapshot that must already exist in the
Hetzner project. For CAX21 nodes build an ARM Leap Micro snapshot once:

    export HCLOUD_TOKEN=...
    curl -sL https://raw.githubusercontent.com/kube-hetzner/terraform-hcloud-kube-hetzner/v3.0.1/packer-template/hcloud-leapmicro-snapshots.pkr.hcl \
      -o /tmp/hcloud-leapmicro-snapshots.pkr.hcl
    packer init /tmp/hcloud-leapmicro-snapshots.pkr.hcl
    # Source name is leapmicro-arm-snapshot. selinux_package_to_install is k3s or rke2.
    packer build -only=hcloud.leapmicro-arm-snapshot \
      -var 'selinux_package_to_install=k3s' \
      /tmp/hcloud-leapmicro-snapshots.pkr.hcl

Confirm the snapshot exists:

    hcloud image list --type snapshot --architecture arm

## Initialize and plan

    export TF_VAR_hcloud_token=...
    export TF_VAR_cloudflare_api_token=...
    cp terraform.tfvars.example terraform.tfvars
    tofu init
    tofu fmt -check -recursive
    tofu validate
    tofu plan

Review the planned permanent CAX21, zero-to-two CAX21 autoscaler pool with
public IPv4, and Cloudflare DNS-only A records before applying. Do not apply if
the permanent resources exceed the €20/month cost gate. Do not apply if the ARM
snapshot is missing.

## Apply and kubeconfig

    tofu apply

The module writes a local kubeconfig as part of its documented setup. Keep that
file outside Git and use it only through `KUBECONFIG=/path/to/kubeconfig`.
```

If this task is executed without creating a real cluster, still write the README and leave the Packer build as a documented gate; do not skip the documentation.

- [ ] **Step 5: Configure the pinned kube-hetzner module**

Create `deploy/infra/hetzner/main.tf`:

```hcl
module "kube_hetzner" {
  source  = "kube-hetzner/kube-hetzner/hcloud"
  version = "3.0.1"

  hcloud_token     = var.hcloud_token
  cluster_name     = var.cluster_name
  ssh_public_key   = file(pathexpand(var.ssh_public_key_path))
  ssh_private_key  = null

  control_plane_nodepools = [
    {
      name        = "permanent"
      server_type = "cax21"
      location    = var.location
      count       = 1
      # v3.0.1 types control-plane labels/taints as list(string), not maps.
      labels = [
        "jobstrainer.io/node-pool=permanent",
      ]
      taints = []
      extra_write_files = [
        {
          path        = "/etc/sysctl.d/90-opensearch.conf"
          content     = "vm.max_map_count=262144\n"
          permissions = "0644"
        },
      ]
      extra_runcmd = [
        "sysctl --system",
      ]
    },
  ]

  agent_nodepools = []

  autoscaler_nodepools = [
    {
      name        = "burst"
      server_type = "cax21"
      location    = var.location
      min_nodes   = 0
      max_nodes   = 2
      # Autoscaler labels are map(string) in v3.0.1.
      labels = {
        "jobstrainer.io/node-pool" = "burst"
      }
      taints = []
    },
  ]

  # Public IPv4 is required for image pulls and ingestion scraping. An IP-less
  # autoscaler pool needs a permanent NAT router, which exceeds the idle budget.
  autoscaler_enable_public_ipv4 = true
  autoscaler_enable_public_ipv6 = false

  allow_scheduling_on_control_plane = true
  enable_klipper_metal_lb           = true
  kubernetes_distribution           = "k3s"
  ingress_controller                = "traefik"
  enable_cert_manager               = true
  enable_metrics_server             = true
  enable_local_storage              = false
}
```

- [ ] **Step 6: Add DNS-only records from the module ingress output**

Create `deploy/infra/hetzner/dns.tf`:

```hcl
resource "cloudflare_dns_record" "frontend" {
  zone_id = var.cloudflare_zone_id
  name    = "app.${var.domain}"
  type    = "A"
  ttl     = 1
  content = module.kube_hetzner.ingress_public_ipv4
  proxied = false
}

resource "cloudflare_dns_record" "api" {
  zone_id = var.cloudflare_zone_id
  name    = "api.${var.domain}"
  type    = "A"
  ttl     = 1
  content = module.kube_hetzner.ingress_public_ipv4
  proxied = false
}
```

`enable_klipper_metal_lb = true` is deliberate: in this topology Klipper/ServiceLB
exposes Traefik through the permanent node's public address and avoids creating
a paid Hetzner Load Balancer. The module's `ingress_public_ipv4` output falls
back to that control-plane address when no managed LB exists. The design does
not claim ingress high availability until the permanent node is replaced by a
multi-node topology.

- [ ] **Step 7: Add safe outputs**

Create `deploy/infra/hetzner/outputs.tf`:

```hcl
output "cluster_name" {
  value = var.cluster_name
}

output "frontend_hostname" {
  value = "app.${var.domain}"
}

output "api_hostname" {
  value = "api.${var.domain}"
}

output "ingress_public_ipv4" {
  value = module.kube_hetzner.ingress_public_ipv4
}

output "storage_class_name" {
  value = "hcloud-volumes"
}
```

Do not output kubeconfig contents, tokens, or SSH private keys.

- [ ] **Step 8: Format and validate without a real apply**

Run:

```bash
cd deploy/infra/hetzner
tofu init
tofu fmt -check -recursive
tofu validate
```

Expected: providers download, formatting is clean, and validation succeeds with the module's typed nodepool schema.

- [ ] **Step 9: Commit the reproducible cluster definition**

```bash
git add deploy/infra/hetzner .gitignore
git commit -m "feat(infra): add Hetzner k3s and Cloudflare DNS definition"
```

---

### Task 7: Verify and publish ARM64 images

**Files:**
- Modify: `deploy/k8s/README.md`
- Modify: `AGENTS.md`
- Test: ARM64 Docker builds and application test suites

**Interfaces:**
- Consumes the existing root-context backend/ingestion Dockerfiles and frontend `VITE_API_URL` build argument.
- Produces a repeatable manual GHCR publishing procedure. The frontend image tag is bound to `https://api.<domain>` at build time.

- [ ] **Step 1: Correct local image build documentation**

In `deploy/k8s/README.md`, replace:

```sh
docker build -t jobstrainer-backend:local backend/
docker build -t jobstrainer-ingestion:local ingestion/
docker build -t jobstrainer-frontend:local frontend/
```

with:

```sh
docker build -f backend/Dockerfile -t jobstrainer-backend:local .
docker build -f ingestion/Dockerfile -t jobstrainer-ingestion:local .
docker build -f frontend/Dockerfile \
  --build-arg VITE_API_URL=http://localhost:8000 \
  -t jobstrainer-frontend:local ./frontend
```

Backend and ingestion require the repository root as build context because their
Dockerfiles copy the workspace root `pyproject.toml` and `uv.lock`.

- [ ] **Step 2: Add ARM64 build and GHCR publishing instructions**

Append a Hetzner image-build section to `deploy/k8s/README.md`:

```markdown
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

The backend image includes `postgresql-client` and `rclone` for the worker's
nightly Postgres backup loop. No separate postgres-backup image is required.

The frontend API URL is embedded at build time. Rebuild the frontend image when
the public API hostname changes.

If packages under `ghcr.io/OWNER/` are private, create a pull secret and attach
it through `values-hetzner-private.yaml` (or make the packages public for the
portfolio demo). Public packages need no `imagePullSecrets`.
```

- [ ] **Step 3: Run the ARM64 compatibility gate**

Run:

```bash
docker buildx build --platform linux/arm64 \
  -f backend/Dockerfile -t jobstrainer-backend:arm64 --load .

docker buildx build --platform linux/arm64 \
  -f ingestion/Dockerfile -t jobstrainer-ingestion:arm64 --load .

docker buildx build --platform linux/arm64 \
  -f frontend/Dockerfile \
  --build-arg VITE_API_URL=https://api.example.test \
  -t jobstrainer-frontend:arm64 --load ./frontend

cd backend && uv run pytest -q
cd ../ingestion && uv run pytest -q
cd ../frontend && VITE_API_URL=https://api.example.test npm run build
```

Expected: all images build and tests pass. If ingestion fails in the ARM image,
specifically validate real `python-jobspy`/`tls-client` and Playwright execution
before choosing x86; do not deploy emulated x86.

- [ ] **Step 4: Document the ARM gate in `AGENTS.md`**

Add a short deployment note:

```markdown
### Hetzner ARM64 deployment gate

Before deploying the Hetzner profile, build backend, ingestion, and frontend
with `docker buildx build --platform linux/arm64`. The backend image includes
`pg_dump` and `rclone` for the worker's nightly Postgres backup loop.
The ingestion image is the highest-risk component because it includes
Playwright and python-jobspy/tls-client. If the ARM64 gate fails, do not deploy
under emulation; switch the infrastructure profile to x86 and revisit the
budget.
```

- [ ] **Step 5: Commit image portability documentation**

```bash
git add deploy/k8s/README.md AGENTS.md
git commit -m "docs(deploy): document ARM64 image build and publishing flow"
```

---

### Task 8: Write the Hetzner deployment, recovery, and scaling runbook

**Files:**
- Modify: `deploy/k8s/README.md`
- Create: `deploy/k8s/loadtest-job-hetzner.yaml`
- Test: kubeconform schema validation and Helm render

**Interfaces:**
- Consumes the cluster output from Task 6, pushed images from Task 7, `values-hetzner.yaml`, and a manually created `jobstrainer-secrets`.
- Produces the exact operator path from provisioned infrastructure through HTTPS smoke test, backup restoration, OpenSearch recovery, and node-autoscaling measurement.

- [ ] **Step 1: Add a Hetzner secret-creation section**

Append this template to `deploy/k8s/README.md`:

```markdown
## Hetzner application Secret

Create the application secret after OpenTofu has produced a kubeconfig. `.env`
values must remain unquoted because `kubectl --from-env-file` preserves quotes.

    export KUBECONFIG=/path/to/jobstrainer-kubeconfig
    kubectl create secret generic jobstrainer-secrets --from-env-file=.env

Create the rclone password value once:

    rclone obscure "$BACKUP_SBOX_PASSWORD"

Patch the cluster-local URLs, public CORS origin, and Storage Box values.
`BACKUP_SBOX_PATH` is relative (no leading slash). `BACKUP_SBOX_RCLONE_PASS` is
the obscured value, not the raw password:

    kubectl patch secret jobstrainer-secrets --type merge -p \
      '{"stringData":{
        "DATABASE_URL":"postgresql+asyncpg://postgres:postgres@postgres:5432/jobstrainer",
        "OPENSEARCH_URL":"http://opensearch:9200",
        "BACKEND_URL":"http://api:8000",
        "CORS_ORIGINS":"https://app.example.com",
        "BACKUP_SBOX_HOST":"uXXXXX.your-storagebox.de",
        "BACKUP_SBOX_USER":"uXXXXX",
        "BACKUP_SBOX_RCLONE_PASS":"rclone-obscured-password-goes-here",
        "BACKUP_SBOX_PATH":"backups/jobstrainer"
      }}'
```

- [ ] **Step 2: Add the Helm deployment and HTTPS verification sequence**

Append:

```markdown
## Hetzner Helm deployment

Create an ignored `values-hetzner-private.yaml` that overrides the safe example
image repository, immutable tag, hostname, and Let's Encrypt email:

```yaml
bootstrap:
  image: { repository: ghcr.io/loryschi/jobstrainer-backend, tag: "2026-07-27" }
api:
  image: { repository: ghcr.io/loryschi/jobstrainer-backend, tag: "2026-07-27" }
worker:
  image: { repository: ghcr.io/loryschi/jobstrainer-backend, tag: "2026-07-27" }
ingestion:
  image: { repository: ghcr.io/loryschi/jobstrainer-ingestion, tag: "2026-07-27" }
frontend:
  image: { repository: ghcr.io/loryschi/jobstrainer-frontend, tag: "2026-07-27" }
ingress:
  frontendHost: app.example.com
  apiHost: api.example.com
certManager:
  email: ops@example.com
```

Then deploy:

    helm lint deploy/helm/jobstrainer \
      -f deploy/helm/jobstrainer/values.yaml \
      -f deploy/helm/jobstrainer/values-hetzner.yaml \
      -f values-hetzner-private.yaml

    helm install jobstrainer deploy/helm/jobstrainer \
      -f deploy/helm/jobstrainer/values.yaml \
      -f deploy/helm/jobstrainer/values-hetzner.yaml \
      -f values-hetzner-private.yaml

    kubectl get pods -o wide
    kubectl get ingress,clusterissuer,certificate
    curl --fail --silent --show-error https://api.example.com/health
    curl --fail --silent --show-error --output /dev/null https://app.example.com/

Start with `certManager.issuerName: letsencrypt-staging`. After the staging
certificate works, delete the issued Certificate/Secret pair for each host,
set `issuerName` to `letsencrypt-prod`, and run `helm upgrade`. Leaving the
staging Secret in place prevents the production issuer from replacing it.
```

- [ ] **Step 3: Add backup and restore drills**

Append:

```markdown
## Backup and restore drill

The worker runs a backup shortly after start when `BACKUP_SBOX_*` is set, then
every `BACKUP_INTERVAL_SECONDS` (default 86400). Confirm a dump landed:

    kubectl logs -l app=worker --tail=100 | grep -i backup

To restore, download a selected `.dump` from the Storage Box, then restore into
a freshly recreated Postgres PVC only:

    kubectl scale statefulset/postgres --replicas=0
    kubectl delete pvc data-postgres-0
    kubectl scale statefulset/postgres --replicas=1
    kubectl wait --for=condition=Ready pod/postgres-0 --timeout=180s
    kubectl cp selected.dump postgres-0:/tmp/restore.dump
    kubectl exec postgres-0 -- \
      pg_restore -U postgres -d jobstrainer --clean --if-exists --no-owner /tmp/restore.dump

Verify row counts and foreign keys after restoring:

    kubectl exec postgres-0 -- psql -U postgres -d jobstrainer -c \
      "SELECT count(*) AS orphaned_jobs
       FROM jobs j LEFT JOIN companies c ON c.id = j.company_id
       WHERE c.id IS NULL;"
```

- [ ] **Step 4: Add OpenSearch recovery procedure**

Append:

```markdown
## OpenSearch recovery

OpenSearch is derived from Postgres. To test recovery, delete only its PVC:

    kubectl scale statefulset/opensearch --replicas=0
    kubectl delete pvc data-opensearch-0
    kubectl scale statefulset/opensearch --replicas=1
    kubectl wait --for=condition=Ready pod/opensearch-0 --timeout=300s
    kubectl rollout restart deployment/worker

Wait for the reconcile interval, then verify a search returns jobs. Do not
restore OpenSearch from a backup.
```

- [ ] **Step 5: Add a burst-pool load job with distinct resource names**

Create `deploy/k8s/loadtest-job-hetzner.yaml` by copying `deploy/k8s/loadtest-job.yaml` and applying these changes:

1. Rename the ConfigMap to `api-loadtest-hetzner-script`.
2. Rename the Job to `api-loadtest-hetzner`.
3. Point the Job volume at that ConfigMap name.
4. Under `spec.template.spec`, add:

```yaml
affinity:
  nodeAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      nodeSelectorTerms:
      - matchExpressions:
        - key: jobstrainer.io/node-pool
          operator: In
          values:
          - burst
```

Keep the k6 target URL `http://api:8000` so the load path stays cluster-local.
This Job must not reuse the local kind Job/ConfigMap names, and must not run on
the permanent node because that would distort API capacity measurements.

- [ ] **Step 6: Add scaling-measurement instructions**

Append:

```markdown
## Autoscaling verification

Watch the HPA, pods, nodes, and autoscaler while applying the Hetzner k6 Job:

    kubectl get hpa api -w
    kubectl get pods -o wide -w
    kubectl get nodes -w
    kubectl -n kube-system logs deployment/cluster-autoscaler -f
    kubectl apply -f deploy/k8s/loadtest-job-hetzner.yaml

Record p50/p95 latency, error rate, API CPU/memory, HPA transitions, Pending
duration, worker provisioning time, and worker scale-down time. Use those
measurements to revise API resource requests, `hpa.maxReplicas`, and the
autoscaler pool maximum. Do not treat the initial 1–4 pods and 0–2 nodes as
capacity claims.
```

- [ ] **Step 7: Validate runbook manifests offline**

Run:

```bash
kubeconform -strict -ignore-missing-schemas -summary \
  deploy/k8s/loadtest-job-hetzner.yaml

helm template jobstrainer deploy/helm/jobstrainer \
  -f deploy/helm/jobstrainer/values.yaml \
  -f deploy/helm/jobstrainer/values-hetzner.yaml \
  | kubeconform -strict -ignore-missing-schemas -summary
```

Expected: both validations report zero errors without contacting a cluster.

- [ ] **Step 8: Commit operational documentation**

```bash
git add deploy/k8s/README.md deploy/k8s/loadtest-job-hetzner.yaml
git commit -m "docs(k8s): add Hetzner deployment recovery and scaling runbook"
```

---

## Final Verification Gate

- [ ] **Step 1: Verify all local and Hetzner static checks**

Run:

```bash
cd backend && uv run pytest -q
cd ../ingestion && uv run pytest -q
cd ../frontend && VITE_API_URL=https://api.example.test npm run build

cd ..
helm lint deploy/helm/jobstrainer \
  -f deploy/helm/jobstrainer/values-local.yaml
helm lint deploy/helm/jobstrainer \
  -f deploy/helm/jobstrainer/values.yaml \
  -f deploy/helm/jobstrainer/values-hetzner.yaml

helm template jobstrainer deploy/helm/jobstrainer \
  -f deploy/helm/jobstrainer/values-local.yaml \
  > /tmp/jobstrainer-local-final.yaml
diff -u /tmp/jobstrainer-local-before.yaml /tmp/jobstrainer-local-final.yaml

helm template jobstrainer deploy/helm/jobstrainer \
  -f deploy/helm/jobstrainer/values.yaml \
  -f deploy/helm/jobstrainer/values-hetzner.yaml \
  | kubeconform -strict -ignore-missing-schemas -summary

cd deploy/infra/hetzner
tofu fmt -check -recursive
tofu validate
```

Expected: all tests/builds/lints/validation pass, and the local Helm render still matches the pre-edit baseline captured in Task 3.

- [ ] **Step 2: Verify no secrets are staged**

Run:

```bash
git diff --cached --name-only | grep -E '(^|/)(\.env|.*\.tfvars|.*\.tfstate|kubeconfig|rclone\.conf|values-hetzner-private\.yaml)$' \
  && exit 1 || true
```

Expected: exit 0 with no matching files.

- [ ] **Step 3: Perform production acceptance only after a reviewed plan**

Run:

```bash
cd deploy/infra/hetzner
# Confirm the ARM Leap Micro snapshot exists first.
hcloud image list --type snapshot --architecture arm
tofu plan
```

Review before applying:

- exactly one permanent `cax21` node;
- autoscaler pool minimum zero and maximum two;
- autoscaler public IPv4 enabled, public IPv6 disabled;
- no NAT router server;
- only the expected Cloudflare DNS records;
- no unreviewed paid load balancers;
- permanent monthly resources satisfy the current €20 cost gate.

After a human approves the plan, run the deployment, smoke, backup restore,
OpenSearch recovery, and scaling procedures from Task 8.
