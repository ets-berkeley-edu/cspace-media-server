# Serena's container image repositories (D190). Their own configuration (and state), so an image can be pushed before
# the app configuration (../app) starts tasks that run it. Applied by ./serena aws deploy.

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

variable "account_id" {
  description = "The AWS account this environment belongs to; Terraform refuses to run against any other."
  type        = string

  validation {
    condition     = can(regex("^\\d{12}$", var.account_id))
    error_message = "account_id must be a 12-digit AWS account number."
  }
}

variable "region" {
  description = "AWS region."
  type        = string
}

variable "env_name" {
  description = "Environment name within the account, used in every resource name (serena-<env>-...)."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,15}$", var.env_name))
    error_message = "env_name must be 2 to 16 lowercase letters, digits or hyphens, starting with a letter."
  }
}

variable "simulated_cspace" {
  description = "true also creates the repository of the image that runs the simulated CollectionSpace and the fake ETL (../app/devtools.tf)."
  type        = bool
  default     = false
}

resource "aws_ecr_repository" "app" {
  name                 = "serena-${var.env_name}"
  image_tag_mutability = "IMMUTABLE" # every deploy pushes a new tag (commit and time)
  force_delete         = true        # ./serena aws destroy removes the images with the repository

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the 10 newest images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 10 }
      action       = { type = "expire" }
    }]
  })
}

# The local stack's image (backend/Dockerfile: the simulator and the local tools, beside Serena), for an environment
# that runs the simulated CollectionSpace. Its own repository, so Serena's production image never contains them.
resource "aws_ecr_repository" "devtools" {
  count                = var.simulated_cspace ? 1 : 0
  name                 = "serena-${var.env_name}-devtools"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "devtools" {
  count      = var.simulated_cspace ? 1 : 0
  repository = aws_ecr_repository.devtools[0].name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the 3 newest images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 3 }
      action       = { type = "expire" }
    }]
  })
}

output "repository_url" {
  description = "Where ./serena aws deploy pushes Serena's image."
  value       = aws_ecr_repository.app.repository_url
}

output "devtools_repository_url" {
  description = "Where ./serena aws deploy pushes the simulator's and fake ETL's image; empty without the simulator."
  value       = var.simulated_cspace ? aws_ecr_repository.devtools[0].repository_url : ""
}
