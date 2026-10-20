# CloudFront: HTTPS at a *.cloudfront.net address (D183), in front of the internal load balancer, with the path and
# address rules (D185) and, where it's on, WAF (D186). A domain later is an alternate name and an ACM certificate on
# this distribution. Image delivery from the museums' buckets is added to it in pull request 18 (D194).

locals {
  # AWS-managed CloudFront policies (the same IDs in every account).
  cloudfront_policy = {
    caching_disabled              = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
    caching_optimized             = "658327ea-f89d-4fab-a63d-7e88639e58f6"
    all_viewer_except_host_header = "b689b0a8-53d0-40ab-baf2-68738e2966ac"
    security_headers              = "67f7725c-6f97-4210-82d7-5512b31e9d03"
  }

  # Never keep an error answer: one viewer's 403 or 404 must not be served to another.
  uncached_error_codes = [400, 403, 404, 405, 500, 502, 503, 504]
}

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
  })
}

resource "aws_cloudfront_distribution" "main" {
  comment         = "Serena ${var.env_name}"
  enabled         = true
  http_version    = "http2and3"
  is_ipv6_enabled = false
  price_class     = "PriceClass_100"
  web_acl_id      = var.waf ? aws_wafv2_web_acl.main[0].arn : null

  origin {
    origin_id   = "app"
    domain_name = aws_lb.main.dns_name

    vpc_origin_config {
      vpc_origin_id            = aws_cloudfront_vpc_origin.alb.id
      origin_read_timeout      = var.origin_read_timeout
      origin_keepalive_timeout = 5
    }
  }

  # Everything goes to the app, uncached: its answers (redirects to signed URLs, the admin API) are per request.
  default_cache_behavior {
    target_origin_id           = "app"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD", "OPTIONS", "PUT", "PATCH", "POST", "DELETE"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = local.cloudfront_policy.caching_disabled
    origin_request_policy_id   = local.cloudfront_policy.all_viewer_except_host_header
    response_headers_policy_id = local.cloudfront_policy.security_headers

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.allowlist.arn
    }
  }

  # The built admin app's files have content hashes in their names.
  ordered_cache_behavior {
    path_pattern               = "/admin/assets/*"
    target_origin_id           = "app"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = local.cloudfront_policy.caching_optimized
    response_headers_policy_id = local.cloudfront_policy.security_headers

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.allowlist.arn
    }
  }

  dynamic "custom_error_response" {
    for_each = local.uncached_error_codes

    content {
      error_code            = custom_error_response.value
      error_caching_min_ttl = 0
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}
