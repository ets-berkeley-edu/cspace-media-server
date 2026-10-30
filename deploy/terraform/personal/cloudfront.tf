# CloudFront in front of the internal load balancer (D183): the files distribution (../modules/files) takes the app
# through this VPC origin, and runs this function, the path and address rules (D185), on every request. WAF is the
# waf module (main.tf, D186). A domain later is an alternate name and an ACM certificate on the distribution.

resource "aws_cloudfront_vpc_origin" "alb" {
  vpc_origin_endpoint_config {
    name                   = local.name
    arn                    = aws_lb.main.arn
    http_port              = 80
    https_port             = 443
    origin_protocol_policy = "http-only"

    origin_ssl_protocols {
      items    = ["TLSv1.2"]
      quantity = 1
    }
  }

  # A VPC origin needs the VPC's internet gateway attached.
  depends_on = [aws_internet_gateway.main]
}

resource "aws_cloudfront_function" "allowlist" {
  name    = "${local.name}-allowlist"
  comment = "Who may reach which of Serena's paths"
  runtime = "cloudfront-js-2.0"
  publish = true
  code = templatefile("${path.module}/allowlist.js.tftpl", {
    allowed = join(",", var.allowed_cidrs)
    etl     = join(",", var.etl_cidrs)
    admin   = join(",", var.admin_cidrs)
    open    = var.open_images ? "true" : "false"
    museums = join("|", local.museums)
  })
}
