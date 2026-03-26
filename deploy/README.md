# Deploy Directory

This directory contains infrastructure configuration for deploying DocExtract to production environments. Four subdirectories cover Kubernetes, AWS Terraform, Grafana dashboards, and Prometheus scrape config.

---

## Directory Structure

```
deploy/
├── k8s/                    Kubernetes manifests (Kustomize)
│   ├── api-deployment.yaml
│   ├── api-service.yaml
│   ├── worker-deployment.yaml
│   ├── frontend-deployment.yaml
│   ├── frontend-service.yaml
│   ├── hpa.yaml            Horizontal Pod Autoscaler (API + Worker)
│   ├── ingress.yaml
│   ├── configmap.yaml
│   ├── secrets.yaml
│   ├── namespace.yaml
│   ├── kustomization.yaml
│   └── overlays/           Environment-specific patches
│       └── production/
├── aws/                    Terraform for managed AWS services
│   ├── main.tf             RDS, ElastiCache, ECR, S3, EC2, IAM, VPC
│   ├── variables.tf
│   ├── outputs.tf
│   └── user_data.sh        EC2 bootstrap (pulls images, runs compose)
├── grafana/                Grafana dashboard and datasource config
│   ├── docextract-dashboard.json   9-panel LLM observability dashboard
│   ├── datasource.yaml
│   └── dashboard-provider.yaml
└── prometheus/
    └── prometheus.yml      Scrape config for API metrics endpoint
```

---

## Kubernetes

### Services

Three Kubernetes deployments, each with its own HPA:

**API** (`api-deployment.yaml`)
- Image: `docextract-api:latest`
- Port: 8000
- Replicas: 2 min, 8 max
- Resources: 100m–500m CPU, 256Mi–512Mi memory
- Health checks: `/api/v1/health` (readiness + liveness)
- Rolling update: `maxUnavailable: 0` (zero-downtime deploys)

**Worker** (`worker-deployment.yaml`)
- Image: `docextract-worker:latest`
- Replicas: 2 min, 6 max
- No inbound port (pulls jobs from Redis queue)
- Scales on CPU (OCR and embedding are the bottlenecks)

**Frontend** (`frontend-deployment.yaml`)
- Image: `docextract-frontend:latest`
- Port: 8501 (Streamlit)

### Autoscaling (HPA)

`hpa.yaml` configures two HPAs:

| Target | Min | Max | Scale-Up Trigger | Scale-Down Window |
|--------|-----|-----|-----------------|------------------|
| API | 2 | 8 | CPU > 70% or Memory > 80% | 5 minutes |
| Worker | 2 | 6 | CPU > 70% | 5 minutes |

Worker scale-up is immediate (`stabilizationWindowSeconds: 0`) to handle burst document uploads. API scale-up has a 30s stabilization window to avoid reacting to transient spikes.

### Kustomize

Base manifests in `deploy/k8s/`. Environment-specific patches live in `deploy/k8s/overlays/production/`.

Kustomize overlays can patch image tags, replica counts, resource limits, and environment-specific config without duplicating base manifests.

### Deployment Commands

```bash
# Apply to cluster
kubectl apply -k deploy/k8s/

# Apply production overlay
kubectl apply -k deploy/k8s/overlays/production/

# Check rollout status
kubectl rollout status deployment/docextract-api -n docextract

# Scale worker manually
kubectl scale deployment/docextract-worker --replicas=4 -n docextract
```

---

## AWS Terraform

### What Gets Provisioned

`deploy/aws/main.tf` provisions:

| Resource | Type | Purpose |
|----------|------|---------|
| RDS PostgreSQL 16 | db.t3.micro | Primary database with pgvector |
| ElastiCache Redis 7 | cache.t3.micro | Job queue, rate limiting, SSE |
| S3 bucket | Standard | Document storage (AES-256, versioning enabled) |
| ECR (x2) | One per service | Container image registry for API + Worker |
| EC2 | t3.small (default) | Application host |
| IAM role + profile | — | EC2 → ECR pull + S3 read/write |
| Security groups | — | API port 8000, SSH, RDS 5432, Redis 6379 |

