# AWS ECS Managed Showcase Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship an OpenTofu-managed AWS stack (ECS Fargate + RDS + OpenSearch Service + ALB) that runs the existing GHCR images and can take over `jobsifty.com` via a Cloudflare DNS flip for showcase-then-kill demos.

**Architecture:** Hetzner stays Helm/k8s. AWS has no Helm/EKS. OpenTofu under `deploy/infra/aws/` owns VPC, ECS services (frontend/api/worker), EventBridge→RunTask (ingestion), one-shot bootstrap RunTask, RDS Postgres, a single-node OpenSearch Service domain, ALB+ACM, Secrets Manager, and a budget. Backend gains optional OpenSearch basic auth for the managed HTTPS endpoint.

**Tech Stack:** OpenTofu ≥ 1.10.1, AWS provider, Cloudflare provider (DNS validation + flip docs), ECS Fargate, RDS Postgres, OpenSearch Service, ALB, ACM, Secrets Manager, EventBridge Scheduler, Python/`opensearch-py`, pytest

**Spec:** `docs/superpowers/specs/2026-08-11-aws-ecs-managed-showcase-design.md`

## Global Constraints

- No EKS and no Helm on AWS.
- ECS launch type is Fargate for every task.
- RDS Postgres single-AZ (not Aurora); OpenSearch Service provisioned single-node (not Serverless).
- Images from GHCR only (no ECR in v1).
- Frontend remains the nginx ECS service (no S3/CloudFront in v1).
- Secrets live in AWS Secrets Manager.
- Do not set `BACKUP_SBOX_*` on AWS; rely on RDS backups.
- Only one public stack at a time: Cloudflare flips `app`/`api` (and apex/www) between Hetzner IP and the AWS ALB.
- **ALB exception:** an Application Load Balancer requires subnets in **two AZs**. Create two public (and two private) subnets; keep **RDS and OpenSearch single-AZ** and use **one NAT Gateway** to control cost.
- Prefer smallest demo sizes: e.g. `db.t4g.micro` or `db.t4g.small`, OpenSearch `t3.small.search`, Fargate task sizes matching Helm requests where practical.
- Out of scope: Aurora, OS Serverless, multi-AZ data plane, ECR, Lambda scrape fan-out, S3 frontend.

---

## File structure

| File | Responsibility |
|------|----------------|
| `backend/backend/opensearch_client.py` | HTTPS + optional basic auth when `OPENSEARCH_USER`/`OPENSEARCH_PASSWORD` set |
| `backend/tests/test_opensearch_client.py` | Tests for auth/ssl kwargs vs plain local client |
| `deploy/infra/aws/versions.tf` | OpenTofu + provider version floors |
| `deploy/infra/aws/providers.tf` | AWS + Cloudflare providers |
| `deploy/infra/aws/variables.tf` | Region, domain, GHCR images, sizes, secrets inputs |
| `deploy/infra/aws/terraform.tfvars.example` | Placeholder tfvars (no real secrets) |
| `deploy/infra/aws/vpc.tf` | VPC, 2 AZ subnets, IGW, one NAT, routes |
| `deploy/infra/aws/security_groups.tf` | ALB, tasks, RDS, OpenSearch SGs |
| `deploy/infra/aws/rds.tf` | Postgres instance + subnet group |
| `deploy/infra/aws/opensearch.tf` | Single-node domain |
| `deploy/infra/aws/secrets.tf` | Secrets Manager secrets + random passwords |
| `deploy/infra/aws/iam.tf` | ECS task execution + task roles; GHCR pull |
| `deploy/infra/aws/ecs.tf` | Cluster, task defs, services, log groups |
| `deploy/infra/aws/alb.tf` | ALB, target groups, listeners, ACM |
| `deploy/infra/aws/scheduler.tf` | EventBridge schedule → ingestion RunTask |
| `deploy/infra/aws/dns.tf` | Optional Cloudflare records for ACM validation / ALB flip helpers |
| `deploy/infra/aws/budget.tf` | Cost budget + email subscriber |
| `deploy/infra/aws/outputs.tf` | ALB DNS, RDS endpoint, OS endpoint, runbook values |
| `deploy/infra/aws/README.md` | Apply, bootstrap, DNS flip, destroy checklist |

