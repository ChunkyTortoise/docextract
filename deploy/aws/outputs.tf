output "api_public_ip" {
  description = "Public IP of the DocExtract API instance"
  value       = aws_instance.app.public_ip
}

output "api_url" {
  description = "Base URL for the DocExtract API"
  value       = "http://${aws_instance.app.public_ip}:8000"
}

output "ecr_api_uri" {
  description = "ECR URI for the API image (use with docker push)"
  value       = aws_ecr_repository.api.repository_url
}

output "ecr_worker_uri" {
  description = "ECR URI for the worker image (use with docker push)"
  value       = aws_ecr_repository.worker.repository_url
}

output "s3_bucket" {
  description = "S3 bucket name for document storage"
  value       = aws_s3_bucket.storage.bucket
}