### Key Configuration

- RDS uses the default postgres16 parameter group. The pgvector extension is enabled by migration `002_pgvector_extension.py` on first run.
- S3 bucket name includes the AWS account ID as a suffix to guarantee global uniqueness.
- ECR repositories have `scan_on_push = true` for automated vulnerability scanning.
- `user_data.sh` bootstraps the EC2 instance: installs Docker, logs into ECR, pulls images, and starts services.

### Deployment Commands

```bash
cd deploy/aws

# Initialize
terraform init

# Preview
terraform plan -var="anthropic_api_key=sk-ant-..." -var="db_password=..."

# Apply
terraform apply -var="anthropic_api_key=sk-ant-..." -var="db_password=..."

# Get outputs (ECR URIs, RDS endpoint, etc.)
terraform output

# Destroy
terraform destroy
```

### Cost Estimate

Running continuously at minimum configuration:

| Resource | Monthly Cost |
|----------|-------------|
| RDS db.t3.micro | ~$25 |
| ElastiCache cache.t3.micro | ~$15 |
| EC2 t3.small | ~$15 |
| S3 (first 10GB) | ~$0.23 |
| ECR storage | ~$1 |
| **Total** | **~$56/mo** |

For full EKS + managed services, see `deploy/COST_ANALYSIS.md`.

---

## Grafana

### Dashboard: `docextract-dashboard.json`

A 9-panel Grafana dashboard for LLM pipeline observability. Import via the Grafana UI or provision automatically with `dashboard-provider.yaml`.

**Panel breakdown:**

| Panel | Metric | Query |
|-------|--------|-------|
| LLM Call Latency p50/p95/p99 | ms by model | `histogram_quantile(0.95, ...)` |
| Latency by Operation | ms by operation type | extract, classify, embed, retrieve |
| Queue Depth | pending jobs | ARQ queue length |
| Extraction Accuracy | rolling accuracy % | vs. eval threshold |
| Cache Hit Rate | % semantic cache hits | hits / (hits + misses) |
| Token Cost | USD/hour by model | token counts × per-model pricing |
| Circuit Breaker State | CLOSED/OPEN/HALF_OPEN | per model |
| Request Throughput | req/min | by endpoint |
| Error Rate | % by endpoint | 4xx + 5xx |

Requires `OTEL_ENABLED=true` on the API service for the `/metrics` endpoint to be active.

### Provisioning

```bash
# With Docker Compose observability stack
docker compose -f docker-compose.observability.yml up -d

# Grafana UI available at http://localhost:3000
# Default credentials: admin / admin
```

---

## Prometheus

`prometheus/prometheus.yml` configures Prometheus to scrape the DocExtract API:

```yaml
scrape_configs:
  - job_name: docextract-api
    static_configs:
      - targets:
          - docextract-api:8000
    metrics_path: /metrics
```

The target uses the Docker Compose service name `docextract-api`. For K8s deployments, replace with the service DNS name or use the Prometheus Kubernetes service discovery.

Prometheus is included in the observability Docker Compose file (`docker-compose.observability.yml`).

---

## Why This Architecture

**Stateless API + async worker** separates concerns cleanly. The API handles request routing, auth, and SSE streaming. The worker handles the slow operations: OCR, LLM calls, embedding generation, webhook delivery. Each scales independently.

Document processing is inherently bursty (batch uploads at start of business day, spike during contract review cycles). The worker HPA handles this without over-provisioning a fixed-size fleet.

**Managed databases** (RDS + ElastiCache) reduce operational overhead: automated backups, point-in-time recovery, minor version patching, and multi-AZ failover are handled by the provider. The tradeoff is cost (~$40/mo) vs. running self-hosted PostgreSQL + Redis on EC2 (saves ~$30/mo but requires manual backup and failover configuration).
