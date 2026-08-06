# Demo Dump Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `seed-dump` / `demo-up` / `demo-down` scripts so one gitignored `dumps/jobstrainer.current.dump` is the operator source of truth for Hetzner demo data.

**Architecture:** Thin bash scripts under `deploy/scripts/` share `lib/common.sh` for repo paths, kubeconfig defaults, dump validation/promote, and cluster dump/restore via pod file + `kubectl cp`. Scripts call existing `tofu` / `helm` / `kubectl` / `pg_restore`; they do not replace the worker Storage Box backup loop.

**Tech Stack:** bash (`set -euo pipefail`), Docker Compose, kubectl, Helm 3, OpenTofu, local `pg_dump`/`pg_restore`

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-02-demo-dump-lifecycle-design.md` (2026-08-04 amendments).
- One current dump; archive previous on overwrite; no row merge.
- Default kubeconfig: `deploy/infra/hetzner/${CLUSTER_NAME:-jobstrainer}_kubeconfig.yaml`.
- Helm `-f` stack: `values.yaml` + `values-cloud.yaml` + `values-hetzner.yaml` + repo-root `values-private.yaml`.
- Pause api/worker and suspend ingestion CronJob around `pg_restore --clean`.
- Do not commit dump binaries; add `dumps/` to `.gitignore`.
- Do not commit unless the user asks.

---

## File structure

| File | Responsibility |
|------|----------------|
| `deploy/scripts/lib/common.sh` | Paths, kubeconfig, validate/promote, cluster dump/restore helpers |
| `deploy/scripts/seed-dump` | Seed current dump from compose, file, or cluster |
| `deploy/scripts/demo-up` | tofu apply → secret → helm → pause → restore → unpause |
| `deploy/scripts/demo-down` | cluster dump → promote → tofu destroy |
| `.gitignore` | Ignore `dumps/` |
| `deploy/infra/hetzner/README.md` | Document scripts + kubeconfig path |
| `deploy/k8s/README.md` | Short pointer to demo lifecycle |

---

### Task 1: Shared library + seed-dump

**Files:**
- Create: `deploy/scripts/lib/common.sh`
- Create: `deploy/scripts/seed-dump`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `repo_root`, `CURRENT_DUMP`, `ARCHIVE_DIR`, `default_kubeconfig`, `require_pg_client`, `validate_dump`, `promote_dump`, `cluster_pg_dump_to`, `cluster_pg_restore_from`

- [ ] **Step 1: Add `dumps/` to `.gitignore`**

Append:

```
# Canonical Postgres dump lifecycle (never commit binaries)
dumps/
```

- [ ] **Step 2: Create `deploy/scripts/lib/common.sh`**

Implement helpers matching the spec: resolve `REPO_ROOT` from caller script dir (`../..` from `deploy/scripts/<name>`), set dump paths, default kubeconfig under `deploy/infra/hetzner/`, `require_cmd`, `require_pg_client`, `validate_dump FILE`, `promote_dump FILE` (archive current with UTC timestamp, `mkdir -p` archive), `ensure_kubeconfig` (error if file missing), `cluster_pg_dump_to DEST` (pod `/tmp/jobstrainer.dump` then `kubectl cp`), `cluster_pg_restore_from SRC` (cp then `pg_restore --clean --if-exists --no-owner`).

- [ ] **Step 3: Create executable `deploy/scripts/seed-dump`**

Parse `--from compose|file|cluster` (default compose), `--file PATH` for file mode. Compose path: `docker compose exec -T postgres pg_dump -U postgres -Fc jobstrainer` to temp. File path: copy to temp. Cluster path: `cluster_pg_dump_to`. Then validate + promote.

- [ ] **Step 4: Smoke-check syntax**

Run: `bash -n deploy/scripts/lib/common.sh && bash -n deploy/scripts/seed-dump`  
Expected: exit 0

---

### Task 2: demo-up and demo-down

**Files:**
- Create: `deploy/scripts/demo-up`
- Create: `deploy/scripts/demo-down`

**Interfaces:**
- Consumes: helpers from Task 1
- Produces: operator-facing up/down lifecycle

- [ ] **Step 1: Create `deploy/scripts/demo-up`**

Flags: `--yes` → tofu `-auto-approve`. Flow per spec §4.2: require current dump + `values-private.yaml` + pg client; tofu apply in `deploy/infra/hetzner`; set `KUBECONFIG` if unset; create secret only if missing (`.env.public` + `.env` then patch three cluster URLs); helm upgrade with four `-f` files; wait postgres Ready + bootstrap Job complete; save/scale api+worker to 0 and suspend ingestion; restore; on restore success restore scale/suspend; on restore failure print recovery commands and exit non-zero without scaling up.

- [ ] **Step 2: Create `deploy/scripts/demo-down`**

Flags: `--yes` → tofu `-auto-approve`. Flow per spec §4.3: ensure kubeconfig/cluster; dump to temp; validate; promote; only then tofu destroy in `deploy/infra/hetzner`.

- [ ] **Step 3: Smoke-check syntax**

Run: `bash -n deploy/scripts/demo-up && bash -n deploy/scripts/demo-down`  
Expected: exit 0

---

### Task 3: Docs

**Files:**
- Modify: `deploy/infra/hetzner/README.md`
- Modify: `deploy/k8s/README.md`

- [ ] **Step 1: Document in Hetzner README**

Add section: kubeconfig default path `jobstrainer_kubeconfig.yaml` (for default `cluster_name`), warning against bare `tofu destroy`, and the three scripts with typical order `seed-dump` → `demo-up` → … → `demo-down`.

- [ ] **Step 2: Pointer in k8s README**

After Hetzner Helm deployment section (or backup section), add a short “Demo dump lifecycle” paragraph linking to `deploy/infra/hetzner/README.md` and naming the three scripts / `dumps/jobstrainer.current.dump`.

---

## Spec coverage

| Spec item | Task |
|-----------|------|
| `dumps/` + archive layout | 1 |
| `seed-dump` compose/file/cluster | 1 |
| `demo-up` tofu/secret/helm/pause/restore | 2 |
| `demo-down` dump gate then destroy | 2 |
| gitignore + READMEs | 1, 3 |
| Storage Box unchanged | (no code change) |
