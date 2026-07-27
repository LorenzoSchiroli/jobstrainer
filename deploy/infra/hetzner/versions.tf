terraform {
  required_version = ">= 1.10.1"

  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = ">= 1.62.0"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.0"
    }
  }
}
