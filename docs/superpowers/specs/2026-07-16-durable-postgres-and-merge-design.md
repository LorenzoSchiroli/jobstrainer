# Postgres Dataset Merge (compose → k8s) — Design

**Date:** 2026-07-16
**Status:** Design (pre-implementation)
**Author:** lschiroli

> Builds on `docs/superpowers/specs/2026-07-07-k8s-scaling-design.md` (overall
> k8s scaling design) and the completed
> `docs/superpowers/plans/2026-07-11-k8s-phase1-local.md` (Phase 1 local stack).
> This touches **only** a one-time data merge and a test-database setup. The
> Postgres storage layer is deliberately left unchanged.

## 1. Goal

The project currently has **two divergent Postgres datasets**: the docker-compose
Postgres (the old dev DB, holding the user account, CV, applications, and the
larger job archive) and the in-cluster k8s Postgres (holding jobs scraped this
week by the ingestion CronJob). The goal is to **merge them into the single
in-cluster k8s Postgres**, so k8s is the one source of truth and there is no
duplication, then let the compose Postgres fade out of use.

### 1.1 Storage is intentionally NOT changed

The k8s Postgres keeps its **existing dynamic PVC** (StatefulSet
`volumeClaimTemplate`, `storageClassName` unset → inherits the environment's
default StorageClass). This is a deliberate decision, not an omission:

- The dynamic PVC is the **only storage shape portable across all three targets**
  the scaling design cares about. The pod names an abstract claim; each
  environment's default StorageClass fills it: `local-path` (node disk) on kind,
  Longhorn/Rook-Ceph/OpenEBS on bare metal, `gp3`/`standard-rwo` (EBS / PD) on
  cloud. **The same `postgres.yaml` works on all three with no change.**
- A `hostPath` volume (pinning data to the Mac filesystem) was considered and
  **rejected**: `hostPath` is local-only and, worse, ties data to one node's
  disk — an anti-pattern on multi-node bare metal, where a rescheduled pod would
  lose its data. It would actively break the bare-metal goal.

Consequence accepted: on local kind, the PVC is backed by the node's disk (inside
Docker Desktop's `Docker.raw`), so the data survives pod/node/Docker restarts and
cluster stop/start, but **not** an explicit `kind delete cluster` or a Docker
factory reset. That is the normal, accepted tradeoff for a local kind dev cluster;
durable storage arrives for free on bare metal / cloud via their StorageClasses,
with no manifest change. Scheduled backups (a `pg_dump` CronJob / WAL archiving)
are a later phase (scaling design §9), out of scope here.

OpenSearch is untouched — it stays disposable on its in-cluster PVC (scaling
design §2.3: rebuildable derived index, repopulated from Postgres by
`reconcile_worker`).

## 2. The two datasets

| | Compose Postgres (`jobstrainer-postgres-1`, volume `jobstrainer_postgres_data`) | k8s Postgres (`postgres-0`, PVC `data-postgres-0`) |
|---|---|---|
| users | 1 (`admin`) | 0 |
| applicant_profile | 1 (the CV) | 0 |
| applications | 3 (all → jobs >30d old) | 0 |
| preference_memory | 1 | 0 |
| jobs | 1740 (166 ≤30d, 1574 older) | 497 |
| companies | 1163 | 368 |

Overlap between the two: **107 company `name`s** shared, **5 job `url`s** shared.
All primary keys are UUIDs; **zero sequences** in the schema → no sequence
resync. `jobs` unique by `url`, `companies` unique by `name` (AGENTS.md,
confirmed in `models.py`).

**FK graph (confirmed in code):**
`jobs.company_id → companies.id`;
`applications.job_id → jobs.id`, `applications.user_id → users.id`;
`applicant_profile.user_id → users.id`; `preference_memory.user_id → users.id`.

The `checkpoint*` tables (LangGraph agent state) are **transient and excluded**
from the merge; `checkpointer.setup()` recreates them empty. They hold in-flight
agent graph state, not user data.

## 3. Merge target and direction

**Compose is the logical base; k8s contributes only its non-overlapping rows.**

Rationale — this direction protects the precious data. All FK-linked user data
(user, CV, the 3 applications and the jobs they point at, prefs) lives only in
compose, as a self-consistent snapshot. Restoring compose as the base brings that
in with its **original UUIDs and intact FKs — zero remapping of anything the user
cares about.** The k8s dataset has **no users/applications**, so its jobs/
companies can be folded in as a pure addition (remapped where names/urls
collide) with no risk to any user-facing foreign key even if a remap were
imperfect.

The end state lives in the **k8s PVC** (the instance we keep). Because a clean
`pg_restore` of the compose base needs empty target tables, the k8s Postgres's
existing `jobs`/`companies` rows are dumped (§5 step 1) and cleared before the
base restore, then re-merged on top (§4). Clearing them is safe: k8s has no
users/applications/profiles depending on those rows.

## 4. Merge correctness: how remapping avoids dangling FKs

