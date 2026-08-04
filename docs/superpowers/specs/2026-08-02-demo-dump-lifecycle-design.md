# Demo Dump Lifecycle (Hetzner up/down) — Design

**Date:** 2026-08-02  
**Status:** Design (pre-implementation)  
**Author:** lschiroli

> Complements `docs/superpowers/specs/2026-07-27-k8s-phase4-hetzner-design.md`.
> Phase 4 left compose↔k8s data merge out of scope and treats Hetzner as a
> disposable demo environment. This design adds a dump-file source of truth and
> lifecycle scripts (`seed-dump`, `demo-up`, `demo-down`) so demo data is not
> lost when infrastructure is destroyed.

## 1. Goal

Keep **one current Postgres dataset** that is not tied to compose, kind, or
Hetzner. Local and cloud Postgres instances are temporary workspaces restored
from that file. When a demo environment is destroyed, its data is written back
to the file first.

Success looks like:

- after `demo-down`, the laptop holds an updated `dumps/jobstrainer.current.dump`
  and the Hetzner cluster is gone;
- after `demo-up`, the cloud Postgres matches that dump and search works once
  reconcile has run;
- the operator is never unsure which running database is “the” copy.

## 2. Constraints and decisions

- **Hetzner is temporary.** It is a public demo, not the long-lived home of data.
- **One active writer.** Do not run long-lived local ingestion and cloud
  ingestion against divergent DBs at the same time.
- **No merge.** Destroy path replaces the current dump with a full dump of the
  environment being destroyed. Fill-only / last-write-wins row merge is out of
  scope (and unnecessary under the one-writer rule).
- **Full Postgres.** Dump includes all application tables (jobs, companies,
  users, profiles, applications, outbox, LangGraph checkpoints, etc.).
- **OpenSearch is derived.** Never dump or restore OpenSearch; the worker
  reconcile rebuilds the search index from Postgres.
- **Rewrite the current dump only when destroying** the active environment
  (plus the one-time seed that creates the first file). No scheduled checkpoint
  command in v1.
- **Interactive tofu by default.** Scripts do not pass `-auto-approve` unless
  the operator passes an explicit `--yes` flag.

## 3. Source of truth layout

All paths are under the repo root and gitignored:

| Path | Role |
|------|------|
| `dumps/jobstrainer.current.dump` | Canonical current database (`pg_dump -Fc`) |
| `dumps/archive/YYYY-MM-DDTHHMMSSZ.dump` | Previous current, kept when overwritten |

Rules:

1. The current dump file is the only dataset treated as up to date when no demo
   is running.
2. Any running Postgres (compose today, kind later, or Hetzner) is a temporary
   restore of that file unless the operator has deliberately seeded or written
   back through the scripts.
3. Dump files are never “the database” for queries; they must be restored into
   Postgres to use the app.

## 4. Scripts

Place thin shell scripts in `deploy/scripts/`. They chain existing tools
(`pg_dump` / `pg_restore`, `tofu`, `helm`, `kubectl`); they do not introduce a
new backup service.

### 4.1 `seed-dump`

**Purpose:** one-time (or rare) creation of the canonical dump from the data
that already lives in the compose Postgres volume.

Steps:

1. Require compose Postgres reachable (`docker compose exec postgres` or
   equivalent container `jobstrainer-postgres-1`).
2. `pg_dump -U postgres -Fc jobstrainer` → temp file.
3. Validate with `pg_restore -l` on the temp file.
4. If `dumps/jobstrainer.current.dump` exists, move it to `dumps/archive/…`.
5. Move temp → `dumps/jobstrainer.current.dump`.

### 4.2 `demo-up`

**Purpose:** bring up Hetzner demo infrastructure and seed it from the current
dump.

Steps:

1. Fail fast if `dumps/jobstrainer.current.dump` is missing (tell operator to
   run `seed-dump` first).
2. `tofu apply` in `deploy/infra/hetzner` (interactive unless `--yes`).
3. Export `KUBECONFIG` to the kubeconfig written by the tofu module (path
   configurable; documented in the Hetzner README).
4. Ensure `jobstrainer-secrets` exists (same procedure as
   `deploy/k8s/README.md`; script may invoke documented commands or refuse and
   print them if the secret is absent).
5. `helm upgrade --install jobstrainer deploy/helm/jobstrainer`
   `-f deploy/helm/jobstrainer/values.yaml`
   `-f deploy/helm/jobstrainer/values-cloud.yaml`
   `-f deploy/helm/jobstrainer/values-hetzner.yaml`
   `-f values-private.yaml` (repo-root private overrides).
6. Wait until `postgres-0` is Ready.
7. Copy the current dump into the pod and
   `pg_restore -U postgres -d jobstrainer --clean --if-exists --no-owner`.
8. Do not restore OpenSearch; leave reconcile to reindex.

### 4.3 `demo-down`

**Purpose:** capture cloud Postgres into the canonical dump, then destroy
infrastructure.

Steps:

1. Require cluster reachability (`kubectl` via the same kubeconfig convention).
2. `kubectl exec` `pg_dump -U postgres -Fc jobstrainer` → temp file on the
   laptop.
3. Validate with `pg_restore -l`.
4. Archive existing current dump (if any), promote temp →
   `dumps/jobstrainer.current.dump`.
5. Only after a successful promote: `tofu destroy` (interactive unless `--yes`).
6. If any dump/validate/promote step fails, **abort** and do not destroy.

`helm uninstall` is optional and not required before destroy; destroying the
node removes the workloads. Prefer leaving destroy as the single teardown
action to keep the script short.

## 5. Safety and failure behavior

- Scripts use `set -euo pipefail`.
- `demo-down` treats dump success as a hard gate before destroy.
- Overwrites always archive the previous current dump first.
- Clear errors for missing dump, missing kubeconfig, Postgres not Ready, and
  helm/secret prerequisites.
- Nightly Storage Box backups from the worker remain disaster-recovery for a
  live demo; they are **not** the operator’s source of truth for this workflow
  and are not required by `demo-up` / `demo-down`.

## 6. Documentation and gitignore

- Add `dumps/` to `.gitignore`.
- Document the three scripts in `deploy/infra/hetzner/README.md` (primary) with
  a short pointer from `deploy/k8s/README.md`.
- Explicit warning: do not run bare `tofu destroy` while the demo holds data
  that is not yet in `dumps/jobstrainer.current.dump`; use `demo-down`.

## 7. Out of scope

- Bidirectional or row-level merge between environments
- Local kind/compose full lifecycle wrappers (beyond `seed-dump` from compose)
- OpenSearch dump/restore
- Using Storage Box as the canonical dump location for this workflow
- Scheduled `demo-save` checkpoints while an environment stays up
- Changing the Phase 4 recovery RPO/RTO or replacing the worker’s nightly
  Storage Box backup loop

## 8. Relationship to prior designs

- **Phase 4 Hetzner** remains the infra/backup design; this adds an operator
  convenience path for demo teardown without data loss.
- **2026-07-16 compose→k8s merge** stays a separate, still pre-implementation
  one-time migration if kind becomes the local workspace later. It is not
  required for dump-centric demo up/down: today’s compose volume is only an
  input to `seed-dump`.

## 9. Decision summary

- **Truth:** `dumps/jobstrainer.current.dump`
- **Archive:** timestamped copies under `dumps/archive/`
- **Up:** restore dump into fresh Hetzner Postgres after tofu + helm
- **Down:** dump Hetzner → replace current → tofu destroy
- **Seed:** one-time compose → current dump
- **Merge:** none
- **OpenSearch:** reconcile only
