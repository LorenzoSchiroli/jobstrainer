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