---

### Task 1: OpenSearch client — optional HTTPS basic auth

**Files:**
- Modify: `backend/backend/opensearch_client.py`
- Modify: `backend/tests/test_opensearch_client.py`

**Interfaces:**
- Consumes: `OPENSEARCH_URL` (required); `OPENSEARCH_USER` / `OPENSEARCH_PASSWORD` (optional pair)
- Produces: `init_opensearch()` constructs `AsyncOpenSearch` with `http_auth` + SSL when user/password set; unchanged plain HTTP when unset

- [ ] **Step 1: Write failing tests for auth wiring**

Add to `backend/tests/test_opensearch_client.py`:

```python
async def test_init_passes_basic_auth_when_user_password_set(monkeypatch):
    monkeypatch.setenv("OPENSEARCH_URL", "https://search.example.com")
    monkeypatch.setenv("OPENSEARCH_USER", "admin")
    monkeypatch.setenv("OPENSEARCH_PASSWORD", "secret")
    mock_client = AsyncMock()
    mock_client.indices.exists.return_value = True
    with patch("backend.opensearch_client.AsyncOpenSearch", return_value=mock_client) as ctor:
        m._client = None
        await m.init_opensearch()
    kwargs = ctor.call_args.kwargs
    assert kwargs.get("http_auth") == ("admin", "secret")
    assert kwargs.get("use_ssl") is True
    assert kwargs.get("verify_certs") is True


async def test_init_plain_http_without_auth_env(monkeypatch):
    monkeypatch.setenv("OPENSEARCH_URL", "http://localhost:9200")
    monkeypatch.delenv("OPENSEARCH_USER", raising=False)
    monkeypatch.delenv("OPENSEARCH_PASSWORD", raising=False)
    mock_client = AsyncMock()
    mock_client.indices.exists.return_value = True
    with patch("backend.opensearch_client.AsyncOpenSearch", return_value=mock_client) as ctor:
        m._client = None
        await m.init_opensearch()
    kwargs = ctor.call_args.kwargs
    assert "http_auth" not in kwargs or kwargs.get("http_auth") is None
```

- [ ] **Step 2: Run tests — expect FAIL**

Run:

```bash
cd backend && uv run pytest tests/test_opensearch_client.py::test_init_passes_basic_auth_when_user_password_set tests/test_opensearch_client.py::test_init_plain_http_without_auth_env -v
```

Expected: FAIL (kwargs not passed yet) or ctor signature mismatch.

- [ ] **Step 3: Implement minimal `init_opensearch` change**

Replace client construction in `backend/backend/opensearch_client.py` `init_opensearch` with:

```python
async def init_opensearch() -> None:
    global _client
    url = os.environ["OPENSEARCH_URL"]
    user = os.environ.get("OPENSEARCH_USER")
    password = os.environ.get("OPENSEARCH_PASSWORD")
    kwargs: dict = {"hosts": [url]}
    if user and password:
        kwargs["http_auth"] = (user, password)
        kwargs["use_ssl"] = True
        kwargs["verify_certs"] = True
    elif user or password:
        raise ValueError("OPENSEARCH_USER and OPENSEARCH_PASSWORD must both be set")
    _client = AsyncOpenSearch(**kwargs)
    # ... existing index/pipeline setup unchanged ...
```

Keep the existing `indices.exists` / `create` / `put_mapping` / pipeline `perform_request` block as-is after client creation.

- [ ] **Step 4: Run full OpenSearch client tests — expect PASS**

Run:

```bash
cd backend && uv run pytest tests/test_opensearch_client.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/backend/opensearch_client.py backend/tests/test_opensearch_client.py
git commit -m "$(cat <<'EOF'
feat(backend): support OpenSearch basic auth for managed HTTPS

EOF
)"
```

---

### Task 2: OpenTofu scaffold — versions, providers, variables

**Files:**
- Create: `deploy/infra/aws/versions.tf`
- Create: `deploy/infra/aws/providers.tf`
- Create: `deploy/infra/aws/variables.tf`
- Create: `deploy/infra/aws/terraform.tfvars.example`
- Create: `deploy/infra/aws/.gitignore` (ignore `.terraform/`, `*.tfstate*`, `terraform.tfvars`)

