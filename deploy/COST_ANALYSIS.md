# Deployment Cost Analysis

Comparison of four deployment options for DocExtract. All figures are USD/month at minimum viable configuration unless otherwise noted. AWS and GCP pricing as of Q1 2026 (us-east-1 / us-central1).

---

## Option A: Docker Compose on a VPS

**Target**: Evaluation, internal tools, teams under 50 users

| Component | Provider | Monthly Cost |
|-----------|----------|-------------|
| VPS (4 vCPU, 8GB RAM) | DigitalOcean Droplet (s-4vcpu-8gb) | $24 |
| Managed PostgreSQL (optional) | DigitalOcean DBs | $15 |
| Redis (bundled in Docker) | Included in VPS | $0 |
| File storage (local disk) | Included in VPS | $0 |
| **Total (self-managed DB)** | | **$24/mo** |
| **Total (managed DB)** | | **$39/mo** |

**Setup**: `git clone`, set env vars, `docker compose up -d`. Running in under 30 minutes.

**Tradeoffs**:
- No auto-scaling. Single point of failure.
- Manual backup configuration required.
- Suitable for internal use only. Not recommended for customer-facing workloads.

---

## Option B: Render Blueprint

**Target**: Early production, startups, no DevOps capacity

| Component | Render Plan | Monthly Cost |
|-----------|------------|-------------|
| API service (web) | Starter ($7/mo) | $7 |
| Worker service (background) | Starter ($7/mo) | $7 |
| PostgreSQL | Starter ($7/mo) | $7 |
| Redis | Starter ($7/mo) | $7 |
| File storage | Render Disk 10GB | $2.50 |
| **Total** | | **~$35/mo** |

**Setup**: Push `render.yaml` to GitHub, connect in Render dashboard. Running in under 15 minutes.

**Tradeoffs**:
- Easiest setup of any option.
- No DevOps knowledge required.
- Limited scaling. Starter services have 512MB RAM.
- Cold starts on free-tier services cause 30-60s first-request delay.
- Not suitable for processing large document batches or high-volume workloads.

---

## Option C: AWS Terraform

**Target**: Enterprise, compliance-sensitive, high volume

| Component | AWS Resource | Monthly Cost |
|-----------|-------------|-------------|
| RDS PostgreSQL 16 | db.t3.micro, 20GB gp3 | ~$25 |
| ElastiCache Redis 7 | cache.t3.micro | ~$15 |
| EC2 (API + Worker) | t3.small | ~$15 |
| EKS cluster (if using K8s) | Control plane | ~$72 |
| EKS worker nodes | 2x t3.medium | ~$60 |
| S3 document storage | Standard, first 50GB | ~$1.15 |
| ECR storage | First 500MB free | ~$1 |
| Data transfer | First 100GB free | ~$0 |
| **Total (EC2, no EKS)** | | **~$57/mo** |
| **Total (EKS)** | | **~$190/mo** |

**Setup**: `terraform init && terraform apply`. ECR image push + EC2 bootstrap via `user_data.sh`. Allow 2-4 hours for first provisioning.

**Tradeoffs**:
- Full enterprise: managed backups, point-in-time recovery, VPC isolation, IAM roles.
- ECR scan-on-push for container vulnerability detection.
- EKS adds $72/mo for the control plane but enables autoscaling to thousands of documents/day.
- Highest operational complexity. Requires AWS familiarity.
- Recommended for HIPAA or SOC 2 deployments.

---

## Option D: Kubernetes on GKE Autopilot

**Target**: Teams with existing K8s infrastructure or Google Cloud preference

| Component | GKE Resource | Monthly Cost |
|-----------|-------------|-------------|
| GKE Autopilot cluster | Provisioned on demand | ~$72 |
| Cloud SQL PostgreSQL 16 | db-f1-micro | ~$25 |
| Memorystore Redis | Basic, 1GB | ~$35 |
| GCS document storage | Standard, first 50GB | ~$1 |
| **Total** | | **~$133/mo** |

**Setup**: `kubectl apply -k deploy/k8s/`. Kustomize overlays handle GKE-specific configuration. Allow 4-8 hours for first setup including image builds and container registry push.

