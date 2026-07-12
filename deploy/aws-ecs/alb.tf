# ─── deploy/aws-ecs/alb.tf ─────────────────────────────────────────────────────
# Application Load Balancer, target group, and listener.
# Health check path: /api/v1/health (pings Redis + DB — same as local health check).
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_lb" "api" {
  name               = "${var.project_tag}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id

  # Deletion protection OFF — this is a teardown environment.
  enable_deletion_protection = false
}

resource "aws_lb_target_group" "api" {
  name        = "${var.project_tag}-tg"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip" # required for Fargate awsvpc network mode

  health_check {
    enabled             = true
    path                = "/api/v1/health"
    port                = "traffic-port"
    protocol            = "HTTP"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 15
    matcher             = "200"
  }

  deregistration_delay = 30 # reduce for faster teardown
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.api.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}
