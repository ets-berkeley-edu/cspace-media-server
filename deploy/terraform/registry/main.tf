# Serena's container image repositories (D190), and for an environment on the shared root its load balancer's
# certificate (D294). Their own configuration (and state), applied first by ./serena aws deploy, so an image can be
# pushed, and the certificate validated, before the root (../personal or ../shared) starts tasks that use them.

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
  description = "true also creates the repository of the image that runs the simulated CollectionSpace and the fake ETL (../modules/simulator/devtools.tf)."
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

variable "domain_name" {
  description = "The campus name of an environment on the shared root (D293), for its ACM certificate; empty: none."
  type        = string
  default     = ""
}

# DNS-validated (D294): DevOps adds the validation record in campus DNS once, and ACM renews the certificate itself.
# ./serena aws deploy prints the record and stops before the shared root while the certificate isn't issued, so a
# deploy never waits on someone else's step (TQ4). The private key never leaves AWS.
resource "aws_acm_certificate" "app" {
  count             = var.domain_name == "" ? 0 : 1
  domain_name       = var.domain_name
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

output "certificate_arn" {
  description = "The load balancer's certificate; empty without a domain."
  value       = var.domain_name == "" ? "" : aws_acm_certificate.app[0].arn
}

output "repository_url" {
  description = "Where ./serena aws deploy pushes Serena's image."
  value       = aws_ecr_repository.app.repository_url
}

output "devtools_repository_url" {
  description = "Where ./serena aws deploy pushes the simulator's and fake ETL's image; empty without the simulator."
  value       = var.simulated_cspace ? aws_ecr_repository.devtools[0].repository_url : ""
}
