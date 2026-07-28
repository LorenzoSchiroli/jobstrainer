# K8s Phase 4 — Affordable Hetzner Production Design

**Date:** 2026-07-27  
**Status:** Approved design, pre-implementation

## 1. Goal

Deploy jobstrainer as a publicly accessible, HTTPS-enabled Kubernetes
application on Hetzner Cloud while keeping the unloaded baseline below
**€20/month** at current prices.

The deployment must preserve the portability established in Phases 1–3:

- local development continues to use kind;
- the existing Helm chart remains the application deployment unit;
- Hetzner uses k3s, a conformant Kubernetes distribution;
- a future EKS/ECS deployment remains possible because application containers
  and manifests use standard Kubernetes/container interfaces.

Phase 4 adds production-shaped infrastructure, persistence, recovery, ingress,
and node autoscaling. It deliberately does not promise high availability for
the stateful layer at this budget.

## 2. Constraints and accepted trade-offs

- **Idle budget:** below €20/month, excluding the annual domain registration
  and temporary autoscaled nodes.
- **Architecture:** ARM64, using a Hetzner CAX21 as the permanent node.
- **Provisioning:** OpenTofu with the `kube-hetzner` module.
- **Availability:** one permanent k3s server is a single point of failure.
- **Recovery over HA:** nightly Postgres backups provide disaster recovery;
  there is no multi-node Postgres or control-plane quorum.
- **Scaling latency:** adding a worker requires a VM to boot, join k3s, and pull
  images. The baseline API replica remains available during that delay.
- **Capacity limits:** HPA and node-pool ceilings start conservatively and are
  calibrated by load testing rather than treated as final design constants.
- **OpenSearch:** remains derived, rebuildable data. It is not backed up.

## 3. System architecture

### 3.1 Infrastructure

OpenTofu provisions:

- one Hetzner private network and firewall;
- one permanent CAX21 ARM64 k3s server;
- one autoscaled ARM64 worker pool with zero idle nodes;
- Hetzner Cloud Controller Manager and CSI integration through
  `kube-hetzner`;
- the Hetzner CSI storage class that Helm PVCs use to create volumes;
- the public IPv4 address required by the ingress endpoint;
- Cloudflare DNS records for the frontend and API hostnames.

`kube-hetzner` boots nodes from an OS snapshot (Leap Micro or MicroOS) that
must be built with Packer, once per project and per architecture, before the
first `tofu apply`. The ARM snapshot is mandatory here because every node is a
`cax` server.

Cloud credentials and tokens are supplied through local environment variables
or an ignored variable file. They are never committed.

Toolchain floors come from `kube-hetzner` v3.0.1: OpenTofu >= 1.10.1 and the
`hetznercloud/hcloud` provider >= 1.62.0.

### 3.2 Permanent node

The permanent node is both the k3s server and a schedulable worker. It runs the
baseline application:

- Traefik ingress controller;
- cert-manager;
- frontend;
- one API replica;
- singleton reconcile/retention worker;
- Postgres;
- OpenSearch;
- Kubernetes and autoscaler system components.

Postgres and OpenSearch receive a dedicated node label/affinity requirement so
they stay on the permanent pool. Their data lives on CSI-backed volumes rather
than container filesystems.

Moving from kind's local-path volumes to CSI block volumes changes three
assumptions that the chart currently relies on, so the Hetzner profile must
also supply:

- a `PGDATA` subdirectory, because a freshly formatted ext4 volume contains
  `lost+found` and the Postgres image refuses to run `initdb` in a non-empty
  directory;
- `fsGroup` for OpenSearch, because its container runs as a non-root user and
  cannot take ownership of a root-owned CSI mount;
- `vm.max_map_count=262144` on the permanent node, because OpenSearch enforces
  it as a bootstrap check and the node OS defaults lower.

All three are environment-gated. They must stay inert for kind, where changing
`PGDATA` on an initialized volume would silently create an empty database.

### 3.3 Autoscaled worker pool

The worker pool starts at zero nodes. Kubernetes Cluster Autoscaler for Hetzner
creates a temporary CAX worker when a pod cannot be scheduled from its declared
resource requests.

