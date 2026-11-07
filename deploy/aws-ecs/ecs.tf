# ─── deploy/aws-ecs/ecs.tf ─────────────────────────────────────────────────────
# ECS Fargate cluster, IAM roles, secrets, task definitions, and the service.
#
# One task, three containers sharing localhost (awsvpc mode):
#   1. redis  (redis:7-alpine, 6379): ARQ queue + rate limiting
#   2. api    (FastAPI, 8000):        enqueues jobs on localhost Redis
#   3. worker (ARQ):                  consumes the SAME localhost Redis
# The API and worker must share one Redis or uploaded jobs are never picked up;
# co-locating them is the cheapest way to do that (no ElastiCache). With
# desired_count_api > 1 each task still processes its own uploads end to end.
#
# A separate "ops" task definition (api image, no Redis, no service) runs
# one-off commands such as `alembic upgrade head`, because RDS is private.
#
# Secrets go to SSM Parameter Store (SecureString) and are injected with
# `secrets`/valueFrom, so they are not plaintext in the task definition.
# They are still in Terraform state: keep the state file local and private.
# ──────────────────────────────────────────────────────────────────────────────

data "aws_iam_policy_document" "ecs_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# Task execution role: pull images from ECR, write CloudWatch logs, read secrets
resource "aws_iam_role" "ecs_task_execution" {
  name               = "${var.project_tag}-ecs-exec"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume_role.json
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# ── Secrets (SSM Parameter Store, standard tier: no charge) ───────────────────

locals {
  database_url = "postgresql+asyncpg://${var.rds_username}:${var.rds_password}@${aws_db_instance.postgres.address}:5432/${var.rds_db_name}"

  # SSM rejects empty values, so optional keys are only created when set.
  secret_values = { for k, v in {
    DATABASE_URL      = local.database_url
    API_KEY_SECRET    = var.api_key_secret
    ANTHROPIC_API_KEY = var.anthropic_api_key
    GEMINI_API_KEY    = var.gemini_api_key
  } : k => v if v != "" }

  container_secrets = [
    for k in sort(keys(local.secret_values)) : {
      name      = k
      valueFrom = aws_ssm_parameter.secret[k].arn
    }
  ]

  common_environment = [
    { name = "REDIS_URL", value = "redis://localhost:6379/0" },
    { name = "STORAGE_BACKEND", value = "s3" },
    { name = "S3_BUCKET_NAME", value = aws_s3_bucket.storage.bucket },
    { name = "ENVIRONMENT", value = "production" },
  ]

  log_options = {
    "awslogs-group"  = aws_cloudwatch_log_group.ecs.name
    "awslogs-region" = var.region
  }
}

resource "aws_ssm_parameter" "secret" {
  for_each = nonsensitive(toset(keys(local.secret_values)))

  name  = "/${var.project_tag}/${each.key}"
  type  = "SecureString"
  value = local.secret_values[each.key]
}

data "aws_iam_policy_document" "ecs_exec_ssm" {
  statement {
    actions   = ["ssm:GetParameters"]
    resources = [for p in aws_ssm_parameter.secret : p.arn]
  }
}

resource "aws_iam_role_policy" "ecs_exec_ssm" {
  name   = "read-app-secrets"
  role   = aws_iam_role.ecs_task_execution.id
  policy = data.aws_iam_policy_document.ecs_exec_ssm.json
}

# Task role: S3 access for document storage (boto3 picks this up; no keys)
resource "aws_iam_role" "ecs_task" {
  name               = "${var.project_tag}-ecs-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume_role.json
}

data "aws_iam_policy_document" "ecs_task_s3" {
  statement {
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.storage.arn, "${aws_s3_bucket.storage.arn}/*"]
  }
}

resource "aws_iam_role_policy" "ecs_task_s3" {
  name   = "s3-access"
  role   = aws_iam_role.ecs_task.id
  policy = data.aws_iam_policy_document.ecs_task_s3.json
}

