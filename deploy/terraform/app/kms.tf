# Serena's customer-managed KMS key (design: Storage, Least privilege; D192): it encrypts the tables, the museums'
# buckets, the secrets and the logs. The account's IAM policies decide who may use it (iam.tf), and CloudWatch Logs
# may use it for Serena's own log groups only. Yearly rotation.

data "aws_iam_policy_document" "key" {
  statement {
    sid       = "AccountPoliciesControlUse"
    actions   = ["kms:*"]
    resources = ["*"]

    principals {
      type        = "AWS"
      identifiers = ["arn:${local.partition}:iam::${local.account_id}:root"]
    }
  }

  statement {
    sid       = "CloudWatchLogsForSerenasLogGroups"
    actions   = ["kms:Encrypt*", "kms:Decrypt*", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:Describe*"]
    resources = ["*"]

    principals {
      type        = "Service"
      identifiers = ["logs.${var.region}.amazonaws.com"]
    }

    condition {
      test     = "ArnLike"
      variable = "kms:EncryptionContext:aws:logs:arn"
      values   = ["arn:${local.partition}:logs:${var.region}:${local.account_id}:log-group:/serena/${var.env_name}/*"]
    }
  }
}

resource "aws_kms_key" "main" {
  description             = "Serena ${var.env_name}: tables, buckets, secrets and logs"
  enable_key_rotation     = true
  deletion_window_in_days = var.protect_data ? 30 : 7
  policy                  = data.aws_iam_policy_document.key.json
}

resource "aws_kms_alias" "main" {
  name          = "alias/${local.name}"
  target_key_id = aws_kms_key.main.key_id
}
