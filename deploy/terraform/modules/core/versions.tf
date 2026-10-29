# Serena's own resources, the same in every environment whatever its front door and network (D302): the tables, the
# museums' buckets, the KMS key, the secrets, the app's and the worker's roles, tasks and services, and the alert topic
# and alarms. The root gives it the network (subnets, security groups), the load balancer's target group, and the
# files distribution (modules/files) that delivers from the buckets.

terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

locals {
  name       = var.name
  account_id = var.account_id
  partition  = var.partition
  museums    = sort(keys(var.tenants))

  # Each museum's configuration (backend/serena/museums/<museum>.yaml): which kinds it serves with a portal's
  # signed link, so which museums get a portal signing key's secret (secrets.tf).
  museum_config  = { for m in local.museums : m => yamldecode(file("${path.module}/../../../../backend/serena/museums/${m}.yaml")) }
  signed_museums = [for m in local.museums : m if length(try(local.museum_config[m].signed_access_kinds, [])) > 0]
}