# CloudWatch log group
resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/${var.project_tag}"
  retention_in_days = 1 # teardown environment; minimize log storage cost
}

# ── App task definition (redis + api + worker) ────────────────────────────────

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.project_tag}-api"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.fargate_cpu
  memory                   = var.fargate_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  # Images are built on the operator's machine; ARM64 matches Apple Silicon
  # builds and Graviton Fargate is ~20% cheaper than X86_64.
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = var.cpu_architecture
  }

  container_definitions = jsonencode(concat(
    [
      # Redis sidecar — must start before the API and worker
      {
        name         = "redis"
        image        = "public.ecr.aws/docker/library/redis:7-alpine"
        essential    = true # the API health check pings Redis
        portMappings = [{ containerPort = 6379, protocol = "tcp" }]
        logConfiguration = {
          logDriver = "awslogs"
          options   = merge(local.log_options, { "awslogs-stream-prefix" = "redis" })
        }
      },
      {
        name         = "api"
        image        = "${aws_ecr_repository.api.repository_url}:${var.image_tag}"
        essential    = true
        portMappings = [{ containerPort = 8000, protocol = "tcp" }]
        dependsOn    = [{ containerName = "redis", condition = "START" }]
        environment = concat(local.common_environment, [
          { name = "DEMO_MODE", value = tostring(var.demo_mode) },
          { name = "DEMO_API_KEY", value = var.demo_api_key },
        ])
        secrets = local.container_secrets
        logConfiguration = {
          logDriver = "awslogs"
          options   = merge(local.log_options, { "awslogs-stream-prefix" = "api" })
        }
        # python:3.12-slim ships no curl, so probe with the Python stdlib.
        healthCheck = {
          command     = ["CMD-SHELL", "python -c \"import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/v1/health', timeout=4).status == 200 else 1)\""]
          interval    = 15
          timeout     = 5
          retries     = 3
          startPeriod = 30
        }
      },
    ],
    var.run_worker ? [
      {
        name      = "worker"
        image     = "${aws_ecr_repository.worker.repository_url}:${var.image_tag}"
        essential = true
        dependsOn = [{ containerName = "redis", condition = "START" }]
        environment = concat(local.common_environment, [
          { name = "WORKER_MAX_JOBS", value = tostring(var.worker_max_jobs) },
        ])
        secrets = local.container_secrets
        logConfiguration = {
          logDriver = "awslogs"
          options   = merge(local.log_options, { "awslogs-stream-prefix" = "worker" })
        }
      },
    ] : []
  ))
}

# ── Ops task definition (one-off: migrations, API key seeding) ───────────────
# Run with `aws ecs run-task ... --overrides` from scripts/aws/deploy.sh.

resource "aws_ecs_task_definition" "ops" {
  family                   = "${var.project_tag}-ops"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = var.cpu_architecture
  }

  container_definitions = jsonencode([
    {
      name        = "ops"
      image       = "${aws_ecr_repository.api.repository_url}:${var.image_tag}"
      essential   = true
      command     = ["alembic", "upgrade", "head"]
      environment = local.common_environment
      secrets     = local.container_secrets
      logConfiguration = {
        logDriver = "awslogs"
        options   = merge(local.log_options, { "awslogs-stream-prefix" = "ops" })
      }
    }
  ])
}

# ── ECS cluster ───────────────────────────────────────────────────────────────

resource "aws_ecs_cluster" "main" {
  name = var.project_tag
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name       = aws_ecs_cluster.main.name
  capacity_providers = ["FARGATE"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
  }
}

# ── App service ───────────────────────────────────────────────────────────────

resource "aws_ecs_service" "api" {
  name            = "${var.project_tag}-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.desired_count_api
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = var.assign_public_ip # true = no NAT gateway
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  depends_on = [
    aws_lb_listener.http,
    aws_iam_role_policy_attachment.ecs_task_execution,
    aws_iam_role_policy.ecs_exec_ssm,
  ]

  # With one task, allow a brief gap on redeploy; raise for zero-downtime.
  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 200
}
