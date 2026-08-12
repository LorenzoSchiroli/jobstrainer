# AWS ECS Managed Showcase — Design

**Date:** 2026-08-11  
**Status:** Design (pre-implementation)  
**Author:** lschiroli

> Complements Hetzner k8s Phase 4
> (`docs/superpowers/specs/2026-07-27-k8s-phase4-hetzner-design.md`) and the
> cloud-agnostic Helm layering
> (`docs/superpowers/specs/2026-08-04-cloud-agnostic-helm-values-design.md`).
> This design is the **AWS** deploy path: managed AWS services, not EKS/Helm.

## 1. Goal

Provide a showcase-then-kill AWS deployment of jobstrainer that:

- keeps **Hetzner on Kubernetes/Helm**;
- on AWS, prefers **managed AWS primitives** (ECS Fargate, RDS, OpenSearch
  Service, ALB, ACM, Secrets Manager, EventBridge);
- reuses the **same application images** from **GHCR**;
- serves the public site on **jobsifty.com** via existing **Cloudflare** DNS,
  with only one stack live at a time (flip records between Hetzner and AWS);
- stays cheap enough for short demos (hourly billing, destroy when done).

Success looks like:

- OpenTofu under `deploy/infra/aws/` brings up a working stack;
- `app.jobsifty.com` / `api.jobsifty.com` work over HTTPS after a DNS flip;
- search/ingestion/worker behave as on Hetzner against RDS + managed OpenSearch;
- `tofu destroy` (plus DNS flip back) leaves no meaningful ongoing AWS cost.

## 2. Constraints and decisions

- **No EKS / no Helm on AWS.** K8s remains the Hetzner (and kind) path only.
- **ECS on Fargate** for all containers (frontend, api, worker, one-shot tasks).
- **RDS Postgres** (not Aurora), **single-AZ**, small instance class.
- **Amazon OpenSearch Service** (provisioned domain), **one small data node**,
  single-AZ — not OpenSearch Serverless (OCU minimum is too expensive for this
  size). Node/instance scaling is manual via OpenTofu later if ever needed.
- **Images: GHCR only** for now (no ECR). ECS pulls with a stored GitHub
  credential when repos are private.
- **Frontend stays an ECS nginx task** (same image as Hetzner). S3 + CloudFront
  is an explicit future option, not v1.
- **Mostly single-AZ for demo cost** (accepted SPOF for RDS/OpenSearch). **Exception:** an ALB requires subnets in **two AZs**, so the VPC still has two public and two private subnets; data plane stays single-AZ and **one NAT Gateway** handles egress.
- **One NAT Gateway** for private-subnet egress (GHCR pulls, Groq, scraping).
- **DNS:** reuse `app.jobsifty.com` / `api.jobsifty.com` (and apex/www as on
  Hetzner). Cloudflare records point at the AWS ALB while AWS is live; never
  run Hetzner and AWS publicly at the same time.
- **TLS:** ACM certificates on the ALB (replaces cert-manager on this path).
- **Backups on AWS:** RDS automated backups/snapshots. Do not set
  `BACKUP_SBOX_*`; existing `backup_worker` already no-ops when unset.
- **Paid AWS account + credits:** Free plan may block or hobble this stack;
  expect Paid plan with Free Tier credits as a cushion, plus a low budget alert.
- **Out of scope v1:** EKS, ECR, Aurora, OpenSearch Serverless, multi-AZ,
  Lambda/SQS scrape fan-out, S3 frontend, Step Functions for ingestion
  concurrency hardening beyond a simple schedule.

## 3. Architecture

```
Cloudflare DNS (jobsifty.com, DNS-only)
  app.jobsifty.com  ──┐
  api.jobsifty.com  ──┼─→ ALB (public) + ACM
  apex / www        ──┘         │
                    ┌───────────┴────────────┐
                    ▼                        ▼
           frontend (Fargate)         api (Fargate, autoscaled)
                                              │
                    worker (Fargate, desired=1)
                    EventBridge → RunTask: ingestion
                    RunTask once: bootstrap
                                              │
                         ┌────────────────────┼────────────────────┐
                         ▼                    ▼                    ▼
                   RDS Postgres      OpenSearch Service      external APIs
                   (private)         (private, HTTPS)        (via NAT)
```

### 3.1 Component map

| Role | AWS resource | Notes |
|------|--------------|-------|
| frontend | ECS Service (Fargate) | GHCR nginx image; ALB target for `app.*` |
| api | ECS Service (Fargate) | Autoscale on CPU and/or ALB request count |
| worker | ECS Service (Fargate) | `desiredCount = 1`; reconcile + retention |
| ingestion | Task definition + EventBridge Scheduler → `RunTask` | Same command as Helm CronJob |
| bootstrap | Task definition + one-shot `RunTask` | Migrations + OpenSearch index/pipeline |
| Postgres | RDS Postgres, single-AZ, small | Private; `DATABASE_URL` into tasks |
| Search | OpenSearch Service, 1× small node | HTTPS + auth; see §5 |
| Secrets | Secrets Manager | Injected into task definitions; SSM only if a later need appears |
| Edge | ALB + ACM | HTTP→HTTPS redirect |
| Infra | OpenTofu in `deploy/infra/aws/` | VPC, ECS, RDS, OS, ALB, IAM, EventBridge, logs |
| Logs | CloudWatch Logs | `awslogs` on all tasks |

