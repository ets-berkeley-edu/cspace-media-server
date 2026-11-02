# Read by ./serena aws pipeline: the roles' ARNs go into the GitHub environments' AWS_ROLE_ARN secrets.

output "plan_role_arn" {
  value = aws_iam_role.github["plan"].arn
}

output "apply_role_arn" {
  value = aws_iam_role.github["apply"].arn
}

output "projects" {
  value = { for k, p in aws_codebuild_project.build : k => p.name }
}

output "plans_bucket" {
  value = aws_s3_bucket.plans.bucket
}

output "oidc_provider_created" {
  description = "Whether this root made GitHub's OIDC provider (and destroying it deletes it)."
  value       = var.create_oidc_provider
}

output "build_policy_parts" {
  description = "How many managed policies the deployer policy was split into, and each one's length."
  value       = module.deployer_policy.parts
}
