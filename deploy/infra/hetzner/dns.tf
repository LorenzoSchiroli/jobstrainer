resource "cloudflare_dns_record" "frontend" {
  zone_id = var.cloudflare_zone_id
  name    = "app.${var.domain}"
  type    = "A"
  ttl     = 1
  content = module.kube_hetzner.ingress_public_ipv4
  proxied = false
}

resource "cloudflare_dns_record" "api" {
  zone_id = var.cloudflare_zone_id
  name    = "api.${var.domain}"
  type    = "A"
  ttl     = 1
  content = module.kube_hetzner.ingress_public_ipv4
  proxied = false
}
