# AWS Demo Dump Lifecycle — Design

**Date:** 2026-08-13  
**Status:** Implemented  
**Author:** lschiroli

> Complements `docs/superpowers/specs/2026-08-02-demo-dump-lifecycle-design.md`
> (Hetzner) and `docs/superpowers/specs/2026-08-11-aws-ecs-managed-showcase-design.md`.
> Same dump-file source of truth; AWS bring-up/tear-down without kubectl/Helm.

## 1. Goal

Give AWS the same operator story as Hetzner:

- **`demo-up-aws`** brings up the ECS/RDS/OpenSearch stack and restores
  `dumps/jobstrainer.current.dump` into RDS;
- **`demo-down-aws`** dumps RDS back into that file (promoting/archiving as
  today), then destroys the OpenTofu stack so **ongoing AWS cost returns to
  essentially zero** (no leftover NAT, ALB, RDS, OpenSearch, EIPs, schedules).

While the stack is up, normal AWS showcase costs apply. “Zero cost” means
**after a successful destroy**, not free creation.

Success looks like:

- after `demo-down-aws`, the laptop holds an updated current dump and
  `tofu destroy` has removed billable stack resources;
- after `demo-up-aws`, RDS matches that dump and search works once reconcile
  reindexes OpenSearch;
- scripts never touch Cloudflare/Hetzner DNS or Hetzner OpenTofu.

## 2. Constraints and decisions

- **AWS-only.** No DNS flip, no Hetzner kubeconfig/Helm, no shared
  `demo-up --aws` flag soup — separate `demo-up-aws` / `demo-down-aws`.
- **Same dump file** as Hetzner: `dumps/jobstrainer.current.dump` (+ archive
  on promote). One writer rule still applies across clouds.
- **Postgres full dump only.** OpenSearch is derived; reconcile rebuilds it.
- **RDS stays private.** Dump/restore via **Fargate RunTask** + **S3 staging**,
  not laptop SG holes or Lambda (15‑minute limit).
- **Abort destroy** if dump/validate/promote fails (parity with Hetzner
  `demo-down`).
- **Pause writers** around restore (and preferably dump): ECS api/worker
  desired count 0; disable EventBridge ingestion schedule; restore previous
  state afterward.
- **Interactive tofu by default**; `--yes` → `-auto-approve`.
- **Showcase secret recovery:** set Secrets Manager
  `recovery_window_in_days = 0` (or equivalent) so destroy does not leave a
  30‑day recoverable secret billing footprint.
- **Out of scope:** DNS automation, Lambda dump path, OpenSearch dump, dump
  merge, kind/compose AWS wrappers.

## 3. Architecture

```
Laptop                          AWS (while up)
──────                          ──────────────
dumps/jobstrainer.current.dump
        │ upload                S3 dump bucket (force_destroy)
        ├───────────────────►   │
        │                       ▼
        │                   Fargate dump/restore task
        │                   (postgres:16, private subnets)
        │                       │
        │                       ▼
        │                   RDS Postgres
        │
        │ download ◄──────── S3 after pg_dump
        ▼
   validate + promote
        │
        └──► tofu destroy  →  empty residual billables
```

## 4. OpenTofu additions (`deploy/infra/aws/`)

| Resource | Role |
|----------|------|
| S3 bucket | Staging object e.g. `demo/jobstrainer.dump`; `force_destroy = true`; short lifecycle expire optional |
| IAM for dump task | Read app secret (`DATABASE_URL`); read/write dump bucket |
| ECS task definition(s) | Image `postgres:16` (public); command selected by override: dump vs restore |
| Outputs | `dump_bucket_name`, `dump_task_definition_arn` (plus existing cluster/subnet/SG outputs) |

Dump task steps (container):

1. Load `DATABASE_URL` from env (injected from Secrets Manager like other tasks).
2. Mode via argv/env: `dump` → `pg_dump -Fc` → `aws s3 cp` to staging key;
   `restore` → `aws s3 cp` from staging → `pg_restore --clean --if-exists --no-owner`.
3. Exit non-zero on failure so the scripts abort destroy/up.

**Image (pinned):** `deploy/infra/aws/docker/pgtools/` — `FROM postgres:16`, install
AWS CLI v2, add `entrypoint.sh`. Build/push **linux/amd64** to GHCR (same gate
as other cloud images) and pass URI as `var.pgtools_image` (default in tfvars
example). No Lambda; no public RDS.

## 5. Scripts

### 5.1 Shared

Extend `deploy/scripts/lib/common.sh` and/or add `deploy/scripts/lib/aws.sh`:

- `AWS_DIR=${REPO_ROOT}/deploy/infra/aws`
- Helpers: require AWS CLI + tofu; `aws_pause_writers` / `aws_resume_writers`;
  `aws_run_dump_task` / `aws_run_restore_task`; wait for ECS task stopped +
  exit code 0; `aws s3 cp` wrappers.
- Reuse `CURRENT_DUMP`, `promote_dump`, `validate_dump`.

### 5.2 `demo-up-aws`

1. Fail if `dumps/jobstrainer.current.dump` missing (hint `seed-dump`).
2. Fail if `deploy/infra/aws/terraform.tfvars` missing.
3. `tofu apply` in `AWS_DIR` (unless `--yes`).
4. Wait until RDS available and ECS services stable enough to run tasks.
5. Bootstrap RunTask (same as README: migrations + `backend.bootstrap`).
6. Record api/worker desired counts; set desired=0; disable EventBridge
   ingestion schedule.
7. `aws s3 cp` current dump → staging key.
8. Restore RunTask; fail closed (leave writers paused) on error.
9. Resume api/worker desired counts; re-enable ingestion schedule.
10. Do not touch DNS. OpenSearch refill via worker reconcile.

### 5.3 `demo-down-aws`

1. Require AWS stack reachable (tofu state / cluster exists).
2. Pause writers + disable ingestion schedule.
3. Dump RunTask → staging key.
4. `aws s3 cp` staging → temp on laptop.
5. Validate + promote (archive previous current).
6. **Only then** `tofu destroy` (unless `--yes`).
7. On dump/validate/promote failure: **do not destroy**; leave stack up.

## 6. Zero residual cost after destroy

Destroy must remove (already mostly in module; tighten where noted):

| Resource | Note |
|----------|------|
| NAT + EIP | Highest idle risk if orphaned |
| ALB | |
| ECS services, tasks, cluster | |
| EventBridge schedule | |
| RDS | `skip_final_snapshot = true` already |
| OpenSearch domain | |
| S3 dump bucket | `force_destroy` so destroy empties objects |
| Secrets Manager secret | `recovery_window_in_days = 0` for showcase |
| CloudWatch log groups | Prefer delete with stack or document residual |

Document a post-destroy console spot-check (NAT, EIP, OpenSearch, RDS) in
`deploy/infra/aws/README.md` and point Hetzner README / k8s README at the AWS
scripts symmetrically.

## 7. Non-goals

- Managing Cloudflare / `manage_dns_flip` inside these scripts
- Calling Hetzner tofu or Helm
- Lambda-based dump/restore
- Dumping or restoring OpenSearch
- Changing the Hetzner `demo-up` / `demo-down` contracts

## 8. Implementation follow-ups (for the plan)

1. OpenTofu: S3 bucket, dump task role/definition, secret recovery window, outputs.
2. `lib/aws.sh` + `demo-up-aws` / `demo-down-aws`.
3. README updates (AWS + cross-links from Hetzner/k8s dump lifecycle sections).
4. Manual test notes: up → smoke → down → confirm empty billables + dump file.
