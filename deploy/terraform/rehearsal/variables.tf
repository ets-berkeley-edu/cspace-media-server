variable "account_id" {
  description = "The developer's own AWS account; Terraform refuses to run against any other."
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
  description = "The rehearsal environment's SERENA_ENV_NAME, in the VPC's and the deployer's names (rehearsal-<env>-...)."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,15}$", var.env_name))
    error_message = "env_name must be 2 to 16 lowercase letters, digits or hyphens, starting with a letter."
  }
}

variable "vpc_cidr" {
  description = "The VPC's range: a /16, split into two public and two private /20 subnets."
  type        = string
  default     = "10.42.0.0/16"
}
