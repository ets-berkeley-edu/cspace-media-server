# Image delivery (D194 to D200; design: Signed URLs, Unavailable images). The app answers a servable request with a
# 302 to a CloudFront signed URL, <address>/<museum>/objects/<sha256>; CloudFront checks the signature against the
# key group, removes /<museum> (the allowlist function) and reads objects/<sha256> from the museum's bucket through
# origin access control. The unavailable images and the generic placeholder are served without a signature from a
# small static bucket.
#
# The signing key (D200): ./serena aws makes the key pair; the private key goes straight into its secret (secrets.tf)
# and the public keys, the current one and the one before it, into the SSM parameter /serena-<env>/cloudfront-public-keys
# (a JSON list of {"name", "public_key"}), which Terraform reads here. Until the first key exists (cdn_keys = false),
# nothing is delivered: the app has no signer and answers with the unavailable image ("delivery not set up").

data "aws_ssm_parameter" "cdn_keys" {
  count = var.cdn_keys ? 1 : 0
  name  = "/${local.name}/cloudfront-public-keys"
}

locals {
  # name => public key PEM. A String parameter, so its insecure_value isn't marked sensitive.
  cdn_public_keys = var.cdn_keys ? { for k in jsondecode(data.aws_ssm_parameter.cdn_keys[0].insecure_value) : k.name => k.public_key } : {}
  delivery        = length(local.cdn_public_keys) > 0
  static_bucket   = "${local.name}-static-${local.account_id}-${var.region}"

  # The static bucket's files: each museum's unavailable image and the default one (the same file today, D199), and
  # the generic placeholder picture (D168).
  static_files = merge(
    { for m in concat(local.museums, ["default"]) : "${m}/unavailable.svg" => "unavailable.svg" },
    { "default/placeholder.svg" = "placeholder.svg" },
  )
}

# Keyed by name, so a rotation adds one key and removes the oldest, and a key's ID never changes while it's trusted.
resource "aws_cloudfront_public_key" "cdn" {
  for_each    = local.cdn_public_keys
  name        = each.key
  comment     = "Serena ${var.env_name}: signs the URLs of the museums' files (./serena aws cdn-key)"
  encoded_key = each.value
}

resource "aws_cloudfront_key_group" "cdn" {
  count   = local.delivery ? 1 : 0
  name    = "${local.name}-files"
  comment = "Serena ${var.env_name}: the current signing key and the one before it"
  items   = [for k in aws_cloudfront_public_key.cdn : k.id]
}

resource "aws_cloudfront_origin_access_control" "s3" {
  name                              = "${local.name}-s3"
  description                       = "Serena ${var.env_name}: CloudFront reads the museums' files and the static files"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# A delivered file (D198): the browser keeps it no longer than about a URL's life, whatever the object carries.
resource "aws_cloudfront_response_headers_policy" "files" {
  name    = "${local.name}-files"
  comment = "Serena: the museums' files"

  custom_headers_config {
    items {
      header   = "Cache-Control"
      value    = "private, max-age=900"
      override = true
    }
  }

  security_headers_config {
    content_type_options {
      override = true
    }

    strict_transport_security {
      access_control_max_age_sec = 31536000
      override                   = true
    }
  }
}

# The unavailable images and the placeholder (D199): SVGs that may draw, but never run a script or load anything.
resource "aws_cloudfront_response_headers_policy" "static" {
  name    = "${local.name}-static"
  comment = "Serena: the unavailable images and the generic placeholder"

  custom_headers_config {
    items {
      header   = "Cache-Control"
      value    = "public, max-age=300"
      override = true
    }
  }

  security_headers_config {
    content_security_policy {
      content_security_policy = "default-src 'none'; style-src 'unsafe-inline'"
      override                = true
    }

    content_type_options {
      override = true
    }

    strict_transport_security {
      access_control_max_age_sec = 31536000
      override                   = true
    }
  }
}

# ---- the static bucket (D199) --------------------------------------------------------------------------------------
# Public files from the repository, so S3's own encryption, and Terraform may always empty it.
resource "aws_s3_bucket" "static" {
  bucket        = local.static_bucket
  force_destroy = true
}

resource "aws_s3_bucket_ownership_controls" "static" {
  bucket = aws_s3_bucket.static.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "static" {
  bucket                  = aws_s3_bucket.static.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "static" {
  bucket = aws_s3_bucket.static.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

data "aws_iam_policy_document" "static_bucket" {
  statement {
    sid       = "TlsOnly"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.static.arn, "${aws_s3_bucket.static.arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  statement {
    sid       = "CloudFrontReads"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.static.arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.main.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "static" {
  bucket     = aws_s3_bucket.static.id
  policy     = data.aws_iam_policy_document.static_bucket.json
  depends_on = [aws_s3_bucket_public_access_block.static]
}

resource "aws_s3_object" "static" {
  for_each     = local.static_files
  bucket       = aws_s3_bucket.static.id
  key          = each.key
  source       = "${path.module}/../../../backend/serena/static/${each.value}"
  etag         = filemd5("${path.module}/../../../backend/serena/static/${each.value}")
  content_type = "image/svg+xml"
}
