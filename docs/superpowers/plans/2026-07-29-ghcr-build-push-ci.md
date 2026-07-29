# GHCR Build & Push CI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `workflow_dispatch`-only GitHub Actions workflow that builds `backend`, `ingestion`, and `frontend` for `linux/arm64` on native ARM runners and pushes `latest` + short-SHA tags to GHCR, with retention of the two newest SHA tags.

**Architecture:** One workflow file with a three-way matrix `build` job (Docker Buildx → GHCR via `GITHUB_TOKEN`) and a dependent `prune-tags` job that deletes older SHA-tagged package versions through the GitHub Packages API. Deploy stays manual; docs tell operators to use Actions instead of laptop `buildx`, and Helm private values examples use `tag: latest` with the existing Hetzner `imagePullPolicy: Always`.

**Tech Stack:** GitHub Actions (`ubuntu-24.04-arm`), Docker Buildx, `docker/login-action`, `docker/build-push-action`, GHCR, `gh` + `jq` for package version prune, Helm values docs.

## Global Constraints

- Trigger: `workflow_dispatch` only (no `push` / PR / tag triggers).
- Platform: `linux/arm64` only on `ubuntu-24.04-arm` (no QEMU, no `amd64`).
- Always build all three images in parallel on each dispatch.
- Auth: `GITHUB_TOKEN` with `packages: write` (no PAT for publish).
- Tags: `latest` + 7-char short SHA; retain at most the two newest SHA tags per package; never delete `latest`.
- Frontend: `VITE_API_URL` from repository variable `vars.VITE_API_URL`; fail the frontend leg if empty.
- No tests and no deploy in this workflow.
- Image names: `ghcr.io/<owner>/jobstrainer-{backend,ingestion,frontend}` with `<owner>` = lowercased `github.repository_owner`.
- Spec: `docs/superpowers/specs/2026-07-29-ghcr-build-push-ci-design.md`.

---

## File structure

| Path | Responsibility |
|------|----------------|
| `.github/workflows/build-push-images.yml` | Entire CI: matrix build/push + prune |
| `deploy/k8s/README.md` | Prefer Actions; keep laptop fallback; `latest` + `Always` notes |
| `AGENTS.md` | Point Hetzner image publish at the Actions workflow |
| `deploy/helm/jobstrainer/values-hetzner.yaml` | Example tags stay placeholders OR switch example to `latest` for consistency with the design (private overlay is what production uses) |

Do not modify Dockerfiles unless a build fails for a workflow-only reason; build-args and OCI labels belong in the workflow.

---

### Task 1: Add the build-and-push workflow

**Files:**
- Create: `.github/workflows/build-push-images.yml`
- Test: validate YAML locally with `actionlint` if installed, otherwise `python -c` YAML parse; full proof is a manual Actions dispatch after merge

**Interfaces:**
- Consumes: existing `backend/Dockerfile`, `ingestion/Dockerfile`, `frontend/Dockerfile` and build contexts from Phase 4 docs; repo variable `VITE_API_URL`
- Produces: GHCR images tagged `latest` and short SHA; workflow name suitable for the Actions UI (“Build and push images”)

- [ ] **Step 1: Create the workflows directory if missing**

```bash
mkdir -p .github/workflows
```

- [ ] **Step 2: Write `.github/workflows/build-push-images.yml`**

Create the file with this exact content (adjust only if action major versions need bumping for security advisories at implement time — keep the same job/step structure):

