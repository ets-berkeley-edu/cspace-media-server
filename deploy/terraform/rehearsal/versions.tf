# The stage 2 rehearsal (personal accounts only): what Ops provides for stage 2, made in a developer's own account so
# that the shared root can be deployed there first, under the stage 2 deployer policy alone (checklist section 54). A VPC
# like Ops's (network.tf) and a deployer role with only ../../iam/serena-deployer-policy.json (deployer.tf). Applied
# by ./serena aws rehearsal-vpc with the account's administrator profile, never by the deployer it makes; the shared
# root stays as it is (D303). Nothing here is tagged project=serena, as Ops's VPC can't carry Serena's tag.

terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # Bucket, key and region come from ./serena aws (deploy/aws.sh): the account's state bucket, serena/<env>/rehearsal.tfstate.
  backend "s3" {}
}

provider "aws" {
  region              = var.region
  allowed_account_ids = [var.account_id] # refuse to touch any other account, whatever credentials are in use

  default_tags {
    tags = {
      purpose     = "serena-stage2-rehearsal"
      environment = var.env_name
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  name = "rehearsal-${var.env_name}"
}