**Interfaces:**
- Consumes: none
- Produces: root module ready for `tofu init` with AWS + Cloudflare providers

- [ ] **Step 1: Write `versions.tf`**

```hcl
terraform {
  required_version = ">= 1.10.1"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.5"
    }
  }
}
```

- [ ] **Step 2: Write `providers.tf`**

```hcl
provider "aws" {
  region = var.aws_region
}

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}
```

- [ ] **Step 3: Write `variables.tf` with at least**

```hcl
variable "aws_region" {
  type    = string
  default = "eu-central-1"
}

variable "project" {
  type    = string
  default = "jobstrainer"
}

variable "domain" {
  type = string
}

variable "cloudflare_api_token" {
  type      = string
  sensitive = true
}

variable "cloudflare_zone_id" {
  type = string
}

variable "manage_dns_flip" {
  type        = bool
  default     = false
  description = "When true, Cloudflare app/api/apex/www point at the ALB. Keep false while Hetzner is live."
}

variable "ghcr_username" {
  type = string
}

variable "ghcr_token" {
  type      = string
  sensitive = true
}

variable "frontend_image" {
  type = string
}

variable "backend_image" {
  type = string
}

variable "ingestion_image" {
  type = string
}

variable "alert_email" {
  type = string
}

variable "budget_limit_usd" {
  type    = number
  default = 10
}

variable "rds_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "opensearch_instance_type" {
  type    = string
  default = "t3.small.search"
}
```

- [ ] **Step 4: Write `terraform.tfvars.example` and `.gitignore`**

`terraform.tfvars.example`:

```hcl
aws_region           = "eu-central-1"
domain               = "jobsifty.com"
cloudflare_zone_id   = "00000000000000000000000000000000"
manage_dns_flip      = false
ghcr_username        = "YOUR_GITHUB_USER"
frontend_image       = "ghcr.io/OWNER/jobstrainer-frontend:TAG"
backend_image        = "ghcr.io/OWNER/jobstrainer-backend:TAG"
ingestion_image      = "ghcr.io/OWNER/jobstrainer-ingestion:TAG"
alert_email          = "you@example.com"
# cloudflare_api_token / ghcr_token via TF_VAR_ or terraform.tfvars (gitignored)
```

`.gitignore`:

```
.terraform/
*.tfstate
*.tfstate.*
.terraform.lock.hcl
terraform.tfvars
crash.log
```

Keep `.terraform.lock.hcl` committed after first successful `tofu init` if the Hetzner module does (Hetzner commits the lock — **override**: commit the aws lock file like Hetzner; remove `.terraform.lock.hcl` from this gitignore).

Correct `.gitignore`:

```
.terraform/
*.tfstate
*.tfstate.*
terraform.tfvars
crash.log
```

- [ ] **Step 5: Init**

Run:

```bash
cd deploy/infra/aws && tofu init
```

Expected: providers installed; no error.

- [ ] **Step 6: Commit**

```bash
git add deploy/infra/aws/
git commit -m "$(cat <<'EOF'
chore(infra): scaffold OpenTofu AWS root module

EOF
)"
```

---

### Task 3: VPC, subnets, NAT, security groups

**Files:**
- Create: `deploy/infra/aws/vpc.tf`
- Create: `deploy/infra/aws/security_groups.tf`

**Interfaces:**
- Consumes: `var.aws_region`, `var.project`
- Produces: `aws_vpc.main`, public/private subnets in two AZs, `aws_nat_gateway.main` (one), SGs: `alb`, `ecs_tasks`, `rds`, `opensearch`

- [ ] **Step 1: Implement VPC + networking in `vpc.tf`**

Use the default VPC CIDR `10.40.0.0/16` (avoid clash with common `10.0.0.0/16` labs):

- `aws_vpc.main` with DNS hostnames enabled
- Data source `aws_availability_zones` → take first two
- Public subnets `10.40.0.0/24`, `10.40.1.0/24` with public IP on launch
- Private subnets `10.40.10.0/24`, `10.40.11.0/24`
- Internet gateway + public route table
- One EIP + one NAT in public subnet[0]; private route tables → NAT
- Tags: `Name = "${var.project}-…"`

