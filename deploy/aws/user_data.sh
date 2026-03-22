#!/bin/bash
# EC2 bootstrap script — installs Docker, pulls images from ECR, starts the stack
# RDS Postgres and ElastiCache Redis are provisioned separately by Terraform.
set -euo pipefail

# ── System setup ──────────────────────────────
dnf update -y
dnf install -y docker
systemctl enable --now docker
usermod -aG docker ec2-user

# ── AWS CLI is pre-installed on AL2023; authenticate Docker to ECR ──
aws ecr get-login-password --region ${aws_region} \
  | docker login --username AWS --password-stdin \
    $(echo ${api_image_uri} | cut -d/ -f1)

# ── Pull images ──────────────────────────────
docker pull ${api_image_uri}
docker pull ${worker_image_uri}

# ── Write environment file (never committed — lives only on the instance) ──
# DATABASE_URL: managed RDS Postgres (pgvector extension enabled by migration 002)
# REDIS_URL: managed ElastiCache Redis (no auth — private subnet, app SG only)
cat > /opt/docextract.env <<EOF
ANTHROPIC_API_KEY=${anthropic_api_key}
GEMINI_API_KEY=${gemini_api_key}
STORAGE_BACKEND=s3
STORAGE_S3_BUCKET=${s3_bucket}
AWS_REGION=${aws_region}
DEMO_MODE=false
OTEL_ENABLED=true
DATABASE_URL=postgresql+asyncpg://docextract:${db_password}@${rds_endpoint}:5432/docextract
REDIS_URL=redis://${redis_endpoint}:6379/0
EOF

chmod 600 /opt/docextract.env

# ── Run Alembic migrations (wait for RDS to be reachable) ──
# RDS is typically available by the time user_data runs, but retry for safety.
for i in $(seq 1 12); do
  docker run --rm \
    --env-file /opt/docextract.env \
    ${api_image_uri} \
    alembic upgrade head && break || (echo "Migration attempt $i failed, retrying in 10s..." && sleep 10)
done

# ── API service ──────────────────────────────
docker run -d \
  --name docextract-api \
  --restart unless-stopped \
  --env-file /opt/docextract.env \
  -p 8000:8000 \
  ${api_image_uri}

# ── ARQ worker ───────────────────────────────
docker run -d \
  --name docextract-worker \
  --restart unless-stopped \
  --env-file /opt/docextract.env \
  ${worker_image_uri} \
  python -m arq worker.main.WorkerSettings

echo "DocExtract bootstrap complete — API on :8000, using RDS Postgres + ElastiCache Redis"
