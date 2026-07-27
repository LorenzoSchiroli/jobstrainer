output "cluster_name" {
  value = var.cluster_name
}

output "frontend_hostname" {
  value = "app.${var.domain}"
}

output "api_hostname" {
  value = "api.${var.domain}"
}

output "ingress_public_ipv4" {
  value = module.kube_hetzner.ingress_public_ipv4
}

output "storage_class_name" {
  value = "hcloud-volumes"
}
