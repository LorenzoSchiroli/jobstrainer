resource "cloudflare_dns_record" "acm_validation" {
  for_each = {
    for dvo in aws_acm_certificate.main.domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      record = dvo.resource_record_value
      type   = dvo.resource_record_type
    }
  }

  zone_id = var.cloudflare_zone_id
  name    = replace(trimsuffix(each.value.name, "."), ".${var.domain}", "")
  type    = each.value.type
  content = trimsuffix(each.value.record, ".")
  ttl     = 1
  proxied = false
}

resource "cloudflare_dns_record" "app" {
  count = var.manage_dns_flip ? 1 : 0

  zone_id = var.cloudflare_zone_id
  name    = "app.${var.domain}"
  type    = "CNAME"
  content = aws_lb.main.dns_name
  ttl     = 1
  proxied = false
}

resource "cloudflare_dns_record" "api" {
  count = var.manage_dns_flip ? 1 : 0

  zone_id = var.cloudflare_zone_id
  name    = "api.${var.domain}"
  type    = "CNAME"
  content = aws_lb.main.dns_name
  ttl     = 1
  proxied = false
}

# Apex CNAME flattening: Cloudflare resolves the ALB hostname at the zone apex.
resource "cloudflare_dns_record" "apex" {
  count = var.manage_dns_flip ? 1 : 0

  zone_id = var.cloudflare_zone_id
  name    = var.domain
  type    = "CNAME"
  content = aws_lb.main.dns_name
  ttl     = 1
  proxied = false
}

resource "cloudflare_dns_record" "www" {
  count = var.manage_dns_flip ? 1 : 0

  zone_id = var.cloudflare_zone_id
  name    = "www.${var.domain}"
  type    = "CNAME"
  content = aws_lb.main.dns_name
  ttl     = 1
  proxied = false
}
