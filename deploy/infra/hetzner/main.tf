module "kube_hetzner" {
  source  = "kube-hetzner/kube-hetzner/hcloud"
  version = "3.0.1"

  # Required by kube-hetzner v3 so the root hcloud provider is passed into nested host modules.
  providers = {
    hcloud = hcloud
  }

  hcloud_token    = var.hcloud_token
  cluster_name    = var.cluster_name
  ssh_public_key  = file(pathexpand(var.ssh_public_key_path))
  ssh_private_key = null

  control_plane_nodepools = [
    {
      name        = "permanent"
      # CX33 (x86, 8 GiB): ARM CAX capacity unavailable; same RAM class as CAX21.
      server_type = "cx33"
      location    = var.location
      count       = 1
      # v3.0.1 types control-plane labels/taints as list(string), not maps.
      labels = [
        "jobsifty.io/node-pool=permanent",
      ]
      taints = []
      extra_write_files = [
        {
          path        = "/etc/sysctl.d/90-opensearch.conf"
          content     = "vm.max_map_count=262144\n"
          permissions = "0644"
        },
      ]
      extra_runcmd = [
        "sysctl --system",
      ]
    },
  ]

  agent_nodepools = []

  autoscaler_nodepools = [
    {
      name        = "burst"
      server_type = "cx33"
      location    = var.location
      min_nodes   = 0
      max_nodes   = 2
      # Autoscaler labels are map(string) in v3.0.1.
      labels = {
        "jobsifty.io/node-pool" = "burst"
      }
      taints = []
    },
  ]

  # Public IPv4 is required for image pulls and ingestion scraping. An IP-less
  # autoscaler pool needs a permanent NAT router, which exceeds the idle budget.
  autoscaler_enable_public_ipv4 = true
  autoscaler_enable_public_ipv6 = false

  allow_scheduling_on_control_plane = true
  enable_klipper_metal_lb           = true
  kubernetes_distribution           = "k3s"
  ingress_controller                = "traefik"
  enable_cert_manager               = true
  enable_metrics_server             = true
  enable_local_storage              = false
}
