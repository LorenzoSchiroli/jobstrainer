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

# Apex + www DNS-only (same as app/api). Safari was unreliable via Cloudflare
# proxy on the apex; Traefik HTTPS middleware redirects to app.<domain>.
resource "cloudflare_dns_record" "apex" {
  zone_id = var.cloudflare_zone_id
  name    = var.domain
  type    = "A"
  ttl     = 1
  content = module.kube_hetzner.ingress_public_ipv4
  proxied = false
}

resource "cloudflare_dns_record" "www" {
  zone_id = var.cloudflare_zone_id
  name    = "www.${var.domain}"
  type    = "A"
  ttl     = 1
  content = module.kube_hetzner.ingress_public_ipv4
  proxied = false
}
