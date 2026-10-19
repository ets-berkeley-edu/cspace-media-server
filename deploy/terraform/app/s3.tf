# One bucket per museum (design: Storage; D192): every file Serena has fetched (objects/<sha256>) and every servable
# list it received (servable-list/...). Private, encrypted with Serena's key, versioned, HTTPS only, and no rule that
# deletes anything; S3 Intelligent-Tiering for cost. Where data isn't protected (personal-dev), ./serena aws destroy
# empties and deletes them.

locals {
  buckets = { for m in local.museums : m => "${local.name}-${m}-${local.account_id}-${var.region}" }
}

resource "aws_s3_bucket" "museum" {
  for_each      = local.buckets
  bucket        = each.value
  force_destroy = !var.protect_data
}

resource "aws_s3_bucket_ownership_controls" "museum" {
  for_each = local.buckets
  bucket   = aws_s3_bucket.museum[each.key].id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "museum" {
  for_each = local.buckets
  bucket   = aws_s3_bucket.museum[each.key].id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "museum" {
  for_each = local.buckets
  bucket   = aws_s3_bucket.museum[each.key].id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "museum" {
  for_each = local.buckets
  bucket   = aws_s3_bucket.museum[each.key].id

  rule {
    bucket_key_enabled = true # one KMS request per object's data key, not per request

    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.main.arn
    }
  }
}

# Moves objects to Intelligent-Tiering; never expires or deletes anything.
resource "aws_s3_bucket_lifecycle_configuration" "museum" {
  for_each = local.buckets
  bucket   = aws_s3_bucket.museum[each.key].id

  rule {
    id     = "intelligent-tiering"
    status = "Enabled"

    filter {}

    transition {
      days          = 0
      storage_class = "INTELLIGENT_TIERING"
    }
  }

  depends_on = [aws_s3_bucket_versioning.museum]
}

data "aws_iam_policy_document" "museum_bucket" {
  for_each = local.buckets

  statement {
    sid       = "TlsOnly"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.museum[each.key].arn, "${aws_s3_bucket.museum[each.key].arn}/*"]

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
}

resource "aws_s3_bucket_policy" "museum" {
  for_each = local.buckets
  bucket   = aws_s3_bucket.museum[each.key].id
  policy   = data.aws_iam_policy_document.museum_bucket[each.key].json

  depends_on = [aws_s3_bucket_public_access_block.museum]
}
