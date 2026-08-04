# Cloud-Agnostic Helm Values Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split portable cloud Helm settings into `values-cloud.yaml`, leave `values-hetzner.yaml` provider-only, and rename the gitignored private overlay to `values-private.yaml`.

**Architecture:** Chart defaults stay kind-safe in `values.yaml`. A new `values-cloud.yaml` holds CSI-safe knobs, scheduling, ingress/cert placeholders, and example GHCR repos. `values-hetzner.yaml` keeps only `storageClass: hcloud-volumes`. Real deploy identity moves to repo-root `values-private.yaml`. Docs and the live private file are updated to the new `-f` stack.

**Tech Stack:** Helm 3 values overlays, gitignore, `deploy/k8s/README.md`

## Global Constraints

- `values.yaml` stays kind-safe (no CSI `pgdataSubdir`, `fsGroup`, ingress-on, or `imagePullPolicy: Always` in base).
- Overlays must not restate keys that already match `values.yaml`.
- Committed files use fake placeholders only; real images/hosts/email stay in `values-private.yaml`.
- Out of scope: OpenTofu / `deploy/infra/hetzner/`, chart template changes, creating `values-aws.yaml`.
- Spec: `docs/superpowers/specs/2026-08-04-cloud-agnostic-helm-values-design.md`.

---

## File structure

| File | Responsibility |
|------|----------------|
| `deploy/helm/jobstrainer/values-cloud.yaml` | New portable cloud/demo overlay |
| `deploy/helm/jobstrainer/values-hetzner.yaml` | Thin Hetzner-only overlay (`storageClass`) |
| `values-private.yaml` (repo root, gitignored) | Operator real images/hosts/cert (renamed) |
| `.gitignore` | Ignore `values-private.yaml` instead of old name |
| `deploy/k8s/README.md` | Document new `-f` stack and private filename |
| `docs/superpowers/specs/2026-08-02-demo-dump-lifecycle-design.md` | Align helm `-f` list with new layering |

Do not rewrite historical Phase 4 plans end-to-end; only touch docs needed for operators going forward.

---

### Task 1: Create `values-cloud.yaml` and thin `values-hetzner.yaml`

**Files:**
- Create: `deploy/helm/jobstrainer/values-cloud.yaml`
- Modify: `deploy/helm/jobstrainer/values-hetzner.yaml`
- Test: `helm lint` / `helm template` with the new stack (no private file required for lint of placeholders)

**Interfaces:**
- Consumes: current keys in `values-hetzner.yaml` and defaults in `values.yaml`
- Produces: cloud overlay content below; Hetzner file containing only `storageClass: hcloud-volumes`

- [ ] **Step 1: Create `values-cloud.yaml` with the full portable content**

Create `deploy/helm/jobstrainer/values-cloud.yaml`:

```yaml
# Portable cloud/demo settings. Provider overlays (e.g. values-hetzner.yaml)
# add only cloud-specific knobs. Real images/hosts/email go in values-private.yaml.
imagePullPolicy: Always

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
  fsGroup: 1000

bootstrap:
  image:
    repository: ghcr.io/jobstrainer-demo/jobstrainer-backend
    tag: latest

api:
  image:
    repository: ghcr.io/jobstrainer-demo/jobstrainer-backend
    tag: latest

worker:
  image:
    repository: ghcr.io/jobstrainer-demo/jobstrainer-backend
    tag: latest

ingestion:
  image:
    repository: ghcr.io/jobstrainer-demo/jobstrainer-ingestion
    tag: latest

frontend:
  image:
    repository: ghcr.io/jobstrainer-demo/jobstrainer-frontend
    tag: latest

ingress:
  enabled: true
  frontendHost: app.example.com
  apiHost: api.example.com

certManager:
  createIssuers: true
  email: ops@example.com
  issuerName: letsencrypt-staging
```

Notes for the implementer:
- Do **not** copy `storageClass` here.
- Do **not** restate `ingress.className`, TLS secret names, `opensearch.javaOpts`, or ingestion `schedule`/`hours`/`activeDeadlineSeconds` when they already match `values.yaml`.
- Do **not** put real domains or personal GHCR repos here.

- [ ] **Step 2: Replace `values-hetzner.yaml` with provider-only content**

Overwrite `deploy/helm/jobstrainer/values-hetzner.yaml` with:

```yaml
# Hetzner-specific overrides on top of values-cloud.yaml.
storageClass: hcloud-volumes
```

