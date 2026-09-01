# jobstrainer Hetzner infrastructure

## Prerequisites

- OpenTofu >= 1.10.1
- Packer (initial Leap Micro snapshot only)
- Hetzner Cloud project token (`HCLOUD_TOKEN`)
- Cloudflare API token scoped to DNS Edit for the selected zone
- SSH public key
- hcloud CLI

## One-time x86 OS snapshot

kube-hetzner boots nodes from an OS snapshot that must already exist in the
Hetzner project. For CX33 nodes build an x86 Leap Micro snapshot once:

    export HCLOUD_TOKEN=...
    curl -sL https://raw.githubusercontent.com/kube-hetzner/terraform-hcloud-kube-hetzner/v3.0.1/packer-template/hcloud-leapmicro-snapshots.pkr.hcl \
      -o /tmp/hcloud-leapmicro-snapshots.pkr.hcl
    packer init /tmp/hcloud-leapmicro-snapshots.pkr.hcl
    # Source name is leapmicro-x86-snapshot. Defaults: cx23 @ nbg1.
    packer build -only=hcloud.leapmicro-x86-snapshot \
      -var 'selinux_package_to_install=k3s' \
      /tmp/hcloud-leapmicro-snapshots.pkr.hcl

Confirm the snapshot exists:

    hcloud image list --type snapshot --architecture x86

## Initialize and plan

    # Prefer tokens in gitignored terraform.tfvars (see terraform.tfvars.example).
    cp terraform.tfvars.example terraform.tfvars
    tofu init
    tofu fmt -check -recursive
    tofu validate
    tofu plan

Review the planned permanent CX33, zero-to-two CX33 autoscaler pool with
public IPv4, and Cloudflare DNS-only A records before applying. Do not apply if
the permanent resources exceed the €20/month cost gate. Do not apply if the x86
snapshot is missing.

**Coexisting with AWS.** `manage_dns` (default `true`) gates the `app`/`api`/
apex/`www` Cloudflare A records the same way AWS's `manage_dns_flip` gates its
CNAMEs — only one side should own DNS at a time. Set `manage_dns = false` here
before (or when) you set `manage_dns_flip = true` in `deploy/infra/aws`, and
vice versa when flipping back.

## Apply and kubeconfig

    tofu apply

kube-hetzner writes a local kubeconfig next to this module:

    export KUBECONFIG=$PWD/jobstrainer_kubeconfig.yaml

(Default `cluster_name` is `jobstrainer`, so the file is
`jobstrainer_kubeconfig.yaml`. Keep it out of Git; `kubeconfig*` is gitignored.)

## Demo dump lifecycle

Hetzner is disposable. The operator source of truth is a single custom-format
dump at the repo root (gitignored):

    dumps/jobstrainer.current.dump

Do **not** run bare `tofu destroy` while the demo holds data that is not yet in
that file — use `deploy/scripts/run hetzner down` instead.

Typical flow from the repo root:

    # One-time (or rare): create the canonical dump
    deploy/scripts/seed-dump --from compose
    # or: deploy/scripts/seed-dump --from file --file ~/jobstrainer-data/dumps/compose-base.dump
    # or: deploy/scripts/seed-dump --from cluster

    deploy/scripts/run hetzner        # tofu apply → helm → restore dump
    # … use the demo …
    deploy/scripts/run hetzner down   # dump → promote current → tofu destroy

`up` is the default action, so `run hetzner` means `run hetzner up`. Both
accept `--yes` to pass `-auto-approve` to tofu.
Dump validation prefers Homebrew `libpq`’s `pg_restore` (even if keg-only),
then PATH `pg_restore`, then Docker `postgres:16`/`17`, then the cluster
Postgres pod. If PATH still has an old PostgreSQL 14 client, install/link
`libpq` or leave the keg path at `/opt/homebrew/opt/libpq/bin`.

For the **AWS** ECS showcase (same dump file, no kubectl), use
`deploy/scripts/run aws` / `run aws down` — see
`deploy/infra/aws/README.md` (§ Demo dump lifecycle).

Nightly Storage Box backups (worker) remain disaster recovery for a live demo;
they are not this workflow’s source of truth. Details:
`docs/superpowers/specs/2026-08-02-demo-dump-lifecycle-design.md`.
