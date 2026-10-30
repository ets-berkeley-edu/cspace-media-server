# The VPC Operations provides (D303): Serena creates no VPC, subnet, route or gateway, only, when asked, the free
# gateway endpoints for S3 and DynamoDB on the app subnets' route tables. The subnets must be in that VPC.

data "aws_vpc" "main" {
  id = var.vpc_id
}

data "aws_subnet" "app" {
  for_each = toset(var.app_subnet_ids)
  id       = each.value

  lifecycle {
    postcondition {
      condition     = self.vpc_id == var.vpc_id
      error_message = "app subnet ${each.value} isn't in ${var.vpc_id}."
    }
  }
}

data "aws_subnet" "lb" {
  for_each = toset(var.lb_subnet_ids)
  id       = each.value

  lifecycle {
    postcondition {
      condition     = self.vpc_id == var.vpc_id
      error_message = "load balancer subnet ${each.value} isn't in ${var.vpc_id}."
    }
  }
}

data "aws_route_table" "app" {
  for_each  = var.create_gateway_endpoints ? toset(var.app_subnet_ids) : toset([])
  subnet_id = each.value
}

locals {
  app_route_tables = distinct([for t in data.aws_route_table.app : t.id])
}

resource "aws_vpc_endpoint" "s3" {
  count             = var.create_gateway_endpoints ? 1 : 0
  vpc_id            = var.vpc_id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = local.app_route_tables

  tags = { Name = "${local.name}-s3" }
}

resource "aws_vpc_endpoint" "dynamodb" {
  count             = var.create_gateway_endpoints ? 1 : 0
  vpc_id            = var.vpc_id
  service_name      = "com.amazonaws.${var.region}.dynamodb"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = local.app_route_tables

  tags = { Name = "${local.name}-dynamodb" }
}
