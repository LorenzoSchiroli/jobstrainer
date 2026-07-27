# jobstrainer Hetzner infrastructure

## Prerequisites

- OpenTofu >= 1.10.1
- Packer (initial ARM Leap Micro snapshot only)
- Hetzner Cloud project token (`HCLOUD_TOKEN`)
- Cloudflare API token scoped to DNS Edit for the selected zone
- SSH public key
- hcloud CLI

## One-time ARM OS snapshot

kube-hetzner boots nodes from an OS snapshot that must already exist in the
Hetzner project. For CAX21 nodes build an ARM Leap Micro snapshot once:

    export HCLOUD_TOKEN=...
    curl -sL https://raw.githubusercontent.com/kube-hetzner/terraform-hcloud-kube-hetzner/v3.0.1/packer-template/hcloud-leapmicro-snapshots.pkr.hcl \
      -o /tmp/hcloud-leapmicro-snapshots.pkr.hcl
    packer init /tmp/hcloud-leapmicro-snapshots.pkr.hcl
    # Source name is leapmicro-arm-snapshot. selinux_package_to_install is k3s or rke2.
    packer build -only=hcloud.leapmicro-arm-snapshot \
      -var 'selinux_package_to_install=k3s' \
      /tmp/hcloud-leapmicro-snapshots.pkr.hcl

Confirm the snapshot exists:

    hcloud image list --type snapshot --architecture arm

## Initialize and plan

    export TF_VAR_hcloud_token=...
    export TF_VAR_cloudflare_api_token=...
    cp terraform.tfvars.example terraform.tfvars
    tofu init
    tofu fmt -check -recursive
    tofu validate
    tofu plan

Review the planned permanent CAX21, zero-to-two CAX21 autoscaler pool with
public IPv4, and Cloudflare DNS-only A records before applying. Do not apply if
the permanent resources exceed the €20/month cost gate. Do not apply if the ARM
snapshot is missing.

## Apply and kubeconfig

    tofu apply

The module writes a local kubeconfig as part of its documented setup. Keep that
file outside Git and use it only through `KUBECONFIG=/path/to/kubeconfig`.