- [ ] **Step 2: Implement security groups in `security_groups.tf`**

- `aws_security_group.alb`: ingress 80/443 from `0.0.0.0/0`; egress all
- `aws_security_group.ecs_tasks`: ingress 8080 (or frontend 80 / api 8000 — match container ports) from `alb` SG only; egress all
- `aws_security_group.rds`: ingress 5432 from `ecs_tasks` only
- `aws_security_group.opensearch`: ingress 443 from `ecs_tasks` only

Use explicit container ports consistent with Task 5 (frontend **80**, api/worker/bootstrap/ingestion **8000** only if the image listens there — backend uvicorn is **8000**; frontend nginx **80**). Prefer two listener rules and one tasks SG allowing 80 and 8000 from ALB.

- [ ] **Step 3: `tofu validate`**

Run:

```bash
cd deploy/infra/aws && tofu validate
```

Expected: Success (may need stub resources if validate requires all refs — complete files first).

- [ ] **Step 4: Commit**

```bash
git add deploy/infra/aws/vpc.tf deploy/infra/aws/security_groups.tf
git commit -m "$(cat <<'EOF'
feat(infra): add AWS VPC, NAT, and security groups

EOF
)"
```

---

### Task 4: Secrets, RDS, OpenSearch

**Files:**
- Create: `deploy/infra/aws/secrets.tf`
- Create: `deploy/infra/aws/rds.tf`
- Create: `deploy/infra/aws/opensearch.tf`

**Interfaces:**
- Consumes: private subnets[0] for single-AZ data; `ecs_tasks` SG; variables for instance sizes
- Produces: Secrets Manager secret JSON for app env; RDS endpoint; OpenSearch endpoint; master user/password for OS

- [ ] **Step 1: `secrets.tf` — generate passwords and app secret**

```hcl
resource "random_password" "db" {
  length  = 32
  special = false
}

resource "random_password" "opensearch" {
  length  = 32
  special = false
}

resource "random_password" "app_secret_key" {
  length  = 48
  special = false
}

resource "aws_secretsmanager_secret" "app" {
  name = "${var.project}/app"
}

# aws_secretsmanager_secret_version.app — JSON body filled in Task 5/6 once endpoints exist,
# or use a single version that interpolates RDS/OS addresses after those resources exist.
```

Put the full `aws_secretsmanager_secret_version` in this task **after** RDS/OS resources using interpolation (same apply is fine).

Secret JSON keys (string map):

- `DATABASE_URL` = `postgresql+asyncpg://jobstrainer:${random_password.db.result}@${aws_db_instance.main.address}:5432/jobstrainer`
- `OPENSEARCH_URL` = `https://${aws_opensearch_domain.main.endpoint}`
- `OPENSEARCH_USER` = `jobstrainer`
- `OPENSEARCH_PASSWORD` = `random_password.opensearch.result`
- `SECRET_KEY` = `random_password.app_secret_key.result`
- plus placeholders or variables for `GROQ_API_KEY`, `GROQ_MODEL_*`, `CORS_ORIGINS` (`https://app.${var.domain}`), `OFFER_QUERY`, etc. via `var.groq_api_key` and friends added to `variables.tf` as sensitive.

Add sensitive variables:

```hcl
variable "groq_api_key" {
  type      = string
  sensitive = true
}
```

Wire remaining keys from `.env.example` / `.env.public` that the containers need at runtime (match Helm `existingSecret` usage).

- [ ] **Step 2: `rds.tf`**

- `aws_db_subnet_group` spanning both private subnets (RDS API requirement) with `multi_az = false` and `availability_zone` set to the first AZ
- `aws_db_instance.main`: engine `postgres`, engine_version compatible with the project (prefer **16** unless compose pins otherwise), `instance_class = var.rds_instance_class`, `allocated_storage = 20`, `max_allocated_storage = 100`, `db_name = "jobstrainer"`, `username = "jobstrainer"`, `password = random_password.db.result`, `vpc_security_group_ids = [aws_security_group.rds.id]`, `publicly_accessible = false`, `skip_final_snapshot = true` (showcase destroy), `backup_retention_period = 7`

- [ ] **Step 3: `opensearch.tf`**

