#!/usr/bin/env bash
# DocExtract on AWS ECS Fargate: deploy, measure, tear down.
#
# Run from the repo root on your own machine, with your own AWS credentials
# (aws configure / AWS_PROFILE). Nothing here stores or prints secret values.
#
#   scripts/aws/deploy.sh preflight   # tools, AWS identity, required TF_VARs (no cost)
#   scripts/aws/deploy.sh plan        # terraform plan (no cost)
#   scripts/aws/deploy.sh up          # BILLABLE: ECR -> push images -> full apply -> migrate
#   scripts/aws/deploy.sh push        # rebuild + push images, roll the service
#   scripts/aws/deploy.sh migrate     # alembic upgrade head inside the VPC
#   scripts/aws/deploy.sh seed-key    # create an upload API key (raw key saved locally only)
#   scripts/aws/deploy.sh status      # service state + /api/v1/health through the ALB
#   scripts/aws/deploy.sh down        # terraform destroy + tagged-resource sweep
#
# Required environment (set in your shell, never commit):
#   TF_VAR_rds_password        RDS master password (8+ chars; letters, digits, _ and - only,
#                              because it is embedded in DATABASE_URL)
#   TF_VAR_api_key_secret      32+ char secret used to HMAC API keys
#   TF_VAR_anthropic_api_key   Anthropic key for extraction
# Optional: TF_VAR_gemini_api_key, AWS_REGION (default us-west-2), AWS_PROFILE.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TF_DIR="$REPO_ROOT/deploy/aws-ecs"
STATE_DIR="${DOCEXTRACT_AWS_STATE_DIR:-$HOME/.docextract-aws}"
export AWS_REGION="${AWS_REGION:-us-west-2}"
export TF_VAR_region="$AWS_REGION"
ARCH="${TF_VAR_cpu_architecture:-ARM64}"
case "$ARCH" in
  ARM64) PLATFORM=linux/arm64 ;;
  X86_64) PLATFORM=linux/amd64 ;;
  *) echo "TF_VAR_cpu_architecture must be ARM64 or X86_64" >&2; exit 1 ;;
esac

