#!/bin/bash
# EC2 bootstrap script — installs Docker, pulls images from ECR, starts the stack
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
cat > /opt/docextract.env <<EOF
ANTHROPIC_API_KEY=${anthropic_api_key}
GEMINI_API_KEY=${gemini_api_key}
STORAGE_BACKEND=s3
STORAGE_S3_BUCKET=${s3_bucket}
AWS_REGION=${aws_region}
DEMO_MODE=false
OTEL_ENABLED=false
DATABASE_URL=sqlite:////data/docextract.db
REDIS_URL=redis://localhost:6379/0
EOF

chmod 600 /opt/docextract.env

# ── Lightweight Redis (sidecar, no persistence required for demo) ──
docker run -d --name redis --restart unless-stopped -p 6379:6379 redis:7-alpine

# ── API service ──────────────────────────────
docker run -d \
  --name docextract-api \
  --restart unless-stopped \
  --env-file /opt/docextract.env \
  -v /data:/data \
  -p 8000:8000 \
  ${api_image_uri}

# ── ARQ worker ───────────────────────────────
docker run -d \
  --name docextract-worker \
  --restart unless-stopped \
  --env-file /opt/docextract.env \
  -v /data:/data \
  ${worker_image_uri} \
  python -m arq worker.main.WorkerSettings

echo "DocExtract bootstrap complete"