Temporary workers run only disposable compute:

- additional API replicas created by the HPA;
- ingestion jobs;
- test/load-generation jobs when explicitly enabled.

Temporary workers keep a public IPv4 address. `kube-hetzner` gives IP-less
nodes no egress path unless a permanently running NAT router server is
provisioned, and such a router costs more per month than the IPv4 addresses it
would save. Without egress a burst node cannot pull application images, and
ingestion cannot reach job sources at all. Because Hetzner bills IPv4 hourly
alongside the server, a pool sitting at zero nodes still costs nothing. Public
IPv6 stays disabled.

Only API replicas are placed by resource pressure. The ingestion CronJob is
pinned to the burst pool so its CPU/memory-heavy run does not compete with
Postgres and OpenSearch on the permanent node, which means a scheduled run
creates a temporary worker even without user traffic. To bound that cost, the
Hetzner profile lowers the ingestion schedule from every two hours to once
daily; keeping the two-hour cadence would boot a worker twelve times a day and
add several euro per month to a €20 budget.

After pods finish or become movable and capacity remains unnecessary for the
configured scale-down window, Cluster Autoscaler deletes the temporary VM.

### 3.4 Pod scaling and node scaling

The two autoscalers solve different problems:

1. API HPA observes average API CPU utilization relative to the pod's CPU
   request and creates more API pods.
2. The scheduler places those pods on existing nodes when capacity is
   available.
3. If a pod remains Pending because no node has sufficient requested CPU or
   memory, Cluster Autoscaler creates a worker node.

The current `minReplicas: 1`, `maxReplicas: 4`, and 70% CPU target are retained
only as initial safety settings. The initial worker pool is `min_nodes = 0`,
`max_nodes = 2`. Load tests must determine whether these values and the API's
current `250m` CPU / `512Mi` memory requests represent actual usage.

Accurate requests are essential: Cluster Autoscaler reasons about requested
capacity, not live CPU saturation. Understated requests could pack too many
model-heavy API pods onto one node and prevent timely node scale-up.

The API deployment carries no node affinity, by design. A required affinity to
the burst pool would leave the baseline replica unschedulable whenever the pool
sits at zero, and a required affinity to the permanent pool would defeat node
autoscaling entirely. Overflow therefore reaches burst nodes as an emergent
result of resource pressure rather than an enforced placement rule.

## 4. Traffic, DNS, and TLS

Cloudflare provides authoritative DNS on its free plan. Phase 4 uses two
configurable hostnames:

- the application hostname routes to the frontend Service;
- the API hostname routes to the API Service.

The initial DNS records point directly to the Hetzner ingress address. Cloudflare
proxying is optional and not required for the first deployment.

k3s supplies Traefik as its ingress controller. Helm Ingress resources describe
the hostname-to-Service routes. cert-manager obtains and renews free Let's
Encrypt certificates, and Traefik terminates HTTPS before forwarding requests
inside the cluster.

Each hostname owns its own TLS Secret. Two Ingresses that name one shared
Secret would produce two Certificates whose controllers overwrite each other's
SANs on every renewal.

The ingress endpoint is the permanent node's own public address, exposed by k3s
ServiceLB rather than a paid Hetzner load balancer. The infrastructure code must
read that address from the provisioning module's ingress output instead of
querying servers by label, and the firewall must allow inbound 80/443 so the
HTTP-01 challenge can complete.

The frontend image is built with the public API hostname. Backend CORS origins
become environment-driven so the hosted frontend origin is allowed without
removing the local `http://localhost:3000` workflow.

## 5. Container images and ARM64

ARM64 is selected to meet the budget and provides a migration path to AWS
Graviton. Before infrastructure deployment, the backend, ingestion, and
frontend images must build and run for `linux/arm64`.

The compatibility gate covers:

- Python 3.13 package wheels;
- PyTorch/sentence-transformers and both ML models;
- Playwright/browser dependencies used by ingestion;
- the OpenSearch image;
- database drivers and native dependencies.

