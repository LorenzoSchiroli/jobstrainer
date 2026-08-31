# Internal service discovery so in-VPC callers reach this stack's own API,
# independent of public DNS. Mirrors the Helm path, where ingestion posts to
# the in-cluster Service (http://api:8000) rather than the public hostname.
resource "aws_service_discovery_private_dns_namespace" "main" {
  name        = "${var.project}.local"
  description = "Private DNS for in-VPC service discovery"
  vpc         = aws_vpc.main.id
}

resource "aws_service_discovery_service" "api" {
  name = "api"

  dns_config {
    namespace_id   = aws_service_discovery_private_dns_namespace.main.id
    routing_policy = "MULTIVALUE"

    dns_records {
      ttl  = 10
      type = "A"
    }
  }
}
