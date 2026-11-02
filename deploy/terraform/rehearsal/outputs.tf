# Read by ./serena aws rehearsal-vpc, which saves the first four in the environment's .local.conf.

output "vpc_id" {
  value = aws_vpc.main.id
}

output "app_subnet_ids" {
  description = "The private subnets, for APP_SUBNET_IDS."
  value       = join(",", aws_subnet.private[*].id)
}

output "lb_subnet_ids" {
  description = "The public subnets, for LB_SUBNET_IDS."
  value       = join(",", aws_subnet.public[*].id)
}

output "nat_address" {
  description = "The NAT gateway's outbound address: the fake ETL's calls come from it (ETL_CIDRS)."
  value       = aws_eip.nat.public_ip
}

output "deployer_role_arn" {
  value = aws_iam_role.deployer.arn
}

output "deployer_policy_parts" {
  description = "How many managed policies the deployer policy was split into, and each one's length."
  value       = module.deployer_policy.parts
}
