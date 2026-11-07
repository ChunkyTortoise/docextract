# Deploying DocExtract to AWS (ECS Fargate) and measuring it

This runbook deploys the stack in [`deploy/aws-ecs/`](../deploy/aws-ecs/), measures
end-to-end latency and cost per document against the live deployment, and tears it
down. Nothing in this repo has been deployed by following it yet; the README's
"Live AWS deployment" numbers stay empty until a run is committed.

## What gets created

| Piece | Choice | Why |
|---|---|---|
| Compute | 1 Fargate task, ARM64, 0.5 vCPU / 2 GB, with three containers: Redis, API, ARQ worker | API and worker must share one Redis queue; co-locating avoids ElastiCache |
| Load balancer | ALB, HTTP on port 80 | Stable public URL and health checks |
| Database | RDS PostgreSQL 15, db.t4g.micro, 20 GB gp3, single-AZ, private | pgvector; no backups (teardown environment) |
| Documents | S3, SSE-S3, public access blocked | Read and written with the task role, no access keys |
| Secrets | SSM Parameter Store SecureString | Not plaintext in the task definition |
| Network | New VPC, 2 public subnets, no NAT gateway | Tasks get a public IP for egress instead of a ~$33/month NAT |
| Logs | CloudWatch, 1-day retention | |

There is no custom domain or HTTPS. The ALB URL is `http://<name>.us-west-2.elb.amazonaws.com`.

## Monthly cost estimate (us-west-2)

On-demand prices from the AWS Price List API (offer files published 2026-10-19),
730 hours a month. LLM spend is separate and depends on traffic.

| Item | Rate | Per month |
|---|---|---|
| Fargate ARM64: 0.5 vCPU + 2 GB | $0.03238/vCPU-h, $0.00356/GB-h | $17.02 |
| Application Load Balancer | $0.0225/h + ~0.2 LCU at $0.008/LCU-h | $17.60 |
| RDS db.t4g.micro + 20 GB gp3 | $0.016/h, $0.115/GB-mo | $13.98 |
| Public IPv4 addresses: ALB (2) + task (1) | $0.005/h each | $10.95 |
| ECR, CloudWatch Logs, S3, SSM | $0.10/GB-mo, $0.50/GB ingested | ~$1 |
| **Total, always on** | **~$0.083/hour** | **~$60** |

For comparison, the previous defaults (x86, two 0.5 vCPU / 1 GB tasks) came to
about $83 a month. A one-day measure-and-teardown run costs about $2 of
infrastructure plus the LLM calls it makes.

Pass `--infra-hourly-usd 0.083` to `scripts/bench_live.py`.

## Before you start (on your own machine)

1. An AWS account with billing set up, and credentials for it in your shell
   (`aws configure` or `AWS_PROFILE`). An IAM user or SSO role that can manage
   VPC, ECS, ECR, RDS, S3, IAM roles, SSM, ELB and CloudWatch Logs.
2. A budget alarm, so a forgotten stack can't run up a bill (the first two
   AWS Budgets are free). In the AWS console: Billing → Budgets → Create budget,
   or with the CLI.
3. Tools: AWS CLI v2, Terraform ≥ 1.5, Docker with buildx, Python 3.12.
4. An Anthropic API key with credit. Gemini is optional (embeddings).
5. Secrets exported in your shell, never written to a file in the repo:

   ```bash
   export TF_VAR_rds_password='letters-digits-_-and-dash-only'
   export TF_VAR_api_key_secret='at-least-32-characters-of-random-text'
   export TF_VAR_anthropic_api_key='...'
   # optional: export TF_VAR_gemini_api_key='...'
   ```

Terraform state stays local in `deploy/aws-ecs/terraform.tfstate` and contains
those secrets. It is git-ignored; keep it that way.

## Deploy

```bash
scripts/aws/deploy.sh preflight   # checks tools, AWS identity and variables; free
scripts/aws/deploy.sh plan        # shows what would be created; free
scripts/aws/deploy.sh up          # asks you to type 'deploy', then creates everything
```

`up` creates the ECR repositories, builds and pushes ARM64 images tagged with the
git SHA, applies the rest, runs `alembic upgrade head` as a one-off task inside
the VPC (RDS is private), waits for the service and checks `/api/v1/health`.

## Measure

```bash
scripts/aws/deploy.sh seed-key    # key generated locally; only its hash goes to AWS
export DOCEXTRACT_API_KEY="$(cat ~/.docextract-aws/bench_api_key)"
python scripts/bench_live.py --base-url "http://$(terraform -chdir=deploy/aws-ecs output -raw alb_dns_name)" \
  --runs 10 --infra-hourly-usd 0.083
```

`bench_live.py` uploads each sample document, polls its job to completion one at
a time, and writes `eval_artifacts/bench_live_<timestamp>.json` with end-to-end
p50/p95, server processing time, the run's LLM tokens by model (from the
deployment's own traces) and infrastructure cost per document. Re-price the token
counts at current list prices before publishing; the app's price table is
approximate.

For extraction accuracy and per-document LLM cost over the 72-case corpus, also
run `scripts/benchmark.py` locally with the same API key.

## Tear down

```bash
scripts/aws/deploy.sh down        # asks you to type 'destroy'; then sweeps tagged leftovers
```

## Known limits

- One task means a short gap during redeploys.
- Each task has its own Redis; scaling out works because every task processes its
  own uploads, but queued jobs are lost if a task is replaced.
- The demo key (`DEMO_MODE`) is read-only; uploads need a seeded key.