- [ ] **Step 3: Lint and template with the new committed stack**

Run from repo root:

```bash
helm lint deploy/helm/jobstrainer \
  -f deploy/helm/jobstrainer/values.yaml \
  -f deploy/helm/jobstrainer/values-cloud.yaml \
  -f deploy/helm/jobstrainer/values-hetzner.yaml

helm template jobstrainer deploy/helm/jobstrainer \
  -f deploy/helm/jobstrainer/values.yaml \
  -f deploy/helm/jobstrainer/values-cloud.yaml \
  -f deploy/helm/jobstrainer/values-hetzner.yaml \
  | grep -E 'storageClassName:|imagePullPolicy:|pgdata|fsGroup|app.example.com|hcloud-volumes' | head -40
```

Expected:
- `helm lint` reports no errors
- rendered output includes `hcloud-volumes`, `imagePullPolicy: Always`, `app.example.com`, and CSI-related postgres/opensearch settings from the cloud file

Also confirm kind path still works:

```bash
helm lint deploy/helm/jobstrainer -f deploy/helm/jobstrainer/values-local.yaml
```

Expected: no errors; kind profile must not pick up `hcloud-volumes` or `pgdataSubdir: pgdata`.

- [ ] **Step 4: Commit**

```bash
git add \
  deploy/helm/jobstrainer/values-cloud.yaml \
  deploy/helm/jobstrainer/values-hetzner.yaml
git commit -m "$(cat <<'EOF'
refactor(helm): split portable cloud values from Hetzner overlay

Move CSI, scheduling, ingress placeholders, and example images into
values-cloud.yaml; keep only storageClass in values-hetzner.yaml.
EOF
)"
```

---

### Task 2: Rename private overlay and update gitignore

**Files:**
- Modify: `.gitignore`
- Rename (local only, not committed): `values-hetzner-private.yaml` → `values-private.yaml`
- Test: confirm gitignore hides the new name and does not track it

**Interfaces:**
- Consumes: existing local `values-hetzner-private.yaml` contents (unchanged YAML)
- Produces: gitignored `values-private.yaml` at repo root

- [ ] **Step 1: Update `.gitignore`**

In `.gitignore`, replace:

```
values-hetzner-private.yaml
```

with:

```
values-private.yaml
```

- [ ] **Step 2: Rename the local private file**

If `values-hetzner-private.yaml` exists at the repo root:

```bash
mv values-hetzner-private.yaml values-private.yaml
```

Do not `git add` this file. Contents stay the same (real GHCR repos, hosts, cert email).

If the file does not exist on this machine, create `values-private.yaml` from the README example in Task 3 (still gitignored).

- [ ] **Step 3: Verify ignore behavior**

```bash
git check-ignore -v values-private.yaml
git status --short values-private.yaml values-hetzner-private.yaml
```

Expected:
- `check-ignore` prints a `.gitignore` rule for `values-private.yaml`
- neither private filename appears as a staged/untracked file to commit

- [ ] **Step 4: Lint with private overlay if present**

```bash
helm lint deploy/helm/jobstrainer \
  -f deploy/helm/jobstrainer/values.yaml \
  -f deploy/helm/jobstrainer/values-cloud.yaml \
  -f deploy/helm/jobstrainer/values-hetzner.yaml \
  -f values-private.yaml
```

Expected: no errors. If `values-private.yaml` is missing, skip this step (placeholders-only lint from Task 1 is enough).

- [ ] **Step 5: Commit gitignore only**

```bash
git add .gitignore
git commit -m "$(cat <<'EOF'
chore: rename ignored Helm private overlay to values-private.yaml

Keep deploy identity out of git with a provider-neutral filename.
EOF
)"
```

---

### Task 3: Update operator docs and active design refs

**Files:**
- Modify: `deploy/k8s/README.md`
- Modify: `docs/superpowers/specs/2026-08-02-demo-dump-lifecycle-design.md` (helm `-f` list only)
- Test: grep for leftover `values-hetzner-private` in operator-facing docs

**Interfaces:**
- Consumes: layering from Task 1–2
- Produces: README and dump-lifecycle spec that document the four-file cloud stack

- [ ] **Step 1: Update Hetzner image / pull-secret mentions in `deploy/k8s/README.md`**

Replace every operator-facing `values-hetzner-private.yaml` with `values-private.yaml`.

In the “Hetzner amd64 images” section, change the sentence that says `imagePullPolicy: Always` is set in `values-hetzner.yaml` so it points at `values-cloud.yaml` instead.

