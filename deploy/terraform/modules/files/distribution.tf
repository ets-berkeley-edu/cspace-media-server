# The distribution, at its own *.cloudfront.net address. With an app origin (the personal root) it is the app's front
# door too, as D183 describes: everything else goes to the app, uncached, and the admin app's built files are cached.
# Without one (the shared root), the default behavior reads the static bucket, which answers anything that isn't one
# of its files with 403.

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

  app = var.app_origin != null
}

resource "aws_cloudfront_distribution" "main" {
  comment         = "Serena ${var.env_name}"
  enabled         = true
  http_version    = "http2and3"
  is_ipv6_enabled = false
  price_class     = "PriceClass_100"
  web_acl_id      = var.web_acl_arn

  dynamic "origin" {
    for_each = local.app ? [var.app_origin] : []

    content {
      origin_id   = "app"
      domain_name = origin.value.domain_name

      vpc_origin_config {
        vpc_origin_id            = origin.value.vpc_origin_id
        origin_read_timeout      = origin.value.origin_read_timeout
        origin_keepalive_timeout = 5
      }
    }
  }

  # Each museum's bucket (D195, D196): only its objects/ are reachable, with a signed URL.
  dynamic "origin" {
    for_each = toset(local.museums)

    content {
      origin_id                = "museum-${origin.value}"
      domain_name              = var.bucket_domains[origin.value]
      origin_access_control_id = aws_cloudfront_origin_access_control.s3.id
    }
  }

  origin {
    origin_id                = "static"
    domain_name              = aws_s3_bucket.static.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.s3.id
  }

  # With the app: everything goes to it, uncached, since its answers (redirects to signed URLs, the admin API) are per
  # request. Without it: the static bucket.
  default_cache_behavior {
    target_origin_id           = local.app ? "app" : "static"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = local.app ? ["GET", "HEAD", "OPTIONS", "PUT", "PATCH", "POST", "DELETE"] : ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = local.app ? local.cloudfront_policy.caching_disabled : local.cloudfront_policy.caching_optimized
    origin_request_policy_id   = local.app ? local.cloudfront_policy.all_viewer_except_host_header : null
    response_headers_policy_id = local.app ? local.cloudfront_policy.security_headers : aws_cloudfront_response_headers_policy.static.id

    function_association {
      event_type   = "viewer-request"
      function_arn = var.viewer_request_function_arn
    }
  }

  # The built admin app's files have content hashes in their names.
  dynamic "ordered_cache_behavior" {
    for_each = local.app ? ["/admin/assets/*"] : []

    content {
      path_pattern               = ordered_cache_behavior.value
      target_origin_id           = "app"
      viewer_protocol_policy     = "redirect-to-https"
      allowed_methods            = ["GET", "HEAD"]
      cached_methods             = ["GET", "HEAD"]
      compress                   = true
      cache_policy_id            = local.cloudfront_policy.caching_optimized
      response_headers_policy_id = local.cloudfront_policy.security_headers

      function_association {
        event_type   = "viewer-request"
        function_arn = var.viewer_request_function_arn
      }
    }
  }

  # A museum's files (D195 to D198), once there is a signing key: a valid signed URL only, cached at the edge (the
  # signature isn't in the cache key; CloudFront checks it first), /<museum> removed by the function.
  dynamic "ordered_cache_behavior" {
    for_each = local.delivery ? local.museums : []

    content {
      path_pattern               = "/${ordered_cache_behavior.value}/objects/*"
      target_origin_id           = "museum-${ordered_cache_behavior.value}"
      viewer_protocol_policy     = "redirect-to-https"
      allowed_methods            = ["GET", "HEAD"]
      cached_methods             = ["GET", "HEAD"]
      compress                   = false
      cache_policy_id            = local.cloudfront_policy.caching_optimized
      response_headers_policy_id = aws_cloudfront_response_headers_policy.files.id
      trusted_key_groups         = [aws_cloudfront_key_group.cdn[0].id]

      function_association {
        event_type   = "viewer-request"
        function_arn = var.viewer_request_function_arn
      }
    }
  }

  # The unavailable images and the generic placeholder (D199), without a signature.
  dynamic "ordered_cache_behavior" {
    for_each = ["*/unavailable.svg", "/default/placeholder.svg"]

    content {
      path_pattern               = ordered_cache_behavior.value
      target_origin_id           = "static"
      viewer_protocol_policy     = "redirect-to-https"
      allowed_methods            = ["GET", "HEAD"]
      cached_methods             = ["GET", "HEAD"]
      compress                   = true
      cache_policy_id            = local.cloudfront_policy.caching_optimized
      response_headers_policy_id = aws_cloudfront_response_headers_policy.static.id

      function_association {
        event_type   = "viewer-request"
        function_arn = var.viewer_request_function_arn
      }
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
