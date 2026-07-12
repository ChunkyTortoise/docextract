# ─── deploy/aws-ecs/variables.tf ───────────────────────────────────────────────
# Pinned inputs for the hiring-proof deploy-measure-teardown run.
# All defaults are set to the spec-mandated values; override via terraform.tfvars
# or -var flags.  Sensitive variables must never be committed.
# ──────────────────────────────────────────────────────────────────────────────

variable "project_tag" {
  description = "Tag applied to every resource; used by the billable-resource sweep."
  type        = string
  default     = "docextract-hiring-proof"
}

variable "region" {
  description = "AWS region for all resources."
  type        = string
  default     = "us-west-2"
}

# ── Fargate ───────────────────────────────────────────────────────────────────

variable "fargate_cpu" {
  description = "CPU units for the API task (512 = 0.5 vCPU)."
  type        = number
  default     = 512
}

variable "fargate_memory" {
  description = "Memory (MiB) for the API task."
  type        = number
  default     = 1024
}

variable "desired_count_api" {
  description = "Desired running task count for the API service."
  type        = number
  default     = 2
}

variable "desired_count_worker" {
  description = "Desired running task count for the ARQ worker service. Keep 0 during stubbed load runs."
  type        = number
  default     = 0
}

# ── RDS ───────────────────────────────────────────────────────────────────────

variable "rds_instance_class" {
  description = "RDS instance class. db.t4g.micro (~$0.016/hr) for the hiring-proof run."
  type        = string
  default     = "db.t4g.micro"
}

variable "rds_allocated_storage" {
  description = "RDS allocated storage (GiB)."
  type        = number
  default     = 20
}

variable "rds_storage_type" {
  description = "RDS storage type."
  type        = string
  default     = "gp3"
}

variable "rds_engine_version" {
  description = "PostgreSQL engine version. Must support pgvector (15+)."
  type        = string
  default     = "15.8"
}

variable "rds_skip_final_snapshot" {
  description = "Skip final snapshot on destroy. Must be true for a teardown environment."
  type        = bool
  default     = true
}

variable "rds_deletion_protection" {
  description = "Enable RDS deletion protection. Must be false for teardown."
  type        = bool
  default     = false
}

variable "rds_db_name" {
  description = "Database name."
  type        = string
  default     = "docextract"
}

variable "rds_username" {
  description = "RDS master username."
  type        = string
  default     = "docextract_admin"
  sensitive   = true
}

variable "rds_password" {
  description = "RDS master password. Set via TF_VAR_rds_password environment variable; never commit."
  type        = string
  sensitive   = true
}

# ── S3 ────────────────────────────────────────────────────────────────────────

variable "s3_force_destroy" {
  description = "Allow S3 bucket deletion even when non-empty. Must be true for teardown."
  type        = bool
  default     = true
}

# ── Networking ────────────────────────────────────────────────────────────────

variable "assign_public_ip" {
  description = "Assign public IPs to Fargate tasks. true = no NAT gateway needed."
  type        = bool
  default     = true
}

variable "vpc_cidr" {
  description = "CIDR block for the new VPC."
  type        = string
  default     = "10.0.0.0/16"
}

variable "subnet_cidrs" {
  description = "CIDR blocks for two public subnets (ALB requires 2 AZs)."
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24"]
}

# ── App secrets (passed via environment variables to the ECS task) ────────────

variable "anthropic_api_key" {
  description = "Anthropic API key injected into the container env."
  type        = string
  sensitive   = true
  default     = ""
}

variable "gemini_api_key" {
  description = "Google Gemini API key injected into the container env."
  type        = string
  sensitive   = true
  default     = ""
}

variable "api_key_secret" {
  description = "32-char minimum secret for signing API keys."
  type        = string
  sensitive   = true
}

variable "demo_mode" {
  description = "Enable DEMO_MODE on the container (keyless demo auth)."
  type        = bool
  default     = true
}

variable "demo_api_key" {
  description = "API key used when DEMO_MODE=true."
  type        = string
  default     = "demo-key-docextract-2026"
}

variable "stub_extraction" {
  description = "Enable STUB_EXTRACTION on the worker (required for load tests)."
  type        = bool
  default     = true
}
