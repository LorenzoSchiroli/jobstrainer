# Demo Dump Lifecycle (Hetzner up/down) — Design

**Date:** 2026-08-02  
**Updated:** 2026-08-04  
**Status:** Design (approved for implementation)  
**Author:** lschiroli

> Complements `docs/superpowers/specs/2026-07-27-k8s-phase4-hetzner-design.md`
> and `docs/superpowers/specs/2026-08-04-cloud-agnostic-helm-values-design.md`.
> Phase 4 left compose↔k8s data merge out of scope and treats Hetzner as a
> disposable demo environment. This design adds a dump-file source of truth and
> lifecycle scripts (`seed-dump`, `demo-up`, `demo-down`) so demo data is not
> lost when infrastructure is destroyed.

## 1. Goal

Keep **one current Postgres dataset** that is not tied to compose, kind, or
Hetzner. Hetzner Postgres is a temporary workspace restored from that file and
written back before destroy. Local compose is only an optional seed source (and
a manual restore target later); kind/compose full up/down wrappers are out of
scope for v1.

Success looks like:

- after `demo-down`, the laptop holds an updated `dumps/jobstrainer.current.dump`
  and the Hetzner cluster is gone;
- after `demo-up`, the cloud Postgres matches that dump and search works once
  reconcile has run;
- the operator is never unsure which dump file is “the” copy when no demo is
  running.

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
  (plus seed that creates/replaces the first file). No scheduled checkpoint
  command in v1.
- **Interactive tofu by default.** Scripts do not pass `-auto-approve` unless
  the operator passes an explicit `--yes` flag.
- **Pause writers around restore.** `demo-up` scales api/worker to 0 and
  suspends the ingestion CronJob while `pg_restore --clean` runs, then restores
  previous scale/suspend state.
- **Dump validation** uses `pg_restore -l`, preferring host tools, then
  `docker run postgres:16|17`, then `postgres-0` in the cluster. Host
  `pg_restore` older than the dump format (e.g. Homebrew 14 vs format 1.15)
  is not sufficient alone — upgrade `libpq` or use Docker/cluster fallbacks.

## 3. Source of truth layout

All paths are under the repo root and gitignored:

| Path | Role |
|------|------|
| `dumps/jobstrainer.current.dump` | Canonical current database (`pg_dump -Fc`) |
| `dumps/archive/YYYY-MM-DDTHHMMSSZ.dump` | Previous current, kept when overwritten |

Rules:

1. The current dump file is the only dataset treated as up to date when no demo
   is running.
2. Any running Hetzner Postgres is a temporary restore of that file unless the
   operator has deliberately seeded or written back through the scripts.
3. Dump files are never “the database” for queries; they must be restored into
   Postgres to use the app.
4. Legacy one-off dumps under `~/jobstrainer-data/dumps/` are not part of this
   layout; import them once via `seed-dump --from file` if needed.

## 4. Scripts

Place thin shell scripts in `deploy/scripts/` plus a small shared library
`deploy/scripts/lib/common.sh`. They chain existing tools (`pg_dump` /
`pg_restore`, `tofu`, `helm`, `kubectl`); they do not introduce a new backup
service.

Shared conventions:

- Repo root resolved from script location.
- Default kubeconfig:
  `deploy/infra/hetzner/${CLUSTER_NAME:-jobstrainer}_kubeconfig.yaml`
  (kube-hetzner writes `${cluster_name}_kubeconfig.yaml` next to the module
  root). Override with `KUBECONFIG` if already set.
- Custom-format dumps move via pod file + `kubectl cp` (not binary stdout
  redirects) when talking to the cluster.
- Promote helper: validate with `pg_restore -l`, archive existing current if
  present, then move temp → current.

### 4.1 `seed-dump`

**Purpose:** create or replace the canonical dump from an existing Postgres or
dump file (no merge — chosen source fully replaces current after archive).

Usage:

```bash
deploy/scripts/seed-dump --from compose          # default
deploy/scripts/seed-dump --from file --file PATH
deploy/scripts/seed-dump --from cluster          # uses KUBECONFIG convention
```

Steps (`--from compose`):

1. Require compose Postgres reachable (`docker compose exec postgres`).
2. `pg_dump -U postgres -Fc jobstrainer` → temp file (via `docker compose exec -T`).
3. Validate with `pg_restore -l` on the temp file.
4. If `dumps/jobstrainer.current.dump` exists, move it to `dumps/archive/…`.
5. Move temp → `dumps/jobstrainer.current.dump`.

Steps (`--from file`): copy/validate the given `.dump`, then promote.

Steps (`--from cluster`): dump from `postgres-0` via pod file + `kubectl cp`,
validate, promote.

