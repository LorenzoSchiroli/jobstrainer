# AWS Demo Dump Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `demo-up-aws` / `demo-down-aws` that restore/promote `dumps/jobstrainer.current.dump` via Fargate+S3 and tear the AWS OpenTofu stack down to ~zero residual cost.

**Architecture:** S3 staging bucket + ECS Fargate `pgtools` task (postgres:16 + AWS CLI) dump/restore private RDS; laptop scripts orchestrate tofu, pause writers (ECS + EventBridge + API autoscaling min), S3 sync, RunTask, validate/promote.

**Tech Stack:** OpenTofu, AWS ECS/S3/Secrets Manager/EventBridge Scheduler CLI, bash, Docker/GHCR.

## Global Constraints

- Same dump file as Hetzner: `dumps/jobstrainer.current.dump`
- No DNS / Cloudflare / Hetzner changes in these scripts
- Abort `tofu destroy` if dump/validate/promote fails
- Secrets Manager `recovery_window_in_days = 0` for showcase secrets
- `pgtools` image: `linux/amd64` on GHCR; `var.pgtools_image`

## File map

| Path | Role |
|------|------|
| `deploy/infra/aws/docker/pgtools/*` | Dump/restore image |
| `deploy/infra/aws/dump.tf` | S3 + dump task def + IAM |
| `deploy/infra/aws/secrets.tf` | recovery window 0 |
| `deploy/scripts/lib/aws.sh` | AWS helpers |
| `deploy/scripts/demo-up-aws` / `demo-down-aws` | Operator entrypoints |
| `.github/workflows/build-push-images.yml` | Build `jobstrainer-pgtools` |
| READMEs | Operator docs |

---

### Task 1: pgtools image + OpenTofu dump stack

**Files:**
- Create: `deploy/infra/aws/docker/pgtools/Dockerfile`, `entrypoint.sh`
- Create: `deploy/infra/aws/dump.tf`
- Modify: `secrets.tf`, `variables.tf`, `outputs.tf`, `ecs.tf` (log group), `terraform.tfvars.example`, `build-push-images.yml`

- [ ] **Step 1:** Add Dockerfile (`FROM postgres:16`, AWS CLI v2) and `entrypoint.sh` modes `dump` / `restore` (strip `+asyncpg` from `DATABASE_URL`; `pg_restore` exit ≤1 + `SELECT 1 FROM jobs`).
- [ ] **Step 2:** Add S3 bucket (`force_destroy`), dump task role (S3 R/W), task definition (secrets: `DATABASE_URL`; env `DUMP_S3_URI`), outputs; set secret recovery windows to 0; variable `pgtools_image`.
- [ ] **Step 3:** Add matrix entry `jobstrainer-pgtools` + prune list.
- [ ] **Step 4:** `tofu validate` in `deploy/infra/aws`.

### Task 2: Scripts

**Files:**
- Create: `deploy/scripts/lib/aws.sh`, `demo-up-aws`, `demo-down-aws`

- [ ] **Step 1:** Helpers: tofu output wrappers, RunTask+wait, pause/resume writers (api autoscaling min→0, worker desired 0, EventBridge schedule DISABLED via get+update), S3 upload/download.
- [ ] **Step 2:** `demo-up-aws` per spec §5.2; `demo-down-aws` per §5.3; chmod +x.

### Task 3: Docs

**Files:**
- Modify: `deploy/infra/aws/README.md`, `deploy/infra/hetzner/README.md`, `deploy/k8s/README.md`
- Update design status to implemented

- [ ] **Step 1:** Document demo dump lifecycle, pgtools image, post-destroy checklist (incl. S3 + Secrets Manager).