```yaml
name: Build and push images

on:
  workflow_dispatch:

permissions:
  contents: read
  packages: write

env:
  REGISTRY: ghcr.io

jobs:
  build:
    name: Build ${{ matrix.image }}
    runs-on: ubuntu-24.04-arm
    strategy:
      fail-fast: false
      matrix:
        include:
          - image: backend
            dockerfile: backend/Dockerfile
            context: .
            package: jobstrainer-backend
          - image: ingestion
            dockerfile: ingestion/Dockerfile
            context: .
            package: jobstrainer-ingestion
          - image: frontend
            dockerfile: frontend/Dockerfile
            context: ./frontend
            package: jobstrainer-frontend
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Require VITE_API_URL for frontend
        if: matrix.image == 'frontend'
        env:
          VITE_API_URL: ${{ vars.VITE_API_URL }}
        run: |
          if [ -z "$VITE_API_URL" ]; then
            echo "::error::Set repository variable VITE_API_URL (Settings → Secrets and variables → Actions → Variables)"
            exit 1
          fi

      - name: Image name and short SHA
        id: meta
        run: |
          OWNER=$(echo '${{ github.repository_owner }}' | tr '[:upper:]' '[:lower:]')
          SHORT_SHA=$(echo '${{ github.sha }}' | cut -c1-7)
          echo "owner=${OWNER}" >> "$GITHUB_OUTPUT"
          echo "short_sha=${SHORT_SHA}" >> "$GITHUB_OUTPUT"
          echo "image=${{ env.REGISTRY }}/${OWNER}/${{ matrix.package }}" >> "$GITHUB_OUTPUT"

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and push
        uses: docker/build-push-action@v6
        with:
          context: ${{ matrix.context }}
          file: ${{ matrix.dockerfile }}
          platforms: linux/arm64
          push: true
          tags: |
            ${{ steps.meta.outputs.image }}:latest
            ${{ steps.meta.outputs.image }}:${{ steps.meta.outputs.short_sha }}
          build-args: |
            ${{ matrix.image == 'frontend' && format('VITE_API_URL={0}', vars.VITE_API_URL) || '' }}
          labels: |
            org.opencontainers.image.revision=${{ github.sha }}
            org.opencontainers.image.source=https://github.com/${{ github.repository }}

  prune-tags:
    name: Prune old SHA tags
    runs-on: ubuntu-24.04-arm
    needs: build
    permissions:
      packages: write
    strategy:
      matrix:
        package:
          - jobstrainer-backend
          - jobstrainer-ingestion
          - jobstrainer-frontend
    steps:
      - name: Keep latest + two newest SHA tags
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          OWNER: ${{ github.repository_owner }}
          PACKAGE: ${{ matrix.package }}
        run: |
          set -euo pipefail
          # List container package versions for the user/org owner.
          # User-owned: /users/{user}/packages/container/{name}/versions
          # Org-owned:  /orgs/{org}/packages/container/{name}/versions
          if gh api "users/${OWNER}" --jq '.type' | grep -qi organization; then
            API_BASE="orgs/${OWNER}/packages/container/${PACKAGE}/versions"
          else
            API_BASE="users/${OWNER}/packages/container/${PACKAGE}/versions"
          fi

          VERSIONS=$(gh api --paginate "${API_BASE}")
          # Versions that carry a 7-char hex SHA tag, newest first.
          mapfile -t SHA_VERSION_IDS < <(
            echo "${VERSIONS}" | jq -r '
              [.[] | {
                id,
                updated_at,
                tags: (.metadata.container.tags // [])
              }
              | select(.tags | map(test("^[0-9a-f]{7}$")) | any)]
              | sort_by(.updated_at) | reverse | .[].id
            '
          )

          KEEP=2
          idx=0
          for id in "${SHA_VERSION_IDS[@]:-}"; do
            idx=$((idx + 1))
            TAGS=$(echo "${VERSIONS}" | jq -r --argjson id "$id" '
              .[] | select(.id == $id) | (.metadata.container.tags // []) | join(",")
            ')
            if echo "${TAGS}" | tr ',' '\n' | grep -qx 'latest'; then
              echo "Skip version ${id} (has latest): ${TAGS}"
              continue
            fi
            if [ "$idx" -le "$KEEP" ]; then
              echo "Keep SHA version ${id}: ${TAGS}"
              continue
            fi
            echo "Delete SHA version ${id}: ${TAGS}"
            gh api -X DELETE "${API_BASE}/${id}"
          done
```

Notes for implementers:

- `fail-fast: false` matches the spec (one image can fail while others still publish).
- `prune-tags` only runs when all matrix legs succeed (`needs: build`).
- The frontend `build-args` expression must not pass an empty spurious arg that breaks BuildKit; if the conditional form is awkward in practice, use a dedicated step that writes `VITE_API_URL=...` into an env file / outputs only for `frontend`, and pass `build-args: ${{ steps.args.outputs.build_args }}`.
- Package delete requires the package to be linked to this repository (or the token to have delete rights). First successful push from Actions usually links it; if prune returns 403, link the package to the repo in GHCR package settings and re-run.

