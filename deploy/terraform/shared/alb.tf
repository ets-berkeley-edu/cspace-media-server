# The app's front door (D289 to D292, D295): an internet-facing load balancer on the campus domain, HTTPS only.
# Everyone the security group admits reaches the image paths and /health (TQ6); listener rules let /etl/ through only
# from ETL_CIDRS and /admin only from ADMIN_CIDRS, and answer those paths from anywhere else with a fixed 403 (D291).
# A rule takes at most 5 condition values, so each address list is cut into rules of a few addresses each.

resource "aws_lb" "main" {
  name               = local.name
  internal           = false
  load_balancer_type = "application"
  subnets            = var.lb_subnet_ids
  security_groups    = [aws_security_group.alb.id]
  # Nothing in front of the app limits a first fetch's wait (D295): Apache's proxy timeout for Serena's paths is at
  # least as long.
  idle_timeout               = 300
  drop_invalid_header_fields = true
}

resource "aws_lb_target_group" "web" {
  name                 = "${local.name}-web"
  vpc_id               = var.vpc_id
  target_type          = "ip"
  protocol             = "HTTP"
  port                 = 8000
  deregistration_delay = 30

  health_check {
    path                = "/health"
    interval            = 15
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.main.arn
  protocol          = "HTTPS"
  port              = 443
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }
}

locals {
  # path values + address values <= 5 per rule.
  restricted_paths = {
    etl   = { paths = ["/etl/*"], deny = ["/etl", "/etl/*"], cidrs = chunklist(var.etl_cidrs, 4), base = 100 }
    admin = { paths = ["/admin", "/admin/*"], deny = ["/admin", "/admin/*"], cidrs = chunklist(var.admin_cidrs, 3), base = 200 }
  }

  allow_rules = merge([for k, r in local.restricted_paths : {
    for i, chunk in r.cidrs : "${k}-${i}" => { paths = r.paths, cidrs = chunk, priority = r.base + i }
  }]...)
}

resource "aws_lb_listener_rule" "allow" {
  for_each     = local.allow_rules
  listener_arn = aws_lb_listener.https.arn
  priority     = each.value.priority

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }

  condition {
    path_pattern {
      values = each.value.paths
    }
  }

  condition {
    source_ip {
      values = each.value.cidrs
    }
  }
}

resource "aws_lb_listener_rule" "deny" {
  for_each     = local.restricted_paths
  listener_arn = aws_lb_listener.https.arn
  priority     = each.value.base + 99

  action {
    type = "fixed-response"

    fixed_response {
      content_type = "text/plain"
      message_body = "Not from this address.\n"
      status_code  = "403"
    }
  }

  condition {
    path_pattern {
      values = each.value.deny
    }
  }
}
