# Serena's customer-managed KMS key (design: Storage, Least privilege; D192): it encrypts the tables, the museums'
# buckets, the secrets, the logs and the alert topic. The account's IAM policies decide who may use it (iam.tf).
# Besides: CloudWatch Logs may use it for Serena's own log groups only; CloudFront may decrypt for this environment's
# distribution only, to deliver the museums' files (D196); CloudWatch alarms may use it to publish to the alert topic
# (D201); a museum's ETL server may decrypt its own token, through Secrets Manager only (D275, DP15). Yearly rotation.
# The policy is its own resource, so the key needn't wait for the distribution.

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

  # Origin access control reads the museums' files, which are encrypted with this key (D196).
  statement {
    sid       = "CloudFrontDecryptsForThisDistribution"
    actions   = ["kms:Decrypt"]
    resources = ["*"]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [var.distribution_arn]
    }
  }

  # An alarm publishes to the encrypted alert topic (alerts.tf, D201).
  statement {
    sid       = "CloudWatchAlarmsPublishToTheAlertTopic"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey*"]
    resources = ["*"]

    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com"]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:${local.partition}:cloudwatch:${var.region}:${local.account_id}:alarm:${local.name}-*"]
    }
  }

  # A museum's ETL server's role decrypts its token, only as Secrets Manager reads it and only for that museum's secret
  # (secrets.tf; D275, DP15). One statement a museum, so no role can decrypt another museum's token.
  dynamic "statement" {
    for_each = var.etl_reader_role_arns
    content {
      sid       = "EtlServerDecryptsItsToken${title(statement.key)}"
      actions   = ["kms:Decrypt"]
      resources = ["*"]

      principals {
        type        = "AWS"
        identifiers = [statement.value]
      }

      condition {
        test     = "StringEquals"
        variable = "kms:ViaService"
        values   = ["secretsmanager.${var.region}.amazonaws.com"]
      }

      condition {
        test     = "StringEquals"
        variable = "kms:EncryptionContext:SecretARN"
        values   = [aws_secretsmanager_secret.etl_tokens[statement.key].arn]
      }
    }
  }
}

resource "aws_kms_key" "main" {
  description             = "Serena ${var.env_name}: tables, buckets, secrets and logs"
  enable_key_rotation     = true
  deletion_window_in_days = var.protect_data ? 30 : 7
}

resource "aws_kms_key_policy" "main" {
  key_id = aws_kms_key.main.id
  policy = data.aws_iam_policy_document.key.json
}

resource "aws_kms_alias" "main" {
  name          = "alias/${local.name}"
  target_key_id = aws_kms_key.main.key_id
}