- `aws_opensearch_domain.main`:
  - `engine_version` = `"OpenSearch_2.11"` (or current 2.x supported)
  - `cluster_config`: `instance_type = var.opensearch_instance_type`, `instance_count = 1`, `zone_awareness_enabled = false`
  - `ebs_options`: enabled, `gp3`, 20 GB
  - `vpc_options`: first private subnet only + `opensearch` SG
  - `advanced_security_options` with internal user database, master user `jobstrainer` / `random_password.opensearch`
  - `encrypt_at_rest`, `node_to_node_encryption`, `domain_endpoint_options` enforce HTTPS
  - Access policy allowing the ECS task role or VPC principals as required for fine-grained access; for master-user HTTP basic auth from within VPC, use a domain access policy that allows the account / VPC traffic (follow current AWS OpenSearch VPC domain + FGAC docs — domain policy `Allow` for `es:ESHttp*` from account, auth via master user)

- [ ] **Step 4: Validate**

```bash
cd deploy/infra/aws && tofu validate
```

- [ ] **Step 5: Commit**

```bash
git add deploy/infra/aws/secrets.tf deploy/infra/aws/rds.tf deploy/infra/aws/opensearch.tf deploy/infra/aws/variables.tf
git commit -m "$(cat <<'EOF'
feat(infra): add RDS, OpenSearch Service, and app secrets

EOF
)"
```

---

### Task 5: IAM + ECS cluster, task definitions, services

**Files:**
- Create: `deploy/infra/aws/iam.tf`
- Create: `deploy/infra/aws/ecs.tf`

**Interfaces:**
- Consumes: subnets, SGs, secret ARN, image URIs, GHCR creds
- Produces: ECS cluster; services `frontend`, `api`, `worker`; task defs for those plus `ingestion` and `bootstrap`

- [ ] **Step 1: IAM**

- `aws_iam_role.ecs_execution` + policy: `AmazonECSTaskExecutionRolePolicy` + `secretsmanager:GetSecretValue` on the app secret + (if using private registry) permissions to read a GHCR pull secret
- Create `aws_secretsmanager_secret.ghcr` with JSON `{"username":"…","password":"…"}` from vars; reference as `repository_credentials` on container definitions
- `aws_iam_role.ecs_task` for the app (CloudWatch already via execution role; task role can be minimal empty assume-role for now)

- [ ] **Step 2: Log groups**

`/ecs/${var.project}/frontend`, `api`, `worker`, `ingestion`, `bootstrap` with retention 7 days.

- [ ] **Step 3: Cluster + task definitions**

`aws_ecs_cluster.main`

Task definitions (Fargate, `awsvpc`, `linux/amd64` — Hetzner is ARM on CAX but GHCR cloud images for AWS should be **amd64** per AGENTS.md Hetzner x86 note / GHCR workflow; use the amd64 tags you already publish for cloud):

| Task | Image | Command / port | Essential env |
|------|-------|----------------|---------------|
| frontend | `var.frontend_image` | nginx default; port **80** | none beyond defaults |
| api | `var.backend_image` | `uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000`; port **8000** | secrets from Secrets Manager |
| worker | `var.backend_image` | `uv run python -m backend.worker` | same secrets |
| ingestion | `var.ingestion_image` | `uv run python -m ingestion.pipeline $OFFER_QUERY --hours 2` | same secrets + `OFFER_QUERY` |
| bootstrap | `var.backend_image` | `uv run python -m backend.bootstrap` (and/or `alembic upgrade head` then bootstrap — match k8s bootstrap Job command exactly; read `deploy/helm/jobstrainer/templates/bootstrap-job.yaml` and copy command) | same secrets |

Map Secrets Manager keys to container `secrets` with `valueFrom` JSON key ARNs (`arn:…:secret:…:DATABASE_URL::` syntax).

CPU/memory starting points: frontend `256/512`; api `1024/2048` (models); worker `512/1024`; ingestion `1024/2048`; bootstrap `512/1024`.

- [ ] **Step 4: Services**

- `frontend`: desired 1, public ALB TG later; private subnets; tasks SG
- `api`: desired 1; enable ECS service autoscaling target CPU 70%, min 1 max 4
- `worker`: desired 1, **deployment minimum healthy 0 / maximum 100%** or circuit breaker to avoid two workers briefly if possible; document singleton