An incompatibility that cannot be corrected safely is a stop condition: the
deployment switches to x86 and the budget is revised rather than emulating x86
in production.

Phase 4 requires working ARM64 images. Publishing multi-platform
`linux/arm64` + `linux/amd64` images is desirable for future ECS/EKS portability
but is not required to complete this phase.

Images are published to a configurable OCI registry such as GHCR. Registry
publication may initially be manual; a full CI/CD pipeline remains out of scope.

## 6. Persistence and backup

### 6.1 Active storage

The existing Postgres and OpenSearch StatefulSets continue to request PVCs.
The Hetzner values profile selects the Hetzner CSI storage class and production
volume sizes. CSI creates, attaches, and reattaches the block volumes
independently of pod lifetimes.

A persistent volume is not considered a backup: accidental deletion,
corruption, or credential misuse can affect the active data.

### 6.2 Postgres backup

The singleton backend worker runs a nightly `pg_dump` (custom format) loop and
uploads dumps over SFTP to a Hetzner Storage Box. The same Deployment and
backend image run reconcile, retention, and backup; there is no separate
backup image or CronJob.

The Storage Box is a separately provisioned backup target rather than a
Kubernetes volume. Its credentials are stored in the pre-created application
Secret (`BACKUP_SBOX_*`). When those keys are unset (local kind), the worker
skips the backup loop. The worker Deployment is pinned to the permanent pool.

Two details of the target are fixed by the provider and must be encoded in the
backup job: Storage Box SFTP listens on port 23, and remote paths are relative
to the account home, so they must not begin with a slash. The application's
`DATABASE_URL` is a SQLAlchemy dialect URL, so the job must convert it to a
libpq URI before invoking `pg_dump`.

Backup policy:

- one backup loop inside the worker (errors are isolated so reconcile/retention
  keep running);
- default interval 24h (`BACKUP_INTERVAL_SECONDS`, overridable via Helm);
- retain the latest seven daily dumps;
- delete older dumps only after a new dump uploads successfully;
- prune by sorting the timestamped filenames locally, since the upload tool
  offers no server-side ordering;
- fail loudly rather than silently skipping retention, so the Storage Box
  cannot grow without bound;
- credentials come from the pre-created Kubernetes Secret;
- the runbook includes a `pg_restore` procedure.

Restoration is tested periodically. Backup creation alone is not sufficient
evidence of recoverability.

### 6.3 OpenSearch recovery

OpenSearch remains disposable. If its volume or index is lost:

1. bootstrap recreates the index and search pipeline;
2. the reconciliation worker reindexes the live search window from Postgres;
3. search is verified after a reconciliation cycle.

No OpenSearch backup is introduced.

## 7. Failure behavior and recovery objectives

### Temporary worker failure

Kubernetes reschedules disposable API/ingestion pods. Cluster Autoscaler may
replace lost capacity. No persistent workload is assigned to the burst pool.

### Autoscaling failure

The permanent API replica continues serving within its capacity. Additional
pods remain Pending. The failure is visible in scheduler and autoscaler events;
the system degrades rather than losing database state.

### Postgres corruption or volume loss

Recreate Postgres storage and restore the newest valid Storage Box dump. The
accepted recovery-point objective is **up to 24 hours of data loss**.

### Permanent node or cluster loss

Recreate infrastructure with OpenTofu, reinstall the application with Helm,
restore Postgres, and rebuild OpenSearch. The target recovery-time objective is
**one to two hours** for a practiced operator.

These objectives are portfolio/development targets, not a customer-facing SLA.

## 8. Configuration and repository changes

The implementation is expected to add:

- an OpenTofu environment for Hetzner infrastructure;
- a Hetzner Helm values profile;
- conditional ingress, cert-manager integration, storage class, affinity, and
  worker-backed Postgres backup values (Storage Box via `BACKUP_SBOX_*`);
- configurable backend CORS origins;
- ARM64 build support;
- a deployment and recovery runbook.

The existing local values profile remains functional. Environment-specific
configuration must not be copied into application code.