### 4.2 `demo-up`

**Purpose:** bring up Hetzner demo infrastructure and seed it from the current
dump.

Steps:

1. Fail fast if `dumps/jobstrainer.current.dump` is missing (tell operator to
   run `seed-dump` first). Require local `pg_restore` and `values-private.yaml`.
2. `tofu apply` in `deploy/infra/hetzner` (interactive unless `--yes`).
3. Export `KUBECONFIG` to the default path above if unset.
4. Ensure `jobstrainer-secrets` exists:
   - If missing: require repo-root `.env.public` and `.env`, then
     `kubectl create secret generic jobstrainer-secrets`
     `--from-env-file=.env.public --from-env-file=.env`, then patch the three
     cluster-local URLs (`DATABASE_URL`, `OPENSEARCH_URL`, `BACKEND_URL`) as in
     `deploy/k8s/README.md`. CORS / Storage Box values must already be in those
     env files (or patched by the operator afterward).
   - If present: leave it; do not overwrite.
5. `helm upgrade --install jobstrainer deploy/helm/jobstrainer`
   `-f deploy/helm/jobstrainer/values.yaml`
   `-f deploy/helm/jobstrainer/values-cloud.yaml`
   `-f deploy/helm/jobstrainer/values-hetzner.yaml`
   `-f values-private.yaml`.
6. Wait until `postgres-0` is Ready and Job `jobstrainer-bootstrap` has
   succeeded (helm’s post-install hook normally blocks until bootstrap
   finishes; still verify).
7. Record api/worker replicas and ingestion CronJob `suspend`; scale api and
   worker to 0; suspend ingestion.
8. `kubectl cp` current dump into `postgres-0` and
   `pg_restore -U postgres -d jobstrainer --clean --if-exists --no-owner`.
9. Restore previous api/worker replicas and ingestion suspend flag.
10. Do not restore OpenSearch; leave reconcile to reindex.

### 4.3 `demo-down`

**Purpose:** capture cloud Postgres into the canonical dump, then destroy
infrastructure.

Steps:

1. Require cluster reachability (`kubectl` via the same kubeconfig convention).
2. Dump on the pod to a file, `kubectl cp` to a laptop temp file.
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
- Clear errors for missing dump, missing kubeconfig, Postgres not Ready,
  bootstrap not complete, missing `values-private.yaml`, and secret
  prerequisites.
- If restore fails after scaling down, scripts leave workloads scaled down and
  print recovery commands (do not silently scale up onto a half-restored DB).
- Nightly Storage Box backups from the worker remain disaster-recovery for a
  live demo; they are **not** the operator’s source of truth for this workflow
  and are not required by `demo-up` / `demo-down`.

## 6. Documentation and gitignore

- Add `dumps/` to `.gitignore`.
- Document the three scripts in `deploy/infra/hetzner/README.md` (primary) with
  a short pointer from `deploy/k8s/README.md`.
- Pin the kubeconfig path in the Hetzner README
  (`deploy/infra/hetzner/jobstrainer_kubeconfig.yaml` for the default
  `cluster_name`).
- Explicit warning: do not run bare `tofu destroy` while the demo holds data
  that is not yet in `dumps/jobstrainer.current.dump`; use `demo-down`.

## 7. Out of scope

- Bidirectional or row-level merge between environments
- Local kind/compose full lifecycle wrappers (beyond `seed-dump` sources)
- OpenSearch dump/restore
- Using Storage Box as the canonical dump location for this workflow
- Scheduled `demo-save` checkpoints while an environment stays up
- Changing the Phase 4 recovery RPO/RTO or replacing the worker’s nightly
  Storage Box backup loop
- Auto-deriving `CORS_ORIGINS` / Storage Box secret patches beyond what is
  already in `.env` / `.env.public`

## 8. Relationship to prior designs

- **Phase 4 Hetzner** remains the infra/backup design; this adds an operator
  convenience path for demo teardown without data loss.
- **Cloud-agnostic Helm values** define the `-f` stack `demo-up` uses.
- **2026-07-16 compose→k8s merge** and ad-hoc dumps under
  `~/jobstrainer-data/dumps/` are historical; import via
  `seed-dump --from file` if that data should become canonical.

## 9. Decision summary

- **Truth:** `dumps/jobstrainer.current.dump`
- **Archive:** timestamped copies under `dumps/archive/`
- **Up:** restore dump into fresh Hetzner Postgres after tofu + helm (writers paused)
- **Down:** dump Hetzner → replace current → tofu destroy
- **Seed:** compose, existing file, or live cluster → current dump (replace, no merge)
- **Merge:** none
- **OpenSearch:** reconcile only
