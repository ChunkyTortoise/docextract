# ─── deploy/aws-ecs/outputs.tf ─────────────────────────────────────────────────

output "alb_dns_name" {
  description = "ALB DNS name — use for load testing and health checks."
  value       = aws_lb.api.dns_name
}

output "rds_endpoint" {
  description = "RDS PostgreSQL hostname (port 5432). Used for migrations and the pgvector extension step."
  value       = aws_db_instance.postgres.address
}

output "ecr_repo_url" {
  description = "ECR repository URL for the API image (use with docker push)."
  value       = aws_ecr_repository.api.repository_url
}

output "ecr_worker_repo_url" {
  description = "ECR repository URL for the worker image."
  value       = aws_ecr_repository.worker.repository_url
}

output "s3_bucket" {
  description = "S3 bucket name for document storage."
  value       = aws_s3_bucket.storage.bucket
}

output "ecs_cluster_name" {
  description = "ECS cluster name — use with aws ecs commands."
  value       = aws_ecs_cluster.main.name
}

output "project_tag" {
  description = "Project tag applied to all resources — use in the billable-resource sweep."
  value       = var.project_tag
}

output "public_subnet_ids" {
  description = "Subnets for one-off ops tasks (aws ecs run-task)."
  value       = aws_subnet.public[*].id
}

output "ecs_tasks_security_group_id" {
  description = "Security group for one-off ops tasks; it is the one RDS admits."
  value       = aws_security_group.ecs_tasks.id
}

output "ops_task_family" {
  description = "Task definition family for migrations and key seeding."
  value       = aws_ecs_task_definition.ops.family
}

output "api_service_name" {
  description = "ECS service name, for update-service and wait services-stable."
  value       = aws_ecs_service.api.name
}
