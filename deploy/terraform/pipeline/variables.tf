variable "account_id" {
  description = "The environment's AWS account; Terraform refuses to run against any other."
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

variable "environment" {
  description = "The ./serena aws environment (personal-stage2, ucb-stage2): the GitHub environments' names (<environment>-plan and <environment>) and the pipeline's (pipeline-<environment>-...)."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,19}$", var.environment))
    error_message = "environment must be 2 to 20 lowercase letters, digits or hyphens, starting with a letter."
  }
}

variable "env_name" {
  description = "The environment's SERENA_ENV_NAME: its settings in SSM (/serena-<env_name>/settings/) and its Terraform state (serena/<env_name>/)."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,15}$", var.env_name))
    error_message = "env_name must be 2 to 16 lowercase letters, digits or hyphens, starting with a letter."
  }
}

variable "repository" {
  description = "The GitHub repository whose deploy workflow may start the builds, and which the builds check out (public: no credentials)."
  type        = string
  default     = "ets-berkeley-edu/cspace-media-server"
}

variable "github_subject" {
  description = "The start of the sub claim in GitHub's OIDC tokens for the repository, before :environment:<name>: repo:<owner>/<name>, or repo:<owner>@<id>/<name>@<id> with immutable subjects. ./serena aws pipeline reads it from GitHub."
  type        = string

  validation {
    condition     = can(regex("^repo:[^:*?]+$", var.github_subject))
    error_message = "github_subject must be repo: and the repository, as GitHub names it, with no colon or wildcard."
  }
}

variable "create_oidc_provider" {
  description = "true makes GitHub's OIDC provider; false uses the account's own (there can be only one, DP2). ./serena aws pipeline decides."
  type        = bool
}

variable "codebuild_image" {
  description = "The CodeBuild image, by its versioned name (DP17): Amazon Linux 2023 on ARM, with Docker, Python 3 and the AWS CLI."
  type        = string
  default     = "aws/codebuild/amazonlinux-aarch64-standard:3.0"
}
