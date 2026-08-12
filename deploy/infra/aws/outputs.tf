output "alb_dns_name" {
  description = "DNS name of the internet-facing application load balancer."
  value       = aws_lb.main.dns_name
}