Do not create a long-running ingestion service.

- [ ] **Step 5: Validate + commit**

```bash
cd deploy/infra/aws && tofu validate
git add deploy/infra/aws/iam.tf deploy/infra/aws/ecs.tf
git commit -m "$(cat <<'EOF'
feat(infra): add ECS Fargate services and task definitions

EOF
)"
```

---

### Task 6: ALB, ACM, Cloudflare DNS helpers

**Files:**
- Create: `deploy/infra/aws/alb.tf`
- Create: `deploy/infra/aws/dns.tf`
- Create: `deploy/infra/aws/outputs.tf` (partial OK; complete in Task 8)

**Interfaces:**
- Consumes: public subnets, alb SG, frontend/api target groups attached to services
- Produces: HTTPS ALB; ACM cert for `app.${var.domain}`, `api.${var.domain}`, apex/www as needed; optional Cloudflare records when `manage_dns_flip`

- [ ] **Step 1: ACM certificate**

`aws_acm_certificate.main` for `app.${var.domain}`, `api.${var.domain}`, `${var.domain}`, `www.${var.domain}` with DNS validation.

- [ ] **Step 2: Cloudflare validation records**

`cloudflare_dns_record` for each ACM domain validation option (type/name/value from `aws_acm_certificate.main.domain_validation_options`), `proxied = false`, `ttl = 1` (auto) matching Hetzner style.

`aws_acm_certificate_validation.main` waiting on those records / FQDNS.

- [ ] **Step 3: ALB + listeners**

- `aws_lb.main` application, public, two public subnets
- Target groups: frontend port 80; api port 8000; health checks `/` and a live API path (use `/health` if it exists — otherwise `/docs` or `/auth/me` unauthenticated behavior; **check** `backend` for a health route and use it, or add a trivial `/health` in a tiny follow-up only if missing — prefer existing route)
- Listener 443 with cert; host-header rules for `app.` → frontend, `api.` → api
- Listener 80 → redirect 443

Wire ECS services' `load_balancer` blocks to these TGs (may require editing `ecs.tf` in this task).

- [ ] **Step 4: Optional DNS flip resources**

When `var.manage_dns_flip` is true, Cloudflare CNAME/ALIAS-style records:

- `app` → ALB dns_name (Cloudflare CNAME, proxied false)
- `api` → ALB dns_name
- Apex: Cloudflare CNAME flatten to ALB if supported, or document manual ANAME; match operational reality of Cloudflare + ALB (CNAME flattening on apex)

When false, do not manage those records (Hetzner module owns them).

- [ ] **Step 5: Validate + commit**

```bash
cd deploy/infra/aws && tofu validate
git add deploy/infra/aws/alb.tf deploy/infra/aws/dns.tf deploy/infra/aws/ecs.tf
git commit -m "$(cat <<'EOF'
feat(infra): add ALB, ACM, and Cloudflare DNS flip toggle

EOF
)"
```

---

### Task 7: EventBridge Scheduler for ingestion + bootstrap runbook hook

**Files:**
- Create: `deploy/infra/aws/scheduler.tf`
- Modify: `deploy/infra/aws/iam.tf` (scheduler role)
- Modify: `deploy/infra/aws/README.md` (bootstrap section can start here; finish in Task 8)

**Interfaces:**
- Consumes: ingestion task definition ARN, cluster ARN, private subnets, tasks SG
- Produces: schedule `rate(2 hours)` or cron `cron(0 */2 * * ? *)` invoking ECS RunTask

- [ ] **Step 1: IAM role for Scheduler**

Allow `ecs:RunTask` on the ingestion task definition, `iam:PassRole` on execution/task roles, and `ecs:TagResource` if required.

- [ ] **Step 2: `aws_scheduler_schedule.ingestion`**

Flexible time window off; target ECS RunTask with same network config as services (`awsvpc`, private subnets, tasks SG, assign public IP **DISABLED**).

Set `OFFER_QUERY` / hours via container overrides matching Helm (`hours = 2`).

- [ ] **Step 3: Document bootstrap RunTask CLI** in README draft:

