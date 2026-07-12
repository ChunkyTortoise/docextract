# ─── deploy/aws-ecs/main.tf ────────────────────────────────────────────────────
# Root module: provider, data sources, ECR repositories, S3 bucket.
# Cost guards: force_destroy=true on S3, no versioning (destroy trap removed
# vs legacy deploy/aws/main.tf), tagged resource sweep identifies all resources.
# ──────────────────────────────────────────────────────────────────────────────

terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project = var.project_tag
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_availability_zones" "available" {
  state = "available"
}

# ── ECR — reuse naming pattern from legacy deploy/aws module ──────────────────

resource "aws_ecr_repository" "api" {
  name                 = "${var.project_tag}-api"
  image_tag_mutability = "MUTABLE"
  force_delete         = true # allows destroy even when images have been pushed

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "worker" {
  name                 = "${var.project_tag}-worker"
  image_tag_mutability = "MUTABLE"
  force_delete         = true # allows destroy even when images have been pushed

  image_scanning_configuration {
    scan_on_push = true
  }
}

# ── S3 — document storage ─────────────────────────────────────────────────────
# force_destroy = true prevents the destroy-trap that hit the legacy module
# (versioned objects block bucket deletion; force_destroy deletes all versions).
# No versioning is enabled on this teardown bucket.

resource "aws_s3_bucket" "storage" {
  bucket        = "${var.project_tag}-docs-${data.aws_caller_identity.current.account_id}"
  force_destroy = var.s3_force_destroy
}

resource "aws_s3_bucket_server_side_encryption_configuration" "storage" {
  bucket = aws_s3_bucket.storage.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "storage" {
  bucket = aws_s3_bucket.storage.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
