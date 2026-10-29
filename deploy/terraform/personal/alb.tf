resource "aws_lb" "main" {
  name               = local.name
  internal           = true
  load_balancer_type = "application"
  subnets            = aws_subnet.private[*].id
  security_groups    = [aws_security_group.alb.id]

  # A miss answers only once the file is stored (design: Image fetch). CloudFront stops waiting sooner
  # (origin_read_timeout, D184); a fetch it gave up on still finishes, so the next request is a hit.
  idle_timeout               = 300
  drop_invalid_header_fields = true
}

resource "aws_lb_target_group" "web" {
  name                 = "${local.name}-web"
  vpc_id               = aws_vpc.main.id
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

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  protocol          = "HTTP"
  port              = 80

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }
}
