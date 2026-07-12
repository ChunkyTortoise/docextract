# ─── deploy/aws-ecs/ecs.tf ─────────────────────────────────────────────────────
# ECS Fargate cluster, IAM roles, task definitions, and services.
#
# API task: 2 containers sharing localhost networking (awsvpc mode)
#   1. api (FastAPI, port 8000)
#   2. redis sidecar (redis:7-alpine, port 6379)
#      The health check at /api/v1/health pings Redis; without a Redis sidecar
#      the ALB health check fails and ECS restart-loops.
#
# Worker task: desired_count=0 during stubbed load runs to prevent LLM spend.
#   Worker is defined here for completeness; set desired_count_worker=1 only
#   for the controlled real-batch measurement (Task 10).
#
# Container dependency ordering ensures Redis starts before the API container.
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

# Task execution role: pull images from ECR, write CloudWatch logs
resource "aws_iam_role" "ecs_task_execution" {
  name               = "${var.project_tag}-ecs-exec"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume_role.json
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Task role: S3 access for document storage
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

# ── API task definition ────────────────────────────────────────────────────────

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.project_tag}-api"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.fargate_cpu
  memory                   = var.fargate_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    # Redis sidecar — must start before the API container
    {
      name      = "redis"
      image     = "redis:7-alpine"
      essential = true # Redis crash must restart the whole task — the API health check pings Redis
      portMappings = [
        { containerPort = 6379, protocol = "tcp" }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "redis"
        }
      }
    },
    # API container — depends on Redis being started
    {
      name      = "api"
      image     = "${aws_ecr_repository.api.repository_url}:latest"
      essential = true
      portMappings = [
        { containerPort = 8000, protocol = "tcp" }
      ]
      dependsOn = [
        { containerName = "redis", condition = "START" }
      ]
      environment = [
        { name = "DATABASE_URL", value = "postgresql+asyncpg://${var.rds_username}:${var.rds_password}@${aws_db_instance.postgres.address}:5432/${var.rds_db_name}" },
        { name = "REDIS_URL", value = "redis://localhost:6379/0" },
        { name = "STORAGE_BACKEND", value = "s3" },
        { name = "R2_BUCKET_NAME", value = aws_s3_bucket.storage.bucket },
        { name = "ANTHROPIC_API_KEY", value = var.anthropic_api_key },
        { name = "GEMINI_API_KEY", value = var.gemini_api_key },
        { name = "API_KEY_SECRET", value = var.api_key_secret },
        { name = "DEMO_MODE", value = tostring(var.demo_mode) },
        { name = "DEMO_API_KEY", value = var.demo_api_key },
        { name = "STUB_EXTRACTION", value = tostring(var.stub_extraction) },
        { name = "ENVIRONMENT", value = "production" },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "api"
        }
      }
      healthCheck = {
        command     = ["CMD-SHELL", "curl -fsS http://localhost:8000/api/v1/health || exit 1"]
        interval    = 15
        timeout     = 5
        retries     = 3
        startPeriod = 30
      }
    }
  ])
}

# ── Worker task definition ─────────────────────────────────────────────────────

resource "aws_ecs_task_definition" "worker" {
  family                   = "${var.project_tag}-worker"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.fargate_cpu
  memory                   = var.fargate_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    # Redis sidecar — worker reads ARQ job queue from localhost Redis.
    # Each worker task carries its own Redis; for a multi-replica production
    # deployment you would replace this with a shared ElastiCache endpoint.
    # desired_count_worker=0 during all stubbed load runs, so this sidecar
    # only starts when a real batch run (Task 10) is intentionally launched.
    {
      name      = "redis"
      image     = "redis:7-alpine"
      essential = true
      portMappings = [
        { containerPort = 6379, protocol = "tcp" }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "worker-redis"
        }
      }
    },
    {
      name      = "worker"
      image     = "${aws_ecr_repository.worker.repository_url}:latest"
      essential = true
      dependsOn = [
        { containerName = "redis", condition = "START" }
      ]
      environment = [
        { name = "DATABASE_URL", value = "postgresql+asyncpg://${var.rds_username}:${var.rds_password}@${aws_db_instance.postgres.address}:5432/${var.rds_db_name}" },
        { name = "REDIS_URL", value = "redis://localhost:6379/0" },
        { name = "STORAGE_BACKEND", value = "s3" },
        { name = "R2_BUCKET_NAME", value = aws_s3_bucket.storage.bucket },
        { name = "ANTHROPIC_API_KEY", value = var.anthropic_api_key },
        { name = "GEMINI_API_KEY", value = var.gemini_api_key },
        { name = "STUB_EXTRACTION", value = tostring(var.stub_extraction) },
        { name = "ENVIRONMENT", value = "production" },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "worker"
        }
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

# ── API service ───────────────────────────────────────────────────────────────

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

  depends_on = [aws_lb_listener.http, aws_iam_role_policy_attachment.ecs_task_execution]

  # Allow in-place task replacement without service outage
  deployment_minimum_healthy_percent = 50
  deployment_maximum_percent         = 200
}

# ── Worker service ────────────────────────────────────────────────────────────

resource "aws_ecs_service" "worker" {
  name            = "${var.project_tag}-worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = var.desired_count_worker # 0 during stubbed load runs
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = var.assign_public_ip
  }

  depends_on = [aws_iam_role_policy_attachment.ecs_task_execution]
}