- [ ] **Step 3: Validate workflow YAML syntax**

Run from repo root:

```bash
python3 -c "import yaml,pathlib; yaml.safe_load(pathlib.Path('.github/workflows/build-push-images.yml').read_text()); print('ok')"
```

Expected: `ok`

If `actionlint` is available:

```bash
actionlint .github/workflows/build-push-images.yml
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/build-push-images.yml
git commit -m "$(cat <<'EOF'
ci: add ARM64 GHCR build-and-push workflow

EOF
)"
```

---

### Task 2: Document Actions publish and `latest` Helm usage

**Files:**
- Modify: `deploy/k8s/README.md` (Hetzner ARM64 images section ~lines 123–151, and private values example ~183–202)
- Modify: `AGENTS.md` (Hetzner ARM64 deployment gate ~lines 42–50)
- Modify: `deploy/helm/jobstrainer/values-hetzner.yaml` (example `tag: phase4-example` → `tag: latest` for api/worker/bootstrap/ingestion/frontend so the checked-in Hetzner profile matches the CI contract; repositories may stay as `ghcr.io/jobstrainer-demo/...` placeholders)

**Interfaces:**
- Consumes: workflow from Task 1; existing `imagePullPolicy: Always` in `values-hetzner.yaml`
- Produces: operators know to set `VITE_API_URL`, run the workflow, and point private values at `latest` (or a short SHA for rollback)

- [ ] **Step 1: Replace the Hetzner ARM64 images section in `deploy/k8s/README.md`**

Replace the section starting at `## Hetzner ARM64 images` through the paragraph about public packages with:

```markdown
## Hetzner ARM64 images

Prefer GitHub Actions over a laptop build. The workflow
`.github/workflows/build-push-images.yml` builds backend, ingestion, and
frontend for `linux/arm64` on native ARM runners and pushes to GHCR.

One-time setup:

1. In the GitHub repo: **Settings → Secrets and variables → Actions → Variables**
2. Add `VITE_API_URL` = `https://api.<your-domain>` (public URL; not a secret)
3. Ensure GHCR packages will be pullable by the cluster (public packages, or a
   pull secret via `values-hetzner-private.yaml`)

Publish:

1. Actions → **Build and push images** → Run workflow
2. Wait until all three build jobs are green (re-run if any leg failed before
   upgrading the cluster)
3. Each package is tagged `latest` and a 7-character git SHA; older SHA tags
   are pruned so at most two SHA tags remain per package (`latest` is kept).
   Untagged digests may linger until GHCR garbage-collects them.

Cluster pull of `latest` requires `imagePullPolicy: Always` (already set in
`values-hetzner.yaml`). After a successful publish, `helm upgrade` (or a
rollout restart) picks up the new digest. To roll back, temporarily set the
image `tag` to a retained short SHA.

### Laptop fallback

Build and push from the repository root only if Actions is unavailable.
Replace `OWNER`, `TAG`, and `api.example.com`:

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

The frontend API URL is embedded at build time. Update the `VITE_API_URL`
Actions variable (or the laptop `--build-arg`) and rebuild when the public API
hostname changes.

If packages under `ghcr.io/OWNER/` are private, create a pull secret and attach
it through `values-hetzner-private.yaml` (or make the packages public for the
portfolio demo). Public packages need no `imagePullSecrets`.
```

- [ ] **Step 2: Update the private values example to use `latest`**

In the same README, under `## Hetzner Helm deployment`, change the example image tags from date pins like `"2026-07-27"` to `latest`:

```yaml
bootstrap:
  image: { repository: ghcr.io/loryschi/jobstrainer-backend, tag: latest }
api:
  image: { repository: ghcr.io/loryschi/jobstrainer-backend, tag: latest }
worker:
  image: { repository: ghcr.io/loryschi/jobstrainer-backend, tag: latest }
ingestion:
  image: { repository: ghcr.io/loryschi/jobstrainer-ingestion, tag: latest }
frontend:
  image: { repository: ghcr.io/loryschi/jobstrainer-frontend, tag: latest }
ingress:
  frontendHost: app.example.com
  apiHost: api.example.com
certManager:
  email: ops@example.com
```