- [ ] **Step 2: Rewrite the “Hetzner Helm deployment” section**

Replace the private-file instructions and helm commands with the following
README content (keep the existing post-deploy verification bullets and
staging→prod issuer note that already follow this section):

````markdown
## Hetzner Helm deployment

Cloud deploys layer portable settings, then provider knobs, then a gitignored
private overlay:

1. `values.yaml` — kind-safe chart defaults
2. `values-cloud.yaml` — portable cloud/demo settings (CSI, scheduling, ingress shape, placeholder images)
3. `values-hetzner.yaml` — Hetzner-only (`storageClass: hcloud-volumes`)
4. `values-private.yaml` — real image repos, hostnames, Let's Encrypt email (repo root, gitignored)

A future provider adds `values-<provider>.yaml` instead of step 3; `values-cloud.yaml` stays shared.

Create an ignored `values-private.yaml` that overrides the safe example
image repository, image tag (`latest`, or a retained short SHA for rollback), hostname, and Let's Encrypt email:

```yaml
bootstrap:
  image: { repository: ghcr.io/OWNER/jobstrainer-backend, tag: latest }
api:
  image: { repository: ghcr.io/OWNER/jobstrainer-backend, tag: latest }
worker:
  image: { repository: ghcr.io/OWNER/jobstrainer-backend, tag: latest }
ingestion:
  image: { repository: ghcr.io/OWNER/jobstrainer-ingestion, tag: latest }
frontend:
  image: { repository: ghcr.io/OWNER/jobstrainer-frontend, tag: latest }
ingress:
  frontendHost: app.example.com
  apiHost: api.example.com
certManager:
  email: ops@example.com
```

Then deploy:

    helm lint deploy/helm/jobstrainer \
      -f deploy/helm/jobstrainer/values.yaml \
      -f deploy/helm/jobstrainer/values-cloud.yaml \
      -f deploy/helm/jobstrainer/values-hetzner.yaml \
      -f values-private.yaml

    helm upgrade --install jobstrainer deploy/helm/jobstrainer \
      -f deploy/helm/jobstrainer/values.yaml \
      -f deploy/helm/jobstrainer/values-cloud.yaml \
      -f deploy/helm/jobstrainer/values-hetzner.yaml \
      -f values-private.yaml
````

- [ ] **Step 3: Update dump-lifecycle design helm invocation**

In `docs/superpowers/specs/2026-08-02-demo-dump-lifecycle-design.md`, replace the helm step that lists only Hetzner + private files with:

```markdown
5. `helm upgrade --install jobstrainer deploy/helm/jobstrainer`
   `-f deploy/helm/jobstrainer/values.yaml`
   `-f deploy/helm/jobstrainer/values-cloud.yaml`
   `-f deploy/helm/jobstrainer/values-hetzner.yaml`
   `-f values-private.yaml` (repo-root private overrides).
```

- [ ] **Step 4: Grep for leftover operator-facing old names**

```bash
rg -n 'values-hetzner-private' deploy/k8s/README.md docs/superpowers/specs/2026-08-02-demo-dump-lifecycle-design.md docs/superpowers/specs/2026-08-04-cloud-agnostic-helm-values-design.md
rg -n 'values-private\.yaml|values-cloud\.yaml' deploy/k8s/README.md
```

Expected:
- no `values-hetzner-private` in `deploy/k8s/README.md` or the dump-lifecycle spec
- README mentions both `values-cloud.yaml` and `values-private.yaml`
- historical Phase 4 plans under `docs/superpowers/plans/2026-07-27-*` may still mention the old name; leave them unless you are already editing those files

- [ ] **Step 5: Commit**

```bash
git add \
  deploy/k8s/README.md \
  docs/superpowers/specs/2026-08-02-demo-dump-lifecycle-design.md
git commit -m "$(cat <<'EOF'
docs: document cloud values layer and values-private overlay

Align Hetzner deploy instructions with values-cloud.yaml and the
renamed private file.
EOF
)"
```

---

## Plan self-review

1. **Spec coverage:** Goal/layering (§1–3), content split (§4), docs/migration (§5), non-goals (§6) each map to Tasks 1–3. No AWS infra task (explicit non-goal).
2. **Placeholders:** None — full YAML and README blocks are inlined.
3. **Consistency:** Private filename is `values-private.yaml` everywhere in tasks; helm order is always base → cloud → hetzner → private.
