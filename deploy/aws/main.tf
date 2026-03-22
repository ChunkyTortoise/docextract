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
  region = var.aws_region
}

# ──────────────────────────────────────────────
# ECR – one repository per service image
# ──────────────────────────────────────────────
resource "aws_ecr_repository" "api" {
  name                 = "${var.app_name}-api"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "worker" {
  name                 = "${var.app_name}-worker"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

# ──────────────────────────────────────────────
# S3 – document storage bucket
# ──────────────────────────────────────────────
resource "aws_s3_bucket" "storage" {
  bucket = "${var.app_name}-documents-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_versioning" "storage" {
  bucket = aws_s3_bucket.storage.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "storage" {
  bucket = aws_s3_bucket.storage.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# ──────────────────────────────────────────────
# Networking – use default VPC for simplicity
# ──────────────────────────────────────────────
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

data "aws_caller_identity" "current" {}

# Security group: allow HTTP (8000) + SSH
resource "aws_security_group" "app" {
  name        = "${var.app_name}-sg"
  description = "DocExtract API access"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "API port"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# Inbound PostgreSQL from app security group
resource "aws_security_group_rule" "rds_from_app" {
  type                     = "ingress"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  security_group_id        = aws_security_group.rds.id
  source_security_group_id = aws_security_group.app.id
  description              = "PostgreSQL from EC2 app instances"
}

# Inbound Redis from app security group
resource "aws_security_group_rule" "redis_from_app" {
  type                     = "ingress"
  from_port                = 6379
  to_port                  = 6379
  protocol                 = "tcp"
  security_group_id        = aws_security_group.cache.id
  source_security_group_id = aws_security_group.app.id
  description              = "Redis from EC2 app instances"
}

# ──────────────────────────────────────────────
# RDS – Managed PostgreSQL with pgvector
# ──────────────────────────────────────────────
resource "aws_security_group" "rds" {
  name        = "${var.app_name}-rds-sg"
  description = "DocExtract RDS access"
  vpc_id      = data.aws_vpc.default.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_db_subnet_group" "main" {
  name       = "${var.app_name}-db-subnet"
  subnet_ids = data.aws_subnets.default.ids

  tags = {
    Name    = "${var.app_name}-db-subnet"
    Project = var.app_name
  }
}

resource "aws_db_instance" "postgres" {
  identifier        = "${var.app_name}-db"
  engine            = "postgres"
  engine_version    = "16"
  instance_class    = var.db_instance_class
  allocated_storage = 20
  storage_type      = "gp3"

  db_name  = "docextract"
  username = "docextract"
  password = var.db_password

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]

  # pgvector is available on Postgres 15+ via pg_extension — enabled by migration 002
  parameter_group_name = "default.postgres16"

  # Cost controls
  multi_az               = false
  publicly_accessible    = false
  skip_final_snapshot    = true
  deletion_protection    = false
  backup_retention_period = 1

  tags = {
    Name    = "${var.app_name}-db"
    Project = var.app_name
  }
}

# ──────────────────────────────────────────────
# ElastiCache – Managed Redis
# ──────────────────────────────────────────────
resource "aws_security_group" "cache" {
  name        = "${var.app_name}-cache-sg"
  description = "DocExtract ElastiCache access"
  vpc_id      = data.aws_vpc.default.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_elasticache_subnet_group" "main" {
  name       = "${var.app_name}-cache-subnet"
  subnet_ids = data.aws_subnets.default.ids

  tags = {
    Name    = "${var.app_name}-cache-subnet"
    Project = var.app_name
  }
}

resource "aws_elasticache_cluster" "redis" {
  cluster_id           = "${var.app_name}-redis"
  engine               = "redis"
  node_type            = var.redis_node_type
  num_cache_nodes      = 1
  parameter_group_name = "default.redis7"
  engine_version       = "7.1"
  port                 = 6379

  subnet_group_name  = aws_elasticache_subnet_group.main.name
  security_group_ids = [aws_security_group.cache.id]

  tags = {
    Name    = "${var.app_name}-redis"
    Project = var.app_name
  }
}

# ──────────────────────────────────────────────
# IAM – instance role for ECR pull + S3 access
# ──────────────────────────────────────────────
resource "aws_iam_role" "ec2" {
  name = "${var.app_name}-ec2-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "ecr_s3" {
  name = "${var.app_name}-ecr-s3"
  role = aws_iam_role.ec2.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ECRPull"
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken",
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
        ]
        Resource = "*"
      },
      {
        Sid      = "S3Storage"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
        Resource = [aws_s3_bucket.storage.arn, "${aws_s3_bucket.storage.arn}/*"]
      }
    ]
  })
}

resource "aws_iam_instance_profile" "ec2" {
  name = "${var.app_name}-profile"
  role = aws_iam_role.ec2.name
}

# ──────────────────────────────────────────────
# EC2 – Amazon Linux 2023 (free tier: t2.micro)
# ──────────────────────────────────────────────
data "aws_ami" "amazon_linux_2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }
}

resource "aws_instance" "app" {
  ami                    = data.aws_ami.amazon_linux_2023.id
  instance_type          = var.instance_type
  key_name               = var.key_pair_name
  vpc_security_group_ids = [aws_security_group.app.id]
  iam_instance_profile   = aws_iam_instance_profile.ec2.name

  root_block_device {
    volume_size = 20
    volume_type = "gp3"
  }

  user_data = templatefile("${path.module}/user_data.sh", {
    aws_region        = var.aws_region
    api_image_uri     = "${aws_ecr_repository.api.repository_url}:latest"
    worker_image_uri  = "${aws_ecr_repository.worker.repository_url}:latest"
    s3_bucket         = aws_s3_bucket.storage.bucket
    anthropic_api_key = var.anthropic_api_key
    gemini_api_key    = var.gemini_api_key
    rds_endpoint      = aws_db_instance.postgres.address
    db_password       = var.db_password
    redis_endpoint    = aws_elasticache_cluster.redis.cache_nodes[0].address
  })

  tags = {
    Name    = "${var.app_name}-api"
    Project = var.app_name
  }
}
