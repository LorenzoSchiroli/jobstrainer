# GHCR Build & Push CI — Design

**Date:** 2026-07-29  
**Status:** Approved design, pre-implementation

> Side track outside the numbered k8s phases. Phase 4
> (`2026-07-27-k8s-phase4-hetzner-design.md`) and the scaling roadmap
> (`2026-07-07-k8s-scaling-design.md`) intentionally left full CI/CD and GitOps
> out of scope; this design covers only image build and push to GHCR so Hetzner
> deploys do not require a laptop `docker buildx` push.

## 1. Goal

Add a thin GitHub Actions workflow that builds the three application images for
`linux/arm64` and pushes them to GHCR. Cluster deploy stays manual
(`helm upgrade` with updated image digests/tags).

Success looks like: from the Actions UI, run **Build and push images**, wait for
green jobs, then on the Hetzner cluster pull/restart (or `helm upgrade`) so
workloads using `tag: latest` and `imagePullPolicy: Always` pick up the new
images — without building on a developer machine.

## 2. Constraints and accepted trade-offs

- **Trigger:** `workflow_dispatch` only. No builds on `main` push, PRs, or tags.
- **Platform:** `linux/arm64` only, on native GitHub-hosted ARM runners
  (`ubuntu-24.04-arm`). No QEMU multi-arch in this design.
- **Images:** always build all three (`backend`, `ingestion`, `frontend`) in
  parallel on each dispatch.
- **Auth:** `GITHUB_TOKEN` with `packages: write`. No personal access token in
  local shells or Actions secrets for publish.
- **Tests:** not part of this workflow. Suites remain local / a future CI track.
- **Deploy:** not automated. No kubeconfig in GitHub, no Helm from Actions, no
  ArgoCD/Flux.
- **Cost:** large images (backend ~3GB, ingestion ~4GB) consume Actions minutes
  and GHCR storage; manual dispatch and tag retention keep that bounded.
- **Tracking vs clutter:** each push tags `latest` and a short SHA; only the
  newest two SHA tags are kept per package.

## 3. Approaches considered

1. **Single workflow with a three-image matrix** (chosen) — one dispatch, three
   parallel build jobs, shared prune step.
2. **Three separate workflows** — selective rebuild without inputs; more YAML
   and easy to forget one image. Rejected because this design always builds all
   three.
3. **Reusable workflow + caller** — DRY for many images later; overkill for three
   near-identical Docker builds today.

## 4. System design

### 4.1 Workflow file

**Path:** `.github/workflows/build-push-images.yml`

**Jobs:**

1. **`build`** — matrix over `backend`, `ingestion`, `frontend`, each on
   `ubuntu-24.04-arm`:
   - checkout;
   - set up Docker Buildx;
   - log in to `ghcr.io` with `GITHUB_TOKEN`;
   - `docker buildx build --platform linux/arm64 --push` with tags `latest` and
     short SHA (7 characters from `github.sha`);
   - set OCI labels `org.opencontainers.image.revision` (full SHA) and
     `org.opencontainers.image.source` (repository URL).

2. **`prune-tags`** — `needs: build` (all matrix legs must succeed). For each
   of the three GHCR packages, list tags, keep `latest` and the two newest SHA
   tags, delete older SHA tags. Do not delete `latest`.

**Matrix build commands (contexts match existing Dockerfiles / Phase 4 docs):**

| Image | Dockerfile | Context | Extra build-args |
|-------|------------|---------|------------------|
| backend | `backend/Dockerfile` | repository root (`.`) | — |
| ingestion | `ingestion/Dockerfile` | repository root (`.`) | — |
| frontend | `frontend/Dockerfile` | `./frontend` | `VITE_API_URL` from `vars.VITE_API_URL` |

**Image repositories:**

- `ghcr.io/<owner>/jobstrainer-backend`
- `ghcr.io/<owner>/jobstrainer-ingestion`
- `ghcr.io/<owner>/jobstrainer-frontend`

`<owner>` is `github.repository_owner` lowercased. Package names match the Phase
4 Hetzner values convention.

**Permissions:** `contents: read`, `packages: write`.

**Failure behavior:** matrix legs are independent — one image may fail while
others still publish. Prune runs only when all three builds succeed.

### 4.2 Frontend API URL

The frontend bakes `VITE_API_URL` at image build time. The workflow reads the
GitHub Actions **repository variable** `VITE_API_URL` (not a secret; the URL is
public). If the variable is unset or empty, the frontend matrix leg fails with a
clear error before pushing a useless image.

Optional dispatch override is not required in v1; changing the hostname means
updating the repository variable and re-running the workflow.

### 4.3 Tags and retention

On every successful image push:

- `latest` — mutable; overwritten each run (primary tag for Helm).
- short SHA — tracking / optional rollback pin.

After all builds succeed, prune SHA tags so each package retains at most the
two newest SHA tags plus `latest`. Untagged digests may remain until GHCR
garbage-collects; tag clutter stays bounded by design. Document that storage
is not instantly zeroed.

### 4.4 Cluster usage (manual)

Hetzner app image values should use `tag: latest` and
`imagePullPolicy: Always` so a rollout or `helm upgrade` pulls the new digest
after a successful Actions run. Operators may temporarily pin
`tag: <short-sha>` for rollback. No CI step performs the upgrade.

### 4.5 Documentation

Update:

- `deploy/k8s/README.md` — prefer Actions `workflow_dispatch` for GHCR publish;
  keep laptop `docker buildx` commands as a fallback; note `VITE_API_URL`
  variable and `imagePullPolicy: Always` for `latest`.
- `AGENTS.md` — short pointer under infrastructure/commands that images are
  published via the Actions workflow.

## 5. Out of scope

- Deploy automation, GitOps, or cluster credentials in GitHub.
- Test suites in this workflow.
- Multi-platform `linux/amd64` images.
- Automatic builds on `main` / tags / PRs.
- Selective image builds via dispatch inputs.
- Changing Dockerfiles beyond what is required for labeling (prefer build-arg /
  label flags in the workflow).

## 6. Implementation outline

1. Add `.github/workflows/build-push-images.yml` as specified above.
2. Document the one-time setup: set repository variable `VITE_API_URL`; ensure
   GHCR package visibility / `imagePullSecrets` match the existing Hetzner plan
   (public packages need no pull secret).
3. Update `deploy/k8s/README.md` and `AGENTS.md`.
4. Manually dispatch once, verify three packages receive `latest` + SHA, verify
   prune leaves at most two SHA tags after a second run.
5. Confirm Hetzner values use `latest` + `Always` (or document the required
   values change if they still pin a date tag).

## 7. Risks

- **Actions minutes / storage:** large ARM builds are expensive; mitigate with
  dispatch-only and SHA retention.
- **Stale nodes:** without `imagePullPolicy: Always`, pods may keep an old
  `latest` digest; document the requirement.
- **Missing `VITE_API_URL`:** frontend image would point at the Dockerfile
  default (`http://localhost:8000`); fail the job instead of publishing that.
- **ARM runner availability:** if `ubuntu-24.04-arm` is unavailable for the
  org/plan, the workflow cannot run as designed; do not fall back to QEMU in
  this design — fix runner access or revise the spec.
- **Partial publish:** a failed matrix leg can leave GHCR with a mix of new and
  old images; operators should re-run until all three are green before
  upgrading the cluster.
