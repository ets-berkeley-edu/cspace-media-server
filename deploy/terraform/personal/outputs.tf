output "url" {
  description = "Serena's address."
  value       = "https://${module.files.domain_name}"
}

output "files_url" {
  description = "The files' address: here the same distribution as the app's."
  value       = "https://${module.files.domain_name}"
}

output "cluster_name" {
  description = "The ECS cluster; its services are web and worker (and fakecspace, with the simulator)."
  value       = module.core.cluster_name
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
  description = "Whether the environment runs the simulated CollectionSpace (../modules/simulator)."
  value       = var.simulated_cspace
}

output "simulator_url" {
  description = "The simulator's address inside the VPC; empty without it."
  value       = var.simulated_cspace ? module.simulator[0].url : ""
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
  value = module.core.buckets
}

output "secrets" {
  description = "The secrets ./serena aws sets: each museum's CollectionSpace account, ETL tokens and (where it has signed access) portal signing key."
  value       = module.core.secrets
}

output "fake_etl" {
  description = "What ./serena aws etl needs to run the fake ETL once: its task definition, subnets and security group."
  value       = var.simulated_cspace ? module.simulator[0].fake_etl : null
}

output "delivery" {
  description = "Whether the museums' files are delivered (a signing key exists, D200); false: requests get the unavailable image."
  value       = module.files.delivery
}

output "cdn_key_ids" {
  description = "The trusted CloudFront public keys, name => key ID (the secret's key_pair_id); ./serena aws cdn-key reads it."
  value       = module.files.cdn_key_ids
}

output "alert_topic_arn" {
  description = "The SNS topic for alerts and alarms (D201)."
  value       = module.core.alert_topic_arn
}

output "alert_email" {
  description = "The address subscribed to the alert topic; empty if none."
  value       = var.alert_email
}
