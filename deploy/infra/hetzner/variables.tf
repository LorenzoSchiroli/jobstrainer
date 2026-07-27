variable "hcloud_token" {
  type      = string
  sensitive = true
}

variable "cloudflare_api_token" {
  type      = string
  sensitive = true
}

variable "cloudflare_zone_id" {
  type = string
}

variable "domain" {
  type = string
}

variable "letsencrypt_email" {
  type = string
}

variable "location" {
  type    = string
  default = "nbg1"
}

variable "cluster_name" {
  type    = string
  default = "jobstrainer"
}

variable "ssh_public_key_path" {
  type = string
}
