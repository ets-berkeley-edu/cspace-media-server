# CloudFront reaches the load balancer through its VPC origin, but the connections keep CloudFront's own source
# addresses, so a rule for the VPC's range doesn't match them. AWS publishes those addresses as a managed prefix list.
data "aws_ec2_managed_prefix_list" "cloudfront_origin_facing" {
  name = "com.amazonaws.global.cloudfront.origin-facing"
}

resource "aws_security_group" "alb" {
  name        = "${local.name}-alb"
  description = "Serena load balancer. Only CloudFront (and the fake ETL, with the simulator) connects."
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name}-alb" }
}

# The prefix list counts as about 55 rules toward the security group's limit of 60, so this group has room for
# little else.
resource "aws_vpc_security_group_ingress_rule" "alb_from_cloudfront" {
  security_group_id = aws_security_group.alb.id
  description       = "CloudFront (origin-facing addresses)"
  prefix_list_id    = data.aws_ec2_managed_prefix_list.cloudfront_origin_facing.id
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
}

# The only way out of the load balancer: the app's port.
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
  vpc_id      = aws_vpc.main.id

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
  description       = "CollectionSpace and AWS services"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

resource "aws_security_group" "worker" {
  name        = "${local.name}-worker"
  description = "Serena worker tasks. Nothing can connect to them (no inbound rules)."
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name}-worker" }
}

resource "aws_vpc_security_group_egress_rule" "worker_out" {
  security_group_id = aws_security_group.worker.id
  description       = "AWS services"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}
