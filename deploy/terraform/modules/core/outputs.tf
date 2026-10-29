output "cluster_id" {
  value = aws_ecs_cluster.main.id
}

output "cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "buckets" {
  description = "museum => bucket name."
  value       = local.buckets
}

output "bucket_domains" {
  description = "museum => the bucket's regional domain name, the files distribution's origin."
  value       = { for m, b in aws_s3_bucket.museum : m => b.bucket_regional_domain_name }
}

output "secrets" {
  description = "The secrets ./serena aws sets."
  value = {
    cspace     = { for m, s in aws_secretsmanager_secret.cspace : m => s.name }
    etl_tokens = { for m, s in aws_secretsmanager_secret.etl_tokens : m => s.name }
    portal_key = { for m, s in aws_secretsmanager_secret.portal_key : m => s.name }
  }
}

output "etl_token_secret_arns" {
  value = [for s in aws_secretsmanager_secret.etl_tokens : s.arn]
}

output "execution_role_arn" {
  value = aws_iam_role.execution.arn
}

output "kms_key_arn" {
  description = "Serena's key, once its policy lets CloudWatch Logs use it."
  value       = aws_kms_key.main.arn
  depends_on  = [aws_kms_key_policy.main]
}

output "app_environment" {
  description = "Serena's settings shared by the app, the worker and the fake ETL."
  value       = local.app_environment
}

output "alert_topic_arn" {
  value = aws_sns_topic.alerts.arn
}

# For deploy/terraform/<root>/tests: terraform test reads a module's resources only through its outputs.
output "test" {
  value = {
    tables               = { for t, table in aws_dynamodb_table.main : t => { name = table.name, deletion_protection = table.deletion_protection_enabled } }
    bucket_force_destroy = { for m, b in aws_s3_bucket.museum : m => b.force_destroy }
    web_desired_count    = aws_ecs_service.web.desired_count
    worker_desired_count = aws_ecs_service.worker.desired_count
    web_cpu              = aws_ecs_task_definition.web.cpu
    web_memory           = aws_ecs_task_definition.web.memory
    portal_key_museums   = keys(aws_secretsmanager_secret.portal_key)
    email_protocols      = [for s in aws_sns_topic_subscription.email : s.protocol]
    alarms_enabled = merge(
      { for k, a in aws_cloudwatch_metric_alarm.unserved : k => a.actions_enabled },
      { web-down = aws_cloudwatch_metric_alarm.web_down.actions_enabled, worker-down = aws_cloudwatch_metric_alarm.worker_down.actions_enabled },
    )
    unserved_patterns = { for k, f in aws_cloudwatch_log_metric_filter.unserved : k => f.pattern }
  }
}
