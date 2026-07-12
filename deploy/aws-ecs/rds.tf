# ─── deploy/aws-ecs/rds.tf ─────────────────────────────────────────────────────
# RDS PostgreSQL with pgvector support.
# db.t4g.micro: ~$0.016/hr on-demand.  Single-AZ for cost.
# skip_final_snapshot=true and deletion_protection=false are required for teardown.
#
# pgvector extension installation (one-time, post-apply):
#   psql "host=$(terraform output -raw rds_endpoint) port=5432 \
#         dbname=docextract user=docextract_admin sslmode=require" \
#     -c "CREATE EXTENSION IF NOT EXISTS vector;"
# This must be run from a host in aws_security_group.rds.  A temporary inbound
# rule is needed:
#   aws ec2 authorize-security-group-ingress \
#     --group-id <rds_sg_id> \
#     --protocol tcp --port 5432 \
#     --cidr <your_laptop_public_ip>/32
# Revoke it immediately after the extension is created and migrations run.
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_db_subnet_group" "main" {
  name       = "${var.project_tag}-db-subnet"
  subnet_ids = aws_subnet.public[*].id

  description = "Public subnets for the hiring-proof RDS instance"
}

resource "aws_db_parameter_group" "postgres15" {
  name        = "${var.project_tag}-pg15"
  family      = "postgres15"
  description = "Parameter group for hiring-proof postgres 15 with pgvector"

  # shared_preload_libraries is required to load pgvector
  parameter {
    name  = "shared_preload_libraries"
    value = "pg_stat_statements"
  }
}

resource "aws_db_instance" "postgres" {
  identifier = "${var.project_tag}-db"

  engine         = "postgres"
  engine_version = var.rds_engine_version
  instance_class = var.rds_instance_class

  allocated_storage = var.rds_allocated_storage
  storage_type      = var.rds_storage_type
  storage_encrypted = true

  db_name  = var.rds_db_name
  username = var.rds_username
  password = var.rds_password

  db_subnet_group_name   = aws_db_subnet_group.main.name
  parameter_group_name   = aws_db_parameter_group.postgres15.name
  vpc_security_group_ids = [aws_security_group.rds.id]

  publicly_accessible = false # only reachable from within the VPC
  multi_az            = false # single-AZ for cost

  # Teardown safety: both must be set for terraform destroy to succeed
  skip_final_snapshot = var.rds_skip_final_snapshot
  deletion_protection = var.rds_deletion_protection

  backup_retention_period = 0 # no automated backups for a teardown environment
}
