# AWS WAF (D186, D292): one web ACL with Serena's rules, for a CloudFront distribution (scope CLOUDFRONT, the personal
# root, whose provider for this module is in us-east-1 as CloudFront requires) or a load balancer (scope REGIONAL,
# the shared root). Bot Control counts at first, so we see how crawlers are treated before anything is blocked (the
# catalog is crawled routinely). Logs redact the URI path and the query string (D16, D26).
#
# The rate limit (D306): where the Apache hosts on the museums' webapps hosts proxy the image paths (D290), most
# requests arrive from their few addresses, so requests from those addresses are counted by the visitor's address in
# X-Forwarded-For, and every other request by its own source address. Without apache_cidrs, one rule counts every
# request by its source address.

data "aws_region" "current" {}

locals {
  apache = length(var.apache_cidrs) > 0
}

resource "aws_wafv2_ip_set" "apache" {
  count              = local.apache ? 1 : 0
  name               = "${var.name}-apache"
  description        = "The Apache hosts that proxy the legacy image paths to Serena (D290)"
  scope              = var.scope
  ip_address_version = "IPV4"
  addresses          = var.apache_cidrs
}

resource "aws_wafv2_web_acl" "main" {
  name  = var.name
  scope = var.scope

  default_action {
    allow {}
  }

  # Without the Apache hosts: every request by its source address.
  dynamic "rule" {
    for_each = local.apache ? [] : [1]

    content {
      name     = "rate-limit-per-address"
      priority = 0

      action {
        block {}
      }

      statement {
        rate_based_statement {
          limit              = var.rate_limit
          aggregate_key_type = "IP"
        }
      }

      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = "${var.name}-rate"
        sampled_requests_enabled   = true
      }
    }
  }

  # With them (D306): their requests by the visitor's address in X-Forwarded-For (a request without one isn't counted
  # here; it is still checked by the rules below) ...
  dynamic "rule" {
    for_each = local.apache ? [1] : []

    content {
      name     = "rate-limit-per-visitor-through-apache"
      priority = 0

      action {
        block {}
      }

      statement {
        rate_based_statement {
          limit              = var.rate_limit
          aggregate_key_type = "FORWARDED_IP"

          forwarded_ip_config {
            header_name       = "X-Forwarded-For"
            fallback_behavior = "NO_MATCH"
          }

          scope_down_statement {
            ip_set_reference_statement {
              arn = aws_wafv2_ip_set.apache[0].arn
            }
          }
        }
      }

      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = "${var.name}-rate-apache"
        sampled_requests_enabled   = true
      }
    }
  }

  # ... and everything else by its source address.
  dynamic "rule" {
    for_each = local.apache ? [1] : []

    content {
      name     = "rate-limit-per-address"
      priority = 5

      action {
        block {}
      }

      statement {
        rate_based_statement {
          limit              = var.rate_limit
          aggregate_key_type = "IP"

          scope_down_statement {
            not_statement {
              statement {
                ip_set_reference_statement {
                  arn = aws_wafv2_ip_set.apache[0].arn
                }
              }
            }
          }
        }
      }

      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = "${var.name}-rate"
        sampled_requests_enabled   = true
      }
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
      metric_name                = "${var.name}-ip-reputation"
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
      metric_name                = "${var.name}-core"
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
      metric_name                = "${var.name}-bad-inputs"
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
      metric_name                = "${var.name}-bots"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = var.name
    sampled_requests_enabled   = true
  }
}

# WAF's log group's name must start with aws-waf-logs-.
resource "aws_cloudwatch_log_group" "waf" {
  name              = "aws-waf-logs-${var.name}"
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "waf_logs" {

  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.waf.arn}:*"]

    principals {
      type        = "Service"
      identifiers = ["delivery.logs.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:${var.partition}:logs:${data.aws_region.current.region}:${var.account_id}:*"]
    }
  }
}

resource "aws_cloudwatch_log_resource_policy" "waf" {
  policy_name     = "${var.name}-waf-logs"
  policy_document = data.aws_iam_policy_document.waf_logs.json
}

resource "aws_wafv2_web_acl_logging_configuration" "main" {
  resource_arn            = aws_wafv2_web_acl.main.arn
  log_destination_configs = [aws_cloudwatch_log_group.waf.arn]

  redacted_fields {
    uri_path {}
  }

  redacted_fields {
    query_string {}
  }

  depends_on = [aws_cloudwatch_log_resource_policy.waf]
}
