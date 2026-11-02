# The deploy pipeline's AWS side, for one environment (D268 to D277, DP1 to DP17): GitHub's OIDC provider (made only
# where the account has none, DP2), the two roles GitHub Actions assumes (oidc.tf), the plan and apply CodeBuild
# projects, their build role, log group and the bucket of saved plans (build.tf). Applied by the account's
# administrator with ./serena aws pipeline, never by the deployer or the build: it makes the build's own role (DP1).
# Its state is serena/<env>/pipeline.tfstate, which the build may not write. Nothing here is tagged project=serena,
# since the deployer policy may change what carries that tag, and no name starts with serena-, for the same reason.

terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # Bucket, key and region come from ./serena aws (deploy/aws.sh): the account's state bucket,
  # serena/<env>/pipeline.tfstate.
  backend "s3" {}
}

provider "aws" {
  region              = var.region
  allowed_account_ids = [var.account_id] # refuse to touch any other account, whatever credentials are in use

  default_tags {
    tags = {
      purpose     = "serena-pipeline"
      environment = var.env_name
    }
  }
}

data "aws_partition" "current" {}

locals {
  name      = "pipeline-${var.environment}"
  partition = data.aws_partition.current.partition
  # The projects' ARNs, written out (the role trusts them before they exist).
  project_arn = {
    for mode in ["plan", "apply"] :
    mode => "arn:${local.partition}:codebuild:${var.region}:${var.account_id}:project/${local.name}-${mode}"
  }
}
