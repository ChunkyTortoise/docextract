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
  description = "Memory (MiB) for the app task, shared by redis + api + worker (512 CPU allows 1024-4096)."
  type        = number
  default     = 2048
}

variable "cpu_architecture" {
  description = "Fargate CPU architecture. ARM64 matches images built on Apple Silicon and is cheaper; use X86_64 only with --platform linux/amd64 images."
  type        = string
  default     = "ARM64"

  validation {
    condition     = contains(["ARM64", "X86_64"], var.cpu_architecture)
    error_message = "cpu_architecture must be ARM64 or X86_64."
  }
}

variable "image_tag" {
  description = "Image tag to run for the api and worker images (scripts/aws/deploy.sh pushes the git SHA and latest)."
  type        = string
  default     = "latest"
}

variable "desired_count_api" {
  description = "Running app tasks. Each task carries its own redis + api + worker, so 1 is enough for a demo and for the latency run."
  type        = number
  default     = 1
}

variable "run_worker" {
  description = "Run the ARQ worker container in the app task. false = API only (uploads queue but are never processed)."
  type        = bool
  default     = true
}

variable "worker_max_jobs" {
  description = "ARQ concurrency inside the task. Kept low so the measured latency is per document, not contended."
  type        = number
  default     = 2
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
  description = "PostgreSQL engine version. A major version alone lets RDS pick its current default minor (15.8 is no longer offered). Must support pgvector (15+)."
  type        = string
  default     = "15"
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
  description = "Anthropic API key, stored in SSM and injected as a secret. Set via TF_VAR_anthropic_api_key."
  type        = string
  sensitive   = true
  default     = ""
}

variable "gemini_api_key" {
  description = "Google Gemini API key (embeddings), stored in SSM. Optional. Set via TF_VAR_gemini_api_key."
  type        = string
  sensitive   = true
  default     = ""
}

variable "api_key_secret" {
  description = "32-char minimum secret for hashing API keys, stored in SSM. Set via TF_VAR_api_key_secret."
  type        = string
  sensitive   = true
}

variable "demo_mode" {
  description = "Enable DEMO_MODE on the container (the demo key is read-only; uploads need a seeded key)."
  type        = bool
  default     = true
}

variable "demo_api_key" {
  description = "API key used when DEMO_MODE=true."
  type        = string
  default     = "demo-key-docextract-2026"
}