### 3.2 EventBridge → RunTask

Kubernetes CronJob/Job equivalents on ECS:

- **Ingestion:** EventBridge schedule (mirror Helm cadence, e.g. every 2 hours)
  starts one Fargate task; container runs
  `python -m ingestion.pipeline …` and exits.
- **Bootstrap:** not periodic — one-shot `RunTask` after RDS/OpenSearch are
  available (OpenTofu provisioner and/or documented manual CLI).

Long-running processes (frontend, api, worker) are ECS **Services**, not
RunTask.

## 4. Networking and security

```
VPC (two AZs for ALB; data plane single-AZ)
  public subnets (2 AZs):  ALB, one NAT Gateway
  private subnets (2 AZs): Fargate tasks; RDS + OpenSearch pinned to AZ-a
```

| Concern | Choice |
|---------|--------|
| Subnets | Placement and routing (public vs private) |
| Security groups | Who may talk to whom (ALB ← internet; tasks ← ALB; RDS/OS ← tasks only) |
| Service discovery | ALB for public HTTP; RDS/OS hostnames via env (no mesh) |
| OpenSearch SG | Allow 443 from app task SG only |
| RDS SG | Allow 5432 from app task SG only |
| GHCR pull | Task execution role + secret with GitHub credentials |
| IAM task roles | Least privilege: logs, read secrets; data plane auth via URL/password where applicable |

## 5. Application and config changes

### 5.1 Environment

Reuse existing env keys where possible (`DATABASE_URL`, `SECRET_KEY`, `GROQ_*`,
`CORS_ORIGINS=https://app.jobsifty.com`, etc.). Frontend continues to bake
`VITE_API_URL=https://api.jobsifty.com` at image build time.

Omit `BACKUP_SBOX_*` on AWS.

### 5.2 OpenSearch client

Today `init_opensearch()` uses plain `AsyncOpenSearch(hosts=[url])` suitable for
local/k8s with security disabled.

Managed OpenSearch Service exposes **HTTPS** and requires **authentication**
(master user/password or IAM). Design:

- Keep `OPENSEARCH_URL` (https URL for AWS).
- Add optional `OPENSEARCH_USER` / `OPENSEARCH_PASSWORD` (or a single secret
  JSON) when auth is required.
- Local/Hetzner remain HTTP without auth when those vars are unset.

Index name, hybrid pipeline, and mappings stay the same.

### 5.3 Capacity expectations

~10k–1M job/company rows are within a small single-node OpenSearch domain and a
small RDS instance for this access pattern; retention (~30 days) remains the
primary data bound. User/QPS scale is primarily **API Fargate autoscaling**
(and rerank cost), not OpenSearch node autoscaling.

### 5.4 Worker

`backup_worker` already logs and idles when `BACKUP_SBOX_*` is unset. AWS relies
on RDS snapshots instead of Storage Box.

## 6. DNS and lifecycle

1. `tofu apply` creates the stack; run bootstrap `RunTask`.
2. Flip Cloudflare records for `app` / `api` (and apex/www as needed) from the
   Hetzner ingress IP to the ALB (CNAME/alias to ALB DNS name).
3. Demo; scale API tasks if needed.
4. Flip DNS back to Hetzner when leaving AWS.
5. `tofu destroy`; confirm no ALB/NAT/RDS/OpenSearch/ECS leftovers.
6. Account budget alert (e.g. $5–10) as a safety net.

Billing is hourly/pro-rated; destroy stops the meter (aside from tiny leftover
storage if any snapshots are retained by choice).

## 7. Repo layout

```
deploy/infra/aws/          # OpenTofu: VPC, ECS, RDS, OpenSearch, ALB, IAM, …
deploy/infra/aws/README.md # apply, bootstrap RunTask, DNS flip, destroy
```

Hetzner (`deploy/infra/hetzner/`) and Helm chart remain the k8s path. The
cloud-agnostic Helm values design’s illustrative `values-aws.yaml` is **not**
used for this AWS path (no Helm on AWS).

## 8. Non-goals

- Porting the Helm chart to EKS
- ECR mirroring (may revisit later)
- Aurora, OpenSearch Serverless, multi-AZ HA
- S3 + CloudFront frontend
- Parallel scrape orchestration via Lambda/SQS
- Running Hetzner and AWS public endpoints simultaneously

## 9. Implementation follow-ups (for the plan)

1. Scaffold `deploy/infra/aws/` OpenTofu modules/resources.
2. ECS task definitions/services for frontend, api, worker; GHCR pull secret.
3. RDS + OpenSearch domain + security groups + secrets wiring.
4. ALB + ACM + Cloudflare flip runbook.
5. EventBridge schedule for ingestion; bootstrap RunTask docs/hook.
6. Backend OpenSearch client HTTPS + optional basic auth.
7. Budget alarm + destroy checklist in README.
