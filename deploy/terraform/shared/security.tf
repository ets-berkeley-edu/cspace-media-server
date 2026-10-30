# The load balancer takes HTTPS only (TQ5), and only from the Apache hosts, the ETL servers and the campus and VPN
# ranges (D291); which paths each may reach is in alb.tf. The tasks take traffic only from the load balancer.

locals {
  lb_sources = toset(distinct(concat(var.apache_cidrs, var.etl_cidrs, var.admin_cidrs)))
}

resource "aws_security_group" "alb" {
  name        = "${local.name}-alb"
  description = "Serena load balancer. HTTPS from the Apache hosts, the ETL servers, campus and VPN only."
  vpc_id      = var.vpc_id

  tags = { Name = "${local.name}-alb" }
}

resource "aws_vpc_security_group_ingress_rule" "alb_https" {
  for_each          = local.lb_sources
  security_group_id = aws_security_group.alb.id
  description       = "HTTPS"
  cidr_ipv4         = each.value
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_vpc_security_group_egress_rule" "alb_to_web" {
  security_group_id            = aws_security_group.alb.id
  description                  = "To the app"
  referenced_security_group_id = aws_security_group.web.id
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
}

resource "aws_security_group" "web" {
  name        = "${local.name}-web"
  description = "Serena app tasks. Only the load balancer can connect."
  vpc_id      = var.vpc_id

  tags = { Name = "${local.name}-web" }
}

resource "aws_vpc_security_group_ingress_rule" "web_from_alb" {
  security_group_id            = aws_security_group.web.id
  description                  = "From the load balancer"
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
}

resource "aws_vpc_security_group_egress_rule" "web_out" {
  security_group_id = aws_security_group.web.id
  description       = "CollectionSpace and AWS services, through the VPC's NAT gateway and endpoints"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

resource "aws_security_group" "worker" {
  name        = "${local.name}-worker"
  description = "Serena worker tasks. Nothing can connect to them (no inbound rules)."
  vpc_id      = var.vpc_id

  tags = { Name = "${local.name}-worker" }
}

resource "aws_vpc_security_group_egress_rule" "worker_out" {
  security_group_id = aws_security_group.worker.id
  description       = "AWS services"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}
