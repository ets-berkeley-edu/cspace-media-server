# The simulated CollectionSpace and the fake ETL (D189), for an environment that tries Serena without a real
# CollectionSpace or ETL (SIMULATED_CSPACE=true in its settings; off by default). Nothing here exists when
# simulated_cspace is false. Both run from the local stack's image (backend/Dockerfile), never from Serena's.
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
  simulated     = var.simulated_cspace ? 1 : 0
  simulator_url = "http://fakecspace.${local.name}.internal:8180"
}

resource "aws_service_discovery_private_dns_namespace" "main" {
  count       = local.simulated
  name        = "${local.name}.internal"
  description = "Names inside Serena's VPC: the simulated CollectionSpace"
  vpc         = aws_vpc.main.id
}

resource "aws_service_discovery_service" "fakecspace" {
  count = local.simulated
  name  = "fakecspace"

  dns_config {
    namespace_id   = aws_service_discovery_private_dns_namespace.main[0].id
    routing_policy = "MULTIVALUE"

    dns_records {
      type = "A"
      ttl  = 10
    }
  }
}

# One group for the simulator and the fake ETL: the fake ETL calls the simulator, and the load balancer.
resource "aws_security_group" "devtools" {
  count       = local.simulated
  name        = "${local.name}-devtools"
  description = "Simulated CollectionSpace and fake ETL. Only Serena and the fake ETL reach the simulator."
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name}-devtools" }
}

resource "aws_vpc_security_group_ingress_rule" "simulator_from_web" {
  count                        = local.simulated
  security_group_id            = aws_security_group.devtools[0].id
  description                  = "From the app"
  referenced_security_group_id = aws_security_group.web.id
  ip_protocol                  = "tcp"
  from_port                    = 8180
  to_port                      = 8180
}

resource "aws_vpc_security_group_ingress_rule" "simulator_from_worker" {
  count                        = local.simulated
  security_group_id            = aws_security_group.devtools[0].id
  description                  = "From the worker"
  referenced_security_group_id = aws_security_group.worker.id
  ip_protocol                  = "tcp"
  from_port                    = 8180
  to_port                      = 8180
}

resource "aws_vpc_security_group_ingress_rule" "simulator_from_fake_etl" {
  count                        = local.simulated
  security_group_id            = aws_security_group.devtools[0].id
  description                  = "From the fake ETL"
  referenced_security_group_id = aws_security_group.devtools[0].id
  ip_protocol                  = "tcp"
  from_port                    = 8180
  to_port                      = 8180
}

# Out: the load balancer (the fake ETL's calls), ECR, Secrets Manager and CloudWatch Logs.
resource "aws_vpc_security_group_egress_rule" "devtools_out" {
  count             = local.simulated
  security_group_id = aws_security_group.devtools[0].id
  description       = "The load balancer and AWS services"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

resource "aws_vpc_security_group_ingress_rule" "alb_from_fake_etl" {
  count                        = local.simulated
  security_group_id            = aws_security_group.alb.id
  description                  = "The fake ETL, inside the VPC"
  referenced_security_group_id = aws_security_group.devtools[0].id
  ip_protocol                  = "tcp"
  from_port                    = 80
  to_port                      = 80
}

resource "aws_cloudwatch_log_group" "devtools" {
  count             = local.simulated
  name              = "/serena/${var.env_name}/devtools"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.main.arn
}

# No task role: the simulator calls no AWS service. The execution role pulls its image and writes its logs.
resource "aws_ecs_task_definition" "fakecspace" {
  count                    = local.simulated
  family                   = "${local.name}-fakecspace"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution.arn

  runtime_platform {
    cpu_architecture        = "ARM64"
    operating_system_family = "LINUX"
  }

  container_definitions = jsonencode([{
    name         = "fakecspace"
    image        = var.devtools_image_uri
    essential    = true
    command      = ["uvicorn", "fakecspace.app:app", "--host", "0.0.0.0", "--port", "8180"]
    portMappings = [{ containerPort = 8180, protocol = "tcp" }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.devtools[0].name
        awslogs-region        = var.region
        awslogs-stream-prefix = "fakecspace"
      }
    }
  }])
}

resource "aws_ecs_service" "fakecspace" {
  count           = local.simulated
  name            = "fakecspace"
  cluster         = aws_ecs_cluster.main.id
  launch_type     = "FARGATE"
  task_definition = aws_ecs_task_definition.fakecspace[0].arn
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
    assign_public_ip = true
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.devtools[0].id]
  }

  service_registries {
    registry_arn = aws_service_discovery_service.fakecspace[0].arn
  }

  depends_on = [aws_route_table_association.public]
}

# The fake ETL: run once per refresh by ./serena aws etl, which adds its arguments (--museum and the addresses).
resource "aws_ecs_task_definition" "fake_etl" {
  count                    = local.simulated
  family                   = "${local.name}-fake-etl"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.fake_etl[0].arn

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
    environment = [for name, value in merge(local.app_environment, { SERENA_SIMULATED_CSPACE = "true" }) :
    { name = name, value = value }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.devtools[0].name
        awslogs-region        = var.region
        awslogs-stream-prefix = "fake-etl"
      }
    }
  }])
}
