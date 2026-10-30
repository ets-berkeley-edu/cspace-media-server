# The shared root (D302): Serena in QA and production, in a UC Berkeley account (the split, D289 to D301). The app is
# behind an internet-facing load balancer on a campus domain, with an ACM certificate and a regional web ACL; the
# museums' files and the unavailable images are delivered by a CloudFront distribution of their own. The tasks run in
# the VPC Operations provides (D303). Serena's own resources are in ../modules/core, the distribution in
# ../modules/files, WAF in ../modules/waf and the simulated CollectionSpace in ../modules/simulator (main.tf).
# Planned by ./serena aws; deployed by ./serena aws only while the environment uses only the simulator, otherwise by
# the pipeline (D268) or a break-glass deploy (D276, TQ8).

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

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  name       = "serena-${var.env_name}"
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
  museums    = sort(keys(var.tenants))
}