No secret values, Hetzner tokens, Cloudflare tokens, Storage Box passwords, or
private keys are tracked by Git or exposed as non-sensitive OpenTofu outputs.

## 9. Verification

### Before provisioning

- build all application images for ARM64;
- run backend and ingestion test suites in ARM-compatible images;
- run frontend tests/build;
- run `tofu fmt`, `tofu validate`, and review `tofu plan`;
- run Helm lint and template checks for local and Hetzner values;
- validate rendered manifests with an offline schema validator; `kubectl
  --dry-run=client` is not one, because it resolves API groups and schemas from
  a live server;
- confirm the local kind render is unchanged by diffing it against the render
  from before the chart edits, since StatefulSet volume claim templates are
  immutable on upgrade;
- scan tracked files and OpenTofu outputs for secrets.

### Deployment smoke tests

- frontend and API hostnames resolve through Cloudflare DNS;
- HTTPS certificates are valid and renew automatically;
- authentication and search work through the public frontend;
- API, worker, ingestion, Postgres, and OpenSearch pods are healthy;
- Postgres and OpenSearch data survive pod recreation.

### Recovery tests

- produce a backup and restore it into a clean Postgres instance;
- verify row counts and foreign-key integrity after restoration;
- remove/recreate OpenSearch state and confirm reconciliation restores search;
- document measured RPO/RTO and any manual steps discovered.

### Scaling tests

Use k6 from outside the permanent node, or from a deliberately isolated
temporary worker, so the load generator does not distort API capacity.

For increasing request rates, record:

- p50/p95 response latency;
- error rate;
- per-pod CPU and memory;
- requests handled per API replica;
- HPA replica transitions;
- Pending-pod duration;
- worker provisioning time;
- node scale-down time.

Success criteria:

- p95 and error targets are defined before interpreting results;
- HPA creates additional API replicas under sustained load;
- insufficient cluster capacity creates a Hetzner worker;
- new pods become Ready on that worker;
- the worker is removed after demand falls;
- measured data determines final API requests, HPA maximum, and node-pool
  maximum.

## 10. Cost gate

At the time of design, the intended unloaded cost consists of:

- one CAX21 permanent server;
- one public IPv4 address;
- small Hetzner CSI volumes;
- one BX11 Storage Box;
- free Cloudflare DNS;
- free Let's Encrypt certificates.

The target is below €20/month including VAT, excluding domain registration and
temporary workers. Because cloud prices change, the OpenTofu plan/runbook must
include a current-price check before creation.

Autoscaled workers, and the IPv4 addresses attached to them, are billed only
while they exist. The budget gate fails if the selected permanent resources
exceed €20/month before load, even if short-lived credits or promotional
pricing would hide the cost.

Burst nodes are not free in practice: the daily ingestion run boots one worker
per day, which is a small but real recurring charge on top of the permanent
baseline. Load tests add further short-lived nodes.

## 11. Out of scope

- highly available k3s control plane;
- multi-node or operator-managed Postgres;
- Postgres point-in-time recovery/WAL archiving;
- managed OpenSearch;
- KEDA and scale-to-zero for application pods;
- full GitOps or CI/CD deployment automation;
- Cloudflare paid features;
- service mesh, mTLS, and multi-region deployment;
- production configuration for the Chrome extension;
- the separate compose-to-k8s data merge.

## 12. Decision summary

- **Platform:** k3s on Hetzner, provisioned by OpenTofu/`kube-hetzner`.
- **Baseline:** one schedulable CAX21 ARM64 server.
- **Burst:** zero-to-two temporary ARM workers initially, each with a public
  IPv4 for egress and no IPv6.
- **Application scaling:** API HPA, calibrated by load testing.
- **State:** Postgres/OpenSearch on CSI volumes and the permanent pool.
- **Backup:** nightly Postgres custom-format dump, seven rolling copies.
- **Recovery:** restore Postgres; rebuild OpenSearch.
- **Ingress:** Traefik + cert-manager + Let's Encrypt.
- **DNS:** Cloudflare free authoritative DNS.
- **Budget:** below €20/month unloaded; burst workers billed separately.
