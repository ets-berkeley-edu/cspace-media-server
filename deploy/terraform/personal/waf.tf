# WAF on the distribution (D186), switched by the waf variable: off in personal-dev, on in QA and production. A web ACL
# for CloudFront lives in us-east-1. Bot Control counts at first, so we see how crawlers are treated before anything is
# blocked (the catalog is crawled routinely). Logs redact the URI path and the query string (D16, D26).

resource "aws_wafv2_web_acl" "main" {
  count    = var.waf ? 1 : 0
  provider = aws.us_east_1
  name     = local.name
  scope    = "CLOUDFRONT"

  default_action {
    allow {}
  }

  rule {
    name     = "rate-limit-per-address"
    priority = 0

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit              = var.waf_rate_limit
        aggregate_key_type = "IP"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name}-rate"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "ip-reputation"
    priority = 1

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesAmazonIpReputationList"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name}-ip-reputation"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "core"
    priority = 2

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesCommonRuleSet"

        # Servable lists and other uploads are bigger than the rule set's 8 KB body limit.
        rule_action_override {
          name = "SizeRestrictions_BODY"

          action_to_use {
            count {}
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name}-core"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "known-bad-inputs"
    priority = 3

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name}-bad-inputs"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "bot-control"
    priority = 4

    override_action {
      count {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesBotControlRuleSet"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name}-bots"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = local.name
    sampled_requests_enabled   = true
  }
}

# WAF's log group's name must start with aws-waf-logs-.
resource "aws_cloudwatch_log_group" "waf" {
  count             = var.waf ? 1 : 0
  provider          = aws.us_east_1
  name              = "aws-waf-logs-${local.name}"
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "waf_logs" {
  count = var.waf ? 1 : 0

  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.waf[0].arn}:*"]

    principals {
      type        = "Service"
      identifiers = ["delivery.logs.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:${local.partition}:logs:us-east-1:${local.account_id}:*"]
    }
  }
}

resource "aws_cloudwatch_log_resource_policy" "waf" {
  count           = var.waf ? 1 : 0
  provider        = aws.us_east_1
  policy_name     = "${local.name}-waf-logs"
  policy_document = data.aws_iam_policy_document.waf_logs[0].json
}

resource "aws_wafv2_web_acl_logging_configuration" "main" {
  count                   = var.waf ? 1 : 0
  provider                = aws.us_east_1
  resource_arn            = aws_wafv2_web_acl.main[0].arn
  log_destination_configs = [aws_cloudwatch_log_group.waf[0].arn]

  redacted_fields {
    uri_path {}
  }

  redacted_fields {
    query_string {}
  }

  depends_on = [aws_cloudwatch_log_resource_policy.waf]
}