- [ ] **Step 3: Align `values-hetzner.yaml` example tags with `latest`**

In `deploy/helm/jobstrainer/values-hetzner.yaml`, set every app `image.tag` currently `phase4-example` to `latest` (bootstrap, api, worker, ingestion, frontend). Leave placeholder repositories as-is; private overlay still overrides `repository`.

- [ ] **Step 4: Update `AGENTS.md` Hetzner gate**

Replace the `### Hetzner ARM64 deployment gate` subsection with:

```markdown
### Hetzner ARM64 deployment gate

Before deploying the Hetzner profile, publish backend, ingestion, and frontend
images for `linux/arm64` via GitHub Actions (**Build and push images**
workflow; see `deploy/k8s/README.md`). Set repository variable `VITE_API_URL`
first. Laptop `docker buildx build --platform linux/arm64` remains a fallback.
The backend image includes `pg_dump` and `rclone` for the worker's nightly
Postgres backup loop. The ingestion image is the highest-risk component because
it includes Playwright and python-jobspy/tls-client. If the ARM64 gate fails,
do not deploy under emulation; switch the infrastructure profile to x86 and
revisit the budget.
```

- [ ] **Step 5: Sanity-check docs still mention Always + latest together**

```bash
rg -n "imagePullPolicy: Always|tag: latest|Build and push images|VITE_API_URL" \
  deploy/k8s/README.md \
  deploy/helm/jobstrainer/values-hetzner.yaml \
  AGENTS.md
```

Expected: hits in all three files for the new wording / `latest` tags / Always.

- [ ] **Step 6: Commit**

```bash
git add deploy/k8s/README.md deploy/helm/jobstrainer/values-hetzner.yaml AGENTS.md
git commit -m "$(cat <<'EOF'
docs: prefer Actions for GHCR ARM64 image publish

EOF
)"
```

---

### Task 3: Operator verification (manual)

**Files:**
- None (runtime verification against GitHub + GHCR)

**Interfaces:**
- Consumes: merged workflow + `VITE_API_URL` variable
- Produces: evidence that three packages exist with `latest` + SHA and that a second run prunes older SHA tags

- [ ] **Step 1: Set the repository variable**

In GitHub: Settings → Secrets and variables → Actions → Variables → New  
Name: `VITE_API_URL`  
Value: your public API URL (e.g. `https://api.example.com`)

- [ ] **Step 2: Push the branch (if not on the default branch GitHub can run from) and dispatch**

```bash
gh workflow run "Build and push images" --ref "$(git branch --show-current)"
gh run watch
```

Expected: three green `Build *` jobs; then green `Prune old SHA tags` jobs.

- [ ] **Step 3: Confirm tags on one package**

```bash
OWNER=$(gh repo view --json owner --jq '.owner.login' | tr '[:upper:]' '[:lower:]')
# Browser: https://github.com/users/OWNER/packages/container/jobstrainer-backend/versions
# Or crane/skopeo if installed:
# crane ls ghcr.io/${OWNER}/jobstrainer-backend
```

Expected: `latest` and the short SHA of the commit that was built.

- [ ] **Step 4: Dispatch a second time and confirm prune**

Run the workflow again after a new commit (or the same commit — a second SHA tag only appears if the SHA differs; to exercise prune, run from two different commits). After two distinct SHAs exist, a third distinct SHA publish should leave only two SHA tags plus `latest`.

Expected: at most two 7-char hex tags per package, plus `latest`.

- [ ] **Step 5: No code commit** unless verification found a bug — then fix in a follow-up commit on the workflow file.

---

## Self-review checklist (plan author)

1. **Spec coverage:** workflow path, dispatch-only, ARM runner, all three images, `VITE_API_URL` variable + fail-if-empty, `latest`+SHA, prune last-2 SHA, docs (README + AGENTS), Helm `latest`/`Always`, no tests/deploy — all mapped to tasks.
2. **Placeholders:** none intentional; frontend `build-args` has an implementer note if the conditional expression misbehaves.
3. **Consistency:** package names and contexts match Phase 4 / Dockerfiles; `values-hetzner.yaml` already has `imagePullPolicy: Always`.
