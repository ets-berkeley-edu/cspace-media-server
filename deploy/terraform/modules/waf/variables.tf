variable "name" {
  description = "serena-<env_name>, the prefix of every resource's name."
  type        = string
}

variable "account_id" {
  description = "The AWS account."
  type        = string
}

variable "partition" {
  description = "The AWS partition (aws)."
  type        = string
}

variable "scope" {
  description = "CLOUDFRONT (a distribution; the provider must be in us-east-1) or REGIONAL (a load balancer)."
  type        = string

  validation {
    condition     = contains(["CLOUDFRONT", "REGIONAL"], var.scope)
    error_message = "scope must be CLOUDFRONT or REGIONAL."
  }
}

variable "rate_limit" {
  description = "Requests from one visitor in 5 minutes before WAF blocks it."
  type        = number
}

variable "apache_cidrs" {
  description = "The Apache hosts' outbound addresses, whose requests are counted by X-Forwarded-For (D306); empty: none."
  type        = list(string)
  default     = []
}

variable "log_retention_days" {
  description = "How long WAF's logs are kept."
  type        = number
}
