# The simulated CollectionSpace and the fake ETL (D189), for an environment that tries Serena without a real
# CollectionSpace or ETL (SIMULATED_CSPACE=true in its settings; off by default). The root uses this module only
# when simulated_cspace is true. Both run from the local stack's image (backend/Dockerfile), never from Serena's.
#
# The simulator: one task with its data in memory (a pause, deploy or restart starts it empty, while Serena's tables
# keep theirs). Serena finds it by name through a private DNS namespace (Cloud Map), each museum under its own path
# (http://fakecspace.serena-<env>.internal:8180/<museum>; backend/fakecspace/app.py, MuseumPrefix). Only the app, the
# worker and the fake ETL can connect to it.
#
# The fake ETL: a task definition with no service. ./serena aws etl <museum> runs it once, inside the VPC: it adds the
# day's synthetic records to the simulator and runs a whole daily refresh through Serena's ETL API, by the load
# balancer, with the museum's ETL token, which it reads from Secrets Manager itself (backend/devtools/fake_etl.py).

locals {
  name          = var.name
  simulator_url = "http://fakecspace.${local.name}.internal:8180"
}

resource "aws_service_discovery_private_dns_namespace" "main" {
  name        = "${local.name}.internal"
  description = "Names inside Serena's VPC: the simulated CollectionSpace"
  vpc         = var.vpc_id
}

resource "aws_service_discovery_service" "fakecspace" {
  name = "fakecspace"

  dns_config {
    namespace_id   = aws_service_discovery_private_dns_namespace.main.id
    routing_policy = "MULTIVALUE"

    dns_records {
      type = "A"
      ttl  = 10
    }
  }
}

# One group for the simulator and the fake ETL: the fake ETL calls the simulator, and the load balancer.
resource "aws_security_group" "devtools" {
  name        = "${local.name}-devtools"
  description = "Simulated CollectionSpace and fake ETL. Only Serena and the fake ETL reach the simulator."
  vpc_id      = var.vpc_id

  tags = { Name = "${local.name}-devtools" }
}

resource "aws_vpc_security_group_ingress_rule" "simulator_from_web" {
  security_group_id            = aws_security_group.devtools.id
  description                  = "From the app"
  referenced_security_group_id = var.web_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 8180
  to_port                      = 8180
}

resource "aws_vpc_security_group_ingress_rule" "simulator_from_worker" {
  security_group_id            = aws_security_group.devtools.id
  description                  = "From the worker"
  referenced_security_group_id = var.worker_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 8180
  to_port                      = 8180
}

resource "aws_vpc_security_group_ingress_rule" "simulator_from_fake_etl" {
  security_group_id            = aws_security_group.devtools.id
  description                  = "From the fake ETL"
  referenced_security_group_id = aws_security_group.devtools.id
  ip_protocol                  = "tcp"
  from_port                    = 8180
  to_port                      = 8180
}

# Out: the load balancer (the fake ETL's calls), ECR, Secrets Manager and CloudWatch Logs.
resource "aws_vpc_security_group_egress_rule" "devtools_out" {
  security_group_id = aws_security_group.devtools.id
  description       = "The load balancer and AWS services"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

resource "aws_vpc_security_group_ingress_rule" "alb_from_fake_etl" {
  security_group_id            = var.alb_security_group_id
  description                  = "The fake ETL, inside the VPC"
  referenced_security_group_id = aws_security_group.devtools.id
  ip_protocol                  = "tcp"
  from_port                    = var.alb_port
  to_port                      = var.alb_port
}

resource "aws_cloudwatch_log_group" "devtools" {
  name              = "/serena/${var.env_name}/devtools"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn # once its policy lets CloudWatch Logs use it (modules/core)
}

# No task role: the simulator calls no AWS service. The execution role pulls its image and writes its logs. Half a
# vCPU and 2 GB leave room for ./serena aws replay's files of about a real file's size (D283): the largest, 100 MB,
# is made once after a start and served to several fetches at once.
resource "aws_ecs_task_definition" "fakecspace" {
  family                   = "${local.name}-fakecspace"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 2048
  execution_role_arn       = var.execution_role_arn

  runtime_platform {
    cpu_architecture        = "ARM64"
    operating_system_family = "LINUX"
  }

  container_definitions = jsonencode([{
    name         = "fakecspace"
    image        = var.devtools_image_uri
    essential    = true
    command      = ["uvicorn", "fakecspace.app:app", "--host", "0.0.0.0", "--port", "8180"]
    portMappings = [{ containerPort = 8180, hostPort = 8180, protocol = "tcp" }]
    # ECS fills these in when it registers a task definition; written out here so Terraform's plan doesn't see a
    # difference and replace the task definition at every deploy.
    environment    = []
    mountPoints    = []
    volumesFrom    = []
    systemControls = []
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.devtools.name
        awslogs-region        = var.region
        awslogs-stream-prefix = "fakecspace"
      }
    }
  }])
}

resource "aws_ecs_service" "fakecspace" {
  name            = "fakecspace"
  cluster         = var.cluster_id
  launch_type     = "FARGATE"
  task_definition = aws_ecs_task_definition.fakecspace.arn
  desired_count   = var.running ? 1 : 0
  propagate_tags  = "SERVICE"

  # One copy at a time: its data is in memory, so two would disagree.
  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100
  availability_zone_rebalancing      = "DISABLED"
  wait_for_steady_state              = true

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    assign_public_ip = var.assign_public_ip
    subnets          = var.subnet_ids
    security_groups  = [aws_security_group.devtools.id]
  }

  service_registries {
    registry_arn = aws_service_discovery_service.fakecspace.arn
  }
}

# The fake ETL: run once per refresh by ./serena aws etl, which adds its arguments (--museum and the addresses).
resource "aws_ecs_task_definition" "fake_etl" {
  family                   = "${local.name}-fake-etl"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = aws_iam_role.fake_etl.arn

  runtime_platform {
    cpu_architecture        = "ARM64"
    operating_system_family = "LINUX"
  }

  container_definitions = jsonencode([{
    name      = "fake-etl"
    image     = var.devtools_image_uri
    essential = true
    command   = ["python", "-m", "devtools.fake_etl", "--help"]
    # Serena's settings (for the museums and their token secrets), and the mark that lets the fake ETL run here.
    environment = [for name, value in merge(var.app_environment, { SERENA_SIMULATED_CSPACE = "true" }) :
    { name = name, value = value }]
    # ECS fills these in when it registers a task definition; written out here so Terraform's plan doesn't see a
    # difference and replace the task definition at every deploy.
    portMappings   = []
    mountPoints    = []
    volumesFrom    = []
    systemControls = []
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.devtools.name
        awslogs-region        = var.region
        awslogs-stream-prefix = "fake-etl"
      }
    }
  }])
}
# The fake ETL reads the museums' ETL tokens, as the real ETL reads its own from its secret store.
data "aws_iam_policy_document" "fake_etl" {

  statement {
    sid       = "EtlTokens"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = var.etl_token_secret_arns
  }

  statement {
    sid       = "Key"
    actions   = ["kms:Decrypt"]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_role" "fake_etl" {
  name               = "${local.name}-fake-etl"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy" "fake_etl" {
  name   = "serena-fake-etl"
  role   = aws_iam_role.fake_etl.id
  policy = data.aws_iam_policy_document.fake_etl.json
}
