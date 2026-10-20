# Alerts and alarms (design: Watchdog and alerts, Logs and metrics; D201 to D204).
#
# One SNS topic per environment, encrypted with Serena's key (kms.tf lets CloudWatch alarms use it). The worker emails
# the watchdog's alerts to it (SERENA_ALERT_TOPIC_ARN), and the alarms below publish to it when they fire and when they
# clear. Its one email subscription, ALERT_EMAIL, is confirmed with ./serena aws confirm-alerts, so that unsubscribing
# needs an AWS sign-in.
#
# The alarms' numbers come from the load balancer, ECS, and metric filters on the JSON lines the app already logs
# (D203); embedded metrics come later. While the environment is paused, no alarm sends anything (D204).

resource "aws_sns_topic" "alerts" {
  name              = "${local.name}-alerts"
  kms_master_key_id = aws_kms_key.main.arn
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alert_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

locals {
  metric_namespace = "Serena/${var.env_name}"

  # Unserved requests worth an alarm (D202), by the reason the app logs with "unserved" (backend/serena/unserved.py).
  unserved_alarms = {
    internal-errors = {
      reason      = "internal_error"
      metric      = "InternalErrors"
      threshold   = 5
      description = "Serena answered 5 or more requests with an internal error in 15 minutes: ./serena aws logs web."
    }
    cspace-refused = {
      reason      = "cspace_refused"
      metric      = "CollectionSpaceRefused"
      threshold   = 1
      description = "CollectionSpace refused Serena (401, 403 or an unexpected answer): most often the museum's service account's password changed. ./serena aws cspace-secret <museum>."
    }
    cspace-unavailable = {
      reason      = "cspace_unavailable"
      metric      = "CollectionSpaceUnavailable"
      threshold   = 20
      description = "CollectionSpace didn't answer, or answered 429 or 5xx, for 20 or more of Serena's fetches in 15 minutes."
    }
  }
}

resource "aws_cloudwatch_log_metric_filter" "unserved" {
  for_each       = local.unserved_alarms
  name           = "${local.name}-${each.key}"
  log_group_name = aws_cloudwatch_log_group.web.name
  pattern        = "{ $.message = \"unserved\" && $.reason = \"${each.value.reason}\" }"

  metric_transformation {
    name      = each.value.metric
    namespace = local.metric_namespace
    value     = "1"
    unit      = "Count"
  }
}

resource "aws_cloudwatch_metric_alarm" "unserved" {
  for_each            = local.unserved_alarms
  alarm_name          = "${local.name}-${each.key}"
  alarm_description   = each.value.description
  namespace           = local.metric_namespace
  metric_name         = each.value.metric
  statistic           = "Sum"
  period              = 900
  evaluation_periods  = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = each.value.threshold
  treat_missing_data  = "notBreaching"
  actions_enabled     = var.running
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]

  depends_on = [aws_cloudwatch_log_metric_filter.unserved]
}

# 1. The app is down: no healthy target behind the load balancer for 5 minutes.
resource "aws_cloudwatch_metric_alarm" "web_down" {
  alarm_name          = "${local.name}-web-down"
  alarm_description   = "No healthy Serena app task for 5 minutes: ./serena aws status and ./serena aws logs web."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HealthyHostCount"
  dimensions          = { LoadBalancer = aws_lb.main.arn_suffix, TargetGroup = aws_lb_target_group.web.arn_suffix }
  statistic           = "Minimum"
  period              = 60
  evaluation_periods  = 5
  comparison_operator = "LessThanThreshold"
  threshold           = 1
  treat_missing_data  = "breaching"
  actions_enabled     = var.running
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}

# 2. The worker isn't running: ECS reports no CPU figure for its service for 10 minutes (no Container Insights
# needed). The watchdog runs in the worker, so it can't report this itself.
resource "aws_cloudwatch_metric_alarm" "worker_down" {
  alarm_name          = "${local.name}-worker-down"
  alarm_description   = "Serena's worker hasn't run for 10 minutes, so no daily refresh is checked or applied and the watchdog is silent: ./serena aws status and ./serena aws logs worker."
  namespace           = "AWS/ECS"
  metric_name         = "CPUUtilization"
  dimensions          = { ClusterName = aws_ecs_cluster.main.name, ServiceName = aws_ecs_service.worker.name }
  statistic           = "SampleCount"
  period              = 60
  evaluation_periods  = 10
  comparison_operator = "LessThanThreshold"
  threshold           = 1
  treat_missing_data  = "breaching"
  actions_enabled     = var.running
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}

# 3. The app answers with errors.
resource "aws_cloudwatch_metric_alarm" "web_errors" {
  alarm_name          = "${local.name}-web-5xx"
  alarm_description   = "Serena's app answered 5 or more requests with a 5xx in 5 minutes: ./serena aws logs web."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_Target_5XX_Count"
  dimensions          = { LoadBalancer = aws_lb.main.arn_suffix, TargetGroup = aws_lb_target_group.web.arn_suffix }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 5
  treat_missing_data  = "notBreaching"
  actions_enabled     = var.running
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}
