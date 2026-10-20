# Serena in AWS, one environment per state (D181-D194; docs/design.md, Infrastructure and operations): the app and the
# worker on ECS Fargate, CloudFront (HTTPS, the path and address rules, and WAF where it's on) in front of an internal
# load balancer, DynamoDB, an S3 bucket per museum, a KMS key and Secrets Manager; image delivery from the museums'
# buckets with signed URLs (delivery.tf), and the alert topic and alarms (alerts.tf). Applied by ./serena aws deploy;
# the images come from ../registry.
#
# Layout (D187): tasks run in public subnets with public IPs (no NAT gateway); nothing can reach them from outside,
# because their security groups take traffic only from the load balancer. The load balancer is internal (private
# subnets), reachable only through CloudFront's VPC origin (D183). S3 and DynamoDB traffic from the tasks goes
# through free gateway endpoints.

terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # Bucket, key and region come from ./serena aws (deploy/aws.sh): one state bucket per account, one key per
  # environment.
  backend "s3" {}
}

provider "aws" {
  region              = var.region
  allowed_account_ids = [var.account_id] # refuse to touch any other account, whatever credentials are in use

  default_tags {
    tags = {
      project     = "serena"
      environment = var.env_name
    }
  }
}

# A web ACL for a CloudFront distribution, and its log group, live in us-east-1 (waf.tf).
provider "aws" {
  alias               = "us_east_1"
  region              = "us-east-1"
  allowed_account_ids = [var.account_id]

  default_tags {
    tags = {
      project     = "serena"
      environment = var.env_name
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  name       = "serena-${var.env_name}"
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
  azs        = slice(data.aws_availability_zones.available.names, 0, 2)
  museums    = sort(keys(var.tenants))

  # Each museum's configuration (backend/serena/museums/<museum>.yaml): which kinds it serves with a portal's
  # signed link, so which museums get a portal signing key's secret (secrets.tf).
  museum_config  = { for m in local.museums : m => yamldecode(file("${path.module}/../../../backend/serena/museums/${m}.yaml")) }
  signed_museums = [for m in local.museums : m if length(try(local.museum_config[m].signed_access_kinds, [])) > 0]
}
