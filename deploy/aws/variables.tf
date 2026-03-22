variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "instance_type" {
  description = "EC2 instance type (t2.micro = free tier)"
  type        = string
  default     = "t2.micro"
}

variable "key_pair_name" {
  description = "Name of an existing EC2 key pair for SSH access"
  type        = string
}

variable "anthropic_api_key" {
  description = "Anthropic API key injected into the container at launch"
  type        = string
  sensitive   = true
}

variable "gemini_api_key" {
  description = "Gemini API key injected into the container at launch"
  type        = string
  sensitive   = true
}

variable "app_name" {
  description = "Short name prefix applied to all resources"
  type        = string
  default     = "docextract"
}
