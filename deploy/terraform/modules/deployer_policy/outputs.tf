output "parts" {
  description = "Each part's length, by its number."
  value       = { for k, p in local.policy_parts : k => length(p) }
}

output "test" {
  description = "For terraform test: the managed policies, by their number."
  value       = aws_iam_policy.part
}