**Tradeoffs**:
- GKE Autopilot handles node provisioning automatically. No node pool management.
- Kustomize manifests in `deploy/k8s/` work without modification on GKE.
- Memorystore Redis is pricier than ElastiCache at this tier (~$20/mo more).
- Better choice than AWS if already on Google Cloud.

---

## Claude API Costs

Separate from infrastructure. Charged per token by Anthropic.

| Operation | Model | Cost per Document |
|-----------|-------|-----------------|
| Extraction (Pass 1) | claude-sonnet-4-6 | ~$0.0025 |
| Extraction (Pass 2, if triggered) | claude-sonnet-4-6 | ~$0.0010 |
| Classification | claude-haiku-4-5 | ~$0.00005 |
| **Average per document** | | **~$0.003** |

Pass 2 is only triggered when Pass 1 confidence falls below 0.80. Approximately 15-20% of documents trigger Pass 2, which is factored into the per-document average above.

### Semantic Cache Impact

`app/services/semantic_cache.py` caches extraction responses by embedding similarity. For repeated or near-duplicate documents:

| Cache State | Cost per Document |
|-------------|-----------------|
| Cache miss (fresh document) | ~$0.003 |
| Cache hit | ~$0.0003 (embedding lookup only) |

Cache hit rate approaches 90%+ after a warmup period for document libraries with recurring templates (invoices, standard contracts, form letters). For fully unique document corpora (e.g., one-off research papers), expect low hit rates.

---

## Total Cost of Ownership by Scale

Assumes 22 working days/month. Infrastructure cost is fixed; API cost scales with volume.

### 100 Documents/Day (~2,200/month)

| Option | Infrastructure | API (0% cache) | API (90% cache) | Total (90% cache) |
|--------|---------------|----------------|----------------|-----------------|
| A (VPS) | $24 | $6.60 | $0.99 | **$25/mo** |
| B (Render) | $35 | $6.60 | $0.99 | **$36/mo** |
| C (AWS EC2) | $57 | $6.60 | $0.99 | **$58/mo** |
| D (GKE) | $133 | $6.60 | $0.99 | **$134/mo** |

### 1,000 Documents/Day (~22,000/month)

| Option | Infrastructure | API (0% cache) | API (90% cache) | Total (90% cache) |
|--------|---------------|----------------|----------------|-----------------|
| A (VPS) | $24 | $66 | $9.90 | **$34/mo** |
| B (Render) | $35+ | $66 | $9.90 | Likely need to upgrade plan |
| C (AWS EC2) | $57 | $66 | $9.90 | **$67/mo** |
| D (GKE) | $133 | $66 | $9.90 | **$143/mo** |

At 1,000 docs/day, VPS CPU and memory become the bottleneck. Upgrade to a $48/mo Droplet (8 vCPU, 16GB) or move to Option C.

### 10,000 Documents/Day (~220,000/month)

At this volume, K8s autoscaling is required. Worker HPA (2-6 replicas) handles document processing bursts. Estimate infrastructure at Option C (EKS) or D (GKE).

| Option | Infrastructure | API (0% cache) | API (90% cache) | Total (90% cache) |
|--------|---------------|----------------|----------------|-----------------|
| C (AWS EKS) | $190 | $660 | $99 | **$289/mo** |
| D (GKE Autopilot) | $133+ | $660 | $99 | **$232+/mo** |

At 90% cache hit rate, the cache saves ~$560/month in API costs at 10,000 docs/day.

---

## When Each Option Makes Sense

**Option A (VPS)**
- Evaluating the platform before committing to infrastructure
- Internal tools for a small team
- Document volume under 500/day
- Budget is the primary constraint

**Option B (Render)**
- Fast launch without DevOps investment
- Teams without AWS/GCP/K8s experience
- Document volume under 1,000/day
- Willing to accept cold start latency and limited scaling

**Option C (AWS Terraform)**
- HIPAA, SOC 2, or other compliance requirements
- Document volume over 1,000/day
- Need point-in-time recovery and multi-AZ failover
- Already operating on AWS
- EKS variant for volume over 5,000/day

**Option D (GKE)**
- Already operating on Google Cloud
- Existing K8s operational expertise
- Autopilot cluster eliminates node management overhead
- Acceptable to pay slightly higher Redis cost for operational simplicity
