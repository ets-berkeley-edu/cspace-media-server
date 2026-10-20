output "url" {
  description = "Serena's address."
  value       = "https://${aws_cloudfront_distribution.main.domain_name}"
}

output "cluster_name" {
  description = "The ECS cluster; its services are web and worker (and fakecspace, with the simulator)."
  value       = aws_ecs_cluster.main.name
}

output "image_uri" {
  description = "The image the app and the worker run."
  value       = var.image_uri
}

output "devtools_image_uri" {
  description = "The simulator's and fake ETL's image; empty without the simulator."
  value       = var.devtools_image_uri
}

output "running" {
  description = "Whether the services run (false after ./serena aws pause)."
  value       = var.running
}

output "museums" {
  description = "The museums, as \"museum=server museum=server\" for ./serena aws, which refuses to change a deployed museum's server."
  value       = join(" ", [for m, url in var.tenants : "${m}=${url}"])
}

output "simulated_cspace" {
  description = "Whether the environment runs the simulated CollectionSpace (devtools.tf)."
  value       = var.simulated_cspace
}

output "simulator_url" {
  description = "The simulator's address inside the VPC; empty without it."
  value       = var.simulated_cspace ? local.simulator_url : ""
}

output "load_balancer_url" {
  description = "The internal load balancer's address, for the fake ETL inside the VPC."
  value       = "http://${aws_lb.main.dns_name}"
}

output "allowed_cidrs" {
  description = "Addresses allowed everything."
  value       = var.allowed_cidrs
}

output "buckets" {
  value = local.buckets
}

output "secrets" {
  description = "The secrets ./serena aws sets: each museum's CollectionSpace account, ETL tokens and (where it has signed access) portal signing key."
  value = {
    cspace     = { for m, s in aws_secretsmanager_secret.cspace : m => s.name }
    etl_tokens = { for m, s in aws_secretsmanager_secret.etl_tokens : m => s.name }
    portal_key = { for m, s in aws_secretsmanager_secret.portal_key : m => s.name }
  }
}

output "fake_etl" {
  description = "What ./serena aws etl needs to run the fake ETL once: its task definition, subnets and security group."
  value = var.simulated_cspace ? {
    task_definition = aws_ecs_task_definition.fake_etl[0].family
    subnets         = join(",", aws_subnet.public[*].id)
    security_group  = aws_security_group.devtools[0].id
  } : null
}

output "delivery" {
  description = "Whether the museums' files are delivered (a signing key exists, D200); false: requests get the unavailable image."
  value       = local.delivery
}

output "cdn_key_ids" {
  description = "The trusted CloudFront public keys, name => key ID (the secret's key_pair_id); ./serena aws cdn-key reads it."
  value       = { for name, k in aws_cloudfront_public_key.cdn : name => k.id }
}

output "alert_topic_arn" {
  description = "The SNS topic for alerts and alarms (D201)."
  value       = aws_sns_topic.alerts.arn
}

output "alert_email" {
  description = "The address subscribed to the alert topic; empty if none."
  value       = var.alert_email
}
