output "alb_dns_name" {
  description = "DNS name of the internet-facing application load balancer."
  value       = aws_lb.main.dns_name
}

output "ecs_cluster_name" {
  description = "ECS cluster name for RunTask and service operations."
  value       = aws_ecs_cluster.main.name
}

output "bootstrap_task_definition_arn" {
  description = "Bootstrap task definition ARN (migrations + OpenSearch setup)."
  value       = aws_ecs_task_definition.bootstrap.arn
}

output "ingestion_task_definition_arn" {
  description = "Ingestion task definition ARN (also scheduled every 2 hours)."
  value       = aws_ecs_task_definition.ingestion.arn
}

output "private_subnet_ids" {
  description = "Private subnet IDs for Fargate awsvpc network configuration."
  value       = aws_subnet.private[*].id
}

output "ecs_tasks_security_group_id" {
  description = "Security group ID attached to ECS Fargate tasks."
  value       = aws_security_group.ecs_tasks.id
}

output "rds_address" {
  description = "RDS Postgres hostname for debugging or one-off connections."
  value       = aws_db_instance.main.address
}

output "opensearch_endpoint" {
  description = "OpenSearch domain VPC endpoint (HTTPS)."
  value       = aws_opensearch_domain.main.endpoint
}

output "manage_dns_flip" {
  description = "Whether Cloudflare app/api/apex/www records point at the ALB."
  value       = var.manage_dns_flip
}