```bash
aws ecs run-task \
  --cluster "$(tofu output -raw ecs_cluster_name)" \
  --task-definition "$(tofu output -raw bootstrap_task_definition_arn)" \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[...],securityGroups=[...],assignPublicIp=DISABLED}"
```

Prefer exporting subnet/SG IDs as outputs for copy-paste.

Optional: `null_resource` with `local-exec` is **not** required for v1 if README is clear.

- [ ] **Step 4: Commit**

```bash
git add deploy/infra/aws/scheduler.tf deploy/infra/aws/iam.tf deploy/infra/aws/README.md
git commit -m "$(cat <<'EOF'
feat(infra): schedule ingestion RunTask via EventBridge

EOF
)"
```

---

### Task 8: Budget, outputs, README runbook

**Files:**
- Create: `deploy/infra/aws/budget.tf`
- Create/complete: `deploy/infra/aws/outputs.tf`
- Create/complete: `deploy/infra/aws/README.md`

**Interfaces:**
- Consumes: full stack
- Produces: operator runbook + `$budget_limit_usd` alert

- [ ] **Step 1: `budget.tf`**

`aws_budgets_budget` cost monthly `var.budget_limit_usd`, notification `ACTUAL` `>= 80%` and `100%` to `var.alert_email` (requires SNS topic or budgets email subscriber — use `subscriber_email_addresses`).

- [ ] **Step 2: Outputs**

At minimum:

- `alb_dns_name`
- `ecs_cluster_name`
- `bootstrap_task_definition_arn`
- `ingestion_task_definition_arn`
- `private_subnet_ids`
- `ecs_tasks_security_group_id`
- `rds_address`
- `opensearch_endpoint`
- `manage_dns_flip`

- [ ] **Step 3: README sections**

Must include:

1. Prerequisites (OpenTofu, AWS creds, Paid account, GHCR amd64 images, Cloudflare token)
2. Copy `terraform.tfvars.example` → `terraform.tfvars`
3. `tofu init && tofu apply` with `manage_dns_flip = false` first
4. Bootstrap RunTask
5. Set `manage_dns_flip = true` and apply **or** manual Cloudflare flip; ensure Hetzner is stopped/not serving
6. Smoke: open `https://app.jobsifty.com`, hit API
7. Flip DNS back / `manage_dns_flip = false`
8. `tofu destroy` checklist (NAT, ALB, RDS, OpenSearch, ECS)
9. Cost notes (hourly; destroy stops meter)

- [ ] **Step 4: Final validate**

```bash
cd deploy/infra/aws && tofu validate
```

- [ ] **Step 5: Commit**

```bash
git add deploy/infra/aws/
git commit -m "$(cat <<'EOF'
docs(infra): AWS ECS showcase runbook, outputs, and budget

EOF
)"
```

---

### Task 9: Spec cross-link from AGENTS / deploy docs (light)

**Files:**
- Modify: `deploy/k8s/README.md` — short “AWS is ECS, see deploy/infra/aws” pointer (do not imply Helm-on-AWS)
- Modify: `AGENTS.md` — one bullet under deploy that AWS showcase is ECS managed path per the new spec/plan

- [ ] **Step 1: Add brief pointers (2–4 sentences each), no full duplication of the AWS README**

- [ ] **Step 2: Commit**

```bash
git add deploy/k8s/README.md AGENTS.md
git commit -m "$(cat <<'EOF'
docs: point operators at AWS ECS infra path

EOF
)"
```

---

## Plan self-review

| Spec section | Task(s) |
|--------------|---------|
| Goal / ECS+RDS+OS+ALB+GHCR+DNS flip | 2–8 |
| OpenSearch HTTPS + auth | 1, 4 |
| EventBridge ingestion + bootstrap RunTask | 5, 7 |
| Worker without Storage Box backup | 5 (no BACKUP env) + existing backup no-op |
| Single-AZ data + cost controls | 3, 4, 8 (ALB 2-AZ exception in Global Constraints) |
| Budget + destroy | 8 |
| Non-goals respected | No EKS/ECR/Aurora/Serverless/S3 frontend tasks |

Placeholder scan: no TBD/TODO left in steps. ALB 2-AZ requirement explicitly constrained.
