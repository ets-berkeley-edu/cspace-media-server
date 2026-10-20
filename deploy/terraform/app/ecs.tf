# The app and the worker (D188): two Fargate services on ARM from one image, each with its own role (iam.tf).

resource "aws_cloudwatch_log_group" "web" {
  name              = "/serena/${var.env_name}/web"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.main.arn
  depends_on        = [aws_kms_key_policy.main] # the key's policy lets CloudWatch Logs use it
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/serena/${var.env_name}/worker"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.main.arn
  depends_on        = [aws_kms_key_policy.main] # the key's policy lets CloudWatch Logs use it
}

resource "aws_ecs_cluster" "main" {
  name = local.name
}

locals {
  image_tag = reverse(split(":", var.image_uri))[0]

  # Serena's settings (backend/serena/config.py; .env.example); backend/tests/test_deploy.py checks that each one
  # exists. No secret is a setting: these name the secrets, which the tasks read from Secrets Manager.
  app_environment = {
    SERENA_TENANTS                = jsonencode(var.tenants)
    SERENA_ENV_LABEL              = var.env_label
    SERENA_BUILD                  = local.image_tag
    SERENA_AWS_REGION             = var.region
    SERENA_LOG_LEVEL              = "INFO"
    SERENA_TABLE_PREFIX           = local.name
    SERENA_BUCKETS                = jsonencode(local.buckets)
    SERENA_ETL_TOKEN_SECRET_IDS   = jsonencode({ for m, s in aws_secretsmanager_secret.etl_tokens : m => s.name })
    SERENA_CSPACE_SECRET_IDS      = jsonencode({ for m, s in aws_secretsmanager_secret.cspace : m => s.name })
    SERENA_SIGNING_KEY_SECRET_IDS = jsonencode({ for m, s in aws_secretsmanager_secret.portal_key : m => s.name })
  }
  # The Past requests page queries the app's own log group (D110). The unavailable images are always CloudFront's
  # (D199); the museums' files once there is a signing key (D200). The worker emails the alerts (D201).
  web_environment = merge(local.app_environment,
    {
      SERENA_LOG_GROUP            = aws_cloudwatch_log_group.web.name
      SERENA_UNAVAILABLE_BASE_URL = "https://${aws_cloudfront_distribution.main.domain_name}"
    },
    local.delivery ? {
      SERENA_CDN_BASE_URL             = "https://${aws_cloudfront_distribution.main.domain_name}"
      SERENA_CLOUDFRONT_KEY_SECRET_ID = aws_secretsmanager_secret.cdn_key.name
  } : {})
  worker_environment = merge(local.app_environment, { SERENA_ALERT_TOPIC_ARN = aws_sns_topic.alerts.arn })
}

resource "aws_ecs_task_definition" "web" {
  family                   = "${local.name}-web"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.web_cpu
  memory                   = var.web_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.web.arn

  runtime_platform {
    cpu_architecture        = "ARM64"
    operating_system_family = "LINUX"
  }

  # Where fetched files are written while they're hashed and checked (design: Image fetch).
  ephemeral_storage {
    size_in_gib = var.web_disk_gib
  }

  # No command: the image's own, uvicorn on port 8000 (deploy/Dockerfile).
  container_definitions = jsonencode([{
    name         = "web"
    image        = var.image_uri
    essential    = true
    environment  = [for name, value in local.web_environment : { name = name, value = value }]
    portMappings = [{ containerPort = 8000, protocol = "tcp" }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.web.name
        awslogs-region        = var.region
        awslogs-stream-prefix = "web"
      }
    }
  }])
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "${local.name}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.worker_cpu
  memory                   = var.worker_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.worker.arn

  runtime_platform {
    cpu_architecture        = "ARM64"
    operating_system_family = "LINUX"
  }

  container_definitions = jsonencode([{
    name        = "worker"
    image       = var.image_uri
    essential   = true
    command     = ["python", "-m", "serena.worker"]
    stopTimeout = 120
    environment = [for name, value in local.worker_environment : { name = name, value = value }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.worker.name
        awslogs-region        = var.region
        awslogs-stream-prefix = "worker"
      }
    }
  }])
}

resource "aws_ecs_service" "web" {
  name            = "web"
  cluster         = aws_ecs_cluster.main.id
  launch_type     = "FARGATE"
  task_definition = aws_ecs_task_definition.web.arn
  desired_count   = var.running ? var.web_count : 0
  propagate_tags  = "SERVICE"

  # Replaced one by one, and rolled back if the new tasks don't start (D188).
  health_check_grace_period_seconds  = 60
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  wait_for_steady_state              = true

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    assign_public_ip = true
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.web.id]
  }

  load_balancer {
    container_name   = "web"
    container_port   = 8000
    target_group_arn = aws_lb_target_group.web.arn
  }

  depends_on = [aws_lb_listener.http, aws_iam_role_policy.web, aws_route_table_association.public]
}

resource "aws_ecs_service" "worker" {
  name            = "worker"
  cluster         = aws_ecs_cluster.main.id
  launch_type     = "FARGATE"
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = var.running ? 1 : 0
  propagate_tags  = "SERVICE"

  # One worker at a time: the old one stops before the new one starts (D188). (Zone rebalancing needs room to start
  # a second task, so it is off.)
  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100
  availability_zone_rebalancing      = "DISABLED"
  wait_for_steady_state              = true

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    assign_public_ip = true
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.worker.id]
  }

  depends_on = [aws_iam_role_policy.worker, aws_route_table_association.public]
}