After the base restore, users/CV/applications/prefs and all 1740 base jobs / 1163
base companies are present with their original compose UUIDs and intact FKs —
**nothing in the base needs remapping.** The only remapping is for the
**k8s-contributed companies/jobs**, whose UUIDs differ from base even where the
`name`/`url` matches. A **name/url join through staging tables** makes the
`company_id` remap fall out automatically:

1. Load the k8s-only companies + jobs into staging tables `stg_companies`,
   `stg_jobs` (carrying their original k8s UUIDs and the k8s `company_id` links).
2. Insert companies, base wins on collision:
   `INSERT INTO companies SELECT * FROM stg_companies ON CONFLICT (name) DO NOTHING;`
   — the 107 name collisions are skipped (base kept); the other ~261 k8s
   companies land with their k8s UUIDs.
3. Insert jobs, resolving `company_id` **by name** at insert time:
   ```sql
   INSERT INTO jobs (id, url, company_id, title, ...)
   SELECT sj.id, sj.url, c.id, sj.title, ...
   FROM stg_jobs sj
   JOIN stg_companies sc ON sc.id = sj.company_id   -- k8s job → its k8s company
   JOIN companies c      ON c.name = sc.name        -- k8s company name → final company row
   ON CONFLICT (url) DO NOTHING;                     -- 5 url collisions: base kept
   ```
   For a **collision** company the name-join resolves to the *base* company's
   UUID; for a **new** company it resolves to the just-inserted k8s UUID. Either
   way `company_id` points at a row that exists → **no dangling FK possible.**

**Edge cases, resolved:**

- **107 company collisions:** base row kept (step 2 `DO NOTHING`); any k8s job
  referencing the k8s duplicate is repointed to the base company via the
  name-join (step 3). No orphaned `company_id`.
- **5 job-url collisions:** base job kept (step 3 `DO NOTHING`); the k8s duplicate
  dropped. No `applications` reference k8s jobs (k8s has 0 users), so nothing is
  orphaned.
- **3 applications → jobs >30 days old:** an integrity concern only for *search
  visibility*, not FK integrity. Those 3 jobs are inside the base's 1740 and are
  restored normally, so the FK holds. They simply won't be indexed into
  OpenSearch (reconcile only indexes ≤30d) — accepted; the applications still
  resolve their job rows from Postgres.
- **checkpoint\* tables:** excluded from dump and merge; recreated empty by
  `checkpointer.setup()`.

Idempotency: the merge is all `ON CONFLICT DO NOTHING`, so re-running it (after a
mid-runbook failure) is safe.

Expected post-merge counts: companies = 1163 + (368 − 107) = **1424**; jobs =
1740 + (497 − 5) = **2232**. FK gate:
`SELECT count(*) FROM jobs j LEFT JOIN companies c ON c.id=j.company_id WHERE c.id IS NULL;`
must return **0**.

## 5. Migration runbook (ordered, resumable)

The dumps in step 1 are the **undo button** (§7). No step is destructive to
compose; the compose stack and its named volume are untouched throughout, so
rollback is "just keep using compose."

**Step 0 — prep a dumps directory** on the Mac filesystem (outside `Docker.raw`):
```
mkdir -p ~/jobstrainer-data/dumps
```

**Step 1 — safety dumps** (both live DBs). Exclude the transient `checkpoint*`
tables. Compose publishes `localhost:5432`; the k8s one is reached via a
port-forward on a non-5432 host port to avoid clashing with compose:
```
# base (compose)
pg_dump -h localhost -p 5432 -U postgres -d jobstrainer \
  --exclude-table='checkpoint*' -Fc -f ~/jobstrainer-data/dumps/compose-base.dump

# secondary (k8s)
kubectl port-forward svc/postgres 5544:5432 &
pg_dump -h localhost -p 5544 -U postgres -d jobstrainer \
  --exclude-table='checkpoint*' -Fc -f ~/jobstrainer-data/dumps/k8s-secondary.dump
```
Verify both `.dump` files exist and are non-trivial before continuing.

**Step 2 — clear the k8s base tables** so the compose base restores cleanly.
Only `jobs` + `companies` (k8s has no user data). Inside the cluster:
```
kubectl exec -it postgres-0 -- psql -U postgres -d jobstrainer \
  -c "TRUNCATE jobs, companies CASCADE;"
```
(`CASCADE` is defensive; k8s has no dependent rows, so nothing else is touched.)

**Step 3 — restore the compose base** into the k8s `jobstrainer` DB:
```
kubectl cp ~/jobstrainer-data/dumps/compose-base.dump postgres-0:/tmp/base.dump
kubectl exec -it postgres-0 -- pg_restore -U postgres -d jobstrainer --no-owner --data-only /tmp/base.dump
```
(`--data-only`: the schema already exists from the Phase 1 bootstrap; we load
rows into existing tables.) Verify counts: 1 user, 1740 jobs, 1163 companies,
3 applications, 1 profile, 1 preference_memory.

**Step 4 — merge the k8s-only companies/jobs** (§4): restore the k8s dump's
`companies`+`jobs` into a `staging` schema, then run the ON-CONFLICT name/url-join
inserts. Verify post-merge counts (1424 companies, 2232 jobs) and the FK gate
(= 0). Drop the `staging` schema.