log() { printf '\033[1m==>\033[0m %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }
tf() { terraform -chdir="$TF_DIR" "$@"; }
out() { tf output -raw "$1"; }

confirm_billable() {
  local what="$1"
  echo
  echo "This will $what in AWS account $(aws sts get-caller-identity --query Account --output text), region $AWS_REGION."
  echo "It costs money while it runs (see docs/aws-deploy.md for the estimate)."
  read -r -p "Type 'deploy' to continue: " answer
  [[ "$answer" == "deploy" ]] || die "cancelled"
}

preflight() {
  log "Checking tools"
  for bin in aws terraform docker python3; do
    command -v "$bin" >/dev/null || die "$bin is not installed"
  done
  docker buildx version >/dev/null 2>&1 || die "docker buildx is required"

  log "Checking AWS identity"
  aws sts get-caller-identity --query '{Account:Account,Arn:Arn}' --output table \
    || die "no working AWS credentials; run 'aws configure' or set AWS_PROFILE"

  log "Checking required variables (values are not printed)"
  [[ -n "${TF_VAR_rds_password:-}" ]] || die "TF_VAR_rds_password is not set"
  [[ ${#TF_VAR_rds_password} -ge 8 ]] || die "TF_VAR_rds_password must be 8+ characters"
  [[ "$TF_VAR_rds_password" =~ ^[A-Za-z0-9_-]+$ ]] || die "TF_VAR_rds_password may only use letters, digits, _ and -"
  [[ -n "${TF_VAR_api_key_secret:-}" ]] || die "TF_VAR_api_key_secret is not set"
  [[ ${#TF_VAR_api_key_secret} -ge 32 ]] || die "TF_VAR_api_key_secret must be 32+ characters"
  [[ -n "${TF_VAR_anthropic_api_key:-}" ]] || die "TF_VAR_anthropic_api_key is not set"
  echo "ok: region $AWS_REGION, architecture $ARCH"
}

init() { tf init -input=false >/dev/null; }

plan() {
  preflight
  init
  tf plan -input=false
}

push() {
  local api_repo worker_repo registry tag
  api_repo="$(out ecr_repo_url)"
  worker_repo="$(out ecr_worker_repo_url)"
  registry="${api_repo%%/*}"
  tag="$(git -C "$REPO_ROOT" rev-parse --short HEAD)"

  log "Logging Docker in to $registry"
  aws ecr get-login-password --region "$AWS_REGION" \
    | docker login --username AWS --password-stdin "$registry" >/dev/null

  log "Building and pushing $PLATFORM images tagged $tag and latest"
  docker buildx build --platform "$PLATFORM" -f "$REPO_ROOT/Dockerfile" \
    -t "$api_repo:$tag" -t "$api_repo:latest" --push "$REPO_ROOT"
  docker buildx build --platform "$PLATFORM" -f "$REPO_ROOT/Dockerfile.worker" \
    -t "$worker_repo:$tag" -t "$worker_repo:latest" --push "$REPO_ROOT"

  if tf state list 2>/dev/null | grep -q '^aws_ecs_service.api$'; then
    log "Rolling the service onto the new images"
    aws ecs update-service --cluster "$(out ecs_cluster_name)" \
      --service "$(out api_service_name)" --force-new-deployment >/dev/null
  fi
}

# run_ops <container-overrides-json>: run a one-off ops task and fail on non-zero exit
run_ops() {
  local overrides="$1" cluster subnets sg task_arn code
  cluster="$(out ecs_cluster_name)"
  subnets="$(tf output -json public_subnet_ids | python3 -c 'import json,sys;print(",".join(json.load(sys.stdin)))')"
  sg="$(out ecs_tasks_security_group_id)"
  task_arn="$(aws ecs run-task --cluster "$cluster" --launch-type FARGATE \
    --task-definition "$(out ops_task_family)" \
    --network-configuration "awsvpcConfiguration={subnets=[$subnets],securityGroups=[$sg],assignPublicIp=ENABLED}" \
    --overrides "$overrides" --query 'tasks[0].taskArn' --output text)"
  [[ "$task_arn" == arn:* ]] || die "ops task did not start"
  log "Waiting for ops task ${task_arn##*/}"
  aws ecs wait tasks-stopped --cluster "$cluster" --tasks "$task_arn"
  code="$(aws ecs describe-tasks --cluster "$cluster" --tasks "$task_arn" \
    --query 'tasks[0].containers[0].exitCode' --output text)"
  [[ "$code" == "0" ]] || die "ops task exited with $code; see CloudWatch log group /ecs/$(out project_tag), stream prefix ops"
}

migrate() {
  log "Running alembic upgrade head inside the VPC"
  run_ops '{"containerOverrides":[{"name":"ops","command":["alembic","upgrade","head"]}]}'
  echo "ok: migrations applied"
}

seed_key() {
  [[ -n "${TF_VAR_api_key_secret:-}" ]] || die "TF_VAR_api_key_secret is not set (needed to hash the key locally)"
  mkdir -p "$STATE_DIR"; chmod 700 "$STATE_DIR"
  local key_file="$STATE_DIR/bench_api_key" key_hash overrides
  # Generate the key and its HMAC here; only the hash goes to AWS.
  umask 077
  python3 -c 'import secrets;print("dex_bench_"+secrets.token_hex(24))' > "$key_file"
  key_hash="$(KEY_FILE="$key_file" python3 -c '
import hashlib, hmac, os
key = open(os.environ["KEY_FILE"]).read().strip()
print(hmac.new(os.environ["TF_VAR_api_key_secret"].encode(), key.encode(), hashlib.sha256).hexdigest())')"
  overrides="$(KEY_HASH="$key_hash" python3 -c '
import json, os
print(json.dumps({"containerOverrides": [{"name": "ops",
  "command": ["python", "-m", "scripts.seed_api_key", "--name", "bench-key", "--rate-limit", "600"],
  "environment": [{"name": "SEED_KEY_HASH", "value": os.environ["KEY_HASH"]}]}]}))')"
  log "Seeding an upload API key (hash only)"
  run_ops "$overrides"
  echo "ok: raw key saved to $key_file (mode 600). Export it with:"
  echo "  export DOCEXTRACT_API_KEY=\"\$(cat $key_file)\""
}

status() {
  local url
  url="http://$(out alb_dns_name)"
  aws ecs describe-services --cluster "$(out ecs_cluster_name)" --services "$(out api_service_name)" \
    --query 'services[0].{desired:desiredCount,running:runningCount,pending:pendingCount}' --output table
  log "GET $url/api/v1/health"
  curl -fsS --max-time 10 "$url/api/v1/health" && echo
  echo "Base URL: $url"
}

up() {
  preflight
  init
  confirm_billable "create the DocExtract stack (Fargate, ALB, RDS, S3, ECR)"
  log "Step 1/4: ECR repositories"
  tf apply -input=false -auto-approve -target=aws_ecr_repository.api -target=aws_ecr_repository.worker
  log "Step 2/4: images"
  push
  log "Step 3/4: everything else"
  tf apply -input=false -auto-approve
  log "Step 4/4: migrations"
  migrate
  log "Waiting for the service to become stable"
  aws ecs wait services-stable --cluster "$(out ecs_cluster_name)" --services "$(out api_service_name)"
  status
  echo
  echo "Next: scripts/aws/deploy.sh seed-key, then python scripts/bench_live.py (see docs/aws-deploy.md)."
}

down() {
  init
  local tag
  tag="$(out project_tag 2>/dev/null || echo docextract-hiring-proof)"
  echo "This destroys every resource in the stack, including the database and stored documents."
  read -r -p "Type 'destroy' to continue: " answer
  [[ "$answer" == "destroy" ]] || die "cancelled"
  tf destroy -input=false -auto-approve
  log "Sweeping for anything still tagged Project=$tag"
  local left
  left="$(aws resourcegroupstaggingapi get-resources --tag-filters "Key=Project,Values=$tag" \
    --query 'ResourceTagMappingList[].ResourceARN' --output text)"
  if [[ -n "$left" && "$left" != "None" ]]; then
    echo "Still tagged (may be deleting, or need manual cleanup):"
    tr '\t' '\n' <<<"$left"
  else
    echo "ok: nothing tagged Project=$tag remains"
  fi
}

case "${1:-}" in
  preflight) preflight ;;
  plan) plan ;;
  up) up ;;
  push) init; push ;;
  migrate) init; migrate ;;
  seed-key) init; seed_key ;;
  status) init; status ;;
  down) down ;;
  *) sed -n '2,20p' "$0"; exit 1 ;;
esac
