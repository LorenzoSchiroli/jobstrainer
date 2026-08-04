# Cloud-Agnostic Helm Values Layering — Design

**Date:** 2026-08-04  
**Status:** Design (pre-implementation)  
**Author:** lschiroli

> Complements `docs/superpowers/specs/2026-07-27-k8s-phase4-hetzner-design.md`.
> Phase 4 introduced a Hetzner values profile that mixed portable cloud
> settings with provider-specific knobs. This design splits those layers so a
> future AWS (or other) profile reuses the same cloud file and only swaps
> provider bits.

## 1. Goal

Keep Hetzner configuration to what is strictly Hetzner-specific. Put settings
that any cloud Kubernetes deploy would need into a shared, provider-neutral
values file. Real deployment identity (image repos, hostnames, cert email)
stays in a gitignored private overlay, with committed files using only fake
placeholders.

Success looks like:

- `values-hetzner.yaml` contains only provider knobs (today: `storageClass`);
- adding AWS means a thin `values-aws.yaml` plus the existing cloud file, not
  a copy of CSI/`pgdata`/ingress/scheduling settings;
- kind continues to use `values.yaml` + `values-local.yaml` unchanged in role.

## 2. Constraints and decisions

- **`values.yaml` stays kind-safe.** Do not put CSI `pgdataSubdir`, `fsGroup`,
  ingress-on, or `imagePullPolicy: Always` in the base chart defaults.
- **New shared layer: `values-cloud.yaml`.** Portable cloud/demo settings live
  here.
- **Thin provider overlays.** `values-hetzner.yaml` (and a future
  `values-aws.yaml`) override only provider-specific keys.
- **Private file renamed.** `values-hetzner-private.yaml` →
  `values-private.yaml` (repo root, gitignored). Same role: real images,
  hosts, cert email.
- **Placeholders stay committed.** Fake GHCR repos (`ghcr.io/jobstrainer-demo/...`),
  `app.example.com` / `api.example.com`, and `ops@example.com` live in
  `values-cloud.yaml` so the shape is readable without the private file.
- **No duplication.** Overlays must not repeat keys that already match
  `values.yaml` (e.g. ingestion schedule/hours when identical to base).
- **Out of scope:** OpenTofu / `deploy/infra/hetzner/` layout; chart template
  changes; implementing an AWS profile.

## 3. Values layering

### 3.1 Files

| File | Committed? | Role |
|------|------------|------|
| `deploy/helm/jobstrainer/values.yaml` | yes | Kind-safe chart defaults |
| `deploy/helm/jobstrainer/values-local.yaml` | yes | Kind image tags `:local` |
| `deploy/helm/jobstrainer/values-cloud.yaml` | yes | Portable cloud/demo settings |
| `deploy/helm/jobstrainer/values-hetzner.yaml` | yes | Hetzner-only knobs |
| `values-private.yaml` (repo root) | no | Real deploy identity |

### 3.2 Helm install order

Cloud (Hetzner today):

```bash
helm upgrade --install jobstrainer deploy/helm/jobstrainer \
  -f deploy/helm/jobstrainer/values.yaml \
  -f deploy/helm/jobstrainer/values-cloud.yaml \
  -f deploy/helm/jobstrainer/values-hetzner.yaml \
  -f values-private.yaml
```

Kind (unchanged):

```bash
helm upgrade --install jobstrainer deploy/helm/jobstrainer \
  -f deploy/helm/jobstrainer/values-local.yaml
```

Future AWS (illustrative, not implemented):

```bash
helm upgrade --install jobstrainer deploy/helm/jobstrainer \
  -f deploy/helm/jobstrainer/values.yaml \
  -f deploy/helm/jobstrainer/values-cloud.yaml \
  -f deploy/helm/jobstrainer/values-aws.yaml \
  -f values-private.yaml
```

## 4. Content split

### 4.1 `values-cloud.yaml`

Move from today’s `values-hetzner.yaml` (and keep as placeholders where noted):

- `imagePullPolicy: Always`
- `postgres.storage` (cloud size), `postgres.pgdataSubdir: pgdata`
- `opensearch.storage` (cloud size), `opensearch.fsGroup: 1000`
- `nodePools` (permanent / burst label keys and values)
- `scheduling` (postgres/opensearch/worker → permanent; ingestion → burst)
- `ingress.enabled: true`, `className: traefik`, fake hosts, TLS secret name
  placeholders (including apex TLS name if present in base)
- `certManager.createIssuers: true`, fake email, staging issuer placeholder
- GHCR placeholder image repositories for bootstrap/api/worker/ingestion/frontend

Do not restate keys that already match `values.yaml`.

### 4.2 `values-hetzner.yaml`

Only:

- `storageClass: hcloud-volumes`

Add further keys here only when they are Hetzner-specific (not portable CSI
or app-shape settings).

### 4.3 `values-private.yaml`

Operator-owned overrides, same content as today’s private file after rename:

- real GHCR image repositories (and tags if needed)
- real `ingress.frontendHost` / `apiHost` / `apexRedirectHosts`
- real `certManager.email` / `issuerName` (e.g. prod)

### 4.4 Unchanged

- `values.yaml` — kind-safe defaults
- `values-local.yaml` — `:local` tags for kind side-loaded images
- `deploy/infra/hetzner/` — provider infra remains separate

## 5. Docs and migration

- Update `.gitignore`: `values-hetzner-private.yaml` → `values-private.yaml`
- Rename the local private file on the operator machine (same contents)
- Update `deploy/k8s/README.md` helm commands and private-file instructions
- Note in the README that a future provider adds `values-<provider>.yaml` on
  top of `values-cloud.yaml`
- Refresh references in specs/plans that mention `values-hetzner-private.yaml`
  when those docs are edited for this work; no need to rewrite historical
  Phase 4 narrative beyond pointing at this layering

## 6. Non-goals

- Creating `values-aws.yaml` or any AWS infra
- Changing Helm templates for this split
- Moving secrets into values files (cluster Secret / `.env` flow unchanged)