**Step 5 — create the test database** (separate DB on the same server; the test
suite's `drop_all`/`create_all` then never touches real data):
```
kubectl exec -it postgres-0 -- psql -U postgres -c "CREATE DATABASE jobstrainer_test;"
```

**Step 6 — let reconcile reindex OpenSearch.** `reconcile_worker` (every 5 min)
indexes the ~166 jobs with `created_at ≥ now()−30d` missing from OpenSearch; the
older ~2066 stay Postgres-only (accepted archive). No manual reindex. Verify a
search returns results after a cycle.

**Step 7 — stop relying on compose.** Leave `docker-compose.yml` **as-is** (see
§6); simply stop bringing up its Postgres as the dev DB. Optionally
`docker compose stop postgres` so it isn't holding `localhost:5432` (relevant to
tests, §6). The `jobstrainer_postgres_data` volume and the `compose-base.dump`
remain as cold backups.

## 6. Files that change

| File | Change |
|---|---|
| `docker-compose.yml` | **No change.** Left as-is; compose is deprecated informally over time, not edited now. |
| `deploy/k8s/README.md` | Add a short "Merge / one-time data load" pointer and the `CREATE DATABASE jobstrainer_test` step. |
| `AGENTS.md` | Update the test-DB note: tests target `jobstrainer_test` on the k8s Postgres via `kubectl port-forward svc/postgres 5432:5432`, and the compose Postgres must not be occupying `localhost:5432` at test time (see §6.1). |
| `backend/tests/conftest.py` | **No change needed** — see §6.1. |

No manifest or application code changes: storage is unchanged (§1.1), and the
merge is pure data movement via `psql`/`pg_dump`/`pg_restore`.

### 6.1 Test-database workflow (option b) and the compose caveat

Decision (locked): a **single Postgres server** — the k8s one — also serves the
tests, via a separate `jobstrainer_test` database so the suite's
`Base.metadata.drop_all`/`create_all` (168 tests, `conftest.py:28-30`) never
touches real data.

`conftest.py` needs **no change**: its default is already
`postgresql+asyncpg://postgres:postgres@localhost:5432/jobstrainer_test`. Run
`kubectl port-forward svc/postgres 5432:5432` and `localhost:5432` resolves to the
k8s Postgres, hitting its `jobstrainer_test` DB with matching `postgres/postgres`
credentials.

**Caveat (because compose stays available):** if the compose Postgres is running,
it occupies `localhost:5432`, and the port-forward can't bind — tests would hit
whichever is on 5432. To route tests at k8s, either `docker compose stop postgres`
first, **or** port-forward k8s to a different port (`kubectl port-forward
svc/postgres 5544:5432`) and set `TEST_DATABASE_URL` accordingly. Document both in
`AGENTS.md`.

**Consequence (accepted):** `uv run pytest` now has a "cluster up + port-forward"
precondition; without it the connection is refused and the suite fails fast with a
clean error.

## 7. Risks & rollback

**Rollback = the Step-1 dumps + the untouched compose stack.** Nothing here is
irreversible: compose and its named volume are untouched throughout, so at any
point you can go back to `docker compose up postgres` exactly as before. The k8s
side is reconstructable from the two dumps.

Ranked risks:

1. **Merge remap correctness (§4)** — a wrong join or forgotten `ON CONFLICT`
   could duplicate a company (unique-name violation → hard error, safe) or
   mis-point a `company_id`. The FK gate in Step 4 (`LEFT JOIN … IS NULL` = 0) is
   the check; the whole merge is idempotent and re-runnable from the dumps.
2. **TRUNCATE before restore (§5 step 2)** — clears k8s jobs/companies; safe only
   because the Step-1 k8s dump captured them first and they have no dependent user
   rows. Gate: confirm the k8s dump exists and restores before truncating.
3. **Test-workflow port clash (§6.1)** — compose on 5432 vs. k8s port-forward.
   Low severity; documented workaround.

## 8. Out of scope

- **Storage changes** — the dynamic PVC stays (§1.1). No host-mount, no cluster
  recreation, no external/managed Postgres.
- **Postgres backups** beyond the ad-hoc Step-1 dumps — later phase (scaling
  design §9).
- **OpenSearch durability** — stays disposable (§1.1).
- **Editing/removing `docker-compose.yml`** — left as-is; informal deprecation
  over time.
- **Helm** — stays plain-manifest (Phase 1 shape).

## 9. Self-review

- **Placeholders:** none; the one abstracted spot is the Step-4 staging-restore
  mechanism (marked implementation detail) — the merge SQL itself (§4) is concrete.
- **Contradiction check:** "keep k8s storage as-is" (§1.1) is consistent with the
  merge landing in the k8s PVC (§3). Merge direction (compose = base, k8s =
  additive) is consistent across §3, §4, §5. "compose left untouched" (§6) is
  consistent with the rollback story (§7) and the test caveat (§6.1).
- **Counts reconciled:** post-merge 1424 companies / 2232 jobs derived from the
  stated overlaps (107 / 5); FK gate defined.
- **Scope:** no code/manifest changes; pure data operation plus a test DB and two
  doc edits. Storage explicitly unchanged.
